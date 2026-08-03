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
| `field_values` | Distinct stored values (with row counts) of any of the 13 free-text filter columns (`source_type`, `channel`, `priority`, `lead`, `lead_team`, `partner_team`, `campaign`, `region`, `business_division`, `business_area`, `target_audience`, `audience`, `time_zone`), or the individual members of the 3 multi-value columns (`strategic_objectives`, `bod_geb`, `other_executives`) |
| `search_activities` | Find activities by free-text `query` plus every filterable and multi-value column above, `min_priority_rank`, `executive` (OR across both executive columns), start/end date windows, `max_lead_days`, the boolean flags `news_digest` / `has_tracking_id` / `has_executive` / `locally_modified`, and archive handling via `include_archived` / `archived_only`; returns compact summaries |
| `get_activity` | Full record of one activity by tracking id or UUID |
| `planning_gaps` | Which activities are not fully planned and what is missing, narrowable by `source_type`, `lead_team`, `lead`, `channel`, `region`, `business_division`, `campaign`, `executive`, `min_priority_rank`, `start_after`/`start_before` and `include_archived`, and groupable with `group_by` (any enumerable column) to show which team/channel is behind |
| `activity_counts` | Volume grouped by `dimension` — any filterable or multi-value column, plus `priority_rank` and `month` — filterable by `source_type`, `channel`, `lead_team`, `region`, `business_division`, `campaign`, `executive`, `min_priority_rank`, `start_after`/`start_before` and `include_archived` (a subset of `planning_gaps`'s filters: no `lead`) |

## Resources

| Resource | Carries |
|---|---|
| `cplan://domain-model` | The hierarchy, both priority vocabularies, the archive semantics, the free-text-column trap, the multi-value columns, the unverified audience band, the completeness rule, the result caps, and the planning-only scope boundary |

An agent that skips this resource will answer priority and archive questions
confidently wrong. The server instructions tell it to read the resource first.

## Design notes

**Read-only is enforced by the connection, not by convention.**
`pipeline/mcp/engine.py` installs a statement guard that raises
`ReadOnlyViolation` on anything that is not a read, and additionally sets
`default_transaction_read_only` on PostgreSQL. A tool that tried to write would
fail loudly rather than mutate the plan.

**Every tool caps its own answer.** `GET /api/activities` deliberately returns
the full result set unpaginated — correct for the studio, fatal for an agent
(the current dataset is ≈450 KB of JSON, well over 100k tokens). The MCP tools
return at most 50 rows by default, 200 as a hard cap, and report their own
truncation so the model narrows its filters instead of asking for more.

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

**Multi-value columns split on the separator the ETL actually wrote.** Lookup
values join with `", "`, person values with `"; "`. Person columns are split on
`;` only — deliberately unlike `analytics.js::normalizeMulti`, which splits both
on `/[;,]/`: a person name may contain a comma, and splitting it would invent a
person. Splitting a lookup value on `","` remains lossy for a value whose own
name contains a comma.

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
