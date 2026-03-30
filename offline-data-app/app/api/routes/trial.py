"""Trial status & activation endpoints."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.trial import activate, get_trial_status

router = APIRouter()


class ActivateRequest(BaseModel):
    key: str


@router.get("/trial/status")
async def trial_status() -> dict:
    """Return the current trial / activation status."""
    return get_trial_status()


@router.post("/trial/activate")
async def trial_activate(body: ActivateRequest) -> dict:
    """Validate an activation key and permanently activate this machine."""
    return activate(body.key)
