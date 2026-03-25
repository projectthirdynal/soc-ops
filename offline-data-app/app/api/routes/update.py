"""API routes for OTA update checking, downloading, and installing."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel

from app.core.version import VERSION, BUILD_DATE
from app.core.updater import (
    UpdateConfig,
    UpdateCheckResult,
    check_for_update,
    fetch_manifest,
    download_installer,
    launch_installer,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/update", tags=["update"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class CurrentVersionResponse(BaseModel):
    """Response for the current version endpoint."""
    version: str
    build_date: str


class UpdateCheckResponse(BaseModel):
    """Response for the update check endpoint."""
    update_available: bool
    current_version: str
    remote_version: str
    build_date: str
    changelog: str
    mandatory: bool
    installer_filename: str
    installer_size_bytes: int
    error: str


class DownloadResponse(BaseModel):
    """Response for the download endpoint."""
    success: bool
    installer_path: str
    error: str


class InstallResponse(BaseModel):
    """Response for the install endpoint."""
    success: bool
    message: str
    error: str


class UpdateConfigRequest(BaseModel):
    """Request body for saving update configuration."""
    update_source: str = ""
    check_on_startup: bool = True
    download_dir: str = ""


class UpdateConfigResponse(BaseModel):
    """Response for the configuration endpoint."""
    update_source: str
    check_on_startup: bool
    download_dir: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/current-version", response_model=CurrentVersionResponse)
async def get_current_version() -> CurrentVersionResponse:
    """Return the current application version and build date."""
    return CurrentVersionResponse(version=VERSION, build_date=BUILD_DATE)


@router.get("/check", response_model=UpdateCheckResponse)
async def check_update() -> UpdateCheckResponse:
    """Check the configured update source for a newer version.

    Returns update availability, changelog, and metadata.
    If no update source is configured, returns with error message.
    """
    config = UpdateConfig.load()
    if not config.update_source:
        return UpdateCheckResponse(
            update_available=False,
            current_version=VERSION,
            remote_version="",
            build_date="",
            changelog="",
            mandatory=False,
            installer_filename="",
            installer_size_bytes=0,
            error="Update source not configured. Set it in Settings.",
        )

    result = check_for_update(config.update_source)
    return UpdateCheckResponse(
        update_available=result.update_available,
        current_version=result.current_version,
        remote_version=result.remote_version,
        build_date=result.build_date,
        changelog=result.changelog,
        mandatory=result.mandatory,
        installer_filename=result.installer_filename,
        installer_size_bytes=result.installer_size_bytes,
        error=result.error,
    )


@router.post("/download", response_model=DownloadResponse)
async def download_update() -> DownloadResponse:
    """Download the installer from the update source.

    Fetches the manifest, downloads the installer file, and verifies SHA256.
    """
    config = UpdateConfig.load()
    if not config.update_source:
        return DownloadResponse(
            success=False,
            installer_path="",
            error="Update source not configured.",
        )

    try:
        manifest = fetch_manifest(config.update_source)
        dest_dir = config.effective_download_dir
        installer_path = download_installer(config.update_source, manifest, dest_dir)

        return DownloadResponse(
            success=True,
            installer_path=str(installer_path),
            error="",
        )
    except Exception as exc:
        logger.exception("Download failed: %s", exc)
        return DownloadResponse(
            success=False,
            installer_path="",
            error=str(exc),
        )


@router.post("/install", response_model=InstallResponse)
async def install_update() -> InstallResponse:
    """Launch the downloaded installer and signal the app to exit.

    Looks for the most recently downloaded installer in the download directory.
    Launches it and schedules application shutdown.
    """
    config = UpdateConfig.load()
    dest_dir = config.effective_download_dir

    # Find the installer file (most recent .exe or .msi in the download dir)
    candidates = sorted(
        [f for f in dest_dir.iterdir()
         if f.is_file() and f.suffix.lower() in (".exe", ".msi")],
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )

    if not candidates:
        return InstallResponse(
            success=False,
            message="",
            error="No downloaded installer found. Please download the update first.",
        )

    installer_path = candidates[0]

    try:
        launch_installer(installer_path)
    except Exception as exc:
        logger.exception("Failed to launch installer: %s", exc)
        return InstallResponse(
            success=False,
            message="",
            error=f"Failed to launch installer: {exc}",
        )

    # Schedule app exit after a brief delay to let the response reach the UI
    import threading

    def _shutdown() -> None:
        import time
        time.sleep(2)
        logger.info("Shutting down for update installation.")
        os._exit(0)

    threading.Thread(target=_shutdown, daemon=True).start()

    return InstallResponse(
        success=True,
        message="Installer launched. The application will close shortly.",
        error="",
    )


# ---------------------------------------------------------------------------
# Configuration endpoints
# ---------------------------------------------------------------------------

@router.get("/config", response_model=UpdateConfigResponse)
async def get_update_config() -> UpdateConfigResponse:
    """Return the current update configuration."""
    config = UpdateConfig.load()
    return UpdateConfigResponse(
        update_source=config.update_source,
        check_on_startup=config.check_on_startup,
        download_dir=config.download_dir,
    )


@router.post("/config", response_model=UpdateConfigResponse)
async def save_update_config(req: UpdateConfigRequest) -> UpdateConfigResponse:
    """Save update configuration to disk."""
    config = UpdateConfig(
        update_source=req.update_source,
        check_on_startup=req.check_on_startup,
        download_dir=req.download_dir,
    )
    config.save()
    logger.info("Update config saved: source=%s", config.update_source)
    return UpdateConfigResponse(
        update_source=config.update_source,
        check_on_startup=config.check_on_startup,
        download_dir=config.download_dir,
    )
