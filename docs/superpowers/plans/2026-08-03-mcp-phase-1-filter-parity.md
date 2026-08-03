# MCP Phase 1 — Filter Parity, Catalogue Metadata, Priority Rank

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the data CPLAN already holds askable by an MCP agent, so 18 of the
27 questions currently blocked by a missing tool become answerable, and the agent
stops answering priority and archive questions confidently wrong.

**Architecture:** No new tools. The six existing tools gain the filters, the
groupable dimensions and the derived predicates they are missing, driven by one
internal `ActivityFilters` dataclass so the four query functions stop repeating a
twelve-line kwargs block each. Two predicates (priority rank, lead time) cannot be
expressed portably in SQL, so they are applied in Python over a SQL-narrowed
candidate set — the pattern `planning_gaps` already uses. A `cplan://domain-model`
MCP resource carries the domain traps that currently exist only in the knowledge
base.

**Tech Stack:** Python 3.13, SQLAlchemy 2.x (`select()`, `Mapped`), `mcp` SDK 2.0
(`mcp.server.MCPServer`), pytest with a per-backend parametrized fixture.

**Source spec:** [`2026-08-03-persona-question-catalogue-design.md`](../specs/2026-08-03-persona-question-catalogue-design.md).
Question IDs (Q1–Q63) below refer to that catalogue.

## Global Constraints

- **Read-only, enforced by the connection.** No new tool may write. Never open a
  writable session in `pipeline/mcp/`; `engine.py` raises `ReadOnlyViolation` and
  that is the intended behaviour, not an obstacle to work around.
- **Backend-neutral.** Every query test is parametrized over both backends via the
  existing `engine` fixture: SQLite always, PostgreSQL when
  `CPLAN_TEST_DATABASE_URL` is set. No feature may work on only one backend.
- **Never build on the `v_*` views.** They are PostgreSQL-only and a documented
  no-op on SQLite (`pipeline/api/views.py`). Mirror their semantics in SQLAlchemy
  instead, and pin the mirror with a test.
- **`pipeline/mcp/queries.py` must stay free of any `mcp` import.** It is testable
  without the SDK installed and must remain so.
- **Result caps stay.** `DEFAULT_LIMIT = 50`, `MAX_LIMIT = 200`. Every list-shaped
  answer reports its own truncation. No new code path may return the whole table.
- **No brand names, no personal names, no production identifiers** in code,
  identifiers, comments, tests, fixtures, docs, or commit messages. Use
  `organisation`, `internal`, `external`, `Division One`, `a.person`. All fixture
  data synthetic.
- **CHECK command** (both halves, always together — pytest alone silently skips 54
  node tests):
  ```bash
  .venv/bin/python -m pytest tests/ -q && node --test tests/*.test.js
  ```
- **PostgreSQL run** (do this at least once, at Task 11):
  ```bash
  docker run --rm -d --name cplan-pg -e POSTGRES_PASSWORD=looptest \
    -e POSTGRES_USER=cplan -e POSTGRES_DB=cplan \
    -p 127.0.0.1:55433:5432 postgres:17-alpine
  CPLAN_TEST_DATABASE_URL=postgresql+psycopg://cplan:looptest@127.0.0.1:55433/cplan \
    .venv/bin/python -m pytest tests/ -q
  ```
  (Note: `pgserver` has no wheel for Python 3.13 on macOS-arm64, hence the
  container. The `pgserver`-specific tests stay skipped.)
- **Commit after every task.** Message style: imperative, no brand names.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `pipeline/mcp/queries.py` | All answer-shaped read logic; backend-neutral | Modify — the bulk of this plan |
| `pipeline/mcp/domain.py` | The domain-model text served as an MCP resource | **Create** |
| `pipeline/mcp/server.py` | Protocol surface: tool signatures, descriptions, resource registration | Modify |
| `pipeline/mcp/README.md` | Tool table and design notes | Modify |
| `tests/test_mcp_server.py` | Query, engine and protocol tests | Modify |
| `docs/CPLAN_KNOWLEDGE_BASE.md` | Records the multi-value separator finding | Modify |

`domain.py` is a separate module rather than a string in `server.py` for the same
reason `queries.py` is separate: it must be assertable by a test that does not
import the `mcp` SDK.

---

## Task 1: Multi-value splitting

Three columns hold several values in one string. Grouping the raw strings yields
*combinations*, not pillars or people, so every later task that touches them needs
this first.

The separators are settled (from `pipeline/scripts/process_cplan.py`): lookup and
taxonomy values join with `", "` (`parse_sp_lookup` default), person values join
with `"; "` (`PERSON_JOIN`, applied to `SP_MULTI_PERSON_COLUMNS = {bod_geb,
other_executives}`).

**Deliberate divergence from `analytics.js::normalizeMulti`**, which splits both on
`/[;,]/`: a person name may legitimately contain a comma, so splitting the person
columns on a comma would break names. Person columns split on `;` only. This
divergence is intentional and gets a test that says so, because undocumented drift
between the two is exactly the hazard this codebase has been bitten by before.

**Files:**
- Modify: `pipeline/mcp/queries.py`
- Test: `tests/test_mcp_server.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `MULTI_VALUE_SEPARATORS: dict[str, tuple[str, ...]]` — column name → the
    separator characters to split on.
  - `split_multi(value: Any, field: str) -> list[str]` — trimmed, non-empty
    members; `[]` for blank input; the whole value as a single member for a column
    that is not multi-value.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_mcp_server.py`, in the query-layer section (after
`test_dates_are_missing_only_when_null`):

```python
def test_split_multi_uses_comma_for_lookup_columns():
    assert queries.split_multi("Objective A, Objective B", "strategic_objectives") == [
        "Objective A",
        "Objective B",
    ]


def test_split_multi_also_accepts_a_semicolon_in_lookup_columns():
    # The sync writes ", ", but a studio-entered value may use "; ".
    assert queries.split_multi("Objective A; Objective B", "strategic_objectives") == [
        "Objective A",
        "Objective B",
    ]


def test_split_multi_uses_only_semicolon_for_person_columns():
    # Deliberately unlike analytics.js normalizeMulti, which splits on [;,]:
    # a person name may contain a comma, and splitting it would invent people.
    assert queries.split_multi("Doe, Jane; Roe, Sam", "other_executives") == [
        "Doe, Jane",
        "Roe, Sam",
    ]


@pytest.mark.parametrize("value", [None, "", "   ", "None", "null"])
def test_split_multi_treats_blank_sentinels_as_no_members(value):
    assert queries.split_multi(value, "strategic_objectives") == []


def test_split_multi_drops_empty_members_and_trims():
    assert queries.split_multi(" A ,, B ", "strategic_objectives") == ["A", "B"]


def test_split_multi_returns_a_single_member_for_a_scalar_column():
    assert queries.split_multi("Email", "channel") == ["Email"]


def test_person_columns_match_the_etl_person_column_set():
    """The separator choice must follow the ETL, not a guess."""
    etl = (REPO_ROOT / "pipeline" / "scripts" / "process_cplan.py").read_text()
    declared = re.search(r"SP_MULTI_PERSON_COLUMNS = \{([^}]*)\}", etl).group(1)
    person_columns = set(re.findall(r'"(\w+)"', declared))
    semicolon_only = {
        field
        for field, seps in queries.MULTI_VALUE_SEPARATORS.items()
        if seps == (";",)
    }
    assert person_columns == semicolon_only
```

- [ ] **Step 2: Run them to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_mcp_server.py -k split_multi -v
```

Expected: FAIL — `AttributeError: module 'pipeline.mcp.queries' has no attribute 'split_multi'`.

- [ ] **Step 3: Implement**

In `pipeline/mcp/queries.py`, add `import re` to the imports, then add after
`DATE_FIELDS`:

```python
# Three columns hold several values in one string. The separators follow the ETL
# (`pipeline/scripts/process_cplan.py`): SharePoint lookup and taxonomy values are
# joined with ", " by `parse_sp_lookup`, person values with "; " by `PERSON_JOIN`
# for the columns in `SP_MULTI_PERSON_COLUMNS`.
#
# Person columns split on ";" ONLY -- deliberately unlike
# analytics.js::normalizeMulti, which splits both on /[;,]/. A person name may
# legitimately contain a comma ("Doe, Jane"), and splitting it would invent a
# person who does not exist. Lookup columns accept either, because the sync writes
# ", " while a studio-entered value may use "; ".
#
# Hazard, documented rather than solved: splitting a lookup value on "," is lossy
# -- a single objective whose own name contains a comma is indistinguishable from
# two objectives. Validate any published pillar tally against real values.
MULTI_VALUE_SEPARATORS: dict[str, tuple[str, ...]] = {
    "strategic_objectives": (",", ";"),
    "bod_geb": (";",),
    "other_executives": (";",),
}


def split_multi(value: Any, field: str) -> list[str]:
    """The individual members of a possibly multi-valued column.

    Returns [] for a blank value (same rule as `is_blank`), and a single-member
    list for a column that is not multi-valued -- so callers can treat every
    column uniformly.
    """
    if is_blank(value):
        return []
    text = str(value)
    separators = MULTI_VALUE_SEPARATORS.get(field)
    if not separators:
        return [text.strip()]
    pattern = "[" + re.escape("".join(separators)) + "]"
    return [member.strip() for member in re.split(pattern, text) if member.strip()]
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.venv/bin/python -m pytest tests/test_mcp_server.py -k "split_multi or person_columns" -v
```

Expected: PASS (14 tests — 7 test functions × 2 backends where parametrized, plus
the 5 blank-sentinel cases).

- [ ] **Step 5: Commit**

```bash
git add pipeline/mcp/queries.py tests/test_mcp_server.py
git commit -m "Split the multi-value planning columns on their real separators"
```

---

## Task 2: One filter object instead of twelve repeated kwargs

`_apply_filters` currently takes nine keyword arguments and every caller repeats a
`dict(text_query=None, channel=None, ...)` block. Phase 1 adds twelve more
predicates; without this refactor each of the four query functions grows an
unreadable signature and the boilerplate is copied four times.

This task is behaviour-preserving. The existing tests are the specification: they
must pass unchanged at the end of it.

**Files:**
- Modify: `pipeline/mcp/queries.py`
- Test: `tests/test_mcp_server.py` (existing tests must stay green; one new test)

**Interfaces:**
- Consumes: `split_multi` (Task 1) — not yet used here, wired in Task 5.
- Produces:
  - `ActivityFilters` frozen dataclass with fields `text_query: str | None`,
    `text: dict[str, str]`, `start_after/start_before/end_after/end_before:
    str | None`, `include_archived: bool`.
  - `_apply_filters(statement, filters: ActivityFilters)` — single positional
    statement plus one filters object.

- [ ] **Step 1: Write the failing test**

```python
def test_activity_filters_defaults_to_no_narrowing(session):
    """An empty filter object must behave exactly like the old all-None call."""
    session.add_all([_activity(), _activity(is_archive=True)])
    session.flush()
    unfiltered = queries.search_activities(session)
    assert unfiltered["total_matches"] == 1  # archived still excluded by default
    assert queries.ActivityFilters().include_archived is False
    assert queries.ActivityFilters().text == {}
```

- [ ] **Step 2: Run it to verify it fails**

```bash
.venv/bin/python -m pytest tests/test_mcp_server.py -k activity_filters_defaults -v
```

Expected: FAIL — `AttributeError: module 'pipeline.mcp.queries' has no attribute 'ActivityFilters'`.

- [ ] **Step 3: Implement**

Add to the imports in `pipeline/mcp/queries.py`:

```python
from dataclasses import dataclass, field as dataclass_field
```

Add after `MULTI_VALUE_SEPARATORS` / `split_multi`:

```python
# Every case-insensitive equality filter an agent may apply. Free text in the
# schema, so `field_values` remains the way to learn the real values first.
FILTERABLE_TEXT_FIELDS: tuple[str, ...] = (
    "source_type",
    "channel",
    "priority",
    "lead",
    "lead_team",
    "partner_team",
    "campaign",
    "region",
    "business_division",
    "business_area",
    "target_audience",
    "audience",
    "time_zone",
)


@dataclass(frozen=True)
class ActivityFilters:
    """Everything that narrows an activity query, in one object.

    `text` maps a column in FILTERABLE_TEXT_FIELDS to a value compared
    case-insensitively for equality. Keeping it as a mapping rather than one
    attribute per column is what stops the four query functions from each
    carrying a twenty-line signature; the MCP tool layer still exposes explicit
    named parameters, because those are what the model discovers.
    """

    text_query: str | None = None
    text: dict[str, str] = dataclass_field(default_factory=dict)
    start_after: str | None = None
    start_before: str | None = None
    end_after: str | None = None
    end_before: str | None = None
    include_archived: bool = False
```

Replace the whole `_apply_filters` function with:

```python
def _apply_filters(statement, filters: ActivityFilters):
    if filters.text_query:
        needle = f"%{filters.text_query.strip().lower()}%"
        statement = statement.where(
            or_(
                func.lower(Activity.activity_name).like(needle),
                func.lower(func.coalesce(Activity.tracking_id, "")).like(needle),
                func.lower(func.coalesce(Activity.activity_description, "")).like(needle),
            )
        )
    # Case-insensitive equality throughout: the columns are free text, so an
    # agent that guesses "Email" for a stored "email" should still get its rows.
    for column_name, value in filters.text.items():
        if not value:
            continue
        column = getattr(Activity, column_name)
        statement = statement.where(func.lower(column) == value.strip().lower())
    for column, raw, lower_bound in (
        (Activity.start_date, filters.start_after, True),
        (Activity.start_date, filters.start_before, False),
        (Activity.end_date, filters.end_after, True),
        (Activity.end_date, filters.end_before, False),
    ):
        boundary = _parse_boundary(raw)
        if boundary is None:
            continue
        statement = statement.where(column >= boundary if lower_bound else column <= boundary)
    if not filters.include_archived:
        statement = statement.where(Activity.is_archive.is_(False))
    return statement
```

Now update the three callers. In `search_activities`, replace the `filters = dict(...)`
block and the two `_apply_filters(..., **filters)` calls with:

```python
    filters = ActivityFilters(
        text_query=query,
        text={
            "channel": channel,
            "source_type": source_type,
            "priority": priority,
            "lead": lead,
            "campaign": campaign,
        },
        start_after=start_after,
        start_before=start_before,
        include_archived=include_archived,
    )
    total = session.scalar(_apply_filters(select(func.count()).select_from(Activity), filters))
    rows = session.scalars(
        _apply_filters(select(Activity), filters)
        .order_by(Activity.start_date, Activity.id)
        .limit(capped)
    ).all()
```

In `planning_gaps`, replace its `filters = dict(...)` block and the `_apply_filters`
call with:

```python
    filters = ActivityFilters(
        text={"source_type": source_type},
        start_after=start_after,
        start_before=start_before,
        include_archived=include_archived,
    )
    candidates = session.scalars(
        _apply_filters(select(Activity), filters).order_by(Activity.start_date, Activity.id)
    ).all()
```

In `activity_counts`, replace its `filters = dict(...)` block with the same
`ActivityFilters(...)` construction and change both `_apply_filters(..., **filters)`
calls to `_apply_filters(..., filters)`.

Note: a `None` value in the `text` mapping is skipped by the `if not value`
guard, so passing `{"source_type": None}` behaves exactly as before.

- [ ] **Step 4: Run the whole MCP suite — every existing test must still pass**

```bash
.venv/bin/python -m pytest tests/test_mcp_server.py -q
```

Expected: PASS, with no test removed or edited. If an existing test needed
changing, the refactor changed behaviour — revert and redo.

- [ ] **Step 5: Commit**

```bash
git add pipeline/mcp/queries.py tests/test_mcp_server.py
git commit -m "Collect the activity query filters into one object"
```

---

## Task 3: Free-text filter parity

The asymmetry that blocks the most questions: `activity_counts` can group by
`region`, `business_division` and `lead_team`, but `search_activities` cannot
filter by any of them. Closes Q8, Q9, Q34.

**Files:**
- Modify: `pipeline/mcp/queries.py`
- Test: `tests/test_mcp_server.py`

**Interfaces:**
- Consumes: `ActivityFilters`, `FILTERABLE_TEXT_FIELDS` (Task 2).
- Produces: `search_activities(...)` additionally accepts `lead_team`,
  `partner_team`, `region`, `business_division`, `business_area`,
  `target_audience`, `audience`, `time_zone` — all `str | None = None`, all
  case-insensitive equality.

- [ ] **Step 1: Write the failing tests**

```python
def test_search_filters_by_lead_team(session):
    session.add_all([
        _activity(activity_name="Team one item", lead_team="Team One"),
        _activity(activity_name="Team two item", lead_team="Team Two"),
    ])
    session.flush()
    found = queries.search_activities(session, lead_team="team one")
    assert found["total_matches"] == 1
    assert found["activities"][0]["activity_name"] == "Team one item"


def test_search_filters_by_region_and_division_together(session):
    session.add_all([
        _activity(activity_name="Match", region="Global", business_division="Division One"),
        _activity(activity_name="Wrong division", region="Global", business_division="Division Two"),
        _activity(activity_name="Wrong region", region="Local", business_division="Division One"),
    ])
    session.flush()
    found = queries.search_activities(session, region="global", business_division="Division One")
    assert found["total_matches"] == 1
    assert found["activities"][0]["activity_name"] == "Match"


@pytest.mark.parametrize(
    "field,value",
    [
        ("partner_team", "Partner Team One"),
        ("business_area", "Area One"),
        ("target_audience", "Line managers only"),
        ("audience", "10-50k"),
        ("time_zone", "UTC"),
    ],
)
def test_search_filters_by_every_new_text_field(session, field, value):
    session.add_all([_activity(**{field: value}), _activity(**{field: "Something else"})])
    session.flush()
    found = queries.search_activities(session, **{field: value})
    assert found["total_matches"] == 1


def test_every_filterable_text_field_is_a_real_column():
    for name in queries.FILTERABLE_TEXT_FIELDS:
        assert hasattr(Activity, name), name
```

- [ ] **Step 2: Run them to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_mcp_server.py -k "filters_by_lead_team or region_and_division or every_new_text_field" -v
```

Expected: FAIL — `TypeError: search_activities() got an unexpected keyword argument 'lead_team'`.

- [ ] **Step 3: Implement**

In `queries.search_activities`, add the eight parameters to the signature (after
`campaign`, before `start_after`):

```python
    lead_team: str | None = None,
    partner_team: str | None = None,
    region: str | None = None,
    business_division: str | None = None,
    business_area: str | None = None,
    target_audience: str | None = None,
    audience: str | None = None,
    time_zone: str | None = None,
```

and extend the `text` mapping in its `ActivityFilters(...)` construction:

```python
        text={
            "channel": channel,
            "source_type": source_type,
            "priority": priority,
            "lead": lead,
            "lead_team": lead_team,
            "partner_team": partner_team,
            "campaign": campaign,
            "region": region,
            "business_division": business_division,
            "business_area": business_area,
            "target_audience": target_audience,
            "audience": audience,
            "time_zone": time_zone,
        },
```

- [ ] **Step 4: Run the tests**

```bash
.venv/bin/python -m pytest tests/test_mcp_server.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/mcp/queries.py tests/test_mcp_server.py
git commit -m "Let activity search filter on every descriptive column"
```

---

## Task 4: End-date windows and boolean predicates

Date filters currently apply to `start_date` only, so "what ends within a
fortnight" is unaskable. Adds the end-date window plus three boolean predicates.
Closes Q16, Q26, Q30, Q52, and the archived half of Q63.

`is_locally_modified` is `version > synced_version` with `synced_version NOT NULL`
— per `pipeline/api/app.py`, `NULL` means "never synced" (a studio-created row or a
row imported before the column existed), which is not the same as diverging.

**Files:**
- Modify: `pipeline/mcp/queries.py`
- Test: `tests/test_mcp_server.py`

**Interfaces:**
- Consumes: `ActivityFilters` (Task 2), whose `end_after`/`end_before` fields are
  already applied by `_apply_filters`.
- Produces: `ActivityFilters` additionally carries `news_digest: bool | None`,
  `has_tracking_id: bool | None`, `locally_modified: bool | None`,
  `archived_only: bool`. `search_activities` accepts `end_after`, `end_before`,
  `news_digest`, `has_tracking_id`, `locally_modified`, `archived_only`.

- [ ] **Step 1: Write the failing tests**

```python
def test_search_filters_by_end_date_window(session):
    session.add_all([
        _activity(activity_name="Ends soon", end_date=REFERENCE + timedelta(days=3)),
        _activity(activity_name="Ends late", end_date=REFERENCE + timedelta(days=90)),
    ])
    session.flush()
    found = queries.search_activities(
        session,
        end_after=REFERENCE.date().isoformat(),
        end_before=(REFERENCE + timedelta(days=14)).date().isoformat(),
    )
    assert [row["activity_name"] for row in found["activities"]] == ["Ends soon"]


def test_search_finds_activities_without_a_tracking_id(session):
    session.add_all([
        _activity(activity_name="Untracked", tracking_id=None),
        _activity(activity_name="Blank tracked", tracking_id="   "),
        _activity(activity_name="Tracked"),
    ])
    session.flush()
    missing = queries.search_activities(session, has_tracking_id=False)
    assert sorted(row["activity_name"] for row in missing["activities"]) == [
        "Blank tracked",
        "Untracked",
    ]
    present = queries.search_activities(session, has_tracking_id=True)
    assert [row["activity_name"] for row in present["activities"]] == ["Tracked"]


def test_search_finds_locally_modified_rows_but_not_never_synced_ones(session):
    session.add_all([
        _activity(activity_name="Diverged", version=3, synced_version=2),
        _activity(activity_name="In step", version=2, synced_version=2),
        _activity(activity_name="Never synced", version=4, synced_version=None),
    ])
    session.flush()
    found = queries.search_activities(session, locally_modified=True)
    assert [row["activity_name"] for row in found["activities"]] == ["Diverged"]


def test_search_filters_by_news_digest_flag(session):
    session.add_all([
        _activity(activity_name="In digest", news_digest=True),
        _activity(activity_name="Not in digest", news_digest=False),
    ])
    session.flush()
    found = queries.search_activities(session, news_digest=True)
    assert [row["activity_name"] for row in found["activities"]] == ["In digest"]


def test_archived_only_returns_just_the_archived_rows(session):
    session.add_all([
        _activity(activity_name="Live"),
        _activity(activity_name="Archived", is_archive=True),
    ])
    session.flush()
    found = queries.search_activities(session, archived_only=True)
    assert [row["activity_name"] for row in found["activities"]] == ["Archived"]
```

- [ ] **Step 2: Run them to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_mcp_server.py -k "end_date_window or tracking_id or locally_modified or news_digest or archived_only" -v
```

Expected: FAIL — unexpected keyword arguments.

- [ ] **Step 3: Implement**

Add `and_` to the SQLAlchemy import line in `queries.py`:

```python
from sqlalchemy import String, and_, func, or_, select
```

Add the four fields to `ActivityFilters` (after `include_archived`):

```python
    news_digest: bool | None = None
    has_tracking_id: bool | None = None
    locally_modified: bool | None = None
    # Archived is a source-system view-size workaround, not a relevance signal --
    # so it gets an explicit "only these" mode rather than only a hide/show flag.
    archived_only: bool = False
```

In `_apply_filters`, replace the trailing archive clause with:

```python
    if filters.news_digest is not None:
        statement = statement.where(Activity.news_digest.is_(filters.news_digest))
    if filters.has_tracking_id is not None:
        blank = or_(
            Activity.tracking_id.is_(None),
            func.trim(Activity.tracking_id) == "",
        )
        statement = statement.where(~blank if filters.has_tracking_id else blank)
    if filters.locally_modified is not None:
        # synced_version IS NULL means "never synced", which is not divergence.
        diverged = and_(
            Activity.synced_version.is_not(None),
            Activity.version > Activity.synced_version,
        )
        statement = statement.where(diverged if filters.locally_modified else ~diverged)
    if filters.archived_only:
        statement = statement.where(Activity.is_archive.is_(True))
    elif not filters.include_archived:
        statement = statement.where(Activity.is_archive.is_(False))
    return statement
```

In `search_activities`, add to the signature (after `time_zone`):

```python
    end_after: str | None = None,
    end_before: str | None = None,
    news_digest: bool | None = None,
    has_tracking_id: bool | None = None,
    locally_modified: bool | None = None,
    archived_only: bool = False,
```

and pass them through in the `ActivityFilters(...)` construction:

```python
        end_after=end_after,
        end_before=end_before,
        news_digest=news_digest,
        has_tracking_id=has_tracking_id,
        locally_modified=locally_modified,
        archived_only=archived_only,
```

- [ ] **Step 4: Run the tests**

```bash
.venv/bin/python -m pytest tests/test_mcp_server.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/mcp/queries.py tests/test_mcp_server.py
git commit -m "Add end-date windows and the boolean planning predicates"
```

---

## Task 5: Priority rank, lead time, and exact multi-value matching

Three predicates that cannot be expressed portably in SQL:

- **Priority rank.** Two vocabularies are live at once. `analytics.js::priorityRank`
  reads a leading integer first (1 → top rank, each step down loses one) and falls
  back to words, with anything unrecognised landing on the middle rank. In SQL this
  needs a dialect-specific regex.
- **Lead time.** `v_lead_times` uses PostgreSQL `round()`, which rounds an exact
  half-day away from zero, while Python's `round()` goes to even. Computing this in
  Python is what keeps the two backends from disagreeing by a day.
- **Exact multi-value membership.** A SQL `LIKE` on the joined string matches
  "Objective A" inside "Objective AB". SQL narrows cheaply; Python decides exactly.

So: narrow in SQL, then apply these in Python over the candidate set — the pattern
`planning_gaps` already uses. The fast SQL-count path is preserved for queries that
use none of them.

Closes Q17, Q26 (rank half), Q43, Q45, Q47, Q48; hardens Q46.

**Files:**
- Modify: `pipeline/mcp/queries.py`
- Test: `tests/test_mcp_server.py`

**Interfaces:**
- Consumes: `split_multi` (Task 1), `ActivityFilters` (Task 2).
- Produces:
  - `PRIORITY_WORD_RANKS: dict[str, int]`, `DEFAULT_PRIORITY_RANK: int`
  - `priority_rank(value: Any) -> int`, `is_high_priority(value: Any) -> bool`
  - `lead_days(activity: Activity) -> int | None`
  - `ActivityFilters.contains: dict[str, str]`, `.max_lead_days: int | None`,
    `.min_priority_rank: int | None`
  - `needs_post_filter(filters: ActivityFilters) -> bool`
  - `passes_post_filter(activity: Activity, filters: ActivityFilters) -> bool`
  - `search_activities(...)` accepts `strategic_objective`, `executive`,
    `max_lead_days`, `min_priority_rank`.

- [ ] **Step 1: Write the failing tests**

```python
def test_priority_rank_reads_the_leading_number_first():
    assert queries.priority_rank("1 - most urgent label") == 4
    assert queries.priority_rank("2 - next label") == 3
    assert queries.priority_rank("3 - lower label") == 2
    assert queries.priority_rank("4 - lowest label") == 1


def test_priority_rank_falls_back_to_the_words():
    assert queries.priority_rank("Critical") == 4
    assert queries.priority_rank("high") == 3
    assert queries.priority_rank("Medium") == 2
    assert queries.priority_rank("Low") == 0


def test_priority_rank_puts_unknown_values_in_the_middle_not_at_the_bottom():
    for value in (None, "", "   ", "Wichtig"):
        assert queries.priority_rank(value) == queries.DEFAULT_PRIORITY_RANK == 1


def test_is_high_priority_covers_both_vocabularies():
    assert queries.is_high_priority("1 - label")
    assert queries.is_high_priority("2 - label")
    assert not queries.is_high_priority("3 - label")
    assert queries.is_high_priority("Critical")
    assert queries.is_high_priority("High")
    assert not queries.is_high_priority("Medium")


def test_priority_rank_matches_the_studio_implementation():
    """Pinned against analytics.js so the fourth copy of this rule cannot drift."""
    studio = (REPO_ROOT / "pipeline" / "studio" / "analytics.js").read_text()
    declared = re.search(r"const ranks = \{([^}]*)\}", studio).group(1)
    studio_ranks = {
        key: int(value)
        for key, value in re.findall(r"(\w+):\s*(\d+)", declared)
    }
    assert studio_ranks == queries.PRIORITY_WORD_RANKS
    # The numbered branch and the default, also read from the studio source.
    assert "5 - Number(numbered[1])" in studio
    assert re.search(r"\?\?\s*1;", studio), "studio default rank is 1"
    assert queries.DEFAULT_PRIORITY_RANK == 1


def test_lead_days_matches_the_api_read_model(session):
    activity = _activity(
        source_created_at=REFERENCE,
        start_date=REFERENCE + timedelta(days=12),
    )
    session.add(activity)
    session.flush()
    assert queries.lead_days(activity) == 12
    from pipeline.api.app import ActivityRead

    assert queries.lead_days(activity) == ActivityRead.model_validate(activity).planning_lead_days


def test_lead_days_is_none_without_a_start_date(session):
    activity = _activity(start_date=None)
    session.add(activity)
    session.flush()
    assert queries.lead_days(activity) is None


def test_search_filters_by_short_lead_time(session):
    session.add_all([
        _activity(
            activity_name="Short notice",
            source_created_at=REFERENCE,
            start_date=REFERENCE + timedelta(days=2),
        ),
        _activity(
            activity_name="Well planned",
            source_created_at=REFERENCE,
            start_date=REFERENCE + timedelta(days=40),
        ),
    ])
    session.flush()
    found = queries.search_activities(session, max_lead_days=7)
    assert [row["activity_name"] for row in found["activities"]] == ["Short notice"]
    assert found["total_matches"] == 1


def test_search_filters_by_minimum_priority_rank_across_both_vocabularies(session):
    session.add_all([
        _activity(activity_name="Numbered urgent", priority="2 - label"),
        _activity(activity_name="Worded urgent", priority="Critical"),
        _activity(activity_name="Routine", priority="4 - label"),
    ])
    session.flush()
    found = queries.search_activities(session, min_priority_rank=3)
    assert sorted(row["activity_name"] for row in found["activities"]) == [
        "Numbered urgent",
        "Worded urgent",
    ]
    assert found["total_matches"] == 2


def test_search_matches_one_member_of_a_multi_value_column(session):
    session.add_all([
        _activity(activity_name="Two objectives", strategic_objectives="Objective A, Objective B"),
        _activity(activity_name="Longer name", strategic_objectives="Objective AB"),
        _activity(activity_name="Other", strategic_objectives="Objective C"),
    ])
    session.flush()
    found = queries.search_activities(session, strategic_objective="Objective A")
    assert [row["activity_name"] for row in found["activities"]] == ["Two objectives"]


def test_search_matches_an_executive_across_both_executive_columns(session):
    session.add_all([
        _activity(activity_name="Board member", bod_geb="Doe, Jane"),
        _activity(activity_name="Other executive", other_executives="Roe, Sam; Poe, Ana"),
        _activity(activity_name="Nobody"),
    ])
    session.flush()
    assert [
        row["activity_name"]
        for row in queries.search_activities(session, executive="Doe, Jane")["activities"]
    ] == ["Board member"]
    assert [
        row["activity_name"]
        for row in queries.search_activities(session, executive="Poe, Ana")["activities"]
    ] == ["Other executive"]


def test_post_filtered_search_still_reports_truncation(session):
    session.add_all([
        _activity(activity_name=f"Urgent {index}", priority="1 - label")
        for index in range(5)
    ])
    session.flush()
    found = queries.search_activities(session, min_priority_rank=3, limit=2)
    assert found["total_matches"] == 5
    assert found["returned"] == 2
    assert found["truncated"] is True
    assert "Narrow the filters" in found["note"]


def test_search_without_post_filters_keeps_the_sql_count_path(session):
    session.add_all([_activity() for _ in range(3)])
    session.flush()
    assert queries.needs_post_filter(queries.ActivityFilters()) is False
    assert queries.search_activities(session)["total_matches"] == 3
```

- [ ] **Step 2: Run them to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_mcp_server.py -k "priority_rank or lead_days or short_lead_time or minimum_priority or multi_value_column or executive_across or post_filter" -v
```

Expected: FAIL — `AttributeError: ... has no attribute 'priority_rank'`.

- [ ] **Step 3: Implement the three predicates**

Add to `queries.py` after `split_multi`:

```python
# The two live priority vocabularies, mirroring analytics.js::priorityRank.
#
# The studio's entry form offers Critical / High / Medium / Low. Rows mirrored in
# from the source system instead carry a numbered label, "<n> - <label>", with four
# levels where 1 is the most urgent and 4 the least. The labels are internal
# governance wording and are deliberately not reproduced here -- only the leading
# digit carries meaning for this code.
#
# A leading integer wins because it is unambiguous. Anything in neither shape
# lands on the middle rank rather than silently reading as low: matching only the
# words was a real defect, and it made every mirrored record score the default
# while the portfolio held thousands of level-1 and level-2 activities.
PRIORITY_WORD_RANKS: dict[str, int] = {
    "critical": 4,
    "high": 3,
    "medium": 2,
    "normal": 1,
    "low": 0,
}
DEFAULT_PRIORITY_RANK = 1
HIGH_PRIORITY_RANK = 3

_LEADING_INTEGER = re.compile(r"^(\d+)")


def priority_rank(value: Any) -> int:
    """0-4, higher is more urgent, across both live priority vocabularies."""
    text = "" if value is None else str(value).strip()
    numbered = _LEADING_INTEGER.match(text)
    if numbered:
        return max(0, 5 - int(numbered.group(1)))
    return PRIORITY_WORD_RANKS.get(text.lower(), DEFAULT_PRIORITY_RANK)


def is_high_priority(value: Any) -> bool:
    """'Critical and high' in one place -- numbered levels 1-2, or the words."""
    return priority_rank(value) >= HIGH_PRIORITY_RANK


def lead_days(activity: Activity) -> int | None:
    """Whole days between the reference timestamp and start_date.

    Mirrors ActivityRead.planning_lead_days: the reference is source_created_at
    when set, else created_at. Computed here in Python rather than in SQL on
    purpose -- v_lead_times uses PostgreSQL round(), which rounds an exact half
    day away from zero while Python rounds to even, so a SQL implementation would
    disagree with the API by a day on that edge case.
    """
    if activity.start_date is None:
        return None
    reference = activity.source_created_at or activity.created_at
    if reference is None:
        return None
    delta = as_utc(activity.start_date) - as_utc(reference)
    return round(delta.total_seconds() / 86400)
```

- [ ] **Step 4: Implement the post-filter stage**

Add the three fields to `ActivityFilters` (after `archived_only`):

```python
    # Exact membership in a multi-value column: {column_name: one member value}.
    contains: dict[str, str] = dataclass_field(default_factory=dict)
    max_lead_days: int | None = None
    min_priority_rank: int | None = None
```

In `_apply_filters`, add a cheap SQL prefilter for `contains` right after the
`filters.text` loop:

```python
    # A cheap substring prefilter only: "Objective A" also matches "Objective AB",
    # so `passes_post_filter` decides membership exactly. Narrowing here keeps the
    # candidate set small; correctness happens in Python.
    for column_name, member in filters.contains.items():
        if not member:
            continue
        column = getattr(Activity, column_name)
        needle = f"%{member.strip().lower()}%"
        statement = statement.where(func.lower(func.coalesce(column, "")).like(needle))
```

Add after `_apply_filters`:

```python
def needs_post_filter(filters: ActivityFilters) -> bool:
    """True when a predicate cannot be evaluated in portable SQL.

    When this is False, the caller keeps the cheap SELECT COUNT path.
    """
    return bool(
        filters.contains
        or filters.max_lead_days is not None
        or filters.min_priority_rank is not None
    )


def passes_post_filter(activity: Activity, filters: ActivityFilters) -> bool:
    """The predicates SQL cannot express portably, evaluated exactly."""
    for column_name, member in filters.contains.items():
        if not member:
            continue
        wanted = member.strip().lower()
        members = {value.lower() for value in split_multi(getattr(activity, column_name), column_name)}
        if wanted not in members:
            return False
    if filters.max_lead_days is not None:
        days = lead_days(activity)
        if days is None or days > filters.max_lead_days:
            return False
    if filters.min_priority_rank is not None:
        if priority_rank(activity.priority) < filters.min_priority_rank:
            return False
    return True
```

Note: the `executive` filter spans two columns, which the single-column
`contains` mapping cannot express as an AND. It is handled as a special case in
`search_activities` below (OR across the two columns), not in `_apply_filters`.

- [ ] **Step 5: Wire the post-filter into `search_activities`**

Add to the signature (after `archived_only`):

```python
    strategic_objective: str | None = None,
    executive: str | None = None,
    max_lead_days: int | None = None,
    min_priority_rank: int | None = None,
```

Add to the `ActivityFilters(...)` construction:

```python
        contains={"strategic_objectives": strategic_objective},
        max_lead_days=max_lead_days,
        min_priority_rank=min_priority_rank,
```

Then replace the `total`/`rows` block with:

```python
    if needs_post_filter(filters) or executive:
        # A Python predicate is active, so the count has to come from the
        # filtered set rather than from SQL. SQL still does the narrowing.
        statement = _apply_filters(select(Activity), filters)
        if executive:
            needle = f"%{executive.strip().lower()}%"
            statement = statement.where(
                or_(
                    func.lower(func.coalesce(Activity.bod_geb, "")).like(needle),
                    func.lower(func.coalesce(Activity.other_executives, "")).like(needle),
                )
            )
        candidates = session.scalars(
            statement.order_by(Activity.start_date, Activity.id)
        ).all()
        matching = [
            activity
            for activity in candidates
            if passes_post_filter(activity, filters)
            and (
                not executive
                or executive.strip().lower()
                in {
                    value.lower()
                    for column in ("bod_geb", "other_executives")
                    for value in split_multi(getattr(activity, column), column)
                }
            )
        ]
        total = len(matching)
        rows = matching[:capped]
    else:
        total = int(
            session.scalar(_apply_filters(select(func.count()).select_from(Activity), filters)) or 0
        )
        rows = session.scalars(
            _apply_filters(select(Activity), filters)
            .order_by(Activity.start_date, Activity.id)
            .limit(capped)
        ).all()
    items = [_summarize(activity) for activity in rows]
    return {
        "total_matches": int(total),
        "returned": len(items),
        "truncated": len(items) < int(total),
        "note": _truncation_note(int(total), len(items), capped),
        "activities": items,
    }
```

- [ ] **Step 6: Run the tests**

```bash
.venv/bin/python -m pytest tests/test_mcp_server.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add pipeline/mcp/queries.py tests/test_mcp_server.py
git commit -m "Add priority-rank, lead-time and exact multi-value filters"
```

---

## Task 6: Groupable and enumerable dimension parity

`activity_counts` and `field_values` must cover the same columns
`search_activities` now filters on — otherwise the agent can filter on a value it
has no way to discover. Multi-value dimensions tally *members*, not combinations.
Adds `priority_rank` as its own dimension so Q45 is one call.

Closes Q35, Q43, Q48, Q50; hardens Q46.

**Files:**
- Modify: `pipeline/mcp/queries.py`
- Test: `tests/test_mcp_server.py`

**Interfaces:**
- Consumes: `split_multi` (Task 1), `priority_rank` (Task 5), `ActivityFilters`.
- Produces: `GROUPABLE_FIELDS` and `ENUMERABLE_FIELDS` extended;
  `MULTI_VALUE_DIMENSIONS: tuple[str, ...]`; `activity_counts` and `field_values`
  accept every filter `search_activities` does.

- [ ] **Step 1: Write the failing tests**

```python
def test_counts_by_a_multi_value_dimension_tally_members_not_combinations(session):
    session.add_all([
        _activity(strategic_objectives="Objective A, Objective B"),
        _activity(strategic_objectives="Objective A"),
    ])
    session.flush()
    counted = queries.activity_counts(session, dimension="strategic_objectives")
    buckets = {bucket["value"]: bucket["count"] for bucket in counted["buckets"]}
    assert buckets == {"Objective A": 2, "Objective B": 1}
    # The total counts memberships, which can exceed the row count -- say so.
    assert counted["counts_memberships"] is True


def test_counts_by_priority_rank_collapses_both_vocabularies(session):
    session.add_all([
        _activity(priority="1 - label"),
        _activity(priority="Critical"),
        _activity(priority="4 - label"),
    ])
    session.flush()
    counted = queries.activity_counts(session, dimension="priority_rank")
    buckets = {bucket["value"]: bucket["count"] for bucket in counted["buckets"]}
    assert buckets == {"4": 2, "1": 1}


def test_counts_accept_the_same_filters_as_search(session):
    session.add_all([
        _activity(region="Global", channel="Email"),
        _activity(region="Local", channel="Email"),
    ])
    session.flush()
    counted = queries.activity_counts(session, dimension="channel", region="Global")
    assert counted["buckets"] == [{"value": "Email", "count": 1}]


@pytest.mark.parametrize(
    "field", ["partner_team", "business_area", "target_audience", "audience", "time_zone"]
)
def test_field_values_enumerates_every_new_filter_column(session, field):
    session.add_all([_activity(**{field: "Value One"}), _activity(**{field: "Value One"})])
    session.flush()
    listed = queries.field_values(session, field=field)
    assert listed["values"] == [{"value": "Value One", "count": 2}]


def test_field_values_splits_multi_value_columns(session):
    session.add(_activity(strategic_objectives="Objective A, Objective B"))
    session.flush()
    listed = queries.field_values(session, field="strategic_objectives")
    assert sorted(entry["value"] for entry in listed["values"]) == [
        "Objective A",
        "Objective B",
    ]


def test_every_filterable_column_is_also_discoverable():
    """An agent must never be able to filter on a column it cannot enumerate."""
    missing = set(queries.FILTERABLE_TEXT_FIELDS) - set(queries.ENUMERABLE_FIELDS)
    assert missing == set(), f"filterable but not enumerable: {sorted(missing)}"
```

- [ ] **Step 2: Run them to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_mcp_server.py -k "multi_value_dimension or priority_rank_collapses or counts_accept or new_filter_column or splits_multi_value or also_discoverable" -v
```

Expected: FAIL — unknown dimension / unknown field errors.

- [ ] **Step 3: Implement**

Replace the `GROUPABLE_FIELDS` / `ENUMERABLE_FIELDS` block:

```python
# Columns an agent may group or enumerate. Free-text columns in the schema are not
# enumerated types, so `field_values` is what stops the model from guessing filter
# values that do not exist -- which means every filterable column must appear
# here too (pinned by test_every_filterable_column_is_also_discoverable).
MULTI_VALUE_DIMENSIONS: tuple[str, ...] = tuple(MULTI_VALUE_SEPARATORS)

GROUPABLE_FIELDS: tuple[str, ...] = (
    *FILTERABLE_TEXT_FIELDS,
    *MULTI_VALUE_DIMENSIONS,
    "priority_rank",
    "month",
)

# 'month' and 'priority_rank' are derived, not stored, so they are groupable but
# not enumerable.
ENUMERABLE_FIELDS: tuple[str, ...] = (
    *FILTERABLE_TEXT_FIELDS,
    *MULTI_VALUE_DIMENSIONS,
)
```

Replace `activity_counts` with:

```python
def activity_counts(
    session: Session,
    *,
    dimension: str,
    **filter_kwargs: Any,
) -> dict[str, Any]:
    """Activity volume grouped by one dimension, honouring every search filter."""
    if dimension not in GROUPABLE_FIELDS:
        return {
            "error": f"Unknown dimension {dimension!r}.",
            "supported_dimensions": list(GROUPABLE_FIELDS),
        }
    filters = _build_filters(**filter_kwargs)
    counts_memberships = dimension in MULTI_VALUE_DIMENSIONS
    if dimension in ("month", "priority_rank") or counts_memberships or needs_post_filter(filters):
        # Grouped in Python: month has no portable SQL spelling (date_trunc vs
        # strftime), priority_rank needs the two-vocabulary rule, and a
        # multi-value dimension has to be split before it can be tallied.
        rows = _filtered_activities(session, filters)
        tally: dict[str, int] = {}
        for activity in rows:
            if dimension == "month":
                keys = [_month_key(activity.start_date)]
            elif dimension == "priority_rank":
                keys = [str(priority_rank(activity.priority))]
            elif counts_memberships:
                keys = split_multi(getattr(activity, dimension), dimension) or ["Unassigned"]
            else:
                value = getattr(activity, dimension)
                keys = ["Unassigned" if is_blank(value) else str(value)]
            for key in keys:
                tally[key] = tally.get(key, 0) + 1
        if dimension == "month":
            buckets = [{"value": key, "count": count} for key, count in sorted(tally.items())]
        else:
            buckets = sorted(
                ({"value": key, "count": count} for key, count in tally.items()),
                key=lambda bucket: (-bucket["count"], str(bucket["value"])),
            )
        total = sum(bucket["count"] for bucket in buckets)
    else:
        column = getattr(Activity, dimension)
        # Unassigned rows are surfaced as their own bucket, never dropped.
        label = func.coalesce(column, "Unassigned").cast(String)
        statement = _apply_filters(
            select(label.label("value"), func.count().label("count")), filters
        ).group_by(label)
        rows = session.execute(statement).all()
        buckets = sorted(
            ({"value": value, "count": int(count)} for value, count in rows),
            key=lambda bucket: (-bucket["count"], str(bucket["value"])),
        )
        total = sum(bucket["count"] for bucket in buckets)
    return {
        "dimension": dimension,
        "total": total,
        "counts_memberships": counts_memberships,
        "buckets": buckets,
    }
```

Add the two shared helpers above it:

```python
def _build_filters(**kwargs: Any) -> ActivityFilters:
    """Build an ActivityFilters from the flat keyword set the tools expose.

    One place that knows which keyword goes into `text`, which into `contains`
    and which is a scalar, so search, counts and gaps cannot drift apart.
    """
    text = {
        name: kwargs.pop(name, None)
        for name in FILTERABLE_TEXT_FIELDS
    }
    contains = {"strategic_objectives": kwargs.pop("strategic_objective", None)}
    return ActivityFilters(
        text_query=kwargs.pop("query", None),
        text={name: value for name, value in text.items() if value},
        contains={name: value for name, value in contains.items() if value},
        start_after=kwargs.pop("start_after", None),
        start_before=kwargs.pop("start_before", None),
        end_after=kwargs.pop("end_after", None),
        end_before=kwargs.pop("end_before", None),
        include_archived=kwargs.pop("include_archived", False),
        archived_only=kwargs.pop("archived_only", False),
        news_digest=kwargs.pop("news_digest", None),
        has_tracking_id=kwargs.pop("has_tracking_id", None),
        locally_modified=kwargs.pop("locally_modified", None),
        max_lead_days=kwargs.pop("max_lead_days", None),
        min_priority_rank=kwargs.pop("min_priority_rank", None),
    )


def _filtered_activities(session: Session, filters: ActivityFilters) -> list[Activity]:
    """Every activity matching `filters`, SQL first then the Python predicates."""
    candidates = session.scalars(
        _apply_filters(select(Activity), filters).order_by(Activity.start_date, Activity.id)
    ).all()
    if not needs_post_filter(filters):
        return list(candidates)
    return [activity for activity in candidates if passes_post_filter(activity, filters)]
```

Then refactor `search_activities` to build its filters via `_build_filters` and its
rows via `_filtered_activities`, keeping the SQL-count fast path:

```python
    filters = _build_filters(
        query=query,
        channel=channel,
        source_type=source_type,
        priority=priority,
        lead=lead,
        lead_team=lead_team,
        partner_team=partner_team,
        campaign=campaign,
        region=region,
        business_division=business_division,
        business_area=business_area,
        target_audience=target_audience,
        audience=audience,
        time_zone=time_zone,
        strategic_objective=strategic_objective,
        start_after=start_after,
        start_before=start_before,
        end_after=end_after,
        end_before=end_before,
        include_archived=include_archived,
        archived_only=archived_only,
        news_digest=news_digest,
        has_tracking_id=has_tracking_id,
        locally_modified=locally_modified,
        max_lead_days=max_lead_days,
        min_priority_rank=min_priority_rank,
    )
```

Finally, make `field_values` multi-value aware — replace its query body with:

```python
    capped = _clamp_limit(limit)
    column = getattr(Activity, field)
    if field in MULTI_VALUE_DIMENSIONS:
        # Split before tallying, or the buckets are combinations rather than values.
        stored = session.scalars(select(column)).all()
        tally: dict[str, int] = {}
        blank_count = 0
        for value in stored:
            members = split_multi(value, field)
            if not members:
                blank_count += 1
                continue
            for member in members:
                tally[member] = tally.get(member, 0) + 1
        values = sorted(
            ({"value": name, "count": count} for name, count in tally.items()),
            key=lambda entry: (-entry["count"], entry["value"]),
        )[:capped]
        return {"field": field, "values": values, "blank_count": blank_count}
    rows = session.execute(
        select(column, func.count()).group_by(column).order_by(func.count().desc()).limit(capped)
    ).all()
    return {
        "field": field,
        "values": [
            {"value": value, "count": int(count)}
            for value, count in rows
            if not is_blank(value)
        ],
        "blank_count": sum(int(count) for value, count in rows if is_blank(value)),
    }
```

- [ ] **Step 4: Run the tests**

```bash
.venv/bin/python -m pytest tests/test_mcp_server.py -q
```

Expected: PASS. `test_activity_counts_rejects_unknown_dimension` and
`test_field_values_rejects_unknown_field` must still pass — the supported lists
grew, they did not become permissive.

- [ ] **Step 5: Commit**

```bash
git add pipeline/mcp/queries.py tests/test_mcp_server.py
git commit -m "Give counts and value lists the same reach as activity search"
```

---

## Task 7: Narrow and group planning gaps

`planning_gaps` is the strongest tool in the set and the least steerable: it
accepts only `source_type` and a date window. Adding the full filter set plus a
grouping turns "what is incomplete" into "which team is behind, and on which
high-priority items".

Closes Q24, Q25, Q49.

**Files:**
- Modify: `pipeline/mcp/queries.py`
- Test: `tests/test_mcp_server.py`

**Interfaces:**
- Consumes: `_build_filters`, `_filtered_activities` (Task 6), `missing_fields`.
- Produces: `planning_gaps(session, *, group_by: str | None = None, limit=None,
  **filter_kwargs)` — adds a `groups` list of
  `{value, checked, complete, incomplete}` when `group_by` is given.

- [ ] **Step 1: Write the failing tests**

```python
def test_planning_gaps_can_be_narrowed_by_priority_rank(session):
    session.add_all([
        _activity(activity_name="Urgent gap", priority="1 - label", channel=None),
        _activity(activity_name="Routine gap", priority="4 - label", channel=None),
    ])
    session.flush()
    gaps = queries.planning_gaps(session, min_priority_rank=3)
    assert gaps["incomplete"] == 1
    assert gaps["activities"][0]["activity_name"] == "Urgent gap"


def test_planning_gaps_can_be_narrowed_by_lead_team(session):
    session.add_all([
        _activity(lead_team="Team One", channel=None),
        _activity(lead_team="Team Two", channel=None),
    ])
    session.flush()
    gaps = queries.planning_gaps(session, lead_team="Team One")
    assert gaps["checked"] == 1
    assert gaps["incomplete"] == 1


def test_planning_gaps_groups_completeness_by_lead_team(session):
    session.add_all([
        _activity(lead_team="Team One", channel=None),
        _activity(lead_team="Team One", channel=None),
        _activity(lead_team="Team Two"),
    ])
    session.flush()
    gaps = queries.planning_gaps(session, group_by="lead_team")
    groups = {group["value"]: group for group in gaps["groups"]}
    assert groups["Team One"]["incomplete"] == 2
    assert groups["Team One"]["complete"] == 0
    assert groups["Team Two"]["incomplete"] == 0
    assert groups["Team Two"]["complete"] == 1
    # Worst group first, so the answer leads with where the problem is.
    assert gaps["groups"][0]["value"] == "Team One"


def test_planning_gaps_rejects_an_unknown_grouping(session):
    result = queries.planning_gaps(session, group_by="nonsense")
    assert "error" in result
    assert "lead_team" in result["supported_dimensions"]
```

- [ ] **Step 2: Run them to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_mcp_server.py -k planning_gaps -v
```

Expected: FAIL — `TypeError: planning_gaps() got an unexpected keyword argument 'min_priority_rank'`.

- [ ] **Step 3: Implement**

Replace `planning_gaps` with:

```python
def planning_gaps(
    session: Session,
    *,
    group_by: str | None = None,
    limit: int | None = None,
    **filter_kwargs: Any,
) -> dict[str, Any]:
    """Activities failing the unified completeness rule, worst offenders first.

    The rule is evaluated in Python rather than SQL so it holds identically on
    SQLite and PostgreSQL; the candidate set is narrowed in SQL first.

    `group_by` additionally reports completeness per group -- which team or
    channel is behind, rather than only which records are.
    """
    if group_by is not None and group_by not in ENUMERABLE_FIELDS:
        return {
            "error": f"Cannot group planning gaps by {group_by!r}.",
            "supported_dimensions": list(ENUMERABLE_FIELDS),
        }
    capped = _clamp_limit(limit)
    filters = _build_filters(**filter_kwargs)
    candidates = _filtered_activities(session, filters)

    incomplete: list[tuple[Activity, list[str]]] = []
    field_tally: dict[str, int] = {}
    groups: dict[str, dict[str, int]] = {}
    for activity in candidates:
        gaps = missing_fields(activity)
        if group_by is not None:
            for key in split_multi(getattr(activity, group_by), group_by) or ["Unassigned"]:
                bucket = groups.setdefault(key, {"checked": 0, "complete": 0, "incomplete": 0})
                bucket["checked"] += 1
                bucket["incomplete" if gaps else "complete"] += 1
        if not gaps:
            continue
        for name in gaps:
            field_tally[name] = field_tally.get(name, 0) + 1
        incomplete.append((activity, gaps))

    incomplete.sort(key=lambda pair: (-len(pair[1]), pair[0].start_date is None))
    shown = incomplete[:capped]
    answer: dict[str, Any] = {
        "checked": len(candidates),
        "complete": len(candidates) - len(incomplete),
        "incomplete": len(incomplete),
        "returned": len(shown),
        "truncated": len(shown) < len(incomplete),
        "missing_field_counts": dict(
            sorted(field_tally.items(), key=lambda item: (-item[1], item[0]))
        ),
        "activities": [
            {
                **_summarize(activity),
                "missing_required_fields": gaps,
                "missing_count": len(gaps),
            }
            for activity, gaps in shown
        ],
    }
    if group_by is not None:
        answer["group_by"] = group_by
        answer["groups"] = sorted(
            ({"value": key, **counts} for key, counts in groups.items()),
            key=lambda group: (-group["incomplete"], group["value"]),
        )
    return answer
```

- [ ] **Step 4: Run the tests**

```bash
.venv/bin/python -m pytest tests/test_mcp_server.py -q
```

Expected: PASS, including the existing
`test_planning_gaps_agrees_with_the_postgres_view` — the completeness rule itself
is untouched.

- [ ] **Step 5: Commit**

```bash
git add pipeline/mcp/queries.py tests/test_mcp_server.py
git commit -m "Let planning gaps be narrowed and grouped"
```

---

## Task 8: Expose the priority rank on every activity summary

The agent should not have to re-derive urgency per row. Adds `priority_rank` to the
compact summary and to `get_activity`, so a mixed-vocabulary result set can be
sorted and explained without the model knowing the rule.

**Files:**
- Modify: `pipeline/mcp/queries.py`
- Test: `tests/test_mcp_server.py`

**Interfaces:**
- Consumes: `priority_rank`, `is_high_priority` (Task 5).
- Produces: `_summarize()` output gains `priority_rank: int` and
  `is_high_priority: bool`; `get_activity()`'s `activity` record gains the same two
  keys.

- [ ] **Step 1: Write the failing tests**

```python
def test_summaries_carry_the_derived_priority_rank(session):
    session.add(_activity(priority="2 - label"))
    session.flush()
    row = queries.search_activities(session)["activities"][0]
    assert row["priority_rank"] == 3
    assert row["is_high_priority"] is True


def test_full_record_carries_the_derived_priority_rank(session):
    activity = _activity(priority="4 - label")
    session.add(activity)
    session.flush()
    record = queries.get_activity(session, str(activity.id))["activity"]
    assert record["priority_rank"] == 1
    assert record["is_high_priority"] is False
```

- [ ] **Step 2: Run them to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_mcp_server.py -k derived_priority_rank -v
```

Expected: FAIL — `KeyError: 'priority_rank'`.

- [ ] **Step 3: Implement**

In `_summarize`, add before the `return`:

```python
    # Derived, so a mixed-vocabulary result set can be ranked without the model
    # having to know the two priority schemes.
    row["priority_rank"] = priority_rank(activity.priority)
    row["is_high_priority"] = is_high_priority(activity.priority)
```

In `get_activity`, add after the `record["is_complete"] = not gaps` line:

```python
    record["priority_rank"] = priority_rank(activity.priority)
    record["is_high_priority"] = is_high_priority(activity.priority)
```

Check `test_get_activity_returns_the_api_read_model_verbatim` still passes: it
asserts the API read-model fields are present and unchanged, and these are
additions, not overwrites. If it asserts exact key equality, extend its expected
set with the two derived keys and the existing `missing_required_fields` /
`is_complete` pattern it already allows.

- [ ] **Step 4: Run the tests**

```bash
.venv/bin/python -m pytest tests/test_mcp_server.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/mcp/queries.py tests/test_mcp_server.py
git commit -m "Report the derived priority rank on every activity answer"
```

---

## Task 9: The domain-model resource

The correctness half of Phase 1. Five domain traps are documented in the knowledge
base and invisible to an agent, and the failure mode is a confident wrong answer.
This task makes them discoverable and states the phase-one scope boundary so
performance questions get declined rather than approximated.

**Files:**
- Create: `pipeline/mcp/domain.py`
- Test: `tests/test_mcp_server.py`

**Interfaces:**
- Consumes: `queries.PRIORITY_WORD_RANKS`, `queries.REQUIRED_COMMON_FIELDS`,
  `queries.REQUIRED_INTERNAL_FIELDS`, `queries.MULTI_VALUE_SEPARATORS`.
- Produces: `DOMAIN_MODEL: str` (Markdown), `domain_model() -> str`.
  No `mcp` import — assertable without the SDK.

- [ ] **Step 1: Write the failing tests**

```python
def test_domain_model_names_every_trap():
    from pipeline.mcp.domain import domain_model

    text = domain_model()
    for phrase in (
        "two vocabularies",
        "archiv",          # archived is not a relevance signal
        "tracking cluster",
        "other_executives",
        "audience",
        "planning only",
    ):
        assert phrase.lower() in text.lower(), phrase


def test_domain_model_lists_the_real_required_fields():
    from pipeline.mcp.domain import domain_model

    text = domain_model()
    for name in queries.REQUIRED_COMMON_FIELDS + queries.REQUIRED_INTERNAL_FIELDS:
        assert name in text, name


def test_domain_model_states_the_real_multi_value_separators():
    from pipeline.mcp.domain import domain_model

    text = domain_model()
    for name in queries.MULTI_VALUE_SEPARATORS:
        assert name in text, name


def test_domain_model_uses_the_generic_organisation_vocabulary():
    """The resource text reaches an external model -- it must stay brand-neutral.

    Asserted positively, by requiring the generic wording. A denylist test would
    have to spell the forbidden name, which is the thing that must not enter this
    repository; the repo-wide pre-push grep is the negative check.
    """
    from pipeline.mcp.domain import domain_model

    text = domain_model().lower()
    assert "source system" in text
    assert "communication" in text
    # The executive columns must be described by column name, never by example --
    # an example would be a personal name, and this text reaches an external
    # model. Assert the column names carry the explanation.
    assert "bod_geb" in text
    assert "other_executives" in text
```

- [ ] **Step 2: Run them to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_mcp_server.py -k domain_model -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.mcp.domain'`.

- [ ] **Step 3: Implement**

Create `pipeline/mcp/domain.py`:

```python
"""The domain model an agent needs before it trusts its own answers.

Served as the `cplan://domain-model` MCP resource. Deliberately free of any `mcp`
import, for the same reason `queries.py` is: it must be assertable by a test that
runs without the optional SDK installed.

The field lists are generated from `queries.py` rather than restated, so the
resource cannot drift from the rule the tools actually apply.
"""

from __future__ import annotations

from pipeline.mcp import queries


def _bullets(names: tuple[str, ...]) -> str:
    return ", ".join(f"`{name}`" for name in names)


def domain_model() -> str:
    """The domain model, vocabularies and traps, as Markdown."""
    word_ranks = ", ".join(
        f"{word} = {rank}" for word, rank in sorted(
            queries.PRIORITY_WORD_RANKS.items(), key=lambda item: -item[1]
        )
    )
    separators = "\n".join(
        f"- `{field}` splits on {' or '.join(repr(sep) for sep in seps)}"
        for field, seps in sorted(queries.MULTI_VALUE_SEPARATORS.items())
    )
    return f"""\
# CPLAN domain model

Read this before answering anything quantitative. Five properties of this data
produce confidently wrong answers if you do not know them.

## What CPLAN is

A communication planning tool: one row per planned communication activity, each
with a channel, a priority, an owning lead and lead team, a start and end date,
and a tracking id.

**Scope: planning only.** CPLAN holds no performance data — no views, no
engagement, no reach achieved. The tracking id is the intended join key to
cross-channel reporting, but the other side of that join is not in this database.
If asked how something performed, say plainly that this data cannot answer it.
Do not approximate performance from planning fields.

## Hierarchy

    Tracking cluster
    └── Communication pack
        └── Communication activity

Only the activity level is a first-class record. Cluster and pack identity live
inside the tracking id (`CLUSTER-PACKNUM-YYMMDD-ACTNUM-CHANNEL`) and in the
`campaign` / `communication_pack` text columns. So `campaign` is not the whole
hierarchy, and cluster-level questions cannot be answered exactly.

An activity with no pack is not incomplete — a legitimate standalone activity is
fully planned once its own fields are filled in. Never guess pack membership.

## Trap 1 — priority has two live vocabularies at once

Activities created in the studio use **Critical / High / Medium / Low**.
Activities mirrored from the source system use a **numbered label**,
`<n> - <label>`, with four levels where **1 is most urgent and 4 least**.

Filtering `priority="High"` therefore misses every urgent mirrored record. Use
the `priority_rank` dimension or the `min_priority_rank` filter instead: rank runs
0-4, higher is more urgent ({word_ranks}), a leading digit `n` maps to `5 - n`,
and an unrecognised value lands on the middle rank ({queries.DEFAULT_PRIORITY_RANK})
rather than reading as low. "Critical and high" means rank >= {queries.HIGH_PRIORITY_RANK}.

The distribution is heavily skewed: in a production-scale portfolio the lowest
level held roughly two thirds of all activities and the top level about one
percent. A filter returning about a sixth of the portfolio as urgent is working
correctly, not broken.

## Trap 2 — archived does not mean irrelevant

The source system splits activities into an active list and an archive purely
because its list views cap at about 5,000 items. Archiving is a view-size
workaround, not a relevance signal, and archived activities count in every KPI.

`search_activities` nevertheless **excludes archived rows by default**. Pass
`include_archived=True` for a true total, or `archived_only=True` to inspect them.
`field_values` always counts across archived rows.

## Trap 3 — the filter columns are free text, not enumerations

`channel`, `priority`, `region` and the rest are text columns. A guessed value
matches nothing and returns zero — which looks like a real answer. Call
`field_values` for a column before filtering on it. Filters compare
case-insensitively, so only the spelling has to be right.

## Trap 4 — three columns hold several values in one string

{separators}

Grouping the raw strings yields combinations, not individual objectives or people.
The tools split them for you: group by the column name, or filter with
`strategic_objective=` / `executive=` for exact membership.

Executive involvement is split across **two** columns — `bod_geb` (executive-board
members) and `other_executives` (senior leaders who are not on that board) — and
they are counted separately everywhere. The `executive=` filter searches both.

## Trap 5 — `audience` is a band label, and its meaning is unverified

`audience` holds a size band (`< 1000`, `1-10k`, `10-50k`, `50-100k`, `> 100k`),
not a number, so planned reach cannot be summed. The mapping from the source
system's "estimated audience size" field to this column is a documented
assumption, not a confirmed fact. Do not present it as measured reach.

## Planning completeness

An activity is complete when it has all of: {_bullets(queries.REQUIRED_COMMON_FIELDS)}.
Internal activities additionally need {_bullets(queries.REQUIRED_INTERNAL_FIELDS)}.
Both `lead` and `lead_team` are required — there is no either-satisfies shortcut.
A text field counts as missing when it is null, blank, or the literal string
'None' or 'null'. This is exactly the rule the studio shows, so
`planning_gaps` and the studio never disagree.

## Result caps

Every list-shaped answer is capped ({queries.DEFAULT_LIMIT} rows by default,
{queries.MAX_LIMIT} maximum) and reports its own truncation. When an answer is
truncated, narrow the filters — do not raise the limit and do not assume the
returned rows are the whole set.
"""


DOMAIN_MODEL: str = domain_model()
```

- [ ] **Step 4: Run the tests**

```bash
.venv/bin/python -m pytest tests/test_mcp_server.py -k domain_model -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/mcp/domain.py tests/test_mcp_server.py
git commit -m "Describe the domain traps an agent has to know"
```

---

## Task 10: Wire everything into the protocol surface

Until this task the new capability is invisible over MCP. Registers the resource,
rewrites the instructions, and extends the six tool signatures and docstrings.

The tool docstring **is** the model's only guidance for that call, so each one has
to name its own traps.

**Files:**
- Modify: `pipeline/mcp/server.py`
- Test: `tests/test_mcp_server.py`

**Interfaces:**
- Consumes: every `queries` addition above, and `domain.domain_model`.
- Produces: `build_server()` registers the `cplan://domain-model` resource; all six
  tools accept the new parameters.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.skipif(MCP_SDK_MISSING, reason="the mcp SDK is optional (pip install mcp)")
def test_domain_model_is_registered_as_a_resource(engine):
    from pipeline.mcp.server import build_server

    server = build_server(str(engine.url))
    uris = {str(resource.uri) for resource in asyncio.run(server.list_resources())}
    assert "cplan://domain-model" in uris


@pytest.mark.skipif(MCP_SDK_MISSING, reason="the mcp SDK is optional (pip install mcp)")
def test_instructions_point_at_the_domain_model_resource(engine):
    from pipeline.mcp.server import build_server

    server = build_server(str(engine.url))
    assert "cplan://domain-model" in server.instructions


@pytest.mark.skipif(MCP_SDK_MISSING, reason="the mcp SDK is optional (pip install mcp)")
def test_search_exposes_every_new_filter_over_the_protocol(engine):
    from pipeline.mcp.server import build_server

    server = build_server(str(engine.url))
    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
    properties = tools["search_activities"].input_schema["properties"]
    for name in (
        "lead_team", "partner_team", "region", "business_division", "business_area",
        "target_audience", "audience", "time_zone", "end_after", "end_before",
        "news_digest", "has_tracking_id", "locally_modified", "archived_only",
        "strategic_objective", "executive", "max_lead_days", "min_priority_rank",
    ):
        assert name in properties, name


@pytest.mark.skipif(MCP_SDK_MISSING, reason="the mcp SDK is optional (pip install mcp)")
def test_planning_gaps_exposes_grouping_over_the_protocol(engine):
    from pipeline.mcp.server import build_server

    server = build_server(str(engine.url))
    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
    assert "group_by" in tools["planning_gaps"].input_schema["properties"]


@pytest.mark.skipif(MCP_SDK_MISSING, reason="the mcp SDK is optional (pip install mcp)")
def test_priority_tool_descriptions_warn_about_the_two_vocabularies(engine):
    from pipeline.mcp.server import build_server

    server = build_server(str(engine.url))
    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
    for name in ("search_activities", "activity_counts"):
        assert "vocabular" in tools[name].description.lower(), name
```

Add `import asyncio` to the test module's imports.

- [ ] **Step 2: Run them to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_mcp_server.py -k "registered_as_a_resource or point_at_the_domain or every_new_filter or exposes_grouping or two_vocabularies" -v
```

Expected: FAIL — the resource is not registered and the parameters do not exist.

- [ ] **Step 3: Replace the instructions and register the resource**

In `pipeline/mcp/server.py`, add the import:

```python
from pipeline.mcp.domain import domain_model  # noqa: E402
```

Replace `INSTRUCTIONS` with:

```python
INSTRUCTIONS = """\
CPLAN holds the communication activity plan: one row per planned communication
activity, each with a channel, a priority, an owning lead/lead team, a start and
end date, and a tracking id of the form CLUSTER-PACKNUM-....

Read-only, and planning only -- there is no performance, reach or engagement data
here. Say so plainly rather than approximating it from planning fields.

READ THE `cplan://domain-model` RESOURCE FIRST. It carries five properties of this
data that otherwise produce confidently wrong answers: priority runs on two
different vocabularies at once, archived does not mean irrelevant, the filter
columns are free text rather than enumerations, three columns hold several values
in one string, and the audience column is an unverified size band.

Then: database_status for size and freshness, field_values before filtering on any
free-text value, search_activities to narrow, get_activity for one full record,
planning_gaps for what is not ready yet, activity_counts for volumes. Every list
answer is capped and reports its own truncation -- narrow the filters instead of
raising the limit.
"""
```

Inside `build_server`, after the `server = MCPServer(...)` block:

```python
    @server.resource(
        "cplan://domain-model",
        name="CPLAN domain model",
        description=(
            "The planning domain model, both priority vocabularies, the archive "
            "semantics, the multi-value columns and the completeness rule. Read "
            "before answering anything quantitative."
        ),
        mime_type="text/markdown",
    )
    def cplan_domain_model() -> str:
        return domain_model()
```

- [ ] **Step 4: Extend the tool signatures**

Replace the `search_activities` tool with:

```python
    @server.tool()
    def search_activities(
        query: str | None = None,
        channel: str | None = None,
        source_type: str | None = None,
        priority: str | None = None,
        min_priority_rank: int | None = None,
        lead: str | None = None,
        lead_team: str | None = None,
        partner_team: str | None = None,
        campaign: str | None = None,
        region: str | None = None,
        business_division: str | None = None,
        business_area: str | None = None,
        target_audience: str | None = None,
        audience: str | None = None,
        time_zone: str | None = None,
        strategic_objective: str | None = None,
        executive: str | None = None,
        start_after: str | None = None,
        start_before: str | None = None,
        end_after: str | None = None,
        end_before: str | None = None,
        max_lead_days: int | None = None,
        news_digest: bool | None = None,
        has_tracking_id: bool | None = None,
        locally_modified: bool | None = None,
        include_archived: bool = False,
        archived_only: bool = False,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Find activities by text and/or filters; returns compact summaries.

        `query` matches the activity name, tracking id and description
        case-insensitively. Every other text filter is case-insensitive equality
        on a free-text column -- call field_values first, because a guessed value
        matches nothing and returns zero.

        Priority: two vocabularies are live at once (studio words, and numbered
        source labels where 1 is most urgent), so prefer `min_priority_rank`
        (0-4, higher is more urgent; 3 means "critical and high") over `priority`.

        `strategic_objective` and `executive` match one member of a multi-valued
        column; `executive` searches both executive columns.

        Windows: `start_after`/`start_before` filter start_date,
        `end_after`/`end_before` filter end_date; both take 'YYYY-MM-DD' or a full
        ISO timestamp. `max_lead_days` finds short-notice activities (days between
        creation and start).

        Archived activities are excluded unless `include_archived`; archiving is a
        source-system view-size workaround, not a relevance signal, so a true
        total needs `include_archived=True`. `archived_only` inspects just those.

        Returns at most 50 rows by default (200 hard cap) plus the true match
        count, so a broad search reports its own truncation instead of filling the
        context. Use get_activity for the full record of one row.
        """
        return read(
            lambda session: queries.search_activities(
                session,
                query=query,
                channel=channel,
                source_type=source_type,
                priority=priority,
                min_priority_rank=min_priority_rank,
                lead=lead,
                lead_team=lead_team,
                partner_team=partner_team,
                campaign=campaign,
                region=region,
                business_division=business_division,
                business_area=business_area,
                target_audience=target_audience,
                audience=audience,
                time_zone=time_zone,
                strategic_objective=strategic_objective,
                executive=executive,
                start_after=start_after,
                start_before=start_before,
                end_after=end_after,
                end_before=end_before,
                max_lead_days=max_lead_days,
                news_digest=news_digest,
                has_tracking_id=has_tracking_id,
                locally_modified=locally_modified,
                include_archived=include_archived,
                archived_only=archived_only,
                limit=limit,
            )
        )
```

Replace `planning_gaps` with the same filter set plus `group_by`, forwarding via
`**` is not possible across the MCP boundary (the schema comes from the signature),
so list the parameters explicitly:

```python
    @server.tool()
    def planning_gaps(
        source_type: str | None = None,
        lead_team: str | None = None,
        lead: str | None = None,
        channel: str | None = None,
        region: str | None = None,
        business_division: str | None = None,
        campaign: str | None = None,
        min_priority_rank: int | None = None,
        start_after: str | None = None,
        start_before: str | None = None,
        group_by: str | None = None,
        include_archived: bool = False,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Activities that are not fully planned yet, worst first.

        Applies the studio's completeness rule: every activity needs name,
        description, channel, priority, strategic objectives, region, start and
        end date, time zone, lead and lead team; internal activities also need
        target audience, audience and business division. Both lead and lead_team
        are required -- there is no either-satisfies shortcut.

        Narrow it like a search: `min_priority_rank=3` finds the urgent gaps,
        `lead_team=` scopes it to one team. `group_by` (any enumerable column,
        e.g. lead_team) additionally reports complete/incomplete per group, worst
        group first -- that is how to answer "which team is behind" rather than
        "which records are incomplete".

        Returns per-activity missing fields plus a tally of which fields are
        missing most often. Pack/campaign linkage is deliberately NOT part of
        completeness: a standalone activity with no pack is fully planned.

        There is no `executive` filter here: to find incomplete executive
        activities, call search_activities with `executive=` and read
        `missing_required_fields` on the results.
        """
        return read(
            lambda session: queries.planning_gaps(
                session,
                source_type=source_type,
                lead_team=lead_team,
                lead=lead,
                channel=channel,
                region=region,
                business_division=business_division,
                campaign=campaign,
                min_priority_rank=min_priority_rank,
                start_after=start_after,
                start_before=start_before,
                group_by=group_by,
                include_archived=include_archived,
                limit=limit,
            )
        )
```

Why no `executive` parameter here: matching an executive is an OR across two
columns, which the single-column `contains` mapping in `_build_filters` does not
model. Accepting a parameter that silently does nothing is worse than not offering
it, so it is absent and the docstring routes the user to `search_activities`.

Replace `activity_counts` with:

```python
    @server.tool()
    def activity_counts(
        dimension: str,
        source_type: str | None = None,
        channel: str | None = None,
        lead_team: str | None = None,
        region: str | None = None,
        business_division: str | None = None,
        campaign: str | None = None,
        min_priority_rank: int | None = None,
        start_after: str | None = None,
        start_before: str | None = None,
        include_archived: bool = False,
    ) -> dict[str, Any]:
        """Activity volume grouped by one dimension, with optional filters.

        dimension is any filterable column, plus 'month', 'priority_rank', and
        the multi-value columns. 'month' buckets by start_date as 'YYYY-MM'
        ('unscheduled' when missing); rows with no value are grouped as
        'Unassigned' rather than dropped.

        Use 'priority_rank' rather than 'priority': two vocabularies are live at
        once (studio words, and numbered source labels where 1 is most urgent),
        so grouping the raw labels splits the same urgency across two spellings.
        Rank runs 0-4, higher is more urgent.

        Grouping a multi-value column (strategic_objectives, the executive
        columns) tallies individual members, so the total counts memberships and
        can exceed the activity count -- `counts_memberships` says when.
        """
        return read(
            lambda session: queries.activity_counts(
                session,
                dimension=dimension,
                source_type=source_type,
                channel=channel,
                lead_team=lead_team,
                region=region,
                business_division=business_division,
                campaign=campaign,
                min_priority_rank=min_priority_rank,
                start_after=start_after,
                start_before=start_before,
                include_archived=include_archived,
            )
        )
```

Update `field_values` so its supported-field list is generated rather than
restated — a hand-written list drifts the moment `ENUMERABLE_FIELDS` grows.

An f-string cannot be a docstring: Python treats it as a plain expression and
`__doc__` becomes `None`, which would break
`test_every_tool_is_registered_with_a_description`. Pass the generated text to the
decorator instead, which is also the one place the SDK is guaranteed to read it:

```python
    @server.tool(
        description=(
            "Distinct stored values of a filter column, with row counts.\n\n"
            "Use before filtering: channel, priority, region and the rest are "
            "free text, not enumerations, so a guessed value silently matches "
            "nothing. Counts include archived rows, so a value occurring only on "
            "archived activities is still discoverable. Multi-value columns are "
            "split into their individual members rather than listed as "
            "combinations.\n\n"
            f"Supported fields: {', '.join(queries.ENUMERABLE_FIELDS)}."
        )
    )
    def field_values(field: str, limit: int | None = None) -> dict[str, Any]:
        return read(lambda session: queries.field_values(session, field=field, limit=limit))
```

`@server.tool()` accepts `description` in the installed SDK — verified signature:
`tool(name=None, title=None, description=None, annotations=None, icons=None,
meta=None, structured_output=None)`.

- [ ] **Step 5: Run the whole suite**

```bash
.venv/bin/python -m pytest tests/test_mcp_server.py -q
```

Expected: PASS, including `test_every_tool_is_registered_with_a_description`,
`test_stdio_handshake_lists_and_calls_tools` and
`test_stdio_server_keeps_stdout_clean`.

- [ ] **Step 6: Manual smoke check over stdio**

```bash
.venv/bin/python -m pipeline.mcp.server --settings data/cplan-settings.json
```

Expected on stderr: `cplan MCP server ready (sqlite, read-only)` and nothing on
stdout. Terminate with Ctrl-C.

- [ ] **Step 7: Commit**

```bash
git add pipeline/mcp/server.py tests/test_mcp_server.py
git commit -m "Expose the new filters and the domain model over the protocol"
```

---

## Task 11: Documentation and both-backend verification

**Files:**
- Modify: `pipeline/mcp/README.md`
- Modify: `docs/CPLAN_KNOWLEDGE_BASE.md`

- [ ] **Step 1: Update the MCP README**

In the `## Tools` table, replace the `field_values`, `search_activities`,
`planning_gaps` and `activity_counts` rows so they describe the widened surface,
and add a `## Resources` section above `## Design notes`:

```markdown
## Resources

| Resource | Carries |
|---|---|
| `cplan://domain-model` | The hierarchy, both priority vocabularies, the archive semantics, the multi-value columns, the completeness rule, and the planning-only scope boundary |

An agent that skips this resource will answer priority and archive questions
confidently wrong. The server instructions tell it to read the resource first.
```

Add to `## Design notes`:

```markdown
**Filter, group and enumerate are kept in step by a test.**
`test_every_filterable_column_is_also_discoverable` fails if a column becomes
filterable without also being enumerable — an agent must never be able to filter
on a value it has no way to discover.

**Two predicates are evaluated in Python, not SQL.** `priority_rank` needs the
two-vocabulary rule and `max_lead_days` has to match the API's rounding
(`v_lead_times` uses PostgreSQL `round()`, which rounds an exact half day away
from zero while Python rounds to even). SQL narrows the candidate set first;
`needs_post_filter` keeps the cheap `SELECT COUNT` path for every query that uses
neither.

**Multi-value columns split on the separator the ETL actually wrote.** Lookup
values join with `", "`, person values with `"; "`. Person columns are split on
`;` only — deliberately unlike `analytics.js::normalizeMulti`, which splits both
on `/[;,]/`: a person name may contain a comma, and splitting it would invent a
person. Splitting a lookup value on `","` remains lossy for a value whose own
name contains a comma.
```

Update the `## Known limits` section: remove nothing (no authentication and no
write tools are both still true), and add:

```markdown
- Cluster-level questions cannot be answered exactly. Tracking clusters and
  communication packs are not first-class records; their identity lives in the
  tracking-id string and in free-text columns.
- No performance data. Reach and engagement questions are out of scope by design;
  the domain-model resource tells the agent to decline them rather than
  approximate them from planning fields.
```

- [ ] **Step 2: Record the separator finding in the knowledge base**

In `docs/CPLAN_KNOWLEDGE_BASE.md`, add to the `### Local database` section:

```markdown
Multi-value columns carry several values in one string. `pipeline/scripts/process_cplan.py`
joins SharePoint lookup and taxonomy values with `", "` (`parse_sp_lookup`) and
person values with `"; "` (`PERSON_JOIN`, for `SP_MULTI_PERSON_COLUMNS` — the two
executive columns). Consumers must split before tallying, or they count
combinations rather than values. Splitting a lookup value on `","` is lossy for a
value whose own name contains a comma; the person separator is unambiguous. Not
yet verified against a production snapshot — the code is authoritative for what
the sync writes.
```

- [ ] **Step 3: Run the full check on SQLite**

```bash
.venv/bin/python -m pytest tests/ -q && node --test tests/*.test.js
```

Expected: all pytest tests pass (685 before this plan, plus the ~45 added here),
all 54 node tests pass.

- [ ] **Step 4: Run the full check against real PostgreSQL**

```bash
docker run --rm -d --name cplan-pg -e POSTGRES_PASSWORD=looptest \
  -e POSTGRES_USER=cplan -e POSTGRES_DB=cplan \
  -p 127.0.0.1:55433:5432 postgres:17-alpine
CPLAN_TEST_DATABASE_URL=postgresql+psycopg://cplan:looptest@127.0.0.1:55433/cplan \
  .venv/bin/python -m pytest tests/ -q
docker stop cplan-pg
```

Expected: PASS. Every new query test runs twice; a failure here means a predicate
was written for one dialect.

- [ ] **Step 5: Confirm no brand or path leakage**

Run the two-command leakage check documented in the workspace `CLAUDE.md` under
"Kein Markenname in Git" — a case-insensitive whole-word `git grep` for the
employer name across the tree (excluding lock files), and the same grep over the
last 15 commit subjects. The exact token is deliberately not written here: this
file is committed, and spelling it would be the leak.

Expected: no output from either command. Also confirm no absolute local path has
entered the new files (`git grep -n "/Users/"`).

- [ ] **Step 6: Commit**

```bash
git add pipeline/mcp/README.md docs/CPLAN_KNOWLEDGE_BASE.md
git commit -m "Document the widened read surface and the multi-value separators"
```

---

## Self-review notes

**Spec coverage.** Phase 1 item 1 (filter/group parity) → Tasks 2–7. Item 2
(catalogue metadata) → Tasks 9–10. Item 3 (priority-rank projection) → Tasks 5, 6,
8. The spec's multi-value caveat → Task 1. The spec's projection of Q8, Q9, Q13,
Q16, Q17, Q24, Q25, Q26, Q30, Q34, Q35, Q43, Q45, Q47, Q48, Q49, Q50, Q52 is
covered, except as noted below.

**Two deviations from the spec, both deliberate:**

1. **Q13** ("does my date collide with a senior-leader communication that week")
   is only partly closed. Task 5 makes executive activities *findable* by date
   window, which is what Phase 1 can do; scoring it as a collision needs the
   `detectCollisions` port in Phase 2. Treat Q13 as **P**, not **A**, after this
   plan.
2. **`planning_gaps` does not take `executive`.** The two-column OR does not fit
   the single-column `contains` mapping, and accepting a parameter that silently
   does nothing is worse than not offering it. Q49 is answered by searching with
   `executive=` and reading `missing_required_fields` on the results — the
   docstring says so.

**Revised projection:** 33 A / 11 P / 8 T / 11 D, not the spec's 34/10/8/11.
Update the spec's Phase 1 line when this plan lands.

**Type consistency check.** `split_multi(value, field)` — same argument order at
all six call sites. `priority_rank(value)` takes the raw column value everywhere,
never an `Activity`. `lead_days(activity)` takes the `Activity`, unlike
`priority_rank` — the asymmetry is real (it needs three columns) and both are used
consistently. `_build_filters(**kwargs)` and `_filtered_activities(session,
filters)` are the only two entry points the query functions share.

**Known cost, accepted.** Any query using a Python-side predicate loses the SQL
`COUNT` path and materialises the SQL-narrowed candidate set. `planning_gaps`
already worked this way. At the documented production scale (~18k activities) this
is acceptable for a local single-user deployment; if the dataset grows, the
`min_priority_rank` predicate is the one worth pushing into dialect-specific SQL
first.
