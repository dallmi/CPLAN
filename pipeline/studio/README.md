# CPLAN Studio

The planning studio is served by the local FastAPI application. Earlier snapshot studios and the SharePoint draft have been retired; their implementations live in git history.

## Data path

The browser uses same-origin REST endpoints only:

```text
Planning studio -> FastAPI -> configured PostgreSQL or SQLite database
```

- PostgreSQL is the preferred backend.
- SQLite is the explicit installer-free fallback.
- Backend credentials never enter the browser bundle.
- Activities are persisted immediately through versioned API updates.
- Stale writes are rejected with HTTP `409 Conflict`.
- No browser `localStorage`, DuckDB runtime, or external CDN is required.

Start and backend setup instructions are in `pipeline/api/README.md`.

## Included planning capabilities

- Attention queue and planning completeness
- Lead-time distribution and short-notice rate
- Conflict versus same-pack orchestration detection
- Forward load and coverage horizons
- Campaign/pack orchestration scorecard
- Strategic alignment and data-quality diagnostics
- Activity drawer with validated database editing
- Pack bulk creation: shared fields once, channel matrix, one atomic batch save
- Activity duplication and campaign/pack filtering for fast find-and-clone
- CSV export of filtered activities

## Standalone export (read-only)

`pipeline/scripts/build_studio_standalone.py` writes the whole studio into one
file — `pipeline/output/cplan_studio_standalone.html` — that opens by
double-click with no web server and no internet. Every asset `index.html`
references is inlined from `pipeline/studio/` at build time, and the activities
are embedded as JSON straight from the database.

```bash
python -m pipeline.scripts.build_studio_standalone   # or: snapshot.cmd
```

The export runs as step 3 of `daily_refresh`, where it is deliberately
non-fatal: the refresh has done its job once the database is current.
`--skip-standalone` leaves it out.

| Works offline | Absent by design |
|---|---|
| all four pages, every analytic | create, edit, delete, pack bulk create |
| filters, search, sorting, date range | login and sign-out |
| read-only drawer | per-activity change history |
| CSV and Excel export | live sync status (frozen at export) |

Read-only is not a separate mode: `snapshot.js` supplies a repository with the
same method surface as `DatabasePlanningRepository`, and the session declares the
`viewer` role, which switches off every write affordance through the role gating
the multi-user backend already uses.

**The file carries the complete plan in cleartext, with no access control and no
expiry.** The header band names the export date so nobody reads stale numbers as
current, but distribution is not controllable once it is sent.

## Tests

```bash
node --test tests/analytics.test.js tests/xlsx.test.js tests/snapshot.test.js
python3 tests/test_studio.py -v
node --check pipeline/studio/app.js
```
