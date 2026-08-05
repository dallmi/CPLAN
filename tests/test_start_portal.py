"""start_portal wires the resolved database URL into a portal app on the portal port."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from pipeline.scripts import start_portal


def _configured(monkeypatch, tmp_path, *, guard_installed: bool):
    monkeypatch.setattr(start_portal, "load_backend_config", lambda p: {"backend": "sqlite"})
    monkeypatch.setattr(
        start_portal, "resolve_backend_database_url", lambda c: "sqlite:///" + str(tmp_path / "x.db")
    )
    monkeypatch.setattr(start_portal, "login_guard_installed", lambda engine: guard_installed)
    return mock.patch.object(
        start_portal, "create_portal_app", return_value=mock.Mock(state=mock.Mock(engine=mock.Mock()))
    )


def test_create_configured_portal_app_uses_resolved_url(tmp_path, monkeypatch):
    with _configured(monkeypatch, tmp_path, guard_installed=True) as factory:
        start_portal.create_configured_portal_app(Path("settings.json"))
    factory.assert_called_once()
    assert factory.call_args.args[0].startswith("sqlite:///")


def test_a_database_without_the_login_throttle_refuses_to_serve(tmp_path, monkeypatch):
    """The upgrade path this product actually has is hand-copied files.

    An installation that receives the new portal without re-running
    `setup_portal` has no counters for the login endpoint to consult, and that
    endpoint fails closed -- so without this check the portal would start,
    serve its landing page, pass the readiness probe, and then answer every
    single sign-in (the administrator's included) with a 503 whose only trace
    is a traceback in a spawned server window. Refuse here instead, where
    there is room to print the one command that fixes it.
    """
    with _configured(monkeypatch, tmp_path, guard_installed=False):
        with pytest.raises(start_portal.PortalSetupIncomplete) as exc:
            start_portal.create_configured_portal_app(Path("settings.json"))
    # The message has to name the command, not just the missing object: the
    # person reading it is looking at a window that just closed.
    assert "setup_portal" in str(exc.value)


def test_default_port_is_portal_port():
    assert start_portal.DEFAULT_PORT == 8781
