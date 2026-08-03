# The planning studio as a standalone, read-only HTML file

**Date:** 2026-08-03
**Status:** approved

## Problem

The planning studio needs a running FastAPI process and a reachable database.
That is right for planning work, and wrong for everyone who only wants to look:
a stakeholder who needs to explore the plan, sort it, filter it and pull a table
out of it has to be talked through a local install first.

The repository already ships one standalone artefact —
`pipeline/scripts/build_standalone.py`, which embeds Parquet into
`pipeline/dashboard/index.html`. It predates the studio, carries the older
analytics, and still needs the internet for its CDN libraries.

## What makes this cheap

Four properties of the studio, established by reading it, decide the whole
design:

**It has no external dependencies.** `analytics.js`, `xlsx.js`, `app.js` and
`styles.css` are local, and none of them touches the network. `xlsx.js` is the
project's own workbook writer. The studio can already run with no internet at
all; the only thing standing between it and a `file://` URL is the API.

**Everything derives from one payload.** Overview, Activities, Packs, Health and
every analytic in `analytics.js` are computed in the browser from
`state.snapshotRows`, the result of a single `GET /api/activities`. There is no
server-side aggregation to reimplement.

**There is exactly one seam to the server.** `DatabasePlanningRepository`
(`pipeline/studio/app.js`) is the sole API client, plus four loose calls:
`/api/me`, `/api/login`, `/api/logout`, and the `DELETE` in `deleteActivity`.

**Read-only already exists.** The role gating written for the multi-user backend
— `canCreate`, `canEditActivity`, `canDelete`, `applyRoleGating` — produces
exactly the read-only interface this feature wants when the role is `viewer`.
Nothing in `styles.css` hangs off `data-role`, so there is no styling to
untangle either.

So this is not a port. It is a second repository implementation plus an
inlining build step.

## Decisions

**The snapshot comes from the database, not from the Parquet.** Activities
created directly in the studio have no `legacy_sp_id` and never appear in
`communications.parquet`. A Parquet-fed export would silently omit exactly the
rows the studio exists to produce. The build therefore requires a reachable
database and fails loudly when it has none, rather than quietly shipping a
partial plan.

**Serialization reuses the API's own read model.** The build serializes through
the same `ActivityRead` model the API's `GET /api/activities` returns. A
hand-written second serializer is the most likely place for this feature to rot:
it would drift the first time a field is added, and the failure would surface as
a subtly wrong dashboard rather than an error. There is one definition of an
activity's wire shape and both paths use it.

**The mode is chosen in `app.js`, not faked at the network layer.** The existing
`build_standalone.py` intercepts `fetch()` to serve embedded files. That was
right for data-file loads. Faking a REST API — request bodies, status codes,
`/api/me`, the login overlay's 401 path — is a different and much more fragile
job. Instead `app.js` reads `window.__CPLAN_SNAPSHOT__` and picks its repository
and session from it. One honest code path, testable from Node.

**Assets are inlined from the live studio directory.** The build reads
`pipeline/studio/*.{css,js}` at build time and never keeps a copy. A copied
studio would be a second implementation that diverges the first week nobody
looks at it.

**The change history is deliberately not embedded.** It names who changed what
and when. In a file whose whole purpose is to be handed around, that is a second
confidentiality surface for a panel almost nobody opens. `loadHistory` already
wraps its call in try/catch and renders an empty state on failure, so the
snapshot repository rejects the call with a message that explains itself.

**The existing Parquet standalone dashboard stays, for now.** The two are
clearly distinguishable by filename. Retiring `build_standalone.py` and
`pipeline/dashboard/index.html` is a separate decision, taken once the new
artefact has been used in anger.

## Architecture

```
database ──► build_studio_standalone.py ──► cplan_studio_standalone.html
                       ▲                            (one file, opens by
pipeline/studio/ ──────┘                             double-click, offline)
  styles.css, analytics.js,
  xlsx.js, snapshot.js, app.js
```

| File | Change | Size |
|---|---|---|
| `pipeline/studio/snapshot.js` | new, checked in | ~70 lines |
| `pipeline/scripts/build_studio_standalone.py` | new | ~160 lines |
| `pipeline/studio/app.js` | modified | ~10 lines |
| `pipeline/scripts/daily_refresh.py` | modified | step 3 of 3 |
| `snapshot.cmd`, `snapshot.ps1` | new | as `report.cmd` |

Output: `pipeline/output/cplan_studio_standalone.html`, already covered by
`pipeline/output/*.html` in `.gitignore`.

## The snapshot repository

`snapshot.js` defines `SnapshotPlanningRepository` with the same method names as
`DatabasePlanningRepository`, reading from `window.__CPLAN_SNAPSHOT__`:

| Method | Behaviour |
|---|---|
| `listActivities()` | embedded items |
| `health()` | `{status:'ok', database:'snapshot'}` |
| `latestSyncRun()` | the sync run frozen at build time |
| `getActivityChanges()` | rejects: `History is not available in a snapshot` |
| `createActivity`, `createActivitiesBatch`, `updateActivity` | reject: `This is a read-only snapshot` |

The write rejections are a safety net, not the user-facing story — the role
gating below means nothing in the interface can reach them.

## Changes to `app.js`

Three points, no restructuring:

1. Repository selection: `window.__CPLAN_SNAPSHOT__ ? new SnapshotPlanningRepository() : new DatabasePlanningRepository()`.
2. `initSession()` returns `{username:'snapshot', role:'viewer', auth:false}`
   without a fetch when a snapshot is present.
3. `backendLabel()` gains a `'snapshot'` case.

Everything else follows from the `viewer` role through code that already exists:

| Existing mechanism | Effect in the snapshot |
|---|---|
| `applyRoleGating()` | hides "New activity", "New pack", the overview create button |
| `canEditActivity()` → false | drawer opens read-only; no edit affordances, no "— Add" jumps |
| `canDelete()` → false | no delete |
| `updateUserChip()` (`auth !== true`) | no user chip |
| no 401 is possible | the login overlay never appears |

## Telling the truth about being a snapshot

Two places would otherwise mislead:

**The header.** `updated 14:32` becomes `Snapshot · 3 Aug 2026 · read-only`.
Somebody opening the file two weeks later must see the age of the data before
they read a number off it.

**The Health page.** The reconciliation card currently states `Write adapter:
PostgreSQL REST API` and `Versioned writes: stale updates are rejected with HTTP
409`. Neither is true here. Both are replaced with `Read-only snapshot, exported
<date>`.

## What the file can and cannot do

Works, entirely offline: all four pages, every analytic, filters, search,
sorting, date range, the pack view, the read-only drawer, CSV export, XLSX
export.

Absent by design: create, edit, delete, bulk pack creation, login, per-activity
change history, live sync status.

## Wiring into the run

- **`daily_refresh.py`**: a third step after pipeline and sync. Non-fatal — a
  failed export must not make a successful refresh report failure. It prints
  what went wrong and exits with the refresh's own status.
- **Standalone script**: `python -m pipeline.scripts.build_studio_standalone`,
  for exporting on demand between daily runs.
- **`snapshot.cmd`**: double-clickable, resolves the interpreter the way
  `report.cmd` does (`CPLAN_PYTHON`, active venv, repo `.venv`), opens the file
  when finished. `-NoOpen` writes without opening.

## Testing

- `tests/test_build_studio_standalone.py` builds against a seeded test database
  and asserts: no `src=` or `href=` reference to a local asset survives in the
  output, the seeded rows are present in the embedded payload, and
  `window.__CPLAN_SNAPSHOT__` is defined before the inlined `app.js`.
- **The contract test that matters:** every public method of
  `DatabasePlanningRepository` exists on `SnapshotPlanningRepository`. Without
  it, the standalone breaks silently the first time the studio gains an
  endpoint.
- A Playwright smoke test opens the built file over `file://`, visits all four
  pages, triggers the CSV and XLSX exports, asserts no create button is visible,
  and asserts the page issued no network request beyond the file itself — the
  offline guarantee, checked rather than assumed.

## Accepted risk

The file carries the complete plan in cleartext, with no access control, and can
be forwarded without limit. The snapshot banner makes the data's age visible; it
does nothing about its distribution. Whoever holds the file holds everything in
it. That is the real decision behind this feature — the engineering is the easy
part — and it is taken knowingly.

## Out of scope

- Writing anything back from the snapshot.
- Any form of encryption, expiry or access control on the file.
- Retiring the Parquet standalone dashboard.
- Pagination or size limits. At current volumes the embedded payload is a few
  hundred kilobytes; revisit if the activity count reaches five figures.
