"""
Temporal-based FastAPI Gateway for ComfyUI

This gateway uses Temporal for durable workflow execution.
"""

import asyncio
import uuid
import sys
from pathlib import Path
from typing import Dict, Any, Optional

import json
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from temporalio.client import Client

# Add parent to path
sys.path.append(str(Path(__file__).parent.parent))

from core.executors import ComfyUIWorkflow, WorkflowExecutionRequest, ChainExecutorWorkflow
from core.workflow_registry import get_registry
from core.registry import ComfyServerRegistry
from core.logging_config import setup_logging, get_logger
from core.chains import (
    load_chain_from_dict,
    create_execution_graph,
    ChainEngine
)
from core.chains.hashing import calculate_definition_hash
from core.database.session import get_session
from core.database.crud.chain import get_chain_by_hash, get_chains_by_hash, get_chain, list_chains, delete_chain
from core.clients.approval import router as approval_router, initialize_approval_service
from core.services.broadcast import get_broadcast, connect_broadcast, disconnect_broadcast
from core.observability.chain_logger import ChainLogger

app = FastAPI(title="ComfyAutomate Temporal Gateway", version="2.0.0")

# CORS middleware for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(approval_router)

# Temporal client (will be initialized on startup)
temporal_client: Client = None

# ComfyUI server registry (will be initialized on startup)
comfy_server_registry: ComfyServerRegistry = None

# Workflow registry (will be initialized on startup)
workflow_registry = None

# Chain engine (will be initialized on startup)
chain_engine: ChainEngine = None


@app.on_event("startup")
async def startup():
    """Connect to Temporal Server and initialize workflow registry on startup"""
    global temporal_client, comfy_server_registry, workflow_registry, chain_engine

    # Setup colored logging with file output
    log_dir = Path(__file__).parent / "logs"
    logger, log_file = setup_logging(log_dir=log_dir, log_level="INFO")

    # Connect to Temporal
    temporal_client = await Client.connect("localhost:7233")

    # Step 1: Sync templates from ComfyUI servers (downloads new templates with UI metadata)
    comfy_server_registry = ComfyServerRegistry.get_instance()
    try:
        await comfy_server_registry.sync_all_servers()
        logger.info("ComfyUI servers synced", servers=len(comfy_server_registry.servers))
    except Exception as e:
        logger.warning("ComfyUI server sync failed", error=str(e))

    # Step 2: Discover workflows (creates override files with parameters from synced templates)
    workflow_registry = get_registry()
    summary = workflow_registry.discover_workflows()

    # Initialize chain engine
    chain_engine = ChainEngine(temporal_client)

    # Initialize approval service with temporal client
    initialize_approval_service(temporal_client)

    # Connect to Redis for pub/sub
    await connect_broadcast()

    logger.info("=" * 60)
    logger.info("🚀 Temporal Gateway Started")
    logger.info("=" * 60)
    logger.info("Connected to Temporal", host="localhost:7233")
    logger.info("Gateway API", url="http://localhost:8001")
    logger.info("Temporal UI", url="http://localhost:8233")
    logger.info("Workflows discovered", count=summary.get('discovered', 0))
    if log_file:
        logger.info("Log file", path=str(log_file))
    logger.info("=" * 60)


@app.on_event("shutdown")
async def shutdown():
    """Cleanup on shutdown"""
    await disconnect_broadcast()
    if temporal_client:
        await temporal_client.close()


# Request/Response Models
class WorkflowStatusResponse(BaseModel):
    workflow_id: str
    status: str
    server_address: str | None = None
    prompt_id: str | None = None
    current_node: str | None = None
    progress: float = 0.0
    local_preview: list[Dict[str, str]] = []
    log_file_path: str | None = None
    error: str | None = None


# ============================================================================
# Workflow Discovery & Template Endpoints
# ============================================================================

@app.get("/workflows")
async def list_workflows() -> Dict[str, Any]:
    """
    List all available workflow templates

    Returns a list of discovered workflows with their metadata.
    Each workflow has a set of overridable parameters defined in its override file.

    Returns:
        Dictionary with list of workflows and their metadata
    """
    if not workflow_registry:
        raise HTTPException(status_code=503, detail="Workflow registry not initialized")

    workflows = workflow_registry.list_workflows()

    return {
        "workflows": workflows,
        "count": len(workflows)
    }


@app.get("/workflows/{workflow_name}")
async def get_workflow_details(workflow_name: str) -> Dict[str, Any]:
    """
    Get detailed information about a specific workflow template

    Returns all overridable parameters grouped by category, output information,
    and workflow metadata.

    Args:
        workflow_name: Name of the workflow (e.g., "video_wan2_2_14B_i2v")

    Returns:
        Detailed workflow information including parameters and output

    Raises:
        404: If workflow not found
    """
    if not workflow_registry:
        raise HTTPException(status_code=503, detail="Workflow registry not initialized")

    info = workflow_registry.get_workflow_info(workflow_name)

    if not info:
        available = [w["name"] for w in workflow_registry.list_workflows()]
        raise HTTPException(
            status_code=404,
            detail=f"Workflow '{workflow_name}' not found. Available workflows: {available}"
        )

    # Group parameters by category
    params_by_category = {}
    for param in info["parameters"]:
        category = param.get("category", "other")
        if category not in params_by_category:
            params_by_category[category] = []
        params_by_category[category].append(param)

    return {
        "name": info["name"],
        "description": info["description"],
        "output": info["output"],
        "parameters": params_by_category,
        "parameter_count": len(info["parameters"])
    }


# Standalone workflow endpoints removed - use chains instead
# A single workflow can be expressed as a single-step chain


class ValidateWorkflowServerRequest(BaseModel):
    """Request to validate if a workflow can run on a server"""
    workflow_name: str = Field(..., description="Name of the workflow to validate")
    server_name: str = Field(..., description="Name of the server to validate against")


@app.post("/workflows/validate-server")
async def validate_workflow_server(request: ValidateWorkflowServerRequest) -> Dict[str, Any]:
    """
    Validate if a workflow can run on a specific server.

    Checks:
    1. If server is already in workflow's validated_servers list, returns valid
    2. Otherwise validates the workflow against server's object_info
    3. If valid, adds server to validated_servers in override file

    Args:
        request: Workflow name and server name to validate

    Returns:
        {
            "valid": bool,
            "workflow_name": str,
            "server_name": str,
            "already_validated": bool,  # True if was in validated_servers
            "missing_nodes": [...],     # Only if invalid
            "invalid_inputs": [...]     # Only if invalid
        }
    """
    if not workflow_registry:
        raise HTTPException(status_code=503, detail="Workflow registry not initialized")
    if not comfy_server_registry:
        raise HTTPException(status_code=503, detail="ComfyUI server registry not initialized")

    workflow_name = request.workflow_name
    server_name = request.server_name

    # Check if workflow exists
    workflow_info = workflow_registry.get_workflow_info(workflow_name)
    if not workflow_info:
        raise HTTPException(status_code=404, detail=f"Workflow '{workflow_name}' not found")

    # Check if server exists in ComfyServerRegistry
    server_inventory = comfy_server_registry.get_server(server_name)
    if not server_inventory:
        available_servers = list(comfy_server_registry.get_all_servers().keys())
        raise HTTPException(
            status_code=404,
            detail=f"Server '{server_name}' not found. Available: {available_servers}"
        )

    # Load override file to check validated_servers
    templates_dir = Path(__file__).parent.parent / "templates"
    override_file = templates_dir / f"{workflow_name}_overrides.json"

    override_data = None
    validated_servers = []

    if override_file.exists():
        try:
            with open(override_file, 'r') as f:
                override_data = json.load(f)
            validated_servers = override_data.get("validated_servers", [])
        except Exception:
            pass

    # Check if already validated
    if server_name in validated_servers:
        return {
            "valid": True,
            "workflow_name": workflow_name,
            "server_name": server_name,
            "already_validated": True
        }

    # Load workflow template and validate against server
    workflow_file = templates_dir / f"{workflow_name}.json"
    if not workflow_file.exists():
        raise HTTPException(status_code=404, detail=f"Workflow template file not found")

    try:
        with open(workflow_file, 'r') as f:
            workflow_data = json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load workflow: {e}")

    # Remove metadata keys (not part of actual workflow)
    workflow_prompt = {k: v for k, v in workflow_data.items() if not k.startswith('_')}

    # Validate against server
    result = comfy_server_registry.validate_prompt(workflow_prompt, server_name)

    if result["valid"]:
        # Add to validated_servers and update override file
        if override_data is not None:
            validated_servers.append(server_name)
            override_data["validated_servers"] = validated_servers
            try:
                with open(override_file, 'w') as f:
                    json.dump(override_data, f, indent=2, ensure_ascii=False)
            except Exception:
                pass  # Non-critical if we can't update

        return {
            "valid": True,
            "workflow_name": workflow_name,
            "server_name": server_name,
            "already_validated": False
        }
    else:
        return {
            "valid": False,
            "workflow_name": workflow_name,
            "server_name": server_name,
            "already_validated": False,
            "missing_nodes": result.get("missing_nodes", []),
            "invalid_inputs": result.get("invalid_inputs", [])
        }


@app.get("/servers")
async def list_servers() -> Dict[str, Any]:
    """
    List all available ComfyUI servers with their status.

    Returns:
        List of servers with name, URL, status, and node count
    """
    if not comfy_server_registry:
        raise HTTPException(status_code=503, detail="ComfyUI server registry not initialized")

    servers = []
    for name, inventory in comfy_server_registry.get_all_servers().items():
        servers.append({
            "name": name,
            "url": inventory.server_url,
            "node_count": len(inventory.available_nodes),
            "template_count": len(inventory.templates),
            "last_sync": inventory.last_sync.isoformat() if inventory.last_sync else None,
            "sync_error": inventory.sync_error
        })

    return {
        "servers": servers,
        "count": len(servers)
    }


@app.get("/workflows/{workflow_name}/validated-servers")
async def get_workflow_validated_servers(workflow_name: str) -> Dict[str, Any]:
    """
    Get list of servers validated to run a specific workflow.

    Args:
        workflow_name: Name of the workflow

    Returns:
        List of validated server names
    """
    if not workflow_registry:
        raise HTTPException(status_code=503, detail="Workflow registry not initialized")

    # Check if workflow exists
    workflow_info = workflow_registry.get_workflow_info(workflow_name)
    if not workflow_info:
        raise HTTPException(status_code=404, detail=f"Workflow '{workflow_name}' not found")

    # Load override file
    templates_dir = Path(__file__).parent.parent / "templates"
    override_file = templates_dir / f"{workflow_name}_overrides.json"

    validated_servers = []

    if override_file.exists():
        try:
            with open(override_file, 'r') as f:
                override_data = json.load(f)
            validated_servers = override_data.get("validated_servers", [])
        except Exception:
            pass

    return {
        "workflow_name": workflow_name,
        "validated_servers": validated_servers,
        "count": len(validated_servers)
    }


@app.get("/servers/{server_name}/combo-options/{class_type}/{input_name}")
async def get_combo_options(server_name: str, class_type: str, input_name: str) -> Dict[str, Any]:
    """
    Get available options for a combo input (dropdown) from a server.

    This is useful for getting available checkpoints, LoRAs, VAEs, etc.

    Args:
        server_name: Name of the ComfyUI server
        class_type: Node class type (e.g., "CheckpointLoaderSimple")
        input_name: Input name (e.g., "ckpt_name")

    Returns:
        List of available options for the combo input
    """
    if not comfy_server_registry:
        raise HTTPException(status_code=503, detail="ComfyUI server registry not initialized")

    server_inventory = comfy_server_registry.get_server(server_name)
    if not server_inventory:
        available_servers = list(comfy_server_registry.get_all_servers().keys())
        raise HTTPException(
            status_code=404,
            detail=f"Server '{server_name}' not found. Available: {available_servers}"
        )

    options = server_inventory.get_combo_options(class_type, input_name)

    if options is None:
        return {
            "server_name": server_name,
            "class_type": class_type,
            "input_name": input_name,
            "options": [],
            "is_combo": False
        }

    return {
        "server_name": server_name,
        "class_type": class_type,
        "input_name": input_name,
        "options": options,
        "is_combo": True,
        "count": len(options)
    }


@app.get("/workflows/{workflow_name}/parameter-options/{server_name}")
async def get_workflow_parameter_options(workflow_name: str, server_name: str) -> Dict[str, Any]:
    """
    Get available combo options for overridable parameters in a workflow.

    Only returns options for parameters defined in the override file,
    not all inputs in the workflow.

    Args:
        workflow_name: Name of the workflow
        server_name: Name of the ComfyUI server

    Returns:
        Dictionary mapping parameter keys to their available options
    """
    if not comfy_server_registry:
        raise HTTPException(status_code=503, detail="ComfyUI server registry not initialized")

    # Check server exists
    server_inventory = comfy_server_registry.get_server(server_name)
    if not server_inventory:
        available_servers = list(comfy_server_registry.get_all_servers().keys())
        raise HTTPException(
            status_code=404,
            detail=f"Server '{server_name}' not found. Available: {available_servers}"
        )

    # Load override file to get overridable parameters
    templates_dir = Path(__file__).parent.parent / "templates"
    override_file = templates_dir / f"{workflow_name}_overrides.json"

    if not override_file.exists():
        raise HTTPException(status_code=404, detail=f"Workflow '{workflow_name}' not found")

    try:
        with open(override_file, 'r') as f:
            override_data = json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load override file: {e}")

    parameters = override_data.get("parameters", [])

    # Get combo options for each parameter
    parameter_options = {}

    for param in parameters:
        class_type = param.get("node_class")
        input_name = param.get("input_key")
        param_key = param.get("key")  # e.g., "30.ckpt_name"

        if not class_type or not input_name:
            continue

        options = server_inventory.get_combo_options(class_type, input_name)
        if options:
            parameter_options[param_key] = options

    return {
        "workflow_name": workflow_name,
        "server_name": server_name,
        "parameter_options": parameter_options,
        "count": len(parameter_options)
    }


@app.get("/workflow/status/{workflow_id}")
async def get_workflow_status(workflow_id: str) -> WorkflowStatusResponse:
    """
    Get current workflow status by querying Temporal

    This uses Temporal queries to get real-time state from running workflow.
    """
    try:
        # Get workflow handle
        handle = temporal_client.get_workflow_handle(workflow_id)

        # Query current status
        status_data = await handle.query("get_status")

        # Try to get result if completed
        result = None
        try:
            result = await handle.result()
        except:
            # Workflow still running
            pass

        # Build response
        response = WorkflowStatusResponse(
            workflow_id=workflow_id,
            status=status_data.get("status", "unknown"),
            server_address=status_data.get("server_address"),
            prompt_id=status_data.get("prompt_id"),
            current_node=status_data.get("current_node"),
            progress=status_data.get("progress", 0.0),
            error=status_data.get("error")
        )

        # If completed, add final results
        # Note: result is a dict, not WorkflowExecutionResult object
        if result:
            response.status = result.get("status")
            response.local_preview = result.get("local_preview", [])
            response.log_file_path = result.get("log_file_path")
            if result.get("error"):
                response.error = result.get("error")

        return response

    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Workflow not found: {str(e)}")


@app.post("/workflow/cancel/{workflow_id}")
async def cancel_workflow(workflow_id: str) -> Dict[str, str]:
    """
    Cancel a running workflow by sending cancel signal
    """
    try:
        handle = temporal_client.get_workflow_handle(workflow_id)
        await handle.signal("cancel")

        return {
            "workflow_id": workflow_id,
            "status": "cancel_requested",
            "message": "Cancel signal sent to workflow"
        }

    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Failed to cancel workflow: {str(e)}")


@app.get("/artifacts/{artifact_id}")
async def serve_artifact(artifact_id: str):
    """Serve an artifact (image/video) by ID"""
    from core.database import get_session
    from core.database.crud.artifact import get_artifact

    with get_session() as session:
        artifact = get_artifact(session, artifact_id)

        if not artifact:
            raise HTTPException(status_code=404, detail="Artifact not found")

        artifact_path = Path(artifact.local_path)

        if not artifact_path.exists():
            raise HTTPException(status_code=404, detail="Artifact file not found on disk")

        # Determine media type based on file type
        media_type_map = {
            "image": f"image/{artifact.file_format or 'png'}",
            "video": f"video/{artifact.file_format or 'mp4'}",
        }
        media_type = media_type_map.get(artifact.file_type, "application/octet-stream")

        return StreamingResponse(
            iter([artifact_path.read_bytes()]),
            media_type=media_type,
            headers={"Content-Disposition": f"inline; filename={artifact.filename}"}
        )


@app.get("/health")
async def health_check():
    """Gateway health check"""
    return {
        "status": "healthy",
        "temporal_connected": temporal_client is not None,
        "version": "2.0.0-temporal"
    }


@app.get("/node-definitions")
async def get_node_definitions():
    """
    Get all workflow definitions for the frontend node editor.
    Returns UI metadata + overridable parameters for each workflow.
    """
    from dataclasses import asdict

    workflows = []
    for name, info in workflow_registry.workflows.items():
        # Skip workflows without UI metadata
        if not info.ui_metadata:
            continue

        ui = info.ui_metadata

        # Derive inputSockets from parameters with input_key containing "image" or "video"
        input_sockets = []
        for p in info.parameters:
            if "image" in p.input_key.lower() or "video" in p.input_key.lower():
                # Determine socket type from input_key
                socket_type = "video" if "video" in p.input_key.lower() else "image"
                input_sockets.append({
                    "id": p.key,  # Use full key (e.g. "78.image") for uniqueness
                    "type": socket_type,
                    "label": p.node_title,  # Use node title as label
                })

        workflows.append({
            "workflow_name": name,
            "nodeType": ui.nodeType,
            "label": ui.label,
            "icon": ui.icon,
            "color": ui.color,
            "category": ui.category,
            "inputSockets": input_sockets,
            "outputSockets": [asdict(s) for s in ui.outputSockets],
            "parameters": [
                {
                    "key": p.key,
                    "input_key": p.input_key,
                    "default_value": p.default_value,
                    "type": p.type,
                    "description": p.description,
                    "category": p.category,
                }
                for p in info.parameters
            ],
        })

    return workflows


# ============================================================================
# Chain List & Management Endpoints
# ============================================================================

@app.get("/chains")
async def get_chains(
    limit: int = 50,
    offset: int = 0,
    status: Optional[str] = None,
):
    """
    List all chains with optional filtering.

    Args:
        limit: Maximum number of chains to return (default 50)
        offset: Number of chains to skip (for pagination)
        status: Optional status filter ('running', 'completed', 'failed')

    Returns:
        List of chains with metadata
    """
    with get_session() as session:
        chains = list_chains(session, limit=limit, offset=offset, status=status)

        return {
            "chains": [
                {
                    "id": c.id,
                    "name": c.name,
                    "version": c.version,
                    "status": c.status,
                    "job_id": c.job_id,
                    "started_at": c.started_at.isoformat() if c.started_at else None,
                    "completed_at": c.completed_at.isoformat() if c.completed_at else None,
                    "error_message": c.error_message,
                    "definition_hash": c.definition_hash,
                }
                for c in chains
            ],
            "count": len(chains),
            "limit": limit,
            "offset": offset,
        }


@app.get("/chains/names")
async def get_chain_names():
    """
    Get unique chain names with version counts.

    Returns:
        List of unique chain names with their latest version and run count
    """
    from sqlalchemy import func, desc

    with get_session() as session:
        from core.database.models import Chain

        # Get unique names with counts and latest info
        results = session.query(
            Chain.name,
            func.count(Chain.id).label("run_count"),
            func.max(Chain.version).label("latest_version"),
            func.max(Chain.started_at).label("last_run"),
        ).group_by(Chain.name).order_by(desc(func.max(Chain.started_at))).all()

        return {
            "chain_names": [
                {
                    "name": r.name,
                    "run_count": r.run_count,
                    "latest_version": r.latest_version,
                    "last_run": r.last_run.isoformat() if r.last_run else None,
                }
                for r in results
            ]
        }


@app.get("/chains/by-name/{chain_name}")
async def get_chain_versions(chain_name: str):
    """
    Get all versions/runs of a specific chain name.

    Args:
        chain_name: Chain name to look up

    Returns:
        List of all chain runs for this name
    """
    from sqlalchemy import desc

    with get_session() as session:
        from core.database.models import Chain

        chains = session.query(Chain).filter(
            Chain.name == chain_name
        ).order_by(desc(Chain.version)).all()

        return {
            "chain_name": chain_name,
            "versions": [
                {
                    "id": c.id,
                    "version": c.version,
                    "status": c.status,
                    "job_id": c.job_id,
                    "started_at": c.started_at.isoformat() if c.started_at else None,
                    "completed_at": c.completed_at.isoformat() if c.completed_at else None,
                    "error_message": c.error_message,
                }
                for c in chains
            ]
        }


@app.get("/chains/{chain_id}/artifacts")
async def get_chain_artifacts(chain_id: str):
    """
    Get all artifacts for a chain, organized by step.

    Args:
        chain_id: Chain ID

    Returns:
        Artifacts grouped by step_id
    """
    with get_session() as session:
        from core.database.models import Chain, Workflow, Artifact

        chain = session.query(Chain).filter(Chain.id == chain_id).first()
        if not chain:
            raise HTTPException(status_code=404, detail=f"Chain not found: {chain_id}")

        # Get all workflows for this chain with their artifacts
        workflows = session.query(Workflow).filter(
            Workflow.chain_id == chain_id
        ).all()

        steps = []
        for wf in workflows:
            artifacts = session.query(Artifact).filter(
                Artifact.workflow_id == wf.id
            ).all()

            steps.append({
                "step_id": wf.step_id,
                "workflow_name": wf.workflow_name,
                "status": wf.status,
                "error_message": wf.error_message,
                "artifacts": [
                    {
                        "id": a.id,
                        "filename": a.filename,
                        "file_type": a.file_type,
                        "file_format": a.file_format,
                        "file_size": a.file_size,
                        "created_at": a.created_at.isoformat() if a.created_at else None,
                        "url": f"/artifacts/{a.id}",
                    }
                    for a in artifacts
                ]
            })

        return {
            "chain_id": chain_id,
            "chain_name": chain.name,
            "version": chain.version,
            "status": chain.status,
            "error_message": chain.error_message,
            "steps": steps,
        }


@app.get("/chains/{chain_id}/definition")
async def get_chain_definition(chain_id: str):
    """
    Get the chain definitions for a chain.

    Args:
        chain_id: Chain ID

    Returns:
        Both original and executed definitions (executed may be null if not completed)
    """
    with get_session() as session:
        from core.database.models import Chain

        chain = session.query(Chain).filter(Chain.id == chain_id).first()
        if not chain:
            raise HTTPException(status_code=404, detail=f"Chain not found: {chain_id}")

        if not chain.chain_definition:
            raise HTTPException(status_code=404, detail=f"Chain definition not found for: {chain_id}")

        return {
            "chain_id": chain_id,
            "chain_name": chain.name,
            "version": chain.version,
            "definition": chain.chain_definition,
            "executed_definition": chain.executed_definition,
        }


@app.delete("/chains/{chain_id}")
async def delete_chain_endpoint(chain_id: str):
    """
    Delete a chain and all associated data.

    Args:
        chain_id: Chain ID to delete

    Returns:
        Success message or 404 if not found
    """
    with get_session() as session:
        success = delete_chain(session, chain_id)

        if not success:
            raise HTTPException(status_code=404, detail=f"Chain not found: {chain_id}")

        return {"message": f"Chain {chain_id} deleted successfully"}


# ============================================================================
# Hash-based Chain Lookup Endpoints
# ============================================================================

class HashRequest(BaseModel):
    """Request to calculate hash from chain definition"""
    chain: Dict[str, Any]


@app.post("/chains/hash")
async def calculate_chain_hash(request: HashRequest):
    """
    Calculate hash for a chain definition.

    The hash is content-addressable - same definition always produces same hash.
    Use this to check if a chain has been executed before.

    Returns:
        - hash: 16-character hash of the chain definition
    """
    try:
        definition_hash = calculate_definition_hash(request.chain)
        return {"hash": definition_hash}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to calculate hash: {str(e)}")


@app.get("/chains/by-hash/{definition_hash}")
async def get_chain_by_definition_hash(definition_hash: str, status: Optional[str] = None):
    """
    Look up chains by definition hash.

    Args:
        definition_hash: 16-character hash from /chains/hash
        status: Optional filter (e.g., 'completed', 'running')

    Returns:
        - chains: List of matching chains (newest first)
        - latest_completed: The most recent completed chain (if any)
    """
    with get_session() as session:
        chains = get_chains_by_hash(session, definition_hash, status=status, limit=10)

        if not chains:
            return {
                "chains": [],
                "latest_completed": None,
                "message": "No chains found with this hash"
            }

        # Find latest completed with definition
        latest_completed = None
        chain_definition = None
        for chain in chains:
            if chain.status == "completed":
                latest_completed = {
                    "chain_id": chain.id,
                    "job_id": chain.job_id,
                    "version": chain.version,
                    "status": chain.status,
                    "completed_at": chain.completed_at.isoformat() if chain.completed_at else None,
                }
                chain_definition = chain.chain_definition
                break

        return {
            "chains": [
                {
                    "chain_id": c.id,
                    "job_id": c.job_id,
                    "version": c.version,
                    "status": c.status,
                    "started_at": c.started_at.isoformat() if c.started_at else None,
                    "completed_at": c.completed_at.isoformat() if c.completed_at else None,
                }
                for c in chains
            ],
            "latest_completed": latest_completed,
            "chain_definition": chain_definition,
        }


# ============================================================================
# SSE Events Endpoint
# ============================================================================

@app.get("/chains/events")
async def chain_events(chain_id: str, request: Request):
    """
    SSE endpoint for chain events (approvals, completions, etc.)

    Subscribe to real-time events for a specific chain.
    Events include: approval_requested, step_completed, chain_completed, chain_failed
    """
    # Look up chain to get name/version for logging
    chain_logger = None
    with get_session() as session:
        chain = get_chain(session, chain_id)
        if chain:
            chain_logger = ChainLogger.create(chain.name, chain.version, chain_id)

    def log(msg: str, level: str = "info"):
        if chain_logger:
            getattr(chain_logger.gateway, level)(msg)

    log(f"SSE client subscribing to chain:{chain_id}")

    async def event_generator():
        broadcast = get_broadcast()
        channel = f"chain:{chain_id}"

        log(f"Starting SSE subscription for {channel}")
        try:
            async with broadcast.subscribe(channel=channel) as subscriber:
                async for event in subscriber:
                    if await request.is_disconnected():
                        log(f"SSE client disconnected from {channel}")
                        break
                    data = json.loads(event.message)
                    event_type = data.get("type", "unknown")
                    log(f"SSE sending event: {event_type} for {channel}")
                    yield {
                        "event": event_type,
                        "data": event.message
                    }
        except asyncio.CancelledError:
            log(f"SSE subscription cancelled for {channel}")
        except RuntimeError as e:
            # Handle Redis transport closed during cleanup
            if "handler is closed" in str(e):
                log(f"SSE cleanup: Redis connection already closed for {channel}")
            else:
                raise
        except Exception as e:
            log(f"SSE error for {channel}: {e}", level="error")
        finally:
            log(f"SSE subscription ended for {channel}")

    return EventSourceResponse(event_generator())


# ============================================================================
# Chain Execution Endpoints
# ============================================================================

class ChainExecutionRequest(BaseModel):
    """Request to execute a chain with inline definition"""
    chain: Dict[str, Any]  # Chain definition (name, steps, etc.)
    parameters: Dict[str, Any] = {}  # Runtime parameters
    level_wait_seconds: int = Field(default=0, ge=0, le=300)  # Wait between levels (0-300s)


class ChainRegenerationRequest(BaseModel):
    """Request to regenerate chain from a specific step"""
    definition_hash: str  # Hash to look up cached results from
    from_step: str
    new_parameters: Dict[str, Any] = {}
    chain_definition: Optional[Dict[str, Any]] = None  # Current definition (overrides stored)


@app.post("/chains/execute")
async def execute_chain(request: ChainExecutionRequest, force: bool = False):
    """
    Execute a workflow chain.

    If the same chain definition was executed before and completed,
    returns the cached result instead of re-executing (unless force=true).

    Args:
        request: Chain definition and parameters
        force: If true, always execute even if cached result exists

    Returns:
        - chain_id: Database ID for SSE subscription
        - job_id: Temporal ID for status/result queries
        - cached: True if returning cached result
    """
    try:
        # Calculate hash for cache lookup
        definition_hash = calculate_definition_hash(request.chain)

        # Check for existing completed chain with same hash (unless force=true)
        if not force:
            with get_session() as session:
                existing = get_chain_by_hash(session, definition_hash)
                if existing and existing.status == "completed":
                    return {
                        "chain_id": existing.id,
                        "job_id": existing.job_id,
                        "chain_name": existing.name,
                        "definition_hash": definition_hash,
                        "status": "completed",
                        "cached": True,
                        "version": existing.version,
                        "completed_at": existing.completed_at.isoformat() if existing.completed_at else None,
                        "message": f"Returning cached result. Use /chains/result/{existing.job_id} to get results. Pass force=true to re-execute."
                    }

        # Load and validate chain
        chain = load_chain_from_dict(request.chain)
        graph = create_execution_graph(chain)

        # Execute via chain engine
        result = await chain_engine.execute_chain(
            graph=graph,
            chain_definition=request.chain,
            initial_parameters=request.parameters,
            level_wait_seconds=request.level_wait_seconds,
        )

        return {
            "chain_id": result["chain_id"],
            "job_id": result["job_id"],
            "chain_name": chain.name,
            "definition_hash": definition_hash,
            "status": "started",
            "cached": False,
            "total_steps": len(graph.nodes),
            "parallel_groups": [list(level) for level in graph.get_execution_levels()],
            "message": f"Chain execution started. Use /chains/status/{result['job_id']} to check progress."
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start chain: {str(e)}")


@app.get("/chains/status/{job_id}")
async def get_chain_status(job_id: str):
    """
    Get current status of a running chain

    Args:
        job_id: Job ID (Temporal workflow ID) returned from /chains/execute

    Returns current level, completed steps, and step statuses
    """
    try:
        status = await chain_engine.get_chain_status(job_id)
        return status

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get chain status: {str(e)}")


@app.get("/chains/result/{job_id}")
async def get_chain_result(job_id: str):
    """
    Wait for chain to complete and get final result

    Args:
        job_id: Job ID (Temporal workflow ID) returned from /chains/execute

    Returns ChainExecutionResult with all step results
    """
    try:
        result = await chain_engine.get_chain_result(job_id)
        # Result is already a dict from Temporal

        # Process step results
        step_results_processed = {}
        for step_id, step_result in result.get("step_results", {}).items():
            step_results_processed[step_id] = {
                "status": step_result.get("status"),
                "workflow": step_result.get("workflow"),
                "output": step_result.get("output"),
                "parameters": step_result.get("parameters"),
                "error": step_result.get("error")
            }

        # Calculate successful/failed steps
        successful_steps = [
            step_id for step_id, sr in result.get("step_results", {}).items()
            if sr.get("status") == "completed"
        ]
        failed_steps = [
            step_id for step_id, sr in result.get("step_results", {}).items()
            if sr.get("status") == "failed"
        ]

        return {
            "chain_name": result.get("chain_name"),
            "status": result.get("status"),
            "step_results": step_results_processed,
            "successful_steps": successful_steps,
            "failed_steps": failed_steps,
            "error": result.get("error")
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get chain result: {str(e)}")


@app.post("/chains/regenerate")
async def regenerate_chain_endpoint(request: ChainRegenerationRequest):
    """
    Regenerate chain from a specific step with new parameters.

    Looks up chain definition by hash and regenerates from the specified step.

    Args:
        request: definition_hash, from_step, and new_parameters

    Returns:
        chain_id (for SSE) and job_id (for status queries)
    """
    try:
        # Look up chain by hash (for cached results lookup)
        with get_session() as session:
            chain_record = get_chain_by_hash(session, request.definition_hash)
            if not chain_record:
                raise HTTPException(status_code=404, detail=f"No chain found with hash: {request.definition_hash}")

            chain_name = chain_record.name

        # Use provided chain_definition if available, otherwise fall back to stored
        # The provided definition has the current YAML config (e.g., updated approval settings)
        chain_definition = request.chain_definition or chain_record.chain_definition
        if not chain_definition:
            raise HTTPException(status_code=400, detail="No chain definition provided or stored")

        # Create graph from current definition (not stored)
        chain = load_chain_from_dict(chain_definition)
        graph = create_execution_graph(chain)

        # Regenerate using engine
        result = await chain_engine.regenerate_chain(
            chain_name=chain_name,
            graph=graph,
            from_step=request.from_step,
            new_parameters=request.new_parameters,
            chain_definition=chain_definition,
            definition_hash=request.definition_hash,
        )

        return {
            "chain_id": result["chain_id"],
            "job_id": result["job_id"],
            "chain_name": chain_name,
            "definition_hash": request.definition_hash,
            "status": "started",
            "from_step": request.from_step,
            "message": f"Regeneration started from step '{request.from_step}'."
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to regenerate: {str(e)}")


# ============================================================================
# Step Parameter Update Endpoints
# ============================================================================

class UpdateStepParametersRequest(BaseModel):
    """Request to update parameters for a pending step"""
    parameters: Dict[str, Any]


@app.post("/chains/{chain_id}/steps/{step_id}/update-parameters")
async def update_step_parameters(
    chain_id: str,
    step_id: str,
    request: UpdateStepParametersRequest
):
    """
    Update parameters for any step that hasn't executed yet.

    This sends a signal to the running workflow to update the step's parameters.
    The update will only take effect if the step hasn't started executing.

    Args:
        chain_id: Chain ID (database ID)
        step_id: Step ID to update
        request: New parameters to merge into the step

    Returns:
        Status of the signal sent
    """
    with get_session() as session:
        chain = get_chain(session, chain_id)
        if not chain:
            raise HTTPException(status_code=404, detail=f"Chain not found: {chain_id}")
        if not chain.job_id:
            raise HTTPException(status_code=400, detail="Chain has no running job")

        job_id = chain.job_id

    try:
        handle = temporal_client.get_workflow_handle(job_id)
        await handle.signal("update_step_parameters_signal", {
            "step_id": step_id,
            "parameters": request.parameters,
        })

        return {
            "status": "signal_sent",
            "chain_id": chain_id,
            "step_id": step_id,
            "parameters_updated": list(request.parameters.keys()),
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update parameters: {str(e)}")


@app.get("/chains/{chain_id}/pending-steps")
async def get_pending_steps(chain_id: str):
    """
    Get steps that haven't executed yet (can have params updated).

    Args:
        chain_id: Chain ID (database ID)

    Returns:
        List of step IDs that are pending execution
    """
    with get_session() as session:
        chain = get_chain(session, chain_id)
        if not chain:
            raise HTTPException(status_code=404, detail=f"Chain not found: {chain_id}")
        if not chain.job_id:
            raise HTTPException(status_code=400, detail="Chain has no running job")

        job_id = chain.job_id

    try:
        handle = temporal_client.get_workflow_handle(job_id)
        pending = await handle.query("get_pending_steps")

        return {
            "chain_id": chain_id,
            "pending_steps": pending,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get pending steps: {str(e)}")


@app.post("/chains/{chain_id}/cancel")
async def cancel_chain(chain_id: str):
    """
    Cancel a running chain execution.

    Args:
        chain_id: Chain ID (database ID)

    Returns:
        Status of the cancellation
    """
    with get_session() as session:
        chain = get_chain(session, chain_id)
        if not chain:
            raise HTTPException(status_code=404, detail=f"Chain not found: {chain_id}")
        if not chain.job_id:
            raise HTTPException(status_code=400, detail="Chain has no running job")

        job_id = chain.job_id

    try:
        await chain_engine.cancel_chain(job_id)

        # Update chain status to cancelled in database
        from core.database.crud.chain import update_chain_status
        with get_session() as session:
            update_chain_status(session, chain_id, "cancelled")

        return {
            "status": "cancelled",
            "chain_id": chain_id,
            "job_id": job_id,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to cancel chain: {str(e)}")


@app.post("/chains/{chain_id}/skip-level-wait")
async def skip_level_wait(chain_id: str, level_num: Optional[int] = None):
    """
    Skip the current level wait early.

    Args:
        chain_id: Chain ID (database ID)
        level_num: Optional level number to skip (defaults to current level)

    Returns:
        Status of the signal sent
    """
    with get_session() as session:
        chain = get_chain(session, chain_id)
        if not chain:
            raise HTTPException(status_code=404, detail=f"Chain not found: {chain_id}")
        if not chain.job_id:
            raise HTTPException(status_code=400, detail="Chain has no running job")

        job_id = chain.job_id

    try:
        handle = temporal_client.get_workflow_handle(job_id)
        signal_data = {}
        if level_num is not None:
            signal_data["level_num"] = level_num

        await handle.signal("skip_level_wait_signal", signal_data)

        return {
            "status": "signal_sent",
            "chain_id": chain_id,
            "level_num": level_num,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to skip level wait: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001, log_level="info")
