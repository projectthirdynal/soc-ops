"""Trial status endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.trial import get_trial_status

router = APIRouter()


@router.get("/trial/status")
async def trial_status() -> dict:
    """Return the current trial status (exempt from trial enforcement middleware)."""
    return get_trial_status()
