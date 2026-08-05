import pytest

from pipeline.api.setup_backend import configure_backend
from pipeline.scripts import start_cplan
from pipeline.scripts.start_cplan import StudioSetupIncomplete, create_configured_app


def test_launcher_uses_the_persisted_sqlite_backend(tmp_path):
    settings_path = tmp_path / "cplan-settings.json"
    database_path = tmp_path / "cplan.sqlite3"
    configure_backend("sqlite", f"sqlite:///{database_path}", settings_path)

    app = create_configured_app(settings_path)

    assert app.state.engine.dialect.name == "sqlite"


def test_launcher_does_not_create_a_fallback_when_configuration_is_missing(tmp_path):
    with pytest.raises(FileNotFoundError, match="not configured"):
        create_configured_app(tmp_path / "missing.json")

    assert not (tmp_path / "cplan.sqlite3").exists()


def test_solo_mode_needs_no_login_throttle(tmp_path, monkeypatch):
    """Nothing to rate-limit where there is nothing to guess.

    With no `CPLAN_AUTH_SECRET` the studio has no login at all, and SQLite has
    neither login roles nor a `portal` schema -- so requiring the portal's
    schema step here would break the one configuration that never needed it.
    """
    monkeypatch.delenv("CPLAN_AUTH_SECRET", raising=False)
    settings_path = tmp_path / "cplan-settings.json"
    configure_backend("sqlite", f"sqlite:///{tmp_path / 'cplan.sqlite3'}", settings_path)

    app = create_configured_app(settings_path)

    assert app.state.login_guard is None


def test_an_authenticating_studio_refuses_a_database_without_the_throttle(tmp_path, monkeypatch):
    """The studio's own login checks the same roles and mints the same cookie
    the portal accepts, so it shares the portal's counters -- and therefore
    needs the same schema step. Starting anyway would mean a studio that
    answers every sign-in with a 503, or (worse, if it did not fail closed) an
    unlimited guessing endpoint on the other port."""
    settings_path = tmp_path / "cplan-settings.json"
    configure_backend("sqlite", f"sqlite:///{tmp_path / 'cplan.sqlite3'}", settings_path)
    monkeypatch.setattr(start_cplan, "login_guard_installed", lambda engine: False)

    with pytest.raises(StudioSetupIncomplete, match="setup_portal"):
        # Solo mode has no guard to miss, so stand in for the authenticating
        # configuration by giving the app one.
        with monkeypatch.context() as patched:
            real_create_app = start_cplan.create_app

            def with_guard(url):
                app = real_create_app(url)
                app.state.login_guard = object()
                return app

            patched.setattr(start_cplan, "create_app", with_guard)
            create_configured_app(settings_path)
