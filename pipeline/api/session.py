"""Per-request Postgres identity for the CPLAN APIs (studio + portal).

Single source of truth for the SET ROLE impersonation lifecycle: the pool holds
one `cplan_authenticator` identity and each request switches to the logged-in
user via session-scoped SET ROLE, resetting before the connection returns to the
pool. Shared by pipeline/api/app.py and pipeline/portal/app.py so the security-
critical teardown ordering lives in exactly one place.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterator

from fastapi import Depends, HTTPException, Request
from sqlalchemy import Engine
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from pipeline.api.auth import AuthSettings, verify_session_token


@dataclass(frozen=True)
class CurrentUser:
    username: str
    db_role: str | None  # None: legacy solo mode — no SET ROLE, actor "studio"


def build_session_dependencies(engine: Engine, auth: AuthSettings | None) -> tuple[Callable, Callable]:
    def current_user(request: Request) -> CurrentUser:
        if auth is None:
            return CurrentUser(username="studio", db_role=None)
        token = request.cookies.get(auth.cookie_name)
        username = verify_session_token(auth, token) if token else None
        if username is None:
            raise HTTPException(status_code=401, detail={"code": "unauthenticated"})
        return CurrentUser(username=username, db_role=username)

    def db_session(user: CurrentUser = Depends(current_user)) -> Iterator[Session]:
        connection = engine.connect()
        try:
            if user.db_role is not None:
                quoted = engine.dialect.identifier_preparer.quote(user.db_role)
                try:
                    connection.exec_driver_sql(f"SET ROLE {quoted}")
                    connection.commit()
                except ProgrammingError:
                    raise HTTPException(status_code=401, detail={"code": "unauthenticated"})
            session = Session(bind=connection)
            try:
                yield session
            finally:
                session.close()
        finally:
            # Ordering is load-bearing: rollback first to clear any failed
            # transaction (SET ROLE is session-scoped and survives a commit),
            # then RESET ROLE + commit so the connection never returns to the
            # pool still impersonating the request's user. A rollback that
            # itself raises invalidates the connection (SQLAlchemy discards it
            # rather than pooling it), so no impersonating connection is reused.
            try:
                connection.rollback()
                if user.db_role is not None:
                    connection.exec_driver_sql("RESET ROLE")
                    connection.commit()
            finally:
                connection.close()

    return current_user, db_session
