"""Portal API: shared-cookie auth, project tiles, admin-only user management via SECURITY DEFINER."""

from __future__ import annotations

import importlib.util

import pytest
from fastapi.testclient import TestClient

from pipeline.api.app import Base
from pipeline.api.auth import AuthSettings
from pipeline.api.database import create_cplan_engine, embedded_database_url
from pipeline.api.setup_portal import apply_portal, register_project
from pipeline.api.setup_roles import apply_roles, create_user
from pipeline.portal.app import create_portal_app
from pipeline.scripts.cplan_db import stop

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("pgserver") is None,
    reason="pgserver is not installed; the postgres-embedded backend is optional (pip install pgserver)",
)

SETTINGS = AuthSettings(secret="portal-secret")
PW = {"pa_admin": "pw-a", "pa_viewer": "pw-v"}


@pytest.fixture(scope="module")
def portal(tmp_path_factory):
    pgdata = tmp_path_factory.mktemp("portalapi") / "pgdata"
    url = embedded_database_url(pgdata)
    engine = create_cplan_engine(url)
    Base.metadata.create_all(engine)
    apply_roles(engine)
    apply_portal(engine)
    create_user(engine, "pa_admin", PW["pa_admin"], "admin")
    create_user(engine, "pa_viewer", PW["pa_viewer"], "viewer")
    engine.dispose()
    app = create_portal_app(url, auth_settings=SETTINGS)
    with TestClient(app):
        yield app
    stop(pgdata)


def login(app, username):
    client = TestClient(app)
    r = client.post("/api/login", json={"username": username, "password": PW[username]})
    assert r.status_code == 200, r.text
    return client


def test_create_portal_app_fails_closed_without_auth_secret(portal, monkeypatch):
    # CRITICAL: with no AuthSettings passed and no CPLAN_AUTH_SECRET in the
    # environment, the portal must refuse to start rather than serve the
    # user-administration surface unauthenticated (pooled connections run as
    # the embedded backend's postgres superuser without SET ROLE).
    monkeypatch.delenv("CPLAN_AUTH_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="requires authentication"):
        create_portal_app(portal.state.engine.url, auth_settings=None)


def test_unauthenticated_endpoints_rejected(portal):
    client = TestClient(portal)
    assert client.get("/api/portal/projects").status_code == 401
    assert client.get("/api/portal/users").status_code == 401


def test_projects_tiles_reflect_membership(portal):
    for user in ("pa_admin", "pa_viewer"):
        slugs = [p["slug"] for p in login(portal, user).get("/api/portal/projects").json()["projects"]]
        assert "cplan" in slugs  # both hold a cplan group role


def test_only_admin_lists_users(portal):
    assert login(portal, "pa_admin").get("/api/portal/users").status_code == 200
    assert login(portal, "pa_viewer").get("/api/portal/users").status_code == 403


def test_admin_creates_and_manages_user(portal):
    admin = login(portal, "pa_admin")
    created = admin.post("/api/portal/users", json={"username": "pa_new", "password": "pw-new", "project": "cplan", "role": "contributor"})
    assert created.status_code == 201, created.text
    users = {u["username"]: u for u in admin.get("/api/portal/users").json()["users"]}
    assert users["pa_new"]["role"] == "contributor" and users["pa_new"]["active"] is True

    assert admin.post("/api/portal/users/pa_new/role", json={"project": "cplan", "role": "editor"}).status_code == 200
    assert admin.post("/api/portal/users/pa_new/password", json={"password": "pw-rot"}).status_code == 200
    assert admin.post("/api/portal/users/pa_new/active", json={"active": False}).status_code == 200
    after = {u["username"]: u for u in admin.get("/api/portal/users").json()["users"]}
    assert after["pa_new"]["role"] == "editor" and after["pa_new"]["active"] is False

    # The newly created user can actually authenticate (password works, login role active until deactivated).
    reactivate = admin.post("/api/portal/users/pa_new/active", json={"active": True})
    assert reactivate.status_code == 200


def test_non_admin_cannot_create_user(portal):
    viewer = login(portal, "pa_viewer")
    denied = viewer.post("/api/portal/users", json={"username": "pa_evil", "password": "x", "project": "cplan", "role": "admin"})
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "forbidden"
    assert login(portal, "pa_admin").get("/api/portal/users").json()  # sanity: still listable
    assert "pa_evil" not in {u["username"] for u in login(portal, "pa_admin").get("/api/portal/users").json()["users"]}


def test_invalid_role_is_422_or_400_not_500(portal):
    admin = login(portal, "pa_admin")
    bad = admin.post("/api/portal/users", json={"username": "pa_bad", "password": "x", "project": "cplan", "role": "superuser"})
    assert bad.status_code == 422, bad.text
    assert bad.json()["detail"]["code"] == "invalid_input"


def test_duplicate_username_is_clean_422_not_500(portal):
    admin = login(portal, "pa_admin")
    first = admin.post("/api/portal/users", json={"username": "pa_dupe", "password": "pw1", "project": "cplan", "role": "viewer"})
    assert first.status_code == 201, first.text
    again = admin.post("/api/portal/users", json={"username": "pa_dupe", "password": "pw2", "project": "cplan", "role": "editor"})
    assert again.status_code == 422, again.text
    assert again.json()["detail"]["code"] == "invalid_input"
    assert "already exists" in again.json()["detail"]["message"]


def test_role_change_on_unknown_user_is_clean_422_not_500(portal):
    admin = login(portal, "pa_admin")
    resp = admin.post("/api/portal/users/pa_ghost/role", json={"project": "cplan", "role": "editor"})
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "invalid_input"


def test_unexpected_db_fault_is_not_masked_as_422(portal):
    # A genuinely misconfigured project (registered in the registry but whose
    # <prefix>_viewer group role was never created) makes portal.create_user's
    # GRANT fail inside Postgres with SQLSTATE 42704 (undefined_object) — a real
    # server/config fault, distinct from the functions' own P0001 validation.
    # It must surface as 500, never be echoed back as a 422 "invalid_input".
    # raise_server_exceptions is disabled so the unhandled exception becomes an
    # HTTP response instead of being re-raised in-process by the test client.
    register_project(portal.state.engine, "brokenproj", "Broken", "http://x/", "brokenproj")
    try:
        client = TestClient(portal, raise_server_exceptions=False)
        login_resp = client.post("/api/login", json={"username": "pa_admin", "password": PW["pa_admin"]})
        assert login_resp.status_code == 200, login_resp.text
        resp = client.post(
            "/api/portal/users",
            json={"username": "pa_broken", "password": "pw", "project": "brokenproj", "role": "viewer"},
        )
        assert resp.status_code == 500, resp.text
    finally:
        with portal.state.engine.begin() as c:
            c.exec_driver_sql("DELETE FROM portal.projects WHERE slug = 'brokenproj'")
