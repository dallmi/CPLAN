"""Daily snapshot sync — upsert the SharePoint mirror snapshot into the CPLAN database.

Runs after `process_cplan.py` produces `pipeline/output/communications.parquet`, so the
CPLAN database stays a faithful mirror of the corp source system while studio-created
activities (`legacy_sp_id IS NULL`) live alongside it — parallel operation until the
corp system migrates.

Sync policy (binding):
- **Source wins, conflicts reported.** SharePoint remains the system of record. If a
  row changed in the source AND was edited locally in the studio, the source values
  overwrite the local edit and the conflict (field-level diff: field, local value,
  incoming value) is recorded in the sync report.
- **Studio-created rows** (`legacy_sp_id IS NULL`) are never touched by sync; counted as
  "local-only".
- **Never delete.** A DB row whose `(source_type, legacy_sp_id)` no longer appears in
  the snapshot is reported as "vanished from source" and otherwise left untouched.
- Sync key: `(source_type, legacy_sp_id)`. Snapshot records without an sp_id are
  skipped and counted.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import func, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from .app import Activity, Base, SyncRun, as_utc, create_app
from .database import ensure_schema
from .import_snapshot import ALLOWED_FIELDS, DATE_FIELDS, normalize_record, resolve_database_url
from .setup_backend import default_settings_path


MAX_DETAIL_ENTRIES = 50
# The full imported field set, minus nothing: comparing the match-key fields
# (source_type, legacy_sp_id) against themselves is a harmless no-op since the row
# was looked up by exactly those values.
SYNCED_FIELDS = sorted(ALLOWED_FIELDS)


def _values_equal(field_name: str, stored: Any, incoming: Any) -> bool:
    """Compare a stored (possibly SQLite-naive) value against a normalized incoming one.

    Datetime fields are re-normalized to UTC on both sides via `as_utc` before
    comparing. Without this, SQLite's naive round-trip would make every equal
    instant look like a diff, so every row would read as "updated" (or worse,
    "conflict") on every single run — breaking idempotency.
    """
    if field_name in DATE_FIELDS:
        return as_utc(stored) == as_utc(incoming)
    return stored == incoming


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        normalized = as_utc(value)
        return normalized.isoformat().replace("+00:00", "Z") if normalized else None
    return value


@dataclass
class SyncReport:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    conflicts: int = 0
    vanished: int = 0
    local_only: int = 0
    skipped_no_id: int = 0
    conflict_details: list[dict[str, Any]] = field(default_factory=list)
    vanished_keys: list[dict[str, Any]] = field(default_factory=list)

    def details_json(self) -> str:
        return json.dumps(
            {
                "conflicts": self.conflict_details[:MAX_DETAIL_ENTRIES],
                "vanished": self.vanished_keys[:MAX_DETAIL_ENTRIES],
            }
        )


def _diff_fields(existing: Activity, normalized: dict[str, Any]) -> list[tuple[str, Any, Any]]:
    diffs = []
    for field_name in SYNCED_FIELDS:
        stored_value = getattr(existing, field_name)
        incoming_value = normalized[field_name]
        if not _values_equal(field_name, stored_value, incoming_value):
            diffs.append((field_name, stored_value, incoming_value))
    return diffs


def sync_records(
    database_url: str | URL,
    records: Iterable[dict[str, Any]],
    snapshot_path: str | Path,
) -> SyncReport:
    """Upsert normalized snapshot `records` into the CPLAN database. See module docstring for policy.

    `Base.metadata.create_all` + `ensure_schema` are run here explicitly (mirroring
    the app's lifespan) since this is a standalone job invocation, not a running
    FastAPI app — the `synced_version` column and `sync_runs` table must arrive on an
    existing (pre-Task-9) database through that same top-up mechanism.
    """
    app = create_app(database_url)
    engine = app.state.engine
    Base.metadata.create_all(engine)
    ensure_schema(engine, Base.metadata)

    report = SyncReport()
    seen_keys: set[tuple[str, int]] = set()

    with Session(engine) as session:
        for record in records:
            normalized = normalize_record(record)
            if normalized["legacy_sp_id"] is None:
                report.skipped_no_id += 1
                continue

            key = (normalized["source_type"], normalized["legacy_sp_id"])
            seen_keys.add(key)
            existing = session.scalar(
                select(Activity).where(
                    Activity.source_type == key[0],
                    Activity.legacy_sp_id == key[1],
                )
            )

            if existing is None:
                session.add(Activity(**normalized, version=1, synced_version=1))
                report.created += 1
                continue

            diffs = _diff_fields(existing, normalized)
            if not diffs:
                report.unchanged += 1
                continue

            # Must be captured before applying the incoming values below, since
            # applying them immediately sets synced_version == version.
            was_locally_dirty = (
                existing.synced_version is not None and existing.version > existing.synced_version
            )

            for field_name, _local_value, incoming_value in diffs:
                setattr(existing, field_name, incoming_value)
            existing.version = existing.version + 1
            existing.synced_version = existing.version

            if was_locally_dirty:
                report.conflicts += 1
                report.conflict_details.append(
                    {
                        "source_type": key[0],
                        "legacy_sp_id": key[1],
                        "tracking_id": existing.tracking_id,
                        "fields": [
                            {
                                "field": field_name,
                                "local": _json_safe(local_value),
                                "incoming": _json_safe(incoming_value),
                            }
                            for field_name, local_value, incoming_value in diffs
                        ],
                    }
                )
            else:
                report.updated += 1

        legacy_rows = session.scalars(select(Activity).where(Activity.legacy_sp_id.isnot(None))).all()
        for row in legacy_rows:
            row_key = (row.source_type, row.legacy_sp_id)
            if row_key not in seen_keys:
                report.vanished += 1
                report.vanished_keys.append(
                    {
                        "source_type": row.source_type,
                        "legacy_sp_id": row.legacy_sp_id,
                        "tracking_id": row.tracking_id,
                    }
                )

        report.local_only = (
            session.scalar(select(func.count()).select_from(Activity).where(Activity.legacy_sp_id.is_(None)))
            or 0
        )

        session.add(
            SyncRun(
                snapshot_path=str(snapshot_path),
                created=report.created,
                updated=report.updated,
                unchanged=report.unchanged,
                conflicts=report.conflicts,
                vanished=report.vanished,
                local_only=report.local_only,
                skipped_no_id=report.skipped_no_id,
                details=report.details_json(),
            )
        )
        session.commit()

    return report


def sync_parquet(database_url: str | URL, parquet_path: Path) -> SyncReport:
    import pyarrow.parquet as parquet

    records = parquet.read_table(parquet_path).to_pylist()
    return sync_records(database_url, records, parquet_path)


def format_report(report: SyncReport) -> str:
    lines = [
        "CPLAN sync complete: "
        f"{report.created} created, {report.updated} updated, {report.unchanged} unchanged, "
        f"{report.conflicts} conflicts, {report.vanished} vanished, {report.local_only} local-only, "
        f"{report.skipped_no_id} skipped (no id)"
    ]
    if report.conflict_details:
        lines.append("First conflicts:")
        for entry in report.conflict_details[:5]:
            field_summary = ", ".join(
                f"{item['field']}: '{item['local']}' -> '{item['incoming']}'" for item in entry["fields"]
            )
            lines.append(f"  - {entry['source_type']}/{entry['legacy_sp_id']} ({entry['tracking_id']}): {field_summary}")
    return "\n".join(lines)


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
    report = sync_parquet(database_url, args.parquet)
    print(format_report(report))


if __name__ == "__main__":
    main()
