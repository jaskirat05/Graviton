"""
Logging configuration using structlog with Rich for colored output
"""

import sys
import logging
from pathlib import Path
from datetime import datetime

import structlog
from rich.console import Console
from rich.logging import RichHandler


def setup_logging(log_dir: Path = None, log_level: str = "INFO", log_prefix: str = "gateway"):
    """
    Setup structured logging with rich colored output

    Args:
        log_dir: Directory to save log files (optional)
        log_level: Logging level (INFO, DEBUG, WARNING, ERROR)
        log_prefix: Prefix for log file name (e.g., "gateway", "worker")
    """
    # Create log directory if specified
    if log_dir:
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        log_file = log_dir / f"{log_prefix}_{timestamp}.log"
    else:
        log_file = None

    # Configure standard logging
    handlers = [
        RichHandler(
            console=Console(stderr=True),
            show_time=True,
            show_path=False,
            markup=True,
            rich_tracebacks=True,
            tracebacks_show_locals=False,
        )
    ]

    # Add file handler if log_dir specified
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(
            logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        )
        handlers.append(file_handler)

    logging.basicConfig(
        level=log_level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=handlers
    )

    # Configure structlog
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    logger = structlog.get_logger()

    if log_file:
        logger.info("Logging configured", log_file=str(log_file), level=log_level)
    else:
        logger.info("Logging configured (console only)", level=log_level)

    return logger, log_file


def get_logger(name: str = None):
    """Get a structured logger instance"""
    return structlog.get_logger(name)
