"""CPLAN portal service: landing page, project tiles, admin user management.

Separate FastAPI app sharing the studio's Postgres cluster, session cookie, and
per-request SET ROLE identity (pipeline/api/session). Privileged user management
is delegated to the portal.* SECURITY DEFINER functions (pipeline/api/setup_portal);
the portal holds no DDL rights of its own — a non-admin's call is rejected by
Postgres (42501 -> 403) before anything happens.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from pipeline.api.auth import (
    AuthSettings,
    auth_settings_from_environment,
    create_session_token,
    verify_credentials,
)
from pipeline.api.database import backend_from_url, create_cplan_engine
from pipeline.api.session import CurrentUser, build_session_dependencies
from pipeline.portal.resolvers import RESOLVERS
from pipeline.portal.resources import PROJECTS_ROOT, load_manifest, manifest_path, resolve_tiles


# Most-privileged first: `PROJECT_ROLE` reports the first arm that matches, and
# the four groups are nested (viewer <- contributor <- editor <- admin), so an
# admin matches all four and must be reported as admin.
ROLES = ("admin", "editor", "contributor", "viewer")


def _holds(role: str) -> str:
    """SQL: does the caller hold this project's `<prefix>_<role>` group?

    One definition of the rule, used by the list endpoint and the detail query
    alike. It was written out twice, and the copies drifted: the detail query
    was given `to_regrole` while the list endpoint kept bare role names, so a
    project registered before its group roles existed took the landing page
    down for every caller with SQLSTATE 42704 — `pg_has_role` raises on a name
    that is not a role. `to_regrole` yields NULL for an unknown name instead,
    which makes this expression NULL: it falls out of a WHERE on its own and
    falls through a CASE to the next arm. Whatever this rule becomes next, it
    can now only be learned, and changed, in one place.
    """
    return f"pg_has_role(current_user, to_regrole(p.role_prefix || '_{role}'), 'member')"


# "The caller holds some role on p" — for filtering the project list.
PROJECT_VISIBLE = " OR ".join(_holds(role) for role in ROLES)
# "…and it is this one" — for naming it on a single project.
PROJECT_ROLE = (
    "CASE " + " ".join(f"WHEN {_holds(role)} THEN '{role}'" for role in ROLES) + " END"
)


class LoginPayload(BaseModel):
    username: str = Field(min_length=1, max_length=63)
    password: str


class CreateUserPayload(BaseModel):
    # The access matrix encodes a grant as `username:slug` in a data-cell
    # attribute and splits it on ':' (pipeline/portal/static/js/matrix.js);
    # a colon in the username would silently break that lookup. The pattern
    # keeps a username to what a system identifier needs -- letters, digits,
    # dot, hyphen, underscore -- so it can never contain one. invite.js checks
    # the same pattern client-side so the admin is told before submitting, but
    # this is the enforcement that actually matters: the API is not relying
    # on the browser.
    username: str = Field(min_length=1, max_length=63, pattern=r"^[A-Za-z0-9._-]+$")
    password: str = Field(min_length=1)
    project: str = Field(min_length=1)
    role: str = Field(min_length=1)


class RolePayload(BaseModel):
    project: str = Field(min_length=1)
    role: str = Field(min_length=1)


class RevokePayload(BaseModel):
    project: str = Field(min_length=1)


class PasswordPayload(BaseModel):
    password: str = Field(min_length=1)


class ActivePayload(BaseModel):
    active: bool


def create_portal_app(database_url: str | URL | None = None, auth_settings: AuthSettings | None = None) -> FastAPI:
    resolved_url = database_url or os.environ.get("CPLAN_DATABASE_URL")
    if not resolved_url:
        raise RuntimeError("CPLAN database is not configured; set CPLAN_DATABASE_URL")
    backend = backend_from_url(resolved_url)
    if backend != "postgresql":
        raise RuntimeError(
            "The portal requires a PostgreSQL backend (it delegates user administration to "
            "portal.* functions that only exist there); the configured backend is "
            f"{backend!r}. Refusing to start."
        )
    engine = create_cplan_engine(resolved_url)
    auth = auth_settings if auth_settings is not None else auth_settings_from_environment()
    if auth is None:
        raise RuntimeError(
            "The portal requires authentication: set CPLAN_AUTH_SECRET (and use a PostgreSQL "
            "backend). Refusing to start an unauthenticated user-administration surface."
        )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        engine.dispose()

    app = FastAPI(title="CPLAN Portal", version="0.1.0", lifespan=lifespan)
    app.state.engine = engine
    current_user, db_session = build_session_dependencies(engine, auth)

    @app.exception_handler(ProgrammingError)
    async def insufficient_privilege_handler(_: Request, exc: ProgrammingError):
        if getattr(exc.orig, "sqlstate", None) == "42501":
            return JSONResponse(status_code=403, content={"detail": {"code": "forbidden"}})
        raise exc

    @app.post("/api/login")
    def login(payload: LoginPayload, response: Response):
        if not verify_credentials(resolved_url, payload.username, payload.password):
            raise HTTPException(status_code=401, detail={"code": "invalid_credentials"})
        response.set_cookie(
            auth.cookie_name,
            create_session_token(auth, payload.username),
            max_age=auth.max_age_seconds,
            httponly=True,
            samesite="lax",
        )
        return {"username": payload.username}

    @app.post("/api/logout")
    def logout(response: Response):
        response.delete_cookie(auth.cookie_name)
        return {"status": "ok"}

    @app.get("/api/me")
    def me(user: CurrentUser = Depends(current_user), session: Session = Depends(db_session)):
        flags = session.execute(
            text(
                "SELECT pg_has_role(current_user, 'cplan_admin', 'member') AS is_admin, "
                "pg_has_role(current_user, 'cplan_editor', 'member') AS is_editor, "
                "pg_has_role(current_user, 'cplan_contributor', 'member') AS is_contributor"
            )
        ).one()
        role = (
            "admin" if flags.is_admin
            else "editor" if flags.is_editor
            else "contributor" if flags.is_contributor
            else "viewer"
        )
        return {"username": user.username, "role": role, "auth": True}

    @app.get("/api/portal/projects")
    def projects(session: Session = Depends(db_session)):
        rows = session.execute(
            text(
                "SELECT p.slug, p.name, p.url, "
                f"  {PROJECT_ROLE} AS role "
                "FROM portal.projects p "
                f"WHERE {PROJECT_VISIBLE} "
                "ORDER BY p.name"
            )
        ).all()
        return {
            "projects": [
                {
                    "slug": r.slug,
                    "name": r.name,
                    "url": r.url,
                    "purpose": load_manifest(r.slug, root=PROJECTS_ROOT).get("purpose"),
                    "role": r.role,
                }
                for r in rows
            ]
        }

    PROJECT_SQL = text(
        "SELECT p.slug, p.name, p.url, p.role_prefix, "
        f"  {PROJECT_ROLE} AS role "
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
        """People who can sign in and hold one of this project's four group roles.

        Mirrors `_USERS_VIEW` (pipeline/api/setup_portal.py) rather than a LIKE
        pattern on role_prefix, and for the same reason that comment gives:
        the privilege chain (viewer <- contributor <- editor <- admin) makes
        each group a member of the ones below it, so a LIKE would also match
        cplan_sync/cplan_authenticator/portal_owner and inflate the count with
        roles that are not people at all; a LIKE also treats role_prefix's own
        `_`/`%` as wildcards and would absorb a nested prefix (cplan_sub). The
        four exact names side-step all of that, and `rolcanlogin` on the
        member keeps the count meaning "people who can actually sign in", not
        every login and service role transitively granted the group.
        """
        groups = [f"{role_prefix}_{suffix}" for suffix in ("viewer", "contributor", "editor", "admin")]
        try:
            return session.execute(
                text(
                    "SELECT count(DISTINCT m.member) FROM pg_auth_members m "
                    "JOIN pg_roles g ON g.oid = m.roleid "
                    "JOIN pg_roles u ON u.oid = m.member AND u.rolcanlogin "
                    "WHERE g.rolname IN (:viewer, :contributor, :editor, :admin)"
                ),
                dict(zip(("viewer", "contributor", "editor", "admin"), groups)),
            ).scalar_one()
        except Exception:  # noqa: BLE001 - a headcount is never worth a 500
            session.rollback()
            return None

    def tile_context(session: Session, row, manifest: dict | None = None) -> dict:
        # `manifest` is optional so a caller holding only the row keeps
        # working, at the cost of a reload — the access page reaches this
        # through register_pages that way. project_detail below always has the
        # manifest already and passes it, so the three manifest_path lookups
        # don't each re-read and re-parse the same file.
        if manifest is None:
            manifest = load_manifest(row.slug, root=PROJECTS_ROOT)
        return {
            "session": session,
            "slug": row.slug,
            "role": row.role,
            "member_count": member_count(session, row.role_prefix),
            "manual_path": manifest_path(row.slug, "manual", root=PROJECTS_ROOT, manifest=manifest),
            "changelog_path": manifest_path(row.slug, "changelog", root=PROJECTS_ROOT, manifest=manifest),
            "reports_dir": manifest_path(row.slug, "reports", root=PROJECTS_ROOT, manifest=manifest),
        }

    @app.get("/api/portal/projects/{slug}")
    def project_detail(slug: str, session: Session = Depends(db_session)):
        row = project_row(session, slug)
        if row is None:
            raise HTTPException(status_code=404, detail={"code": "not_found"})
        # Everything from here on comes from the registry row, not the raw
        # path parameter, now that row.slug is known to exist and be the
        # caller's actual entitlement target.
        manifest = load_manifest(row.slug, root=PROJECTS_ROOT)
        tiles = resolve_tiles(
            row.slug, manifest, row.url, RESOLVERS, tile_context(session, row, manifest)
        )
        return {
            "slug": row.slug,
            "name": row.name,
            "purpose": manifest.get("purpose"),
            "role": row.role,
            "url": row.url,
            "tiles": [t.as_dict() for t in tiles],
        }

    @app.get("/api/portal/users")
    def list_users(session: Session = Depends(db_session)):
        # SELECT on portal.users is granted only to cplan_admin -> 42501 -> 403 for others.
        rows = session.execute(
            text("SELECT username, project, role, active FROM portal.users ORDER BY username")
        ).all()
        return {"users": [{"username": r.username, "project": r.project, "role": r.role, "active": r.active} for r in rows]}

    def _call(session: Session, sql: str, params: dict):
        """Invoke a portal.* SECURITY DEFINER function and translate its failure.

        These calls can fail with `sqlalchemy.exc.ProgrammingError` for several
        distinct reasons, distinguished by SQLSTATE (see pipeline/api/setup_portal.py's
        module note): Postgres's own privilege check on EXECUTE raises SQLSTATE
        42501 (insufficient_privilege) for a non-admin caller; the functions'
        own `RAISE EXCEPTION` (unknown project/role, reserved name) defaults to
        SQLSTATE P0001 (plpgsql raise_exception) — deliberately NOT the class-22
        DataError code, so it still surfaces as ProgrammingError; anything else
        (a typo'd query, schema drift, an undefined object such as a role that
        does not exist) is a genuine server fault, not caller input.

        Only P0001 — the functions' own input validation — is mapped to 422.
        42501 is re-raised for the app-level exception_handler above to turn
        into 403. Every other SQLSTATE is re-raised unchanged, becoming a 500;
        it must never be echoed to the client as if it were a client error.
        """
        try:
            session.execute(text(sql), params)
            session.commit()
        except ProgrammingError as exc:
            session.rollback()
            if getattr(exc.orig, "sqlstate", None) != "P0001":
                raise
            raise HTTPException(status_code=422, detail={"code": "invalid_input", "message": str(exc.orig)}) from exc

    @app.post("/api/portal/users", status_code=status.HTTP_201_CREATED)
    def create_user_endpoint(payload: CreateUserPayload, session: Session = Depends(db_session)):
        _call(
            session,
            "SELECT portal.create_user(:n, :p, :proj, :r)",
            {"n": payload.username, "p": payload.password, "proj": payload.project, "r": payload.role},
        )
        return {"username": payload.username}

    @app.post("/api/portal/users/{username}/role")
    def set_role_endpoint(username: str, payload: RolePayload, session: Session = Depends(db_session)):
        _call(session, "SELECT portal.set_project_role(:n, :proj, :r)", {"n": username, "proj": payload.project, "r": payload.role})
        return {"status": "ok"}

    @app.post("/api/portal/users/{username}/revoke")
    def revoke_role_endpoint(username: str, payload: RevokePayload, session: Session = Depends(db_session)):
        _call(session, "SELECT portal.revoke_project_role(:n, :proj)", {"n": username, "proj": payload.project})
        return {"status": "ok"}

    @app.post("/api/portal/users/{username}/password")
    def set_password_endpoint(username: str, payload: PasswordPayload, session: Session = Depends(db_session)):
        _call(session, "SELECT portal.reset_password(:n, :p)", {"n": username, "p": payload.password})
        return {"status": "ok"}

    @app.post("/api/portal/users/{username}/active")
    def set_active_endpoint(username: str, payload: ActivePayload, session: Session = Depends(db_session)):
        _call(session, "SELECT portal.set_active(:n, :a)", {"n": username, "a": payload.active})
        return {"status": "ok"}

    from pipeline.portal.pages import register_pages

    register_pages(app, db_session, project_row, tile_context)

    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="portal")
    return app


def create_environment_app() -> FastAPI:
    from pipeline.api.database import database_url_from_environment

    return create_portal_app(database_url_from_environment())
