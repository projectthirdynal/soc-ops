---
name: soc-data-format
description: Schema, column types, and SOC-specific defaults for soc.xlsx — the primary dataset for this app
type: project
---

## File: soc.xlsx

**Shape:** 69,410 rows × 18 columns — logistics/warehouse lost-parcel tracking data

**Why:** This is the confirmed production data format the app must handle. SOC = Station Operations Center.

**Normalized column names (after import):**

| Original Column Name        | Normalized Name              | Type      | Notes                                    |
|-----------------------------|------------------------------|-----------|------------------------------------------|
| TRACKING NUMBER             | tracking_number              | String    | Parcel ID; 6,174 unique values           |
| lost_status                 | lost_status                  | String    | 49 unique statuses (e.g. "Return_SOC_Received") |
| lost_status_time            | lost_status_time             | Datetime  | Primary date column for timeline charts  |
| cogs_local                  | cogs_local                   | Int64     | Cost of goods; range 1–84,380            |
| station_reference           | station_reference            | String    | Hub/station name; 128 unique values      |
| activity_type               | activity_type                | String    | 5 values: packer, sorting, receiver, inbound, outbound |
| ops_id                      | ops_id                       | String    | 97.7% NULL — mostly missing              |
| operator                    | operator                     | String    | **Person key** for aggregation; 1,236 unique |
| first_clock_in              | first_clock_in               | String    | 97.7% NULL                               |
| last_clock_out              | last_clock_out               | String    | 97.7% NULL                               |
| station_activity_total_ops  | station_activity_total_ops   | Int64     | Ops count at station                     |
| agency_ops_count            | agency_ops_count             | Int64     | Agency-level ops count                   |
| entity_to_charge            | entity_to_charge             | String    | Always "ASN" (1 unique value)            |
| cogs_share_local            | cogs_share_local             | Float64   | Per-operator COGS share; 0–1,403         |
| Type of Lost                | type_of_lost                 | String    | 3 values: SOC, SHORT, HUB                |
| Link                        | link                         | String    | Google Docs links (7 unique) — ignore    |
| Agency remarks              | agency_remarks               | String    | 100% NULL                                |
| Claims remarks              | claims_remarks               | String    | 100% NULL                                |

**SOC detection fingerprint** (used in `/api/dashboard/summary`):
- Columns present: `tracking_number`, `lost_status`, `cogs_local`, `type_of_lost`

**Default app settings for SOC data:**
- Person/group key: `operator`
- Numeric cols for aggregation: `cogs_local`, `cogs_share_local`, `station_activity_total_ops`, `agency_ops_count`
- Date cols: `lost_status_time`
- Category cols: `lost_status`, `station_reference`, `activity_type`, `type_of_lost`
- Timeline date col: `lost_status_time`
- Dashboard pie chart 1: `type_of_lost` distribution
- Dashboard pie chart 2: `activity_type` distribution
- Top-by chart 1: top `station_reference` by SUM(`cogs_local`)
- Top-by chart 2: top `operator` by COUNT(*)
- Clustering features: `cogs_local`, `cogs_share_local`, `station_activity_total_ops`, `agency_ops_count`

**How to apply:** When the app detects SOC schema, pre-select all these defaults in the UI dropdowns and checkboxes. The JS constant `SOC_DEFAULTS` in `app.js` holds these values.
