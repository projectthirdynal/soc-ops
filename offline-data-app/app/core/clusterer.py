"""Clustering pipeline using scikit-learn on person_summary data."""

from __future__ import annotations

import logging
import time
from typing import Any

import duckdb
import numpy as np
from sklearn.cluster import MiniBatchKMeans, Birch
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import silhouette_score

logger = logging.getLogger(__name__)

_ALGORITHMS = {
    "MiniBatchKMeans": MiniBatchKMeans,
    "BIRCH": Birch,
}


def run_clustering(
    db: duckdb.DuckDBPyConnection,
    feature_cols: list[str],
    algorithm: str = "MiniBatchKMeans",
    n_clusters: int = 8,
    batch_size: int = 1024,
) -> dict[str, Any]:
    """Run clustering on person_summary and write cluster_id back.

    Workflow:
        1. Fetch selected feature columns from ``person_summary`` via DuckDB.
        2. StandardScaler normalisation.
        3. Fit the chosen algorithm (MiniBatchKMeans or BIRCH).
        4. Compute silhouette score (sampled if dataset is large).
        5. Write ``cluster_id`` back into ``person_summary``.
        6. Record the run in ``cluster_runs``.

    Args:
        db: Active DuckDB connection.
        feature_cols: Numeric columns in person_summary to use as features.
        algorithm: One of ``"MiniBatchKMeans"`` or ``"BIRCH"``.
        n_clusters: Number of clusters to create.
        batch_size: Batch size for MiniBatchKMeans.

    Returns:
        Dict with ``run_id``, ``silhouette``, ``distribution`` (cluster → count),
        and ``n_clusters``.
    """
    t0 = time.perf_counter()

    if algorithm not in _ALGORITHMS:
        raise ValueError(f"Unsupported algorithm '{algorithm}'. Choose from {list(_ALGORITHMS)}")

    if not feature_cols:
        raise ValueError("At least one feature column is required.")

    # ------------------------------------------------------------------
    # 1. Fetch feature matrix
    # ------------------------------------------------------------------
    col_list = ", ".join(f'"{c}"' for c in feature_cols)
    query = f"SELECT {col_list} FROM person_summary"
    result = db.execute(query).fetchnumpy()

    # Build a numpy array from the dict of arrays
    arrays = [result[c].astype(np.float64) for c in feature_cols]
    X = np.column_stack(arrays)

    # Replace NaN with 0 for clustering
    X = np.nan_to_num(X, nan=0.0)

    n_samples = X.shape[0]
    if n_samples < n_clusters:
        raise ValueError(
            f"Only {n_samples} persons in summary — need at least {n_clusters} for "
            f"{n_clusters} clusters. Reduce n_clusters or aggregate more data."
        )

    logger.info(
        "Clustering %d persons on %d features with %s (k=%d)",
        n_samples,
        len(feature_cols),
        algorithm,
        n_clusters,
    )

    # ------------------------------------------------------------------
    # 2. Scale
    # ------------------------------------------------------------------
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # ------------------------------------------------------------------
    # 3. Fit
    # ------------------------------------------------------------------
    if algorithm == "MiniBatchKMeans":
        model = MiniBatchKMeans(
            n_clusters=n_clusters,
            batch_size=min(batch_size, n_samples),
            random_state=42,
            n_init=3,
        )
    else:
        model = Birch(n_clusters=n_clusters)

    labels = model.fit_predict(X_scaled)

    # ------------------------------------------------------------------
    # 4. Silhouette (sample if large)
    # ------------------------------------------------------------------
    sil: float = -1.0
    if n_samples > 1 and n_clusters > 1:
        sample_size = min(10_000, n_samples)
        sil = float(
            silhouette_score(
                X_scaled,
                labels,
                sample_size=sample_size,
                random_state=42,
            )
        )
    logger.info("Silhouette score: %.4f", sil)

    # ------------------------------------------------------------------
    # 5. Write cluster_id back
    # ------------------------------------------------------------------
    # Add a row_number column to person_summary for joining
    db.execute("ALTER TABLE person_summary DROP COLUMN IF EXISTS cluster_id")
    db.execute("ALTER TABLE person_summary ADD COLUMN cluster_id INTEGER")

    # Write labels back via a temp table keyed on person_key
    db.execute("CREATE OR REPLACE TEMP TABLE _cluster_labels (rn INTEGER, cluster_id INTEGER)")
    label_data = [(int(i + 1), int(labels[i])) for i in range(len(labels))]
    db.executemany("INSERT INTO _cluster_labels VALUES (?, ?)", label_data)

    # Match rows by row-number order (same SELECT order used to fetch features)
    db.execute("""
        WITH numbered AS (
            SELECT ROW_NUMBER() OVER () AS rn, person_key
            FROM person_summary
        )
        UPDATE person_summary
        SET cluster_id = cl.cluster_id
        FROM numbered n
        JOIN _cluster_labels cl ON cl.rn = n.rn
        WHERE person_summary.person_key = n.person_key
    """)

    db.execute("DROP TABLE IF EXISTS _cluster_labels")

    # ------------------------------------------------------------------
    # 6. Record run
    # ------------------------------------------------------------------
    db.execute(
        """
        INSERT INTO cluster_runs (algorithm, n_clusters, feature_columns, silhouette_score)
        VALUES (?, ?, ?, ?)
        """,
        [algorithm, n_clusters, feature_cols, sil],
    )

    run_id_result = db.execute(
        "SELECT MAX(run_id) FROM cluster_runs"
    ).fetchone()
    run_id: int = run_id_result[0] if run_id_result else 0

    # ------------------------------------------------------------------
    # 7. Build distribution
    # ------------------------------------------------------------------
    dist_rows = db.execute(
        "SELECT cluster_id, COUNT(*) AS cnt FROM person_summary GROUP BY cluster_id ORDER BY cluster_id"
    ).fetchall()
    distribution = {int(r[0]): int(r[1]) for r in dist_rows}

    elapsed = time.perf_counter() - t0
    logger.info(
        "Clustering complete in %.2fs: algorithm=%s, k=%d, silhouette=%.4f, samples=%d",
        elapsed, algorithm, n_clusters, sil, n_samples,
    )

    return {
        "run_id": run_id,
        "algorithm": algorithm,
        "n_clusters": n_clusters,
        "silhouette": round(sil, 4),
        "distribution": distribution,
        "total_persons": n_samples,
    }
