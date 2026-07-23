# Postgres-Native RBAC Implementation Plan (Plan 1 of 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce viewer/contributor/editor/admin permissions for the CPLAN studio inside PostgreSQL (group roles + row level security), with app login whose password check is delegated to Postgres, per-request `SET ROLE` impersonation, an admin-only DELETE endpoint, and role-aware studio UI.

**Architecture:** Group roles carry privileges; user roles are real Postgres LOGIN roles granted into exactly one group. The API pools one connection identity and switches to the session user per request via session-scoped `SET ROLE` (PostgREST pattern). RLS policies express "contributors may only update their own rows" via a new `activities.created_by` column. Auth is enabled by setting `CPLAN_AUTH_SECRET` (Postgres backends only); without it the API behaves exactly as today (local solo mode, SQLite included). The portal (project tiles, user-admin UI) is **Plan 2** and builds on the roles created here; until then, user management is a CLI (`setup_roles.py`) and the studio has its own login overlay.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, psycopg 3, itsdangerous (signed session cookie), pgserver (embedded Postgres 16), vanilla-JS studio.

**Spec:** `docs/superpowers/specs/2026-07-23-postgres-rbac-portal-design.md`

## Global Constraints

- Run tests with `PYTHONPATH=. .venv/bin/python -m pytest tests/<file> -v` from the repo root.
- All existing suites must keep passing unmodified in default (no `CPLAN_AUTH_SECRET`, SQLite) mode.
- Role names are exactly: `cplan_viewer`, `cplan_contributor`, `cplan_editor`, `cplan_admin`, `cplan_sync`, `cplan_authenticator`.
- Never interpolate unquoted identifiers into SQL: use `engine.dialect.identifier_preparer.quote(...)` for role/user names; escape password literals by doubling single quotes (DDL cannot be parameterized).
- No brand names; UI text/icon rules per CLAUDE.md (Lucide, no emojis — `tests/test_studio.py::test_no_emoji_codepoints` enforces this).
- Commit after every green test cycle; commit messages in the repo's existing imperative style.

---

### Task 1: `created_by` ownership column

**Files:**
- Modify: `pipeline/api/app.py` (Activity model ~line 145; `ActivityRead`; `create_activity` ~line 552; `create_activities_batch` ~line 593)
- Modify: `pipeline/api/sync_snapshot.py:138` (new-mirror-row construction)
- Modify: `pipeline/api/import_snapshot.py:119` (seed construction)
- Test: `tests/test_api.py`, `tests/test_sync.py`, `tests/test_import.py`

**Interfaces:**
- Produces: `Activity.created_by: Mapped[str | None]` (Text, nullable in the model; Postgres DDL tightens it in Task 3), exposed as `created_by: str | None = None` on `ActivityRead`. Studio-created rows carry `"studio"` for now (Task 5 switches this to the logged-in username); mirrored and seeded rows carry `"cplan_sync"`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_api.py`:

```python
@pytest.mark.parametrize("backend", TEST_BACKENDS)
def test_create_activity_stamps_created_by(backend, tmp_path):
    client = make_client(backend, tmp_path)  # reuse this module's existing client helper/fixture pattern
    response = client.post("/api/activities", json=minimal_activity_payload())
    assert response.status_code == 201
    assert response.json()["created_by"] == "studio"
```

(Reuse the module's existing client-construction and minimal-payload helpers — `test_api.py` already has both for the create tests; match their names exactly rather than inventing new ones.)

Append to `tests/test_sync.py` (inside the existing test that creates a new mirror row, extend its assertions):

```python
    assert created_activity.created_by == "cplan_sync"
```

Append to `tests/test_import.py` (existing seed test):

```python
    assert all(a.created_by == "cplan_sync" for a in seeded_activities)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_api.py -k created_by tests/test_sync.py tests/test_import.py -v`
Expected: FAIL — `created_by` missing from response / model.

- [ ] **Step 3: Implement**

In `pipeline/api/app.py`, add to the `Activity` model (next to `author` ~line 145):

```python
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)
```

Add to `ActivityRead` (the response schema):

```python
    created_by: str | None = None
```

Do NOT add it to `ActivityCreate`/`ActivityFields`/`ActivityPatch` — clients must never set it (spoofing).

In `create_activity` (~line 566) and `create_activities_batch` (~line 633), extend the constructor call:

```python
activity = Activity(id=activity_id, **activity_fields, tracking_id=tracking_id, created_by="studio")
```

(batch: `**item.model_dump()` variant gets the same `created_by="studio"` kwarg.)

In `pipeline/api/sync_snapshot.py:138`:

```python
session.add(Activity(id=new_activity_id, **normalized, version=1, synced_version=1, created_by="cplan_sync"))
```

In `pipeline/api/import_snapshot.py:119`:

```python
activities.append(Activity(id=activity_id, **normalize_record(record), created_by="cplan_sync"))
```

`ensure_schema` (already in the lifespan and in sync jobs) tops existing databases up with the nullable column automatically — no migration step needed here.

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_api.py tests/test_sync.py tests/test_import.py -v`
Expected: PASS (all, including pre-existing tests).

- [ ] **Step 5: Commit**

```bash
git add pipeline/api/app.py pipeline/api/sync_snapshot.py pipeline/api/import_snapshot.py tests/
git commit -m "Add created_by ownership column to activities"
```

---

### Task 2: Auth module — session tokens and credential verification

**Files:**
- Create: `pipeline/api/auth.py`
- Modify: `pipeline/api/requirements.txt` (add `itsdangerous`)
- Test: `tests/test_auth.py`

**Interfaces:**
- Produces (consumed by Task 5):
  - `AuthSettings(secret: str, max_age_seconds: int = 43200, cookie_name: str = "cplan_session")` (frozen dataclass)
  - `auth_settings_from_environment(environ: Mapping[str, str] | None = None) -> AuthSettings | None` — reads `CPLAN_AUTH_SECRET`; `None` when unset/empty (auth disabled)
  - `create_session_token(settings: AuthSettings, username: str) -> str`
  - `verify_session_token(settings: AuthSettings, token: str) -> str | None` — username, or `None` on bad/expired token
  - `verify_credentials(database_url: str | URL, username: str, password: str) -> bool` — attempts a real Postgres connection with those credentials

- [ ] **Step 1: Add dependency**

Append `itsdangerous` to `pipeline/api/requirements.txt` and install:
Run: `PYTHONPATH= .venv/bin/python -m pip install itsdangerous`

- [ ] **Step 2: Write the failing tests**

Create `tests/test_auth.py`:

```python
import pytest

from pipeline.api.auth import (
    AuthSettings,
    auth_settings_from_environment,
    create_session_token,
    verify_credentials,
    verify_session_token,
)


def test_environment_disabled_when_secret_missing_or_empty():
    assert auth_settings_from_environment({}) is None
    assert auth_settings_from_environment({"CPLAN_AUTH_SECRET": ""}) is None


def test_environment_enabled_with_secret():
    settings = auth_settings_from_environment({"CPLAN_AUTH_SECRET": "s3cret"})
    assert settings == AuthSettings(secret="s3cret")
    assert settings.cookie_name == "cplan_session"
    assert settings.max_age_seconds == 43200


def test_token_roundtrip():
    settings = AuthSettings(secret="s3cret")
    token = create_session_token(settings, "alice")
    assert verify_session_token(settings, token) == "alice"


def test_token_rejected_with_wrong_secret_or_garbage():
    settings = AuthSettings(secret="s3cret")
    token = create_session_token(settings, "alice")
    assert verify_session_token(AuthSettings(secret="other"), token) is None
    assert verify_session_token(settings, "not-a-token") is None


def test_token_rejected_when_expired():
    settings = AuthSettings(secret="s3cret", max_age_seconds=0)
    token = create_session_token(settings, "alice")
    import time

    time.sleep(1.1)
    assert verify_session_token(settings, token) is None


def test_verify_credentials_rejects_unreachable_database():
    # Connection refused == False, never an exception.
    assert verify_credentials("postgresql+psycopg://u:pw@127.0.0.1:1/cplan", "u", "pw") is False
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_auth.py -v`
Expected: FAIL — `ModuleNotFoundError: pipeline.api.auth`.

- [ ] **Step 4: Implement `pipeline/api/auth.py`**

```python
"""Session tokens and Postgres-delegated credential verification for the CPLAN API.

Passwords are never stored or hashed here: `verify_credentials` simply attempts
a real database connection with the supplied username/password, so the
authority on passwords is PostgreSQL itself (SCRAM). The session token is a
signed, timestamped pointer to the username — not an authority: even a forged
role claim only changes UI rendering, Postgres rejects unauthorized statements
with 42501 (see the design spec).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import create_engine, make_url, select, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

_TOKEN_SALT = "cplan-session"


@dataclass(frozen=True)
class AuthSettings:
    secret: str
    max_age_seconds: int = 43200  # 12h — one working day with margin
    cookie_name: str = "cplan_session"


def auth_settings_from_environment(environ: Mapping[str, str] | None = None) -> AuthSettings | None:
    environment = os.environ if environ is None else environ
    secret = environment.get("CPLAN_AUTH_SECRET", "")
    if not secret:
        return None
    return AuthSettings(secret=secret)


def _serializer(settings: AuthSettings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.secret, salt=_TOKEN_SALT)


def create_session_token(settings: AuthSettings, username: str) -> str:
    return _serializer(settings).dumps({"u": username})


def verify_session_token(settings: AuthSettings, token: str) -> str | None:
    try:
        payload = _serializer(settings).loads(token, max_age=settings.max_age_seconds)
    except (BadSignature, SignatureExpired):
        return None
    username = payload.get("u") if isinstance(payload, dict) else None
    return username if isinstance(username, str) and username else None


def verify_credentials(database_url: str | URL, username: str, password: str) -> bool:
    """True iff PostgreSQL accepts a connection as `username`/`password`.

    NullPool + immediate dispose: this is a throwaway probe connection, it must
    never linger in a pool. Any failure — bad password, NOLOGIN (deactivated
    user), unknown role, unreachable server — is simply `False`; the caller
    turns that into a uniform 401 without leaking which part failed.
    """
    probe_url = make_url(database_url).set(username=username, password=password)
    engine = create_engine(probe_url, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            connection.execute(select(1))
        return True
    except SQLAlchemyError:
        return False
    finally:
        engine.dispose()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_auth.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pipeline/api/auth.py pipeline/api/requirements.txt tests/test_auth.py
git commit -m "Add auth module: signed session tokens, Postgres-delegated credential check"
```

---

### Task 3: `setup_roles.py` — role DDL, RLS policies, user management CLI

**Files:**
- Create: `pipeline/api/setup_roles.py`
- Test: `tests/test_setup_roles.py`

**Interfaces:**
- Consumes: `pipeline.api.database.create_cplan_engine`, `embedded_database_url`, `database_url_from_environment`; `pipeline.api.setup_backend.load_backend_config`, `resolve_backend_database_url` (same URL resolution `pipeline/scripts/start_cplan.py` uses — mirror it exactly).
- Produces (consumed by Tasks 4-6 and Plan 2):
  - `GROUP_ROLES: tuple[str, ...]`, `AUTHENTICATOR = "cplan_authenticator"`, `ASSIGNABLE_ROLES: dict[str, str]` (`{"viewer": "cplan_viewer", "contributor": "cplan_contributor", "editor": "cplan_editor", "admin": "cplan_admin"}`)
  - `apply_roles(engine: Engine) -> None` — idempotent full DDL (roles, grants, `created_by` hardening, `actor` widening, RLS policies)
  - `create_user(engine, username: str, password: str, role_key: str) -> None`
  - `set_user_role(engine, username: str, role_key: str) -> None`
  - `set_user_password(engine, username: str, password: str) -> None`
  - `set_user_active(engine, username: str, active: bool) -> None` (`ALTER ROLE ... LOGIN/NOLOGIN`)
  - CLI: `python -m pipeline.api.setup_roles [--database-url URL] [--create-user NAME --role ROLE --password PW] [--set-role NAME --role ROLE] [--reset-password NAME --password PW] [--deactivate NAME] [--activate NAME]` — with no action flags it applies the DDL only.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_setup_roles.py` (real embedded Postgres, same skip guard and lifecycle as `tests/test_postgres_embedded.py`):

```python
"""setup_roles DDL against a real embedded PostgreSQL — roles, grants, RLS, idempotency."""

from __future__ import annotations

import importlib.util

import pytest
from sqlalchemy import text

from pipeline.api.app import Base
from pipeline.api.database import create_cplan_engine, embedded_database_url
from pipeline.api.setup_roles import (
    ASSIGNABLE_ROLES,
    AUTHENTICATOR,
    GROUP_ROLES,
    apply_roles,
    create_user,
    set_user_active,
    set_user_role,
)
from pipeline.scripts.cplan_db import stop

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("pgserver") is None,
    reason="pgserver is not installed; the postgres-embedded backend is optional (pip install pgserver)",
)


@pytest.fixture(scope="module")
def engine(tmp_path_factory):
    pgdata = tmp_path_factory.mktemp("roles") / "pgdata"
    engine = create_cplan_engine(embedded_database_url(pgdata))
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()
    stop(pgdata)


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
            connection.execute(text("SELECT polname FROM pg_policies WHERE tablename = 'activities'")).scalars()
        )
        assert policies == {"read_all", "contrib_insert", "contrib_update", "editor_write", "admin_delete"}


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_setup_roles.py -v`
Expected: FAIL — `ModuleNotFoundError: pipeline.api.setup_roles`.

- [ ] **Step 3: Implement `pipeline/api/setup_roles.py`**

```python
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

_POLICIES = ("read_all", "contrib_insert", "contrib_update", "editor_write", "admin_delete")


def _quote(connection: Connection, identifier: str) -> str:
    return connection.dialect.identifier_preparer.quote(identifier)


def _pw_literal(password: str) -> str:
    return "'" + password.replace("'", "''") + "'"


def _role_exists(connection: Connection, name: str) -> bool:
    return connection.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :n"), {"n": name}).first() is not None


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
    group = _resolve_group(role_key)
    with engine.begin() as c:
        if _role_exists(c, username):
            raise ValueError(f"Role {username!r} already exists; use set-role/reset-password instead")
        q = _quote(c, username)
        c.exec_driver_sql(f"CREATE ROLE {q} LOGIN PASSWORD {_pw_literal(password)}")
        c.exec_driver_sql(f"GRANT {group} TO {q}")
        c.exec_driver_sql(f"GRANT {q} TO {AUTHENTICATOR}")


def set_user_role(engine: Engine, username: str, role_key: str) -> None:
    group = _resolve_group(role_key)
    with engine.begin() as c:
        q = _quote(c, username)
        for other in ASSIGNABLE_ROLES.values():
            c.exec_driver_sql(f"REVOKE {other} FROM {q}")
        c.exec_driver_sql(f"GRANT {group} TO {q}")


def set_user_password(engine: Engine, username: str, password: str) -> None:
    with engine.begin() as c:
        c.exec_driver_sql(f"ALTER ROLE {_quote(c, username)} PASSWORD {_pw_literal(password)}")


def set_user_active(engine: Engine, username: str, active: bool) -> None:
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
```

Check `pipeline/api/setup_backend.py` for `load_backend_config`'s default settings path — if it has no default argument, pass the same default path constant `start_cplan.py` uses.

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_setup_roles.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/api/setup_roles.py tests/test_setup_roles.py
git commit -m "Add setup_roles: group roles, RLS policies, and user management CLI"
```

---

### Task 4: Rights-matrix integration tests (SQL level)

**Files:**
- Test: `tests/test_rbac_matrix.py` (new; test-only task — it validates Task 3's DDL from the perspective of each role)

**Interfaces:**
- Consumes: `apply_roles`, `create_user` from Task 3; `Activity`, `Base` from `pipeline.api.app`.
- Produces: `role_connection(engine, username)` context-manager helper other tests may copy (SET ROLE / RESET ROLE around a connection).

- [ ] **Step 1: Write the matrix tests (these should largely pass immediately — they are the verification harness for Task 3; any failure here is a Task 3 bug to fix now)**

Create `tests/test_rbac_matrix.py`:

```python
"""Every role × every operation × own/foreign rows, against real embedded Postgres.

The suite connects as the embedded superuser and impersonates each user via
SET ROLE — exactly what the API does per request (Task 5) — so what passes
here is what production enforces. 42501 = insufficient_privilege; RLS's
write-policy violation reports the same SQLSTATE; RLS on UPDATE/DELETE
without a matching policy row silently affects 0 rows.
"""

from __future__ import annotations

import contextlib
import importlib.util
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from pipeline.api.app import Base
from pipeline.api.database import create_cplan_engine, embedded_database_url
from pipeline.api.setup_roles import apply_roles, create_user
from pipeline.scripts.cplan_db import stop

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("pgserver") is None,
    reason="pgserver is not installed; the postgres-embedded backend is optional (pip install pgserver)",
)

OWN_ID = uuid.uuid4()
FOREIGN_ID = uuid.uuid4()  # owned by cplan_sync (a mirrored row)


@pytest.fixture(scope="module")
def engine(tmp_path_factory):
    pgdata = tmp_path_factory.mktemp("matrix") / "pgdata"
    engine = create_cplan_engine(embedded_database_url(pgdata))
    Base.metadata.create_all(engine)
    apply_roles(engine)
    for name, role in (("m_viewer", "viewer"), ("m_contrib", "contributor"), ("m_editor", "editor"), ("m_admin", "admin")):
        create_user(engine, name, f"pw-{name}", role)
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO activities (id, source_type, activity_name, version, is_archive, created_by) "
                "VALUES (:i1, 'internal', 'own row', 1, false, 'm_contrib'), "
                "       (:i2, 'internal', 'mirrored row', 1, false, 'cplan_sync')"
            ),
            {"i1": OWN_ID, "i2": FOREIGN_ID},
        )
    yield engine
    engine.dispose()
    stop(pgdata)
```

(If `activities` has further NOT NULL columns without defaults, extend the INSERT accordingly — check the model, not trial and error.)

```python
@contextlib.contextmanager
def role_connection(engine, username):
    connection = engine.connect()
    try:
        connection.exec_driver_sql(f'SET ROLE "{username}"')
        connection.commit()  # SET is transactional; commit so later rollbacks keep the role
        yield connection
    finally:
        connection.rollback()
        connection.exec_driver_sql("RESET ROLE")
        connection.commit()
        connection.close()


def _insert(connection, created_by):
    connection.execute(
        text(
            "INSERT INTO activities (id, source_type, activity_name, version, is_archive, created_by) "
            "VALUES (:i, 'internal', 'inserted', 1, false, :cb)"
        ),
        {"i": uuid.uuid4(), "cb": created_by},
    )


def _update(connection, target_id):
    return connection.execute(
        text("UPDATE activities SET activity_name = 'renamed' WHERE id = :i"), {"i": target_id}
    ).rowcount


def _delete(connection, target_id):
    return connection.execute(text("DELETE FROM activities WHERE id = :i"), {"i": target_id}).rowcount


def _assert_denied(callable_):
    with pytest.raises(ProgrammingError) as excinfo:
        callable_()
    assert excinfo.value.orig.sqlstate == "42501"


def test_everyone_reads_everything(engine):
    for user in ("m_viewer", "m_contrib", "m_editor", "m_admin"):
        with role_connection(engine, user) as c:
            count = c.execute(text("SELECT count(*) FROM activities")).scalar_one()
            assert count >= 2, user
            c.rollback()


def test_viewer_cannot_write_at_all(engine):
    with role_connection(engine, "m_viewer") as c:
        _assert_denied(lambda: _insert(c, "m_viewer")); c.rollback()
        _assert_denied(lambda: _update(c, OWN_ID)); c.rollback()
        _assert_denied(lambda: _delete(c, OWN_ID)); c.rollback()


def test_contributor_inserts_as_self_but_cannot_spoof(engine):
    with role_connection(engine, "m_contrib") as c:
        _insert(c, "m_contrib")
        c.rollback()  # keep fixture data stable
        _assert_denied(lambda: _insert(c, "somebody_else"))
        c.rollback()


def test_contributor_updates_own_but_not_foreign_and_never_deletes(engine):
    with role_connection(engine, "m_contrib") as c:
        assert _update(c, OWN_ID) == 1
        c.rollback()
        assert _update(c, FOREIGN_ID) == 0  # RLS filters silently — no error, no effect
        c.rollback()
        _assert_denied(lambda: _delete(c, OWN_ID))
        c.rollback()


def test_editor_updates_everything_but_cannot_delete(engine):
    with role_connection(engine, "m_editor") as c:
        assert _update(c, OWN_ID) == 1
        c.rollback()
        assert _update(c, FOREIGN_ID) == 1
        c.rollback()
        _assert_denied(lambda: _delete(c, FOREIGN_ID))
        c.rollback()


def test_admin_updates_and_deletes_everything(engine):
    with role_connection(engine, "m_admin") as c:
        assert _update(c, FOREIGN_ID) == 1
        c.rollback()
        assert _delete(c, OWN_ID) == 1
        c.rollback()
        assert _delete(c, FOREIGN_ID) == 1
        c.rollback()
```

- [ ] **Step 2: Run the suite**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_rbac_matrix.py -v`
Expected: PASS. Any failure is a defect in Task 3's DDL — fix `setup_roles.py` (not the test) until the matrix is green, and re-run `tests/test_setup_roles.py` afterwards.

- [ ] **Step 3: Commit**

```bash
git add tests/test_rbac_matrix.py pipeline/api/setup_roles.py
git commit -m "Add role-by-operation RBAC matrix tests against embedded Postgres"
```

---

### Task 5: API auth wiring — login, per-request SET ROLE, real actor

**Files:**
- Modify: `pipeline/api/app.py` (create_app ~line 525: dependencies, new endpoints, handler refactor, exception handler; `ActivityChange.actor` column ~line 215 → `String(64)`)
- Test: `tests/test_api_auth.py` (new), `tests/test_api.py` (regression, unmodified)

**Interfaces:**
- Consumes: Task 2's `AuthSettings`, `auth_settings_from_environment`, `create_session_token`, `verify_session_token`, `verify_credentials`; Task 3's role model.
- Produces:
  - `create_app(database_url=None, auth_settings: AuthSettings | None = None)` — `auth_settings` param overrides the environment; auth is active only when settings exist AND backend is postgresql.
  - `CurrentUser(username: str, db_role: str | None)` frozen dataclass (`db_role is None` = legacy solo mode, no SET ROLE).
  - Endpoints: `POST /api/login {username, password}` → `{"username": ...}` + `Set-Cookie`; `POST /api/logout` → clears cookie; `GET /api/me` → `{"username", "role": "viewer"|"contributor"|"editor"|"admin", "auth": bool}` (legacy mode: `{"username": "studio", "role": "editor", "auth": false}`).
  - All `/api/activities*` and `/api/sync-runs*` endpoints return `401 {"code": "unauthenticated"}` without a valid session when auth is enabled; Postgres privilege violations surface as `403 {"code": "forbidden"}`; contributor patching a foreign row gets `403 {"code": "forbidden_not_owner"}`.
  - `ActivityChange.actor` records the username (auth mode) or `"studio"` (legacy mode); `created_by` likewise.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_api_auth.py` (embedded Postgres; skip guard as in Task 3/4). Shared fixture:

```python
"""End-to-end auth + RBAC through the FastAPI TestClient against embedded Postgres."""

from __future__ import annotations

import importlib.util

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from pipeline.api.app import Base, create_app
from pipeline.api.auth import AuthSettings
from pipeline.api.database import create_cplan_engine, embedded_database_url
from pipeline.api.setup_roles import apply_roles, create_user
from pipeline.scripts.cplan_db import stop

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("pgserver") is None,
    reason="pgserver is not installed; the postgres-embedded backend is optional (pip install pgserver)",
)

SETTINGS = AuthSettings(secret="test-secret")
PASSWORDS = {"a_viewer": "pw-v", "a_contrib": "pw-c", "a_editor": "pw-e", "a_admin": "pw-a"}


@pytest.fixture(scope="module")
def api(tmp_path_factory):
    pgdata = tmp_path_factory.mktemp("apiauth") / "pgdata"
    url = embedded_database_url(pgdata)
    engine = create_cplan_engine(url)
    Base.metadata.create_all(engine)
    apply_roles(engine)
    for name, role in (("a_viewer", "viewer"), ("a_contrib", "contributor"), ("a_editor", "editor"), ("a_admin", "admin")):
        create_user(engine, name, PASSWORDS[name], role)
    engine.dispose()
    app = create_app(url, auth_settings=SETTINGS)
    with TestClient(app) as client:
        yield app, url
    stop(pgdata)


def login(app, username):
    client = TestClient(app)
    response = client.post("/api/login", json={"username": username, "password": PASSWORDS[username]})
    assert response.status_code == 200, response.text
    return client


PAYLOAD = {"source_type": "internal", "activity_name": "Auth test activity"}
```

Tests:

```python
def test_unauthenticated_requests_are_rejected(api):
    app, _ = api
    client = TestClient(app)
    assert client.get("/api/activities").status_code == 401
    assert client.post("/api/activities", json=PAYLOAD).status_code == 401
    assert client.get("/api/health").status_code == 200  # health stays open


def test_login_rejects_wrong_password_uniformly(api):
    app, _ = api
    client = TestClient(app)
    assert client.post("/api/login", json={"username": "a_viewer", "password": "wrong"}).status_code == 401
    assert client.post("/api/login", json={"username": "ghost", "password": "wrong"}).status_code == 401


def test_me_reports_username_and_role(api):
    app, _ = api
    assert login(app, "a_admin").get("/api/me").json() == {"username": "a_admin", "role": "admin", "auth": True}
    assert login(app, "a_viewer").get("/api/me").json() == {"username": "a_viewer", "role": "viewer", "auth": True}


def test_viewer_reads_but_cannot_create(api):
    app, _ = api
    client = login(app, "a_viewer")
    assert client.get("/api/activities").status_code == 200
    response = client.post("/api/activities", json=PAYLOAD)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "forbidden"


def test_contributor_creates_with_ownership_and_real_actor(api):
    app, url = api
    client = login(app, "a_contrib")
    created = client.post("/api/activities", json=PAYLOAD)
    assert created.status_code == 201
    body = created.json()
    assert body["created_by"] == "a_contrib"
    changes = client.get(f"/api/activities/{body['id']}/changes").json()["items"]
    assert changes[-1]["actor"] == "a_contrib"


def test_contributor_edits_own_but_not_foreign(api):
    app, _ = api
    contrib = login(app, "a_contrib")
    own = contrib.post("/api/activities", json=PAYLOAD).json()
    patch = contrib.patch(f"/api/activities/{own['id']}", json={"version": own["version"], "priority": "High"})
    assert patch.status_code == 200

    editor = login(app, "a_editor")
    foreign = editor.post("/api/activities", json=PAYLOAD).json()
    denied = contrib.patch(f"/api/activities/{foreign['id']}", json={"version": foreign["version"], "priority": "High"})
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "forbidden_not_owner"


def test_editor_edits_foreign_rows(api):
    app, _ = api
    contrib = login(app, "a_contrib")
    row = contrib.post("/api/activities", json=PAYLOAD).json()
    editor = login(app, "a_editor")
    assert editor.patch(
        f"/api/activities/{row['id']}", json={"version": row["version"], "priority": "High"}
    ).status_code == 200


def test_logout_clears_session(api):
    app, _ = api
    client = login(app, "a_viewer")
    assert client.post("/api/logout").status_code == 200
    assert client.get("/api/activities").status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_api_auth.py -v`
Expected: FAIL — `create_app` has no `auth_settings` parameter / no login endpoint.

- [ ] **Step 3: Implement in `pipeline/api/app.py`**

3a. Widen the audit actor column (model line ~215):

```python
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
```

3b. New imports at the top: `from dataclasses import dataclass`, `from typing import Iterator`, `from fastapi import Depends, Request, Response`, `from fastapi.responses import JSONResponse`, `from sqlalchemy import text`, `from sqlalchemy.exc import ProgrammingError`, and from `.auth`: `AuthSettings, auth_settings_from_environment, create_session_token, verify_credentials, verify_session_token`.

3c. `CurrentUser` at module level:

```python
@dataclass(frozen=True)
class CurrentUser:
    username: str
    db_role: str | None  # None: legacy solo mode — no SET ROLE, actor "studio"
```

3d. Inside `create_app`, after `engine` is built:

```python
def create_app(database_url: str | URL | None = None, auth_settings: AuthSettings | None = None) -> FastAPI:
    ...
    auth = auth_settings if auth_settings is not None else auth_settings_from_environment()
    if backend != "postgresql":
        auth = None  # roles are Postgres-only; SQLite stays the solo-mode fallback
```

3e. Dependencies (inside `create_app`, before the endpoints):

```python
    def current_user(request: Request) -> CurrentUser:
        if auth is None:
            return CurrentUser(username="studio", db_role=None)
        token = request.cookies.get(auth.cookie_name)
        username = verify_session_token(auth, token) if token else None
        if username is None:
            raise HTTPException(status_code=401, detail={"code": "unauthenticated"})
        return CurrentUser(username=username, db_role=username)

    def db_session(user: CurrentUser = Depends(current_user)) -> Iterator[Session]:
        """One connection per request, impersonating the session user.

        SET ROLE (session-scoped, not SET LOCAL) + immediate commit: handlers
        commit and roll back mid-request (tracking-id retry loops), and a
        transaction-scoped role would silently revert on the first of those.
        RESET ROLE before the connection returns to the pool — the pool's
        rollback-on-return does NOT reset the role.
        """
        connection = engine.connect()
        try:
            if user.db_role is not None:
                quoted = engine.dialect.identifier_preparer.quote(user.db_role)
                try:
                    connection.exec_driver_sql(f"SET ROLE {quoted}")
                    connection.commit()
                except ProgrammingError:
                    # Valid token but the role vanished (user deleted): dead session.
                    raise HTTPException(status_code=401, detail={"code": "unauthenticated"})
            session = Session(bind=connection)
            try:
                yield session
            finally:
                session.close()
        finally:
            try:
                connection.rollback()
                if user.db_role is not None:
                    connection.exec_driver_sql("RESET ROLE")
                    connection.commit()
            finally:
                connection.close()
```

3f. Exception handler (privilege violations from any handler → clean 403):

```python
    @app.exception_handler(ProgrammingError)
    async def insufficient_privilege_handler(request: Request, exc: ProgrammingError):
        if getattr(exc.orig, "sqlstate", None) == "42501":
            return JSONResponse(status_code=403, content={"detail": {"code": "forbidden"}})
        raise exc
```

3g. Auth endpoints:

```python
    class LoginPayload(BaseModel):
        username: str = Field(min_length=1, max_length=63)  # Postgres identifier limit
        password: str

    @app.post("/api/login")
    def login(payload: LoginPayload, response: Response):
        if auth is None:
            return {"username": "studio"}
        if not verify_credentials(resolved_url, payload.username, payload.password):
            raise HTTPException(status_code=401, detail={"code": "invalid_credentials"})
        response.set_cookie(
            auth.cookie_name,
            create_session_token(auth, payload.username),
            max_age=auth.max_age_seconds,
            httponly=True,
            samesite="lax",
        )
        return {"username": payload.username}

    @app.post("/api/logout")
    def logout(response: Response):
        if auth is not None:
            response.delete_cookie(auth.cookie_name)
        return {"status": "ok"}

    @app.get("/api/me")
    def me(user: CurrentUser = Depends(current_user), session: Session = Depends(db_session)):
        if user.db_role is None:
            return {"username": user.username, "role": "editor", "auth": False}
        flags = session.execute(
            text(
                "SELECT pg_has_role(current_user, 'cplan_admin', 'member') AS is_admin, "
                "pg_has_role(current_user, 'cplan_editor', 'member') AS is_editor, "
                "pg_has_role(current_user, 'cplan_contributor', 'member') AS is_contributor"
            )
        ).one()
        role = (
            "admin" if flags.is_admin
            else "editor" if flags.is_editor
            else "contributor" if flags.is_contributor
            else "viewer"
        )
        return {"username": user.username, "role": role, "auth": True}
```

3h. Refactor the five data handlers to injected sessions. Mechanical pattern — add the two dependency parameters, delete the `with Session(engine) as session:` line, and de-indent the body one level. `/api/health` keeps its own `Session(engine)` (stays unauthenticated). Example, `create_activity`:

```python
    @app.post("/api/activities", response_model=ActivityRead, status_code=status.HTTP_201_CREATED)
    def create_activity(
        payload: ActivityCreate,
        user: CurrentUser = Depends(current_user),
        session: Session = Depends(db_session),
    ):
        tracking_id = _generate_unique_tracking_id(session, payload)
        activity_fields = payload.model_dump()
        attempts = 0
        while True:
            # (existing body unchanged, one indent level up, except:)
            activity = Activity(
                id=activity_id, **activity_fields, tracking_id=tracking_id, created_by=user.username
            )
            session.add(activity)
            session.add(
                ActivityChange(
                    activity_id=activity_id,
                    actor=user.username,
                    change_type="created",
                    version_to=1,
                )
            )
            ...
```

Apply the same to `create_activities_batch` (`created_by=user.username`, `actor=user.username`), `list_activities`, `update_activity` (`actor=user.username`), `list_activity_changes`, and `latest_sync_run`. In legacy mode `user.username == "studio"`, so existing behavior and tests are preserved verbatim.

3i. Ownership pre-check in `update_activity`, directly after the 404/version checks (~line 679) — turns the silent RLS no-op into an explicit 403:

```python
        if user.db_role is not None:
            may_edit_all = session.execute(
                text(
                    "SELECT pg_has_role(current_user, 'cplan_editor', 'member') "
                    "OR pg_has_role(current_user, 'cplan_admin', 'member')"
                )
            ).scalar_one()
            if not may_edit_all and current.created_by != user.username:
                raise HTTPException(status_code=403, detail={"code": "forbidden_not_owner"})
```

- [ ] **Step 4: Run the new suite and the full regression**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_api_auth.py tests/test_api.py tests/test_sync.py tests/test_import.py -v`
Expected: PASS — auth suite green AND every pre-existing test green in legacy mode.

- [ ] **Step 5: Commit**

```bash
git add pipeline/api/app.py tests/test_api_auth.py
git commit -m "Wire login, per-request SET ROLE, and real audit actors into the API"
```

---

### Task 6: Admin-only DELETE endpoint with surviving audit row

**Files:**
- Modify: `pipeline/api/app.py` (new endpoint after `update_activity`)
- Test: `tests/test_api_auth.py` (extend), `tests/test_api.py` (legacy-mode delete)

**Interfaces:**
- Consumes: Task 5's `current_user`/`db_session` dependencies and 403 exception handler.
- Produces: `DELETE /api/activities/{activity_id}` → `204`; `404 {"code": "not_found"}` for unknown ids; `403` (via the 42501 handler) for non-admins. Appends `ActivityChange(change_type="deleted", field=None, old_value=<JSON snapshot>)` where the snapshot is `{"tracking_id": ..., "activity_name": ...}` — the audit row has no FK and outlives the activity.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_api_auth.py`:

```python
def test_only_admin_deletes_and_audit_survives(api):
    app, url = api
    editor = login(app, "a_editor")
    row = editor.post("/api/activities", json=PAYLOAD).json()

    for username in ("a_viewer", "a_contrib", "a_editor"):
        assert login(app, username).delete(f"/api/activities/{row['id']}").status_code == 403

    admin = login(app, "a_admin")
    assert admin.delete(f"/api/activities/{row['id']}").status_code == 204
    assert admin.delete(f"/api/activities/{row['id']}").status_code == 404  # gone

    engine = create_cplan_engine(url)
    try:
        with engine.connect() as connection:
            deleted = connection.execute(
                text(
                    "SELECT actor, old_value FROM activity_changes "
                    "WHERE activity_id = :i AND change_type = 'deleted'"
                ),
                {"i": row["id"]},
            ).one()
        assert deleted.actor == "a_admin"
        assert row["tracking_id"] in deleted.old_value
    finally:
        engine.dispose()
```

Append to `tests/test_api.py` (legacy mode — single user acts as admin of their own local database):

```python
@pytest.mark.parametrize("backend", TEST_BACKENDS)
def test_delete_activity_legacy_mode(backend, tmp_path):
    client = make_client(backend, tmp_path)  # same helper as Task 1
    row = client.post("/api/activities", json=minimal_activity_payload()).json()
    assert client.delete(f"/api/activities/{row['id']}").status_code == 204
    assert client.get("/api/activities").json()["total"] == 0
    assert client.delete(f"/api/activities/{row['id']}").status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_api_auth.py::test_only_admin_deletes_and_audit_survives tests/test_api.py -k delete -v`
Expected: FAIL — 405 Method Not Allowed (endpoint missing).

- [ ] **Step 3: Implement** (after `update_activity`; add `delete as sqlalchemy_delete` to the existing `sqlalchemy` import):

```python
    @app.delete("/api/activities/{activity_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_activity(
        activity_id: uuid.UUID,
        user: CurrentUser = Depends(current_user),
        session: Session = Depends(db_session),
    ):
        current = session.get(Activity, activity_id)
        if current is None:
            raise HTTPException(status_code=404, detail={"code": "not_found"})
        snapshot = json.dumps(
            {"tracking_id": current.tracking_id, "activity_name": current.activity_name}
        )
        # Missing DELETE grant (everyone but admin) raises 42501 here -> the
        # global handler turns it into a clean 403 before any audit row exists.
        result = session.execute(sqlalchemy_delete(Activity).where(Activity.id == activity_id))
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail={"code": "not_found"})
        session.add(
            ActivityChange(
                activity_id=activity_id,
                actor=user.username,
                change_type="deleted",
                old_value=snapshot,
                version_from=current.version,
            )
        )
        session.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_api_auth.py tests/test_api.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/api/app.py tests/
git commit -m "Add admin-only DELETE endpoint with surviving audit snapshot"
```

---

### Task 7: Studio login overlay and session bootstrap

**Files:**
- Modify: `pipeline/studio/index.html` (overlay markup), `pipeline/studio/styles.css` (overlay styles), `pipeline/studio/app.js` (fetch wrapper, boot sequence, logout)
- Test: `tests/test_studio.py` (static-marker style, matching the existing suite)

**Interfaces:**
- Consumes: `POST /api/login`, `POST /api/logout`, `GET /api/me` from Task 5.
- Produces: `state.currentUser = {username, role, auth}` populated before first data fetch; `apiFetch(url, options)` wrapper used by ALL `/api/*` calls (Task 8 relies on both).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_studio.py` inside `StudioTests`:

```python
    def test_login_overlay_and_session_bootstrap(self):
        html = (DASHBOARD / "index.html").read_text(encoding="utf-8")
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")
        css = (DASHBOARD / "styles.css").read_text(encoding="utf-8")

        self.assertIn('id="login-overlay"', html)
        self.assertIn('autocomplete="current-password"', html)
        self.assertIn("/api/login", app)
        self.assertIn("/api/me", app)
        self.assertIn("/api/logout", app)
        self.assertIn("function apiFetch", app)
        self.assertNotIn("Anmelden", html)  # UI copy is English, matching the studio
        self.assertIn(".login-overlay", css)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_studio.py -k login -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

`index.html` — overlay directly after `<body>` (hidden by default; corporate palette per CLAUDE.md — white card on `#F7F7F5`, red primary button, 2px radius, no emojis):

```html
<div id="login-overlay" class="login-overlay hidden" role="dialog" aria-modal="true" aria-labelledby="login-title">
  <form id="login-form" class="login-card">
    <h2 id="login-title">Sign in</h2>
    <p class="login-subtitle">CPLAN Planning Studio</p>
    <label for="login-username">Username</label>
    <input id="login-username" name="username" autocomplete="username" required />
    <label for="login-password">Password</label>
    <input id="login-password" name="password" type="password" autocomplete="current-password" required />
    <p id="login-error" class="login-error hidden">Invalid username or password.</p>
    <button type="submit" class="btn-primary">Sign in</button>
  </form>
</div>
```

`styles.css` (append; reuse existing variables — the file already defines the corporate tokens):

```css
.login-overlay {
  position: fixed;
  inset: 0;
  background: var(--bg, #F7F7F5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}
.login-overlay.hidden { display: none; }
.login-card {
  background: #FFFFFF;
  border: 1px solid var(--surface, #ECEBE4);
  border-radius: 2px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
  padding: 32px;
  width: 320px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.login-card h2 { font-size: 24px; font-weight: 600; margin: 0; }
.login-subtitle { font-size: 14px; color: #7A7870; margin: 0 0 16px; }
.login-error { color: #BD000C; font-size: 12px; margin: 0; }
.login-error.hidden { display: none; }
```

`app.js` — near the top, the wrapper and session state; then route every existing `fetch("/api/...")` call through `apiFetch` (grep for `fetch(` — do not miss the health/sync-status calls):

```js
// --- session -----------------------------------------------------------
// state.currentUser: {username, role, auth} — populated by initSession()
// before any data loads. 401 from any API call re-opens the login overlay.
async function apiFetch(url, options) {
  const response = await fetch(url, options);
  if (response.status === 401) {
    showLoginOverlay();
    throw new Error("unauthenticated");
  }
  return response;
}

function showLoginOverlay() {
  document.getElementById("login-overlay").classList.remove("hidden");
  document.getElementById("login-username").focus();
}

function hideLoginOverlay() {
  document.getElementById("login-overlay").classList.add("hidden");
  document.getElementById("login-error").classList.add("hidden");
}

async function initSession() {
  const response = await fetch("/api/me");
  if (response.status === 401) {
    showLoginOverlay();
    return null;
  }
  state.currentUser = await response.json();
  return state.currentUser;
}

async function logout() {
  await fetch("/api/logout", { method: "POST" });
  window.location.reload();
}

document.getElementById("login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const username = document.getElementById("login-username").value.trim();
  const password = document.getElementById("login-password").value;
  const response = await fetch("/api/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!response.ok) {
    document.getElementById("login-error").classList.remove("hidden");
    return;
  }
  hideLoginOverlay();
  await initSession();
  await refreshAll(); // the studio's existing full-reload entry point — match its real name
});
```

Boot sequence: find the studio's existing init/boot function (the one that first calls `/api/activities`) and prepend `const user = await initSession(); if (!user) return;` so nothing loads until the session exists. In legacy mode `/api/me` returns 200 (`auth: false`) and the overlay never shows.

- [ ] **Step 4: Run tests + manual smoke**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_studio.py -v`
Expected: PASS (including the pre-existing marker/emoji tests).
Manual: `PYTHONPATH=. .venv/bin/python pipeline/scripts/start_cplan.py`, open the studio — no overlay in legacy mode; with `CPLAN_AUTH_SECRET=dev-secret` exported and a user created via `setup_roles.py`, the overlay appears and login works.

- [ ] **Step 5: Commit**

```bash
git add pipeline/studio/ tests/test_studio.py
git commit -m "Add studio login overlay and session bootstrap"
```

---

### Task 8: Role-aware studio UI (gating + delete)

**Files:**
- Modify: `pipeline/studio/app.js`, `pipeline/studio/index.html`, `pipeline/studio/styles.css`
- Test: `tests/test_studio.py`

**Interfaces:**
- Consumes: `state.currentUser` and `apiFetch` from Task 7; `DELETE /api/activities/{id}` from Task 6; `created_by` on activity rows from Task 1.
- Produces: `canCreate()`, `canEditActivity(activity)`, `canDelete()` helpers; a header user chip with username/role and a Sign-out action; a Delete action (admin only) in the detail drawer with a confirm step.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_studio.py`:

```python
    def test_role_gating_helpers_and_delete_action(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")
        html = (DASHBOARD / "index.html").read_text(encoding="utf-8")

        self.assertIn("function canCreate", app)
        self.assertIn("function canEditActivity", app)
        self.assertIn("function canDelete", app)
        self.assertIn("created_by", app)
        self.assertIn('id="user-chip"', html)
        self.assertIn("Sign out", app)
        self.assertIn("Delete activity", app)
        # DELETE verb actually used against the API
        self.assertIn('method: "DELETE"', app)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_studio.py -k role_gating -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

Helpers in `app.js` (below the session block from Task 7):

```js
// --- role gating -------------------------------------------------------
// Comfort only: the server (Postgres RLS/grants) is the authority; a
// manipulated UI gets 403 and the action simply fails.
function canCreate() {
  const role = state.currentUser?.role;
  return role === "contributor" || role === "editor" || role === "admin";
}

function canEditActivity(activity) {
  const user = state.currentUser;
  if (!user) return false;
  if (user.role === "editor" || user.role === "admin") return true;
  return user.role === "contributor" && activity.created_by === user.username;
}

function canDelete() {
  return state.currentUser?.role === "admin";
}
```

Apply the gates at the studio's existing render points (locate by grepping for the markers the existing tests assert on — the create entry point, the row/drawer edit affordances, the pack drawer trigger):

- Create entry point + pack drawer trigger: hide when `!canCreate()` (add/remove the existing `hidden` utility class).
- Row and drawer edit affordances (including duplicate): render only when `canEditActivity(activity)`.
- Drawer: add a "Delete activity" button, rendered only when `canDelete()`, with an inline confirm step (reuse the drawer's existing confirm pattern if one exists; otherwise a two-click "Delete activity" → "Confirm delete" swap — no `window.confirm`, matching studio conventions):

```js
async function deleteActivity(activityId) {
  const response = await apiFetch(`/api/activities/${activityId}`, { method: "DELETE" });
  if (response.status === 403) {
    showToast("You do not have permission to delete activities.");
    return;
  }
  closeDrawer();
  await refreshAll(); // match the studio's real reload entry point, as in Task 7
}
```

(`showToast`/`closeDrawer`: use the studio's existing toast/notification and drawer-close functions — grep for how the PATCH error paths surface messages and reuse exactly that mechanism.)

Header user chip in `index.html` (top-right, next to the existing header actions):

```html
<div id="user-chip" class="user-chip hidden">
  <span id="user-chip-name"></span>
  <button id="user-chip-logout" class="btn-ghost" type="button">Sign out</button>
</div>
```

Populate in `initSession()` (Task 7's function): set `#user-chip-name` to `${user.username} · ${user.role}`, unhide the chip only when `user.auth === true`, and bind `#user-chip-logout` to `logout()`. Style `.user-chip` in `styles.css`: 12px, Gray IV `#7A7870`, flex with 8px gap — consistent with the existing header metadata styling.

Also: after `initSession()` resolves, add `document.body.dataset.role = user.role` and re-run gating on data refresh, so late-loaded rows respect the role too.

- [ ] **Step 4: Run tests + manual role walk-through**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_studio.py -v`
Expected: PASS.
Manual (auth mode, one user per role): viewer sees no create/edit/delete affordances; contributor sees create + edit only on own rows; editor edits everything, no delete; admin sees delete with confirm and it removes the row.

- [ ] **Step 5: Commit**

```bash
git add pipeline/studio/ tests/test_studio.py
git commit -m "Gate studio actions by role and add admin delete with confirm"
```

---

### Task 9: Documentation

**Files:**
- Modify: `pipeline/api/README.md` (new "Authentication & roles" section), `README.md` (quick-start addition)
- Test: none (docs); full suite as final gate

**Interfaces:**
- Consumes: everything above — this task documents it.

- [ ] **Step 1: Write `pipeline/api/README.md` section**

Add an "Authentication & roles" section covering, in this order (write it out fully — concrete commands, no stubs):

1. **Enable**: `export CPLAN_AUTH_SECRET=<long random string>` (Postgres backends only; SQLite stays solo mode). One command to generate a secret: `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
2. **Set up roles + first admin**: `PYTHONPATH=. .venv/bin/python -m pipeline.api.setup_roles --create-user <name> --role admin` (prompts for password). Re-run plain `setup_roles` after schema changes — `GRANT ... ON ALL TABLES` only covers existing objects.
3. **Manage users**: `--create-user/--set-role/--reset-password/--deactivate/--activate` examples, one line each. Note this CLI is the interim admin surface until the portal (Plan 2) ships.
4. **The role model**: table mapping viewer/contributor/editor/admin to allowed operations, incl. "contributors edit only their own rows (RLS, `created_by`)" and "delete is admin-only, audit row survives".
5. **Central-server hardening**: on a shared instance, `pg_hba.conf` must use `scram-sha-256` for TCP connections; the embedded pgserver's default local trust config means `verify_credentials` accepts any password locally — fine for solo dev, not for the shared server. The API service itself should connect as `cplan_authenticator` (each user role is granted to it at creation).
6. **pgAdmin**: user roles can safely be handed direct read access — same grants as the studio enforces.

- [ ] **Step 2: Update root `README.md`**

In the corp quick-start block, add one line after the `import_snapshot` step:

```bash
PYTHONPATH=. .venv/bin/python -m pipeline.api.setup_roles   # multi-user only: roles + RLS (see pipeline/api/README.md)
```

and a one-sentence pointer: "Multi-user access control (login, viewer/contributor/editor/admin) is documented in [`pipeline/api/README.md`](pipeline/api/README.md#authentication--roles)."

- [ ] **Step 3: Full suite as final gate**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/ -v`
Expected: ALL PASS.

- [ ] **Step 4: Commit**

```bash
git add pipeline/api/README.md README.md
git commit -m "Document authentication, role model, and user management CLI"
```
