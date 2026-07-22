# CPLAN - Communication Planning Dashboard

Python pipeline that reads communication activity CSVs (exported via Power Automate from SharePoint Lists) and produces a self-contained HTML dashboard.

## Product knowledge

The organisation-neutral domain model, current SharePoint-backed entry forms, tracking-ID logic, implementation status, and known gaps are documented in [`docs/CPLAN_KNOWLEDGE_BASE.md`](docs/CPLAN_KNOWLEDGE_BASE.md).

Source screenshots are local reference material only. The `pictures/` directory is ignored and must never be committed. Repository content must use generic organisation terminology and synthetic examples; do not include company branding, personal names, production identifiers, or confidential source content.

## Dashboard versions

Two planning studios sit alongside the original Parquet-fed dashboard described below:

- **V6** (`pipeline/dashboard-v6-postgres/`) — the go-forward planning studio. Same analytics as V4, backed by a local FastAPI + PostgreSQL/SQLite API instead of a static snapshot. See [`pipeline/api_v6/README.md`](pipeline/api_v6/README.md) for setup.
- **V4** (`pipeline/dashboard-v4/`) — read-only analytical snapshot with browser-local draft edits. Superseded by V6 for new work; kept as an isolated reference implementation and untouched.

V6's `GET /api/activities` deliberately returns the full result set with no pagination — the deployment target is local, single-user use. Revisit if the dataset outgrows an unpaginated response.

## Architecture

```
OneDrive sync folder          pipeline/
  (or pipeline/input/)          process_cplan.py   <- ETL script
  *.csv  ──────────────────>    data/cplan.db      <- DuckDB database
                                output/communications.parquet
                                output/communications.json
                                dashboard/index.html  <- HTML dashboard
```

## Prerequisites

```
pip install pandas duckdb pyarrow
```

## Usage

```bash
# Process all input CSVs and generate outputs
python pipeline/scripts/process_cplan.py

# Preview data without writing outputs
python pipeline/scripts/process_cplan.py --preview

# Full refresh (delete DB and reprocess)
python pipeline/scripts/process_cplan.py --full-refresh

# Build the standalone (double-clickable) dashboard from the current outputs
python pipeline/scripts/build_standalone.py
```

## Input

The pipeline looks for CSV files in this order:

1. **OneDrive sync folder**: `<OneDrive>/Projekte/CPLAN/Input/*.csv`
2. **Local fallback**: `pipeline/input/*.csv`

Expected files:
- `InternalCommunicationActivities*.csv`
- `ExternalCommunicationActivities*.csv`

## Output

| File | Purpose |
|------|---------|
| `pipeline/data/cplan.db` | DuckDB database |
| `pipeline/output/communications.parquet` | Combined data as Parquet |
| `pipeline/output/communications.json` | JSON for the HTML dashboard |
| `pipeline/dashboard/index.html` | HTML dashboard (loads Parquet via HTTP — needs a local web server) |
| `pipeline/output/cplan_dashboard_standalone.html` | Standalone dashboard — Parquet + meta.json embedded as base64, runs from `file://` by double-click (CDN libs still require internet) |
