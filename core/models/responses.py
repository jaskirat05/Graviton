"""
Response Models

Pydantic models for API responses.
"""

from typing import Optional, List
from pydantic import BaseModel


class PromptResponse(BaseModel):
    """Response from queuing a prompt"""
    prompt_id: str
    server_address: str
    number: int
    queued_at: str


class WorkflowExecutionResponse(BaseModel):
    """Response from workflow execution"""
    job_id: str
    status: str
    server_address: str
    prompt_id: Optional[str] = None
    images: List[str] = []
    queued_at: str
    completed_at: Optional[str] = None
    log_file_path: Optional[str] = None
