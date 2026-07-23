import json
import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Column, MetaData, Table, inspect
from sqlalchemy.orm import Session

from pipeline.api.app import Activity, ActivityChange, Base, SyncRun, create_app
from pipeline.api.database import create_cplan_engine, ensure_schema
from pipeline.api.import_snapshot import seed_records
from pipeline.api.sync_snapshot import format_report, sync_parquet, sync_records


TEST_DATABASE_URL = os.environ.get("CPLAN_TEST_DATABASE_URL")
TEST_BACKENDS = ("sqlite", "postgresql") if TEST_DATABASE_URL else ("sqlite",)


@pytest.fixture(params=TEST_BACKENDS)
def database_url(request, tmp_path):
    url = (
        TEST_DATABASE_URL
        if request.param == "postgresql"
        else f"sqlite:///{tmp_path / 'cplan-sync-test.sqlite3'}"
    )
    engine = create_cplan_engine(url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield url
    Base.metadata.drop_all(engine)
    engine.dispose()


def _snapshot_record(sp_id=1, source_type="internal", activity_name="Snapshot activity", **overrides):
    record = {
        "sp_id": sp_id,
        "source_type": source_type,
        "tracking_id": f"QRREP-{sp_id}",
        "activity_name": activity_name,
        "channel": "Email",
        "start_date": "01.08.2026 09:00",
        "end_date": "01.08.2026 10:00",
        "created": "01.07.2026 08:00",
        "modified": "05.07.2026 08:00",
        "news_digest": "TRUE",
        "is_archive": False,
    }
    record.update(overrides)
    return record


def _activity(database_url, legacy_sp_id):
    engine = create_cplan_engine(database_url)
    try:
        with Session(engine) as session:
            activity = session.query(Activity).filter_by(legacy_sp_id=legacy_sp_id).one()
            session.expunge(activity)
            return activity
    finally:
        engine.dispose()


def _activity_changes(database_url, activity_id):
    engine = create_cplan_engine(database_url)
    try:
        with Session(engine) as session:
            rows = (
                session.query(ActivityChange)
                .filter_by(activity_id=activity_id)
                .order_by(ActivityChange.id)
                .all()
            )
            session.expunge_all()
            return rows
    finally:
        engine.dispose()


def _latest_sync_run_snapshot(database_url):
    engine = create_cplan_engine(database_url)
    try:
        with Session(engine) as session:
            run = session.query(SyncRun).order_by(SyncRun.ran_at.desc()).first()
            return {
                "snapshot_path": run.snapshot_path,
                "created": run.created,
                "updated": run.updated,
                "unchanged": run.unchanged,
                "conflicts": run.conflicts,
                "vanished": run.vanished,
                "local_only": run.local_only,
                "skipped_no_id": run.skipped_no_id,
                "details": json.loads(run.details) if run.details else None,
            }
    finally:
        engine.dispose()


def test_sync_inserts_new_record_from_snapshot(database_url):
    report = sync_records(database_url, [_snapshot_record(sp_id=101)], "test.parquet")

    assert report.created == 1
    assert report.updated == 0
    assert report.conflicts == 0
    assert report.unchanged == 0

    activity = _activity(database_url, 101)
    assert activity.version == 1
    assert activity.synced_version == 1
    assert activity.activity_name == "Snapshot activity"
    assert activity.created_by == "cplan_sync"


def test_sync_insert_writes_one_created_activity_change_row_actor_sync(database_url):
    sync_records(database_url, [_snapshot_record(sp_id=111)], "test.parquet")

    activity = _activity(database_url, 111)
    changes = _activity_changes(database_url, activity.id)

    assert len(changes) == 1
    change = changes[0]
    assert change.actor == "sync"
    assert change.change_type == "created"
    assert change.field is None
    assert change.version_from is None
    assert change.version_to == 1


def test_sync_marks_unchanged_when_stored_values_already_match(database_url):
    record = _snapshot_record(sp_id=102)
    sync_records(database_url, [record], "test.parquet")

    report = sync_records(database_url, [record], "test.parquet")

    assert report.created == 0
    assert report.updated == 0
    assert report.conflicts == 0
    assert report.unchanged == 1

    activity = _activity(database_url, 102)
    assert activity.version == 1
    assert activity.synced_version == 1


def test_sync_updates_when_source_changed_and_row_not_locally_dirty(database_url):
    sync_records(database_url, [_snapshot_record(sp_id=103, activity_name="Original name")], "test.parquet")

    report = sync_records(
        database_url, [_snapshot_record(sp_id=103, activity_name="Updated by source")], "test.parquet"
    )

    assert report.updated == 1
    assert report.conflicts == 0
    assert report.unchanged == 0

    activity = _activity(database_url, 103)
    assert activity.activity_name == "Updated by source"
    assert activity.version == 2
    assert activity.synced_version == 2


def test_sync_update_writes_one_updated_activity_change_row_per_changed_field_actor_sync(database_url):
    sync_records(
        database_url,
        [_snapshot_record(sp_id=112, activity_name="Original name", channel="Email")],
        "test.parquet",
    )

    sync_records(
        database_url,
        [_snapshot_record(sp_id=112, activity_name="Updated by source", channel="Webinar")],
        "test.parquet",
    )

    activity = _activity(database_url, 112)
    changes = [c for c in _activity_changes(database_url, activity.id) if c.change_type == "updated"]
    by_field = {change.field: change for change in changes}

    assert by_field["activity_name"].old_value == "Original name"
    assert by_field["activity_name"].new_value == "Updated by source"
    assert by_field["channel"].old_value == "Email"
    assert by_field["channel"].new_value == "Webinar"
    for change in changes:
        assert change.actor == "sync"
        assert change.version_from == 1
        assert change.version_to == 2


def test_sync_conflict_when_locally_dirty_row_is_overwritten_by_source(database_url):
    sync_records(database_url, [_snapshot_record(sp_id=104, activity_name="Original name")], "test.parquet")

    engine = create_cplan_engine(database_url)
    with Session(engine) as session:
        activity = session.query(Activity).filter_by(legacy_sp_id=104).one()
        # Simulate a UI PATCH: it bumps `version` but never touches `synced_version`
        # (see app.py's update_activity route) -> the row reads as locally dirty.
        activity.activity_name = "Locally edited name"
        activity.version = activity.version + 1
        session.commit()
    engine.dispose()

    report = sync_records(
        database_url, [_snapshot_record(sp_id=104, activity_name="Source updated name")], "test.parquet"
    )

    assert report.conflicts == 1
    assert report.updated == 0

    activity = _activity(database_url, 104)
    assert activity.activity_name == "Source updated name"  # source wins
    assert activity.version == 3
    assert activity.synced_version == 3

    run = _latest_sync_run_snapshot(database_url)
    conflicts = run["details"]["conflicts"]
    assert len(conflicts) == 1
    assert conflicts[0]["legacy_sp_id"] == 104
    field_diff = next(item for item in conflicts[0]["fields"] if item["field"] == "activity_name")
    assert field_diff["local"] == "Locally edited name"
    assert field_diff["incoming"] == "Source updated name"


def test_sync_conflict_still_writes_updated_activity_change_rows(database_url):
    """A conflict is still an applied field change (source wins) -- it must
    show up in history the same as a plain sync update, not be dropped just
    because the report buckets it under `conflicts` instead of `updated`."""
    sync_records(database_url, [_snapshot_record(sp_id=113, activity_name="Original name")], "test.parquet")

    engine = create_cplan_engine(database_url)
    with Session(engine) as session:
        activity = session.query(Activity).filter_by(legacy_sp_id=113).one()
        activity.activity_name = "Locally edited name"
        activity.version = activity.version + 1
        session.commit()
    engine.dispose()

    report = sync_records(
        database_url, [_snapshot_record(sp_id=113, activity_name="Source updated name")], "test.parquet"
    )
    assert report.conflicts == 1
    assert report.updated == 0

    activity = _activity(database_url, 113)
    changes = [c for c in _activity_changes(database_url, activity.id) if c.change_type == "updated"]
    by_field = {change.field: change for change in changes}

    assert by_field["activity_name"].actor == "sync"
    assert by_field["activity_name"].old_value == "Locally edited name"
    assert by_field["activity_name"].new_value == "Source updated name"
    assert by_field["activity_name"].version_from == 2
    assert by_field["activity_name"].version_to == 3


def test_sync_reports_vanished_rows_without_deleting_or_modifying_them(database_url):
    record_a = _snapshot_record(sp_id=105, activity_name="Stays present")
    record_b = _snapshot_record(sp_id=106, activity_name="Will vanish")
    sync_records(database_url, [record_a, record_b], "test.parquet")

    report = sync_records(database_url, [record_a], "test.parquet")

    assert report.vanished == 1
    assert report.created == 0
    assert report.updated == 0

    still_there = _activity(database_url, 106)
    assert still_there.activity_name == "Will vanish"
    assert still_there.version == 1
    assert still_there.synced_version == 1

    run = _latest_sync_run_snapshot(database_url)
    assert run["details"]["vanished"] == [
        {"source_type": "internal", "legacy_sp_id": 106, "tracking_id": "QRREP-106"}
    ]


def test_sync_never_touches_studio_created_local_only_rows(database_url):
    engine = create_cplan_engine(database_url)
    with Session(engine) as session:
        session.add(
            Activity(
                source_type="internal",
                activity_name="Studio-created activity",
                tracking_id="STA-0000000-260101-0000001-GEN",
            )
        )
        session.commit()
    engine.dispose()

    report = sync_records(database_url, [_snapshot_record(sp_id=107)], "test.parquet")

    assert report.local_only == 1

    engine = create_cplan_engine(database_url)
    with Session(engine) as session:
        local_only_activity = session.query(Activity).filter_by(
            tracking_id="STA-0000000-260101-0000001-GEN"
        ).one()
        assert local_only_activity.version == 1
        assert local_only_activity.synced_version is None
    engine.dispose()


def test_sync_skips_snapshot_records_without_an_sp_id(database_url):
    report = sync_records(database_url, [_snapshot_record(sp_id=None)], "test.parquet")

    assert report.skipped_no_id == 1
    assert report.created == 0
    assert report.updated == 0
    assert report.unchanged == 0


def test_sync_is_idempotent_second_run_reports_all_unchanged(database_url):
    records = [_snapshot_record(sp_id=n, activity_name=f"Activity {n}") for n in (201, 202, 203)]

    first_report = sync_records(database_url, records, "test.parquet")
    assert first_report.created == 3

    second_report = sync_records(database_url, records, "test.parquet")

    assert second_report.created == 0
    assert second_report.updated == 0
    assert second_report.conflicts == 0
    assert second_report.vanished == 0
    assert second_report.unchanged == 3


def test_sync_on_empty_db_matches_a_full_seed_via_import_snapshot(tmp_path):
    records = [_snapshot_record(sp_id=n, activity_name=f"Seed activity {n}") for n in (301, 302, 303)]

    seeded_url = f"sqlite:///{tmp_path / 'seeded-via-import.sqlite3'}"
    seeded_count = seed_records(seeded_url, records)

    synced_url = f"sqlite:///{tmp_path / 'seeded-via-sync.sqlite3'}"
    report = sync_records(synced_url, records, "test.parquet")

    assert report.created == seeded_count == 3

    def _fingerprints(url):
        engine = create_cplan_engine(url)
        try:
            with Session(engine) as session:
                rows = session.query(Activity).order_by(Activity.legacy_sp_id).all()
                return [
                    (row.legacy_sp_id, row.tracking_id, row.activity_name, row.channel) for row in rows
                ]
        finally:
            engine.dispose()

    assert _fingerprints(seeded_url) == _fingerprints(synced_url)


def _create_legacy_activities_table_without_synced_version(engine) -> None:
    """Recreate `activities` as it looked before `synced_version` existed, with no `sync_runs` table at all."""
    activities = Base.metadata.tables["activities"]
    legacy_metadata = MetaData()
    legacy_columns = [
        Column(
            column.name,
            column.type,
            primary_key=column.primary_key,
            nullable=column.nullable,
            server_default=column.server_default,
        )
        for column in activities.columns
        if column.name != "synced_version"
    ]
    Table(activities.name, legacy_metadata, *legacy_columns)
    legacy_metadata.create_all(engine)


def test_ensure_schema_adds_synced_version_and_sync_runs_table_to_a_legacy_db(tmp_path):
    engine = create_cplan_engine(f"sqlite:///{tmp_path / 'legacy-sync-topup.sqlite3'}")
    _create_legacy_activities_table_without_synced_version(engine)

    columns_before = {column["name"] for column in inspect(engine).get_columns("activities")}
    assert "synced_version" not in columns_before
    assert not inspect(engine).has_table("sync_runs")

    # Mirrors the app lifespan's bootstrap sequence: create_all only creates missing
    # tables (sync_runs), ensure_schema tops up the missing column on the existing
    # activities table.
    Base.metadata.create_all(engine)
    ensure_schema(engine, Base.metadata)

    columns_after = {column["name"] for column in inspect(engine).get_columns("activities")}
    assert "synced_version" in columns_after
    assert inspect(engine).has_table("sync_runs")

    with Session(engine) as session:
        session.add(
            Activity(
                source_type="internal",
                activity_name="Legacy row upgraded by schema top-up",
                synced_version=1,
            )
        )
        session.commit()
    engine.dispose()


def test_ui_patch_bumps_version_but_leaves_synced_version_untouched(database_url):
    engine = create_cplan_engine(database_url)
    with Session(engine) as session:
        activity = Activity(
            source_type="internal",
            activity_name="Synced then patched",
            legacy_sp_id=108,
            tracking_id="QRREP-108",
            version=1,
            synced_version=1,
        )
        session.add(activity)
        session.commit()
        activity_id = activity.id
    engine.dispose()

    app = create_app(database_url)
    with TestClient(app) as client:
        response = client.patch(
            f"/api/activities/{activity_id}",
            json={"version": 1, "activity_name": "Patched locally"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["version"] == 2
    app.state.engine.dispose()

    engine = create_cplan_engine(database_url)
    with Session(engine) as session:
        stored = session.get(Activity, activity_id)
        assert stored.version == 2
        assert stored.synced_version == 1  # untouched by PATCH
        assert stored.version > stored.synced_version  # locally dirty
    engine.dispose()


def test_patched_then_synced_row_shows_both_studio_and_sync_actors_in_history(database_url):
    engine = create_cplan_engine(database_url)
    with Session(engine) as session:
        activity = Activity(
            source_type="internal",
            activity_name="Synced then patched",
            legacy_sp_id=114,
            tracking_id="QRREP-114",
            version=1,
            synced_version=1,
        )
        session.add(activity)
        session.commit()
        activity_id = activity.id
    engine.dispose()

    app = create_app(database_url)
    with TestClient(app) as client:
        response = client.patch(
            f"/api/activities/{activity_id}",
            json={"version": 1, "activity_name": "Patched locally"},
        )
        assert response.status_code == 200, response.text
    app.state.engine.dispose()

    sync_records(
        database_url,
        [_snapshot_record(sp_id=114, activity_name="Source updated name")],
        "test.parquet",
    )

    changes = _activity_changes(database_url, activity_id)
    actors = {change.actor for change in changes}
    assert actors == {"studio", "sync"}
    assert any(c.actor == "studio" and c.change_type == "updated" for c in changes)
    assert any(c.actor == "sync" for c in changes)


def test_create_all_adds_activity_changes_table_to_a_legacy_db_missing_it(tmp_path):
    """Mirrors `test_ensure_schema_adds_synced_version_and_sync_runs_table_to_a_legacy_db`:
    `activity_changes` is a brand new table, not a new column on an existing
    table, so `Base.metadata.create_all` alone (checkfirst is the default) is
    enough to top it up on an existing database -- no `ensure_schema` change
    needed."""
    engine = create_cplan_engine(f"sqlite:///{tmp_path / 'legacy-activity-changes-topup.sqlite3'}")

    legacy_metadata = MetaData()
    for table in Base.metadata.sorted_tables:
        if table.name == "activity_changes":
            continue
        table.to_metadata(legacy_metadata)
    legacy_metadata.create_all(engine)

    assert not inspect(engine).has_table("activity_changes")
    assert inspect(engine).has_table("activities")
    assert inspect(engine).has_table("sync_runs")

    Base.metadata.create_all(engine)
    ensure_schema(engine, Base.metadata)

    assert inspect(engine).has_table("activity_changes")
    with Session(engine) as session:
        session.add(
            ActivityChange(activity_id=uuid.uuid4(), actor="seed", change_type="created", version_to=1)
        )
        session.commit()
    engine.dispose()


def test_sync_writes_exactly_one_sync_runs_row_per_invocation(database_url):
    sync_records(database_url, [_snapshot_record(sp_id=109)], "run-one.parquet")
    sync_records(database_url, [_snapshot_record(sp_id=109)], "run-two.parquet")

    engine = create_cplan_engine(database_url)
    with Session(engine) as session:
        runs = session.query(SyncRun).all()
        assert len(runs) == 2
        assert {run.snapshot_path for run in runs} == {"run-one.parquet", "run-two.parquet"}
    engine.dispose()


def test_sync_parquet_reads_a_real_parquet_file_and_syncs(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as parquet

    table = pa.Table.from_pylist([_snapshot_record(sp_id=401, activity_name="Parquet activity")])
    parquet_path = tmp_path / "communications.parquet"
    parquet.write_table(table, parquet_path)

    database_url = f"sqlite:///{tmp_path / 'parquet-sync.sqlite3'}"
    report = sync_parquet(database_url, parquet_path)

    assert report.created == 1
    activity = _activity(database_url, 401)
    assert activity.activity_name == "Parquet activity"


def test_format_report_includes_counts_and_first_conflict_field_diff(database_url):
    sync_records(database_url, [_snapshot_record(sp_id=110, activity_name="Original")], "test.parquet")

    engine = create_cplan_engine(database_url)
    with Session(engine) as session:
        activity = session.query(Activity).filter_by(legacy_sp_id=110).one()
        activity.version = activity.version + 1  # simulate a local edit -> dirty
        session.commit()
    engine.dispose()

    report = sync_records(
        database_url, [_snapshot_record(sp_id=110, activity_name="Source changed")], "test.parquet"
    )

    output = format_report(report)

    assert "1 conflicts" in output
    assert "activity_name" in output
    assert "Original" in output
    assert "Source changed" in output
