"""Build the SCRAM-SHA-256 verifier PostgreSQL stores, so no cleartext password ever enters a SQL statement.

`CREATE ROLE ... PASSWORD 'secret'` and `ALTER ROLE ... PASSWORD 'secret'`
carry the cleartext inside the statement *text*. Statement text is what gets
logged -- `log_statement = 'ddl'` or `'all'`, a low enough
`log_min_duration_statement`, or any auditing extension (pgaudit logs
statements executed inside functions too, which is exactly where the portal's
`format(... %L)` DDL is built) -- and the server log is a file operators read
routinely and central collection ships onwards. A password that reaches it is
disclosed to everyone who can read a log, forever, with no trace of the
disclosure.

PostgreSQL accepts an already-hashed verifier anywhere it accepts a password:
`encrypt_password()` asks `get_password_type()` what it was handed and stores
anything that parses as a verifier verbatim, whatever `password_encryption`
says. So hashing here means the cleartext stops at this process boundary, and
the only thing that travels to the server -- and into any log -- is the same
string that would have ended up in `pg_authid.rolpassword` anyway.

The format is RFC 5802 (SCRAM) / RFC 7677 (SCRAM-SHA-256) in PostgreSQL's own
storage encoding (`src/common/scram-common.c`):

    SCRAM-SHA-256$<iterations>:<b64 salt>$<b64 StoredKey>:<b64 ServerKey>

    SaltedPassword = PBKDF2-HMAC-SHA-256(SASLprep(password), salt, iterations)
    ClientKey      = HMAC-SHA-256(SaltedPassword, "Client Key")
    StoredKey      = SHA-256(ClientKey)
    ServerKey      = HMAC-SHA-256(SaltedPassword, "Server Key")

Getting any of that wrong fails *silently and totally*: a string PostgreSQL
cannot parse as a verifier is classified as `PASSWORD_TYPE_PLAINTEXT` and
hashed as if it were the password, so the account ends up with a password
nobody knows, no error is raised anywhere, and the first symptom is a person
who cannot sign in. That is why the tests for this module prove a real sign-in
end to end and compare byte-for-byte against a verifier the server built
itself, rather than asserting on the shape of the string.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import stringprep
import unicodedata
from typing import Protocol

from sqlalchemy import text

VERIFIER_PREFIX = "SCRAM-SHA-256$"

# PostgreSQL's own default for the `scram_iterations` setting. Only the
# fallback: `verifier_for` below asks the server what it is actually
# configured for.
DEFAULT_ITERATIONS = 4096

_SALT_BYTES = 16  # what PostgreSQL generates itself (SCRAM_DEFAULT_SALT_LEN)
_KEY_BYTES = 32  # SHA-256 digest length

_PROHIBITED_TABLES = (
    stringprep.in_table_c12,  # non-ASCII space (mapped above; a leftover means normalisation produced one)
    stringprep.in_table_c21_c22,  # control characters, ASCII and non-ASCII
    stringprep.in_table_c3,  # private use
    stringprep.in_table_c4,  # non-character code points
    stringprep.in_table_c5,  # surrogate codes
    stringprep.in_table_c6,  # inappropriate for plain text
    stringprep.in_table_c7,  # inappropriate for canonical representation
    stringprep.in_table_c8,  # change display properties / deprecated
    stringprep.in_table_c9,  # tagging characters
)


class _Executor(Protocol):
    """The single method `server_iterations` needs, shared by Session and Connection."""

    def execute(self, statement, /, *args, **kwargs): ...  # pragma: no cover - typing only


def _bidi_ok(prepared: str) -> bool:
    """RFC 3454 section 6: a string with any RandALCat character must have no LCat character and must both start and end with one."""
    if not any(stringprep.in_table_d1(character) for character in prepared):
        return True
    if any(stringprep.in_table_d2(character) for character in prepared):
        return False
    return stringprep.in_table_d1(prepared[0]) and stringprep.in_table_d1(prepared[-1])


def saslprep(password: str) -> str:
    """RFC 4013 SASLprep, including the fallback PostgreSQL and libpq both make.

    Both ends of a SCRAM exchange prepare the password this way before hashing
    it, so this has to agree with them: a verifier built from a differently
    prepared string is perfectly well-formed and simply never matches what the
    client sends, which is the silent-lockout failure this module's docstring
    warns about.

    The fallback is part of that agreement, not laxness. `pg_saslprep`
    returning anything other than `SASLPREP_SUCCESS` -- invalid UTF-8, a
    prohibited character, a bidirectional violation -- leaves the *raw*
    password in place on both sides (`pg_be_scram_build_secret` on the server,
    `build_client_final_message` in libpq), so this returns the input unchanged
    in exactly those cases instead of raising.

    Pure-ASCII passwords -- everything the portal generates, and effectively
    everything an administrator types -- come back unchanged whichever way the
    logic runs: no mapping table below contains an ASCII character, NFKC is the
    identity on ASCII, and an ASCII control character is prohibited, which
    lands on the fallback that returns the input. The interesting paths only
    ever execute for a password that genuinely carries non-ASCII text.
    """
    try:
        mapped = "".join(
            " " if stringprep.in_table_c12(character) else character
            for character in password
            if not stringprep.in_table_b1(character)  # "commonly mapped to nothing"
        )
        prepared = unicodedata.normalize("NFKC", mapped)
        if any(table(character) for character in prepared for table in _PROHIBITED_TABLES):
            return password
        if not _bidi_ok(prepared):
            return password
        prepared.encode("utf-8")  # unencodable (lone surrogate) is PostgreSQL's invalid-UTF-8 case
    except (UnicodeError, ValueError):
        return password
    return prepared


def build_verifier(password: str, *, salt: bytes | None = None, iterations: int = DEFAULT_ITERATIONS) -> str:
    """The string to hand PostgreSQL in place of `password`.

    `salt` exists for the tests, which rebuild a verifier the server already
    produced and compare the two; leave it None in production so every call
    draws a fresh cryptographically random salt, as PostgreSQL would.
    """
    if iterations < 1:
        raise ValueError("iterations must be a positive integer")
    if salt is None:
        salt = secrets.token_bytes(_SALT_BYTES)
    salted = hashlib.pbkdf2_hmac("sha256", saslprep(password).encode("utf-8"), salt, iterations, dklen=_KEY_BYTES)
    client_key = hmac.new(salted, b"Client Key", hashlib.sha256).digest()
    stored_key = hashlib.sha256(client_key).digest()
    server_key = hmac.new(salted, b"Server Key", hashlib.sha256).digest()
    return f"{VERIFIER_PREFIX}{iterations}:{_b64(salt)}${_b64(stored_key)}:{_b64(server_key)}"


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def server_iterations(executor: _Executor) -> int:
    """What this server would have used had it hashed the password itself.

    `scram_iterations` is a PostgreSQL 16+ setting an operator may raise well
    above the 4096 default to make stored verifiers more expensive to attack.
    Moving the hashing out of the server means honouring that setting out here
    too -- otherwise this change would quietly undo a deliberate hardening
    decision, and nothing would report it. `current_setting(..., true)` answers
    NULL instead of erroring on releases that do not have the setting at all,
    and NULL (like any unreadable value) falls back to the server's own
    default, which is what it would have used.
    """
    configured = executor.execute(text("SELECT current_setting('scram_iterations', true)")).scalar()
    try:
        return int(configured)
    except (TypeError, ValueError):
        return DEFAULT_ITERATIONS


def verifier_for(executor: _Executor, password: str) -> str:
    """`build_verifier` at the iteration count `executor`'s server is configured for."""
    return build_verifier(password, iterations=server_iterations(executor))
