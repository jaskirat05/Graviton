"""
CRUD operations for Artifact model
"""

import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc

from ..models import Artifact
from .workflow import get_workflow


def create_artifact(
    session: Session,
    workflow_id: str,
    filename: str,
    local_filename: str,
    local_path: str,
    file_type: str,
    file_format: Optional[str] = None,
    file_size: Optional[int] = None,
    node_id: Optional[str] = None,
    subfolder: str = "",
    comfy_folder_type: str = "output",
    version: int = 1,
    is_latest: bool = True,
    parent_artifact_id: Optional[str] = None,
    approval_status: str = "auto_approved",
    extra_metadata: Optional[Dict[str, Any]] = None,
) -> Artifact:
    """Create a new artifact record"""
    artifact = Artifact(
        id=str(uuid.uuid4()),
        workflow_id=workflow_id,
        filename=filename,
        local_filename=local_filename,
        local_path=local_path,
        file_type=file_type,
        file_format=file_format,
        file_size=file_size,
        node_id=node_id,
        subfolder=subfolder,
        comfy_folder_type=comfy_folder_type,
        version=version,
        is_latest=is_latest,
        parent_artifact_id=parent_artifact_id,
        approval_status=approval_status,
        extra_metadata=extra_metadata,
    )
    session.add(artifact)

    # If this is the latest, update workflow's latest_artifact_id
    if is_latest:
        # First, set all other artifacts for this workflow to is_latest=False
        session.query(Artifact).filter(
            and_(Artifact.workflow_id == workflow_id, Artifact.id != artifact.id)
        ).update({"is_latest": False})

        # Update workflow's latest_artifact_id
        workflow = get_workflow(session, workflow_id)
        if workflow:
            workflow.latest_artifact_id = artifact.id

    session.commit()
    session.refresh(artifact)
    return artifact


def get_artifact(session: Session, artifact_id: str) -> Optional[Artifact]:
    """Get artifact by ID"""
    return session.query(Artifact).filter(Artifact.id == artifact_id).first()


def get_latest_artifact(session: Session, workflow_id: str) -> Optional[Artifact]:
    """Get latest artifact for a workflow"""
    return session.query(Artifact).filter(
        and_(Artifact.workflow_id == workflow_id, Artifact.is_latest == True)
    ).first()


def get_artifacts_by_workflow(
    session: Session,
    workflow_id: str,
    include_old_versions: bool = False,
) -> List[Artifact]:
    """Get all artifacts for a workflow"""
    query = session.query(Artifact).filter(Artifact.workflow_id == workflow_id)
    if not include_old_versions:
        query = query.filter(Artifact.is_latest == True)
    return query.order_by(desc(Artifact.version)).all()


def get_artifact_versions(session: Session, artifact_id: str) -> List[Artifact]:
    """Get all versions of an artifact (including parent versions)"""
    artifact = get_artifact(session, artifact_id)
    if not artifact:
        return []

    versions = [artifact]
    current = artifact

    # Walk back through parent chain
    while current.parent_artifact_id:
        parent = get_artifact(session, current.parent_artifact_id)
        if not parent:
            break
        versions.append(parent)
        current = parent

    return sorted(versions, key=lambda a: a.version, reverse=True)


def update_artifact_latest_flag(
    session: Session,
    artifact_id: str,
    is_latest: bool = True,
) -> Optional[Artifact]:
    """Update artifact's is_latest flag"""
    artifact = get_artifact(session, artifact_id)
    if not artifact:
        return None

    if is_latest:
        # Set all other artifacts for this workflow to is_latest=False
        session.query(Artifact).filter(
            and_(
                Artifact.workflow_id == artifact.workflow_id,
                Artifact.id != artifact_id
            )
        ).update({"is_latest": False})

        # Import here to avoid circular dependency
        from .workflow import update_workflow_latest_artifact
        update_workflow_latest_artifact(session, artifact.workflow_id, artifact_id)

    artifact.is_latest = is_latest
    session.commit()
    session.refresh(artifact)
    return artifact


def approve_artifact(
    session: Session,
    artifact_id: str,
    approved_by: str,
) -> Optional[Artifact]:
    """Approve an artifact"""
    artifact = get_artifact(session, artifact_id)
    if not artifact:
        return None

    artifact.approval_status = "approved"
    artifact.approved_by = approved_by
    artifact.approved_at = datetime.utcnow()

    session.commit()
    session.refresh(artifact)
    return artifact


def reject_artifact(
    session: Session,
    artifact_id: str,
    rejected_by: str,
    reason: Optional[str] = None,
) -> Optional[Artifact]:
    """Reject an artifact"""
    artifact = get_artifact(session, artifact_id)
    if not artifact:
        return None

    artifact.approval_status = "rejected"
    artifact.approved_by = rejected_by
    artifact.approved_at = datetime.utcnow()
    artifact.rejection_reason = reason

    session.commit()
    session.refresh(artifact)
    return artifact


def list_artifacts(
    session: Session,
    limit: int = 100,
    offset: int = 0,
    workflow_id: Optional[str] = None,
    approval_status: Optional[str] = None,
    is_latest: Optional[bool] = None,
) -> List[Artifact]:
    """List artifacts with optional filtering"""
    query = session.query(Artifact)
    if workflow_id:
        query = query.filter(Artifact.workflow_id == workflow_id)
    if approval_status:
        query = query.filter(Artifact.approval_status == approval_status)
    if is_latest is not None:
        query = query.filter(Artifact.is_latest == is_latest)
    return query.order_by(desc(Artifact.created_at)).limit(limit).offset(offset).all()


def delete_artifact(session: Session, artifact_id: str) -> bool:
    """Delete an artifact"""
    artifact = get_artifact(session, artifact_id)
    if not artifact:
        return False

    session.delete(artifact)
    session.commit()
    return True
