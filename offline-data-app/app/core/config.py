"""Application configuration with sensible defaults for offline desktop use."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


def _default_base_dir() -> Path:
    """Resolve the base data directory.

    Tries platformdirs first; falls back to a ``data/`` folder next to the
    application root.
    """
    try:
        from platformdirs import user_data_dir

        return Path(user_data_dir("offline-data-app", appauthor=False))
    except ImportError:
        return Path(__file__).resolve().parent.parent.parent / "data"


@dataclass
class Settings:
    """Central configuration for the application.

    All path attributes are resolved to absolute ``Path`` objects on
    construction so that callers never need to worry about relative paths.
    """

    BASE_DIR: Path = field(default_factory=_default_base_dir)
    CHUNK_SIZE: int = 1000
    DEFAULT_N_CLUSTERS: int = 8
    DEFAULT_ALGORITHM: str = "MiniBatchKMeans"
    MAX_UPLOAD_SIZE_MB: int = 2048
    LOG_FILE: str = "app.log"

    # OTA update settings
    UPDATE_CHECK_URL: str = "github:projectthirdynal/soc-ops"  # GitHub repo, file path, UNC path, or HTTP URL
    UPDATE_CHECK_ON_STARTUP: bool = True
    UPDATE_DOWNLOAD_DIR: str = ""         # empty = use default in app data directory

    @property
    def DATA_DIR(self) -> Path:
        """Directory for general runtime data."""
        return self.BASE_DIR

    @property
    def DB_PATH(self) -> Path:
        """Path to the DuckDB database file."""
        return self.BASE_DIR / "app.duckdb"

    @property
    def EXPORTS_DIR(self) -> Path:
        """Default directory for split-file exports."""
        return self.BASE_DIR / "exports"

    def ensure_dirs(self) -> None:
        """Create all required directories if they do not exist."""
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
        logger.info("Data directory: %s", self.DATA_DIR)
        logger.info("Exports directory: %s", self.EXPORTS_DIR)


# Module-level singleton --------------------------------------------------
settings = Settings()
