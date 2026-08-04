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
    "No usable manifest" includes a *structurally* wrong one — valid JSON that
    is not an object — not only an unreadable or unparseable file. Without that
    last check a `resources.json` holding `[]` reached `resolve_tiles` and
    `tile_context` as a list and raised AttributeError out of both, turning a
    typo in one project's manifest into a 500 on its whole page.
    """
    path = root / slug / "resources.json"
    if not path.is_file():
        return {}
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.exception("Unreadable resource manifest for project %r", slug)
        return {}
    if not isinstance(manifest, dict):
        logger.error(
            "Resource manifest for project %r is a %s, not an object; ignoring it",
            slug,
            type(manifest).__name__,
        )
        return {}
    return manifest


def tile_specs(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """The manifest's declared tiles — every entry that is actually an object.

    The single place the `tiles` key is read, so one hand-written manifest
    cannot break some readers and not others: a `tiles` that is not a list, or
    a list holding strings, degrades to "this project declares no tiles"
    rather than raising out of whichever caller reached it first.
    """
    tiles = manifest.get("tiles")
    if tiles is None:
        return []
    if not isinstance(tiles, list):
        logger.error("Manifest declares `tiles` as a %s, not a list", type(tiles).__name__)
        return []
    specs = [spec for spec in tiles if isinstance(spec, dict)]
    if len(specs) != len(tiles):
        logger.error("Manifest declares %d tile(s) that are not objects; ignoring them", len(tiles) - len(specs))
    return specs


def tile_documents(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """The documents declared on one tile — same shape guard as `tile_specs`."""
    documents = spec.get("documents")
    if not isinstance(documents, list):
        return []
    return [document for document in documents if isinstance(document, dict)]


def manifest_path(
    slug: str,
    kind: str,
    key: str | None = None,
    root: Path = PROJECTS_ROOT,
    manifest: dict[str, Any] | None = None,
    field: str = "path",
) -> Path | None:
    """Resolve a *declared* path for one tile, or one document within it.

    Pass an already-loaded `manifest` when the caller has one (e.g. a request
    handler that loads it once for several lookups) to skip the redundant
    read-and-parse; omitted, it is loaded fresh as before.

    `field` names which key on the tile carries the path — `path` for the tile's
    own target, `assets` for the directory of images a document is served with.
    """
    if manifest is None:
        manifest = load_manifest(slug, root=root)
    specs = [spec for spec in tile_specs(manifest) if spec.get("kind") == kind]
    if not specs:
        return None
    if len(specs) > 1:
        # First one wins, as it always has; it is the silence that was the
        # problem. A second tile of the same kind is unreachable — every route
        # addresses a tile by its kind — so a manifest that declares one is
        # wrong, and says so in the log rather than losing a document quietly.
        logger.warning(
            "Project %r declares %d %r tiles; only the first is reachable, the rest are ignored",
            slug,
            len(specs),
            kind,
        )
    spec = specs[0]
    declared = spec.get(field)
    if key is not None:
        declared = next(
            (d.get("path") for d in tile_documents(spec) if d.get("key") == key), None
        )
    if not declared or not isinstance(declared, str):
        return None
    resolved = (REPO_ROOT / declared).resolve()
    if not resolved.is_relative_to(REPO_ROOT):
        logger.error("Manifest for %r declares a path outside the repository: %r", slug, declared)
        return None
    return resolved


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
    for spec in tile_specs(manifest):
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
        _rollback(context)
        return None


def _rollback(context: dict) -> None:
    """Undo a failed resolver's effect on the session it shares with the rest of the page.

    Swallowing the exception is only half the contract. The database-backed
    resolvers run on the request's own session, and PostgreSQL aborts the whole
    transaction on any error: without a rollback here, every later statement on
    that session fails with 25P02, so one broken resolver costs every tile after
    it its status line — and the access page its roster. `member_count` in
    pipeline/portal/app.py already rolls back for exactly this reason; this is
    the same fix for the generic path.

    Duck-typed rather than typed against `Session`, because this module is
    deliberately free of both FastAPI and SQLAlchemy: a context without a
    session (every file-backed resolver's) simply has nothing to undo.
    """
    session = context.get("session")
    if session is None:
        return
    try:
        session.rollback()
    except Exception:  # noqa: BLE001 - the page still renders without its status lines
        logger.exception("Rolling back after a failed resolver did not succeed")
