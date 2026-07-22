# CPLAN Planning Studio V4

V4 is a separate implementation. It does not modify or replace `pipeline/dashboard/index.html` or `pipeline/output/cplan_dashboard_standalone.html`.

## Open

Build the standalone artifact:

```bash
python3 pipeline/scripts/build_standalone_v4.py
```

Then open:

`pipeline/output/cplan_dashboard_v4_standalone.html`

DuckDB-WASM is loaded from jsDelivr, so an internet connection is still required.

## Local editing model

- The analytical snapshot remains read-only.
- Edits are stored in browser `localStorage` as a versioned local change set.
- Drafts are overlaid on the snapshot for all V4 views.
- Drafts are not applied when the tracking ID is duplicated or the source record changed after the draft was created; the change queue shows the conflict instead.
- **Export changes** downloads a `cplan-local-change-set/v1` JSON payload.
- No SharePoint records are changed by V4.

The UI uses a `PlanningRepository` boundary and a `LocalDraftRepository` adapter. A future SharePoint adapter can implement the same boundary with current-user authentication, ETags and conflict handling.

## Included planning capabilities

- Attention queue and planning completeness
- Lead-time distribution and short-notice rate
- Conflict versus same-pack orchestration detection
- Forward load and coverage horizons
- Campaign/pack orchestration scorecard
- Strategic alignment and data-quality diagnostics
- Activity drawer with validated local draft editing
- Local change queue, discard and JSON export
- CSV export of filtered activities

## Tests

```bash
node --test tests/dashboard_v4_analytics.test.js
python3 tests/test_dashboard_v4.py -v
```
