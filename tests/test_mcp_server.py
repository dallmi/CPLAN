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


def _activity(**overrides):
    """A fully planned internal activity; override to introduce gaps."""
    base = dict(
        id=uuid.uuid4(),
        source_type="internal",
        tracking_id=f"CLU-1-260110-{uuid.uuid4().int % 10_000_000:07d}-EM",
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


def test_search_finds_locally_modified_rows_but_not_never_synced_ones(writable_session):
    writable_session.add_all([
        _activity(activity_name="Diverged", version=3, synced_version=2),
        _activity(activity_name="In step", version=2, synced_version=2),
        _activity(activity_name="Never synced", version=4, synced_version=None),
    ])
    writable_session.flush()
    found = queries.search_activities(writable_session, locally_modified=True)
    assert [row["activity_name"] for row in found["activities"]] == ["Diverged"]


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


def test_field_values_rejects_unknown_field(session):
    result = queries.field_values(session, field="secret")

    assert "error" in result
    assert "channel" in result["supported_fields"]


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

    by_name = {tool.name: tool for tool in tools}
    assert set(by_name) == {
        "database_status",
        "field_values",
        "search_activities",
        "get_activity",
        "planning_gaps",
        "activity_counts",
    }
    for tool in tools:
        # The description is the only thing the model sees before choosing.
        assert tool.description and len(tool.description) > 40
        assert tool.input_schema["type"] == "object"


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


@pytest.mark.skipif(MCP_SDK_MISSING, reason="the mcp SDK is optional (pip install mcp)")
def test_stdio_server_keeps_stdout_clean(settings_file):
    """Diagnostics must go to stderr -- a stray print corrupts the transport."""
    server_source = (REPO_ROOT / "pipeline" / "mcp" / "server.py").read_text(encoding="utf-8")

    for line in server_source.splitlines():
        stripped = line.strip()
        if stripped.startswith("print("):
            assert "file=sys.stderr" in stripped, f"print without stderr redirect: {stripped}"
