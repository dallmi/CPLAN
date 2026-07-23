"""Session tokens and Postgres-delegated credential verification for the CPLAN API.

Passwords are never stored or hashed here: `verify_credentials` simply attempts
a real database connection with the supplied username/password, so the
authority on passwords is PostgreSQL itself (SCRAM). The session token is a
signed, timestamped pointer to the username — not an authority: even a forged
role claim only changes UI rendering, Postgres rejects unauthorized statements
with 42501 (see the design spec).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import create_engine, make_url, select
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

_TOKEN_SALT = "cplan-session"


@dataclass(frozen=True)
class AuthSettings:
    secret: str
    max_age_seconds: int = 43200  # 12h — one working day with margin
    cookie_name: str = "cplan_session"


def auth_settings_from_environment(environ: Mapping[str, str] | None = None) -> AuthSettings | None:
    environment = os.environ if environ is None else environ
    secret = environment.get("CPLAN_AUTH_SECRET", "")
    if not secret:
        return None
    return AuthSettings(secret=secret)


def _serializer(settings: AuthSettings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.secret, salt=_TOKEN_SALT)


def create_session_token(settings: AuthSettings, username: str) -> str:
    return _serializer(settings).dumps({"u": username})


def verify_session_token(settings: AuthSettings, token: str) -> str | None:
    try:
        payload = _serializer(settings).loads(token, max_age=settings.max_age_seconds)
    except (BadSignature, SignatureExpired):
        return None
    username = payload.get("u") if isinstance(payload, dict) else None
    return username if isinstance(username, str) and username else None


def verify_credentials(database_url: str | URL, username: str, password: str) -> bool:
    """True iff PostgreSQL accepts a connection as `username`/`password`.

    NullPool + immediate dispose: this is a throwaway probe connection, it must
    never linger in a pool. Any failure — bad password, NOLOGIN (deactivated
    user), unknown role, unreachable server, malformed URL — is simply `False`;
    the caller turns that into a uniform 401 without leaking which part failed.
    """
    engine = None
    try:
        probe_url = make_url(database_url).set(username=username, password=password)
        engine = create_engine(probe_url, poolclass=NullPool)
        with engine.connect() as connection:
            connection.execute(select(1))
        return True
    except SQLAlchemyError:
        return False
    finally:
        if engine is not None:
            engine.dispose()
