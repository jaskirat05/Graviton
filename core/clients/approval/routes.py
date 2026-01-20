"""
Approval API Routes

Handles approval requests for artifacts with parameter validation.
"""

import logging
from fastapi import APIRouter, HTTPException
from temporalio.client import Client

from .service import get_approval_service, ApprovalService
from .models import RejectRequest, ApproveRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/approval", tags=["approval"])


# Routes
@router.get("/pending")
async def get_pending_approvals():
    """
    Get all pending approval requests

    Returns a list of pending approval requests with basic info

    Example:
        GET /approval/pending
    """
    try:
        from ...database import get_session
        from ...database.crud.approval import get_pending_approval_requests

        with get_session() as session:
            pending_requests = get_pending_approval_requests(session, limit=100)

            return [
                {
                    "id": req.id,
                    "approval_link_token": req.approval_link_token,
                    "artifact_id": req.artifact_id,
                    "artifact_view_url": req.artifact_view_url,
                    "step_id": req.step_id,
                    "chain_id": req.chain_id,
                    "created_at": req.created_at.isoformat() if req.created_at else None,
                    "link_expires_at": req.link_expires_at.isoformat() if req.link_expires_at else None,
                }
                for req in pending_requests
            ]
    except Exception as e:
        logger.error(f"Error getting pending approvals: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/{token}")
async def get_approval_request(token: str):
    """
    Get approval request details

    Returns:
    - Artifact information (filename, type, view URL)
    - Generation parameters used
    - Link to get editable parameters

    Example:
        GET /approval/abc123token
    """
    try:
        service = get_approval_service()
        if service is None:
            logger.error("Approval service not initialized!")
            raise HTTPException(status_code=500, detail="Approval service not initialized")
        details = await service.get_approval_details(token)
        return details
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting approval details: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/{token}/parameters")
async def get_approval_parameters(token: str):
    """
    Get editable parameters from workflow registry

    Returns parameter schema with:
    - Current parameters used for generation
    - All editable parameters (from workflow override file)
    - Parameter metadata (type, description, category, etc.)

    Example:
        GET /approval/abc123token/parameters
    """
    try:
        service = get_approval_service()
        parameters = await service.get_editable_parameters(token)
        return parameters
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting approval parameters: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/{token}/approve")
async def approve_artifact(token: str, request: ApproveRequest):
    """
    Approve an artifact

    This will:
    1. Validate the approval link
    2. Update approval request status to 'approved'
    3. Send signal to Temporal workflow to continue

    Example:
        POST /approval/abc123token/approve
        {
            "decided_by": "user@example.com"
        }
    """
    try:
        service = get_approval_service()
        if service is None:
            logger.error("Approval service not initialized!")
            raise HTTPException(status_code=500, detail="Approval service not initialized")
        if service.temporal_client is None:
            logger.error("Approval service has no Temporal client!")
            raise HTTPException(status_code=500, detail="Approval service missing Temporal client")
        logger.info(f"Approving token {token[:16]}... with service that has client: {service.temporal_client is not None}")
        result = await service.approve(token, request.decided_by)
        logger.info(f"Approve result: {result}")
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error approving artifact: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/{token}/reject")
async def reject_artifact(token: str, request: RejectRequest):
    """
    Reject an artifact and regenerate with new parameters

    This will:
    1. Validate the approval link
    2. Validate provided parameters against workflow registry
    3. Update approval request status to 'rejected'
    4. Send signal to Temporal workflow with new parameters
    5. Workflow will regenerate with provided parameters

    Parameters must be editable (present in workflow override file).
    Use GET /{token}/parameters to get list of editable parameters.

    Example:
        POST /approval/abc123token/reject
        {
            "decided_by": "user@example.com",
            "parameters": {
                "93.text": "A darker, more dramatic landscape",
                "3.seed": 42,
                "3.steps": 30
            },
            "rejection_comment": "Please make it more dramatic"
        }
    """
    try:
        service = get_approval_service()
        result = await service.reject(
            token,
            request.decided_by,
            request.parameters,
            request.rejection_comment
        )
        return result
    except ValueError as e:
        # Could be validation errors dict or simple string
        if isinstance(e.args[0], dict):
            raise HTTPException(status_code=400, detail=e.args[0])
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error rejecting artifact: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


# Initialize service with Temporal client
def initialize_approval_service(temporal_client: Client):
    """
    Initialize approval service with Temporal client

    Call this during app startup to configure Temporal client
    for sending workflow signals.

    Args:
        temporal_client: Connected Temporal client
    """
    from . import service

    service._approval_service = ApprovalService(temporal_client=temporal_client)
    logger.info("Approval service initialized with Temporal client")
