"""Lifecycle control for CPLAN's embedded PostgreSQL server (see `pipeline/api/database.py`).

`start_cplan.py` and `daily_refresh.py` never stop the embedded server -- it is
left running between sessions so the next command starts instantly instead of
paying PostgreSQL's startup cost again. Use this script to check on it or shut
it down cleanly when you are done for the day.

Usage:
    python -m pipeline.scripts.cplan_db --status
    python -m pipeline.scripts.cplan_db --stop
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from pipeline.api.database import EMBEDDED_DATABASE_NAME
from pipeline.api.setup_backend import default_settings_path, load_backend_config, resolve_pgdata

POSTMASTER_FIELDS = ("pid", "pgdata", "start_time", "port", "socket_dir", "hostname", "shmem_info", "status")


def _read_postmaster_info(pgdata: Path) -> dict[str, str] | None:
    """Parse `pgdata/postmaster.pid`, the same file PostgreSQL itself writes.

    One value per line, in `POSTMASTER_FIELDS` order. Returns `None` if the file
    does not exist -- the server has never started, or was stopped cleanly (a
    clean `pg_ctl stop` removes this file).
    """
    pid_file = pgdata / "postmaster.pid"
    if not pid_file.exists():
        return None
    lines = pid_file.read_text(encoding="utf-8").splitlines()
    return {name: (lines[index].strip() if index < len(lines) else "") for index, name in enumerate(POSTMASTER_FIELDS)}


def _pg_version(pgdata: Path) -> str | None:
    version_file = pgdata / "PG_VERSION"
    return version_file.read_text(encoding="utf-8").strip() if version_file.exists() else None


def is_running(pgdata: Path) -> tuple[bool, dict[str, str] | None]:
    """True if `postmaster.pid` records a live PID and PostgreSQL last reported itself ready.

    This is a liveness check only -- it does not confirm the PID is actually a
    postgres process (see `_pid_is_postgres`, which `stop()` uses for that
    before ever sending it a signal). Good enough for `--status`, which is
    read-only and merely informational.
    """
    info = _read_postmaster_info(pgdata)
    if not info or not info.get("pid"):
        return False, info
    if info.get("status") != "ready":
        return False, info
    import psutil

    try:
        return psutil.pid_exists(int(info["pid"])), info
    except ValueError:
        return False, info


def print_status(pgdata: Path, database: str = EMBEDDED_DATABASE_NAME) -> int:
    running, info = is_running(pgdata)
    version = _pg_version(pgdata)
    print(f"pgdata:   {pgdata}")
    print(f"database: {database}")
    print(f"version:  PostgreSQL {version or 'unknown (not initialized yet)'}")
    if not running:
        print("status:   NOT running")
        return 0
    socket_dir = (info or {}).get("socket_dir")
    if socket_dir:
        print(f"status:   running (pid {info['pid']}, socket {socket_dir})")
    else:
        host = (info or {}).get("hostname") or "127.0.0.1"
        port = (info or {}).get("port") or "?"
        print(f"status:   running (pid {info['pid']}, host {host}, port {port})")
    return 0


def _pid_is_postgres(pid: int) -> bool:
    """True only if `pid` is alive AND actually looks like a postgres process.

    Guards `stop()` against a stale `postmaster.pid` naming an unrelated,
    recycled PID -- a real risk after an unclean shutdown, especially on
    Windows, which reuses PIDs far more aggressively than POSIX. `pg_ctl stop`
    trusts the file and would otherwise send a termination signal to whatever
    process now happens to hold that PID.
    """
    import psutil

    try:
        return "postgres" in psutil.Process(pid).name().lower()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def stop(pgdata: Path) -> int:
    """Stop the embedded server CLEANLY via `pg_ctl -D pgdata stop -m fast`.

    Never hard-kills: an unclean stop (`SIGKILL`/`TerminateProcess`, or deleting
    `pgdata` out from under a running postmaster) skips the checkpoint, leaves
    `postmaster.pid` behind, and forces a slow WAL-replaying crash-recovery on
    the next start -- exactly the failure mode a previous project hit hard on a
    network share. A clean stop always checkpoints first and removes
    `postmaster.pid`, so the next start is instant.
    """
    running, info = is_running(pgdata)
    if not running:
        print(f"Embedded PostgreSQL is not running (pgdata: {pgdata}).")
        return 0

    pid = int(info["pid"])
    if not _pid_is_postgres(pid):
        print(
            f"Refusing to stop: postmaster.pid names pid {pid}, which is not a postgres "
            "process. This looks like a stale postmaster.pid left by an unclean shutdown or "
            f"PID reuse -- inspect {pgdata / 'postmaster.pid'} manually before removing it."
        )
        return 1

    from pgserver._commands import POSTGRES_BIN_PATH

    pg_ctl_exe = POSTGRES_BIN_PATH / ("pg_ctl.exe" if os.name == "nt" else "pg_ctl")
    result = subprocess.run(
        [str(pg_ctl_exe), "-D", str(pgdata), "stop", "-m", "fast", "-w", "-t", "120"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"pg_ctl stop failed (exit {result.returncode}): {result.stderr.strip() or result.stdout.strip()}")
        return 1
    print(f"Stopped embedded PostgreSQL cleanly (pgdata: {pgdata}).")
    return 0


def _resolve_target_pgdata(args: argparse.Namespace) -> Path:
    if args.pgdata is not None:
        return resolve_pgdata(explicit=args.pgdata)
    config = load_backend_config(args.settings)
    if config.backend != "postgres-embedded":
        raise SystemExit(
            f"Configured backend is {config.backend!r}, not postgres-embedded; nothing to control here. "
            "Pass --pgdata explicitly to target a specific data directory anyway."
        )
    return resolve_pgdata(persisted=config.pgdata)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--settings", type=Path, default=default_settings_path())
    parser.add_argument(
        "--pgdata", type=Path, default=None, help="Target this pgdata directly, bypassing persisted settings."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--status", action="store_true", help="Show whether the embedded server is running.")
    mode.add_argument("--stop", action="store_true", help="Stop the embedded server cleanly (pg_ctl -m fast).")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)

    try:
        import psutil  # noqa: F401  (used by is_running(); pgserver depends on it transitively)
    except ImportError:
        print("Cannot inspect the embedded PostgreSQL server: missing dependency 'psutil'.")
        print("Install the embedded-postgres dependency with: pip install pgserver")
        sys.exit(1)

    pgdata = _resolve_target_pgdata(args)
    sys.exit(print_status(pgdata) if args.status else stop(pgdata))


if __name__ == "__main__":
    main()
