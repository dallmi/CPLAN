"""Shared PostgreSQL test-database fixtures for the postgres-backed test modules.

`tests/test_portal_api.py`, `tests/test_rbac_matrix.py`, `tests/test_session.py`,
`tests/test_setup_portal.py`, `tests/test_api_auth.py`, `tests/test_setup_roles.py`
and the one Postgres test in `tests/test_views.py` all need a real PostgreSQL
server. There are two ways to get one:

1. **Embedded (default, no setup).** `pgserver` starts a throwaway PostgreSQL 16
   cluster entirely inside pytest's `tmp_path`. Nothing to configure, but
   `pgserver` publishes no wheel for every platform (e.g. Python 3.13 on macOS
   arm64, as of 2026) -- on such a machine it is simply not installed, and
   dependent tests skip cleanly.

2. **External (opt-in via `CPLAN_TEST_DATABASE_URL`).** Point it at any
   PostgreSQL server a test run may freely create databases and roles in --
   this repository's own `compose.yaml` ships exactly such a server:

       CPLAN_DB_PASSWORD=<pick one> docker compose up -d db

   which publishes on `127.0.0.1:55432`, database `cplan`, user `cplan` (a
   superuser inside that container -- these tests create roles, which requires
   superuser). Then run the tests with:

       CPLAN_TEST_DATABASE_URL=postgresql+psycopg://cplan:<password>@127.0.0.1:55432/cplan \
           pytest tests/test_portal_api.py tests/test_rbac_matrix.py -q

`pipeline/api/README.md`'s Tests section documents the same variable.

When neither is available, dependent tests skip -- the default on a machine
with nothing configured, same as today.

## Isolation across modules and across repeated runs

`apply_roles`/`apply_portal`/`create_user` (`pipeline/api/setup_roles.py`,
`pipeline/api/setup_portal.py`) create PostgreSQL ROLES, and roles are
cluster-global, not database-scoped -- unlike the embedded path, where every
module gets its own throwaway *cluster* (a fresh `pgdata` under `tmp_path`),
every module sharing one external cluster would otherwise collide on role
names, and a second run would collide with the first run's leftovers.

Two things make this safe:

- **A freshly, uniquely named database per module**, dropped in teardown.
  `apply_roles`/`apply_portal` are already idempotent (they check
  `pg_roles`/`information_schema` before creating anything), so re-running
  them against a shared cluster is safe on its own -- but the *data* (the
  `activities` table, the `portal` schema, RLS policies) must not leak
  between modules or runs, hence the dedicated database.
- **A before/after snapshot of `pg_roles` around each module's database,
  diffed at teardown.** Every role a module's fixture or its test bodies
  create -- the fixed-name group roles (`cplan_viewer` etc.), the ad hoc
  login roles a fixture creates directly (`pa_admin`, `m_viewer`, ...), *and*
  roles created indirectly through the API during a test (e.g.
  `test_admin_creates_and_manages_user` creating `pa_new` via
  `POST /api/portal/users`) -- is new relative to the snapshot taken right
  after the database was created, so all of them get dropped, without the
  helper needing to know each module's specific usernames. `DROP DATABASE`
  runs first, which drops every RLS policy/grant/ownership tied to that
  database from `pg_shdepend`, so the subsequent `DROP ROLE` calls have
  nothing left depending on them and never fail with "role cannot be dropped
  because some objects depend on it".

This survives a second consecutive run because nothing is left behind: the
database is gone and every role the module touched is gone, so the next
run's `apply_roles`/`create_user` start from a clean slate again (creating
the group roles is idempotent either way, but the ad hoc login roles --
which are *not* idempotent, `create_user` raises if the role already exists
-- absolutely need this cleanup, or the second run's
`test_admin_creates_and_manages_user`-style tests would fail to create a
user that "already exists" from the first run).

Not handled (out of scope for this task): two *concurrent* runs against the
same external cluster (e.g. `pytest -n auto` across processes) would still
race on the fixed-name group roles, since those names are not per-run
unique. Sequential runs -- including two full suite runs back to back -- are
what this is designed for and verified against.
"""

from __future__ import annotations

import importlib.util
import os
import uuid
from typing import Callable

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from pipeline.api.database import embedded_database_url
from pipeline.api.scram import build_verifier
from pipeline.scripts.cplan_db import stop

HAS_PGSERVER = importlib.util.find_spec("pgserver") is not None
EXTERNAL_DATABASE_URL = os.environ.get("CPLAN_TEST_DATABASE_URL")


def scram_literal(password: str) -> str:
    """`password` as a SCRAM verifier, wrapped as a SQL string literal.

    `portal.create_user`/`portal.reset_password` refuse anything that is not a
    verifier (pipeline/api/scram.py), so a test calling them as raw SQL has to
    hash first, exactly as the portal service does. Safe to splice into an
    `exec_driver_sql` string: a verifier is base64 plus `$:=`, so there is no
    quote to escape and no `%` for psycopg's placeholder scan to trip over.
    """
    return "'" + build_verifier(password) + "'"

# Shared skip condition for every module that needs a real PostgreSQL server:
# skip only when NEITHER path is available, so a machine with nothing
# configured sees exactly the skips it sees today.
postgres_required = pytest.mark.skipif(
    not HAS_PGSERVER and not EXTERNAL_DATABASE_URL,
    reason=(
        "neither pgserver nor CPLAN_TEST_DATABASE_URL is available; these tests need a real "
        "PostgreSQL server (pip install pgserver for an embedded one, or set "
        "CPLAN_TEST_DATABASE_URL -- see tests/conftest.py)"
    ),
)


def postgres_test_database(tmp_path_factory, label: str) -> tuple[str, Callable[[], None]]:
    """A fresh, isolated PostgreSQL database URL plus its teardown callable.

    Picks the external `CPLAN_TEST_DATABASE_URL` when set, the embedded
    `pgserver` backend otherwise -- mirroring the module-level
    `postgres_required` skip condition, so a caller never reaches here with
    neither available. `label` becomes part of the temp dir name (embedded
    path) or the generated database name (external path); pass something
    short and unique per module (e.g. the module's existing `tmp_path_factory
    .mktemp("...")` label).
    """
    if EXTERNAL_DATABASE_URL:
        return _external_test_database(label)

    pgdata = tmp_path_factory.mktemp(label) / "pgdata"
    url = embedded_database_url(pgdata)
    return url, lambda: stop(pgdata)


def _external_test_database(label: str) -> tuple[str, Callable[[], None]]:
    base_url = make_url(EXTERNAL_DATABASE_URL)
    db_name = f"cplan_test_{label}_{uuid.uuid4().hex[:8]}"
    admin_engine = create_engine(base_url, isolation_level="AUTOCOMMIT")
    quote = admin_engine.dialect.identifier_preparer.quote

    with admin_engine.connect() as connection:
        connection.execute(text(f"CREATE DATABASE {quote(db_name)}"))
        # Snapshot BEFORE the caller's own fixture runs apply_roles/apply_portal/
        # create_user (or any test body creates a role via the API) -- see the
        # module docstring for why the diff at teardown is what makes this safe
        # to re-run.
        roles_before = {row[0] for row in connection.execute(text("SELECT rolname FROM pg_roles"))}

    # NOT str(...): SQLAlchemy's URL.__str__ hides the password by default
    # (renders it as "***"), which would make every connection to the fresh
    # per-test database fail authentication with the literal string "***".
    database_url = base_url.set(database=db_name).render_as_string(hide_password=False)

    def teardown() -> None:
        try:
            with admin_engine.connect() as connection:
                connection.execute(text(f"DROP DATABASE IF EXISTS {quote(db_name)} WITH (FORCE)"))
                roles_after = {row[0] for row in connection.execute(text("SELECT rolname FROM pg_roles"))}
                for role in sorted(roles_after - roles_before):
                    connection.execute(text(f"DROP ROLE IF EXISTS {quote(role)}"))
        finally:
            admin_engine.dispose()

    return database_url, teardown
