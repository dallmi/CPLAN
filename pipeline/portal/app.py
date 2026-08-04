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


class LoginPayload(BaseModel):
    username: str = Field(min_length=1, max_length=63)
    password: str


class CreateUserPayload(BaseModel):
    username: str = Field(min_length=1, max_length=63)
    password: str = Field(min_length=1)
    project: str = Field(min_length=1)
    role: str = Field(min_length=1)


class RolePayload(BaseModel):
    project: str = Field(min_length=1)
    role: str = Field(min_length=1)


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
                "SELECT slug, name, url FROM portal.projects p "
                "WHERE pg_has_role(current_user, p.role_prefix || '_viewer', 'member') "
                "   OR pg_has_role(current_user, p.role_prefix || '_contributor', 'member') "
                "   OR pg_has_role(current_user, p.role_prefix || '_editor', 'member') "
                "   OR pg_has_role(current_user, p.role_prefix || '_admin', 'member') "
                "ORDER BY name"
            )
        ).all()
        return {"projects": [{"slug": r.slug, "name": r.name, "url": r.url} for r in rows]}

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

    @app.post("/api/portal/users/{username}/password")
    def set_password_endpoint(username: str, payload: PasswordPayload, session: Session = Depends(db_session)):
        _call(session, "SELECT portal.reset_password(:n, :p)", {"n": username, "p": payload.password})
        return {"status": "ok"}

    @app.post("/api/portal/users/{username}/active")
    def set_active_endpoint(username: str, payload: ActivePayload, session: Session = Depends(db_session)):
        _call(session, "SELECT portal.set_active(:n, :a)", {"n": username, "a": payload.active})
        return {"status": "ok"}

    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="portal")
    return app


def create_environment_app() -> FastAPI:
    from pipeline.api.database import database_url_from_environment

    return create_portal_app(database_url_from_environment())
