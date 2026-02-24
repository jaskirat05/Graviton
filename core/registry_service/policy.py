"""Platform policy checks for template workflows."""

from __future__ import annotations

from typing import Any, Dict, List


GRAVITON_SAVE_NODE_TYPES = {
    "GravitonSaveImage": "image",
    "GravitonSaveVideo": "video",
    "GravitonSaveText": "text",
    "GravitonSaveFile": "file",
    "GravitonSaveAudio": "audio",
    "GravitonSave3D": "3d",
}


def check_template_policy(template_name: str, workflow: Dict[str, Any]) -> Dict[str, Any]:
    """Return policy validation result for a template workflow."""
    # Strict policy: detect exactly ONE Graviton proprietary save node.
    prompt = {k: v for k, v in workflow.items() if not str(k).startswith("_")}

    output_nodes: List[str] = []
    output_types: List[str] = []
    for node_id, node in prompt.items():
        node = prompt.get(node_id)
        if not isinstance(node, dict):
            continue
        node_class = str(node.get("class_type", ""))
        output_type = GRAVITON_SAVE_NODE_TYPES.get(node_class)
        if output_type:
            output_nodes.append(str(node_id))
            output_types.append(output_type)

    errors: List[str] = []
    if len(output_nodes) == 0:
        errors.append("POLICY_NO_OUTPUT_NODE")
    elif len(output_nodes) > 1:
        errors.append("POLICY_MULTI_OUTPUT_UNSUPPORTED")

    return {
        "template_name": template_name,
        "valid": len(errors) == 0,
        "errors": errors,
        "output_nodes": output_nodes,
        "output_types": output_types,
    }
