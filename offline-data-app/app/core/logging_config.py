"""Structured logging configuration with rotating file handler.

Call ``setup_logging()`` once at application startup (before any other imports
that use ``logging.getLogger``).  All subsequent ``getLogger()`` calls will
inherit the configured handlers and format.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Optional


_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Maximum bytes per log file before rotation (5 MB)
_MAX_BYTES = 5 * 1024 * 1024
# Number of backup files to keep
_BACKUP_COUNT = 3


def setup_logging(
    log_dir: Optional[Path] = None,
    level: int = logging.INFO,
    log_filename: str = "app.log",
) -> Path:
    """Configure the root logger with rotating file and console handlers.

    Args:
        log_dir: Directory for the log file.  Falls back to a ``logs/``
            folder next to the application root when *None*.
        level: Logging level for all handlers (default ``INFO``).
        log_filename: Name of the log file inside *log_dir*.

    Returns:
        Absolute path to the active log file.
    """
    if log_dir is None:
        if getattr(sys, "frozen", False):
            log_dir = Path(sys.executable).parent / "logs"
        else:
            log_dir = Path(__file__).resolve().parent.parent.parent / "logs"

    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / log_filename

    root = logging.getLogger()

    # Avoid adding duplicate handlers if called more than once
    if root.handlers:
        root.handlers.clear()

    root.setLevel(level)

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    # Rotating file handler
    file_handler = logging.handlers.RotatingFileHandler(
        str(log_path),
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # Console handler (stdout) — skip if stdout is None (PyInstaller with console=False)
    if sys.stdout is not None:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        root.addHandler(console_handler)

    # Quieten noisy third-party loggers
    for noisy in ("uvicorn.access", "uvicorn.error", "watchfiles"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    return log_path
