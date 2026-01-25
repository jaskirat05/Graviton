"""
Database module for ComfyAutomate Temporal Gateway

Provides SQLAlchemy models and CRUD operations for artifact tracking.
"""

from .models import Chain, Workflow, Artifact, ArtifactTransfer, Base
from .session import get_session, get_session_direct, init_db, engine
from .crud import (
    # Chain
    create_chain,
    get_chain,
    get_chain_by_job_id,
    update_chain_status,
    list_chains,
    delete_chain,
    save_executed_definition,
    # Workflow
    create_workflow,
    get_workflow,
    get_workflow_by_prompt,
    get_workflow_by_step,
    get_workflows_by_chain,
    update_workflow_status,
    update_workflow_latest_artifact,
    list_workflows,
    delete_workflow,
    # Artifact
    create_artifact,
    get_artifact,
    get_latest_artifact,
    get_artifacts_by_workflow,
    get_artifact_versions,
    update_artifact_latest_flag,
    approve_artifact,
    reject_artifact,
    list_artifacts,
    delete_artifact,
    # Transfer
    create_transfer,
    get_transfer,
    update_transfer_status,
    list_transfers,
    delete_transfer,
)

__all__ = [
    # Models
    "Chain",
    "Workflow",
    "Artifact",
    "ArtifactTransfer",
    "Base",
    # Session
    "get_session",
    "get_session_direct",
    "init_db",
    "engine",
    # Chain CRUD
    "create_chain",
    "get_chain",
    "get_chain_by_job_id",
    "update_chain_status",
    "list_chains",
    "delete_chain",
    "save_executed_definition",
    # Workflow CRUD
    "create_workflow",
    "get_workflow",
    "get_workflow_by_prompt",
    "get_workflow_by_step",
    "get_workflows_by_chain",
    "update_workflow_status",
    "update_workflow_latest_artifact",
    "list_workflows",
    "delete_workflow",
    # Artifact CRUD
    "create_artifact",
    "get_artifact",
    "get_latest_artifact",
    "get_artifacts_by_workflow",
    "get_artifact_versions",
    "update_artifact_latest_flag",
    "approve_artifact",
    "reject_artifact",
    "list_artifacts",
    "delete_artifact",
    # Transfer CRUD
    "create_transfer",
    "get_transfer",
    "update_transfer_status",
    "list_transfers",
    "delete_transfer",
]
