# CPLAN - Communication Planning Dashboard

Python pipeline that reads communication activity CSVs (exported via Power Automate from SharePoint Lists) and produces a self-contained HTML dashboard.

## Product knowledge

The organisation-neutral domain model, current SharePoint-backed entry forms, tracking-ID logic, implementation status, and known gaps are documented in [`docs/CPLAN_KNOWLEDGE_BASE.md`](docs/CPLAN_KNOWLEDGE_BASE.md).

Source screenshots are local reference material only. The `pictures/` directory is ignored and must never be committed. Repository content must use generic organisation terminology and synthetic examples; do not include company branding, personal names, production identifiers, or confidential source content.

## Planning studio

The planning studio (`pipeline/studio/`) sits alongside the original Parquet-fed dashboard described below. It is backed by a local FastAPI + PostgreSQL/SQLite API instead of a static snapshot — see [`pipeline/api/README.md`](pipeline/api/README.md) for setup. Earlier snapshot studios were superseded and removed; their implementations live in git history.

**Corp quick-start (no admin rights, no external database):**

```bash
PYTHONPATH= .venv/bin/python -m pip install -r pipeline/api/requirements.txt
PYTHONPATH=. .venv/bin/python -m pipeline.api.setup_backend --backend postgres-embedded
PYTHONPATH=. .venv/bin/python -m pipeline.api.ensure_db     # schema only; skip if import_snapshot ran (it creates it too)
PYTHONPATH=. .venv/bin/python -m pipeline.api.import_snapshot
PYTHONPATH=. .venv/bin/python -m pipeline.api.setup_roles   # multi-user only: roles + RLS (see pipeline/api/README.md)
PYTHONPATH=. .venv/bin/python pipeline/scripts/start_cplan.py
```

Multi-user access control (login, viewer/contributor/editor/admin) is documented in [`pipeline/api/README.md`](pipeline/api/README.md#authentication--roles).

A portal (landing page with project tiles and browser-based user administration) is available — see [`pipeline/api/README.md`](pipeline/api/README.md#portal).

`--backend postgres-embedded` is the recommended corp default: a real PostgreSQL 16, run as an unprivileged local process via [`pgserver`](https://pypi.org/project/pgserver/) — no admin rights, no installer, no external service. SQLite (`--backend sqlite`) remains the zero-dependency fallback when even that is not wanted. See [`pipeline/api/README.md`](pipeline/api/README.md#embedded-postgresql---backend-postgres-embedded) for the data-directory story, `cplan_db.py --status`/`--stop`, and the pg_dump-to-production path.

`GET /api/activities` deliberately returns the full result set with no pagination — the deployment target is local, single-user use. Revisit if the dataset outgrows an unpaginated response.

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

## Daily workflow

For the database-backed planning studio, `pipeline/scripts/daily_refresh.py` runs the whole daily refresh as one command: the CSV pipeline above, then the database sync (`pipeline/api/sync_snapshot.py`) that mirrors the result into the CPLAN database.

```bash
# Pipeline + sync (the normal daily run)
PYTHONPATH=. .venv/bin/python -m pipeline.scripts.daily_refresh

# Sync only — reuse the parquet snapshot already on disk, skip the CSV step
PYTHONPATH=. .venv/bin/python -m pipeline.scripts.daily_refresh --skip-pipeline
```

**Parallel operation.** This is not a one-shot migration: activities created directly in the studio (no `legacy_sp_id`) and activities mirrored in from the SharePoint source live in the same database at the same time. Each daily sync updates only the mirrored rows — source wins on conflicts, nothing is ever deleted — while studio-created activities are left completely untouched. This lets the studio be used for real planning work before the source system is retired; see [`pipeline/api/README.md`](pipeline/api/README.md#daily-snapshot-sync) for the full sync policy.

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
