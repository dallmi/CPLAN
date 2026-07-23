# CPLAN Planning Studio

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
- CSV export of filtered activities

## Tests

```bash
node --test tests/analytics.test.js
python3 tests/test_studio.py -v
node --check pipeline/studio/app.js
```
