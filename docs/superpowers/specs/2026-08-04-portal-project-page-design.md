# The portal as a multi-project shell: project pages with resource tiles

**Date:** 2026-08-04
**Status:** draft

## Problem

The portal's landing page lists projects as tiles, and each tile is a link
straight into the application. That makes the portal a bookmark list. Everything
else a project carries — how to use it, how it is built, where its data comes
from, what changed, who may see it, what it produced — has no place in the
interface at all. It lives in the repository as markdown, or nowhere.

Two consequences. A new user gets an application and no way in. And a project is
represented by exactly one artefact, its web application, which forecloses the
actual goal: a portal holding several projects, each of which is more than a URL.

## Goal

Clicking a project tile opens that project's own page, showing its resources as
a second layer of tiles — the application, an illustrated user manual, technical
documentation, data provenance, changes, access, outputs. Adding a second
project later must be a registration, not a code change.

## What exists today

Verified by reading, and the design leans on all of it:

**The portal is a separate service.** `pipeline/portal/app.py` serves a FastAPI
app on `127.0.0.1:8781` with three static files — `index.html`, `app.js`,
`styles.css` — independently of the studio on `8780`. It refuses to start
without `CPLAN_AUTH_SECRET` and a PostgreSQL backend.

**Projects are already a registry.** `portal.projects (slug, name, url,
role_prefix)` in `pipeline/api/setup_portal.py` is a table, seeded idempotently,
with `register_project()` already written and exported. `GET
/api/portal/projects` joins it against the caller's role memberships, so a user
sees only their projects. The multi-project story is half-built; nothing about
it is CPLAN-specific except the single seeded row.

**Roles exist and are enforced in the database.** viewer / contributor / editor
/ admin, as PostgreSQL roles with RLS, per project via `role_prefix`.

**The technical documentation is already written.** `pipeline/docs/` holds
`data-model.md`, `tracking-id.md`, `cross-channel-matching.md`,
`planning-process.md` and `communication-structure.md` — plus
`design-review-v2.md`, which is an internal review artefact and must not be
published. The documentation tile therefore needs an explicit publication list,
not a directory scan.

**A demo database ships with the repository.** `pipeline/data/cplan-demo.sqlite3`.

**A reference manual exists in a neighbouring project.** The campaign analytics
guide is a single self-contained HTML file: numbered steps in a two-column grid,
one screenshot per step with a caption, a linked glossary, a print button, and
print CSS that works around two named browser bugs — Safari emitting an empty
content stream when `position: sticky` appears anywhere in the DOM, and Chromium
mishandling `break-inside: avoid` inside CSS Grid. That file is the template for
the manual, and those two workarounds are inherited deliberately.

**The redesign prototype is the review channel.** The Claude Design project
"CPLAN Studio" holds `portal/home.html` and eight sibling screens. Round 1
settled the visual direction: restraint inside the corporate design system,
white dominant, red as a small accent, no modern-SaaS vocabulary. Tiles there
already carry purpose, the viewer's role and a no-access state; the raw URL is
gone. This design continues that language rather than inventing one.

## Design

### A project page, not an expanding tile

The literal reading of the request — more tiles *inside* the project tile — is
an expansion in place on the home screen. Rejected: seven resources do not fit
inside a tile without becoming a menu, and nothing inside an expansion can be
linked, bookmarked or sent to a colleague.

Instead each project gets a page at `/project/<slug>`, reached by clicking its
tile, with a breadcrumb back to Home. The tile grid carries over, so it still
reads as going *into* the project. Every resource beneath it gets a stable URL
of its own.

Also rejected: one portal-wide "Documentation" section listing every document
across all projects. It is less work and it dissolves exactly the per-project
framing this design exists to create.

### Tiles carry state

A tile showing only a title is a link with extra padding. Each resource tile
carries one status line, and that line is the reason the page is worth opening:

| Tile | Kind | Status line |
|---|---|---|
| Open the planning studio | `app` | your role on this project |
| User manual | `manual` | step count, last updated |
| Technical documentation | `docs` | document count, subject list |
| Data & freshness | `data` | last refresh, activity count |
| What's new | `changelog` | entries since your last visit |
| Access & support | `access` | your role, number of people with access |
| Reports & downloads | `reports` | file count, newest file date |

Layout is one wide primary tile for the application, then the six resource tiles
in a grid. Not seven equal squares — the application is what most people came
for, and the restraint agreed in round 1 rules out an app-launcher wall.

### Declaration and resolution are separate

Which tiles a project has is a repository fact: the resources *are* repository
artefacts and must version with the documents they point at. Each project gets a
`resources.json` declaring its tiles — kind, title, target, order, and for
`docs`, the explicit list of markdown files to publish.

What a tile's status line says is a runtime fact. Each kind has a resolver:
`data` queries the last refresh and row count, `reports` lists the report
directory, `changelog` reads the project's changelog, `access` reads the
caller's own role and the project's member count, `manual` and `docs` read file
mtimes and counts. A resolver that fails or finds nothing yields a tile without
a status line — never a broken page.

Who may see a tile stays in PostgreSQL, unchanged.

`portal.projects` gains no columns.

### The access section

Access is the question people arrive with, so the project page answers the
smallest part of it without a click: the page header states the caller's role on
this project. The tile then leads to the full project-scoped view — what that
role permits in plain sentences, and who else has access. For an admin it also
links into the portal-wide access matrix; for everyone else it names who to ask
for more. The role descriptions are the ones already written in the prototype.

### Documents

**The user manual** is hand-authored HTML per project, in the shape of the
campaign guide: numbered steps, a screenshot per step, captions, a glossary with
linked terms, a print/PDF button, print-safe CSS including the two browser
workarounds named above. Hand-authored because the illustrated step layout is
the thing that makes it usable, and no renderer produces it.

**The technical documentation** is rendered from the existing markdown at
request time, wrapped in the same page chrome, cached by file mtime. Rendered
rather than rewritten so the published documentation cannot drift from the
documentation the repository already maintains. The manifest lists which files
are published, so internal notes stay internal.

This costs one small pure-Python markdown dependency in the portal service.

### Screenshots

A capture script drives the studio with Playwright against
`pipeline/data/cplan-demo.sqlite3` and writes PNGs into a committed asset
directory under the portal's static tree. Re-running it after a UI change
refreshes every image in the manual.

The brand guarantee is structural rather than a scan: the demo dataset and the
studio interface contain no employer name by construction — the repository
already requires generic organisation terminology throughout — so anything
captured from them is safe to commit. The committed assets live under the portal
static tree, not under `pictures/`, which stays ignored.

Playwright is a development dependency only. It goes in a separate dev
requirements file, never in `pipeline/api/requirements.txt`; the portal must not
gain a browser dependency at runtime, and a checkout without Playwright must
still serve the manual from the committed images.

### Adding a second project

The test of this design is what a second project costs. Registering campaign
analytics as a portal project should be:

1. `register_project(engine, slug, name, url, role_prefix)` — already written
2. create the PostgreSQL roles for the new `role_prefix` — already scripted
3. drop a `resources.json` next to its documents
4. write its manual, or omit the `manual` tile

No portal code, no new endpoint, no new template. If any step requires touching
`pipeline/portal/`, the resolver registry is wrong and the design has failed.
This is worth an explicit test: register a second, fictitious project against
the test database and assert its page renders with its declared tiles.

## Interface

`GET /api/portal/projects/{slug}` returns the project and its resolved tiles,
filtered by the caller's role, `404` when the project does not exist or the
caller has no access — the same response for both, so the endpoint does not
disclose which projects exist.

```json
{
  "slug": "cplan",
  "name": "Communication Planning",
  "purpose": "…",
  "role": "editor",
  "url": "http://127.0.0.1:8780/",
  "tiles": [
    { "kind": "app",    "title": "Open the planning studio", "href": "…", "status": "Your role: Editor", "primary": true },
    { "kind": "manual", "title": "User manual",              "href": "…", "status": "9 steps · updated 28 Jul" }
  ]
}
```

Documents are served as pages, not JSON: `/project/{slug}/manual`,
`/project/{slug}/docs/{name}`, `/project/{slug}/access`, and so on, each gated
by the same role check.

## States

Every tile needs its empty and failed forms, because most of them read
something that may be absent in a fresh checkout:

- no reports generated yet — tile present, status line reads "none yet"
- no changelog — tile omitted entirely by the manifest
- no manual written for this project — tile omitted by the manifest
- resolver raises — tile renders without a status line, error logged
- project has no `resources.json` — page renders with only the application tile
- caller lacks access — `404`, identical to a missing project

## Testing

Following the repository's existing pattern — `tests/test_portal_api.py` for
endpoints, `tests/test_portal_frontend.py` for static markers:

- the detail endpoint returns declared tiles, and filters by role
- an unknown slug and a forbidden slug produce identical `404` responses
- each resolver against a fixture: populated, empty, and raising
- `design-review-v2.md` is not reachable through the documentation route
- the second-project test described above
- markdown rendering escapes HTML in source documents
- static markers for the project page and manual, including the print CSS and
  the absence of `position: sticky` in the printable documents
- the manual references only images that exist in the committed asset directory

## Out of scope

Editing `resources.json` from the browser. Search across documents. Per-project
theming. Versioned or translated manuals. Wiring campaign analytics in as a real
second project — this design only guarantees it is cheap.

## Order of work

1. **Prototype** in the Claude Design project: the project page, the manual, one
   rendered technical document, the access view. Reviewed there before any
   repository code is written.
2. **Repository**: detail endpoint and resolver registry, manifest for CPLAN,
   markdown rendering, the capture script and its screenshots, the manual's
   written content, tests.
