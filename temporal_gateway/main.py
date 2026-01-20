"""
Temporal-based FastAPI Gateway for ComfyUI

This gateway uses Temporal for durable workflow execution.
"""

import uuid
import sys
from pathlib import Path
from typing import Dict, Any, Optional

import json
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from temporalio.client import Client

# Add parent to path
sys.path.append(str(Path(__file__).parent.parent))

from temporal_gateway.executors import ComfyUIWorkflow, WorkflowExecutionRequest, ChainExecutorWorkflow
from temporal_gateway.registry import get_registry
from temporal_gateway.logging_config import setup_logging, get_logger
from temporal_gateway.chains import (
    load_chain_from_dict,
    create_execution_graph,
    ChainEngine
)
from temporal_gateway.chains.hashing import calculate_definition_hash
from temporal_gateway.database.session import get_session
from temporal_gateway.database.crud.chain import get_chain_by_hash, get_chains_by_hash, get_chain
from temporal_gateway.clients.approval import router as approval_router, initialize_approval_service
from temporal_gateway.services.broadcast import get_broadcast, connect_broadcast, disconnect_broadcast

app = FastAPI(title="ComfyAutomate Temporal Gateway", version="2.0.0")

# Include routers
app.include_router(approval_router)

# Temporal client (will be initialized on startup)
temporal_client: Client = None

# Workflow registry (will be initialized on startup)
workflow_registry = None

# Chain engine (will be initialized on startup)
chain_engine: ChainEngine = None


@app.on_event("startup")
async def startup():
    """Connect to Temporal Server and initialize workflow registry on startup"""
    global temporal_client, workflow_registry, chain_engine

    # Setup colored logging with file output
    log_dir = Path(__file__).parent / "logs"
    logger, log_file = setup_logging(log_dir=log_dir, log_level="INFO")

    # Connect to Temporal
    temporal_client = await Client.connect("localhost:7233")

    # Initialize workflow registry
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
    logger.info("Workflows discovered", count=summary['discovered'])
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
    from temporal_gateway.database import get_session
    from temporal_gateway.database.crud.artifact import get_artifact

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
    logger = get_logger(__name__)
    logger.info(f"SSE client subscribing to chain:{chain_id}")

    async def event_generator():
        broadcast = get_broadcast()
        channel = f"chain:{chain_id}"

        logger.info(f"Starting SSE subscription for {channel}")
        async with broadcast.subscribe(channel=channel) as subscriber:
            async for event in subscriber:
                if await request.is_disconnected():
                    logger.info(f"SSE client disconnected from {channel}")
                    break
                data = json.loads(event.message)
                event_type = data.get("type", "unknown")
                logger.info(f"SSE sending event: {event_type} for {channel}")
                yield {
                    "event": event_type,
                    "data": event.message
                }
        logger.info(f"SSE subscription ended for {channel}")

    return EventSourceResponse(event_generator())


# ============================================================================
# Chain Execution Endpoints
# ============================================================================

class ChainExecutionRequest(BaseModel):
    """Request to execute a chain with inline definition"""
    chain: Dict[str, Any]  # Chain definition (name, steps, etc.)
    parameters: Dict[str, Any] = {}  # Runtime parameters


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
            initial_parameters=request.parameters
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001, log_level="info")
