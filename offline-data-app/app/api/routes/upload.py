"""File upload endpoints — CSV and XLSX import into DuckDB."""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path
from typing import Any

import duckdb
import polars as pl
from fastapi import APIRouter, File, Form, UploadFile, HTTPException
from pydantic import BaseModel

from app.core.database import get_db
from app.core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class ImportResult(BaseModel):
    """Response after a successful file import."""
    import_id: int
    filename: str
    row_count: int
    columns: list[str]
    append_mode: bool = False
    total_rows: int = 0


class ImportRecord(BaseModel):
    """A single import history entry."""
    import_id: int
    filename: str
    file_type: str
    row_count: int
    imported_at: str
    column_names: list[str]
    notes: str | None = None


class ColumnsResponse(BaseModel):
    """Column listing for the current raw_data table."""
    columns: list[str]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_column_name(name: str) -> str:
    """Lowercase, replace spaces/special chars with underscores."""
    name = name.strip().lower()
    name = re.sub(r"[^a-z0-9_]", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    return name or "col"


def _deduplicate_columns(cols: list[str]) -> list[str]:
    """Ensure column names are unique by appending _N suffixes."""
    seen: dict[str, int] = {}
    result: list[str] = []
    for c in cols:
        if c in seen:
            seen[c] += 1
            result.append(f"{c}_{seen[c]}")
        else:
            seen[c] = 0
            result.append(c)
    return result


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/upload", response_model=ImportResult)
async def upload_file(
    file: UploadFile = File(...),
    append: bool = Form(False),
) -> dict[str, Any]:
    """Upload a CSV or XLSX file into the raw_data table.

    - CSV files are read directly by DuckDB for maximum speed.
    - XLSX files are read via Polars (offline-safe) and registered as a
      DuckDB relation before being stored.

    Column names are normalised to lowercase with underscores.
    When ``append=True``, rows are inserted into the existing raw_data table
    instead of replacing it.
    """
    if file.filename is None:
        raise HTTPException(status_code=400, detail="No filename provided.")

    suffix = Path(file.filename).suffix.lower()
    if suffix not in (".csv", ".xlsx"):
        logger.warning("Rejected upload with unsupported type: %s", suffix)
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{suffix}'. Upload a .csv or .xlsx file.",
        )

    logger.info("Upload started: filename=%s, type=%s, append=%s", file.filename, suffix, append)
    db = get_db()
    settings.ensure_dirs()

    # Use a UUID-based temp filename to prevent path traversal via filenames
    tmp_path = str(settings.DATA_DIR / f"_upload_{uuid.uuid4().hex}{suffix}")

    # Stream the upload to disk with a size limit check
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    bytes_written = 0
    try:
        with open(tmp_path, "wb") as tmp_f:
            while True:
                chunk = await file.read(1024 * 1024)  # 1 MB chunks
                if not chunk:
                    break
                bytes_written += len(chunk)
                if bytes_written > max_bytes:
                    tmp_f.close()
                    Path(tmp_path).unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=413,
                        detail=f"File exceeds maximum upload size of {settings.MAX_UPLOAD_SIZE_MB} MB.",
                    )
                tmp_f.write(chunk)
    except HTTPException:
        raise
    except Exception as exc:
        Path(tmp_path).unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Failed to save upload: {exc}") from exc

    try:
        if suffix == ".csv":
            row_count, columns = _import_csv(db, tmp_path, append)
        else:
            row_count, columns = _import_xlsx(db, tmp_path, append)
    except Exception as exc:
        logger.exception("Import failed for %s", file.filename)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        # Clean up temp file
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except OSError:
            pass

    # Total rows in raw_data after import
    total_rows_result = db.execute("SELECT COUNT(*) FROM raw_data").fetchone()
    total_rows: int = total_rows_result[0] if total_rows_result else 0

    # Record in imports table
    db.execute(
        "INSERT INTO imports (filename, file_type, row_count, column_names) VALUES (?, ?, ?, ?)",
        [file.filename, suffix.lstrip("."), row_count, columns],
    )
    import_id_result = db.execute("SELECT MAX(import_id) FROM imports").fetchone()
    import_id: int = import_id_result[0] if import_id_result else 0

    logger.info("Imported %s: %d rows, %d columns (import_id=%d, append=%s)", file.filename, row_count, len(columns), import_id, append)

    return {
        "import_id": import_id,
        "filename": file.filename,
        "row_count": row_count,
        "columns": columns,
        "append_mode": append,
        "total_rows": total_rows,
    }


def _sanitize_identifier(name: str) -> str:
    """Double-quote a SQL identifier, escaping any embedded double quotes."""
    return '"' + name.replace('"', '""') + '"'


def _import_csv(db: duckdb.DuckDBPyConnection, path: str, append: bool = False) -> tuple[int, list[str]]:
    """Import a CSV file via DuckDB read_csv_auto."""
    # Read into a temporary relation to normalise column names
    rel = db.read_csv(path, header=True)
    original_cols = rel.columns

    normalized = _deduplicate_columns([_normalize_column_name(c) for c in original_cols])

    # Rename columns — use safe identifier quoting
    rename_exprs = [
        f'{_sanitize_identifier(orig)} AS {_sanitize_identifier(norm)}'
        for orig, norm in zip(original_cols, normalized)
    ]
    select_sql = ", ".join(rename_exprs)

    # Check if raw_data exists for append
    table_exists = False
    try:
        db.execute("SELECT 1 FROM raw_data LIMIT 0")
        table_exists = True
    except Exception:
        pass

    # Use parameterised path via DuckDB's read_csv_auto($1) syntax
    if append and table_exists:
        db.execute(f"INSERT INTO raw_data SELECT {select_sql} FROM read_csv_auto(?)", [path])
    else:
        db.execute(f"CREATE OR REPLACE TABLE raw_data AS SELECT {select_sql} FROM read_csv_auto(?)", [path])

    row_count_result = db.execute("SELECT COUNT(*) FROM raw_data").fetchone()
    return row_count_result[0] if row_count_result else 0, normalized


def _import_xlsx(db: duckdb.DuckDBPyConnection, path: str, append: bool = False) -> tuple[int, list[str]]:
    """Import an XLSX file via Polars, then load into DuckDB via temp Parquet.

    Avoids the pyarrow dependency that DuckDB's direct DataFrame registration requires.
    Polars can write Parquet natively; DuckDB reads it natively — no pyarrow needed.
    """
    df = pl.read_excel(path, engine="openpyxl")

    original_cols = df.columns
    normalized = _deduplicate_columns([_normalize_column_name(c) for c in original_cols])

    rename_map = dict(zip(original_cols, normalized))
    df = df.rename(rename_map)

    # Cast Null-dtype columns to String — Polars marks all-null XLSX columns
    # as pl.Null which Parquet cannot represent with a usable schema.
    null_cols = [c for c in df.columns if df[c].dtype == pl.Null]
    if null_cols:
        df = df.with_columns([pl.lit(None).cast(pl.Utf8).alias(c) for c in null_cols])
        logger.info("Cast %d all-null columns to String: %s", len(null_cols), null_cols)

    # Check if raw_data exists for append
    table_exists = False
    try:
        db.execute("SELECT 1 FROM raw_data LIMIT 0")
        table_exists = True
    except Exception:
        pass

    # Write to a temp Parquet file so DuckDB can read it without pyarrow
    tmp_parquet = Path(path).with_suffix(".tmp.parquet")
    try:
        df.write_parquet(str(tmp_parquet))
        parquet_path = str(tmp_parquet)
        if append and table_exists:
            db.execute(
                "INSERT INTO raw_data SELECT * FROM read_parquet(?)",
                [parquet_path],
            )
        else:
            db.execute(
                "CREATE OR REPLACE TABLE raw_data AS SELECT * FROM read_parquet(?)",
                [parquet_path],
            )
    finally:
        tmp_parquet.unlink(missing_ok=True)

    row_count = len(df)
    return row_count, normalized


@router.get("/imports", response_model=list[ImportRecord])
async def list_imports() -> list[dict[str, Any]]:
    """Return all past import records."""
    db = get_db()
    rows = db.execute(
        "SELECT import_id, filename, file_type, row_count, "
        "imported_at::VARCHAR AS imported_at, column_names, notes "
        "FROM imports ORDER BY import_id DESC"
    ).fetchall()
    cols = ["import_id", "filename", "file_type", "row_count", "imported_at", "column_names", "notes"]
    return [dict(zip(cols, row)) for row in rows]


@router.get("/columns", response_model=ColumnsResponse)
async def get_columns() -> dict[str, Any]:
    """Return column names of the current raw_data table."""
    db = get_db()
    try:
        desc = db.execute("SELECT * FROM raw_data LIMIT 0").description
        columns = [d[0] for d in desc]
    except duckdb.CatalogException:
        columns = []
    return {"columns": columns}
