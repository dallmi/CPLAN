"""Failed-login throttling for the credential endpoints.

`verify_credentials` (pipeline/api/auth.py) authenticates by opening a real
PostgreSQL connection, so an unthrottled `POST /api/login` lets a caller try
passwords as fast as the server answers them. That matters more here than in a
typical web app: accounts *are* PostgreSQL login roles, so a guessed password
is a database session at that account's privilege level, and initial passwords
are administrator-generated and handed over by phone or chat -- exactly the
population of secrets an online guessing run is best at.

Both doors use this module. The portal and the studio are separate processes
that already share this cluster and this session secret, and each publishes its
own `POST /api/login` against the same roles and mints the same `cplan_session`
cookie -- a limit on one of them is not a limit, it is a choice of port number.

## The mechanism

Three sliding counters over `portal.login_attempts`, each a fixed window of
`window_seconds`:

* **per name and address together** (`pair_failures`) -- the counter that
  actually stops a sequential guessing run, because a guesser sits at one
  address and works through one name.
* **per submitted username** (`username_failures`), across every address -- the
  backstop for a guessing run spread over many addresses, which the pair
  counter cannot see.
* **per source address** (`source_failures`), across every name -- the counter
  that stops password spraying, which neither of the others can see: one guess
  against each of two hundred usernames never reaches a per-name threshold.

Four properties are deliberate, not incidental:

1. **A lockout always releases on its own, and hammering cannot extend it.**
   The window is fixed: it starts at a counter's first attempt and ends
   `window_seconds` later, whatever arrives in between, and a blocked attempt
   hands its reservation straight back so it is never counted at all. An
   earlier revision measured the window from the last *counted* attempt
   instead, which reads as the more forgiving choice and is the opposite: each
   attempt that aged out admitted exactly one new one, which was counted and
   restarted the window, so five wrong passwords plus continuous hammering
   denied a named account for as long as the attacker kept typing. Priority
   one is that a real person who mistypes gets back in.
2. **A lockout is aimed as narrowly as it can be.** Five wrong passwords from
   one address stop *that address* guessing *that name*; they do not stop the
   account's owner signing in from their own address, and the account-wide
   counter that does apply to everyone sits four times higher, where only a
   distributed run reaches it. A per-account lockout that any stranger can
   trigger is a denial-of-service tool with a friendly name, on a portal with
   no self-service recovery.
3. **The counting is atomic.** `begin_attempt` reserves the attempt and returns
   the verdict in one round trip, under the row lock PostgreSQL takes for
   `INSERT ... ON CONFLICT DO UPDATE`. Read-then-probe-then-write would admit
   every request already in flight, making the real ceiling the server's
   thread pool (and multiplying again per process), not the policy. The
   reservation is handed back by `end_attempt` when the attempt turns out not
   to have been a guess: a correct password, or a credential check that could
   not be carried out at all.
4. **A throttled attempt looks the same whatever the username.** The counter is
   keyed on the string that was submitted, so a name that does not exist
   accumulates and blocks exactly like a real one; the handler answers both
   with the same status, body and `Retry-After`, and -- because the block is
   evaluated *before* `verify_credentials` -- neither performs the database
   probe, so the two cannot be told apart by response time either. Nothing
   ever clears another caller's counter, either: a successful sign-in gives
   back only the one reservation it took, so watching how much headroom a name
   has left cannot tell an attacker that the owner just signed in, or that the
   name is a real account at all.

## Why the counters are in the database and not in the process

A dict in the portal's memory would be a limit on one front door, and the
attacker chooses the door; it would also multiply by the worker count the
moment anyone runs more than one worker, and reset to zero on every restart
(the portal is restarted routinely). Putting the rows in PostgreSQL makes the
limit a property of the account and of the source address rather than of the
process that happened to receive the request: add a second portal process, a
second worker, the studio's own login endpoint or a second host and the numbers
below still mean the same thing for the deployment as a whole, with no new
state to synchronise. The cost is one round trip per login attempt, to a
database the attempt has to reach anyway.

Rejected alternatives: an in-process dictionary (above); Redis or another
shared store (new infrastructure and a new secret, for a deployment whose
whole premise is that it needs neither); rate limiting in a reverse proxy
(there is none, and it cannot see the username, so it could only ever do the
spraying half); and a fixed delay or tarpit on failure (it does not bound the
total number of guesses, it ties up a worker per guess, and an attacker just
opens more connections).

## The numbers

`pair_failures = 5` in a **15-minute** window. Five is well clear of the one to
three attempts a real person spends on a typo or on their other password, so a
legitimate user essentially never reaches it; someone who does reach it is not
mistyping, and waits at most fifteen minutes rather than phoning an
administrator.

`username_failures = 20`, same window: the account-wide backstop. From a single
address the pair counter stops a run four times sooner, so this one is only
reached by a run spread over at least four addresses, and it caps even that at
80 guesses an hour against a named account -- five orders of magnitude below
what the endpoint answers unthrottled, and hopeless against an
administrator-generated password. It is deliberately not lower: this is the
one counter a stranger can use to lock an account its owner is holding, so it
sits where only an attack reaches it and a working day never does.

`source_failures = 20`, same window: one address may exhaust four different
accounts before it is stopped, while a spray that touches twenty names once
each is cut off at the twentieth. The collateral is honest and bounded: people
sharing one source address (a NAT gateway) share this budget, and would need
twenty failures between them in fifteen minutes to trip it, after which it
releases on its own.

## What a "source" is, and when it is allowed to block

`client_source` reports the transport peer and never an `X-Forwarded-For` or
`X-Real-IP` header: those are attacker-supplied strings, and honouring one
would turn the per-source counter into a per-*header* counter -- a fresh bucket
per request, i.e. no spraying limit at all, plus a way to spend a named
address's budget. That is only true if the ASGI server has not already
rewritten the peer for us, which uvicorn does by default (`proxy_headers=True`
with `forwarded_allow_ips` defaulting to the bound host), so both launchers
pass `proxy_headers=False` -- see pipeline/scripts/start_portal.py. A
deployment that does put a proxy in front of the portal has to establish a
trusted-proxy chain first.

The flip side is `source_counts_toward_limit`. The portal binds loopback, so in
the shipped configuration every peer the portal can see reports `127.0.0.1`,
and a deployment-wide bucket of twenty that refuses every user -- admins
included -- once anyone's typos add up is a denial of service that needs no
attacker at all. A source that identifies nobody therefore counts nobody: the
per-source limit applies only to a real remote address, and the per-name
counters (which do apply to loopback) are what stands between a local caller
and an unlimited guessing run. That is not a hole so much as an honest reading
of the boundary: anything that can reach a loopback-only port already runs code
on that host, where `cplan_authenticator`'s own credentials sit in the backend
settings -- a door that does not go through this endpoint at all.

## Recovery

Blocks release on their own within one window. For the case that cannot wait --
an administrator locked out of the portal that is the tool for fixing it --
`python -m pipeline.api.setup_portal --clear-login-block <name>` clears a
counter immediately, run by the same identity that runs `setup_portal` itself
(pipeline/api/README.md, "Portal"). There is deliberately no portal endpoint
for it: the person who needs it is the person the portal is refusing.
"""

from __future__ import annotations

import ipaddress
import logging

from dataclasses import dataclass

from fastapi import Request
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from pipeline.api.setup_portal import LOGIN_GUARD_ENTRY_POINT

logger = logging.getLogger(__name__)

# The address recorded when the ASGI server reports no peer (in-process test
# clients, some socket-activated setups). One shared bucket for all of them,
# and -- like loopback -- one that is never allowed to block on its own.
UNKNOWN_SOURCE = "unknown"

# What an operator has to do when the guard's objects are missing. Printed by
# both launchers before they refuse to start, so the fix is on screen rather
# than in a traceback.
MISSING_GUARD_MESSAGE = (
    "The login throttle is not installed in this database: portal.begin_login_attempt "
    "is missing. This release adds it, and only setup_portal creates it.\n"
    "Run the one-time setup step again (setup.cmd, or:\n"
    "  python -m pipeline.api.setup_portal\n"
    ") as the same admin/superuser identity that set the database up, then start again.\n"
    "Refusing to start: a login endpoint that cannot consult its rate limit would "
    "either answer every sign-in with an error or accept unlimited password guesses."
)


@dataclass(frozen=True)
class LoginLimits:
    """Policy. See the module docstring for why these four numbers."""

    pair_failures: int = 5  # one address against one name
    username_failures: int = 20  # one name, every address
    source_failures: int = 20  # one address, every name
    window_seconds: int = 900  # 15 minutes


def client_source(request: Request) -> str:
    """The address a failed attempt is counted against.

    The transport peer, never a forwarded-for header -- see the module
    docstring's "What a source is" for both halves of why, including what the
    launchers have to do to keep this true.
    """
    client = getattr(request, "client", None)
    host = getattr(client, "host", None) if client is not None else None
    return host or UNKNOWN_SOURCE


def source_counts_toward_limit(source: str) -> bool:
    """Whether this address may block attempts on its own.

    False for loopback, for the unspecified address and for anything that is
    not an IP address at all (the test clients' `testclient`, a Unix socket
    peer, `UNKNOWN_SOURCE`): those name every caller in the deployment at once,
    so a shared budget of twenty on them is not a rate limit but a switch that
    turns sign-in off for everybody. The per-name counters still apply to every
    attempt, whatever its source.
    """
    if not source or source == UNKNOWN_SOURCE:
        return False
    try:
        address = ipaddress.ip_address(source)
    except ValueError:
        return False
    return not (address.is_loopback or address.is_unspecified)


_BEGIN_SQL = text(
    "SELECT portal.begin_login_attempt("
    ":username, :source, :username_limit, :pair_limit, :source_limit, "
    ":window_seconds, :count_source)"
)
_END_SQL = text("SELECT portal.end_login_attempt(:username, :source, :count_source)")
_INSTALLED_SQL = text(f"SELECT to_regprocedure('{LOGIN_GUARD_ENTRY_POINT}') IS NOT NULL")


def login_guard_installed(engine: Engine) -> bool:
    """Whether this database has run the `apply_portal` that creates the guard.

    Called by the launchers at startup so an installation upgraded without its
    schema step is announced there and then, instead of starting, serving its
    landing page, passing the readiness probe and answering every single
    sign-in with an error whose only trace is a traceback in a server window.
    """
    with engine.connect() as connection:
        return bool(connection.execute(_INSTALLED_SQL).scalar_one())


class LoginGuard:
    """The counters, over the engine's own (service-role) connections.

    Runs on the engine rather than a request session for the same reason
    `portal.record_sign_in` does: a login request has no `SET ROLE`'d identity
    yet -- establishing one is what login is for -- so these functions are
    granted to `cplan_authenticator`, not to `cplan_admin`.
    """

    def __init__(self, engine: Engine, limits: LoginLimits | None = None) -> None:
        self._engine = engine
        self.limits = limits if limits is not None else LoginLimits()

    @property
    def retry_after_seconds(self) -> int:
        """Advertised as a constant, not as the time actually left on the block.

        A constant keeps every throttled response byte-identical, so the
        header cannot become the one field that separates a locked real
        account from a locked imaginary one; and it is never a lie, because
        the window is the longest the caller can possibly have to wait.
        """
        return self.limits.window_seconds

    def begin_attempt(self, username: str, source: str) -> bool:
        """Reserve one attempt. False means: refuse it, do not probe anything.

        Propagates `SQLAlchemyError`: unlike `end_attempt` below, this one *is*
        the control, and a caller that cannot consult it must refuse the
        attempt rather than wave it through (see the login handlers, which
        answer 503). A database that is unreachable fails `verify_credentials`
        a moment later anyway; the case this actually guards is schema drift --
        a database that never ran the current `apply_portal` -- where silently
        serving an unlimited login endpoint would be far worse than an outage
        with a one-command fix, which is also why both launchers check for the
        same objects before they start at all.
        """
        with self._engine.begin() as connection:
            admitted = connection.execute(
                _BEGIN_SQL,
                {
                    "username": username,
                    "source": source,
                    "username_limit": self.limits.username_failures,
                    "pair_limit": self.limits.pair_failures,
                    "source_limit": self.limits.source_failures,
                    "window_seconds": self.limits.window_seconds,
                    "count_source": source_counts_toward_limit(source),
                },
            ).scalar_one()
        return bool(admitted)

    def end_attempt(self, username: str, source: str) -> None:
        """Give a reservation back -- this attempt was not a password guess.

        Swallows database errors (logged) rather than turning a *successful*
        sign-in into a 500. The exposure that creates is theoretical and
        self-limiting: `begin_attempt` just succeeded against the same pool a
        few milliseconds earlier, and the worst outcome is that one correct
        password stays counted for the rest of the window.
        """
        try:
            with self._engine.begin() as connection:
                connection.execute(
                    _END_SQL,
                    {
                        "username": username,
                        "source": source,
                        "count_source": source_counts_toward_limit(source),
                    },
                )
        except SQLAlchemyError:
            logger.exception("could not release a login attempt for %s", username)
