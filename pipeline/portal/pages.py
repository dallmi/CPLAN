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


def _people_section(row, session: Session, member_count: int | None) -> tuple[str, str]:
    """Who else has access: a (heading, body) pair of HTML fragments.

    Returned as a pair rather than one blob so the caller can build the
    section heading itself and skip the summary line entirely when there is
    none to show — emitting an empty `<p class="footnote"></p>` placeholder
    for that case previously left a stray empty element (and, depending on
    surrounding rules, a visible rule with nothing on it) between the
    heading and the content.

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
            body = f'<div class="prose"><p>{_count_people(member_count)} have access to this project.</p></div>'
        else:
            body = '<div class="prose"><p>Nobody else has been given access to this project yet.</p></div>'
        return "", body

    people_rows = "\n".join(
        f"<tr><td>{html_escape.escape(u.username)}</td>"
        f"<td>{html_escape.escape(ROLE_LABEL.get(u.role, u.role or '—'))}</td>"
        f"<td>{'Active' if u.active else 'Disabled'}</td></tr>"
        for u in rows
    )
    heading = f"{_count_people(len(rows))} in total"
    body = (
        '<table class="user-table">\n'
        "<thead><tr><th>Name</th><th>Role on this project</th><th>Status</th></tr></thead>\n"
        f"<tbody>{people_rows}</tbody>\n"
        "</table>"
    )
    return heading, body


def _section_head(title: str, footnote: str = "") -> str:
    aside = f'<p class="footnote">{footnote}</p>' if footnote else ""
    return f'<div class="section-head"><h2>{title}</h2>{aside}</div>'


def _access_page(row, context: dict) -> str:
    role = row.role
    role_label = html_escape.escape(ROLE_LABEL.get(role, role or ""))
    role_desc = html_escape.escape(ROLE_DESC.get(role, ""))
    project = html_escape.escape(row.name)
    slug = html_escape.escape(row.slug)
    people_heading, people_body = _people_section(row, context["session"], context.get("member_count"))
    return _ACCESS_PAGE.format(
        project=project,
        slug=slug,
        role_label=role_label,
        role_desc=role_desc,
        your_access_head=_section_head("Your access"),
        people_head=_section_head("Who else has access", people_heading),
        people_body=people_body,
        asking_head=_section_head("Asking for more"),
    )


# The portal shell (styles.css), not the document chrome (document.css): this
# is a portal page reading like Home and the project page, not a document.
# Matches the topbar/breadcrumb/page-head idiom of project.html, with the
# same client-side touch for the top bar as project.js -- fetch /api/me and
# show the username only, no role label. Roles are per project, so a role
# shown next to the username would contradict the sentence in "Your access"
# below it whenever they happen to differ; the page's own sentence is the
# only statement of this project's role.
_ACCESS_PAGE = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Access — {project}</title>
<link rel="stylesheet" href="/styles.css">
</head><body>
<header class="topbar">
  <div class="brand"><span class="brand-mark"></span><h1>CPLAN Portal</h1></div>
  <div id="user-chip" class="user-chip hidden">
    <span id="user-chip-name"></span>
    <button id="user-chip-logout" class="btn-ghost" type="button">Sign out</button>
  </div>
</header>
<main class="content">
  <nav class="crumbs" aria-label="Breadcrumb">
    <a href="/">Portal</a>
    <span class="crumb-sep" aria-hidden="true">&rsaquo;</span>
    <a href="/project/{slug}">{project}</a>
    <span class="crumb-sep" aria-hidden="true">&rsaquo;</span>
    <span class="crumb-here" aria-current="page">Access &amp; support</span>
  </nav>

  <div class="page-head">
    <h1>Access &amp; support</h1>
    <p class="subtitle">What you may do in {project}, who else is here, and who to ask for more.</p>
  </div>

  <div class="section">
    {your_access_head}
    <div class="prose">
      <p>You are <strong>{role_label}</strong> on this project.</p>
      <p>{role_desc}</p>
    </div>
  </div>

  <div class="section">
    {people_head}
    {people_body}
  </div>

  <div class="section">
    {asking_head}
    <div class="prose">
      <p>Roles are changed by a person, not by a form. Ask a project administrator to change your role — the portal team does not hand out project roles.</p>
    </div>
  </div>
</main>
<script>
(function () {{
  fetch('/api/me').then(function (r) {{ return r.ok ? r.json() : null; }}).then(function (user) {{
    if (!user) return;
    document.getElementById('user-chip-name').textContent = user.username;
    document.getElementById('user-chip').classList.remove('hidden');
  }});
  document.getElementById('user-chip-logout').addEventListener('click', function () {{
    fetch('/api/logout', {{ method: 'POST' }}).then(function () {{ window.location.href = '/'; }});
  }});
}})();
</script>
</body></html>
"""
