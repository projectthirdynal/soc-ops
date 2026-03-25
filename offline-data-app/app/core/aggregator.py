"""Aggregate raw_data into a person_summary table via dynamic DuckDB SQL."""

from __future__ import annotations

import logging
import time
from typing import Optional

import duckdb

logger = logging.getLogger(__name__)


def aggregate_persons(
    db: duckdb.DuckDBPyConnection,
    person_key: str,
    numeric_cols: list[str] | None = None,
    date_cols: list[str] | None = None,
    category_cols: list[str] | None = None,
) -> dict:
    """Build a person-level summary table from raw_data.

    The function constructs a dynamic ``GROUP BY`` query that applies
    appropriate aggregations per column type:

    - **numeric_cols**: SUM, AVG, MIN, MAX, COUNT
    - **date_cols**: MIN (earliest), MAX (latest)
    - **category_cols**: MODE (most frequent value), COUNT DISTINCT

    The resulting table ``person_summary`` replaces any previous version.

    Args:
        db: Active DuckDB connection.
        person_key: Column name used to identify a person.
        numeric_cols: Columns to aggregate numerically.
        date_cols: Columns to aggregate as dates.
        category_cols: Columns to aggregate categorically.

    Returns:
        Dict with ``columns`` (list[str]) and ``row_count`` (int).
    """
    numeric_cols = numeric_cols or []
    date_cols = date_cols or []
    category_cols = category_cols or []

    if not person_key:
        raise ValueError("person_key is required for aggregation.")

    # Validate all column names against the actual raw_data schema
    try:
        desc = db.execute("SELECT * FROM raw_data LIMIT 0").description
    except Exception as exc:
        raise ValueError("raw_data table does not exist.") from exc

    available_cols = {d[0] for d in desc}
    all_requested = [person_key] + numeric_cols + date_cols + category_cols
    invalid = [c for c in all_requested if c not in available_cols]
    if invalid:
        raise ValueError(
            f"Column(s) not found in raw_data: {invalid}. "
            f"Available: {sorted(available_cols)}"
        )

    select_parts: list[str] = [f'"{person_key}"', "COUNT(*) AS record_count"]

    for col in numeric_cols:
        q = f'"{col}"'
        select_parts.extend(
            [
                f"SUM({q}) AS \"{col}_sum\"",
                f"AVG({q}) AS \"{col}_avg\"",
                f"MIN({q}) AS \"{col}_min\"",
                f"MAX({q}) AS \"{col}_max\"",
            ]
        )

    for col in date_cols:
        q = f'"{col}"'
        select_parts.extend(
            [
                f"MIN({q}) AS \"{col}_earliest\"",
                f"MAX({q}) AS \"{col}_latest\"",
            ]
        )

    for col in category_cols:
        q = f'"{col}"'
        select_parts.extend(
            [
                f"MODE({q}) AS \"{col}_mode\"",
                f"COUNT(DISTINCT {q}) AS \"{col}_nunique\"",
            ]
        )

    select_clause = ",\n    ".join(select_parts)
    sql = f"""
    CREATE OR REPLACE TABLE person_summary AS
    SELECT
        {select_clause}
    FROM raw_data
    GROUP BY "{person_key}"
    """

    logger.info(
        "Running aggregation grouped by '%s' (numeric=%d, date=%d, category=%d cols)",
        person_key, len(numeric_cols), len(date_cols), len(category_cols),
    )
    logger.debug("Aggregation SQL:\n%s", sql)

    t0 = time.perf_counter()
    db.execute(sql)
    elapsed = time.perf_counter() - t0

    row_count_result = db.execute("SELECT COUNT(*) FROM person_summary").fetchone()
    row_count: int = row_count_result[0] if row_count_result else 0

    columns = [desc[0] for desc in db.execute("SELECT * FROM person_summary LIMIT 0").description]

    logger.info(
        "person_summary created: %d rows, %d columns in %.2fs",
        row_count, len(columns), elapsed,
    )
    return {"columns": columns, "row_count": row_count}
