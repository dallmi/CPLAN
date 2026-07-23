"""Database backend selection and safe engine construction for CPLAN."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from sqlalchemy import Engine, MetaData, create_engine, event, inspect, text
from sqlalchemy.engine import URL, make_url


SUPPORTED_BACKENDS = {"postgresql", "sqlite"}

# The single database the postgres-embedded backend targets on its embedded server.
EMBEDDED_DATABASE_NAME = "cplan"


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


def embedded_database_url(pgdata: str | os.PathLike[str]) -> str:
    """Start (or attach to) an embedded PostgreSQL 16 server rooted at `pgdata` via
    the `pgserver` package, and return a SQLAlchemy `postgresql+psycopg://` URL for
    its `cplan` database.

    `pgserver.get_server(pgdata, cleanup_mode=None)` is idempotent: it starts the
    server if one is not already running for this `pgdata`, or hands back the
    already-running instance otherwise -- safe to call on every CPLAN startup.
    `cleanup_mode=None` means nothing here ever stops the server; the one
    deliberate, clean shutdown path is `pipeline/scripts/cplan_db.py --stop`.

    `pgserver` is an optional dependency (only needed for the postgres-embedded
    backend, see `pipeline/api/requirements.txt`), so the import is lazy and
    guarded here -- same pattern as `daily_refresh`'s guard around
    `process_cplan`'s `pandas`/`duckdb` import -- turning a bare
    `ModuleNotFoundError` into an actionable message instead of a raw traceback.

    `server.get_uri()` returns a socket-style URI on macOS/Linux
    (`postgresql://postgres:@/postgres?host=/path/to/sockdir`) or a TCP-style URI
    with a dynamic port on Windows (`postgresql://postgres:@127.0.0.1:PORT/postgres`).
    Both are valid SQLAlchemy URLs already, so `make_url(...).set(...)` handles the
    conversion (driver + target database) without needing to special-case either
    form.
    """
    try:
        import pgserver
    except ImportError as exc:
        raise RuntimeError(
            "The postgres-embedded backend requires the 'pgserver' package, which is not "
            "installed in this environment. Install it with: pip install pgserver"
        ) from exc

    pgdata_path = Path(pgdata).expanduser()
    pgdata_path.parent.mkdir(parents=True, exist_ok=True)
    server = pgserver.get_server(str(pgdata_path), cleanup_mode=None)
    _ensure_embedded_database_exists(server)
    _harden_local_authentication(server)
    return (
        make_url(server.get_uri())
        .set(drivername="postgresql+psycopg", database=EMBEDDED_DATABASE_NAME)
        .render_as_string(hide_password=False)
    )


def _harden_local_authentication(server) -> None:
    """Require a real password for every login role except `postgres`.

    `pgserver` always runs `initdb --auth=trust --auth-local=trust`, so a
    freshly created `pgdata` trusts *any* local connection as *any* role --
    harmless for the app's own `postgres` superuser connections (which never
    carry a password: engine bootstrap, `setup_roles`), but it silently
    defeats `verify_credentials` (`pipeline/api/auth.py`), whose docstring
    states passwords are authoritatively checked by "PostgreSQL itself
    (SCRAM)": under the default trust rules, a *wrong* password for an
    existing role would still authenticate. Rewrite `pg_hba.conf` so
    `postgres` keeps `trust` (needed for internal engine/role-management
    connections that never supply a password) while every other role must
    present the scram-sha-256 password it was created with, then reload the
    config so the change applies without a restart. Idempotent: a pgdata
    already hardened by an earlier call is left untouched.
    """
    hba_path = Path(server.pgdata) / "pg_hba.conf"
    original = hba_path.read_text()
    marker = "local   all             postgres                                trust"
    if marker in original:
        return

    # The lines below are the exact trust-for-all-roles rules `str.replace()`
    # targets. If a future pgserver release ships a pg_hba.conf template that
    # formats or orders these differently, every replace below silently no-ops
    # and `hardened == original` -- the file would be written back unchanged,
    # reopening the trust-auth bypass with no error. Assert the precondition
    # up front and the postcondition before writing, so drift fails loudly
    # instead of silently.
    trust_for_all_lines = (
        "local   all             all                                     trust",
        "host    all             all             127.0.0.1/32            trust",
        "host    all             all             ::1/128                 trust",
    )
    if not all(line in original for line in trust_for_all_lines):
        raise RuntimeError(
            "pgserver pg_hba.conf template changed; scram hardening did not apply "
            "-- refusing to start with trust auth"
        )

    hardened = (
        original.replace(
            "local   all             all                                     trust",
            "local   all             postgres                                trust\n"
            "local   all             all                                     scram-sha-256",
        )
        .replace(
            "host    all             all             127.0.0.1/32            trust",
            "host    all             postgres        127.0.0.1/32            trust\n"
            "host    all             all             127.0.0.1/32            scram-sha-256",
        )
        .replace(
            "host    all             all             ::1/128                 trust",
            "host    all             postgres        ::1/128                 trust\n"
            "host    all             all             ::1/128                 scram-sha-256",
        )
    )

    scram_for_all_lines = (
        "local   all             all                                     scram-sha-256",
        "host    all             all             127.0.0.1/32            scram-sha-256",
        "host    all             all             ::1/128                 scram-sha-256",
    )
    if any(line in hardened for line in trust_for_all_lines) or not all(
        line in hardened for line in scram_for_all_lines
    ):
        raise RuntimeError(
            "pgserver pg_hba.conf template changed; scram hardening did not apply "
            "-- refusing to start with trust auth"
        )

    hba_path.write_text(hardened)
    # File edits alone are not enough -- the running postmaster keeps the old
    # rules in memory until reloaded. This connection still succeeds under
    # the *old* (not-yet-reloaded) trust rule; the reload it triggers only
    # affects connections made after it returns.
    maintenance_url = make_url(server.get_uri()).set(drivername="postgresql+psycopg")
    engine = create_engine(maintenance_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT pg_reload_conf()"))
    finally:
        engine.dispose()


def _ensure_embedded_database_exists(server) -> None:
    """Create the `cplan` database on the embedded server if it does not exist yet.

    Connects to the always-present `postgres` maintenance database rather than
    parsing `server.psql()`'s tabular text output -- a real parameterized query
    against `pg_database` is unambiguous regardless of server locale. `CREATE
    DATABASE` cannot run inside a transaction, hence the AUTOCOMMIT isolation level.
    """
    maintenance_url = make_url(server.get_uri()).set(drivername="postgresql+psycopg")
    engine = create_engine(maintenance_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            exists = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": EMBEDDED_DATABASE_NAME},
            ).first()
            if exists is None:
                identifier = engine.dialect.identifier_preparer.quote(EMBEDDED_DATABASE_NAME)
                connection.execute(text(f"CREATE DATABASE {identifier}"))
    finally:
        engine.dispose()


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
