"""Portal API: shared-cookie auth, project tiles, admin-only user management via SECURITY DEFINER."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from pipeline.api.app import Base
from pipeline.api.auth import AuthSettings
from pipeline.api.database import create_cplan_engine
from pipeline.api.setup_portal import apply_portal, register_project
from pipeline.api.setup_roles import apply_roles, create_user
from pipeline.portal.app import create_portal_app
from tests.conftest import postgres_required, postgres_test_database

pytestmark = postgres_required

SETTINGS = AuthSettings(secret="portal-secret")
PW = {"pa_admin": "pw-a", "pa_viewer": "pw-v"}


@pytest.fixture(scope="module")
def portal(tmp_path_factory):
    url, teardown = postgres_test_database(tmp_path_factory, "portalapi")
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
    teardown()


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


def test_projects_endpoint_returns_purpose_and_callers_role(portal):
    client = login(portal, "pa_admin")
    body = client.get("/api/portal/projects").json()
    cplan = next(p for p in body["projects"] if p["slug"] == "cplan")
    assert cplan["role"] == "admin"
    assert cplan["purpose"]

    viewer = login(portal, "pa_viewer")
    cplan_as_viewer = next(
        p for p in viewer.get("/api/portal/projects").json()["projects"] if p["slug"] == "cplan"
    )
    assert cplan_as_viewer["role"] == "viewer"


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


def test_username_with_a_colon_is_rejected_before_it_reaches_postgres(portal):
    # The access matrix encodes a grant as `username:slug` in a data-cell
    # attribute and splits it on ':' (matrix.js); a colon in the username
    # would silently break that lookup. CreateUserPayload's pattern rejects
    # it at the pydantic layer -- a request validation error (422), never
    # reaching portal.create_user -- so this is distinct from the P0001
    # "invalid_input" 422s above and does not carry that detail shape.
    admin = login(portal, "pa_admin")
    bad = admin.post("/api/portal/users", json={"username": "pa:evil", "password": "x", "project": "cplan", "role": "viewer"})
    assert bad.status_code == 422, bad.text
    assert "pa:evil" not in {u["username"] for u in admin.get("/api/portal/users").json()["users"]}


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


def test_admin_cannot_disable_own_account_via_endpoint(portal):
    admin = login(portal, "pa_admin")
    denied = admin.post("/api/portal/users/pa_admin/active", json={"active": False})
    assert denied.status_code == 422, denied.text
    assert denied.json()["detail"]["code"] == "invalid_input"
    assert "own account" in denied.json()["detail"]["message"]
    # Still enabled and still able to act.
    assert admin.get("/api/portal/users").status_code == 200


def test_admin_can_revoke_a_project_role(portal):
    client = login(portal, "pa_admin")
    client.post(
        "/api/portal/users",
        json={"username": "pa_temp", "password": "pw-t", "project": "cplan", "role": "viewer"},
    )
    assert any(u["username"] == "pa_temp" for u in client.get("/api/portal/users").json()["users"])

    response = client.post("/api/portal/users/pa_temp/revoke", json={"project": "cplan"})
    assert response.status_code == 200
    assert not any(u["username"] == "pa_temp" for u in client.get("/api/portal/users").json()["users"])


def test_non_admin_cannot_revoke(portal):
    viewer = login(portal, "pa_viewer")
    response = viewer.post("/api/portal/users/pa_admin/revoke", json={"project": "cplan"})
    assert response.status_code == 403


def test_revoke_role_on_unknown_project_is_422(portal):
    admin = login(portal, "pa_admin")
    resp = admin.post("/api/portal/users/pa_viewer/revoke", json={"project": "no-such-project"})
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "invalid_input"


def test_revoke_role_on_unknown_user_is_422(portal):
    admin = login(portal, "pa_admin")
    resp = admin.post("/api/portal/users/pa_ghost/revoke", json={"project": "cplan"})
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "invalid_input"


def test_revoke_last_active_admin_via_endpoint_is_422(portal):
    # pa_admin is the sole active cplan admin throughout this module's
    # fixture -- no other test in this file grants a second account the
    # admin role -- so this exercises the point-4 lockout guard end to end.
    admin = login(portal, "pa_admin")
    resp = admin.post("/api/portal/users/pa_admin/revoke", json={"project": "cplan"})
    assert resp.status_code == 422, resp.text
    assert "last active admin" in resp.json()["detail"]["message"]
    # Still admin afterward and still able to act through the portal.
    assert admin.get("/api/portal/users").status_code == 200


def test_demote_last_active_admin_via_role_endpoint_is_422(portal):
    # The matrix popover offers "No access" right below "Viewer"/"Contributor"/
    # "Editor" -- POST /role must refuse the last-admin lockout exactly like
    # POST /revoke does, since it reaches the identical end state (an
    # adminless project) via the adjacent menu item.
    admin = login(portal, "pa_admin")
    resp = admin.post("/api/portal/users/pa_admin/role", json={"project": "cplan", "role": "viewer"})
    assert resp.status_code == 422, resp.text
    assert "last active admin" in resp.json()["detail"]["message"]
    # Still admin afterward and still able to act through the portal.
    assert admin.get("/api/portal/users").status_code == 200


def test_revoke_leaves_other_project_access_and_the_account_intact(portal):
    admin = login(portal, "pa_admin")
    prefix = "revokeproj"
    groups = [f"{prefix}_{role}" for role in ("viewer", "contributor", "editor", "admin")]
    try:
        with portal.state.engine.begin() as c:
            for group in groups:
                c.exec_driver_sql(f"CREATE ROLE {group} NOLOGIN")
            c.exec_driver_sql(f"GRANT {prefix}_viewer TO {prefix}_contributor")
            c.exec_driver_sql(f"GRANT {prefix}_contributor TO {prefix}_editor")
            c.exec_driver_sql(f"GRANT {prefix}_editor TO {prefix}_admin")
            # A second admin on THIS project too, so this test's revoke below
            # never trips the last-active-admin guard by accident.
            c.exec_driver_sql(f"GRANT {prefix}_admin TO pa_admin")
        register_project(portal.state.engine, "revokeproj", "Revoke Project", "http://x/", prefix)

        created = admin.post(
            "/api/portal/users",
            json={"username": "pa_multi", "password": "pw-multi", "project": "cplan", "role": "viewer"},
        )
        assert created.status_code == 201, created.text
        # Granted directly rather than through the /role endpoint: portal_owner
        # only holds ADMIN OPTION on the cplan_* groups apply_portal wires up
        # (see _ASSIGNABLE_GROUPS), not on this test's ad hoc revokeproj_*
        # groups, so portal.set_project_role's GRANT would 42501 for reasons
        # unrelated to what this test is checking.
        with portal.state.engine.begin() as c:
            c.exec_driver_sql(f"GRANT {prefix}_viewer TO pa_multi")

        response = admin.post("/api/portal/users/pa_multi/revoke", json={"project": "cplan"})
        assert response.status_code == 200, response.text

        rows = {(u["username"], u["project"]) for u in admin.get("/api/portal/users").json()["users"]}
        assert ("pa_multi", "cplan") not in rows
        assert ("pa_multi", "revokeproj") in rows  # access to the OTHER project survives

        with portal.state.engine.connect() as c:
            assert c.exec_driver_sql("SELECT 1 FROM pg_roles WHERE rolname = 'pa_multi'").first()  # account survives
    finally:
        with portal.state.engine.begin() as c:
            c.exec_driver_sql("DELETE FROM portal.projects WHERE slug = 'revokeproj'")
            c.exec_driver_sql("DROP ROLE IF EXISTS pa_multi")
            for group in groups:
                c.exec_driver_sql(f"DROP ROLE IF EXISTS {group}")


def test_project_detail_returns_declared_tiles(portal):
    detail = login(portal, "pa_admin").get("/api/portal/projects/cplan")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["slug"] == "cplan"
    assert body["role"] == "admin"
    kinds = [t["kind"] for t in body["tiles"]]
    assert kinds[0] == "app" and body["tiles"][0]["primary"] is True
    assert kinds[1:] == ["manual", "docs", "data", "changelog", "access", "reports"]


def test_project_detail_states_the_callers_own_role(portal):
    assert login(portal, "pa_viewer").get("/api/portal/projects/cplan").json()["role"] == "viewer"


def test_project_detail_hides_existence_from_the_unentitled(portal):
    # A project the caller holds no role on must be indistinguishable from one
    # that does not exist — otherwise the 403/404 split enumerates the registry.
    register_project(portal.state.engine, "secretproj", "Secret", "http://x/", "secretproj")
    try:
        client = login(portal, "pa_viewer")
        forbidden = client.get("/api/portal/projects/secretproj")
        missing = client.get("/api/portal/projects/nosuchproject")
        assert forbidden.status_code == missing.status_code == 404
        assert forbidden.json() == missing.json()
    finally:
        with portal.state.engine.begin() as c:
            c.exec_driver_sql("DELETE FROM portal.projects WHERE slug = 'secretproj'")


def test_project_detail_is_unauthenticated_401(portal):
    assert TestClient(portal).get("/api/portal/projects/cplan").status_code == 401


def test_a_project_whose_group_roles_were_never_created_is_404_not_500(portal):
    # `pg_has_role` on a name that is not a role raises 42704. The detail
    # endpoint must resolve role names through `to_regrole`, which yields NULL
    # instead, so a half-registered project degrades to "no access".
    register_project(portal.state.engine, "brokenproj2", "Broken", "http://x/", "brokenproj2")
    try:
        client = TestClient(portal, raise_server_exceptions=False)
        client.post("/api/login", json={"username": "pa_admin", "password": PW["pa_admin"]})
        assert client.get("/api/portal/projects/brokenproj2").status_code == 404
    finally:
        with portal.state.engine.begin() as c:
            c.exec_driver_sql("DELETE FROM portal.projects WHERE slug = 'brokenproj2'")


def test_a_second_project_needs_no_portal_code(portal, tmp_path):
    # The measure of the whole design: registering a real second project --
    # its own role group, a registry row, and a manifest beside it -- must
    # produce a working page, with zero changes to pipeline/portal itself.
    # "Its own role group" is not optional set dressing: portal.projects.role_prefix
    # is UNIQUE precisely so a grant on one project can never silently apply
    # to another, so this project gets its own four roles, wired the same way
    # apply_roles wires cplan's (viewer subset of contributor subset of editor
    # subset of admin), rather than borrowing cplan's.
    from pipeline.portal import app as portal_app

    prefix = "secondproj"
    groups = [f"{prefix}_{role}" for role in ("viewer", "contributor", "editor", "admin")]
    original = portal_app.PROJECTS_ROOT
    try:
        # Role creation is the first thing inside the try, not before it, so
        # a failure partway through role setup still hits the finally below
        # instead of leaking roles past the end of this test.
        with portal.state.engine.begin() as c:
            for group in groups:
                c.exec_driver_sql(f"CREATE ROLE {group} NOLOGIN")
            c.exec_driver_sql(f"GRANT {prefix}_viewer TO {prefix}_contributor")
            c.exec_driver_sql(f"GRANT {prefix}_contributor TO {prefix}_editor")
            c.exec_driver_sql(f"GRANT {prefix}_editor TO {prefix}_admin")
            c.exec_driver_sql(f"GRANT {prefix}_admin TO pa_admin")

        register_project(portal.state.engine, "secondproj", "Second Project", "http://second/", prefix)
        projects_root = tmp_path / "projects"
        (projects_root / "secondproj").mkdir(parents=True)
        (projects_root / "secondproj" / "resources.json").write_text(
            '{"purpose": "A second tenant.", "app_title": "Open it",'
            ' "tiles": [{"kind": "access", "title": "Access & support"}]}',
            encoding="utf-8",
        )
        portal_app.PROJECTS_ROOT = projects_root

        body = login(portal, "pa_admin").get("/api/portal/projects/secondproj").json()
        assert body["purpose"] == "A second tenant."
        assert [t["kind"] for t in body["tiles"]] == ["app", "access"]
        assert body["tiles"][0]["title"] == "Open it"
        assert body["role"] == "admin"
        # pa_viewer holds no role on THIS project's group (only cplan's), so
        # a real entitlement check, not just the to_regrole-NULL path, must
        # still 404 -- the two existing "unentitled" tests both used projects
        # with no roles at all and would not have caught this.
        assert login(portal, "pa_viewer").get("/api/portal/projects/secondproj").status_code == 404
    finally:
        portal_app.PROJECTS_ROOT = original
        with portal.state.engine.begin() as c:
            c.exec_driver_sql("DELETE FROM portal.projects WHERE slug = 'secondproj'")
            for group in groups:
                c.exec_driver_sql(f"DROP ROLE IF EXISTS {group}")


def test_role_prefix_must_stay_unique_across_projects(portal):
    # The isolation property the UNIQUE constraint enforces has no other test:
    # without it, two rows could share a role_prefix and a grant on one
    # project would silently apply to the other (see portal.users' JOIN and
    # create_user/set_project_role's role_prefix lookup in setup_portal.py).
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        register_project(portal.state.engine, "dupeprefix", "Dupe", "http://x/", "cplan")


def test_login_records_sign_in_and_display_name_round_trips(portal):
    client = login(portal, "pa_admin")
    client.post("/api/portal/users/pa_viewer/display-name", json={"display_name": "Vera Iewer"})

    row = next(u for u in client.get("/api/portal/users").json()["users"] if u["username"] == "pa_viewer")
    assert row["display_name"] == "Vera Iewer"

    login(portal, "pa_viewer")
    refreshed = next(u for u in client.get("/api/portal/users").json()["users"] if u["username"] == "pa_viewer")
    assert refreshed["last_sign_in"] is not None


def test_a_later_login_updates_last_sign_in(portal):
    admin = login(portal, "pa_admin")
    created = admin.post(
        "/api/portal/users",
        json={"username": "pa_signin", "password": "pw-signin", "project": "cplan", "role": "viewer"},
    )
    assert created.status_code == 201, created.text
    PW["pa_signin"] = "pw-signin"

    login(portal, "pa_signin")
    first = next(
        u for u in admin.get("/api/portal/users").json()["users"] if u["username"] == "pa_signin"
    )
    assert first["last_sign_in"] is not None

    login(portal, "pa_signin")
    second = next(
        u for u in admin.get("/api/portal/users").json()["users"] if u["username"] == "pa_signin"
    )
    assert second["last_sign_in"] is not None
    assert second["last_sign_in"] >= first["last_sign_in"]


def test_a_user_with_no_profile_row_still_appears_with_nulls(portal):
    admin = login(portal, "pa_admin")
    created = admin.post(
        "/api/portal/users",
        json={"username": "pa_noprofile", "password": "pw-noprofile", "project": "cplan", "role": "viewer"},
    )
    assert created.status_code == 201, created.text
    # Never logged in, no display name set -- portal.user_profile has no row
    # for this account at all, so the LEFT JOIN in portal.users must still
    # surface the account with both columns null rather than dropping it.
    row = next(
        u for u in admin.get("/api/portal/users").json()["users"] if u["username"] == "pa_noprofile"
    )
    assert row["display_name"] is None
    assert row["last_sign_in"] is None


def test_set_display_name_is_refused_for_non_admin(portal):
    viewer = login(portal, "pa_viewer")
    denied = viewer.post("/api/portal/users/pa_admin/display-name", json={"display_name": "Someone Else"})
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "forbidden"


def test_a_failed_login_does_not_stamp_last_sign_in(portal):
    # Point 6: a wrong password never authenticates, so it must never look
    # like a sign-in either -- otherwise "last sign-in" would silently record
    # login *attempts* (including someone else's guesses) rather than actual
    # sessions, which is both misleading to an admin reading the users table
    # and would mask a brute-force attempt as if it had succeeded.
    admin = login(portal, "pa_admin")
    created = admin.post(
        "/api/portal/users",
        json={"username": "pa_wrongpw", "password": "pw-correct", "project": "cplan", "role": "viewer"},
    )
    assert created.status_code == 201, created.text
    PW["pa_wrongpw"] = "pw-correct"

    bad = TestClient(portal).post("/api/login", json={"username": "pa_wrongpw", "password": "not-the-password"})
    assert bad.status_code == 401

    row = next(
        u for u in admin.get("/api/portal/users").json()["users"] if u["username"] == "pa_wrongpw"
    )
    assert row["last_sign_in"] is None

    login(portal, "pa_wrongpw")
    row = next(
        u for u in admin.get("/api/portal/users").json()["users"] if u["username"] == "pa_wrongpw"
    )
    assert row["last_sign_in"] is not None


def test_login_succeeds_even_if_record_sign_in_fails(portal):
    """A bookkeeping timestamp must never block a successful credential check
    -- most obviously on a database that has not yet run the current
    apply_portal, where portal.record_sign_in does not exist yet. Simulate
    exactly that by dropping the function, confirm login still returns 200,
    then restore it (via apply_portal) so later tests are unaffected."""
    with portal.state.engine.begin() as c:
        c.exec_driver_sql("DROP FUNCTION portal.record_sign_in(text)")
    try:
        r = TestClient(portal).post("/api/login", json={"username": "pa_viewer", "password": PW["pa_viewer"]})
        assert r.status_code == 200, r.text
    finally:
        apply_portal(portal.state.engine)  # restore the function for every later test


def test_create_user_with_display_name_is_atomic(portal):
    """create_user and set_display_name used to run as two separate
    transactions: if the second failed, the account existed but the client
    saw an error, and a retry then hit "already exists". Force the second
    call to fail (temporarily revoke its EXECUTE grant) and confirm the whole
    request fails with no half-created account left behind; restore the
    grant and confirm the same payload then succeeds cleanly, with both
    changes landing together."""
    admin = login(portal, "pa_admin")
    payload = {
        "username": "pa_atomic",
        "password": "pw-atomic",
        "project": "cplan",
        "role": "viewer",
        "display_name": "Atomic User",
    }

    with portal.state.engine.begin() as c:
        c.exec_driver_sql("REVOKE EXECUTE ON FUNCTION portal.set_display_name(text, text) FROM cplan_admin")
    try:
        failed = admin.post("/api/portal/users", json=payload)
        assert failed.status_code == 403, failed.text
        users = admin.get("/api/portal/users").json()["users"]
        assert not any(u["username"] == "pa_atomic" for u in users)  # create_user rolled back with it
    finally:
        with portal.state.engine.begin() as c:
            c.exec_driver_sql("GRANT EXECUTE ON FUNCTION portal.set_display_name(text, text) TO cplan_admin")

    retried = admin.post("/api/portal/users", json=payload)
    assert retried.status_code == 201, retried.text
    row = next(u for u in admin.get("/api/portal/users").json()["users"] if u["username"] == "pa_atomic")
    assert row["display_name"] == "Atomic User"


def test_projects_list_survives_a_project_with_no_group_roles(portal):
    # The list endpoint used to pass bare role names to pg_has_role, which
    # raises 42704 for a name that is not a role -- taking the landing page
    # down for every caller, not just the one probing the half-registered
    # project. to_regrole must make this endpoint survive it too, the same
    # way project_detail already does.
    register_project(portal.state.engine, "halfreg", "Half Registered", "http://x/", "halfreg")
    try:
        resp = login(portal, "pa_admin").get("/api/portal/projects")
        assert resp.status_code == 200, resp.text
    finally:
        with portal.state.engine.begin() as c:
            c.exec_driver_sql("DELETE FROM portal.projects WHERE slug = 'halfreg'")
