# MCP Phase 2 — Cross-Tabulation, Calendar, Collisions, Packs, History

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the eight remaining Tier-1 and Tier-2 catalogue questions that need
analytics rather than filters — the ones a human at the studio can see today and an
agent cannot.

**Architecture:** Four new read tools plus one widened one, all on the machinery
Phase 1 built. `_build_filters` / `_filtered_activities` / `ActivityFilters`
already give every new tool the full filter set for free; `split_multi`,
`priority_rank`, `lead_days`, `_bucket_keys` and `_capped_by_count` are the
primitives the ports need. Three of these tools mirror logic that already exists
in `pipeline/studio/analytics.js`, so each one gets a test that pins it against
that source the way `test_priority_rank_matches_the_studio_implementation` does.

**Tech Stack:** Python 3.13, SQLAlchemy 2.x, `mcp` SDK 2.0, pytest parametrized
over SQLite + PostgreSQL.

**Source spec:** [`../specs/2026-08-03-persona-question-catalogue-design.md`](../specs/2026-08-03-persona-question-catalogue-design.md)
(Phase 2 of its Roadmap). Question IDs below are that catalogue's.

## Convention for this plan

Phase 1's plan pasted complete code because the patterns did not exist yet. They
exist now, so this plan specifies **semantics, signatures, and test assertions
exactly**, and points at the concrete precedent in the tree for mechanics
(`queries.activity_counts` for a grouped answer, `queries.planning_gaps` for a
narrowable one, `tests/test_mcp_server.py::test_priority_rank_matches_the_studio_implementation`
for a drift pin). Where a semantic rule is subtle, it is written out in full —
that is where the defects live. A reference to a named precedent is not a
placeholder; a vague instruction would be.

## Global Constraints

- **Read-only, enforced by the connection.** No tool may write. Never open a
  writable session in `pipeline/mcp/`.
- **Backend-neutral.** Every query test runs on SQLite always and PostgreSQL when
  `CPLAN_TEST_DATABASE_URL` is set. No dialect-specific SQL.
- **Never build on the `v_*` views** — PostgreSQL-only, a no-op on SQLite.
- **`queries.py` and `domain.py` import no `mcp`.** Only `server.py` does.
- **Caps.** `DEFAULT_LIMIT = 50`, `MAX_LIMIT = 200`. Every list- *and* bucket-shaped
  answer reports its own truncation; reuse `_capped_by_count`.
- **Fixtures.** Row-inserting tests take `writable_session`; pure tests take no
  fixture. Never `str(engine.url)` for a server URL — it masks the password. Use
  `engine.url.render_as_string(hide_password=False)`.
- **No brand names, personal names, or production identifiers** anywhere,
  including commit messages. Synthetic fixture data only.
- **CHECK** (both halves, always):
  ```bash
  .venv/bin/python -m pytest tests/ -q && node --test tests/*.test.js
  ```
- **PostgreSQL run** at Task 8:
  ```bash
  docker run --rm -d --name cplan-pg -e POSTGRES_PASSWORD=looptest \
    -e POSTGRES_USER=cplan -e POSTGRES_DB=cplan \
    -p 127.0.0.1:55433:5432 postgres:17-alpine
  CPLAN_TEST_DATABASE_URL=postgresql+psycopg://cplan:looptest@127.0.0.1:55433/cplan \
    .venv/bin/python -m pytest tests/ -q
  docker stop cplan-pg
  ```
- Commit after every task; imperative message, no brand names.

## File Structure

| File | Change |
|---|---|
| `pipeline/mcp/queries.py` | Modify — all new query logic |
| `pipeline/mcp/server.py` | Modify — new tool registrations (Task 7) |
| `pipeline/mcp/domain.py` | Modify — describe the new answers (Task 7) |
| `pipeline/mcp/README.md` | Modify — tool table, design notes (Task 8) |
| `tests/test_mcp_server.py` | Modify — every task adds tests here |
| `evals/questions.py` | Modify — one eval question per closed catalogue entry (Task 8) |

---

## Task 1: Cross-tabulation and finer time buckets

Closes Q4, Q12; improves Q14, Q41, Q40, Q3, Q7. The real questions are
two-dimensional (channel by month, division by priority, audience by day) and
today the agent must fetch rows and count them itself, which collides with the
row caps.

**Files:** Modify `pipeline/mcp/queries.py`; test in `tests/test_mcp_server.py`.

**Interfaces produced:**
- `TIME_BUCKETS: tuple[str, ...] = ("day", "week", "month")` and
  `_time_bucket_key(value: datetime | None, bucket: str) -> str`.
  `day` → `YYYY-MM-DD`, `week` → `YYYY-Www` (ISO week, so `2026-W32`), `month` →
  `YYYY-MM` (the existing `_month_key` shape). `None` → `"unscheduled"` on every
  bucket, matching `_month_key` today.
- `GROUPABLE_FIELDS` gains `"day"` and `"week"` alongside `"month"`.
- `activity_counts(session, *, dimension, second_dimension=None, **filter_kwargs)`.

**Semantics that matter:**
- With `second_dimension`, buckets become `{"value": <d1>, "second_value": <d2>,
  "count": n}`. Keep the flat one-dimensional shape unchanged when it is `None` —
  an agent that asked for one dimension must not get a different response shape.
- **Cross-tabs multiply.** 32 packs × 15 channels is 480 buckets, and Phase 1's
  flat `MAX_LIMIT` cap is the wrong shape for two axes: truncating a flat sorted
  list silently drops whole rows of the table. Cap **per axis instead**: keep the
  top `MAX_CROSS_AXIS = 20` values of each dimension by total count, plus report
  `axis_truncated: {"dimension": bool, "second_dimension": bool}` and the true
  `distinct_values` per axis. An agent must be able to tell "these are the top 20
  channels" from "these are all the channels".
- Multi-value dimensions still tally members on both axes; `counts_memberships`
  becomes true if **either** axis is multi-valued.
- Reject an unknown `second_dimension` with the same error-dict convention as
  `dimension`, naming `supported_dimensions`.

- [ ] **Step 1: Write the failing tests.** In `tests/test_mcp_server.py`:
  - `test_counts_cross_tabulates_two_dimensions` — three activities over two
    channels and two source types; assert the four-cell shape and counts.
  - `test_counts_without_second_dimension_keeps_the_flat_shape` — assert no
    `second_value` key appears, so the one-dimensional contract is unchanged.
  - `test_counts_by_week_buckets_iso_weeks` — two activities in the same ISO week
    and one in the next; assert `YYYY-Www` keys and the split.
  - `test_counts_by_day_buckets_dates` — assert `YYYY-MM-DD`.
  - `test_unscheduled_rows_bucket_together_on_every_time_grain` — parametrize over
    `("day", "week", "month")`, one row with `start_date=None`, assert
    `"unscheduled"` each time.
  - `test_cross_tab_caps_each_axis_and_says_so` — build more than
    `MAX_CROSS_AXIS` distinct channels; assert `len` per axis ≤ the cap, that
    `axis_truncated["dimension"]` is True, and that `distinct_values` reports the
    real total. **This is the test that would catch a flat cap** — write it so it
    fails if the implementation truncates the flat bucket list instead.
  - `test_counts_rejects_an_unknown_second_dimension`.
- [ ] **Step 2:** Run them; expect failures on the unexpected keyword and unknown dimensions.
- [ ] **Step 3:** Implement. Follow `activity_counts`' existing two-branch shape
  (SQL group-by when possible, Python when a derived/multi-value/post-filtered
  dimension is involved). A cross-tab with any derived or multi-value axis is
  Python-grouped; a two-column SQL `GROUP BY` is fine when both axes are stored
  scalars and no post-filter is active.
- [ ] **Step 4:** Run the full CHECK.
- [ ] **Step 5:** Commit — `Let volume counts cross two dimensions and finer time buckets`.

---

## Task 2: Calendar load and window comparison

Closes Q4 fully and Q3, Q7, Q10; supports Q16. A planner's load question is
weekly, and "is this month busier than last" needs a comparison the agent
currently does by hand across two calls.

**Files:** Modify `queries.py`; test in `tests/test_mcp_server.py`.

**Interfaces produced:**
- `calendar_load(session, *, weeks=8, start_date=None, **filter_kwargs)` → per-week
  buckets `{"from": iso, "to": iso, "count": n}` plus `busiest` / `quietest` and
  `empty_weeks`. Mirrors `analytics.js::weeklyCoverage`: half-open `[from, to)`
  windows, `weeks` consecutive spans of 7 days from `start_date`.
- `window_comparison(session, *, days=30, reference=None, **filter_kwargs)` →
  `{"current": {...}, "previous": {...}, "change": n, "change_pct": float|None}`.
  Mirrors `analytics.js::comparisonWindow`: the previous window is the same span
  immediately before the current one.

**Semantics that matter:**
- **`start_date` and `reference` must be explicit parameters, defaulting to the
  latest sync run and falling back to `max(start_date)` in the data.** Do *not*
  call `datetime.now()`: the tools must be deterministic under test, and the eval
  already surfaced an agent reasoning about "next month" against a database whose
  clock it could not establish. Return the resolved anchor in the response as
  `anchor` with an `anchor_source` of `"argument"`, `"latest_sync"` or
  `"latest_start_date"`, so the agent can say what "next month" meant.
- `change_pct` is `None` when the previous window is empty — never `inf`, never 0.
- The week span is capped: `weeks` clamps to 1..52.

- [ ] **Step 1: Write the failing tests.**
  - `test_calendar_load_buckets_consecutive_weeks` — activities on known dates;
    assert per-week counts and half-open boundaries (an activity exactly on a
    `to` boundary belongs to the *next* week).
  - `test_calendar_load_names_empty_weeks` — a gap week appears with count 0 and
    in `empty_weeks`.
  - `test_calendar_load_resolves_its_anchor_deterministically` — no sync run
    present → `anchor_source == "latest_start_date"`; with a `SyncRun` row →
    `"latest_sync"`; with an explicit argument → `"argument"`. **Assert the same
    input yields the same anchor twice**, which is what pins out `datetime.now()`.
  - `test_window_comparison_counts_both_windows_and_the_delta`.
  - `test_window_comparison_reports_no_percentage_when_the_previous_window_is_empty`.
  - `test_calendar_load_clamps_the_week_count`.
  - `test_calendar_load_matches_the_studio_week_math` — parse
    `pipeline/studio/analytics.js` for `weeklyCoverage` and assert the 7-day step
    and half-open comparison (`>= from`, `< to`) are still what the studio does,
    in the style of the existing `priority_rank` studio pin.
- [ ] **Step 2:** Run; expect `AttributeError` on the missing functions.
- [ ] **Step 3:** Implement, reusing `_filtered_activities` for the candidate set.
- [ ] **Step 4:** Full CHECK.
- [ ] **Step 5:** Commit — `Answer the weekly load and window-over-window questions`.

---

## Task 3: Collision detection

Closes Q11 (rank 7) and Q13 (rank 13) — the highest risk premium in the
catalogue, and the thing a human at the studio can see that an agent cannot.

**Files:** Modify `queries.py`; test in `tests/test_mcp_server.py`.

**Interfaces produced:**
- `detect_collisions(session, *, proximity_days=0, limit=None, **filter_kwargs)`
  → `{"checked": n, "collisions": m, "returned": k, "truncated": bool, "note":
  str|None, "collisions": [...]}` with each entry
  `{"left": <summary>, "right": <summary>, "gap_days": n, "kind": str,
  "severity": str}`.

**Semantics — port `analytics.js::detectCollisions` exactly; this is the part to get right:**
- A pair collides only when it shares **both** a `channel` value **and** a
  `target_audience` value. Both are multi-valued: use `split_multi` and test set
  intersection, case-insensitively. **Either-not-both is wrong** and would flag
  most of the portfolio.
- `kind` is `"orchestration"` when both activities share a non-blank
  `tracking_pack_id` (the `CLUSTER-PACKNUM` prefix, available on `ActivityRead`),
  else `"conflict"`. **This distinction is the whole value of the tool**: two
  activities inside one pack hitting the same audience is good planning, not a
  problem. A port that drops it flags every well-orchestrated campaign and the
  tool gets ignored.
- `severity`: `"info"` when same-pack; otherwise from
  `max(priority_rank(left), priority_rank(right))` — `>= 4` → `"critical"`,
  `>= 3` → `"high"`, else `"medium"`.
- Ordering: severity descending (`critical > high > medium > info`), then
  `gap_days` ascending.
- Rows with no `start_date` are excluded from pairing.
- Cap the returned list with `_clamp_limit` and report truncation; the count is
  the true total.

**Cost note:** this is the fourth copy of shared logic in this codebase. It gets a
studio pin (below) for the same reason the completeness rule has two.

- [ ] **Step 1: Write the failing tests.**
  - `test_collision_needs_both_a_shared_channel_and_a_shared_audience` — three
    pairs: shares both (collides), shares channel only (does not), shares
    audience only (does not). **The single most important test in this task.**
  - `test_same_pack_is_orchestration_not_conflict` — two activities with the same
    `tracking_id` pack prefix; assert `kind == "orchestration"` and
    `severity == "info"` even at top priority.
  - `test_severity_comes_from_the_higher_priority_of_the_pair` — parametrize over
    numbered and worded vocabularies, asserting `critical` / `high` / `medium`.
  - `test_collisions_respect_the_proximity_window` — a pair 3 days apart is found
    at `proximity_days=3` and not at `proximity_days=1`.
  - `test_collisions_are_ordered_worst_first`.
  - `test_collisions_ignore_activities_without_a_start_date`.
  - `test_collisions_report_their_own_truncation`.
  - `test_collision_rule_matches_the_studio_implementation` — parse
    `analytics.js::detectCollisions` and assert both `sharesDimension` calls
    (`'channel'` and `'target_audience'`) and the `samePack` severity branch are
    still present, so a change on either side fails the suite.
- [ ] **Step 2:** Run; expect failures.
- [ ] **Step 3:** Implement over `_filtered_activities`. Sort candidates by start
  day and slide a window rather than comparing every pair, as the studio does.
- [ ] **Step 4:** Full CHECK.
- [ ] **Step 5:** Commit — `Find activities that collide on channel and audience`.

---

## Task 4: Pack and campaign overview

Closes Q37 (rank 2) properly and Q40; improves Q28, Q41.

**Files:** Modify `queries.py`; test in `tests/test_mcp_server.py`.

**Interfaces produced:**
- `pack_overview(session, *, limit=None, **filter_kwargs)` → per-pack
  `{"pack_id", "label", "activities", "channels", "channel_names", "objectives",
  "audiences", "first_date", "last_date", "span_days", "internal", "external",
  "incomplete"}`, ordered by `activities` descending, capped and truncation-reported.

**Semantics that matter:**
- **The pack key is the preference chain `communication_pack_cpid ||
  tracking_pack_id || communication_pack || campaign`**, exactly as
  `analytics.js::campaignScorecards` resolves it, and for the reason its comment
  records: measured on the same portfolio, `tracking_pack_id` collapsed everything
  into buckets of 273 and 125 while the pack id resolved 32 packs of 2–11. Getting
  this order wrong makes every metric describe the portfolio instead of a planning
  unit. Report which key each row resolved through as `key_source`.
- Activities where every key in the chain is blank are excluded, not bucketed
  together — a standalone activity is not a pack of one.
- `channels` / `objectives` / `audiences` are **distinct member counts** via
  `split_multi`, not raw string counts.
- `internal` / `external` split per pack, and `incomplete` reuses `missing_fields`
  so the readiness figure matches `planning_gaps` exactly.

- [ ] **Step 1: Write the failing tests.**
  - `test_pack_overview_prefers_the_pack_id_over_the_campaign_label` — one
    campaign label spanning three pack ids; assert three rows, not one. **The
    reason this tool exists.**
  - `test_pack_overview_falls_back_down_the_key_chain` — parametrize: only
    `communication_pack` set → `key_source == "communication_pack"`; only
    `campaign` → `"campaign"`; nothing set → row absent entirely.
  - `test_pack_overview_counts_distinct_members_not_strings` — an activity with
    `channel="Email, Intranet"` contributes 2 channels.
  - `test_pack_overview_readiness_agrees_with_planning_gaps` — assert the
    `incomplete` sum equals `planning_gaps`' `incomplete` for the same filter.
  - `test_pack_overview_orders_by_size_and_reports_truncation`.
  - `test_pack_key_chain_matches_the_studio_implementation` — parse
    `campaignScorecards` and assert the `||` chain order is unchanged.
- [ ] **Step 2:** Run; expect failures.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Full CHECK.
- [ ] **Step 5:** Commit — `Summarise the plan by communication pack`.

---

## Task 5: Lead-time statistics and data quality

Closes Q18 and Q19; supports Q17 and Q23.

**Files:** Modify `queries.py`; test in `tests/test_mcp_server.py`.

**Interfaces produced:**
- `lead_time_stats(session, *, threshold_days=7, **filter_kwargs)` →
  `{"valid", "excluded", "short_notice", "short_notice_rate", "median", "p25",
  "p75", "threshold_days"}`. Mirrors `analytics.js::leadTimeStats`, including
  excluding negative lead times and rows with no computable value.
- `data_quality(session, **filter_kwargs)` →
  `{"total", "missing_tracking_ids", "duplicate_tracking_ids",
  "invalid_date_ranges", "missing_pack_ids", "incomplete", "completeness_rate"}`.
  Mirrors `analytics.js::dataQuality`.

**Semantics that matter:**
- Reuse `lead_days` from Phase 1 — it already matches
  `ActivityRead.planning_lead_days` and deliberately computes in Python because
  `v_lead_times`' PostgreSQL `round()` disagrees with Python's on an exact half
  day. Do not reimplement.
- `duplicate_tracking_ids` counts *ids occurring more than once*, not the number
  of duplicate rows — the studio counts groups. State it in the docstring.
- `invalid_date_ranges` is `end_date < start_date`, both present.
- `missing_pack_ids` uses the same "has campaign or pack" rule as the studio's
  `hasCampaignOrPack`, which deliberately excludes `tracking_pack_id`; keep that.
- `completeness_rate` is a percentage to one decimal, as the studio reports it.

- [ ] **Step 1: Write the failing tests.**
  - `test_lead_time_quantiles_match_the_studio_math` — a fixed set of lead times
    with hand-computed median/p25/p75; assert exact values including the
    one-decimal rounding.
  - `test_lead_time_excludes_negative_and_unknown_values` — assert `excluded`
    counts them and they do not enter the quantiles.
  - `test_data_quality_counts_duplicate_ids_as_groups_not_rows` — three rows
    sharing one tracking id → `duplicate_tracking_ids == 1`.
  - `test_data_quality_flags_reversed_date_ranges`.
  - `test_data_quality_incomplete_agrees_with_planning_gaps`.
  - `test_lead_time_and_quality_pin_against_the_studio` — parse `analytics.js` for
    the quantile formula and the `hasCampaignOrPack` exclusion of
    `tracking_pack_id`.
- [ ] **Step 2:** Run; expect failures.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Full CHECK.
- [ ] **Step 5:** Commit — `Report planning lead time and data-quality figures`.

---

## Task 6: Change history

Closes Q61 and Q62 (rank 10). Carries the sharpest demo argument in the tool set:
the source system cannot show what changed when, and this can.

**Files:** Modify `queries.py`; test in `tests/test_mcp_server.py`.

**Interfaces produced:**
- `activity_history(session, identifier, *, limit=None)` → the change rows for one
  activity, newest first, each `{"changed_at", "actor", "change_type", "field",
  "old_value", "new_value", "version_from", "version_to"}`, plus the activity's
  `tracking_id` and `activity_name` for context. Resolves `identifier` by tracking
  id or UUID exactly as `get_activity` does — reuse its `_lookup`.
- `plan_changes_since(session, *, since, limit=None, **filter_kwargs)` →
  `{"since", "changes", "returned", "truncated", "note", "by_actor": {...},
  "by_change_type": {...}, "by_field": {...}, "activities": [...]}` where
  `activities` groups changes per activity so "what moved this week" reads as a
  list of activities, not a flat field log.

**Semantics that matter:**
- `activity_changes` has **no foreign key** to `activities` (deliberate — see the
  model docstring). So join in Python or with an explicit join, and handle a
  change row whose activity no longer exists by reporting it under a null
  activity rather than dropping it.
- A `created` row has `field IS NULL`; do not let it fall out of a `by_field`
  tally silently — bucket it as `"(created)"`.
- `actor` is one of `studio` / `sync` / `seed` (and the sync writes
  `cplan_sync`) — do not hardcode an enum, tally whatever is there.
- `since` accepts `YYYY-MM-DD` or a full ISO timestamp, parsed by the existing
  `_parse_boundary`.
- Free text from the source system reaches the model through `old_value` /
  `new_value` — the untrusted-input warning in the resource covers it, and Task 7
  extends that sentence to name change values explicitly.

- [ ] **Step 1: Write the failing tests.**
  - `test_activity_history_returns_changes_newest_first`.
  - `test_activity_history_resolves_by_tracking_id_and_uuid`.
  - `test_activity_history_reports_a_clean_miss_for_an_unknown_identifier`.
  - `test_plan_changes_since_groups_by_activity_and_tallies_actors`.
  - `test_plan_changes_since_buckets_created_rows_without_a_field`.
  - `test_plan_changes_survive_a_missing_activity` — a change row whose
    `activity_id` matches no activity is reported, not dropped.
  - `test_plan_changes_since_reports_truncation`.
- [ ] **Step 2:** Run; expect failures.
- [ ] **Step 3:** Implement. `ActivityChange` is already imported in `queries.py`.
- [ ] **Step 4:** Full CHECK.
- [ ] **Step 5:** Commit — `Show what changed on an activity and across the plan`.

---

## Task 7: Protocol surface and domain model

None of Tasks 1–6 is reachable by an agent until this lands.

**Files:** Modify `pipeline/mcp/server.py`, `pipeline/mcp/domain.py`; test in
`tests/test_mcp_server.py`.

- [ ] **Step 1: Write the failing tests.**
  - `test_every_new_tool_is_registered_with_a_description` — assert the five new
    tools (`calendar_load`, `window_comparison`, `detect_collisions`,
    `pack_overview`, `lead_time_stats`, `data_quality`, `activity_history`,
    `plan_changes_since`) appear in `list_tools()` with non-empty descriptions.
  - `test_cross_tab_is_exposed_on_activity_counts` — `second_dimension` in the
    schema properties.
  - `test_collision_description_explains_orchestration_versus_conflict` — assert
    both words appear in the tool description, because an agent that does not know
    the difference will report good planning as a problem.
  - `test_pack_overview_description_names_the_pack_key`.
  - Extend the existing schema-driven forwarding probe
    (`test_every_declared_parameter_can_be_forwarded_without_a_typo`) so it covers
    the new tools automatically — it derives from `list_tools()`, so confirm it
    picks them up rather than hardcoding a list.
- [ ] **Step 2:** Run; expect failures.
- [ ] **Step 3:** Register the tools. Each docstring names its own trap, following
  the Phase 1 tools: state what the tool answers, which argument to prefer, and
  the one thing an agent would otherwise get wrong. `field_values`' generated
  description shows the `@server.tool(description=...)` pattern for anything that
  needs interpolation.
- [ ] **Step 4:** Extend `domain.py`: a short section on what the new answers mean
  — that a collision needs a shared channel *and* audience, that orchestration is
  expected rather than a problem, that pack figures group by the pack id, and that
  calendar answers carry an explicit resolved `anchor` rather than "today".
  Extend the untrusted-free-text sentence to name change-log values.
- [ ] **Step 5:** Full CHECK, plus the manual stdio smoke check
  (`.venv/bin/python -m pipeline.mcp.server --settings data/cplan-settings.json`,
  expect the ready line on stderr and nothing on stdout).
- [ ] **Step 6:** Commit — `Expose the phase two analytics over the protocol`.

---

## Task 8: Docs, eval coverage, both-backend verification

**Files:** Modify `pipeline/mcp/README.md`, `evals/questions.py`, `evals/README.md`.

- [ ] **Step 1:** Update the README tool table and add design notes: the per-axis
  cross-tab cap and why a flat cap is wrong for two axes; the collision
  orchestration/conflict distinction; the pack-key chain; and that three tools are
  now pinned against `analytics.js`.
- [ ] **Step 2:** Add one eval question per newly closed catalogue entry, each with
  at least one **trace** grader — the eval's own README explains why an
  answer-only grader can pass by luck. Minimum set:
  - `collision-orchestration` (Q11) — seed a same-pack pair and a cross-pack pair;
    grade that the agent reports the cross-pack one as a conflict and does **not**
    describe the same-pack pair as a problem.
  - `pack-overview` (Q37) — grade that `pack_overview` was called, not
    `activity_counts(dimension="campaign")`.
  - `weekly-load` (Q4) — grade that `calendar_load` was called rather than
    hand-rolled date windows.
  - `changed-since` (Q62) — grade that `plan_changes_since` was called.
  **Verify each new grader fails a fabricated wrong answer**, the way the
  existing ones were checked; a grader that cannot fail is worse than none.
- [ ] **Step 3:** Add `--base-url` to `evals/run_eval.py`, passed through to
  `AsyncAnthropic(base_url=...)` and defaulting to `ANTHROPIC_BASE_URL` if set, so
  the harness can be pointed at a local model without a code change. Document it
  in `evals/README.md` under Credentials, noting that production data must not
  leave the corporate environment and a local endpoint is the way to run this
  against real data.
- [ ] **Step 4:** Full CHECK on SQLite.
- [ ] **Step 5:** Full CHECK against real PostgreSQL (command in Global
  Constraints). Report both pass counts.
- [ ] **Step 6:** Controller runs the brand/path leakage check.
- [ ] **Step 7:** Commit — `Document the phase two analytics and cover them in the eval`.

---

## Deliberately not in this plan

- **Phase 3 (packs and clusters as first-class records; audience size as an
  ordinal column).** Both need production facts that cannot be obtained here:
  whether `campaign_ltid` is the tracking-cluster key (empty in every local
  snapshot), and whether production stores audience bands or integers (integers
  locally, and the domain-model resource asserted the opposite until an eval run
  caught it). Each is a write-path schema change touching the studio, the API and
  the sync. Designing one against synthetic assumptions and then finding
  production differs is worse than waiting.

  **The way to unblock is `pipeline/mcp/probe.py`, not the queries alone.**
  Production data must not leave the corporate environment, so the facts have to
  be produced *there*. `python -m pipeline.mcp.probe --settings <path>` answers
  both questions — plus the combination question phase 2 disclosed but left
  whole-matched, and the pack-key-chain facts a `packs` table needs — against
  whatever database the settings point at, over the same read-only engine the
  server uses. Its output is shape-only by construction (counts, rates, distinct
  cardinalities, shape classifications and redacted patterns; never a value), so
  the operator can run it inside the environment and carry the report out. The
  spec records the underlying questions; `pipeline/mcp/README.md` records what
  decision each of the probe's four answers unblocks. Phase 3 starts when that
  report comes back, not before.
- **Semantic search** (Q29, Q42) — needs embeddings, and the
  free-text-is-untrusted caveat applies doubly once the model compares message
  content.
- **Performance data** (Q53–Q57) — out of scope by decision, and unreachable
  anyway while corporate data cannot leave the environment.

## Projected coverage

Phase 1 left **33 A / 11 P / 8 T / 11 D**. This plan closes Q4, Q11, Q13, Q18,
Q19, Q37, Q40, Q61, Q62 and converts most remaining partials, landing at roughly
**≈49 A / 3 P / 0 T / 11 D** — every question whose data CPLAN already holds.
