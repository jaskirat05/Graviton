"""
Approval Request/Response Models
"""

from typing import Dict, Any, Optional
from pydantic import BaseModel, Field


class RejectRequest(BaseModel):
    """Request body for rejecting an artifact"""
    decided_by: str = Field(..., description="Identifier of who is rejecting")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="New parameters for regeneration")
    rejection_comment: Optional[str] = Field(None, description="Optional comment explaining rejection")


class ApproveRequest(BaseModel):
    """Request body for approving an artifact"""
    decided_by: str = Field(..., description="Identifier of who is approving")
