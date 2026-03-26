"""Data management endpoints — clear/reset user data."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from app.core.database import get_db, close_db

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/data/clear")
async def clear_data(scope: str = "data") -> dict[str, Any]:
    """Drop all user data tables and reset history.

    Query param ``scope``:
      - ``"data"``  (default) — drops raw_data and person_summary only.
                                History tables (imports, split_exports, cluster_runs) are kept.
      - ``"all"``             — drops everything including history tables.
    """
    if scope not in ("data", "all"):
        raise HTTPException(status_code=400, detail="scope must be 'data' or 'all'")

    db = get_db()
    dropped: list[str] = []

    # Always drop the user data tables
    for table in ("raw_data", "person_summary"):
        try:
            db.execute(f'DROP TABLE IF EXISTS "{table}"')
            dropped.append(table)
        except Exception as exc:
            logger.warning("Could not drop %s: %s", table, exc)

    if scope == "all":
        for table in ("imports", "split_exports", "cluster_runs"):
            try:
                db.execute(f'DROP TABLE IF EXISTS "{table}"')
                dropped.append(table)
            except Exception as exc:
                logger.warning("Could not drop %s: %s", table, exc)

        # Re-initialise schema so sequences and history tables exist again
        try:
            from app.core.database import _init_schema
            _init_schema(db)
        except Exception as exc:
            logger.warning("Schema re-init after full clear: %s", exc)

    logger.info("Data cleared (scope=%s): %s", scope, dropped)
    return {"cleared": dropped, "scope": scope}
