"""Dashboard endpoints — summary statistics and chart-ready data."""

from __future__ import annotations

import logging
import time
from typing import Any

import duckdb
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.core.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter()

# Threshold in seconds above which a dashboard query triggers a warning log
_SLOW_QUERY_THRESHOLD = 1.0

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NUMERIC_TYPES = {"INTEGER", "BIGINT", "DOUBLE", "FLOAT", "DECIMAL",
                  "HUGEINT", "INT4", "INT8", "FLOAT4", "FLOAT8", "INT2",
                  "SMALLINT", "TINYINT", "UBIGINT", "UINTEGER"}
_DATETIME_TYPES = {"TIMESTAMP", "DATE", "TIMESTAMP WITH TIME ZONE",
                   "TIMESTAMP_NS", "TIMESTAMP_MS", "TIMESTAMP_S"}


def _table_exists(db: duckdb.DuckDBPyConnection, table: str) -> bool:
    """Return True if the named table exists in DuckDB."""
    try:
        db.execute(f'SELECT 1 FROM "{table}" LIMIT 0')
        return True
    except Exception:
        return False


def _validate_column(db: duckdb.DuckDBPyConnection, table: str, col: str) -> None:
    """Raise HTTPException if *col* is not a real column in *table*.

    This prevents SQL injection via user-supplied column names — only names
    that actually exist in the table schema are accepted.
    """
    info = _col_info(db) if table == "raw_data" else {}
    if table != "raw_data":
        # Generic path: query the table schema directly
        if not _table_exists(db, table):
            raise HTTPException(status_code=400, detail=f"Table '{table}' does not exist.")
        desc = db.execute(f'SELECT * FROM "{table}" LIMIT 0').description
        info = {d[0]: str(d[1]).upper() if d[1] else "" for d in desc}
    if col not in info:
        raise HTTPException(
            status_code=400,
            detail=f"Column '{col}' not found in {table}. Available: {sorted(info.keys())}",
        )


def _col_info(db: duckdb.DuckDBPyConnection) -> dict[str, str]:
    """Return {column_name: dtype_str} for raw_data, or {} if missing.

    Uses str() on the type code because DuckDB returns a DuckDBPyType object
    in newer versions rather than a plain string.
    """
    if not _table_exists(db, "raw_data"):
        return {}
    try:
        desc = db.execute("SELECT * FROM raw_data LIMIT 0").description
        return {d[0]: str(d[1]).upper() if d[1] else "" for d in desc}
    except Exception:
        logger.exception("_col_info failed")
        return {}


def _classify_cols(
    col_map: dict[str, str],
) -> tuple[list[str], list[str], list[str]]:
    """Split columns into (numeric, datetime, string) lists."""
    numeric, datetimes, strings = [], [], []
    for col, dtype in col_map.items():
        if any(t in dtype for t in _NUMERIC_TYPES):
            numeric.append(col)
        elif any(t in dtype for t in _DATETIME_TYPES):
            datetimes.append(col)
        else:
            strings.append(col)
    return numeric, datetimes, strings


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class SummaryResponse(BaseModel):
    """High-level summary of imported data."""
    has_data: bool
    row_count: int
    col_count: int
    columns: list[str]
    numeric_cols: list[str]
    datetime_cols: list[str]
    string_cols: list[str]
    detected_type: str  # "soc" | "generic" | "none"


class MetricCard(BaseModel):
    """A single KPI card for the dashboard."""
    label: str
    value: str
    icon: str


class DistributionItem(BaseModel):
    """One slice of a categorical distribution."""
    label: str
    count: int
    pct: float


class TopByItem(BaseModel):
    """One bar in a ranked bar chart."""
    label: str
    value: float


class TimelineItem(BaseModel):
    """One point on a time-series chart."""
    date: str
    value: float


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/dashboard/summary", response_model=SummaryResponse)
async def get_summary() -> dict[str, Any]:
    """Return column classification and row count for the imported dataset."""
    t0 = time.perf_counter()
    db = get_db()
    info = _col_info(db)
    if not info:
        return {
            "has_data": False,
            "row_count": 0,
            "col_count": 0,
            "columns": [],
            "numeric_cols": [],
            "datetime_cols": [],
            "string_cols": [],
            "detected_type": "none",
        }

    row_count: int = db.execute("SELECT COUNT(*) FROM raw_data").fetchone()[0]
    numeric, datetimes, strings = _classify_cols(info)

    # Detect Claims-specific schema (normalized column names after upload)
    # CLAIMS NAME → claims_name, TRACKING NUMBER → tracking_number, NAME → name, HUB → hub
    soc_markers = {"claims_name", "cogs_share_local", "name", "hub"}
    detected = "soc" if soc_markers.issubset(info.keys()) else "generic"

    elapsed = time.perf_counter() - t0
    if elapsed > _SLOW_QUERY_THRESHOLD:
        logger.warning("Slow dashboard/summary query: %.2fs", elapsed)

    return {
        "has_data": True,
        "row_count": row_count,
        "col_count": len(info),
        "columns": list(info.keys()),
        "numeric_cols": numeric,
        "datetime_cols": datetimes,
        "string_cols": strings,
        "detected_type": detected,
    }


@router.get("/dashboard/metrics", response_model=list[MetricCard])
async def get_metrics() -> list[dict[str, Any]]:
    """Return KPI metric cards — SOC-aware when applicable."""
    t0 = time.perf_counter()
    db = get_db()
    info = _col_info(db)
    if not info:
        return []

    cols = set(info.keys())
    cards: list[dict[str, Any]] = []

    try:
        total: int = db.execute("SELECT COUNT(*) FROM raw_data").fetchone()[0]
        cards.append({"label": "Total Claims", "value": f"{total:,}", "icon": "📋"})

        # Claims format (normalized column names): claims_name, tracking_number, cogs_share_local, name, hub
        if "claims_name" in cols:
            n: int = db.execute(
                "SELECT COUNT(DISTINCT claims_name) FROM raw_data"
            ).fetchone()[0]
            cards.append({"label": "Total Premises", "value": f"{n:,}", "icon": "🏠"})

        if "cogs_share_local" in cols:
            avg_val = db.execute(
                "SELECT AVG(CAST(cogs_share_local AS DOUBLE)) FROM raw_data"
            ).fetchone()[0] or 0.0
            cards.append({
                "label": "Avg COGS Share",
                "value": f"{avg_val:.3f}",
                "icon": "📊",
            })

        if "hub" in cols:
            n = db.execute("SELECT COUNT(DISTINCT hub) FROM raw_data").fetchone()[0]
            cards.append({"label": "Active Hubs", "value": f"{n:,}", "icon": "🏭"})

        if "name" in cols:
            n = db.execute("SELECT COUNT(DISTINCT name) FROM raw_data").fetchone()[0]
            cards.append({"label": "Total Operators", "value": f"{n:,}", "icon": "👤"})

        if "cogs_share_local" in cols:
            val = db.execute(
                "SELECT SUM(CAST(cogs_share_local AS DOUBLE)) FROM raw_data"
            ).fetchone()[0] or 0.0
            cards.append({
                "label": "Lost Item Value",
                "value": f"{val:,.2f}",
                "icon": "💸",
            })

        # Legacy / generic fallbacks
        if "claims_name" not in cols:
            if "tracking_number" in cols:
                n = db.execute(
                    "SELECT COUNT(DISTINCT tracking_number) FROM raw_data"
                ).fetchone()[0]
                cards.append({"label": "Unique Parcels", "value": f"{n:,}", "icon": "🔍"})

            if "operator" in cols:
                n = db.execute(
                    "SELECT COUNT(DISTINCT operator) FROM raw_data"
                ).fetchone()[0]
                cards.append({"label": "Unique Operators", "value": f"{n:,}", "icon": "👤"})

            if "cogs_local" in cols:
                cogs_val = db.execute("SELECT SUM(cogs_local) FROM raw_data").fetchone()[0] or 0
                cards.append({
                    "label": "Total COGS (Local)",
                    "value": f"\u20b1{cogs_val:,.0f}",
                    "icon": "💰",
                })

            if "type_of_lost" in cols:
                lrows = db.execute(
                    "SELECT type_of_lost, COUNT(*) FROM raw_data "
                    "WHERE type_of_lost IS NOT NULL "
                    "GROUP BY type_of_lost ORDER BY 2 DESC"
                ).fetchall()
                for t, c in lrows:
                    cards.append({"label": f"Lost Type: {t}", "value": f"{c:,}", "icon": "⚠️"})

        elapsed = time.perf_counter() - t0
        if elapsed > _SLOW_QUERY_THRESHOLD:
            logger.warning("Slow dashboard/metrics query: %.2fs", elapsed)

        return cards

    except Exception as exc:
        logger.exception("metrics error")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/dashboard/distribution", response_model=list[DistributionItem])
async def get_distribution(
    column: str = Query(..., description="Column to group by"),
    limit: int = Query(15, ge=1, le=50),
) -> list[dict[str, Any]]:
    """Return value distribution for any categorical column."""
    t0 = time.perf_counter()
    db = get_db()
    info = _col_info(db)
    if not info:
        return []
    _validate_column(db, "raw_data", column)

    try:
        total: int = db.execute("SELECT COUNT(*) FROM raw_data").fetchone()[0]
        rows = db.execute(
            f"""
            SELECT
                COALESCE(CAST("{column}" AS VARCHAR), '(null)') AS label,
                COUNT(*) AS cnt
            FROM raw_data
            GROUP BY "{column}"
            ORDER BY cnt DESC
            LIMIT ?
            """,
            [limit],
        ).fetchall()
        result = [
            {
                "label": r[0],
                "count": r[1],
                "pct": round(r[1] / total * 100, 1) if total else 0.0,
            }
            for r in rows
        ]
        elapsed = time.perf_counter() - t0
        if elapsed > _SLOW_QUERY_THRESHOLD:
            logger.warning("Slow dashboard/distribution query (column=%s): %.2fs", column, elapsed)
        return result
    except Exception as exc:
        logger.exception("distribution error for %s", column)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/dashboard/top-by", response_model=list[TopByItem])
async def get_top_by(
    group_col: str = Query(..., description="Column to group by"),
    value_col: str = Query(..., description="Column to aggregate"),
    agg: str = Query("sum", pattern="^(sum|avg|count|min|max)$"),
    limit: int = Query(10, ge=1, le=50),
) -> list[dict[str, Any]]:
    """Return top groups ranked by an aggregated numeric value."""
    t0 = time.perf_counter()
    db = get_db()
    info = _col_info(db)
    if not info:
        return []

    for col in [group_col, value_col]:
        _validate_column(db, "raw_data", col)

    agg_fn = agg.upper()
    value_expr = (
        "COUNT(*)"
        if agg_fn == "COUNT"
        else f'{agg_fn}(CAST("{value_col}" AS DOUBLE))'
    )

    try:
        rows = db.execute(
            f"""
            SELECT
                COALESCE(CAST("{group_col}" AS VARCHAR), '(null)') AS label,
                {value_expr} AS val
            FROM raw_data
            GROUP BY "{group_col}"
            ORDER BY val DESC
            LIMIT ?
            """,
            [limit],
        ).fetchall()
        result = [
            {"label": r[0], "value": float(r[1]) if r[1] is not None else 0.0}
            for r in rows
        ]
        elapsed = time.perf_counter() - t0
        if elapsed > _SLOW_QUERY_THRESHOLD:
            logger.warning(
                "Slow dashboard/top-by query (group=%s, value=%s, agg=%s): %.2fs",
                group_col, value_col, agg, elapsed,
            )
        return result
    except Exception as exc:
        logger.exception("top-by error")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/dashboard/timeline", response_model=list[TimelineItem])
async def get_timeline(
    date_col: str = Query(..., description="Datetime column for the X-axis"),
    value_col: str = Query("*", description="Column to aggregate (use * for COUNT)"),
    agg: str = Query("count", pattern="^(sum|avg|count|min|max)$"),
    granularity: str = Query("day", pattern="^(day|week|month)$"),
) -> list[dict[str, Any]]:
    """Return time-series aggregated data for line/area charts."""
    t0 = time.perf_counter()
    db = get_db()
    info = _col_info(db)
    if not info:
        return []
    _validate_column(db, "raw_data", date_col)

    # granularity is already constrained by the Query pattern to day|week|month
    _ALLOWED_GRANULARITY = {"day", "week", "month"}
    if granularity not in _ALLOWED_GRANULARITY:
        raise HTTPException(status_code=400, detail=f"Invalid granularity '{granularity}'.")
    trunc = f"DATE_TRUNC('{granularity}', CAST(\"{date_col}\" AS TIMESTAMP))"

    agg_fn = agg.upper()
    if agg_fn == "COUNT" or value_col == "*":
        value_expr = "COUNT(*)"
    else:
        _validate_column(db, "raw_data", value_col)
        value_expr = f'{agg_fn}(CAST("{value_col}" AS DOUBLE))'

    try:
        rows = db.execute(
            f"""
            SELECT
                {trunc}::VARCHAR AS dt,
                {value_expr} AS val
            FROM raw_data
            WHERE "{date_col}" IS NOT NULL
            GROUP BY {trunc}
            ORDER BY {trunc}
            """
        ).fetchall()
        result = [
            {"date": (r[0] or "")[:10], "value": float(r[1]) if r[1] is not None else 0.0}
            for r in rows
        ]
        elapsed = time.perf_counter() - t0
        if elapsed > _SLOW_QUERY_THRESHOLD:
            logger.warning(
                "Slow dashboard/timeline query (date=%s, value=%s, gran=%s): %.2fs",
                date_col, value_col, granularity, elapsed,
            )
        return result
    except Exception as exc:
        logger.exception("timeline error")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/dashboard/cogs-distribution", response_model=list[DistributionItem])
async def get_cogs_distribution() -> list[dict[str, Any]]:
    """Return binned distribution of cogs_share_local into 0.2-width buckets."""
    t0 = time.perf_counter()
    db = get_db()
    info = _col_info(db)
    if not info or "cogs_share_local" not in info:
        return []

    try:
        total: int = db.execute("SELECT COUNT(*) FROM raw_data WHERE cogs_share_local IS NOT NULL").fetchone()[0]
        if total == 0:
            return []

        bins = [
            ("0.0–0.2", 0.0, 0.2),
            ("0.2–0.4", 0.2, 0.4),
            ("0.4–0.6", 0.4, 0.6),
            ("0.6–0.8", 0.6, 0.8),
            ("0.8–1.0", 0.8, 1.0),
        ]
        result = []
        for label, lo, hi in bins:
            cnt: int = db.execute(
                "SELECT COUNT(*) FROM raw_data "
                "WHERE CAST(cogs_share_local AS DOUBLE) >= ? AND CAST(cogs_share_local AS DOUBLE) < ?",
                [lo, hi],
            ).fetchone()[0]
            result.append({
                "label": label,
                "count": cnt,
                "pct": round(cnt / total * 100, 1) if total else 0.0,
            })

        elapsed = time.perf_counter() - t0
        if elapsed > _SLOW_QUERY_THRESHOLD:
            logger.warning("Slow dashboard/cogs-distribution query: %.2fs", elapsed)
        return result
    except Exception as exc:
        logger.exception("cogs-distribution error")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/dashboard/hub-performance")
async def get_hub_performance(limit: int = Query(10, ge=1, le=30)) -> list[dict[str, Any]]:
    """Return per-hub claims count and average COGS share."""
    t0 = time.perf_counter()
    db = get_db()
    info = _col_info(db)
    if not info or "hub" not in info:
        return []

    try:
        rows = db.execute(
            """
            SELECT
                COALESCE(CAST(hub AS VARCHAR), '(null)') AS hub,
                COUNT(*) AS claims,
                AVG(CAST(cogs_share_local AS DOUBLE)) AS avg_cogs
            FROM raw_data
            GROUP BY hub
            ORDER BY claims DESC
            LIMIT ?
            """,
            [limit],
        ).fetchall()
        result = [
            {
                "hub": r[0],
                "claims": int(r[1]),
                "avg_cogs": round(float(r[2]) if r[2] is not None else 0.0, 4),
            }
            for r in rows
        ]
        elapsed = time.perf_counter() - t0
        if elapsed > _SLOW_QUERY_THRESHOLD:
            logger.warning("Slow dashboard/hub-performance query: %.2fs", elapsed)
        return result
    except Exception as exc:
        logger.exception("hub-performance error")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/dashboard/recent-claims")
async def get_recent_claims(limit: int = Query(20, ge=1, le=100)) -> list[dict[str, Any]]:
    """Return the most recent claim rows for the Recent Claims Records table."""
    db = get_db()
    info = _col_info(db)
    if not info:
        return []

    # Use normalized Claims-format columns when available, else fall back to all columns
    claims_cols = [c for c in ["claims_name", "tracking_number", "cogs_share_local", "name", "hub"] if c in info]
    if not claims_cols:
        claims_cols = list(info.keys())[:6]

    quoted = ", ".join(f'"{c}"' for c in claims_cols)
    try:
        rows = db.execute(f"SELECT {quoted} FROM raw_data LIMIT ?", [limit]).fetchall()
        return [dict(zip(claims_cols, r)) for r in rows]
    except Exception as exc:
        logger.exception("recent-claims error")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
