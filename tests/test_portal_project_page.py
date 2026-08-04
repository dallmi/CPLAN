"""Project page routes: gating, document serving, and the static shell."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.conftest import postgres_required
from tests.test_portal_api import PW, login, portal  # noqa: F401 - fixture reuse

STATIC = Path(__file__).resolve().parents[1] / "pipeline" / "portal" / "static"

# The `portal` fixture is reused from test_portal_api, but pytest's skipif
# marker applies per module, not to the fixture itself -- without this,
# collecting this module without a database available doesn't skip these
# tests, it errors them (the fixture tries to start postgres and fails).
pytestmark = postgres_required


def test_project_page_is_served_and_not_swallowed_by_the_static_mount(portal):
    page = login(portal, "pa_admin").get("/project/cplan")
    assert page.status_code == 200
    assert "project-tiles" in page.text


def test_project_page_requires_a_session(portal):
    anonymous = TestClient(portal).get("/project/cplan", follow_redirects=False)
    assert anonymous.status_code in (302, 401)


def test_declared_document_renders(portal):
    page = login(portal, "pa_viewer").get("/project/cplan/docs/data-model")
    assert page.status_code == 200
    assert "Data model" in page.text


def test_undeclared_document_is_404(portal):
    # The internal review document is in pipeline/docs/ but not in the manifest.
    assert login(portal, "pa_admin").get("/project/cplan/docs/design-review-v2").status_code == 404


def test_document_key_cannot_traverse(portal):
    client = login(portal, "pa_admin")
    for key in ("../../../etc/passwd", "..%2F..%2Fapp.py", "....//app.py"):
        assert client.get(f"/project/cplan/docs/{key}").status_code in (400, 404)


def test_manual_route_serves_the_file_once_it_exists(portal):
    # The manual itself is written in Task 11. Until then the declared file is
    # absent and the route must 404 cleanly rather than 500 — which is the more
    # important half of this test anyway, since it is also what a project
    # without a manual gets.
    manual = Path(__file__).resolve().parents[1] / "pipeline" / "portal" / "projects" / "cplan" / "manual.html"
    page = login(portal, "pa_viewer").get("/project/cplan/manual")
    if manual.is_file():
        assert page.status_code == 200
        assert "glossary" in page.text.lower()
    else:
        assert page.status_code == 404


def test_access_page_states_the_callers_role(portal):
    page = login(portal, "pa_viewer").get("/project/cplan/access")
    assert page.status_code == 200
    assert "Viewer" in page.text


def test_access_page_top_bar_carries_the_username_and_no_role_label(portal):
    # Carried over from the project-page decision this page's own comment
    # documents: "username only, no role label" -- a role shown in the top
    # bar would contradict the sentence "Your access" states below it
    # whenever the two happen to differ, which is exactly the contradiction
    # this decision exists to avoid; the role stays a one-place fact. The
    # username is populated client-side (same /api/me fetch project pages
    # use), so the assertion is on the markup and script the client runs,
    # not on rendered text.
    page = login(portal, "pa_viewer").get("/project/cplan/access")
    assert page.status_code == 200
    assert 'id="user-chip-name"' in page.text
    assert "/api/me" in page.text
    assert "user.username" in page.text
    assert "user.role" not in page.text


def test_pages_of_an_unentitled_project_are_404(portal):
    assert login(portal, "pa_admin").get("/project/nosuchproject").status_code == 404


def test_home_tiles_link_into_the_project_page():
    app_js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "/project/" in app_js
    # The raw URL is gone from the tile: it belongs on the project page now.
    assert "tile-url" not in app_js


def test_project_shell_markup_and_no_emoji():
    html = (STATIC / "project.html").read_text(encoding="utf-8")
    js = (STATIC / "project.js").read_text(encoding="utf-8")
    assert 'id="project-tiles"' in html
    assert 'id="project-role"' in html
    assert "/api/portal/projects/" in js
    emoji = re.compile("[\U0001F000-\U0001FFFF\U00002600-\U000027BF\U00002B00-\U00002BFF]")
    assert not emoji.search(html) and not emoji.search(js)


def test_document_css_keeps_sticky_off_the_print_path():
    css = (STATIC / "document.css").read_text(encoding="utf-8")
    if "position: sticky" in css:
        assert "@media screen" in css


def test_every_manual_screenshot_referenced_exists():
    manual = Path(__file__).resolve().parents[1] / "pipeline" / "portal" / "projects" / "cplan" / "manual.html"
    if not manual.is_file():
        pytest.skip("the manual has not been written yet")
    referenced = set(re.findall(r'src="(/docs/img/[^"]+)"', manual.read_text(encoding="utf-8")))
    assert referenced, "the manual should carry screenshots"
    for source in referenced:
        assert (STATIC / source.lstrip("/")).is_file(), f"missing screenshot: {source}"


def test_capture_script_declares_a_shot_per_manual_step():
    from pipeline.scripts.capture_manual_shots import SHOTS

    assert len(SHOTS) >= 9
    assert len({shot.key for shot in SHOTS}) == len(SHOTS)
