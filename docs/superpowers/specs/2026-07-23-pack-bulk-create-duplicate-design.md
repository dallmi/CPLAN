# Planning Studio: Pack Bulk Creation & Activity Duplicate — Design

**Date:** 2026-07-23
**Status:** Approved by Michael (scope: pack level only, no cluster editor)

## Problem

Planning a communication pack today means filling the full create form once per
activity — a five-channel pack requires five complete passes through the drawer.
There is also no way to clone an existing activity and adjust a few fields.
Field feedback: the entry UX is not good enough.

## Scope decisions (from brainstorming)

1. **Pack flow shape:** shared-fields form + channel matrix (not "first activity
   + extra channels", not a grid editor).
2. **Duplicate:** button in the drawer (read-only mode) **and** an icon per
   table row. Opens the create drawer prefilled; nothing is saved until
   "Create activity".
3. **Cluster scope:** pack level only. Clusters are ICPG governance and are
   encoded in the pack CPID / tracking ID; no cluster editor.

## 1. Pack flow ("New pack")

- New button **New pack** next to **New activity** on the Activities page
  (`.page-actions`).
- Reuses the existing activity drawer with a third mode (`state.packMode`
  alongside `creating`/`editing`):
  - **Shared fields**, filled once: source type toggle (internal/external),
    campaign, communication_pack_cpid, activity_description,
    strategic_objectives, priority, target_audience, audience (internal only),
    business_division, business_area, region, time_zone, lead, lead_team,
    partner_team, news_digest (internal only).
  - **Channel selection:** checkbox grid of known channels for the selected
    source type (same source as today's channel `<select>`, via
    `distinctChannels(sourceType)`), plus a free-text input to add a channel
    that does not exist in the data yet.
  - **Activity rows:** one row per checked channel with:
    - *Activity name* — prefilled `"<campaign or pack> — <channel>"`, editable.
    - *Start* / *End* (`datetime-local`) — the first row is entered manually;
      subsequently checked channels default to the first row's values; each row
      remains individually editable.
  - Submit button **Create N activities** (count live-updates with checked
    channels).
- **Validation:** per activity the same required sets as today
  (`REQUIRED_INTERNAL` / `REQUIRED_EXTERNAL`); shared-field errors point at the
  shared field, per-row errors name the channel row (e.g. "Email: end date
  before start date"). At least one channel must be selected.
- **Persistence:** one atomic batch request (all-or-nothing). On success the
  drawer closes, rows are appended to state, toast shows
  "N activities created — <pack/tracking prefix>".

## 2. Backend: `POST /api/activities/batch`

- Request body: `{"items": [ActivityCreate, ...]}` (1–50 items).
- Single DB transaction; any validation failure rolls back everything and
  returns 422/400 with the failing item index in the error detail
  (`{"code": ..., "index": i, ...}`).
- Tracking IDs are generated sequentially inside the transaction using the
  existing `_generate_unique_tracking_id` logic so activity numbers within the
  pack are consecutive. Each generated ID is added to the in-transaction
  `existing` set so items in the same batch do not collide.
- Response: `{"items": [ActivityRead, ...]}` in request order, HTTP 201.
- `activity_changes` history: one `created` entry per activity with actor
  `studio` (same as single create).
- The existing single-create endpoint is unchanged.

## 3. Duplicate

- **Table:** new narrow trailing column with a Lucide `copy` icon button per
  row. Click opens the create drawer directly (stops propagation; does not open
  the detail drawer). Keyboard accessible (`aria-label="Duplicate <name>"`).
- **Drawer:** in read-only mode a **Duplicate** button next to **Edit
  activity**.
- Prefill: all `CREATE_FIELDS` plus source type from the source row, including
  dates and pack assignment. Drawer title "Duplicate of <name>"; mode badge
  "New record"; focus on *Activity name* with text pre-selected for quick
  overwrite.
- Tracking ID is generated server-side on save as today. Nothing is persisted
  until **Create activity** — cancelling leaves no residue. The standard
  dirty-discard modal applies.

## 4. Find: campaign/pack filter

- New dropdown **Campaign / pack** in the Activities filterbar, populated from
  `campaignLabel(row)` values (campaign, else pack CPID, else tracking pack
  prefix; the standalone prefix `STA-0000000` is excluded).
- Combines with the existing search and filters; included in the Clear action.
- Together with row-level duplicate this makes "find pack → clone activity →
  adjust two fields" a three-click flow.

## Error handling

- Batch API errors surface in the drawer validation area with the failing
  channel row named (mapped from the returned item index).
- 409 handling is not applicable to creation flows (no versions yet).
- Network failure: keep the drawer open with entered data; show error.

## Testing

- `tests/test_api.py`: batch endpoint — happy path, atomic rollback on a
  failing item, sequential tracking IDs within a batch, per-item validation
  error includes the index, history entries written.
- `tests/test_studio.py`: DOM contract — New pack button, channel matrix
  markup, duplicate buttons (row + drawer), campaign/pack filter element.
- `node --test tests/analytics.test.js` unchanged; `node --check
  pipeline/studio/app.js` for syntax.

## Out of scope

- Cluster creation/editing (ICPG governance).
- Editing multiple activities of an existing pack at once.
- Any change to sync or dashboard outputs.
