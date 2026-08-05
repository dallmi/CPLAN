# CPLAN Studio — admin-free local database MVP

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
- field-level change history: every create/update, from any write path, is recorded per changed field and surfaced in the drawer's History panel

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

## Field-level change history

Every write path records what changed, field by field, in the `activity_changes` table — the demo argument being that the SharePoint source cannot show what changed when; CPLAN can. Each row: `activity_id` (no FK — kept delete-free and SQLite-friendly, same as `Activity.legacy_sp_id`), `changed_at`, `actor`, `change_type` (`created` or `updated`), `field` (`NULL` for `created`), `old_value`/`new_value`, `version_from`/`version_to`. Values are stringified consistently everywhere: `NULL` for `None`, UTC ISO with a trailing `Z` for datetimes, `'true'`/`'false'` for booleans, `str()` otherwise.

| Actor | Written by | When |
|---|---|---|
| `studio` | `POST /api/activities`, `PATCH /api/activities/{id}` | a user creates or edits an activity in the dashboard |
| `sync` | `sync_snapshot.py` | a mirror row is created, or updated (including a conflict — source still wins and every overwritten field is still history-worthy, even though the run counts it separately from a plain update) |
| `seed` | `import_snapshot.seed_records` | the one-time initial seed from `communications.parquet` |

Every writer records the change in the same transaction as the data change itself — there is no separate audit step to fall out of sync. `PATCH` writes one row per field the client actually patched (not per field that happens to differ from its previous value — it is an edit trail, not a diff report); `sync_snapshot` reuses its existing per-field diffing (previously used only for conflict reporting) and now records every applied field change.

`GET /api/activities/{activity_id}/changes` returns `{items: [...], total}`, newest first (`changed_at` DESC, `id` DESC as a tiebreaker), or 404 for an unknown activity. The dashboard's drawer fetches this lazily whenever it opens in read-only mode (never while editing) and renders a History section: date/time in local time, an actor label (`You` / `Source sync` / `Initial import`), and either `Created` or `field: old → new` (an em dash for `NULL`) — the latest 30 entries, with a muted "N earlier changes not shown" line beyond that.

`activity_changes` is a brand new table, so `Base.metadata.create_all()` alone (its default `checkfirst=True`) creates it on an existing database at startup — no `ensure_schema()` top-up needed (that mechanism is for new columns/indexes on tables that already exist).

## Analysis views (pgAdmin)

`pipeline/api/views.py` creates a set of read-only SQL views for ad-hoc analysis directly in pgAdmin — no restructuring of how data is stored, just ready-made queries. **Postgres-only by design**: their whole purpose is pgAdmin access; SQLite users already have the studio's own analytics (`pipeline/studio/analytics.js`). `ensure_analysis_views(engine)` runs in the app lifespan right after `ensure_schema`, is a clean no-op on a SQLite engine, and re-creates every view with `CREATE OR REPLACE VIEW` on every startup (idempotent; a view renamed or dropped from a later version is not garbage-collected from an existing database). After the next app start, find them under `cplan → Schemas → public → Views`:

| View | Purpose |
|---|---|
| `v_activity_overview` | The working set for ad-hoc filtering — one row per activity, the columns most commonly filtered/sorted on. |
| `v_activities_by_month` | Activity count grouped by calendar month and source type. |
| `v_activities_by_channel` | Activity count grouped by channel (NULL as `Unassigned`) and source type. |
| `v_planning_completeness` | Per-activity booleans for each form-aligned required field (mirrors `REQUIRED_FIELDS` in `analytics.js`) plus `is_complete`. |
| `v_lead_times` | Per-activity whole-day lead time between `start_date` and `coalesce(source_created_at, created_at)` — matches `planning_lead_days`. |
| `v_pack_overview` | Activity count, date range and distinct channel count per communication pack (`tracking_id`'s `CLUSTER-PACKNUM` prefix). |
| `v_sync_history` | One row per `sync_snapshot.py` run — the same counts as `GET /api/sync-runs/latest`. |
| `v_change_log` | Every `activity_changes` row joined to its activity's `tracking_id`/`activity_name`; newest-first ordering is left to the consumer's own `ORDER BY`. |

## Authentication & roles

Solo/local use needs nothing here: with no `CPLAN_AUTH_SECRET` set, the API stays in the existing single-user "studio" mode (every write is attributed to the actor `studio`, no login, no role checks) — for both SQLite and PostgreSQL. Login and roles are a PostgreSQL-only feature; setting `CPLAN_AUTH_SECRET` against a SQLite backend has no effect.

### Enable

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"   # generate a secret once
export CPLAN_AUTH_SECRET=<the generated string>                # set before starting the API
```

`CPLAN_AUTH_SECRET` signs session cookies (`itsdangerous`, 12h expiry) — keep it out of Git the same way `CPLAN_DB_PASSWORD` is kept out. Once it is set and the backend is PostgreSQL, `POST /api/login` starts checking real credentials — under the shared limit described in [Failed sign-in throttling](#failed-sign-in-throttling), which the studio's login endpoint is subject to exactly as the portal's is — `GET /api/me` reports the caller's role, and every write is attributed to the logged-in username instead of `studio`. Because the counters live in the database, this also means the studio needs the portal's schema step (`setup_portal`) whenever authentication is enabled, and refuses to start without it.

### Set up roles + first admin

**The schema must exist first.** `apply_roles` opens with `ALTER TABLE activities ADD COLUMN IF NOT EXISTS created_by ...` — `IF NOT EXISTS` guards the column, not the table, so against a database nothing has created the schema in yet it fails with `relation "activities" does not exist`. Anything that starts the API (`start_cplan.py`), seeds it (`import_snapshot`) or syncs it (`sync_snapshot`) creates the schema as a side effect; when none of them has run yet, do it explicitly:

```bash
PYTHONPATH=. .venv/bin/python -m pipeline.api.ensure_db
```

`ensure_db` runs exactly what the app lifespan runs — `create_all` + `ensure_schema` + `ensure_analysis_views` — and nothing else: no data, idempotent, safe on a populated database. `setup.ps1` calls it as step 3, before the roles step.

```bash
PYTHONPATH=. .venv/bin/python -m pipeline.api.setup_roles --create-user a.admin --role admin
```

Prompts for a password (pass `--password` to skip the prompt, e.g. in a script). This single command both applies the role/grant/RLS model (idempotent — safe to re-run) and creates the first login. Re-run plain `setup_roles` (no flags) after every schema change: `GRANT ... ON ALL TABLES IN SCHEMA public` only covers tables that exist at the moment it runs, so a table added later needs another pass to pick up the grant.

### Manage users

Every flag below re-applies the role/grant/RLS model first, then performs its action. This CLI remains the way to bootstrap the very first admin and to script user changes; day-to-day user administration is otherwise done in the browser through the [portal](#portal) below.

```bash
PYTHONPATH=. .venv/bin/python -m pipeline.api.setup_roles --create-user <name> --role <viewer|contributor|editor|admin>   # new login, prompts for password
PYTHONPATH=. .venv/bin/python -m pipeline.api.setup_roles --set-role <name> --role <viewer|contributor|editor|admin>     # change an existing user's role
PYTHONPATH=. .venv/bin/python -m pipeline.api.setup_roles --reset-password <name>                                        # prompts for the new password
PYTHONPATH=. .venv/bin/python -m pipeline.api.setup_roles --deactivate <name>                                            # revoke LOGIN — user can no longer authenticate
PYTHONPATH=. .venv/bin/python -m pipeline.api.setup_roles --activate <name>                                              # restore LOGIN
```

All five accept `--password` to supply the value non-interactively instead of the getpass prompt, and `--database-url` to target a database other than the resolved default (`CPLAN_DATABASE_URL`, then `CPLAN_DB_*`, then the persisted backend settings — same resolution `setup_backend`/`import_snapshot` use). Usernames are plain PostgreSQL login roles, so they follow PostgreSQL identifier rules; the internal group roles and `cplan_authenticator` are rejected as usernames (`RESERVED_ROLES`) since a real user could otherwise collide with the privilege model itself.

The password never travels to the server: `setup_roles` hashes it into a SCRAM-SHA-256 verifier locally and puts *that* into the `CREATE ROLE`/`ALTER ROLE` statement — see [Passwords never reach the server log](#passwords-never-reach-the-server-log). `--password` does still put it in your shell history and in the process list, so the prompt stays the better option outside a script.

### Portal

The portal is a small landing page — project tiles plus browser-based user administration — that sits next to the studio and shares its login. PostgreSQL only, same as the rest of this section.

**Setup — after `setup_roles` has created the first admin, and again after every update:**

```bash
PYTHONPATH=. .venv/bin/python -m pipeline.api.setup_portal
```

Idempotent, and run as the same admin/superuser identity as `setup_roles` — never by the portal service itself. It creates the `portal_owner` role, the `portal` schema, the project registry (seeded with the CPLAN entry), the `portal.users` view, the `SECURITY DEFINER` user-management functions (`portal.create_user`, `portal.set_project_role`, `portal.revoke_project_role`, `portal.reset_password`, `portal.set_active`, `portal.set_display_name`) with `EXECUTE` granted only to `cplan_admin`, `portal.record_sign_in` granted to the service role — and the failed-sign-in counters (`portal.login_attempts`, `portal.begin_login_attempt`, `portal.end_login_attempt`, `portal.clear_login_attempts`; see [Failed sign-in throttling](#failed-sign-in-throttling)).

`portal.create_user` and `portal.reset_password` take a SCRAM-SHA-256 verifier, not a password, and refuse anything else (SQLSTATE `P0001`, surfaced as `422`) — see [Passwords never reach the server log](#passwords-never-reach-the-server-log). Upgrading an installation that predates this renames those two functions' second parameter, which `CREATE OR REPLACE` cannot do, so `apply_portal` drops and recreates them inside its own transaction; nothing else about the step changes.

**This is not once-only, despite the name.** A release that adds a `portal.*` object needs another pass, and this one does: an installation that receives the new files without re-running `setup_portal` has a portal and a studio whose login endpoints cannot consult their rate limit. Both refuse to start in that state and print the command above rather than serving sign-in without a limit — so "the portal window closed / says the login throttle is not installed" after an update means exactly this step is missing. `setup.cmd` runs it; `check.cmd` verifies the files on disk, not the database.

**Run:**

```bash
PYTHONPATH=. .venv/bin/python pipeline/scripts/start_portal.py
```

Serves on port 8781 by default (`--port` to override) — the studio keeps port 8780, so both run side by side. Requires `CPLAN_AUTH_SECRET` to be set: the portal reads the same signed session cookie as the studio (`CPLAN_AUTH_SECRET`, `Enable` above), so logging in on either one signs you into both.

**What the portal does:** an admin manages users entirely in the browser — invite, change role per project, reset password, enable/disable — without touching the CLI. The users list and the user × project access matrix show every account against every registered project, and a matrix cell can be set to any role. Emptying a cell (revoking a grant) is wired up in the browser, but the server does not yet expose a revoke endpoint, so it currently fails against a real deployment — a follow-up, not shipped. The portal service itself holds no DDL rights; every change that does reach the server is routed through the `portal.*` `SECURITY DEFINER` functions above, so a non-admin caller is rejected by PostgreSQL's own privilege check (SQLSTATE `42501`) before any change happens, surfaced to the browser as `403`.

#### The project page

Every tile on the portal home page links to a page of its own at `/project/{slug}`: the application tile, plus one tile per resource the project has declared — a manual, its technical documentation, data & freshness, what's new, access & support, generated reports. A tile is only ever what its manifest says it is; there is no directory scan that could pick up an undeclared file.

**Manifest.** A project declares its tiles in `pipeline/portal/projects/<slug>/resources.json` — a repository artefact that versions alongside the documents it points at. It lists, in display order, one entry per tile: a `kind`, a `title`, and whatever that kind needs (`manual` and `changelog` take a `path`; `docs` takes a `documents` list of `{key, title, path}`; `data`, `access` and `reports` need no path at all — `reports` takes a directory `path` instead of a file). `load_manifest`/`manifest_path` (`pipeline/portal/resources.py`) do the reading: an unknown project gets `{}` and just its `app` tile — no manifest is not an error — and a declared path that resolves outside the repository is refused rather than served, so a manifest typo can never turn into a file disclosure.

**Status lines.** Each tile kind has exactly one *resolver* — a small function in `pipeline/portal/resolvers.py` (`RESOLVERS`, keyed by `kind`) that answers the one question a person would ask before clicking: how many steps in the manual and when it last changed (`_manual`), how many documents and their titles (`_docs`), how fresh the data is and how many activities (`_data`, the only resolver that touches the database), how many entries and the latest one (`_changelog`), the caller's role and headcount (`_access`), how many report files and the newest (`_reports`). `resolve_tiles` (`pipeline/portal/resources.py`) builds the `app` tile first, then one tile per manifest entry in declaration order; a resolver that raises loses only its own status line (logged, not surfaced), because the application tile is what most people came for, not the sidebar's prose.

**Registering a second project costs zero changes to `pipeline/portal`** — that is the whole point of the declaration/resolution split above, and it is asserted, not just claimed: `test_a_second_project_needs_no_portal_code` in `tests/test_portal_api.py` registers a real second project, group roles and manifest and only then calls the existing endpoint. Five steps:

1. **Register it** — `register_project(engine, slug, name, url, role_prefix)` (`pipeline/api/setup_portal.py`), once, run against the same admin/superuser identity `setup_roles`/`setup_portal` use.
2. **Create its PostgreSQL group roles** — `<role_prefix>_{viewer,contributor,editor,admin}`, wired with the same additive membership chain `setup_roles` builds for CPLAN's own roles (`viewer` ⊂ `contributor` ⊂ `editor` ⊂ `admin`). Whoever holds one of the four is who sees the project's tile on the portal home page and can open its project page — nothing else grants that.
3. **Re-run `setup_portal`** (`PYTHONPATH=. .venv/bin/python -m pipeline.api.setup_portal`), once more, against the same admin/superuser identity. Step 1's `register_project` tried to extend `portal_owner`'s `ADMIN OPTION` to these roles already, but at that point they didn't exist yet, so that grant was a no-op; it is `apply_portal`'s own sweep over every registered project, run again now that step 2 has created the roles, that actually closes the gap. Skip this and `portal.create_user`/`set_project_role`/`revoke_project_role` fail PostgreSQL's own privilege check (SQLSTATE `42501`) the first time anyone tries to use them on the new project — surfacing as a `403` that looks like a permissions bug rather than a step left undone.
4. **Drop a `resources.json`** beside the project's own documents, declaring its tiles as above.
5. **Write its manual, or omit that tile** — a manifest with no `manual` entry simply shows no manual tile; nothing else needs to exist for the rest of the page to work.

**`role_prefix` is `UNIQUE`** (`portal.projects.role_prefix`) — read this sentence before registering project number two. Every place that resolves a caller's role — `project_detail`'s `PROJECT_SQL`, `member_count`, `portal.users`, the `portal.*` `SECURITY DEFINER` functions — does it by deriving `<role_prefix>_<role>` and asking PostgreSQL whether the caller holds that role; there is no other qualifier tying a role to a project. Two projects sharing a prefix would make a grant on one project's `<prefix>_admin` (say) silently apply to the other, and `portal.users` would emit a duplicate row per shared user. The `UNIQUE` constraint is the last line of defence against that, not the first — pick a prefix that cannot collide with an existing one.

Note the current single-project scope of user *administration* specifically (distinct from the above): `EXECUTE` on the user-management functions is granted to `cplan_admin` project-wide, so today every admin is a portal-wide admin; per-project admin scoping is the documented extension point once a second project is registered.

**Bootstrap admin caveat:** the portal manages users it can already see through `portal.users`, but it cannot create the very first admin from an empty database — that first login still comes from `setup_roles --create-user <name> --role admin` (`Set up roles + first admin` above).

### Failed sign-in throttling

Accounts here *are* PostgreSQL login roles, so a guessed password is a database session at that account's privilege level — and initial passwords are administrator-generated and handed over by phone or chat. Both `POST /api/login` endpoints (the studio's on 8780 and the portal's on 8781) therefore share one set of counters, held in `portal.login_attempts` and read and written only through `portal.begin_login_attempt`/`portal.end_login_attempt`. Throttling one door and not the other would have been no limit at all: both check the same roles and mint the same `cplan_session` cookie, which the other accepts. The policy lives in `pipeline/api/login_guard.py`, whose module docstring carries the full reasoning; this is what an operator needs at 2am.

**The limits.** Three counters, each over a fixed **15-minute** window:

| Counter | Limit | What it stops |
|---|---|---|
| one address against one username | **5** failures | a sequential guessing run — the counter a real person could plausibly reach, and the reason it is not lower |
| one username, all addresses | **20** failures | a run spread over several addresses |
| one address, all usernames | **20** failures | password spraying — one guess against each of many names |

Only failures count. A correct password, and a credential check the database could not answer at all (a restart, an exhausted connection limit), hand their attempt back, so neither spends anyone's budget.

**What a user sees.** A throttled attempt is `429` with `{"detail": {"code": "too_many_attempts"}}` and `Retry-After: 900`, identical whether or not the username exists — the browser shows *Too many failed sign-in attempts*. `503 login_unavailable` (*Sign-in is temporarily unavailable*) is a different thing entirely: it means the server could not consult the counters, which in practice means this database never ran the `setup_portal` above.

**Three properties worth knowing before you debug one.**

- **A block always releases on its own within 15 minutes, and hammering cannot extend it.** The window is fixed from the counter's first attempt, and a blocked attempt is not counted at all.
- **Five failures do not lock the account.** They lock *the address that produced them* out of *that name*, so a stranger who knows a username cannot deny its owner service; the account-wide counter that does apply to everyone sits four times higher.
- **The per-address counter ignores addresses that identify nobody** — loopback above all. Both servers bind `127.0.0.1`, so every peer they can see reports `127.0.0.1`; a shared budget of twenty on that key would mean twenty typos anywhere in the deployment answering every remaining user, administrators included, with `429`. The per-username counters still apply to every attempt whatever its source. For the same reason both launchers pass `proxy_headers=False`: uvicorn's default would let any caller of a loopback-bound server rewrite its own source address with an `X-Forwarded-For` header. Putting a real reverse proxy in front of either server means establishing a trusted-proxy chain first.

**Releasing a block immediately**, for the case waiting cannot fix — an administrator locked out of the portal that is the tool for fixing things:

```bash
PYTHONPATH=. .venv/bin/python -m pipeline.api.setup_portal --clear-login-block <username-or-address>
PYTHONPATH=. .venv/bin/python -m pipeline.api.setup_portal --clear-login-block --all   # every counter
```

Run as the same admin/superuser identity as `setup_portal` itself. There is deliberately no portal endpoint and no admin UI for it: the person who needs it is the person the portal is refusing, and `EXECUTE` on `portal.clear_login_attempts` is granted to nobody — not even the service role, which would otherwise be a way to hand a guessing run its budget back.

`tests/test_login_throttle.py` covers all of the above against a real PostgreSQL, including four simulated hours of continuous guessing and thirty concurrent attempts.

### The role model

| Role | Read | Create | Edit own rows | Edit any row | Delete |
|---|---|---|---|---|---|
| `viewer` | yes | — | — | — | — |
| `contributor` | yes | yes | yes | — | — |
| `editor` | yes | yes | yes | yes | — |
| `admin` | yes | yes | yes | yes | yes |

Roles are additive group memberships (`viewer` ⊂ `contributor` ⊂ `editor` ⊂ `admin`), enforced two ways at once:

- **Grants** — plain PostgreSQL `GRANT`s decide which SQL statements a role may issue at all (`SELECT` for everyone, `INSERT`/`UPDATE` from `contributor` up, `DELETE` only for `admin`).
- **Row-level security** on `activities` — `contributor` may only `INSERT`/`UPDATE` rows where `created_by` matches their own username (policies `contrib_insert`/`contrib_update`); `editor` and the sync job (`cplan_sync`) write any row (`editor_write`, `FOR ALL USING (true)`); `admin` alone carries the `DELETE` policy (`admin_delete`). Everyone reads every row (`read_all`, `FOR SELECT USING (true)`).

A contributor's attempt to edit or delete a row they don't own fails as a normal HTTP error, not a leak: the app's ownership check (`update_activity`) returns `403 forbidden_not_owner` before the query even runs, and any privilege PostgreSQL itself rejects (e.g. a raw `DELETE` attempt) surfaces via the global `ProgrammingError` handler as `403 forbidden` (SQLSTATE `42501`) rather than a raw 500.

Delete is intentionally hard to lose data from: `DELETE /api/activities/{id}` is `admin`-only, and even then the row is not silently gone — the handler writes an `activity_changes` audit row (`change_type "deleted"`, a JSON snapshot of `tracking_id`/`activity_name` in `old_value`) in the same transaction as the delete, so the deletion itself remains visible in the History panel and `v_change_log` after the activity row is gone.

### Passwords never reach the server log

`CREATE ROLE … PASSWORD 'secret'` puts the cleartext inside the statement *text*, and statement text is exactly what gets logged: `log_statement = 'ddl'` or `'all'`, a low enough `log_min_duration_statement`, or an audit extension such as pgaudit (which logs statements executed *inside* functions too, where the portal builds its DDL). The server log is a file operators read routinely and central collection ships onwards, so a password that lands there is disclosed broadly, permanently, and invisibly.

Both paths that set a password therefore hash it first, in this process, and send only the result:

- `pipeline/api/scram.py` builds the SCRAM-SHA-256 verifier PostgreSQL would have built itself — RFC 5802/7677, SASLprep included, at the server's own configured `scram_iterations`. PostgreSQL stores a string it recognises as a verifier verbatim, so the account is byte-for-byte what a cleartext `PASSWORD` would have produced.
- `setup_roles` (the CLI) and the portal endpoints (`POST /api/portal/users`, `…/password`) both call it. The cleartext exists only in the request handler and the `getpass` prompt; from there on, only the verifier travels.
- `portal.create_user` and `portal.reset_password` **refuse** a value that is not a verifier rather than passing it on, so the leak cannot return through a caller that forgets to hash. An out-of-date client gets `422`, and the account it was changing is untouched.

Two things about this are worth knowing when changing it. A malformed verifier is *not* rejected by PostgreSQL — anything it cannot parse as one is treated as a cleartext password and hashed, which locks the account out silently — so `tests/test_scram.py` proves a real sign-in and compares byte-for-byte against a verifier the server built itself, rather than asserting on the shape of the string. And nothing here changes how sign-in works: `pipeline/api/auth.py` still verifies a password by opening a real connection, and PostgreSQL is still the only authority on passwords.

### Central-server hardening

On a shared/central instance, `pg_hba.conf` must require `scram-sha-256` for every non-superuser role over TCP — a server reachable from other machines must never fall back to `trust` auth for login roles, or any known username authenticates with any (or no) password.

The **embedded** backend (`postgres-embedded` via `pgserver`) already does the right thing for its one legitimate local-trust case and nothing more: `pgserver` provisions a fresh `pgdata` with `trust` for every role, and `database.py`'s `_harden_local_authentication` rewrites `pg_hba.conf` on every startup so only `postgres` (the app's own superuser, used for engine bootstrap and `setup_roles` itself, which never carries a password) keeps `trust`; every other role — every user created via `setup_roles --create-user` — must present its real `scram-sha-256` password, both over the Unix socket and over `127.0.0.1`/`::1`. This is what makes `verify_credentials` (`pipeline/api/auth.py`) meaningful even for local/solo use: a wrong password for an existing user role is rejected, not silently accepted. On a real shared PostgreSQL server (not the embedded one), apply the equivalent rule directly in that server's own `pg_hba.conf` — do not lower it back to `trust` for convenience.

The API service itself never connects as an end user's role directly: it authenticates as `cplan_authenticator` and `SET ROLE` into the logged-in user's role for the duration of the request (`setup_roles` grants every created user role `TO cplan_authenticator` at creation time, and `apply_roles` re-applies that shape on every run) — the PostgREST pattern. Point `CPLAN_DATABASE_URL` at `cplan_authenticator`'s own credentials when running the API against a central server, not at any individual user's login.

### pgAdmin

The same grants the studio enforces apply to a direct pgAdmin connection — there is no separate read path to lock down. Handing a user their own `cplan_viewer`/`cplan_contributor`/`cplan_editor`/`cplan_admin`-derived login and connecting pgAdmin with it is safe: they see exactly the rows and columns their role already permits through the API (RLS applies identically outside the API, since `activities` has `FORCE ROW LEVEL SECURITY` enabled), plus the read-only analysis views under `cplan → Schemas → public → Views` (see [Analysis views](#analysis-views-pgadmin) above) — `cplan_viewer`'s blanket `SELECT` on all tables already covers them.

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
PYTHONPATH=. .venv/bin/python -m pytest tests/test_views.py -q
python3 tests/test_studio.py -v
node --check pipeline/studio/app.js
```

`tests/test_postgres_embedded.py` starts a real embedded PostgreSQL server end-to-end (setup, connect, clean stop) and skips itself automatically when `pgserver` is not installed, so CI without that optional dependency stays green. `tests/test_database.py` and `tests/test_setup_backend.py` cover the same URL-conversion and settings logic against a stubbed `pgserver` module — no real server needed for those.

The role/RBAC/portal/session test modules (`tests/test_setup_roles.py`, `tests/test_setup_portal.py`, `tests/test_rbac_matrix.py`, `tests/test_portal_api.py`, `tests/test_portal_project_page.py`, `tests/test_session.py`, `tests/test_api_auth.py`, `tests/test_login_throttle.py`) need a real PostgreSQL server the same way `test_postgres_embedded.py` does, and skip — not fail — the same way when `pgserver` is missing: `postgres_required` (`tests/conftest.py`) skips a whole module when neither `pgserver` is importable nor `CPLAN_TEST_DATABASE_URL` is set, so a run that expects the portal's own tests to execute can go quietly green on 0 assertions instead. `pgserver` has no wheel for every platform (e.g. Python 3.13 on macOS arm64, as of 2026) — on such a machine it is simply not installed, and every test gated on it skips by default; watch for that when a change under `pipeline/portal/` reports full green but the skip count went up. On a machine without a `pgserver` wheel, set `CPLAN_TEST_DATABASE_URL` to a SQLAlchemy URL for a disposable PostgreSQL server instead — this repository's own `compose.yaml` provides one:

```bash
CPLAN_DB_PASSWORD=<pick one> docker compose up -d db   # publishes 127.0.0.1:55432, db "cplan", user "cplan" (superuser)
CPLAN_TEST_DATABASE_URL=postgresql+psycopg://cplan:<password>@127.0.0.1:55432/cplan \
    PYTHONPATH=. .venv/bin/python -m pytest tests/test_setup_roles.py tests/test_setup_portal.py tests/test_rbac_matrix.py tests/test_portal_api.py tests/test_portal_project_page.py tests/test_session.py tests/test_api_auth.py tests/test_login_throttle.py -q
```

Each affected module's fixture then creates its own freshly named database on that server (and drops it afterwards, along with every role it created), so it is safe to point the whole suite at the same server and run it more than once in a row — see `tests/conftest.py` for the isolation approach. `test_postgres_embedded.py` itself is the one exception: it tests the embedded `pgserver` backend's own start/stop mechanics, which have no external-database equivalent, so it keeps skipping without `pgserver` regardless of `CPLAN_TEST_DATABASE_URL`.
