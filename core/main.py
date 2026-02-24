"""
Temporal-based FastAPI Gateway for ComfyUI

This gateway uses Temporal for durable workflow execution.
"""

import asyncio
import os
import uuid
import sys
from pathlib import Path
from typing import Dict, Any, Optional

import json
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from temporalio.client import Client

# Add parent to path
sys.path.append(str(Path(__file__).parent.parent))

from core.executors import ComfyUIWorkflow, WorkflowExecutionRequest, ChainExecutorWorkflow
from core.registry_service.main import app as registry_service_app
from core.registry_service.main import startup as registry_startup
from core.registry_service.main import shutdown as registry_shutdown
from core.registry_service.env import load_root_env
from core.logging_config import setup_logging, get_logger
from core.chains import (
    load_chain_from_dict,
    create_execution_graph,
    ChainEngine
)
from core.chains.hashing import calculate_definition_hash
from core.database.session import get_session
from core.database import init_db
from core.database.crud.chain import get_chain_by_hash, get_chains_by_hash, get_chain, list_chains, delete_chain
from core.clients.approval import router as approval_router, initialize_approval_service
from core.services.broadcast import get_broadcast, connect_broadcast, disconnect_broadcast
from core.observability.chain_logger import ChainLogger
from core.artifact_service import ArtifactService


def _get_allowed_cors_origins() -> list[str]:
    """Return allowed CORS origins from env, with safe local dev defaults."""
    raw = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000,http://0.0.0.0:3000",
    )
    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
    return origins or ["http://localhost:3000"]


app = FastAPI(title="Graviton Temporal Gateway", version="2.0.0")

# CORS middleware for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=_get_allowed_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(approval_router)
app.mount("/api/registry", registry_service_app)

# Temporal client (will be initialized on startup)
temporal_client: Client = None

# Chain engine (will be initialized on startup)
chain_engine: ChainEngine = None

# Registry sub-app startup guard
registry_initialized: bool = False

# Load root .env without overriding already-set process env vars.
load_root_env()
artifact_service = ArtifactService()


@app.on_event("startup")
async def startup():
    """Connect to Temporal Server and initialize workflow registry on startup"""
    global temporal_client, chain_engine, registry_initialized

    # Setup colored logging with file output
    log_dir = Path(__file__).parent / "logs"
    logger, log_file = setup_logging(log_dir=log_dir, log_level="INFO")

    # Connect to Temporal
    from core.config import get_temporal_address
    temporal_address = get_temporal_address()
    logger.info("Connecting to Temporal", address=temporal_address)
    temporal_client = await Client.connect(temporal_address)

    # Ensure DB tables exist.
    init_db()

    # Initialize chain engine
    chain_engine = ChainEngine(temporal_client)

    # Initialize approval service with temporal client
    initialize_approval_service(temporal_client)

    # Connect to Redis for pub/sub
    await connect_broadcast()

    # Explicitly initialize mounted registry sub-app resources.
    # Mounted app startup events are not guaranteed in all run modes.
    if not registry_initialized:
        await registry_startup()
        registry_initialized = True

    logger.info("=" * 60)
    logger.info("🚀 Temporal Gateway Started")
    logger.info("=" * 60)
    logger.info("Connected to Temporal", host="localhost:7233")
    logger.info("Gateway API", url="http://localhost:8001")
    logger.info("Temporal UI", url="http://localhost:8233")
    logger.info("Registry service mounted", path="/api/registry")
    if log_file:
        logger.info("Log file", path=str(log_file))
    logger.info("=" * 60)


@app.on_event("shutdown")
async def shutdown():
    """Cleanup on shutdown"""
    global registry_initialized
    await disconnect_broadcast()
    if registry_initialized:
        await registry_shutdown()
        registry_initialized = False
    if temporal_client:
        await temporal_client.close()


class ArtifactRefRequest(BaseModel):
    asset_ref: Dict[str, Any] | str


class ArtifactDownloadUrlRequest(BaseModel):
    asset_ref: Dict[str, Any] | str
    expires_in: int = Field(default=3600, ge=60, le=86400)


@app.get("/artifact-service/artifacts/{artifact_id}/download")
async def artifact_service_download_artifact(artifact_id: str):
    from core.database.crud.artifact import get_artifact

    with get_session() as session:
        artifact = get_artifact(session, artifact_id)
        if not artifact:
            raise HTTPException(status_code=404, detail="Artifact not found")

        metadata = artifact.extra_metadata if isinstance(artifact.extra_metadata, dict) else None
        asset_ref = metadata.get("asset_ref") if isinstance(metadata, dict) else None
        if not isinstance(asset_ref, dict):
            raise HTTPException(status_code=404, detail="Artifact has no asset_ref metadata")

    try:
        download_url = artifact_service.get_download_url(asset_ref=asset_ref, expires_in=3600)
        return RedirectResponse(url=download_url, status_code=307)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Artifact redirect failed: {error}") from error


@app.post("/artifact-service/create")
async def artifact_service_create(
    provider: str = Form(...),
    kind: str = Form("file"),
    metadata_json: str = Form(""),
    file: UploadFile = File(...),
):
    try:
        payload = await file.read()
        if not payload:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")
        metadata: Dict[str, Any] | None = None
        if metadata_json.strip():
            parsed = json.loads(metadata_json)
            if not isinstance(parsed, dict):
                raise HTTPException(status_code=400, detail="metadata_json must be a JSON object")
            metadata = parsed

        asset_ref = artifact_service.create(
            provider=provider.strip().lower(),
            payload=payload,
            filename=file.filename or "upload.bin",
            kind=kind.strip() or "file",
            mime_type=file.content_type,
            metadata=metadata,
        )
        return {"asset_ref": asset_ref}
    except HTTPException:
        raise
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Artifact create failed: {error}") from error


@app.post("/artifact-service/read")
async def artifact_service_read(request: ArtifactRefRequest):
    try:
        asset_ref = artifact_service.read(asset_ref=request.asset_ref)
        return {"asset_ref": asset_ref}
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Artifact read failed: {error}") from error


@app.post("/artifact-service/download-url")
async def artifact_service_download_url(request: ArtifactDownloadUrlRequest):
    try:
        url = artifact_service.get_download_url(
            asset_ref=request.asset_ref,
            expires_in=request.expires_in,
        )
        return {"download_url": url}
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Artifact download URL failed: {error}") from error


@app.post("/artifact-service/update")
async def artifact_service_update(
    asset_ref_json: str = Form(...),
    metadata_json: str = Form(""),
    filename: str = Form(""),
    mime_type: str = Form(""),
    file: UploadFile = File(...),
):
    try:
        parsed_asset_ref = json.loads(asset_ref_json)
        if not isinstance(parsed_asset_ref, dict):
            raise HTTPException(status_code=400, detail="asset_ref_json must be a JSON object")
        payload = await file.read()
        if not payload:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")

        metadata: Dict[str, Any] | None = None
        if metadata_json.strip():
            parsed_metadata = json.loads(metadata_json)
            if not isinstance(parsed_metadata, dict):
                raise HTTPException(status_code=400, detail="metadata_json must be a JSON object")
            metadata = parsed_metadata

        updated = artifact_service.update(
            asset_ref=parsed_asset_ref,
            payload=payload,
            filename=filename.strip() or None,
            mime_type=mime_type.strip() or file.content_type or None,
            metadata=metadata,
        )
        return {"asset_ref": updated}
    except HTTPException:
        raise
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Artifact update failed: {error}") from error


@app.post("/artifact-service/delete")
async def artifact_service_delete(request: ArtifactRefRequest):
    try:
        artifact_service.delete(asset_ref=request.asset_ref)
        return {"ok": True}
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Artifact delete failed: {error}") from error


@app.get("/health")
async def health_check():
    """Gateway health check"""
    return {
        "status": "healthy",
        "temporal_connected": temporal_client is not None,
        "version": "2.0.0-temporal"
    }


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
                    "definition_hash": c.definition_hash,
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
            if not artifacts and wf.latest_artifact_id:
                latest = session.query(Artifact).filter(Artifact.id == wf.latest_artifact_id).first()
                if latest:
                    artifacts = [latest]

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
                        "url": f"/artifact-service/artifacts/{a.id}/download",
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
            "definition_hash": chain.definition_hash,
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


@app.post("/chains/abort-all")
async def abort_all_chains():
    """
    Cancel all active chain executions (queued/running) and mark them cancelled.

    Returns:
        Summary of cancelled chains and any per-chain failures.
    """
    from core.database.models import Chain
    from core.database.crud.chain import update_chain_status

    terminal_statuses = {"completed", "failed", "cancelled"}

    with get_session() as session:
        active_chains = (
            session.query(Chain)
            .filter(~Chain.status.in_(terminal_statuses))
            .all()
        )

        targets = [
            {
                "chain_id": chain.id,
                "job_id": chain.job_id,
                "status": chain.status,
            }
            for chain in active_chains
        ]

    results: list[dict[str, Any]] = []
    cancelled_count = 0

    for target in targets:
        chain_id = target["chain_id"]
        job_id = target["job_id"]
        try:
            if job_id:
                abort_mode = await chain_engine.abort_chain(job_id, grace_seconds=5.0)
            else:
                abort_mode = "no_job"

            with get_session() as session:
                update_chain_status(session, chain_id, "cancelled")

            results.append(
                {
                    "chain_id": chain_id,
                    "job_id": job_id,
                    "status": "cancelled",
                    "mode": abort_mode,
                }
            )
            cancelled_count += 1
        except Exception as e:
            results.append(
                {
                    "chain_id": chain_id,
                    "job_id": job_id,
                    "status": "error",
                    "error": str(e),
                }
            )

    return {
        "ok": True,
        "requested_count": len(targets),
        "cancelled_count": cancelled_count,
        "results": results,
    }


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
