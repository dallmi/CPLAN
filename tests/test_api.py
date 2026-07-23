import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from pipeline.api.app import Activity, ActivityRead, Base, SyncRun, create_app, create_environment_app

TRACKING_ID_PATTERN = re.compile(r"^[A-Z0-9]+-[0-9]+-\d{6}-\d{7}-[A-Z]{2,4}$")


TEST_DATABASE_URL = os.environ.get("CPLAN_TEST_DATABASE_URL")
TEST_BACKENDS = ("sqlite", "postgresql") if TEST_DATABASE_URL else ("sqlite",)


def test_container_factory_preserves_special_characters_in_database_password(monkeypatch):
    monkeypatch.delenv("CPLAN_DATABASE_URL", raising=False)
    monkeypatch.setenv("CPLAN_DB_HOST", "db")
    monkeypatch.setenv("CPLAN_DB_PASSWORD", "local:@/?# test")

    app = create_environment_app()

    assert app.state.engine.url.host == "db"
    assert app.state.engine.url.password == "local:@/?# test"
    app.state.engine.dispose()


@pytest.fixture(params=TEST_BACKENDS)
def client(request, tmp_path):
    database_url = (
        TEST_DATABASE_URL
        if request.param == "postgresql"
        else f"sqlite:///{tmp_path / 'cplan-test.sqlite3'}"
    )
    app = create_app(database_url)
    Base.metadata.drop_all(app.state.engine)
    Base.metadata.create_all(app.state.engine)
    with TestClient(app) as test_client:
        test_client.cplan_backend = request.param
        yield test_client
    Base.metadata.drop_all(app.state.engine)
    app.state.engine.dispose()


def create_activity(client):
    response = client.post(
        "/api/activities",
        json={
            "source_type": "internal",
            "activity_name": "Initial planning activity",
            "activity_description": "Created by the API integration test.",
            "start_date": "2026-08-03T09:00:00+02:00",
            "end_date": "2026-08-03T10:00:00+02:00",
            "news_digest": False,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_activity_datetimes_require_an_explicit_timezone(client):
    response = client.post(
        "/api/activities",
        json={
            "source_type": "internal",
            "activity_name": "Ambiguous local time",
            "start_date": "2026-08-03T09:00:00",
        },
    )

    assert response.status_code == 422


def test_activity_update_rejects_stale_version(client):
    created = create_activity(client)

    updated_response = client.patch(
        f"/api/activities/{created['id']}",
        json={"version": created["version"], "activity_name": "Updated planning activity"},
    )
    assert updated_response.status_code == 200
    updated = updated_response.json()
    assert updated["activity_name"] == "Updated planning activity"
    assert updated["version"] == 2

    stale_response = client.patch(
        f"/api/activities/{created['id']}",
        json={"version": created["version"], "activity_name": "Stale overwrite"},
    )
    assert stale_response.status_code == 409
    assert stale_response.json()["detail"]["code"] == "version_conflict"


def test_partial_update_rejects_invalid_resulting_date_range_without_persisting(client):
    created = create_activity(client)

    response = client.patch(
        f"/api/activities/{created['id']}",
        json={"version": created["version"], "start_date": "2026-08-03T11:00:00+02:00"},
    )

    assert response.status_code == 422
    persisted = client.get("/api/activities").json()["items"][0]
    assert persisted["version"] == created["version"]
    assert persisted["start_date"] == created["start_date"]


def test_partial_update_channel_only_succeeds_on_legacy_invalid_date_range_row(client):
    """A legacy row can already carry end_date < start_date (import_snapshot
    inserts via the ORM directly, bypassing ActivityCreate validation). The
    resulting-range check must only run when the patch itself touches a date
    field, so an unrelated edit (channel only) must not be blocked by a
    pre-existing invalid range it never asked to change.
    """
    with Session(client.app.state.engine) as session:
        activity = Activity(
            source_type="internal",
            activity_name="Legacy row with inverted date range",
            legacy_sp_id=555,
            tracking_id="QRREP-0000058-240709-0000060-EMI",
            start_date=datetime(2026, 8, 10, tzinfo=timezone.utc),
            end_date=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )
        session.add(activity)
        session.commit()
        activity_id = activity.id
        version = activity.version

    response = client.patch(
        f"/api/activities/{activity_id}",
        json={"version": version, "channel": "Email"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["channel"] == "Email"


def test_partial_update_rejects_internal_only_field_for_external_record(client):
    created = client.post(
        "/api/activities",
        json={"source_type": "external", "activity_name": "External activity"},
    ).json()

    response = client.patch(
        f"/api/activities/{created['id']}",
        json={"version": created["version"], "news_digest": True},
    )

    assert response.status_code == 422
    persisted = client.get("/api/activities").json()["items"][0]
    assert persisted["version"] == created["version"]
    assert persisted["news_digest"] is None


def test_partial_update_rejects_null_activity_name_without_persisting(client):
    created = create_activity(client)

    response = client.patch(
        f"/api/activities/{created['id']}",
        json={"version": created["version"], "activity_name": None},
    )

    assert response.status_code == 422
    persisted = client.get("/api/activities").json()["items"][0]
    assert persisted["activity_name"] == created["activity_name"]
    assert persisted["version"] == created["version"]


def test_activity_list_returns_persisted_rows(client):
    created = create_activity(client)

    response = client.get("/api/activities")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == created["id"]
    assert body["items"][0]["start_date"] == "2026-08-03T07:00:00Z"


def test_api_serves_the_studio_dashboard(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "CPLAN Planning Studio" in response.text


def test_health_reports_the_selected_database_backend(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": client.cplan_backend}


def _activity_read(**overrides):
    """Build an ActivityRead directly, bypassing the DB, for computed-field unit tests."""
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    fields = dict(
        id=uuid.uuid4(),
        source_type="internal",
        activity_name="Computed fields fixture activity",
        version=1,
        created_at=now,
        updated_at=now,
    )
    fields.update(overrides)
    return ActivityRead(**fields)


def test_planning_lead_days_uses_source_created_at_when_present():
    reference = datetime(2026, 1, 1, tzinfo=timezone.utc)
    start = reference + timedelta(days=10)

    activity = _activity_read(
        source_created_at=reference,
        created_at=reference - timedelta(days=100),
        start_date=start,
    )

    assert activity.planning_lead_days == 10


def test_planning_lead_days_falls_back_to_created_at_without_source_created_at():
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    start = created + timedelta(days=5)

    activity = _activity_read(
        source_created_at=None,
        created_at=created,
        updated_at=created,
        start_date=start,
    )

    assert activity.planning_lead_days == 5


def test_planning_lead_days_is_none_without_start_date():
    activity = _activity_read(start_date=None)

    assert activity.planning_lead_days is None


def test_planning_lead_days_allows_negative_values():
    reference = datetime(2026, 1, 10, tzinfo=timezone.utc)
    start = reference - timedelta(days=3)

    activity = _activity_read(source_created_at=reference, start_date=start)

    assert activity.planning_lead_days == -3


def test_tracking_pack_id_from_five_part_tracking_id():
    activity = _activity_read(tracking_id="CLUSTER-PACKNUM-EXTRA-EXTRA2-EXTRA3")

    assert activity.tracking_pack_id == "CLUSTER-PACKNUM"


def test_tracking_pack_id_from_two_part_tracking_id():
    activity = _activity_read(tracking_id="ALPHA-BETA")

    assert activity.tracking_pack_id == "ALPHA-BETA"


def test_tracking_pack_id_none_for_single_part_tracking_id():
    activity = _activity_read(tracking_id="SOLO")

    assert activity.tracking_pack_id is None


def test_tracking_pack_id_none_when_tracking_id_missing():
    activity = _activity_read(tracking_id=None)

    assert activity.tracking_pack_id is None


def test_activity_create_and_list_include_computed_analytics_fields(client):
    created = client.post(
        "/api/activities",
        json={
            "source_type": "internal",
            "communication_pack_cpid": "QRREP-0000058",
            "activity_name": "Analytics fields activity",
            "start_date": "2026-08-03T09:00:00+02:00",
            "source_created_at": "2026-07-20T09:00:00+02:00",
        },
    ).json()

    assert created["tracking_pack_id"] == "QRREP-0000058"
    assert created["planning_lead_days"] == 14

    listed = client.get("/api/activities").json()["items"][0]
    assert listed["tracking_pack_id"] == "QRREP-0000058"
    assert listed["planning_lead_days"] == 14


def test_create_rejects_empty_activity_name_via_min_length(client):
    response = client.post(
        "/api/activities",
        json={"source_type": "internal", "activity_name": ""},
    )

    assert response.status_code == 422
    errors = response.json()["detail"]
    assert any(err["type"] == "string_too_short" for err in errors)


def test_create_rejects_end_date_before_start_date(client):
    response = client.post(
        "/api/activities",
        json={
            "source_type": "internal",
            "activity_name": "Inverted date range activity",
            "start_date": "2026-08-10T09:00:00+02:00",
            "end_date": "2026-08-01T09:00:00+02:00",
        },
    )

    assert response.status_code == 422


def test_list_activities_serves_legacy_rows_that_would_fail_create_validation(client):
    """import_snapshot inserts Activity rows directly via the ORM, bypassing
    ActivityCreate entirely. Invalid date ranges and empty activity names are
    expected conditions in imported source data (the dashboard has a
    dedicated invalidDateRanges KPI to surface them) — ActivityRead must
    describe such rows, not police them, so GET /api/activities must return
    200 and serialize both instead of 500ing the whole list.
    """
    with Session(client.app.state.engine) as session:
        session.add_all(
            [
                Activity(
                    source_type="internal",
                    activity_name="Legacy row with inverted date range",
                    legacy_sp_id=201,
                    tracking_id="QRREP-0000058-240709-0000060-EMI",
                    start_date=datetime(2026, 8, 10, tzinfo=timezone.utc),
                    end_date=datetime(2026, 8, 1, tzinfo=timezone.utc),
                ),
                Activity(
                    source_type="internal",
                    activity_name="",
                    legacy_sp_id=202,
                    tracking_id="QRREP-0000058-240709-0000061-EMI",
                ),
            ]
        )
        session.commit()

    response = client.get("/api/activities")

    assert response.status_code == 200
    names = {item["activity_name"] for item in response.json()["items"]}
    assert "Legacy row with inverted date range" in names
    assert "" in names


def test_create_normalizes_whitespace_only_strings_to_none(client):
    created = client.post(
        "/api/activities",
        json={
            "source_type": "internal",
            "activity_name": "Whitespace channel activity",
            "channel": "   ",
        },
    ).json()

    assert created["channel"] is None


def test_patch_empty_string_clears_channel_to_null(client):
    created = client.post(
        "/api/activities",
        json={
            "source_type": "internal",
            "activity_name": "Channel clearing activity",
            "channel": "Email",
        },
    ).json()
    assert created["channel"] == "Email"

    response = client.patch(
        f"/api/activities/{created['id']}",
        json={"version": created["version"], "channel": ""},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["channel"] is None
    assert "planning_lead_days" in body
    assert "tracking_pack_id" in body

    persisted = client.get("/api/activities").json()["items"][0]
    assert persisted["channel"] is None


def test_patch_explicit_null_clears_channel(client):
    created = client.post(
        "/api/activities",
        json={
            "source_type": "internal",
            "activity_name": "Channel clearing via null activity",
            "channel": "Email",
        },
    ).json()

    response = client.patch(
        f"/api/activities/{created['id']}",
        json={"version": created["version"], "channel": None},
    )

    assert response.status_code == 200
    assert response.json()["channel"] is None


def _seed_activity(client, **overrides):
    """Insert an Activity row directly, bypassing the API, to seed a fixed tracking_id/channel pair."""
    fields = dict(
        source_type="internal",
        activity_name="Seed activity",
        tracking_id="STA-0000000-250101-0000001-EMI",
        channel="Email",
    )
    fields.update(overrides)
    with Session(client.app.state.engine) as session:
        session.add(Activity(**fields))
        session.commit()


def test_create_rejects_a_client_supplied_tracking_id(client):
    response = client.post(
        "/api/activities",
        json={
            "source_type": "internal",
            "activity_name": "Client supplied tracking id",
            "tracking_id": "MANUAL-0000001-260101-0000001-EMI",
        },
    )

    assert response.status_code == 422
    errors = response.json()["detail"]
    assert any(err["type"] == "extra_forbidden" for err in errors)


def test_generated_tracking_id_matches_the_documented_format(client):
    created = create_activity(client)

    assert TRACKING_ID_PATTERN.match(created["tracking_id"])


def test_generated_tracking_id_uses_the_communication_pack_cpid_as_prefix(client):
    created = client.post(
        "/api/activities",
        json={
            "source_type": "internal",
            "activity_name": "Pack-linked activity",
            "communication_pack_cpid": "QRREP-0000058",
        },
    ).json()

    assert created["tracking_id"].startswith("QRREP-0000058-")


def test_generated_tracking_id_falls_back_to_the_standalone_prefix(client):
    created = client.post(
        "/api/activities",
        json={"source_type": "internal", "activity_name": "Standalone activity"},
    ).json()

    assert created["tracking_id"].startswith("STA-0000000-")


def test_generated_tracking_id_activity_number_increments_across_creates(client):
    first = client.post(
        "/api/activities",
        json={"source_type": "internal", "activity_name": "First sequenced activity"},
    ).json()
    second = client.post(
        "/api/activities",
        json={"source_type": "internal", "activity_name": "Second sequenced activity"},
    ).json()

    first_number = int(first["tracking_id"].split("-")[3])
    second_number = int(second["tracking_id"].split("-")[3])
    assert second_number == first_number + 1


def test_generated_tracking_id_channel_abbr_uses_majority_vote_from_existing_rows(client):
    _seed_activity(client, tracking_id="STA-0000000-250101-0000001-EMI", channel="Email")
    _seed_activity(client, tracking_id="STA-0000000-250102-0000002-EMI", channel="Email")
    _seed_activity(client, tracking_id="STA-0000000-250103-0000003-EML", channel="Email")

    created = client.post(
        "/api/activities",
        json={"source_type": "internal", "activity_name": "Majority vote activity", "channel": "Email"},
    ).json()

    assert created["tracking_id"].split("-")[4] == "EMI"


def test_generated_tracking_id_channel_abbr_falls_back_to_channel_name_without_a_vote(client):
    created = client.post(
        "/api/activities",
        json={"source_type": "internal", "activity_name": "Webinar activity", "channel": "Webinar"},
    ).json()

    assert created["tracking_id"].split("-")[4] == "WEB"


def test_generated_tracking_id_channel_abbr_is_gen_without_a_channel(client):
    created = client.post(
        "/api/activities",
        json={"source_type": "internal", "activity_name": "Channel-less activity"},
    ).json()

    assert created["tracking_id"].split("-")[4] == "GEN"


def test_generated_tracking_id_channel_abbr_falls_back_to_gen_when_alphabetic_prefix_is_too_short(client):
    created = client.post(
        "/api/activities",
        json={"source_type": "internal", "activity_name": "Short alphabetic channel activity", "channel": "5G"},
    ).json()

    assert created["tracking_id"].split("-")[4] == "GEN"


def test_create_retries_on_tracking_id_collision_from_a_concurrent_insert(client, monkeypatch):
    """The SELECT-based fast path can miss a same-instant concurrent insert (TOCTOU race).

    Simulate that by forcing the initial generation to return an ID that already
    exists in the DB; the create route must catch the resulting IntegrityError,
    roll back, and retry with an incremented activity number instead of erroring.
    """
    duplicate_tracking_id = "STA-0000000-260101-0000001-GEN"
    _seed_activity(client, tracking_id=duplicate_tracking_id, legacy_sp_id=None)

    import pipeline.api.app as app_module

    monkeypatch.setattr(app_module, "_generate_unique_tracking_id", lambda session, payload: duplicate_tracking_id)

    response = client.post(
        "/api/activities",
        json={"source_type": "internal", "activity_name": "Collides with concurrent insert"},
    )

    assert response.status_code == 201, response.text
    assert response.json()["tracking_id"] == "STA-0000000-260101-0000002-GEN"


def test_time_zone_round_trips_through_create_patch_and_read(client):
    created = client.post(
        "/api/activities",
        json={
            "source_type": "internal",
            "activity_name": "Time zone activity",
            "time_zone": "Europe/Zurich",
        },
    ).json()
    assert created["time_zone"] == "Europe/Zurich"

    patched = client.patch(
        f"/api/activities/{created['id']}",
        json={"version": created["version"], "time_zone": "America/New_York"},
    ).json()
    assert patched["time_zone"] == "America/New_York"

    listed = client.get("/api/activities").json()["items"][0]
    assert listed["time_zone"] == "America/New_York"


def test_sync_runs_latest_reports_never_synced_when_no_run_exists(client):
    response = client.get("/api/sync-runs/latest")

    assert response.status_code == 200
    assert response.json() == {"status": "never_synced"}


def test_sync_runs_latest_returns_the_most_recently_run_sync(client):
    with Session(client.app.state.engine) as session:
        session.add(
            SyncRun(
                snapshot_path="older.parquet",
                ran_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                created=1,
                details=json.dumps({"conflicts": [], "vanished": []}),
            )
        )
        session.add(
            SyncRun(
                snapshot_path="newer.parquet",
                ran_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
                updated=5,
                conflicts=2,
                details=json.dumps({"conflicts": [{"field": "activity_name"}], "vanished": []}),
            )
        )
        session.commit()

    response = client.get("/api/sync-runs/latest")

    assert response.status_code == 200
    body = response.json()
    assert body["snapshot_path"] == "newer.parquet"
    assert body["ran_at"] == "2026-01-02T00:00:00Z"
    assert body["updated"] == 5
    assert body["conflicts"] == 2
    assert body["created"] == 0
    assert body["details"]["conflicts"] == [{"field": "activity_name"}]
