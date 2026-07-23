import importlib.util
import json
import os

import pytest

from pipeline.api.setup_backend import SETTINGS_SCHEMA_VERSION
from pipeline.scripts.cplan_db import _resolve_target_pgdata, is_running, print_status, stop

# cplan_db.py's status/stop paths import psutil (a pgserver dependency, also declared
# directly in pipeline/api/requirements.txt since it's a hard runtime dependency of this
# module). Skip the whole file rather than annotating individual tests -- simpler, and
# every test here exists to cover this one psutil-dependent script.
pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("psutil") is None,
    reason="psutil is not installed; pipeline/scripts/cplan_db.py requires it",
)


def _write_postmaster_pid(pgdata, *, pid, port="5432", socket_dir="", hostname="localhost", status="ready") -> None:
    pgdata.mkdir(parents=True, exist_ok=True)
    lines = [str(pid), str(pgdata), "1690000000", port, socket_dir, hostname, "12345 67890", status]
    (pgdata / "postmaster.pid").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_is_running_false_when_no_postmaster_pid(tmp_path):
    running, info = is_running(tmp_path / "pgdata")
    assert running is False
    assert info is None


def test_is_running_true_for_a_live_process_marked_ready(tmp_path):
    pgdata = tmp_path / "pgdata"
    _write_postmaster_pid(pgdata, pid=os.getpid(), socket_dir=str(tmp_path))

    running, info = is_running(pgdata)

    assert running is True
    assert info["pid"] == str(os.getpid())


def test_is_running_false_when_status_is_not_ready(tmp_path):
    """A postmaster.pid can exist mid-startup/-recovery, before the server accepts connections."""
    pgdata = tmp_path / "pgdata"
    _write_postmaster_pid(pgdata, pid=os.getpid(), status="starting")

    running, _info = is_running(pgdata)

    assert running is False


def test_is_running_false_when_pid_is_stale(tmp_path):
    """A PID recorded in postmaster.pid whose process no longer exists (unclean shutdown, crash, PID reuse)."""
    pgdata = tmp_path / "pgdata"
    # PID 2**31-1 is never a real process on any platform this runs on.
    _write_postmaster_pid(pgdata, pid=2**31 - 1)

    running, _info = is_running(pgdata)

    assert running is False


def test_print_status_reports_not_running(tmp_path, capsys):
    exit_code = print_status(tmp_path / "pgdata")

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "NOT running" in captured.out


def test_print_status_reports_socket_connection(tmp_path, capsys):
    pgdata = tmp_path / "pgdata"
    _write_postmaster_pid(pgdata, pid=os.getpid(), socket_dir=str(tmp_path / "sock"))

    exit_code = print_status(pgdata)

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "running" in captured.out
    assert str(tmp_path / "sock") in captured.out


def test_print_status_reports_host_and_port_when_no_socket(tmp_path, capsys):
    pgdata = tmp_path / "pgdata"
    _write_postmaster_pid(pgdata, pid=os.getpid(), socket_dir="", hostname="127.0.0.1", port="54321")

    exit_code = print_status(pgdata)

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "127.0.0.1" in captured.out
    assert "54321" in captured.out


def test_print_status_reports_pg_version_from_pg_version_file(tmp_path, capsys):
    pgdata = tmp_path / "pgdata"
    pgdata.mkdir(parents=True)
    (pgdata / "PG_VERSION").write_text("16\n", encoding="utf-8")

    print_status(pgdata)

    captured = capsys.readouterr()
    assert "16" in captured.out


def test_stop_is_a_noop_when_not_running(tmp_path, capsys):
    exit_code = stop(tmp_path / "pgdata")

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "not running" in captured.out.lower()


def test_stop_refuses_when_postmaster_pid_names_a_process_that_is_not_postgres(tmp_path, capsys):
    """A live PID that is not actually postgres (stale postmaster.pid from an unclean
    shutdown, or PID reuse -- a real risk on Windows) must never be sent a stop signal:
    `pg_ctl stop` trusts the file blindly and would terminate whatever process holds
    that PID."""
    pgdata = tmp_path / "pgdata"
    _write_postmaster_pid(pgdata, pid=os.getpid())  # this test process, not postgres

    exit_code = stop(pgdata)

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "not a postgres process" in captured.out


def test_resolve_target_pgdata_uses_explicit_flag_bypassing_settings(tmp_path):
    from argparse import Namespace

    explicit = tmp_path / "explicit-pgdata"
    args = Namespace(pgdata=explicit, settings=tmp_path / "does-not-exist.json")

    result = _resolve_target_pgdata(args)

    assert result == explicit.resolve()


def test_resolve_target_pgdata_gives_an_actionable_error_when_unconfigured(tmp_path):
    """No raw FileNotFoundError traceback -- a clear message with the fix, same style as
    the missing-psutil path in main()."""
    from argparse import Namespace

    args = Namespace(pgdata=None, settings=tmp_path / "missing-settings.json")

    with pytest.raises(SystemExit, match="setup_backend --backend postgres-embedded"):
        _resolve_target_pgdata(args)


def test_resolve_target_pgdata_errors_when_backend_is_not_postgres_embedded(tmp_path):
    from argparse import Namespace

    settings_path = tmp_path / "cplan-settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "schema_version": SETTINGS_SCHEMA_VERSION,
                "backend": "sqlite",
                "database_url": f"sqlite:///{tmp_path / 'cplan.sqlite3'}",
            }
        ),
        encoding="utf-8",
    )
    args = Namespace(pgdata=None, settings=settings_path)

    with pytest.raises(SystemExit, match="not postgres-embedded"):
        _resolve_target_pgdata(args)
