# CPLAN MCP server (read-only)

Exposes the planning data to AI agents over the [Model Context Protocol](https://modelcontextprotocol.io).
An agent connects, discovers the tools at runtime, and answers questions like
"which activities in Q1 are not fully planned and who owns them" without any
knowledge of the schema or the REST API.

Read-only, stdio transport, no running API server required.

## Install and run

```bash
.venv/bin/python -m pip install -r pipeline/mcp/requirements.txt
.venv/bin/python -m pipeline.mcp.server            # uses the configured backend
.venv/bin/python -m pipeline.mcp.server --settings path/to/cplan-settings.json
```

The database is resolved exactly as `pipeline/scripts/start_cplan.py` resolves
it (`load_backend_config` → `resolve_backend_database_url`), so the server always
reads whatever backend the studio is configured against — SQLite or PostgreSQL.

Register it with an MCP host (Claude Desktop, Claude Code, …) by pointing the
host at that command with `cwd` set to the repository root.

## Tools

| Tool | Answers |
|---|---|
| `database_status` | How big is the plan, what date range, when did the last sync run |
| `field_values` | Distinct stored values (with row counts) of any filterable column, or the individual members of the three multi-value columns (`strategic_objectives`, `bod_geb`, `other_executives`). The tool's own description generates the current list from `queries.ENUMERABLE_FIELDS`, so it cannot go stale — do not restate it here |
| `search_activities` | Find activities by free-text `query` plus every filterable and multi-value column above, `min_priority_rank`, `executive` (OR across both executive columns), start/end date windows, `max_lead_days`, the boolean flags `news_digest` / `has_tracking_id` / `has_executive` / `locally_modified`, and archive handling via `include_archived` / `archived_only`; returns compact summaries |
| `get_activity` | Full record of one activity by tracking id or UUID |
| `planning_gaps` | Which activities are not fully planned and what is missing, narrowable by `source_type`, `lead_team`, `lead`, `channel`, `region`, `business_division`, `communication_pack_cpid`, `campaign`, `executive`, `min_priority_rank`, `start_after`/`start_before` and `include_archived`, and groupable with `group_by` (any enumerable column) to show which team/channel is behind |
| `activity_counts` | Volume grouped by `dimension` — any filterable or multi-value column, plus `priority_rank` and `month` — filterable by `source_type`, `channel`, `lead_team`, `region`, `business_division`, `communication_pack_cpid`, `campaign`, `executive`, `min_priority_rank`, `start_after`/`start_before` and `include_archived` (a subset of `planning_gaps`'s filters: no `lead`). `second_dimension` turns it into a cross-tab |
| `calendar_load` | Activity volume over `weeks` consecutive 7-day windows, anchored on `start_date` if given, else the latest sync run, else the latest scheduled activity in the filtered set — never today's wall clock. Reports `anchor`/`anchor_source`, `busiest`/`quietest` and an `empty_weeks` list; accepts every `search_activities` filter |
| `window_comparison` | The current `days`-length window against the immediately preceding one of equal length, anchored the same way as `calendar_load`; `change_pct` comes back `null` (never `inf` or `0`) when there is no prior window to compare against |
| `detect_collisions` | Activity pairs sharing both a `channel` member and a `target_audience` member within `proximity_days`; pairs in the same communication pack are labelled `orchestration` (`severity: "info"`), pairs spanning different packs are labelled `conflict` (severity from the pair's priority ranks), each carrying `shared_channels`/`shared_audiences` |
| `pack_overview` | Per-communication-pack rollup — size, channel/objective/audience breadth, date span, readiness — keyed by `communication_pack_cpid`, falling back to `tracking_pack_id`, `communication_pack`, then `campaign`; `key_source` on each row names which link resolved it |
| `lead_time_stats` | Planning lead-time distribution (median/p25/p75 days) over activities with a valid, non-negative lead time, plus `short_notice_rate` against `threshold_days`; `excluded` counts everything left out and why |
| `data_quality` | Portfolio-wide health tally: duplicate and missing tracking ids, reversed date ranges, missing pack linkage, `completeness_rate` — `incomplete` reuses `planning_gaps`'s own rule so the two figures cannot disagree |
| `activity_history` | The change log for one activity, newest first, resolved by tracking id or UUID like `get_activity` |
| `plan_changes_since` | Change rows since `since`, grouped per activity, with `by_actor`/`by_change_type`/`by_field` tallies; changes whose activity no longer resolves are still reported (unless an activity filter is active) rather than silently dropped. A blank `since` is an error, not "everything"; groups, each group's own `changes` list and all three tallies are capped independently |

## Resources

| Resource | Carries |
|---|---|
| `cplan://domain-model` | The hierarchy, both priority vocabularies, the archive semantics, the free-text-column trap, the multi-value columns, the unverified audience band, the completeness rule, the result caps, and the planning-only scope boundary |

An agent that skips this resource will answer priority and archive questions
confidently wrong. The server instructions tell it to read the resource first.

## Design notes

**Read-only is enforced by the connection, not by convention.**
`pipeline/mcp/engine.py` installs a statement guard that raises
`ReadOnlyViolation` on every statement whose leading keyword is not one that
reads, and additionally sets `default_transaction_read_only` on PostgreSQL. A tool
that tried to write would fail loudly rather than mutate the plan. `with` and
`pragma` are allowed prefixes but not sufficient ones — a `WITH … DELETE` or
`PRAGMA writable_schema = ON` is refused, a plain `WITH … SELECT` is not — because
on SQLite the guard is the only layer there is. No tool accepts SQL today, so the
guard is defence in depth rather than the primary control.

**Every tool caps its own answer.** `GET /api/activities` deliberately returns
the full result set unpaginated — correct for the studio, fatal for an agent
(the current dataset is ≈450 KB of JSON, well over 100k tokens). The MCP tools
return at most 50 rows by default, 200 as a hard cap, and report their own
truncation so the model narrows its filters instead of asking for more. That
covers the aggregates too: `activity_counts` caps its buckets and `planning_gaps`
its groups at 200 (largest first, `bucket_count` / `group_count` and a truncation
flag alongside), and `field_values` reports `distinct_values` so a truncated value
list can never be mistaken for the column's whole vocabulary — a model that
filters on a value it never saw and then reports "no activities" as fact is the
failure this prevents.

**The cap invariant lives in one function, not in every tool.**
`queries._capped_list` returns the four keys — the total, `returned`,
`truncated`, `note` — that every capped answer here reports, and each tool
spreads it into its response. Only the total's key varies (`total_matches`,
`incomplete`, `pack_count`, `bucket_count`, …), which is precisely why the
invariant used to be hand-rolled seven times: seven near-identical blocks that
looked different enough to read as intentional. One of them then quietly broke
it — `plan_changes_since` capped activity groups but inlined every change row
inside each group, so a nightly-synced activity produced `returned: 1` with
hundreds of changes underneath and no truncation flag anywhere.
`test_every_capped_answer_reports_the_same_truncation_invariant` now checks all
of them against the one rule.

**A cross-tab caps each axis independently, not the flat cell count.**
`activity_counts(second_dimension=...)` multiplies two dimensions together --
32 packs x 15 channels is 480 cells -- and the flat 200-row cap the other
tools use is the wrong shape for that: sorting the flat cell list by count and
slicing off the tail drops whole rows or columns of the table rather than
shrinking it, which reads to an agent as a full cross-tab that is quietly
missing data. Each axis is instead capped independently to its own top 20
values by total count (`MAX_CROSS_AXIS`), so the result stays a smaller but
COMPLETE cross-tab rather than an arbitrary, incomplete slice of a bigger one.
`axis_truncated` (keyed `dimension` / `second_dimension`) and
`distinct_values` say which axis, if any, was cut -- check them before reading
the table as exhaustive. There is deliberately no `bucket_count` on a cross-tab:
the flat cell count is not the number the caps are about, and the domain-model
resource says so rather than letting an agent look for a key that is not there.
A `TIME_BUCKETS` axis is ordered chronologically on either side of the table,
matching the single-dimension path -- a timeline sorted by volume is not a
timeline. The cap itself stays by count on both axes, so the buckets that
survive are still the busiest ones.

**`detect_collisions` distinguishes orchestration from conflict by pack, not
by severity.** Two activities sharing both a `channel` member and a
`target_audience` member within `proximity_days` are a candidate pair. If they
also carry the same non-blank `tracking_pack_id`, that is what a communication
pack IS -- the planner put them there on purpose -- and the pair is labelled
`orchestration` with `severity: "info"` regardless of priority. Only a pair
spanning two different packs is a genuine `conflict`, and its severity is the
higher of the pair's two priority ranks (critical/high/medium). Reporting an
orchestration pair as a problem is the fastest way to make this tool stop
being trusted, which is why the distinction is load-bearing rather than
cosmetic; each pair also carries `shared_channels` / `shared_audiences` so an
agent can say *why* it collided, not only that it did.

**Not built on the `v_*` analysis views.** Those are PostgreSQL-only by design
and a documented no-op on SQLite (`pipeline/api/views.py`), so building on them
would leave the server dead on every SQLite deployment. `queries.py` mirrors
their semantics in backend-neutral SQLAlchemy instead. The completeness rule in
particular now exists in three places — `pipeline/studio/analytics.js`,
`v_planning_completeness`, and `queries.REQUIRED_*` — so
`tests/test_mcp_server.py` pins the MCP copy against the view two ways: by flag
name always, and by *verdict* whenever a real PostgreSQL is available (every
activity must get the same is_complete from both). Adding or dropping a required
field on one side without the other fails the suite.

**Every query test runs on both backends.** "Backend-neutral" is the premise of
not building on the views, so the test fixture is parametrized exactly like
`tests/test_api.py`'s: SQLite always, PostgreSQL when `CPLAN_TEST_DATABASE_URL`
is set.

**Free-text columns are the main usability trap.** `channel`, `priority`,
`region` and friends are `Text`, not enumerations, so a model that guesses
"Newsletter" silently matches nothing. `field_values` exists to close that gap,
and the filters compare case-insensitively.

**Filter, group and enumerate are kept in step by a test.**
`test_every_filterable_column_is_also_discoverable` fails if a column becomes
filterable without also being enumerable — an agent must never be able to filter
on a value it has no way to discover.

**Three predicates are evaluated in Python, not SQL.** `priority_rank` needs the
two-vocabulary rule; `max_lead_days` has to match the API's rounding
(`v_lead_times` uses PostgreSQL `round()`, which rounds an exact half day away
from zero while Python rounds to even); and exact multi-value membership
(`contains`) needs the same tokenising `split_multi` does everywhere else — SQL
can narrow with a substring `LIKE`, but not decide membership, because "Objective
A" also matches "Objective AB" as a substring. SQL narrows the candidate set
first; `needs_post_filter` keeps the cheap `SELECT COUNT` path for every query
that uses none of the three.

The `executive` filter is the same two-stage idiom, OR'd across the two executive
columns because a single-column `contains` entry cannot express that. Both stages
read `EXECUTIVE_COLUMNS`, so the SQL prefilter and the Python membership check can
never span different columns — the way rows would be silently dropped. Because it
lives in `ActivityFilters` rather than in one tool, `planning_gaps` and
`activity_counts` accept it too.

**One labelling rule for every grouping path.** `_bucket_keys` (`split_multi` or
`"Unassigned"`) labels both `planning_gaps(group_by=…)` and `activity_counts`'
Python branch, and the SQL branch's label is trimmed to match — otherwise `" Email
"` is a bucket of its own in one tool and folds into `"Email"` in the other. SQL
`trim()` removes spaces only, so a tab-padded value can still differ from the
Python label; documented rather than solved, because there is no portable
whitespace trim.

**The pack key is `communication_pack_cpid`, not `campaign`.** Both columns
answer "which campaign is this part of", at different granularities, and grouping
by the coarser one makes pack size, channel breadth and readiness describe the
portfolio instead of a planning unit. This is the lesson
`analytics.js::campaignScorecards` already records in a comment. Both columns stay
filterable and groupable; the `cplan://domain-model` resource carries the measured
figures and tells the agent which one is the planning unit — they are stated there
once rather than repeated here.

`pack_overview` walks the full chain rather than the single column:
`communication_pack_cpid`, then `tracking_pack_id` (the `CLUSTER-PACKNUM`
prefix `ActivityRead` derives from `tracking_id`), then `communication_pack`,
then `campaign`, taking the first non-blank link. It reports which one
resolved each row as `key_source`, so a genuine pack id can be told apart from
a campaign-label fallback. The order matters more than any other choice in
that tool: on the local snapshot, grouping by `tracking_pack_id` alone
collapses everything into two buckets of 273 and 125 activities, and grouping
by `campaign` alone collapses it into 4 buckets of about 60 -- only
`communication_pack_cpid` resolves the 32 real packs of 2-11 activities a
planner actually owns. The chain order is pinned against
`analytics.js::campaignScorecards`'s own preference order (see below), so it
cannot drift on either side of the port without failing the suite.

**Multi-value columns split on the separator the ETL actually wrote.** Lookup
values join with `", "`, person values with `"; "`. Person columns are split on
`;` only — deliberately unlike `analytics.js::normalizeMulti`, which splits both
on `/[;,]/`: a person name may contain a comma, and splitting it would invent a
person. Splitting a lookup value on `","` remains lossy for a value whose own
name contains a comma.

**`_normalize_multi` is a deliberate second fork of `split_multi`, not a
duplicate of it.** `detect_collisions` needs `channel` and `target_audience`
treated as multi-valued for exactly one purpose -- deciding whether two
activities share a member -- even though neither column is in
`MULTI_VALUE_SEPARATORS` and `split_multi` treats both as scalars everywhere
else in this server. `_normalize_multi` mirrors `analytics.js::normalizeMulti`
instead: it splits on `,` OR `;` unconditionally, sharing `_split_on`'s
trim-and-drop-blanks algorithm with `split_multi` but forking the separator
choice. Each function carries a comment pointing at the other so neither can
be "fixed" into matching the other by someone who has only read one of them:
`split_multi` explains why `channel` / `target_audience` land on its scalar
branch and says to check `_normalize_multi` first before changing that;
`_normalize_multi` names the two columns and the one tool it exists for, and
says why it is not simply a call to `split_multi`.

**Five tools are pinned against `pipeline/studio/analytics.js`, not
re-derived independently.** `pack_overview`'s key chain against
`campaignScorecards`, `calendar_load`'s week math against `weeklyCoverage`,
`detect_collisions`'s channel/audience guard and same-pack severity branch
against `detectCollisions`, and `lead_time_stats` / `data_quality` against
`quantile` and `hasCampaignOrPack` respectively. Each pin test reads the
studio's own source text with a regex rather than hand-copying the formula
into the test, so a change on either side of the port -- the studio or the
MCP query -- fails the suite instead of quietly diverging.

## Known limits

- No write tools. Creating activities has to go through the REST API, whose
  tracking-ID generation carries retry and concurrency logic that must not be
  bypassed.
- No authentication. The stdio server runs as the local user with whatever
  database credentials the settings file resolves to — it does not carry the
  studio's per-user `SET ROLE` identity, so PostgreSQL row-level security is
  applied to the connecting role, not to an end user. A multi-user deployment
  would need the streamable-HTTP transport plus OAuth before this is safe.
- Free text from the source system (activity names, descriptions) reaches the
  model verbatim; treat it as untrusted input.
- Cluster-level questions cannot be answered exactly. Tracking clusters and
  communication packs are not first-class records; their identity lives in the
  tracking-id string and in free-text columns.
- No performance data. Reach and engagement questions are out of scope by design;
  the domain-model resource tells the agent to decline them rather than
  approximate them from planning fields.
