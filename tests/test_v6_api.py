import os

import pytest
from fastapi.testclient import TestClient

from pipeline.api_v6.app import Base, create_app, create_environment_app


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
