---
name: project-architecture
description: Core architectural decisions and table schema for the offline data app
type: project
---

## Project Root

`/home/it-admin/Documents/auto-dave/offline-data-app/`

## DuckDB Tables

- **imports** — tracks every file upload (filename, type, row count, column names, timestamp)
- **raw_data** — the currently loaded dataset (replaced on each new upload)
- **person_summary** — aggregated person-level data (created by the Aggregate step, replaced on re-run)
- **split_exports** — history of split-to-file operations
- **cluster_runs** — history of clustering runs with algorithm, parameters, and silhouette score

Sequences: `seq_import_id`, `seq_export_id`, `seq_cluster_run_id` auto-increment primary keys.

## Processing Flow

1. Upload CSV/XLSX  -->  normalize column names  -->  store as `raw_data`
2. Aggregate  -->  GROUP BY person key  -->  `person_summary`
3. Cluster  -->  StandardScaler + MiniBatchKMeans/BIRCH  -->  `cluster_id` written back to `person_summary`
4. Split/Export  -->  DuckDB COPY for chunk-sized CSV files (export feature, not primary storage)

## Key Decisions

- **Default clustering algorithm**: MiniBatchKMeans (NOT standard KMeans). BIRCH available as second option. DBSCAN not offered.
- **XLSX reading**: Polars `read_excel(engine="openpyxl")` — offline-safe, no DuckDB Excel extension needed.
- **Memory discipline**: Never load full datasets into Python lists/dicts. Use DuckDB SQL or Polars lazy evaluation.
- **Split files**: Export feature only — primary data stays in DuckDB `raw_data`.
- **UI**: Vanilla HTML/JS/CSS, no CDN links, no frameworks. Served as static files by FastAPI.
- **Desktop wrapper**: pywebview. Falls back to system browser if pywebview unavailable.
- **Server**: FastAPI + uvicorn on random localhost port, started in a daemon thread.
- **Packaging**: PyInstaller onedir mode. UI files bundled via `datas` in spec.

## Tech Stack

Python, FastAPI, uvicorn, DuckDB, Polars, scikit-learn, pywebview, PyInstaller, openpyxl
