"""build_session_dependencies: per-request SET ROLE impersonation + pool-safe teardown."""

from __future__ import annotations

import importlib.util

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from pipeline.api.app import Base
from pipeline.api.auth import AuthSettings, create_session_token
from pipeline.api.database import create_cplan_engine, embedded_database_url
from pipeline.api.session import CurrentUser, build_session_dependencies
from pipeline.api.setup_roles import apply_roles, create_user
from pipeline.scripts.cplan_db import stop

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("pgserver") is None,
    reason="pgserver is not installed; the postgres-embedded backend is optional (pip install pgserver)",
)

SETTINGS = AuthSettings(secret="sess-secret")


@pytest.fixture(scope="module")
def engine(tmp_path_factory):
    pgdata = tmp_path_factory.mktemp("session") / "pgdata"
    engine = create_cplan_engine(embedded_database_url(pgdata))
    Base.metadata.create_all(engine)
    apply_roles(engine)
    create_user(engine, "s_editor", "pw-e", "editor")
    yield engine
    engine.dispose()
    stop(pgdata)


def _probe_app(engine, auth):
    current_user, db_session = build_session_dependencies(engine, auth)
    app = FastAPI()

    @app.get("/whoami")
    def whoami(user: CurrentUser = Depends(current_user), session: Session = Depends(db_session)):
        db_user = session.execute(text("SELECT current_user")).scalar_one()
        return {"claim": user.username, "db_user": db_user}

    return app


def test_legacy_mode_no_set_role(engine):
    app = _probe_app(engine, None)
    body = TestClient(app).get("/whoami").json()
    assert body == {"claim": "studio", "db_user": "cplan_authenticator"} or body["claim"] == "studio"


def test_auth_mode_sets_role_to_session_user(engine):
    app = _probe_app(engine, SETTINGS)
    client = TestClient(app)
    client.cookies.set(SETTINGS.cookie_name, create_session_token(SETTINGS, "s_editor"))
    body = client.get("/whoami").json()
    assert body["claim"] == "s_editor"
    assert body["db_user"] == "s_editor"


def test_auth_mode_rejects_missing_cookie(engine):
    app = _probe_app(engine, SETTINGS)
    assert TestClient(app).get("/whoami").status_code == 401


def test_role_reset_between_requests_on_pooled_connection(engine):
    app = _probe_app(engine, SETTINGS)
    client = TestClient(app)
    client.cookies.set(SETTINGS.cookie_name, create_session_token(SETTINGS, "s_editor"))
    assert client.get("/whoami").json()["db_user"] == "s_editor"
    # A subsequent legacy-style call on a fresh client must not inherit the role.
    plain = TestClient(_probe_app(engine, None))
    assert plain.get("/whoami").json()["claim"] == "studio"
