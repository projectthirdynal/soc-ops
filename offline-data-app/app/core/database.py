"""DuckDB connection management with automatic schema initialization.

Provides a singleton connection with retry logic, health checks, and
lifecycle logging.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

import duckdb

from app.core.config import settings

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_connection: Optional[duckdb.DuckDBPyConnection] = None

_MAX_CONNECT_RETRIES = 3
_RETRY_DELAY_SECONDS = 1.0

_SCHEMA_SQL = """
CREATE SEQUENCE IF NOT EXISTS seq_import_id START 1;
CREATE SEQUENCE IF NOT EXISTS seq_export_id START 1;
CREATE SEQUENCE IF NOT EXISTS seq_cluster_run_id START 1;

CREATE TABLE IF NOT EXISTS imports (
    import_id INTEGER DEFAULT nextval('seq_import_id') PRIMARY KEY,
    filename VARCHAR,
    file_type VARCHAR,
    row_count INTEGER,
    imported_at TIMESTAMP DEFAULT current_timestamp,
    column_names VARCHAR[],
    notes VARCHAR
);

CREATE TABLE IF NOT EXISTS split_exports (
    export_id INTEGER DEFAULT nextval('seq_export_id') PRIMARY KEY,
    import_id INTEGER,
    chunk_size INTEGER,
    file_count INTEGER,
    exported_at TIMESTAMP DEFAULT current_timestamp,
    output_folder VARCHAR
);

CREATE TABLE IF NOT EXISTS cluster_runs (
    run_id INTEGER DEFAULT nextval('seq_cluster_run_id') PRIMARY KEY,
    algorithm VARCHAR,
    n_clusters INTEGER,
    feature_columns VARCHAR[],
    run_at TIMESTAMP DEFAULT current_timestamp,
    silhouette_score DOUBLE
);
"""


def _init_schema(conn: duckdb.DuckDBPyConnection) -> None:
    """Run DDL statements to ensure all required tables exist."""
    for stmt in _SCHEMA_SQL.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            conn.execute(stmt)
    logger.info("Database schema initialized.")


def get_db() -> duckdb.DuckDBPyConnection:
    """Return the singleton DuckDB connection, creating it if necessary.

    Thread-safe -- a lock guards the initial creation.  DuckDB itself
    serialises concurrent writes internally.

    Retries up to ``_MAX_CONNECT_RETRIES`` times on connection failure.

    Returns:
        Active DuckDB connection.

    Raises:
        RuntimeError: If all connection attempts fail.
    """
    global _connection
    if _connection is not None:
        return _connection

    with _lock:
        # Double-check after acquiring lock
        if _connection is not None:
            return _connection

        settings.ensure_dirs()
        db_path = str(settings.DB_PATH)

        last_error: Exception | None = None
        for attempt in range(1, _MAX_CONNECT_RETRIES + 1):
            try:
                logger.info(
                    "Opening DuckDB at %s (attempt %d/%d)",
                    db_path, attempt, _MAX_CONNECT_RETRIES,
                )
                conn = duckdb.connect(db_path)
                _init_schema(conn)
                _connection = conn
                logger.info("DuckDB connection established successfully.")
                return _connection
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "DuckDB connection attempt %d/%d failed: %s",
                    attempt, _MAX_CONNECT_RETRIES, exc,
                )
                if attempt < _MAX_CONNECT_RETRIES:
                    time.sleep(_RETRY_DELAY_SECONDS)

        msg = f"Failed to connect to DuckDB after {_MAX_CONNECT_RETRIES} attempts."
        logger.error(msg)
        raise RuntimeError(msg) from last_error


def close_db() -> None:
    """Close the database connection if open."""
    global _connection
    with _lock:
        if _connection is not None:
            try:
                _connection.close()
                logger.info("DuckDB connection closed.")
            except Exception:
                logger.exception("Error while closing DuckDB connection.")
            finally:
                _connection = None


def health_check() -> dict[str, object]:
    """Return a lightweight health status for the database connection.

    Returns:
        Dict with ``ok`` (bool) and ``detail`` (str).
    """
    try:
        conn = get_db()
        result = conn.execute("SELECT 1").fetchone()
        if result and result[0] == 1:
            return {"ok": True, "detail": "DuckDB responding normally."}
        return {"ok": False, "detail": "Unexpected query result."}
    except Exception as exc:
        logger.error("Database health check failed: %s", exc)
        return {"ok": False, "detail": str(exc)}
