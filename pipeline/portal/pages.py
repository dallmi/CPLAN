"""Server-rendered pages hanging off a project.

Separate from `app.py` because they are a different job from the JSON API: they
serve HTML, and they will grow as document kinds are added.

Registered before the catch-all StaticFiles mount — Starlette matches in
registration order, so a route added after it never runs.
"""

from __future__ import annotations

import html as html_escape
import logging
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from pipeline.portal.documents import published_documents, render_document, render_markdown_file
from pipeline.portal.resolvers import ROLE_LABEL, humanise_age, report_files
from pipeline.portal.resources import (
    PROJECTS_ROOT,
    assets_dir,
    load_manifest,
    manifest_path,
    named_file,
    tile_specs,
)

logger = logging.getLogger(__name__)

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

    @app.get("/project/{slug}/assets/{name}")
    def project_asset(slug: str, name: str, session: Session = Depends(db_session)):
        """One picture the project publishes, gated exactly like the project is.

        The manual's illustrations were once served from the portal's public
        static tree, so nine screenshots of the application — including a viewer
        session showing its role interface — were readable with no session at
        all, and by anyone entitled to any project. Per-project asset
        directories plus this route make a picture exactly as private as the
        project it belongs to. Everything the project shows lives behind it: the
        manual's screenshots and the logo on its tile alike.

        The name is matched against the directory's own listing, never joined
        onto it: an entry that does not exist under that exact name simply has
        no match, so no traversal is expressible here.
        """
        require_project(session, slug)
        match = named_file(assets_dir(slug, root=PROJECTS_ROOT), name)
        if match is None:
            raise HTTPException(status_code=404, detail={"code": "not_found"})
        return FileResponse(match)

    @app.get("/project/{slug}/docs")
    def project_docs_index(slug: str, session: Session = Depends(db_session)):
        require_project(session, slug)
        documents = published_documents(slug, root=PROJECTS_ROOT)
        if not documents:
            raise HTTPException(status_code=404, detail={"code": "not_found"})
        return RedirectResponse(f"/project/{slug}/docs/{documents[0]['key']}")

    @app.get("/project/{slug}/docs/{key}", response_class=HTMLResponse)
    def project_document(slug: str, key: str, session: Session = Depends(db_session)):
        row = require_project(session, slug)
        manifest = load_manifest(row.slug, root=PROJECTS_ROOT)
        documents = published_documents(row.slug, root=PROJECTS_ROOT, manifest=manifest)
        page = render_document(
            row.slug, key, row.name, documents, root=PROJECTS_ROOT, manifest=manifest
        )
        if page is None:
            raise HTTPException(status_code=404, detail={"code": "not_found"})
        return HTMLResponse(page)

    @app.get("/project/{slug}/changelog", response_class=HTMLResponse)
    def project_changelog(slug: str, session: Session = Depends(db_session)):
        """The project's own changelog, rendered by the document machinery.

        A changelog is read and printed like the technical documents, so it
        gets their chrome rather than the portal shell — and it goes through
        `documents.render_markdown_file` rather than a second markdown renderer
        living next to a route.
        """
        row = require_project(session, slug)
        manifest = load_manifest(row.slug, root=PROJECTS_ROOT)
        path = manifest_path(row.slug, "changelog", root=PROJECTS_ROOT, manifest=manifest)
        title = _tile_title(manifest, "changelog", "What's new")
        return HTMLResponse(render_markdown_file(path, title, row.name, row.slug))

    @app.get("/project/{slug}/data", response_class=HTMLResponse)
    def project_data(slug: str, session: Session = Depends(db_session)):
        row = require_project(session, slug)
        manifest = load_manifest(row.slug, root=PROJECTS_ROOT)
        return HTMLResponse(
            _data_page(row, _data_state(session), _tile_title(manifest, "data", "Data & freshness"))
        )

    @app.get("/project/{slug}/reports", response_class=HTMLResponse)
    def project_reports(slug: str, session: Session = Depends(db_session)):
        row = require_project(session, slug)
        manifest = load_manifest(row.slug, root=PROJECTS_ROOT)
        directory = manifest_path(row.slug, "reports", root=PROJECTS_ROOT, manifest=manifest)
        return HTMLResponse(
            _reports_page(
                row, report_files(directory), _tile_title(manifest, "reports", "Reports & downloads")
            )
        )

    @app.get("/project/{slug}/reports/{name}")
    def project_report_download(slug: str, name: str, session: Session = Depends(db_session)):
        """One generated workbook, gated by the same role check as its listing.

        Resolved the same way an asset is: by matching the requested name
        against the directory listing the page itself was built from, so the
        only files reachable here are the ones already shown, and no
        user-supplied string ever reaches the filesystem.
        """
        require_project(session, slug)
        directory = manifest_path(slug, "reports", root=PROJECTS_ROOT)
        match = next((path for path in report_files(directory) if path.name == name), None)
        if match is None:
            raise HTTPException(status_code=404, detail={"code": "not_found"})
        return FileResponse(match, filename=match.name)

    @app.get("/project/{slug}/access", response_class=HTMLResponse)
    def project_access(slug: str, session: Session = Depends(db_session)):
        row = require_project(session, slug)
        return HTMLResponse(_access_page(row, tile_context(session, row)))


def _tile_title(manifest: dict, kind: str, default: str) -> str:
    """What the project calls this tile — the same words on the tile and its page."""
    for spec in tile_specs(manifest):
        if spec.get("kind") == kind:
            title = spec.get("title")
            if isinstance(title, str) and title:
                return title
    return default


def _count_people(n: int, verb: bool = False) -> str:
    """"1 person"/"4 people", or with `verb=True` the count plus its agreeing "has"/"have".

    The verb lives here, not stranded in the caller's f-string, precisely
    because it was stranded in one once: `_people_section`'s degraded
    (non-admin) branch below used to hard-code "have" onto this count,
    reading "1 person have access to this project" for a single-member
    project -- caught only because that branch, being the one every
    non-admin sees, is read more than the admin one below it. Same class of
    bug `pipeline/portal/resolvers.py`'s `_count` exists to prevent for tile
    status lines; this is the equivalent fix for this module's one
    person-count call site that also needs a verb.
    """
    noun = "1 person" if n == 1 else f"{n} people"
    if not verb:
        return noun
    return f"{noun} has" if n == 1 else f"{noun} have"


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
            body = f'<div class="prose"><p>{_count_people(member_count, verb=True)} access to this project.</p></div>'
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


def _section(title: str, body: str, footnote: str = "") -> str:
    return f'<div class="section">{_section_head(title, footnote)}{body}</div>'


def _prose(*paragraphs: str) -> str:
    """Paragraphs, minus the empty ones — an empty <p> is a visible gap, not nothing."""
    return '<div class="prose">' + "".join(f"<p>{p}</p>" for p in paragraphs if p) + "</div>"


def _access_page(row, context: dict) -> str:
    role = row.role
    role_label = html_escape.escape(ROLE_LABEL.get(role, role or ""))
    role_desc = html_escape.escape(ROLE_DESC.get(role, ""))
    people_heading, people_body = _people_section(row, context["session"], context.get("member_count"))
    return _shell_page(
        row=row,
        title="Access",
        heading="Access & support",
        subtitle=f"What you may do in {row.name}, who else is here, and who to ask for more.",
        sections=(
            _section(
                "Your access",
                _prose(f"You are <strong>{role_label}</strong> on this project.", role_desc),
            )
            + _section("Who else has access", people_body, people_heading)
            + _section(
                "Asking for more",
                _prose(
                    "Roles are changed by a person, not by a form. Ask a project administrator "
                    "to change your role — the portal team does not hand out project roles."
                ),
            )
        ),
    )


def _data_state(session: Session) -> dict | None:
    """What this project holds and what the last sync run did, or None if unreadable.

    One statement's failure must not cost the page: a database that cannot
    answer (a fresh installation whose tables are not there yet, a revoked
    grant) leaves the page standing and saying so, the same contract
    `member_count` and `_people_section` already hold. The rollback matters as
    much as the catch — the request's session is shared with everything after
    this, and PostgreSQL refuses every later statement on an aborted one.
    """
    try:
        activities = session.execute(text("SELECT count(*) FROM activities")).scalar_one()
        run = session.execute(
            text(
                "SELECT ran_at, created, updated, unchanged, conflicts, vanished "
                "FROM sync_runs ORDER BY ran_at DESC LIMIT 1"
            )
        ).one_or_none()
    except Exception:  # noqa: BLE001 - a provenance page is never worth a 500
        logger.exception("Reading the data-freshness state failed")
        session.rollback()
        return None
    return {"activities": activities, "run": run}


# What each sync counter means, in the words the sync policy itself uses
# (pipeline/api/sync_snapshot.py's module docstring is the binding statement).
# A bare number under a bare label would be unreadable to the people this page
# is for: "conflicts" and "vanished" in particular have precise meanings that
# do not survive being guessed at.
_COUNTERS = (
    ("created", "Created", "Activities the run added from the source system."),
    ("updated", "Updated", "Activities that changed in the source and were brought up to date."),
    ("unchanged", "Unchanged", "Activities the run found already identical."),
    ("conflicts", "Conflicts", "Changed in both places. The source value won and the difference was recorded."),
    ("vanished", "Vanished", "No longer in the source. Nothing is deleted by a sync; they were left alone."),
)


def _data_page(row, state: dict | None, heading: str) -> str:
    if state is None:
        holdings = _prose("The database could not be asked what this project holds just now.")
        freshness = _prose("The date of the last refresh could not be read.")
        counters = ""
    else:
        holdings = _prose(f"This project holds <strong>{_number(state['activities'])}</strong>.")
        run = state["run"]
        if run is None:
            freshness = _prose(
                "Nothing has ever synced into this project. Everything it holds was created in "
                "the studio itself."
            )
            counters = ""
        else:
            freshness = _prose(
                f"Last refreshed <strong>{html_escape.escape(humanise_age(run.ran_at) or 'at an unknown time')}</strong>, "
                f"on {_moment(run.ran_at)}."
            )
            counters = _section("What the last refresh did", _counter_table(run))
    return _shell_page(
        row=row,
        title="Data",
        heading=heading,
        subtitle=f"Where {row.name} gets its data, and how current it is.",
        sections=(
            _section("What this project holds", holdings)
            + _section("How current it is", freshness)
            + counters
            + _section(
                "Where it comes from",
                _prose(
                    "Activities arrive two ways. Most are mirrored from the source system, which "
                    "stays the record of truth for them: a sync run reads its snapshot and brings "
                    "this database up to date with it.",
                    "The rest are created in the studio and belong to it alone — a sync run never "
                    "touches them. Where the same activity changed in both places, the source value "
                    "wins and the difference is recorded as a conflict rather than discarded. "
                    "Nothing is ever deleted by a sync.",
                ),
            )
        ),
    )


def _counter_table(run) -> str:
    rows = "\n".join(
        f"<tr><td>{label}</td><td>{_number_only(getattr(run, attribute))}</td><td>{meaning}</td></tr>"
        for attribute, label, meaning in _COUNTERS
    )
    return (
        '<table class="user-table">\n'
        "<thead><tr><th>Outcome</th><th>Activities</th><th>What it means</th></tr></thead>\n"
        f"<tbody>{rows}</tbody>\n"
        "</table>"
    )


def _reports_page(row, files: list[Path], heading: str) -> str:
    if not files:
        body = _prose(
            "No reports have been generated for this project yet. They appear here as soon as a "
            "reporting run has produced one."
        )
    else:
        rows = "\n".join(
            f'<tr><td><a href="/project/{html_escape.escape(row.slug)}/reports/'
            f'{html_escape.escape(quote(path.name))}">{html_escape.escape(path.name)}</a></td>'
            f"<td>{_size(path)}</td><td>{_moment(_modified(path))}</td></tr>"
            for path in files
        )
        body = (
            '<table class="user-table">\n'
            "<thead><tr><th>File</th><th>Size</th><th>Generated</th></tr></thead>\n"
            f"<tbody>{rows}</tbody>\n"
            "</table>"
        )
    return _shell_page(
        row=row,
        title="Reports",
        heading=heading,
        subtitle=f"Workbooks a reporting run has produced for {row.name}. Newest first.",
        sections=_section(
            "Generated workbooks",
            body,
            _count_files(len(files)) if files else "",
        )
        + _section(
            "How they are produced",
            _prose(
                "A reporting run writes the whole planning year as one workbook. It is not "
                "produced from the studio interface and it is not emailed to anyone: it lands in "
                "this project's report directory, and it appears in the list above.",
                "The studio's own Export to Excel is the other route, and a different question — "
                "it writes whatever you are looking at, filtered the way you filtered it.",
            ),
        ),
    )


def _count_files(n: int) -> str:
    return "1 file" if n == 1 else f"{n} files"


def _number(activities: int) -> str:
    noun = "activity" if activities == 1 else "activities"
    return f"{_number_only(activities)} {noun}"


def _number_only(value: int) -> str:
    """Thin-spaced thousands, as every count in this portal is grouped."""
    return f"{value:,}".replace(",", " ")


def _size(path: Path) -> str:
    """A file size a person reads at a glance, not to the byte."""
    size = path.stat().st_size
    if size < 1024:
        return f"{size} bytes"
    if size < 1024 * 1024:
        return f"{size / 1024:.0f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _modified(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def _moment(moment: datetime | None) -> str:
    """"3 August 2026, 18:42 UTC" — an absolute date beside every relative one."""
    if moment is None:
        return "an unknown date"
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%-d %B %Y, %H:%M UTC")


def _shell_page(row, title: str, heading: str, subtitle: str, sections: str) -> str:
    return _SHELL_PAGE.format(
        title=html_escape.escape(title),
        project=html_escape.escape(row.name),
        slug=html_escape.escape(row.slug),
        heading=html_escape.escape(heading),
        subtitle=html_escape.escape(subtitle),
        sections=sections,
    )


# The portal shell (styles.css), not the document chrome (document.css): these
# are portal pages reading like Home and the project page, not documents. One
# template for all of them — access, data, reports — because they differ only
# in their sections, and three hand-maintained copies of a top bar is how a
# breadcrumb ends up pointing at the wrong project on one page out of three.
# Documents (the technical docs, the changelog) keep their own chrome in
# documents.py: they are printable, this is not.
#
# Matches the topbar/breadcrumb/page-head idiom of project.html, with the
# same client-side touch for the top bar as project.js -- fetch /api/me and
# show the username only, no role label. Roles are per project, so a role
# shown next to the username would contradict the sentence in "Your access"
# below it whenever they happen to differ; the page's own sentence is the
# only statement of this project's role.
_SHELL_PAGE = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — {project}</title>
<link rel="stylesheet" href="/styles.css">
</head><body>
<header class="topbar">
  <div class="brand-block">
    <span class="brand-mark"></span>
    <div>
      <h1>Insights Portal</h1>
      <p>ECC Measurement &amp; Insights</p>
    </div>
  </div>
  <div class="top-actions">
    <div class="user-chip hidden" id="user-chip">
      <span class="avatar" aria-hidden="true" id="user-chip-avatar"></span>
      <span id="user-chip-name"></span>
    </div>
    <button class="btn quiet" id="user-chip-logout" type="button">Sign out</button>
  </div>
</header>
<main class="content">
  <nav class="crumbs" aria-label="Breadcrumb">
    <a href="/">Portal</a>
    <span class="crumb-sep" aria-hidden="true">&rsaquo;</span>
    <a href="/project/{slug}">{project}</a>
    <span class="crumb-sep" aria-hidden="true">&rsaquo;</span>
    <span class="crumb-here" aria-current="page">{heading}</span>
  </nav>

  <div class="page-head">
    <h1>{heading}</h1>
    <p class="subtitle">{subtitle}</p>
  </div>

  {sections}
</main>
<script>
(function () {{
  fetch('/api/me').then(function (r) {{ return r.ok ? r.json() : null; }}).then(function (user) {{
    if (!user) return;
    document.getElementById('user-chip-name').textContent = user.username;
    // Same derivation as js/ui.js's initials() -- this shell page is a plain
    // inline script, not an ES module, so it cannot import that helper.
    document.getElementById('user-chip-avatar').textContent = user.username
      .split(/[\\s.]+/).filter(Boolean).map(function (p) {{ return p[0]; }}).join('').slice(0, 2).toUpperCase();
    document.getElementById('user-chip').classList.remove('hidden');
  }});
  document.getElementById('user-chip-logout').addEventListener('click', function () {{
    fetch('/api/logout', {{ method: 'POST' }}).then(function () {{ window.location.href = '/'; }});
  }});
}})();
</script>
</body></html>
"""
