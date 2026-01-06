"""
CRUD operations for ApprovalRequest model
"""

import uuid
import secrets
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import desc, and_

from ..models import ApprovalRequest


def create_approval_request(
    session: Session,
    artifact_id: str,
    temporal_workflow_id: str,
    artifact_view_url: str,
    chain_id: Optional[str] = None,
    step_id: Optional[str] = None,
    temporal_run_id: Optional[str] = None,
    link_expiration_hours: Optional[int] = None,
    config_metadata: Optional[Dict[str, Any]] = None,
) -> ApprovalRequest:
    """
    Create a new approval request (idempotent - returns existing if already created)

    Args:
        session: Database session
        artifact_id: ID of artifact to approve
        temporal_workflow_id: Temporal workflow ID to signal when decision is made
        artifact_view_url: URL where approvers can view the artifact
        chain_id: Optional chain context
        step_id: Optional step identifier in chain
        temporal_run_id: Optional Temporal run ID
        link_expiration_hours: Optional hours until approval link expires
        config_metadata: Additional configuration for external systems

    Returns:
        Created or existing ApprovalRequest
    """
    # Check if approval request already exists for this artifact (idempotent for retries)
    # Each step produces a unique artifact, so use artifact_id as the key
    existing = session.query(ApprovalRequest).filter(
        ApprovalRequest.artifact_id == artifact_id
    ).first()

    if existing:
        return existing

    # Generate secure token for approval link
    approval_link_token = secrets.token_urlsafe(32)

    # Calculate link expiration if specified
    link_expires_at = None
    if link_expiration_hours:
        link_expires_at = datetime.utcnow() + timedelta(hours=link_expiration_hours)

    request = ApprovalRequest(
        id=str(uuid.uuid4()),
        artifact_id=artifact_id,
        chain_id=chain_id,
        step_id=step_id,
        temporal_workflow_id=temporal_workflow_id,
        temporal_run_id=temporal_run_id,
        approval_link_token=approval_link_token,
        artifact_view_url=artifact_view_url,
        link_expires_at=link_expires_at,
        config_metadata=config_metadata or {},
    )

    session.add(request)
    session.commit()
    session.refresh(request)
    return request


def get_approval_request(session: Session, request_id: str) -> Optional[ApprovalRequest]:
    """Get approval request by ID"""
    return session.query(ApprovalRequest).filter(ApprovalRequest.id == request_id).first()


def get_approval_request_by_token(session: Session, token: str) -> Optional[ApprovalRequest]:
    """Get approval request by link token"""
    return session.query(ApprovalRequest).filter(
        ApprovalRequest.approval_link_token == token
    ).first()


def get_approval_request_by_artifact(
    session: Session,
    artifact_id: str,
    status: Optional[str] = None,
) -> Optional[ApprovalRequest]:
    """Get approval request for an artifact (latest if multiple)"""
    query = session.query(ApprovalRequest).filter(
        ApprovalRequest.artifact_id == artifact_id
    )
    if status:
        query = query.filter(ApprovalRequest.status == status)
    return query.order_by(desc(ApprovalRequest.created_at)).first()


def get_approval_requests_by_chain(
    session: Session,
    chain_id: str,
    status: Optional[str] = None,
) -> List[ApprovalRequest]:
    """Get all approval requests for a chain"""
    query = session.query(ApprovalRequest).filter(ApprovalRequest.chain_id == chain_id)
    if status:
        query = query.filter(ApprovalRequest.status == status)
    return query.order_by(desc(ApprovalRequest.created_at)).all()


def approve_approval_request(
    session: Session,
    request_id: str,
    decided_by: Optional[str] = None,
) -> Optional[ApprovalRequest]:
    """
    Mark an approval request as approved

    Args:
        session: Database session
        request_id: ID of approval request
        decided_by: Optional identifier of who approved

    Returns:
        Updated ApprovalRequest or None if not found
    """
    request = get_approval_request(session, request_id)
    if not request:
        return None

    if request.status != "pending":
        # Already decided
        return request

    request.status = "approved"
    request.decided_at = datetime.utcnow()
    if decided_by:
        request.decided_by = decided_by

    session.commit()
    session.refresh(request)
    return request


def reject_approval_request(
    session: Session,
    request_id: str,
    decided_by: Optional[str] = None,
) -> Optional[ApprovalRequest]:
    """
    Mark an approval request as rejected

    Args:
        session: Database session
        request_id: ID of approval request
        decided_by: Optional identifier of who rejected

    Returns:
        Updated ApprovalRequest or None if not found
    """
    request = get_approval_request(session, request_id)
    if not request:
        return None

    if request.status != "pending":
        # Already decided
        return request

    request.status = "rejected"
    request.decided_at = datetime.utcnow()
    if decided_by:
        request.decided_by = decided_by

    session.commit()
    session.refresh(request)
    return request


def cancel_approval_request(
    session: Session,
    request_id: str,
) -> Optional[ApprovalRequest]:
    """Cancel an approval request"""
    request = get_approval_request(session, request_id)
    if not request:
        return None

    if request.status != "pending":
        # Already decided
        return request

    request.status = "cancelled"
    request.decided_at = datetime.utcnow()

    session.commit()
    session.refresh(request)
    return request


def list_approval_requests(
    session: Session,
    limit: int = 100,
    offset: int = 0,
    status: Optional[str] = None,
    chain_id: Optional[str] = None,
    artifact_id: Optional[str] = None,
) -> List[ApprovalRequest]:
    """
    List approval requests with optional filtering

    Args:
        session: Database session
        limit: Maximum number of results
        offset: Offset for pagination
        status: Filter by status
        chain_id: Filter by chain
        artifact_id: Filter by artifact

    Returns:
        List of ApprovalRequest objects
    """
    query = session.query(ApprovalRequest)

    if status:
        query = query.filter(ApprovalRequest.status == status)
    if chain_id:
        query = query.filter(ApprovalRequest.chain_id == chain_id)
    if artifact_id:
        query = query.filter(ApprovalRequest.artifact_id == artifact_id)

    return query.order_by(desc(ApprovalRequest.created_at)).limit(limit).offset(offset).all()


def get_pending_approval_requests(
    session: Session,
    limit: int = 100,
) -> List[ApprovalRequest]:
    """Get all pending approval requests"""
    return session.query(ApprovalRequest).filter(
        ApprovalRequest.status == "pending"
    ).order_by(desc(ApprovalRequest.created_at)).limit(limit).all()


def delete_approval_request(session: Session, request_id: str) -> bool:
    """Delete an approval request"""
    request = get_approval_request(session, request_id)
    if not request:
        return False

    session.delete(request)
    session.commit()
    return True


def validate_approval_link(
    session: Session,
    token: str,
) -> tuple[bool, Optional[str]]:
    """
    Validate an approval link token

    Args:
        session: Database session
        token: Approval link token

    Returns:
        Tuple of (is_valid, error_message)
    """
    request = get_approval_request_by_token(session, token)

    if not request:
        return False, "Invalid approval link"

    if request.status != "pending":
        return False, f"Approval request is already {request.status}"

    if request.link_expires_at and request.link_expires_at < datetime.utcnow():
        return False, "Approval link has expired"

    return True, None
