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

## Commit guard — do this in every clone

This repository is public. Two things must never reach a commit: the
organisation's name, and an absolute path from the machine you work on — which
on most machines here spells out the organisation in its directory names.
Both have got in before, past a check that ran `git grep` on a file that was
not yet tracked and so matched nothing.

```bash
git config core.hooksPath .githooks
cp forbidden-terms.txt.example forbidden-terms.txt   # then fill in the real terms
```

The hook reads the staged diff — the thing that is actually about to become
history — and refuses the commit with the file and line it objects to. The
path half needs no configuration and runs from the moment `core.hooksPath` is
set. The term half reads `forbidden-terms.txt`, which is gitignored: a
committed list of words that must not appear in the repository would put every
one of them in the repository. Its `.example` carries placeholders, the same
arrangement `geb-members.csv` uses.

`tests/test_commit_guard.py` covers both halves, including that the hook names
no forbidden term itself and that removing a bad line is never blocked by the
line being in the diff.

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
| `pack/` | four `.txt` and three `.csv` — four where a pack export was synced: what the skill archive is built from, and the readable copy of what the agent holds. **Not uploaded** — see below |
| `cplan-skill.zip` | the same content as a skill package, `SKILL.md` at the archive root |
| `chart-standards-skill.zip` | the visual rules as a second skill. No data files, so it is rebuilt identically every run — upload it once and again only when the rules change |
| `evaluation.csv` | the same questions as an importable test set. Safe to upload: an evaluation set is never grounded on |
| `agent-instructions.md` | the whole agent prompt. Paste into Instructions after one find-and-replace of `<ORGANISATION>` |
| `checklist.md` | questions with computed answers, half of them pre-computed in the pack and half not. **Not for uploading** — an agent that can read the answer key passes without computing anything |

**The pack's scope is wider than the workbook's.** The report is a planning
instrument and drops what nobody plans against — priority 4, and rows tagged
with nothing but the catch-all objective. The agent answers questions, and
"which deprioritised activities are coming up" deserves an answer, so
`agent_pack.pack_config` drops those two filters. The period is untouched.

That makes the two disagree about how many activities there are, which is
normally the failure this repository is built to prevent. It is survivable only
because it is visible from both ends: every row in `05-activities.csv` carries
`in_report` and `report_exclusion`, counting `in_report = Yes` reproduces the
workbook exactly, and `01-summary.txt` states how many rows the difference
covers. A silent divergence would be a wrong number that looks right.

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
`--geb-members path/to/list.xlsx` (or `report.ps1 -GebMembers ...`,
`agentpack.ps1 -GebMembers ...`). The file names each GEB member by email
and/or display name, in two columns headed `email` and `name`. Either format is
read, chosen by the extension:

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

The agent pack takes the same list, through the same `resolve_scope`, and both
deliveries carry the result:

| | Without a list | With one |
|---|---|---|
| `04-calendar.csv`, `06-breakdowns.csv` | `block=executives` | `block=executives_geb` and `block=executives_geb1` |
| `01-summary.txt` | `With GEB/GEB-1 involvement` | plus `With GEB involvement`, named as a subset |
| `02-glossary.txt` | never name a GEB member | the blocks separate the levels, and the list is the source |
| `03-data-quality.txt` | — | `GEB list entries`, `GEB list entries never matched` |
| `05-activities.csv` | `GEB/GEB-1 members` | plus `GEB members` and `GEB-1 members` |

The prose matters as much as the figures here. An agent believes a sentence
about the data over the data — that is what the sentence is for — so a pack
whose blocks separate the levels while its glossary says nothing can is worse
than one that never split them. `02-glossary.txt` therefore follows the run,
and the pasted prompts, which stay put while the pack is rebuilt underneath
them, describe both states rather than assert either.

What does *not* change with a list: no GEB-1 line in the summary (an activity
can name people at both levels, so the two would not partition the combined
figure), and no board label reading "GEB" — every panel on *Leadership
attention* counts the combined field.

#### The same pack for Agent Builder

Publishing through Copilot Studio needs registration and review. Agent Builder
in Microsoft 365 Copilot needs neither — an agent built there is shared with
named people, or exported as a ZIP for an administrator, the day it is
finished. `agentpack.cmd` writes that delivery too, from the same run, into
`Projekte/CPLAN/Output/agent-builder` (`pipeline/output/agent-builder/` without
OneDrive). `README.txt` in that folder is the four steps in order.

Both deliveries come from one command deliberately. Two commands would let one
be rebuilt and the other forgotten, and two packs built on two days are two
vintages of one figure with nothing on either folder saying so.

The surface holds 8,000 characters of Instructions and **no skill packages at
all**, so the two skills have nowhere to go: `08-reading-guide.txt` and
`09-chart-standards.txt` ship as knowledge files instead, and `upload/` holds
those two, the three board files `10`–`12-board-*.txt`, and the data files —
**eleven** sources on a machine with no pack export, **twelve** where
`07-packs.csv` was written, against a limit of twenty. Both counts are real:
the pack export is optional, and the folder is uploaded whole either way.
`00-README.txt` stays out for the reason the skill archive leaves it out, and
`checklist.md` stays out because an agent that can read the answer key passes
without computing anything.

##### The upload folder mirrors itself

The knowledge files also land in the agent's **own** folder in the same run, so
the copy that used to close this delivery no longer has to be made by hand. A
hand copy is a step that can be skipped, and a skipped one is invisible: the
folder still looks full, and the agent answers this month's questions from last
month's pack.

That folder is not named in this repository, because it cannot be. It sits in a
synced document library, under a tenant and a site that differ per machine, per
person and per agent. Its *shape* is what the run looks for: a folder called
`CPLAN/agent`, one or two levels below the user profile. Creating it in
Explorer is the whole instruction. `-AgentDir` names one instead, and so does
`CPLAN_AGENT_DIR`; two candidate folders and none is written to, because the
wrong knowledge in the right place is not visible from either.

Only the numbered knowledge files are mirrored — never `checklist.md`, never
`instructions.md`. Everything in that folder is grounded on, exactly as in
`upload/`. Numbered files an earlier run left behind are removed, and that half
cannot be skipped: the numbering shifts whenever a file is added — the boards
moved from `09`–`11` to `10`–`12` when the chart rules became a knowledge file
— so copying alone leaves the previous run's board beside this run's, both
retrievable and both looking current. Anything else in the folder is left
alone. A folder that was named and is not there ends the run with exit code
`3`: the pack was written, and only the mirror was not.

The prompt is a separate hand-written literal rather than the Studio one with
sections removed: which rules survive a compression to 8,000 characters is an
editorial judgement, and `tests/test_agent_builder.py` holds it to a named list
of the rules whose absence makes an answer *wrong* rather than merely duller.
The palette and the red-to-white ratio move up into it, because a knowledge
file is retrieved rather than loaded — a missed document should cost an ugly
chart, not an off-brand one.

This inverts two decisions made deliberately next door: the rules were moved
*out* of Instructions into skills, and the knowledge source was *removed* after
two probes showed it was never reached for. Both inversions are forced by the
surface rather than chosen. The consequence to watch is the one those probes
found — counting over `05-activities.csv` worked because the agent read the
file whole, and chunked retrieval is the one thing that cannot. `01-summary.txt`
and `06-breakdowns.csv` pre-compute what they can; the signal that it is not
enough is the agent no longer writing "examined all N rows".

The design is in
[`docs/superpowers/specs/2026-08-07-agent-builder-variant-design.md`](docs/superpowers/specs/2026-08-07-agent-builder-variant-design.md).

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

### Tracking-ID check (are these IDs real?)

```bash
# Which of the IDs in this list are actually in the export
python -m pipeline.scripts.check_tracking_ids --ids ids.txt

# ...and list the ones that were found too, and keep the result as a CSV
python -m pipeline.scripts.check_tracking_ids --ids ids.txt --all --csv result.csv
```

Tracking IDs travel by hand — in a mail, on a slide, pasted out of a planning
sheet — and the question asked of them is whether the activities behind them
exist at all. This takes the list (one ID per line; blank lines and `#` lines
are ignored), reads the four activity exports the pipeline itself reads, and
reports the ones it could not find. On Windows, `trackids.cmd`.

A match is exact. The work is in the misses: an unfound ID is reported with the
nearest thing in the export — the same activity on another channel, the pack it
should have belonged to, or an ID one character away — because "never created"
and "spelled wrong" lead somewhere completely different. The reason and that
nearest ID get a column each, since a tracking ID is 32 characters and sharing
one column truncates the part worth reading. The hint is never a verdict; the
row still reads missing.

Only the activity exports are searched, live and archived. The pack, channel
and cluster exports carry their own identifiers, and searching them would let a
pack ID report as a found activity. Exit code 0 only when every listed ID was
found.

### Pack-link check (does the pack export actually join?)

```bash
# Which activity column links to the pack list, and how well
PYTHONPATH=. .venv/bin/python -m pipeline.scripts.check_pack_link

# ...against a folder that is not the usual input, keeping the scores
PYTHONPATH=. .venv/bin/python -m pipeline.scripts.check_pack_link --input <folder> --csv scores.csv

# ...keeping one row per identifier, with the category it fell into
PYTHONPATH=. .venv/bin/python -m pipeline.scripts.check_pack_link --detail identifiers.csv
```

Three activity columns could carry the pack's identifier —
`communication_pack_cpid`, `campaign_ltid`, and the `tracking_pack_id` split out
of the tracking ID — and the exports do not say which one the pack list answers
to. Choosing by reasoning would put an unverified assumption under
`07-packs.csv`, where a wrong join does not look wrong: it looks like a pack
file with plausible numbers in it.

So it is measured. This reads the same exports a refresh reads, read-only, and
reports which columns of the pack export the ETL does not map, and how each
candidate column scores against the pack list. Three sample values are printed
**per side**, because a candidate at 0% is otherwise unreadable — an export
that does not link at all and one whose identifiers are merely spelled
differently (`CP-100` against `100`) produce the same zero, and only the two
sample lines tell them apart. On Windows, `packlink.cmd`.

One candidate is scored twice, and the second reading is the one to act on. A
tracking ID is `<cluster>-<pack number>-<date>-<activity>-<channel>` and is
generated for **every** activity, with generic cluster and pack identifiers
where there is no pack — which is the normal case, since a pack is attached
only to the larger communications and a cluster only where several packs belong
together. Counted as references, those placeholders turn "how many activities
have a pack" into a number sitting where a reader looks for "how many
references resolve": on the export of 2026-08-11 that was `tracking_pack_id` at
10%, which said nothing about the join at all. So the placeholders are measured
by frequency rather than assumed, named in the output, and taken out of the
rate. Every reference then falls into a category — resolved, generic, cluster
prefix differs, zero padding differs, a number two packs share, or no pack —
which separates a repairable join from a dead identifier; `--detail` writes one
row per identifier so the verdict can be checked against the export instead of
believed.

The tracking ID's pack number is scored as a candidate of its own, without the
cluster prefix in front of it. The two are not the same question: the live
export carries the generic cluster over real pack numbers, so a pack whose
prefix drifted is a miss for `tracking_pack_id` and a hit for the number alone.
What that costs is printed beside it — dropping the prefix leaves nothing to
tell two packs with the same number apart, so those references are counted on
their own line instead of being assigned to one of them.

The fallback chain `communication_pack_cpid` then `tracking_pack_id` is scored
beside the real columns and deliberately kept out of the winner selection: it
needs code the ETL does not have, and it resolves at least as well as its first
column by construction, so scoring it as a candidate would report a tie needing
a human on every healthy export. Whether it may be built is decided by the last
figure instead — the activities where **both** columns name a pack and name
different ones. Every other number says how much resolves; only that one can
say it resolves to the wrong pack.

Exit code 0 only when exactly one candidate clears 80% of the activities that
carry any pack reference at all. That floor is `packs.MIN_LINK_RATE` itself —
the check imports it rather than restating it, so the rate this gate passes at
and the rate a report run warns below cannot drift apart — and the winner is
what `packs.PACK_LINK_COLUMN` holds. Run this whenever the pack export changes
shape, and before merging any change to how the two are joined.

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
- `CommunicationPacks*.csv` — the communication pack list. Optional, and
  everything downstream of it is inert without it: no `07-packs.csv`, no
  `pack_known` column on the activity rows, and no pack-list figures in
  `03-data-quality.txt`. A machine syncing only the two activity exports
  produces exactly the output it produced before the pack list existed, which
  is why nothing errors when it is absent — run the pack-link check above to
  see whether it is arriving and whether it joins.

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
| `<OneDrive>/Projekte/CPLAN/Output/agent-builder/upload/` | Agent Builder knowledge — eleven files, twelve where a pack export was synced; uploaded whole |
| `<OneDrive>/Projekte/CPLAN/Output/agent-builder/instructions.md` | Agent Builder Instructions — pasted, after one find-and-replace |
| `<synced library>/CPLAN/agent/` | the same knowledge files, mirrored into the folder the agent is fed from — created by hand once, kept current by every run |
