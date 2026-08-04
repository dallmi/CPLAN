"""Every role × every operation × own/foreign rows, against real embedded Postgres.

The suite connects as the embedded superuser and impersonates each user via
SET ROLE — exactly what the API does per request (Task 5) — so what passes
here is what production enforces. 42501 = insufficient_privilege; RLS's
write-policy violation reports the same SQLSTATE; RLS on UPDATE/DELETE
without a matching policy row silently affects 0 rows.
"""

from __future__ import annotations

import contextlib
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from pipeline.api.app import Base
from pipeline.api.database import create_cplan_engine
from pipeline.api.setup_roles import apply_roles, create_user
from tests.conftest import postgres_required, postgres_test_database

pytestmark = postgres_required

OWN_ID = uuid.uuid4()
FOREIGN_ID = uuid.uuid4()  # owned by cplan_sync (a mirrored row)


@pytest.fixture(scope="module")
def engine(tmp_path_factory):
    url, teardown = postgres_test_database(tmp_path_factory, "matrix")
    engine = create_cplan_engine(url)
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
    teardown()


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
