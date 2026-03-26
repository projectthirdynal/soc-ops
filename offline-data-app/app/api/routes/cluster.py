"""Clustering endpoints — run ML clustering and export results."""

from __future__ import annotations

import csv
import io
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.database import get_db
from app.core.clusterer import run_clustering
from app.api import acquire_operation, release_operation

logger = logging.getLogger(__name__)
router = APIRouter()


class ClusterRequest(BaseModel):
    """Parameters for a clustering run."""
    feature_cols: list[str]
    algorithm: str = Field(default="MiniBatchKMeans", pattern="^(MiniBatchKMeans|BIRCH)$")
    n_clusters: int = Field(default=8, ge=2, le=100)


class ClusterResult(BaseModel):
    """Result of a clustering run."""
    run_id: int
    algorithm: str
    n_clusters: int
    silhouette: float
    distribution: dict[str, int]
    total_persons: int


class ClusterHistory(BaseModel):
    """A single cluster run history entry."""
    run_id: int
    algorithm: str
    n_clusters: int
    feature_columns: list[str]
    run_at: str
    silhouette_score: float


class PaginatedClusterResults(BaseModel):
    """Paginated view of clustered person_summary."""
    columns: list[str]
    rows: list[dict[str, Any]]
    total: int
    page: int
    page_size: int


@router.post("/cluster", response_model=ClusterResult)
async def run_cluster(req: ClusterRequest) -> dict[str, Any]:
    """Run clustering on person_summary.

    Requires that aggregation has already been performed.
    """
    db = get_db()

    try:
        desc = db.execute("SELECT * FROM person_summary LIMIT 0").description
    except Exception:
        raise HTTPException(status_code=400, detail="person_summary not yet created. Run aggregation first.")

    available = [d[0] for d in desc]
    for col in req.feature_cols:
        if col not in available:
            raise HTTPException(
                status_code=400,
                detail=f"Column '{col}' not in person_summary. Available: {available}",
            )

    logger.info(
        "Clustering started: algorithm=%s, n_clusters=%d, features=%s",
        req.algorithm, req.n_clusters, req.feature_cols,
    )

    acquire_operation("cluster")
    try:
        result = run_clustering(
            db,
            feature_cols=req.feature_cols,
            algorithm=req.algorithm,
            n_clusters=req.n_clusters,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Clustering failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        release_operation()

    logger.info(
        "Clustering complete: run_id=%d, silhouette=%.4f, total_persons=%d",
        result["run_id"], result["silhouette"], result["total_persons"],
    )

    # Convert int keys to str for JSON serialisation
    result["distribution"] = {str(k): v for k, v in result["distribution"].items()}
    return result


@router.get("/cluster/results", response_model=PaginatedClusterResults)
async def cluster_results(
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=500),
) -> dict[str, Any]:
    """Return paginated clustered person_summary data."""
    db = get_db()

    try:
        desc = db.execute("SELECT * FROM person_summary LIMIT 0").description
    except Exception:
        raise HTTPException(status_code=400, detail="person_summary not yet created.")

    columns = [d[0] for d in desc]

    if "cluster_id" not in columns:
        raise HTTPException(status_code=400, detail="No clustering has been run yet.")

    total_result = db.execute("SELECT COUNT(*) FROM person_summary").fetchone()
    total = total_result[0] if total_result else 0

    offset = (page - 1) * size
    rows = db.execute(
        "SELECT * FROM person_summary ORDER BY cluster_id LIMIT ? OFFSET ?", [size, offset]
    ).fetchall()

    return {
        "columns": columns,
        "rows": [dict(zip(columns, row)) for row in rows],
        "total": total,
        "page": page,
        "page_size": size,
    }


@router.get("/cluster/history")
async def cluster_history() -> list[dict[str, Any]]:
    """Return all past cluster run records."""
    db = get_db()
    rows = db.execute(
        "SELECT run_id, algorithm, n_clusters, feature_columns, "
        "run_at::VARCHAR AS run_at, silhouette_score "
        "FROM cluster_runs ORDER BY run_id DESC"
    ).fetchall()
    cols = ["run_id", "algorithm", "n_clusters", "feature_columns", "run_at", "silhouette_score"]
    return [dict(zip(cols, row)) for row in rows]


@router.get("/cluster/export")
async def export_clustered() -> StreamingResponse:
    """Export clustered person_summary as a streaming CSV file download."""
    db = get_db()

    try:
        desc = db.execute("SELECT * FROM person_summary LIMIT 0").description
    except Exception:
        raise HTTPException(status_code=400, detail="person_summary not yet created.")

    columns = [d[0] for d in desc]
    if "cluster_id" not in columns:
        raise HTTPException(status_code=400, detail="No clustering has been run yet.")

    total_result = db.execute("SELECT COUNT(*) FROM person_summary").fetchone()
    total = total_result[0] if total_result else 0

    def _csv_generator():
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(columns)
        yield buf.getvalue()

        chunk = 10_000
        for offset in range(0, total, chunk):
            buf = io.StringIO()
            writer = csv.writer(buf)
            rows = db.execute(
                "SELECT * FROM person_summary ORDER BY cluster_id LIMIT ? OFFSET ?",
                [chunk, offset],
            ).fetchall()
            writer.writerows(rows)
            yield buf.getvalue()

    return StreamingResponse(
        _csv_generator(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=clustered_person_summary.csv"},
    )
