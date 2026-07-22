import pytest
from sqlalchemy import Column, MetaData, Table, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pipeline.api_v6.app import Activity, Base
from pipeline.api_v6.database import backend_from_url, create_cplan_engine, ensure_schema


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


def _create_legacy_activities_table_without_time_zone(engine) -> None:
    """Recreate the `activities` table as it looked before `time_zone` existed."""
    activities = Base.metadata.tables["activities"]
    legacy_metadata = MetaData()
    legacy_columns = [
        Column(
            column.name,
            column.type,
            primary_key=column.primary_key,
            nullable=column.nullable,
            server_default=column.server_default,
        )
        for column in activities.columns
        if column.name != "time_zone"
    ]
    Table(activities.name, legacy_metadata, *legacy_columns)
    legacy_metadata.create_all(engine)


def test_ensure_schema_adds_missing_column_to_an_existing_table(tmp_path):
    engine = create_cplan_engine(f"sqlite:///{tmp_path / 'schema-topup.sqlite3'}")
    _create_legacy_activities_table_without_time_zone(engine)

    columns_before = {column["name"] for column in inspect(engine).get_columns("activities")}
    assert "time_zone" not in columns_before

    ensure_schema(engine, Base.metadata)

    columns_after = {column["name"] for column in inspect(engine).get_columns("activities")}
    assert "time_zone" in columns_after

    with Session(engine) as session:
        session.add(
            Activity(
                source_type="internal",
                activity_name="Legacy row upgraded by schema top-up",
                time_zone="Europe/Zurich",
            )
        )
        session.commit()
        stored = session.scalar(
            select(Activity).where(Activity.activity_name == "Legacy row upgraded by schema top-up")
        )
        assert stored.time_zone == "Europe/Zurich"
    engine.dispose()


def test_ensure_schema_is_a_no_op_when_schema_is_already_current(tmp_path):
    engine = create_cplan_engine(f"sqlite:///{tmp_path / 'schema-current.sqlite3'}")
    Base.metadata.create_all(engine)

    columns_before = {column["name"] for column in inspect(engine).get_columns("activities")}

    ensure_schema(engine, Base.metadata)

    columns_after = {column["name"] for column in inspect(engine).get_columns("activities")}
    assert columns_after == columns_before
    engine.dispose()


def test_tracking_id_unique_index_blocks_duplicates_among_v6_created_rows(tmp_path):
    """The partial unique index only covers rows without legacy_sp_id (V6-created rows)."""
    engine = create_cplan_engine(f"sqlite:///{tmp_path / 'unique-index.sqlite3'}")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add(
            Activity(source_type="internal", activity_name="First", tracking_id="STA-0000000-260101-0000001-GEN")
        )
        session.commit()

    with Session(engine) as session:
        session.add(
            Activity(source_type="internal", activity_name="Second", tracking_id="STA-0000000-260101-0000001-GEN")
        )
        with pytest.raises(IntegrityError):
            session.commit()
    engine.dispose()


def test_tracking_id_unique_index_allows_duplicates_among_legacy_rows(tmp_path):
    """Legacy imports (carrying legacy_sp_id) are exempt, since duplicate tracking IDs exist in the source data."""
    engine = create_cplan_engine(f"sqlite:///{tmp_path / 'legacy-duplicates.sqlite3'}")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add_all(
            [
                Activity(
                    source_type="internal",
                    activity_name="Legacy first",
                    legacy_sp_id=1,
                    tracking_id="QRREP-0000058-240709-0000060-EMI",
                ),
                Activity(
                    source_type="internal",
                    activity_name="Legacy second",
                    legacy_sp_id=2,
                    tracking_id="QRREP-0000058-240709-0000060-EMI",
                ),
            ]
        )
        session.commit()  # must not raise
    engine.dispose()
