"""Start CPLAN with its explicitly configured local database backend."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import uvicorn
from sqlalchemy import text

from pipeline.api.app import create_app
from pipeline.api.login_guard import MISSING_GUARD_MESSAGE, login_guard_installed
from pipeline.api.setup_backend import (
    default_settings_path,
    load_backend_config,
    resolve_backend_database_url,
)


class StudioSetupIncomplete(RuntimeError):
    """The database is missing objects only `setup_portal` creates."""


def create_configured_app(settings_path: Path | None = None):
    config = load_backend_config(settings_path)
    app = create_app(resolve_backend_database_url(config))
    with app.state.engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    # Only when this studio actually authenticates people: solo mode has no
    # login to throttle. With a secret set, the studio's own POST /api/login
    # checks the same roles and mints the same cookie as the portal, so it
    # shares the portal's counters -- and therefore needs the same schema step.
    if app.state.login_guard is not None and not login_guard_installed(app.state.engine):
        raise StudioSetupIncomplete(MISSING_GUARD_MESSAGE)
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, default=default_settings_path())
    parser.add_argument("--port", type=int, default=8780)
    args = parser.parse_args()

    try:
        app = create_configured_app(args.settings)
    except StudioSetupIncomplete as exc:
        print(f"\n{exc}\n")
        raise SystemExit(2)
    print(f"Starting CPLAN with {app.state.engine.dialect.name} at http://127.0.0.1:{args.port}/")
    # See start_portal.py: uvicorn would otherwise trust an X-Forwarded-For
    # from every peer of a loopback-bound server and hand each request its own
    # rate-limit bucket.
    uvicorn.run(app, host="127.0.0.1", port=args.port, proxy_headers=False, forwarded_allow_ips=[])


if __name__ == "__main__":
    main()
