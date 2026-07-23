"""Database backend selection and safe engine construction for CPLAN."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

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


def database_url_from_environment(environ: Mapping[str, str] | None = None) -> str | URL | None:
    """Compose a PostgreSQL URL from `CPLAN_DB_*` parts, mirroring the Docker Compose `api` service.

    `compose.yaml` only sets `CPLAN_DB_HOST`/`_PORT`/`_NAME`/`_USER`/`_PASSWORD`
    on the container — there is no `CPLAN_DATABASE_URL` inside it — so any code
    path that only checks `CPLAN_DATABASE_URL` (e.g. a `docker compose exec`
    command) fails with no configured database. This is the single place that
    composition happens; both `create_environment_app` and
    `import_snapshot.resolve_database_url` call it instead of duplicating the
    logic.

    Returns the explicit `CPLAN_DATABASE_URL` when set, the composed URL when
    `CPLAN_DB_PASSWORD` is present, or `None` when neither is configured.
    """
    environment = os.environ if environ is None else environ
    if environment.get("CPLAN_DATABASE_URL"):
        return environment["CPLAN_DATABASE_URL"]
    if not environment.get("CPLAN_DB_PASSWORD"):
        return None
    return URL.create(
        "postgresql+psycopg",
        username=environment.get("CPLAN_DB_USER", "cplan"),
        password=environment["CPLAN_DB_PASSWORD"],
        host=environment.get("CPLAN_DB_HOST", "127.0.0.1"),
        port=int(environment.get("CPLAN_DB_PORT", "5432")),
        database=environment.get("CPLAN_DB_NAME", "cplan"),
    )


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
    """Top up existing tables with any model columns or indexes the live database is missing.

    Intended to run right after `metadata.create_all(engine)` in the app
    lifespan: `create_all` only creates tables that don't exist yet (and only
    creates indexes as part of creating a table), so a database created under
    an older model version — e.g. before `time_zone` was added to `Activity`,
    or before the `ix_activities_tracking_id_v6_unique` partial unique index
    existed — would otherwise never pick up the new column or index.

    Every added column is issued as a plain nullable `ALTER TABLE ... ADD
    COLUMN` (no default, no NOT NULL) since existing rows have no value to
    backfill. Every missing index is created via `Index.create()`, which
    emits the correct dialect-specific DDL (including a partial index's
    `WHERE` clause) for whichever dialect `engine` uses. Works on both
    SQLite and PostgreSQL.
    """
    inspector = inspect(engine)
    for table in metadata.sorted_tables:
        if not inspector.has_table(table.name):
            continue

        existing_columns = {column["name"] for column in inspector.get_columns(table.name)}
        missing_columns = [column for column in table.columns if column.name not in existing_columns]
        if missing_columns:
            preparer = engine.dialect.identifier_preparer
            quoted_table = preparer.quote(table.name)
            with engine.begin() as connection:
                for column in missing_columns:
                    compiled_type = column.type.compile(dialect=engine.dialect)
                    quoted_column = preparer.quote(column.name)
                    connection.execute(
                        text(f"ALTER TABLE {quoted_table} ADD COLUMN {quoted_column} {compiled_type}")
                    )

        existing_indexes = {index["name"] for index in inspector.get_indexes(table.name)}
        missing_indexes = [index for index in table.indexes if index.name not in existing_indexes]
        for index in missing_indexes:
            index.create(bind=engine)
