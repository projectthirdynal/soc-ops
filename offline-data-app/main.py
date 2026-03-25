"""Entry point -- starts FastAPI on a random port and opens a pywebview window.

Includes graceful shutdown handling: signal handlers (SIGTERM/SIGINT), atexit
fallback, and pywebview close-event cleanup.
"""

from __future__ import annotations

import atexit
import logging
import multiprocessing
import os
import signal
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

import uvicorn

# ---------------------------------------------------------------------------
# Early bootstrap — ensure stdout/stderr exist (PyInstaller console=False
# sets them to None, which crashes logging and print statements).
# ---------------------------------------------------------------------------
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

from app.core.logging_config import setup_logging
from app.core.config import settings

# ---------------------------------------------------------------------------
# Logging -- must happen before any other module-level getLogger() calls
# ---------------------------------------------------------------------------
try:
    settings.ensure_dirs()
    _log_path = setup_logging(log_dir=settings.DATA_DIR / "logs")
except Exception:
    # Fallback: log next to executable
    _fallback_dir = Path(sys.executable).parent / "logs" if getattr(sys, "frozen", False) else Path(".")
    _fallback_dir.mkdir(parents=True, exist_ok=True)
    _log_path = setup_logging(log_dir=_fallback_dir)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Global state for coordinated shutdown
# ---------------------------------------------------------------------------
_shutdown_event = threading.Event()
_uvicorn_server: uvicorn.Server | None = None
_temp_files_to_clean: list[Path] = []


def register_temp_file(path: Path | str) -> None:
    """Register a temporary file for cleanup on shutdown."""
    _temp_files_to_clean.append(Path(path))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _show_error(title: str, message: str) -> None:
    """Print error to stderr and attempt a native Windows dialog if available."""
    print(f"ERROR -- {title}: {message}", file=sys.stderr)
    try:
        import ctypes  # only present on Windows
        ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)  # type: ignore[attr-defined]
    except Exception:
        pass


def _find_free_port() -> int:
    """Find an available TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------------------
# Shutdown logic
# ---------------------------------------------------------------------------

def _cleanup_temp_files() -> None:
    """Remove any temporary files registered during the session."""
    for p in _temp_files_to_clean:
        try:
            if p.exists():
                p.unlink()
                logger.debug("Cleaned up temp file: %s", p)
        except OSError as exc:
            logger.debug("Could not remove temp file %s: %s", p, exc)


def _shutdown() -> None:
    """Perform orderly shutdown: stop uvicorn, close DB, clean temp files.

    Safe to call multiple times -- the shutdown event prevents re-entry.
    """
    if _shutdown_event.is_set():
        return
    _shutdown_event.set()

    logger.info("Shutdown initiated.")

    # 1. Stop uvicorn server
    if _uvicorn_server is not None:
        logger.info("Requesting uvicorn shutdown.")
        _uvicorn_server.should_exit = True

    # 2. Close DuckDB connection
    try:
        from app.core.database import close_db
        close_db()
    except Exception:
        logger.exception("Error closing DuckDB during shutdown.")

    # 3. Clean temp files
    _cleanup_temp_files()

    logger.info("Shutdown complete.")


def _signal_handler(signum: int, _frame: object) -> None:
    """Handle SIGTERM / SIGINT by triggering orderly shutdown."""
    sig_name = signal.Signals(signum).name if hasattr(signal, "Signals") else str(signum)
    logger.info("Received signal %s -- shutting down.", sig_name)
    _shutdown()
    # If running in browser-fallback mode, exit so the join() unblocks.
    sys.exit(0)


# Register atexit as a safety net (runs even if signals are missed)
atexit.register(_shutdown)


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

def _start_server(port: int) -> None:
    """Run the uvicorn server (blocking -- meant for a background thread)."""
    global _uvicorn_server
    try:
        from app.api import create_app

        app = create_app()

        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
        )
        _uvicorn_server = uvicorn.Server(config)
        logger.info("Uvicorn server starting on 127.0.0.1:%d", port)
        _uvicorn_server.run()
        logger.info("Uvicorn server stopped.")
    except Exception:
        logger.exception("Server thread crashed during startup.")


def _wait_for_server(port: int, timeout: float = 30.0) -> bool:
    """Block until the server accepts connections or timeout expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Application entry point."""
    multiprocessing.freeze_support()  # Required on Windows for PyInstaller

    try:
        _main_inner()
    except Exception as exc:
        logger.exception("Fatal error during startup: %s", exc)
        _show_error(
            "SOC Data Processor -- Fatal Error",
            f"{exc}\n\nCheck {_log_path} for details.",
        )
        sys.exit(1)


def _main_inner() -> None:
    """Inner main logic — separated so we can wrap it in a try/except."""
    logger.info("Application starting (PID %d). Log file: %s", os.getpid(), _log_path)

    # Install signal handlers (SIGTERM may not exist on all Windows builds)
    signal.signal(signal.SIGINT, _signal_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _signal_handler)

    port = _find_free_port()
    logger.info("Starting server on port %d", port)

    # Start FastAPI in a daemon thread
    server_thread = threading.Thread(
        target=_start_server, args=(port,), daemon=True, name="uvicorn-server",
    )
    server_thread.start()

    if not _wait_for_server(port):
        msg = (
            f"FastAPI server failed to start within 30 seconds.\n"
            f"Check {_log_path} for details."
        )
        logger.error(msg)
        _show_error("SOC Data Processor -- Startup Error", msg)
        sys.exit(1)

    logger.info("Server ready on port %d -- launching UI", port)
    url = f"http://127.0.0.1:{port}"

    try:
        import webview

        window = webview.create_window(
            "SOC Data Processor",
            url,
            width=1400,
            height=900,
            min_size=(1024, 600),
        )

        # Hook the window-close event to trigger orderly shutdown
        def _on_closing() -> None:
            logger.info("pywebview window closing.")
            _shutdown()

        window.events.closing += _on_closing

        webview.start()

    except ImportError:
        logger.warning("pywebview not available -- opening in default browser")
        import webbrowser

        webbrowser.open(url)
        try:
            server_thread.join()
        except KeyboardInterrupt:
            pass

    except Exception as exc:
        logger.exception("pywebview error: %s", exc)
        _show_error("SOC Data Processor -- UI Error", str(exc))
        sys.exit(1)

    # Final shutdown (may already have been called via signal or window close)
    _shutdown()
    logger.info("Application exited.")


if __name__ == "__main__":
    main()
