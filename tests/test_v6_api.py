import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from pipeline.api_v6.app import ActivityRead, Base, create_app, create_environment_app


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
        else f"sqlite:///{tmp_path / 'cplan-v6-test.sqlite3'}"
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
            "tracking_id": "CPLAN-V6-TEST-001",
            "activity_name": "Initial planning activity",
            "activity_description": "Created by the V6 API integration test.",
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


def test_api_serves_the_v6_dashboard(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "CPLAN Planning Studio V6" in response.text


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
            "tracking_id": "CLUSTER-PACKNUM-EXTRA",
            "activity_name": "Analytics fields activity",
            "start_date": "2026-08-03T09:00:00+02:00",
            "source_created_at": "2026-07-20T09:00:00+02:00",
        },
    ).json()

    assert created["tracking_pack_id"] == "CLUSTER-PACKNUM"
    assert created["planning_lead_days"] == 14

    listed = client.get("/api/activities").json()["items"][0]
    assert listed["tracking_pack_id"] == "CLUSTER-PACKNUM"
    assert listed["planning_lead_days"] == 14


def test_create_rejects_empty_activity_name_via_min_length(client):
    response = client.post(
        "/api/activities",
        json={"source_type": "internal", "activity_name": ""},
    )

    assert response.status_code == 422
    errors = response.json()["detail"]
    assert any(err["type"] == "string_too_short" for err in errors)


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
