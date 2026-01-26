"""
ComfyUI Server Resource Registry

Provides:
- Node and model validation using /object_info (contains available values directly)
- Template syncing from /models/templates with hash-based deduplication
- Embeds UI metadata in workflow files for WorkflowRegistry to process
"""

import asyncio
import hashlib
import json
import logging
import os
import random
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set, Any, Optional

from core.clients.comfy.http import ComfyHTTPClient
from core.config import get_servers

logger = logging.getLogger(__name__)

# Local templates directory (env: TEMPLATES_DIR, default: ./templates relative to cwd)
TEMPLATES_DIR = Path(os.environ.get("TEMPLATES_DIR", "templates"))

# Color palette for random UI assignment
UI_COLORS = [
    '#6366f1',  # Indigo
    '#8b5cf6',  # Violet
    '#ec4899',  # Pink
    '#f43f5e',  # Rose
    '#f97316',  # Orange
    '#eab308',  # Yellow
    '#22c55e',  # Green
    '#14b8a6',  # Teal
    '#0ea5e9',  # Sky
]


def compute_workflow_hash(workflow: Dict[str, Any]) -> str:
    """Compute SHA256 hash of workflow content.

    IMPORTANT: Must match WorkflowRegistry._calculate_hash() serialization format.
    """
    # Use same format as WorkflowRegistry: sort_keys=True, ensure_ascii=False, default separators
    content = json.dumps(workflow, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(content.encode('utf-8')).hexdigest()


@dataclass
class ComfyServerInventory:
    """Resource inventory for a ComfyUI server."""
    server_name: str
    server_url: str

    # Full object_info - contains nodes and their available input values
    object_info: Dict[str, Any] = field(default_factory=dict)

    # Available node class_types (keys of object_info)
    available_nodes: Set[str] = field(default_factory=set)

    # Templates available on this server
    templates: List[str] = field(default_factory=list)

    # Sync metadata
    last_sync: Optional[datetime] = None
    sync_error: Optional[str] = None

    def has_node(self, class_type: str) -> bool:
        return class_type in self.available_nodes

    def get_combo_options(self, class_type: str, input_name: str) -> Optional[List[str]]:
        """Get available options for a combo input directly from object_info."""
        node_info = self.object_info.get(class_type)
        if not node_info:
            return None

        input_types = node_info.get('input', {})

        for category in ['required', 'optional']:
            inputs = input_types.get(category, {})
            if input_name in inputs:
                input_def = inputs[input_name]
                if isinstance(input_def, list) and len(input_def) > 0:
                    options = input_def[0]
                    if isinstance(options, list):
                        return options
        return None

    def validate_combo_value(self, class_type: str, input_name: str, value: str) -> bool:
        """Check if a value is valid for a combo input."""
        options = self.get_combo_options(class_type, input_name)
        if options is None:
            return True  # Not a combo input, assume valid
        return value in options


class ComfyServerRegistry:
    """
    Registry for ComfyUI server resources.

    - Uses object_info for validation (contains available models directly)
    - Syncs templates with hash-based deduplication
    - Embeds UI metadata in workflow files (WorkflowRegistry creates override files)
    """

    _instance: Optional["ComfyServerRegistry"] = None

    def __init__(self):
        self.servers: Dict[str, ComfyServerInventory] = {}
        self._lock = asyncio.Lock()

        # Hash -> filename mapping for local templates (read from override files)
        self.local_template_hashes: Dict[str, str] = {}

        # Load existing template hashes from override files on init
        self._load_local_template_hashes()

    @classmethod
    def get_instance(cls) -> "ComfyServerRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls):
        cls._instance = None

    def _load_local_template_hashes(self):
        """Scan override files and build hash map from workflow_hash field."""
        self.local_template_hashes.clear()

        if not TEMPLATES_DIR.exists():
            TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
            return

        # Read hashes from override files (which are created by WorkflowRegistry)
        for file_path in TEMPLATES_DIR.glob("*_overrides.json"):
            try:
                with open(file_path, 'r') as f:
                    override_data = json.load(f)

                workflow_hash = override_data.get('workflow_hash', '')
                if workflow_hash:
                    # Remove prefix if present (sha256:xxx -> xxx)
                    if workflow_hash.startswith('sha256:'):
                        workflow_hash = workflow_hash[7:]
                    workflow_name = file_path.stem.replace('_overrides', '')
                    self.local_template_hashes[workflow_hash] = f"{workflow_name}.json"

            except Exception as e:
                logger.warning(f"Failed to read override {file_path}: {e}")

        logger.info(f"Loaded {len(self.local_template_hashes)} template hashes from override files")

    async def sync_all_servers(self) -> Dict[str, ComfyServerInventory]:
        """Sync resources from all servers in config.yaml."""
        servers_config = get_servers()

        for server_config in servers_config:
            name = server_config.get("name")
            address = server_config.get("address")
            port = server_config.get("port")

            if not name or not address:
                continue

            if address.startswith(("http://", "https://")):
                url = address
            elif port:
                url = f"http://{address}:{port}"
            else:
                url = f"http://{address}"

            try:
                await self.sync_server(name, url)
            except Exception as e:
                logger.error(f"Failed to sync server {name}: {e}")
                self.servers[name] = ComfyServerInventory(
                    server_name=name,
                    server_url=url,
                    sync_error=str(e)
                )

        return self.servers

    async def sync_server(self, server_name: str, server_url: str) -> ComfyServerInventory:
        """Sync all resources from a server."""
        inventory = ComfyServerInventory(
            server_name=server_name,
            server_url=server_url
        )

        client = ComfyHTTPClient(server_url)

        try:
            # 1. Fetch object_info (contains nodes + available input values)
            try:
                object_info = await client.get_object_info()
                inventory.object_info = object_info
                inventory.available_nodes = set(object_info.keys())
                logger.info(f"{server_name}: {len(inventory.available_nodes)} nodes")
            except Exception as e:
                logger.warning(f"{server_name}: Failed to get object_info: {e}")

            # 2. Fetch and sync templates
            try:
                templates = await client.get_models_by_category("templates")
                inventory.templates = templates

                # Download new templates
                await self._sync_templates(client, server_name, templates)

            except Exception as e:
                logger.warning(f"{server_name}: Failed to sync templates: {e}")

            inventory.last_sync = datetime.utcnow()

            async with self._lock:
                self.servers[server_name] = inventory

        except Exception as e:
            logger.error(f"Failed to sync {server_name}: {e}")
            inventory.sync_error = str(e)
            self.servers[server_name] = inventory
            raise
        finally:
            await client.close()

        return inventory

    async def _sync_templates(
        self,
        client: ComfyHTTPClient,
        server_name: str,
        template_names: List[str]
    ):
        """Download templates that don't exist locally (by hash)."""
        new_count = 0

        for template_name in template_names:
            if not template_name.endswith('.json'):
                continue

            try:
                # Download template content
                content_bytes = await client.download_file(
                    filename=template_name,
                    subfolder="",
                    folder_type="templates"
                )

                workflow = json.loads(content_bytes.decode('utf-8'))
                content_hash = compute_workflow_hash(workflow)

                # Check if we already have this workflow (hash in override file)
                if content_hash in self.local_template_hashes:
                    logger.debug(f"Template {template_name} already exists (hash match)")
                    continue

                # Save new template with embedded UI metadata
                await self._save_template(server_name, template_name, workflow, content_hash)
                new_count += 1

            except Exception as e:
                logger.warning(f"Failed to sync template {template_name}: {e}")

        if new_count > 0:
            logger.info(f"{server_name}: Downloaded {new_count} new templates")

    async def _save_template(
        self,
        server_name: str,
        template_name: str,
        workflow: Dict[str, Any],
        content_hash: str
    ):
        """Save template with embedded UI metadata (no override file - WorkflowRegistry handles that)."""
        name = Path(template_name).stem
        output_type = self._detect_output_type(workflow)

        # Embed UI metadata directly in workflow (WorkflowRegistry will extract and migrate)
        workflow['_ui_metadata'] = {
            'nodeType': f"workflow_{name}",
            'label': name.replace('_', ' ').title(),
            'icon': 'video' if output_type == 'video' else 'image',
            'color': random.choice(UI_COLORS),
            'category': output_type,
            'outputSockets': [{'id': 'output', 'type': output_type, 'label': output_type.title()}],
            'sourceServer': server_name,
        }

        # Add source metadata
        workflow['_comfy_automate'] = {
            'source_server': server_name,
            'downloaded_at': datetime.utcnow().isoformat(),
            'content_hash': content_hash,
        }

        # Determine local filename
        local_name = template_name
        local_path = TEMPLATES_DIR / local_name

        # Handle name collision (different content, same name)
        counter = 1
        while local_path.exists():
            stem = Path(template_name).stem
            local_name = f"{stem}_{counter}.json"
            local_path = TEMPLATES_DIR / local_name
            counter += 1

        # Save workflow only (WorkflowRegistry will create override file with parameters)
        TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
        with open(local_path, 'w') as f:
            json.dump(workflow, f, indent=2)

        # Track hash in memory for this session
        self.local_template_hashes[content_hash] = local_name

        logger.info(f"Saved template: {local_name}")

    def _detect_output_type(self, workflow: Dict[str, Any]) -> str:
        """Detect workflow output type: video, audio, 3d, or image."""
        video_nodes = {'VHS_VideoCombine', 'SaveVideo', 'VideoSave', 'SaveAnimatedWEBP'}
        audio_nodes = {'SaveAudio', 'AudioSave', 'VHS_AudioCombine'}
        mesh_nodes = {'Save3DModel', 'SaveMesh', 'ExportGLTF', 'ExportOBJ', 'SavePLY'}

        nodes = workflow
        if 'nodes' in workflow:
            nodes = {str(n.get('id', i)): n for i, n in enumerate(workflow['nodes'])}

        for node_data in nodes.values():
            if isinstance(node_data, dict):
                class_type = node_data.get('class_type', '')
                class_lower = class_type.lower()

                if class_type in video_nodes or 'video' in class_lower:
                    return 'video'
                if class_type in audio_nodes or 'audio' in class_lower:
                    return 'audio'
                if class_type in mesh_nodes or 'mesh' in class_lower or '3d' in class_lower or 'gltf' in class_lower:
                    return '3d'

        return 'image'

    def validate_prompt(
        self,
        prompt: Dict[str, Any],
        server_name: str
    ) -> Dict[str, Any]:
        """
        Validate a prompt against a server's resources.

        Uses object_info directly - combo options contain available values.
        """
        if server_name not in self.servers:
            return {
                'valid': False,
                'error': f"Server {server_name} not in registry",
                'missing_nodes': [],
                'invalid_inputs': []
            }

        inventory = self.servers[server_name]

        if inventory.sync_error:
            return {
                'valid': False,
                'error': f"Server sync failed: {inventory.sync_error}",
                'missing_nodes': [],
                'invalid_inputs': []
            }

        missing_nodes = []
        invalid_inputs = []

        for node_id, node_data in prompt.items():
            if not isinstance(node_data, dict):
                continue

            class_type = node_data.get('class_type')
            if not class_type:
                continue

            # Check node exists
            if not inventory.has_node(class_type):
                missing_nodes.append(class_type)
                continue

            # Check input values against combo options
            inputs = node_data.get('inputs', {})
            for input_name, value in inputs.items():
                # Skip linked inputs
                if isinstance(value, list):
                    continue

                # Skip non-string values
                if not isinstance(value, str):
                    continue

                # Validate against combo options
                if not inventory.validate_combo_value(class_type, input_name, value):
                    options = inventory.get_combo_options(class_type, input_name)
                    invalid_inputs.append({
                        'node_id': node_id,
                        'class_type': class_type,
                        'input_name': input_name,
                        'value': value,
                        'available_count': len(options) if options else 0
                    })

        is_valid = len(missing_nodes) == 0 and len(invalid_inputs) == 0

        return {
            'valid': is_valid,
            'missing_nodes': list(set(missing_nodes)),
            'invalid_inputs': invalid_inputs
        }

    def get_server(self, server_name: str) -> Optional[ComfyServerInventory]:
        return self.servers.get(server_name)

    def get_all_servers(self) -> Dict[str, ComfyServerInventory]:
        return self.servers
