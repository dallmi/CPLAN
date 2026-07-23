from datetime import timezone

from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from pipeline.api.app import Activity, ActivityChange
from pipeline.api.database import backend_from_url, create_cplan_engine
from pipeline.api.import_snapshot import normalize_record, resolve_database_url, seed_records
from pipeline.api.setup_backend import configure_backend


def test_snapshot_record_is_normalized_for_postgres():
    normalized = normalize_record(
        {
            "sp_id": 42,
            "source_type": "internal",
            "tracking_id": "CPLAN-42",
            "activity_name": "Imported activity",
            "start_date": "03.08.2026 09:00",
            "end_date": "2026-08-03T10:30:00+02:00",
            "news_digest": "TRUE",
            "is_archive": False,
            "campaign": float("nan"),
        }
    )

    assert normalized["legacy_sp_id"] == 42
    assert normalized["news_digest"] is True
    assert normalized["campaign"] is None
    assert normalized["start_date"].tzinfo is not None
    assert normalized["start_date"].utcoffset().total_seconds() == 0
    assert normalized["start_date"].astimezone(timezone.utc).isoformat() == "2026-08-03T07:00:00+00:00"
    assert normalized["end_date"].astimezone(timezone.utc).isoformat() == "2026-08-03T08:30:00+00:00"


def test_importer_uses_explicit_environment_url_before_persisted_settings(tmp_path):
    settings_path = tmp_path / "cplan-settings.json"
    configured_url = f"sqlite:///{tmp_path / 'configured.sqlite3'}"
    environment_url = f"sqlite:///{tmp_path / 'environment.sqlite3'}"
    configure_backend("sqlite", configured_url, settings_path)

    assert resolve_database_url(settings_path, {"CPLAN_DATABASE_URL": environment_url}) == environment_url
    assert resolve_database_url(settings_path, {}) == configured_url


def test_resolve_database_url_composes_from_cplan_db_env_vars_like_the_docker_container():
    """Mirrors compose.yaml's `api` service and the documented Docker seed
    command (`docker compose ... exec api python -m pipeline.api.import_snapshot
    ...`): inside that container only CPLAN_DB_HOST/_PORT/_NAME/_USER/_PASSWORD
    are set — there is no CPLAN_DATABASE_URL and no persisted settings file —
    so resolve_database_url must compose a working URL from those alone.
    """
    environ = {
        "CPLAN_DB_HOST": "db",
        "CPLAN_DB_PORT": "5432",
        "CPLAN_DB_NAME": "cplan",
        "CPLAN_DB_USER": "cplan",
        "CPLAN_DB_PASSWORD": "local:@/?# test",
    }

    resolved = resolve_database_url(environ=environ)

    assert backend_from_url(resolved) == "postgresql"
    url = make_url(resolved)
    assert url.host == "db"
    assert url.username == "cplan"
    assert url.password == "local:@/?# test"
    assert url.database == "cplan"


def test_resolve_database_url_prefers_explicit_cplan_database_url_over_cplan_db_parts():
    environ = {
        "CPLAN_DATABASE_URL": "postgresql+psycopg://explicit@localhost/cplan",
        "CPLAN_DB_PASSWORD": "should-be-ignored",
    }

    assert resolve_database_url(environ=environ) == "postgresql+psycopg://explicit@localhost/cplan"


def test_seed_records_writes_one_created_activity_change_row_per_activity_actor_seed(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'seed-changes.sqlite3'}"
    records = [
        {"sp_id": 1, "source_type": "internal", "activity_name": "Seed activity one"},
        {"sp_id": 2, "source_type": "internal", "activity_name": "Seed activity two"},
    ]

    count = seed_records(database_url, records)
    assert count == 2

    engine = create_cplan_engine(database_url)
    try:
        with Session(engine) as session:
            activity_ids = {activity.id for activity in session.query(Activity).all()}
            changes = session.query(ActivityChange).all()

            assert len(changes) == 2
            for change in changes:
                assert change.actor == "seed"
                assert change.change_type == "created"
                assert change.field is None
                assert change.old_value is None
                assert change.new_value is None
                assert change.version_from is None
                assert change.version_to == 1
                assert change.activity_id in activity_ids
    finally:
        engine.dispose()


def test_snapshot_record_rejects_unknown_source_type():
    try:
        normalize_record({"source_type": "archive", "activity_name": "Invalid"})
    except ValueError as error:
        assert "source_type" in str(error)
    else:
        raise AssertionError("normalize_record accepted an unknown source type")
