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
- server-generated, uniqueness-enforced tracking IDs on activity creation
- computed read-only fields (`planning_lead_days`, `tracking_pack_id`) on every activity read
- blank-string input on create/patch normalized to `NULL` for optional fields

## Activity fields and generated values

### Tracking IDs

`tracking_id` is never client-supplied — `POST /api/activities` rejects a `tracking_id` in the request body (the payload model forbids extra fields) and generates one on save in the format:

```
CLUSTER-PACKNUM-YYMMDD-ACTNUM-CHANNELABBR
```

- `CLUSTER-PACKNUM` is taken from `communication_pack_cpid` when it matches `^[A-Z0-9]+-[0-9]+$`; otherwise it falls back to the standalone prefix `STA-0000000`.
- `YYMMDD` is the activity's `start_date` converted to `Europe/Zurich`, or the current Zurich date when `start_date` is unset.
- `ACTNUM` is a global 7-digit sequence: one more than the highest activity number found across *all* existing tracking IDs, regardless of pack.
- `CHANNELABBR` is a majority vote of the abbreviation already used by other activities sharing the same `channel` value. With no precedent it falls back to the first three alphabetic characters of the channel, uppercased; if that yields fewer than two characters (or no channel was given), it falls back to `GEN`.
- Uniqueness is enforced by a partial unique index (`ix_activities_tracking_id_v6_unique`, `WHERE legacy_sp_id IS NULL`) — legacy-imported rows are exempt because the source system genuinely contains duplicate tracking IDs. A read-then-check pass narrows collisions before insert; a concurrent collision that still reaches the database surfaces as an `IntegrityError` and is retried with an incremented activity number. Both the pre-check and the commit-retry loop are bounded and raise HTTP 500 `tracking_id_generation_exhausted` if their retry budget runs out.

### `time_zone`

`time_zone` is a nullable `String(64)` column on `Activity`. Databases created before this column existed are topped up automatically: `ensure_schema()` (in `pipeline/api_v6/database.py`) runs right after `Base.metadata.create_all()` on every app startup and issues a plain `ALTER TABLE ... ADD COLUMN` for any model column the live table is missing, on both SQLite and PostgreSQL.

### Empty-string-to-null normalization

On both `POST /api/activities` and `PATCH /api/activities/{id}`, an empty or whitespace-only string supplied for an optional string field is normalized to `null` before validation — so `{"channel": ""}` clears the field the same way `{"channel": null}` does. The one exception is `activity_name`: it stays required, so an explicit empty string is rejected rather than silently cleared.

### Computed fields

Every activity returned by the API (list or single) carries two read-only computed fields alongside the stored columns:

- `planning_lead_days` — whole days between the activity's `start_date` and a reference timestamp (`source_created_at` when set, else `created_at`); negative values mean the start date precedes the reference and are returned as-is.
- `tracking_pack_id` — the `CLUSTER-PACKNUM` prefix of `tracking_id` (its first two `-`-separated segments), or `null` when there is no tracking ID.

These exist so `pipeline/dashboard-v6-postgres/analytics.js` — kept byte-identical to `pipeline/dashboard-v4/analytics.js` — can consume the same field names from both the V4 static snapshot and the V6 live API without forking the analytics code.

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

The seed command is intentionally idempotent: if the activities table already contains records, it imports nothing. The importer resolves the database the same way the API does: an explicit `CPLAN_DATABASE_URL` first, then `CPLAN_DB_HOST`/`_PORT`/`_NAME`/`_USER`/`_PASSWORD` composed into one (see the Docker Compose section below — this is what lets the seed command work inside the `api` container, which only sets the `CPLAN_DB_*` variables), then the persisted backend settings file.

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
