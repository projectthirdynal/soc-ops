"""Split data endpoints with SSE progress streaming."""

from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, UploadFile, File, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.database import get_db
from app.core.splitter import split_to_files
from app.api import acquire_operation, release_operation

logger = logging.getLogger(__name__)
router = APIRouter()

# Module-level state for SSE progress, guarded by a lock
_split_lock = threading.Lock()
_split_progress: dict[str, Any] = {"running": False, "progress": 0, "files_written": 0, "done": False, "error": None}


class SplitRequest(BaseModel):
    """Parameters for a split operation."""
    chunk_size: int = Field(default=1000, ge=1, le=1_000_000)
    order_column: str | None = None
    output_folder: str | None = None


class SplitExportRecord(BaseModel):
    """A single export history entry."""
    export_id: int
    import_id: int | None
    chunk_size: int
    file_count: int
    exported_at: str
    output_folder: str


def _validate_output_dir(raw_path: str | None) -> str:
    """Resolve the output directory, allowing any valid absolute path.

    If *raw_path* is empty/None the default exports directory is used.
    Relative paths are resolved under EXPORTS_DIR.  A warning is logged
    when the resolved path falls outside the application data directory.
    """
    if not raw_path:
        return str(settings.EXPORTS_DIR.resolve())

    candidate = Path(raw_path).resolve()

    # Create the directory if it doesn't exist
    try:
        candidate.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"Cannot create output folder: {exc}")

    # Warn (but allow) paths outside the app's data directory
    try:
        candidate.relative_to(settings.EXPORTS_DIR.resolve())
    except ValueError:
        logger.warning(
            "Output folder '%s' is outside the default exports directory (%s).",
            candidate,
            settings.EXPORTS_DIR.resolve(),
        )

    return str(candidate)


@router.post("/split")
async def start_split(req: SplitRequest) -> dict[str, Any]:
    """Start a split operation (runs in background, progress via SSE).

    The split writes chunk-sized CSV files to the output folder using
    DuckDB COPY for efficiency.
    """
    global _split_progress

    with _split_lock:
        if _split_progress.get("running"):
            raise HTTPException(status_code=409, detail="A split operation is already running.")

    db = get_db()

    # Validate raw_data exists
    try:
        db.execute("SELECT 1 FROM raw_data LIMIT 1")
    except Exception:
        raise HTTPException(status_code=400, detail="No data loaded. Upload a file first.")

    # Validate and resolve output directory (path traversal protection)
    output_dir = _validate_output_dir(req.output_folder)

    # Validate order column if provided
    if req.order_column:
        cols = [d[0] for d in db.execute("SELECT * FROM raw_data LIMIT 0").description]
        if req.order_column not in cols:
            raise HTTPException(
                status_code=400,
                detail=f"Column '{req.order_column}' not found. Available: {cols}",
            )

    # Acquire the global operation lock (raises 409 if another op is running)
    acquire_operation("split")

    # Reset progress (under lock)
    with _split_lock:
        _split_progress = {"running": True, "progress": 0, "files_written": 0, "done": False, "error": None}

    logger.info(
        "Split operation started: chunk_size=%d, order_column=%s, output=%s",
        req.chunk_size, req.order_column, output_dir,
    )

    # Run split in a background task
    asyncio.get_running_loop().run_in_executor(None, _run_split, db, output_dir, req.chunk_size, req.order_column)

    return {"status": "started", "output_folder": output_dir, "chunk_size": req.chunk_size}


def _run_split(
    db: Any,
    output_dir: str,
    chunk_size: int,
    order_column: str | None,
) -> None:
    """Execute the split in a thread, updating _split_progress under lock."""
    global _split_progress
    try:
        gen = split_to_files(db, output_dir, chunk_size, order_column)
        for update in gen:
            with _split_lock:
                _split_progress["progress"] = update["progress"]
                _split_progress["files_written"] = update["files_written"]

        # Record export
        with _split_lock:
            total_files = _split_progress["files_written"]

        import_id_result = db.execute("SELECT MAX(import_id) FROM imports").fetchone()
        import_id = import_id_result[0] if import_id_result else None

        db.execute(
            "INSERT INTO split_exports (import_id, chunk_size, file_count, output_folder) VALUES (?, ?, ?, ?)",
            [import_id, chunk_size, total_files, output_dir],
        )

        with _split_lock:
            _split_progress["done"] = True
            _split_progress["running"] = False
        release_operation()
        logger.info("Split complete: %d files", total_files)

    except Exception as exc:
        logger.exception("Split failed")
        with _split_lock:
            _split_progress["error"] = str(exc)
            _split_progress["done"] = True
            _split_progress["running"] = False
        release_operation()


@router.get("/split/progress")
async def split_progress_sse() -> StreamingResponse:
    """SSE endpoint streaming split progress events."""

    async def event_generator():
        import json

        while True:
            with _split_lock:
                snapshot = dict(_split_progress)
            data = json.dumps(snapshot)
            yield f"data: {data}\n\n"
            if snapshot.get("done") or snapshot.get("error"):
                break
            await asyncio.sleep(0.3)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/split/exports", response_model=list[SplitExportRecord])
async def list_exports() -> list[dict[str, Any]]:
    """Return all past split export records."""
    db = get_db()
    rows = db.execute(
        "SELECT export_id, import_id, chunk_size, file_count, "
        "exported_at::VARCHAR AS exported_at, output_folder "
        "FROM split_exports ORDER BY export_id DESC"
    ).fetchall()
    cols = ["export_id", "import_id", "chunk_size", "file_count", "exported_at", "output_folder"]
    return [dict(zip(cols, row)) for row in rows]


# ------------------------------------------------------------------
# Standalone file-splitting endpoint (no database import required)
# ------------------------------------------------------------------

# Module-level state for standalone split SSE progress
_file_split_lock = threading.Lock()
_file_split_progress: dict[str, Any] = {"running": False, "progress": 0, "files_written": 0, "done": False, "error": None}


@router.post("/split/file")
async def split_uploaded_file(
    file: UploadFile = File(...),
    chunk_size: int = Query(default=1000, ge=1, le=1_000_000),
    output_folder: str = Query(default=""),
) -> dict[str, Any]:
    """Split an uploaded CSV/XLSX file directly into XLSX chunks.

    Does NOT import to database -- purely a file splitting tool.
    Saves the uploaded file to a temp location, reads it with an
    in-memory DuckDB connection, and writes chunk-sized XLSX files.
    """
    global _file_split_progress

    with _file_split_lock:
        if _file_split_progress.get("running"):
            raise HTTPException(status_code=409, detail="A file split operation is already running.")

    # Resolve output directory
    output_dir = _validate_output_dir(output_folder or None)

    # Save uploaded file to a temp location
    import tempfile
    import shutil

    suffix = Path(file.filename or "upload.csv").suffix.lower()
    if suffix not in (".csv", ".xlsx", ".xls", ".tsv"):
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {suffix}")

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        shutil.copyfileobj(file.file, tmp)
        tmp.close()
        tmp_path = tmp.name
    except Exception as exc:
        tmp.close()
        Path(tmp.name).unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Failed to save uploaded file: {exc}")

    # Reset progress
    with _file_split_lock:
        _file_split_progress = {"running": True, "progress": 0, "files_written": 0, "done": False, "error": None}

    # Run in background
    asyncio.get_running_loop().run_in_executor(None, _run_file_split, tmp_path, suffix, output_dir, chunk_size)

    return {"status": "started", "output_folder": output_dir, "chunk_size": chunk_size}


def _run_file_split(
    tmp_path: str,
    suffix: str,
    output_dir: str,
    chunk_size: int,
) -> None:
    """Execute standalone file split in a thread."""
    global _file_split_progress
    import duckdb as _duckdb
    from openpyxl import Workbook

    try:
        mem_db = _duckdb.connect(":memory:")

        # Load file into temp table
        if suffix == ".csv" or suffix == ".tsv":
            mem_db.execute("CREATE TABLE tmp_split AS SELECT * FROM read_csv_auto(?)", [tmp_path])
        else:
            # XLSX — use polars → temp parquet → DuckDB (avoids pyarrow dependency)
            import polars as pl
            tmp_parquet = tmp_path + ".parquet"
            try:
                pl.read_excel(tmp_path).write_parquet(tmp_parquet)
                mem_db.execute(
                    "CREATE TABLE tmp_split AS SELECT * FROM read_parquet(?)",
                    [tmp_parquet],
                )
            finally:
                Path(tmp_parquet).unlink(missing_ok=True)

        total_rows = mem_db.execute("SELECT COUNT(*) FROM tmp_split").fetchone()[0]
        if total_rows == 0:
            raise ValueError("Uploaded file is empty -- nothing to split.")

        total_files = (total_rows + chunk_size - 1) // chunk_size

        # Get column names
        col_info = mem_db.execute("SELECT * FROM tmp_split LIMIT 0").description
        col_names = [d[0] for d in col_info]

        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        files_written = 0
        for i in range(total_files):
            offset = i * chunk_size
            file_path = out / f"split_{i + 1:05d}.xlsx"

            query = f"SELECT * FROM tmp_split ORDER BY rowid LIMIT {chunk_size} OFFSET {offset}"
            rows = mem_db.execute(query).fetchall()

            wb = Workbook()
            ws = wb.active
            ws.append(col_names)
            for row in rows:
                ws.append(list(row))
            wb.save(str(file_path))

            files_written += 1
            progress = round(files_written / total_files * 100, 1)

            with _file_split_lock:
                _file_split_progress["progress"] = progress
                _file_split_progress["files_written"] = files_written

            if files_written == 1 or files_written == total_files or files_written % max(1, total_files // 10) == 0:
                logger.info("File split progress: %d/%d files (%.1f%%)", files_written, total_files, progress)

        mem_db.close()

        with _file_split_lock:
            _file_split_progress["done"] = True
            _file_split_progress["running"] = False
        logger.info("File split complete: %d XLSX files written.", files_written)

    except Exception as exc:
        logger.exception("File split failed")
        with _file_split_lock:
            _file_split_progress["error"] = str(exc)
            _file_split_progress["done"] = True
            _file_split_progress["running"] = False
    finally:
        # Clean up temp file
        Path(tmp_path).unlink(missing_ok=True)


@router.get("/split/file/status")
async def file_split_status() -> dict[str, Any]:
    """Return current file-split progress as plain JSON (for reconnect checks)."""
    with _file_split_lock:
        return dict(_file_split_progress)


@router.get("/split/file/progress")
async def file_split_progress_sse() -> StreamingResponse:
    """SSE endpoint streaming standalone file-split progress events."""

    async def event_generator():
        import json

        while True:
            with _file_split_lock:
                snapshot = dict(_file_split_progress)
            data = json.dumps(snapshot)
            yield f"data: {data}\n\n"
            if snapshot.get("done") or snapshot.get("error"):
                break
            await asyncio.sleep(0.3)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
