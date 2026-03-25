"""Global operation lock to prevent concurrent long-running operations."""

from __future__ import annotations

import logging
import threading
from typing import Optional

from fastapi import HTTPException

logger = logging.getLogger(__name__)

_operation_lock = threading.Lock()
_current_operation: Optional[str] = None


def acquire_operation(name: str) -> None:
    """Attempt to claim the global operation slot.

    Raises HTTPException(409) if another operation is already running.
    """
    global _current_operation
    acquired = _operation_lock.acquire(blocking=False)
    if not acquired:
        raise HTTPException(
            status_code=409,
            detail=f"Another operation is already running: {_current_operation}. "
                   "Please wait for it to finish.",
        )
    _current_operation = name
    logger.info("Operation acquired: %s", name)


def release_operation() -> None:
    """Release the global operation slot."""
    global _current_operation
    op = _current_operation
    _current_operation = None
    try:
        _operation_lock.release()
    except RuntimeError:
        pass  # Already released
    logger.info("Operation released: %s", op)
