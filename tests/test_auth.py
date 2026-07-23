import pytest

from pipeline.api.auth import (
    AuthSettings,
    auth_settings_from_environment,
    create_session_token,
    verify_credentials,
    verify_session_token,
)


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
