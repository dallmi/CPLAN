"""Seed the configured database from the existing CPLAN Parquet snapshot."""

from __future__ import annotations

import argparse
import math
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from .app import Activity, ActivityChange, Base, create_app
from .database import database_url_from_environment
from .setup_backend import default_settings_path, load_backend_config, resolve_backend_database_url


DATE_FIELDS = {"start_date", "end_date", "source_created_at", "source_modified_at"}
BOOLEAN_FIELDS = {"news_digest", "is_archive"}
TEXT_FIELDS = {
    "tracking_id", "activity_name", "activity_description", "target_audience", "extended_audience",
    "business_division", "business_area", "region", "channel", "partner_team", "lead_team", "lead",
    "priority", "strategic_objectives", "campaign", "campaign_ltid", "communication_pack_cpid",
    "bod_geb", "communication_pack", "communication_ref", "author", "author_email", "audience",
    "time_zone", "other_executives",
}
SOURCE_RENAMES = {
    "sp_id": "legacy_sp_id",
    "created": "source_created_at",
    "modified": "source_modified_at",
}
ALLOWED_FIELDS = DATE_FIELDS | BOOLEAN_FIELDS | TEXT_FIELDS | {"legacy_sp_id", "source_type"}
ZURICH = ZoneInfo("Europe/Zurich")


def _missing(value: Any) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


def _datetime(value: Any) -> datetime | None:
    if _missing(value) or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        parsed = None
        for pattern in ("%d.%m.%Y %H:%M", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y"):
            try:
                parsed = datetime.strptime(text, pattern)
                break
            except ValueError:
                continue
        if parsed is None:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZURICH)
    return parsed.astimezone(timezone.utc)


def _boolean(value: Any) -> bool | None:
    if _missing(value) or value == "":
        return None
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().upper()
    if normalized in {"TRUE", "1", "YES"}:
        return True
    if normalized in {"FALSE", "0", "NO"}:
        return False
    raise ValueError(f"Invalid boolean value: {value}")


def normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    renamed = {SOURCE_RENAMES.get(key, key): value for key, value in record.items()}
    source_type = renamed.get("source_type")
    if source_type not in {"internal", "external"}:
        raise ValueError(f"Invalid source_type: {source_type}")

    normalized: dict[str, Any] = {}
    for key in ALLOWED_FIELDS:
        value = renamed.get(key)
        if key in DATE_FIELDS:
            normalized[key] = _datetime(value)
        elif key in BOOLEAN_FIELDS:
            normalized[key] = _boolean(value)
        elif key == "legacy_sp_id":
            normalized[key] = None if _missing(value) else int(value)
        elif key == "source_type":
            normalized[key] = source_type
        else:
            normalized[key] = None if _missing(value) else str(value)
    normalized["is_archive"] = bool(normalized.get("is_archive"))
    if not normalized.get("activity_name"):
        normalized["activity_name"] = "Untitled activity"
    if source_type == "external":
        normalized["news_digest"] = None
    return normalized


def seed_records(database_url: str | URL, records: Iterable[dict[str, Any]]) -> int:
    app = create_app(database_url)
    engine = app.state.engine
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        if session.scalar(select(func.count()).select_from(Activity)):
            return 0
        activities = []
        changes = []
        for record in records:
            # id generated explicitly (not left to the column's Python-side
            # default) so it is known here to link the ActivityChange row --
            # see create_activity's identical reasoning in app.py.
            activity_id = uuid.uuid4()
            activities.append(Activity(id=activity_id, **normalize_record(record), created_by="cplan_sync"))
            changes.append(
                ActivityChange(activity_id=activity_id, actor="seed", change_type="created", version_to=1)
            )
        # Kept as two bulk add_all/commit calls (no per-row flush or query) so
        # this stays fast at the ~5k-row snapshot size this seeds from.
        session.add_all(activities)
        session.add_all(changes)
        session.commit()
        return len(activities)


def seed_parquet(database_url: str | URL, parquet_path: Path) -> int:
    import pyarrow.parquet as parquet

    return seed_records(database_url, parquet.read_table(parquet_path).to_pylist())


def resolve_database_url(
    settings_path: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> str | URL:
    """Resolve the database URL to seed, preferring the environment over persisted settings.

    Composes the same `CPLAN_DB_*` variables that `create_environment_app`
    understands (see `database_url_from_environment`) before falling back to
    the persisted backend settings file. This matters for the documented
    Docker seed command (`docker compose ... exec api python -m
    pipeline.api.import_snapshot ...`): inside the `api` container, only
    `CPLAN_DB_HOST`/`_PORT`/`_NAME`/`_USER`/`_PASSWORD` are set (see
    `compose.yaml`) — there is no `CPLAN_DATABASE_URL` and no settings
    file — so checking only `CPLAN_DATABASE_URL` and the settings file would
    otherwise raise `FileNotFoundError` for that documented command.
    """
    environment = os.environ if environ is None else environ
    composed = database_url_from_environment(environment)
    if composed is not None:
        return composed
    return resolve_backend_database_url(load_backend_config(settings_path), environment)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, default=default_settings_path())
    parser.add_argument(
        "--parquet",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "output" / "communications.parquet",
    )
    args = parser.parse_args()
    database_url = resolve_database_url(args.settings)
    count = seed_parquet(database_url, args.parquet)
    print(f"Seeded {count} CPLAN activities" if count else "Database already contains activities; seed skipped")


if __name__ == "__main__":
    main()
