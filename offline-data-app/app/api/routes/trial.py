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
    return get_trial_status()


@router.post("/trial/activate")
async def trial_activate(body: ActivateRequest) -> dict:
    return activate(body.key)
