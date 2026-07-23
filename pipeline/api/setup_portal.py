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
_CPLAN = {"slug": "cplan", "name": "CPLAN Planning Studio", "url": "http://127.0.0.1:8780/", "role_prefix": "cplan"}

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
  FOREACH r IN ARRAY ARRAY['viewer','contributor','editor','admin'] LOOP
    EXECUTE format('REVOKE %%I FROM %%I', v_prefix || '_' || r, p_name);
  END LOOP;
  EXECUTE format('GRANT %%I TO %%I', v_prefix || '_' || p_role, p_name);
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

_SET_ACTIVE_FN = f"""
CREATE OR REPLACE FUNCTION portal.set_active(p_name text, p_active boolean)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $fn$
BEGIN
  IF p_name = ANY ({_RESERVED_SQL_ARRAY}) THEN
    RAISE EXCEPTION 'reserved role %%', p_name;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = p_name) THEN
    RAISE EXCEPTION 'unknown user %%', p_name;
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
WHERE u.rolname NOT IN ('cplan_authenticator', 'portal_owner');
"""

_FUNCTIONS = (
    ("portal.create_user(text, text, text, text)", _CREATE_USER_FN),
    ("portal.set_project_role(text, text, text)", _SET_ROLE_FN),
    ("portal.reset_password(text, text)", _RESET_PW_FN),
    ("portal.set_active(text, boolean)", _SET_ACTIVE_FN),
)


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
