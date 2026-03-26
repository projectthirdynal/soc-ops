"""Generic file-save export endpoint — saves raw CSV/XLSX directly to Documents."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import openpyxl
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


class SaveRequest(BaseModel):
    """Payload for saving arbitrary CSV data to disk."""
    filename: str          # desired filename (without extension)
    rows: list[list[Any]]  # row data including header as first row


@router.post("/export/save")
async def save_to_disk(req: SaveRequest) -> dict[str, Any]:
    """Save rows as XLSX to Documents/ASN Claims Processor and return the path.

    Used by dashboard and search exports where data is assembled on the
    frontend — posting here lets the backend write it to a real file path
    instead of relying on pywebview's unreliable blob-URL download handler.
    """
    if not req.rows:
        raise HTTPException(status_code=400, detail="No rows provided.")

    out_dir = settings.EXPORTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in req.filename)
    out_path = out_dir / f"{safe_name}_{timestamp}.xlsx"

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = safe_name[:31]  # Excel sheet name limit
    for row in req.rows:
        ws.append([str(v) if v is not None else "" for v in row])
    wb.save(str(out_path))

    logger.info("Export saved: %s (%d rows)", out_path, len(req.rows) - 1)
    return {"path": str(out_path), "filename": out_path.name, "rows": len(req.rows) - 1}


@router.get("/export/default-dir")
async def get_default_dir() -> dict[str, str]:
    """Return the default export directory path (for pre-filling UI fields)."""
    return {"path": str(settings.EXPORTS_DIR)}
