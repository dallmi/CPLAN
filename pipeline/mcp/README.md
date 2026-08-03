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
| `field_values` | Which values does `channel` / `priority` / `region` / … actually contain |
| `search_activities` | Find activities by text and filters; compact summaries |
| `get_activity` | Full record of one activity by tracking id or UUID |
| `planning_gaps` | Which activities are not fully planned, and what is missing |
| `activity_counts` | Volume by channel, month, lead team, priority, … |

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
