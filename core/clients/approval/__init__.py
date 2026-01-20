"""
Approval Client Module

Handles approval requests for artifacts with parameter validation.
"""

from .routes import router, initialize_approval_service
from .service import ApprovalService, ApprovalParameterValidator, get_approval_service
from .models import RejectRequest, ApproveRequest

__all__ = [
    'router',
    'initialize_approval_service',
    'ApprovalService',
    'ApprovalParameterValidator',
    'get_approval_service',
    'RejectRequest',
    'ApproveRequest',
]
