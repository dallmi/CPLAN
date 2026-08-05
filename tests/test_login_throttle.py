"""Failed-login throttling on the portal's and the studio's credential endpoints.

Every test here runs at the real policy values (5 per address-and-name, 20 per
name, 20 per address, a 15-minute window) and none of them sleeps. "Fifteen
minutes later" is `rewind()`: the windows are measured against the database's
own `now()` -- the only clock every process in the deployment shares, and the
one clock a workstation cannot set -- so a test moves time by moving the stored
window starts backwards instead. That is a design requirement, not a testing
trick: a lockout whose release can only be observed by waiting is a lockout
nobody ever regression-tests.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import make_url, text
from sqlalchemy.exc import ProgrammingError

from pipeline.api.app import Base, create_app
from pipeline.api.auth import AuthSettings, CredentialCheck, check_credentials
from pipeline.api.database import create_cplan_engine
from pipeline.api.login_guard import LoginLimits
from pipeline.api.setup_portal import apply_portal, clear_login_block
from pipeline.api.setup_roles import apply_roles, create_user
from pipeline.portal.app import create_portal_app
from tests.conftest import postgres_required, postgres_test_database

pytestmark = postgres_required

LIMITS = LoginLimits()
SECRET = "throttle-secret"
GOOD = "pw-real-one"
BAD = "pw-not-it"

# Addresses that count as an identifying source (documentation ranges), and one
# that does not: the portal binds loopback, so 127.0.0.1 is every user at once
# and is deliberately never allowed to block on its own.
ATTACKER = "203.0.113.1"
OWNER = "198.51.100.7"
LOOPBACK = "127.0.0.1"


@pytest.fixture(scope="module")
def portal(tmp_path_factory):
    url, teardown = postgres_test_database(tmp_path_factory, "throttle")
    engine = create_cplan_engine(url)
    Base.metadata.create_all(engine)
    apply_roles(engine)
    apply_portal(engine)
    create_user(engine, "lt_user", GOOD, "viewer")
    create_user(engine, "lt_other", GOOD, "viewer")
    engine.dispose()
    app = create_portal_app(url, auth_settings=AuthSettings(secret=SECRET))
    with TestClient(app):
        yield app, url
    teardown()


@pytest.fixture(autouse=True)
def fresh_counters(portal):
    """Start every test with nothing left over from the one before.

    The counters are shared state in one database for the whole module. This
    uses the operator's own release path (`--clear-login-block --all`), so the
    reset the tests rely on is the reset an administrator actually has.
    """
    clear_login_block(portal[0].state.engine, None)


def rewind(app, seconds: int) -> None:
    """Move every live counter `seconds` into the past.

    Equivalent to the server clock moving forward, which is what the windows
    are measured against -- and the only way to simulate it that a caller
    cannot also perform in production, which is the point: the SQL functions
    take no timestamp from their caller.
    """
    with app.state.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE portal.login_attempts "
                "SET window_started_at = window_started_at - make_interval(secs => :s)"
            ),
            {"s": seconds},
        )


def counters(app) -> dict[tuple[str, str], int]:
    with app.state.engine.connect() as connection:
        return {
            (row.kind, row.key): row.attempts
            for row in connection.execute(text("SELECT kind, key, attempts FROM portal.login_attempts"))
        }


def attempt(app, username: str, password: str, source: str):
    """One login attempt from a named source address.

    A fresh client per attempt, and deliberately not used as a context manager
    -- entering one runs the app's lifespan, whose shutdown half disposes the
    shared engine the module fixture is still holding.
    """
    client = TestClient(app, client=(source, 4444))
    return client.post("/api/login", json={"username": username, "password": password})


def burn(app, username: str, source: str, count: int) -> None:
    for i in range(count):
        assert attempt(app, username, BAD, source).status_code == 401, f"attempt {i + 1}"


def test_five_wrong_passwords_from_one_address_lock_that_address_out(portal):
    app, _ = portal
    burn(app, "lt_user", ATTACKER, LIMITS.pair_failures)

    throttled = attempt(app, "lt_user", BAD, ATTACKER)
    assert throttled.status_code == 429, throttled.text
    assert throttled.json() == {"detail": {"code": "too_many_attempts"}}
    assert throttled.headers["retry-after"] == str(LIMITS.window_seconds)

    # The block is on the attempt, not on the guess: the right password from
    # that same address is refused too, or the limit would only be a limit on
    # wrong guesses and none at all on finding the right one.
    assert attempt(app, "lt_user", GOOD, ATTACKER).status_code == 429
    # ...and only that name from that address. A different account is untouched.
    assert attempt(app, "lt_other", GOOD, ATTACKER).status_code == 200


def test_a_lockout_does_not_reach_the_owner_at_their_own_address(portal):
    """The property that keeps this a rate limit rather than a weapon.

    Anyone who knows a username can send it wrong passwords. If that locked the
    account itself, every account with a guessable name could be denied service
    by a stranger, on a portal with no self-service recovery -- so five
    failures stop the address that produced them, and the account-wide counter
    that does apply to everybody sits four times higher (see the backstop test).
    """
    app, _ = portal
    burn(app, "lt_user", ATTACKER, LIMITS.pair_failures)
    assert attempt(app, "lt_user", BAD, ATTACKER).status_code == 429

    signed_in = attempt(app, "lt_user", GOOD, OWNER)
    assert signed_in.status_code == 200, signed_in.text
    assert signed_in.json() == {"username": "lt_user"}
    assert signed_in.cookies.get("cplan_session")


def test_the_lock_releases_on_its_own_and_the_real_password_then_works(portal):
    app, _ = portal
    burn(app, "lt_user", ATTACKER, LIMITS.pair_failures)
    assert attempt(app, "lt_user", GOOD, ATTACKER).status_code == 429

    # One second short of the window: still locked. One second past it: in.
    rewind(app, LIMITS.window_seconds - 1)
    assert attempt(app, "lt_user", GOOD, ATTACKER).status_code == 429
    rewind(app, 2)
    released = attempt(app, "lt_user", GOOD, ATTACKER)
    assert released.status_code == 200, released.text


def test_a_wrong_password_after_the_window_is_a_plain_401_again(portal):
    """The lockout expires into "normal", not into "one strike and out"."""
    app, _ = portal
    burn(app, "lt_user", ATTACKER, LIMITS.pair_failures)
    assert attempt(app, "lt_user", BAD, ATTACKER).status_code == 429

    rewind(app, LIMITS.window_seconds + 1)
    assert attempt(app, "lt_user", BAD, ATTACKER).status_code == 401
    assert attempt(app, "lt_user", GOOD, ATTACKER).status_code == 200


def test_hammering_cannot_hold_a_lockout_or_reach_the_owner(portal):
    """Four simulated hours of continuous guessing against a known username.

    Two things have to hold throughout, and an earlier revision held neither.
    The window used to slide from the last *counted* failure, so each failure
    that aged out admitted exactly one new one, which was counted and started
    the window again: the account stayed locked for as long as the attacker
    kept typing, and the only way out was psql. And the lockout applied to
    every address, so the owner was locked out with it.

    Now: the window is fixed, so the attacker's budget is the same five per
    fifteen minutes however hard they hammer, and the owner -- at their own
    address -- is never once refused.
    """
    app, _ = portal
    counted = 0
    for minute in range(4 * 60):
        rewind(app, 60)
        response = attempt(app, "lt_user", BAD, ATTACKER)
        assert response.status_code in (401, 429), response.text
        counted += response.status_code == 401
        owner = attempt(app, "lt_user", GOOD, OWNER)
        assert owner.status_code == 200, f"minute {minute}: owner refused with {owner.text}"

    # Four hours is sixteen windows; five guesses each is the policy, and the
    # hammering in between bought exactly nothing.
    assert counted <= 5 * 17, counted
    assert counted >= 5 * 15, counted


def test_a_distributed_run_on_one_account_hits_the_account_wide_backstop(portal):
    """The counter the per-address one cannot see.

    Four addresses each spend their five without ever tripping their own pair
    counter twice; the twenty-first attempt on that name is refused wherever it
    comes from, because at that point it is not somebody mistyping.
    """
    app, _ = portal
    sources = [f"203.0.113.{n}" for n in range(20, 24)]
    assert len(sources) * LIMITS.pair_failures == LIMITS.username_failures
    for source in sources:
        burn(app, "lt_user", source, LIMITS.pair_failures)

    blocked = attempt(app, "lt_user", GOOD, "203.0.113.99")
    assert blocked.status_code == 429, blocked.text
    # And only that account: the four addresses have spent nothing on anyone else.
    assert attempt(app, "lt_other", GOOD, "203.0.113.99").status_code == 200


def test_spraying_many_usernames_from_one_source_is_caught(portal):
    """One guess against each of many accounts never trips a per-name counter
    -- the per-source counter is the only thing that sees it."""
    app, _ = portal
    source = "203.0.113.6"
    for i in range(LIMITS.source_failures):
        response = attempt(app, f"lt_spray{i:02d}", BAD, source)
        assert response.status_code == 401, f"spray {i}: {response.text}"

    # The next attempt from that address is refused even though it names a real
    # account and carries its real password -- the address is out of budget.
    blocked = attempt(app, "lt_other", GOOD, source)
    assert blocked.status_code == 429, blocked.text
    assert blocked.json() == {"detail": {"code": "too_many_attempts"}}

    # The same credentials from any other address still work: the block
    # follows the sprayer, it does not disable the accounts they touched.
    assert attempt(app, "lt_other", GOOD, "198.51.100.9").status_code == 200


def test_loopback_is_not_one_deployment_wide_bucket(portal):
    """The portal binds 127.0.0.1, so every peer it can see is 127.0.0.1.

    A shared per-source budget on that key would mean twenty typos anywhere in
    the deployment -- four people exhausting their five, or one person spraying
    from any workstation -- answered every remaining user, administrators
    included, with 429 until the window ran out, with no operator override and
    no attacker skill required. The per-name counters still apply to loopback;
    the shared one does not.
    """
    app, _ = portal
    for i in range(LIMITS.source_failures * 2):
        assert attempt(app, f"lt_local{i:02d}", BAD, LOOPBACK).status_code == 401

    assert attempt(app, "lt_user", GOOD, LOOPBACK).status_code == 200
    assert ("source", LOOPBACK) not in counters(app)

    # ...but a name guessed over and over from loopback is still stopped.
    burn(app, "lt_other", LOOPBACK, LIMITS.pair_failures)
    assert attempt(app, "lt_other", BAD, LOOPBACK).status_code == 429


def test_a_successful_sign_in_leaks_nothing_about_the_account(portal):
    """The counter must not become the oracle the uniform 429 avoided.

    A counter that a successful login *cleared* would answer, to anyone who can
    count 401s, both "is this a real account?" and "did its owner sign in in
    the last quarter of an hour?" -- cheaply, repeatedly, and from any address.
    A sign-in gives back only the reservation it took, so the headroom an
    onlooker measures is the same either way.
    """
    app, _ = portal

    def headroom(name: str, source: str) -> int:
        """How many more 401s this address can spend on this name."""
        spent = 0
        while attempt(app, name, BAD, source).status_code == 401:
            spent += 1
            assert spent < 20, "the counter never blocked"
        return spent

    burn(app, "lt_user", ATTACKER, 4)
    assert attempt(app, "lt_user", GOOD, OWNER).status_code == 200  # the owner signs in
    with_sign_in = headroom("lt_user", ATTACKER)

    clear_login_block(app.state.engine, None)
    burn(app, "lt_user", ATTACKER, 4)
    without_sign_in = headroom("lt_user", ATTACKER)

    clear_login_block(app.state.engine, None)
    burn(app, "lt_ghost_account", ATTACKER, 4)
    ghost = headroom("lt_ghost_account", ATTACKER)

    assert with_sign_in == without_sign_in == ghost == 1


def test_concurrent_attempts_cannot_exceed_the_limit(portal):
    """Check-then-act is the classic way a rate limit turns out not to be one.

    Thirty attempts fired at once against one name: with the count read on one
    connection, the credential probe run, and the count written back after, all
    thirty read the same pre-increment value and all thirty were admitted --
    making the enforced ceiling the server's thread pool (and multiplying again
    per process), not the policy. The reservation is taken in the same
    statement that reads the counter, so the answer is the same as if they had
    arrived one at a time.
    """
    app, _ = portal
    with ThreadPoolExecutor(max_workers=30) as pool:
        codes = [
            future.result().status_code
            for future in [pool.submit(attempt, app, "lt_user", BAD, ATTACKER) for _ in range(30)]
        ]
    assert codes.count(401) == LIMITS.pair_failures, codes
    assert codes.count(429) == 30 - LIMITS.pair_failures, codes


def test_a_wrong_password_is_classified_as_a_guess_against_a_real_server(portal):
    """The distinction the whole limit rests on, checked where it actually breaks.

    A failure during *connect* carries no `PGresult`, so libpq exposes no error
    fields and psycopg leaves `sqlstate` as `None` -- for the wrong-password
    case above all. Classifying on `sqlstate` alone therefore called every
    wrong password "the database did not answer", the handler handed the
    reservation back, and the counters counted nothing at all: an unlimited
    login endpoint that answered 503. No amount of stubbing sees this; only a
    real server does, which is why the assertion is here and not in
    tests/test_auth.py.
    """
    _, url = portal
    assert check_credentials(url, "lt_user", BAD) is CredentialCheck.REJECTED
    assert check_credentials(url, "lt_ghost_account", BAD) is CredentialCheck.REJECTED
    assert check_credentials(url, "lt_user", GOOD) is CredentialCheck.ACCEPTED
    # A server that is not there is still told apart from a rejection -- the
    # property that keeps an outage from locking a real account out past it.
    unreachable = make_url(url).set(port=1)
    assert check_credentials(unreachable, "lt_user", GOOD) is CredentialCheck.UNAVAILABLE


def test_a_database_that_could_not_answer_is_not_counted_as_a_guess(portal, monkeypatch):
    """`verify_credentials` returned False for an unreachable server exactly as
    it did for a wrong password, so a pg restart or an exhausted connection
    limit spent a real user's budget on the server's own outage and locked the
    account for fifteen minutes past recovery."""
    app, _ = portal
    from pipeline.portal import app as portal_module

    monkeypatch.setattr(
        portal_module, "check_credentials", lambda *_: CredentialCheck.UNAVAILABLE
    )
    for _ in range(LIMITS.pair_failures * 2):
        refused = attempt(app, "lt_user", GOOD, ATTACKER)
        assert refused.status_code == 503, refused.text
        assert refused.json() == {"detail": {"code": "login_unavailable"}}
    assert counters(app) == {}

    monkeypatch.undo()
    # The outage cost the account nothing: a full budget is still there.
    burn(app, "lt_user", ATTACKER, LIMITS.pair_failures)
    assert attempt(app, "lt_user", GOOD, ATTACKER).status_code == 429


def test_a_throttled_response_cannot_tell_a_real_username_from_a_fake_one(portal, monkeypatch):
    """Constraint: the throttle must not become the enumeration oracle the
    401 path was careful not to be.

    Both halves are checked. The response: same status, same body, same
    headers that could possibly differ. And the timing: the only thing on this
    endpoint that costs measurable time is the credential probe, which opens a
    real database connection -- so instead of timing anything (flaky, and it
    would need real seconds), this asserts it is never called for either
    throttled request. Equal work, therefore equal time, deterministically.
    """
    app, _ = portal
    for name in ("lt_user", "lt_ghost_account"):
        burn(app, name, ATTACKER, LIMITS.pair_failures)
    # Ten failures from one address, still under the twenty it may spend -- so
    # what follows is the per-name block, not the per-source one.

    from pipeline.portal import app as portal_module

    calls: list[str] = []

    def spy(url, username, password):  # pragma: no cover - must never run
        calls.append(username)
        return CredentialCheck.REJECTED

    monkeypatch.setattr(portal_module, "check_credentials", spy)

    real = attempt(app, "lt_user", BAD, ATTACKER)
    fake = attempt(app, "lt_ghost_account", BAD, ATTACKER)

    assert calls == [], "a throttled attempt must not reach the credential probe"
    assert real.status_code == fake.status_code == 429
    assert real.json() == fake.json()
    for header in ("retry-after", "content-type", "content-length"):
        assert real.headers[header] == fake.headers[header], header


def test_the_counter_is_shared_by_a_second_process(portal):
    """The state is in the database, so it is one limit for the deployment.

    A second `create_portal_app` on the same URL is what a second worker, a
    second portal process, or a second host would be. An in-process counter
    would give each of them a private allowance and quietly multiply every
    threshold by the number of processes; here the fifth failure locks the
    address whichever of them saw the first four.
    """
    app_one, url = portal
    app_two = create_portal_app(url, auth_settings=AuthSettings(secret=SECRET))
    # The lifespan's shutdown half disposes app_two's own engine on exit.
    with TestClient(app_two):
        for _ in range(3):
            assert attempt(app_one, "lt_user", BAD, ATTACKER).status_code == 401
        for _ in range(2):
            assert attempt(app_two, "lt_user", BAD, ATTACKER).status_code == 401

        # Five between them: both doors are now shut, for the right password.
        assert attempt(app_two, "lt_user", GOOD, ATTACKER).status_code == 429
        assert attempt(app_one, "lt_user", GOOD, ATTACKER).status_code == 429


def test_the_studio_login_shares_the_same_counters(portal):
    """The studio authenticates the same roles through the same probe and mints
    the same `cplan_session` cookie the portal accepts, on a different port --
    so a limit that only the portal enforced was bypassed by changing the port
    number, and the guesses were redeemable as a portal session."""
    app, url = portal
    studio = create_app(url, auth_settings=AuthSettings(secret=SECRET))
    with TestClient(studio):
        for _ in range(LIMITS.pair_failures):
            assert attempt(studio, "lt_user", BAD, ATTACKER).status_code == 401
        throttled = attempt(studio, "lt_user", GOOD, ATTACKER)
        assert throttled.status_code == 429, throttled.text
        assert throttled.headers["retry-after"] == str(LIMITS.window_seconds)
        # Same budget, not a second one: the portal is shut for that address too.
        assert attempt(app, "lt_user", GOOD, ATTACKER).status_code == 429


def test_login_is_refused_when_the_limiter_cannot_be_consulted(portal):
    """Fail closed. A database that never ran the current `apply_portal` has
    no throttle, and serving an unlimited login endpoint on it silently is
    worse than an outage -- which is also why both launchers now check for
    these objects before they serve anything at all."""
    app, _ = portal
    engine = app.state.engine
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "DROP FUNCTION portal.begin_login_attempt"
            "(text, text, integer, integer, integer, integer, boolean)"
        )
    try:
        refused = attempt(app, "lt_user", GOOD, ATTACKER)
        assert refused.status_code == 503, refused.text
        assert refused.json() == {"detail": {"code": "login_unavailable"}}
    finally:
        apply_portal(engine)  # restore for whatever runs next
    assert attempt(app, "lt_user", GOOD, ATTACKER).status_code == 200


def test_an_operator_can_release_a_lockout_without_waiting(portal):
    """The way out for the case waiting cannot fix: an administrator locked out
    of the portal that is the tool for fixing it. Not reachable through the
    portal itself -- the person who needs it is the person it is refusing."""
    app, _ = portal
    burn(app, "lt_user", ATTACKER, LIMITS.pair_failures)
    assert attempt(app, "lt_user", GOOD, ATTACKER).status_code == 429

    assert clear_login_block(app.state.engine, "lt_user") == 2  # the name and the pair
    assert attempt(app, "lt_user", GOOD, ATTACKER).status_code == 200


def test_the_counter_table_is_pruned_and_readable_by_nobody_directly(portal):
    """Two properties of the store itself.

    It forgets: a counter that can no longer block anything is deleted by the
    next attempt, so the table holds submitted usernames only while they are
    still capable of blocking something (a password typed into the wrong box is
    not kept for weeks) and it cannot grow without bound. And it is not a
    roster: a signed-in non-admin with psql must not be able to read who has
    been failing to log in -- the SECURITY DEFINER functions are the only way
    in.
    """
    app, _ = portal
    engine = app.state.engine
    burn(app, "lt_prune_probe", ATTACKER, 3)
    assert counters(app)[("username", "lt_prune_probe")] == 3

    rewind(app, LIMITS.window_seconds * 2 + 1)
    assert attempt(app, "lt_user", BAD, OWNER).status_code == 401
    assert ("username", "lt_prune_probe") not in counters(app), "stale counters should be pruned"

    connection = engine.connect()
    try:
        connection.exec_driver_sql('SET ROLE "lt_user"')
        connection.commit()
        with pytest.raises(ProgrammingError) as exc:
            connection.exec_driver_sql("SELECT count(*) FROM portal.login_attempts")
        assert exc.value.orig.sqlstate == "42501"
    finally:
        connection.rollback()
        connection.exec_driver_sql("RESET ROLE")
        connection.commit()
        connection.close()
