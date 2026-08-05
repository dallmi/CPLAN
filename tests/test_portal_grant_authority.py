"""Grant-authority fixes: bootstrap-admin manageability, existing-installation
repair, and second-project support for portal_owner's ADMIN OPTION.

Covers the gap recorded in
docs/superpowers/plans/2026-08-04-portal-redesign-phase-1.md ("Completed
2026-08-05 -- open items found along the way"):

- `setup_roles.create_user` (the CLI bootstrap path for the very first admin)
  issues its GRANT while connected as the superuser, so the superuser is the
  grantor. PostgreSQL's REVOKE honours the grantor, and every `portal.*`
  user-management function runs as `portal_owner` (SECURITY DEFINER) -- so
  without a fix, that account can never be revoked, demoted, or removed
  through the portal.
- `portal_owner` held ADMIN OPTION only on CPLAN's own four group roles, so a
  second registered project's `portal.create_user`/`set_project_role`/
  `revoke_project_role` calls failed Postgres's own privilege check (42501,
  surfacing as a 403 that looks like a permissions problem rather than an
  incomplete installation).

Each test builds its own fresh database (function-scoped fixture) rather than
sharing one across the file: the whole point of these tests is to control the
*order* create_user/apply_portal/register_project run in, which a shared
module-scoped fixture (as in test_setup_portal.py) would obscure.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from pipeline.api.app import Base
from pipeline.api.database import create_cplan_engine
from pipeline.api.setup_portal import PORTAL_OWNER, apply_portal, register_project
from pipeline.api.setup_roles import apply_roles, create_user, set_user_active
from tests.conftest import postgres_required, postgres_test_database

pytestmark = postgres_required


@pytest.fixture
def engine(tmp_path_factory):
    url, teardown = postgres_test_database(tmp_path_factory, "grantauth")
    engine = create_cplan_engine(url)
    Base.metadata.create_all(engine)
    apply_roles(engine)
    yield engine
    engine.dispose()
    teardown()


def _as(engine, username):
    """A connection impersonating `username` via SET ROLE (mirrors the API per-request identity)."""
    connection = engine.connect()
    connection.exec_driver_sql(f'SET ROLE "{username}"')
    connection.commit()
    return connection


def _direct_groups(engine, username, prefix="cplan"):
    """Every group role `username` is a DIRECT member of under `prefix` (mirrors
    the same query used throughout test_setup_portal.py/test_setup_roles.py)."""
    with engine.connect() as c:
        return c.execute(
            text(
                "SELECT r.rolname FROM pg_auth_members m "
                "JOIN pg_roles r ON r.oid = m.roleid "
                "JOIN pg_roles u ON u.oid = m.member WHERE u.rolname = :n AND r.rolname LIKE :like"
            ),
            {"n": username, "like": f"{prefix}\\_%"},
        ).scalars().all()


def _grantors_of(engine, group, member):
    """Every distinct grantor recorded for `member`'s membership in `group`."""
    with engine.connect() as c:
        return c.execute(
            text(
                "SELECT gr.rolname FROM pg_auth_members m "
                "JOIN pg_roles g ON g.oid = m.roleid "
                "JOIN pg_roles u ON u.oid = m.member "
                "JOIN pg_roles gr ON gr.oid = m.grantor "
                "WHERE g.rolname = :g AND u.rolname = :u"
            ),
            {"g": group, "u": member},
        ).scalars().all()


def test_bootstrap_admin_can_be_demoted_and_revoked_through_the_portal(engine):
    # Realistic order: setup_roles creates the very first admin BEFORE the
    # portal (and portal_owner) exist at all -- see setup_portal's module
    # docstring and the README's documented bootstrap sequence ("Set up roles
    # + first admin", then, once, "setup_portal").
    create_user(engine, "boot_admin", "pw-boot", "admin")
    apply_portal(engine)  # one-time setup, run once after the first admin exists

    # boot_admin's membership must already be attributed to portal_owner, or
    # every step below (all SECURITY DEFINER, executing as portal_owner) would
    # silently no-op instead of raising -- PostgreSQL's REVOKE-by-a-grantor-
    # that-does-not-match is a no-op with a warning, not an error.
    assert _grantors_of(engine, "cplan_admin", "boot_admin") == [PORTAL_OWNER]

    # A second admin, created normally through the portal, so demoting/
    # revoking boot_admin never trips the last-active-admin guard -- that
    # guard's own behaviour is covered separately, below.
    first = _as(engine, "boot_admin")
    try:
        first.exec_driver_sql("SELECT portal.create_user('second_admin', 'pw-2nd', 'cplan', 'admin')")
        first.commit()
    finally:
        first.exec_driver_sql("RESET ROLE")
        first.commit()
        first.close()

    demoter = _as(engine, "second_admin")
    try:
        demoter.exec_driver_sql("SELECT portal.set_project_role('boot_admin', 'cplan', 'viewer')")
        demoter.commit()
    finally:
        demoter.exec_driver_sql("RESET ROLE")
        demoter.commit()
        demoter.close()
    assert _direct_groups(engine, "boot_admin") == ["cplan_viewer"]

    revoker = _as(engine, "second_admin")
    try:
        revoker.exec_driver_sql("SELECT portal.revoke_project_role('boot_admin', 'cplan')")
        revoker.commit()
    finally:
        revoker.exec_driver_sql("RESET ROLE")
        revoker.commit()
        revoker.close()
    assert _direct_groups(engine, "boot_admin") == []

    with engine.connect() as c:
        # The account itself survives -- only its project role was revoked.
        assert c.execute(text("SELECT 1 FROM pg_roles WHERE rolname = 'boot_admin'")).first()


def test_apply_portal_repairs_a_superuser_granted_membership(engine):
    """The repair path, isolated from the rest of the demote/revoke lifecycle:
    construct a membership granted by the connecting superuser (exactly what
    setup_roles.create_user always produces, whether it runs before or after
    apply_portal -- it never sets GRANTED BY), run apply_portal, and assert
    the membership is then revocable by portal_owner directly."""
    apply_portal(engine)  # an "existing installation" -- the portal is already set up
    create_user(engine, "legacy_admin", "pw-legacy", "admin")
    # Whichever role this test's connection URL uses as its superuser, it is
    # not portal_owner -- assert that without hardcoding the name (it differs
    # between the embedded and external test-database backends).
    assert _grantors_of(engine, "cplan_admin", "legacy_admin") != [PORTAL_OWNER]

    apply_portal(engine)  # the repair pass

    assert _grantors_of(engine, "cplan_admin", "legacy_admin") == [PORTAL_OWNER]

    # Not just relabelled: portal_owner can now actually revoke it directly,
    # which it could not before (see test_setup_portal.py's docstring on why
    # PostgreSQL's REVOKE honours the grantor).
    owner = _as(engine, PORTAL_OWNER)
    try:
        owner.exec_driver_sql('REVOKE cplan_admin FROM "legacy_admin"')
        owner.commit()
    finally:
        owner.exec_driver_sql("RESET ROLE")
        owner.commit()
        owner.close()
    assert _direct_groups(engine, "legacy_admin") == []


def test_apply_portal_repairs_a_disabled_accounts_grantor(engine):
    """`rolcanlogin` cannot stand in for "is this a real account": it is
    `portal.set_active`'s own active/disabled flag, and a disabled account is
    still a fully manageable one -- neither `set_project_role` nor
    `revoke_project_role` checks whether its target is active. It is also
    exactly the account most likely to need this repair: someone who left,
    disabled rather than deleted, is precisely who an operator would next try
    to strip of access.

    Exercises the real failure end to end rather than just the predicate: a
    superuser-granted membership, disabled via the exact `ALTER ROLE ...
    NOLOGIN` statement `portal.set_active` issues (here via
    `setup_roles.set_user_active`, i.e. the `--deactivate` CLI path -- not
    the `portal.set_active` RPC itself: that SECURITY DEFINER function always
    runs its `ALTER ROLE` as `portal_owner`, which requires `portal_owner` to
    hold ADMIN OPTION on the *login role itself*, a distinct PostgreSQL
    authority from the group-role membership this task's fix repairs, and
    one a superuser-bootstrapped account never grants it -- a real,
    separate, and still-open gap, but not what `_repair_grantor`'s predicate
    is about or what this test targets), then `apply_portal`, then a genuine
    `portal.revoke_project_role` call. Against the old `u.rolcanlogin`-scoped
    predicate this would still reach every assertion up to the last one --
    the disabled account is silently excluded from the sweep, so its grantor
    is never repaired, and the final REVOKE (issued by `portal_owner` through
    the SECURITY DEFINER function) silently changes nothing: PostgreSQL's
    grantor-mismatch REVOKE is a WARNING, never an error, so only checking
    the resulting database state -- not the absence of an exception --
    catches it."""
    apply_portal(engine)  # an "existing installation"
    create_user(engine, "leaver_admin", "pw-leaver", "admin")
    create_user(engine, "ops_admin", "pw-ops", "admin")  # a second admin, so the last-admin guard never fires
    # Both created via the CLI bootstrap path (connected as the superuser),
    # so both start out superuser-granted -- exactly like legacy_admin above.
    assert _grantors_of(engine, "cplan_admin", "leaver_admin") != [PORTAL_OWNER]

    set_user_active(engine, "leaver_admin", False)
    with engine.connect() as c:
        assert (
            c.execute(text("SELECT rolcanlogin FROM pg_roles WHERE rolname = 'leaver_admin'")).scalar_one() is False
        )

    apply_portal(engine)  # the repair pass -- must reach leaver_admin despite it being disabled

    assert _grantors_of(engine, "cplan_admin", "leaver_admin") == [PORTAL_OWNER]

    # Not just relabelled: portal_owner (via the SECURITY DEFINER function,
    # called by another admin) can now actually revoke it.
    revoker = _as(engine, "ops_admin")
    try:
        revoker.exec_driver_sql("SELECT portal.revoke_project_role('leaver_admin', 'cplan')")
        revoker.commit()
    finally:
        revoker.exec_driver_sql("RESET ROLE")
        revoker.commit()
        revoker.close()
    assert _direct_groups(engine, "leaver_admin") == []

    with engine.connect() as c:
        # The account itself survives, still disabled -- only its project role was revoked.
        assert c.execute(text("SELECT 1 FROM pg_roles WHERE rolname = 'leaver_admin'")).first()


def test_apply_portal_repair_is_a_no_op_when_nothing_needs_repairing(engine):
    """Idempotent and safe to re-run: a membership already granted by
    portal_owner (the normal case for every account created through the portal
    itself, e.g. via portal.create_user) must never be touched by a later
    apply_portal run."""
    apply_portal(engine)
    create_user(engine, "already_fine", "pw-fine", "admin")
    apply_portal(engine)  # first repair
    assert _grantors_of(engine, "cplan_admin", "already_fine") == [PORTAL_OWNER]

    apply_portal(engine)  # second run: nothing left to repair -- must not raise or change anything
    assert _grantors_of(engine, "cplan_admin", "already_fine") == [PORTAL_OWNER]


def test_last_admin_guard_still_blocks_the_repaired_bootstrap_admin(engine):
    """Regression: the guards in _is_last_active_admin read pg_auth_members
    directly and must keep working exactly as before once the membership they
    are counting is attributed to portal_owner instead of the superuser."""
    create_user(engine, "sole_admin", "pw-sole", "admin")
    apply_portal(engine)  # repairs sole_admin's grantor

    caller = _as(engine, "sole_admin")
    try:
        with pytest.raises(ProgrammingError) as exc:
            caller.exec_driver_sql("SELECT portal.revoke_project_role('sole_admin', 'cplan')")
        assert exc.value.orig.sqlstate == "P0001"
        assert "last active admin" in str(exc.value.orig)
        caller.rollback()
    finally:
        caller.exec_driver_sql("RESET ROLE")
        caller.commit()
        caller.close()

    assert _direct_groups(engine, "sole_admin") == ["cplan_admin"]  # untouched


def test_set_active_guard_still_blocks_disabling_the_repaired_bootstrap_admin(engine):
    """Same regression as above, for set_active's own inline last-admin guard."""
    create_user(engine, "sole_admin2", "pw-sole2", "admin")
    apply_portal(engine)

    caller = _as(engine, "sole_admin2")
    try:
        with pytest.raises(ProgrammingError) as exc:
            caller.exec_driver_sql("SELECT portal.set_active('sole_admin2', false, 'someone_else')")
        assert exc.value.orig.sqlstate == "P0001"
        assert "last active admin" in str(exc.value.orig)
        caller.rollback()
    finally:
        caller.exec_driver_sql("RESET ROLE")
        caller.commit()
        caller.close()

    with engine.connect() as c:
        assert c.execute(text("SELECT rolcanlogin FROM pg_roles WHERE rolname = 'sole_admin2'")).scalar_one() is True


def test_second_project_supports_full_user_lifecycle_via_the_portal(engine):
    """The measure of point 3: register_project must leave a *working*
    installation for the new project, not just a registry row -- create,
    change role, and revoke must all succeed the same way they do for CPLAN."""
    apply_portal(engine)
    create_user(engine, "proj2_admin", "pw-p2", "admin")
    apply_portal(engine)  # repair proj2_admin's grantor before using it as caller

    prefix = "secondp"
    groups = [f"{prefix}_{suffix}" for suffix in ("viewer", "contributor", "editor", "admin")]
    with engine.begin() as c:
        for group in groups:
            c.exec_driver_sql(f"CREATE ROLE {group} NOLOGIN")
        c.exec_driver_sql(f"GRANT {prefix}_viewer TO {prefix}_contributor")
        c.exec_driver_sql(f"GRANT {prefix}_contributor TO {prefix}_editor")
        c.exec_driver_sql(f"GRANT {prefix}_editor TO {prefix}_admin")

    # Registered AFTER its roles already exist -- exercises register_project's
    # own immediate ADMIN OPTION extension (the "both" half of point 3), not
    # apply_portal's sweep (covered by the next test).
    register_project(engine, "secondp", "Second Project", "http://second/", prefix)

    admin = _as(engine, "proj2_admin")
    try:
        admin.exec_driver_sql("SELECT portal.create_user('p2_user', 'pw-p2u', 'secondp', 'viewer')")
        admin.commit()
        admin.exec_driver_sql("SELECT portal.set_project_role('p2_user', 'secondp', 'editor')")
        admin.commit()
    finally:
        admin.exec_driver_sql("RESET ROLE")
        admin.commit()
        admin.close()
    assert _direct_groups(engine, "p2_user", prefix) == [f"{prefix}_editor"]

    revoker = _as(engine, "proj2_admin")
    try:
        revoker.exec_driver_sql("SELECT portal.revoke_project_role('p2_user', 'secondp')")
        revoker.commit()
    finally:
        revoker.exec_driver_sql("RESET ROLE")
        revoker.commit()
        revoker.close()

    assert _direct_groups(engine, "p2_user", prefix) == []
    with engine.connect() as c:
        assert c.execute(text("SELECT 1 FROM pg_roles WHERE rolname = 'p2_user'")).first()  # account persists


def test_a_project_registered_before_its_roles_exist_works_after_apply_portal(engine):
    """A project registered before this change (or before its group roles were
    ever created) must also end up working after an apply_portal run -- the
    documented register-then-create-roles order, closed by apply_portal's
    per-project sweep rather than by register_project itself."""
    apply_portal(engine)
    create_user(engine, "proj3_admin", "pw-p3", "admin")
    apply_portal(engine)

    prefix = "thirdp"
    register_project(engine, "thirdp", "Third Project", "http://third/", prefix)  # roles do not exist yet

    groups = [f"{prefix}_{suffix}" for suffix in ("viewer", "contributor", "editor", "admin")]
    with engine.begin() as c:
        for group in groups:
            c.exec_driver_sql(f"CREATE ROLE {group} NOLOGIN")
        c.exec_driver_sql(f"GRANT {prefix}_viewer TO {prefix}_contributor")
        c.exec_driver_sql(f"GRANT {prefix}_contributor TO {prefix}_editor")
        c.exec_driver_sql(f"GRANT {prefix}_editor TO {prefix}_admin")

    apply_portal(engine)  # the sweep that closes the gap now that the roles exist

    admin = _as(engine, "proj3_admin")
    try:
        admin.exec_driver_sql("SELECT portal.create_user('p3_user', 'pw-p3u', 'thirdp', 'viewer')")
        admin.commit()
    finally:
        admin.exec_driver_sql("RESET ROLE")
        admin.commit()
        admin.close()

    with engine.connect() as c:
        assert c.execute(text("SELECT 1 FROM pg_roles WHERE rolname = 'p3_user'")).first()
