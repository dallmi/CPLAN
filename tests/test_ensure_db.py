"""Tests for `pipeline/api/ensure_db.py` -- the schema step `setup.ps1` runs before setup_roles.

The regression these guard: `setup_roles.apply_roles` opens with
`ALTER TABLE activities ADD COLUMN IF NOT EXISTS created_by TEXT`, which raises
`UndefinedTable` when no table exists yet. A first `setup.cmd` against a fresh
`pgdata` therefore failed until the schema was created up front.
"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect

from pipeline.api.app import Base
from pipeline.api.database import create_cplan_engine
from pipeline.api.ensure_db import ensure_database


@pytest.fixture
def engine(tmp_path):
    engine = create_cplan_engine(f"sqlite:///{tmp_path / 'ensure-db.sqlite3'}")
    yield engine
    engine.dispose()


def test_creates_the_full_schema_on_an_empty_database(engine):
    assert inspect(engine).get_table_names() == []

    created = ensure_database(engine)

    assert set(created) == {table.name for table in Base.metadata.sorted_tables}
    assert "activities" in created


def test_activities_carries_created_by_so_apply_roles_can_harden_it(engine):
    """apply_roles' first statements target activities.created_by -- it must exist."""
    ensure_database(engine)

    columns = {column["name"] for column in inspect(engine).get_columns("activities")}
    assert "created_by" in columns


def test_is_idempotent_and_reports_nothing_created_on_a_second_run(engine):
    ensure_database(engine)

    assert ensure_database(engine) == []


def test_a_database_from_before_a_new_column_picks_it_up(engine):
    """No hand-written migration exists in this project, so a model column that
    `ensure_schema` cannot add would simply never reach a deployed database --
    and the field would read as permanently empty rather than as broken.

    `other_executives` is the concrete case: added to the model after the live
    databases were created.
    """
    from sqlalchemy import text

    ensure_database(engine)
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE activities DROP COLUMN other_executives"))
    assert "other_executives" not in _columns(engine)

    ensure_database(engine)

    assert "other_executives" in _columns(engine)


def _columns(engine):
    return {column["name"] for column in inspect(engine).get_columns("activities")}
