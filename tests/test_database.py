import sys
from types import SimpleNamespace

import pytest
from sqlalchemy import Column, MetaData, Table, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import pipeline.api.database as database
from pipeline.api.app import Activity, Base
from pipeline.api.database import backend_from_url, create_cplan_engine, embedded_database_url, ensure_schema


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


def _create_legacy_activities_table_without_indexes(engine) -> None:
    """Recreate the `activities` table with every model column but none of its
    indexes — mirrors a database created before the partial unique index
    `ix_activities_tracking_id_v6_unique` existed. `Base.metadata.create_all`
    only creates indexes as part of creating a table, so a table like this
    one, already present, would otherwise never gain the index.
    """
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
    ]
    Table(activities.name, legacy_metadata, *legacy_columns)
    legacy_metadata.create_all(engine)


def test_ensure_schema_adds_missing_unique_index_to_an_existing_table(tmp_path):
    engine = create_cplan_engine(f"sqlite:///{tmp_path / 'index-topup.sqlite3'}")
    _create_legacy_activities_table_without_indexes(engine)

    indexes_before = {index["name"] for index in inspect(engine).get_indexes("activities")}
    assert "ix_activities_tracking_id_v6_unique" not in indexes_before

    ensure_schema(engine, Base.metadata)

    indexes_after = {index["name"] for index in inspect(engine).get_indexes("activities")}
    assert "ix_activities_tracking_id_v6_unique" in indexes_after

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


def test_ensure_schema_index_topup_is_idempotent(tmp_path):
    engine = create_cplan_engine(f"sqlite:///{tmp_path / 'index-topup-idempotent.sqlite3'}")
    _create_legacy_activities_table_without_indexes(engine)

    ensure_schema(engine, Base.metadata)
    ensure_schema(engine, Base.metadata)  # second run must no-op, not error on "index already exists"

    indexes_after = {index["name"] for index in inspect(engine).get_indexes("activities")}
    assert "ix_activities_tracking_id_v6_unique" in indexes_after
    engine.dispose()


def test_tracking_id_unique_index_blocks_duplicates_among_studio_created_rows(tmp_path):
    """The partial unique index only covers rows without legacy_sp_id (studio-created rows)."""
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


def _stub_pgserver(monkeypatch, raw_uri: str) -> None:
    """Install a fake `pgserver` module so `embedded_database_url` never touches a real server.

    `embedded_database_url` also creates the `cplan` database via a real SQLAlchemy
    connection to the server's maintenance database -- pointless (and unreachable)
    against a fake server, so that step is stubbed out too; these tests are only
    about the URI-conversion logic (socket vs. TCP forms).
    """
    fake_server = SimpleNamespace(get_uri=lambda database=None: raw_uri)
    fake_pgserver = SimpleNamespace(get_server=lambda pgdata, cleanup_mode=None: fake_server)
    monkeypatch.setitem(sys.modules, "pgserver", fake_pgserver)
    monkeypatch.setattr(database, "_ensure_embedded_database_exists", lambda server: None)
    # Same rationale as _ensure_embedded_database_exists above: pointless (and
    # unreachable -- no pg_hba.conf on disk) against a fake server.
    monkeypatch.setattr(database, "_harden_local_authentication", lambda server: None)
    # The readiness probe opens a real psycopg connection -- meaningless against
    # a fake URI, so it is stubbed for URI-conversion tests.
    monkeypatch.setattr(database, "_probe_server_ready", lambda uri: None)


def test_embedded_database_url_converts_socket_style_uri(monkeypatch, tmp_path):
    _stub_pgserver(monkeypatch, "postgresql://postgres:@/postgres?host=/tmp/some/sockdir")

    url = embedded_database_url(tmp_path / "pgdata")

    assert url == "postgresql+psycopg://postgres:@/cplan?host=%2Ftmp%2Fsome%2Fsockdir"


def test_embedded_database_url_converts_tcp_style_uri(monkeypatch, tmp_path):
    _stub_pgserver(monkeypatch, "postgresql://postgres:@127.0.0.1:54321/postgres")

    url = embedded_database_url(tmp_path / "pgdata")

    assert url == "postgresql+psycopg://postgres:@127.0.0.1:54321/cplan"


def test_embedded_database_url_creates_missing_pgdata_parent(monkeypatch, tmp_path):
    _stub_pgserver(monkeypatch, "postgresql://postgres:@127.0.0.1:1/postgres")
    pgdata = tmp_path / "nested" / "does" / "not" / "exist" / "pgdata"

    embedded_database_url(pgdata)

    assert pgdata.parent.is_dir()


def test_embedded_database_url_raises_actionable_error_when_pgserver_missing(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "pgserver", None)

    with pytest.raises(RuntimeError, match="pip install pgserver"):
        embedded_database_url(tmp_path / "pgdata")


def test_harden_local_authentication_raises_when_pg_hba_template_drifted(tmp_path):
    """A future pgserver release could ship a pg_hba.conf default formatted or
    ordered differently than the exact lines `_harden_local_authentication`
    targets with `str.replace()`. Without a guard, every replace would
    silently no-op and the file would be written back unchanged -- trust auth
    left in place with no error. `_harden_local_authentication` must instead
    fail loudly, before writing anything.
    """
    pgdata = tmp_path / "pgdata"
    pgdata.mkdir()
    (pgdata / "pg_hba.conf").write_text(
        "# drifted template: different column spacing than pgserver's real default\n"
        "local all all trust\n"
        "host all all 127.0.0.1/32 trust\n"
        "host all all ::1/128 trust\n"
    )
    fake_server = SimpleNamespace(
        pgdata=str(pgdata),
        get_uri=lambda database=None: "postgresql://postgres:@/postgres?host=/tmp/does-not-exist",
    )

    with pytest.raises(RuntimeError, match="pg_hba.conf template changed"):
        database._harden_local_authentication(fake_server)

    # Must refuse before writing -- the drifted file is left untouched, not
    # silently rewritten as a no-op.
    assert (pgdata / "pg_hba.conf").read_text() == (
        "# drifted template: different column spacing than pgserver's real default\n"
        "local all all trust\n"
        "host all all 127.0.0.1/32 trust\n"
        "host all all ::1/128 trust\n"
    )


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


def _no_probe(monkeypatch):
    monkeypatch.setattr(database, "_probe_server_ready", lambda uri: None)


def test_get_server_through_recovery_retries_slow_crash_recovery(monkeypatch):
    """A slow crash-recovery start (pg_ctl 10s subprocess timeout) is retried, not fatal."""
    import subprocess

    _no_probe(monkeypatch)
    calls = {"n": 0}

    class RecoveringPgserver:
        def get_server(self, pgdata, cleanup_mode=None):
            calls["n"] += 1
            if calls["n"] <= 2:
                raise subprocess.TimeoutExpired(cmd="pg_ctl", timeout=10)
            return SimpleNamespace(get_uri=lambda: "postgresql://postgres:@/postgres?host=/x")

    server = database._get_server_through_recovery(
        RecoveringPgserver(), "/tmp/pgdata", total_wait=1.0, poll=0.01
    )
    assert server.get_uri().startswith("postgresql://")
    assert calls["n"] == 3


def test_get_server_through_recovery_retries_not_ready_connections(monkeypatch):
    """postmaster.pid readable but connections refused (WAL recovery) is retried too."""
    probes = {"n": 0}

    def flaky_probe(uri):
        probes["n"] += 1
        if probes["n"] <= 2:
            raise database._ServerNotReady("the database system is starting up")

    monkeypatch.setattr(database, "_probe_server_ready", flaky_probe)

    class AlwaysAttaches:
        def get_server(self, pgdata, cleanup_mode=None):
            return SimpleNamespace(get_uri=lambda: "postgresql://postgres:@127.0.0.1:5/x")

    server = database._get_server_through_recovery(
        AlwaysAttaches(), "/tmp/pgdata", total_wait=1.0, poll=0.01
    )
    assert probes["n"] == 3
    assert server.get_uri().startswith("postgresql://")


def test_get_server_through_recovery_evicts_poisoned_cache_between_attempts(monkeypatch):
    """pgserver caches the instance BEFORE its start succeeds; without eviction a
    retry would receive the same broken object forever."""
    import subprocess

    _no_probe(monkeypatch)
    evictions = []
    monkeypatch.setattr(
        database, "_evict_cached_server_instance", lambda pg, path: evictions.append(str(path))
    )

    calls = {"n": 0}

    class FailsOnce:
        def get_server(self, pgdata, cleanup_mode=None):
            calls["n"] += 1
            if calls["n"] == 1:
                raise subprocess.TimeoutExpired(cmd="pg_ctl", timeout=10)
            return SimpleNamespace(get_uri=lambda: "postgresql://postgres:@/x")

    database._get_server_through_recovery(FailsOnce(), "/tmp/pgdata", total_wait=1.0, poll=0.01)
    assert evictions == ["/tmp/pgdata"]


def test_get_server_through_recovery_gives_up_with_actionable_error(monkeypatch):
    import subprocess

    _no_probe(monkeypatch)

    class NeverReady:
        def get_server(self, pgdata, cleanup_mode=None):
            raise subprocess.TimeoutExpired(cmd="pg_ctl", timeout=10)

    with pytest.raises(RuntimeError, match="did not become ready"):
        database._get_server_through_recovery(NeverReady(), "/tmp/pgdata", total_wait=0.05, poll=0.01)


def test_evict_cached_server_instance_pops_pgserver_registry(tmp_path):
    resolved = tmp_path.expanduser().resolve()
    fake_pgserver = SimpleNamespace(PostgresServer=SimpleNamespace(_instances={resolved: object()}))
    database._evict_cached_server_instance(fake_pgserver, tmp_path)
    assert resolved not in fake_pgserver.PostgresServer._instances
    # And it must tolerate a pgserver without the expected attribute.
    database._evict_cached_server_instance(SimpleNamespace(), tmp_path)


def test_build_prestart_command_waits_generously_and_binds_dynamic_port():
    cmd = database._build_prestart_command("/bins/pg_ctl.exe", database.Path("/data/pg"), 54999)
    assert cmd[0] == "/bins/pg_ctl.exe"
    assert cmd[-1] == "start"
    assert "-w" in cmd
    assert cmd[cmd.index("-t") + 1] == "300"
    assert cmd[cmd.index("-D") + 1].endswith("pg")
    # Explicit host/port, mirroring pgserver's own Windows start: without them
    # the server would bind postgresql.conf's default 5432 and fail wherever
    # that port is taken -- silently losing the detached protection.
    assert '-h "127.0.0.1"' in cmd
    assert "-p 54999" in cmd


def test_prestart_is_noop_on_posix(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(database.subprocess, "run", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(database, "_IS_WINDOWS", False)
    database._prestart_server_detached(tmp_path)
    assert calls == []


def test_prestart_skips_uninitialized_cluster_and_running_server(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(database.subprocess, "run", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(database, "_IS_WINDOWS", True)
    # No PG_VERSION -> first-time init is handled by the caller's recycle path.
    database._prestart_server_detached(tmp_path)
    assert calls == []
    # Cluster exists but a postmaster is already alive -> attach path, no start.
    (tmp_path / "PG_VERSION").write_text("16")
    monkeypatch.setattr(database, "_postmaster_alive", lambda p: True)
    database._prestart_server_detached(tmp_path)
    assert calls == []


def test_prestart_starts_hidden_console_devnull_no_pipes(tmp_path, monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(database.subprocess, "run", fake_run)
    monkeypatch.setattr(database, "_IS_WINDOWS", True)
    (tmp_path / "PG_VERSION").write_text("16")
    monkeypatch.setattr(database, "_postmaster_alive", lambda p: False)
    monkeypatch.setattr(database, "_find_free_port", lambda: 55123)

    fake_bin = tmp_path / "bins"
    fake_bin.mkdir()
    (fake_bin / "pg_ctl.exe").write_text("")
    fake_commands = SimpleNamespace(POSTGRES_BIN_PATH=fake_bin)
    monkeypatch.setitem(sys.modules, "pgserver._commands", fake_commands)
    monkeypatch.setitem(sys.modules, "pgserver", SimpleNamespace(_commands=fake_commands))

    database._prestart_server_detached(tmp_path)

    assert captured["cmd"][-1] == "start"
    assert "-p 55123" in captured["cmd"]
    kwargs = captured["kwargs"]
    # Hidden console (NOT a detached ghost window whose closure would kill the
    # server), isolated from the launching console's Ctrl+C.
    assert kwargs["creationflags"] == database._CREATE_NO_WINDOW | database._CREATE_NEW_PROCESS_GROUP
    # DEVNULL, never pipes: pg_ctl hands its std handles to the postmaster's
    # cmd.exe wrapper, so pipes would never see EOF and hang the SUCCESS path
    # (pgserver's own _commands.py documents this exact hang).
    import subprocess as sp

    assert kwargs["stdout"] == sp.DEVNULL and kwargs["stderr"] == sp.DEVNULL
    assert "capture_output" not in kwargs


def test_embedded_database_url_recycles_first_run_to_detached(tmp_path, monkeypatch):
    """A fresh cluster's console-attached first start is stopped and replaced."""
    order = []
    fake_server = SimpleNamespace(get_uri=lambda database=None: "postgresql://postgres:@127.0.0.1:5/postgres")
    fake_pgserver = SimpleNamespace(get_server=lambda pgdata, cleanup_mode=None: fake_server)
    monkeypatch.setitem(sys.modules, "pgserver", fake_pgserver)
    monkeypatch.setattr(database, "_IS_WINDOWS", True)
    monkeypatch.setattr(database, "_probe_server_ready", lambda uri: order.append("probe"))
    monkeypatch.setattr(database, "_stop_embedded_server", lambda p: order.append("stop"))
    monkeypatch.setattr(database, "_evict_cached_server_instance", lambda pg, p: order.append("evict"))
    monkeypatch.setattr(database, "_prestart_server_detached", lambda p: order.append("prestart"))
    monkeypatch.setattr(database, "_ensure_embedded_database_exists", lambda server: None)
    monkeypatch.setattr(database, "_harden_local_authentication", lambda server: None)

    pgdata = tmp_path / "pgdata"  # no PG_VERSION -> first run
    url = database.embedded_database_url(pgdata)

    assert url.startswith("postgresql+psycopg://")
    assert order == ["probe", "stop", "evict", "prestart", "probe"]


def test_postmaster_alive_false_without_pidfile_or_garbage(tmp_path):
    assert database._postmaster_alive(tmp_path) is False
    (tmp_path / "postmaster.pid").write_text("not-a-pid\n")
    assert database._postmaster_alive(tmp_path) is False
