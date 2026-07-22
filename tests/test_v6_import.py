from datetime import timezone

from pipeline.api_v6.import_snapshot import normalize_record, resolve_database_url
from pipeline.api_v6.setup_backend import configure_backend


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


def test_snapshot_record_rejects_unknown_source_type():
    try:
        normalize_record({"source_type": "archive", "activity_name": "Invalid"})
    except ValueError as error:
        assert "source_type" in str(error)
    else:
        raise AssertionError("normalize_record accepted an unknown source type")
