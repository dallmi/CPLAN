"""Server-rendered pages hanging off a project.

Separate from `app.py` because they are a different job from the JSON API: they
serve HTML, and they will grow as document kinds are added.

Registered before the catch-all StaticFiles mount — Starlette matches in
registration order, so a route added after it never runs.
"""

from __future__ import annotations

import html as html_escape
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
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


def _count_people(n: int) -> str:
    return "1 person" if n == 1 else f"{n} people"


def _people_section(row, session: Session, member_count: int | None) -> str:
    """Who else has access, read from `portal.users` when the caller may see it.

    `portal.users` grants SELECT to the studio's admin group alone (see
    pipeline/api/setup_portal.py's `_USERS_VIEW` grant); a non-admin's query
    raises SQLSTATE 42501, which the caller (this function) must absorb —
    the app-level exception_handler in pipeline/portal/app.py would otherwise
    turn it into a 403 for the *entire* page, including the "your access"
    section a viewer is fully entitled to read. Catching it here and falling
    back to the headcount already computed for the tile status line (the
    same `member_count` the "access" tile shows) means every caller, admin
    or not, gets a working page — just a shorter one for a non-admin. This
    mirrors `member_count`'s own try/except in pipeline/portal/app.py rather
    than gating on `row.role == "admin"`: the SELECT grant is tied to one
    fixed studio-wide group, not to being an admin of any particular
    project, so asking Postgres and catching its answer is the only check
    that is actually correct for every project, not just this one.
    """
    try:
        rows = session.execute(
            text(
                "SELECT username, role, active FROM portal.users "
                "WHERE project = :slug ORDER BY username"
            ),
            {"slug": row.slug},
        ).all()
    except ProgrammingError as exc:
        session.rollback()
        if getattr(exc.orig, "sqlstate", None) != "42501":
            raise
        if member_count:
            return f"<p>{_count_people(member_count)} have access to this project.</p>"
        return "<p>Nobody else has been given access to this project yet.</p>"

    people_rows = "\n".join(
        f"<tr><td>{html_escape.escape(u.username)}</td>"
        f"<td>{html_escape.escape(ROLE_LABEL.get(u.role, u.role or '—'))}</td>"
        f"<td>{'Active' if u.active else 'Disabled'}</td></tr>"
        for u in rows
    )
    return (
        f'<p class="footnote">{_count_people(len(rows))} in total.</p>'
        '<table>\n'
        "<thead><tr><th>Name</th><th>Role on this project</th><th>Status</th></tr></thead>\n"
        f"<tbody>{people_rows}</tbody>\n"
        "</table>"
    )


def _access_page(row, context: dict) -> str:
    role = row.role
    role_label = html_escape.escape(ROLE_LABEL.get(role, role or ""))
    role_desc = html_escape.escape(ROLE_DESC.get(role, ""))
    project = html_escape.escape(row.name)
    slug = html_escape.escape(row.slug)
    people_section = _people_section(row, context["session"], context.get("member_count"))
    return _ACCESS_PAGE.format(
        project=project,
        slug=slug,
        role_label=role_label,
        role_desc=role_desc,
        people_section=people_section,
    )


_ACCESS_PAGE = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Access — {project}</title>
<link rel="stylesheet" href="/document.css">
</head><body>
<header class="top no-print">
  <a class="brand" href="/project/{slug}"><span class="brand-mark"></span>{project}</a>
</header>
<nav class="crumb no-print"><a href="/">Portal</a> › <a href="/project/{slug}">{project}</a> › Access</nav>
<main class="doc-layout solo">
  <article class="doc">
    <h1>Access &amp; support</h1>

    <h2>Your access</h2>
    <p>You are <strong>{role_label}</strong> on this project.</p>
    <p>{role_desc}</p>

    <h2>Who else has access</h2>
    {people_section}

    <h2>Asking for more</h2>
    <p>Roles are changed by a person, not by a form. Ask a project administrator to change your role — the portal team does not hand out project roles.</p>
  </article>
</main>
</body></html>
"""
