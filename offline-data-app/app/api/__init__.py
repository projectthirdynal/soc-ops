"""FastAPI application factory, router registration, and request logging middleware."""

from __future__ import annotations

import logging
import time

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.core.version import VERSION

logger = logging.getLogger(__name__)

# Re-export for route modules that do `from app.api import acquire_operation, release_operation`
from app.api.ops_lock import acquire_operation, release_operation

__all__ = ["create_app", "acquire_operation", "release_operation"]

# API paths exempt from trial enforcement
_TRIAL_EXEMPT = frozenset({
    "/api/health",
    "/api/trial/status",
    "/api/trial/activate",
})

# Paths that should not be logged to avoid noise
_QUIET_PATHS = frozenset({
    "/api/health",
    "/api/split/progress",
    "/api/split/file/progress",
    "/api/dashboard/metrics",
    "/api/dashboard/cogs-distribution",
    "/api/dashboard/hub-performance",
    "/api/dashboard/recent-claims",
})


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Registers all API routers, adds request-logging middleware, and mounts
    the static UI directory.

    Returns:
        Configured FastAPI application instance.
    """
    application = FastAPI(
        title="ASN Claims Processor",
        description="Offline desktop claims data processing application",
        version=VERSION,
    )

    # ------------------------------------------------------------------
    # Trial enforcement middleware (runs before logging middleware)
    # ------------------------------------------------------------------
    @application.middleware("http")
    async def enforce_trial(request: Request, call_next) -> Response:
        path = request.url.path
        if path.startswith("/api/") and path not in _TRIAL_EXEMPT:
            from app.core.trial import get_trial_status
            status = get_trial_status()
            if status.get("expired"):
                return JSONResponse(
                    status_code=402,
                    content={"detail": "trial_expired"},
                )
        return await call_next(request)

    # ------------------------------------------------------------------
    # Request logging middleware
    # ------------------------------------------------------------------
    @application.middleware("http")
    async def log_requests(request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        """Log method, path, status code, and duration for every request."""
        if request.url.path in _QUIET_PATHS:
            return await call_next(request)

        start = time.perf_counter()
        try:
            response: Response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.exception(
                "%s %s -> 500 (unhandled) [%.1fms]",
                request.method,
                request.url.path,
                duration_ms,
            )
            raise

        duration_ms = (time.perf_counter() - start) * 1000
        log_fn = logger.warning if response.status_code >= 400 else logger.info
        log_fn(
            "%s %s -> %d [%.1fms]",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response

    # ------------------------------------------------------------------
    # Health check (lightweight, not logged)
    # ------------------------------------------------------------------
    @application.get("/api/health")
    async def health() -> dict[str, object]:
        from app.core.database import health_check
        return health_check()

    # ------------------------------------------------------------------
    # Routers (imported here to avoid circular imports — route modules
    # import acquire_operation / release_operation from app.api)
    # ------------------------------------------------------------------
    from app.api.routes import upload, split, aggregate, cluster, dashboard, update, search, data, fileexport, trial

    application.include_router(trial.router, prefix="/api", tags=["trial"])
    application.include_router(upload.router, prefix="/api", tags=["upload"])
    application.include_router(split.router, prefix="/api", tags=["split"])
    application.include_router(aggregate.router, prefix="/api", tags=["aggregate"])
    application.include_router(cluster.router, prefix="/api", tags=["cluster"])
    application.include_router(dashboard.router, prefix="/api", tags=["dashboard"])
    application.include_router(update.router, prefix="/api", tags=["update"])
    application.include_router(search.router, prefix="/api", tags=["search"])
    application.include_router(data.router, prefix="/api", tags=["data"])
    application.include_router(fileexport.router, prefix="/api", tags=["export"])

    # ------------------------------------------------------------------
    # Static UI files
    # ------------------------------------------------------------------
    ui_dir = Path(__file__).resolve().parent.parent / "ui"
    if not ui_dir.exists():
        import sys
        # PyInstaller bundle path
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent.parent))
        ui_dir = base / "app" / "ui"

    # Mount static files for CSS/JS
    application.mount("/static", StaticFiles(directory=str(ui_dir)), name="static")

    @application.get("/")
    async def serve_index() -> FileResponse:
        """Serve the main UI page."""
        return FileResponse(str(ui_dir / "index.html"), media_type="text/html")

    logger.info("FastAPI application created.")
    return application
