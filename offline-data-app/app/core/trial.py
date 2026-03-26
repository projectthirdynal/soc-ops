"""Trial period enforcement.

Records first-launch timestamp in an encoded file under LOCALAPPDATA.
Returns trial status (expired/remaining) for use by middleware and UI.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

TRIAL_DAYS: int = 1
_SECRET = "asn-claims-2026-thirdynal"


def _data_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(local) / "offline-data-app"


def _trial_file() -> Path:
    return _data_dir() / ".activation"


def _encode(start_iso: str) -> str:
    h = hashlib.sha256(f"{start_iso}{_SECRET}".encode()).hexdigest()[:20]
    payload = json.dumps({"s": start_iso, "h": h})
    return base64.b64encode(payload.encode()).decode()


def _decode(raw: str) -> str | None:
    """Return start ISO string if file is intact, None if tampered."""
    try:
        payload = json.loads(base64.b64decode(raw.strip().encode()).decode())
        start_iso: str = payload["s"]
        expected = hashlib.sha256(f"{start_iso}{_SECRET}".encode()).hexdigest()[:20]
        if payload.get("h") != expected:
            return None  # tampered
        return start_iso
    except Exception:
        return None


def get_trial_status() -> dict:
    """Return a dict describing the current trial state.

    Keys:
        expired (bool): True when the trial period is over.
        remaining_seconds (int): Seconds left in the trial (0 when expired).
        remaining_hours (float): Human-readable hours remaining.
        trial_days (int): Total trial length in days.
        tampered (bool): True if the activation file was manually modified.
    """
    f = _trial_file()
    try:
        if f.exists():
            start_iso = _decode(f.read_text().strip())
            if start_iso is None:
                logger.warning("Trial activation file appears tampered.")
                return {
                    "expired": True,
                    "remaining_seconds": 0,
                    "remaining_hours": 0.0,
                    "trial_days": TRIAL_DAYS,
                    "tampered": True,
                }
            start = datetime.fromisoformat(start_iso)
        else:
            start = datetime.now(timezone.utc)
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(_encode(start.isoformat()))
            logger.info("Trial started: %s", start.isoformat())

        # Ensure timezone-aware for subtraction
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)

        now = datetime.now(timezone.utc)
        elapsed = (now - start).total_seconds()
        trial_seconds = TRIAL_DAYS * 86_400
        remaining = max(0.0, trial_seconds - elapsed)
        expired = elapsed >= trial_seconds

        return {
            "expired": expired,
            "remaining_seconds": int(remaining),
            "remaining_hours": round(remaining / 3600, 2),
            "trial_days": TRIAL_DAYS,
            "tampered": False,
        }

    except Exception:
        logger.exception("Trial status check failed — allowing access.")
        # Fail open so a legitimate bug doesn't lock out the user
        return {
            "expired": False,
            "remaining_seconds": TRIAL_DAYS * 86_400,
            "remaining_hours": float(TRIAL_DAYS * 24),
            "trial_days": TRIAL_DAYS,
            "tampered": False,
        }
