"""Real end-to-end coverage for the postgres-embedded backend, against an actual pgserver instance.

Everything else in the suite either exercises this backend's logic against a
stubbed `pgserver` module (`tests/test_database.py`, `tests/test_setup_backend.py`)
or with hand-built `postmaster.pid` fixtures (`tests/test_cplan_db.py`) -- fast and
dependency-free. This module is the one place that starts a real embedded
PostgreSQL 16 server, so it is intentionally compact and skips itself cleanly
when `pgserver` is not installed (an optional dependency -- see
`pipeline/api/requirements.txt`), so CI without it stays green.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import text

from pipeline.api.database import create_cplan_engine, embedded_database_url
from pipeline.api.setup_backend import configure_backend, load_backend_config, resolve_backend_database_url
from pipeline.scripts.cplan_db import is_running, stop

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("pgserver") is None,
    reason="pgserver is not installed; the postgres-embedded backend is optional (pip install pgserver)",
)


def test_postgres_embedded_backend_configures_connects_and_stops_cleanly(tmp_path):
    settings_path = tmp_path / "cplan-settings.json"
    pgdata = tmp_path / "pgdata"

    # 1. Setup: starts the embedded server, creates the `cplan` database, validates with SELECT 1.
    configured = configure_backend("postgres-embedded", settings_path=settings_path, pgdata=pgdata)

    assert configured.backend == "postgres-embedded"
    assert Path(configured.pgdata) == pgdata.resolve()
    assert (pgdata / "PG_VERSION").exists()
    running, _info = is_running(pgdata)
    assert running is True

    # 2. Runtime resolution: a fresh process reading persisted settings gets a working URL.
    loaded = load_backend_config(settings_path)
    database_url = resolve_backend_database_url(loaded)
    assert database_url.startswith("postgresql+psycopg://")

    engine = create_cplan_engine(database_url)
    try:
        with engine.connect() as connection:
            assert connection.execute(text("SELECT 1")).scalar_one() == 1
    finally:
        engine.dispose()

    # 3. Idempotency: calling embedded_database_url again reuses the running server.
    assert embedded_database_url(pgdata) == database_url

    # 4. Clean stop: pg_ctl -m fast, never a hard kill; postmaster.pid is removed.
    exit_code = stop(pgdata)
    assert exit_code == 0
    running_after_stop, _info = is_running(pgdata)
    assert running_after_stop is False
    assert not (pgdata / "postmaster.pid").exists()
