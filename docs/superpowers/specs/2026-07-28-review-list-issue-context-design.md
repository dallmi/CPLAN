# Planning Studio: Review-List Issue Context & Field Jump — Design

**Date:** 2026-07-28
**Status:** Approved by Michael (scope: studio UX only; time-zone backfill deferred to its own task)

## Problem

The Overview "Attention required" card groups findings by issue type and offers a
**Review list** button per group (`data-queue="incomplete" | "short-notice" |
"invalid-date"`). Clicking it jumps to the Activities workbench with
`state.queueFilter` set — but the workbench never says *why* those rows are
there. The only trace is a text suffix appended to the result count:
`23 of 210 · Missing fields — Clear to remove`.

Two concrete failures:

1. **No issue context.** After the jump you face a generic table. Neither the
   page nor any row states the finding that put it in the list.
2. **The Readiness column answers a different question than the one asked.**
   For a row in the `short-notice` or `invalid-date` queue the column reports
   completeness, which is unrelated to why the row is in the list. Two
   variants, both verified against the local snapshot (40 rows,
   `data/cplan.sqlite3`):

   - Row is 100 % complete → the column renders `—`. No issue shown, nothing
     to click, no way to fix.
   - Row is also incomplete → worse. Arriving from *"40 activities on short
     notice"*, the column shows `3 missing` / *"Description, Time zone,
     Estimated audience size"*, and the badge jumps to `activity_description`.
     Not one of those is the short-notice finding. The UI silently substitutes
     a different issue for the one the user clicked.

The drawer *does* already focus a field: the readiness badge carries
`data-fix-field="${ready.missing[0]}"` and `openDrawer` calls `focusField`. But
it only ever targets the first missing field, the remaining gaps stay hidden
behind a `title` tooltip, and `focusField` calls `.focus()` with no scroll and
no highlight — in the dense drawer form the native focus ring is easy to miss.

## Scope decisions (from brainstorming)

1. **Readiness column becomes `Issue`**, rendering the concrete finding as
   clickable chips — not a count with a tooltip. This is the option that also
   closes the gap for complete-but-flagged rows.
2. **A context bar above the table**, not a stronger inline pill. The queue a
   user arrived from is page-level state and deserves page-level chrome.
3. **Drawer gets focus + highlight + a jump bar** listing every open issue, so
   multiple gaps can be worked through in sequence.

All user-facing strings are English. The app has no German UI.

## 1. `rowIssues(row)` — one rule for "what is wrong here"

Lives in **`analytics.js`**, not `app.js`. `app.js` is a browser IIFE with no
exports and can only be checked by asserting on its source text; `analytics.js`
is a real module with a node test file and already owns `planningCompleteness`,
`requiredFor` and `parseDate`. Putting the rule there makes it genuinely
unit-testable and keeps the completeness logic and the issue logic in one place.

It returns **presentation-free descriptors** — `analytics.js` names no user-facing
copy today and must not start:

| Kind | `field` (focus target) | Extra |
|---|---|---|
| `invalid-date` | `end_date` | — |
| `short-notice` | `start_date` | `leadDays` |
| `missing` (one per field) | the missing field | — |

`app.js` maps a descriptor to its label via a thin `issueLabel(issue)` next to
`missingLabels`: `End before start`, `{leadDays}d lead`, and
`FIELD_LABELS[issue.field]` respectively. All user-facing strings stay in
`app.js` alongside the other copy.

Order: hard date error → short notice → missing fields (the latter in
`REQUIRED_*` order, so the list is stable across renders). Both the Issue column
and the drawer jump bar read only this helper, so the two cannot drift apart.

The order is **fixed, not queue-aware**. A row must read the same everywhere, or
the column becomes unlearnable — the same activity would lead with a different
chip depending on which link you arrived through. Because date findings sort
first, a row reached from a date queue leads with that queue's finding anyway,
and the context bar (§3) names the queue's headline regardless.

The two date predicates are currently inlined three times — in `renderOverview`
(app.js:464-465) and in `matchesQueueFilter` (app.js:645-646). They move into
`analytics.js` as exported `isShortNotice(row)` and `hasInvalidDates(row)`, and
all three call sites plus `rowIssues` use them. No refactoring beyond that.

`planningCompleteness` stays the sole owner of the completeness rule;
`rowIssues` composes it with the two date predicates and never re-implements it.

## 2. Activities table: `Readiness` → `Issue`

- Complete **and** no date problem → `—` (unchanged `.readiness-ok` span).
- Otherwise: up to two chips, plus a `+N` overflow chip when more remain.
- Each chip is `<button type="button" class="issue-chip" data-fix-id
  data-fix-field>`. The existing delegated `[data-fix-id]` handler
  (app.js:2165-2170) picks them up — no new event wiring.
- The `+N` chip carries the third issue's field as its target and lists every
  remaining issue in its `title`.
- Column header renamed to `Issue` in `index.html`.

**Colour.** All chips share one neutral pastel surface; a 2px left bar carries
severity — Bronze I for missing fields, RAG Amber for short notice, RAG Red for
the invalid date range. Same device as the `severity-line` already used in the
attention queue, and red stays a small accent reserved for the one finding that
is a genuine error. The orphaned `.missing-chip` rule in `styles.css` (unused
since the kit pass) is replaced by `.issue-chip`; the class name is
deliberately different so the existing "missing-chip is retired" test guard
keeps its meaning.

## 3. Queue context bar

New `#activity-queue-bar` between the filter row and the table card in
`index.html`, `hidden` by default. `applyActivityFilters()` fills and reveals it
whenever `state.queueFilter` is set, and hides it otherwise — the normal
workbench is visually unchanged.

Contents:

- severity line + title: `Missing fields` / `Short notice` /
  `Invalid date ranges` (reusing `QUEUE_FILTER_LABELS`)
- meta line: `{n} in view` plus a queue-specific detail —
  `Largest gap: Target audience (14)` for `incomplete`,
  `Under 7 days lead time` for `short-notice`,
  `End date before start date` for `invalid-date`.
  `{n}` and the largest gap are computed over the **rows currently in view**
  (`state.filteredRows`), not the whole dataset, so they stay truthful when the
  queue is combined with a search term or another filter.
- a `Clear` button

`Clear` and the existing `#activity-clear` button both route through one
`clearQueueFilter()` / `clearAllFilters()` pair so the reset logic exists once.
The `· {label} — Clear to remove` suffix on the result count is removed; the bar
replaces it.

## 4. Drawer: jump bar and field highlight

- New `#drawer-issue-jump` directly under `#drawer-mode`, above the fieldsets.
  Renders `To fix:` followed by one `link-inline` button per issue — the same
  `data-jump` pattern the draft modal already uses (app.js:1697).
- Rendered from `rowIssues(state.selected)` inside `setDrawerEditing(true)`,
  not inside `openDrawer` — a row opened read-only and then switched to edit via
  the drawer's own Edit control must get the bar too. `setDrawerEditing(false)`
  hides it, and `prepareCreateChrome` clears it so no stale list bleeds into a
  create/duplicate session in the reused drawer DOM.
- A jump button calls `focusField(name)` and takes an `active` class, so it is
  obvious which issue is currently targeted; the class moves on the next jump.
- `focusField` (app.js:960-978) gains two behaviours after the existing focus
  call: `scrollIntoView({block: 'center'})` on the field's `.f-label` container,
  and a transient `.pulse` class removed on animation end. The pack-row-token
  and multiselect branches keep their current targets and only inherit the
  scroll + pulse.

## 5. Tests

Three layers, because no single one covers this change:

**Behavioural (`tests/analytics.test.js`, node).** `rowIssues`, `isShortNotice`
and `hasInvalidDates` are real functions in a real module, so they get real
assertions: ordering (date findings before missing fields), the `leadDays`
payload, a clean row returning `[]`, the internal/external required-set split,
and a row that is both short-notice and incomplete.

**Static (`tests/test_studio_list.py`).**
`test_readiness_badge_uses_the_pastel_dot_contract` asserts the current badge
markup verbatim, so it moves with the code to the Issue-chip contract. The
`assertNotIn('class="missing-chip"')` guard stays. New guards: issue chips carry
`data-fix-id` and `data-fix-field`; the queue bar renders only under
`state.queueFilter`; the Issue column and the jump bar both read `A.rowIssues`;
`focusField` scrolls into view and applies the transient highlight; the date
predicates are called via `A.`, not re-inlined, at all three call sites.

**Click-through (chrome-devtools MCP against a local studio).** The API runs
against `data/cplan.sqlite3` (40 rows) via
`start_cplan.py --settings data/cplan-settings.json`. Walk: Overview → each
Review list → assert the context bar names that queue → click the leading issue
chip → assert the drawer is in edit mode and `document.activeElement` is the
field the chip pointed at. Only this layer can catch a chip that renders
correctly but focuses nothing.

## 6. Corp handover

Michael copies files by hand on the corp machine; `check.ps1` markers must only
match the **current** version of each file, otherwise a stale copy passes the
preflight. Three studio markers currently match the old files too and move:

| File | Old marker | New marker |
|---|---|---|
| `pipeline\studio\app.js` | `updateReady` | `issueLabel` |
| `pipeline\studio\analytics.js` | `requiredFor` | `rowIssues` |
| `pipeline\studio\index.html` | `scope-toggle` | `activity-queue-bar` |
| `pipeline\studio\styles.css` | `ready-line` | `issue-chip` |

`analytics.js` matters most here: `app.js` calls `A.rowIssues`, so a stale
`analytics.js` next to a current `app.js` breaks the Issue column and the drawer
outright. Its existing marker (`requiredFor`) would still match the old file.

## Files touched

- `pipeline/studio/analytics.js`
- `pipeline/studio/app.js`
- `pipeline/studio/index.html`
- `pipeline/studio/styles.css`
- `tests/analytics.test.js`
- `tests/test_studio_list.py`
- `check.ps1`

## Out of scope — time zone (separate task)

Recorded here so the finding is not lost.

`time_zone` is required for both variants (`REQUIRED_COMMON`, analytics.js:15)
and mirrored in the DB view as `missing_time_zone` (views.py:104). It is **not**
in `TEXT_FIELDS` / `ALLOWED_FIELDS` in `import_snapshot.py:25-30`, so the source
snapshot never carries it and no synced row ever gets a value. In
`data/cplan.sqlite3` all 40 of 40 rows are missing it — currently the single
largest contributor to the "missing fields" queue.

It cannot be derived from `region`: `region` is a multiselect (app.js:142), so a
row may hold `APAC;EMEA` with no single value to map, and the values are macro
regions (APAC 17, Americas 12, EMEA 11) spanning UTC+5:30 to +13 and UTC−10 to
−3 respectively. A mapping would silently stamp wrong local times onto the very
field that makes `start_date` / `end_date` interpretable.

The defensible default is `Europe/Zurich`: `import_snapshot.py:60-62` already
stamps naive source timestamps as `Europe/Zurich` before converting to UTC. The
assumption is in the code already — it is simply never written to the field.
Setting it on import (only where empty, so a value entered in the studio is
never overwritten by a sync) plus a one-off backfill would make it explicit.

Consequence for this spec: until that task lands, `Time zone` will be the
first — and on most rows only — chip in the new Issue column.
