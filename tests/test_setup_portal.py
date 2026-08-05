"""setup_portal: portal schema, registry, and SECURITY DEFINER user-management functions."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from pipeline.api.app import Base
from pipeline.api.database import create_cplan_engine
from pipeline.api.setup_portal import PORTAL_OWNER, apply_portal, register_project
from pipeline.api.setup_roles import apply_roles, create_user
from tests.conftest import postgres_required, postgres_test_database

pytestmark = postgres_required


@pytest.fixture(scope="module")
def engine(tmp_path_factory):
    url, teardown = postgres_test_database(tmp_path_factory, "portal")
    engine = create_cplan_engine(url)
    Base.metadata.create_all(engine)
    apply_roles(engine)
    apply_portal(engine)
    create_user(engine, "p_admin", "pw-admin", "admin")      # bootstrap CPLAN admin
    create_user(engine, "p_viewer", "pw-viewer", "viewer")
    yield engine
    engine.dispose()
    teardown()


def _as(engine, username):
    """A connection impersonating `username` via SET ROLE (mirrors the API per-request identity)."""
    connection = engine.connect()
    connection.exec_driver_sql(f'SET ROLE "{username}"')
    connection.commit()
    return connection


def test_apply_portal_is_idempotent_and_creates_objects(engine):
    apply_portal(engine)  # second run must not raise
    with engine.connect() as c:
        assert c.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :n"), {"n": PORTAL_OWNER}).first()
        assert c.execute(text("SELECT rolcreaterole FROM pg_roles WHERE rolname = :n"), {"n": PORTAL_OWNER}).scalar_one() is True
        assert c.execute(text("SELECT 1 FROM information_schema.schemata WHERE schema_name = 'portal'")).first()
        seeded = c.execute(text("SELECT role_prefix FROM portal.projects WHERE slug = 'cplan'")).scalar_one()
        assert seeded == "cplan"


def test_admin_creates_user_via_definer_function(engine):
    admin = _as(engine, "p_admin")
    try:
        admin.exec_driver_sql("SELECT portal.create_user('newbie', 'pw-newbie', 'cplan', 'contributor')")
        admin.commit()
    finally:
        admin.rollback(); admin.exec_driver_sql("RESET ROLE"); admin.commit(); admin.close()
    with engine.connect() as c:
        assert c.execute(text("SELECT rolcanlogin FROM pg_roles WHERE rolname = 'newbie'")).scalar_one() is True
        assert c.execute(text("SELECT pg_has_role('newbie', 'cplan_contributor', 'member')")).scalar_one() is True
        assert c.execute(text("SELECT pg_has_role('cplan_authenticator', 'newbie', 'member')")).scalar_one() is True


def test_non_admin_cannot_execute_functions(engine):
    viewer = _as(engine, "p_viewer")
    try:
        with pytest.raises(ProgrammingError) as exc:
            viewer.exec_driver_sql("SELECT portal.create_user('hacker', 'pw', 'cplan', 'admin')")
        assert exc.value.orig.sqlstate == "42501"
    finally:
        viewer.rollback(); viewer.exec_driver_sql("RESET ROLE"); viewer.commit(); viewer.close()
    with engine.connect() as c:
        assert c.execute(text("SELECT 1 FROM pg_roles WHERE rolname = 'hacker'")).first() is None


def test_function_rejects_unknown_project_role_and_reserved_name(engine):
    admin = _as(engine, "p_admin")
    try:
        for sql in (
            "SELECT portal.create_user('x1', 'pw', 'nope', 'viewer')",       # unknown project
            "SELECT portal.create_user('x2', 'pw', 'cplan', 'superuser')",    # unknown role
            "SELECT portal.create_user('cplan_admin', 'pw', 'cplan', 'viewer')",  # reserved name
        ):
            with pytest.raises(ProgrammingError):
                admin.exec_driver_sql(sql)
            admin.rollback()
    finally:
        admin.exec_driver_sql("RESET ROLE"); admin.commit(); admin.close()


def test_create_user_rejects_duplicate_name(engine):
    admin = _as(engine, "p_admin")
    try:
        admin.exec_driver_sql("SELECT portal.create_user('dupe', 'pw', 'cplan', 'viewer')"); admin.commit()
        with pytest.raises(ProgrammingError) as exc:
            admin.exec_driver_sql("SELECT portal.create_user('dupe', 'pw2', 'cplan', 'editor')")
        # Clean validation raise (P0001), not a raw CREATE ROLE 42710 duplicate_object.
        assert exc.value.orig.sqlstate == "P0001"
        assert "already exists" in str(exc.value.orig)
        admin.rollback()
    finally:
        admin.exec_driver_sql("RESET ROLE"); admin.commit(); admin.close()


def test_mutators_reject_unknown_user(engine):
    admin = _as(engine, "p_admin")
    try:
        for sql in (
            "SELECT portal.set_project_role('ghost', 'cplan', 'editor')",
            "SELECT portal.revoke_project_role('ghost', 'cplan')",
            "SELECT portal.reset_password('ghost', 'pw')",
            "SELECT portal.set_active('ghost', false)",
        ):
            with pytest.raises(ProgrammingError) as exc:
                admin.exec_driver_sql(sql)
            # P0001 validation raise, not 42704 undefined_object.
            assert exc.value.orig.sqlstate == "P0001"
            admin.rollback()
    finally:
        admin.exec_driver_sql("RESET ROLE"); admin.commit(); admin.close()


def test_set_role_password_and_active_functions(engine):
    admin = _as(engine, "p_admin")
    try:
        admin.exec_driver_sql("SELECT portal.create_user('mutable', 'pw0', 'cplan', 'viewer')"); admin.commit()
        admin.exec_driver_sql("SELECT portal.set_project_role('mutable', 'cplan', 'editor')"); admin.commit()
        admin.exec_driver_sql("SELECT portal.reset_password('mutable', 'pw1')"); admin.commit()
        admin.exec_driver_sql("SELECT portal.set_active('mutable', false)"); admin.commit()
    finally:
        admin.rollback(); admin.exec_driver_sql("RESET ROLE"); admin.commit(); admin.close()
    with engine.connect() as c:
        assert c.execute(text("SELECT pg_has_role('mutable', 'cplan_editor', 'member')")).scalar_one() is True
        # NOT pg_has_role(..., 'cplan_viewer', 'member'): that check is transitive
        # over the viewer ⊂ contributor ⊂ editor ⊂ admin group hierarchy apply_roles
        # establishes (GRANT cplan_viewer TO cplan_contributor TO cplan_editor ...),
        # so it is *correctly* True for any cplan_editor member and would stay True
        # no matter how set_project_role is implemented. What set_project_role can
        # and must guarantee is the *direct* group membership, mirroring
        # test_setup_roles.py's test_set_user_role_replaces_membership.
        direct = c.execute(
            text(
                "SELECT r.rolname FROM pg_auth_members m "
                "JOIN pg_roles r ON r.oid = m.roleid "
                "JOIN pg_roles u ON u.oid = m.member WHERE u.rolname = 'mutable' AND r.rolname LIKE 'cplan\\_%'"
            )
        ).scalars().all()
        assert direct == ["cplan_editor"]  # old direct membership revoked, exactly one group
        assert c.execute(text("SELECT rolcanlogin FROM pg_roles WHERE rolname = 'mutable'")).scalar_one() is False


def test_revoke_role_rejects_unknown_project_and_reserved_name(engine):
    admin = _as(engine, "p_admin")
    try:
        for sql in (
            "SELECT portal.revoke_project_role('p_admin', 'nope')",       # unknown project
            "SELECT portal.revoke_project_role('cplan_admin', 'cplan')",  # reserved name
        ):
            with pytest.raises(ProgrammingError) as exc:
                admin.exec_driver_sql(sql)
            assert exc.value.orig.sqlstate == "P0001"
            admin.rollback()
    finally:
        admin.exec_driver_sql("RESET ROLE"); admin.commit(); admin.close()


def test_revoke_role_removes_group_membership_and_preserves_account(engine):
    admin = _as(engine, "p_admin")
    try:
        admin.exec_driver_sql("SELECT portal.create_user('revocable', 'pw0', 'cplan', 'contributor')"); admin.commit()
        admin.exec_driver_sql("SELECT portal.revoke_project_role('revocable', 'cplan')"); admin.commit()
    finally:
        admin.rollback(); admin.exec_driver_sql("RESET ROLE"); admin.commit(); admin.close()
    with engine.connect() as c:
        # No more cplan.* group membership -- gone from portal.users for cplan.
        direct = c.execute(
            text(
                "SELECT r.rolname FROM pg_auth_members m "
                "JOIN pg_roles r ON r.oid = m.roleid "
                "JOIN pg_roles u ON u.oid = m.member WHERE u.rolname = 'revocable' AND r.rolname LIKE 'cplan\\_%'"
            )
        ).scalars().all()
        assert direct == []
        # The account itself (the login role) is untouched by revoking a project role.
        assert c.execute(text("SELECT rolcanlogin FROM pg_roles WHERE rolname = 'revocable'")).scalar_one() is True


def test_revoke_role_blocks_last_active_admin(engine):
    # p_admin is the only active cplan admin at this point in the fixture
    # (the earlier 'second_admin' from test_set_active_allows_disable_when_
    # another_active_admin_exists was left disabled, so it does not count).
    # Revoking the project's last admin would leave nobody able to grant
    # access back through the portal -- the same failure shape set_active's
    # own last-admin guard exists to prevent.
    admin = _as(engine, "p_admin")
    try:
        with pytest.raises(ProgrammingError) as exc:
            admin.exec_driver_sql("SELECT portal.revoke_project_role('p_admin', 'cplan')")
        assert exc.value.orig.sqlstate == "P0001"
        assert "last active admin" in str(exc.value.orig)
        admin.rollback()
    finally:
        admin.exec_driver_sql("RESET ROLE"); admin.commit(); admin.close()
    with engine.connect() as c:
        assert c.execute(text("SELECT pg_has_role('p_admin', 'cplan_admin', 'member')")).scalar_one() is True


def test_revoke_role_allowed_when_another_active_admin_exists(engine):
    # Revoking someone who is NOT the last active admin must succeed --
    # p_admin remains, so 'temp_admin' losing cplan is recoverable through
    # p_admin and is not a lockout.
    admin = _as(engine, "p_admin")
    try:
        admin.exec_driver_sql("SELECT portal.create_user('temp_admin', 'pw-temp', 'cplan', 'admin')"); admin.commit()
        admin.exec_driver_sql("SELECT portal.revoke_project_role('temp_admin', 'cplan')"); admin.commit()
    finally:
        admin.rollback(); admin.exec_driver_sql("RESET ROLE"); admin.commit(); admin.close()
    with engine.connect() as c:
        assert c.execute(text("SELECT pg_has_role('temp_admin', 'cplan_admin', 'member')")).scalar_one() is False
        # Account itself still exists -- only the project role was revoked.
        assert c.execute(text("SELECT 1 FROM pg_roles WHERE rolname = 'temp_admin'")).first()


def test_portal_users_view_lists_project_members(engine):
    with engine.connect() as c:
        rows = {
            (r.username, r.project, r.role, r.active)
            for r in c.execute(text("SELECT username, project, role, active FROM portal.users")).all()
        }
    assert ("p_admin", "cplan", "admin", True) in rows
    assert ("p_viewer", "cplan", "viewer", True) in rows
    assert all(u not in {name for name, *_ in rows} for u in ("cplan_authenticator", "portal_owner"))


def test_register_project_upserts(engine):
    register_project(engine, "demo", "Demo Project", "http://localhost:9001/", "demo")
    register_project(engine, "demo", "Demo Project Renamed", "http://localhost:9001/", "demo")
    with engine.connect() as c:
        name = c.execute(text("SELECT name FROM portal.projects WHERE slug = 'demo'")).scalar_one()
    assert name == "Demo Project Renamed"


def test_set_active_rejects_self_disable(engine):
    admin = _as(engine, "p_admin")
    try:
        with pytest.raises(ProgrammingError) as exc:
            admin.exec_driver_sql("SELECT portal.set_active('p_admin', false)")
        assert exc.value.orig.sqlstate == "P0001"
        assert "own account" in str(exc.value.orig)
        admin.rollback()
    finally:
        admin.exec_driver_sql("RESET ROLE"); admin.commit(); admin.close()
    with engine.connect() as c:
        assert c.execute(text("SELECT rolcanlogin FROM pg_roles WHERE rolname = 'p_admin'")).scalar_one() is True


def test_set_active_blocks_disabling_last_active_admin(engine):
    # p_admin is the only active cplan admin in this fixture. An explicit
    # p_caller bypasses the self-guard, so this exercises the last-admin rule
    # in isolation (the cross-project case a future second registry row makes
    # reachable without any bypass).
    admin = _as(engine, "p_admin")
    try:
        with pytest.raises(ProgrammingError) as exc:
            admin.exec_driver_sql("SELECT portal.set_active('p_admin', false, 'someone_else')")
        assert exc.value.orig.sqlstate == "P0001"
        assert "last active admin" in str(exc.value.orig)
        admin.rollback()
    finally:
        admin.exec_driver_sql("RESET ROLE"); admin.commit(); admin.close()


def test_set_active_allows_disable_when_another_active_admin_exists(engine):
    admin = _as(engine, "p_admin")
    try:
        admin.exec_driver_sql("SELECT portal.create_user('second_admin', 'pw-2nd', 'cplan', 'admin')"); admin.commit()
        admin.exec_driver_sql("SELECT portal.set_active('second_admin', false)"); admin.commit()
        # Re-enabling is never guarded.
        admin.exec_driver_sql("SELECT portal.set_active('second_admin', true)"); admin.commit()
    finally:
        admin.rollback(); admin.exec_driver_sql("RESET ROLE"); admin.commit(); admin.close()
    with engine.connect() as c:
        assert c.execute(text("SELECT rolcanlogin FROM pg_roles WHERE rolname = 'second_admin'")).scalar_one() is True


def test_no_guard_free_set_active_overload_remains(engine):
    # CREATE OR REPLACE cannot change a signature; apply_portal must have
    # dropped the legacy (text, boolean) variant, or the API's two-argument
    # call would silently resolve to the unguarded overload.
    with engine.connect() as c:
        count = c.execute(
            text(
                "SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                "WHERE n.nspname = 'portal' AND p.proname = 'set_active'"
            )
        ).scalar_one()
    assert count == 1


def test_portal_users_view_excludes_group_and_service_roles(engine):
    """The privilege hierarchy makes group roles members of each other; they
    must never list as pseudo-users ("cplan_admin / editor / Disabled")."""
    apply_portal(engine)  # ensure the current view definition
    with engine.connect() as c:
        usernames = set(c.execute(text("SELECT username FROM portal.users")).scalars())
    assert usernames.isdisjoint(
        {"cplan_viewer", "cplan_contributor", "cplan_editor", "cplan_admin", "cplan_sync"}
    )
    assert "p_admin" in usernames
