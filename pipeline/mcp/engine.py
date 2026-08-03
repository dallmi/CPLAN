"""A CPLAN engine that cannot write, whichever backend is configured.

The MCP server hands its tools to a language model, so "read-only" must be a
property of the connection rather than a property of the tool code being
careful. Two independent layers:

1. A statement guard on every cursor execution -- works on SQLite and
   PostgreSQL alike, and fails loudly instead of silently mutating.
2. `default_transaction_read_only` on PostgreSQL, so the server refuses writes
   even if a future code path bypasses SQLAlchemy's event system.

SQLite deliberately does NOT use an `mode=ro` URI: the project runs SQLite in
WAL mode, and a read-only connection to a WAL database fails outright when the
`-shm` sidecar is absent. The statement guard covers that case without the
trap.
"""

from __future__ import annotations

import re

from sqlalchemy import event, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import URL

from pipeline.api.app import Base
from pipeline.api.database import create_cplan_engine

# Statement prefixes that cannot change data. Everything else is refused.
_READ_ONLY_PREFIXES = ("select", "with", "pragma", "explain", "show", "set", "reset")

# Two of those prefixes are not read-only by themselves: `WITH x AS (...) DELETE
# FROM activities` and `PRAGMA writable_schema = ON` both begin with an allowed
# word and both mutate. PostgreSQL still refuses them via
# `default_transaction_read_only`, but nothing stops them on SQLite -- so a
# statement with either prefix is refused when it also names a mutating keyword.
# A plain read-only CTE (`WITH ... SELECT`) still passes.
_CONDITIONAL_PREFIXES = ("with", "pragma")
_MUTATING_KEYWORDS = re.compile(
    r"\b(insert|update|delete|drop|alter|truncate|create|grant|revoke|attach|vacuum"
    r"|writable_schema)\b"
)


class ReadOnlyViolation(RuntimeError):
    """Raised when a write statement is attempted on a read-only CPLAN engine."""


class SchemaOutOfDate(RuntimeError):
    """Raised when the live database predates the current ORM models.

    The API tops missing columns up on every startup (`ensure_schema`), but a
    read-only consumer cannot -- and must not -- do that. Without this check the
    server starts fine, answers the few tools that touch only old columns, and
    fails on the rest with a raw `no such column` from deep inside SQLAlchemy.
    """


def missing_model_columns(engine: Engine) -> dict[str, list[str]]:
    """Tables/columns the ORM expects that the live database does not have."""
    inspector = inspect(engine)
    present_tables = set(inspector.get_table_names())
    drift: dict[str, list[str]] = {}
    for table in Base.metadata.sorted_tables:
        if table.name not in present_tables:
            drift[table.name] = ["<table missing>"]
            continue
        present = {column["name"] for column in inspector.get_columns(table.name)}
        missing = [column.name for column in table.columns if column.name not in present]
        if missing:
            drift[table.name] = missing
    return drift


def verify_schema(engine: Engine) -> None:
    drift = missing_model_columns(engine)
    if not drift:
        return
    detail = "; ".join(f"{table}: {', '.join(columns)}" for table, columns in sorted(drift.items()))
    raise SchemaOutOfDate(
        "The CPLAN database is older than the current models and this server is "
        f"read-only, so it cannot migrate it. Missing -- {detail}. "
        "Start the studio once (python pipeline/scripts/start_cplan.py) or run "
        "python -m pipeline.api.ensure_db, then start the MCP server again."
    )


def _is_read_only(statement: str) -> bool:
    stripped = statement.lstrip().lstrip("(").lstrip()
    lowered = stripped.lower()
    if not lowered:
        return True
    if not lowered.startswith(_READ_ONLY_PREFIXES):
        return False
    if lowered.startswith(_CONDITIONAL_PREFIXES) and _MUTATING_KEYWORDS.search(lowered):
        return False
    return True


def create_read_only_engine(database_url: str | URL) -> Engine:
    engine = create_cplan_engine(database_url)

    if engine.dialect.name == "postgresql":

        @event.listens_for(engine, "connect")
        def enforce_postgres_read_only(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("SET default_transaction_read_only = on")
            cursor.close()
            dbapi_connection.commit()

    @event.listens_for(engine, "before_cursor_execute")
    def refuse_writes(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        if not _is_read_only(statement):
            raise ReadOnlyViolation(
                f"The CPLAN MCP server is read-only; refused statement: {statement.strip()[:120]}"
            )

    return engine
