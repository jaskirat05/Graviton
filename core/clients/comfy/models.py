"""
ComfyUI Client Data Models
"""

from dataclasses import dataclass
from typing import Optional, Dict, Any, List
from enum import Enum


class ExecutionStatus(str, Enum):
    """Workflow execution status"""
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"
    INTERRUPTED = "interrupted"
    UNKNOWN = "unknown"


@dataclass
class WorkflowResult:
    """Result of a workflow execution"""
    status: ExecutionStatus
    prompt_id: str
    server_address: str
    outputs: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    error_details: Optional[Dict[str, Any]] = None

    @property
    def is_success(self) -> bool:
        return self.status == ExecutionStatus.SUCCESS

    @property
    def is_error(self) -> bool:
        return self.status == ExecutionStatus.ERROR


@dataclass
class ProgressUpdate:
    """Real-time progress update from WebSocket"""
    prompt_id: str
    node_id: Optional[str] = None
    progress: float = 0.0  # 0.0 to 1.0
    current_node: Optional[str] = None
    preview_image: Optional[bytes] = None
