"""The project resource manifest: declaration, path resolution, tile assembly."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.portal import resources
from pipeline.portal.resources import (
    PROJECTS_ROOT,
    Tile,
    assets_dir,
    load_manifest,
    manifest_path,
    named_file,
    project_logo,
    resolve_tiles,
)


def write_manifest(root: Path, slug: str, manifest: dict) -> None:
    directory = root / slug
    directory.mkdir(parents=True)
    (directory / "resources.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_missing_project_yields_empty_manifest(tmp_path):
    assert load_manifest("nosuch", root=tmp_path) == {}


def test_project_without_manifest_yields_empty_manifest(tmp_path):
    (tmp_path / "bare").mkdir()
    assert load_manifest("bare", root=tmp_path) == {}


def test_manifest_is_read(tmp_path):
    write_manifest(tmp_path, "demo", {"purpose": "Plan things.", "tiles": []})
    assert load_manifest("demo", root=tmp_path)["purpose"] == "Plan things."


def write_raw_manifest(root: Path, slug: str, text: str) -> None:
    directory = root / slug
    directory.mkdir(parents=True)
    (directory / "resources.json").write_text(text, encoding="utf-8")


@pytest.mark.parametrize("source", ['[]', '"a string"', '42', 'null', '{"tiles": "manual"}'])
def test_a_structurally_wrong_manifest_is_no_manifest_at_all(tmp_path, source):
    # The module contract is that a project with no *usable* manifest is not an
    # error. Valid JSON that is not an object used to satisfy load_manifest and
    # then raise AttributeError out of resolve_tiles and tile_context, so a
    # typo in one project's manifest returned 500 from both its API endpoint
    # and its access page.
    write_raw_manifest(tmp_path, "broken", source)
    manifest = load_manifest("broken", root=tmp_path)
    tiles = resolve_tiles("broken", manifest, "http://studio/", resolvers={}, context={})
    assert [t.kind for t in tiles] == ["app"]
    assert manifest_path("broken", "docs", "data-model", root=tmp_path) is None


def test_tiles_that_are_not_objects_are_ignored_not_fatal(tmp_path):
    write_raw_manifest(
        tmp_path,
        "mixed",
        '{"tiles": ["manual", 7, null, {"kind": "access", "title": "Access & support"}]}',
    )
    manifest = load_manifest("mixed", root=tmp_path)
    tiles = resolve_tiles("mixed", manifest, "http://studio/", resolvers={}, context={})
    assert [t.kind for t in tiles] == ["app", "access"]


def test_documents_that_are_not_objects_are_ignored_not_fatal(tmp_path):
    write_raw_manifest(
        tmp_path,
        "mixed2",
        '{"tiles": [{"kind": "docs", "documents": ["data-model", {"key": "k", "path": "README.md"}]}]}',
    )
    assert manifest_path("mixed2", "docs", "data-model", root=tmp_path) is None
    assert manifest_path("mixed2", "docs", "k", root=tmp_path) is not None


def test_a_second_tile_of_one_kind_is_ignored_and_logged(tmp_path, caplog):
    # Every route addresses a tile by its kind, so a second `docs` tile is
    # unreachable. First one still wins; it is the silence that was the bug.
    write_manifest(tmp_path, "twice", {"tiles": [
        {"kind": "docs", "documents": [{"key": "a", "path": "README.md"}]},
        {"kind": "docs", "documents": [{"key": "b", "path": "README.md"}]},
    ]})
    with caplog.at_level("WARNING", logger="pipeline.portal.resources"):
        assert manifest_path("twice", "docs", "a", root=tmp_path) is not None
        assert manifest_path("twice", "docs", "b", root=tmp_path) is None
    assert "only the first is reachable" in caplog.text


def test_manifest_path_reads_a_named_field(tmp_path):
    # The manual's illustrations are declared beside the manual, on the same
    # tile, and resolved through the same repository-escape guard.
    write_manifest(tmp_path, "demo", {"tiles": [
        {"kind": "manual", "path": "pipeline/portal/projects/cplan/manual.html",
         "assets": "pipeline/portal/projects/cplan/assets"},
    ]})
    assets = manifest_path("demo", "manual", root=tmp_path, field="assets")
    assert assets is not None and assets.name == "assets"
    assert manifest_path("demo", "manual", root=tmp_path, field="nosuchfield") is None


def test_a_named_field_cannot_escape_the_repository(tmp_path):
    write_manifest(tmp_path, "demo", {"tiles": [
        {"kind": "manual", "path": "x.html", "assets": "../../../etc"},
    ]})
    assert manifest_path("demo", "manual", root=tmp_path, field="assets") is None


def test_app_tile_is_always_present_and_primary(tmp_path):
    write_manifest(tmp_path, "demo", {"tiles": []})
    tiles = resolve_tiles(
        "demo", load_manifest("demo", root=tmp_path), "http://studio/", resolvers={}, context={}
    )
    assert [t.kind for t in tiles] == ["app"]
    assert tiles[0].primary is True
    assert tiles[0].href == "http://studio/"


def test_declared_tiles_follow_the_application_in_manifest_order(tmp_path):
    write_manifest(tmp_path, "demo", {"tiles": [
        {"kind": "manual", "title": "User manual"},
        {"kind": "reports", "title": "Reports & downloads"},
    ]})
    tiles = resolve_tiles(
        "demo", load_manifest("demo", root=tmp_path), "http://studio/", resolvers={}, context={}
    )
    assert [t.kind for t in tiles] == ["app", "manual", "reports"]
    assert tiles[1].href == "/project/demo/manual"
    assert all(t.primary is False for t in tiles[1:])


def test_resolver_supplies_the_status_line(tmp_path):
    write_manifest(tmp_path, "demo", {"tiles": [{"kind": "reports", "title": "Reports"}]})
    tiles = resolve_tiles(
        "demo",
        load_manifest("demo", root=tmp_path),
        "http://studio/",
        resolvers={"reports": lambda spec, context: "4 files"},
        context={},
    )
    assert tiles[1].status == "4 files"


def test_a_failing_resolver_costs_only_its_status_line(tmp_path):
    def explode(spec, context):
        raise RuntimeError("resolver is broken")

    write_manifest(tmp_path, "demo", {"tiles": [{"kind": "data", "title": "Data & freshness"}]})
    tiles = resolve_tiles(
        "demo",
        load_manifest("demo", root=tmp_path),
        "http://studio/",
        resolvers={"data": explode},
        context={},
    )
    assert [t.kind for t in tiles] == ["app", "data"]
    assert tiles[1].status is None


class _AbortingSession:
    """A session with PostgreSQL's aborted-transaction semantics.

    A statement that raises aborts the whole transaction, and every later
    statement on the same session then fails with 25P02 until someone rolls
    back. That is why swallowing a resolver's exception is only half the fix:
    the resolvers share the request's session with each other and with the page
    built after them.
    """

    def __init__(self) -> None:
        self.aborted = False
        self.rollbacks = 0

    def execute(self, *args, **kwargs):
        if self.aborted:
            raise RuntimeError("current transaction is aborted, commands ignored until end of block")
        return 41

    def rollback(self) -> None:
        self.rollbacks += 1
        self.aborted = False


def test_a_failing_database_resolver_does_not_cost_the_next_one_its_status(tmp_path):
    def explode(spec, context):
        context["session"].execute("SELECT count(*) FROM activities")
        context["session"].aborted = True  # as the failing statement itself would
        raise RuntimeError("relation does not exist")

    def counts(spec, context):
        return f"{context['session'].execute('SELECT count(*) FROM activities')} activities"

    session = _AbortingSession()
    write_manifest(tmp_path, "demo", {"tiles": [
        {"kind": "data", "title": "Data & freshness"},
        {"kind": "access", "title": "Access & support"},
    ]})
    tiles = resolve_tiles(
        "demo",
        load_manifest("demo", root=tmp_path),
        "http://studio/",
        resolvers={"data": explode, "access": counts},
        context={"session": session},
    )
    assert tiles[1].status is None
    assert tiles[2].status == "41 activities"
    assert session.rollbacks == 1


def test_a_failing_resolver_without_a_session_needs_no_rollback(tmp_path):
    def explode(spec, context):
        raise RuntimeError("no database in sight")

    write_manifest(tmp_path, "demo", {"tiles": [{"kind": "manual", "title": "User manual"}]})
    tiles = resolve_tiles(
        "demo",
        load_manifest("demo", root=tmp_path),
        "http://studio/",
        resolvers={"manual": explode},
        context={},
    )
    assert tiles[1].status is None


def test_a_tile_with_no_resolver_simply_has_no_status(tmp_path):
    write_manifest(tmp_path, "demo", {"tiles": [{"kind": "access", "title": "Access"}]})
    tiles = resolve_tiles(
        "demo", load_manifest("demo", root=tmp_path), "http://studio/", resolvers={}, context={}
    )
    assert tiles[1].status is None


def test_manifest_path_resolves_a_declared_document(tmp_path):
    write_manifest(tmp_path, "demo", {"tiles": [
        {"kind": "docs", "title": "Docs", "documents": [
            {"key": "data-model", "title": "Data model", "path": "pipeline/docs/data-model.md"},
        ]},
    ]})
    resolved = manifest_path("demo", "docs", "data-model", root=tmp_path)
    assert resolved is not None and resolved.name == "data-model.md"


def test_manifest_path_rejects_an_undeclared_key(tmp_path):
    write_manifest(tmp_path, "demo", {"tiles": [
        {"kind": "docs", "title": "Docs", "documents": [
            {"key": "data-model", "title": "Data model", "path": "pipeline/docs/data-model.md"},
        ]},
    ]})
    assert manifest_path("demo", "docs", "design-review-v2", root=tmp_path) is None


def test_manifest_path_rejects_an_escape_from_the_repository(tmp_path):
    write_manifest(tmp_path, "demo", {"tiles": [
        {"kind": "docs", "title": "Docs", "documents": [
            {"key": "escape", "title": "Escape", "path": "../../../etc/passwd"},
        ]},
    ]})
    assert manifest_path("demo", "docs", "escape", root=tmp_path) is None


def test_shipped_cplan_manifest_publishes_five_documents_and_not_the_review(tmp_path):
    manifest = load_manifest("cplan")
    docs = next(t for t in manifest["tiles"] if t["kind"] == "docs")["documents"]
    keys = {d["key"] for d in docs}
    assert len(docs) == 5
    assert "design-review-v2" not in keys
    for document in docs:
        assert (PROJECTS_ROOT.parents[2] / document["path"]).is_file()


from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy.exc import ProgrammingError

from pipeline.portal.pages import _people_section
from pipeline.portal.resolvers import RESOLVERS, humanise_age


def test_humanise_age_reads_as_a_person_would():
    now = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)
    assert humanise_age(now - timedelta(minutes=3), now=now) == "just now"
    assert humanise_age(now - timedelta(hours=2), now=now) == "2 hours ago"
    assert humanise_age(now - timedelta(days=1), now=now) == "yesterday"
    assert humanise_age(now - timedelta(days=9), now=now) == "26 Jul"
    assert humanise_age(None, now=now) is None


def test_app_resolver_states_the_role():
    assert RESOLVERS["app"]({}, {"role": "editor"}) == "Your role: Editor"


def test_manual_resolver_counts_steps_and_dates_the_file(tmp_path):
    manual = tmp_path / "manual.html"
    manual.write_text("<div class='step'></div>" * 9, encoding="utf-8")
    status = RESOLVERS["manual"]({"steps": 9}, {"manual_path": manual})
    assert status is not None and status.startswith("9 steps · updated ")


def test_manual_resolver_without_a_file_says_nothing():
    assert RESOLVERS["manual"]({"steps": 9}, {"manual_path": None}) is None


def test_docs_resolver_counts_and_names():
    spec = {"documents": [
        {"key": "a", "title": "Data model"},
        {"key": "b", "title": "Tracking IDs"},
        {"key": "c", "title": "Cross-channel matching"},
    ]}
    assert RESOLVERS["docs"](spec, {}) == "3 documents · Data model, Tracking IDs, Cross-channel matching"


def test_docs_resolver_with_no_documents_says_none_yet():
    assert RESOLVERS["docs"]({"documents": []}, {}) == "None yet"


def test_reports_resolver_counts_files_and_dates_the_newest(tmp_path):
    (tmp_path / "a.xlsx").write_bytes(b"x")
    (tmp_path / "b.xlsx").write_bytes(b"y")
    (tmp_path / "notes.txt").write_bytes(b"z")
    status = RESOLVERS["reports"]({}, {"reports_dir": tmp_path})
    assert status is not None and status.startswith("2 files · latest ")


def test_reports_resolver_on_an_empty_directory_says_none_yet(tmp_path):
    assert RESOLVERS["reports"]({}, {"reports_dir": tmp_path}) == "None yet"


def test_reports_resolver_on_a_missing_directory_says_none_yet(tmp_path):
    assert RESOLVERS["reports"]({}, {"reports_dir": tmp_path / "absent"}) == "None yet"


def test_changelog_resolver_counts_dated_entries(tmp_path):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "# What's new\n\n## 4 August 2026\n\n- one\n- two\n\n## 1 July 2026\n\n- three\n",
        encoding="utf-8",
    )
    assert RESOLVERS["changelog"]({}, {"changelog_path": changelog}) == "2 entries · latest 4 August 2026"


def test_changelog_resolver_without_a_file_says_nothing():
    assert RESOLVERS["changelog"]({}, {"changelog_path": None}) is None


class _AnsweringSession:
    """Answers `_data`'s two statements in order: the activity count, then the last run."""

    def __init__(self, activities: int, ran_at):
        self._answers = [activities, ran_at]

    def execute(self, *args, **kwargs):
        value = self._answers.pop(0)
        return SimpleNamespace(scalar_one=lambda: value, scalar_one_or_none=lambda: value)


def test_data_resolver_states_the_refresh_and_the_grouped_activity_count():
    # This line was the only status line that formatted its own number AND
    # passed it through the counting helper, so it printed the count twice:
    # "4 109 4109 activities". Nothing tested it, because it is the one
    # resolver that needs a session.
    session = _AnsweringSession(4109, datetime.now(timezone.utc) - timedelta(hours=2))
    assert RESOLVERS["data"]({}, {"session": session}) == "Refreshed 2 hours ago · 4 109 activities"


def test_data_resolver_says_never_synced_on_a_fresh_installation():
    session = _AnsweringSession(0, None)
    assert RESOLVERS["data"]({}, {"session": session}) == "Never synced · 0 activities"


def test_data_resolver_with_a_single_activity():
    session = _AnsweringSession(1, None)
    assert RESOLVERS["data"]({}, {"session": session}) == "Never synced · 1 activity"


def test_data_resolver_without_a_session_says_nothing():
    assert RESOLVERS["data"]({}, {}) is None


def test_access_resolver_states_role_and_headcount():
    assert RESOLVERS["access"]({}, {"role": "viewer", "member_count": 7}) == "You are Viewer · 7 people have access"


def test_access_resolver_survives_an_unknown_headcount():
    assert RESOLVERS["access"]({}, {"role": "viewer", "member_count": None}) == "You are Viewer"


def test_manual_resolver_with_singular_step(tmp_path):
    manual = tmp_path / "manual.html"
    manual.write_text("<div class='step'></div>", encoding="utf-8")
    status = RESOLVERS["manual"]({"steps": 1}, {"manual_path": manual})
    assert status is not None and status.startswith("1 step · updated ")


def test_docs_resolver_with_singular_document():
    spec = {"documents": [
        {"key": "a", "title": "Data model"},
    ]}
    assert RESOLVERS["docs"](spec, {}) == "1 document · Data model"


def test_reports_resolver_with_singular_file(tmp_path):
    (tmp_path / "a.xlsx").write_bytes(b"x")
    status = RESOLVERS["reports"]({}, {"reports_dir": tmp_path})
    assert status is not None and status.startswith("1 file · latest ")


def test_changelog_resolver_with_singular_entry(tmp_path):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "# What's new\n\n## 4 August 2026\n\n- one\n",
        encoding="utf-8",
    )
    assert RESOLVERS["changelog"]({}, {"changelog_path": changelog}) == "1 entry · latest 4 August 2026"


def test_access_resolver_with_singular_member():
    assert RESOLVERS["access"]({}, {"role": "viewer", "member_count": 1}) == "You are Viewer · 1 person has access"


class _FakeSqlstateOrig(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


class _FakeSession:
    """A session whose `execute` always raises SQLSTATE 42501 -- the shape a
    non-admin caller gets from `portal.users` (see `_people_section`'s own
    docstring in pipeline/portal/pages.py)."""

    def execute(self, *args, **kwargs):
        raise ProgrammingError("SELECT ...", {}, _FakeSqlstateOrig("42501"))

    def rollback(self) -> None:
        pass


def test_people_section_degraded_branch_agrees_with_a_singular_headcount():
    # This is the branch every non-admin sees (SELECT on portal.users is
    # admin-only), so it is read more, not less, than the admin table below
    # it -- and it once hard-coded "have" onto the count, reading "1 person
    # have access to this project" for a single-member project. Every other
    # test of a counted phrase in this file already used a plural quantity,
    # which is exactly how that shipped.
    row = SimpleNamespace(slug="cplan")
    heading, body = _people_section(row, _FakeSession(), member_count=1)
    assert heading == ""
    assert "1 person has access to this project." in body
    assert "have" not in body


def test_people_section_degraded_branch_still_agrees_with_a_plural_headcount():
    row = SimpleNamespace(slug="cplan")
    heading, body = _people_section(row, _FakeSession(), member_count=3)
    assert "3 people have access to this project." in body


# --- The project's picture store ---------------------------------------------


def test_assets_directory_is_declared_at_the_top_of_the_manifest(tmp_path):
    # A picture belongs to the project, not to whichever tile needed one first,
    # so the directory is declared once beside `purpose` and `logo`.
    write_manifest(tmp_path, "demo", {"assets": "pipeline/portal/projects/cplan/assets"})
    directory = assets_dir("demo", root=tmp_path)
    assert directory is not None
    assert directory.name == "assets"


def test_a_manifest_without_a_project_assets_key_still_serves_the_manual_shots(tmp_path):
    # Every manifest written before the top-level key declared its screenshots
    # on the manual tile. Those keep resolving, from exactly where they did.
    write_manifest(
        tmp_path,
        "legacy",
        {"tiles": [{"kind": "manual", "assets": "pipeline/portal/projects/cplan/assets"}]},
    )
    directory = assets_dir("legacy", root=tmp_path)
    assert directory is not None
    assert directory.name == "assets"


def test_a_project_level_assets_key_wins_over_the_manual_tiles(tmp_path):
    write_manifest(
        tmp_path,
        "both",
        {
            "assets": "pipeline/portal/projects/cplan/assets",
            "tiles": [{"kind": "manual", "assets": "pipeline/docs"}],
        },
    )
    assert assets_dir("both", root=tmp_path).name == "assets"


def test_a_project_declaring_no_assets_has_no_picture_directory(tmp_path):
    write_manifest(tmp_path, "bare", {"tiles": []})
    assert assets_dir("bare", root=tmp_path) is None


def test_an_assets_directory_outside_the_repository_is_no_directory(tmp_path):
    write_manifest(tmp_path, "escapee", {"assets": "../../../../etc"})
    assert assets_dir("escapee", root=tmp_path) is None


def logo_project(root: Path, slug: str, manifest: dict) -> Path:
    """A project whose assets directory is real, so a logo can be put in it."""
    assets = root / slug / "assets"
    assets.mkdir(parents=True)
    directory = root / slug
    (directory / "resources.json").write_text(json.dumps(manifest), encoding="utf-8")
    return assets


def test_a_declared_logo_resolves_to_the_file_in_the_assets_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(resources, "REPO_ROOT", tmp_path)
    assets = logo_project(tmp_path, "demo", {"assets": "demo/assets", "logo": "logo.png"})
    (assets / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    found = project_logo("demo", root=tmp_path)
    assert found is not None
    assert found.name == "logo.png"


def test_a_declared_logo_whose_file_has_not_landed_yet_is_simply_no_logo(tmp_path, monkeypatch):
    # Declaring the picture before it exists is the ordinary order of work, and
    # it must leave the tile reading exactly as it did before -- not raise, and
    # not point the tile at a 404.
    monkeypatch.setattr(resources, "REPO_ROOT", tmp_path)
    logo_project(tmp_path, "demo", {"assets": "demo/assets", "logo": "logo.png"})
    assert project_logo("demo", root=tmp_path) is None


def test_a_project_declaring_no_logo_has_none(tmp_path, monkeypatch):
    monkeypatch.setattr(resources, "REPO_ROOT", tmp_path)
    assets = logo_project(tmp_path, "demo", {"assets": "demo/assets"})
    (assets / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    # The file being there is not the declaration; the manifest is.
    assert project_logo("demo", root=tmp_path) is None


@pytest.mark.parametrize("name", ["../resources.json", "..", "sub/logo.png", "", 7, None])
def test_a_logo_name_cannot_reach_outside_the_assets_directory(tmp_path, monkeypatch, name):
    # The manifest names a file, not a path. `named_file` matches against the
    # directory's own listing, so a name carrying `..` or a separator has no
    # match at all rather than resolving somewhere else in the repository.
    monkeypatch.setattr(resources, "REPO_ROOT", tmp_path)
    assets = logo_project(tmp_path, "demo", {"assets": "demo/assets", "logo": name})
    (assets / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (tmp_path / "demo" / "assets" / "sub").mkdir()
    (tmp_path / "demo" / "assets" / "sub" / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    assert project_logo("demo", root=tmp_path) is None


def test_named_file_finds_only_files_directly_in_the_directory(tmp_path):
    (tmp_path / "logo.png").write_bytes(b"\x89PNG")
    (tmp_path / "nested").mkdir()
    assert named_file(tmp_path, "logo.png").name == "logo.png"
    assert named_file(tmp_path, "nested") is None
    assert named_file(tmp_path, "absent.png") is None
    assert named_file(None, "logo.png") is None
    assert named_file(tmp_path / "nosuch", "logo.png") is None


def test_the_shipped_cplan_manifest_declares_its_picture_store():
    # The real manifest, not a fixture: the assets directory it names must be
    # the one the manual's committed screenshots actually live in, or the
    # portal serves a manual with nine broken images.
    manifest = load_manifest("cplan")
    directory = assets_dir("cplan", manifest=manifest)
    assert directory is not None and directory.is_dir()
    assert (directory / "roles.png").is_file()
    assert manifest.get("logo") == "logo.png"
