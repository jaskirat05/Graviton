"""
Chain-scoped Logging

Creates per-chain log folders with separate log files for different components:
- worker.log: Temporal worker/workflow execution logs
- comfy_http.log: ComfyUI HTTP API requests/responses
- comfy_ws.log: ComfyUI WebSocket events
- gateway.log: Gateway API logs for this chain
- chain_definition.json: The chain definition being executed
- cached_definition.json: The cached definition compared against (if any)
- cached_steps.json: Steps that were cached/reused

Folder structure:
    logs/chains/{chain_name}/v{version}/
        ├── worker.log
        ├── comfy_http.log
        ├── comfy_ws.log
        ├── gateway.log
        ├── chain_definition.json
        ├── cached_definition.json (optional)
        └── cached_steps.json (optional)

Usage:
    chain_logger = ChainLogger.create("my-pipeline", version=1, chain_id="abc123")
    chain_logger.worker.info("Starting step execution")
    chain_logger.comfy_http.info("POST /prompt - 200 OK")
    chain_logger.save_chain_definition({"name": "my-pipeline", "steps": [...]})
    chain_logger.save_cached_steps({"step1": {...}, "step2": {...}})
"""

import os
import re
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Any, Dict
from contextvars import ContextVar

# Context var to track current chain for automatic log routing
_current_chain_logger: ContextVar[Optional['ChainLogger']] = ContextVar('chain_logger', default=None)


def sanitize_chain_name(name: str) -> str:
    """
    Sanitize chain name for safe filesystem use.

    Prevents path traversal attacks and invalid filesystem characters.
    """
    if not name:
        return "unnamed"

    # Only allow alphanumeric, hyphens, underscores
    sanitized = re.sub(r'[^a-zA-Z0-9_-]', '_', name)

    # Remove leading/trailing underscores and hyphens
    sanitized = sanitized.strip('_-')

    # Prevent directory traversal patterns
    if not sanitized or sanitized in ('.', '..'):
        return "unnamed"

    # Limit length to prevent filesystem issues
    return sanitized[:64]


class ChainLogger:
    """
    Per-chain logging that creates a dedicated log folder with separate files.

    Creates folder structure:
        logs/chains/{sanitized_name}/v{version}/
            ├── worker.log        - Temporal worker logs
            ├── comfy_http.log    - ComfyUI HTTP API logs
            ├── comfy_ws.log      - ComfyUI WebSocket logs
            └── gateway.log       - Gateway API logs
    """

    # Class-level registry of active chain loggers by (name, version)
    _instances: dict[tuple[str, int], 'ChainLogger'] = {}

    def __init__(
        self,
        chain_name: str,
        version: int,
        chain_id: str,
        base_log_dir: Path = None,
    ):
        """
        Initialize chain logger.

        Args:
            chain_name: Chain name (will be sanitized)
            version: Chain version number
            chain_id: Chain UUID (for reference in logs)
            base_log_dir: Base directory for logs (default: core/logs/chains)
        """
        self.chain_name = chain_name
        self.version = version
        self.chain_id = chain_id
        self._sanitized_name = sanitize_chain_name(chain_name)

        # Determine base log directory
        if base_log_dir is None:
            base_log_dir = Path(__file__).parent.parent / "logs" / "chains"

        # Create chain-specific folder: {name}/v{version}/
        self.log_dir = base_log_dir / self._sanitized_name / f"v{version}"
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Set restrictive permissions on the directory (owner read/write/execute, group read/execute)
        try:
            os.chmod(self.log_dir, 0o750)
        except OSError:
            pass  # May fail on some systems, not critical

        # Create dedicated loggers with file handlers
        self.worker = self._create_logger("worker", "worker.log")
        self.comfy_http = self._create_logger("comfy_http", "comfy_http.log")
        self.comfy_ws = self._create_logger("comfy_ws", "comfy_ws.log")
        self.gateway = self._create_logger("gateway", "gateway.log")

        # Register this instance
        key = (self._sanitized_name, version)
        ChainLogger._instances[key] = self

        # Log initialization
        self.worker.info(f"=== Chain Logger Initialized ===")
        self.worker.info(f"Chain: {chain_name} (v{version})")
        self.worker.info(f"Chain ID: {chain_id}")
        self.worker.info(f"Log directory: {self.log_dir}")

    def _create_logger(self, name: str, filename: str) -> logging.Logger:
        """Create a logger with a file handler for this chain."""
        # Unique logger name to avoid conflicts
        logger_name = f"chain.{self._sanitized_name}.v{self.version}.{name}"
        logger = logging.getLogger(logger_name)
        logger.setLevel(logging.DEBUG)

        # Remove any existing handlers to avoid duplicates
        logger.handlers.clear()

        # Create file handler
        log_file = self.log_dir / filename
        handler = logging.FileHandler(log_file)
        handler.setLevel(logging.DEBUG)

        # Set restrictive permissions on log file (owner read/write, group read)
        try:
            os.chmod(log_file, 0o640)
        except OSError:
            pass  # May fail on some systems

        # Format with timestamp, level, and message
        formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

        # Don't propagate to root logger (avoid duplicate logs)
        logger.propagate = False

        return logger

    def _save_json(self, filename: str, data: Any, description: str):
        """Save data as JSON file with metadata."""
        file_path = self.log_dir / filename
        output = {
            "_metadata": {
                "chain_name": self.chain_name,
                "chain_id": self.chain_id,
                "version": self.version,
                "saved_at": datetime.utcnow().isoformat(),
                "description": description,
            },
            "data": data,
        }
        with open(file_path, 'w') as f:
            json.dump(output, f, indent=2, default=str)

        # Set restrictive permissions
        try:
            os.chmod(file_path, 0o640)
        except OSError:
            pass

        self.worker.info(f"Saved {filename}")

    def save_chain_definition(self, definition: Dict[str, Any]):
        """
        Save the chain definition being executed.

        Args:
            definition: The chain definition (from YAML)
        """
        self._save_json(
            "chain_definition.json",
            definition,
            "Chain definition being executed"
        )

    def save_cached_definition(self, definition: Dict[str, Any]):
        """
        Save the cached definition that was compared against.

        Args:
            definition: The previously cached chain definition
        """
        self._save_json(
            "cached_definition.json",
            definition,
            "Cached chain definition (compared against current)"
        )

    def save_cached_steps(self, cached_steps: Dict[str, Any]):
        """
        Save information about which steps were cached/reused.

        Args:
            cached_steps: Dict mapping step_id to cached result info
        """
        self._save_json(
            "cached_steps.json",
            cached_steps,
            "Steps that were cached and reused from previous execution"
        )

    def save_step_result(self, step_id: str, result: Dict[str, Any]):
        """
        Save individual step result (for debugging).

        Args:
            step_id: The step identifier
            result: The step execution result
        """
        # Append to a step_results.jsonl file (one JSON per line)
        file_path = self.log_dir / "step_results.jsonl"
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "step_id": step_id,
            "result": result,
        }
        with open(file_path, 'a') as f:
            f.write(json.dumps(entry, default=str) + "\n")

    def close(self):
        """Close all log handlers."""
        for logger in [self.worker, self.comfy_http, self.comfy_ws, self.gateway]:
            for handler in logger.handlers:
                handler.close()
            logger.handlers.clear()

        # Unregister
        key = (self._sanitized_name, self.version)
        if key in ChainLogger._instances:
            del ChainLogger._instances[key]

    @classmethod
    def create(
        cls,
        chain_name: str,
        version: int,
        chain_id: str,
        base_log_dir: Path = None,
    ) -> 'ChainLogger':
        """
        Create a new chain logger.

        Args:
            chain_name: Chain name (will be sanitized)
            version: Chain version number
            chain_id: Chain UUID
            base_log_dir: Optional custom log directory

        Returns:
            ChainLogger instance
        """
        return cls(chain_name, version, chain_id, base_log_dir)

    @classmethod
    def get(cls, chain_name: str, version: int) -> Optional['ChainLogger']:
        """Get existing chain logger by name and version."""
        key = (sanitize_chain_name(chain_name), version)
        return cls._instances.get(key)

    @classmethod
    def get_by_id(cls, chain_id: str) -> Optional['ChainLogger']:
        """Get chain logger by chain_id (searches all instances)."""
        for logger in cls._instances.values():
            if logger.chain_id == chain_id:
                return logger
        return None


def set_current_chain_logger(logger: Optional[ChainLogger]):
    """Set the current chain logger for this async context."""
    _current_chain_logger.set(logger)


def get_current_chain_logger() -> Optional[ChainLogger]:
    """Get the current chain logger from context."""
    return _current_chain_logger.get()


# Convenience functions for logging from any module
def log_worker(message: str, level: str = "info"):
    """Log to worker.log for current chain context."""
    chain_logger = get_current_chain_logger()
    if chain_logger:
        getattr(chain_logger.worker, level)(message)


def log_comfy_http(message: str, level: str = "info"):
    """Log to comfy_http.log for current chain context."""
    chain_logger = get_current_chain_logger()
    if chain_logger:
        getattr(chain_logger.comfy_http, level)(message)


def log_comfy_ws(message: str, level: str = "info"):
    """Log to comfy_ws.log for current chain context."""
    chain_logger = get_current_chain_logger()
    if chain_logger:
        getattr(chain_logger.comfy_ws, level)(message)


def log_gateway(message: str, level: str = "info"):
    """Log to gateway.log for current chain context."""
    chain_logger = get_current_chain_logger()
    if chain_logger:
        getattr(chain_logger.gateway, level)(message)
