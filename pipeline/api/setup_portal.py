"""Portal schema, project registry, and SECURITY DEFINER user-management functions.

Runs once as a superuser/admin (like setup_roles), NOT by the portal service.
The portal service connects as cplan_authenticator, SET ROLEs to the logged-in
user, and calls these functions; EXECUTE is granted only to cplan_admin, so the
membership check is Postgres's own privilege check performed against the real
caller before the SECURITY DEFINER switch. The functions do input validation and
identifier quoting (format %I/%L) as defence in depth. PostgreSQL only.
"""

from __future__ import annotations

import argparse

from sqlalchemy import Engine, text

from pipeline.api.database import create_cplan_engine, database_url_from_environment
from pipeline.api.setup_roles import ASSIGNABLE_ROLES, AUTHENTICATOR, GROUP_ROLES

PORTAL_OWNER = "portal_owner"
PORTAL_RESERVED = frozenset(GROUP_ROLES) | {AUTHENTICATOR, PORTAL_OWNER}

# The four assignable CPLAN group roles portal_owner must be able to grant.
_ASSIGNABLE_GROUPS = tuple(ASSIGNABLE_ROLES.values())  # cplan_viewer/contributor/editor/admin

# CPLAN seed for the project registry.
_CPLAN = {"slug": "cplan", "name": "CPLAN Studio", "url": "http://127.0.0.1:8780/", "role_prefix": "cplan"}

# The reserved-name array literal the functions guard against, built once here so
# it matches PORTAL_RESERVED exactly.
_RESERVED_SQL_ARRAY = "ARRAY[" + ",".join(f"'{name}'" for name in sorted(PORTAL_RESERVED)) + "]"

# NOTE: every literal '%' below is doubled ('%%') because these strings go
# through psycopg3's cursor.execute(), which always scans for placeholders
# (%s/%b/%t) even when no bind parameters are supplied — a bare '%' (as in
# plpgsql's RAISE '...%', arg or format()'s %I/%L/%s) raises psycopg's own
# ProgrammingError before the DDL ever reaches Postgres. Doubling yields a
# literal '%' once psycopg's client-side parser unescapes it.
#
# NOTE: RAISE EXCEPTION below intentionally does NOT set
# `USING ERRCODE = 'invalid_parameter_value'` (SQLSTATE 22023, class 22 "Data
# Exception"). psycopg/SQLAlchemy map class-22 errors to DataError, not
# ProgrammingError; callers (and the test suite) expect a uniform
# ProgrammingError for every rejected call to these functions, including the
# 42501 insufficient-privilege case. Plain `RAISE EXCEPTION` defaults to
# SQLSTATE P0001 ("raise_exception", class P0 PL/pgSQL Error), which psycopg
# maps to ProgrammingError — matching the 42501 case's exception type without
# changing what is validated or rejected.

_CREATE_USER_FN = f"""
CREATE OR REPLACE FUNCTION portal.create_user(p_name text, p_password text, p_project text, p_role text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $fn$
DECLARE v_prefix text; v_group text;
BEGIN
  IF p_role NOT IN ('viewer','contributor','editor','admin') THEN
    RAISE EXCEPTION 'unknown role %%', p_role;
  END IF;
  SELECT role_prefix INTO v_prefix FROM portal.projects WHERE slug = p_project;
  IF v_prefix IS NULL THEN
    RAISE EXCEPTION 'unknown project %%', p_project;
  END IF;
  IF p_name = ANY ({_RESERVED_SQL_ARRAY}) THEN
    RAISE EXCEPTION 'reserved role %%', p_name;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = p_name) THEN
    RAISE EXCEPTION 'user %% already exists', p_name;
  END IF;
  v_group := v_prefix || '_' || p_role;
  EXECUTE format('CREATE ROLE %%I LOGIN PASSWORD %%L', p_name, p_password);
  EXECUTE format('GRANT %%I TO %%I', v_group, p_name);
  EXECUTE format('GRANT %%I TO {AUTHENTICATOR}', p_name);
END; $fn$;
"""

# set_project_role and revoke_project_role both need to answer the same
# question -- "does p_name hold this project's admin group, and if so, would
# taking it away leave zero OTHER active admins?" -- over the identical
# two-step EXISTS+count query, so it lives once here rather than as two
# near-identical blocks that could quietly drift apart. Only the message each
# caller raises differs, so the predicate stays a boolean and the RAISE
# EXCEPTION stays at each call site rather than being parametrised into the
# helper too.
#
# A plain (non-SECURITY DEFINER) function is enough: both callers are
# themselves SECURITY DEFINER, so by the time either of them calls this, the
# active role is already portal_owner, and portal_owner -- as this function's
# owner -- may always execute it regardless of grants. It is deliberately
# never listed in _FUNCTIONS below, so cplan_admin is never GRANTed EXECUTE
# on it directly: it is an implementation detail shared between two API
# functions, not part of the API surface itself.
#
# set_active's own last-admin guard is NOT built on this helper, despite
# checking the same thing in spirit: it loops over every project a disabled
# account might administer (disabling a login is account-wide, not
# project-scoped, unlike a role change on one project) and it also carries
# its own self-caller check that has no equivalent here. Sharing would have
# meant reshaping set_active's cross-project loop around a single-project
# predicate, touching a function this task has no reason to change.
_LAST_ACTIVE_ADMIN_FN = """
CREATE OR REPLACE FUNCTION portal._is_last_active_admin(p_name text, p_admin_group text)
RETURNS boolean LANGUAGE plpgsql AS $fn$
DECLARE v_other_active_admins int;
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_auth_members m
    JOIN pg_roles g ON g.oid = m.roleid AND g.rolname = p_admin_group
    JOIN pg_roles u ON u.oid = m.member AND u.rolname = p_name
  ) THEN
    RETURN false;
  END IF;
  SELECT count(*) INTO v_other_active_admins FROM pg_auth_members m
  JOIN pg_roles g ON g.oid = m.roleid AND g.rolname = p_admin_group
  JOIN pg_roles u ON u.oid = m.member
  WHERE u.rolcanlogin AND u.rolname <> p_name;
  RETURN v_other_active_admins = 0;
END; $fn$;
"""

# Moving a project's last active admin to any non-admin role empties the
# admin group exactly as surely as revoke_project_role would -- reachable
# from the very next line of the same matrix popover -- so it is refused the
# same way. Re-granting admin to the sole admin (p_role = 'admin') is
# excluded from the guard: that leaves the admin group non-empty, so it must
# stay the no-op it already is.
_SET_ROLE_FN = f"""
CREATE OR REPLACE FUNCTION portal.set_project_role(p_name text, p_project text, p_role text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $fn$
DECLARE v_prefix text; r text;
BEGIN
  IF p_role NOT IN ('viewer','contributor','editor','admin') THEN
    RAISE EXCEPTION 'unknown role %%', p_role;
  END IF;
  IF p_name = ANY ({_RESERVED_SQL_ARRAY}) THEN
    RAISE EXCEPTION 'reserved role %%', p_name;
  END IF;
  SELECT role_prefix INTO v_prefix FROM portal.projects WHERE slug = p_project;
  IF v_prefix IS NULL THEN
    RAISE EXCEPTION 'unknown project %%', p_project;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = p_name) THEN
    RAISE EXCEPTION 'unknown user %%', p_name;
  END IF;
  IF p_role <> 'admin' AND portal._is_last_active_admin(p_name, v_prefix || '_admin') THEN
    RAISE EXCEPTION 'cannot demote %%: last active admin (%%)', p_name, v_prefix || '_admin';
  END IF;
  FOREACH r IN ARRAY ARRAY['viewer','contributor','editor','admin'] LOOP
    EXECUTE format('REVOKE %%I FROM %%I', v_prefix || '_' || r, p_name);
  END LOOP;
  EXECUTE format('GRANT %%I TO %%I', v_prefix || '_' || p_role, p_name);
END; $fn$;
"""

# Removing every assignable group role for one project drops the user out of
# portal.users for that project entirely -- which is what an emptied matrix
# cell means. The account itself and any access to OTHER projects are
# untouched. Revoking the project's last active admin has the same failure
# shape set_active's disable guard exists to prevent: nobody would be left
# who can grant access back through the portal for that project, and
# recovery would need the setup_roles CLI on the host machine, so that case
# is guarded the same way (mirroring set_active's rolcanlogin-scoped count,
# via the shared portal._is_last_active_admin above).
# Unlike set_active, this does NOT special-case the caller's own account:
# set_project_role already lets an admin demote themselves away from
# <prefix>_admin today with no such guard (it is revoke-then-grant), and a
# self-revoke while another admin remains is recoverable through that other
# admin -- it is the *last* admin leaving that the portal cannot undo, not
# *which* admin does the revoking.
_REVOKE_ROLE_FN = f"""
CREATE OR REPLACE FUNCTION portal.revoke_project_role(p_name text, p_project text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $fn$
DECLARE v_prefix text; r text;
BEGIN
  IF p_name = ANY ({_RESERVED_SQL_ARRAY}) THEN
    RAISE EXCEPTION 'reserved role %%', p_name;
  END IF;
  SELECT role_prefix INTO v_prefix FROM portal.projects WHERE slug = p_project;
  IF v_prefix IS NULL THEN
    RAISE EXCEPTION 'unknown project %%', p_project;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = p_name) THEN
    RAISE EXCEPTION 'unknown user %%', p_name;
  END IF;
  IF portal._is_last_active_admin(p_name, v_prefix || '_admin') THEN
    RAISE EXCEPTION 'cannot revoke %%: last active admin (%%)', p_name, v_prefix || '_admin';
  END IF;
  FOREACH r IN ARRAY ARRAY['viewer','contributor','editor','admin'] LOOP
    EXECUTE format('REVOKE %%I FROM %%I', v_prefix || '_' || r, p_name);
  END LOOP;
END; $fn$;
"""

_RESET_PW_FN = f"""
CREATE OR REPLACE FUNCTION portal.reset_password(p_name text, p_password text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $fn$
BEGIN
  IF p_name = ANY ({_RESERVED_SQL_ARRAY}) THEN
    RAISE EXCEPTION 'reserved role %%', p_name;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = p_name) THEN
    RAISE EXCEPTION 'unknown user %%', p_name;
  END IF;
  EXECUTE format('ALTER ROLE %%I PASSWORD %%L', p_name, p_password);
END; $fn$;
"""

# p_caller's DEFAULT current_user is evaluated in the CALLER's context (before
# the SECURITY DEFINER switch), so it reliably names the SET ROLE'd admin who
# invoked the function -- the API always calls with two arguments. An admin
# passing an explicit third argument only bypasses the self-disable guard, and
# admins are trusted with worse; the guards protect against accidents, not
# malice. Lockout guards fire only when DISABLING:
#   - you cannot disable your own account (the session would outlive the lock
#     and the lockout would surface hours later, after logout);
#   - you cannot disable the last ACTIVE admin of any project (nobody could
#     re-enable anyone via the portal afterwards; recovery would require the
#     setup_roles CLI on the host machine).
_SET_ACTIVE_FN = f"""
CREATE OR REPLACE FUNCTION portal.set_active(p_name text, p_active boolean, p_caller text DEFAULT current_user)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $fn$
DECLARE v_admin_group text; v_other_active_admins int;
BEGIN
  IF p_name = ANY ({_RESERVED_SQL_ARRAY}) THEN
    RAISE EXCEPTION 'reserved role %%', p_name;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = p_name) THEN
    RAISE EXCEPTION 'unknown user %%', p_name;
  END IF;
  IF NOT p_active THEN
    IF p_name = p_caller THEN
      RAISE EXCEPTION 'you cannot disable your own account (%%)', p_name;
    END IF;
    FOR v_admin_group IN SELECT role_prefix || '_admin' FROM portal.projects LOOP
      IF EXISTS (
        SELECT 1 FROM pg_auth_members m
        JOIN pg_roles g ON g.oid = m.roleid AND g.rolname = v_admin_group
        JOIN pg_roles u ON u.oid = m.member AND u.rolname = p_name
      ) THEN
        SELECT count(*) INTO v_other_active_admins FROM pg_auth_members m
        JOIN pg_roles g ON g.oid = m.roleid AND g.rolname = v_admin_group
        JOIN pg_roles u ON u.oid = m.member
        WHERE u.rolcanlogin AND u.rolname <> p_name;
        IF v_other_active_admins = 0 THEN
          RAISE EXCEPTION 'cannot disable %%: last active admin (%%)', p_name, v_admin_group;
        END IF;
      END IF;
    END LOOP;
  END IF;
  EXECUTE format('ALTER ROLE %%I %%s', p_name, CASE WHEN p_active THEN 'LOGIN' ELSE 'NOLOGIN' END);
END; $fn$;
"""

# One row per (login user, project, role). LIKE prefix\_% would also match the
# service role cplan_sync, so the role is matched against the four assignable
# group roles explicitly and sync/authenticator/owner are excluded.
_USERS_VIEW = """
CREATE OR REPLACE VIEW portal.users AS
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
  -- Group and service roles are not accounts: the privilege hierarchy
  -- (GRANT <prefix>_viewer TO <prefix>_contributor TO ...) makes the group
  -- roles members of each other, so without this filter they would list as
  -- pseudo-users ("cplan_admin / editor / Disabled").
  AND u.rolname NOT IN (
      SELECT p2.role_prefix || suffix.s
      FROM portal.projects p2,
           (VALUES ('_viewer'), ('_contributor'), ('_editor'), ('_admin'), ('_sync')) AS suffix(s)
  );
"""

_FUNCTIONS = (
    ("portal.create_user(text, text, text, text)", _CREATE_USER_FN),
    ("portal.set_project_role(text, text, text)", _SET_ROLE_FN),
    ("portal.revoke_project_role(text, text)", _REVOKE_ROLE_FN),
    ("portal.reset_password(text, text)", _RESET_PW_FN),
    ("portal.set_active(text, boolean, text)", _SET_ACTIVE_FN),
)

# Superseded signatures that must be dropped before (re)creating the functions:
# CREATE OR REPLACE cannot change a signature -- it would ADD an overload, and
# the API's two-argument call would keep resolving to the old, guard-free
# variant that still carries its EXECUTE grant.
_LEGACY_SIGNATURES = ("portal.set_active(text, boolean)",)


def apply_portal(engine: Engine) -> None:
    with engine.begin() as c:
        exists = c.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :n"), {"n": PORTAL_OWNER}).first()
        if not exists:
            c.exec_driver_sql(f"CREATE ROLE {PORTAL_OWNER} NOLOGIN CREATEROLE")
        # portal_owner must be able to GRANT the assignable group roles to new users.
        for group in _ASSIGNABLE_GROUPS:
            c.exec_driver_sql(f"GRANT {group} TO {PORTAL_OWNER} WITH ADMIN OPTION")

        c.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS portal AUTHORIZATION portal_owner")
        c.exec_driver_sql("GRANT USAGE ON SCHEMA portal TO PUBLIC")
        c.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS portal.projects ("
            "slug text PRIMARY KEY, name text NOT NULL, url text NOT NULL, role_prefix text NOT NULL UNIQUE)"
        )
        # UNIQUE is load-bearing, not incidental: portal.users and the
        # create_user/set_project_role functions resolve a project's group
        # roles by SELECTing role_prefix from this table. Two rows sharing a
        # prefix would make a grant on one project silently apply to the
        # other, and portal.users would emit a duplicate row per shared user.
        # A previous revision of this function briefly dropped the
        # constraint on this branch to let a test reuse another project's
        # prefix; that was wrong and never reached a pushed commit or a
        # database older than this branch, so there is nothing to migrate.
        c.exec_driver_sql("GRANT SELECT ON portal.projects TO PUBLIC")
        # Registry & view are owned by portal_owner so the SECURITY DEFINER
        # functions (also owned by it) can read them under their own privileges.
        c.exec_driver_sql("ALTER TABLE portal.projects OWNER TO portal_owner")

        # Seed CPLAN (idempotent upsert).
        c.execute(
            text(
                "INSERT INTO portal.projects (slug, name, url, role_prefix) "
                "VALUES (:slug, :name, :url, :role_prefix) "
                "ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name, url = EXCLUDED.url, "
                "role_prefix = EXCLUDED.role_prefix"
            ),
            _CPLAN,
        )

        c.exec_driver_sql(_USERS_VIEW)
        c.exec_driver_sql("ALTER VIEW portal.users OWNER TO portal_owner")
        c.exec_driver_sql("GRANT SELECT ON portal.users TO cplan_admin")

        # Created and owned before _FUNCTIONS below: set_project_role and
        # revoke_project_role call it by name in their bodies, and plpgsql
        # resolves that call (and so requires the function to already exist)
        # when THEY are created, not only when they are later invoked. It is
        # intentionally not part of _FUNCTIONS -- see the comment on
        # _LAST_ACTIVE_ADMIN_FN -- so it gets no GRANT EXECUTE TO cplan_admin.
        c.exec_driver_sql(_LAST_ACTIVE_ADMIN_FN)
        c.exec_driver_sql("ALTER FUNCTION portal._is_last_active_admin(text, text) OWNER TO portal_owner")
        c.exec_driver_sql("REVOKE ALL ON FUNCTION portal._is_last_active_admin(text, text) FROM PUBLIC")

        for legacy in _LEGACY_SIGNATURES:
            c.exec_driver_sql(f"DROP FUNCTION IF EXISTS {legacy}")
        for signature, ddl in _FUNCTIONS:
            c.exec_driver_sql(ddl)
            c.exec_driver_sql(f"ALTER FUNCTION {signature} OWNER TO portal_owner")
            c.exec_driver_sql(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
            c.exec_driver_sql(f"GRANT EXECUTE ON FUNCTION {signature} TO cplan_admin")


def register_project(engine: Engine, slug: str, name: str, url: str, role_prefix: str) -> None:
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO portal.projects (slug, name, url, role_prefix) "
                "VALUES (:slug, :name, :url, :role_prefix) "
                "ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name, url = EXCLUDED.url, "
                "role_prefix = EXCLUDED.role_prefix"
            ),
            {"slug": slug, "name": name, "url": url, "role_prefix": role_prefix},
        )


def _resolve_url(explicit: str | None) -> str:
    if explicit:
        return explicit
    from_environment = database_url_from_environment()
    if from_environment:
        return str(from_environment)
    from pipeline.api.setup_backend import load_backend_config, resolve_backend_database_url

    return resolve_backend_database_url(load_backend_config())


def main() -> None:
    parser = argparse.ArgumentParser(description="CPLAN portal schema, registry, and user-management functions")
    parser.add_argument("--database-url", default=None)
    args = parser.parse_args()
    engine = create_cplan_engine(_resolve_url(args.database_url))
    try:
        apply_portal(engine)
        print("Portal schema, project registry, and user-management functions applied.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
