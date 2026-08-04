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
