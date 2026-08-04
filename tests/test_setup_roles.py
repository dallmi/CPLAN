"""setup_roles DDL against a real embedded PostgreSQL — roles, grants, RLS, idempotency."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from pipeline.api.app import Base
from pipeline.api.database import create_cplan_engine
from pipeline.api.setup_roles import (
    ASSIGNABLE_ROLES,
    AUTHENTICATOR,
    GROUP_ROLES,
    apply_roles,
    create_user,
    set_user_active,
    set_user_password,
    set_user_role,
)
from tests.conftest import postgres_required, postgres_test_database

pytestmark = postgres_required


@pytest.fixture(scope="module")
def engine(tmp_path_factory):
    url, teardown = postgres_test_database(tmp_path_factory, "roles")
    engine = create_cplan_engine(url)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()
    teardown()


def _role_exists(connection, name):
    return connection.execute(
        text("SELECT 1 FROM pg_roles WHERE rolname = :n"), {"n": name}
    ).first() is not None


def test_apply_roles_creates_everything_and_is_idempotent(engine):
    apply_roles(engine)
    apply_roles(engine)  # second run must not raise

    with engine.connect() as connection:
        for name in GROUP_ROLES + (AUTHENTICATOR,):
            assert _role_exists(connection, name), name
        # created_by hardened
        row = connection.execute(
            text(
                "SELECT is_nullable, column_default FROM information_schema.columns "
                "WHERE table_name = 'activities' AND column_name = 'created_by'"
            )
        ).one()
        assert row.is_nullable == "NO"
        assert "CURRENT_USER" in row.column_default.upper()
        # actor widened for real usernames
        actor = connection.execute(
            text(
                "SELECT character_maximum_length FROM information_schema.columns "
                "WHERE table_name = 'activity_changes' AND column_name = 'actor'"
            )
        ).scalar_one()
        assert actor == 64
        # RLS enabled + forced
        rls = connection.execute(
            text("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = 'activities'")
        ).one()
        assert rls.relrowsecurity is True and rls.relforcerowsecurity is True
        policies = set(
            connection.execute(text("SELECT policyname FROM pg_policies WHERE tablename = 'activities'")).scalars()
        )
        assert policies == {"read_all", "contrib_insert", "contrib_update", "editor_write", "admin_delete"}
        # Defense-in-depth: the pooled login identity must not transitively
        # inherit the privileges of the users granted TO it (every user role
        # is granted TO cplan_authenticator so it can SET ROLE into them) —
        # only an explicit per-request SET ROLE may impersonate a user.
        assert connection.execute(
            text("SELECT rolinherit FROM pg_roles WHERE rolname = :n"), {"n": AUTHENTICATOR}
        ).scalar_one() is False


def test_create_user_grants_group_and_authenticator_membership(engine):
    apply_roles(engine)
    create_user(engine, "alice.viewer", "pw-alice", "viewer")

    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT pg_has_role('alice.viewer', 'cplan_viewer', 'member')")
        ).scalar_one() is True
        assert connection.execute(
            text(f"SELECT pg_has_role('{AUTHENTICATOR}', 'alice.viewer', 'member')")
        ).scalar_one() is True


def test_set_user_role_replaces_membership(engine):
    apply_roles(engine)
    create_user(engine, "bob", "pw-bob", "viewer")
    set_user_role(engine, "bob", "editor")

    with engine.connect() as connection:
        assert connection.execute(text("SELECT pg_has_role('bob', 'cplan_editor', 'member')")).scalar_one()
        direct = connection.execute(
            text(
                "SELECT r.rolname FROM pg_auth_members m "
                "JOIN pg_roles r ON r.oid = m.roleid "
                "JOIN pg_roles u ON u.oid = m.member WHERE u.rolname = 'bob' AND r.rolname LIKE 'cplan\\_%'"
            )
        ).scalars().all()
        assert direct == ["cplan_editor"]  # old membership revoked, exactly one group


def test_deactivate_blocks_login_flag(engine):
    apply_roles(engine)
    create_user(engine, "carol", "pw-carol", "contributor")
    set_user_active(engine, "carol", False)
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT rolcanlogin FROM pg_roles WHERE rolname = 'carol'")
        ).scalar_one() is False


def test_create_user_rejects_unknown_role(engine):
    apply_roles(engine)
    with pytest.raises(ValueError):
        create_user(engine, "mallory", "pw", "superuser")
    assert "superuser" not in ASSIGNABLE_ROLES


def test_user_mutators_reject_reserved_roles(engine):
    apply_roles(engine)
    with pytest.raises(ValueError):
        set_user_role(engine, "cplan_admin", "viewer")
    with pytest.raises(ValueError):
        set_user_active(engine, "cplan_authenticator", False)
    with pytest.raises(ValueError):
        set_user_password(engine, "cplan_sync", "x")
    with pytest.raises(ValueError):
        create_user(engine, "cplan_viewer", "x", "viewer")


def test_apply_roles_survives_existing_change_log_view(engine):
    """Regression: v_change_log references activity_changes.actor.

    apply_roles must not fail trying to widen a column a view depends on
    (Postgres SQLSTATE 0A000 FeatureNotSupported). New databases already have
    actor as VARCHAR(64), so the widen is skipped and the view is left intact.
    """
    from pipeline.api.views import ensure_analysis_views

    ensure_analysis_views(engine)
    apply_roles(engine)  # must not raise even with the view present
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT 1 FROM pg_views WHERE viewname = 'v_change_log'")
        ).first() is not None


def test_apply_roles_widens_narrow_actor_despite_view(engine):
    """When actor is genuinely narrower than 64, the dependent view is dropped and the widen succeeds."""
    from pipeline.api.views import ensure_analysis_views

    with engine.begin() as connection:
        connection.exec_driver_sql("DROP VIEW IF EXISTS v_change_log")
        connection.exec_driver_sql("ALTER TABLE activity_changes ALTER COLUMN actor TYPE VARCHAR(16)")
    ensure_analysis_views(engine)  # recreate the view so it now blocks a naive ALTER

    apply_roles(engine)  # must drop the view, widen, and not raise

    with engine.connect() as connection:
        length = connection.execute(
            text(
                "SELECT character_maximum_length FROM information_schema.columns "
                "WHERE table_name = 'activity_changes' AND column_name = 'actor'"
            )
        ).scalar_one()
        assert length == 64
    ensure_analysis_views(engine)  # restore the view for any later test
