"""Database backend selection and safe engine construction for CPLAN V6."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine, create_engine, event
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
