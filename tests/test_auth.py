from types import SimpleNamespace

from pipeline.api.auth import (
    AuthSettings,
    CredentialCheck,
    auth_settings_from_environment,
    check_credentials,
    create_session_token,
    verify_credentials,
    verify_session_token,
)
from pipeline.api.login_guard import UNKNOWN_SOURCE, client_source, source_counts_toward_limit


def test_environment_disabled_when_secret_missing_or_empty():
    assert auth_settings_from_environment({}) is None
    assert auth_settings_from_environment({"CPLAN_AUTH_SECRET": ""}) is None


def test_environment_enabled_with_secret():
    settings = auth_settings_from_environment({"CPLAN_AUTH_SECRET": "s3cret"})
    assert settings == AuthSettings(secret="s3cret")
    assert settings.cookie_name == "cplan_session"
    assert settings.max_age_seconds == 43200


def test_token_roundtrip():
    settings = AuthSettings(secret="s3cret")
    token = create_session_token(settings, "alice")
    assert verify_session_token(settings, token) == "alice"


def test_token_rejected_with_wrong_secret_or_garbage():
    settings = AuthSettings(secret="s3cret")
    token = create_session_token(settings, "alice")
    assert verify_session_token(AuthSettings(secret="other"), token) is None
    assert verify_session_token(settings, "not-a-token") is None


def test_token_rejected_when_expired():
    settings = AuthSettings(secret="s3cret", max_age_seconds=0)
    token = create_session_token(settings, "alice")
    import time

    time.sleep(1.1)
    assert verify_session_token(settings, token) is None


def test_verify_credentials_rejects_unreachable_database():
    # Connection refused == False, never an exception.
    assert verify_credentials("postgresql+psycopg://u:pw@127.0.0.1:1/cplan", "u", "pw") is False


def test_verify_credentials_returns_false_on_malformed_url():
    assert verify_credentials("not-a-valid-url-at-all", "u", "pw") is False


def test_an_unanswerable_database_is_unavailable_not_rejected():
    """The distinction the login throttle counts on.

    A server that never answered has not rejected anything, and charging the
    attempt to the account's lockout budget turns a database restart or an
    exhausted connection limit into a fifteen-minute lockout that outlives it.
    Both cases still look identical to the *client*; only the counter is told
    them apart.
    """
    assert check_credentials("postgresql+psycopg://u:pw@127.0.0.1:1/cplan", "u", "pw") is (
        CredentialCheck.UNAVAILABLE
    )
    assert check_credentials("not-a-valid-url-at-all", "u", "pw") is CredentialCheck.UNAVAILABLE


def _request(host):
    return SimpleNamespace(client=SimpleNamespace(host=host) if host else None)


def test_client_source_is_the_transport_peer_and_nothing_else():
    assert client_source(_request("203.0.113.9")) == "203.0.113.9"
    assert client_source(_request(None)) == UNKNOWN_SOURCE
    assert client_source(SimpleNamespace()) == UNKNOWN_SOURCE


def test_only_an_identifying_address_may_block_on_its_own():
    """A source counter is a shared budget, so it may only be keyed on
    something that identifies one caller.

    The portal binds loopback and the studio image runs behind no proxy, so
    `127.0.0.1` (and a test client's `testclient`, and the socket-activated
    `unknown`) is not one caller -- it is everybody. A shared budget of twenty
    on that key is not a rate limit, it is a switch that turns sign-in off for
    the whole deployment once anyone's typos add up.
    """
    assert source_counts_toward_limit("203.0.113.9") is True
    assert source_counts_toward_limit("2001:db8::1") is True
    assert source_counts_toward_limit("127.0.0.1") is False
    assert source_counts_toward_limit("::1") is False
    assert source_counts_toward_limit("0.0.0.0") is False
    assert source_counts_toward_limit(UNKNOWN_SOURCE) is False
    assert source_counts_toward_limit("testclient") is False
    assert source_counts_toward_limit("") is False
