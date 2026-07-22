"""Database backend selection and safe engine construction for CPLAN V6."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine, MetaData, create_engine, event, inspect, text
from sqlalchemy.engine import URL, make_url


SUPPORTED_BACKENDS = {"postgresql", "sqlite"}


@dataclass(frozen=True)
class DatabaseSettings:
    url: str | URL
    backend: str

    @classmethod
    def from_url(cls, url: str | URL) -> "DatabaseSettings":
        return cls(url=url, backend=backend_from_url(url))


def backend_from_url(database_url: str | URL) -> str:
    backend = make_url(database_url).get_backend_name()
    if backend not in SUPPORTED_BACKENDS:
        raise ValueError(f"Unsupported database backend: {backend}")
    return backend


def create_cplan_engine(database_url: str | URL) -> Engine:
    settings = DatabaseSettings.from_url(database_url)
    if settings.backend == "sqlite":
        engine = create_engine(
            settings.url,
            connect_args={"check_same_thread": False, "timeout": 5},
        )

        @event.listens_for(engine, "connect")
        def configure_sqlite(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

        return engine

    return create_engine(settings.url, pool_pre_ping=True)


def ensure_schema(engine: Engine, metadata: MetaData) -> None:
    """Top up existing tables with any model columns the live database is missing.

    Intended to run right after `metadata.create_all(engine)` in the app
    lifespan: `create_all` only creates tables that don't exist yet, so a
    database created under an older model version (e.g. before `time_zone`
    was added to `Activity`) would otherwise never pick up new columns. Every
    added column is issued as a plain nullable `ALTER TABLE ... ADD COLUMN`
    (no default, no NOT NULL) since existing rows have no value to backfill.
    Works on both SQLite and PostgreSQL — the column type is compiled for
    whichever dialect `engine` uses.
    """
    inspector = inspect(engine)
    for table in metadata.sorted_tables:
        if not inspector.has_table(table.name):
            continue
        existing_columns = {column["name"] for column in inspector.get_columns(table.name)}
        missing_columns = [column for column in table.columns if column.name not in existing_columns]
        if not missing_columns:
            continue
        preparer = engine.dialect.identifier_preparer
        quoted_table = preparer.quote(table.name)
        with engine.begin() as connection:
            for column in missing_columns:
                compiled_type = column.type.compile(dialect=engine.dialect)
                quoted_column = preparer.quote(column.name)
                connection.execute(text(f"ALTER TABLE {quoted_table} ADD COLUMN {quoted_column} {compiled_type}"))
