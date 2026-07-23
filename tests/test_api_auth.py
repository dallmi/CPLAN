"""End-to-end auth + RBAC through the FastAPI TestClient against embedded Postgres."""

from __future__ import annotations

import importlib.util

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from pipeline.api.app import Base, create_app
from pipeline.api.auth import AuthSettings
from pipeline.api.database import create_cplan_engine, embedded_database_url
from pipeline.api.setup_roles import apply_roles, create_user
from pipeline.scripts.cplan_db import stop

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("pgserver") is None,
    reason="pgserver is not installed; the postgres-embedded backend is optional (pip install pgserver)",
)

SETTINGS = AuthSettings(secret="test-secret")
PASSWORDS = {"a_viewer": "pw-v", "a_contrib": "pw-c", "a_editor": "pw-e", "a_admin": "pw-a"}


@pytest.fixture(scope="module")
def api(tmp_path_factory):
    pgdata = tmp_path_factory.mktemp("apiauth") / "pgdata"
    url = embedded_database_url(pgdata)
    engine = create_cplan_engine(url)
    Base.metadata.create_all(engine)
    apply_roles(engine)
    for name, role in (("a_viewer", "viewer"), ("a_contrib", "contributor"), ("a_editor", "editor"), ("a_admin", "admin")):
        create_user(engine, name, PASSWORDS[name], role)
    engine.dispose()
    app = create_app(url, auth_settings=SETTINGS)
    with TestClient(app) as client:
        yield app, url
    stop(pgdata)


def login(app, username):
    client = TestClient(app)
    response = client.post("/api/login", json={"username": username, "password": PASSWORDS[username]})
    assert response.status_code == 200, response.text
    return client


PAYLOAD = {"source_type": "internal", "activity_name": "Auth test activity"}


def test_unauthenticated_requests_are_rejected(api):
    app, _ = api
    client = TestClient(app)
    assert client.get("/api/activities").status_code == 401
    assert client.post("/api/activities", json=PAYLOAD).status_code == 401
    assert client.get("/api/health").status_code == 200  # health stays open


def test_login_rejects_wrong_password_uniformly(api):
    app, _ = api
    client = TestClient(app)
    assert client.post("/api/login", json={"username": "a_viewer", "password": "wrong"}).status_code == 401
    assert client.post("/api/login", json={"username": "ghost", "password": "wrong"}).status_code == 401


def test_me_reports_username_and_role(api):
    app, _ = api
    assert login(app, "a_admin").get("/api/me").json() == {"username": "a_admin", "role": "admin", "auth": True}
    assert login(app, "a_viewer").get("/api/me").json() == {"username": "a_viewer", "role": "viewer", "auth": True}


def test_viewer_reads_but_cannot_create(api):
    app, _ = api
    client = login(app, "a_viewer")
    assert client.get("/api/activities").status_code == 200
    response = client.post("/api/activities", json=PAYLOAD)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "forbidden"


def test_contributor_creates_with_ownership_and_real_actor(api):
    app, url = api
    client = login(app, "a_contrib")
    created = client.post("/api/activities", json=PAYLOAD)
    assert created.status_code == 201
    body = created.json()
    assert body["created_by"] == "a_contrib"
    changes = client.get(f"/api/activities/{body['id']}/changes").json()["items"]
    assert changes[-1]["actor"] == "a_contrib"


def test_contributor_edits_own_but_not_foreign(api):
    app, _ = api
    contrib = login(app, "a_contrib")
    own = contrib.post("/api/activities", json=PAYLOAD).json()
    patch = contrib.patch(f"/api/activities/{own['id']}", json={"version": own["version"], "priority": "High"})
    assert patch.status_code == 200

    editor = login(app, "a_editor")
    foreign = editor.post("/api/activities", json=PAYLOAD).json()
    denied = contrib.patch(f"/api/activities/{foreign['id']}", json={"version": foreign["version"], "priority": "High"})
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "forbidden_not_owner"


def test_editor_edits_foreign_rows(api):
    app, _ = api
    contrib = login(app, "a_contrib")
    row = contrib.post("/api/activities", json=PAYLOAD).json()
    editor = login(app, "a_editor")
    assert editor.patch(
        f"/api/activities/{row['id']}", json={"version": row["version"], "priority": "High"}
    ).status_code == 200


def test_logout_clears_session(api):
    app, _ = api
    client = login(app, "a_viewer")
    assert client.post("/api/logout").status_code == 200
    assert client.get("/api/activities").status_code == 401


def test_only_admin_deletes_and_audit_survives(api):
    app, url = api
    editor = login(app, "a_editor")
    row = editor.post("/api/activities", json=PAYLOAD).json()

    for username in ("a_viewer", "a_contrib", "a_editor"):
        assert login(app, username).delete(f"/api/activities/{row['id']}").status_code == 403

    admin = login(app, "a_admin")
    assert admin.delete(f"/api/activities/{row['id']}").status_code == 204
    assert admin.delete(f"/api/activities/{row['id']}").status_code == 404  # gone

    engine = create_cplan_engine(url)
    try:
        with engine.connect() as connection:
            deleted = connection.execute(
                text(
                    "SELECT actor, old_value FROM activity_changes "
                    "WHERE activity_id = :i AND change_type = 'deleted'"
                ),
                {"i": row["id"]},
            ).one()
        assert deleted.actor == "a_admin"
        assert row["tracking_id"] in deleted.old_value
    finally:
        engine.dispose()
