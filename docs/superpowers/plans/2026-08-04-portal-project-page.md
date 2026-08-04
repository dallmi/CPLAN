# Portal Project Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clicking a project tile in the portal opens that project's own page, whose second layer of tiles covers the application, an illustrated user manual, the technical documentation, data provenance, changes, access and outputs — built so that registering a second project costs no portal code.

**Architecture:** A manifest beside each project's documents declares which tiles it has; a resolver registry keyed by tile kind fills in each tile's status line at request time; PostgreSQL keeps deciding who may see what. One new JSON endpoint feeds the page, and a small set of server-rendered page routes serve the documents. Nothing is added to `portal.projects`.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2, PostgreSQL 16 (embedded via `pgserver`), vanilla JS + CSS in `pipeline/portal/static/`, `markdown` for document rendering, Playwright for screenshot capture (development only).

## Global Constraints

- **No employer brand name anywhere in the repository** — not in code, identifiers, CSS classes, comments, docs, test data, commit messages or committed images. Use "the organisation", "internal platform", `--primary`, `--corp-*`. Verify before every commit with `git grep -Inwi $BRAND -- . ':!*.lock'`.
- **No absolute local paths in committed files.** Resolve from the project root via `Path(__file__).resolve().parents[N]`.
- **`pictures/` stays git-ignored.** Manual screenshots go to `pipeline/portal/static/docs/img/`, never to `pictures/`.
- **The portal must not gain a runtime browser dependency.** Playwright belongs in `requirements-dev.txt` only; a checkout without it must still serve the manual from committed images.
- **Design system:** corporate tokens only — white dominant, grey carries layout, red and bronze are small accents. No gradients, no tints of the brand red, no drop shadows on layout surfaces, radius `2px`, no ALL CAPS, no underlines, left-aligned. No emoji anywhere in the UI (`tests/test_portal_frontend.py` asserts this).
- **Copy is English**, sentence case, no exclamation marks.
- **New routes must be registered before `app.mount("/", StaticFiles(...))`** in `create_portal_app`. Starlette matches routes in registration order; a route added after the catch-all mount is dead.
- **Document identity travels as a manifest key, never as a path.** No user-supplied string is ever joined onto a filesystem path.

---

## File Structure

**Phase A — prototype, in the Claude Design project `e0b5307c-9db2-4773-9060-18895177240d` (not the repository):**

- `portal/project.html` — the project page: header, seven tiles
- `portal/project-access.html` — the project-scoped access view
- `portal/manual.html` — illustrated manual, campaign-guide shape
- `portal/tech-doc.html` — one rendered technical document in page chrome
- `_ds_manifest.json` — merged by hand so the cards appear in the Design System pane

**Phase B — repository:**

- `pipeline/portal/resources.py` — `Tile`, manifest loading, `resolve_tiles`. No database, no FastAPI.
- `pipeline/portal/resolvers.py` — one function per tile kind, plus the `RESOLVERS` registry.
- `pipeline/portal/documents.py` — markdown to a full HTML page in portal chrome.
- `pipeline/portal/pages.py` — the page routes, mounted by `app.py`. Keeps `app.py` from growing a second responsibility.
- `pipeline/portal/app.py` — modify: one JSON endpoint, one call to register the page routes.
- `pipeline/portal/projects/cplan/resources.json` — CPLAN's manifest.
- `pipeline/portal/projects/cplan/manual.html` — CPLAN's user manual.
- `pipeline/portal/projects/cplan/CHANGELOG.md` — CPLAN's user-facing changes.
- `pipeline/portal/static/project.html`, `project.js` — the project page shell.
- `pipeline/portal/static/styles.css`, `index.html`, `app.js` — modify: tiles link into the project page.
- `pipeline/portal/static/docs/img/` — committed screenshots.
- `pipeline/scripts/capture_manual_shots.py` — Playwright capture, development only.
- `requirements-dev.txt` — new, Playwright only.
- Tests: `tests/test_portal_resources.py`, `tests/test_portal_documents.py`, `tests/test_portal_project_page.py`, plus additions to `tests/test_portal_api.py` and `tests/test_portal_frontend.py`.

---

## Task 1: The project page prototype screen

Phase A. No repository code. The deliverable is a screen in the Claude Design project for Michael to review.

**Files:**
- Create (Design project): `portal/project.html`
- Read first: `portal/home.html`, `portal/portal.css`, `design-system/corporate-design-system.md`

**Interfaces:**
- Consumes: nothing.
- Produces: the visual contract every later task implements — tile order, the status-line wording in the table below, the header that states the caller's role.

- [ ] **Step 1: Read the existing prototype screens**

```
DesignSync get_file projectId=e0b5307c-9db2-4773-9060-18895177240d path=portal/home.html
DesignSync get_file projectId=e0b5307c-9db2-4773-9060-18895177240d path=design-system/corporate-design-system.md
```

Take from `home.html`: the `:root` token block, `.topbar`, `.brand-mark`, `.tiles`, `.btn`, `.footnote` rules, and the `PROJECTS` array. Reuse them verbatim — this screen must look like a sibling of Home, not a new design.

- [ ] **Step 2: Build the screen**

A self-contained HTML file, first line a `@dsCard` marker:

```html
<!-- @dsCard group="Portal" name="Project — Communication Planning" subtitle="Second tile layer: application, manual, technical docs, data, changes, access, outputs" width="1440" height="900" -->
```

Content, in order:

1. The same topbar as Home.
2. A breadcrumb: `Portal` (link) `›` `Communication Planning`.
3. A page header: project name as `.page-title`; the purpose sentence as `.page-subtitle`; below it one line stating the viewer's role — `You are an Editor on this project.`
4. One wide primary tile: **Open the planning studio**, status `Your role: Editor`, marked as opening in a new tab.
5. A grid of six resource tiles, in this order and with exactly this copy:

| Title | Status line in the mockup |
|---|---|
| User manual | `9 steps · updated 28 Jul` |
| Technical documentation | `5 documents · data model, tracking IDs, matching` |
| Data & freshness | `Refreshed 2 hours ago · 1,204 activities` |
| What's new | `3 entries · latest 4 Aug` |
| Access & support | `You are Editor · 7 people have access` |
| Reports & downloads | `4 files · latest 1 Aug` |

6. Below the grid, a muted `.footnote`: `Documents open in this tab. The studio opens in a new one.`

The primary tile spans the full grid width and is visually heavier than the six; the six are equal. No icons — the corporate system has no icon set and inventing one breaks the restraint agreed in round 1.

- [ ] **Step 3: Add the empty and no-access forms to the same file**

Below the main screen, in a section headed `States`, render three variants at reduced size, so the review covers them:

- a project with only the application tile (no manifest)
- the reports tile with status `None yet`
- a tile whose resolver failed: title only, no status line

- [ ] **Step 4: Self-check against the design system**

Verify by reading the file: no gradient, no `box-shadow` on a layout surface, no `border-radius` other than `2px`, no ALL CAPS, no underline, no emoji, no employer name. Red appears only as the brand mark and at most one accent.

- [ ] **Step 5: Commit nothing**

This task produces no repository change. Upload happens in Task 4.

---

## Task 2: The manual prototype screen

Phase A.

**Files:**
- Create (Design project): `portal/manual.html`
- Read first: the campaign analytics guide at `../campaign/dashboard/guide.html` (local reference, outside this repository)

**Interfaces:**
- Consumes: Task 1's page chrome and tokens.
- Produces: the manual layout that `pipeline/portal/projects/cplan/manual.html` implements in Task 10.

- [ ] **Step 1: Read the reference guide**

Read `../campaign/dashboard/guide.html` in full. Take its structure and its two print workarounds; take none of its copy and none of its brand references.

- [ ] **Step 2: Build the screen with the print workarounds intact**

```html
<!-- @dsCard group="Portal" name="User manual" subtitle="Numbered steps, one screenshot each, glossary, print-safe" width="1100" height="1400" -->
```

Required structure: cover block (kicker, title, intro, `Updated` date); numbered steps in a `2.4rem 1fr` grid with a red numbered square; one screenshot frame plus caption per step; a closing tip block; a glossary as a `dl` with a `200px 1fr` grid, zebra striping and `:target` highlighting; a top bar with `Glossary`, `Print / PDF` and `Back to the project` buttons.

Both workarounds are mandatory and must carry their explanatory comment:

```css
/* position:sticky is screen-only: Safari's real "Save as PDF" writer can
   silently emit an empty content stream when a sticky element exists
   anywhere in the DOM. */
@media screen { .top { position: sticky; top: 0; z-index: 10; } }

@media print {
  /* CSS Grid + break-inside:avoid is a known Chromium print bug — fall back
     to block flow for print only; screen keeps the grid. */
  .step { display: block; }
  .step-num { display: inline-flex; margin-bottom: 0.5rem; }
  .shot, .tip { break-inside: avoid; page-break-inside: avoid; }
}
```

- [ ] **Step 3: Use placeholder screenshots**

Real screenshots arrive in Task 9. Here each `.shot` holds a grey `1600×900` block labelled with the screen it will show, so the layout is reviewable without images.

- [ ] **Step 4: Write nine real steps**

Not lorem. The steps a new CPLAN user actually needs, drawn from `pipeline/docs/planning-process.md` and `pipeline/docs/tracking-id.md`: sign in and pick a project; read the overview; find an activity; create a single activity; create a pack; understand the tracking ID; check planning gaps; export the calendar report; know what your role allows. Each step: a short paragraph, a bullet list where it helps, one screenshot frame with a caption.

- [ ] **Step 5: Commit nothing**

Upload happens in Task 4.

---

## Task 3: The technical-document and access prototype screens

Phase A.

**Files:**
- Create (Design project): `portal/tech-doc.html`, `portal/project-access.html`

**Interfaces:**
- Consumes: Task 1's chrome.
- Produces: the chrome that `pipeline/portal/documents.py` emits in Task 7, and the access view built in Task 8.

- [ ] **Step 1: Build the technical-document screen**

```html
<!-- @dsCard group="Portal" name="Technical document" subtitle="Repository markdown in portal chrome, with a document switcher" width="1100" height="1000" -->
```

Render the real content of `pipeline/docs/data-model.md` as the body. Around it: the breadcrumb `Portal › Communication Planning › Technical documentation › Data model`; a left rail listing the five published documents with the current one marked; a `Print / PDF` button; a footnote naming the source file and its last-modified date. Style headings, tables, lists and code blocks with the corporate tokens — monospace only inside code.

- [ ] **Step 2: Build the access screen**

```html
<!-- @dsCard group="Portal" name="Project access" subtitle="Your role in plain sentences, who else has access, where to ask" width="1100" height="900" -->
```

Three sections: **Your access** — your role, and what it permits in plain sentences (reuse the `ROLE_DESC` wording already in `portal/portal.js`); **Who else has access** — a table of name, role, status; **Asking for more** — who the project administrators are, and for an admin a link into the portal-wide access matrix. A non-admin sees the third section without the link.

- [ ] **Step 3: Self-check both files**

Same checklist as Task 1 Step 4.

- [ ] **Step 4: Commit nothing**

---

## Task 4: Upload the prototype and stop for review

Phase A. This task ends at a human gate.

**Files:**
- Modify (Design project): `_ds_manifest.json`
- Upload (Design project): the four screens from Tasks 1–3

- [ ] **Step 1: Read the current manifest**

```
DesignSync get_file projectId=e0b5307c-9db2-4773-9060-18895177240d path=_ds_manifest.json
```

- [ ] **Step 2: Merge the four new cards into it by hand**

Uploading files with `@dsCard` markers is not enough for them to appear in the Design System pane, and `register_assets` reports success without touching the index. The pane reads `_ds_manifest.json` only. Merge the four new entries into the existing `cards` array and reproduce `tokens`, `globalCssPaths` and `brandFonts` exactly — a later self-check regenerates the same entries from the markers, so this does not diverge.

- [ ] **Step 3: Finalize the plan and upload**

```
DesignSync finalize_plan projectId=… writes=["portal/project.html","portal/project-access.html","portal/manual.html","portal/tech-doc.html","_ds_manifest.json"] localDir=<scratchpad dir>
DesignSync write_files planId=… files=[…localPath each…]
```

- [ ] **Step 4: Stop and ask for review**

Report the four screen names and stop. Do not begin Task 5 until Michael has reviewed them in the Design project and said to continue. Feed any change he asks for back into Tasks 1–3 and re-upload.

---

## Task 5: The manifest and the resolver registry

Phase B begins. Pure Python, no database, no FastAPI — so it is testable without PostgreSQL.

**Files:**
- Create: `pipeline/portal/resources.py`
- Create: `pipeline/portal/projects/cplan/resources.json`
- Test: `tests/test_portal_resources.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `Tile(kind: str, title: str, href: str, status: str | None = None, primary: bool = False)` — a frozen dataclass with `.as_dict() -> dict`
  - `PROJECTS_ROOT: Path` — `pipeline/portal/projects`
  - `REPO_ROOT: Path` — the repository root
  - `load_manifest(slug: str, root: Path = PROJECTS_ROOT) -> dict` — `{}` when the project has no directory or no `resources.json`
  - `manifest_path(slug: str, kind: str, key: str | None = None, root: Path = PROJECTS_ROOT) -> Path | None` — resolves a declared path to an absolute path inside the repository, `None` when undeclared or when it escapes the repository
  - `resolve_tiles(slug, manifest, project_url, resolvers, context) -> list[Tile]`

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_portal_resources.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.portal.resources'`

- [ ] **Step 3: Write the module**

```python
"""What resources a project has (declared) and what each one currently says (resolved).

Declaration is a repository fact: the manual, the documents and the changelog
are repository artefacts, so a project declares its tiles in a `resources.json`
that versions alongside them. Resolution is a runtime fact, supplied by the
callables in `pipeline/portal/resolvers.py`.

A document is addressed by its manifest key, never by a path taken from a URL.
`manifest_path` is therefore a lookup, not a join: an unknown key resolves to
nothing, and a declared path that escapes the repository resolves to nothing
either — a mistake in a manifest cannot become a file disclosure.

Kept free of FastAPI and of the database so it can be tested without either.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

PORTAL_ROOT = Path(__file__).resolve().parent
PROJECTS_ROOT = PORTAL_ROOT / "projects"
REPO_ROOT = PORTAL_ROOT.parents[1]

Resolver = Callable[[dict[str, Any], dict[str, Any]], str | None]


@dataclass(frozen=True)
class Tile:
    kind: str
    title: str
    href: str
    status: str | None = None
    primary: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "title": self.title,
            "href": self.href,
            "status": self.status,
            "primary": self.primary,
        }


def load_manifest(slug: str, root: Path = PROJECTS_ROOT) -> dict[str, Any]:
    """The project's declared resources, or `{}` when it declares none.

    A project with no manifest is not an error: it still gets its application
    tile, which is exactly the portal's behaviour before this feature existed.
    """
    path = root / slug / "resources.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.exception("Unreadable resource manifest for project %r", slug)
        return {}


def manifest_path(slug: str, kind: str, key: str | None = None, root: Path = PROJECTS_ROOT) -> Path | None:
    """Resolve a *declared* path for one tile, or one document within it."""
    for spec in load_manifest(slug, root=root).get("tiles", []):
        if spec.get("kind") != kind:
            continue
        declared = spec.get("path")
        if key is not None:
            declared = next(
                (d.get("path") for d in spec.get("documents", []) if d.get("key") == key), None
            )
        if not declared:
            return None
        resolved = (REPO_ROOT / declared).resolve()
        if not resolved.is_relative_to(REPO_ROOT):
            logger.error("Manifest for %r declares a path outside the repository: %r", slug, declared)
            return None
        return resolved
    return None


def resolve_tiles(
    slug: str,
    manifest: dict[str, Any],
    project_url: str,
    resolvers: dict[str, Resolver],
    context: dict[str, Any],
) -> list[Tile]:
    """The application tile, then every declared tile in manifest order.

    A resolver that raises costs its own status line and nothing else: a
    project page must survive a broken report directory or an unreachable
    counter, because the application tile is the thing most people came for.
    """
    tiles = [
        Tile(
            kind="app",
            title=manifest.get("app_title", "Open the application"),
            href=project_url,
            status=_status("app", resolvers, {}, context),
            primary=True,
        )
    ]
    for spec in manifest.get("tiles", []):
        kind = spec.get("kind")
        if not kind:
            continue
        tiles.append(
            Tile(
                kind=kind,
                title=spec.get("title", kind),
                href=f"/project/{slug}/{kind}",
                status=_status(kind, resolvers, spec, context),
            )
        )
    return tiles


def _status(kind: str, resolvers: dict[str, Resolver], spec: dict, context: dict) -> str | None:
    resolver = resolvers.get(kind)
    if resolver is None:
        return None
    try:
        return resolver(spec, context)
    except Exception:  # noqa: BLE001 - a status line is never worth a 500
        logger.exception("Resolver for tile kind %r failed", kind)
        return None
```

- [ ] **Step 4: Write CPLAN's manifest**

Create `pipeline/portal/projects/cplan/resources.json`. Note `design-review-v2.md` is absent by design — it is an internal review artefact.

```json
{
  "purpose": "Plan and track internal and external communication activity across the year.",
  "app_title": "Open the planning studio",
  "tiles": [
    {
      "kind": "manual",
      "title": "User manual",
      "path": "pipeline/portal/projects/cplan/manual.html",
      "steps": 9
    },
    {
      "kind": "docs",
      "title": "Technical documentation",
      "documents": [
        {"key": "data-model", "title": "Data model", "path": "pipeline/docs/data-model.md"},
        {"key": "planning-process", "title": "Planning process", "path": "pipeline/docs/planning-process.md"},
        {"key": "tracking-id", "title": "Tracking IDs", "path": "pipeline/docs/tracking-id.md"},
        {"key": "cross-channel-matching", "title": "Cross-channel matching", "path": "pipeline/docs/cross-channel-matching.md"},
        {"key": "communication-structure", "title": "Communication structure", "path": "pipeline/docs/communication-structure.md"}
      ]
    },
    {"kind": "data", "title": "Data & freshness"},
    {"kind": "changelog", "title": "What's new", "path": "pipeline/portal/projects/cplan/CHANGELOG.md"},
    {"kind": "access", "title": "Access & support"},
    {"kind": "reports", "title": "Reports & downloads", "path": "pipeline/output/reports"}
  ]
}
```

- [ ] **Step 5: Create the changelog with one real entry**

`pipeline/portal/projects/cplan/CHANGELOG.md`:

```markdown
# What's new in Communication Planning

## 4 August 2026

- Each project now has a page of its own: the manual, the technical
  documentation, data provenance, access and generated reports all sit one
  click from the project tile.
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_portal_resources.py -v`
Expected: PASS, 12 tests

- [ ] **Step 7: Commit**

```bash
git add pipeline/portal/resources.py pipeline/portal/projects tests/test_portal_resources.py
git commit -m "Let a project declare what it carries besides its application"
```

---

## Task 6: The resolvers

**Files:**
- Create: `pipeline/portal/resolvers.py`
- Test: `tests/test_portal_resources.py` (append a second class of tests)

**Interfaces:**
- Consumes: `Tile`, `manifest_path` from Task 5.
- Produces: `RESOLVERS: dict[str, Resolver]` with keys `app`, `manual`, `docs`, `data`, `changelog`, `access`, `reports`. Every resolver has the signature `(spec: dict, context: dict) -> str | None`. `context` carries `{"session": Session, "role": str, "slug": str, "member_count": int}`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_portal_resources.py`:

```python
from datetime import datetime, timedelta, timezone

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


def test_access_resolver_states_role_and_headcount():
    assert RESOLVERS["access"]({}, {"role": "viewer", "member_count": 7}) == "You are Viewer · 7 people have access"


def test_access_resolver_survives_an_unknown_headcount():
    assert RESOLVERS["access"]({}, {"role": "viewer", "member_count": None}) == "You are Viewer"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_portal_resources.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.portal.resolvers'`

- [ ] **Step 3: Write the module**

```python
"""One status line per tile kind.

Each resolver answers a single question a person would ask before clicking, and
each is deliberately dull: it reads one directory, one file or one counter. A
resolver may return `None`, meaning "nothing worth saying"; `resolve_tiles`
turns a raised exception into the same thing.

The `data` resolver is the only one that touches the database, and it does so
through the session already open for the request.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text

ROLE_LABEL = {"admin": "Admin", "editor": "Editor", "contributor": "Contributor", "viewer": "Viewer"}


def humanise_age(moment: datetime | None, now: datetime | None = None) -> str | None:
    """"2 hours ago" up to a week, an absolute date beyond it."""
    if moment is None:
        return None
    now = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    delta = now - moment
    seconds = delta.total_seconds()
    if seconds < 600:
        return "just now"
    if seconds < 5400:
        return "1 hour ago" if seconds >= 3600 else f"{int(seconds // 60)} minutes ago"
    if delta.days < 1:
        return f"{int(seconds // 3600)} hours ago"
    if delta.days == 1:
        return "yesterday"
    if delta.days < 7:
        return f"{delta.days} days ago"
    return moment.strftime("%-d %b")


def _app(spec: dict[str, Any], context: dict[str, Any]) -> str | None:
    role = ROLE_LABEL.get(context.get("role", ""))
    return f"Your role: {role}" if role else None


def _manual(spec: dict[str, Any], context: dict[str, Any]) -> str | None:
    path: Path | None = context.get("manual_path")
    if path is None or not path.is_file():
        return None
    steps = spec.get("steps") or path.read_text(encoding="utf-8").count('class="step"')
    updated = humanise_age(datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc))
    return f"{steps} steps · updated {updated}"


def _docs(spec: dict[str, Any], context: dict[str, Any]) -> str | None:
    documents = spec.get("documents", [])
    if not documents:
        return "None yet"
    titles = ", ".join(d.get("title", d.get("key", "")) for d in documents[:3])
    return f"{len(documents)} documents · {titles}"


def _data(spec: dict[str, Any], context: dict[str, Any]) -> str | None:
    session = context.get("session")
    if session is None:
        return None
    activities = session.execute(text("SELECT count(*) FROM activities")).scalar_one()
    ran_at = session.execute(text("SELECT max(ran_at) FROM sync_runs")).scalar_one_or_none()
    count = f"{activities:,} activities".replace(",", " ")
    refreshed = humanise_age(ran_at)
    return f"Refreshed {refreshed} · {count}" if refreshed else f"Never synced · {count}"


def _changelog(spec: dict[str, Any], context: dict[str, Any]) -> str | None:
    path: Path | None = context.get("changelog_path")
    if path is None or not path.is_file():
        return None
    headings = [
        line[3:].strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.startswith("## ")
    ]
    if not headings:
        return "None yet"
    return f"{len(headings)} entries · latest {headings[0]}"


def _access(spec: dict[str, Any], context: dict[str, Any]) -> str | None:
    role = ROLE_LABEL.get(context.get("role", ""))
    if role is None:
        return None
    members = context.get("member_count")
    return f"You are {role} · {members} people have access" if members else f"You are {role}"


def _reports(spec: dict[str, Any], context: dict[str, Any]) -> str | None:
    directory: Path | None = context.get("reports_dir")
    if directory is None or not directory.is_dir():
        return "None yet"
    files = sorted(directory.glob("*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return "None yet"
    newest = datetime.fromtimestamp(files[0].stat().st_mtime, tz=timezone.utc).strftime("%-d %b")
    return f"{len(files)} files · latest {newest}"


RESOLVERS = {
    "app": _app,
    "manual": _manual,
    "docs": _docs,
    "data": _data,
    "changelog": _changelog,
    "access": _access,
    "reports": _reports,
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_portal_resources.py -v`
Expected: PASS, 24 tests

- [ ] **Step 5: Commit**

```bash
git add pipeline/portal/resolvers.py tests/test_portal_resources.py
git commit -m "Give every tile one dull sentence about its current state"
```

---

## Task 7: The project detail endpoint

**Files:**
- Modify: `pipeline/portal/app.py` (add one endpoint before the static mount at line 202)
- Test: `tests/test_portal_api.py`

**Interfaces:**
- Consumes: `load_manifest`, `resolve_tiles`, `manifest_path` (Task 5); `RESOLVERS` (Task 6).
- Produces: `GET /api/portal/projects/{slug}` returning `{slug, name, purpose, role, url, tiles: [...]}`; and the helper `project_row(session, slug)` returning a row with `slug, name, url, role_prefix, role` or `None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_portal_api.py`:

```python
def test_project_detail_returns_declared_tiles(portal):
    detail = login(portal, "pa_admin").get("/api/portal/projects/cplan")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["slug"] == "cplan"
    assert body["role"] == "admin"
    kinds = [t["kind"] for t in body["tiles"]]
    assert kinds[0] == "app" and body["tiles"][0]["primary"] is True
    assert kinds[1:] == ["manual", "docs", "data", "changelog", "access", "reports"]


def test_project_detail_states_the_callers_own_role(portal):
    assert login(portal, "pa_viewer").get("/api/portal/projects/cplan").json()["role"] == "viewer"


def test_project_detail_hides_existence_from_the_unentitled(portal):
    # A project the caller holds no role on must be indistinguishable from one
    # that does not exist — otherwise the 403/404 split enumerates the registry.
    register_project(portal.state.engine, "secretproj", "Secret", "http://x/", "secretproj")
    try:
        client = login(portal, "pa_viewer")
        forbidden = client.get("/api/portal/projects/secretproj")
        missing = client.get("/api/portal/projects/nosuchproject")
        assert forbidden.status_code == missing.status_code == 404
        assert forbidden.json() == missing.json()
    finally:
        with portal.state.engine.begin() as c:
            c.exec_driver_sql("DELETE FROM portal.projects WHERE slug = 'secretproj'")


def test_project_detail_is_unauthenticated_401(portal):
    assert TestClient(portal).get("/api/portal/projects/cplan").status_code == 401


def test_a_project_whose_group_roles_were_never_created_is_404_not_500(portal):
    # `pg_has_role` on a name that is not a role raises 42704. The detail
    # endpoint must resolve role names through `to_regrole`, which yields NULL
    # instead, so a half-registered project degrades to "no access".
    register_project(portal.state.engine, "brokenproj2", "Broken", "http://x/", "brokenproj2")
    try:
        client = TestClient(portal, raise_server_exceptions=False)
        client.post("/api/login", json={"username": "pa_admin", "password": PW["pa_admin"]})
        assert client.get("/api/portal/projects/brokenproj2").status_code == 404
    finally:
        with portal.state.engine.begin() as c:
            c.exec_driver_sql("DELETE FROM portal.projects WHERE slug = 'brokenproj2'")


def test_a_second_project_needs_no_portal_code(portal, tmp_path):
    # The measure of the whole design: registering a project and dropping a
    # manifest beside it must produce a working page.
    from pipeline.portal import app as portal_app

    register_project(portal.state.engine, "secondproj", "Second Project", "http://second/", "cplan")
    projects_root = tmp_path / "projects"
    (projects_root / "secondproj").mkdir(parents=True)
    (projects_root / "secondproj" / "resources.json").write_text(
        '{"purpose": "A second tenant.", "app_title": "Open it",'
        ' "tiles": [{"kind": "access", "title": "Access & support"}]}',
        encoding="utf-8",
    )
    original = portal_app.PROJECTS_ROOT
    portal_app.PROJECTS_ROOT = projects_root
    try:
        body = login(portal, "pa_admin").get("/api/portal/projects/secondproj").json()
        assert body["purpose"] == "A second tenant."
        assert [t["kind"] for t in body["tiles"]] == ["app", "access"]
        assert body["tiles"][0]["title"] == "Open it"
    finally:
        portal_app.PROJECTS_ROOT = original
        with portal.state.engine.begin() as c:
            c.exec_driver_sql("DELETE FROM portal.projects WHERE slug = 'secondproj'")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_portal_api.py -v -k project_detail`
Expected: FAIL — 404 from the static mount, not from the endpoint

- [ ] **Step 3: Add the endpoint**

In `pipeline/portal/app.py`, add the imports near the existing ones:

```python
from pipeline.portal.resources import PROJECTS_ROOT, load_manifest, manifest_path, resolve_tiles
from pipeline.portal.resolvers import RESOLVERS
```

Then, immediately after the existing `projects()` endpoint (line 141) and well before the static mount, add:

```python
    # `to_regrole` rather than a bare name: pg_has_role raises 42704 for a name
    # that is not a role, so a project registered before its group roles were
    # created would take down the request. NULL simply falls through the CASE,
    # leaving role NULL, which this endpoint reports as "no such project".
    PROJECT_SQL = text(
        "SELECT p.slug, p.name, p.url, p.role_prefix, "
        "  CASE WHEN pg_has_role(current_user, to_regrole(p.role_prefix || '_admin'), 'member') THEN 'admin' "
        "       WHEN pg_has_role(current_user, to_regrole(p.role_prefix || '_editor'), 'member') THEN 'editor' "
        "       WHEN pg_has_role(current_user, to_regrole(p.role_prefix || '_contributor'), 'member') THEN 'contributor' "
        "       WHEN pg_has_role(current_user, to_regrole(p.role_prefix || '_viewer'), 'member') THEN 'viewer' "
        "  END AS role "
        "FROM portal.projects p WHERE p.slug = :slug"
    )

    def project_row(session: Session, slug: str):
        """The project and the caller's role on it, or None.

        None covers both "not registered" and "you hold no role on it". The
        endpoints keep them indistinguishable on the wire: a different status
        for the second case would let anyone enumerate the project registry.
        """
        row = session.execute(PROJECT_SQL, {"slug": slug}).one_or_none()
        return row if row is not None and row.role is not None else None

    def member_count(session: Session, role_prefix: str) -> int | None:
        try:
            return session.execute(
                text(
                    "SELECT count(DISTINCT m.member) FROM pg_auth_members m "
                    "JOIN pg_roles g ON g.oid = m.roleid "
                    "WHERE g.rolname LIKE :prefix"
                ),
                {"prefix": f"{role_prefix}\\_%"},
            ).scalar_one()
        except Exception:  # noqa: BLE001 - a headcount is never worth a 500
            return None

    def tile_context(session: Session, row) -> dict:
        return {
            "session": session,
            "slug": row.slug,
            "role": row.role,
            "member_count": member_count(session, row.role_prefix),
            "manual_path": manifest_path(row.slug, "manual", root=PROJECTS_ROOT),
            "changelog_path": manifest_path(row.slug, "changelog", root=PROJECTS_ROOT),
            "reports_dir": manifest_path(row.slug, "reports", root=PROJECTS_ROOT),
        }

    @app.get("/api/portal/projects/{slug}")
    def project_detail(slug: str, session: Session = Depends(db_session)):
        row = project_row(session, slug)
        if row is None:
            raise HTTPException(status_code=404, detail={"code": "not_found"})
        manifest = load_manifest(slug, root=PROJECTS_ROOT)
        tiles = resolve_tiles(
            slug, manifest, row.url, RESOLVERS, tile_context(session, row)
        )
        return {
            "slug": row.slug,
            "name": row.name,
            "purpose": manifest.get("purpose"),
            "role": row.role,
            "url": row.url,
            "tiles": [t.as_dict() for t in tiles],
        }

    app.state.project_row = project_row
    app.state.tile_context = tile_context
```

`PROJECTS_ROOT` is imported into `app.py`'s module namespace so the second-project test can point it at a temporary directory.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_portal_api.py -v`
Expected: PASS, all tests including the six new ones

- [ ] **Step 5: Commit**

```bash
git add pipeline/portal/app.py tests/test_portal_api.py
git commit -m "Answer what one project carries, without saying which ones exist"
```

---

## Task 8: Rendering a technical document

**Files:**
- Create: `pipeline/portal/documents.py`
- Modify: `pipeline/api/requirements.txt` (add `Markdown==3.7`)
- Test: `tests/test_portal_documents.py`

**Interfaces:**
- Consumes: `manifest_path`, `load_manifest` (Task 5).
- Produces: `render_document(slug, key, project_name, documents) -> str` returning a complete HTML page; `published_documents(slug) -> list[dict]` returning the manifest's `documents` list for the `docs` tile.

- [ ] **Step 1: Write the failing tests**

```python
"""Rendering repository markdown into portal chrome."""

from __future__ import annotations

import pytest

from pipeline.portal.documents import published_documents, render_document


def test_published_documents_lists_the_manifest_entries():
    keys = [d["key"] for d in published_documents("cplan")]
    assert "data-model" in keys
    assert "design-review-v2" not in keys


def test_render_produces_a_whole_page_with_the_document_in_it():
    html = render_document("cplan", "data-model", "Communication Planning", published_documents("cplan"))
    assert html.startswith("<!DOCTYPE html>")
    assert "Data model" in html
    assert "Communication Planning" in html


def test_render_lists_every_sibling_document_and_marks_the_current_one():
    html = render_document("cplan", "tracking-id", "Communication Planning", published_documents("cplan"))
    assert '/project/cplan/docs/data-model' in html
    assert 'aria-current="page"' in html


def test_render_refuses_an_undeclared_key():
    assert render_document("cplan", "design-review-v2", "Communication Planning", published_documents("cplan")) is None


def test_markdown_source_is_treated_as_markdown_not_html(tmp_path, monkeypatch):
    # These documents are markdown. A stray tag in one must render as text, so
    # that adding a document can never inject markup into the portal.
    source = tmp_path / "evil.md"
    source.write_text("# Title\n\n<script>alert(1)</script>\n", encoding="utf-8")
    monkeypatch.setattr("pipeline.portal.documents.manifest_path", lambda *a, **k: source)
    html = render_document("cplan", "evil", "Project", [{"key": "evil", "title": "Evil"}])
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_render_says_so_when_the_declared_file_is_gone(tmp_path, monkeypatch):
    monkeypatch.setattr("pipeline.portal.documents.manifest_path", lambda *a, **k: tmp_path / "absent.md")
    html = render_document("cplan", "data-model", "Project", [{"key": "data-model", "title": "Data model"}])
    assert html is not None and "not available" in html


def test_rendered_page_carries_no_sticky_positioning():
    # The document pages are printable; Safari's PDF writer can emit an empty
    # content stream when `position: sticky` exists anywhere in the DOM.
    html = render_document("cplan", "data-model", "Communication Planning", published_documents("cplan"))
    assert "position: sticky" not in html or "@media screen" in html
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_portal_documents.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.portal.documents'`

- [ ] **Step 3: Install the dependency**

Add `Markdown==3.7` to `pipeline/api/requirements.txt`, then:

Run: `PYTHONPATH= .venv/bin/python -m pip install Markdown==3.7`

- [ ] **Step 4: Write the module**

```python
"""Repository markdown, rendered into the portal's chrome on request.

Rendered rather than rewritten: the technical documentation already exists in
`pipeline/docs/`, is already maintained there, and a hand-copied second version
would be wrong within a month. Rendering happens per request and is cheap — the
largest of these documents is under 200 lines.

The source is escaped before conversion. These files are markdown, not HTML, so
nothing is lost, and a document added later cannot inject markup into a portal
page.
"""

from __future__ import annotations

import html as html_escape
from typing import Any

import markdown

from pipeline.portal.resources import load_manifest, manifest_path

_EXTENSIONS = ["tables", "fenced_code", "sane_lists"]


def published_documents(slug: str) -> list[dict[str, Any]]:
    """The documents this project publishes — an allow-list, not a directory scan."""
    for spec in load_manifest(slug).get("tiles", []):
        if spec.get("kind") == "docs":
            return spec.get("documents", [])
    return []


def render_document(
    slug: str, key: str, project_name: str, documents: list[dict[str, Any]]
) -> str | None:
    """A complete HTML page for one declared document, or None if undeclared."""
    entry = next((d for d in documents if d.get("key") == key), None)
    if entry is None:
        return None
    path = manifest_path(slug, "docs", key)
    if path is None or not path.is_file():
        body = "<p class='missing'>This document is not available in this installation.</p>"
        source_note = ""
    else:
        source = path.read_text(encoding="utf-8")
        body = markdown.markdown(html_escape.escape(source), extensions=_EXTENSIONS)
        source_note = f"Source: <code>{html_escape.escape(str(path.relative_to(path.parents[2])))}</code>"
    return _PAGE.format(
        title=html_escape.escape(entry.get("title", key)),
        project=html_escape.escape(project_name),
        slug=html_escape.escape(slug),
        rail=_rail(slug, key, documents),
        body=body,
        source_note=source_note,
    )


def _rail(slug: str, current: str, documents: list[dict[str, Any]]) -> str:
    items = []
    for document in documents:
        key = html_escape.escape(document.get("key", ""))
        title = html_escape.escape(document.get("title", key))
        current_attr = ' aria-current="page"' if document.get("key") == current else ""
        items.append(f'<li><a href="/project/{slug}/docs/{key}"{current_attr}>{title}</a></li>')
    return "\n".join(items)


_PAGE = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — {project}</title>
<link rel="stylesheet" href="/document.css">
</head><body>
<header class="top no-print">
  <a class="brand" href="/project/{slug}"><span class="brand-mark"></span>{project}</a>
  <button class="btn" onclick="window.print()">Print / PDF</button>
</header>
<nav class="crumb no-print"><a href="/">Portal</a> › <a href="/project/{slug}">{project}</a> › {title}</nav>
<main class="doc-layout">
  <aside class="doc-rail no-print"><ul>{rail}</ul></aside>
  <article class="doc"><h1>{title}</h1>{body}<p class="footnote">{source_note}</p></article>
</main>
</body></html>
"""
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_portal_documents.py -v`
Expected: PASS, 7 tests

- [ ] **Step 6: Commit**

```bash
git add pipeline/portal/documents.py tests/test_portal_documents.py pipeline/api/requirements.txt
git commit -m "Publish the documentation the repository already keeps"
```

---

## Task 9: The page routes and the project page

**Files:**
- Create: `pipeline/portal/pages.py`
- Create: `pipeline/portal/static/project.html`, `pipeline/portal/static/project.js`, `pipeline/portal/static/document.css`
- Modify: `pipeline/portal/app.py` (call `register_pages(app, …)` before the static mount)
- Modify: `pipeline/portal/static/app.js` (tiles link to `/project/<slug>`), `pipeline/portal/static/styles.css`
- Test: `tests/test_portal_project_page.py`, `tests/test_portal_frontend.py`

**Interfaces:**
- Consumes: `project_row`, `tile_context` (Task 7); `render_document`, `published_documents` (Task 8).
- Produces: routes `GET /project/{slug}`, `/project/{slug}/manual`, `/project/{slug}/docs`, `/project/{slug}/docs/{key}`, `/project/{slug}/access`; and `register_pages(app, db_session, current_user)`.

- [ ] **Step 1: Write the failing tests**

```python
"""Project page routes: gating, document serving, and the static shell."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.test_portal_api import PW, login, portal  # noqa: F401 - fixture reuse

STATIC = Path(__file__).resolve().parents[1] / "pipeline" / "portal" / "static"


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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_portal_project_page.py -v`
Expected: FAIL — the static mount returns 404 for `/project/cplan`

- [ ] **Step 3: Write the page routes**

```python
"""Server-rendered pages hanging off a project.

Separate from `app.py` because they are a different job from the JSON API: they
serve HTML, they redirect rather than 401 when a browser arrives without a
session, and they will grow as document kinds are added.

Registered before the catch-all StaticFiles mount — Starlette matches in
registration order, so a route added after it never runs.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from pipeline.portal.documents import published_documents, render_document
from pipeline.portal.resolvers import ROLE_LABEL
from pipeline.portal.resources import PROJECTS_ROOT, manifest_path

STATIC = Path(__file__).resolve().parent / "static"

ROLE_DESC = {
    "admin": "Everything an editor can do, plus deleting activities and managing access.",
    "editor": "Create activities and edit any activity, including other people's.",
    "contributor": "Create activities and edit only the ones they created.",
    "viewer": "Read everything. Change nothing.",
}


def register_pages(app: FastAPI, db_session, project_row, tile_context) -> None:
    def require_project(session: Session, slug: str):
        row = project_row(session, slug)
        if row is None:
            raise HTTPException(status_code=404, detail={"code": "not_found"})
        return row

    @app.get("/project/{slug}", response_class=HTMLResponse)
    def project_page(slug: str, session: Session = Depends(db_session)):
        require_project(session, slug)
        return FileResponse(STATIC / "project.html")

    @app.get("/project/{slug}/manual")
    def project_manual(slug: str, session: Session = Depends(db_session)):
        require_project(session, slug)
        path = manifest_path(slug, "manual", root=PROJECTS_ROOT)
        if path is None or not path.is_file():
            raise HTTPException(status_code=404, detail={"code": "not_found"})
        return FileResponse(path)

    @app.get("/project/{slug}/docs")
    def project_docs_index(slug: str, session: Session = Depends(db_session)):
        require_project(session, slug)
        documents = published_documents(slug)
        if not documents:
            raise HTTPException(status_code=404, detail={"code": "not_found"})
        return RedirectResponse(f"/project/{slug}/docs/{documents[0]['key']}")

    @app.get("/project/{slug}/docs/{key}", response_class=HTMLResponse)
    def project_document(slug: str, key: str, session: Session = Depends(db_session)):
        row = require_project(session, slug)
        page = render_document(slug, key, row.name, published_documents(slug))
        if page is None:
            raise HTTPException(status_code=404, detail={"code": "not_found"})
        return HTMLResponse(page)

    @app.get("/project/{slug}/access", response_class=HTMLResponse)
    def project_access(slug: str, session: Session = Depends(db_session)):
        row = require_project(session, slug)
        return HTMLResponse(_access_page(row, tile_context(session, row)))
```

`_access_page` renders the three sections designed in Task 3 — your access (`ROLE_LABEL[row.role]` and `ROLE_DESC[row.role]`), who else has access (from `portal.users` when the caller is an admin, otherwise only the headcount from `context["member_count"]`), and who to ask. Write it in the same `str.format` style as `documents._PAGE`, sharing `/document.css`.

Then in `pipeline/portal/app.py`, immediately before the static mount:

```python
    from pipeline.portal.pages import register_pages

    register_pages(app, db_session, project_row, tile_context)
```

- [ ] **Step 4: Write the project page shell**

`static/project.html` is a small shell — a topbar, a breadcrumb, `<h1 id="project-name">`, `<p id="project-purpose">`, `<p id="project-role">`, `<div id="project-tiles">` — filled by `project.js`:

```javascript
// The project page: one fetch, one render. The slug comes from the path, so
// the page is linkable and the browser's back button works.
const slug = location.pathname.split('/')[2];

async function load() {
  const response = await fetch(`/api/portal/projects/${encodeURIComponent(slug)}`);
  if (response.status === 401) { location.href = '/'; return; }
  if (!response.ok) { showMissing(); return; }
  render(await response.json());
}

function render(project) {
  document.getElementById('project-name').textContent = project.name;
  document.getElementById('project-purpose').textContent = project.purpose || '';
  document.getElementById('project-role').textContent =
    project.role ? `You are ${label(project.role)} on this project.` : '';
  document.getElementById('project-tiles').innerHTML = project.tiles.map(tile => {
    const external = tile.kind === 'app' ? ' target="_blank" rel="noopener"' : '';
    const status = tile.status ? `<div class="tile-status">${escapeHtml(tile.status)}</div>` : '';
    return `<a class="tile${tile.primary ? ' tile-primary' : ''}" href="${escapeHtml(tile.href)}"${external}>`
      + `<div class="tile-name">${escapeHtml(tile.title)}</div>${status}</a>`;
  }).join('');
}
```

Reuse `escapeHtml` and `label` from the existing `app.js` pattern.

- [ ] **Step 5: Point the home tiles at the project page**

In `static/app.js` line 51, replace the tile template: `href` becomes `/project/${escapeHtml(p.slug)}`, no `target="_blank"`, and the `tile-url` div is dropped — the URL belongs on the project page now.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_portal_project_page.py tests/test_portal_frontend.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add pipeline/portal/pages.py pipeline/portal/static pipeline/portal/app.py tests/test_portal_project_page.py tests/test_portal_frontend.py
git commit -m "Open a project instead of its application"
```

---

## Task 10: Screenshot capture

**Files:**
- Create: `pipeline/scripts/capture_manual_shots.py`
- Create: `requirements-dev.txt`
- Create: `pipeline/portal/static/docs/img/*.png` (generated, committed)
- Test: `tests/test_portal_project_page.py` (append)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `SHOTS: list[Shot]` where `Shot(key: str, path: str, wait_for: str)`, and a `main()` writing `<key>.png` per entry.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_portal_project_page.py`:

```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_portal_project_page.py -v -k capture`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the capture script**

```python
"""Capture the manual's screenshots from the demo dataset.

Development tooling, not part of the portal: Playwright lives in
requirements-dev.txt and a checkout without it still serves the manual from the
committed PNGs. Run it after a studio UI change and the manual updates itself.

The images are safe to commit by construction rather than by inspection. They
are captured against pipeline/data/cplan-demo.sqlite3 with the repository's own
synthetic content, and the studio interface carries no organisation name, so
nothing identifying can reach the frames.

Usage:
    PYTHONPATH=. python pipeline/scripts/capture_manual_shots.py
"""

from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "pipeline" / "portal" / "static" / "docs" / "img"
DEMO_DB = ROOT / "pipeline" / "data" / "cplan-demo.sqlite3"
BASE = "http://127.0.0.1:8788"
VIEWPORT = {"width": 1600, "height": 900}


@dataclass(frozen=True)
class Shot:
    key: str
    path: str
    wait_for: str


SHOTS = [
    Shot("sign-in", "/", "#login-form"),
    Shot("overview", "/#overview", "#overview-cards"),
    Shot("activities", "/#activities", "#activity-table"),
    Shot("activity-detail", "/#activities", "#detail-drawer"),
    Shot("create-single", "/#activities", "#create-modal"),
    Shot("create-pack", "/#activities", "#pack-modal"),
    Shot("tracking-id", "/#activities", "#tracking-id-field"),
    Shot("health", "/#health", "#health-panel"),
    Shot("report", "/#report", "#report-panel"),
]


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright is not installed. pip install -r requirements-dev.txt", file=sys.stderr)
        print("then: python -m playwright install chromium", file=sys.stderr)
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    server = subprocess.Popen(
        [sys.executable, str(ROOT / "pipeline" / "scripts" / "start_cplan.py"), "--port", "8788"],
        env={"CPLAN_DATABASE_URL": f"sqlite:///{DEMO_DB}"},
        cwd=ROOT,
    )
    try:
        time.sleep(5)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport=VIEWPORT, device_scale_factor=2)
            for shot in SHOTS:
                page.goto(f"{BASE}{shot.path}")
                page.wait_for_selector(shot.wait_for, timeout=15_000)
                page.screenshot(path=str(OUT / f"{shot.key}.png"))
                print(f"captured {shot.key}.png")
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=10)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Adjust each `Shot.wait_for` to the selector that actually exists in `pipeline/studio/index.html` — read it before running, and correct the placeholders above to real IDs. Some shots need a click first (opening the create modal, opening the drawer); add the needed `page.click(...)` per shot as a `steps` field on `Shot` if more than two need it.

- [ ] **Step 4: Create the dev requirements file**

`requirements-dev.txt`:

```
# Development only. The portal must never depend on a browser at runtime.
playwright==1.49.0
```

- [ ] **Step 5: Run the capture**

```bash
PYTHONPATH= .venv/bin/python -m pip install -r requirements-dev.txt
PYTHONPATH= .venv/bin/python -m playwright install chromium
PYTHONPATH=. .venv/bin/python pipeline/scripts/capture_manual_shots.py
```
Expected: nine PNGs in `pipeline/portal/static/docs/img/`

- [ ] **Step 6: Inspect every captured image before committing**

Open each PNG. Confirm: no organisation name, no real person's name, no production identifier, no local filesystem path in a visible field. Any hit means the demo dataset needs fixing, not the screenshot cropping.

- [ ] **Step 7: Commit**

```bash
git add pipeline/scripts/capture_manual_shots.py requirements-dev.txt pipeline/portal/static/docs/img
git commit -m "Capture the manual's pictures from the demo data, repeatably"
```

---

## Task 11: The manual itself

**Files:**
- Create: `pipeline/portal/projects/cplan/manual.html`
- Test: `tests/test_portal_project_page.py` (the screenshot test from Task 10 now runs instead of skipping)

**Interfaces:**
- Consumes: the layout approved in Task 2; the screenshots from Task 10.
- Produces: the file `resources.json` already declares.

- [ ] **Step 1: Port the approved prototype**

Take `portal/manual.html` from the Design project as reviewed, replace the grey placeholder blocks with `<img src="/docs/img/<key>.png" alt="…">`, and set the `Updated` date on the cover.

- [ ] **Step 2: Write the nine steps against the real product**

Verify each step against the running studio, not against memory. Where the prototype's copy describes something the studio does not do, the copy is wrong — fix the copy, and note the discrepancy in the completion report rather than silently changing scope.

- [ ] **Step 3: Write the glossary**

Terms from `pipeline/docs/`: activity, pack, tracking ID, channel, audience, planning gap, cross-channel match, snapshot, sync run. Each with a one-sentence definition and, where one exists, the field name in monospace.

- [ ] **Step 4: Check the print path in a real browser**

Open `/project/cplan/manual`, print to PDF in Chrome and in Safari. Expected: a complete PDF in both, steps not split across pages mid-screenshot, the top bar absent.

- [ ] **Step 5: Run the tests**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/ -v -k portal`
Expected: PASS, including the screenshot-existence test that skipped in Task 10

- [ ] **Step 6: Commit**

```bash
git add pipeline/portal/projects/cplan/manual.html
git commit -m "Explain the studio in nine steps and a glossary"
```

---

## Task 12: Documentation and the brand check

**Files:**
- Modify: `README.md`, `pipeline/api/README.md`, `docs/CPLAN_KNOWLEDGE_BASE.md`

**Interfaces:**
- Consumes: everything above.
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Document the portal's second layer**

In `pipeline/api/README.md` under `#### Portal`, describe: the project page, the manifest at `pipeline/portal/projects/<slug>/resources.json`, the tile kinds and what each resolver reads, and the four steps to register a second project.

- [ ] **Step 2: Document the capture script**

In `README.md`, next to the existing pipeline commands: what `capture_manual_shots.py` does, that Playwright is dev-only, and that the images are committed.

- [ ] **Step 3: Run the whole suite**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/ -q`
Expected: PASS, no new failures against the pre-change baseline

- [ ] **Step 4: Run the brand check over tree and history**

```bash
git grep -Inwi $BRAND -- . ':!*.lock' ':!pnpm-lock.yaml'
git log --oneline -20 | grep -iw $BRAND
grep -rn "/Users/" --include=*.py --include=*.md --include=*.html --include=*.json pipeline/ docs/ README.md
```
Expected: no output from any of the three.

- [ ] **Step 5: Commit**

```bash
git add README.md pipeline/api/README.md docs/CPLAN_KNOWLEDGE_BASE.md
git commit -m "Write down how a second project gets a page"
```

---

## Self-Review

**Spec coverage.** Project page rather than expanding tile → Tasks 1, 9. Seven tiles with status lines → Tasks 1, 5, 6. Declaration/resolution/authorisation split → Tasks 5, 6, 7. Access section and page header role → Tasks 3, 9. Manual hand-authored → Tasks 2, 11. Technical docs rendered from existing markdown → Task 8. `design-review-v2.md` unpublishable → tested in Tasks 5, 8, 9. Screenshots auto-captured, brand-safe by construction, Playwright dev-only → Task 10. Adding a second project costs no portal code → tested in Task 7. Identical 404 for missing and forbidden → Task 7. Empty and failure states → Tasks 1, 5, 6. Interface shape → Task 7. Testing section → covered across Tasks 5–11.

**Known gap, deliberate:** the spec's "entries since your last visit" for the What's new tile needs a per-user last-seen timestamp, which no table holds. Task 6 resolves it as total entries plus the latest date instead. Adding a `portal.last_seen` table is a separate change and is not in this plan; the prototype copy in Task 1 should say `3 entries · latest 4 Aug` rather than `3 changes since your last visit`.

**Type consistency.** `Tile`, `Resolver`, `load_manifest`, `manifest_path`, `resolve_tiles`, `RESOLVERS`, `ROLE_LABEL`, `ROLE_DESC`, `project_row`, `tile_context`, `register_pages`, `published_documents`, `render_document`, `Shot`, `SHOTS` — each defined once and referenced with the same name and signature throughout. Resolver context keys `session`, `slug`, `role`, `member_count`, `manual_path`, `changelog_path`, `reports_dir` are produced by `tile_context` in Task 7 and consumed by the resolvers in Task 6.
