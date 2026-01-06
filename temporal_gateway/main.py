"""
Temporal-based FastAPI Gateway for ComfyUI

This gateway uses Temporal for durable workflow execution.
"""

import uuid
import sys
from pathlib import Path
from typing import Dict, Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from temporalio.client import Client

# Add parent to path
sys.path.append(str(Path(__file__).parent.parent))

from temporal_gateway.workflows import ComfyUIWorkflow, WorkflowExecutionRequest, ChainExecutorWorkflow
from temporal_gateway.workflow_registry import get_registry
from temporal_gateway.logging_config import setup_logging, get_logger
from gateway.core import load_balancer, image_storage
from gateway.models import ComfyUIServer
from temporal_gateway.chains import (
    load_chain,
    create_execution_graph,
    discover_chains,
    ChainEngine
)
from temporal_gateway.clients.approval import router as approval_router, initialize_approval_service

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
    if temporal_client:
        await temporal_client.close()


# Request/Response Models
class ExecuteWorkflowRequest(BaseModel):
    workflow: Dict[str, Any]
    strategy: str = "least_loaded"


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


# Template-based workflow execution models
class TemplateExecuteRequest(BaseModel):
    parameters: Dict[str, Any]
    strategy: str = "least_loaded"


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


@app.post("/workflows/{workflow_name}/execute")
async def execute_workflow_template(
    workflow_name: str,
    request: TemplateExecuteRequest
) -> Dict[str, str]:
    """
    Execute a workflow template with parameter overrides

    This endpoint allows you to execute a pre-defined workflow template
    by providing only the parameters you want to override. All other
    parameters will use their default values from the workflow.

    Only parameters defined in the workflow's override file can be changed.
    Parameters removed from the override file are frozen and cannot be modified.

    Args:
        workflow_name: Name of the workflow template
        request: Execution request with parameters and strategy

    Returns:
        Dictionary with workflow_id and execution status

    Raises:
        400: If invalid parameters provided
        404: If workflow not found
        500: If execution fails

    Example:
        POST /workflows/video_wan2_2_14B_i2v/execute
        {
            "parameters": {
                "93.text": "A dragon flying in the sky",
                "98.width": 1024,
                "98.height": 576
            },
            "strategy": "least_loaded"
        }
    """
    if not workflow_registry:
        raise HTTPException(status_code=503, detail="Workflow registry not initialized")

    try:
        # Apply parameter overrides to the workflow template
        workflow_json = workflow_registry.apply_overrides(
            workflow_name,
            request.parameters
        )

    except ValueError as e:
        # Parameter validation failed
        raise HTTPException(status_code=400, detail=str(e))

    except Exception as e:
        # Workflow not found or other error
        available = [w["name"] for w in workflow_registry.list_workflows()]
        raise HTTPException(
            status_code=404,
            detail=f"Workflow '{workflow_name}' not found. Available workflows: {available}"
        )

    # Generate unique workflow ID
    workflow_id = f"workflow-{uuid.uuid4()}"

    try:
        # Start Temporal workflow with modified workflow JSON
        await temporal_client.start_workflow(
            ComfyUIWorkflow.run,
            WorkflowExecutionRequest(
                workflow_definition=workflow_json,
                strategy=request.strategy
            ),
            id=workflow_id,
            task_queue="comfyui-gpu-farm"
        )

        # Get output type for response
        info = workflow_registry.get_workflow_info(workflow_name)
        output_type = info["output"]["output_type"] if info and info["output"] else "unknown"

        return {
            "workflow_id": workflow_id,
            "status": "started",
            "workflow_name": workflow_name,
            "output_type": output_type,
            "message": f"Workflow execution started. Use /workflow/status/{workflow_id} to check progress."
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start workflow: {str(e)}")


# ============================================================================
# Raw Workflow Execution (Advanced Users)
# ============================================================================

@app.post("/workflow/execute")
async def execute_workflow(request: ExecuteWorkflowRequest) -> Dict[str, str]:
    """
    Start workflow execution using Temporal

    Returns workflow_id immediately. Workflow runs in background.
    """
    # Generate unique workflow ID
    workflow_id = f"workflow-{uuid.uuid4()}"

    try:
        # Start Temporal workflow
        await temporal_client.start_workflow(
            ComfyUIWorkflow.run,
            WorkflowExecutionRequest(
                workflow_definition=request.workflow,
                strategy=request.strategy
            ),
            id=workflow_id,
            task_queue="comfyui-gpu-farm"
        )

        return {
            "workflow_id": workflow_id,
            "status": "started",
            "message": "Workflow execution started. Use /workflow/status/{workflow_id} to check progress."
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start workflow: {str(e)}")


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


@app.get("/images/{filename}")
async def serve_image(filename: str):
    """Serve a stored image"""
    image_path = image_storage.get_image_path(filename)

    if not image_path:
        raise HTTPException(status_code=404, detail="Image not found")

    return StreamingResponse(
        iter([image_path.read_bytes()]),
        media_type="image/png",
        headers={"Content-Disposition": f"inline; filename={filename}"}
    )


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


# Server management endpoints (reuse existing load balancer)
@app.post("/servers/register")
async def register_server(server: ComfyUIServer):
    """Register a new ComfyUI server"""
    try:
        success = load_balancer.register_server(
            name=server.name,
            address=server.address,
            description=server.description
        )

        if success:
            return {"status": "registered", "server": server.address}
        else:
            raise HTTPException(status_code=400, detail="Failed to register server")

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/servers")
async def list_servers():
    """List all registered servers"""
    return {"servers": load_balancer.list_servers()}


@app.get("/servers/health")
async def get_servers_health():
    """Get health status of all servers"""
    return load_balancer.get_servers_health()


@app.get("/health")
async def health_check():
    """Gateway health check"""
    return {
        "status": "healthy",
        "temporal_connected": temporal_client is not None,
        "version": "2.0.0-temporal"
    }


# ============================================================================
# Chain Execution Endpoints
# ============================================================================

@app.get("/chains")
async def list_chains():
    """
    List all available workflow chains

    Returns:
        List of chain summaries with name, description, and step count
    """
    try:
        chains = discover_chains("chains/")
        return {"chains": chains, "count": len(chains)}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to discover chains: {str(e)}")


@app.get("/chains/{chain_name}")
async def get_chain_details(chain_name: str):
    """
    Get detailed information about a specific chain

    Returns chain structure, execution plan, and parallel groups
    """
    try:
        # Load chain
        chain_path = Path("chains") / f"{chain_name}.yaml"
        if not chain_path.exists():
            raise HTTPException(status_code=404, detail=f"Chain '{chain_name}' not found")

        chain = load_chain(chain_path)
        graph = create_execution_graph(chain)

        return {
            "name": chain.name,
            "description": chain.description,
            "steps": [
                {
                    "id": step.id,
                    "workflow": step.workflow,
                    "description": step.description,
                    "depends_on": step.depends_on,
                    "condition": step.condition,
                    "parameters": step.parameters
                }
                for step in chain.steps
            ],
            "execution_plan": {
                "total_levels": graph.get_total_levels(),
                "parallel_groups": graph.get_level_groups(),
                "total_steps": len(graph.nodes)
            },
            "metadata": chain.metadata
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load chain: {str(e)}")


class ChainExecutionRequest(BaseModel):
    """Request to execute a chain"""
    parameters: Dict[str, Any] = {}


class ChainRegenerationRequest(BaseModel):
    """Request to regenerate chain from a specific step"""
    from_step: str
    new_parameters: Dict[str, Any] = {}
    use_version: Optional[int] = None  # None = use latest


@app.post("/chains/{chain_name}/execute")
async def execute_chain(chain_name: str, request: ChainExecutionRequest):
    """
    Execute a workflow chain

    Returns workflow_id for tracking the chain execution
    """
    try:
        # Load chain
        chain_path = Path("chains") / f"{chain_name}.yaml"
        if not chain_path.exists():
            raise HTTPException(status_code=404, detail=f"Chain '{chain_name}' not found")

        chain = load_chain(chain_path)
        graph = create_execution_graph(chain)

        # Execute via chain engine
        workflow_id = await chain_engine.execute_chain(
            graph=graph,
            initial_parameters=request.parameters
        )

        # Get execution levels for response
        levels = graph.get_execution_levels()
        total_steps = len(graph.nodes)

        return {
            "workflow_id": workflow_id,
            "chain_name": chain.name,
            "status": "started",
            "total_steps": total_steps,
            "parallel_groups": [[step_id for step_id in level] for level in levels],
            "message": f"Chain execution started. Use /chains/status/{workflow_id} to check progress."
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start chain: {str(e)}")


@app.get("/chains/status/{workflow_id}")
async def get_chain_status(workflow_id: str):
    """
    Get current status of a running chain

    Returns current level, completed steps, and step statuses
    """
    try:
        status = await chain_engine.get_chain_status(workflow_id)
        return status

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get chain status: {str(e)}")


@app.get("/chains/result/{workflow_id}")
async def get_chain_result(workflow_id: str):
    """
    Wait for chain to complete and get final result

    Returns ChainExecutionResult with all step results
    """
    try:
        result = await chain_engine.get_chain_result(workflow_id)
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


@app.post("/chains/{chain_name}/regenerate")
async def regenerate_chain(chain_name: str, request: ChainRegenerationRequest):
    """
    Regenerate chain from a specific step with new parameters

    This creates a new chain version that:
    - Caches results from previous executions
    - Re-executes from the specified step with new parameters
    - Continues through all descendant steps

    Args:
        chain_name: Name of the chain
        request: Regeneration request with from_step and new parameters

    Returns:
        New workflow_id and version info
    """
    try:
        # Load chain definition
        chain_path = Path("chains") / f"{chain_name}.yaml"
        if not chain_path.exists():
            raise HTTPException(status_code=404, detail=f"Chain '{chain_name}' not found")

        chain = load_chain(chain_path)
        graph = create_execution_graph(chain)

        # Execute via chain engine with regeneration
        workflow_id = await chain_engine.regenerate_chain(
            chain_name=chain_name,
            graph=graph,
            from_step=request.from_step,
            new_parameters=request.new_parameters,
            use_version=request.use_version
        )

        return {
            "workflow_id": workflow_id,
            "chain_name": chain_name,
            "status": "started",
            "regeneration_from_step": request.from_step,
            "message": f"Chain regeneration started from step '{request.from_step}'. Use /chains/status/{workflow_id} to check progress."
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start chain regeneration: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001, log_level="info")
