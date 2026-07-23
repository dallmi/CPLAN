import pytest

from pipeline.api.setup_backend import configure_backend
from pipeline.scripts.start_cplan import create_configured_app


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
