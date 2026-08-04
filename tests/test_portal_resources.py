"""The project resource manifest: declaration, path resolution, tile assembly."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.portal.resources import (
    PROJECTS_ROOT,
    Tile,
    load_manifest,
    manifest_path,
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
