"""
Server Models

Data classes for server status and connection information.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class ServerStatus:
    """Status information from a server health check"""

    healthy: bool
    queue_depth: int = 0
    gpu_memory_used: float = 0.0
    gpu_memory_total: float = 0.0
    last_check: Optional[datetime] = None
    error: Optional[str] = None

    @property
    def gpu_memory_percent(self) -> float:
        """GPU memory usage as percentage"""
        if self.gpu_memory_total == 0:
            return 0.0
        return (self.gpu_memory_used / self.gpu_memory_total) * 100


@dataclass
class ServerInfo:
    """Connection information for a server"""

    name: str
    provider_type: str
    http_url: str
    ws_url: str
