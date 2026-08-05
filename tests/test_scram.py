"""Passwords are hashed before they reach the server, and the hash is the one PostgreSQL would have produced.

Two things have to hold at once, and each is worthless without the other:

* **No cleartext leaves this process.** That is what keeps a password out of
  the server log -- `log_statement`, `log_min_duration_statement`, pgaudit --
  and it is checked here by recording every statement and every bound
  parameter the portal actually sends while creating an account.
* **The verifier is correct.** A malformed one is not rejected: PostgreSQL
  reads anything it cannot parse as a verifier as a *cleartext* password and
  hashes it, so the account silently ends up with a password nobody knows.
  Nothing about the shape of the string catches that, so the tests below sign
  in for real, and compare byte-for-byte against a verifier the server built
  itself for the same password, salt and iteration count.

The comparison tests are the only place in the repository that still sends a
cleartext `ALTER ROLE ... PASSWORD`: it is how PostgreSQL is asked for its own
answer, against a throwaway test cluster, which is precisely the situation the
production paths no longer need to be in.
"""

from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy.exc import ProgrammingError

from pipeline.api.app import Base
from pipeline.api.auth import AuthSettings, CredentialCheck, check_credentials
from pipeline.api.database import create_cplan_engine
from pipeline.api.scram import DEFAULT_ITERATIONS, VERIFIER_PREFIX, build_verifier, saslprep, verifier_for
from pipeline.api.setup_portal import CREATE_USER_SIGNATURE, RESET_PASSWORD_SIGNATURE, apply_portal
from pipeline.api.setup_roles import apply_roles, create_user
from pipeline.portal import app as portal_module
from pipeline.portal.app import MAX_PASSWORD_LENGTH, create_portal_app
from tests.conftest import postgres_required, postgres_test_database, scram_literal

ADMIN = "sc_admin"
ADMIN_PW = "pw-sc-admin"
VIEWER = "sc_outsider"
VIEWER_PW = "pw-sc-outsider"

# Every one of these is fed to PostgreSQL and to `build_verifier`, and the two
# answers must be identical. Each entry is a password and the string
# `pg_saslprep` turns it into.
#
# The first group is not about SASLprep at all: it covers the PBKDF2/HMAC chain
# and the SQL literal escaping the comparison below needs. Every entry after it
# pins *one named rule* in pipeline/api/scram.py -- delete the rule and that
# case stops matching the server. A case whose prepared form equals its raw
# form earns its place only when a rule has to fire to keep it that way; a
# password preparation simply does not touch would pass with SASLprep removed
# altogether and proves nothing, which is exactly what was wrong with the
# corpus this replaced.
#
# They are chosen for the rules they pin, not for realism: an administrator
# types the first one, but a verifier that only agrees with the server on ASCII
# is a lockout waiting for the first person with an umlaut in their password.
SASLPREP_CASES = {
    # name: (password, the string PostgreSQL hashes for it)
    #
    # Nothing to prepare -- the hash chain and the literal escaping instead.
    "ascii": ("pw-plain-ascii-42", "pw-plain-ascii-42"),
    "quote-and-percent": ("it's 100% fine", "it's 100% fine"),
    "latin-1-supplement": ("Ünïcödé-Paßwört", "Ünïcödé-Paßwört"),
    #
    # One rule each, from here down.
    #
    # B.1 "commonly mapped to nothing": the soft hyphen is dropped.
    "soft-hyphen-mapped-away": ("soft\u00adhyphen", "softhyphen"),
    # C.1.2 non-ASCII space: mapped to U+0020.
    "non-ascii-space": ("nbsp\u00a0space", "nbsp space"),
    # U+200B is in C.1.2 *and* in B.1. PostgreSQL applies C.1.2 first, so it
    # becomes a space; applying B.1 first deletes it instead. Pins the order.
    "zero-width-space": ("zero\u200bwidth", "zero width"),
    # NFKC: ROMAN NUMERAL NINE -> "IX".
    "nfkc-normalised": ("roman-Ⅸ", "roman-IX"),
    # NFKC again, by canonical composition rather than a compatibility mapping:
    # "e" + U+0301 has to arrive at the precomposed U+00E9 the server arrives at.
    "nfd-decomposed-accent": ("nfd-cafe\u0301", "nfd-caf\u00e9"),
    # NFKC once more, on a singleton decomposition (CJK compatibility
    # ideographs are composition exclusions, so this stays decomposed rather
    # than composing back): U+FA0B -> U+5ED3. Escaped because the two render
    # identically -- the whole point of the case would be invisible otherwise.
    "cjk-compatibility-ideograph": ("compat-\ufa0b", "compat-\u5ed3"),
    # U+0340 is prohibited (C.8), but NFKC turns it into U+0300, which is not.
    # PostgreSQL checks *before* normalising, so it refuses and hashes the raw
    # password; checking afterwards silently accepts a different string. Pins
    # the check-before-normalise order.
    "prohibited-before-normalisation": ("grave\u0340mark", "grave\u0340mark"),
    # U+1D2C is unassigned in Unicode 3.2 (table A.1), which PostgreSQL treats
    # as prohibited output -- so the raw password is hashed, not the "A" that
    # NFKC would otherwise have produced. Pins A.1 being in the prohibited set.
    "unassigned-in-unicode-3-2": ("modifier-ᴬ", "modifier-ᴬ"),
    # The same rule, for the character a real person is likeliest to reach for:
    # every emoji is unassigned in Unicode 3.2. The variation selector is what
    # an emoji keyboard actually emits, and B.1 would otherwise drop it.
    "emoji": ("lock-\U0001f512\ufe0f", "lock-\U0001f512\ufe0f"),
    # RFC 3454 section 6: a string containing a right-to-left character must
    # begin and end with one. This one begins with alef but ends in digits, so
    # preparation fails and the raw password is hashed -- soft hyphen and all.
    # Pins the bidirectional check: without it the soft hyphen would vanish.
    "bidi-violation": ("ال\u00ad42", "ال\u00ad42"),
    # A password of nothing but characters B.1 deletes maps to the empty
    # string, which PostgreSQL refuses ("don't allow empty password") rather
    # than hashing "". Pins that exit.
    "everything-mapped-away": ("\u00ad\u00ad\u00ad", "\u00ad\u00ad\u00ad"),
    # C.2.1, an ASCII control character: prohibited, so both ends fall back to
    # the raw password rather than raising. PostgreSQL's pure-ASCII shortcut
    # reaches the same string by a shorter route; either way the account this
    # password belongs to has to keep working.
    "prohibited-falls-back": ("bell\u0007inside", "bell\u0007inside"),
}


@pytest.fixture(scope="module")
def portal(tmp_path_factory):
    url, teardown = postgres_test_database(tmp_path_factory, "scram")
    engine = create_cplan_engine(url)
    Base.metadata.create_all(engine)
    apply_roles(engine)
    apply_portal(engine)
    create_user(engine, ADMIN, ADMIN_PW, "admin")
    create_user(engine, VIEWER, VIEWER_PW, "viewer")
    engine.dispose()
    app = create_portal_app(url, auth_settings=AuthSettings(secret="scram-secret"))
    with TestClient(app):
        yield app, url
    teardown()


def admin_client(app) -> TestClient:
    return signed_in(app, ADMIN, ADMIN_PW)


def signed_in(app, username: str, password: str) -> TestClient:
    client = TestClient(app)
    response = client.post("/api/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return client


def parse_verifier(stored: str) -> tuple[int, bytes]:
    """The iteration count and raw salt out of a stored `SCRAM-SHA-256$...` string."""
    assert stored.startswith(VERIFIER_PREFIX), stored[:32]
    head = stored[len(VERIFIER_PREFIX) :].split("$", 1)[0]
    iterations, encoded_salt = head.split(":")
    return int(iterations), base64.b64decode(encoded_salt)


def stored_secret(engine, username: str) -> str:
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT rolpassword FROM pg_authid WHERE rolname = :n"), {"n": username}
        ).scalar_one()


# --- SASLprep, without a server -------------------------------------------------


@pytest.mark.parametrize("case", sorted(SASLPREP_CASES))
def test_saslprep_prepares_each_case_the_way_postgresql_does(case):
    """The same corpus as the server comparison below, asserted without a server.

    This is the test that says *which string* is expected and why, so a rule
    removed from `pipeline/api/scram.py` names itself here instead of only
    surfacing as two unequal base64 blobs. It is not the authority, though --
    the comparison against PostgreSQL's own verifier is; if the two ever
    disagree, this file is what is wrong.
    """
    password, prepared = SASLPREP_CASES[case]
    assert saslprep(password) == prepared


def test_saslprep_returns_the_raw_password_when_preparation_is_impossible():
    """PostgreSQL and libpq both fall back to the unprepared password here, so
    this must too -- preparing it differently from the client is exactly the
    mismatch that makes a well-formed verifier reject the right password.

    Each of these carries a soft hyphen that preparation *would* have removed
    had it got that far, so a fallback that quietly went ahead anyway shows up
    as an unequal string instead of passing on a coincidence."""
    assert saslprep("bell\u0007in\u00adside") == "bell\u0007in\u00adside"  # C.2.1 prohibited
    assert saslprep("\u0627\u00ad1") == "\u0627\u00ad1"  # RandALCat then a digit: bidi violation
    assert saslprep("\ud800\u00ad") == "\ud800\u00ad"  # lone surrogate: C.5, and not UTF-8 either


def test_a_password_that_cannot_be_encoded_fails_without_quoting_itself():
    """The one input `build_verifier` cannot hash must not put a fragment of the
    password into a traceback -- in the module written to keep passwords out of
    logs, of all places. `UnicodeEncodeError` names the offending character in
    its own message, so it must not be what escapes, and it must not be attached
    as the cause either."""
    with pytest.raises(ValueError) as raised:
        build_verifier("secret-\ud800-tail")
    assert not isinstance(raised.value, UnicodeEncodeError)
    assert raised.value.__cause__ is None and raised.value.__context__ is None
    assert "\ud800" not in str(raised.value)
    assert "secret" not in str(raised.value)


def test_build_verifier_is_salted_and_shaped_like_postgresqls_own():
    first, second = build_verifier("same-password"), build_verifier("same-password")
    assert first != second  # a fresh random salt per call, as the server does
    assert first.startswith(f"{VERIFIER_PREFIX}{DEFAULT_ITERATIONS}:")
    assert parse_verifier(first)[1] != parse_verifier(second)[1]


# --- the verifier is byte-for-byte what the server would have stored ------------


@postgres_required
@pytest.mark.parametrize("case", sorted(SASLPREP_CASES))
def test_verifier_matches_the_one_postgresql_builds_itself(portal, case):
    """The only check that can catch a wrong hash before a person cannot sign in.

    Hand the server the cleartext, let it hash the password its own way, then
    rebuild the verifier here from the salt and iteration count it chose. Equal
    strings mean the PBKDF2/HMAC chain *and* the SASLprep step agree with
    PostgreSQL's, for this password.
    """
    app, url = portal
    password, _ = SASLPREP_CASES[case]
    name = f"sc_cmp_{case.replace('-', '_')}"
    engine = app.state.engine
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE ROLE "{name}" LOGIN')
        # Doubling '%' is for psycopg's placeholder scan, not for SQL: it runs
        # over every statement string even when no parameters are bound.
        literal = "'" + password.replace("'", "''") + "'"
        connection.exec_driver_sql(f'ALTER ROLE "{name}" PASSWORD {literal}'.replace("%", "%%"))
    try:
        postgres_built = stored_secret(engine, name)
        iterations, salt = parse_verifier(postgres_built)
        assert build_verifier(password, salt=salt, iterations=iterations) == postgres_built
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP ROLE "{name}"')


@postgres_required
def test_verifier_for_follows_the_servers_configured_iteration_count(portal):
    """`scram_iterations` is an operator's hardening dial. Hashing outside the
    server has to keep honouring it, or this change quietly reverts a decision
    somebody made on purpose and nothing anywhere reports it."""
    app, _ = portal
    with app.state.engine.connect() as connection:
        assert verifier_for(connection, "x").startswith(f"{VERIFIER_PREFIX}{DEFAULT_ITERATIONS}:")
        connection.exec_driver_sql("SET scram_iterations = 8192")
        assert verifier_for(connection, "x").startswith(f"{VERIFIER_PREFIX}8192:")


# --- the whole point: a created account can actually sign in --------------------


@postgres_required
@pytest.mark.parametrize(
    "case",
    [
        "ascii",
        "latin-1-supplement",
        "soft-hyphen-mapped-away",
        "nfkc-normalised",
        # The two the fix was about: one where the mapping order decides the
        # prepared string, one where the prohibited set does. Both are cases
        # the previous code created an account for that could never sign in.
        "zero-width-space",
        "emoji",
    ],
)
def test_account_created_through_the_portal_can_sign_in(portal, case):
    """End-to-end, through the real endpoint and against the real server: create
    the account over HTTP, then open a database session as that account with the
    password the admin typed. A verifier that is well-formed but wrong passes
    every other assertion in this file and fails only here."""
    app, url = portal
    password, _ = SASLPREP_CASES[case]
    name = f"sc_login_{case.replace('-', '_')}"
    created = admin_client(app).post(
        "/api/portal/users",
        json={"username": name, "password": password, "project": "cplan", "role": "viewer"},
    )
    assert created.status_code == 201, created.text
    assert check_credentials(url, name, password) is CredentialCheck.ACCEPTED
    assert check_credentials(url, name, password + "-not-it") is CredentialCheck.REJECTED


@postgres_required
def test_password_reset_through_the_portal_swaps_which_password_works(portal):
    app, url = portal
    admin = admin_client(app)
    assert admin.post(
        "/api/portal/users",
        json={"username": "sc_rotate", "password": "pw-before", "project": "cplan", "role": "viewer"},
    ).status_code == 201
    assert admin.post("/api/portal/users/sc_rotate/password", json={"password": "pw-after"}).status_code == 200

    assert check_credentials(url, "sc_rotate", "pw-after") is CredentialCheck.ACCEPTED
    assert check_credentials(url, "sc_rotate", "pw-before") is CredentialCheck.REJECTED


@postgres_required
def test_bootstrap_cli_stores_a_verifier_and_the_account_signs_in(portal):
    """`setup_roles.create_user` builds its own `CREATE ROLE ... PASSWORD` DDL
    rather than calling the portal functions, so it needs its own proof: the
    stored secret is a verifier (the cleartext was never in the statement) and
    the password still opens a session."""
    app, url = portal
    engine = app.state.engine
    create_user(engine, "sc_cli", "pw-cli-bootstrap", "viewer")
    assert stored_secret(engine, "sc_cli").startswith(VERIFIER_PREFIX)
    assert check_credentials(url, "sc_cli", "pw-cli-bootstrap") is CredentialCheck.ACCEPTED


# --- the cleartext never travels ------------------------------------------------


@postgres_required
def test_no_statement_the_portal_sends_carries_the_cleartext_password(portal):
    """What actually keeps the password out of the log.

    A statement is logged with its text and, under `log_statement = 'all'`,
    its bound parameters -- so "not in the log" means "not in either". Record
    both for every statement the portal issues while creating an account, and
    require the password to appear in none of them, while the verifier does.
    """
    app, _ = portal
    password = "pw-never-logged-91"
    recorded: list[tuple[str, object]] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        recorded.append((statement, parameters))

    event.listen(app.state.engine, "before_cursor_execute", record)
    try:
        created = admin_client(app).post(
            "/api/portal/users",
            json={"username": "sc_quiet", "password": password, "project": "cplan", "role": "viewer"},
        )
        assert created.status_code == 201, created.text
    finally:
        event.remove(app.state.engine, "before_cursor_execute", record)

    assert recorded, "nothing was recorded -- the listener never fired, so this proves nothing"
    haystack = "\n".join(f"{statement} {parameters!r}" for statement, parameters in recorded)
    assert password not in haystack
    assert VERIFIER_PREFIX in haystack  # the verifier did travel, so the right call was observed


# --- and cleartext is refused rather than silently passed on --------------------


@postgres_required
def test_portal_functions_refuse_a_cleartext_password(portal):
    """The guard that stops the leak coming back through a caller that forgets
    to hash. Without it, a plain string would simply be interpolated into the
    DDL again -- working perfectly, and disclosing the password to the log."""
    app, _ = portal
    engine = app.state.engine
    connection = engine.connect()
    try:
        connection.exec_driver_sql(f'SET ROLE "{ADMIN}"')
        for sql in (
            "SELECT portal.create_user('sc_cleartext', 'hunter2', 'cplan', 'viewer')",
            f"SELECT portal.reset_password('{ADMIN}', 'hunter2')",
            # Shaped like a verifier but not parseable as one -- PostgreSQL
            # would take this for a cleartext password and hash it, locking the
            # account out with no error at all.
            "SELECT portal.create_user('sc_cleartext', 'SCRAM-SHA-256$notavalidverifier', 'cplan', 'viewer')",
        ):
            with pytest.raises(ProgrammingError) as exc:
                connection.exec_driver_sql(sql)
            assert exc.value.orig.sqlstate == "P0001"
            assert "SCRAM-SHA-256 verifier" in str(exc.value.orig)
            assert "hunter2" not in str(exc.value.orig)  # the message must not echo what it refused
            connection.rollback()
        # A verifier goes through, so the refusals above were about the value
        # and not about the caller or the arguments around it.
        connection.exec_driver_sql(
            f"SELECT portal.create_user('sc_cleartext', {scram_literal('pw-ok')}, 'cplan', 'viewer')"
        )
        connection.commit()
    finally:
        connection.rollback()
        connection.exec_driver_sql("RESET ROLE")
        connection.commit()
        connection.close()
    assert stored_secret(engine, "sc_cleartext").startswith(VERIFIER_PREFIX)


@postgres_required
def test_a_refused_cleartext_reset_leaves_the_existing_password_working(portal):
    """The refusal must be a no-op, not a half-applied change: an admin whose
    client is out of date gets an error, and the account they were resetting is
    still the account it was."""
    app, url = portal
    admin = admin_client(app)
    assert admin.post(
        "/api/portal/users",
        json={"username": "sc_untouched", "password": "pw-untouched", "project": "cplan", "role": "viewer"},
    ).status_code == 201
    before = stored_secret(app.state.engine, "sc_untouched")

    connection = app.state.engine.connect()
    try:
        connection.exec_driver_sql(f'SET ROLE "{ADMIN}"')
        with pytest.raises(ProgrammingError):
            connection.exec_driver_sql("SELECT portal.reset_password('sc_untouched', 'pw-cleartext')")
        connection.rollback()
    finally:
        connection.exec_driver_sql("RESET ROLE")
        connection.commit()
        connection.close()

    assert stored_secret(app.state.engine, "sc_untouched") == before
    assert check_credentials(url, "sc_untouched", "pw-untouched") is CredentialCheck.ACCEPTED
    assert check_credentials(url, "sc_untouched", "pw-cleartext") is CredentialCheck.REJECTED


# --- hashing is bounded work, done only for a caller entitled to it -------------
#
# Hashing runs in the request handler, before the statement Postgres would
# refuse. SASLprep (pipeline/api/scram.py) is a per-character Python loop over
# nine `stringprep` predicates and holds the GIL for its whole run, so its cost
# is linear in the length of the submitted password and is paid on the one
# process that also serves /api/login and every page. Unbounded, and reachable
# before the authorization check, that is a signed-in viewer's denial of
# service against the administrators. Two independent things stop it, and each
# of the tests below pins one of them.


def _count_hashes(monkeypatch) -> list[str]:
    """Record every password `verifier_for` is asked to hash, and hash nothing.

    Counting calls is the assertion that matters: "was refused" and "was
    refused *before the work*" look identical from the outside, and it is the
    ordering that this whole section is about.
    """
    hashed: list[str] = []

    def record(executor, password: str) -> str:
        hashed.append(password)
        return build_verifier("stand-in-not-the-real-password")

    monkeypatch.setattr(portal_module, "verifier_for", record)
    return hashed


@postgres_required
@pytest.mark.parametrize(
    "method,path,payload",
    [
        ("create", "/api/portal/users", {"username": "sc_nope", "project": "cplan", "role": "viewer"}),
        ("reset", f"/api/portal/users/{ADMIN}/password", {}),
    ],
)
def test_a_non_admin_is_refused_before_their_password_is_hashed(portal, monkeypatch, method, path, payload):
    """The ordering fix. A viewer holds no EXECUTE on either function, so both
    calls end in 403 either way -- what is asserted here is that no hashing was
    done on the way to that 403."""
    app, _ = portal
    hashed = _count_hashes(monkeypatch)
    response = signed_in(app, VIEWER, VIEWER_PW).post(path, json={**payload, "password": "pw-attacker"})
    assert response.status_code == 403, response.text
    assert response.json()["detail"]["code"] == "forbidden"
    assert hashed == [], f"hashed {len(hashed)} password(s) for a caller that was going to be refused"


@postgres_required
def test_the_privilege_precheck_agrees_with_the_execute_check_it_stands_in_for(portal):
    """`has_function_privilege` is asked instead of waiting for 42501, so the
    two must answer the same thing -- including about the *signature that
    actually exists*, which is why both read setup_portal's own constant. A
    typo'd signature raises 42883 rather than answering False, and would turn
    every reset into a 500."""
    app, _ = portal
    with app.state.engine.connect() as connection:
        for signature in (CREATE_USER_SIGNATURE, RESET_PASSWORD_SIGNATURE):
            for role, expected in ((ADMIN, True), (VIEWER, False)):
                connection.exec_driver_sql(f'SET ROLE "{role}"')
                granted = connection.execute(
                    text("SELECT has_function_privilege(CAST(:signature AS text), 'EXECUTE')"),
                    {"signature": signature},
                ).scalar()
                connection.exec_driver_sql("RESET ROLE")
                assert granted is expected, f"{role} on {signature}"


@postgres_required
@pytest.mark.parametrize(
    "path,payload",
    [
        ("/api/portal/users", {"username": "sc_toolong", "project": "cplan", "role": "viewer"}),
        (f"/api/portal/users/{ADMIN}/password", {}),
    ],
)
def test_an_oversized_password_is_rejected_before_it_is_hashed(portal, monkeypatch, path, payload):
    """The bound. This one is asserted for an *admin* on purpose: the length
    limit is not an authorization rule, it is what stops the request body from
    deciding how much CPU the process spends, so it has to hold for the caller
    who is allowed in as much as for the one who is not. Being a Pydantic
    constraint, it is enforced during request validation -- the endpoint body
    never runs, so nothing is hashed."""
    app, _ = portal
    hashed = _count_hashes(monkeypatch)
    response = admin_client(app).post(path, json={**payload, "password": "x" * (MAX_PASSWORD_LENGTH + 1)})
    assert response.status_code == 422, response.text
    assert hashed == []


@postgres_required
def test_a_password_at_the_limit_still_creates_an_account_that_signs_in(portal):
    """The bound has to be a limit on abuse and not on passwords: the longest
    accepted password must still work end to end, or this would have traded a
    denial of service for a lockout."""
    app, url = portal
    password = "sc-long-" + "p" * (MAX_PASSWORD_LENGTH - len("sc-long-"))
    assert len(password) == MAX_PASSWORD_LENGTH
    created = admin_client(app).post(
        "/api/portal/users",
        json={"username": "sc_maxlen", "password": password, "project": "cplan", "role": "viewer"},
    )
    assert created.status_code == 201, created.text
    assert check_credentials(url, "sc_maxlen", password) is CredentialCheck.ACCEPTED
