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
