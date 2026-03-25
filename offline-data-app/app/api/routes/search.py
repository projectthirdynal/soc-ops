"""Search and browse data in the database."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter()


class SearchRequest(BaseModel):
    """Parameters for a search / browse query against raw_data."""

    query: str = ""
    columns: list[str] = []  # empty = search all columns
    page: int = 1
    page_size: int = 50
    sort_column: str = ""
    sort_desc: bool = False


@router.post("/search")
async def search_data(req: SearchRequest) -> dict[str, Any]:
    """Search raw_data with text matching across specified columns.

    If *query* is empty, returns paginated data (browse mode).
    If *columns* is empty, searches all text/varchar columns.
    """
    db = get_db()

    try:
        db.execute("SELECT 1 FROM raw_data LIMIT 1")
    except Exception:
        raise HTTPException(status_code=400, detail="No data loaded.")

    # Get column info
    col_info = db.execute("SELECT * FROM raw_data LIMIT 0").description
    all_cols = [d[0] for d in col_info]

    # Build WHERE clause
    where_parts: list[str] = []
    params: list[str] = []

    if req.query.strip():
        search_term = f"%{req.query.strip()}%"
        # Determine which columns to search
        search_cols = req.columns if req.columns else all_cols
        # Validate columns exist
        search_cols = [c for c in search_cols if c in all_cols]
        if not search_cols:
            search_cols = all_cols

        col_conditions = []
        for col in search_cols:
            col_conditions.append(f'CAST("{col}" AS VARCHAR) ILIKE ?')
            params.append(search_term)

        where_parts.append(f"({' OR '.join(col_conditions)})")

    where_clause = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

    # Count total matching rows
    count_sql = f"SELECT COUNT(*) FROM raw_data {where_clause}"
    total_rows: int = db.execute(count_sql, params).fetchone()[0]

    # Sort
    if req.sort_column and req.sort_column in all_cols:
        direction = "DESC" if req.sort_desc else "ASC"
        order_clause = f'ORDER BY "{req.sort_column}" {direction}'
    else:
        order_clause = "ORDER BY rowid"

    # Paginate
    offset = (req.page - 1) * req.page_size
    data_sql = f"SELECT * FROM raw_data {where_clause} {order_clause} LIMIT ? OFFSET ?"
    data_params: list[Any] = params + [req.page_size, offset]

    rows = db.execute(data_sql, data_params).fetchall()

    result_rows = [dict(zip(all_cols, row)) for row in rows]

    total_pages = max(1, (total_rows + req.page_size - 1) // req.page_size)

    return {
        "rows": result_rows,
        "total_rows": total_rows,
        "total_pages": total_pages,
        "page": req.page,
        "page_size": req.page_size,
        "columns": all_cols,
    }


@router.get("/search/columns")
async def get_searchable_columns() -> dict[str, Any]:
    """Return column names and types for the search UI."""
    db = get_db()
    try:
        col_info = db.execute("SELECT * FROM raw_data LIMIT 0").description
        columns = []
        for d in col_info:
            columns.append({"name": d[0], "type": str(d[1])})
        return {"columns": columns}
    except Exception:
        return {"columns": []}
