# CPLAN Planning Studio V6

V6 is an isolated planning workspace served by the local FastAPI application. It does not modify or replace V3, V4, or the V5 SharePoint draft.

## Data path

The browser uses same-origin REST endpoints only:

```text
V6 dashboard -> FastAPI -> configured PostgreSQL or SQLite database
```

- PostgreSQL is the preferred backend.
- SQLite is the explicit installer-free fallback.
- Backend credentials never enter the browser bundle.
- Activities are persisted immediately through versioned API updates.
- Stale writes are rejected with HTTP `409 Conflict`.
- No browser `localStorage`, DuckDB runtime, or external CDN is required.

Start and backend setup instructions are in `pipeline/api_v6/README.md`.

## Included planning capabilities

- Attention queue and planning completeness
- Lead-time distribution and short-notice rate
- Conflict versus same-pack orchestration detection
- Forward load and coverage horizons
- Campaign/pack orchestration scorecard
- Strategic alignment and data-quality diagnostics
- Activity drawer with validated database editing
- CSV export of filtered activities

## Tests

```bash
node --test tests/dashboard_v4_analytics.test.js
python3 tests/test_dashboard_v6.py -v
node --check pipeline/dashboard-v6-postgres/app.js
```
