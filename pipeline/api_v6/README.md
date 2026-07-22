# CPLAN Planning Studio V6 — admin-free local database MVP

V6 keeps the V4 analytics and planning experience but replaces the browser-local draft store and Parquet runtime with a same-origin FastAPI/SQLAlchemy data path. PostgreSQL is preferred; SQLite is the explicit no-install fallback. Both run in the user's context without a Windows service or admin rights.

## Implemented

- PostgreSQL- or SQLite-backed activities with stable UUIDs and retained SharePoint source IDs
- REST endpoints for health, list, create and versioned partial updates
- optimistic concurrency: stale updates receive HTTP `409 Conflict`
- one-time seed from the existing `pipeline/output/communications.parquet`
- V6 dashboard served by FastAPI; all edits are persisted immediately
- V4 and earlier dashboard implementations remain untouched
- explicit persisted backend selection; no silent PostgreSQL-to-SQLite fallback
- SQLite foreign keys, WAL journal mode and five-second busy timeout

## Choose the backend once

Settings default to `~/.cplan/cplan-settings.json`. Override that user-owned directory with `CPLAN_HOME` if needed.

Preferred PostgreSQL configuration (provide `CPLAN_DATABASE_URL` through the current process environment; do not pass credentials as command arguments):

```bash
# CPLAN_DATABASE_URL must already be set in the current process environment.
PYTHONPATH=. .venv/bin/python -m pipeline.api_v6.setup_backend --backend postgresql
```

Installer-free SQLite fallback:

```bash
PYTHONPATH=. .venv/bin/python -m pipeline.api_v6.setup_backend --backend sqlite
```

The setup validates the database before persisting the choice. For PostgreSQL, only the backend marker is stored; the connection URL and any password remain outside the JSON settings and must be present in `CPLAN_DATABASE_URL` when importing or starting. Existing settings require `--force` to replace. A configured PostgreSQL outage is reported; the launcher never creates or opens SQLite implicitly.

## Run with an available local PostgreSQL instance

From the repository root:

```bash
createdb cplan_v6  # only once
python3.11 -m venv .venv
PYTHONPATH= .venv/bin/python -m pip install -r pipeline/api_v6/requirements.txt
PYTHONPATH=. .venv/bin/python -m pipeline.api_v6.import_snapshot
PYTHONPATH=. .venv/bin/python pipeline/scripts/start_cplan_v6.py
```

Open <http://127.0.0.1:8780/>. API documentation is available at <http://127.0.0.1:8780/docs>.

The seed command is intentionally idempotent: if the activities table already contains records, it imports nothing. The importer uses the persisted backend settings; `CPLAN_DATABASE_URL` can override them explicitly for automation without exposing credentials in process arguments.

## Run with Docker Compose

Docker Desktop must be running. Keep the password outside Git:

```bash
read -s -p 'Local CPLAN database password: ' CPLAN_DB_PASSWORD && echo
export CPLAN_DB_PASSWORD
docker compose -f compose.v6.yaml up --build -d

# Optional seed when the local ignored snapshot exists:
docker compose -f compose.v6.yaml cp \
  pipeline/output/communications.parquet api:/tmp/communications.parquet
docker compose -f compose.v6.yaml exec api \
  python -m pipeline.api_v6.import_snapshot --parquet /tmp/communications.parquet
```

Then open <http://127.0.0.1:8780/>. Both published ports bind only to localhost. This configuration is for local development, not production deployment.

## Tests

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_v6_api.py tests/test_v6_import.py -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_v6_database.py tests/test_v6_setup_backend.py -q
python3 tests/test_dashboard_v6.py -v
node --check pipeline/dashboard-v6-postgres/app.js
```
