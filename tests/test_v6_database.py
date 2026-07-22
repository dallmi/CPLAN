import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from pipeline.api_v6.database import backend_from_url, create_cplan_engine


def test_backend_is_derived_from_sqlalchemy_url():
    assert backend_from_url("postgresql+psycopg://user@localhost/cplan") == "postgresql"
    assert backend_from_url("sqlite:////tmp/cplan.sqlite3") == "sqlite"

    with pytest.raises(ValueError, match="Unsupported database backend"):
        backend_from_url("mysql+pymysql://user@localhost/cplan")


def test_sqlite_engine_enables_safe_local_pragmas(tmp_path):
    database_path = tmp_path / "cplan.sqlite3"
    engine = create_cplan_engine(f"sqlite:///{database_path}")

    with engine.connect() as connection:
        foreign_keys = connection.execute(text("PRAGMA foreign_keys")).scalar_one()
        journal_mode = connection.execute(text("PRAGMA journal_mode")).scalar_one()
        busy_timeout = connection.execute(text("PRAGMA busy_timeout")).scalar_one()

    assert foreign_keys == 1
    assert journal_mode.lower() == "wal"
    assert busy_timeout == 5000
    engine.dispose()


def test_sqlite_foreign_keys_are_enforced(tmp_path):
    engine = create_cplan_engine(f"sqlite:///{tmp_path / 'foreign-keys.sqlite3'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE parent (id INTEGER PRIMARY KEY)"))
        connection.execute(
            text("CREATE TABLE child (id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES parent(id))")
        )
        with pytest.raises(IntegrityError):
            connection.execute(text("INSERT INTO child (id, parent_id) VALUES (1, 99)"))
    engine.dispose()
