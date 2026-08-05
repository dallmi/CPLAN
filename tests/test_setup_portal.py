"""setup_portal: portal schema, registry, and SECURITY DEFINER user-management functions."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from pipeline.api.app import Base
from pipeline.api.database import create_cplan_engine
from pipeline.api.setup_portal import PORTAL_OWNER, apply_portal, register_project
from pipeline.api.setup_roles import AUTHENTICATOR, apply_roles, create_user
from tests.conftest import postgres_required, postgres_test_database, scram_literal

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
        admin.exec_driver_sql(f"SELECT portal.create_user('newbie', {scram_literal('pw-newbie')}, 'cplan', 'contributor')")
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
            viewer.exec_driver_sql(f"SELECT portal.create_user('hacker', {scram_literal('pw')}, 'cplan', 'admin')")
        assert exc.value.orig.sqlstate == "42501"
    finally:
        viewer.rollback(); viewer.exec_driver_sql("RESET ROLE"); viewer.commit(); viewer.close()
    with engine.connect() as c:
        assert c.execute(text("SELECT 1 FROM pg_roles WHERE rolname = 'hacker'")).first() is None


def test_non_admin_cannot_execute_any_definer_function(engine):
    """The test above only probes create_user -- exactly the gap that let
    record_sign_in's over-grant to cplan_admin (fixed alongside this test)
    survive unnoticed. Cover every function in _FUNCTIONS here instead of
    just the one an earlier test happens to name, so a future over-grant on
    any of them fails a test instead of shipping quietly."""
    viewer = _as(engine, "p_viewer")
    try:
        for sql in (
            f"SELECT portal.create_user('priv_probe', {scram_literal('pw')}, 'cplan', 'viewer')",
            "SELECT portal.set_project_role('p_admin', 'cplan', 'viewer')",
            "SELECT portal.revoke_project_role('p_admin', 'cplan')",
            f"SELECT portal.reset_password('p_admin', {scram_literal('pw')})",
            "SELECT portal.set_active('p_admin', false)",
            "SELECT portal.set_display_name('p_admin', 'Someone Else')",
        ):
            with pytest.raises(ProgrammingError) as exc:
                viewer.exec_driver_sql(sql)
            assert exc.value.orig.sqlstate == "42501"
            viewer.rollback()
    finally:
        viewer.exec_driver_sql("RESET ROLE"); viewer.commit(); viewer.close()
    with engine.connect() as c:
        assert c.execute(text("SELECT 1 FROM pg_roles WHERE rolname = 'priv_probe'")).first() is None
        # None of the rejected calls above touched p_admin's real account.
        assert c.execute(text("SELECT pg_has_role('p_admin', 'cplan_admin', 'member')")).scalar_one() is True
        assert c.execute(text("SELECT rolcanlogin FROM pg_roles WHERE rolname = 'p_admin'")).scalar_one() is True


def test_record_sign_in_is_not_executable_by_cplan_admin(engine):
    """record_sign_in is granted only to the service role (cplan_authenticator)
    -- unlike every function in _FUNCTIONS, no admin-facing endpoint calls it,
    so a grant to cplan_admin on top would be unused attack surface (an admin
    could stamp an arbitrary username's last_sign_in, or insert a profile row
    for a name of their choosing). It must fail exactly like a non-admin's
    call to any other function: 42501, not a successful write."""
    admin = _as(engine, "p_admin")
    try:
        with pytest.raises(ProgrammingError) as exc:
            admin.exec_driver_sql("SELECT portal.record_sign_in('p_admin')")
        assert exc.value.orig.sqlstate == "42501"
        admin.rollback()
    finally:
        admin.exec_driver_sql("RESET ROLE"); admin.commit(); admin.close()


def test_apply_portal_revokes_a_stale_cplan_admin_grant_on_record_sign_in(engine):
    """CREATE OR REPLACE FUNCTION preserves an existing function's ACL rather
    than resetting it. A database that ran a previous apply_portal -- back
    when record_sign_in was still part of the _FUNCTIONS loop and so received
    `GRANT EXECUTE ... TO cplan_admin` -- would keep that grant forever if
    apply_portal only ever granted and revoked from PUBLIC. Simulate exactly
    that stale state by granting EXECUTE to cplan_admin directly, re-run
    apply_portal, and assert the grant is gone. test_record_sign_in_is_not_
    executable_by_cplan_admin above only proves this on a fresh install,
    where the grant was never made in the first place -- it cannot catch a
    regression that reintroduces the grant without also reintroducing an
    explicit revoke."""
    with engine.begin() as c:
        c.exec_driver_sql("GRANT EXECUTE ON FUNCTION portal.record_sign_in(text) TO cplan_admin")
        assert c.execute(
            text("SELECT has_function_privilege('cplan_admin', 'portal.record_sign_in(text)', 'EXECUTE')")
        ).scalar_one() is True  # the stale-grant simulation actually took

    apply_portal(engine)

    with engine.connect() as c:
        assert c.execute(
            text("SELECT has_function_privilege('cplan_admin', 'portal.record_sign_in(text)', 'EXECUTE')")
        ).scalar_one() is False
        assert c.execute(
            text(f"SELECT has_function_privilege('{AUTHENTICATOR}', 'portal.record_sign_in(text)', 'EXECUTE')")
        ).scalar_one() is True  # the grant it does need survives the upgrade


def test_function_rejects_unknown_project_role_and_reserved_name(engine):
    admin = _as(engine, "p_admin")
    try:
        for sql in (
            f"SELECT portal.create_user('x1', {scram_literal('pw')}, 'nope', 'viewer')",       # unknown project
            f"SELECT portal.create_user('x2', {scram_literal('pw')}, 'cplan', 'superuser')",    # unknown role
            f"SELECT portal.create_user('cplan_admin', {scram_literal('pw')}, 'cplan', 'viewer')",  # reserved name
        ):
            with pytest.raises(ProgrammingError):
                admin.exec_driver_sql(sql)
            admin.rollback()
    finally:
        admin.exec_driver_sql("RESET ROLE"); admin.commit(); admin.close()


def test_create_user_rejects_duplicate_name(engine):
    admin = _as(engine, "p_admin")
    try:
        admin.exec_driver_sql(f"SELECT portal.create_user('dupe', {scram_literal('pw')}, 'cplan', 'viewer')"); admin.commit()
        with pytest.raises(ProgrammingError) as exc:
            admin.exec_driver_sql(f"SELECT portal.create_user('dupe', {scram_literal('pw2')}, 'cplan', 'editor')")
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
            f"SELECT portal.reset_password('ghost', {scram_literal('pw')})",
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
        admin.exec_driver_sql(f"SELECT portal.create_user('mutable', {scram_literal('pw0')}, 'cplan', 'viewer')"); admin.commit()
        admin.exec_driver_sql("SELECT portal.set_project_role('mutable', 'cplan', 'editor')"); admin.commit()
        admin.exec_driver_sql(f"SELECT portal.reset_password('mutable', {scram_literal('pw1')})"); admin.commit()
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


@pytest.mark.parametrize("role", ["viewer", "contributor", "editor"])
def test_set_role_refuses_to_demote_the_last_active_admin(engine, role):
    # p_admin is the only active cplan admin in this fixture. Moving them to
    # any role but admin empties the admin group exactly as
    # revoke_project_role would -- reachable from the very next line of the
    # same matrix popover -- so set_project_role must refuse it too.
    admin = _as(engine, "p_admin")
    try:
        with pytest.raises(ProgrammingError) as exc:
            admin.exec_driver_sql(f"SELECT portal.set_project_role('p_admin', 'cplan', '{role}')")
        assert exc.value.orig.sqlstate == "P0001"
        assert "last active admin" in str(exc.value.orig)
        admin.rollback()
    finally:
        admin.exec_driver_sql("RESET ROLE"); admin.commit(); admin.close()
    with engine.connect() as c:
        assert c.execute(text("SELECT pg_has_role('p_admin', 'cplan_admin', 'member')")).scalar_one() is True


def test_set_role_allows_re_granting_admin_to_the_sole_admin(engine):
    # p_role = 'admin' must stay the no-op it already is: granting admin to
    # someone who already holds it never empties the admin group, so the
    # guard must not fire here even though p_admin is the sole active admin.
    admin = _as(engine, "p_admin")
    try:
        admin.exec_driver_sql("SELECT portal.set_project_role('p_admin', 'cplan', 'admin')"); admin.commit()
    finally:
        admin.rollback(); admin.exec_driver_sql("RESET ROLE"); admin.commit(); admin.close()
    with engine.connect() as c:
        assert c.execute(text("SELECT pg_has_role('p_admin', 'cplan_admin', 'member')")).scalar_one() is True


def test_set_role_allows_demoting_a_non_last_admin(engine):
    # A second ACTIVE admin exists here ('extra_admin'), so demoting it must
    # still work -- p_admin remains, and this is not the lockout case.
    #
    # Cleanup below is unconditional (outer try/finally): `engine` is a
    # module-scoped fixture shared with every later test in this file,
    # including the last-admin guard tests. A failure between the create and
    # the demote step would otherwise leave 'extra_admin' behind as a second
    # ACTIVE ADMIN and silently invalidate every "p_admin is the only active
    # admin" assumption those tests make.
    try:
        admin = _as(engine, "p_admin")
        try:
            admin.exec_driver_sql(f"SELECT portal.create_user('extra_admin', {scram_literal('pw-extra')}, 'cplan', 'admin')"); admin.commit()
            admin.exec_driver_sql("SELECT portal.set_project_role('extra_admin', 'cplan', 'viewer')"); admin.commit()
        finally:
            admin.rollback(); admin.exec_driver_sql("RESET ROLE"); admin.commit(); admin.close()
        with engine.connect() as c:
            direct = c.execute(
                text(
                    "SELECT r.rolname FROM pg_auth_members m "
                    "JOIN pg_roles r ON r.oid = m.roleid "
                    "JOIN pg_roles u ON u.oid = m.member WHERE u.rolname = 'extra_admin' AND r.rolname LIKE 'cplan\\_%'"
                )
            ).scalars().all()
            assert direct == ["cplan_viewer"]
    finally:
        cleanup = _as(engine, "p_admin")
        try:
            # Idempotent-safe whether the demote step above ran or not:
            # revoke_project_role strips all four possible group roles
            # unconditionally and only refuses when the target is the LAST
            # active admin -- p_admin always remains, so this always
            # succeeds once 'extra_admin' exists at all.
            cleanup.exec_driver_sql("SELECT portal.revoke_project_role('extra_admin', 'cplan')")
            cleanup.commit()
        except ProgrammingError:
            cleanup.rollback()  # 'extra_admin' never existed (create_user itself failed) -- nothing to clean up
        finally:
            cleanup.exec_driver_sql("RESET ROLE"); cleanup.commit(); cleanup.close()


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
        admin.exec_driver_sql(f"SELECT portal.create_user('revocable', {scram_literal('pw0')}, 'cplan', 'contributor')"); admin.commit()
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
    # Earlier revision of this test claimed "p_admin is the only active cplan
    # admin ... the earlier 'second_admin' ... was left disabled" -- false:
    # 'second_admin' is created (and later re-enabled) by
    # test_set_active_allows_disable_when_another_active_admin_exists, which
    # runs AFTER this test in file order, so at this point it does not exist
    # at all. The test happened to pass anyway (nothing else in this module
    # leaves a stray active cplan admin around before this point), but that
    # was true by file order, not by anything this test established itself.
    # Create and disable a second admin here instead, so "p_admin is the
    # only ACTIVE admin" is something this test proves, not assumes.
    #
    # Cleanup below is unconditional (outer try/finally) for the same reason
    # as its neighbour test_set_role_allows_demoting_a_non_last_admin: this
    # `engine` fixture is module-scoped and shared with every later test, so
    # leaving 'revoke_guard_admin' behind -- even disabled -- is unwanted
    # residue rather than something a later test should have to account for.
    try:
        admin = _as(engine, "p_admin")
        try:
            admin.exec_driver_sql(f"SELECT portal.create_user('revoke_guard_admin', {scram_literal('pw-guard')}, 'cplan', 'admin')"); admin.commit()
            admin.exec_driver_sql("SELECT portal.set_active('revoke_guard_admin', false)"); admin.commit()
            with pytest.raises(ProgrammingError) as exc:
                admin.exec_driver_sql("SELECT portal.revoke_project_role('p_admin', 'cplan')")
            assert exc.value.orig.sqlstate == "P0001"
            assert "last active admin" in str(exc.value.orig)
            admin.rollback()
        finally:
            admin.exec_driver_sql("RESET ROLE"); admin.commit(); admin.close()
        with engine.connect() as c:
            assert c.execute(text("SELECT pg_has_role('p_admin', 'cplan_admin', 'member')")).scalar_one() is True
    finally:
        cleanup = _as(engine, "p_admin")
        try:
            cleanup.exec_driver_sql("SELECT portal.revoke_project_role('revoke_guard_admin', 'cplan')")
            cleanup.commit()
        except ProgrammingError:
            cleanup.rollback()  # 'revoke_guard_admin' never existed (create_user itself failed) -- nothing to clean up
        finally:
            cleanup.exec_driver_sql("RESET ROLE"); cleanup.commit(); cleanup.close()


def test_revoke_role_allowed_when_another_active_admin_exists(engine):
    # Revoking someone who is NOT the last active admin must succeed --
    # p_admin remains, so 'temp_admin' losing cplan is recoverable through
    # p_admin and is not a lockout.
    admin = _as(engine, "p_admin")
    try:
        admin.exec_driver_sql(f"SELECT portal.create_user('temp_admin', {scram_literal('pw-temp')}, 'cplan', 'admin')"); admin.commit()
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
        admin.exec_driver_sql(f"SELECT portal.create_user('second_admin', {scram_literal('pw-2nd')}, 'cplan', 'admin')"); admin.commit()
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


def test_user_profile_table_is_not_selectable_by_a_non_admin(engine):
    """Nothing in the application reads portal.user_profile directly -- only
    portal.users (SELECT granted to cplan_admin alone) joins it, and the
    SECURITY DEFINER functions read/write it under their own owner
    privileges. A stray PUBLIC grant here would let any cluster login role,
    including a mere cplan_viewer with psql, read the full account roster
    and every last-sign-in time, bypassing portal.users' admin-only intent
    entirely. Even cplan_admin has no direct grant on the table itself --
    only on the view -- so a plain non-admin role is enough to prove PUBLIC
    has nothing here."""
    viewer = _as(engine, "p_viewer")
    try:
        with pytest.raises(ProgrammingError) as exc:
            viewer.exec_driver_sql("SELECT 1 FROM portal.user_profile LIMIT 1")
        assert exc.value.orig.sqlstate == "42501"
        viewer.rollback()
    finally:
        viewer.exec_driver_sql("RESET ROLE"); viewer.commit(); viewer.close()


def test_apply_portal_revokes_a_stale_public_grant_on_user_profile(engine):
    """The test above only proves PUBLIC has no SELECT on a fresh install --
    it cannot catch a regression on an already-upgraded installation that
    ran the old `GRANT SELECT ON portal.user_profile TO PUBLIC` before the
    fix. Simulate that stale state directly (grants, unlike a view's column
    list, are not something CREATE-time DDL touches at all -- only an
    explicit REVOKE removes one), re-run apply_portal, and assert PUBLIC's
    access is gone. This is the load-bearing half of the fix: omitting the
    GRANT going forward does nothing for a database that already has it."""
    def _public_has_select(c):
        # has_table_privilege() takes a role name/oid, not the PUBLIC pseudo-
        # role keyword -- 'PUBLIC' as a text argument is looked up as an
        # actual role and raises undefined_object. information_schema's
        # table_privileges lists PUBLIC grants under that literal grantee
        # name, so query it directly instead.
        return (
            c.execute(
                text(
                    "SELECT 1 FROM information_schema.table_privileges "
                    "WHERE grantee = 'PUBLIC' AND table_schema = 'portal' "
                    "AND table_name = 'user_profile' AND privilege_type = 'SELECT'"
                )
            ).first()
            is not None
        )

    with engine.begin() as c:
        c.exec_driver_sql("GRANT SELECT ON portal.user_profile TO PUBLIC")
        assert _public_has_select(c)  # the stale-grant simulation actually took

    apply_portal(engine)

    with engine.connect() as c:
        assert not _public_has_select(c)


def test_apply_portal_upgrades_the_view_from_a_pre_profile_definition(engine):
    """CREATE OR REPLACE VIEW does not migrate an already-applied definition on
    its own -- it only takes effect the next time something reissues it. This
    installs the view exactly as it looked before display_name/last_sign_in
    were joined in (commit a9c8881), then re-runs apply_portal and asserts
    the current definition wins. Without this, apply_portal's CREATE OR
    REPLACE VIEW correctness is never actually exercised on an
    already-upgraded database: test_apply_portal_is_idempotent_and_creates_objects
    only re-runs new code against a schema apply_portal itself just created,
    which is a no-op upgrade by construction."""
    previous_view = """
    CREATE VIEW portal.users AS
    SELECT u.rolname AS username,
           p.slug    AS project,
           CASE g.rolname
             WHEN p.role_prefix || '_admin'       THEN 'admin'
             WHEN p.role_prefix || '_editor'      THEN 'editor'
             WHEN p.role_prefix || '_contributor' THEN 'contributor'
             WHEN p.role_prefix || '_viewer'      THEN 'viewer'
           END AS role,
           u.rolcanlogin AS active
    FROM pg_roles u
    JOIN pg_auth_members am ON am.member = u.oid
    JOIN pg_roles g ON g.oid = am.roleid
    JOIN portal.projects p ON g.rolname IN (
        p.role_prefix || '_viewer', p.role_prefix || '_contributor',
        p.role_prefix || '_editor', p.role_prefix || '_admin')
    WHERE u.rolname NOT IN ('cplan_authenticator', 'portal_owner')
      AND u.rolname NOT IN (
          SELECT p2.role_prefix || suffix.s
          FROM portal.projects p2,
               (VALUES ('_viewer'), ('_contributor'), ('_editor'), ('_admin'), ('_sync')) AS suffix(s)
      );
    """

    def _users_columns(c):
        return {
            r[0]
            for r in c.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'portal' AND table_name = 'users'"
                )
            ).all()
        }

    with engine.begin() as c:
        # CREATE OR REPLACE VIEW cannot drop columns from an existing view
        # (Postgres: "cannot drop columns from view"), so simulating an
        # older installation needs a real DROP -- exactly what a database
        # that never ran the profile-join migration would have instead.
        c.exec_driver_sql("DROP VIEW portal.users")
        c.exec_driver_sql(previous_view)
        assert "display_name" not in _users_columns(c)  # the downgrade actually took

    apply_portal(engine)  # must upgrade the view back, not error, not leave it stale

    with engine.connect() as c:
        assert {"display_name", "last_sign_in"} <= _users_columns(c)
        assert c.execute(text("SELECT 1 FROM portal.users WHERE username = 'p_admin'")).first()


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


def test_apply_portal_upgrades_a_database_whose_functions_still_take_a_password(engine):
    """The one upgrade step `CREATE OR REPLACE FUNCTION` cannot perform on its own.

    `portal.create_user`/`portal.reset_password` took `p_password` before they
    took `p_verifier`; renaming an input parameter is refused outright ("cannot
    change name of input parameter"), so `apply_portal` has to DROP them first
    (`_RENAMED_PARAMETER_SIGNATURES`). Every existing installation goes through
    exactly this path, and no test that only ever builds a database from
    scratch would ever execute it -- so this one builds the older shape on
    purpose and then upgrades it.
    """
    with engine.begin() as c:
        c.exec_driver_sql("DROP FUNCTION portal.create_user(text, text, text, text)")
        c.exec_driver_sql(
            "CREATE FUNCTION portal.create_user(p_name text, p_password text, p_project text, p_role text) "
            "RETURNS void LANGUAGE plpgsql AS $fn$ BEGIN END; $fn$"
        )
        arguments = c.execute(
            text("SELECT pg_get_function_arguments(oid) FROM pg_proc WHERE oid = 'portal.create_user(text,text,text,text)'::regprocedure")
        ).scalar_one()
        assert "p_password" in arguments  # the downgrade actually took

    apply_portal(engine)  # must upgrade in place, not fail on the rename

    with engine.connect() as c:
        arguments = c.execute(
            text("SELECT pg_get_function_arguments(oid) FROM pg_proc WHERE oid = 'portal.create_user(text,text,text,text)'::regprocedure")
        ).scalar_one()
        assert "p_verifier" in arguments and "p_password" not in arguments
        # No stray overload left behind, and the admin grant the DROP removed is back.
        assert c.execute(
            text("SELECT count(*) FROM pg_proc WHERE proname = 'create_user' AND pronamespace = 'portal'::regnamespace")
        ).scalar_one() == 1
        assert c.execute(
            text(
                "SELECT has_function_privilege('cplan_admin', "
                "'portal.create_user(text, text, text, text)', 'EXECUTE')"
            )
        ).scalar_one() is True

    # And it still works: the upgraded function creates a real account.
    admin = _as(engine, "p_admin")
    try:
        admin.exec_driver_sql(
            f"SELECT portal.create_user('upgraded', {scram_literal('pw-upgraded')}, 'cplan', 'viewer')"
        )
        admin.commit()
    finally:
        admin.rollback(); admin.exec_driver_sql("RESET ROLE"); admin.commit(); admin.close()
    with engine.connect() as c:
        assert c.execute(text("SELECT rolcanlogin FROM pg_roles WHERE rolname = 'upgraded'")).scalar_one() is True
