"""setup_portal: portal schema, registry, and SECURITY DEFINER user-management functions."""

from __future__ import annotations

import importlib.util

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from pipeline.api.app import Base
from pipeline.api.database import create_cplan_engine, embedded_database_url
from pipeline.api.setup_portal import PORTAL_OWNER, apply_portal, register_project
from pipeline.api.setup_roles import apply_roles, create_user
from pipeline.scripts.cplan_db import stop

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("pgserver") is None,
    reason="pgserver is not installed; the postgres-embedded backend is optional (pip install pgserver)",
)


@pytest.fixture(scope="module")
def engine(tmp_path_factory):
    pgdata = tmp_path_factory.mktemp("portal") / "pgdata"
    engine = create_cplan_engine(embedded_database_url(pgdata))
    Base.metadata.create_all(engine)
    apply_roles(engine)
    apply_portal(engine)
    create_user(engine, "p_admin", "pw-admin", "admin")      # bootstrap CPLAN admin
    create_user(engine, "p_viewer", "pw-viewer", "viewer")
    yield engine
    engine.dispose()
    stop(pgdata)


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
