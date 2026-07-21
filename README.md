# CPLAN - Communication Planning Dashboard

Python pipeline that reads communication activity CSVs (exported via Power Automate from SharePoint Lists) and produces a self-contained HTML dashboard.

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
python pipeline/process_cplan.py

# Preview data without writing outputs
python pipeline/process_cplan.py --preview

# Full refresh (delete DB and reprocess)
python pipeline/process_cplan.py --full-refresh

# Build the standalone (double-clickable) dashboard from the current outputs
python pipeline/build_standalone.py
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
