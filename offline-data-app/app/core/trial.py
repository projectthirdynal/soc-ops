"""Trial period enforcement with machine-locked activation codes.

Flow:
  1. First launch → records start timestamp in .activation (encoded + signed).
  2. Each launch → checks for .licence first (permanent activation).
     If no licence → checks trial countdown (TRIAL_DAYS).
  3. User enters activation key → validated against machine ID → writes .licence.

Key generation (admin-only):
  python keygen.py <machine_id>
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import platform
import uuid
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

TRIAL_DAYS: int = 1
_SECRET = "asn-claims-2026-thirdynal"
_LICENCE_SECRET = "thirdynal-licence-key-2026"


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
# Machine identity
# ---------------------------------------------------------------------------

def get_machine_id() -> str:
    """Stable, per-machine identifier (MAC address + hostname hashed).

    Displayed in the UI so the admin can generate a key for this machine.
    """
    raw = f"{uuid.getnode()}-{platform.node()}".encode()
    return hashlib.sha256(raw).hexdigest()[:16].upper()


# ---------------------------------------------------------------------------
# Activation key generation & validation
# ---------------------------------------------------------------------------

def generate_licence_key(machine_id: str) -> str:
    """Generate a licence key for a given machine ID (admin utility).

    Returns a key in the format XXXX-XXXX-XXXX-XXXX.
    """
    sig = hmac.new(
        _LICENCE_SECRET.encode(),
        machine_id.upper().encode(),
        hashlib.sha256,
    ).hexdigest()[:16].upper()
    return f"{sig[:4]}-{sig[4:8]}-{sig[8:12]}-{sig[12:16]}"


def _verify_licence_key(key: str, machine_id: str) -> bool:
    """Check whether *key* is valid for *machine_id*."""
    expected = generate_licence_key(machine_id)
    return hmac.compare_digest(key.strip().upper(), expected.upper())


# ---------------------------------------------------------------------------
# Activation persistence
# ---------------------------------------------------------------------------

def _save_licence(key: str) -> None:
    """Write the validated licence to disk."""
    f = _licence_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"k": key.strip().upper(), "m": get_machine_id()})
    f.write_text(base64.b64encode(payload.encode()).decode())
    logger.info("Licence activated.")


def _load_licence() -> bool:
    """Return True if a valid licence file exists for this machine."""
    f = _licence_file()
    if not f.exists():
        return False
    try:
        payload = json.loads(base64.b64decode(f.read_text().strip().encode()).decode())
        return _verify_licence_key(payload["k"], payload["m"]) and payload["m"] == get_machine_id()
    except Exception:
        logger.warning("Licence file unreadable or tampered.")
        return False


# ---------------------------------------------------------------------------
# Public API: activate
# ---------------------------------------------------------------------------

def activate(key: str) -> dict:
    """Attempt to activate with the given key.

    Returns {"success": True} or {"success": False, "error": "..."}.
    """
    machine_id = get_machine_id()
    if _verify_licence_key(key, machine_id):
        _save_licence(key)
        return {"success": True, "machine_id": machine_id}
    return {"success": False, "error": "Invalid activation key for this machine."}


# ---------------------------------------------------------------------------
# Trial file encoding (unchanged)
# ---------------------------------------------------------------------------

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
            return None
        return start_iso
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Public API: status
# ---------------------------------------------------------------------------

def get_trial_status() -> dict:
    """Return a dict describing the current trial / activation state.

    Keys:
        activated (bool): True if a valid licence exists → skip trial.
        expired (bool): True when trial period is over (and not activated).
        remaining_seconds (int): Seconds left in trial (0 when expired/activated).
        remaining_hours (float): Human-readable hours remaining.
        trial_days (int): Total trial length in days.
        tampered (bool): True if activation file was modified.
        machine_id (str): This machine's ID (for requesting a key).
    """
    machine_id = get_machine_id()

    # Check permanent licence first
    if _load_licence():
        return {
            "activated": True,
            "expired": False,
            "remaining_seconds": 0,
            "remaining_hours": 0.0,
            "trial_days": TRIAL_DAYS,
            "tampered": False,
            "machine_id": machine_id,
        }

    # Fall through to trial logic
    f = _trial_file()
    try:
        if f.exists():
            start_iso = _decode(f.read_text().strip())
            if start_iso is None:
                logger.warning("Trial activation file appears tampered.")
                return {
                    "activated": False,
                    "expired": True,
                    "remaining_seconds": 0,
                    "remaining_hours": 0.0,
                    "trial_days": TRIAL_DAYS,
                    "tampered": True,
                    "machine_id": machine_id,
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
            "machine_id": machine_id,
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
            "machine_id": machine_id,
        }
