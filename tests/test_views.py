"""Tests for the Postgres analysis views (`pipeline/api/views.py`).

Views exist for pgAdmin users only -- Postgres-only by design (SQLite users
have the studio). The SQLite no-op is unit-tested directly (no skip needed);
the real view creation/query behavior needs a real PostgreSQL server, so that
part follows the same skip-if-no-`pgserver` pattern as
`tests/test_postgres_embedded.py`.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from pipeline.api.app import Activity, ActivityChange, Base, SyncRun
from pipeline.api.database import create_cplan_engine
from pipeline.api.views import ANALYSIS_VIEWS, ensure_analysis_views
from tests.conftest import postgres_required, postgres_test_database


def test_ensure_analysis_views_is_a_documented_no_op_on_sqlite(tmp_path):
    """SQLite backends never get analysis views -- pgAdmin-only feature.

    Must always run, with or without `pgserver` installed -- the skipif for
    the real-Postgres test below is applied directly on that test function,
    not at module level, so it cannot accidentally skip this one too.
    """
    engine = create_cplan_engine(f"sqlite:///{tmp_path / 'views-no-op.sqlite3'}")
    Base.metadata.create_all(engine)

    ensure_analysis_views(engine)  # must not raise

    assert inspect(engine).get_view_names() == []
    engine.dispose()


@postgres_required
def test_ensure_analysis_views_creates_and_populates_views_on_postgres(tmp_path_factory):
    database_url, teardown = postgres_test_database(tmp_path_factory, "views")
    engine = create_cplan_engine(database_url)
    try:
        Base.metadata.create_all(engine)

        ensure_analysis_views(engine)

        view_names = set(inspect(engine).get_view_names())
        assert set(ANALYSIS_VIEWS) <= view_names

        reference = datetime.now(timezone.utc) - timedelta(days=10)
        start_date = datetime.now(timezone.utc)
        end_date = start_date + timedelta(hours=2)
        complete_id = uuid.uuid4()
        incomplete_id = uuid.uuid4()
        lead_only_id = uuid.uuid4()
        external_id = uuid.uuid4()

        # Every field the variant-aware rule requires of an internal activity;
        # individual fixtures below blank exactly one to exercise a gap.
        internal_complete = dict(
            source_type="internal",
            activity_description="Has a description",
            channel="Email",
            priority="High",
            strategic_objectives="Growth",
            region="EMEA",
            time_zone="Europe/Zurich",
            lead="Jane Doe",
            lead_team="Marketing",
            target_audience="Everyone",
            audience="10-50k",
            business_division="Retail",
            start_date=start_date,
            end_date=end_date,
        )

        with Session(engine) as session:
            session.add_all(
                [
                    Activity(
                        id=complete_id,
                        tracking_id="STA-0000000-260101-0000001-GEN",
                        activity_name="Complete activity",
                        source_created_at=reference,
                        **internal_complete,
                    ),
                    Activity(
                        id=incomplete_id,
                        tracking_id="STA-0000000-260101-0000002-GEN",
                        activity_name="Incomplete activity",
                        # whitespace-only description is the sole gap; every
                        # other required field is present, so is_complete is
                        # false purely because of the description.
                        **{**internal_complete, "activity_description": "   "},
                    ),
                    Activity(
                        id=lead_only_id,
                        tracking_id="STA-0000000-260101-0000003-GEN",
                        activity_name="Lead-only activity",
                        # lead set, lead_team empty: both are now required, so
                        # this is missing lead_team (no either-satisfies shortcut).
                        **{**internal_complete, "lead_team": ""},
                    ),
                    Activity(
                        id=external_id,
                        source_type="external",
                        tracking_id="STA-0000000-260101-0000004-GEN",
                        activity_name="Complete external activity",
                        activity_description="Has a description",
                        channel="Email",
                        priority="High",
                        strategic_objectives="Growth",
                        region="EMEA",
                        time_zone="Europe/Zurich",
                        lead="Ext Lead",
                        lead_team="Ext Team",
                        start_date=start_date,
                        end_date=end_date,
                        source_created_at=reference,
                        # NO target_audience/audience/business_division --
                        # not required for external, so still complete.
                    ),
                ]
            )
            session.add(
                SyncRun(
                    snapshot_path="communications.parquet",
                    created=2,
                    updated=0,
                    unchanged=0,
                    conflicts=0,
                    vanished=0,
                    local_only=0,
                    skipped_no_id=0,
                )
            )
            session.add(
                ActivityChange(
                    activity_id=complete_id,
                    actor="studio",
                    change_type="created",
                    version_to=1,
                )
            )
            session.add(
                ActivityChange(
                    activity_id=complete_id,
                    actor="studio",
                    change_type="updated",
                    field="priority",
                    old_value="Medium",
                    new_value="High",
                    version_from=1,
                    version_to=2,
                )
            )
            session.commit()

        with engine.connect() as connection:
            overview_rows = connection.execute(text("SELECT tracking_id FROM v_activity_overview")).all()
            assert len(overview_rows) == 4

            completeness = {
                row.id: row for row in connection.execute(text("SELECT * FROM v_planning_completeness")).all()
            }
            # Fully planned internal row: every applicable flag false, complete.
            assert completeness[complete_id].missing_description is False
            assert completeness[complete_id].missing_channel is False
            assert completeness[complete_id].missing_priority is False
            assert completeness[complete_id].missing_pillars is False
            assert completeness[complete_id].missing_region is False
            assert completeness[complete_id].missing_start_date is False
            assert completeness[complete_id].missing_end_date is False
            assert completeness[complete_id].missing_time_zone is False
            assert completeness[complete_id].missing_lead is False
            assert completeness[complete_id].missing_lead_team is False
            assert completeness[complete_id].missing_target_audience is False
            assert completeness[complete_id].missing_audience is False
            assert completeness[complete_id].missing_business_division is False
            assert completeness[complete_id].is_complete is True
            # Whitespace-only description is the only gap.
            assert completeness[incomplete_id].missing_description is True
            assert completeness[incomplete_id].is_complete is False
            # lead set, lead_team empty: both are required now (no shortcut).
            assert completeness[lead_only_id].missing_lead is False
            assert completeness[lead_only_id].missing_lead_team is True
            assert completeness[lead_only_id].is_complete is False
            # External row is complete without the internal-only fields, and
            # those flags stay false for it (not required for external).
            assert completeness[external_id].missing_target_audience is False
            assert completeness[external_id].missing_audience is False
            assert completeness[external_id].missing_business_division is False
            assert completeness[external_id].missing_region is False
            assert completeness[external_id].missing_end_date is False
            assert completeness[external_id].is_complete is True

            change_log = connection.execute(
                text(
                    "SELECT field, old_value, new_value, tracking_id, activity_name "
                    "FROM v_change_log WHERE change_type = 'updated'"
                )
            ).all()
            assert len(change_log) == 1
            assert change_log[0].field == "priority"
            assert change_log[0].old_value == "Medium"
            assert change_log[0].new_value == "High"
            assert change_log[0].tracking_id == "STA-0000000-260101-0000001-GEN"
            assert change_log[0].activity_name == "Complete activity"

            sync_history = connection.execute(text("SELECT created FROM v_sync_history")).all()
            assert sync_history[0].created == 2

            by_month = connection.execute(text("SELECT source_type, count FROM v_activities_by_month")).all()
            assert sum(row.count for row in by_month) == 4

            by_channel = connection.execute(text("SELECT channel, count FROM v_activities_by_channel")).all()
            assert {row.channel for row in by_channel} == {"Email"}

            pack_overview = connection.execute(
                text("SELECT pack_id, activity_count, channel_count FROM v_pack_overview")
            ).all()
            assert len(pack_overview) == 1
            assert pack_overview[0].pack_id == "STA-0000000"
            assert pack_overview[0].activity_count == 4
            assert pack_overview[0].channel_count == 1

            lead_times = {
                row.id: row.lead_days for row in connection.execute(text("SELECT id, lead_days FROM v_lead_times")).all()
            }
            expected_lead_days = round((start_date - reference).total_seconds() / 86400)
            assert lead_times[complete_id] == expected_lead_days
            # No source_created_at set -- reference falls back to created_at, still a real number.
            assert lead_times[incomplete_id] is not None

        # Idempotency: re-running on an already-populated database must not error.
        ensure_analysis_views(engine)
    finally:
        engine.dispose()
        teardown()
