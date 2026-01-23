"""
Workflow Discovery System with Hash-Based Override Files

Key Features:
1. Auto-generates override files with all mutable parameters
2. Users can edit override files to freeze specific parameters
3. Hash validation ensures sync between workflow and override file
4. Auto-regenerates overrides when workflow changes

File Structure:
    workflows/
    ├── my_workflow.json              # Workflow definition
    └── my_workflow_overrides.json    # Mutable parameters (editable by user)

Usage:
    registry = WorkflowRegistry()
    registry.discover_workflows()  # Generates override files if needed

    # Execute with overrides
    workflow = registry.apply_overrides(
        "my_workflow",
        {"93.text": "A dragon flying"}
    )
"""

import json
import hashlib
import logging
import shutil
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field, asdict
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class WorkflowParameter:
    """Represents an overridable parameter"""
    key: str                    # Full key: "node_id.input_key"
    node_id: str               # ComfyUI node ID
    input_key: str             # Input key in the node
    default_value: Any         # Default value from workflow
    type: str                  # Python type name (str, int, float, bool)
    node_class: str            # ComfyUI node class
    node_title: str            # Human-readable node title
    description: str = ""      # User-editable description
    category: str = "other"    # Parameter category (prompts, dimensions, etc)


@dataclass
class WorkflowOutput:
    """Represents the output of a workflow"""
    node_id: str               # Node ID that produces output
    output_type: str           # "video" or "image"
    node_class: str            # ComfyUI node class (SaveVideo, SaveImage, etc)
    node_title: str            # Human-readable title
    format: str = "auto"       # Output format
    filename_prefix: str = ""  # Filename prefix/pattern


@dataclass
class SocketDefinition:
    """Socket definition for node connections"""
    id: str
    type: str  # "image", "video", "any"
    label: str


@dataclass
class UIMetadata:
    """UI metadata for frontend node editor"""
    nodeType: str
    label: str
    icon: str
    color: str
    category: str  # "image", "video", "utility"
    # inputSockets are derived from parameters with input_key "image" or "video"
    outputSockets: List[SocketDefinition] = field(default_factory=list)


@dataclass
class WorkflowInfo:
    """Information about a discovered workflow"""
    name: str
    parameters: List[WorkflowParameter] = field(default_factory=list)
    output: Optional[WorkflowOutput] = None
    description: str = ""
    ui_metadata: Optional[UIMetadata] = None


@dataclass
class OverrideFile:
    """Structure of the override JSON file"""
    workflow_hash: str
    generated_at: str
    workflow_name: str
    description: str
    parameters: List[Dict[str, Any]]


class WorkflowRegistry:
    """
    Manages ComfyUI workflows with hash-based override files

    Workflow Discovery Process:
    1. Find workflow.json
    2. Check if workflow_overrides.json exists
    3. If exists: validate hash, load if valid, regenerate if invalid
    4. If not exists: generate new override file
    """

    OVERRIDE_SUFFIX = "_overrides.json"
    BACKUP_SUFFIX = ".bak"

    def __init__(self, workflows_dir: Optional[Path] = None):
        """
        Initialize registry

        Args:
            workflows_dir: Path to workflows directory
        """
        if workflows_dir is None:
            workflows_dir = Path(__file__).parent.parent / "templates"

        self.workflows_dir = Path(workflows_dir)
        self.workflows: Dict[str, WorkflowInfo] = {}
        self.workflow_hashes: Dict[str, str] = {}

        logger.info(f"WorkflowRegistry initialized: {self.workflows_dir}")

    def discover_workflows(self) -> Dict[str, Any]:
        """
        Discover all workflows and generate/load override files

        Returns:
            Summary of discovery process
        """
        if not self.workflows_dir.exists():
            logger.warning(f"Workflows directory not found: {self.workflows_dir}")
            return {"error": "Workflows directory not found"}

        summary = {
            "discovered": 0,
            "generated": 0,
            "loaded": 0,
            "regenerated": 0,
            "errors": []
        }

        for workflow_file in self.workflows_dir.glob("*.json"):
            # Skip override files
            if self.OVERRIDE_SUFFIX in workflow_file.name:
                continue

            try:
                result = self._process_workflow(workflow_file)
                summary["discovered"] += 1
                summary[result] += 1

            except Exception as e:
                error_msg = f"Failed to process {workflow_file.name}: {e}"
                logger.error(error_msg)
                summary["errors"].append(error_msg)

        logger.info(
            f"Discovery complete: {summary['discovered']} workflows, "
            f"{summary['generated']} generated, "
            f"{summary['loaded']} loaded, "
            f"{summary['regenerated']} regenerated"
        )

        return summary

    def _find_terminal_nodes(self, workflow_data: Dict) -> set:
        """
        Find terminal nodes (nodes not referenced by any other node)

        Args:
            workflow_data: Parsed workflow JSON

        Returns:
            Set of node IDs that are terminal
        """
        all_nodes = set(workflow_data.keys())
        referenced_nodes = set()

        # Find all referenced nodes
        for node in workflow_data.values():
            for value in node.get("inputs", {}).values():
                if isinstance(value, list) and len(value) > 0:
                    # This is a node reference
                    referenced_nodes.add(str(value[0]))

        # Terminal nodes = not referenced by anyone
        terminal = all_nodes - referenced_nodes
        return terminal

    def _detect_output(self, workflow_data: Dict) -> Optional[WorkflowOutput]:
        """
        Detect the output node of a workflow

        Rules:
        1. Must be SaveVideo or SaveImage node
        2. Must be a terminal node (not referenced by others)
        3. There should be exactly ONE such node

        Args:
            workflow_data: Parsed workflow JSON

        Returns:
            WorkflowOutput if found, None otherwise

        Raises:
            ValueError: If multiple output nodes found
        """
        # Known output node types
        OUTPUT_NODE_TYPES = {
            "SaveVideo": "video",
            "SaveImage": "image",
            "PreviewImage": "image",
            "VHS_VideoCombine": "video",  # VideoHelperSuite
            "SaveAnimatedWEBP": "image"
        }

        # Find terminal nodes
        terminal_nodes = self._find_terminal_nodes(workflow_data)

        # Find output nodes (SaveVideo/SaveImage that are terminal)
        output_nodes = []

        for node_id in terminal_nodes:
            node = workflow_data.get(node_id)
            if not node:
                continue

            node_class = node.get("class_type", "")

            if node_class in OUTPUT_NODE_TYPES:
                output_type = OUTPUT_NODE_TYPES[node_class]
                node_title = node.get("_meta", {}).get("title", node_class)
                inputs = node.get("inputs", {})

                output_nodes.append(WorkflowOutput(
                    node_id=node_id,
                    output_type=output_type,
                    node_class=node_class,
                    node_title=node_title,
                    format=inputs.get("format", "auto"),
                    filename_prefix=inputs.get("filename_prefix", "")
                ))

        # Validation
        if len(output_nodes) == 0:
            logger.warning("No output node found (no terminal SaveVideo/SaveImage)")
            return None

        if len(output_nodes) > 1:
            node_ids = [o.node_id for o in output_nodes]
            raise ValueError(
                f"Multiple output nodes found: {node_ids}. "
                f"Workflows should have exactly ONE output. "
                f"Please split this into separate workflows."
            )

        return output_nodes[0]

    def _process_workflow(self, workflow_file: Path) -> str:
        """
        Process a single workflow file

        Returns:
            "generated" | "loaded" | "regenerated"
        """
        workflow_name = workflow_file.stem
        override_file = self._get_override_path(workflow_file)

        # Load workflow JSON
        with open(workflow_file, 'r', encoding='utf-8') as f:
            workflow_data = json.load(f)

        # Extract and strip UI metadata (not sent to ComfyUI)
        ui_metadata_raw = workflow_data.pop("_ui_metadata", None)
        ui_metadata = self._parse_ui_metadata(ui_metadata_raw) if ui_metadata_raw else None

        # If _ui_metadata was present, write cleaned workflow back to disk
        # This ensures workflow files stay ComfyUI-compatible
        if ui_metadata_raw is not None:
            with open(workflow_file, 'w', encoding='utf-8') as f:
                json.dump(workflow_data, f, indent=2, ensure_ascii=False)
            logger.info(f"  Stripped _ui_metadata from {workflow_file.name}")

        # Calculate current hash (without _ui_metadata)
        current_hash = self._calculate_hash(workflow_data)
        self.workflow_hashes[workflow_name] = current_hash

        # Check if override file exists
        if override_file.exists():
            # Load and validate
            with open(override_file, 'r', encoding='utf-8') as f:
                override_data = json.load(f)

            stored_hash = override_data.get("workflow_hash", "")

            if stored_hash == current_hash:
                # Hash matches - load parameters
                logger.info(f"✓ {workflow_name}: Loading from override file")

                # If we stripped ui_metadata from workflow file, always update override file
                # (workflow file is source of truth for UI metadata)
                if ui_metadata_raw is not None:
                    override_data["ui_metadata"] = {
                        "nodeType": ui_metadata.nodeType,
                        "label": ui_metadata.label,
                        "icon": ui_metadata.icon,
                        "color": ui_metadata.color,
                        "category": ui_metadata.category,
                        "outputSockets": [asdict(s) for s in ui_metadata.outputSockets],
                    }
                    with open(override_file, 'w', encoding='utf-8') as f:
                        json.dump(override_data, f, indent=2, ensure_ascii=False)
                    logger.info(f"  Migrated ui_metadata to {override_file.name}")
                elif "ui_metadata" in override_data:
                    # Load ui_metadata from override file (already migrated)
                    ui_metadata = self._parse_ui_metadata(override_data["ui_metadata"])

                self._load_from_override(workflow_name, workflow_data, override_data, ui_metadata)
                return "loaded"
            else:
                # Hash mismatch - regenerate
                logger.warning(
                    f"⚠️ {workflow_name}: Workflow changed! "
                    f"Regenerating overrides..."
                )
                self._backup_override_file(override_file)
                self._generate_override_file(
                    workflow_name,
                    workflow_data,
                    current_hash,
                    override_file,
                    ui_metadata,
                )
                return "regenerated"
        else:
            # No override file - generate new one
            logger.info(f"→ {workflow_name}: Generating override file")
            self._generate_override_file(
                workflow_name,
                workflow_data,
                current_hash,
                override_file,
                ui_metadata,
            )
            return "generated"

    def _calculate_hash(self, workflow_data: Dict) -> str:
        """
        Calculate SHA256 hash of workflow JSON

        Args:
            workflow_data: Parsed workflow JSON

        Returns:
            Hash string with prefix (e.g., "sha256:abc123...")
        """
        # Create canonical JSON (sorted keys for determinism)
        canonical = json.dumps(workflow_data, sort_keys=True, ensure_ascii=False)

        # Calculate hash
        hash_obj = hashlib.sha256(canonical.encode('utf-8'))
        hash_hex = hash_obj.hexdigest()

        return f"sha256:{hash_hex}"

    def _get_override_path(self, workflow_file: Path) -> Path:
        """Get path to override file for a workflow"""
        return workflow_file.parent / f"{workflow_file.stem}{self.OVERRIDE_SUFFIX}"

    def _backup_override_file(self, override_file: Path) -> None:
        """Backup existing override file before regenerating"""
        backup_path = override_file.with_suffix(
            override_file.suffix + self.BACKUP_SUFFIX
        )
        shutil.copy2(override_file, backup_path)
        logger.info(f"  Backed up old overrides to: {backup_path.name}")

    def _parse_ui_metadata(self, ui_data: Dict) -> UIMetadata:
        """Parse raw UI metadata dict into UIMetadata dataclass"""
        output_sockets = [
            SocketDefinition(**s) for s in ui_data.get("outputSockets", [])
        ]
        return UIMetadata(
            nodeType=ui_data.get("nodeType", "unknown"),
            label=ui_data.get("label", "Unknown"),
            icon=ui_data.get("icon", "⚙️"),
            color=ui_data.get("color", "#666666"),
            category=ui_data.get("category", "utility"),
            outputSockets=output_sockets,
        )

    def _generate_override_file(
        self,
        workflow_name: str,
        workflow_data: Dict,
        workflow_hash: str,
        override_file: Path,
        ui_metadata: Optional[UIMetadata] = None,
    ) -> None:
        """
        Generate override file with all mutable parameters

        Args:
            workflow_name: Name of the workflow
            workflow_data: Parsed workflow JSON
            workflow_hash: Calculated hash
            override_file: Path to write override file
            ui_metadata: UI metadata for frontend (optional)
        """
        # Extract all mutable parameters
        parameters = self._extract_parameters(workflow_data)

        # Detect workflow output
        output = self._detect_output(workflow_data)

        # Store in registry
        self.workflows[workflow_name] = WorkflowInfo(
            name=workflow_name,
            parameters=parameters,
            output=output,
            description=f"Workflow with {len(parameters)} parameters",
            ui_metadata=ui_metadata,
        )

        # Create override file data
        override_data = {
            "workflow_hash": workflow_hash,
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "workflow_name": workflow_name,
            "description": (
                "Auto-generated parameter overrides. "
                "You can edit descriptions, remove parameters to make them immutable, "
                "or add custom categories."
            ),
            "parameters": [
                {
                    "key": p.key,
                    "node_id": p.node_id,
                    "input_key": p.input_key,
                    "default_value": p.default_value,
                    "type": p.type,
                    "node_class": p.node_class,
                    "node_title": p.node_title,
                    "description": p.description,
                    "category": p.category
                }
                for p in parameters
            ]
        }

        # Add UI metadata if present
        if ui_metadata:
            override_data["ui_metadata"] = {
                "nodeType": ui_metadata.nodeType,
                "label": ui_metadata.label,
                "icon": ui_metadata.icon,
                "color": ui_metadata.color,
                "category": ui_metadata.category,
                "outputSockets": [asdict(s) for s in ui_metadata.outputSockets],
            }

        # Write to file (pretty-printed for human editing)
        with open(override_file, 'w', encoding='utf-8') as f:
            json.dump(override_data, f, indent=2, ensure_ascii=False)

        logger.info(
            f"  Generated: {override_file.name} "
            f"({len(parameters)} parameters)"
        )

    def _load_from_override(
        self,
        workflow_name: str,
        workflow_data: Dict,
        override_data: Dict,
        ui_metadata: Optional[UIMetadata] = None,
    ) -> None:
        """
        Load parameters from existing override file

        Args:
            workflow_name: Name of the workflow
            workflow_data: Parsed workflow JSON (for output detection)
            override_data: Parsed override JSON
            ui_metadata: UI metadata from workflow file (always use this, not from override)
        """
        parameters = [
            WorkflowParameter(**param_data)
            for param_data in override_data.get("parameters", [])
        ]

        # Detect workflow output
        output = self._detect_output(workflow_data)

        # Store in registry (ui_metadata comes from workflow file, not override)
        self.workflows[workflow_name] = WorkflowInfo(
            name=workflow_name,
            parameters=parameters,
            output=output,
            description=override_data.get("description", ""),
            ui_metadata=ui_metadata,
        )

        logger.info(f"  Loaded {len(parameters)} parameters from override file")

    def _extract_parameters(self, workflow_data: Dict) -> List[WorkflowParameter]:
        """
        Extract all mutable parameters from workflow

        Key insight: Non-list values in inputs are overridable!

        Args:
            workflow_data: Parsed workflow JSON

        Returns:
            List of WorkflowParameter objects
        """
        parameters = []

        for node_id, node in workflow_data.items():
            inputs = node.get("inputs", {})
            node_class = node.get("class_type", "Unknown")
            node_title = node.get("_meta", {}).get("title", node_class)

            for input_key, value in inputs.items():
                # Skip node connections (they're lists)
                if isinstance(value, list):
                    continue

                # This is a mutable parameter!
                category = self._categorize_parameter(
                    input_key, value, node_class
                )
                description = self._generate_description(
                    input_key, node_class, node_title
                )

                parameters.append(WorkflowParameter(
                    key=f"{node_id}.{input_key}",
                    node_id=node_id,
                    input_key=input_key,
                    default_value=value,
                    type=type(value).__name__,
                    node_class=node_class,
                    node_title=node_title,
                    description=description,
                    category=category
                ))

        return parameters

    def _categorize_parameter(
        self,
        input_key: str,
        value: Any,
        node_class: str
    ) -> str:
        """Auto-categorize parameter for better organization"""
        key_lower = input_key.lower()

        if "text" in key_lower or "prompt" in key_lower:
            return "prompts"
        elif key_lower in ["width", "height", "length", "batch_size"]:
            return "dimensions"
        elif "seed" in key_lower:
            return "generation"
        elif key_lower in ["steps", "cfg", "denoise", "sampler_name", "scheduler"]:
            return "sampling"
        elif key_lower in ["fps", "frame", "duration"]:
            return "video"
        elif "image" in key_lower or "video" in key_lower:
            return "media"
        elif "model" in key_lower or "lora" in key_lower or "vae" in key_lower:
            return "models"
        else:
            return "other"

    def _generate_description(
        self,
        input_key: str,
        node_class: str,
        node_title: str
    ) -> str:
        """Generate helpful description for parameter"""
        if "text" in input_key.lower():
            if "negative" in node_title.lower():
                return "Negative prompt (what to avoid)"
            elif "positive" in node_title.lower():
                return "Positive prompt (what to generate)"
            else:
                return f"Text input for {node_title}"
        elif input_key == "width":
            return "Output width in pixels"
        elif input_key == "height":
            return "Output height in pixels"
        elif "seed" in input_key.lower():
            return "Random seed for reproducibility"
        elif input_key == "steps":
            return "Number of sampling steps"
        elif input_key == "cfg":
            return "Classifier-free guidance scale"
        elif input_key == "fps":
            return "Frames per second for video output"
        else:
            return f"{input_key} parameter for {node_class}"

    def list_workflows(self) -> List[Dict[str, Any]]:
        """List all discovered workflows"""
        return [
            {
                "name": info.name,
                "description": info.description,
                "parameters": len(info.parameters),
                "output_type": info.output.output_type if info.output else "unknown",
                "hash": self.workflow_hashes.get(info.name, "unknown"),
                "categories": list(set(p.category for p in info.parameters))
            }
            for name, info in self.workflows.items()
        ]

    def get_workflow_parameters(
        self,
        workflow_name: str
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Get parameters for a workflow

        Args:
            workflow_name: Name of the workflow

        Returns:
            List of parameters with metadata, or None if not found
        """
        info = self.workflows.get(workflow_name)
        if not info:
            return None

        return [asdict(p) for p in info.parameters]

    def get_workflow_info(self, workflow_name: str) -> Optional[Dict[str, Any]]:
        """
        Get full workflow information including output

        Args:
            workflow_name: Name of the workflow

        Returns:
            Dict with workflow info including parameters and output, or None if not found
        """
        info = self.workflows.get(workflow_name)
        if not info:
            return None

        return {
            "name": info.name,
            "description": info.description,
            "parameters": [asdict(p) for p in info.parameters],
            "output": asdict(info.output) if info.output else None
        }

    def apply_overrides(
        self,
        workflow_name: str,
        overrides: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Apply parameter overrides to a workflow

        Args:
            workflow_name: Name of the workflow
            overrides: Dict of parameter overrides (key -> value)

        Returns:
            Modified workflow JSON ready for execution

        Raises:
            ValueError: If workflow not found or parameter not overridable
        """
        if workflow_name not in self.workflows:
            raise ValueError(f"Workflow '{workflow_name}' not found")

        # Load original workflow
        workflow_file = self.workflows_dir / f"{workflow_name}.json"
        with open(workflow_file, 'r', encoding='utf-8') as f:
            workflow_data = json.load(f)

        # Get allowed parameters
        workflow_info = self.workflows[workflow_name]
        allowed_params = {p.key: p for p in workflow_info.parameters}

        # Apply each override
        for key, value in overrides.items():
            if key not in allowed_params:
                raise ValueError(
                    f"Parameter '{key}' is not overridable in workflow '{workflow_name}'. "
                    f"Available parameters: {list(allowed_params.keys())}"
                )

            param = allowed_params[key]

            # Apply to workflow data
            workflow_data[param.node_id]["inputs"][param.input_key] = value
            logger.info(f"Applied override: {key} = {value}")

        return workflow_data

    def reload(self) -> Dict[str, Any]:
        """Reload all workflows from disk"""
        self.workflows.clear()
        self.workflow_hashes.clear()
        return self.discover_workflows()


# Global registry singleton
_registry: Optional[WorkflowRegistry] = None


def get_registry() -> WorkflowRegistry:
    """Get or create global workflow registry"""
    global _registry
    if _registry is None:
        _registry = WorkflowRegistry()
        _registry.discover_workflows()
    return _registry
