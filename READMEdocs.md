# ASN Claims Processor

> Offline desktop application for processing, splitting, and analyzing ASN claims data.
> Built with **FastAPI · DuckDB · Polars · Chart.js · PyInstaller** — no internet required after installation.

---

## Table of Contents

1. [Requirements](#requirements)
2. [Installation](#installation)
3. [First Launch](#first-launch)
4. [Uploading Data](#uploading-data)
5. [Dashboard](#dashboard)
6. [Splitting Files](#splitting-files)
7. [Aggregation](#aggregation)
8. [Clustering](#clustering)
9. [Search](#search)
10. [Exporting Data](#exporting-data)
11. [Setting Up Export & Download Directories](#setting-up-export--download-directories)
12. [Updating the Application](#updating-the-application)
13. [Troubleshooting](#troubleshooting)

---

## Requirements

| Item | Minimum |
|------|---------|
| OS | Windows 10 / 11 (64-bit) |
| RAM | 4 GB (8 GB recommended for large files) |
| Disk | 500 MB free |
| Internet | Only needed for OTA updates |

---

## Installation

### Step 1 — Download the installer

Go to the [Releases page](https://github.com/projectthirdynal/soc-ops/releases/latest) and download:

```
ASNClaimsProcessor-Setup-1.0.2.exe
```

### Step 2 — Run the installer

1. Double-click `ASNClaimsProcessor-Setup-1.0.0.exe`
2. If Windows SmartScreen appears, click **More info → Run anyway**
3. Follow the installer prompts (default install path is recommended)
4. Click **Finish** — the app will launch automatically

### Step 3 — Verify installation

The app window opens showing the **Claims Dashboard**. The status bar at the top will show `No data loaded`.

> **If you have a previous version:** The installer upgrades automatically — your data and settings are preserved.

---

## First Launch

When the app starts for the first time:

1. The **Dashboard** tab is shown — it will display `No data loaded`
2. A default export folder is created automatically at:
   ```
   Documents\ASN Claims Processor\
   ```
3. If an update is available it downloads automatically in the background — a green **Apply Now** button appears when ready

---

## Uploading Data

**Tab: Upload**

### Supported formats
- `.xlsx` — Excel workbook
- `.csv` — Comma-separated values (UTF-8, UTF-16, or Windows CP1252 — auto-detected)

### Steps

1. Click the **Upload** tab
2. Drag and drop your file onto the drop zone **or** click **Browse File**
3. *(Optional)* Check **Append to existing data** to add rows without replacing current data
4. The app imports the file and redirects to the Dashboard automatically

### Expected columns (Claims format)

The app auto-detects the Claims format when these columns are present:

| Column in file | Normalized name | Used for |
|----------------|-----------------|---------|
| `CLAIMS NAME` | `claims_name` | Premise grouping |
| `TRACKING NUMBER` | `tracking_number` | Unique parcel ID |
| `cogs_share_local` | `cogs_share_local` | Value / COGS analysis |
| `NAME` | `name` | Operator name |
| `HUB` | `hub` | Hub filtering |

> Extra columns are imported as-is and available in Search and Split.

---

## Dashboard

**Tab: Dashboard**

After uploading, the dashboard shows:

| Card / Chart | Description |
|---|---|
| **KPI Cards** | Total claims, premises, hubs, operators, lost item value |
| **COGS Share Distribution** | Donut chart — distribution of claim values across 5 equal ranges |
| **Hub Performance Analysis** | Horizontal bar — top 10 hubs by claim count |
| **Top Operator Performance** | Horizontal bar — top operators by claim count |
| **Claims by Premise Type** | Horizontal bar — top premises |
| **Recent Claims Records** | Table of the latest 20 records |

### Hub filter

Use the **HUB** dropdown at the top of the dashboard to filter all charts to a specific hub.

### Refresh

Click the **Refresh** button (top-right of dashboard) to reload all charts with the latest data.

---

## Splitting Files

**Tab: Split**

Splits a large file into smaller XLSX chunks.

### Steps

1. Click the **Split** tab
2. Drag and drop a `.csv` or `.xlsx` file onto the drop zone
3. Set **Rows per file** (default: 1000)
4. Set the **Output folder** — defaults to `Documents\ASN Claims Processor\` automatically
5. Click **Split into XLSX Files**

### Background progress

- A **green progress bar** appears below the header — visible on **all tabs** while splitting runs
- You can freely navigate to other tabs; splitting continues in the background
- A toast notification confirms completion with the file count

### Output

Split files are saved as:
```
Documents\ASN Claims Processor\split_00001.xlsx
Documents\ASN Claims Processor\split_00002.xlsx
...
```

---

## Aggregation

**Tab: Aggregate**

Groups raw data by a person/key column and computes sum, average, count per group.

### Steps

1. Upload data first
2. Click **Aggregate** tab
3. Choose the **Person / Key column** (e.g. `name`)
4. Select **Numeric columns** to sum/average (e.g. `cogs_share_local`)
5. *(Optional)* Select category columns to include as modes
6. Click **Run Aggregation**
7. Preview appears below — click **Export** to save results

---

## Clustering

**Tab: Cluster**

Groups aggregated persons into clusters using K-Means or Mini-Batch K-Means.

### Steps

1. Run **Aggregation** first
2. Click **Cluster** tab
3. Choose **algorithm** (MiniBatchKMeans recommended for large data)
4. Set **number of clusters** (default: 8)
5. Tick the **feature columns** to cluster on (columns ending in `_sum` are pre-selected)
6. Click **Run Clustering**
7. Results show silhouette score and cluster preview
8. Click **Export** to save the clustered results

---

## Search

**Tab: Search**

Full-text search across all imported data.

### Steps

1. Type a search term in the search box
2. *(Optional)* Select specific columns to search within
3. Results appear in a paginated table
4. Click **Export Results** to save the current search results to Excel

---

## Exporting Data

All exports are saved as **XLSX files** directly to:

```
Documents\ASN Claims Processor\
```

A toast notification confirms the save with the exact file path.

| Export type | How to trigger | Filename |
|---|---|---|
| All data (dashboard) | Dashboard → **Export** button | `claims_export_YYYYMMDD_HHMMSS.xlsx` |
| Search results | Search → **Export Results** | `search_results_YYYYMMDD_HHMMSS.xlsx` |
| Aggregated summary | Aggregate → **Export** | `person_summary_YYYYMMDD_HHMMSS.xlsx` |
| Clustered results | Cluster → **Export** | `clustered_persons_YYYYMMDD_HHMMSS.xlsx` |
| Split chunks | Split tab output folder | `split_00001.xlsx`, `split_00002.xlsx`, … |

---

## Setting Up Export & Download Directories

### Default directory

On first launch, the app automatically creates and uses:
```
C:\Users\<YourName>\Documents\ASN Claims Processor\
```

### Changing the export directory

1. Click the **⚙ Settings** icon (top-right of header)
2. Find the **Download / Export Directory** field
3. Enter the full path to your preferred folder, e.g.:
   ```
   D:\Operations\Claims Exports\
   ```
4. Click **Save Settings**

All subsequent exports (aggregate, cluster, dashboard, search) will save to this folder.

### Changing the split output folder

The split output folder is set **per-split** in the Split tab:

1. Click the **Split** tab
2. Edit the **Output Folder** field (pre-filled with the Documents default)
3. Enter any folder path you have write access to

### Update download directory

OTA update installers are also saved to the same Documents folder by default. You can override this in Settings using the same **Download / Export Directory** field.

---

## Updating the Application

### Automatic (recommended)

Updates are fully automatic:

1. On startup, the app checks GitHub for a new version
2. If found, it **downloads the installer silently** in the background
3. A green banner appears: **"Update vX.X.X is ready → Apply Now"**
4. Click **Apply Now** — the installer launches and the app closes
5. Complete the installer steps — your data is preserved

### Manual check

1. Click the **⟳** button in the top-right header
2. The update dialog shows your current version vs. the available version
3. If an update is available, download and install from there

### Checking your version

Your current version is shown at the bottom-right of the app window (e.g. `v1.0.2`).

---

## Troubleshooting

### Upload fails with "Invalid Input Error"

- Make sure the file is `.csv` or `.xlsx`
- For CSV files with encoding issues (exported from Excel), the app auto-converts — if it still fails, re-save the file from Excel as **CSV UTF-8**

### Charts are empty after upload

- Click **Refresh** on the dashboard
- Verify the file has the expected columns (`CLAIMS NAME`, `HUB`, `NAME`, `cogs_share_local`)

### Export file not found

- Check `Documents\ASN Claims Processor\` in File Explorer
- The toast notification shows the exact path — copy it and paste into File Explorer's address bar

### Split seems stuck

- Check the green progress bar below the header — it shows live percentage
- You can switch tabs freely; splitting runs in the background
- If the bar disappears without a toast, check the **Split History** table for results

### Update banner not appearing

- Check your internet connection
- Click **⟳** in the header to manually trigger a check
- Verify the update source is set to `github:projectthirdynal/soc-ops` in Settings

### Application won't open

- Run the installer again — it will repair the installation
- Check Windows Event Viewer → Application log for details

---

## Data Storage

| What | Where |
|------|-------|
| Database | `%LOCALAPPDATA%\offline-data-app\app.duckdb` |
| Uploads (temp) | `%LOCALAPPDATA%\offline-data-app\` (auto-cleaned) |
| Exports | `Documents\ASN Claims Processor\` |
| App logs | `%LOCALAPPDATA%\offline-data-app\app.log` |

---

*Built and maintained by the AsiaNow Operations Team.*
