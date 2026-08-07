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

A portal (landing page with project tiles, a users list and a user × project access matrix) is available — see [`pipeline/api/README.md`](pipeline/api/README.md#portal). Its project page carries a hand-authored user manual illustrated with real screenshots; after a portal or studio UI change, refresh them with:

```bash
CPLAN_DB_PASSWORD=<password> docker compose up -d db
CPLAN_TEST_DATABASE_URL=postgresql+psycopg://cplan:<password>@127.0.0.1:55432/cplan \
    PYTHONPATH=. .venv/bin/python pipeline/scripts/capture_manual_shots.py
```

`pipeline/scripts/capture_manual_shots.py` provisions a disposable PostgreSQL database (schema, roles, seed data), drives the studio and the portal through Playwright, saves nine PNGs to `pipeline/portal/projects/cplan/assets/`, and drops the database again — repeatable, and safe on a shared server. Playwright is a development-only dependency (`requirements-dev.txt`, `pip install -r requirements-dev.txt` then `playwright install chromium`); it is never imported by the portal itself. The captured PNGs are committed, so a checkout with no Playwright installed still serves a working manual with its existing pictures — only regenerating them needs the dev dependency. Inspect every PNG by hand before committing: the seed data is organisation-neutral by construction, but a screenshot is still a screenshot.

### Pictures a project publishes

Every image a project shows lives in one directory, declared at the top of its `resources.json`:

```json
{
  "assets": "pipeline/portal/projects/cplan/assets",
  "logo": "logo.png"
}
```

`assets` is the store — the manual's nine screenshots are in it, and so is anything added later. `logo` names the file within it that stands for the project: the portal puts it on the project's tile, left of the name. It is a *file name*, not a path, so a picture cannot be declared from somewhere else in the repository, and the whole store stays in one place.

Drop a new picture in, name it in the manifest, and it is served — behind the session, at `/project/{slug}/assets/{name}`, exactly as private as the project itself. Nothing is public: a logo is a hint about what the organisation runs. Declaring a file that is not there yet is not an error; the tile reads as it did before, so the declaration and the picture can land in either order. Sizing is the portal's job (28 px tall, capped at 104 px wide, undistorted), so any reasonable PNG or SVG fits without being prepared first — but check a picture for organisation branding before committing it, the same rule the screenshots follow.

`--backend postgres-embedded` is the recommended corp default: a real PostgreSQL 16, run as an unprivileged local process via [`pgserver`](https://pypi.org/project/pgserver/) — no admin rights, no installer, no external service. SQLite (`--backend sqlite`) remains the zero-dependency fallback when even that is not wanted. See [`pipeline/api/README.md`](pipeline/api/README.md#embedded-postgresql---backend-postgres-embedded) for the data-directory story, `cplan_db.py --status`/`--stop`, and the pg_dump-to-production path.

`GET /api/activities` deliberately returns the full result set with no pagination — the deployment target is local, single-user use. Revisit if the dataset outgrows an unpaginated response.

## MCP server

An optional read-only [MCP](https://modelcontextprotocol.io) server (`pipeline/mcp/`) exposes the planning data to AI agents over stdio — six tools for searching activities, inspecting planning gaps and counting volumes, on a database connection that refuses writes. It needs no running API server. See [`pipeline/mcp/README.md`](pipeline/mcp/README.md).

## Architecture

```
OneDrive sync folder          pipeline/
  (or pipeline/input/)          process_cplan.py   <- ETL script
  *.csv  ──────────────────>    data/cplan.db      <- DuckDB database
                                output/communications.parquet
                                output/communications.json
                                output/reports/*.xlsx  <- calendar reports
                                dashboard/index.html  <- HTML dashboard
```

## Prerequisites

```
pip install pandas duckdb pyarrow openpyxl
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

### Calendar report

On Windows, double-click `report.cmd` — it resolves the interpreter the same
way the other launchers do (`CPLAN_PYTHON`, then an active venv, then the
repo's `.venv`) and opens the workbook when it is done. `report.cmd -NoOpen`
writes it without opening; `-Out`, `-InputDir` and `-GebMembers` are passed
through.

```bash
# Generate the .xlsx planning report from the CSV exports (no database needed)
python pipeline/scripts/report_calendar.py
```

Edit the `CONFIG` block at the top of
[`pipeline/scripts/report_calendar.py`](pipeline/scripts/report_calendar.py) to
change the period, the senior-executive criterion and the audience-size
criterion. The design is documented in
[`docs/superpowers/specs/2026-07-30-calendar-report-design.md`](docs/superpowers/specs/2026-07-30-calendar-report-design.md).

### Agent pack

The same report in a shape a retrieval agent can read. The workbook cannot be
grounded on: its meaning lives in merged headers, collapsed outlines and
formulas, and a formula written by `openpyxl` carries no cached value at all —
on the Executive Summary the share formula *is* the row label, so an indexer
reads neither the percentage nor what it describes.

```bash
python pipeline/scripts/build_agent_pack.py            # same period flags as the report
```

On Windows, double-click `agentpack.cmd`. It takes the same period flags as
`report.cmd`; running both with the same flags is what makes them two
renderings of one report rather than two reports.

The artefacts land in the OneDrive CPLAN folder — `Projekte/CPLAN/Input`, the
same one the Power Automate export arrives in — so the pack can be uploaded
from any machine that syncs it. Nothing in the pipeline deletes from there, and
no file the pack writes matches an input glob, so the two sets sit side by side.
Without that folder they land in `pipeline/output/agent-pack/` instead
(gitignored — they carry production figures).

| | |
|---|---|
| `pack/` | four `.txt` and two `.csv`: what the skill archive is built from, and the readable copy of what the agent holds. **Not uploaded** — see below |
| `cplan-skill.zip` | the same content as a skill package, `SKILL.md` at the archive root |
| `chart-standards-skill.zip` | the visual rules as a second skill. No data files, so it is rebuilt identically every run — upload it once and again only when the rules change |
| `evaluation.csv` | the same questions as an importable test set. Safe to upload: an evaluation set is never grounded on |
| `agent-instructions.md` | the whole agent prompt. Paste into Instructions after one find-and-replace of `<ORGANISATION>` |
| `checklist.md` | questions with computed answers, half of them pre-computed in the pack and half not. **Not for uploading** — an agent that can read the answer key passes without computing anything |

The data reaches the agent through the skill, not through a knowledge source.
`pack/` was one until two probes showed it was never reached for: a needle
question found its row by reading the file — and caught that the tracking ID in
the question was missing a letter — and a counting question answered by
examining all 1,385 rows, which is the one thing chunked retrieval cannot do.
Both still answered with the knowledge source removed.

A second grounding path that is never taken still has to be re-uploaded on
every refresh, and a pack refreshed on one path and not the other hands the
agent two vintages of the same figure. The fallback it bought was also the
wrong one: if the skill fails to load, its rules do not load either, so an
answer grounded on the index alone is an answer without them — which looks
right and is not.

This holds at 1,385 rows. If the plan grows to several thousand the file will
stop fitting in one read, and a knowledge source becomes the only way to find a
single row again. The signal is in the answers: the agent stops writing
"examined all N rows" and starts naming a subset.

`.txt` rather than `.md` because Markdown is not on the crawled-extension list,
and a file that is not crawled is not retrievable. The calendar is long rather
than wide — one row per block × value × week — so a row keeps its meaning
wherever the file is chunked, and every row carries an `overlaps` column
because only `block=TOTAL` sums to the portfolio.

`tests/test_agent_pack.py` holds the pack and the workbook to each other; both
resolve their scope through the same `resolve_scope`.

The combined leadership field can be split into GEB and GEB-1 with
`--geb-members path/to/list.xlsx` (or `report.ps1 -GebMembers ...`). The file
names each GEB member by email and/or display name, in two columns headed
`email` and `name`. Either format is read, chosen by the extension:

- **`geb-members.xlsx`** — the easier one to keep by hand. Excel's own
  encoding, no separator to get wrong, and a `Last, First` name needs no
  quoting.
- **`geb-members.csv`** — must be saved as *CSV UTF-8*, comma-separated. On a
  German locale Excel writes semicolons, which the reader rejects by name.
  `geb-members.csv.example` is the committed template.

Both are gitignored because they name real people. Placed in the repository
root, either is found without passing the flag; holding *both* is an error
rather than a precedence rule, so a stale copy cannot quietly outrank the list
being edited. With no default file present, the two levels stay combined
exactly as before. A `--geb-members` path that does not exist is treated as a
typo, not as "no list": the report aborts with an error instead of silently
falling back to the combined field.

## Daily workflow

For the database-backed planning studio, `pipeline/scripts/daily_refresh.py` runs the whole daily refresh as one command: the CSV pipeline above, then the database sync (`pipeline/api/sync_snapshot.py`) that mirrors the result into the CPLAN database.

```bash
# Pipeline + sync + standalone export (the normal daily run)
PYTHONPATH=. .venv/bin/python -m pipeline.scripts.daily_refresh

# Sync only — reuse the parquet snapshot already on disk, skip the CSV step
PYTHONPATH=. .venv/bin/python -m pipeline.scripts.daily_refresh --skip-pipeline

# Leave the standalone export out
PYTHONPATH=. .venv/bin/python -m pipeline.scripts.daily_refresh --skip-standalone
```

### Time-zone check (before a refresh, when the export changed)

```bash
PYTHONPATH=. .venv/bin/python -m pipeline.scripts.check_time_zones

# ...and which regions and lead teams sit behind each zone
PYTHONPATH=. .venv/bin/python -m pipeline.scripts.check_time_zones --context
```

The source's time-zone column is a lookup into a list the organisation
maintains, so its values are display names — `Hong Kong, China, Taiwan Time -
GMT+8:00` — which the ETL translates to IANA zones via `TIME_ZONE_MAP` in
`process_cplan.py`. The studio's select offers every zone that table maps to;
`tests/test_studio.py` fails if one is missing, because a target with no option
is a synced activity whose drawer reads "Not set" for a field that is filled.

A value the table does not translate is stored as it stands and reported here as
unmapped — nothing is lost, but the select cannot offer it either. And since
`activities.time_zone` is a fixed-width column, an untranslated value longer than
it ends the refresh on the INSERT before a single row is written, and every
activity then reads as missing a time zone. This lists what the export carries,
names anything that will not fit, and exits nonzero when it finds one. On
Windows, `timezones.cmd` (add `-Context` for the breakdown).

`--context` answers a different question. The labels are inherited descriptions
— they are the legacy Java three-letter zone names — not places a planner typed,
so a zone can be picked for its offset or by mistake, and only its own rows say
which. A bucket whose activities all sit in one region means what it says; one
whose rows sit somewhere else is a mis-pick, and mapping it to the place in its
name would carry that mistake into the database.

### Standalone studio (read-only)

The third step exports the whole planning studio as one double-clickable file
that runs offline: `pipeline/output/cplan_studio_standalone.html`. All four
pages, every analytic, filters, the read-only drawer, CSV and Excel export — no
web server, no internet, no database. Writing, login and per-activity change
history stay in the studio. On Windows, `snapshot.cmd` builds and opens it.

The design is documented in
[`docs/superpowers/specs/2026-08-03-studio-standalone-design.md`](docs/superpowers/specs/2026-08-03-studio-standalone-design.md).
Note what the file is before sending it anywhere: the complete plan in
cleartext, with no access control and no expiry.

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
| `pipeline/output/reports/*.xlsx` | Calendar reports — this folder holds nothing else |
| `pipeline/output/cplan_dashboard_standalone.html` | Standalone dashboard — Parquet + meta.json embedded as base64, runs from `file://` by double-click (CDN libs still require internet) |
| `pipeline/output/cplan_studio_standalone.html` | Standalone planning studio — read-only, database-fed, fully offline (no CDN at all) |
