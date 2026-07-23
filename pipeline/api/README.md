# CPLAN Planning Studio — admin-free local database MVP

The planning studio replaces a browser-local draft store and Parquet runtime with a same-origin FastAPI/SQLAlchemy data path. Three backends share the same API and studio code, chosen once via `setup_backend` and never silently switched: **postgres-embedded** (a real PostgreSQL 16, run as an unprivileged local process — the recommended corp default), a real **PostgreSQL** server you already have, or **SQLite** as the zero-dependency fallback. All three run in the user's context without a Windows service or admin rights.

## Implemented

- PostgreSQL (embedded or external) or SQLite-backed activities with stable UUIDs and retained SharePoint source IDs
- REST endpoints for health, list, create and versioned partial updates
- optimistic concurrency: stale updates receive HTTP `409 Conflict`
- one-time seed from the existing `pipeline/output/communications.parquet`
- planning studio served by FastAPI; all edits are persisted immediately
- explicit persisted backend selection; no silent PostgreSQL-to-SQLite fallback
- SQLite foreign keys, WAL journal mode and five-second busy timeout
- server-generated, uniqueness-enforced tracking IDs on activity creation
- computed read-only fields (`planning_lead_days`, `tracking_pack_id`) on every activity read
- blank-string input on create/patch normalized to `NULL` for optional fields
- daily snapshot sync: upserts the SharePoint mirror into the database (source wins, conflicts reported, nothing deleted) alongside activities created directly in the studio

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

`time_zone` is a nullable `String(64)` column on `Activity`. Databases created before this column existed are topped up automatically: `ensure_schema()` (in `pipeline/api/database.py`) runs right after `Base.metadata.create_all()` on every app startup and issues a plain `ALTER TABLE ... ADD COLUMN` for any model column the live table is missing, on both SQLite and PostgreSQL.

### Empty-string-to-null normalization

On both `POST /api/activities` and `PATCH /api/activities/{id}`, an empty or whitespace-only string supplied for an optional string field is normalized to `null` before validation — so `{"channel": ""}` clears the field the same way `{"channel": null}` does. The one exception is `activity_name`: it stays required, so an explicit empty string is rejected rather than silently cleared.

### Computed fields

Every activity returned by the API (list or single) carries two read-only computed fields alongside the stored columns:

- `planning_lead_days` — whole days between the activity's `start_date` and a reference timestamp (`source_created_at` when set, else `created_at`); negative values mean the start date precedes the reference and are returned as-is.
- `tracking_pack_id` — the `CLUSTER-PACKNUM` prefix of `tracking_id` (its first two `-`-separated segments), or `null` when there is no tracking ID.

These exist so `pipeline/studio/analytics.js` can consume these field names directly from the live API.

## Choose the backend once

Settings default to `pipeline/data/cplan-settings.json` (the SQLite database, when chosen, lands alongside it at `pipeline/data/cplan.sqlite3`), resolved relative to the repository regardless of the current working directory. Override that directory with `CPLAN_HOME` if needed — do not point it at a OneDrive-synced folder (SQLite's WAL journal mode does not tolerate concurrent file sync and risks corruption).

**Recommended corp default — embedded PostgreSQL, no admin rights needed:**

```bash
PYTHONPATH=. .venv/bin/python -m pipeline.api.setup_backend --backend postgres-embedded
```

Preferred configuration against a PostgreSQL server you already have (provide `CPLAN_DATABASE_URL` through the current process environment; do not pass credentials as command arguments):

```bash
# CPLAN_DATABASE_URL must already be set in the current process environment.
PYTHONPATH=. .venv/bin/python -m pipeline.api.setup_backend --backend postgresql
```

Installer-free SQLite fallback:

```bash
PYTHONPATH=. .venv/bin/python -m pipeline.api.setup_backend --backend sqlite
```

The setup validates the database before persisting the choice. For `postgresql`, only the backend marker is stored; the connection URL and any password remain outside the JSON settings and must be present in `CPLAN_DATABASE_URL` when importing or starting. Existing settings require `--force` to replace. A configured PostgreSQL outage is reported; the launcher never creates or opens SQLite implicitly.

### Embedded PostgreSQL (`--backend postgres-embedded`)

[`pgserver`](https://pypi.org/project/pgserver/) ships prebuilt PostgreSQL 16 binaries as a plain pip package and runs them as an unprivileged local process — no admin rights, no Windows service, no manual install. `setup_backend` starts it once, creates the `cplan` database if it doesn't exist yet, and validates with `SELECT 1`. Nothing secret is persisted: the server uses trust auth bound to localhost/a local socket, so settings only ever store the `pgdata` path, never a password.

**Data directory — why not `P:` or OneDrive.** The default `pgdata` is a platform user-data directory: Windows `%LOCALAPPDATA%/CPLAN/postgres`, macOS `~/Library/Application Support/CPLAN/postgres`, Linux `~/.local/share/CPLAN/postgres`. A prior project put PostgreSQL's data directory on a corp network home drive (`P:`) and hit WAL-write stalls, connection timeouts and crash-recovery hangs under normal use; OneDrive-synced folders have the same failure mode as with SQLite above (a background sync process racing PostgreSQL's own file writes). Keep `pgdata` on local disk — `%LOCALAPPDATA%` is writable without admin rights on every corp Windows machine.

**Overriding the location:** `--pgdata PATH` at setup time, or the `CPLAN_PGDATA` environment variable, which also wins over whatever is already persisted in settings at every subsequent run — so a corp fallback (e.g. local disk turns out unusable, switch to a network share) takes effect just by exporting the variable, no need to re-run `setup_backend`. If the resolved `pgdata` still ends up on a UNC network path, `setup_backend` and `cplan_db.py` print a clear warning (and proceed anyway) — raise client connection timeouts to at least 60s if you must use one.

**Lifecycle:** the server is left running between CPLAN sessions — `start_cplan.py` and `daily_refresh.py` never stop it, so the next command starts instantly. Manage it explicitly with `pipeline/scripts/cplan_db.py`:

```bash
PYTHONPATH=. .venv/bin/python -m pipeline.scripts.cplan_db --start    # start (idempotent) without studio/sync -- e.g. pgAdmin-only use after a reboot
PYTHONPATH=. .venv/bin/python -m pipeline.scripts.cplan_db --status   # running? host/port or socket, pgdata, PG version
PYTHONPATH=. .venv/bin/python -m pipeline.scripts.cplan_db --stop     # clean shutdown (pg_ctl -m fast) -- never a hard kill
```

A clean stop checkpoints and removes `postmaster.pid`, so the next start is instant; a hard kill (which this script never does) skips the checkpoint and forces a slow WAL-replaying crash recovery on the next start — exactly the failure mode the network-drive story above describes.

**Connecting pgAdmin:** run `cplan_db.py --status` to read the current host/port (TCP on Windows, a dynamic port that changes on every restart) or socket path (macOS/Linux). User is always `postgres` with an empty password (trust auth — tick "Save password" in pgAdmin and leave the field blank). If `pgdata` sits on a network share, raise pgAdmin's connection timeout to 60s.

**Going to production:** the embedded server is a real PostgreSQL 16 — there is no schema translation step. `pg_dump` it and restore 1:1 into a production PostgreSQL instance:

```bash
PYTHONPATH=. .venv/bin/python -m pipeline.scripts.cplan_db --status   # read host/port or socket
pg_dump -h <host> -p <port> -U postgres cplan > cplan.sql             # or via the socket path shown above
psql <production-connection> -f cplan.sql
```

## Run with an available local PostgreSQL instance

From the repository root:

```bash
createdb cplan  # only once
python3.11 -m venv .venv
PYTHONPATH= .venv/bin/python -m pip install -r pipeline/api/requirements.txt
PYTHONPATH=. .venv/bin/python -m pipeline.api.import_snapshot
PYTHONPATH=. .venv/bin/python pipeline/scripts/start_cplan.py
```

Open <http://127.0.0.1:8780/>. API documentation is available at <http://127.0.0.1:8780/docs>.

The seed command is intentionally idempotent: if the activities table already contains records, it imports nothing. The importer resolves the database the same way the API does: an explicit `CPLAN_DATABASE_URL` first, then `CPLAN_DB_HOST`/`_PORT`/`_NAME`/`_USER`/`_PASSWORD` composed into one (see the Docker Compose section below — this is what lets the seed command work inside the `api` container, which only sets the `CPLAN_DB_*` variables), then the persisted backend settings file.

## Daily snapshot sync

Once seeded, `pipeline/api/sync_snapshot.py` keeps the database in step with the daily SharePoint export (`pipeline/output/communications.parquet`) without disturbing activities created directly in the studio:

```bash
PYTHONPATH=. .venv/bin/python -m pipeline.api.sync_snapshot
```

Policy (binding): SharePoint is the system of record, so a row changed in both the source and locally in the studio is overwritten by the source value and reported as a **conflict** (field-level diff). Rows created in the studio (`legacy_sp_id IS NULL`) are never touched and are counted as **local-only**. Rows are never deleted — a `(source_type, legacy_sp_id)` missing from the snapshot is reported as **vanished** and left as-is. Records without an `sp_id` are **skipped**. Every run writes one `sync_runs` row (counts + a JSON detail blob capped at 50 entries each for conflicts/vanished); `GET /api/sync-runs/latest` returns it, or `{"status": "never_synced"}` before the first run. Accepts the same `--settings`/`--parquet` flags as `import_snapshot`.

`pipeline/scripts/daily_refresh.py` is the recommended one-command entry point: it runs the CSV pipeline (`process_cplan.py`) and this sync in sequence, or `--skip-pipeline` to run the sync alone against the parquet already on disk — see the top-level [`README.md`](../../README.md#daily-workflow). The dashboard's Analytics → Data Quality → "Refresh & reconciliation" card reads `GET /api/sync-runs/latest` to surface the last sync timestamp, the created/updated/conflicts/local-only counts, and a warning line when conflicts overrode local edits.

## Run with Docker Compose

Docker Desktop must be running. Keep the password outside Git:

```bash
read -s -p 'Local CPLAN database password: ' CPLAN_DB_PASSWORD && echo
export CPLAN_DB_PASSWORD
docker compose -f compose.yaml up --build -d

# Optional seed when the local ignored snapshot exists:
docker compose -f compose.yaml cp \
  pipeline/output/communications.parquet api:/tmp/communications.parquet
docker compose -f compose.yaml exec api \
  python -m pipeline.api.import_snapshot --parquet /tmp/communications.parquet
```

Then open <http://127.0.0.1:8780/>. Both published ports bind only to localhost. This configuration is for local development, not production deployment.

## Tests

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_api.py tests/test_import.py -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_database.py tests/test_setup_backend.py -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_sync.py -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_cplan_db.py tests/test_postgres_embedded.py -q
python3 tests/test_studio.py -v
node --check pipeline/studio/app.js
```

`tests/test_postgres_embedded.py` starts a real embedded PostgreSQL server end-to-end (setup, connect, clean stop) and skips itself automatically when `pgserver` is not installed, so CI without that optional dependency stays green. `tests/test_database.py` and `tests/test_setup_backend.py` cover the same URL-conversion and settings logic against a stubbed `pgserver` module — no real server needed for those.
