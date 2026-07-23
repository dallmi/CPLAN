import json
import stat
import sys
from pathlib import Path

import pytest

import pipeline.api.setup_backend as setup_backend
from pipeline.api.setup_backend import (
    BackendConfig,
    configure_backend,
    default_pgdata_dir,
    load_backend_config,
    resolve_backend_database_url,
    resolve_pgdata,
)

REPO_PIPELINE_DATA = Path(setup_backend.__file__).resolve().parents[1] / "data"


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


def test_default_cplan_home_resolves_to_repo_pipeline_data(monkeypatch, tmp_path):
    monkeypatch.delenv("CPLAN_HOME", raising=False)
    monkeypatch.chdir(tmp_path)  # proves resolution is module-relative, not cwd-relative

    assert setup_backend.default_cplan_home() == REPO_PIPELINE_DATA


def test_cplan_home_env_var_still_overrides_default(monkeypatch, tmp_path):
    override = tmp_path / "custom-home"
    monkeypatch.setenv("CPLAN_HOME", str(override))

    assert setup_backend.default_cplan_home() == override.resolve()


def test_configure_backend_default_settings_path_lands_in_repo_data_dir(monkeypatch, tmp_path):
    monkeypatch.delenv("CPLAN_HOME", raising=False)
    monkeypatch.chdir(tmp_path)  # proves cwd-independence, not just default-arg convenience

    expected_settings = REPO_PIPELINE_DATA / "cplan-settings.json"
    expected_settings_tmp = expected_settings.with_suffix(expected_settings.suffix + ".tmp")
    original_mode = stat.S_IMODE(REPO_PIPELINE_DATA.stat().st_mode)
    expected_settings.unlink(missing_ok=True)
    expected_settings_tmp.unlink(missing_ok=True)

    database_path = tmp_path / "cplan.sqlite3"
    try:
        configured = configure_backend(
            backend="sqlite",
            database_url=f"sqlite:///{database_path}",
        )

        assert configured.backend == "sqlite"
        assert expected_settings.parent == REPO_PIPELINE_DATA
        persisted = json.loads(expected_settings.read_text(encoding="utf-8"))
        assert persisted["backend"] == "sqlite"
    finally:
        expected_settings.unlink(missing_ok=True)
        expected_settings_tmp.unlink(missing_ok=True)
        REPO_PIPELINE_DATA.chmod(original_mode)


# --- postgres-embedded backend -------------------------------------------------


def _stub_embedded_database_url(monkeypatch, expected_pgdata=None):
    """Stub out the real pgserver-backed validation so these settings/precedence
    tests never start a real server -- they are about JSON persistence and path
    resolution, not pgserver itself (see tests/test_database.py and
    tests/test_postgres_embedded.py for that)."""
    calls = []

    def fake_embedded_database_url(pgdata):
        calls.append(Path(pgdata))
        return "postgresql+psycopg://postgres:@/cplan?host=%2Ftmp%2Ffake-sockdir"

    monkeypatch.setattr(setup_backend, "embedded_database_url", fake_embedded_database_url)
    monkeypatch.setattr(setup_backend, "_validate_database", lambda _: None)
    return calls


def test_default_pgdata_dir_on_windows_uses_localappdata(monkeypatch):
    monkeypatch.setattr(setup_backend.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\example\AppData\Local")

    assert default_pgdata_dir() == Path(r"C:\Users\example\AppData\Local") / "CPLAN" / "postgres"


def test_default_pgdata_dir_on_windows_falls_back_without_localappdata(monkeypatch):
    monkeypatch.setattr(setup_backend.sys, "platform", "win32")
    monkeypatch.delenv("LOCALAPPDATA", raising=False)

    result = default_pgdata_dir()

    assert result == Path.home() / "AppData" / "Local" / "CPLAN" / "postgres"


def test_default_pgdata_dir_on_macos(monkeypatch):
    monkeypatch.setattr(setup_backend.sys, "platform", "darwin")

    expected = Path.home() / "Library" / "Application Support" / "CPLAN" / "postgres"
    assert default_pgdata_dir() == expected


def test_default_pgdata_dir_on_linux_uses_xdg_data_home(monkeypatch):
    monkeypatch.setattr(setup_backend.sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", "/custom/xdg")

    assert default_pgdata_dir() == Path("/custom/xdg") / "CPLAN" / "postgres"


def test_default_pgdata_dir_on_linux_without_xdg_data_home(monkeypatch):
    monkeypatch.setattr(setup_backend.sys, "platform", "linux")
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)

    expected = Path.home() / ".local" / "share" / "CPLAN" / "postgres"
    assert default_pgdata_dir() == expected


def test_resolve_pgdata_explicit_flag_wins_over_everything(monkeypatch, tmp_path):
    monkeypatch.setenv("CPLAN_PGDATA", str(tmp_path / "from-env"))

    result = resolve_pgdata(explicit=tmp_path / "from-flag", persisted=str(tmp_path / "from-settings"))

    assert result == (tmp_path / "from-flag").resolve()


def test_resolve_pgdata_env_wins_over_persisted_settings(monkeypatch, tmp_path):
    """The corp fallback (e.g. to a network share) must take effect just by
    exporting CPLAN_PGDATA, with no need to re-run setup_backend."""
    monkeypatch.setenv("CPLAN_PGDATA", str(tmp_path / "from-env"))

    result = resolve_pgdata(persisted=str(tmp_path / "from-settings"))

    assert result == (tmp_path / "from-env").resolve()


def test_resolve_pgdata_falls_back_to_persisted_settings(monkeypatch, tmp_path):
    monkeypatch.delenv("CPLAN_PGDATA", raising=False)

    result = resolve_pgdata(persisted=str(tmp_path / "from-settings"))

    assert result == (tmp_path / "from-settings").resolve()


def test_resolve_pgdata_falls_back_to_platform_default(monkeypatch):
    monkeypatch.delenv("CPLAN_PGDATA", raising=False)
    monkeypatch.setattr(setup_backend.sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", "/custom/xdg")

    assert resolve_pgdata() == Path("/custom/xdg") / "CPLAN" / "postgres"


def test_resolve_pgdata_warns_on_unc_path(monkeypatch, capsys):
    monkeypatch.delenv("CPLAN_PGDATA", raising=False)

    resolve_pgdata(explicit=r"\\corpserver\share\CPLAN\postgres")

    captured = capsys.readouterr()
    assert "UNC" in captured.err or "network" in captured.err.lower()


def test_resolve_pgdata_does_not_warn_on_a_normal_path(monkeypatch, capsys, tmp_path):
    monkeypatch.delenv("CPLAN_PGDATA", raising=False)

    resolve_pgdata(explicit=tmp_path / "pgdata")

    captured = capsys.readouterr()
    assert captured.err == ""


def test_postgres_embedded_backend_configuration_is_persisted_without_a_database_url(monkeypatch, tmp_path):
    settings_path = tmp_path / "cplan-settings.json"
    pgdata = tmp_path / "pgdata"
    calls = _stub_embedded_database_url(monkeypatch)

    configured = configure_backend(backend="postgres-embedded", settings_path=settings_path, pgdata=pgdata)

    assert configured == BackendConfig(backend="postgres-embedded", database_url=None, pgdata=str(pgdata.resolve()))
    assert calls == [pgdata.resolve()]
    persisted = json.loads(settings_path.read_text(encoding="utf-8"))
    assert persisted["backend"] == "postgres-embedded"
    assert persisted["pgdata"] == str(pgdata.resolve())
    assert persisted["database_url"] is None
    assert stat.S_IMODE(settings_path.stat().st_mode) == 0o600

    loaded = load_backend_config(settings_path)
    assert loaded == configured


def test_postgres_embedded_backend_uses_default_pgdata_when_not_given(monkeypatch, tmp_path):
    settings_path = tmp_path / "cplan-settings.json"
    default_dir = tmp_path / "platform-default" / "CPLAN" / "postgres"
    monkeypatch.setattr(setup_backend, "default_pgdata_dir", lambda: default_dir)
    monkeypatch.delenv("CPLAN_PGDATA", raising=False)
    calls = _stub_embedded_database_url(monkeypatch)

    configured = configure_backend(backend="postgres-embedded", settings_path=settings_path)

    assert configured.pgdata == str(default_dir.resolve())
    assert calls == [default_dir.resolve()]


def test_postgres_embedded_backend_honors_cplan_pgdata_env_at_configure_time(monkeypatch, tmp_path):
    settings_path = tmp_path / "cplan-settings.json"
    env_pgdata = tmp_path / "from-env"
    monkeypatch.setenv("CPLAN_PGDATA", str(env_pgdata))
    calls = _stub_embedded_database_url(monkeypatch)

    configured = configure_backend(backend="postgres-embedded", settings_path=settings_path)

    assert configured.pgdata == str(env_pgdata.resolve())
    assert calls == [env_pgdata.resolve()]


def test_resolve_backend_database_url_for_postgres_embedded_uses_persisted_pgdata(monkeypatch, tmp_path):
    settings_path = tmp_path / "cplan-settings.json"
    pgdata = tmp_path / "pgdata"
    _stub_embedded_database_url(monkeypatch)
    configured = configure_backend(backend="postgres-embedded", settings_path=settings_path, pgdata=pgdata)

    calls = _stub_embedded_database_url(monkeypatch)
    url = resolve_backend_database_url(configured, environ={})

    assert url == "postgresql+psycopg://postgres:@/cplan?host=%2Ftmp%2Ffake-sockdir"
    assert calls == [pgdata.resolve()]


def test_resolve_backend_database_url_for_postgres_embedded_lets_env_override_persisted_pgdata(monkeypatch, tmp_path):
    """CPLAN_PGDATA must win at resolve time even though the settings file already
    has a pgdata recorded -- the whole point of the corp fallback."""
    settings_path = tmp_path / "cplan-settings.json"
    _stub_embedded_database_url(monkeypatch)
    configured = configure_backend(
        backend="postgres-embedded", settings_path=settings_path, pgdata=tmp_path / "configured-pgdata"
    )

    env_pgdata = tmp_path / "fallback-pgdata"
    calls = _stub_embedded_database_url(monkeypatch)
    resolve_backend_database_url(configured, environ={"CPLAN_PGDATA": str(env_pgdata)})

    assert calls == [env_pgdata.resolve()]


def test_load_backend_config_rejects_postgres_embedded_without_pgdata(tmp_path):
    settings_path = tmp_path / "cplan-settings.json"
    settings_path.write_text(
        json.dumps({"schema_version": setup_backend.SETTINGS_SCHEMA_VERSION, "backend": "postgres-embedded"}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="pgdata"):
        load_backend_config(settings_path)


def test_load_backend_config_rejects_postgres_embedded_with_a_persisted_database_url(tmp_path):
    settings_path = tmp_path / "cplan-settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "schema_version": setup_backend.SETTINGS_SCHEMA_VERSION,
                "backend": "postgres-embedded",
                "pgdata": str(tmp_path / "pgdata"),
                "database_url": "postgresql+psycopg://postgres:@/cplan",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="database URL"):
        load_backend_config(settings_path)
