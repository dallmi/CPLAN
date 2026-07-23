"""Postgres role, grant, and row-level-security setup for CPLAN (design spec 2026-07-23).

Idempotent: safe to re-run after every schema change (`GRANT ... ON ALL TABLES`
only covers objects that exist at run time, so re-run after new tables/views).
PostgreSQL only — the SQLite fallback intentionally has no roles (solo mode).

DDL cannot be parameterized; identifiers go through the dialect's identifier
preparer, password literals double their single quotes. Group roles carry the
privileges, user roles are LOGIN roles granted into exactly one group; every
user role is also granted TO cplan_authenticator so the pooled API identity
may SET ROLE into it (PostgREST pattern).
"""

from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import Engine, text
from sqlalchemy.engine import Connection

from pipeline.api.database import create_cplan_engine, database_url_from_environment

GROUP_ROLES = ("cplan_viewer", "cplan_contributor", "cplan_editor", "cplan_admin", "cplan_sync")
AUTHENTICATOR = "cplan_authenticator"
ASSIGNABLE_ROLES = {
    "viewer": "cplan_viewer",
    "contributor": "cplan_contributor",
    "editor": "cplan_editor",
    "admin": "cplan_admin",
}
RESERVED_ROLES = frozenset(GROUP_ROLES) | {AUTHENTICATOR}

_POLICIES = ("read_all", "contrib_insert", "contrib_update", "editor_write", "admin_delete")


def _quote(connection: Connection, identifier: str) -> str:
    return connection.dialect.identifier_preparer.quote(identifier)


def _pw_literal(password: str) -> str:
    return "'" + password.replace("'", "''") + "'"


def _role_exists(connection: Connection, name: str) -> bool:
    return connection.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :n"), {"n": name}).first() is not None


def _reject_reserved(username: str) -> None:
    if username in RESERVED_ROLES:
        raise ValueError(f"{username!r} is a reserved internal role")


def _ensure_role(connection: Connection, name: str, login: bool = False) -> None:
    if not _role_exists(connection, name):
        connection.exec_driver_sql(f"CREATE ROLE {_quote(connection, name)} {'LOGIN' if login else 'NOLOGIN'}")


def apply_roles(engine: Engine) -> None:
    with engine.begin() as c:
        for name in GROUP_ROLES:
            _ensure_role(c, name)
        _ensure_role(c, AUTHENTICATOR, login=True)

        # -- created_by hardening (column itself arrives via ensure_schema/Task 1)
        c.exec_driver_sql("ALTER TABLE activities ADD COLUMN IF NOT EXISTS created_by TEXT")
        c.exec_driver_sql("UPDATE activities SET created_by = 'cplan_sync' WHERE created_by IS NULL")
        c.exec_driver_sql("ALTER TABLE activities ALTER COLUMN created_by SET NOT NULL")
        c.exec_driver_sql("ALTER TABLE activities ALTER COLUMN created_by SET DEFAULT current_user")
        # -- audit actor must fit real usernames, not just 'studio'/'sync'/'seed'
        c.exec_driver_sql("ALTER TABLE activity_changes ALTER COLUMN actor TYPE VARCHAR(64)")

        # -- grants: viewer ⊂ contributor ⊂ editor ⊂ admin; sync writes like an editor
        c.exec_driver_sql("GRANT USAGE ON SCHEMA public TO cplan_viewer")
        c.exec_driver_sql("GRANT SELECT ON ALL TABLES IN SCHEMA public TO cplan_viewer")
        c.exec_driver_sql("GRANT cplan_viewer TO cplan_contributor")
        c.exec_driver_sql("GRANT INSERT ON activities, activity_changes TO cplan_contributor")
        c.exec_driver_sql("GRANT UPDATE ON activities TO cplan_contributor")
        c.exec_driver_sql("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO cplan_contributor")
        c.exec_driver_sql("GRANT cplan_contributor TO cplan_editor")
        c.exec_driver_sql("GRANT cplan_editor TO cplan_admin")
        c.exec_driver_sql("GRANT DELETE ON activities TO cplan_admin")
        c.exec_driver_sql("GRANT cplan_editor TO cplan_sync")

        # -- row level security on activities
        c.exec_driver_sql("ALTER TABLE activities ENABLE ROW LEVEL SECURITY")
        c.exec_driver_sql("ALTER TABLE activities FORCE ROW LEVEL SECURITY")
        for policy in _POLICIES:
            c.exec_driver_sql(f"DROP POLICY IF EXISTS {policy} ON activities")
        c.exec_driver_sql("CREATE POLICY read_all ON activities FOR SELECT USING (true)")
        c.exec_driver_sql(
            "CREATE POLICY contrib_insert ON activities FOR INSERT TO cplan_contributor "
            "WITH CHECK (created_by = current_user)"
        )
        c.exec_driver_sql(
            "CREATE POLICY contrib_update ON activities FOR UPDATE TO cplan_contributor "
            "USING (created_by = current_user)"
        )
        c.exec_driver_sql(
            "CREATE POLICY editor_write ON activities FOR ALL TO cplan_editor, cplan_sync "
            "USING (true) WITH CHECK (true)"
        )
        c.exec_driver_sql("CREATE POLICY admin_delete ON activities FOR DELETE TO cplan_admin USING (true)")


def _resolve_group(role_key: str) -> str:
    if role_key not in ASSIGNABLE_ROLES:
        raise ValueError(f"Unknown role {role_key!r}; expected one of {sorted(ASSIGNABLE_ROLES)}")
    return ASSIGNABLE_ROLES[role_key]


def create_user(engine: Engine, username: str, password: str, role_key: str) -> None:
    _reject_reserved(username)
    group = _resolve_group(role_key)
    with engine.begin() as c:
        if _role_exists(c, username):
            raise ValueError(f"Role {username!r} already exists; use set-role/reset-password instead")
        q = _quote(c, username)
        c.exec_driver_sql(f"CREATE ROLE {q} LOGIN PASSWORD {_pw_literal(password)}")
        c.exec_driver_sql(f"GRANT {group} TO {q}")
        c.exec_driver_sql(f"GRANT {q} TO {AUTHENTICATOR}")


def set_user_role(engine: Engine, username: str, role_key: str) -> None:
    _reject_reserved(username)
    group = _resolve_group(role_key)
    with engine.begin() as c:
        q = _quote(c, username)
        for other in ASSIGNABLE_ROLES.values():
            c.exec_driver_sql(f"REVOKE {other} FROM {q}")
        c.exec_driver_sql(f"GRANT {group} TO {q}")


def set_user_password(engine: Engine, username: str, password: str) -> None:
    _reject_reserved(username)
    with engine.begin() as c:
        c.exec_driver_sql(f"ALTER ROLE {_quote(c, username)} PASSWORD {_pw_literal(password)}")


def set_user_active(engine: Engine, username: str, active: bool) -> None:
    _reject_reserved(username)
    with engine.begin() as c:
        c.exec_driver_sql(f"ALTER ROLE {_quote(c, username)} {'LOGIN' if active else 'NOLOGIN'}")


def _resolve_url(explicit: str | None) -> str:
    if explicit:
        return explicit
    from_environment = database_url_from_environment()
    if from_environment:
        return str(from_environment)
    # Mirror start_cplan.py's persisted-settings resolution as the last resort.
    from pipeline.api.setup_backend import load_backend_config, resolve_backend_database_url

    return resolve_backend_database_url(load_backend_config())


def main() -> None:
    parser = argparse.ArgumentParser(description="CPLAN Postgres roles, RLS, and user management")
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--create-user", metavar="NAME")
    parser.add_argument("--set-role", metavar="NAME")
    parser.add_argument("--reset-password", metavar="NAME")
    parser.add_argument("--deactivate", metavar="NAME")
    parser.add_argument("--activate", metavar="NAME")
    parser.add_argument("--role", choices=sorted(ASSIGNABLE_ROLES), default=None)
    parser.add_argument("--password", default=None, help="omit to be prompted without echo")
    args = parser.parse_args()

    engine = create_cplan_engine(_resolve_url(args.database_url))
    try:
        apply_roles(engine)
        print("Roles, grants, and RLS policies applied.")
        if args.create_user:
            if not args.role:
                parser.error("--create-user requires --role")
            create_user(engine, args.create_user, args.password or getpass.getpass("Password: "), args.role)
            print(f"Created user {args.create_user} ({args.role}).")
        if args.set_role:
            if not args.role:
                parser.error("--set-role requires --role")
            set_user_role(engine, args.set_role, args.role)
            print(f"Set {args.set_role} to {args.role}.")
        if args.reset_password:
            set_user_password(engine, args.reset_password, args.password or getpass.getpass("New password: "))
            print(f"Password reset for {args.reset_password}.")
        if args.deactivate:
            set_user_active(engine, args.deactivate, False)
            print(f"Deactivated {args.deactivate}.")
        if args.activate:
            set_user_active(engine, args.activate, True)
            print(f"Activated {args.activate}.")
    except ValueError as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
