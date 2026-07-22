import json
import stat

import pytest

import pipeline.api_v6.setup_backend as setup_backend
from pipeline.api_v6.setup_backend import (
    BackendConfig,
    configure_backend,
    load_backend_config,
    resolve_backend_database_url,
)


def test_sqlite_backend_configuration_is_persisted_and_validated(tmp_path):
    settings_path = tmp_path / "config" / "cplan-settings.json"
    database_path = tmp_path / "data" / "cplan.sqlite3"

    configured = configure_backend(
        backend="sqlite",
        database_url=f"sqlite:///{database_path}",
        settings_path=settings_path,
    )

    assert configured == BackendConfig(backend="sqlite", database_url=f"sqlite:///{database_path}")
    assert database_path.exists()
    assert load_backend_config(settings_path) == configured
    persisted = json.loads(settings_path.read_text(encoding="utf-8"))
    assert persisted["backend"] == "sqlite"
    assert stat.S_IMODE(database_path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(database_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(settings_path.stat().st_mode) == 0o600


def test_existing_backend_configuration_requires_explicit_force(tmp_path):
    settings_path = tmp_path / "cplan-settings.json"
    first_database = tmp_path / "first.sqlite3"
    second_database = tmp_path / "second.sqlite3"
    configure_backend("sqlite", f"sqlite:///{first_database}", settings_path)

    with pytest.raises(FileExistsError, match="already configured"):
        configure_backend("sqlite", f"sqlite:///{second_database}", settings_path)

    unchanged = load_backend_config(settings_path)
    assert unchanged.database_url.endswith("first.sqlite3")

    replacement = configure_backend(
        "sqlite",
        f"sqlite:///{second_database}",
        settings_path,
        force=True,
    )
    assert replacement.database_url.endswith("second.sqlite3")


def test_backend_must_match_database_url(tmp_path):
    with pytest.raises(ValueError, match="does not match"):
        configure_backend(
            backend="postgresql",
            database_url=f"sqlite:///{tmp_path / 'wrong.sqlite3'}",
            settings_path=tmp_path / "settings.json",
        )


def test_postgresql_url_is_validated_but_never_persisted(monkeypatch, tmp_path):
    settings_path = tmp_path / "cplan-settings.json"
    database_url = "postgresql+psycopg://user@127.0.0.1/cplan"
    monkeypatch.setattr(setup_backend, "_validate_database", lambda _: None)

    configured = configure_backend("postgresql", database_url, settings_path)

    assert configured == BackendConfig(backend="postgresql", database_url=None)
    assert json.loads(settings_path.read_text(encoding="utf-8"))["database_url"] is None
    assert resolve_backend_database_url(configured, {"CPLAN_DATABASE_URL": database_url}) == database_url
    with pytest.raises(RuntimeError, match="CPLAN_DATABASE_URL is required"):
        resolve_backend_database_url(configured, {})


def test_missing_configuration_never_creates_an_implicit_fallback(tmp_path):
    settings_path = tmp_path / "missing-settings.json"

    with pytest.raises(FileNotFoundError, match="not configured"):
        load_backend_config(settings_path)

    assert not (tmp_path / "cplan.sqlite3").exists()
