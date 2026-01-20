"""
Request Models

Pydantic models for API requests.
"""

from typing import Dict, Any, Optional
from pydantic import BaseModel, Field


class ComfyUIServer(BaseModel):
    """ComfyUI server configuration"""
    name: str = Field(..., description="Friendly name for this server")
    address: str = Field(..., description="Server address (e.g., '127.0.0.1:8188')")
    description: Optional[str] = Field(None, description="Optional description")


class QueuePromptRequest(BaseModel):
    """Request to queue a prompt"""
    workflow: Dict[str, Any] = Field(..., description="Workflow definition in API format")
    server_address: str = Field(..., description="ComfyUI server address")


class DownloadImageRequest(BaseModel):
    """Request to download an image"""
    filename: str
    server_address: str
    subfolder: str = ""
    image_type: str = "output"


class ExecuteWorkflowRequest(BaseModel):
    """Request to execute a workflow with automatic server selection"""
    workflow: Dict[str, Any] = Field(..., description="Workflow definition in API format")
    wait_for_completion: bool = Field(True, description="Wait for completion before returning")
    strategy: str = Field("least_loaded", description="Server selection strategy")
