"""Trial period enforcement with simple activation code.

Flow:
  1. First launch → records start timestamp in .activation (encoded + signed).
  2. Each launch → checks for .licence first (permanent activation).
     If no licence → checks trial countdown (TRIAL_DAYS).
  3. User enters activation code → if it matches → writes .licence → unlocked forever.
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

# The activation code users enter after paying.
# Change this to whatever you want to give to paid customers.
_ACTIVATION_CODE = "ASIANOW-2026-PRO"


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _data_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(local) / "offline-data-app"


def _trial_file() -> Path:
    return _data_dir() / ".activation"


def _licence_file() -> Path:
    return _data_dir() / ".licence"


# ---------------------------------------------------------------------------
# Activation
# ---------------------------------------------------------------------------

def _save_licence() -> None:
    f = _licence_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"activated": True})
    f.write_text(base64.b64encode(payload.encode()).decode())
    logger.info("Licence activated.")


def _load_licence() -> bool:
    f = _licence_file()
    if not f.exists():
        return False
    try:
        payload = json.loads(base64.b64decode(f.read_text().strip().encode()).decode())
        return payload.get("activated") is True
    except Exception:
        return False


def activate(key: str) -> dict:
    """Validate activation code. Returns success/failure dict."""
    if key.strip().upper() == _ACTIVATION_CODE.upper():
        _save_licence()
        return {"success": True}
    return {"success": False, "error": "Invalid activation code."}


# ---------------------------------------------------------------------------
# Trial file encoding
# ---------------------------------------------------------------------------

def _encode(start_iso: str) -> str:
    h = hashlib.sha256(f"{start_iso}{_SECRET}".encode()).hexdigest()[:20]
    payload = json.dumps({"s": start_iso, "h": h})
    return base64.b64encode(payload.encode()).decode()


def _decode(raw: str) -> str | None:
    try:
        payload = json.loads(base64.b64decode(raw.strip().encode()).decode())
        start_iso: str = payload["s"]
        expected = hashlib.sha256(f"{start_iso}{_SECRET}".encode()).hexdigest()[:20]
        if payload.get("h") != expected:
            return None
        return start_iso
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

def get_trial_status() -> dict:
    if _load_licence():
        return {
            "activated": True,
            "expired": False,
            "remaining_seconds": 0,
            "remaining_hours": 0.0,
            "trial_days": TRIAL_DAYS,
            "tampered": False,
        }

    f = _trial_file()
    try:
        if f.exists():
            start_iso = _decode(f.read_text().strip())
            if start_iso is None:
                return {
                    "activated": False,
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

        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)

        now = datetime.now(timezone.utc)
        elapsed = (now - start).total_seconds()
        trial_seconds = TRIAL_DAYS * 86_400
        remaining = max(0.0, trial_seconds - elapsed)
        expired = elapsed >= trial_seconds

        return {
            "activated": False,
            "expired": expired,
            "remaining_seconds": int(remaining),
            "remaining_hours": round(remaining / 3600, 2),
            "trial_days": TRIAL_DAYS,
            "tampered": False,
        }

    except Exception:
        logger.exception("Trial status check failed — allowing access.")
        return {
            "activated": False,
            "expired": False,
            "remaining_seconds": TRIAL_DAYS * 86_400,
            "remaining_hours": float(TRIAL_DAYS * 24),
            "trial_days": TRIAL_DAYS,
            "tampered": False,
        }
