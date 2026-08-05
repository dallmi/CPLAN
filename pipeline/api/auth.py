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
from enum import Enum
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


class CredentialCheck(Enum):
    """What a credential probe actually established."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"  # PostgreSQL said no: wrong password, NOLOGIN, no such role
    UNAVAILABLE = "unavailable"  # PostgreSQL never got as far as saying anything


# SQLSTATE class 28 is "invalid authorization specification": 28P01 for a wrong
# password, 28000 for a deactivated (NOLOGIN) or non-existent role, and for a
# pg_hba rule that refuses the connection.
#
# It is only ever a bonus here, never the decision. A failure *during connect*
# carries no `PGresult`, so libpq has no error fields to expose and psycopg
# leaves `sqlstate` as `None` — which is precisely the case this function
# exists to classify. Reading the classification off `sqlstate` alone
# therefore called every wrong password "the database did not answer", and
# since the login throttle hands back the reservation for exactly that answer,
# the counters never counted a single guess: the rate limit was a no-op and
# every failed sign-in was a 503. `tests/test_login_throttle.py` catches this
# against a real server; nothing that stubs the probe can.
_REJECTED_SQLSTATE_CLASS = "28"


def _server_is_answering(url: URL) -> bool:
    """Can a brand-new connection reach this server *right now*?

    Deliberately the same shape as the probe it explains — a fresh NullPool
    connection, a moment later — because the failures worth telling apart are
    the ones a warm pooled connection cannot see: an exhausted `max_connections`
    (53300), a `pg_hba` reload, a restart in progress. Asking the app's own
    live engine instead would answer "up" in exactly those cases, which is the
    bug this whole distinction was introduced to remove.
    """
    engine = None
    try:
        engine = create_engine(url, poolclass=NullPool)
        with engine.connect() as connection:
            connection.execute(select(1))
        return True
    except SQLAlchemyError:
        return False
    finally:
        if engine is not None:
            engine.dispose()


def check_credentials(database_url: str | URL, username: str, password: str) -> CredentialCheck:
    """Ask PostgreSQL whether `username`/`password` may open a session.

    NullPool + immediate dispose: this is a throwaway probe connection, it must
    never linger in a pool.

    The three-way answer exists because the login throttle counts guesses, and
    a database that could not be reached is not a guess. Collapsing both
    failures into "no" (as a bool must) meant a pg restart or an exhausted
    connection limit spent a real user's lockout budget on the server's own
    outage and locked the account for fifteen minutes past recovery. Callers
    still owe the *client* a uniform answer — REJECTED must not say which part
    failed — but they owe the counter an honest one.

    Which way an *unclassifiable* failure goes is the security-relevant half.
    UNAVAILABLE refunds the attempt, so guessing wrong there costs the limit
    everything: it stops counting. REJECTED costs at worst a fifteen-minute
    lockout that releases on its own. So the default is REJECTED, and
    UNAVAILABLE is returned only on positive evidence — the server did not
    answer a second, identical connection attempt made with the service
    credentials the caller passed in, which are known-good.
    """
    try:
        service_url = make_url(database_url)
    except SQLAlchemyError:
        # Not a URL at all: no server was asked anything, so nothing was
        # rejected. A misconfiguration, and never a password guess.
        return CredentialCheck.UNAVAILABLE

    engine = None
    connected = False
    try:
        engine = create_engine(service_url.set(username=username, password=password), poolclass=NullPool)
        with engine.connect() as connection:
            connected = True
            connection.execute(select(1))
        return CredentialCheck.ACCEPTED
    except SQLAlchemyError as exc:
        if connected:
            # Authentication had already succeeded; whatever failed after it
            # is the server's problem, not the caller's credentials.
            return CredentialCheck.UNAVAILABLE
        sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
        if sqlstate and sqlstate.startswith(_REJECTED_SQLSTATE_CLASS):
            return CredentialCheck.REJECTED
        return (
            CredentialCheck.REJECTED
            if _server_is_answering(service_url)
            else CredentialCheck.UNAVAILABLE
        )
    finally:
        if engine is not None:
            engine.dispose()


def verify_credentials(database_url: str | URL, username: str, password: str) -> bool:
    """True iff PostgreSQL accepts a connection as `username`/`password`.

    The bool form, for callers with nothing to decide between "rejected" and
    "could not ask" (both are a 401's worth of information to the client).
    """
    return check_credentials(database_url, username, password) is CredentialCheck.ACCEPTED
