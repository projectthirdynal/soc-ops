"""Aggregation endpoints — build and query person_summary."""

from __future__ import annotations

import io
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.database import get_db
from app.core.aggregator import aggregate_persons
from app.api import acquire_operation, release_operation

logger = logging.getLogger(__name__)
router = APIRouter()


class AggregateRequest(BaseModel):
    """Parameters for an aggregation run."""
    person_key: str
    numeric_cols: list[str] = []
    date_cols: list[str] = []
    category_cols: list[str] = []


class AggregateResult(BaseModel):
    """Result of an aggregation run."""
    columns: list[str]
    row_count: int
    preview: list[dict[str, Any]]


class PaginatedPreview(BaseModel):
    """Paginated view of person_summary."""
    columns: list[str]
    rows: list[dict[str, Any]]
    total: int
    page: int
    page_size: int


@router.post("/aggregate", response_model=AggregateResult)
async def run_aggregation(req: AggregateRequest) -> dict[str, Any]:
    """Run person-level aggregation on raw_data.

    Creates or replaces the ``person_summary`` table and returns a preview
    of the first 50 rows.
    """
    db = get_db()

    # Validate raw_data exists
    try:
        db.execute("SELECT 1 FROM raw_data LIMIT 1")
    except Exception:
        raise HTTPException(status_code=400, detail="No data loaded. Upload a file first.")

    # Validate columns exist
    available = [d[0] for d in db.execute("SELECT * FROM raw_data LIMIT 0").description]
    for col in [req.person_key] + req.numeric_cols + req.date_cols + req.category_cols:
        if col not in available:
            raise HTTPException(
                status_code=400,
                detail=f"Column '{col}' not found in raw_data. Available: {available}",
            )

    logger.info(
        "Aggregation started: person_key=%s, numeric=%s, date=%s, category=%s",
        req.person_key, req.numeric_cols, req.date_cols, req.category_cols,
    )

    acquire_operation("aggregate")
    try:
        result = aggregate_persons(
            db,
            person_key=req.person_key,
            numeric_cols=req.numeric_cols,
            date_cols=req.date_cols,
            category_cols=req.category_cols,
        )
    except Exception as exc:
        logger.exception("Aggregation failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        release_operation()

    logger.info(
        "Aggregation complete: %d rows, %d columns",
        result["row_count"], len(result["columns"]),
    )

    # Fetch preview
    preview_rows = db.execute("SELECT * FROM person_summary LIMIT 50").fetchall()
    columns = result["columns"]
    preview = [dict(zip(columns, row)) for row in preview_rows]

    return {
        "columns": columns,
        "row_count": result["row_count"],
        "preview": preview,
    }


@router.get("/aggregate/preview", response_model=PaginatedPreview)
async def preview_aggregate(
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=500),
) -> dict[str, Any]:
    """Return a paginated view of the person_summary table."""
    db = get_db()

    try:
        desc = db.execute("SELECT * FROM person_summary LIMIT 0").description
    except Exception:
        raise HTTPException(status_code=400, detail="person_summary not yet created. Run aggregation first.")

    columns = [d[0] for d in desc]
    total_result = db.execute("SELECT COUNT(*) FROM person_summary").fetchone()
    total = total_result[0] if total_result else 0

    offset = (page - 1) * size
    rows = db.execute(f"SELECT * FROM person_summary LIMIT {size} OFFSET {offset}").fetchall()

    return {
        "columns": columns,
        "rows": [dict(zip(columns, row)) for row in rows],
        "total": total,
        "page": page,
        "page_size": size,
    }


@router.get("/aggregate/export")
async def export_aggregate() -> StreamingResponse:
    """Export person_summary as a CSV file download."""
    db = get_db()

    try:
        desc = db.execute("SELECT * FROM person_summary LIMIT 0").description
    except Exception:
        raise HTTPException(status_code=400, detail="person_summary not yet created.")

    columns = [d[0] for d in desc]

    # Stream CSV via DuckDB
    import csv

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(columns)

    # Fetch in chunks to avoid loading everything into memory
    total_result = db.execute("SELECT COUNT(*) FROM person_summary").fetchone()
    total = total_result[0] if total_result else 0
    chunk = 10_000
    for offset in range(0, total, chunk):
        rows = db.execute(f"SELECT * FROM person_summary LIMIT {chunk} OFFSET {offset}").fetchall()
        writer.writerows(rows)

    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=person_summary.csv"},
    )


@router.get("/aggregate/columns")
async def get_aggregate_columns() -> dict:
    """Return column names and numeric columns from person_summary."""
    db = get_db()
    try:
        desc = db.execute("SELECT * FROM person_summary LIMIT 0").description
    except Exception:
        return {"columns": [], "numeric_cols": [], "available": False}

    _NUMERIC = {"INTEGER","BIGINT","DOUBLE","FLOAT","HUGEINT","DECIMAL","REAL","SMALLINT","TINYINT","UBIGINT","UINTEGER"}
    columns = [d[0] for d in desc]
    numeric_cols = [d[0] for d in desc if str(d[1]).upper().split("(")[0].strip() in _NUMERIC
                    or any(t in str(d[1]).upper() for t in _NUMERIC)]
    return {"columns": columns, "numeric_cols": numeric_cols, "available": True}
