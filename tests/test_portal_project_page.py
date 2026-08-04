"""Project page routes: gating, document serving, reports, data and the changelog.

Static markers that only read files live in tests/test_portal_frontend.py,
which is ungated; everything here needs a real database and a real session.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from tests.conftest import postgres_required
from tests.test_portal_api import PW, login, portal  # noqa: F401 - fixture reuse

PROJECT = Path(__file__).resolve().parents[1] / "pipeline" / "portal" / "projects" / "cplan"

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


def test_manual_route_serves_the_file(portal):
    # Unconditional: the manual exists, and deleting it must fail loudly here
    # rather than quietly take the other branch of an `if`.
    assert (PROJECT / "manual.html").is_file()
    page = login(portal, "pa_viewer").get("/project/cplan/manual")
    assert page.status_code == 200
    assert "glossary" in page.text.lower()


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


def test_every_tile_the_endpoint_renders_resolves_to_a_live_route(portal):
    # The test this feature was missing. `resolve_tiles` emits an href for
    # every declared kind, but only the kinds with a registered route answer
    # it: three of the seven shipped tiles were dead links to a raw JSON 404
    # from the static mount, and the manual sent readers to one of them in
    # prose, twice. Walking the endpoint's own output closes the hole for
    # every kind added after this one, not just for the three fixed here.
    client = login(portal, "pa_admin")
    body = client.get("/api/portal/projects/cplan").json()
    assert len(body["tiles"]) == 7
    for tile in body["tiles"]:
        if tile["kind"] != "app":  # the application is an external URL
            assert client.get(tile["href"]).status_code == 200, tile


def test_reports_page_lists_the_generated_workbooks(portal, tmp_path, monkeypatch):
    from pipeline.portal import pages

    directory = tmp_path / "reports"
    directory.mkdir()
    (directory / "calendar_2026.xlsx").write_bytes(b"x" * 4096)
    (directory / "notes.txt").write_bytes(b"not a report")
    monkeypatch.setattr(pages, "manifest_path", _only_for("reports", directory))

    page = login(portal, "pa_viewer").get("/project/cplan/reports")
    assert page.status_code == 200
    assert "calendar_2026.xlsx" in page.text
    assert "notes.txt" not in page.text
    assert "/project/cplan/reports/calendar_2026.xlsx" in page.text
    assert "4 KB" in page.text


def test_a_listed_report_downloads(portal, tmp_path, monkeypatch):
    from pipeline.portal import pages

    directory = tmp_path / "reports"
    directory.mkdir()
    (directory / "calendar_2026.xlsx").write_bytes(b"workbook-bytes")
    monkeypatch.setattr(pages, "manifest_path", _only_for("reports", directory))

    downloaded = login(portal, "pa_viewer").get("/project/cplan/reports/calendar_2026.xlsx")
    assert downloaded.status_code == 200
    assert downloaded.content == b"workbook-bytes"


def test_a_report_download_cannot_leave_the_report_directory(portal, tmp_path, monkeypatch):
    from pipeline.portal import pages

    directory = tmp_path / "reports"
    directory.mkdir()
    (directory / "calendar_2026.xlsx").write_bytes(b"x")
    (directory.parent / "secret.xlsx").write_bytes(b"not yours")
    monkeypatch.setattr(pages, "manifest_path", _only_for("reports", directory))

    client = login(portal, "pa_viewer")
    for name in ("../secret.xlsx", "..%2Fsecret.xlsx", "....//secret.xlsx", "notes.txt"):
        assert client.get(f"/project/cplan/reports/{name}").status_code in (400, 404)


def test_reports_page_says_none_yet_for_an_empty_or_missing_directory(portal, tmp_path, monkeypatch):
    from pipeline.portal import pages

    empty = tmp_path / "empty"
    empty.mkdir()
    for directory in (empty, tmp_path / "absent"):
        monkeypatch.setattr(pages, "manifest_path", _only_for("reports", directory))
        page = login(portal, "pa_viewer").get("/project/cplan/reports")
        assert page.status_code == 200
        assert "No reports have been generated" in page.text


def test_changelog_page_renders_the_projects_changelog(portal):
    page = login(portal, "pa_viewer").get("/project/cplan/changelog")
    assert page.status_code == 200
    # The document chrome and the print path, not the portal shell.
    assert "/document.css" in page.text
    assert "window.print()" in page.text
    assert "position: sticky" not in page.text
    # The changelog's own first entry heading, rendered from markdown.
    heading = next(
        line[3:].strip()
        for line in (PROJECT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines()
        if line.startswith("## ")
    )
    assert heading in page.text
    assert page.text.count("<h1") == 1


def test_data_page_states_the_holdings_and_the_last_refresh(portal):
    page = login(portal, "pa_viewer").get("/project/cplan/data")
    assert page.status_code == 200
    assert "This project holds" in page.text
    # The fixture database has never synced, and the page must say so plainly
    # rather than showing an empty counter table.
    assert "Nothing has ever synced" in page.text
    assert "Conflicts" not in page.text


def test_data_page_shows_the_last_sync_runs_counters(portal):
    import uuid
    from datetime import datetime, timezone

    from sqlalchemy import text

    with portal.state.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO sync_runs (id, ran_at, snapshot_path, created, updated, unchanged, "
                "conflicts, vanished, local_only, skipped_no_id) "
                "VALUES (:id, :ran_at, 'snapshot.parquet', 3, 2, 41, 1, 4, 0, 0)"
            ),
            {"id": str(uuid.uuid4()), "ran_at": datetime.now(timezone.utc)},
        )
    try:
        page = login(portal, "pa_viewer").get("/project/cplan/data")
        assert page.status_code == 200
        for label in ("Created", "Updated", "Unchanged", "Conflicts", "Vanished"):
            assert label in page.text
        assert "Nothing has ever synced" not in page.text
        assert "Last refreshed" in page.text
    finally:
        with portal.state.engine.begin() as connection:
            connection.exec_driver_sql("DELETE FROM sync_runs")


def test_manual_assets_are_gated_like_the_manual(portal):
    anonymous = TestClient(portal).get("/project/cplan/assets/roles.png", follow_redirects=False)
    assert anonymous.status_code in (302, 401)
    assert anonymous.status_code != 200

    served = login(portal, "pa_viewer").get("/project/cplan/assets/roles.png")
    assert served.status_code == 200
    assert served.content[:4] == b"\x89PNG"


def test_manual_assets_are_no_longer_on_the_public_static_tree(portal):
    # The nine screenshots used to sit under the portal's static mount, where
    # `/docs/img/roles.png` answered 200 with no session at all.
    assert TestClient(portal).get("/docs/img/roles.png").status_code != 200


def test_a_manual_asset_name_cannot_traverse(portal):
    client = login(portal, "pa_admin")
    for name in ("../manual.html", "..%2Fmanual.html", "....//resources.json", "nosuch.png"):
        assert client.get(f"/project/cplan/assets/{name}").status_code in (400, 404)


def test_new_pages_gate_exactly_like_the_existing_ones(portal):
    for suffix in ("data", "changelog", "reports"):
        anonymous = TestClient(portal).get(f"/project/cplan/{suffix}", follow_redirects=False)
        assert anonymous.status_code in (302, 401), suffix
        # An unknown project and an unentitled one are the same 404 as
        # /project/{slug}/access already is.
        assert login(portal, "pa_admin").get(f"/project/nosuchproject/{suffix}").status_code == 404


def _only_for(kind: str, directory: Path):
    """Patch `pages.manifest_path` for one tile kind, leaving the others real."""
    from pipeline.portal.resources import manifest_path as real

    def patched(slug, wanted, key=None, **kwargs):
        if wanted == kind:
            return directory
        return real(slug, wanted, key, **kwargs)

    return patched
