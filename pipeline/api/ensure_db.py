"""Create (or top up) the CPLAN schema without seeding any data.

Exists because `setup_roles.apply_roles` starts with `ALTER TABLE activities
ADD COLUMN IF NOT EXISTS created_by ...`, which fails outright with
`UndefinedTable` on a freshly provisioned database -- `IF NOT EXISTS` guards
the *column*, not the table. Until now the schema was only ever created as a
side effect of something else: the app lifespan (`create_app`) or
`import_snapshot`/`sync_snapshot`. Neither runs during `setup.ps1`, so a first
setup against a new `pgdata` (the corp path) always died at the roles step.

Same three calls, in the same order, as the app lifespan -- so a database
prepared here is exactly what the API would have produced on its first start:

    Base.metadata.create_all(engine)   # new tables
    ensure_schema(engine, metadata)    # new columns/indexes on existing tables
    ensure_analysis_views(engine)      # pgAdmin views (no-op on SQLite)

Idempotent by construction; safe on an existing, populated database.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy import Engine, inspect

from .app import Base
from .database import create_cplan_engine, ensure_schema
from .import_snapshot import resolve_database_url
from .setup_backend import default_settings_path
from .views import ensure_analysis_views


def ensure_database(engine: Engine) -> list[str]:
    """Bring `engine`'s database up to the current model; return the tables created."""
    before = set(inspect(engine).get_table_names())
    Base.metadata.create_all(engine)
    ensure_schema(engine, Base.metadata)
    ensure_analysis_views(engine)
    return sorted(set(inspect(engine).get_table_names()) - before)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or top up the CPLAN schema (no data)")
    parser.add_argument("--settings", type=Path, default=default_settings_path())
    parser.add_argument("--database-url", default=None)
    args = parser.parse_args()

    engine = create_cplan_engine(args.database_url or resolve_database_url(args.settings))
    try:
        created = ensure_database(engine)
        print(f"Schema created: {', '.join(created)}" if created else "Schema already up to date.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
