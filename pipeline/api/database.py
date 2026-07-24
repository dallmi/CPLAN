"""Database backend selection and safe engine construction for CPLAN."""

from __future__ import annotations

import os
import subprocess
import time
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
    if _IS_WINDOWS and not (pgdata_path / "PG_VERSION").exists():
        # First-time init: pgserver's initdb + first start are console-attached.
        # Recycle immediately (clean stop, drop the cached instance) so the
        # server that actually serves this session is the detached one below --
        # otherwise the very first session stays kill-on-window-close.
        _get_server_through_recovery(pgserver, pgdata_path)
        _stop_embedded_server(pgdata_path)
        _evict_cached_server_instance(pgserver, pgdata_path)
    _prestart_server_detached(pgdata_path)
    server = _get_server_through_recovery(pgserver, pgdata_path)
    _ensure_embedded_database_exists(server)
    _harden_local_authentication(server)
    return (
        make_url(server.get_uri())
        .set(drivername="postgresql+psycopg", database=EMBEDDED_DATABASE_NAME)
        .render_as_string(hide_password=False)
    )


# Windows CreateProcess flags (subprocess exposes them only on Windows; defined
# here as plain constants so the module imports everywhere). CREATE_NO_WINDOW --
# NOT DETACHED_PROCESS -- is deliberate: pg_ctl starts the postmaster through a
# cmd.exe wrapper, and a console-subsystem child of a *console-less* parent gets
# a brand-new VISIBLE console window allocated by the OS; closing that mystery
# window would deliver CTRL_CLOSE_EVENT to postgres and kill it -- the exact
# failure this code exists to prevent. CREATE_NO_WINDOW gives pg_ctl a hidden
# console that cmd.exe and postgres inherit: no window exists to close, and the
# launching console's Ctrl+C can never reach the server.
_CREATE_NO_WINDOW = 0x08000000
_CREATE_NEW_PROCESS_GROUP = 0x00000200

_IS_WINDOWS = os.name == "nt"


class _ServerNotReady(Exception):
    """The embedded server is up but not accepting connections yet (e.g. WAL recovery)."""


def _probe_server_ready(uri: str) -> None:
    """Open one real connection to prove the server accepts sessions.

    `get_uri()` succeeding only proves postmaster.pid was readable -- during
    crash recovery the file exists (status 'starting') while every connection
    is refused with 'the database system is starting up'. Wrapped in a local
    exception type so the retry loop can catch readiness precisely without
    importing psycopg at module level.
    """
    import psycopg

    try:
        with psycopg.connect(uri, connect_timeout=10):
            pass
    except psycopg.OperationalError as error:
        raise _ServerNotReady(str(error)) from error


def _evict_cached_server_instance(pgserver, pgdata_path) -> None:
    """Drop pgserver's cached PostgresServer for `pgdata_path`, if any.

    pgserver registers the instance in `PostgresServer._instances` BEFORE
    `ensure_postgres_running()` runs; when that raises (10s pg_ctl timeout under
    antivirus, or an attach during WAL recovery), the broken instance stays
    cached and every later `get_server` in this process returns it unchanged --
    without eviction a retry loop can structurally never succeed.
    """
    try:
        instances = pgserver.PostgresServer._instances
    except AttributeError:
        try:
            from pgserver.postgres_server import PostgresServer

            instances = PostgresServer._instances
        except Exception:
            return
    try:
        instances.pop(Path(pgdata_path).expanduser().resolve(), None)
    except Exception:
        pass


def _find_free_port() -> int:
    """A currently free localhost TCP port (same approach as pgserver's own start)."""
    try:
        from pgserver.utils import find_suitable_port

        return int(find_suitable_port("127.0.0.1"))
    except Exception:
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            return probe.getsockname()[1]


def _postmaster_alive(pgdata_path: Path) -> bool:
    """True if postmaster.pid names a live process that looks like postgres.

    Mirrors cplan_db._pid_is_postgres (kept local to avoid an api -> scripts
    import). A stale pid file after a hard crash is handled by pg_ctl itself,
    so returning False for a dead/recycled pid is safe.
    """
    pid_file = pgdata_path / "postmaster.pid"
    if not pid_file.exists():
        return False
    try:
        pid = int(pid_file.read_text().splitlines()[0].strip())
    except (ValueError, IndexError, OSError):
        return False
    try:
        import psutil

        return "postgres" in psutil.Process(pid).name().lower()
    except Exception:
        return False


def _build_prestart_command(pg_ctl_exe, pgdata_path, port: int) -> list[str]:
    """pg_ctl start command with a generous readiness wait (-w -t 300).

    300s covers the worst observed corp-Windows cold start: antivirus-throttled
    fsync (~40s) + a 30s locked-log retry window + WAL crash recovery.

    Host/port are passed explicitly (mirroring pgserver's own Windows start):
    without them postgres would bind postgresql.conf's default 5432, which
    (a) fails outright on any machine where 5432 is taken -- silently losing
    the detached protection every run -- and (b) squats the well-known port.
    Attaching is port-agnostic either way: pgserver reads host/port back from
    postmaster.pid.
    """
    return [
        str(pg_ctl_exe),
        "-D", str(pgdata_path),
        "-l", str(pgdata_path / "log"),
        "-o", '-h "127.0.0.1"',
        "-o", f"-p {port}",
        "-w", "-t", "300",
        "start",
    ]


def _stop_embedded_server(pgdata_path: Path) -> None:
    """Cleanly stop the embedded server (`pg_ctl stop -m fast`), best-effort.

    Used by the first-run recycle: after initdb pgserver has started a
    console-attached postmaster; it is stopped here so the detached pre-start
    below owns the running server. Failure is non-fatal -- the caller falls
    back to attaching to whatever is running.
    """
    try:
        from pgserver._commands import POSTGRES_BIN_PATH
    except ImportError:
        return
    pg_ctl_exe = POSTGRES_BIN_PATH / ("pg_ctl.exe" if _IS_WINDOWS else "pg_ctl")
    if not pg_ctl_exe.exists():
        return
    try:
        subprocess.run(
            [str(pg_ctl_exe), "-D", str(pgdata_path), "stop", "-m", "fast", "-w", "-t", "120"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=150,
        )
    except (subprocess.TimeoutExpired, OSError):
        pass


def _prestart_server_detached(pgdata_path: Path) -> None:
    """Windows only: start the embedded postmaster detached from this console.

    pgserver launches postgres as a child of the calling console window, so
    every Ctrl+C in that window -- and closing it -- delivers a console control
    event straight to the postmaster (exception 0xC000013A), killing it mid-run
    or even mid-recovery. Real session logs show the resulting death spiral:
    slow start -> silent multi-minute wait -> user presses Ctrl+C -> crash ->
    next start needs even longer recovery. Starting the postmaster ourselves
    with DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP severs the console tie:
    the server then survives any window close or Ctrl+C, and pgserver's
    get_server simply attaches to the already-running instance.

    No-op when: not Windows (POSIX pg_ctl daemonizes the postmaster away from
    the terminal already), the cluster does not exist yet (the caller recycles
    a fresh cluster through this function afterwards), or a postmaster is
    already alive (attach path). Failures here are non-fatal --
    _get_server_through_recovery remains the backstop, though a server started
    by that fallback is console-attached again, which the fallback message
    states honestly.

    stdout/stderr go to DEVNULL, never pipes: pg_ctl hands its std handles to
    the cmd.exe wrapper that lives as long as the postmaster, so pipe read
    ends would never see EOF and subprocess.run would hang forever precisely
    when the start SUCCEEDS (pgserver's own _commands.py documents this exact
    hang and uses temp files for the same reason).
    """
    if not _IS_WINDOWS:
        return
    if not (pgdata_path / "PG_VERSION").exists():
        return
    if _postmaster_alive(pgdata_path):
        return
    try:
        from pgserver._commands import POSTGRES_BIN_PATH
    except ImportError:
        return
    pg_ctl_exe = POSTGRES_BIN_PATH / "pg_ctl.exe"
    if not pg_ctl_exe.exists():
        return
    print(
        "Starting the embedded PostgreSQL server. After an unclean shutdown or "
        "under antivirus scanning this can take a few MINUTES - it is working, "
        "do not press Ctrl+C and do not close this window...",
        flush=True,
    )
    try:
        result = subprocess.run(
            _build_prestart_command(pg_ctl_exe, pgdata_path, _find_free_port()),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=330,
            creationflags=_CREATE_NO_WINDOW | _CREATE_NEW_PROCESS_GROUP,
        )
        if result.returncode == 0:
            print("Embedded PostgreSQL is ready.", flush=True)
        else:
            print(
                "Pre-start could not confirm readiness (details in the server log); "
                "falling back to the standard start. NOTE: a server started this way "
                "is tied to this window - closing it stops the database.",
                flush=True,
            )
    except (subprocess.TimeoutExpired, OSError):
        print(
            "Pre-start is taking unusually long; continuing to wait for the server...",
            flush=True,
        )


def _get_server_through_recovery(pgserver, pgdata_path, total_wait: float = 300.0, poll: float = 10.0):
    """`pgserver.get_server`, tolerating a slow crash-recovery start.

    After an unclean shutdown -- common on Windows, where closing the owning
    console delivers Ctrl+C to postgres' backend processes and the postmaster
    crash-restarts (exception 0xC000013A / STATUS_CONTROL_C_EXIT) -- the next
    start must replay WAL before it accepts connections. pgserver's internal
    `pg_ctl start` has a fixed 10s subprocess timeout that this recovery
    routinely exceeds on a corp machine (antivirus + WAL replay), raising
    `subprocess.TimeoutExpired` (or a `pg_ctl` "already running" error while the
    launched postmaster is still recovering in the background). The postmaster
    keeps recovering regardless, so we retry: once it accepts connections,
    get_server attaches to it in well under a second instead of starting a new
    one (measured: cold start ~0.5s, attach ~0.00s). Bounded, so a genuine
    misconfiguration still fails with a clear, actionable error.
    """
    polls = max(1, int(total_wait // poll))
    last_error: Exception | None = None
    for attempt in range(polls + 1):
        try:
            server = pgserver.get_server(str(pgdata_path), cleanup_mode=None)
            # Force pgserver to read postmaster.pid now (mid crash-reinit it can
            # hand back a server whose _postmaster_info is still None -> a later
            # AssertionError deep in get_uri), then prove the server actually
            # accepts sessions -- during WAL recovery postmaster.pid exists while
            # every connection is refused with 'the database system is starting
            # up'. Either failure becomes one more retry instead of a crash.
            uri = server.get_uri()
            _probe_server_ready(uri)
            return server
        except (
            subprocess.TimeoutExpired,
            subprocess.CalledProcessError,
            AssertionError,
            _ServerNotReady,
        ) as error:
            last_error = error
            # Drop the (possibly half-initialized) cached instance, or every
            # further get_server would return the same broken object and the
            # retry could structurally never succeed.
            _evict_cached_server_instance(pgserver, pgdata_path)
            if attempt < polls:
                # Never wait silently: silent multi-minute hangs are what tempt
                # users into Ctrl+C, which used to kill the recovering server.
                print(
                    f"Waiting for the embedded PostgreSQL server to become ready "
                    f"({(attempt + 1) * poll:.0f}s of up to {total_wait:.0f}s; crash "
                    "recovery and antivirus scanning can take a few minutes) - do "
                    "not press Ctrl+C and do not close this window...",
                    flush=True,
                )
                time.sleep(poll)
    raise RuntimeError(
        f"The embedded PostgreSQL server did not become ready in {total_wait:.0f}s. "
        "Crash recovery may still be running after an unclean shutdown (e.g. a "
        "console window closed while it was connected), or the data directory is "
        "unavailable. Wait a minute and retry, or stop it cleanly first with: "
        "python -m pipeline.scripts.cplan_db --stop"
    ) from last_error


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
