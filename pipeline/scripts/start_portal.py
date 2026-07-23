"""Start the CPLAN portal against the configured local database backend."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import uvicorn
from sqlalchemy import text

from pipeline.portal.app import create_portal_app
from pipeline.api.setup_backend import (
    default_settings_path,
    load_backend_config,
    resolve_backend_database_url,
)

DEFAULT_PORT = 8781  # studio runs on 8780; the portal sits alongside it


def create_configured_portal_app(settings_path: Path | None = None):
    config = load_backend_config(settings_path)
    app = create_portal_app(resolve_backend_database_url(config))
    connection = app.state.engine.connect()
    try:
        connection.execute(text("SELECT 1"))
    finally:
        connection.close()
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, default=default_settings_path())
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    app = create_configured_portal_app(args.settings)
    print(f"Starting CPLAN portal with {app.state.engine.dialect.name} at http://127.0.0.1:{args.port}/")
    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
