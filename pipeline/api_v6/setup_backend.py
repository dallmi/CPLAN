"""Explicitly configure the local database backend used by CPLAN V6."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, Mapping

from sqlalchemy import text
from sqlalchemy.engine import make_url

from .database import backend_from_url, create_cplan_engine


BackendName = Literal["postgresql", "sqlite"]
SETTINGS_SCHEMA_VERSION = 2


@dataclass(frozen=True)
class BackendConfig:
    backend: BackendName
    database_url: str | None = None


def default_cplan_home() -> Path:
    return Path(os.environ.get("CPLAN_HOME", Path.home() / ".cplan")).expanduser().resolve()


def default_settings_path() -> Path:
    return default_cplan_home() / "cplan-settings.json"


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
            f"CPLAN database is not configured: {path}. Run python -m pipeline.api_v6.setup_backend first."
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    config = BackendConfig(backend=payload["backend"], database_url=payload.get("database_url"))
    if config.backend == "sqlite":
        if not config.database_url:
            raise ValueError("SQLite configuration is missing its database URL")
        actual_backend = backend_from_url(config.database_url)
        if actual_backend != config.backend:
            raise ValueError(
                f"Configured backend {config.backend} does not match database URL backend {actual_backend}"
            )
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
    database_url = environment.get("CPLAN_DATABASE_URL")
    if not database_url:
        raise RuntimeError("CPLAN_DATABASE_URL is required for the configured PostgreSQL backend")
    if backend_from_url(database_url) != "postgresql":
        raise RuntimeError("CPLAN_DATABASE_URL does not point to PostgreSQL")
    return database_url


def configure_backend(
    backend: BackendName,
    database_url: str,
    settings_path: Path | None = None,
    force: bool = False,
) -> BackendConfig:
    path = (settings_path or default_settings_path()).expanduser().resolve()
    actual_backend = backend_from_url(database_url)
    if backend != actual_backend:
        raise ValueError(f"Selected backend {backend} does not match database URL backend {actual_backend}")
    if path.exists() and not force:
        raise FileExistsError(f"CPLAN database is already configured at {path}; use --force to replace it")

    _validate_database(database_url)
    config = BackendConfig(backend=backend, database_url=database_url if backend == "sqlite" else None)
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
    parser.add_argument("--backend", required=True, choices=("postgresql", "sqlite"))
    parser.add_argument("--settings", type=Path, default=default_settings_path())
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

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
