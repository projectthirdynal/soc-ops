"""Split raw_data into multiple XLSX files using DuckDB queries and openpyxl."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Generator

import duckdb
from openpyxl import Workbook

logger = logging.getLogger(__name__)


def _row_count(db: duckdb.DuckDBPyConnection) -> int:
    """Return the number of rows in the raw_data table."""
    result = db.execute("SELECT COUNT(*) FROM raw_data").fetchone()
    return result[0] if result else 0


def split_to_files(
    db: duckdb.DuckDBPyConnection,
    output_dir: str | Path,
    chunk_size: int = 1000,
    order_column: str | None = None,
) -> Generator[dict, None, dict]:
    """Split the raw_data table into chunk-sized XLSX files.

    Queries DuckDB for each chunk and writes the rows to an XLSX
    workbook using openpyxl.

    Args:
        db: Active DuckDB connection.
        output_dir: Directory where split files will be written.
        chunk_size: Maximum number of rows per output file.
        order_column: Column to ORDER BY before splitting.  If *None*,
            the natural row order is used (``rowid``).

    Yields:
        Progress dicts ``{"progress": float, "files_written": int}``.

    Returns:
        Summary dict ``{"total_files": int, "total_rows": int, "output_dir": str}``.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    total_rows = _row_count(db)
    if total_rows == 0:
        raise ValueError("raw_data table is empty — nothing to split.")

    total_files = (total_rows + chunk_size - 1) // chunk_size
    order_clause = f'ORDER BY "{order_column}"' if order_column else "ORDER BY rowid"

    # Get column names
    col_info = db.execute("SELECT * FROM raw_data LIMIT 0").description
    col_names = [d[0] for d in col_info]

    logger.info(
        "Splitting %d rows into ~%d XLSX files of %d rows each → %s",
        total_rows,
        total_files,
        chunk_size,
        out,
    )

    t0 = time.perf_counter()
    files_written = 0
    for i in range(total_files):
        offset = i * chunk_size
        file_path = out / f"split_{i + 1:05d}.xlsx"

        query = f"SELECT * FROM raw_data {order_clause} LIMIT {chunk_size} OFFSET {offset}"
        rows = db.execute(query).fetchall()

        # Write XLSX using openpyxl
        wb = Workbook()
        ws = wb.active
        ws.append(col_names)
        for row in rows:
            ws.append(list(row))
        wb.save(str(file_path))

        files_written += 1
        progress = round(files_written / total_files * 100, 1)

        # Log progress every 10% to avoid log spam on large splits
        if files_written == 1 or files_written == total_files or files_written % max(1, total_files // 10) == 0:
            logger.info("Split progress: %d/%d files (%.1f%%)", files_written, total_files, progress)

        yield {"progress": progress, "files_written": files_written}

    elapsed = time.perf_counter() - t0
    logger.info("Split complete: %d XLSX files written in %.2fs.", files_written, elapsed)
    # The generator's return value is accessible via StopIteration.value
    return {"total_files": files_written, "total_rows": total_rows, "output_dir": str(out)}
