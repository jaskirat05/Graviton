#!/usr/bin/env python3
"""
ComfyUI Resource Registry - POC Script

This script demonstrates the implementation for:
1. Discovering models, LoRAs, checkpoints, VAEs from ComfyUI servers
2. Maintaining a registry of resources per server
3. Downloading workflow templates from ComfyUI's templates directory

ComfyUI API Endpoints used:
- GET /object_info - Node definitions with model/LoRA dropdowns
- GET /models/{folder_type} - List available models (newer API)
- GET /embeddings - List embeddings
- Custom file system discovery via SSH/SFTP for templates
"""

import asyncio
import aiohttp
import json
import hashlib
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, Dict, List, Any, Set
from urllib.parse import urljoin
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================================
# Enums and Data Models
# ============================================================================

class ResourceType(str, Enum):
    # Core model types
    CHECKPOINT = "checkpoint"
    LORA = "lora"
    VAE = "vae"
    EMBEDDING = "embedding"
    CONTROLNET = "controlnet"
    CLIP = "clip"
    UPSCALER = "upscaler"
    HYPERNETWORK = "hypernetwork"
    # Extended model types
    DIFFUSION_MODEL = "diffusion_model"
    TEXT_ENCODER = "text_encoder"
    UNET = "unet"
    TTS = "tts"
    AUDIO = "audio"
    DETECTION = "detection"
    FACE_RESTORE = "face_restore"
    SAM = "sam"
    IPADAPTER = "ipadapter"
    INSTANTID = "instantid"
    LLM = "llm"
    # Generic for unknown folders
    OTHER = "other"
    WORKFLOW_TEMPLATE = "workflow_template"


class SyncStatus(str, Enum):
    PENDING = "pending"
    SYNCED = "synced"
    FAILED = "failed"
    OUTDATED = "outdated"


@dataclass
class ComfyUIResource:
    """Represents a model/LoRA/checkpoint resource on a ComfyUI server."""
    name: str
    resource_type: ResourceType
    server_name: str
    relative_path: str  # Path relative to ComfyUI models folder
    file_size: Optional[int] = None
    file_hash: Optional[str] = None  # SHA256 for deduplication
    last_seen: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def unique_id(self) -> str:
        """Generate unique ID for this resource."""
        return f"{self.server_name}:{self.resource_type.value}:{self.relative_path}"

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d['resource_type'] = self.resource_type.value
        d['last_seen'] = self.last_seen.isoformat()
        d['unique_id'] = self.unique_id
        return d


@dataclass
class WorkflowTemplate:
    """Represents a ComfyUI workflow template."""
    name: str
    filename: str
    server_name: str
    template_path: str  # Path on the server
    content_hash: str
    workflow_json: Dict[str, Any]
    discovered_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d['discovered_at'] = self.discovered_at.isoformat()
        return d


@dataclass
class ServerResourceInventory:
    """Complete resource inventory for a ComfyUI server."""
    server_name: str
    server_url: str
    last_sync: Optional[datetime] = None
    sync_status: SyncStatus = SyncStatus.PENDING
    resources: Dict[str, ComfyUIResource] = field(default_factory=dict)
    workflow_templates: Dict[str, WorkflowTemplate] = field(default_factory=dict)
    available_nodes: Set[str] = field(default_factory=set)  # Node class_types from /object_info
    error_message: Optional[str] = None

    def add_resource(self, resource: ComfyUIResource):
        self.resources[resource.unique_id] = resource

    def add_template(self, template: WorkflowTemplate):
        self.workflow_templates[template.content_hash] = template

    def get_resources_by_type(self, resource_type: ResourceType) -> List[ComfyUIResource]:
        return [r for r in self.resources.values() if r.resource_type == resource_type]

    def to_dict(self) -> Dict[str, Any]:
        return {
            'server_name': self.server_name,
            'server_url': self.server_url,
            'last_sync': self.last_sync.isoformat() if self.last_sync else None,
            'sync_status': self.sync_status.value,
            'resources': {k: v.to_dict() for k, v in self.resources.items()},
            'workflow_templates': {k: v.to_dict() for k, v in self.workflow_templates.items()},
            'error_message': self.error_message,
            'available_nodes': list(self.available_nodes),
            'stats': {
                'total_resources': len(self.resources),
                'checkpoints': len(self.get_resources_by_type(ResourceType.CHECKPOINT)),
                'loras': len(self.get_resources_by_type(ResourceType.LORA)),
                'vaes': len(self.get_resources_by_type(ResourceType.VAE)),
                'embeddings': len(self.get_resources_by_type(ResourceType.EMBEDDING)),
                'controlnets': len(self.get_resources_by_type(ResourceType.CONTROLNET)),
                'workflow_templates': len(self.workflow_templates),
                'available_nodes': len(self.available_nodes),
            }
        }


# ============================================================================
# ComfyUI Resource Discovery Client
# ============================================================================

class ComfyUIResourceClient:
    """Client for discovering resources from a ComfyUI server."""

    # Mapping of ComfyUI folder types to ResourceType for known types
    # Other folders will be discovered dynamically from /models endpoint
    FOLDER_TYPE_MAP = {
        'checkpoints': ResourceType.CHECKPOINT,
        'loras': ResourceType.LORA,
        'vae': ResourceType.VAE,
        'embeddings': ResourceType.EMBEDDING,
        'controlnet': ResourceType.CONTROLNET,
        'clip': ResourceType.CLIP,
        'clip_vision': ResourceType.CLIP,
        'upscale_models': ResourceType.UPSCALER,
        'hypernetworks': ResourceType.HYPERNETWORK,
    }

    # Folders to skip (not actual models)
    SKIP_FOLDERS = {
        'custom_nodes',  # Contains node code, not models
        'configs',       # YAML configs, not models
        'VHS_video_formats',  # Video format configs
        'kjnodes_fonts',  # Fonts
    }

    # Node types that expose model selection
    MODEL_NODE_TYPES = {
        'CheckpointLoaderSimple': ('ckpt_name', ResourceType.CHECKPOINT),
        'CheckpointLoader': ('ckpt_name', ResourceType.CHECKPOINT),
        'LoraLoader': ('lora_name', ResourceType.LORA),
        'LoraLoaderModelOnly': ('lora_name', ResourceType.LORA),
        'VAELoader': ('vae_name', ResourceType.VAE),
        'ControlNetLoader': ('control_net_name', ResourceType.CONTROLNET),
        'CLIPLoader': ('clip_name', ResourceType.CLIP),
        'UpscaleModelLoader': ('model_name', ResourceType.UPSCALER),
    }

    def __init__(self, server_name: str, server_url: str, timeout: int = 30):
        self.server_name = server_name
        self.server_url = server_url.rstrip('/')
        self.timeout = aiohttp.ClientTimeout(total=timeout)

    async def discover_all(self) -> ServerResourceInventory:
        """Discover all resources from the server."""
        inventory = ServerResourceInventory(
            server_name=self.server_name,
            server_url=self.server_url
        )

        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                # Discover available nodes from /object_info
                await self._discover_available_nodes(session, inventory)

                # Method 1: Try the newer /models endpoint (ComfyUI >= 0.3.x)
                models_discovered = await self._discover_via_models_endpoint(session, inventory)

                # Method 2: Fall back to /object_info for model discovery
                if not models_discovered:
                    await self._discover_via_object_info(session, inventory)

                # Discover embeddings
                await self._discover_embeddings(session, inventory)

                # Discover workflow templates
                await self._discover_workflow_templates(session, inventory)

                inventory.last_sync = datetime.utcnow()
                inventory.sync_status = SyncStatus.SYNCED

        except Exception as e:
            logger.error(f"Failed to discover resources from {self.server_name}: {e}")
            inventory.sync_status = SyncStatus.FAILED
            inventory.error_message = str(e)

        return inventory

    async def _discover_available_nodes(
        self,
        session: aiohttp.ClientSession,
        inventory: ServerResourceInventory
    ):
        """Discover all available node types from /object_info."""
        try:
            url = urljoin(self.server_url, "/object_info")
            async with session.get(url) as response:
                if response.status == 200:
                    object_info = await response.json()
                    inventory.available_nodes = set(object_info.keys())
                    logger.info(f"Discovered {len(inventory.available_nodes)} available nodes")
        except Exception as e:
            logger.warning(f"Failed to discover nodes: {e}")

    async def _discover_via_models_endpoint(
        self,
        session: aiohttp.ClientSession,
        inventory: ServerResourceInventory
    ) -> bool:
        """
        Try to discover models using the newer /models/{folder_type} endpoint.
        Returns True if successful, False if endpoint doesn't exist.
        """
        discovered = False

        for folder_type, resource_type in self.FOLDER_TYPE_MAP.items():
            try:
                url = urljoin(self.server_url, f"/models/{folder_type}")
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        models = data if isinstance(data, list) else data.get('models', [])

                        for model_path in models:
                            resource = ComfyUIResource(
                                name=Path(model_path).stem,
                                resource_type=resource_type,
                                server_name=self.server_name,
                                relative_path=model_path,
                            )
                            inventory.add_resource(resource)
                            discovered = True

                        logger.info(f"Discovered {len(models)} {folder_type} via /models endpoint")
                    elif response.status == 404:
                        # Endpoint doesn't exist, fall back to object_info
                        pass

            except aiohttp.ClientError:
                continue

        return discovered

    async def _discover_via_object_info(
        self,
        session: aiohttp.ClientSession,
        inventory: ServerResourceInventory
    ):
        """
        Discover models by parsing /object_info response.
        This extracts available models from node input definitions.
        """
        try:
            url = urljoin(self.server_url, "/object_info")
            async with session.get(url) as response:
                if response.status != 200:
                    logger.warning(f"Failed to get object_info: {response.status}")
                    return

                object_info = await response.json()

                for node_type, config in self.MODEL_NODE_TYPES.items():
                    input_name, resource_type = config

                    if node_type not in object_info:
                        continue

                    node_info = object_info[node_type]
                    inputs = node_info.get('input', {})
                    required = inputs.get('required', {})

                    if input_name not in required:
                        continue

                    input_def = required[input_name]
                    if not isinstance(input_def, list) or not input_def:
                        continue

                    # First element is the list of available options
                    options = input_def[0]
                    if not isinstance(options, list):
                        continue

                    for model_path in options:
                        resource = ComfyUIResource(
                            name=Path(model_path).stem,
                            resource_type=resource_type,
                            server_name=self.server_name,
                            relative_path=model_path,
                        )
                        inventory.add_resource(resource)

                    logger.info(f"Discovered {len(options)} {resource_type.value} via object_info")

        except Exception as e:
            logger.error(f"Failed to parse object_info: {e}")

    async def _discover_embeddings(
        self,
        session: aiohttp.ClientSession,
        inventory: ServerResourceInventory
    ):
        """Discover available embeddings."""
        try:
            url = urljoin(self.server_url, "/embeddings")
            async with session.get(url) as response:
                if response.status == 200:
                    embeddings = await response.json()

                    for embedding_name in embeddings:
                        resource = ComfyUIResource(
                            name=embedding_name,
                            resource_type=ResourceType.EMBEDDING,
                            server_name=self.server_name,
                            relative_path=f"embeddings/{embedding_name}",
                        )
                        inventory.add_resource(resource)

                    logger.info(f"Discovered {len(embeddings)} embeddings")

        except Exception as e:
            logger.error(f"Failed to discover embeddings: {e}")

    async def _discover_workflow_templates(
        self,
        session: aiohttp.ClientSession,
        inventory: ServerResourceInventory
    ):
        """
        Discover workflow templates from ComfyUI server using /view endpoint.
        Downloads .json files from the templates subfolder.
        """
        # Use /view endpoint with subfolder=templates to list/download templates
        try:
            # First try to get directory listing
            url = urljoin(self.server_url, "/view")
            params = {
                "subfolder": "templates",
                "type": "input"
            }

            async with session.get(url, params=params) as response:
                if response.status == 200:
                    content_type = response.headers.get('content-type', '')

                    if 'application/json' in content_type:
                        # Got a directory listing
                        data = await response.json()
                        files = data if isinstance(data, list) else data.get('files', [])
                        json_files = [f for f in files if str(f).endswith('.json')]

                        for filename in json_files:
                            await self._download_template_file(session, inventory, filename)

                        logger.info(f"Discovered {len(json_files)} workflow templates")

        except aiohttp.ClientError as e:
            logger.warning(f"Failed to discover templates: {e}")

    async def _download_template_file(
        self,
        session: aiohttp.ClientSession,
        inventory: ServerResourceInventory,
        filename: str
    ):
        """Download a single template .json file using /view endpoint."""
        try:
            url = urljoin(self.server_url, "/view")
            params = {
                "filename": filename,
                "subfolder": "templates",
                "type": "input"
            }

            async with session.get(url, params=params) as response:
                if response.status == 200:
                    content = await response.read()

                    try:
                        workflow_json = json.loads(content)
                        content_hash = hashlib.sha256(content).hexdigest()[:16]

                        template = WorkflowTemplate(
                            name=Path(filename).stem,
                            filename=filename,
                            server_name=self.server_name,
                            template_path=f"templates/{filename}",
                            content_hash=content_hash,
                            workflow_json=workflow_json,
                        )
                        inventory.add_template(template)

                    except json.JSONDecodeError:
                        logger.warning(f"Failed to parse {filename} as JSON")

        except Exception as e:
            logger.warning(f"Failed to download template {filename}: {e}")


# ============================================================================
# SSH-based Template Discovery (for direct file access)
# ============================================================================

class SSHTemplateDiscovery:
    """
    Discover workflow templates via SSH/SFTP from ComfyUI server.

    This is useful when:
    1. ComfyUI doesn't expose template APIs
    2. You want to access custom_nodes workflows
    3. Direct file system access is available
    """

    TEMPLATE_LOCATIONS = [
        "user/default/workflows",
        "web/scripts/templates",
        "custom_nodes/*/workflows",
        "custom_nodes/*/example_workflows",
    ]

    def __init__(
        self,
        server_name: str,
        ssh_host: str,
        ssh_user: str,
        comfyui_path: str,
        ssh_key_path: Optional[str] = None,
        ssh_password: Optional[str] = None,
    ):
        self.server_name = server_name
        self.ssh_host = ssh_host
        self.ssh_user = ssh_user
        self.comfyui_path = comfyui_path
        self.ssh_key_path = ssh_key_path
        self.ssh_password = ssh_password

    async def discover_templates(self) -> List[WorkflowTemplate]:
        """
        Discover templates via SSH.

        Note: This requires asyncssh or paramiko.
        For the POC, we'll show the implementation structure.
        """
        templates = []

        try:
            # Example using asyncssh (would need to be installed)
            # import asyncssh
            #
            # async with asyncssh.connect(
            #     self.ssh_host,
            #     username=self.ssh_user,
            #     client_keys=[self.ssh_key_path] if self.ssh_key_path else None,
            #     password=self.ssh_password,
            # ) as conn:
            #     async with conn.start_sftp_client() as sftp:
            #         for location in self.TEMPLATE_LOCATIONS:
            #             full_path = f"{self.comfyui_path}/{location}"
            #
            #             # Handle glob patterns
            #             if '*' in location:
            #                 # List parent directory and filter
            #                 parent = str(Path(full_path).parent)
            #                 pattern = Path(full_path).name
            #
            #                 try:
            #                     dirs = await sftp.readdir(parent)
            #                     for d in dirs:
            #                         if d.filename.startswith('.'):
            #                             continue
            #                         subpath = f"{parent}/{d.filename}/{pattern.split('/')[-1]}"
            #                         templates.extend(
            #                             await self._scan_directory(sftp, subpath)
            #                         )
            #                 except:
            #                     continue
            #             else:
            #                 templates.extend(
            #                     await self._scan_directory(sftp, full_path)
            #                 )

            logger.info("SSH template discovery would scan: %s", self.TEMPLATE_LOCATIONS)
            logger.info("Implement with asyncssh or paramiko for production use")

        except Exception as e:
            logger.error(f"SSH template discovery failed: {e}")

        return templates


# ============================================================================
# Resource Registry (In-Memory + Persistence)
# ============================================================================

class ComfyUIResourceRegistry:
    """
    Central registry for all ComfyUI server resources.

    Features:
    - Multi-server resource tracking
    - Deduplication by file hash
    - Sync status tracking
    - Persistence to JSON/SQLite
    """

    def __init__(self, storage_path: Optional[Path] = None):
        self.storage_path = storage_path
        self.servers: Dict[str, ServerResourceInventory] = {}
        self._lock = asyncio.Lock()

        if storage_path and storage_path.exists():
            self._load_from_disk()

    async def register_server(
        self,
        server_name: str,
        server_url: str,
        auto_sync: bool = True
    ) -> ServerResourceInventory:
        """Register a new server and optionally sync its resources."""
        async with self._lock:
            if server_name in self.servers:
                inventory = self.servers[server_name]
                # Update URL if changed
                inventory.server_url = server_url
            else:
                inventory = ServerResourceInventory(
                    server_name=server_name,
                    server_url=server_url
                )
                self.servers[server_name] = inventory

        if auto_sync:
            await self.sync_server(server_name)

        return self.servers[server_name]

    async def sync_server(self, server_name: str) -> ServerResourceInventory:
        """Sync resources from a specific server."""
        if server_name not in self.servers:
            raise ValueError(f"Server {server_name} not registered")

        inventory = self.servers[server_name]
        client = ComfyUIResourceClient(
            server_name=server_name,
            server_url=inventory.server_url
        )

        new_inventory = await client.discover_all()

        async with self._lock:
            self.servers[server_name] = new_inventory
            self._save_to_disk()

        return new_inventory

    async def sync_all_servers(self) -> Dict[str, ServerResourceInventory]:
        """Sync resources from all registered servers."""
        tasks = [
            self.sync_server(name)
            for name in self.servers.keys()
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        return {
            name: result if not isinstance(result, Exception) else self.servers[name]
            for name, result in zip(self.servers.keys(), results)
        }

    def get_all_resources(
        self,
        resource_type: Optional[ResourceType] = None
    ) -> List[ComfyUIResource]:
        """Get all resources across all servers, optionally filtered by type."""
        resources = []
        for inventory in self.servers.values():
            if resource_type:
                resources.extend(inventory.get_resources_by_type(resource_type))
            else:
                resources.extend(inventory.resources.values())
        return resources

    def get_unique_resources(
        self,
        resource_type: Optional[ResourceType] = None
    ) -> Dict[str, List[ComfyUIResource]]:
        """
        Get unique resources by name, grouped with their locations.
        Useful for finding models available across multiple servers.
        """
        unique: Dict[str, List[ComfyUIResource]] = {}

        for resource in self.get_all_resources(resource_type):
            key = f"{resource.resource_type.value}:{resource.relative_path}"
            if key not in unique:
                unique[key] = []
            unique[key].append(resource)

        return unique

    def find_missing_resources(
        self,
        server_name: str,
        required_resources: List[str]
    ) -> List[str]:
        """
        Find resources required by a workflow that are missing on a server.

        Args:
            server_name: Server to check
            required_resources: List of resource paths (e.g., "v1-5-pruned.ckpt")

        Returns:
            List of missing resource paths
        """
        if server_name not in self.servers:
            return required_resources

        inventory = self.servers[server_name]
        available = {r.relative_path for r in inventory.resources.values()}

        return [r for r in required_resources if r not in available]

    def get_servers_with_resource(
        self,
        resource_path: str
    ) -> List[str]:
        """Find all servers that have a specific resource."""
        servers = []
        for name, inventory in self.servers.items():
            for resource in inventory.resources.values():
                if resource.relative_path == resource_path:
                    servers.append(name)
                    break
        return servers

    def to_dict(self) -> Dict[str, Any]:
        """Export registry to dictionary."""
        return {
            'servers': {
                name: inv.to_dict()
                for name, inv in self.servers.items()
            },
            'summary': {
                'total_servers': len(self.servers),
                'total_resources': sum(
                    len(inv.resources) for inv in self.servers.values()
                ),
                'total_templates': sum(
                    len(inv.workflow_templates) for inv in self.servers.values()
                ),
            }
        }

    def _save_to_disk(self):
        """Persist registry to disk."""
        if not self.storage_path:
            return

        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.storage_path, 'w') as f:
                json.dump(self.to_dict(), f, indent=2, default=str)
            logger.info(f"Saved registry to {self.storage_path}")
        except Exception as e:
            logger.error(f"Failed to save registry: {e}")

    def _load_from_disk(self):
        """Load registry from disk."""
        try:
            with open(self.storage_path, 'r') as f:
                data = json.load(f)

            for name, inv_data in data.get('servers', {}).items():
                # Reconstruct ServerResourceInventory
                inventory = ServerResourceInventory(
                    server_name=name,
                    server_url=inv_data['server_url'],
                    sync_status=SyncStatus(inv_data.get('sync_status', 'pending')),
                )

                if inv_data.get('last_sync'):
                    inventory.last_sync = datetime.fromisoformat(inv_data['last_sync'])

                # Reconstruct resources
                for uid, res_data in inv_data.get('resources', {}).items():
                    resource = ComfyUIResource(
                        name=res_data['name'],
                        resource_type=ResourceType(res_data['resource_type']),
                        server_name=res_data['server_name'],
                        relative_path=res_data['relative_path'],
                        file_size=res_data.get('file_size'),
                        file_hash=res_data.get('file_hash'),
                        metadata=res_data.get('metadata', {}),
                    )
                    inventory.add_resource(resource)

                self.servers[name] = inventory

            logger.info(f"Loaded registry from {self.storage_path}")

        except Exception as e:
            logger.error(f"Failed to load registry: {e}")


# ============================================================================
# Workflow Dependency Analyzer
# ============================================================================

class WorkflowDependencyAnalyzer:
    """
    Analyze ComfyUI workflows to extract resource dependencies and validate.

    This mimics how ComfyUI frontend validates workflows:
    1. Check if all node class_types exist via /object_info
    2. Check if all models/loras/checkpoints exist via /models/{folder}
    """

    # Node class to input field mapping for resource extraction
    RESOURCE_INPUTS = {
        'CheckpointLoaderSimple': {'ckpt_name': ResourceType.CHECKPOINT},
        'CheckpointLoader': {'ckpt_name': ResourceType.CHECKPOINT},
        'LoraLoader': {'lora_name': ResourceType.LORA},
        'LoraLoaderModelOnly': {'lora_name': ResourceType.LORA},
        'VAELoader': {'vae_name': ResourceType.VAE},
        'ControlNetLoader': {'control_net_name': ResourceType.CONTROLNET},
        'CLIPLoader': {'clip_name': ResourceType.CLIP},
        'UpscaleModelLoader': {'model_name': ResourceType.UPSCALER},
    }

    def get_workflow_nodes(self, workflow: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """
        Normalize workflow to dict of nodes, handling both API and export formats.
        """
        # Handle both API format {"1": {...}} and export format {"nodes": [...]}
        if isinstance(workflow, dict) and 'nodes' in workflow:
            # Export format - convert to dict keyed by id
            return {str(n['id']): n for n in workflow['nodes']}
        return workflow

    def extract_node_types(self, workflow: Dict[str, Any]) -> Set[str]:
        """
        Extract all node class_types from a workflow.
        """
        nodes = self.get_workflow_nodes(workflow)
        node_types = set()

        for node_id, node_data in nodes.items():
            if not isinstance(node_data, dict):
                continue
            class_type = node_data.get('class_type') or node_data.get('type', '')
            if class_type:
                node_types.add(class_type)

        return node_types

    def analyze(self, workflow: Dict[str, Any]) -> Dict[ResourceType, Set[str]]:
        """
        Extract all resource dependencies from a workflow.

        Args:
            workflow: ComfyUI workflow JSON

        Returns:
            Dict mapping resource types to sets of required resource paths
        """
        dependencies: Dict[ResourceType, Set[str]] = {
            rt: set() for rt in ResourceType
        }

        nodes = self.get_workflow_nodes(workflow)

        for node_id, node_data in nodes.items():
            if not isinstance(node_data, dict):
                continue

            class_type = node_data.get('class_type', '')
            inputs = node_data.get('inputs', {})

            # Also check widgets_values for export format
            widget_values = node_data.get('widgets_values', [])

            if class_type in self.RESOURCE_INPUTS:
                for input_name, resource_type in self.RESOURCE_INPUTS[class_type].items():
                    value = inputs.get(input_name)

                    # Skip if it's a link reference [node_id, output_index]
                    if isinstance(value, list):
                        continue

                    if value and isinstance(value, str):
                        dependencies[resource_type].add(value)

        # Remove empty sets
        return {k: v for k, v in dependencies.items() if v}

    def validate_workflow_on_server(
        self,
        workflow: Dict[str, Any],
        registry: 'ComfyUIResourceRegistry',
        server_name: str
    ) -> Dict[str, Any]:
        """
        Validate that a workflow can run on a specific server.

        Checks:
        1. All node types exist on the server
        2. All models/loras/checkpoints are available

        Returns:
            Dict with validation results
        """
        if server_name not in registry.servers:
            return {
                'valid': False,
                'server': server_name,
                'error': f'Server {server_name} not found in registry',
            }

        inventory = registry.servers[server_name]

        # Check for missing nodes
        required_nodes = self.extract_node_types(workflow)
        missing_nodes = required_nodes - inventory.available_nodes

        # Check for missing resources
        dependencies = self.analyze(workflow)
        missing_resources = {}

        for resource_type, resources in dependencies.items():
            for resource_path in resources:
                missing = registry.find_missing_resources(server_name, [resource_path])
                if missing:
                    if resource_type.value not in missing_resources:
                        missing_resources[resource_type.value] = []
                    missing_resources[resource_type.value].append(resource_path)

        is_valid = len(missing_nodes) == 0 and len(missing_resources) == 0

        return {
            'valid': is_valid,
            'server': server_name,
            'required_nodes': list(required_nodes),
            'missing_nodes': list(missing_nodes),
            'required_resources': {k.value: list(v) for k, v in dependencies.items()},
            'missing_resources': missing_resources,
        }


# ============================================================================
# SQLAlchemy Models (for integration with existing database)
# ============================================================================

def get_sqlalchemy_models():
    """
    Returns SQLAlchemy model definitions for integration with existing database.
    These can be added to core/database/models.py
    """
    return '''
# Add these imports at the top of core/database/models.py
from sqlalchemy import Enum as SQLEnum

# Add this enum definition
class ResourceTypeEnum(enum.Enum):
    CHECKPOINT = "checkpoint"
    LORA = "lora"
    VAE = "vae"
    EMBEDDING = "embedding"
    CONTROLNET = "controlnet"
    CLIP = "clip"
    UPSCALER = "upscaler"
    HYPERNETWORK = "hypernetwork"

class SyncStatusEnum(enum.Enum):
    PENDING = "pending"
    SYNCED = "synced"
    FAILED = "failed"
    OUTDATED = "outdated"


class ComfyServer(Base):
    """Registry of ComfyUI servers."""
    __tablename__ = "comfy_servers"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, unique=True, nullable=False, index=True)
    url = Column(String, nullable=False)
    ssh_host = Column(String, nullable=True)  # For SSH-based discovery
    ssh_user = Column(String, nullable=True)
    ssh_key_path = Column(String, nullable=True)
    comfyui_path = Column(String, nullable=True)  # Path on server

    last_sync = Column(DateTime, nullable=True)
    sync_status = Column(String, default="pending")
    error_message = Column(Text, nullable=True)

    # GPU/hardware info from health check
    gpu_memory_total = Column(Float, nullable=True)
    gpu_name = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    resources = relationship("ServerResource", back_populates="server", cascade="all, delete-orphan")
    workflow_templates = relationship("ServerWorkflowTemplate", back_populates="server", cascade="all, delete-orphan")


class ServerResource(Base):
    """Model/LoRA/Checkpoint resource on a ComfyUI server."""
    __tablename__ = "server_resources"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    server_id = Column(String, ForeignKey("comfy_servers.id", ondelete="CASCADE"), nullable=False)

    name = Column(String, nullable=False, index=True)
    resource_type = Column(String, nullable=False, index=True)  # checkpoint, lora, vae, etc.
    relative_path = Column(String, nullable=False)  # Path relative to models folder

    file_size = Column(BigInteger, nullable=True)
    file_hash = Column(String(64), nullable=True, index=True)  # SHA256 for dedup

    last_seen = Column(DateTime, default=datetime.utcnow)
    metadata = Column(JSON, default=dict)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    server = relationship("ComfyServer", back_populates="resources")

    # Unique constraint: one resource path per server
    __table_args__ = (
        Index("ix_server_resource_unique", "server_id", "resource_type", "relative_path", unique=True),
    )


class ServerWorkflowTemplate(Base):
    """Workflow template discovered from a ComfyUI server."""
    __tablename__ = "server_workflow_templates"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    server_id = Column(String, ForeignKey("comfy_servers.id", ondelete="CASCADE"), nullable=False)

    name = Column(String, nullable=False, index=True)
    filename = Column(String, nullable=False)
    template_path = Column(String, nullable=False)  # Path on server
    content_hash = Column(String(16), nullable=False, index=True)

    workflow_json = Column(JSON, nullable=False)
    metadata = Column(JSON, default=dict)

    discovered_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    server = relationship("ComfyServer", back_populates="workflow_templates")

    __table_args__ = (
        Index("ix_server_template_unique", "server_id", "content_hash", unique=True),
    )
'''


# ============================================================================
# Demo / Test
# ============================================================================

async def demo():
    """Demonstrate the registry functionality."""
    print("=" * 60)
    print("ComfyUI Resource Registry - POC Demo")
    print("=" * 60)

    # Create registry with persistence
    registry = ComfyUIResourceRegistry(
        storage_path=Path("./data/comfyui_registry.json")
    )

    # Register servers from config
    # In production, load from config.yaml
    demo_servers = [
        ("local-comfy", "http://localhost:8188"),
        # ("remote-comfy", "http://192.168.1.100:8188"),
    ]

    for name, url in demo_servers:
        print(f"\nRegistering server: {name} ({url})")
        try:
            inventory = await registry.register_server(name, url, auto_sync=True)
            print(f"  Status: {inventory.sync_status.value}")

            if inventory.sync_status == SyncStatus.SYNCED:
                stats = inventory.to_dict()['stats']
                print(f"  Checkpoints: {stats['checkpoints']}")
                print(f"  LoRAs: {stats['loras']}")
                print(f"  VAEs: {stats['vaes']}")
                print(f"  Embeddings: {stats['embeddings']}")
                print(f"  Templates: {stats['workflow_templates']}")
            else:
                print(f"  Error: {inventory.error_message}")

        except Exception as e:
            print(f"  Failed: {e}")

    # Show unique resources across servers
    print("\n" + "=" * 60)
    print("Unique Checkpoints Across All Servers:")
    print("=" * 60)

    unique = registry.get_unique_resources(ResourceType.CHECKPOINT)
    for key, resources in list(unique.items())[:10]:  # Limit to first 10
        servers = [r.server_name for r in resources]
        print(f"  {resources[0].name}: {', '.join(servers)}")

    # Test workflow dependency analysis
    print("\n" + "=" * 60)
    print("Workflow Dependency Analysis:")
    print("=" * 60)

    sample_workflow = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "v1-5-pruned.safetensors"}
        },
        "2": {
            "class_type": "LoraLoader",
            "inputs": {
                "lora_name": "detail_enhancer.safetensors",
                "strength_model": 0.8,
                "strength_clip": 0.8
            }
        }
    }

    analyzer = WorkflowDependencyAnalyzer()
    deps = analyzer.analyze(sample_workflow)

    print("Dependencies found:")
    for resource_type, paths in deps.items():
        for path in paths:
            print(f"  [{resource_type.value}] {path}")

    # Export registry
    print("\n" + "=" * 60)
    print("Registry Summary:")
    print("=" * 60)

    summary = registry.to_dict()['summary']
    print(f"  Total Servers: {summary['total_servers']}")
    print(f"  Total Resources: {summary['total_resources']}")
    print(f"  Total Templates: {summary['total_templates']}")

    return registry


if __name__ == "__main__":
    asyncio.run(demo())
