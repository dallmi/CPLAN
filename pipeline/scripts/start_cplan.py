"""Start CPLAN with its explicitly configured local database backend."""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn
from sqlalchemy import text

from pipeline.api.app import create_app
from pipeline.api.setup_backend import (
    default_settings_path,
    load_backend_config,
    resolve_backend_database_url,
)


def create_configured_app(settings_path: Path | None = None):
    config = load_backend_config(settings_path)
    app = create_app(resolve_backend_database_url(config))
    with app.state.engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, default=default_settings_path())
    parser.add_argument("--port", type=int, default=8780)
    args = parser.parse_args()

    app = create_configured_app(args.settings)
    print(f"Starting CPLAN with {app.state.engine.dialect.name} at http://127.0.0.1:{args.port}/")
    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
