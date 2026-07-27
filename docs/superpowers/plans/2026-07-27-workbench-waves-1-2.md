# Workbench Waves 1 & 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Tasks T1/T2 run in PARALLEL (isolated worktrees, disjoint file ownership); T3–T6 run SEQUENTIALLY (same files).

**Goal:** Build the design-review enhancements (waves 1 & 2) into the real studio: kit-visual polish, accessible table semantics, and the create/edit flow overhaul (single entry + scope toggle, always-visible drafts, live ready-line, prefill, stay-open-after-create, pack table with fill-down and count-labelled atomic create).

**Reference implementation (authoritative for behaviour and naming):** the reviewed prototype at `.playwright-mcp/design-review/prototype/` (`workbench-drawer.js`, `workbench.js`, `workbench.css`). Tasks ADAPT it into the real studio — they never copy it wholesale, because the real studio has auth, roles, a REST API and an existing component vocabulary.

**Excluded (wave 3, do NOT build):** cancelled-status / reinstate (C5), conflict merge UI (I8). The existing 409 conflict banner stays as is.

## Global constraints

- Run tests: `PYTHONPATH=. .venv/bin/python -m pytest tests/<file> -v`; node suite: `node --test tests/analytics.test.js`.
- Kit rules bind (design-system/corporate-design-system.md): sentence case (no ALL CAPS), no underlines, no tints of brand colours, Lake50 `#0C7EC6` for focus/links, red scarce, 2px radius, Lucide/no emojis, English copy.
- The studio is auth/role-aware: `state.currentUser {username, role, auth}`, gates `canCreate()`, `canEditActivity(a)`, `canDelete()`. Every new affordance respects them (server remains authority).
- API contract (unchanged): `POST /api/activities` requires `source_type` + `activity_name` (min 1); all other fields nullable → **a draft is a normal POST with whatever is filled, but a name is always required** (UI rule: "A draft still needs a name."). `PATCH` requires `version`. Batch create per pack via `POST /api/activities/batch`.
- Completeness source of truth stays `REQUIRED_INTERNAL` / `REQUIRED_EXTERNAL` (app.js) — the ready-line, draft modal and readiness badges all derive from these lists; never introduce a second list.
- Prefill source: newest row in `state.rows` with `created_by === state.currentUser.username` (legacy solo mode: `created_by === 'studio'`), by `created_at` desc; keys: `lead`, `lead_team`, `time_zone`, `region`, `business_division`.
- Word choice in UI copy: "draft" (replaces "incomplete" in user-facing copy; the analytics term "incomplete" may remain in Analytics).
- Commit per task, imperative message. Controller pushes.

## File-ownership matrix (conflict avoidance)

| Task | May edit | Must NOT edit |
|---|---|---|
| T1 ∥ | `pipeline/studio/styles.css`; in `tests/test_studio.py` ONLY the function `test_kit_compliance_pass` | app.js, index.html |
| T2 ∥ | `pipeline/studio/app.js` (ONLY: table-render block in `applyActivityFilters`, `PRIORITY_DONUT_COLORS` map, strategic/coverage `barList` calls, attention-card class logic in `renderOverview`, time-filter `.filtering` class toggle); in `tests/test_studio.py` ONLY `test_a11y_open_rows_and_focus_trap`; new file `tests/test_studio_list.py` | styles.css, index.html, drawer functions |
| T3 → | `pipeline/studio/index.html`, app.js chrome (`openCreateDrawer`/`openPackDrawer`/`prepareCreateChrome`/`applyRoleGating`/`setDrawerEditing`), styles.css additive only; `tests/test_studio_drawer.py` (new) + fixing existing markers it breaks | — |
| T4 → | app.js flow functions + minimal index.html (modal), `tests/test_studio_flows.py` (new) | — |
| T5 → | app.js pack region + index.html pack markup + styles.css pack/order rules; `tests/test_studio_pack.py` (new) | — |
| T6 → | sweep across all three + `check.ps1` markers | — |

---

## T1 — Kit visual system (styles.css) [parallel]

Adapt the prototype's visual system (`prototype/workbench.css`) into the existing `styles.css`. Findings: I10, I11, I12(css), P3, P4, P5, P9(css), plus the class contract for T3–T5.

1. **I11 — kill the brand-colour tints.** Locate `--warning-tint`, `--danger-tint`, `--success-tint`, `--bronze-tint` and every use. Replace surfaces with Pastel I `var(--surface)` (or Pastel II where it already sits on Pastel I), status carried by the existing 3px left rule or a new 7px square `.dot` (see prototype `.badge .dot`, `.notice`, `.missing-list li`). Badges become: Pastel-I fill, black text, coloured dot (`.badge.ok/.warn/.bad/.muted` contract). Remove the tint tokens.
2. **I10 — one focus colour.** `[data-open-id]:focus-visible` and any other red focus outlines → `var(--info)`. Keep form-field Lake50 rule.
3. **I12 — no red for active filters.** `.time-filter.filtering .segmented button.active` (and related red filter styling) → default Grey VI segmented treatment.
4. **P3** `.badge.high` text `rgb(138,104,0)` → Bronze III `#6C5312` (or black if contrast fails on Pastel I). **P4** remove `text-decoration:underline` on `.fix-link:hover`, `.range-banner-clear:hover` (hover colour Lake90 `#07476F` only). **P5** remove `box-shadow` from `.card`, `.login-card`, `.ms-popover`, `.toast` (keep on `.drawer-panel`, `.modal-card`). **P9** `.btn.stacked small` `opacity:.75` → full white 9px (T3 later removes stacked CTAs entirely; keep rule harmless).
5. **New class contract for later tasks** (port from prototype css, adapt token names): `.ready-line` (+`.ready` state, warning→success dot), `.prefill-note`, `.link-inline`, `.name-btn`, `.row-actions`, `.pack-table` (+`.ch-name`, `.stub`), `.fill-down`, `.pack-summary .atomic`, `.missing-list li` (pastel+amber rule), `.detail-row .row-edit` (hover-reveal, Lake50), drawer sticky footer grid (`.drawer-actions` two-column grid with `.action-group`). Sentence-case/letter-spacing rules follow the existing kit-pass.
6. Update ONLY `test_kit_compliance_pass` in `tests/test_studio.py`: add assertions — no `-tint` token remains, `.badge .dot` exists, no `text-decoration:underline`, `.ready-line` exists, card has no box-shadow (`assertNotIn("box-shadow", css.split(".card{",1)[1].split("}",1)[0])` style precision), focus outlines contain no `var(--primary)`.
7. Verify: `pytest tests/test_studio.py -q` green (other tests untouched must still pass — pure CSS cannot break markers).

## T2 — Table semantics & chart polish (app.js list region) [parallel]

Findings: C4, P6, P7, P10, I12(js). Reference: `prototype/workbench.js` `renderList`/`readinessCell`.

1. **C4:** in the table-render block of `applyActivityFilters`: drop `role="button"`/`tabindex` on `<tr>`; activity-name cell becomes `<button type="button" class="name-btn" data-open-id="...">`; whole-row click stays as mouse convenience (delegate unchanged); Copy/Duplicate become ordinary buttons in the tab order (Copy button visible on hover/focus per T1 CSS). Keyboard: Enter on the name button opens the drawer (native button).
2. **Readiness badge markup** switches to the T1 contract: `<span class="badge warn"><span class="dot"></span>N missing</span>` (semantics unchanged).
3. **P6:** `PRIORITY_DONUT_COLORS` Low `#CCCABC` → `#8E8D83`; ensure the five values remain distinct (adjust Medium to `#5A5D5C`/`#B8B3A2` spacing if needed).
4. **P7:** strategic/division-coverage `barList(..., true)` bronze flags → plain grey (drop the `true`).
5. **P10:** the "Attention required" card's red top border becomes status-driven: red/`--danger` only when the attention count > 0, otherwise `var(--surface)` (toggle a class from `renderOverview`).
6. **I12(js):** stop toggling any class that turns filter segments red (keep a neutral `.filtering` marker if other logic uses it).
7. Update `test_a11y_open_rows_and_focus_trap` (row-role assertions → name-btn assertions). New `tests/test_studio_list.py`: markers `class="name-btn"`, `badge warn`, absence of `setAttribute('role','button')` on rows... (assert real current behaviours).
8. Verify: `pytest tests/test_studio.py tests/test_studio_list.py -q`, `node --test tests/analytics.test.js`.

## T3 — Entry point & drawer chrome (markup) [sequential]

Findings: I1, C2(button), I3(markup), I9, P1, P2, P8, P11, P12. Reference: `prototype/activities-workbench.html` drawer markup + `workbench-drawer.js` `setScope`.

1. **I1:** page-actions become `Export filtered CSV (secondary) · New activity (primary)`; **remove** `#pack-new`. In the drawer, under the existing Activity-type segmented control, add `Scope · One channel | Several channels` (`#scope-toggle`, ids/`data-scope` per prototype). `setScope('pack')` drives the existing `state.packing` machinery (`data-pack-only`/`data-single-only` visibility) + widens the drawer (`.drawer.wide`). `applyRoleGating` now gates only `#activity-new`; remove pack-new gating. Drawer titles/notes per prototype (`New activity` / `New communication pack`, note texts).
2. **C2/I3 markup:** sticky footer restructured to the T1 grid: left `#ready-line` (dot + `#ready-text`) and `#save-hint` (the version-check hint moves here from the mode bar — P2), right `.action-group`: `Cancel · Save as draft (#btn-draft) · Create activity (#drawer-save)`.
3. **P1/P2:** in edit mode the eyebrow reads `Editing`; the mode bar is hidden while editing (its hint now lives in the footer).
4. **P8:** replace every required-asterisk `<span class="req">*</span>` with `<em>(required)</em>` styled per `.f-label em` (grey, non-italic). Remove now-unused `.req` markup (leave the CSS rule for T6 cleanup).
5. **P11:** variant help text → "Internal also captures audience size and news-digest consideration." (forward-framed; External variant text per prototype `setSource`).
6. **P12:** "Add another channel" input collapses behind a `link-inline` toggle ("Add a channel that is not listed") per prototype.
7. **I9:** pair short fields with the existing `form-grid`: Channel+Priority, Target audience+Estimated size, Lead+Lead team. Description/name/multiselects stay full-width.
8. Fix every existing test marker this breaks (`pack-new`, `.req`, old footer markup, skip-fields help text …) — grep before committing. New `tests/test_studio_drawer.py` with markers: `id="scope-toggle"`, `Save as draft`, `id="ready-line"`, `(required)`, absence of `id="pack-new"`, `Internal also captures`.
9. Verify: full `pytest tests/ -q` (studio files) + `node --test`.

## T4 — Create/edit flows (app.js) [sequential]

Findings: I3, C2, I4, I5, I2, C3, P13. Reference: `prototype/workbench-drawer.js` (`updateReady`, `attemptSave`, `openDraftModal`, `saveDraft`, `applyPrefill`, `requestClose`, `renderDetail` row-edit).

1. **I3:** `updateReady()` on every input/multiselect change: computes missing from `REQUIRED_INTERNAL/EXTERNAL` (+ pack rules in T5), toggles `#ready-line .ready`, text `N required fields left` / `Ready to create|save`; save button label per mode. Submit-time behaviour (paint `.missing`, focus first, hint `— or use "Save as draft"`) per prototype `attemptSave`.
2. **C2/I4:** `#btn-draft` opens the (renamed) draft modal — primary `Save as draft`, secondary `Go back and complete`, each missing field a `Fill it in` link that closes the modal and focuses the field (`data-jump`). Draft save = normal `repository.createActivity`/PATCH with what's filled; **name required** — if missing, modal lists it first and Save-as-draft focuses it instead of posting. After draft save: toast `Draft saved · <TID>` + Copy, reopen read-only; the drawer's detail head shows the "Saved as draft — N fields outstanding" notice (prototype `renderDetail` head).
3. **I5:** after full create: stay open read-only on the new record (already partially in place), toast `Created <TID>` with a Copy-ID button (prototype `W.toast(text, copyValue)` pattern), and a `Save and create another` secondary button in the mode bar that reopens a blank create with prefill.
4. **I2:** `applyPrefill()` from the newest own row (Global constraints rule); `#prefill-note` with `Start blank` link that clears the form. Duplicate flow reuses the note ("Copied from … — dates cleared…").
5. **C3:** unify dismissal: backdrop click, ×, Cancel and Escape all route through one `requestClose()` that opens the discard modal when dirty (create or edit), closes silently when clean. Escape first closes an open multiselect popover, then a modal, then the drawer (prototype keydown cascade). Verify the existing dirty-tracking covers multiselects.
6. **P13:** detail view: filled rows get a hover/focus-revealed `Edit` (`.row-edit`), empty rows keep `— Add …`; both call `setDrawerEditing(true)` + focus that field (extend the existing `data-add-field` mechanism to a shared `data-edit-field`).
7. New `tests/test_studio_flows.py`: markers `updateReady`, `Ready to create`, `Save and create another`, `Start blank`, `data-jump`, `requestClose`, `A draft still needs a name` (or the chosen copy), `row-edit`.
8. Verify: full pytest + node suites.

## T5 — Pack flow (app.js + markup) [sequential]

Findings: C1, I6, I7. Reference: prototype `renderPackRows`, `renderPackSummary`, fill-down handlers, `workbench.css` order rules.

1. **I6:** per-channel rows render as a `pack-table` (Channel · Activity name (required) · Start (required) · End (required) · Tracking ID stub), stubs live-update on start-date change (existing stub logic reused). `Fill down` block above the table (start/end for every channel, per-row still editable). Ticking a channel seeds the row name `"<pack name> — <channel>"` when a pack name exists.
2. **C1:** the pre-save summary is permanently visible in pack scope (empty state: "Nothing will be created yet — tick at least one channel"), lists per-channel name + ID stub, ends with `All N are created together, or none of them are.` The primary button is count-labelled `Create N activities`, disabled at 0 with label `Select a channel to continue`.
3. **I7:** section order in pack scope: Type/Scope → Identity (pack name, campaign) → Channels → "Applies to every activity in this pack" → shared fieldsets → per-channel rows → summary (CSS `order` rules per prototype; single scope order unchanged).
4. Pack draft rule: `Save as draft` in pack scope requires pack name + ≥1 channel + every row name (dates optional); posts via the existing batch endpoint; toast `N draft activities created — chased on the Overview`.
5. New `tests/test_studio_pack.py`: markers `pack-table`, `Fill down`, `Create ` count label logic string, `Select a channel to continue`, `created together, or none`.
6. Verify: full pytest + node suites.

## T6 — Sweep, markers, final gate [sequential]

1. Grep-sweep the leftovers: unused `.req` rule, `.btn.stacked` rules if the markup is gone, dead `--*-tint` references, duplicate readiness copy ("incomplete" vs "draft") in studio UI strings, stale comments.
2. `check.ps1` marker updates (same commit): `pipeline/studio/app.js` → `updateReady`; `pipeline/studio/styles.css` → `ready-line`; add `pipeline/studio/index.html` marker `scope-toggle` (replacing the generic title marker).
3. Final gate: `PYTHONPATH=. .venv/bin/python -m pytest tests/ -q` ALL green + `node --test tests/analytics.test.js` green.
4. Ledger update; controller runs the whole-branch review afterwards.
