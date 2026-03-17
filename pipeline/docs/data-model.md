# Data Model

## Pipeline Overview

```
Power Automate (daily 7:00 AM)
  |
  +-- OneDrive: Projekte/CPLAN/Input/
        |
        +-- InternalCommunicationActivities.csv
        +-- ExternalCommunicationActivities.csv
        +-- CommunicationPacks.csv
        +-- InternalChannels.csv
        +-- ExternalChannels.csv
        +-- TrackingCluster.csv
        |
        v
    process_cplan.py
        |
        +-- output/communications.parquet  (internal + external activities)
        +-- output/packs.parquet           (communication packs)
        +-- output/channels.parquet        (internal + external channels)
        +-- output/clusters.parquet        (tracking clusters)
        +-- data/cplan.db                  (DuckDB with all tables)
        |
        v
    dashboard/index.html                   (DuckDB-WASM, loads parquet in browser)
```

## Tables

### communications

Combined internal and external communication activities.

| Column | Source | Description |
|--------|--------|-------------|
| sp_id | ID | SharePoint list item ID |
| tracking_id | Tracking ID | Full tracking ID (e.g. QRREP-0000058-240709-0000060-EMI) |
| activity_name | Title | Short name of the activity |
| activity_description | Activity | Rich text description (HTML stripped) |
| source_type | (computed) | `internal` or `external` |
| channel | Channel | Communication channel (SP lookup value) |
| start_date | Start date | Activity start datetime (CET) |
| end_date | End date | Activity end datetime (CET) |
| priority | Priority | Priority level (SP lookup value) |
| target_audience | Target audience | Who the activity targets |
| extended_audience | Extended audience | Additional audience |
| business_division | Business Division | Business division(s), comma-separated |
| business_area | Business Area | Business area (GUID stripped) |
| region | Region | Region (GUID stripped) |
| lead | Lead | Lead person display name |
| lead_email | (extracted) | Lead person email from Claims |
| lead_team | Lead Team | Lead team name |
| partner_team | Partner Team | Partner team name |
| news_digest | News digest | Boolean: included in news digest |
| strategic_objectives | Strategic Objectives | Strategic objective(s) |
| communication_pack | Communication pack | Communication pack reference |
| communication_pack_cpid | Communication pack:C | CPID from pack lookup (internal) |
| communication_ref | Communication | Communication reference |
| campaign | Campaign | Campaign (external only) |
| campaign_ltid | Campaign LTID | Campaign LTID (external) |
| bod_geb | BOD...GEB | BOD/GEB flag |
| author | Author | Author display name |
| author_email | (extracted) | Author email from Claims |
| created | Created | Record created datetime (CET) |
| modified | Modified | Record modified datetime (CET) |
| tracking_cluster_id | (parsed) | Cluster abbreviation from tracking ID |
| tracking_pack_number | (parsed) | Pack number from tracking ID |
| tracking_pub_date | (parsed) | Publication date from tracking ID (YYMMDD) |
| tracking_activity_number | (parsed) | Activity number from tracking ID |
| tracking_channel_abbr | (parsed) | Channel abbreviation from tracking ID |
| tracking_pack_id | (parsed) | Pack ID (cluster + pack number) |
| planning_lead_days | (computed) | Days between created and start_date |
| activity_duration_days | (computed) | Days between start_date and end_date |
| quarter | (computed) | Quarter string (e.g. 2025-Q2) |
| year_month | (computed) | Year-month string (e.g. 2025-06) |

### packs

Communication packs metadata.

| Column | Source | Description |
|--------|--------|-------------|
| cpid | LTID | Communication pack ID (e.g. QRREP-0000058) |
| business_division | Business Division | Division (SP lookup) |
| region | Region | Region (GUID stripped) |
| lead | Lead | Planning lead display name |
| lead_email | (extracted) | Lead email |
| lead_team | Lead Team | Lead team |
| strategic_objective | Objective | Strategic objective |
| start_date | Start date | Pack start date (CET) |
| launch_date | Date of launch | Target launch date (CET) |
| communication_pack_lookup | Long Term lookup | Long-term reference |
| short_description | Brief details | Brief description (HTML stripped) |
| partner_team | Partner Team | Partner team |
| created | Created | Record created (CET) |
| modified | Modified | Record modified (CET) |

### channels

Internal and external communication channels.

| Column | Description |
|--------|-------------|
| channel_id | SharePoint ID |
| channel_name | Full channel name (e.g. "Email - Internal") |
| channel_abbr | Abbreviation used in tracking ID (e.g. "EMI") |
| source_type | `internal` or `external` |

### clusters

Tracking clusters (top-level grouping).

| Column | Description |
|--------|-------------|
| cluster_id | SharePoint ID |
| cluster_name | Full cluster name (e.g. "Financial Results") |
| cluster_abbreviation | Abbreviation used in tracking ID (e.g. "QRREP") |

## Key Joins

```sql
-- Full enrichment query
SELECT
    c.*,
    cl.cluster_name,
    p.strategic_objective AS pack_objective,
    p.short_description AS pack_description,
    ch.channel_name
FROM communications c
LEFT JOIN clusters cl ON c.tracking_cluster_id = cl.cluster_abbreviation
LEFT JOIN packs p ON c.tracking_pack_id = p.cpid
LEFT JOIN channels ch
    ON c.tracking_channel_abbr = ch.channel_abbr
    AND c.source_type = ch.source_type
```
