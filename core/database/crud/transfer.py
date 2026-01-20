"""
CRUD operations for ArtifactTransfer model
"""

import uuid
from datetime import datetime
from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import desc

from ..models import ArtifactTransfer


def create_transfer(
    session: Session,
    artifact_id: str,
    source_workflow_id: str,
    target_server: str,
    status: str = "pending",
    target_workflow_id: Optional[str] = None,
    target_subfolder: str = "",
) -> ArtifactTransfer:
    """Create a new artifact transfer record"""
    transfer = ArtifactTransfer(
        id=str(uuid.uuid4()),
        artifact_id=artifact_id,
        source_workflow_id=source_workflow_id,
        target_workflow_id=target_workflow_id,
        target_server=target_server,
        target_subfolder=target_subfolder,
        status=status,
    )
    session.add(transfer)
    session.commit()
    session.refresh(transfer)
    return transfer


def get_transfer(session: Session, transfer_id: str) -> Optional[ArtifactTransfer]:
    """Get transfer by ID"""
    return session.query(ArtifactTransfer).filter(ArtifactTransfer.id == transfer_id).first()


def update_transfer_status(
    session: Session,
    transfer_id: str,
    status: str,
    error_message: Optional[str] = None,
) -> Optional[ArtifactTransfer]:
    """Update transfer status"""
    transfer = get_transfer(session, transfer_id)
    if not transfer:
        return None

    transfer.status = status
    if status == "completed":
        transfer.uploaded_at = datetime.utcnow()
    if error_message:
        transfer.error_message = error_message

    session.commit()
    session.refresh(transfer)
    return transfer


def list_transfers(
    session: Session,
    limit: int = 100,
    offset: int = 0,
    artifact_id: Optional[str] = None,
    status: Optional[str] = None,
) -> List[ArtifactTransfer]:
    """List transfers with optional filtering"""
    query = session.query(ArtifactTransfer)
    if artifact_id:
        query = query.filter(ArtifactTransfer.artifact_id == artifact_id)
    if status:
        query = query.filter(ArtifactTransfer.status == status)
    return query.order_by(desc(ArtifactTransfer.created_at)).limit(limit).offset(offset).all()


def delete_transfer(session: Session, transfer_id: str) -> bool:
    """Delete a transfer record"""
    transfer = get_transfer(session, transfer_id)
    if not transfer:
        return False

    session.delete(transfer)
    session.commit()
    return True
