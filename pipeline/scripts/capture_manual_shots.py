"""Capture the manual's nine screenshots against a disposable PostgreSQL database.

Development tooling, not part of the portal: Playwright lives in
requirements-dev.txt and a checkout without it still serves the manual from the
committed PNGs (see main() below, which fails with an instruction rather than a
traceback). Run this after a portal or studio UI change and the manual's
pictures refresh themselves.

Why PostgreSQL, not the SQLite demo database
----------------------------------------------
Two of the nine shots cannot be produced against SQLite at all:

- "signin" is the portal's own "Your projects" page after signing in -- the
  portal (pipeline/portal/app.py) refuses to start on anything but PostgreSQL,
  because user administration is delegated to portal.* SECURITY DEFINER
  functions that only exist there.
- "roles" needs a genuine read-only session. The CPLAN studio API only
  enforces roles when it runs on PostgreSQL (pipeline/api/app.py:
  `if backend != "postgresql": auth = None`); against SQLite every session is
  the same unauthenticated "solo mode" editor and the login screen never even
  appears (pipeline/studio/app.js `initSession()` -- /api/me returns 200 with
  auth:false, so `showLoginOverlay()` is never called).

Since two shots need PostgreSQL and the other seven read from the very same
studio, this script runs the whole capture against one disposable PostgreSQL
database instead of juggling two backends and two datasets. It creates its own
database on the server pointed to by CPLAN_TEST_DATABASE_URL (falling back to
CPLAN_DATABASE_URL), the same env var the test suite already uses for a
PostgreSQL it may freely create databases and roles in, applies the normal
role/RLS setup (pipeline/api/setup_roles.py, pipeline/api/setup_portal.py),
seeds it with pipeline/scripts/generate_seed.py's synthetic, organisation-
neutral dataset, and drops the whole database (and any roles it created) again
when it is done -- so the capture is repeatable and leaves nothing behind on a
shared server.

The images are safe to commit by construction rather than by inspection: the
seed generator (pipeline/scripts/generate_seed.py) only ever writes generic
division/region/channel/audience names and no personal names, and neither the
studio nor the portal interface names the organisation anywhere. Still,
inspect every PNG by hand before committing -- see the Task 10 report.

Usage:
    CPLAN_DB_PASSWORD=<password> docker compose up -d db
    CPLAN_TEST_DATABASE_URL=postgresql+psycopg://cplan:<password>@127.0.0.1:55432/cplan \\
        PYTHONPATH=. .venv/bin/python pipeline/scripts/capture_manual_shots.py
"""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator

ROOT = Path(__file__).resolve().parents[2]
# The manual's own asset directory, declared by the project manifest
# (resources.json, the manual tile's "assets") and served by the portal's
# gated /project/{slug}/assets route -- NOT the public static tree, where
# these screenshots of the application were readable without a session.
OUT = ROOT / "pipeline" / "portal" / "projects" / "cplan" / "assets"
STUDIO_PORT = 8788
PORTAL_PORT = 8789
STUDIO_BASE = f"http://127.0.0.1:{STUDIO_PORT}"
PORTAL_BASE = f"http://127.0.0.1:{PORTAL_PORT}"
VIEWPORT = {"width": 1600, "height": 900}

BASE_URL_ENV_CANDIDATES = ("CPLAN_TEST_DATABASE_URL", "CPLAN_DATABASE_URL")


@dataclass(frozen=True)
class Shot:
    key: str
    app: str  # "studio" | "portal" -- which server this shot is captured against
    identity: str  # "admin" | "viewer" -- which of the two provisioned users signs in
    page: str | None  # a studio .nav-item[data-page] value, or None to stay put
    clicks: tuple[str, ...] = ()  # CSS selectors clicked in order, after navigating
    wait_for: str = ""  # CSS selector that must appear before the screenshot is taken
    full_page: bool = False  # capture the whole scrollable page, not just the viewport
    search: str | None = None  # typed into #activity-search before clicks, to land on one row


# The nine keys are not a guess: they are the exact <!-- shot: ... --> markers
# in the approved manual prototype
# (.superpowers/sdd/2026-08-04-portal-project-page/prototype/manual.html), in
# the order the manual's nine steps use them. Each selector below was read out
# of pipeline/studio/index.html, pipeline/studio/app.js and
# pipeline/portal/static/{index.html,app.js} -- there is no client-side
# routing in either app (no URL hash, no pushState): a "page" is a
# .nav-item[data-page] click that toggles a `.page.active` section, so every
# shot after the first navigates by clicking, not by URL.
SHOTS = [
    # The manual's own caption: "The portal home. The tile shows the purpose
    # and your role...". That page is pipeline/portal/static/index.html, a
    # different application from the studio -- not a studio login form (the
    # studio's #login-overlay only ever appears when the studio itself is
    # unauthenticated, which is not what step 1 of the manual is about).
    Shot("signin", app="portal", identity="admin", page=None, wait_for="#project-tiles .tile"),
    Shot("overview", app="studio", identity="admin", page="overview", wait_for="#overview-kpis > *"),
    # Taller than 16:9 by construction: the whole result table (and, below,
    # the whole Health page) is a scrolling list. Cropping to one viewport
    # would cut rows out of a manual whose entire point is "here is the
    # workbench" -- decided in favour of a taller frame over a lossy crop.
    Shot(
        "activities",
        app="studio",
        identity="admin",
        page="activities",
        wait_for="#activity-table-body tr",
        full_page=True,
    ),
    # The drawer in CREATE mode, not the read view: openCreateDrawer() (app.js)
    # is only reachable through #activity-new/#overview-new/#packs-new, never
    # by loading a URL.
    Shot(
        "activity-form",
        app="studio",
        identity="admin",
        page="activities",
        clicks=("#activity-new",),
        wait_for="#activity-drawer.open #fs-identity",
    ),
    # #packs-new opens the same drawer already switched to pack scope
    # (app.js: `openCreateDrawer(...);setScope('pack');`), which is what
    # reveals the channel matrix (#pack-channels) and the fill-down rows.
    Shot(
        "pack-form",
        app="studio",
        identity="admin",
        page="packs",
        clicks=("#packs-new",),
        wait_for="#pack-channels input",
    ),
    # A saved activity's read-view drawer, opened from its table row --
    # #drawer-tracking only carries a real tid-prefix/tid-date/... breakdown
    # once a persisted row (with a real tracking_id) is behind it.
    Shot(
        "tracking-id",
        app="studio",
        identity="admin",
        page="activities",
        clicks=("#activity-table-body tr:first-child",),
        wait_for="#drawer-tracking .tid-prefix",
    ),
    Shot(
        "health",
        app="studio",
        identity="admin",
        page="health",
        wait_for="#health-kpis > *",
        full_page=True,
    ),
    # Deliberately not clicked: exportActivities() (app.js) triggers a real
    # browser download via a generated .xlsx Blob, which is a side effect this
    # script has no use for and Playwright would otherwise have to intercept.
    # The manual's own caption only needs the button and the tab it lives on.
    Shot("export", app="studio", identity="admin", page="activities", wait_for="#activity-export"),
    # The same drawer as "tracking-id", opened by the *viewer* user this time.
    # Role gating (app.js canEditActivity/canDelete) hides #drawer-edit and
    # #drawer-delete for a viewer -- that is the whole point of this shot, and
    # why it must not be captured under the admin session everything else
    # uses.
    Shot(
        "roles",
        app="studio",
        identity="viewer",
        page="activities",
        clicks=("#activity-table-body tr:first-child",),
        wait_for="#activity-drawer.open",
    ),
]


def _base_database_url() -> str | None:
    for name in BASE_URL_ENV_CANDIDATES:
        value = os.environ.get(name)
        if value:
            return value
    return None


@contextmanager
def _capture_database(base_url: str) -> Iterator[str]:
    """A freshly created, uniquely named PostgreSQL database, dropped on exit.

    Mirrors tests/conftest.py's `_external_test_database`: creates its own
    database on the same server rather than touching whatever `cplan` holds,
    and diffs pg_roles before/after so every role this run creates (the group
    roles, the two ad hoc login users) is dropped too -- a second run starts
    from a clean slate instead of colliding with "role already exists".
    """
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    admin_url = make_url(base_url)
    db_name = f"cplan_capture_{uuid.uuid4().hex[:10]}"
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    quote = admin_engine.dialect.identifier_preparer.quote
    try:
        with admin_engine.connect() as connection:
            connection.execute(text(f"CREATE DATABASE {quote(db_name)}"))
            roles_before = {row[0] for row in connection.execute(text("SELECT rolname FROM pg_roles"))}
        # NOT str(...): SQLAlchemy's default __str__ hides the password.
        database_url = admin_url.set(database=db_name).render_as_string(hide_password=False)
        try:
            yield database_url
        finally:
            with admin_engine.connect() as connection:
                connection.execute(text(f"DROP DATABASE IF EXISTS {quote(db_name)} WITH (FORCE)"))
                roles_after = {row[0] for row in connection.execute(text("SELECT rolname FROM pg_roles"))}
                for role in sorted(roles_after - roles_before):
                    connection.execute(text(f"DROP ROLE IF EXISTS {quote(role)}"))
    finally:
        admin_engine.dispose()


@dataclass(frozen=True)
class Credentials:
    admin: tuple[str, str]
    viewer: tuple[str, str]
    tracking_id_example: str


def _mint_example_activity(database_url: str) -> str:
    """Insert one activity the same way the API itself would, and return its tracking ID.

    generate_seed.py's own synthetic tracking IDs (e.g. "IC-2026-0001-EM")
    predate the v6 format (pipeline/api/app.py's `generate_tracking_id`,
    CLUSTER-PACKNUM-YYMMDD-ACTNUM-CHANNEL) the studio itself mints on save and
    the manual's own glossary documents -- app.js's TRACKING_ID_RE does not
    match them, so `.tid-prefix` never renders for a seeded row. Rather than
    reach into generate_seed.py's data shape, this adds one further row
    through the exact function POST /api/activities uses to mint an ID, so
    the "tracking-id" shot shows a genuine, correctly formatted one.
    """
    from sqlalchemy.orm import Session

    from pipeline.api.app import Activity, ActivityChange, Base, create_app, generate_tracking_id
    from sqlalchemy import select

    app = create_app(database_url)
    engine = app.state.engine
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        existing = [
            (channel, tracking_id)
            for channel, tracking_id in session.execute(
                select(Activity.channel, Activity.tracking_id).where(Activity.tracking_id.isnot(None))
            ).all()
        ]
        start = datetime.now() + timedelta(days=21)
        tracking_id = generate_tracking_id(
            existing, communication_pack_cpid=None, start_date=start, channel="Email"
        )
        activity_id = uuid.uuid4()
        session.add(
            Activity(
                id=activity_id,
                source_type="internal",
                tracking_id=tracking_id,
                activity_name="Quarterly results town hall",
                activity_description="Town hall recap of quarterly results for all employees.",
                target_audience="All Employees",
                business_division="Corporate Functions",
                region="EMEA",
                channel="Email",
                lead_team="Team A",
                lead="Team A",
                start_date=start,
                end_date=start + timedelta(hours=2),
                priority="High",
                strategic_objectives="Culture",
                audience="4200",
                news_digest=True,
                time_zone="Europe/Zurich",
                is_archive=False,
                created_by="capture_admin",
            )
        )
        session.add(ActivityChange(activity_id=activity_id, actor="capture_admin", change_type="created", version_to=1))
        session.commit()
    engine.dispose()
    return tracking_id


def _provision_and_seed(database_url: str) -> Credentials:
    """Schema, roles, RLS, the portal registry, two login users, and demo data."""
    from pipeline.api.app import Base
    from pipeline.api.database import create_cplan_engine
    from pipeline.api.setup_portal import apply_portal, register_project
    from pipeline.api.setup_roles import apply_roles, create_user
    from pipeline.scripts.generate_seed import build_records, write as write_seed

    engine = create_cplan_engine(database_url)
    try:
        Base.metadata.create_all(engine)
        apply_roles(engine)
        apply_portal(engine)
        register_project(engine, "cplan", "Communication Planning", f"{STUDIO_BASE}/", "cplan")

        admin_password = secrets.token_urlsafe(18)
        viewer_password = secrets.token_urlsafe(18)
        create_user(engine, "capture_admin", admin_password, "admin")
        create_user(engine, "capture_viewer", viewer_password, "viewer")
    finally:
        engine.dispose()

    records, _planted = build_records(count=400, seed=1, today=datetime.now())
    write_seed(database_url, records, replace=True)
    tracking_id_example = _mint_example_activity(database_url)

    return Credentials(
        admin=("capture_admin", admin_password),
        viewer=("capture_viewer", viewer_password),
        tracking_id_example=tracking_id_example,
    )


def _wait_http_ready(url: str, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1)  # noqa: S310 - localhost only
            return
        except urllib.error.URLError as error:
            last_error = error
            time.sleep(0.3)
    raise RuntimeError(f"Server at {url} did not become ready within {timeout:.0f}s") from last_error


@contextmanager
def _server(script: str, port: int, settings_path: Path, database_url: str, auth_secret: str) -> Iterator[None]:
    env = {
        **os.environ,
        "CPLAN_DATABASE_URL": database_url,
        "CPLAN_AUTH_SECRET": auth_secret,
    }
    process = subprocess.Popen(
        [sys.executable, str(ROOT / "pipeline" / "scripts" / script), "--settings", str(settings_path), "--port", str(port)],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    try:
        _wait_http_ready(f"http://127.0.0.1:{port}/")
        yield
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def _login_studio(page, username: str, password: str) -> None:
    page.goto(f"{STUDIO_BASE}/")
    page.wait_for_selector("#login-overlay:not(.hidden) #login-form", state="visible", timeout=15_000)
    page.fill("#login-username", username)
    page.fill("#login-password", password)
    page.click("#login-form button[type=submit]")
    # "#login-overlay.hidden" (display:none) is never "visible" -- wait for
    # the plain #login-overlay element to become hidden instead.
    page.wait_for_selector("#login-overlay", state="hidden", timeout=15_000)
    page.wait_for_selector(".app-shell", state="visible", timeout=15_000)


def _login_portal(page, username: str, password: str) -> None:
    page.goto(f"{PORTAL_BASE}/")
    page.wait_for_selector("#login-overlay:not(.hidden) #login-form", state="visible", timeout=15_000)
    page.fill("#login-username", username)
    page.fill("#login-password", password)
    page.click("#login-form button[type=submit]")
    page.wait_for_selector("#login-overlay", state="hidden", timeout=15_000)


def _close_any_open_drawer(page) -> None:
    """Close the activity drawer left open by a previous shot, if any.

    Its backdrop covers the whole viewport and intercepts every click behind
    it (including the main nav), so a shot that opened the drawer (create,
    pack, tracking-id, roles) would otherwise strand every shot after it.
    """
    if page.locator("#activity-drawer.open").count():
        page.keyboard.press("Escape")
        page.wait_for_selector("#activity-drawer.open", state="detached", timeout=5_000)


def _capture(page, shot: Shot) -> None:
    _close_any_open_drawer(page)
    if shot.page:
        page.click(f'.nav-item[data-page="{shot.page}"]')
    if shot.page == "activities":
        # The search box is app.js SPA state, not reset by switching tabs --
        # without this, a shot that runs after "tracking-id" (which searches
        # for one specific tracking ID) would inherit that filter and show a
        # single leftover row instead of the full, representative table.
        # Same search box the manual's step 3 describes covering activity
        # name, campaign, lead AND tracking ID -- used here (when shot.search
        # is set) to land on exactly the one row the "tracking-id" shot
        # needs, deterministically.
        # The input is filtered through a 200ms debounce (app.js
        # debouncedActivityFilters), so the table right after fill() is still
        # whatever it was before -- wait out the debounce before clicking, or
        # a click lands on an arbitrary/stale row.
        page.fill("#activity-search", shot.search or "")
        page.wait_for_timeout(400)
        page.wait_for_selector("#activity-table-body tr", state="visible", timeout=15_000)
    for selector in shot.clicks:
        page.click(selector)
    page.wait_for_selector(shot.wait_for, state="visible", timeout=15_000)
    page.wait_for_timeout(500)  # let CSS transitions and chart rendering settle
    page.screenshot(path=str(OUT / f"{shot.key}.png"), full_page=shot.full_page)
    print(f"captured {shot.key}.png")


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright is not installed. Install the dev dependency and its browser:", file=sys.stderr)
        print("  .venv/bin/python -m pip install -r requirements-dev.txt", file=sys.stderr)
        print("  .venv/bin/python -m playwright install chromium", file=sys.stderr)
        return 1

    base_url = _base_database_url()
    if not base_url:
        print(
            "No PostgreSQL to capture against. Two of the nine shots (the portal's "
            "sign-in page, and a genuine read-only 'roles' session) need real "
            "PostgreSQL roles that SQLite cannot provide. Start one and point this "
            "script at it:\n"
            "  CPLAN_DB_PASSWORD=<password> docker compose up -d db\n"
            "  CPLAN_TEST_DATABASE_URL=postgresql+psycopg://cplan:<password>@127.0.0.1:55432/cplan \\\n"
            "      PYTHONPATH=. .venv/bin/python pipeline/scripts/capture_manual_shots.py",
            file=sys.stderr,
        )
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    auth_secret = secrets.token_urlsafe(24)

    with _capture_database(base_url) as database_url:
        credentials = _provision_and_seed(database_url)
        # SHOTS stays static (and importable by
        # test_capture_script_declares_a_shot_per_manual_step) -- the one
        # shot that needs a value only known after seeding gets it patched
        # into a per-run copy here instead.
        runtime_shots = [
            replace(shot, search=credentials.tracking_id_example) if shot.key == "tracking-id" else shot
            for shot in SHOTS
        ]

        import tempfile

        with tempfile.TemporaryDirectory() as tmp_dir:
            from pipeline.api.setup_backend import configure_backend

            settings_path = Path(tmp_dir) / "cplan-settings.json"
            configure_backend("postgresql", database_url=database_url, settings_path=settings_path, force=True)

            with _server("start_cplan.py", STUDIO_PORT, settings_path, database_url, auth_secret), _server(
                "start_portal.py", PORTAL_PORT, settings_path, database_url, auth_secret
            ):
                with sync_playwright() as p:
                    browser = p.chromium.launch()
                    try:
                        contexts: dict[tuple[str, str], object] = {}

                        def page_for(shot: Shot):
                            key = (shot.app, shot.identity)
                            if key not in contexts:
                                context = browser.new_context(viewport=VIEWPORT, device_scale_factor=2)
                                new_page = context.new_page()
                                username, password = getattr(credentials, shot.identity)
                                if shot.app == "studio":
                                    _login_studio(new_page, username, password)
                                else:
                                    _login_portal(new_page, username, password)
                                contexts[key] = (context, new_page)
                            return contexts[key][1]

                        for shot in runtime_shots:
                            _capture(page_for(shot), shot)
                    finally:
                        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
