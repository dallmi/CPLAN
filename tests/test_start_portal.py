"""start_portal wires the resolved database URL into a portal app on the portal port."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

from pipeline.scripts import start_portal


def test_create_configured_portal_app_uses_resolved_url(tmp_path, monkeypatch):
    sentinel = object()
    monkeypatch.setattr(start_portal, "load_backend_config", lambda p: {"backend": "sqlite"})
    monkeypatch.setattr(start_portal, "resolve_backend_database_url", lambda c: "sqlite:///" + str(tmp_path / "x.db"))
    with mock.patch.object(start_portal, "create_portal_app", return_value=mock.Mock(state=mock.Mock(engine=mock.Mock()))) as factory:
        start_portal.create_configured_portal_app(Path("settings.json"))
    factory.assert_called_once()
    assert factory.call_args.args[0].startswith("sqlite:///")


def test_default_port_is_portal_port():
    assert start_portal.DEFAULT_PORT == 8781
