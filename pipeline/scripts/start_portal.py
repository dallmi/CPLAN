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
from pipeline.api.login_guard import MISSING_GUARD_MESSAGE, login_guard_installed
from pipeline.api.setup_backend import (
    default_settings_path,
    load_backend_config,
    resolve_backend_database_url,
)

DEFAULT_PORT = 8781  # studio runs on 8780; the portal sits alongside it


class PortalSetupIncomplete(RuntimeError):
    """The database is missing objects only `setup_portal` creates."""


def create_configured_portal_app(settings_path: Path | None = None):
    config = load_backend_config(settings_path)
    app = create_portal_app(resolve_backend_database_url(config))
    connection = app.state.engine.connect()
    try:
        connection.execute(text("SELECT 1"))
    finally:
        connection.close()
    # `SELECT 1` says the database answers; it does not say this release's
    # schema step was ever run against it. The documented upgrade route is
    # hand-copied files, so an installation can end up with the new portal
    # code and an old database, where every sign-in -- user and administrator
    # alike -- fails closed with a 503 and the only trace is a traceback in
    # this window. Refuse here instead, where there is room to say what to run.
    if not login_guard_installed(app.state.engine):
        raise PortalSetupIncomplete(MISSING_GUARD_MESSAGE)
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, default=default_settings_path())
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    try:
        app = create_configured_portal_app(args.settings)
    except PortalSetupIncomplete as exc:
        print(f"\n{exc}\n")
        raise SystemExit(2)
    print(f"Starting CPLAN portal with {app.state.engine.dialect.name} at http://127.0.0.1:{args.port}/")
    # proxy_headers=False is load-bearing, not tidiness. uvicorn's default is
    # True with forwarded_allow_ips falling back to the bound host, so on a
    # server bound to 127.0.0.1 *every* peer is a trusted proxy and
    # ProxyHeadersMiddleware rewrites scope["client"] from whatever
    # X-Forwarded-For the caller sent -- handing each request its own
    # per-source bucket, or letting it spend someone else's. There is no proxy
    # in front of this process; the transport peer is the only address it may
    # believe (pipeline/api/login_guard.py).
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=args.port,
        proxy_headers=False,
        forwarded_allow_ips=[],
    )


if __name__ == "__main__":
    main()
