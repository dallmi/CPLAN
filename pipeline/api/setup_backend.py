"""Explicitly configure the local database backend used by CPLAN."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path, PureWindowsPath
from typing import Literal, Mapping

from sqlalchemy import text
from sqlalchemy.engine import make_url

from .database import backend_from_url, create_cplan_engine, embedded_database_url


BackendName = Literal["postgresql", "sqlite", "postgres-embedded"]
# Bumped for postgres-embedded: a new backend value plus the new `pgdata` field.
SETTINGS_SCHEMA_VERSION = 3


@dataclass(frozen=True)
class BackendConfig:
    backend: BackendName
    database_url: str | None = None
    pgdata: str | None = None


def default_cplan_home() -> Path:
    repo_data_dir = Path(__file__).resolve().parents[1] / "data"
    return Path(os.environ.get("CPLAN_HOME", repo_data_dir)).expanduser().resolve()


def default_settings_path() -> Path:
    return default_cplan_home() / "cplan-settings.json"


def default_pgdata_dir() -> Path:
    """Platform default data directory for the embedded PostgreSQL server.

    Windows: `%LOCALAPPDATA%/CPLAN/postgres` (falls back to `~/AppData/Local` if
    the env var is somehow unset -- it always is on a real Windows session).
    macOS: `~/Library/Application Support/CPLAN/postgres`.
    Linux: `$XDG_DATA_HOME/CPLAN/postgres`, or `~/.local/share/CPLAN/postgres`.

    Branches on `sys.platform` rather than `os.name`: `os.name` also selects
    `pathlib`'s `WindowsPath`/`PosixPath` internally, so monkeypatching it in
    tests to simulate another OS corrupts every `Path` constructed for the rest
    of the process (pytest's own reporting included) -- `sys.platform` carries
    the same information without that side effect.
    """
    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(local_app_data) / "CPLAN" / "postgres"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "CPLAN" / "postgres"
    xdg_data_home = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(xdg_data_home) / "CPLAN" / "postgres"


def resolve_pgdata(
    explicit: str | Path | None = None,
    persisted: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Resolve the embedded PostgreSQL data directory.

    Precedence: `explicit` (the `--pgdata` flag) > `CPLAN_PGDATA` (env) >
    `persisted` (the pgdata recorded in settings) > the platform default user-data
    directory. `CPLAN_PGDATA` deliberately outranks `persisted` so the corp
    fallback (e.g. to a network share when local disk turns out unusable) takes
    effect just by exporting the variable -- no need to re-run setup_backend.

    A resolved path that looks like a UNC network share (`\\\\server\\share\\...`)
    is not rejected -- just warned about: Windows network drives caused real
    WAL/timeout/crash pain in a previous project; a local user-data directory is
    strongly preferred, but the corp machine's actual disk layout is not this
    function's call to make.
    """
    environment = os.environ if environ is None else environ
    candidate = explicit or environment.get("CPLAN_PGDATA") or persisted or default_pgdata_dir()
    if PureWindowsPath(str(candidate)).drive.startswith("\\\\"):
        print(
            f"WARNING: pgdata resolves to a UNC network path ({candidate}). Network shares add "
            "WAL/timeout latency and have caused crashes under load before -- a local user-data "
            "directory is strongly preferred; if you must use a network share, raise client "
            "connection timeouts to at least 60s.",
            file=sys.stderr,
        )
    return Path(candidate).expanduser().resolve()


def _validate_database(database_url: str) -> None:
    parsed = make_url(database_url)
    sqlite_path = None
    if parsed.get_backend_name() == "sqlite" and parsed.database and parsed.database != ":memory:":
        sqlite_path = Path(parsed.database).expanduser().resolve()
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        sqlite_path.parent.chmod(0o700)
    engine = create_cplan_engine(database_url)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    finally:
        engine.dispose()
    if sqlite_path and sqlite_path.exists():
        sqlite_path.chmod(0o600)


def load_backend_config(settings_path: Path | None = None) -> BackendConfig:
    path = (settings_path or default_settings_path()).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(
            f"CPLAN database is not configured: {path}. Run python -m pipeline.api.setup_backend first."
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    config = BackendConfig(
        backend=payload["backend"],
        database_url=payload.get("database_url"),
        pgdata=payload.get("pgdata"),
    )
    if config.backend == "sqlite":
        if not config.database_url:
            raise ValueError("SQLite configuration is missing its database URL")
        actual_backend = backend_from_url(config.database_url)
        if actual_backend != config.backend:
            raise ValueError(
                f"Configured backend {config.backend} does not match database URL backend {actual_backend}"
            )
    elif config.backend == "postgres-embedded":
        if not config.pgdata:
            raise ValueError("postgres-embedded configuration is missing its pgdata path")
        if config.database_url is not None:
            raise ValueError("postgres-embedded configuration must not persist a database URL")
    elif config.database_url is not None:
        raise ValueError("PostgreSQL credentials must not be persisted in CPLAN settings")
    return config


def resolve_backend_database_url(
    config: BackendConfig,
    environ: Mapping[str, str] | None = None,
) -> str:
    if config.backend == "sqlite":
        if not config.database_url:
            raise RuntimeError("SQLite database URL is missing from CPLAN settings")
        return config.database_url

    environment = os.environ if environ is None else environ

    if config.backend == "postgres-embedded":
        if not config.pgdata:
            raise RuntimeError("pgdata is missing from the configured postgres-embedded backend")
        pgdata = resolve_pgdata(persisted=config.pgdata, environ=environment)
        return embedded_database_url(pgdata)

    database_url = environment.get("CPLAN_DATABASE_URL")
    if not database_url:
        raise RuntimeError("CPLAN_DATABASE_URL is required for the configured PostgreSQL backend")
    if backend_from_url(database_url) != "postgresql":
        raise RuntimeError("CPLAN_DATABASE_URL does not point to PostgreSQL")
    return database_url


def configure_backend(
    backend: BackendName,
    database_url: str | None = None,
    settings_path: Path | None = None,
    force: bool = False,
    pgdata: str | Path | None = None,
) -> BackendConfig:
    path = (settings_path or default_settings_path()).expanduser().resolve()

    if backend == "postgres-embedded":
        if path.exists() and not force:
            raise FileExistsError(f"CPLAN database is already configured at {path}; use --force to replace it")
        resolved_pgdata = resolve_pgdata(explicit=pgdata)
        _validate_database(embedded_database_url(resolved_pgdata))
        config = BackendConfig(backend=backend, database_url=None, pgdata=str(resolved_pgdata))
    else:
        if not database_url:
            raise ValueError(f"A database_url is required to configure the {backend} backend")
        actual_backend = backend_from_url(database_url)
        if backend != actual_backend:
            raise ValueError(f"Selected backend {backend} does not match database URL backend {actual_backend}")
        if path.exists() and not force:
            raise FileExistsError(f"CPLAN database is already configured at {path}; use --force to replace it")

        _validate_database(database_url)
        config = BackendConfig(
            backend=backend,
            database_url=database_url if backend == "sqlite" else None,
            pgdata=None,
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps({"schema_version": SETTINGS_SCHEMA_VERSION, **asdict(config)}, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.chmod(0o600)
    temporary_path.replace(path)
    return config


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", required=True, choices=("postgresql", "sqlite", "postgres-embedded"))
    parser.add_argument("--settings", type=Path, default=default_settings_path())
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--pgdata",
        type=Path,
        default=None,
        help=(
            "Embedded PostgreSQL data directory (postgres-embedded backend only). "
            "Defaults to the platform user-data directory; overridable via CPLAN_PGDATA."
        ),
    )
    args = parser.parse_args()

    if args.backend == "postgres-embedded":
        try:
            config = configure_backend(
                "postgres-embedded", settings_path=args.settings, force=args.force, pgdata=args.pgdata
            )
        except RuntimeError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        print(f"Configured CPLAN backend: {config.backend} (pgdata={config.pgdata})")
        return

    database_url = os.environ.get("CPLAN_DATABASE_URL")
    if args.backend == "sqlite":
        database_url = f"sqlite:///{default_cplan_home() / 'cplan.sqlite3'}"
    if not database_url:
        parser.error("CPLAN_DATABASE_URL is required in the environment for PostgreSQL")

    config = configure_backend(args.backend, database_url, args.settings, args.force)
    safe_url = make_url(database_url).render_as_string(hide_password=True)
    print(f"Configured CPLAN backend: {config.backend} ({safe_url})")


if __name__ == "__main__":
    main()
