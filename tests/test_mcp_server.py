"""Tests for the read-only MCP server (`pipeline/mcp/`).

Split in three:

* the query layer (`pipeline/mcp/queries.py`) is plain SQLAlchemy and runs
  against BOTH backends -- "backend-neutral" is the whole premise of not
  building on the PostgreSQL-only `v_*` views, so every query test is
  parametrized the same way `tests/test_api.py` parametrizes its client;
* the read-only engine guard is tested by attempting a write;
* the protocol layer needs the optional `mcp` SDK, so those tests carry a
  skipif in the same style as the optional-`pgserver` tests.

Set `CPLAN_TEST_DATABASE_URL` to a PostgreSQL URL to run the PostgreSQL half
(the sqlite half always runs), e.g.

    CPLAN_TEST_DATABASE_URL=postgresql+psycopg://cplan:...@127.0.0.1:55433/cplan

All fixture data is synthetic.
"""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import itertools
import json
import os
import re
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pytest
from sqlalchemy.orm import Session

from pipeline.api.app import Activity, ActivityChange, Base, SyncRun
from pipeline.api.views import ANALYSIS_VIEWS, drop_analysis_views
from pipeline.mcp import queries
from pipeline.mcp.engine import ReadOnlyViolation, create_read_only_engine

REPO_ROOT = Path(__file__).resolve().parents[1]

MCP_SDK_MISSING = importlib.util.find_spec("mcp") is None

TEST_DATABASE_URL = os.environ.get("CPLAN_TEST_DATABASE_URL")
TEST_BACKENDS = ("sqlite", "postgresql") if TEST_DATABASE_URL else ("sqlite",)

REFERENCE = datetime(2026, 1, 10, 9, 0, tzinfo=timezone.utc)

# A module-level counter, not `uuid.uuid4().int % 10_000_000`: the modulo
# truncated a real uuid down to 7 digits, so any single test inserting a few
# hundred untagged activities (the MAX_LIMIT-plus-surplus tests do) had a real
# birthday-paradox chance of two rows landing on the same tracking_id and
# tripping the column's UNIQUE constraint -- a suite that fails at random is
# worse than one that is merely slow. A monotonic counter can never repeat
# within a test run, no plugin here reorders or parallelizes tests (no
# pytest-randomly, no pytest-xdist), and it keeps the exact digit-count shape
# (`:07d`) the tracking-id pattern (`CLUSTER-PACKNUM-YYMMDD-ACTNUM-CHANNEL`)
# and this module's own literal overrides (e.g. "CLU-1-260110-0000001-EM")
# already assume.
_TRACKING_ID_COUNTER = itertools.count(1)


def _activity(**overrides):
    """A fully planned internal activity; override to introduce gaps."""
    base = dict(
        id=uuid.uuid4(),
        source_type="internal",
        tracking_id=f"CLU-1-260110-{next(_TRACKING_ID_COUNTER):07d}-EM",
        activity_name="Quarterly platform update",
        activity_description="Announcement of the quarterly platform release.",
        target_audience="All staff",
        audience="All staff",
        business_division="Division One",
        region="Global",
        channel="Email",
        priority="High",
        strategic_objectives="Objective A",
        lead="a.person",
        lead_team="Team One",
        time_zone="UTC",
        start_date=REFERENCE + timedelta(days=30),
        end_date=REFERENCE + timedelta(days=30, hours=2),
        source_created_at=REFERENCE,
        created_at=REFERENCE,
        updated_at=REFERENCE,
        is_archive=False,
        version=1,
    )
    base.update(overrides)
    return Activity(**base)


def _drop_everything(writable):
    """Views first, then the tables they depend on -- see drop_analysis_views."""
    drop_analysis_views(writable)
    Base.metadata.drop_all(writable)


@pytest.fixture(params=TEST_BACKENDS)
def engine(request, tmp_path):
    """A read-only engine over a seeded temporary database, per backend."""
    from pipeline.api.database import create_cplan_engine

    database_url = (
        TEST_DATABASE_URL
        if request.param == "postgresql"
        else f"sqlite:///{tmp_path / 'mcp.sqlite3'}"
    )

    writable = create_cplan_engine(database_url)
    _drop_everything(writable)
    Base.metadata.create_all(writable)
    with Session(writable) as session:
        session.add_all(
            [
                _activity(activity_name="Alpha townhall", channel="Email", priority="High"),
                _activity(
                    activity_name="Beta newsletter",
                    channel="email",  # same channel, different casing
                    priority="Medium",
                    start_date=REFERENCE + timedelta(days=60),
                    end_date=REFERENCE + timedelta(days=60, hours=1),
                ),
                _activity(
                    activity_name="Gamma external release",
                    source_type="external",
                    channel="Intranet",
                    # External rows do not require the internal-only trio.
                    target_audience=None,
                    audience=None,
                    business_division=None,
                ),
                _activity(
                    activity_name="Delta draft",
                    channel=None,
                    priority="None",  # the str(None) sentinel from the sync
                    lead_team="   ",
                    start_date=None,
                    end_date=None,
                ),
                _activity(
                    activity_name="Epsilon archived",
                    is_archive=True,
                    channel="Event",
                ),
            ]
        )
        session.add(
            SyncRun(
                ran_at=REFERENCE,
                snapshot_path="communications.parquet",
                created=2,
                updated=1,
                unchanged=3,
                conflicts=0,
                vanished=0,
                local_only=0,
                skipped_no_id=0,
            )
        )
        session.commit()

    read_only = create_read_only_engine(database_url)
    try:
        yield read_only
    finally:
        read_only.dispose()
        _drop_everything(writable)
        writable.dispose()


@pytest.fixture
def session(engine):
    with Session(engine) as active:
        yield active


@pytest.fixture(params=TEST_BACKENDS)
def writable_session(request, tmp_path):
    """A writable session over an EMPTY database, per backend.

    The `session` fixture is read-only over a fixed five-activity seed, which is
    right for tests that query the seed but cannot serve a test that needs its
    own rows. Parametrized identically, so a test built on this one still runs
    on both backends.

    Hazard: on PostgreSQL this fixture and `engine` resolve to the SAME database
    (`CPLAN_TEST_DATABASE_URL`), and each drops and recreates every table on
    setup and teardown -- so a test that takes both would have the other's seed
    dropped out from under it mid-run. Take one or the other, never both.
    """
    from pipeline.api.database import create_cplan_engine

    database_url = (
        TEST_DATABASE_URL
        if request.param == "postgresql"
        else f"sqlite:///{tmp_path / 'mcp-writable.sqlite3'}"
    )

    writable = create_cplan_engine(database_url)
    _drop_everything(writable)
    Base.metadata.create_all(writable)
    try:
        with Session(writable) as active:
            yield active
    finally:
        _drop_everything(writable)
        writable.dispose()


# --------------------------------------------------------------------------
# The completeness rule must not drift from the PostgreSQL view
# --------------------------------------------------------------------------


def test_required_fields_match_the_planning_completeness_view():
    """The rule now lives in three places; this pins two of them together.

    `analytics.js` is the studio's copy and `v_planning_completeness` is the
    pgAdmin copy. `queries.REQUIRED_*` is the MCP copy -- if a required field is
    added or dropped on either side without the other, this fails instead of
    the MCP quietly reporting a different completeness than the studio.
    """
    view_sql = ANALYSIS_VIEWS["v_planning_completeness"]
    flags_in_view = set(re.findall(r"\bAS (missing_[a-z_]+)", view_sql))

    expected = {
        queries.view_flag_name(field)
        for field in queries.REQUIRED_COMMON_FIELDS + queries.REQUIRED_INTERNAL_FIELDS
    }

    assert flags_in_view == expected


def test_internal_only_fields_are_not_required_for_external_activities():
    external = _activity(
        source_type="external", target_audience=None, audience=None, business_division=None
    )
    internal = _activity(
        source_type="internal", target_audience=None, audience=None, business_division=None
    )

    assert queries.missing_fields(external) == []
    assert queries.missing_fields(internal) == [
        "target_audience",
        "audience",
        "business_division",
    ]


@pytest.mark.parametrize("value", [None, "", "   ", "None", "null"])
def test_blank_sentinels_count_as_missing(value):
    assert queries.is_blank(value) is True
    assert "channel" in queries.missing_fields(_activity(channel=value))


def test_dates_are_missing_only_when_null():
    assert queries.missing_fields(_activity(start_date=None)) == ["start_date"]
    assert "start_date" not in queries.missing_fields(_activity())


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
    """The separator choice must follow the ETL, not a guess.

    Pins the column set AND the two separator literals: the column set alone
    would still pass if `parse_sp_lookup`'s default changed from ", " or
    `PERSON_JOIN` from "; ", which is exactly the change that would make
    `split_multi` split on the wrong character and invent or lose members.
    """
    etl = (REPO_ROOT / "pipeline" / "scripts" / "process_cplan.py").read_text()
    declared = re.search(r"SP_MULTI_PERSON_COLUMNS = \{([^}]*)\}", etl).group(1)
    person_columns = set(re.findall(r'"(\w+)"', declared))
    semicolon_only = {
        field
        for field, seps in queries.MULTI_VALUE_SEPARATORS.items()
        if seps == (";",)
    }
    assert person_columns == semicolon_only

    person_join = re.search(r'PERSON_JOIN = "(.*?)"', etl).group(1)
    lookup_join = re.search(r'def parse_sp_lookup\(val, separator="(.*?)"\)', etl).group(1)
    assert person_join.strip() == ";"
    assert lookup_join.strip() == ","
    # Every person column splits on the ETL's person separator, and the lookup
    # columns accept the ETL's lookup separator.
    for field in person_columns:
        assert queries.MULTI_VALUE_SEPARATORS[field] == (person_join.strip(),)
    for field in set(queries.MULTI_VALUE_SEPARATORS) - person_columns:
        assert lookup_join.strip() in queries.MULTI_VALUE_SEPARATORS[field]


# --------------------------------------------------------------------------
# Read-only engine
# --------------------------------------------------------------------------


def test_engine_refuses_writes(session):
    from sqlalchemy import text

    with pytest.raises(ReadOnlyViolation):
        session.execute(text("UPDATE activities SET priority = 'Low'"))


def test_engine_refuses_orm_flush(session):
    session.add(_activity(activity_name="Should never be written"))
    with pytest.raises(ReadOnlyViolation):
        session.flush()


@pytest.mark.parametrize(
    "statement",
    [
        "WITH doomed AS (SELECT id FROM activities) DELETE FROM activities",
        "PRAGMA writable_schema = ON",
        "with x as (select 1) update activities set priority = 'Low'",
    ],
)
def test_engine_refuses_a_write_hidden_behind_an_allowed_prefix(session, statement):
    """`with` and `pragma` start read-only statements -- but not only those.

    The allowlist matched on the prefix alone, so a CTE ending in DELETE and
    `PRAGMA writable_schema = ON` both passed the guard. PostgreSQL still refused
    them via default_transaction_read_only; on SQLite nothing did.
    """
    from sqlalchemy import text

    with pytest.raises(ReadOnlyViolation):
        session.execute(text(statement))


def test_engine_still_allows_a_read_only_cte(session):
    """The narrowing must not break a legitimate `WITH ... SELECT`."""
    from sqlalchemy import text

    rows = session.execute(
        text(
            "WITH counted AS (SELECT channel, COUNT(*) AS n FROM activities "
            "GROUP BY channel) SELECT channel, n FROM counted"
        )
    ).all()
    assert rows  # a real result, not a refusal


def test_engine_allows_reads(session):
    from sqlalchemy import func, select

    assert session.scalar(select(func.count()).select_from(Activity)) == 5


def test_postgres_connections_are_read_only_at_the_server(engine):
    """The `default_transaction_read_only` layer, not just the statement guard."""
    if engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL-only defence in depth")

    with engine.connect() as connection:
        assert connection.exec_driver_sql("SHOW default_transaction_read_only").scalar() == "on"
        # The statement guard would catch this first, so go around it via the
        # raw DBAPI cursor: this proves the server itself refuses the write.
        cursor = connection.connection.dbapi_connection.cursor()
        with pytest.raises(Exception) as failure:
            cursor.execute("UPDATE activities SET priority = 'Low'")
        assert "read-only" in str(failure.value).lower()


def test_planning_gaps_agrees_with_the_postgres_view(engine):
    """Behavioural equivalence with v_planning_completeness, not just field names.

    The name-level guard above catches a renamed flag; this catches a changed
    *rule* -- a different blank-string sentinel, a required field applied to the
    wrong variant, a NULL handled differently. Only possible where the view
    actually exists.
    """
    if engine.dialect.name != "postgresql":
        pytest.skip("v_planning_completeness exists on PostgreSQL only")
    from sqlalchemy import select, text

    from pipeline.api.database import create_cplan_engine
    from pipeline.api.views import ensure_analysis_views

    writable = create_cplan_engine(engine.url.render_as_string(hide_password=False))
    try:
        ensure_analysis_views(writable)
        with writable.connect() as connection:
            view_verdict = {
                row.id: row.is_complete
                for row in connection.execute(
                    text("SELECT id, is_complete FROM v_planning_completeness")
                )
            }
    finally:
        writable.dispose()

    with Session(engine) as session:
        python_verdict = {
            activity.id: not queries.missing_fields(activity)
            for activity in session.scalars(select(Activity))
        }

    assert view_verdict == python_verdict
    # Guard against a vacuous pass if the fixture ever loses its incomplete row.
    assert False in set(view_verdict.values())


def test_schema_check_passes_on_a_current_database(engine):
    from pipeline.mcp.engine import missing_model_columns, verify_schema

    assert missing_model_columns(engine) == {}
    verify_schema(engine)  # must not raise


def test_schema_check_names_the_missing_column_and_the_fix(tmp_path):
    """A read-only server cannot run ensure_schema, so drift must fail loudly.

    Reproduces the real case found on the live database: a column added by a
    later commit is absent because the API's startup top-up never ran there.
    """
    from sqlalchemy import text

    from pipeline.api.database import create_cplan_engine
    from pipeline.mcp.engine import SchemaOutOfDate, verify_schema

    database_url = f"sqlite:///{tmp_path / 'outdated.sqlite3'}"
    writable = create_cplan_engine(database_url)
    Base.metadata.create_all(writable)
    with writable.begin() as connection:
        connection.execute(text("ALTER TABLE activities DROP COLUMN other_executives"))
    writable.dispose()

    read_only = create_read_only_engine(database_url)
    try:
        with pytest.raises(SchemaOutOfDate) as failure:
            verify_schema(read_only)
    finally:
        read_only.dispose()

    message = str(failure.value)
    assert "other_executives" in message
    assert "ensure_db" in message


# --------------------------------------------------------------------------
# Query layer
# --------------------------------------------------------------------------


def test_activity_filters_defaults_to_no_narrowing(writable_session):
    """An empty filter object must behave exactly like the old all-None call.

    Uses `writable_session` rather than the `session` fixture: that fixture is
    wrapped by the read-only guard (see test_engine_refuses_orm_flush), so it
    cannot accept the add_all/flush this test needs.
    """
    writable_session.add_all([_activity(), _activity(is_archive=True)])
    writable_session.flush()

    unfiltered = queries.search_activities(writable_session)
    assert unfiltered["total_matches"] == 1  # archived still excluded by default

    with_archived = queries.search_activities(writable_session, include_archived=True)
    assert with_archived["total_matches"] == 2  # the only narrowing an empty filter does


def test_search_excludes_archived_by_default(session):
    result = queries.search_activities(session)

    names = [row["activity_name"] for row in result["activities"]]
    assert "Epsilon archived" not in names
    assert result["total_matches"] == 4
    assert result["truncated"] is False
    assert result["note"] is None


def test_search_can_include_archived(session):
    result = queries.search_activities(session, include_archived=True)

    assert result["total_matches"] == 5


def test_search_matches_text_case_insensitively(session):
    result = queries.search_activities(session, query="ALPHA")

    assert [row["activity_name"] for row in result["activities"]] == ["Alpha townhall"]


def test_search_filter_is_case_insensitive_on_free_text_columns(session):
    """A model guessing 'EMAIL' must still find rows stored as 'Email'/'email'."""
    result = queries.search_activities(session, channel="EMAIL")

    assert result["total_matches"] == 2


def test_search_filters_by_lead_team(writable_session):
    writable_session.add_all([
        _activity(activity_name="Team one item", lead_team="Team One"),
        _activity(activity_name="Team two item", lead_team="Team Two"),
    ])
    writable_session.flush()
    found = queries.search_activities(writable_session, lead_team="team one")
    assert found["total_matches"] == 1
    assert found["activities"][0]["activity_name"] == "Team one item"


def test_search_filters_by_region_and_division_together(writable_session):
    writable_session.add_all([
        _activity(activity_name="Match", region="Global", business_division="Division One"),
        _activity(activity_name="Wrong division", region="Global", business_division="Division Two"),
        _activity(activity_name="Wrong region", region="Local", business_division="Division One"),
    ])
    writable_session.flush()
    found = queries.search_activities(writable_session, region="global", business_division="Division One")
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
def test_search_filters_by_every_new_text_field(writable_session, field, value):
    writable_session.add_all([_activity(**{field: value}), _activity(**{field: "Something else"})])
    writable_session.flush()
    found = queries.search_activities(writable_session, **{field: value})
    assert found["total_matches"] == 1


def test_every_filterable_text_field_is_a_real_column():
    for name in queries.FILTERABLE_TEXT_FIELDS:
        assert hasattr(Activity, name), name


def test_search_filters_by_start_date_window(session):
    result = queries.search_activities(session, start_after="2026-03-01")

    assert [row["activity_name"] for row in result["activities"]] == ["Beta newsletter"]


def test_search_filters_by_end_date_window(writable_session):
    writable_session.add_all([
        _activity(activity_name="Ends soon", end_date=REFERENCE + timedelta(days=3)),
        _activity(activity_name="Ends late", end_date=REFERENCE + timedelta(days=90)),
    ])
    writable_session.flush()
    found = queries.search_activities(
        writable_session,
        end_after=REFERENCE.date().isoformat(),
        end_before=(REFERENCE + timedelta(days=14)).date().isoformat(),
    )
    assert [row["activity_name"] for row in found["activities"]] == ["Ends soon"]


def test_search_finds_activities_without_a_tracking_id(writable_session):
    writable_session.add_all([
        _activity(activity_name="Untracked", tracking_id=None),
        _activity(activity_name="Blank tracked", tracking_id="   "),
        _activity(activity_name="Tracked"),
    ])
    writable_session.flush()
    missing = queries.search_activities(writable_session, has_tracking_id=False)
    assert sorted(row["activity_name"] for row in missing["activities"]) == [
        "Blank tracked",
        "Untracked",
    ]
    present = queries.search_activities(writable_session, has_tracking_id=True)
    assert [row["activity_name"] for row in present["activities"]] == ["Tracked"]


def test_has_tracking_id_treats_the_sync_sentinel_as_missing(writable_session):
    """One spelling of "blank" in SQL, not two.

    `has_tracking_id` used to check only NULL and `trim() = ''`, so an activity
    whose tracking_id is the literal 'None' -- the exact sentinel the sync leaks
    in, and a value `is_blank` and `activity_counts` both treat as blank -- was
    reported as HAVING a tracking id.
    """
    writable_session.add_all([
        _activity(activity_name="Sentinel", tracking_id="None"),
        _activity(activity_name="Null sentinel", tracking_id="null"),
        _activity(activity_name="Real"),
    ])
    writable_session.flush()
    missing = queries.search_activities(writable_session, has_tracking_id=False)
    assert sorted(row["activity_name"] for row in missing["activities"]) == [
        "Null sentinel",
        "Sentinel",
    ]
    present = queries.search_activities(writable_session, has_tracking_id=True)
    assert [row["activity_name"] for row in present["activities"]] == ["Real"]


def test_search_finds_locally_modified_rows_but_not_never_synced_ones(writable_session):
    writable_session.add_all([
        _activity(activity_name="Diverged", version=3, synced_version=2),
        _activity(activity_name="In step", version=2, synced_version=2),
        _activity(activity_name="Never synced", version=4, synced_version=None),
    ])
    writable_session.flush()
    found = queries.search_activities(writable_session, locally_modified=True)
    assert [row["activity_name"] for row in found["activities"]] == ["Diverged"]


def test_locally_modified_false_keeps_never_synced_rows(writable_session):
    """The `~diverged` branch: never-synced is not divergence, so it is included.

    `synced_version IS NULL` makes the comparison three-valued, which is why the
    predicate guards it explicitly -- a plain `NOT (version > synced_version)`
    would drop every never-synced row here instead of keeping it.
    """
    writable_session.add_all([
        _activity(activity_name="Diverged", version=3, synced_version=2),
        _activity(activity_name="In step", version=2, synced_version=2),
        _activity(activity_name="Never synced", version=4, synced_version=None),
    ])
    writable_session.flush()
    found = queries.search_activities(writable_session, locally_modified=False)
    assert sorted(row["activity_name"] for row in found["activities"]) == [
        "In step",
        "Never synced",
    ]


def test_search_filters_by_news_digest_flag(writable_session):
    writable_session.add_all([
        _activity(activity_name="In digest", news_digest=True),
        _activity(activity_name="Not in digest", news_digest=False),
    ])
    writable_session.flush()
    found = queries.search_activities(writable_session, news_digest=True)
    assert [row["activity_name"] for row in found["activities"]] == ["In digest"]


def test_archived_only_returns_just_the_archived_rows(writable_session):
    writable_session.add_all([
        _activity(activity_name="Live"),
        _activity(activity_name="Archived", is_archive=True),
    ])
    writable_session.flush()
    found = queries.search_activities(writable_session, archived_only=True)
    assert [row["activity_name"] for row in found["activities"]] == ["Archived"]


def test_search_reports_its_own_truncation(session):
    result = queries.search_activities(session, limit=1)

    assert result["returned"] == 1
    assert result["total_matches"] == 4
    assert result["truncated"] is True
    assert "1 of 4" in result["note"]


def test_search_limit_is_hard_capped(session):
    result = queries.search_activities(session, limit=10_000)

    # The cap applies even when the caller asks for more; with 4 matching rows
    # the observable effect is that the call succeeds and stays bounded.
    assert result["returned"] <= queries.MAX_LIMIT


def test_search_summary_omits_long_free_text(session):
    result = queries.search_activities(session, limit=1)

    assert "activity_description" not in result["activities"][0]
    assert set(result["activities"][0]) == set(queries.SUMMARY_FIELDS) | {
        "priority_rank",
        "is_high_priority",
    }


def test_summaries_carry_the_derived_priority_rank(writable_session):
    writable_session.add(_activity(priority="2 - label"))
    writable_session.flush()
    row = queries.search_activities(writable_session)["activities"][0]
    assert row["priority_rank"] == 3
    assert row["is_high_priority"] is True


def test_get_activity_by_tracking_id_and_uuid(session):
    found = queries.search_activities(session, query="Alpha")["activities"][0]

    by_uuid = queries.get_activity(session, found["id"])
    by_tracking_id = queries.get_activity(session, found["tracking_id"])

    assert by_uuid["found"] is True
    assert by_tracking_id["activity"]["id"] == found["id"]


def test_get_activity_adds_derived_fields(session):
    found = queries.search_activities(session, query="Alpha")["activities"][0]

    record = queries.get_activity(session, found["id"])["activity"]

    assert record["planning_lead_days"] == 30
    assert record["tracking_pack_id"] == "CLU-1"
    assert record["is_complete"] is True
    assert record["missing_required_fields"] == []


def test_full_record_carries_the_derived_priority_rank(writable_session):
    activity = _activity(priority="4 - label")
    writable_session.add(activity)
    writable_session.flush()
    record = queries.get_activity(writable_session, str(activity.id))["activity"]
    assert record["priority_rank"] == 1
    assert record["is_high_priority"] is False


def test_get_activity_returns_the_api_read_model_verbatim(session):
    """The full record is the API's ActivityRead plus the completeness extras.

    Pinning this is what lets `queries.get_activity` inherit planning_lead_days
    and tracking_pack_id instead of reimplementing them: if the API read model
    gains or loses a field, the MCP must move with it.
    """
    from pipeline.api.app import ActivityRead

    found = queries.search_activities(session, query="Alpha")["activities"][0]
    record = queries.get_activity(session, found["id"])["activity"]

    extras = {"missing_required_fields", "is_complete", "priority_rank", "is_high_priority"}
    assert set(record) - extras == set(ActivityRead.model_fields) | {
        "planning_lead_days",
        "tracking_pack_id",
    }


def test_get_activity_reports_a_clean_miss(session):
    result = queries.get_activity(session, "NOPE-1-000000-0000000-XX")

    assert result["found"] is False
    assert "search_activities" in result["note"]


def test_planning_gaps_finds_the_incomplete_row(session):
    result = queries.planning_gaps(session)

    assert result["incomplete"] == 1
    assert result["complete"] == 3
    gap = result["activities"][0]
    assert gap["activity_name"] == "Delta draft"
    assert set(gap["missing_required_fields"]) == {
        "channel",
        "priority",
        "start_date",
        "end_date",
        "lead_team",
    }
    assert result["missing_field_counts"]["channel"] == 1


def test_planning_gaps_orders_worst_first(session):
    result = queries.planning_gaps(session, include_archived=True)

    counts = [row["missing_count"] for row in result["activities"]]
    assert counts == sorted(counts, reverse=True)


def test_planning_gaps_can_be_narrowed_by_priority_rank(writable_session):
    writable_session.add_all([
        _activity(activity_name="Urgent gap", priority="1 - label", channel=None),
        _activity(activity_name="Routine gap", priority="4 - label", channel=None),
    ])
    writable_session.flush()
    gaps = queries.planning_gaps(writable_session, min_priority_rank=3)
    assert gaps["incomplete"] == 1
    assert gaps["activities"][0]["activity_name"] == "Urgent gap"


def test_planning_gaps_can_be_narrowed_by_lead_team(writable_session):
    writable_session.add_all([
        _activity(lead_team="Team One", channel=None),
        _activity(lead_team="Team Two", channel=None),
    ])
    writable_session.flush()
    gaps = queries.planning_gaps(writable_session, lead_team="Team One")
    assert gaps["checked"] == 1
    assert gaps["incomplete"] == 1


def test_planning_gaps_groups_completeness_by_lead_team(writable_session):
    writable_session.add_all([
        _activity(lead_team="Team One", channel=None),
        _activity(lead_team="Team One", channel=None),
        _activity(lead_team="Team Two"),
    ])
    writable_session.flush()
    gaps = queries.planning_gaps(writable_session, group_by="lead_team")
    groups = {group["value"]: group for group in gaps["groups"]}
    assert groups["Team One"]["incomplete"] == 2
    assert groups["Team One"]["complete"] == 0
    assert groups["Team Two"]["incomplete"] == 0
    assert groups["Team Two"]["complete"] == 1
    # Worst group first, so the answer leads with where the problem is.
    assert gaps["groups"][0]["value"] == "Team One"


def test_planning_gaps_rejects_an_unknown_grouping(writable_session):
    result = queries.planning_gaps(writable_session, group_by="nonsense")
    assert "error" in result
    assert "lead_team" in result["supported_dimensions"]


def test_activity_counts_by_channel_groups_unassigned(session):
    result = queries.activity_counts(session, dimension="channel")

    buckets = {row["value"]: row["count"] for row in result["buckets"]}
    assert buckets["Unassigned"] == 1
    # Stored casing is preserved -- grouping does not fold 'Email' and 'email'.
    assert buckets["Email"] == 1
    assert buckets["email"] == 1


def test_activity_counts_by_month(session):
    result = queries.activity_counts(session, dimension="month")

    buckets = {row["value"]: row["count"] for row in result["buckets"]}
    assert buckets["2026-02"] == 2
    assert buckets["2026-03"] == 1
    assert buckets["unscheduled"] == 1


def test_activity_counts_rejects_unknown_dimension(session):
    result = queries.activity_counts(session, dimension="colour")

    assert "error" in result
    assert "channel" in result["supported_dimensions"]


def test_field_values_lists_stored_values_and_blanks(session):
    result = queries.field_values(session, field="priority")

    values = {row["value"]: row["count"] for row in result["values"]}
    # Value discovery deliberately spans archived rows too, so a value that
    # only occurs on archived activities is still offered as a filter.
    assert values["High"] == 3
    assert values["Medium"] == 1
    # 'None' is a blank sentinel, not a value an agent should filter on.
    assert "None" not in values
    assert result["blank_count"] == 1


def test_field_values_reports_its_own_truncation(writable_session):
    """A truncated value list must say so, and must not lose the blanks.

    The stored-column branch used to apply the cap as a SQL LIMIT and only then
    filter blanks in Python: blank groups consumed limit slots, `blank_count`
    counted only the blank groups that survived the LIMIT (so it could report 0
    while blanks existed), and the answer carried no truncation flag at all --
    an agent then filtered on a name it never saw and reported "no activities"
    as fact.
    """
    writable_session.add_all(
        [_activity(lead=f"lead.{index:03d}") for index in range(6)]
        + [_activity(lead=None), _activity(lead="None")]
    )
    writable_session.flush()
    listed = queries.field_values(writable_session, field="lead", limit=2)

    assert listed["returned"] == 2
    assert listed["distinct_values"] == 6
    assert listed["truncated"] is True
    assert "6 distinct values" in listed["note"]
    # Both blank rows are counted even though neither survived the cap.
    assert listed["blank_count"] == 2
    assert all(not queries.is_blank(entry["value"]) for entry in listed["values"])


def test_field_values_reports_truncation_for_multi_value_columns_too(writable_session):
    writable_session.add_all([
        _activity(strategic_objectives="Objective A, Objective B, Objective C"),
        _activity(strategic_objectives=None),
    ])
    writable_session.flush()
    listed = queries.field_values(writable_session, field="strategic_objectives", limit=1)

    assert listed["returned"] == 1
    assert listed["distinct_values"] == 3
    assert listed["truncated"] is True
    assert listed["note"] is not None
    assert listed["blank_count"] == 1


def test_field_values_answers_have_the_same_shape_on_both_branches(session):
    """The multi-value and stored-column branches must not report differently."""
    stored = queries.field_values(session, field="priority")
    multi = queries.field_values(session, field="strategic_objectives")

    assert set(stored) == set(multi)
    assert stored["truncated"] is False
    assert stored["note"] is None
    assert stored["returned"] == len(stored["values"]) == stored["distinct_values"]


def test_field_values_rejects_unknown_field(session):
    result = queries.field_values(session, field="secret")

    assert "error" in result
    assert "channel" in result["supported_fields"]


def test_the_pack_id_resolves_packs_that_the_campaign_label_collapses(writable_session):
    """The reason `communication_pack_cpid` is exposed at all.

    Both columns answer "which campaign is this part of", at different
    granularities. Measured against the 400-row portfolio the studio's
    campaignScorecards comment cites, the pack id resolved 32 packs of 2-11
    activities while `campaign` collapsed the same rows into 4 buckets of ~60.
    Reproduced in miniature here: one campaign label over three packs. Grouping
    by the label cannot see the packs, so anything built on it -- pack size,
    channel breadth, readiness -- describes the label instead of a planning unit.
    """
    for pack in ("CP-1", "CP-2", "CP-3"):
        writable_session.add_all(
            [_activity(campaign="Autumn programme", communication_pack_cpid=pack) for _ in range(2)]
        )
    writable_session.flush()

    by_label = queries.activity_counts(writable_session, dimension="campaign")
    by_pack = queries.activity_counts(writable_session, dimension="communication_pack_cpid")

    assert by_label["buckets"] == [{"value": "Autumn programme", "count": 6}]
    assert {bucket["value"]: bucket["count"] for bucket in by_pack["buckets"]} == {
        "CP-1": 2,
        "CP-2": 2,
        "CP-3": 2,
    }


def test_search_and_gaps_can_scope_to_one_pack(writable_session):
    writable_session.add_all([
        _activity(activity_name="In the pack", communication_pack_cpid="CP-1", channel=None),
        _activity(activity_name="Other pack", communication_pack_cpid="CP-2"),
    ])
    writable_session.flush()

    found = queries.search_activities(writable_session, communication_pack_cpid="CP-1")
    assert [row["activity_name"] for row in found["activities"]] == ["In the pack"]

    # Q28: how ready is this one pack, activity by activity.
    gaps = queries.planning_gaps(writable_session, communication_pack_cpid="CP-1")
    assert gaps["checked"] == 1
    assert gaps["incomplete"] == 1
    assert "channel" in gaps["activities"][0]["missing_required_fields"]


def test_pack_overview_prefers_the_pack_id_over_the_campaign_label(writable_session):
    """The reason this tool exists.

    One campaign label, three real packs underneath it. A tool that grouped
    by `campaign` would report one bucket of six; grouping by the pack id
    (the preference chain's first link) must report three packs of two.
    """
    for pack in ("CP-1", "CP-2", "CP-3"):
        writable_session.add_all(
            [_activity(campaign="Autumn programme", communication_pack_cpid=pack) for _ in range(2)]
        )
    writable_session.flush()

    result = queries.pack_overview(writable_session)

    assert result["pack_count"] == 3
    assert {row["pack_id"] for row in result["packs"]} == {"CP-1", "CP-2", "CP-3"}
    for row in result["packs"]:
        assert row["key_source"] == "communication_pack_cpid"
        assert row["activities"] == 2
        # The label still surfaces the human-readable campaign name.
        assert row["label"] == "Autumn programme"


@pytest.mark.parametrize(
    "overrides, expected_key_source",
    [
        ({"communication_pack": "Comms Pack A"}, "communication_pack"),
        ({"campaign": "Campaign A"}, "campaign"),
        ({}, None),
    ],
)
def test_pack_overview_falls_back_down_the_key_chain(
    writable_session, overrides, expected_key_source
):
    writable_session.add(
        _activity(
            communication_pack_cpid=None,
            # No '-' at all, so ActivityRead.tracking_pack_id is also None --
            # every link above `expected_key_source` in the chain is blank.
            tracking_id="NOPACKPREFIX",
            **overrides,
        )
    )
    writable_session.flush()

    result = queries.pack_overview(writable_session)

    if expected_key_source is None:
        # Every key in the chain is blank -- excluded entirely, not folded
        # into a shared bucket: a standalone activity is not a pack of one.
        assert result["pack_count"] == 0
        assert result["packs"] == []
    else:
        assert result["pack_count"] == 1
        assert result["packs"][0]["key_source"] == expected_key_source


def test_pack_overview_label_picks_the_earliest_starting_row_when_campaigns_disagree(
    writable_session,
):
    """`label` is a deterministic rule of `pack_overview`'s own, not an
    accident of whatever order `_filtered_activities` happens to return rows
    in. Two rows in one pack disagree on `campaign`; the later-starting row
    is inserted FIRST, so a "first encountered" rule would pick the wrong
    one -- only "earliest start_date wins" gives the right answer here.
    """
    writable_session.add_all([
        _activity(
            communication_pack_cpid="CP-1",
            campaign="Later campaign name",
            start_date=REFERENCE + timedelta(days=60),
            end_date=REFERENCE + timedelta(days=60, hours=1),
        ),
        _activity(
            communication_pack_cpid="CP-1",
            campaign="Earliest campaign name",
            start_date=REFERENCE + timedelta(days=10),
            end_date=REFERENCE + timedelta(days=10, hours=1),
        ),
    ])
    writable_session.flush()

    result = queries.pack_overview(writable_session)

    assert result["packs"][0]["label"] == "Earliest campaign name"


def test_pack_overview_keeps_an_undated_pack_with_a_null_span(writable_session):
    """An all-undated pack must still appear -- with its real activity count,
    not zero, and a `None` span rather than a fabricated one -- instead of
    being silently dropped from the overview."""
    writable_session.add_all([
        _activity(communication_pack_cpid="CP-1", start_date=None, end_date=None),
        _activity(communication_pack_cpid="CP-1", start_date=None, end_date=None),
    ])
    writable_session.flush()

    result = queries.pack_overview(writable_session)

    assert result["pack_count"] == 1
    pack = result["packs"][0]
    assert pack["activities"] == 2
    assert pack["first_date"] is None
    assert pack["last_date"] is None
    assert pack["span_days"] is None


def test_pack_overview_counts_distinct_members_not_strings(writable_session):
    """Both `channels` and `audiences` split on the studio's rule, not `split_multi`.

    `channel` and `target_audience` are absent from `MULTI_VALUE_SEPARATORS`,
    so `split_multi` returns the whole string as one member for either of
    them. `pack_overview` ports `campaignScorecards`, which uses
    `normalizeMulti` for all three counts -- so both call sites must use
    `_normalize_multi`, and this asserts the audience one too: swapping it to
    `split_multi` would report 1 audience here and pass every other test.
    """
    writable_session.add(
        _activity(
            communication_pack_cpid="CP-1",
            channel="Email, Intranet",
            target_audience="All staff, Line managers",
        )
    )
    writable_session.flush()

    result = queries.pack_overview(writable_session)

    pack = result["packs"][0]
    assert pack["channels"] == 2
    assert set(pack["channel_names"]) == {"Email", "Intranet"}
    assert pack["audiences"] == 2


def test_pack_overview_splits_channels_for_the_counts_but_not_for_the_filter(
    writable_session,
):
    """The three answers one column gives, and the sentence that has to say so.

    `pack_overview` counts channel MEMBERS (`_normalize_multi`) but filters on
    the whole stored string (`_apply_filters`), while `detect_collisions`
    filters by member on both columns. Left undisclosed, an agent reading
    "`detect_collisions` and `pack_overview` DO split them into members" asks
    "which packs run on Email", gets zero packs on a portfolio where every
    pack does, and reports that absence as a fact about the plan.

    Behaviour first, then the prose: the resource is the only place the agent
    can learn this, so a rewording that drops the qualification has to fail
    here too.
    """
    writable_session.add_all([
        _activity(communication_pack_cpid="CP-1", channel="Email, Intranet"),
        _activity(communication_pack_cpid="CP-1", channel="Email, Intranet"),
        _activity(communication_pack_cpid="CP-1", channel="Email, Intranet"),
    ])
    writable_session.flush()

    unfiltered = queries.pack_overview(writable_session)
    filtered = queries.pack_overview(writable_session, channel="Email")
    collisions = queries.detect_collisions(writable_session, channel="Email")

    # Counting splits: one pack, two channels.
    assert unfiltered["pack_count"] == 1
    assert unfiltered["packs"][0]["channels"] == 2
    # Filtering does not: the same portfolio answers "no packs at all".
    assert filtered["pack_count"] == 0
    # detect_collisions' own filter DOES match a member, on the same rows.
    assert collisions["total"] > 0

    from pipeline.mcp.domain import domain_model

    trap = domain_model().split("## Trap 4")[1].split("## Trap 5")[0]
    # One bullet = its own '- ' line plus any indented continuation lines, up
    # to the next bullet or the next blank line. Splitting on '- ' alone lets
    # the final bullet swallow the rest of the section, which then satisfies
    # both assertions below no matter what the prose says.
    bullets = [
        " ".join(match.group(0).split())
        for match in re.finditer(r"(?m)^- .*(?:\n(?![-\s]*$|- ).*)*", trap)
    ]
    pack_bullet = next(bullet for bullet in bullets if "pack_overview" in bullet)
    collision_bullet = next(
        bullet for bullet in bullets if "detect_collisions" in bullet
    )
    assert pack_bullet != collision_bullet
    assert "whole string" in pack_bullet.lower()
    assert "member" in collision_bullet.lower()


def test_pack_overview_readiness_agrees_with_planning_gaps(writable_session):
    """The reason `incomplete` reuses `missing_fields` rather than its own rule."""
    writable_session.add_all([
        _activity(communication_pack_cpid="CP-1", channel=None),  # incomplete
        _activity(communication_pack_cpid="CP-1"),  # complete
        _activity(communication_pack_cpid="CP-2", lead_team=None),  # incomplete
    ])
    writable_session.flush()

    overview = queries.pack_overview(writable_session)
    gaps = queries.planning_gaps(writable_session)

    assert sum(row["incomplete"] for row in overview["packs"]) == gaps["incomplete"]


def test_pack_overview_orders_by_size_and_reports_truncation(writable_session):
    writable_session.add_all([
        _activity(communication_pack_cpid="CP-small"),
        *[_activity(communication_pack_cpid="CP-big") for _ in range(3)],
        *[_activity(communication_pack_cpid="CP-medium") for _ in range(2)],
    ])
    writable_session.flush()

    result = queries.pack_overview(writable_session, limit=2)

    assert result["pack_count"] == 3
    assert result["returned"] == 2
    assert result["truncated"] is True
    assert [row["pack_id"] for row in result["packs"]] == ["CP-big", "CP-medium"]
    assert "2 of 3" in result["note"]


def test_pack_key_chain_matches_the_studio_implementation():
    """Pinned against analytics.js so the preference order cannot drift.

    Same technique as test_priority_rank_matches_the_studio_implementation:
    read the chain straight out of `campaignScorecards` rather than
    re-deriving it independently.
    """
    studio = (REPO_ROOT / "pipeline" / "studio" / "analytics.js").read_text()
    match = re.search(r"const key = (row\.\w+(?:\s*\|\|\s*row\.\w+)*);", studio)
    assert match, "campaignScorecards' key chain not found in analytics.js"
    fields = re.findall(r"row\.(\w+)", match.group(1))
    assert fields == list(queries._PACK_KEY_FIELDS)


def test_the_pack_id_is_discoverable_before_it_is_filtered(writable_session):
    """An agent must be able to learn the pack ids, not guess them."""
    writable_session.add_all([
        _activity(communication_pack_cpid="CP-1"),
        _activity(communication_pack_cpid="CP-1"),
        _activity(communication_pack_cpid="CP-2"),
    ])
    writable_session.flush()

    listed = queries.field_values(writable_session, field="communication_pack_cpid")
    assert {entry["value"]: entry["count"] for entry in listed["values"]} == {"CP-1": 2, "CP-2": 1}


def test_counts_by_a_multi_value_dimension_tally_members_not_combinations(writable_session):
    writable_session.add_all([
        _activity(strategic_objectives="Objective A, Objective B"),
        _activity(strategic_objectives="Objective A"),
    ])
    writable_session.flush()
    counted = queries.activity_counts(writable_session, dimension="strategic_objectives")
    buckets = {bucket["value"]: bucket["count"] for bucket in counted["buckets"]}
    assert buckets == {"Objective A": 2, "Objective B": 1}
    # The total counts memberships, which can exceed the row count -- say so.
    assert counted["counts_memberships"] is True


def test_split_multi_drops_blank_members(writable_session):
    """A sentinel member must not become a value, a bucket or a group.

    "Objective A; None" used to yield ["Objective A", "None"], so the sentinel
    surfaced as a discoverable filter value in `field_values`, its own bucket in
    `activity_counts` and its own group in `planning_gaps`.
    """
    assert queries.split_multi("Objective A; None", "strategic_objectives") == ["Objective A"]
    assert queries.split_multi("null; Roe, Sam", "other_executives") == ["Roe, Sam"]

    writable_session.add(_activity(strategic_objectives="Objective A, None"))
    writable_session.flush()
    listed = queries.field_values(writable_session, field="strategic_objectives")
    counted = queries.activity_counts(writable_session, dimension="strategic_objectives")
    grouped = queries.planning_gaps(writable_session, group_by="strategic_objectives")
    assert [entry["value"] for entry in listed["values"]] == ["Objective A"]
    assert [bucket["value"] for bucket in counted["buckets"]] == ["Objective A"]
    assert [group["value"] for group in grouped["groups"]] == ["Objective A"]


def test_group_labels_agree_between_planning_gaps_and_activity_counts(writable_session):
    """One labelling rule for both Python grouping paths.

    `planning_gaps` routed through `split_multi` (which strips) while
    `activity_counts` used the raw value on one branch and `str(value)` on the
    other, so " Email " was a different bucket in the two tools for the same
    data. Also pins that a two-member activity counts toward BOTH groups.
    """
    writable_session.add_all([
        _activity(strategic_objectives="Objective A, Objective B", channel=" Email "),
        _activity(strategic_objectives="Objective A", channel="Email"),
    ])
    writable_session.flush()

    grouped = queries.planning_gaps(writable_session, group_by="strategic_objectives")
    counted = queries.activity_counts(writable_session, dimension="strategic_objectives")
    assert {group["value"]: group["checked"] for group in grouped["groups"]} == {
        "Objective A": 2,
        "Objective B": 1,
    }
    assert {bucket["value"]: bucket["count"] for bucket in counted["buckets"]} == {
        "Objective A": 2,
        "Objective B": 1,
    }

    # The stored-column path: the SQL label is trimmed, exactly like split_multi.
    gaps_by_channel = queries.planning_gaps(writable_session, group_by="channel")
    counts_by_channel = queries.activity_counts(writable_session, dimension="channel")
    assert [group["value"] for group in gaps_by_channel["groups"]] == ["Email"]
    assert counts_by_channel["buckets"] == [{"value": "Email", "count": 2}]


@pytest.mark.parametrize("extra", [{}, {"min_priority_rank": 0}])
def test_activity_counts_caps_its_buckets_and_says_so(writable_session, extra):
    """Grouping is capped like every other list answer, on both branches.

    `min_priority_rank=0` excludes nothing (it only forces the Python-grouped
    branch), so both branches are exercised over the same rows. `total` must stay
    the TRUE total across all buckets, not the sum of the ones shown.
    """
    surplus = 5
    writable_session.add_all([
        _activity(campaign=f"Campaign {index:04d}")
        for index in range(queries.MAX_LIMIT + surplus)
    ])
    writable_session.flush()
    counted = queries.activity_counts(writable_session, dimension="campaign", **extra)

    assert len(counted["buckets"]) == queries.MAX_LIMIT
    assert counted["bucket_count"] == queries.MAX_LIMIT + surplus
    assert counted["truncated"] is True
    assert counted["total"] == queries.MAX_LIMIT + surplus
    assert "campaign buckets" in counted["note"]


@pytest.mark.parametrize("truncating", [True, False])
def test_every_capped_answer_reports_the_same_truncation_invariant(
    writable_session, truncating
):
    """One invariant, checked across every tool that returns a capped list.

    `truncated` is exactly `returned < total`, `note` exists exactly when
    truncated, and `returned` is exactly the length of the list it describes --
    for every tool, under both a truncating and a non-truncating limit. The
    invariant was hand-rolled in seven places, each naming its total
    differently, which is how one of them (`plan_changes_since`'s per-group
    `changes`) came to break it unnoticed; `_capped_list` is what makes it one
    rule, and this is what keeps it one rule.
    """
    activities = [
        _activity(
            activity_name=f"Row {index}",
            communication_pack_cpid=f"CP-{index}",
            campaign=f"Campaign {index}",
            channel="Email",
            target_audience="Staff",
            start_date=REFERENCE,
            end_date=REFERENCE,
            lead_team=None,  # incomplete, so planning_gaps has rows to cap
        )
        for index in range(4)
    ]
    writable_session.add_all(activities)
    writable_session.flush()
    writable_session.add_all([
        ActivityChange(
            activity_id=activity.id,
            actor="sync",
            change_type="created",
            changed_at=REFERENCE + timedelta(minutes=index),
            version_to=1,
        )
        for index, activity in enumerate(activities)
    ])
    writable_session.flush()

    limit = 2 if truncating else queries.MAX_LIMIT
    answers = [
        (queries.search_activities(writable_session, limit=limit), "total_matches", "activities", ""),
        (queries.planning_gaps(writable_session, limit=limit), "incomplete", "activities", ""),
        (
            queries.planning_gaps(writable_session, group_by="campaign", limit=limit),
            "group_count",
            "groups",
            "groups",
        ),
        (
            queries.detect_collisions(writable_session, limit=limit),
            "total",
            "collisions",
            "",
        ),
        (queries.pack_overview(writable_session, limit=limit), "pack_count", "packs", ""),
        (
            queries.activity_history(writable_session, activities[0].tracking_id, limit=limit),
            "total",
            "changes",
            "",
        ),
        (
            queries.plan_changes_since(writable_session, since="2026-01-01", limit=limit),
            "activity_count",
            "activities",
            "",
        ),
        (queries.activity_counts(writable_session, dimension="campaign"), "bucket_count", "buckets", ""),
    ]

    for answer, total_key, list_key, prefix in answers:
        def key(name: str) -> str:
            return f"{prefix}_{name}" if prefix else name

        label = f"{total_key}/{list_key}"
        assert answer[key("returned")] == len(answer[list_key]), label
        assert answer[key("truncated")] is (
            answer[key("returned")] < answer[total_key]
        ), label
        assert (answer[key("note")] is not None) is answer[key("truncated")], label


def test_activity_counts_reports_no_truncation_when_it_fits(session):
    counted = queries.activity_counts(session, dimension="channel")

    assert counted["truncated"] is False
    assert counted["note"] is None
    assert counted["bucket_count"] == len(counted["buckets"])


def test_planning_gaps_caps_its_groups_and_says_so(writable_session):
    surplus = 5
    writable_session.add_all([
        _activity(campaign=f"Campaign {index:04d}", channel=None)
        for index in range(queries.MAX_LIMIT + surplus)
    ])
    writable_session.flush()
    gaps = queries.planning_gaps(writable_session, group_by="campaign")

    assert len(gaps["groups"]) == queries.MAX_LIMIT
    assert gaps["group_count"] == queries.MAX_LIMIT + surplus
    assert gaps["groups_truncated"] is True
    assert "campaign groups" in gaps["groups_note"]
    # The activity list keeps its own, separate truncation report.
    assert gaps["incomplete"] == queries.MAX_LIMIT + surplus
    assert gaps["truncated"] is True


def test_planning_gaps_reports_no_group_truncation_when_it_fits(writable_session):
    writable_session.add_all([_activity(lead_team="Team One", channel=None)])
    writable_session.flush()
    gaps = queries.planning_gaps(writable_session, group_by="lead_team")

    assert gaps["group_count"] == 1
    assert gaps["groups_returned"] == 1
    assert gaps["groups_truncated"] is False
    # Present and null, not absent: every capped list here reports the same
    # four keys through `_capped_list`, so an untruncated answer says so
    # explicitly rather than by the absence of a key nobody thinks to check.
    assert gaps["groups_note"] is None


def test_counts_by_priority_rank_collapses_both_vocabularies(writable_session):
    writable_session.add_all([
        _activity(priority="1 - label"),
        _activity(priority="Critical"),
        _activity(priority="4 - label"),
    ])
    writable_session.flush()
    counted = queries.activity_counts(writable_session, dimension="priority_rank")
    buckets = {bucket["value"]: bucket["count"] for bucket in counted["buckets"]}
    assert buckets == {"4": 2, "1": 1}


def test_counts_accept_the_same_filters_as_search(writable_session):
    writable_session.add_all([
        _activity(region="Global", channel="Email"),
        _activity(region="Local", channel="Email"),
    ])
    writable_session.flush()
    counted = queries.activity_counts(writable_session, dimension="channel", region="Global")
    assert counted["buckets"] == [{"value": "Email", "count": 1}]


def test_build_filters_rejects_an_unexpected_keyword(writable_session):
    """A typo'd filter name must raise, not return a confidently wrong tally.

    Before this fix, `_build_filters` only ever `pop`ped names it knew and
    never inspected what was left over, so a typo (`regoin=`) or a keyword it
    genuinely doesn't support (`executive=`) silently produced a complete,
    plausible, *unfiltered* result with no error at all.
    """
    writable_session.add_all([_activity(region="Global"), _activity(region="Local")])
    writable_session.flush()
    with pytest.raises(TypeError, match="regoin"):
        queries.activity_counts(writable_session, dimension="channel", regoin="Global")


def test_counts_python_branch_matches_sql_branch_for_a_stored_dimension(writable_session):
    """Pins the fix for divergent blank-bucket labelling across branches.

    Every activity here is priority='Critical' (rank 4), so
    `min_priority_rank=3` excludes nothing -- it only forces `activity_counts`
    through its Python-grouped branch (any post-filter does) instead of the
    plain SQL `GROUP BY` branch, for the exact same counted rows. Before the
    fix, the SQL branch's `coalesce(column, "Unassigned")` caught only NULL,
    so the whitespace-only and 'None'/'null' sentinel rows surfaced as their
    own literal buckets there while the Python branch (using `is_blank`)
    folded all of them into "Unassigned" -- so the bucket name an agent saw
    depended on whether an unrelated filter was active, not on the data.
    """
    writable_session.add_all([
        _activity(channel="Email", priority="Critical"),
        _activity(channel=None, priority="Critical"),
        _activity(channel="   ", priority="Critical"),
        _activity(channel="None", priority="Critical"),
        _activity(channel="null", priority="Critical"),
    ])
    writable_session.flush()
    via_python = queries.activity_counts(writable_session, dimension="channel", min_priority_rank=3)
    via_sql = queries.activity_counts(writable_session, dimension="channel")
    assert via_python["buckets"] == via_sql["buckets"]
    assert {bucket["value"] for bucket in via_sql["buckets"]} == {"Email", "Unassigned"}


# --------------------------------------------------------------------------
# Cross-tabulation and finer time buckets
# --------------------------------------------------------------------------


def test_counts_cross_tabulates_two_dimensions(writable_session):
    writable_session.add_all([
        _activity(channel="Email", source_type="internal"),
        _activity(channel="Email", source_type="external"),
        _activity(channel="Intranet", source_type="internal"),
    ])
    writable_session.flush()

    result = queries.activity_counts(
        writable_session, dimension="channel", second_dimension="source_type"
    )

    assert result["dimension"] == "channel"
    assert result["second_dimension"] == "source_type"
    cells = {
        (bucket["value"], bucket["second_value"]): bucket["count"] for bucket in result["buckets"]
    }
    assert cells == {
        ("Email", "internal"): 1,
        ("Email", "external"): 1,
        ("Intranet", "internal"): 1,
    }
    assert result["total"] == 3
    assert result["axis_truncated"] == {"dimension": False, "second_dimension": False}
    assert result["distinct_values"] == {"dimension": 2, "second_dimension": 2}
    assert result["truncated"] is False


def test_counts_without_second_dimension_keeps_the_flat_shape(session):
    """The one-dimensional contract is unchanged: no `second_value` anywhere.

    Existing callers and a live eval depend on this exact shape -- adding
    `second_dimension` must be additive-only.
    """
    result = queries.activity_counts(session, dimension="channel")

    assert "second_dimension" not in result
    assert "axis_truncated" not in result
    assert "distinct_values" not in result
    assert all("second_value" not in bucket for bucket in result["buckets"])
    assert set(result) == {
        "dimension",
        "total",
        "counts_memberships",
        # `bucket_count` / `returned` / `truncated` / `note` are the four keys
        # `_capped_list` reports for every capped list in this module; the
        # bucket list is capped like any other, so it reports them like any
        # other. `total` stays the activity (or membership) total across ALL
        # buckets, which is a different number from `bucket_count`.
        "bucket_count",
        "returned",
        "truncated",
        "note",
        "buckets",
    }
    assert result["returned"] == len(result["buckets"])


def test_counts_by_week_buckets_iso_weeks(writable_session):
    # 2026-02-02 (Mon) and 2026-02-05 (Thu) fall in the same ISO week
    # (2026-W06); 2026-02-09 (Mon) is the next one (2026-W07).
    writable_session.add_all([
        _activity(start_date=datetime(2026, 2, 2, tzinfo=timezone.utc)),
        _activity(start_date=datetime(2026, 2, 5, tzinfo=timezone.utc)),
        _activity(start_date=datetime(2026, 2, 9, tzinfo=timezone.utc)),
    ])
    writable_session.flush()

    result = queries.activity_counts(writable_session, dimension="week")
    buckets = {bucket["value"]: bucket["count"] for bucket in result["buckets"]}
    assert buckets == {"2026-W06": 2, "2026-W07": 1}


def test_counts_by_day_buckets_dates(writable_session):
    writable_session.add_all([
        _activity(start_date=datetime(2026, 2, 2, 9, tzinfo=timezone.utc)),
        _activity(start_date=datetime(2026, 2, 2, 18, tzinfo=timezone.utc)),
        _activity(start_date=datetime(2026, 2, 3, 9, tzinfo=timezone.utc)),
    ])
    writable_session.flush()

    result = queries.activity_counts(writable_session, dimension="day")
    buckets = {bucket["value"]: bucket["count"] for bucket in result["buckets"]}
    assert buckets == {"2026-02-02": 2, "2026-02-03": 1}


@pytest.mark.parametrize("bucket", queries.TIME_BUCKETS)
def test_unscheduled_rows_bucket_together_on_every_time_grain(writable_session, bucket):
    writable_session.add(_activity(start_date=None))
    writable_session.flush()

    result = queries.activity_counts(writable_session, dimension=bucket)
    assert result["buckets"] == [{"value": "unscheduled", "count": 1}]


def test_cross_tab_caps_each_axis_and_says_so(writable_session):
    """The test that would catch a flat cap.

    More than MAX_CROSS_AXIS distinct channels, each paired with the same
    single source_type. A flat MAX_LIMIT-style cap over the (channel,
    source_type) cells would keep whatever the sort happened to keep and would
    never report which axis, if any, was cut -- this asserts the per-axis
    shape directly: each axis is capped independently, capped, and says so.
    """
    surplus = 5
    writable_session.add_all([
        _activity(channel=f"Channel {index:03d}", source_type="internal")
        for index in range(queries.MAX_CROSS_AXIS + surplus)
    ])
    writable_session.flush()

    result = queries.activity_counts(
        writable_session, dimension="channel", second_dimension="source_type"
    )

    channel_values = {bucket["value"] for bucket in result["buckets"]}
    assert len(channel_values) <= queries.MAX_CROSS_AXIS
    assert result["axis_truncated"]["dimension"] is True
    assert result["axis_truncated"]["second_dimension"] is False
    assert result["distinct_values"]["dimension"] == queries.MAX_CROSS_AXIS + surplus
    assert result["distinct_values"]["second_dimension"] == 1
    assert result["truncated"] is True
    # The true total spans every row, not just the rows behind the kept axis.
    assert result["total"] == queries.MAX_CROSS_AXIS + surplus


def test_counts_rejects_an_unknown_second_dimension(session):
    result = queries.activity_counts(session, dimension="channel", second_dimension="colour")

    assert "error" in result
    assert "channel" in result["supported_dimensions"]


def test_cross_tab_can_truncate_both_axes_at_once(writable_session):
    """Both axes can be truncated in the same answer, independently.

    The other cap test only ever drives `axis_truncated["dimension"]`, with
    the second axis pinned to a single value -- this drives both past
    MAX_CROSS_AXIS at once and checks both flags and both distinct_values.
    """
    surplus = 3
    rows = queries.MAX_CROSS_AXIS + surplus
    writable_session.add_all([
        _activity(channel=f"Channel {index:03d}", region=f"Region {index:03d}")
        for index in range(rows)
    ])
    writable_session.flush()

    result = queries.activity_counts(writable_session, dimension="channel", second_dimension="region")

    assert result["axis_truncated"] == {"dimension": True, "second_dimension": True}
    assert result["distinct_values"] == {"dimension": rows, "second_dimension": rows}
    assert len({bucket["value"] for bucket in result["buckets"]}) <= queries.MAX_CROSS_AXIS
    assert len({bucket["second_value"] for bucket in result["buckets"]}) <= queries.MAX_CROSS_AXIS
    assert result["truncated"] is True
    assert result["total"] == rows


def test_cross_tab_python_branch_matches_sql_branch_for_two_stored_dimensions(writable_session):
    """The Python cross-tab branch must agree with the SQL one on the same data.

    `min_priority_rank=3` excludes nothing here (every row is 'Critical', rank
    4) -- it only forces `activity_counts` through the Python nested-loop
    branch instead of the two-column SQL `GROUP BY`, for channel x
    source_type, both of which are plain stored scalars. Same pattern as
    `test_counts_python_branch_matches_sql_branch_for_a_stored_dimension`, one
    dimension over.
    """
    writable_session.add_all([
        _activity(channel="Email", source_type="internal", priority="Critical"),
        _activity(channel="Email", source_type="external", priority="Critical"),
        _activity(channel="Intranet", source_type="internal", priority="Critical"),
    ])
    writable_session.flush()

    via_python = queries.activity_counts(
        writable_session, dimension="channel", second_dimension="source_type", min_priority_rank=3
    )
    via_sql = queries.activity_counts(
        writable_session, dimension="channel", second_dimension="source_type"
    )

    assert via_python["buckets"] == via_sql["buckets"]
    assert via_python["total"] == via_sql["total"] == 3


def test_cross_tab_buckets_a_derived_time_axis(writable_session):
    """The Python branch also has to run when either axis is derived.

    `month` has no stored column, so `channel x month` can never take the SQL
    `GROUP BY` path -- this is the case the brief's own headline example
    ("channel by month") actually exercises.
    """
    writable_session.add_all([
        _activity(channel="Email", start_date=datetime(2026, 2, 1, tzinfo=timezone.utc)),
        _activity(channel="Email", start_date=datetime(2026, 3, 1, tzinfo=timezone.utc)),
        _activity(channel="Intranet", start_date=datetime(2026, 2, 15, tzinfo=timezone.utc)),
    ])
    writable_session.flush()

    result = queries.activity_counts(writable_session, dimension="channel", second_dimension="month")

    cells = {
        (bucket["value"], bucket["second_value"]): bucket["count"] for bucket in result["buckets"]
    }
    assert cells == {
        ("Email", "2026-02"): 1,
        ("Email", "2026-03"): 1,
        ("Intranet", "2026-02"): 1,
    }
    assert result["counts_memberships"] is False
    # A cross-tab reports its axis cardinalities, not a flat `bucket_count`.
    assert "bucket_count" not in result
    assert result["distinct_values"] == {"dimension": 2, "second_dimension": 2}


def test_cross_tab_orders_a_time_axis_chronologically(writable_session):
    """A `month` axis reads in time order on either side, as it does in 1-D.

    Sorted largest-bucket-first, a `month x channel` table is a timeline
    shuffled by volume -- unreadable as the trend it is meant to show, and
    inconsistent with the single-dimension path, which already orders a time
    dimension chronologically. The cap stays by count; only the order changes.
    """
    writable_session.add_all([
        # March is the busiest month, January the quietest -- so a count-first
        # order would put March first and January last.
        _activity(channel="Email", start_date=datetime(2026, 1, 5, tzinfo=timezone.utc)),
        *[
            _activity(channel="Email", start_date=datetime(2026, 2, 5, tzinfo=timezone.utc))
            for _ in range(2)
        ],
        *[
            _activity(channel="Email", start_date=datetime(2026, 3, 5, tzinfo=timezone.utc))
            for _ in range(3)
        ],
    ])
    writable_session.flush()

    leading = queries.activity_counts(
        writable_session, dimension="month", second_dimension="channel"
    )
    trailing = queries.activity_counts(
        writable_session, dimension="channel", second_dimension="month"
    )
    flat = queries.activity_counts(writable_session, dimension="month")

    months = ["2026-01", "2026-02", "2026-03"]
    assert [bucket["value"] for bucket in leading["buckets"]] == months
    assert [bucket["second_value"] for bucket in trailing["buckets"]] == months
    # The same order the single-dimension path has always produced.
    assert [bucket["value"] for bucket in flat["buckets"]] == months


def test_cross_tab_caps_a_time_axis_as_a_contiguous_recent_window(writable_session):
    """A capped time axis must be a window, not a volume-ranked sample.

    36 months alternating 10 activities and 1. Capped by count -- the rule
    every categorical axis uses -- the 20 survivors are all 18 busy months
    plus 2 quiet ones, and printing them in date order yields
    `2026-01, 2026-02, 2026-03, 2026-05, 2026-07, ...`: sixteen months missing
    from the MIDDLE of something that reads as a timeline, with nothing in the
    response naming them. The 1-D path caps at MAX_LIMIT chronologically and
    never produced this shape; the cross-tab's tighter MAX_CROSS_AXIS made it
    reachable on any real portfolio.

    So a TIME_BUCKETS axis is capped as a contiguous window of the most recent
    MAX_CROSS_AXIS buckets instead. Asserted as consecutive months ending at
    the latest, which is the one property a count-ranked cap can never have.
    """
    months = 36
    for index in range(months):
        year = 2026 + index // 12
        month = index % 12 + 1
        start = datetime(year, month, 5, tzinfo=timezone.utc)
        writable_session.add_all([
            _activity(channel="Email", start_date=start)
            # Alternating volumes: a count-ranked cap keeps the busy months.
            for _ in range(10 if index % 2 == 0 else 1)
        ])
    writable_session.flush()

    result = queries.activity_counts(
        writable_session, dimension="month", second_dimension="channel"
    )

    kept = [bucket["value"] for bucket in result["buckets"]]
    assert len(kept) == queries.MAX_CROSS_AXIS
    expected = [
        f"{2026 + index // 12:04d}-{index % 12 + 1:02d}"
        for index in range(months - queries.MAX_CROSS_AXIS, months)
    ]
    assert kept == expected
    # Consecutive by construction above; asserted directly so a future
    # reordering cannot satisfy the list comparison by accident.
    assert kept == sorted(kept)
    assert result["axis_truncated"] == {"dimension": True, "second_dimension": False}
    assert result["distinct_values"]["dimension"] == months
    assert result["truncated"] is True
    # The cut months still count towards the total, as on every other axis.
    assert result["total"] == 18 * 10 + 18 * 1
    # The note has to name the SHAPE, not just the fact of a cap: "top 20 by
    # count" would be a lie about this axis.
    note = " ".join(result["note"].split())
    assert "most recent" in note
    assert "contiguous" in note


def test_cross_tab_note_names_the_shape_each_cut_axis_got(writable_session):
    """A categorical axis is still capped by count, and says so separately.

    The time-axis fix must not turn every axis into a window: a channel axis
    keeps its busiest values, and the note has to distinguish the two shapes
    when both axes are cut in the same answer -- they hide different data
    (rarest values on one, everything before the window on the other).
    """
    surplus = 3
    for index in range(queries.MAX_CROSS_AXIS + surplus):
        writable_session.add_all([
            _activity(
                channel=f"Channel {index:03d}",
                start_date=datetime(2026, 1, 1, tzinfo=timezone.utc)
                + timedelta(days=index),
            )
            for _ in range(index + 1)
        ])
    writable_session.flush()

    result = queries.activity_counts(
        writable_session, dimension="channel", second_dimension="day"
    )

    note = " ".join(result["note"].split())
    assert result["axis_truncated"] == {"dimension": True, "second_dimension": True}
    assert f"channel: the top {queries.MAX_CROSS_AXIS}" in note
    assert "by total count" in note
    assert f"day: the {queries.MAX_CROSS_AXIS} most recent" in note
    # The categorical axis keeps the busiest channels, which here are the last
    # ones created -- proof it was NOT switched to a chronological window.
    kept_channels = {bucket["value"] for bucket in result["buckets"]}
    assert "Channel 000" not in kept_channels
    assert f"Channel {queries.MAX_CROSS_AXIS + surplus - 1:03d}" in kept_channels


def test_cross_tab_tallies_multi_value_members_on_the_first_axis(writable_session):
    writable_session.add_all([
        _activity(strategic_objectives="Objective A, Objective B", channel="Email"),
        _activity(strategic_objectives="Objective A", channel="Intranet"),
    ])
    writable_session.flush()

    result = queries.activity_counts(
        writable_session, dimension="strategic_objectives", second_dimension="channel"
    )

    cells = {
        (bucket["value"], bucket["second_value"]): bucket["count"] for bucket in result["buckets"]
    }
    assert cells == {
        ("Objective A", "Email"): 1,
        ("Objective B", "Email"): 1,
        ("Objective A", "Intranet"): 1,
    }
    assert result["counts_memberships"] is True


def test_cross_tab_tallies_multi_value_members_on_the_second_axis_only(writable_session):
    """The 'either axis' half of the rule that is easy to get backwards.

    Mirrors the previous test with the multi-value column moved to the SECOND
    axis and a plain stored scalar on the first -- `counts_memberships` must
    still be True.
    """
    writable_session.add_all([
        _activity(channel="Email", strategic_objectives="Objective A, Objective B"),
        _activity(channel="Intranet", strategic_objectives="Objective A"),
    ])
    writable_session.flush()

    result = queries.activity_counts(
        writable_session, dimension="channel", second_dimension="strategic_objectives"
    )

    cells = {
        (bucket["value"], bucket["second_value"]): bucket["count"] for bucket in result["buckets"]
    }
    assert cells == {
        ("Email", "Objective A"): 1,
        ("Email", "Objective B"): 1,
        ("Intranet", "Objective A"): 1,
    }
    assert result["counts_memberships"] is True


def test_cross_tab_tallies_multi_value_members_on_both_axes(writable_session):
    """Both axes multi-valued: one activity fans out into every combination.

    A single activity with two objectives and two board members contributes
    to all four (objective, board member) cells -- the cross product, not the
    pairwise zip -- so `total` across the cross-tab is 4 for one row.
    """
    writable_session.add(
        _activity(strategic_objectives="Objective A, Objective B", bod_geb="Exec X; Exec Y")
    )
    writable_session.flush()

    result = queries.activity_counts(
        writable_session, dimension="strategic_objectives", second_dimension="bod_geb"
    )

    cells = {
        (bucket["value"], bucket["second_value"]): bucket["count"] for bucket in result["buckets"]
    }
    assert cells == {
        ("Objective A", "Exec X"): 1,
        ("Objective A", "Exec Y"): 1,
        ("Objective B", "Exec X"): 1,
        ("Objective B", "Exec Y"): 1,
    }
    assert result["counts_memberships"] is True
    assert result["total"] == 4


def test_time_bucket_key_week_carries_the_iso_year_at_the_boundary():
    """29-31 Dec can fall in ISO week 1 of the FOLLOWING year -- pin it.

    2029-12-31 is a Monday whose ISO calendar places it in week 1 of 2030
    (`date(2029, 12, 31).isocalendar() == (2030, 1, 1)`). The key must carry
    the ISO year (2030), not the calendar year (2029) -- that mismatch is the
    classic off-by-one-year bug this pins against.
    """
    value = datetime(2029, 12, 31, tzinfo=timezone.utc)
    assert queries._time_bucket_key(value, "week") == "2030-W01"


# --------------------------------------------------------------------------
# Calendar load and window-over-window comparison
# --------------------------------------------------------------------------


def test_calendar_load_buckets_consecutive_weeks(writable_session):
    """Half-open [from, to): an activity exactly on a `to` boundary belongs
    to the NEXT week, not the one that just ended."""
    anchor = datetime(2026, 1, 5, tzinfo=timezone.utc)  # a Monday, midnight UTC
    writable_session.add_all([
        _activity(activity_name="On the anchor", start_date=anchor),
        _activity(activity_name="Mid first week", start_date=anchor + timedelta(days=3)),
        _activity(activity_name="On the boundary", start_date=anchor + timedelta(days=7)),
        _activity(activity_name="Mid second week", start_date=anchor + timedelta(days=10)),
    ])
    writable_session.flush()

    result = queries.calendar_load(writable_session, weeks=2, start_date="2026-01-05")

    assert result["anchor"] == "2026-01-05T00:00:00Z"
    assert result["anchor_source"] == "argument"
    assert result["buckets"] == [
        {"from": "2026-01-05T00:00:00Z", "to": "2026-01-12T00:00:00Z", "count": 2},
        {"from": "2026-01-12T00:00:00Z", "to": "2026-01-19T00:00:00Z", "count": 2},
    ]


def test_calendar_load_names_empty_weeks(writable_session):
    writable_session.add_all([
        _activity(start_date=datetime(2026, 1, 6, tzinfo=timezone.utc)),  # week 0
        _activity(start_date=datetime(2026, 1, 20, tzinfo=timezone.utc)),  # week 2
    ])
    writable_session.flush()

    result = queries.calendar_load(writable_session, weeks=3, start_date="2026-01-05")

    assert [bucket["count"] for bucket in result["buckets"]] == [1, 0, 1]
    gap = result["buckets"][1]
    assert gap["count"] == 0
    # A gap week appears in `buckets` with count 0 -- not omitted -- AND is
    # called out in `empty_weeks` so an agent does not have to scan for it.
    assert result["empty_weeks"] == [gap]


def test_calendar_load_resolves_its_anchor_deterministically(writable_session):
    # No SyncRun row and no explicit start_date: falls back to the latest
    # start_date among the FILTERED candidates. Called twice -- the same
    # input must yield the same anchor, which is what rules out `datetime.now()`.
    writable_session.add_all([
        _activity(start_date=datetime(2026, 3, 1, tzinfo=timezone.utc)),
        _activity(start_date=datetime(2026, 3, 15, tzinfo=timezone.utc)),
    ])
    writable_session.flush()

    first = queries.calendar_load(writable_session, weeks=1)
    second = queries.calendar_load(writable_session, weeks=1)
    assert first["anchor_source"] == "latest_start_date"
    assert first["anchor"] == second["anchor"] == "2026-03-15T00:00:00Z"

    # A SyncRun row outranks the latest-start_date fallback.
    writable_session.add(
        SyncRun(
            ran_at=datetime(2026, 4, 1, 9, tzinfo=timezone.utc),
            snapshot_path="communications.parquet",
            created=0,
            updated=0,
            unchanged=0,
            conflicts=0,
            vanished=0,
            local_only=0,
            skipped_no_id=0,
        )
    )
    writable_session.flush()
    with_sync = queries.calendar_load(writable_session, weeks=1)
    assert with_sync["anchor_source"] == "latest_sync"
    assert with_sync["anchor"] == "2026-04-01T00:00:00Z"

    # An explicit argument outranks everything else.
    explicit = queries.calendar_load(writable_session, weeks=1, start_date="2026-05-01")
    assert explicit["anchor_source"] == "argument"
    assert explicit["anchor"] == "2026-05-01T00:00:00Z"


def test_calendar_load_clamps_the_week_count(writable_session):
    writable_session.add(_activity(start_date=datetime(2026, 1, 5, tzinfo=timezone.utc)))
    writable_session.flush()

    too_few = queries.calendar_load(writable_session, weeks=0, start_date="2026-01-05")
    too_many = queries.calendar_load(writable_session, weeks=200, start_date="2026-01-05")

    assert too_few["weeks"] == 1
    assert len(too_few["buckets"]) == 1
    assert too_many["weeks"] == 52
    assert len(too_many["buckets"]) == 52


def test_window_comparison_clamps_the_day_count(writable_session):
    """`days` is clamped like `calendar_load`'s `weeks` -- and must be.

    `timedelta` raises OverflowError past roughly 2.7 million days, so an
    unclamped `days` turned an out-of-range argument into a crash out of a
    read-only query tool rather than an answer. The echoed `days` reports what
    was actually used, so the caller can see the clamp rather than guess at it.
    """
    writable_session.add(_activity(start_date=datetime(2026, 1, 5, tzinfo=timezone.utc)))
    writable_session.flush()

    too_few = queries.window_comparison(writable_session, days=0, reference="2026-01-05")
    too_many = queries.window_comparison(writable_session, days=3_000_000, reference="2026-01-05")

    assert too_few["days"] == 1
    assert too_many["days"] == queries.MAX_WINDOW_DAYS
    assert too_many["current"] is not None


def test_calendar_load_matches_the_studio_week_math():
    """Pinned against analytics.js so the week math cannot silently drift.

    Same technique as test_priority_rank_matches_the_studio_implementation:
    read the studio's own source for the 7-day step, the half-open comparison
    and the midnight truncation rather than re-deriving any of them
    independently.
    """
    studio = (REPO_ROOT / "pipeline" / "studio" / "analytics.js").read_text()
    match = re.search(r"function weeklyCoverage\([^)]*\)\s*\{(.*?)\n  \}", studio, re.DOTALL)
    assert match, "weeklyCoverage not found in analytics.js"
    body = match.group(1)
    assert "from.getDate() + i * 7" in body
    assert "to.getDate() + 7" in body
    assert "date >= from && date < to" in body
    # The truncation `_truncate_to_midnight` mirrors, and the whole reason
    # calendar_load and window_comparison disagree about their anchor:
    # `weeklyCoverage` floors the anchor to midnight, `comparisonWindow` uses
    # the raw instant. Drop this line on either side and the two tools quietly
    # agree again -- which is the bug, not the fix.
    assert "start.setHours(0, 0, 0, 0);" in body


def test_window_comparison_counts_both_windows_and_the_delta(writable_session):
    reference = datetime(2026, 2, 1, tzinfo=timezone.utc)
    writable_session.add_all([
        # Previous window [2026-01-02, 2026-02-01): 2 activities.
        _activity(start_date=reference - timedelta(days=20)),
        _activity(start_date=reference - timedelta(days=5)),
        # Current window [2026-02-01, 2026-03-03): 4 activities.
        _activity(start_date=reference + timedelta(days=1)),
        _activity(start_date=reference + timedelta(days=10)),
        _activity(start_date=reference + timedelta(days=20)),
        _activity(start_date=reference + timedelta(days=29)),
    ])
    writable_session.flush()

    result = queries.window_comparison(
        writable_session, days=30, reference="2026-02-01T00:00:00Z"
    )

    assert result["anchor_source"] == "argument"
    assert result["current"]["count"] == 4
    assert result["previous"]["count"] == 2
    assert result["change"] == 2
    assert result["change_pct"] == 100.0


def test_window_comparison_reports_no_percentage_when_the_previous_window_is_empty(
    writable_session,
):
    reference = datetime(2026, 2, 1, tzinfo=timezone.utc)
    writable_session.add(_activity(start_date=reference + timedelta(days=5)))
    writable_session.flush()

    result = queries.window_comparison(writable_session, days=30, reference=reference)

    assert result["previous"]["count"] == 0
    assert result["current"]["count"] == 1
    assert result["change"] == 1
    # Never inf, never 0 -- both would read as a real percentage.
    assert result["change_pct"] is None


def test_calendar_load_reports_no_anchor_rather_than_inventing_one(writable_session):
    """No SyncRun row and no dated activity: nothing in the data can anchor a
    calendar window. An earlier draft fell back to a fixed 1970-01-01 instant
    labelled `anchor_source: "latest_start_date"` -- a fabricated provenance,
    since there is no latest start date. The honest answer is `anchor: None`,
    `anchor_source: "none"`, and no invented date range.
    """
    writable_session.add(_activity(start_date=None))  # undated, so still no anchor
    writable_session.flush()

    result = queries.calendar_load(writable_session, weeks=8)

    assert result["anchor"] is None
    assert result["anchor_source"] == "none"
    assert result["buckets"] == []
    assert result["empty_weeks"] == []
    assert result["busiest"] is None
    assert result["quietest"] is None
    # No invented date ever shows up as if it were real.
    assert "1970" not in json.dumps(result)


def test_window_comparison_reports_no_anchor_rather_than_inventing_one(writable_session):
    """Same honesty requirement as calendar_load, for the comparison tool."""
    result = queries.window_comparison(writable_session, days=30)

    assert result["anchor"] is None
    assert result["anchor_source"] == "none"
    assert result["current"] is None
    assert result["previous"] is None
    assert result["change"] is None
    assert result["change_pct"] is None
    assert "1970" not in json.dumps(result)


def test_calendar_load_truncates_its_anchor_but_window_comparison_does_not(writable_session):
    """The two tools mirror two different studio functions, and the studio
    functions disagree on this: `weeklyCoverage` truncates its start to
    midnight (`setHours(0, 0, 0, 0)`), `comparisonWindow` uses the raw
    instant. Both query functions route through the same `_resolve_anchor`,
    so this asymmetry reads as a bug unless it is pinned explicitly -- a
    future edit that "fixes" one to match the other would silently break
    whichever studio parity it broke.
    """
    timestamped = "2026-01-05T15:30:00Z"

    calendar_result = queries.calendar_load(writable_session, weeks=1, start_date=timestamped)
    comparison_result = queries.window_comparison(writable_session, days=30, reference=timestamped)

    assert calendar_result["anchor"] == "2026-01-05T00:00:00Z"
    assert comparison_result["anchor"] == "2026-01-05T15:30:00Z"


@pytest.mark.parametrize(
    "field", ["partner_team", "business_area", "target_audience", "audience", "time_zone"]
)
def test_field_values_enumerates_every_new_filter_column(writable_session, field):
    writable_session.add_all([_activity(**{field: "Value One"}), _activity(**{field: "Value One"})])
    writable_session.flush()
    listed = queries.field_values(writable_session, field=field)
    assert listed["values"] == [{"value": "Value One", "count": 2}]


def test_field_values_splits_multi_value_columns(writable_session):
    writable_session.add(_activity(strategic_objectives="Objective A, Objective B"))
    writable_session.flush()
    listed = queries.field_values(writable_session, field="strategic_objectives")
    assert sorted(entry["value"] for entry in listed["values"]) == [
        "Objective A",
        "Objective B",
    ]


def test_every_filterable_column_is_also_discoverable():
    """An agent must never be able to filter on a column it cannot enumerate."""
    missing = set(queries.FILTERABLE_TEXT_FIELDS) - set(queries.ENUMERABLE_FIELDS)
    assert missing == set(), f"filterable but not enumerable: {sorted(missing)}"


def test_database_status_summarizes_the_plan(session, engine):
    status = queries.database_status(session, engine)

    assert status["backend"] == engine.dialect.name
    assert status["read_only"] is True
    assert status["activities"]["total"] == 5
    assert status["activities"]["archived"] == 1
    assert status["activities"]["by_source_type"] == {"internal": 4, "external": 1}
    assert status["latest_sync_run"]["created"] == 2


def test_query_results_are_json_serializable(session, engine):
    """Every tool return value crosses a JSON-RPC boundary."""
    payloads = [
        queries.search_activities(session),
        queries.get_activity(session, "missing"),
        queries.planning_gaps(session),
        queries.activity_counts(session, dimension="month"),
        queries.field_values(session, field="channel"),
        queries.database_status(session, engine),
        queries.calendar_load(session),
        queries.window_comparison(session),
        queries.detect_collisions(session),
    ]

    for payload in payloads:
        json.dumps(payload)


# --------------------------------------------------------------------------
# Priority rank, lead time, and exact multi-value filters
# --------------------------------------------------------------------------


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


def test_lead_days_matches_the_api_read_model(writable_session):
    activity = _activity(
        source_created_at=REFERENCE,
        start_date=REFERENCE + timedelta(days=12),
    )
    writable_session.add(activity)
    writable_session.flush()
    assert queries.lead_days(activity) == 12
    from pipeline.api.app import ActivityRead

    assert queries.lead_days(activity) == ActivityRead.model_validate(activity).planning_lead_days

    # source_created_at and created_at are the SAME instant above, so that case
    # cannot tell "source_created_at wins" apart from "created_at wins", from
    # reversed precedence, or from either operand hardcoded. Here they diverge,
    # so the documented precedence (source_created_at when set, else
    # created_at -- see ActivityRead.planning_lead_days) is actually exercised:
    # a created_at 100 days later would give a very different lead time if it
    # were read instead.
    diverging = _activity(
        source_created_at=REFERENCE,
        created_at=REFERENCE + timedelta(days=100),
        start_date=REFERENCE + timedelta(days=12),
    )
    writable_session.add(diverging)
    writable_session.flush()
    assert queries.lead_days(diverging) == 12  # counted from source_created_at, not created_at
    assert queries.lead_days(diverging) == ActivityRead.model_validate(diverging).planning_lead_days


def test_lead_days_is_none_without_a_start_date(writable_session):
    activity = _activity(start_date=None)
    writable_session.add(activity)
    writable_session.flush()
    assert queries.lead_days(activity) is None


def test_search_filters_by_short_lead_time(writable_session):
    writable_session.add_all([
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
    writable_session.flush()
    found = queries.search_activities(writable_session, max_lead_days=7)
    assert [row["activity_name"] for row in found["activities"]] == ["Short notice"]
    assert found["total_matches"] == 1


def test_search_filters_by_minimum_priority_rank_across_both_vocabularies(writable_session):
    writable_session.add_all([
        _activity(activity_name="Numbered urgent", priority="2 - label"),
        _activity(activity_name="Worded urgent", priority="Critical"),
        _activity(activity_name="Routine", priority="4 - label"),
    ])
    writable_session.flush()
    found = queries.search_activities(writable_session, min_priority_rank=3)
    assert sorted(row["activity_name"] for row in found["activities"]) == [
        "Numbered urgent",
        "Worded urgent",
    ]
    assert found["total_matches"] == 2


def test_search_matches_one_member_of_a_multi_value_column(writable_session):
    writable_session.add_all([
        _activity(activity_name="Two objectives", strategic_objectives="Objective A, Objective B"),
        _activity(activity_name="Longer name", strategic_objectives="Objective AB"),
        _activity(activity_name="Other", strategic_objectives="Objective C"),
    ])
    writable_session.flush()
    found = queries.search_activities(writable_session, strategic_objective="Objective A")
    assert [row["activity_name"] for row in found["activities"]] == ["Two objectives"]


def test_search_matches_an_executive_across_both_executive_columns(writable_session):
    writable_session.add_all([
        _activity(activity_name="Board member", bod_geb="Doe, Jane"),
        _activity(activity_name="Other executive", other_executives="Roe, Sam; Poe, Ana"),
        _activity(activity_name="Nobody"),
    ])
    writable_session.flush()
    assert [
        row["activity_name"]
        for row in queries.search_activities(writable_session, executive="Doe, Jane")["activities"]
    ] == ["Board member"]
    assert [
        row["activity_name"]
        for row in queries.search_activities(writable_session, executive="Poe, Ana")["activities"]
    ] == ["Other executive"]


def test_executive_filter_spans_both_columns_in_both_stages(writable_session):
    """The SQL prefilter and the Python exact check must cover the SAME columns.

    A substring match in either column has to survive the prefilter and then be
    decided exactly: "Doe, Jane" must not match the longer "Doe, Janet", and a
    name held only in the second column must not be dropped.
    """
    writable_session.add_all([
        _activity(activity_name="Board member", bod_geb="Doe, Jane"),
        _activity(activity_name="Longer name", bod_geb="Doe, Janet"),
        _activity(activity_name="Second column", other_executives="Roe, Sam; Doe, Jane"),
        _activity(activity_name="Nobody"),
    ])
    writable_session.flush()
    found = queries.search_activities(writable_session, executive="doe, jane")
    assert sorted(row["activity_name"] for row in found["activities"]) == [
        "Board member",
        "Second column",
    ]
    assert found["total_matches"] == 2


def test_planning_gaps_can_be_narrowed_by_executive(writable_session):
    """Free once the filter lives in ActivityFilters instead of in one tool."""
    writable_session.add_all([
        _activity(activity_name="Executive gap", bod_geb="Doe, Jane", channel=None),
        _activity(activity_name="Other gap", other_executives="Roe, Sam", channel=None),
    ])
    writable_session.flush()
    gaps = queries.planning_gaps(writable_session, executive="Doe, Jane")
    assert gaps["checked"] == 1
    assert gaps["incomplete"] == 1
    assert gaps["activities"][0]["activity_name"] == "Executive gap"


def test_activity_counts_can_be_narrowed_by_executive(writable_session):
    writable_session.add_all([
        _activity(channel="Email", bod_geb="Doe, Jane"),
        _activity(channel="Intranet", other_executives="Doe, Jane"),
        _activity(channel="Email", bod_geb="Roe, Sam"),
    ])
    writable_session.flush()
    counted = queries.activity_counts(
        writable_session, dimension="channel", executive="Doe, Jane"
    )
    assert {bucket["value"]: bucket["count"] for bucket in counted["buckets"]} == {
        "Email": 1,
        "Intranet": 1,
    }


def test_search_finds_activities_involving_any_executive(writable_session):
    """`has_executive` answers "which activities involve an executive at all".

    Without it, that question needs `field_values` plus one search per name.
    """
    writable_session.add_all([
        _activity(activity_name="Board", bod_geb="Doe, Jane"),
        _activity(activity_name="Other", other_executives="Roe, Sam"),
        _activity(activity_name="Sentinel", bod_geb="None", other_executives="   "),
        _activity(activity_name="Nobody"),
    ])
    writable_session.flush()
    involved = queries.search_activities(writable_session, has_executive=True)
    assert sorted(row["activity_name"] for row in involved["activities"]) == [
        "Board",
        "Other",
    ]
    without = queries.search_activities(writable_session, has_executive=False)
    assert sorted(row["activity_name"] for row in without["activities"]) == [
        "Nobody",
        "Sentinel",
    ]


def test_post_filtered_search_still_reports_truncation(writable_session):
    writable_session.add_all([
        _activity(activity_name=f"Urgent {index}", priority="1 - label")
        for index in range(5)
    ])
    writable_session.flush()
    found = queries.search_activities(writable_session, min_priority_rank=3, limit=2)
    assert found["total_matches"] == 5
    assert found["returned"] == 2
    assert found["truncated"] is True
    assert "Narrow the filters" in found["note"]


def test_search_without_post_filters_keeps_the_sql_count_path(writable_session):
    writable_session.add_all([_activity() for _ in range(3)])
    writable_session.flush()
    assert queries.needs_post_filter(queries.ActivityFilters()) is False
    assert queries.search_activities(writable_session)["total_matches"] == 3


def test_search_activities_builds_an_empty_contains_filter_when_unused(writable_session):
    """Regression pin for a real bug caught during review of this task.

    `search_activities` builds `contains={"strategic_objectives": strategic_objective}
    if strategic_objective else {}` internally. The `if strategic_objective else {}`
    guard is essential: an unconditional `{"strategic_objectives": strategic_objective}`
    would leave `contains` a non-empty dict (with a None value) even when the
    caller passes no `strategic_objective` at all, and `needs_post_filter` only
    checks `bool(filters.contains)` -- so that shape would make the gate return
    True unconditionally, permanently disabling the cheap SQL-count path below
    for every single call.

    `test_search_without_post_filters_keeps_the_sql_count_path` does not catch
    this: it calls `needs_post_filter` on a directly constructed, always-empty
    `ActivityFilters()`, never on what `search_activities` itself builds, and
    `total_matches` is correct either way (the slow branch also computes the
    right count, just less cheaply). This test instead spies on the real gate
    with the `ActivityFilters` `search_activities` actually constructs, so a
    future rewrite of that construction (Task 6 replaces it with a
    `_build_filters` helper) trips this test if the property regresses --
    regardless of which function ends up building the dict, as long as
    `needs_post_filter` stays the gate.
    """
    writable_session.add_all([_activity() for _ in range(3)])
    writable_session.flush()

    captured = {}
    original = queries.needs_post_filter

    def recording_gate(filters):
        result = original(filters)
        captured["filters"] = filters
        captured["result"] = result
        return result

    with mock.patch.object(queries, "needs_post_filter", side_effect=recording_gate):
        no_filter_result = queries.search_activities(writable_session)
    assert captured["filters"].contains == {}
    assert captured["result"] is False
    assert no_filter_result["total_matches"] == 3

    with mock.patch.object(queries, "needs_post_filter", side_effect=recording_gate):
        filtered_result = queries.search_activities(
            writable_session, strategic_objective="Objective A"
        )
    assert captured["filters"].contains == {"strategic_objectives": "Objective A"}
    assert captured["result"] is True
    assert filtered_result["total_matches"] == 3  # every fixture row carries "Objective A"


# --------------------------------------------------------------------------
# Collision detection
# --------------------------------------------------------------------------
#
# `detect_collisions` closes the two highest risk-premium questions in the
# catalogue and is the thing a human at the studio can see today that an
# agent could not. The fixtures below give every activity its own
# `tracking_id` so its `tracking_pack_id` is under test control -- the
# `_activity()` default template shares one constant pack ("CLU-1") across
# every row unless overridden, which would silently turn "conflict" fixtures
# into "orchestration" ones.


def test_collision_needs_both_a_shared_channel_and_a_shared_audience(writable_session):
    """The single most important test in this task.

    Three pairs, each isolated on its own day so cross-pair proximity never
    matters at the default `proximity_days=0`: shares both channel and
    audience (collides), shares channel only (must not), shares audience
    only (must not). Either-not-both would flag two of these three pairs
    instead of one, which is exactly the defect rule 1 exists to catch.
    """
    day_both = REFERENCE + timedelta(days=10)
    day_channel_only = REFERENCE + timedelta(days=20)
    day_audience_only = REFERENCE + timedelta(days=30)
    writable_session.add_all(
        [
            _activity(
                activity_name="Shares both A",
                tracking_id="CLU-1-260110-0000001-EM",
                channel="Email",
                target_audience="Staff",
                start_date=day_both,
                end_date=day_both,
            ),
            _activity(
                activity_name="Shares both B",
                tracking_id="CLU-2-260110-0000002-EM",
                channel="Email",
                target_audience="Staff",
                start_date=day_both,
                end_date=day_both,
            ),
            _activity(
                activity_name="Shares channel only A",
                tracking_id="CLU-3-260110-0000003-EM",
                channel="Email",
                target_audience="Retail",
                start_date=day_channel_only,
                end_date=day_channel_only,
            ),
            _activity(
                activity_name="Shares channel only B",
                tracking_id="CLU-4-260110-0000004-EM",
                channel="Email",
                target_audience="Corporate",
                start_date=day_channel_only,
                end_date=day_channel_only,
            ),
            _activity(
                activity_name="Shares audience only A",
                tracking_id="CLU-5-260110-0000005-EM",
                channel="Email",
                target_audience="Staff",
                start_date=day_audience_only,
                end_date=day_audience_only,
            ),
            _activity(
                activity_name="Shares audience only B",
                tracking_id="CLU-6-260110-0000006-SM",
                channel="SMS",
                target_audience="Staff",
                start_date=day_audience_only,
                end_date=day_audience_only,
            ),
        ]
    )
    writable_session.flush()

    result = queries.detect_collisions(writable_session)

    assert result["total"] == 1
    pair = result["collisions"][0]
    names = {pair["left"]["activity_name"], pair["right"]["activity_name"]}
    assert names == {"Shares both A", "Shares both B"}
    assert pair["shared_channels"] == ["Email"]
    assert pair["shared_audiences"] == ["Staff"]


def test_collision_matches_when_one_side_lists_several_channels(writable_session):
    """A pair still collides when one side's `channel` carries more than one
    value ("Email, Intranet") and only one of them matches the other side.

    This is the finding that made the earlier version of this suite
    misleading: every fixture up to this point used single-valued channel and
    audience strings, so swapping `_normalize_multi` for `split_multi` at both
    call sites in `detect_collisions` -- which would silently stop splitting
    `channel`/`target_audience` at all, since neither is declared in
    MULTI_VALUE_SEPARATORS -- passed the whole suite while breaking real
    collision detection on real multi-valued data. This test would fail
    under that swap: `split_multi("Email, Intranet", "channel")` returns the
    whole string as ONE member, which does not intersect `{"email"}`.

    The second assertion pins the fork itself, the same technique
    `test_required_fields_match_the_planning_completeness_view` uses for the
    completeness rule: `split_multi` must keep NOT splitting `channel`, so a
    future "unification" of the two splitters fails loudly here instead of
    only showing up as a silent behaviour change in `detect_collisions`.
    """
    day = REFERENCE + timedelta(days=12)
    writable_session.add_all(
        [
            _activity(
                activity_name="Multi-channel",
                tracking_id="CLU-61-260110-0000001-EM",
                channel="Email, Intranet",
                target_audience="Staff",
                start_date=day,
                end_date=day,
            ),
            _activity(
                activity_name="Single-channel",
                tracking_id="CLU-62-260110-0000002-EM",
                channel="Email",
                target_audience="Staff",
                start_date=day,
                end_date=day,
            ),
        ]
    )
    writable_session.flush()

    result = queries.detect_collisions(writable_session)

    assert result["total"] == 1
    assert result["collisions"][0]["shared_channels"] == ["Email"]

    # Pins the fork: `channel` stays scalar in `split_multi` on purpose (see
    # the comment above MULTI_VALUE_SEPARATORS and above `_normalize_multi`).
    assert queries.split_multi("Email, Intranet", "channel") == ["Email, Intranet"]


def test_collision_matching_is_case_insensitive(writable_session):
    """Differing casing on both dimensions must still collide.

    Every other collision fixture in this suite happens to match casing
    exactly, which would let a regression to exact-string (rather than
    case-folded) intersection pass unnoticed.
    """
    day = REFERENCE + timedelta(days=13)
    writable_session.add_all(
        [
            _activity(
                activity_name="Upper",
                tracking_id="CLU-63-260110-0000001-EM",
                channel="EMAIL",
                target_audience="STAFF",
                start_date=day,
                end_date=day,
            ),
            _activity(
                activity_name="Lower",
                tracking_id="CLU-64-260110-0000002-EM",
                channel="email",
                target_audience="staff",
                start_date=day,
                end_date=day,
            ),
        ]
    )
    writable_session.flush()

    result = queries.detect_collisions(writable_session)

    assert result["total"] == 1


def test_collision_channel_filter_is_membership_aware_not_exact_match(writable_session):
    """`channel="Email"` must still find a row stored as "Email, Intranet".

    `search_activities(channel="Email")` would NOT find that row -- its
    `text` filter is exact-string equality (`_apply_filters`). Narrowing
    `detect_collisions` the same way would silently drop rows the pairing
    rule itself would still call a match on the unfiltered set. This pins
    that `detect_collisions` narrows `channel` / `target_audience` by
    membership instead, without touching `_apply_filters`/`_build_filters`
    (`search_activities` on the same row, asserted here too, proves the
    shared filter machinery was NOT widened to do it).
    """
    day = REFERENCE + timedelta(days=14)
    writable_session.add_all(
        [
            _activity(
                activity_name="Multi-channel filter target",
                tracking_id="CLU-65-260110-0000001-EM",
                channel="Email, Intranet",
                target_audience="Staff",
                start_date=day,
                end_date=day,
            ),
            _activity(
                activity_name="Plain match",
                tracking_id="CLU-66-260110-0000002-EM",
                channel="Email",
                target_audience="Staff",
                start_date=day,
                end_date=day,
            ),
        ]
    )
    writable_session.flush()

    narrowed = queries.detect_collisions(writable_session, channel="Email")
    assert narrowed["checked"] == 2  # both rows carry "Email" as a member
    assert narrowed["total"] == 1

    # The shared filter machinery stays exact-match for every other caller.
    exact_match_only = queries.search_activities(writable_session, channel="Email")
    assert exact_match_only["total_matches"] == 1  # only "Plain match"


def test_proximity_days_is_clamped_to_a_ceiling(writable_session):
    """An unbounded `proximity_days` would let the sliding window's `break`
    never fire, comparing and summarizing every pair before `_clamp_limit`
    ever runs. `MAX_PROXIMITY_DAYS` caps the window regardless of what the
    caller asks for.
    """
    day_zero = REFERENCE + timedelta(days=200)
    within_ceiling = day_zero + timedelta(days=queries.MAX_PROXIMITY_DAYS)
    beyond_ceiling = day_zero + timedelta(days=queries.MAX_PROXIMITY_DAYS + 5)
    writable_session.add_all(
        [
            _activity(
                activity_name="Anchor",
                tracking_id="CLU-67-260110-0000001-EM",
                channel="Email",
                target_audience="Staff",
                start_date=day_zero,
                end_date=day_zero,
            ),
            _activity(
                activity_name="At the ceiling",
                tracking_id="CLU-68-260110-0000002-EM",
                channel="Email",
                target_audience="Staff",
                start_date=within_ceiling,
                end_date=within_ceiling,
            ),
            _activity(
                activity_name="Past the ceiling",
                tracking_id="CLU-69-260110-0000003-EM",
                channel="Email",
                target_audience="Staff",
                start_date=beyond_ceiling,
                end_date=beyond_ceiling,
            ),
        ]
    )
    writable_session.flush()

    result = queries.detect_collisions(writable_session, proximity_days=1_000_000)

    gaps = {pair["gap_days"] for pair in result["collisions"]}
    assert queries.MAX_PROXIMITY_DAYS in gaps
    assert queries.MAX_PROXIMITY_DAYS + 5 not in gaps


def test_same_pack_is_orchestration_not_conflict(writable_session):
    """Two activities in the same pack, top priority on both -- still info.

    This is the whole value of the tool: a naive port that skips the
    same-pack check would call this pair a "critical conflict" and flag
    every well-orchestrated campaign as a problem.
    """
    day = REFERENCE + timedelta(days=15)
    writable_session.add_all(
        [
            _activity(
                activity_name="Pack member A",
                tracking_id="CLU-9-260110-0000001-EM",
                channel="Email",
                target_audience="Staff",
                priority="Critical",
                start_date=day,
                end_date=day,
            ),
            _activity(
                activity_name="Pack member B",
                tracking_id="CLU-9-260110-0000002-SM",
                channel="Email",
                target_audience="Staff",
                priority="Critical",
                start_date=day,
                end_date=day,
            ),
        ]
    )
    writable_session.flush()

    result = queries.detect_collisions(writable_session)

    assert result["total"] == 1
    pair = result["collisions"][0]
    assert pair["kind"] == "orchestration"
    assert pair["severity"] == "info"


@pytest.mark.parametrize(
    "priority_a, priority_b, expected_severity",
    [
        ("Critical", "Low", "critical"),
        ("1 - most urgent label", "4 - lowest label", "critical"),
        ("High", "Low", "high"),
        ("2 - next label", "4 - lowest label", "high"),
        ("Medium", "Normal", "medium"),
        ("Low", "Normal", "medium"),
    ],
)
def test_severity_comes_from_the_higher_priority_of_the_pair(
    writable_session, priority_a, priority_b, expected_severity
):
    """Both live priority vocabularies feed the same `max(rank(left), rank(right))` rule."""
    day = REFERENCE + timedelta(days=40)
    writable_session.add_all(
        [
            _activity(
                activity_name="Left",
                tracking_id="CLU-11-260110-0000001-EM",
                channel="Email",
                target_audience="Staff",
                priority=priority_a,
                start_date=day,
                end_date=day,
            ),
            _activity(
                activity_name="Right",
                tracking_id="CLU-12-260110-0000002-EM",
                channel="Email",
                target_audience="Staff",
                priority=priority_b,
                start_date=day,
                end_date=day,
            ),
        ]
    )
    writable_session.flush()

    result = queries.detect_collisions(writable_session)

    assert result["total"] == 1
    assert result["collisions"][0]["kind"] == "conflict"
    assert result["collisions"][0]["severity"] == expected_severity


def test_collisions_respect_the_proximity_window(writable_session):
    """A pair 3 days apart is found at proximity_days=3 and not at proximity_days=1."""
    day_left = REFERENCE + timedelta(days=50)
    day_right = day_left + timedelta(days=3)
    writable_session.add_all(
        [
            _activity(
                activity_name="Proximity left",
                tracking_id="CLU-21-260110-0000001-EM",
                channel="Email",
                target_audience="Staff",
                start_date=day_left,
                end_date=day_left,
            ),
            _activity(
                activity_name="Proximity right",
                tracking_id="CLU-22-260110-0000002-EM",
                channel="Email",
                target_audience="Staff",
                start_date=day_right,
                end_date=day_right,
            ),
        ]
    )
    writable_session.flush()

    within_window = queries.detect_collisions(writable_session, proximity_days=3)
    outside_window = queries.detect_collisions(writable_session, proximity_days=1)

    assert within_window["total"] == 1
    assert within_window["collisions"][0]["gap_days"] == 3
    assert outside_window["total"] == 0
    assert outside_window["collisions"] == []


def test_collisions_are_ordered_worst_first(writable_session):
    """Severity descending (critical > high > medium > info), then gap_days ascending.

    Five pairs, one per severity bucket plus a second critical pair at a
    wider gap -- each pair uses its own channel/audience combination so no
    pair can accidentally collide with another pair's activities even
    though every pair sits inside the shared `proximity_days=5` window.
    """
    base = REFERENCE + timedelta(days=100)
    writable_session.add_all(
        [
            # Critical, gap 0.
            _activity(
                activity_name="Critical close A",
                tracking_id="CLU-31-260110-0000001-EM",
                channel="Channel A",
                target_audience="Audience A",
                priority="Critical",
                start_date=base,
                end_date=base,
            ),
            _activity(
                activity_name="Critical close B",
                tracking_id="CLU-32-260110-0000002-EM",
                channel="Channel A",
                target_audience="Audience A",
                priority="Critical",
                start_date=base,
                end_date=base,
            ),
            # Critical, gap 2 -- same severity as above, worse (larger) gap.
            _activity(
                activity_name="Critical far A",
                tracking_id="CLU-33-260110-0000003-EM",
                channel="Channel B",
                target_audience="Audience B",
                priority="Critical",
                start_date=base + timedelta(days=20),
                end_date=base + timedelta(days=20),
            ),
            _activity(
                activity_name="Critical far B",
                tracking_id="CLU-34-260110-0000004-EM",
                channel="Channel B",
                target_audience="Audience B",
                priority="Critical",
                start_date=base + timedelta(days=22),
                end_date=base + timedelta(days=22),
            ),
            # High.
            _activity(
                activity_name="High A",
                tracking_id="CLU-35-260110-0000005-EM",
                channel="Channel C",
                target_audience="Audience C",
                priority="High",
                start_date=base + timedelta(days=40),
                end_date=base + timedelta(days=40),
            ),
            _activity(
                activity_name="High B",
                tracking_id="CLU-36-260110-0000006-EM",
                channel="Channel C",
                target_audience="Audience C",
                priority="Low",
                start_date=base + timedelta(days=40),
                end_date=base + timedelta(days=40),
            ),
            # Medium.
            _activity(
                activity_name="Medium A",
                tracking_id="CLU-37-260110-0000007-EM",
                channel="Channel D",
                target_audience="Audience D",
                priority="Medium",
                start_date=base + timedelta(days=60),
                end_date=base + timedelta(days=60),
            ),
            _activity(
                activity_name="Medium B",
                tracking_id="CLU-38-260110-0000008-EM",
                channel="Channel D",
                target_audience="Audience D",
                priority="Normal",
                start_date=base + timedelta(days=60),
                end_date=base + timedelta(days=60),
            ),
            # Info -- same pack, top priority, must still sort last.
            _activity(
                activity_name="Info A",
                tracking_id="CLU-39-260110-0000009-EM",
                channel="Channel E",
                target_audience="Audience E",
                priority="Critical",
                start_date=base + timedelta(days=80),
                end_date=base + timedelta(days=80),
            ),
            _activity(
                activity_name="Info B",
                tracking_id="CLU-39-260110-0000010-EM",
                channel="Channel E",
                target_audience="Audience E",
                priority="Critical",
                start_date=base + timedelta(days=80),
                end_date=base + timedelta(days=80),
            ),
        ]
    )
    writable_session.flush()

    result = queries.detect_collisions(writable_session, proximity_days=5)

    assert result["total"] == 5
    severities = [pair["severity"] for pair in result["collisions"]]
    assert severities == ["critical", "critical", "high", "medium", "info"]
    # The tie-break: both critical pairs sort by gap_days ascending.
    gaps = [pair["gap_days"] for pair in result["collisions"][:2]]
    assert gaps == [0, 2]


def test_collisions_ignore_activities_without_a_start_date(writable_session):
    """A pair that would otherwise collide is not paired when one side is undated."""
    day = REFERENCE + timedelta(days=90)
    writable_session.add_all(
        [
            _activity(
                activity_name="Dated",
                tracking_id="CLU-41-260110-0000001-EM",
                channel="Email",
                target_audience="Staff",
                start_date=day,
                end_date=day,
            ),
            _activity(
                activity_name="Undated",
                tracking_id="CLU-42-260110-0000002-EM",
                channel="Email",
                target_audience="Staff",
                start_date=None,
                end_date=None,
            ),
        ]
    )
    writable_session.flush()

    result = queries.detect_collisions(writable_session)

    assert result["total"] == 0
    assert result["collisions"] == []


def test_collisions_report_their_own_truncation(writable_session):
    """The count is the TRUE total across all pairs, the list is capped."""
    day = REFERENCE + timedelta(days=110)
    writable_session.add_all(
        [
            _activity(
                activity_name=f"Crowd {index}",
                tracking_id=f"CLU-{50 + index}-260110-000000{index}-EM",
                channel="Email",
                target_audience="Staff",
                start_date=day,
                end_date=day,
            )
            for index in range(4)
        ]
    )
    writable_session.flush()

    result = queries.detect_collisions(writable_session, limit=2)

    assert result["total"] == 6  # C(4, 2): every pair of the 4 activities collides
    assert result["returned"] == 2
    assert len(result["collisions"]) == 2
    assert result["truncated"] is True
    assert result["note"] is not None
    assert "collisions" in result["note"]


def test_collisions_summarize_only_the_pairs_they_return(writable_session, monkeypatch):
    """`_summarize` runs after the cap, not before it.

    `MAX_PROXIMITY_DAYS` bounds how many pairs are CONSIDERED, not how much
    each considered pair costs: a 90-day window over a real portfolio still
    collides far more pairs than any answer returns, and building two full
    activity dicts for each of them before `_clamp_limit` is the unbounded
    intermediate this module's docstring promises never to build.
    """
    day = REFERENCE + timedelta(days=130)
    writable_session.add_all(
        [
            _activity(
                activity_name=f"Crowd {index}",
                tracking_id=f"CLU-{70 + index}-260110-000000{index}-EM",
                channel="Email",
                target_audience="Staff",
                start_date=day,
                end_date=day,
            )
            for index in range(6)
        ]
    )
    writable_session.flush()

    calls = 0
    real_summarize = queries._summarize

    def counting_summarize(activity):
        nonlocal calls
        calls += 1
        return real_summarize(activity)

    monkeypatch.setattr(queries, "_summarize", counting_summarize)
    result = queries.detect_collisions(writable_session, limit=2)

    # C(6, 2) == 15 pairs all collide; only 2 are returned.
    assert result["total"] == 15
    assert result["returned"] == 2
    # Two activities per returned pair, and not one dict more.
    assert calls == 4


def test_collision_rule_matches_the_studio_implementation():
    """Pinned against analytics.js so neither collision rule can silently drift.

    Same technique as test_priority_rank_matches_the_studio_implementation:
    read the studio's own source for the full guard line (rule 1) and the
    `samePack` severity branch (rule 2), so a change on either side of the
    port fails the suite instead of quietly diverging.

    The guard is asserted as the WHOLE line, `if (!A || !B) continue`, not as
    two separate substring checks: asserting only that both
    `sharesDimension(...)` calls are present would still pass if the `||`
    drifted to `&&` -- either-not-both, the exact regression rule 1 exists to
    catch -- because both call strings would still be there.
    """
    studio = (REPO_ROOT / "pipeline" / "studio" / "analytics.js").read_text()
    match = re.search(r"function detectCollisions\([^)]*\)\s*\{(.*?)\n  \}", studio, re.DOTALL)
    assert match, "detectCollisions not found in analytics.js"
    body = match.group(1)
    assert (
        "if (!sharesDimension(left, right, 'channel') || "
        "!sharesDimension(left, right, 'target_audience')) continue;"
    ) in body
    assert "samePack ? 'info'" in body


# --------------------------------------------------------------------------
# Lead-time statistics and data quality (Task 5)
# --------------------------------------------------------------------------


def test_lead_time_quantiles_match_the_studio_math(writable_session):
    """Hand-computed against the studio's own interpolation formula.

    Lead times 2, 5, 9, 20 (four activities, `source_created_at=REFERENCE`,
    `start_date` offset to land on exactly those day counts). Verified against
    `analytics.js::quantile` directly (not re-derived independently):

        median = quantile([2, 5, 9, 20], 0.5)
                = 5 + (9 - 5) * (1.5 - 1)      = 7.0
        p25     = quantile([2, 5, 9, 20], 0.25)
                = 2 + (5 - 2) * (0.75 - 0)     = 4.25 -> rounds to 4.3
        p75     = quantile([2, 5, 9, 20], 0.75)
                = 9 + (20 - 9) * (2.25 - 2)    = 11.75 -> rounds to 11.8

    p25's 4.25 is the case that actually exercises `Math.round`'s
    round-half-away-from-zero: 4.25 * 10 = 42.5, and `Math.round(42.5) ===
    43`, while Python's builtin `round(42.5)` rounds to the nearest EVEN
    integer and returns 42 (4.2) -- a naive port using `round()` instead of
    `_js_round` would report 4.2 here and this assertion would catch it.
    """
    for days in (2, 5, 9, 20):
        writable_session.add(
            _activity(
                source_created_at=REFERENCE,
                start_date=REFERENCE + timedelta(days=days),
            )
        )
    writable_session.flush()

    result = queries.lead_time_stats(writable_session)

    assert result["valid"] == 4
    assert result["excluded"] == 0
    assert result["median"] == 7.0
    assert result["p25"] == 4.3
    assert result["p75"] == 11.8


def test_lead_time_excludes_negative_and_unknown_values(writable_session):
    """Negative lead times are DROPPED, not clamped -- and count as excluded.

    An unknown (no `start_date`) value is excluded the same way. Neither
    enters the quantiles: only the single remaining positive value does, so
    every quantile falls back to that lone value (`_quantile`'s
    single-element branch).
    """
    writable_session.add_all(
        [
            _activity(source_created_at=REFERENCE, start_date=REFERENCE + timedelta(days=10)),
            # Negative lead time: starts before its own planning reference.
            _activity(source_created_at=REFERENCE, start_date=REFERENCE - timedelta(days=5)),
            # Unknown: no start_date at all, so lead_days() is None.
            _activity(source_created_at=REFERENCE, start_date=None),
        ]
    )
    writable_session.flush()

    result = queries.lead_time_stats(writable_session)

    assert result["valid"] == 1
    assert result["excluded"] == 2
    assert result["median"] == 10
    assert result["p25"] == 10
    assert result["p75"] == 10


def test_data_quality_counts_duplicate_ids_as_groups_not_rows(writable_session):
    """Three rows sharing one tracking id count as ONE duplicate, not three.

    The studio counts groups (`Array.from(counts.values()).filter(n => n >
    1).length`); counting rows instead would report `3` here (or `2`, the row
    count minus one), either of which would send a data steward looking for
    the wrong number of ids to fix.

    `legacy_sp_id` is set on all four rows: the schema's own unique index on
    `tracking_id` (`ix_activities_tracking_id_v6_unique`) only applies to
    studio-generated rows (`legacy_sp_id IS NULL`) -- legacy-imported rows are
    exempt because the source system genuinely contains duplicate tracking
    ids, which is exactly the case this metric exists to surface.
    """
    writable_session.add_all(
        [
            _activity(legacy_sp_id=1, tracking_id="CLU-1-260110-0000001-EM"),
            _activity(legacy_sp_id=2, tracking_id="CLU-1-260110-0000001-EM"),
            _activity(legacy_sp_id=3, tracking_id="CLU-1-260110-0000001-EM"),
            _activity(legacy_sp_id=4, tracking_id="CLU-1-260110-0000002-EM"),
        ]
    )
    writable_session.flush()

    result = queries.data_quality(writable_session)

    assert result["duplicate_tracking_ids"] == 1


def test_data_quality_flags_reversed_date_ranges(writable_session):
    writable_session.add_all(
        [
            _activity(start_date=REFERENCE, end_date=REFERENCE + timedelta(days=1)),
            # Reversed: end before start.
            _activity(start_date=REFERENCE + timedelta(days=5), end_date=REFERENCE),
        ]
    )
    writable_session.flush()

    result = queries.data_quality(writable_session)

    assert result["invalid_date_ranges"] == 1


def test_data_quality_pack_ids_ignore_tracking_pack_id(writable_session):
    """`missing_pack_ids` must NOT treat a derived `tracking_pack_id` as a pack.

    Every default `_activity()` carries a `tracking_id`, which derives a
    non-blank `tracking_pack_id` (`ActivityRead.tracking_pack_id`). If that
    field counted, this activity -- which has no `communication_pack_cpid`,
    `communication_pack`, or `campaign` -- would wrongly read as pack-linked
    and `missing_pack_ids` would be `0` here instead of `1`.
    """
    writable_session.add_all(
        [
            _activity(communication_pack_cpid=None, communication_pack=None, campaign=None),
            _activity(communication_pack_cpid="CP-1"),
        ]
    )
    writable_session.flush()

    result = queries.data_quality(writable_session)

    assert result["missing_pack_ids"] == 1


def test_data_quality_incomplete_agrees_with_planning_gaps(writable_session):
    """`incomplete` reuses `missing_fields`, the same rule `planning_gaps`
    reports against -- the two figures must not drift apart."""
    writable_session.add_all(
        [
            _activity(channel=None),  # incomplete
            _activity(lead_team=None),  # incomplete
            _activity(),  # complete
        ]
    )
    writable_session.flush()

    quality = queries.data_quality(writable_session)
    gaps = queries.planning_gaps(writable_session)

    assert quality["incomplete"] == gaps["incomplete"]
    assert quality["total"] == gaps["checked"]
    assert quality["completeness_rate"] == round(
        (quality["total"] - quality["incomplete"]) / quality["total"] * 100, 1
    )


def test_lead_time_and_quality_pin_against_the_studio():
    """Pins three studio formulas so this port cannot silently drift.

    Same technique as test_priority_rank_matches_the_studio_implementation:
    read analytics.js's own source for the quantile arithmetic, the
    `leadTimeStats` value filter and the `hasCampaignOrPack` exclusion of
    `tracking_pack_id`, rather than re-deriving any of them independently.

    Each rule is asserted as its WHOLE line, the way
    test_collision_rule_matches_the_studio_implementation asserts its guard:
    a set of substring checks passes even when the operator between them
    flips, which is exactly the drift these pins exist to catch.
    """
    studio = (REPO_ROOT / "pipeline" / "studio" / "analytics.js").read_text()

    quantile_match = re.search(r"function quantile\([^)]*\)\s*\{(.*?)\n  \}", studio, re.DOTALL)
    assert quantile_match, "quantile not found in analytics.js"
    quantile_body = quantile_match.group(1)
    assert "const index = (sorted.length - 1) * p;" in quantile_body
    assert "return Math.round(value * 10) / 10;" in quantile_body
    # The single-element quirk `_quantile` deliberately keeps rather than
    # "fixes": one value is returned raw and unrounded, bypassing the
    # interpolation and the one-decimal rounding entirely.
    assert "if (sorted.length === 1) return sorted[0];" in quantile_body

    lead_match = re.search(r"function leadTimeStats\([^)]*\)\s*\{(.*?)\n  \}", studio, re.DOTALL)
    assert lead_match, "leadTimeStats not found in analytics.js"
    lead_body = lead_match.group(1)
    # A negative lead time is DROPPED, not clamped to zero. Asserted as the
    # whole filter: `>= 0` alone would still pass if the studio started
    # clamping, and `Number.isFinite` alone says nothing about the sign.
    assert ".filter(v => Number.isFinite(v) && v >= 0)" in lead_body

    pack_match = re.search(
        r"function hasCampaignOrPack\([^)]*\)\s*\{(.*?)\n  \}", studio, re.DOTALL
    )
    assert pack_match, "hasCampaignOrPack not found in analytics.js"
    pack_body = pack_match.group(1)
    # The comment explaining the exclusion mentions "tracking_pack_id" by
    # name; only the live code -- a `row.tracking_pack_id` access -- would
    # indicate the exclusion was dropped.
    assert "row.tracking_pack_id" not in pack_body
    # The whole return line, not three presence checks: flipping `||` to `&&`
    # inverts the metric (a row would need all three links to count as
    # pack-linked) while every presence check still passes.
    assert (
        "return !empty(row.communication_pack_cpid) || "
        "!empty(row.communication_pack) || !empty(row.campaign);"
    ) in pack_body


# --------------------------------------------------------------------------
# Change history
# --------------------------------------------------------------------------


def test_activity_history_returns_changes_newest_first(writable_session):
    activity = _activity()
    writable_session.add(activity)
    writable_session.flush()
    writable_session.add_all(
        [
            ActivityChange(
                activity_id=activity.id,
                actor="studio",
                change_type="created",
                changed_at=REFERENCE,
                version_to=1,
            ),
            ActivityChange(
                activity_id=activity.id,
                actor="studio",
                change_type="updated",
                field="channel",
                old_value="Email",
                new_value="Intranet",
                changed_at=REFERENCE + timedelta(days=1),
                version_from=1,
                version_to=2,
            ),
        ]
    )
    writable_session.flush()

    history = queries.activity_history(writable_session, str(activity.id))

    assert history["found"] is True
    assert history["tracking_id"] == activity.tracking_id
    assert history["activity_name"] == activity.activity_name
    assert [change["change_type"] for change in history["changes"]] == ["updated", "created"]
    assert history["changes"][0]["field"] == "channel"
    assert history["changes"][0]["old_value"] == "Email"
    assert history["changes"][0]["new_value"] == "Intranet"
    assert history["total"] == 2
    assert history["returned"] == 2
    assert history["truncated"] is False


def test_activity_history_resolves_by_tracking_id_and_uuid(writable_session):
    activity = _activity()
    writable_session.add(activity)
    writable_session.flush()
    writable_session.add(
        ActivityChange(activity_id=activity.id, actor="seed", change_type="created", version_to=1)
    )
    writable_session.flush()

    by_uuid = queries.activity_history(writable_session, str(activity.id))
    by_tracking_id = queries.activity_history(writable_session, activity.tracking_id)

    assert by_uuid["found"] is True
    assert by_tracking_id["found"] is True
    assert by_uuid["changes"] == by_tracking_id["changes"]
    assert by_tracking_id["activity_id"] == str(activity.id)


def test_activity_history_reports_a_clean_miss_for_an_unknown_identifier(session):
    result = queries.activity_history(session, "NOPE-1-000000-0000000-XX")

    assert result["found"] is False
    assert "search_activities" in result["note"]


def test_activity_history_reports_its_own_truncation(writable_session):
    activity = _activity()
    writable_session.add(activity)
    writable_session.flush()
    writable_session.add_all(
        [
            ActivityChange(
                activity_id=activity.id,
                actor="studio",
                change_type="updated",
                field="channel",
                changed_at=REFERENCE + timedelta(days=index),
                version_from=index,
                version_to=index + 1,
            )
            for index in range(3)
        ]
    )
    writable_session.flush()

    history = queries.activity_history(writable_session, str(activity.id), limit=2)

    assert history["total"] == 3
    assert history["returned"] == 2
    assert history["truncated"] is True
    assert history["note"] is not None


def test_plan_changes_since_groups_by_activity_and_tallies_actors(writable_session):
    first = _activity(activity_name="First activity")
    second = _activity(activity_name="Second activity")
    writable_session.add_all([first, second])
    writable_session.flush()
    writable_session.add_all(
        [
            ActivityChange(
                activity_id=first.id,
                actor="studio",
                change_type="created",
                changed_at=REFERENCE,
                version_to=1,
            ),
            ActivityChange(
                activity_id=first.id,
                actor="studio",
                change_type="updated",
                field="channel",
                old_value="Email",
                new_value="Intranet",
                changed_at=REFERENCE + timedelta(hours=1),
                version_from=1,
                version_to=2,
            ),
            ActivityChange(
                activity_id=second.id,
                actor="sync",
                change_type="updated",
                field="priority",
                old_value="Low",
                new_value="High",
                changed_at=REFERENCE + timedelta(hours=2),
                version_from=1,
                version_to=2,
            ),
        ]
    )
    writable_session.flush()

    result = queries.plan_changes_since(writable_session, since="2026-01-01")

    assert result["changes"] == 3
    assert result["returned"] == 2
    assert result["by_actor"] == {"studio": 2, "sync": 1}
    assert result["by_change_type"] == {"updated": 2, "created": 1}
    groups_by_id = {group["activity_id"]: group for group in result["activities"]}
    assert groups_by_id[str(first.id)]["change_count"] == 2
    assert groups_by_id[str(first.id)]["tracking_id"] == first.tracking_id
    assert groups_by_id[str(second.id)]["change_count"] == 1


def test_plan_changes_since_buckets_created_rows_without_a_field(writable_session):
    activity = _activity()
    writable_session.add(activity)
    writable_session.flush()
    writable_session.add(
        ActivityChange(
            activity_id=activity.id,
            actor="seed",
            change_type="created",
            changed_at=REFERENCE,
            version_to=1,
        )
    )
    writable_session.flush()

    result = queries.plan_changes_since(writable_session, since="2026-01-01")

    # A naive `by_field[change.field]` tally would key this on the literal
    # `None` instead -- silently invisible to anyone reading `by_field` for
    # "which fields moved", which is exactly the failure this bucket exists
    # to prevent.
    assert result["by_field"] == {"(created)": 1}


def test_plan_changes_survive_a_missing_activity(writable_session):
    """A change row whose activity_id matches no activity is reported, not
    dropped -- `activity_changes` has no FK, so this is a real, expected shape,
    not a data-integrity bug the tool should hide from the caller."""
    orphan_id = uuid.uuid4()
    writable_session.add(
        ActivityChange(
            activity_id=orphan_id,
            actor="sync",
            change_type="updated",
            field="channel",
            old_value="Email",
            new_value="Intranet",
            changed_at=REFERENCE,
            version_from=1,
            version_to=2,
        )
    )
    writable_session.flush()

    result = queries.plan_changes_since(writable_session, since="2026-01-01")

    assert result["changes"] == 1
    assert len(result["activities"]) == 1
    orphan_group = result["activities"][0]
    assert orphan_group["activity_id"] == str(orphan_id)
    assert orphan_group["tracking_id"] is None
    assert orphan_group["activity_name"] is None
    assert orphan_group["activity_found"] is False


def test_plan_changes_since_excludes_orphans_once_a_filter_narrows_the_activities(
    writable_session,
):
    """An orphan has no activity to test a filter against, so once a real
    filter is narrowing the activity set, the orphan cannot be a member of
    it -- unlike the no-filter case above, where it is reported under a null
    activity rather than silently dropped."""
    orphan_id = uuid.uuid4()
    writable_session.add(
        ActivityChange(
            activity_id=orphan_id,
            actor="sync",
            change_type="updated",
            field="channel",
            changed_at=REFERENCE,
            version_from=1,
            version_to=2,
        )
    )
    writable_session.flush()

    result = queries.plan_changes_since(
        writable_session, since="2026-01-01", lead_team="Team One"
    )

    assert result["changes"] == 0
    assert result["activities"] == []


def test_plan_changes_since_reports_truncation(writable_session):
    activities = [_activity(activity_name=f"Activity {index}") for index in range(3)]
    writable_session.add_all(activities)
    writable_session.flush()
    writable_session.add_all(
        [
            ActivityChange(
                activity_id=activity.id,
                actor="studio",
                change_type="created",
                changed_at=REFERENCE + timedelta(hours=index),
                version_to=1,
            )
            for index, activity in enumerate(activities)
        ]
    )
    writable_session.flush()

    result = queries.plan_changes_since(writable_session, since="2026-01-01", limit=2)

    assert result["changes"] == 3
    assert result["returned"] == 2
    assert result["truncated"] is True
    assert result["note"] is not None


def test_plan_changes_since_caps_the_changes_inside_one_group(writable_session):
    """`limit` caps groups; the group's own list needs its own cap.

    One nightly-synced activity is enough to produce this shape: `returned: 1`
    with every change row it ever accumulated inlined underneath, plus a
    `by_field` key per column touched -- an unbounded list-shaped answer from
    the one module whose domain resource promises the agent that every
    list-shaped answer is capped.
    """
    activity = _activity()
    writable_session.add(activity)
    writable_session.flush()
    surplus = 5
    writable_session.add_all(
        [
            ActivityChange(
                activity_id=activity.id,
                actor="sync",
                change_type="updated",
                field=f"field_{index}",
                changed_at=REFERENCE + timedelta(minutes=index),
                version_from=index + 1,
                version_to=index + 2,
            )
            for index in range(queries.MAX_CHANGES_PER_ACTIVITY + surplus)
        ]
    )
    writable_session.flush()

    result = queries.plan_changes_since(writable_session, since="2026-01-01")

    assert result["returned"] == 1
    group = result["activities"][0]
    # The true total is still reported -- only the payload is bounded.
    assert group["change_count"] == queries.MAX_CHANGES_PER_ACTIVITY + surplus
    assert len(group["changes"]) == queries.MAX_CHANGES_PER_ACTIVITY
    assert group["changes_truncated"] is True
    # Newest first, like the ungrouped log: the cap keeps the most recent.
    assert group["changes"][0]["field"] == f"field_{queries.MAX_CHANGES_PER_ACTIVITY + surplus - 1}"


def test_plan_changes_since_reports_an_untruncated_group_as_such(writable_session):
    activity = _activity()
    writable_session.add(activity)
    writable_session.flush()
    writable_session.add(
        ActivityChange(
            activity_id=activity.id,
            actor="sync",
            change_type="created",
            changed_at=REFERENCE,
            version_to=1,
        )
    )
    writable_session.flush()

    result = queries.plan_changes_since(writable_session, since="2026-01-01")

    assert result["activities"][0]["changes_truncated"] is False
    assert result["tallies_truncated"] == {
        "by_actor": False,
        "by_change_type": False,
        "by_field": False,
    }


def test_plan_changes_since_caps_its_field_tally(writable_session):
    """`by_field` is a grouped answer too, and nothing bounded it.

    One activity touched on enough distinct columns produces more `by_field`
    keys than any other grouped answer here is allowed to return.
    """
    activity = _activity()
    writable_session.add(activity)
    writable_session.flush()
    surplus = 3
    writable_session.add_all(
        [
            ActivityChange(
                activity_id=activity.id,
                actor=f"actor_{index}",
                change_type="updated",
                field=f"field_{index}",
                changed_at=REFERENCE + timedelta(minutes=index),
                version_from=1,
                version_to=2,
            )
            for index in range(queries.MAX_LIMIT + surplus)
        ]
    )
    writable_session.flush()

    result = queries.plan_changes_since(writable_session, since="2026-01-01")

    assert result["changes"] == queries.MAX_LIMIT + surplus
    assert len(result["by_field"]) == queries.MAX_LIMIT
    assert len(result["by_actor"]) == queries.MAX_LIMIT
    assert result["tallies_truncated"]["by_field"] is True
    assert result["tallies_truncated"]["by_actor"] is True
    assert result["tallies_truncated"]["by_change_type"] is False


@pytest.mark.parametrize("since", ["", "   ", None])
def test_plan_changes_since_refuses_a_blank_boundary(writable_session, since):
    """A blank `since` is a caller slip, not a request for the whole log.

    `since` is a required argument, and `_parse_boundary('')` returns None --
    which used to mean no WHERE clause at all, so the tool answered with the
    entire change log while looking like it had honoured a boundary.
    """
    activity = _activity()
    writable_session.add(activity)
    writable_session.flush()
    writable_session.add(
        ActivityChange(
            activity_id=activity.id,
            actor="sync",
            change_type="created",
            changed_at=REFERENCE,
            version_to=1,
        )
    )
    writable_session.flush()

    result = queries.plan_changes_since(writable_session, since=since)

    assert "error" in result
    assert "YYYY-MM-DD" in result["accepted_formats"]
    assert "activities" not in result


@pytest.mark.parametrize("since", ["last week", "2026-13-45"])
def test_plan_changes_since_refuses_an_unparseable_boundary(writable_session, since):
    """An unreadable date must be an ANSWER, not a traceback.

    Both spellings used to escape `datetime.fromisoformat` as a raw
    `ValueError` ("Invalid isoformat string", "month must be in 1..12") and
    crash the tool call, while the tool description and the docstring both
    promised "a blank or unparseable value returns an error". `"last week"` is
    exactly what a model reaches for when the argument is named `since`, and a
    crashed call teaches it nothing about what to pass instead.
    """
    activity = _activity()
    writable_session.add(activity)
    writable_session.flush()

    result = queries.plan_changes_since(writable_session, since=since)

    assert "error" in result
    assert since in result["error"]
    assert list(queries.ACCEPTED_BOUNDARY_FORMATS) == result["accepted_formats"]
    assert "activities" not in result
    # The note has to point at a real source of dates, because this server has
    # no wall clock to resolve "last week" against.
    assert "database_status" in result["note"]


def test_every_tool_taking_a_date_argument_reports_a_bad_one(writable_session):
    """The rule is the module's, not `plan_changes_since`'s alone.

    `_parse_boundary` backs four filter windows (`start_after`,
    `start_before`, `end_after`, `end_before`) reaching every filtered tool,
    plus the `calendar_load` / `window_comparison` anchors -- all of which
    raised the same way `since` did. Fixing only `since` would have left the
    inconsistency where a model is likeliest to meet it: a date filter on a
    search. Every public tool accepting `**filter_kwargs` is walked here, so a
    tool added without `@_reports_invalid_boundary` fails this test rather
    than crashing an agent.
    """
    # The four filter windows reach `_apply_filters` through `**filter_kwargs`
    # on most tools and are spelled out one by one on `search_activities`, so
    # the walk has to recognise both shapes -- looking only for `**kwargs`
    # silently skips the tool a model is likeliest to pass a date to.
    forwarded = ("start_after", "start_before", "end_after", "end_before")
    date_arguments = (*forwarded, "start_date", "reference", "since")
    # Whatever else a tool demands before it will run at all. Valid values --
    # this test is about the date argument, not about these.
    required = {"since": "2026-01-01", "dimension": "channel"}

    checked: dict[str, list[str]] = {}
    for name, tool in sorted(vars(queries).items()):
        if name.startswith("_") or not inspect.isfunction(tool):
            continue
        if tool.__module__ != queries.__name__:
            continue
        parameters = inspect.signature(tool).parameters
        takes = set(argument for argument in date_arguments if argument in parameters)
        if any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        ):
            takes.update(forwarded)
        if not takes:
            continue
        unsupplied = [
            parameter.name
            for parameter in parameters.values()
            if parameter.kind is inspect.Parameter.KEYWORD_ONLY
            and parameter.default is inspect.Parameter.empty
            and parameter.name not in required
        ]
        assert not unsupplied, f"{name} needs {unsupplied} before it can be called"
        checked[name] = sorted(takes)
        for argument in sorted(takes):
            kwargs = {
                key: value
                for key, value in required.items()
                if key in parameters and key != argument
            }
            result = tool(writable_session, **kwargs, **{argument: "last week"})
            assert isinstance(result, dict), f"{name}({argument}=...)"
            assert "error" in result, f"{name}({argument}=...)"
            assert argument in result["error"], f"{name}({argument}=...)"
            assert result["accepted_formats"] == list(queries.ACCEPTED_BOUNDARY_FORMATS)

    # A guard against the walk quietly matching nothing, and against a tool
    # dropping off it by losing the argument rather than by handling it.
    assert {
        "search_activities",
        "planning_gaps",
        "activity_counts",
        "detect_collisions",
        "pack_overview",
        "lead_time_stats",
        "data_quality",
        "calendar_load",
        "window_comparison",
        "plan_changes_since",
    } <= set(checked)
    assert "start_date" in checked["calendar_load"]
    assert "reference" in checked["window_comparison"]
    assert "since" in checked["plan_changes_since"]


def test_plan_changes_since_excludes_changes_before_the_boundary(writable_session):
    activity = _activity()
    writable_session.add(activity)
    writable_session.flush()
    writable_session.add_all(
        [
            ActivityChange(
                activity_id=activity.id,
                actor="studio",
                change_type="created",
                changed_at=REFERENCE - timedelta(days=365),
                version_to=1,
            ),
            ActivityChange(
                activity_id=activity.id,
                actor="studio",
                change_type="updated",
                field="channel",
                changed_at=REFERENCE,
                version_from=1,
                version_to=2,
            ),
        ]
    )
    writable_session.flush()

    result = queries.plan_changes_since(writable_session, since="2026-01-01")

    assert result["changes"] == 1
    assert result["by_change_type"] == {"updated": 1}


# --------------------------------------------------------------------------
# Domain model resource -- pure text generation, no session, no MCP SDK
# --------------------------------------------------------------------------


def test_domain_model_names_every_trap():
    from pipeline.mcp.domain import domain_model

    text = domain_model()
    for phrase in (
        "two vocabularies",
        "archiv",  # archived is not a relevance signal
        "tracking cluster",
        "other_executives",
        "audience",
        "planning only",
    ):
        assert phrase.lower() in text.lower(), phrase


def test_domain_model_warns_that_free_text_is_untrusted():
    """The warning has to live where the model reads, not only in the README.

    Activity names and descriptions reach the model verbatim from the source
    system. The README says so to the human operator; the domain-model resource
    and the server instructions are the two surfaces built to carry that context
    to the model itself.
    """
    from pipeline.mcp.domain import domain_model

    text = domain_model().lower()
    assert "untrusted" in text
    assert "never as instructions" in text


@pytest.mark.skipif(MCP_SDK_MISSING, reason="the mcp SDK is optional (pip install mcp)")
def test_server_instructions_warn_that_free_text_is_untrusted():
    from pipeline.mcp.server import INSTRUCTIONS

    lowered = INSTRUCTIONS.lower()
    assert "never" in lowered and "as instructions to follow" in lowered


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


def test_domain_model_counts_the_split_columns_instead_of_restating_the_number(
    monkeypatch,
):
    """"Three of them are split for you" must be a count, not a claim.

    Every field list in this resource is generated from `queries.py` precisely
    so it cannot drift; the sentence introducing the generated separator list
    was still spelling its length out by hand, one line above the list itself.
    Add a fourth multi-value column and the list grows while the sentence goes
    on saying three -- a resource contradicting its own next line.
    """
    from pipeline.mcp.domain import domain_model

    assert "three of them" in domain_model().lower()

    monkeypatch.setitem(queries.MULTI_VALUE_SEPARATORS, "partner_team", (",",))
    grown = domain_model()

    assert "four of them" in grown.lower()
    assert "three of them" not in grown.lower()
    assert "`partner_team` splits on" in grown


def test_domain_model_discloses_the_unsplit_multi_value_columns():
    """`channel` and `target_audience` are multi-valued in the data but scalar
    to the filter and group tools -- the resource must say so.

    Trap 4 is generated from `MULTI_VALUE_SEPARATORS`, so it names exactly the
    three columns the tools DO split. Left at that, the resource asserts a data
    shape the database contradicts: a live plan holds `channel="Email,
    Intranet"` alongside `channel="Email"`, so `activity_counts` returns a
    bucket named for the combination, `search_activities(channel="Email")`
    silently misses it, and `pack_overview` counts two channels for the same
    row. Three tools, three answers about one column -- the agent can only
    reconcile them if the resource discloses the fork. This is the same failure
    class an eval run already caught on `audience`: a resource asserting a
    shape the data does not have.
    """
    from pipeline.mcp.domain import domain_model

    text = domain_model()
    trap = text.split("## Trap 4")[1].split("## Trap 5")[0]
    for name in ("channel", "target_audience"):
        assert name in trap, name
    # The three tools that answer differently must all be named, so the agent
    # can tell a genuine contradiction from two different questions.
    for tool in ("search_activities", "activity_counts", "field_values"):
        assert tool in trap, tool
    for tool in ("detect_collisions", "pack_overview"):
        assert tool in trap, tool


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


# --------------------------------------------------------------------------
# Protocol layer -- needs the optional MCP SDK
# --------------------------------------------------------------------------


@pytest.fixture
def settings_file(tmp_path, engine):
    if engine.dialect.name != "sqlite":
        # CPLAN settings deliberately refuse to persist PostgreSQL credentials
        # (they come from the environment), so the subprocess handshake is
        # exercised on SQLite only -- the protocol layer is backend-agnostic.
        pytest.skip("settings files carry a database URL for SQLite only")
    path = tmp_path / "cplan-settings.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "backend": "sqlite",
                "database_url": str(engine.url),
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.mark.skipif(MCP_SDK_MISSING, reason="the mcp SDK is optional (pip install mcp)")
def test_every_tool_is_registered_with_a_description(engine):
    import anyio

    from pipeline.mcp.server import build_server

    server = build_server(engine.url.render_as_string(hide_password=False))
    tools = anyio.run(server.list_tools)

    # No name list here on purpose: a hardcoded set is exactly the drift this
    # module keeps closing elsewhere (FILTERABLE_TEXT_FIELDS vs
    # ENUMERABLE_FIELDS, the completeness rule vs the view). Deriving straight
    # from list_tools() means a newly registered tool is automatically
    # covered and a forgotten description is a red test, not a remembered
    # convention -- `assert tools` alone guards against a vacuous pass if
    # registration silently produced zero tools.
    assert tools
    for tool in tools:
        # The description is the only thing the model sees before choosing.
        assert tool.description and len(tool.description) > 40
        assert tool.input_schema["type"] == "object"


@pytest.mark.skipif(MCP_SDK_MISSING, reason="the mcp SDK is optional (pip install mcp)")
def test_every_new_tool_is_registered_with_a_description(engine):
    """The eight Phase 2 tools specifically, so a rename or omission in the
    protocol layer fails here rather than only in the broader set check above."""
    from pipeline.mcp.server import build_server

    server = build_server(engine.url.render_as_string(hide_password=False))
    tools = asyncio.run(server.list_tools())
    by_name = {tool.name: tool for tool in tools}

    for name in (
        "calendar_load",
        "window_comparison",
        "detect_collisions",
        "pack_overview",
        "lead_time_stats",
        "data_quality",
        "activity_history",
        "plan_changes_since",
    ):
        assert name in by_name, name
        assert by_name[name].description and len(by_name[name].description) > 40


@pytest.mark.skipif(MCP_SDK_MISSING, reason="the mcp SDK is optional (pip install mcp)")
def test_cross_tab_is_exposed_on_activity_counts(engine):
    from pipeline.mcp.server import build_server

    server = build_server(engine.url.render_as_string(hide_password=False))
    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
    assert "second_dimension" in tools["activity_counts"].input_schema["properties"]


@pytest.mark.skipif(MCP_SDK_MISSING, reason="the mcp SDK is optional (pip install mcp)")
def test_collision_description_explains_orchestration_versus_conflict(engine):
    """An agent that cannot tell orchestration from conflict reports well-run
    campaigns as problems, and stops trusting the tool. Both words must be in
    the description the model actually reads before calling it."""
    from pipeline.mcp.server import build_server

    server = build_server(engine.url.render_as_string(hide_password=False))
    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
    description = tools["detect_collisions"].description.lower()
    assert "orchestration" in description
    assert "conflict" in description


@pytest.mark.skipif(MCP_SDK_MISSING, reason="the mcp SDK is optional (pip install mcp)")
def test_pack_overview_description_names_the_pack_key(engine):
    """Grouping by the coarse `campaign` label instead of the pack id makes
    every figure describe the portfolio rather than a planning unit -- the
    description must name the real key so an agent does not guess wrong."""
    from pipeline.mcp.server import build_server

    server = build_server(engine.url.render_as_string(hide_password=False))
    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
    assert "communication_pack_cpid" in tools["pack_overview"].description


@pytest.mark.skipif(MCP_SDK_MISSING, reason="the mcp SDK is optional (pip install mcp)")
def test_stdio_handshake_lists_and_calls_tools(settings_file):
    """A real subprocess handshake: initialize -> tools/list -> tools/call."""
    import anyio
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "pipeline.mcp.server", "--settings", str(settings_file)],
        cwd=str(REPO_ROOT),
    )

    async def exercise():
        async with stdio_client(parameters) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                listed = await session.list_tools()
                status = await session.call_tool("database_status", {})
                search = await session.call_tool(
                    "search_activities", {"query": "Alpha", "limit": 5}
                )
                return listed, status, search

    listed, status, search = anyio.run(exercise)

    assert {tool.name for tool in listed.tools} >= {"database_status", "search_activities"}
    assert status.is_error is False
    assert status.structured_content["activities"]["total"] == 5
    assert search.structured_content["activities"][0]["activity_name"] == "Alpha townhall"


@pytest.mark.skipif(MCP_SDK_MISSING, reason="the mcp SDK is optional (pip install mcp)")
def test_domain_model_is_registered_as_a_resource(engine):
    from pipeline.mcp.server import build_server

    server = build_server(engine.url.render_as_string(hide_password=False))
    uris = {str(resource.uri) for resource in asyncio.run(server.list_resources())}
    assert "cplan://domain-model" in uris


@pytest.mark.skipif(MCP_SDK_MISSING, reason="the mcp SDK is optional (pip install mcp)")
def test_instructions_point_at_the_domain_model_resource(engine):
    from pipeline.mcp.server import build_server

    server = build_server(engine.url.render_as_string(hide_password=False))
    assert "cplan://domain-model" in server.instructions


@pytest.mark.skipif(MCP_SDK_MISSING, reason="the mcp SDK is optional (pip install mcp)")
def test_search_exposes_every_new_filter_over_the_protocol(engine):
    """Every filterable column must be searchable over the protocol, too.

    `ENUMERABLE_FIELDS` and `GROUPABLE_FIELDS` derive from
    `FILTERABLE_TEXT_FIELDS` automatically, but `search_activities`' signature
    and the MCP tool schema restate the list by hand. Driving the loop off
    `FILTERABLE_TEXT_FIELDS` instead of a literal is what stops a newly added
    column from becoming enumerable and groupable but not searchable, with a
    green suite.
    """
    from pipeline.mcp.server import build_server

    server = build_server(engine.url.render_as_string(hide_password=False))
    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
    properties = tools["search_activities"].input_schema["properties"]
    for name in (
        *queries.FILTERABLE_TEXT_FIELDS,
        "end_after", "end_before", "news_digest", "has_tracking_id",
        "has_executive", "locally_modified", "archived_only",
        "strategic_objective", "executive", "max_lead_days", "min_priority_rank",
    ):
        assert name in properties, name


def test_every_filterable_column_is_searchable_in_the_query_layer():
    """The same invariant one layer down, where no MCP SDK is needed.

    The protocol test above needs the optional SDK; this one pins the query
    function's own signature, so the invariant holds even on a machine without
    the SDK installed.
    """
    parameters = set(inspect.signature(queries.search_activities).parameters)
    assert set(queries.FILTERABLE_TEXT_FIELDS) <= parameters


@pytest.mark.skipif(MCP_SDK_MISSING, reason="the mcp SDK is optional (pip install mcp)")
def test_planning_gaps_exposes_grouping_over_the_protocol(engine):
    from pipeline.mcp.server import build_server

    server = build_server(engine.url.render_as_string(hide_password=False))
    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
    assert "group_by" in tools["planning_gaps"].input_schema["properties"]


@pytest.mark.skipif(MCP_SDK_MISSING, reason="the mcp SDK is optional (pip install mcp)")
def test_priority_tool_descriptions_warn_about_the_two_vocabularies(engine):
    from pipeline.mcp.server import build_server

    server = build_server(engine.url.render_as_string(hide_password=False))
    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
    for name in ("search_activities", "activity_counts"):
        assert "vocabular" in tools[name].description.lower(), name


def _plausible_value(name: str, schema: dict) -> object:
    """A type-plausible argument for one declared tool parameter.

    Driven off the parameter's own JSON-schema fragment (plus a handful of
    name-based special cases for the enum-ish parameters, which need a real
    value or the tool legitimately returns an error dict rather than
    exercising the forwarding path) -- not off a hardcoded parameter list, so
    this keeps working when a later task widens a tool's signature.
    """
    if name in ("dimension", "field", "second_dimension"):
        # `second_dimension` must be a real dimension too: an invalid value
        # trips activity_counts' own validation and returns before its
        # filter_kwargs ever reach `_build_filters`, which would silently
        # stop this probe from exercising every OTHER forwarded keyword.
        return "channel"
    if name == "group_by":
        return "lead_team"
    if name == "identifier":
        return "does-not-exist"  # a clean miss is still a non-error result
    if name in (
        "start_after",
        "start_before",
        "end_after",
        "end_before",
        "since",
        "reference",
        "start_date",
    ):
        # Each of these reaches `_parse_boundary` before `_build_filters` ever
        # runs (`since` is required with no default), so an unparseable probe
        # value would raise before the forwarding path is even exercised.
        return "2020-01-01"
    schema_type = schema.get("type")
    if schema_type is None:
        candidates = [
            option.get("type")
            for option in schema.get("anyOf", [])
            if option.get("type") and option.get("type") != "null"
        ]
        schema_type = candidates[0] if candidates else "string"
    if schema_type == "boolean":
        return False
    if schema_type in ("integer", "number"):
        return 1
    return "probe"


@pytest.mark.skipif(MCP_SDK_MISSING, reason="the mcp SDK is optional (pip install mcp)")
def test_every_declared_parameter_can_be_forwarded_without_a_typo(engine):
    """Pins the highest-risk coupling in this task: every parameter a tool's
    schema declares must be a name `queries._build_filters` (or the
    explicit-parameter query functions) actually accepts.

    `activity_counts` and `planning_gaps` forward through `**filter_kwargs`, so
    a typo'd keyword there is NOT a Python-level signature error -- it only
    raises inside `_build_filters`, at call time. Nothing else in this suite
    calls those two tools with more than a couple of parameters (the stdio
    handshake test only exercises `search_activities` with `query`/`limit`),
    so a typo introduced while widening a signature would ship green through
    the rest of the suite. This test drives every tool with every parameter
    its own schema declares -- the same probe used to verify this task by
    hand -- so that coupling is pinned rather than only spot-checked.
    """
    from pipeline.mcp.server import build_server

    server = build_server(engine.url.render_as_string(hide_password=False))

    async def exercise():
        tools = {tool.name: tool for tool in await server.list_tools()}
        results = {}
        for name, tool in tools.items():
            properties = tool.input_schema["properties"]
            arguments = {
                param: _plausible_value(param, schema)
                for param, schema in properties.items()
            }
            results[name] = await server.call_tool(name, arguments)
        return results, set(tools)

    results, tool_names = asyncio.run(exercise())

    # Compared against the LIVE tool set fetched inside `exercise()`, not a
    # literal: a hardcoded name list here is exactly the drift this suite
    # keeps closing elsewhere, and it silently stops covering a newly
    # registered tool rather than failing loudly. `tool_names` is non-empty
    # by construction (`build_server` always registers at least the Phase 1
    # tools), so this still guards against `results` silently dropping an
    # entry while it is built above.
    assert tool_names
    assert set(results) == tool_names
    for name, result in results.items():
        # get_activity legitimately returns a clean miss ({"found": False, ...})
        # for a nonexistent identifier -- that is a successful call, not a
        # protocol error, so `is_error` (not the payload contents) is the
        # right thing to assert on here.
        assert result.is_error is False, f"{name} raised: {result.content}"


@pytest.mark.skipif(MCP_SDK_MISSING, reason="the mcp SDK is optional (pip install mcp)")
def test_stdio_server_keeps_stdout_clean(settings_file):
    """Diagnostics must go to stderr -- a stray print corrupts the transport."""
    server_source = (REPO_ROOT / "pipeline" / "mcp" / "server.py").read_text(encoding="utf-8")

    for line in server_source.splitlines():
        stripped = line.strip()
        if stripped.startswith("print("):
            assert "file=sys.stderr" in stripped, f"print without stderr redirect: {stripped}"
