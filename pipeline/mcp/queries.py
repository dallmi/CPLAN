"""Backend-neutral read queries behind the MCP tools.

Deliberately free of any `mcp` import: this module is the whole answer-shaped
logic and must stay testable without the MCP SDK installed (same split as the
optional-`pgserver` code paths elsewhere in the project).

Why not the `v_*` analysis views: `pipeline/api/views.py` is PostgreSQL-only by
design and a documented no-op on SQLite, so building the tools on those views
would make the server dead on every SQLite deployment. The *semantics* are
mirrored here in SQLAlchemy instead -- see `REQUIRED_COMMON_FIELDS` /
`REQUIRED_INTERNAL_FIELDS`, which `tests/test_mcp_server.py` pins against the
view SQL so the two cannot drift apart silently.

Every function returns plain JSON-ready dicts and caps its own result size: an
agent's context window is a hard resource, so no query here can reproduce the
unpaginated full-table response that `GET /api/activities` deliberately serves
to the studio.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import String, func, or_, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from pipeline.api.app import Activity, ActivityChange, ActivityRead, SyncRun, as_utc

# Mirrors analytics.js empty(): a text field counts as missing when it is NULL,
# blank/whitespace-only, or the literal string 'None'/'null' (Python str(None)
# leaking in through the sync).
BLANK_TEXT_SENTINELS = ("None", "null")

# The unified variant-aware completeness rule. Kept in field-name form (not
# flag-name form) so it can be reused for filtering and reporting alike.
REQUIRED_COMMON_FIELDS: tuple[str, ...] = (
    "activity_name",
    "activity_description",
    "channel",
    "priority",
    "strategic_objectives",
    "region",
    "start_date",
    "end_date",
    "time_zone",
    "lead",
    "lead_team",
)

# Additionally required for internal activities only; never required externally.
REQUIRED_INTERNAL_FIELDS: tuple[str, ...] = (
    "target_audience",
    "audience",
    "business_division",
)

# Two required fields carry a flag name in v_planning_completeness that differs
# from the column name. Everything else is plain `missing_<column>`.
_VIEW_FLAG_ALIASES = {
    "activity_description": "missing_description",
    "strategic_objectives": "missing_pillars",
}

DATE_FIELDS = frozenset({"start_date", "end_date"})

# Columns an agent may group or enumerate. Free-text columns in the schema are
# not enumerated types, so `field_values` is what stops the model from guessing
# filter values that do not exist.
GROUPABLE_FIELDS: tuple[str, ...] = (
    "channel",
    "priority",
    "source_type",
    "lead_team",
    "lead",
    "region",
    "business_division",
    "campaign",
    "month",
)

ENUMERABLE_FIELDS: tuple[str, ...] = tuple(f for f in GROUPABLE_FIELDS if f != "month")

# The compact projection for list-shaped answers, mirroring v_activity_overview.
# Long free text (activity_description) is deliberately absent -- `get_activity`
# is the way to the full record.
SUMMARY_FIELDS: tuple[str, ...] = (
    "id",
    "tracking_id",
    "activity_name",
    "source_type",
    "channel",
    "priority",
    "start_date",
    "end_date",
    "lead",
    "lead_team",
    "is_archive",
)

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def view_flag_name(field: str) -> str:
    """The `missing_*` column v_planning_completeness uses for `field`."""
    return _VIEW_FLAG_ALIASES.get(field, f"missing_{field}")


def _clamp_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_LIMIT
    return max(1, min(int(limit), MAX_LIMIT))


def _iso(value: datetime | None) -> str | None:
    normalized = as_utc(value)
    if normalized is None:
        return None
    return normalized.isoformat().replace("+00:00", "Z")


def _parse_boundary(value: str | date | datetime | None) -> datetime | None:
    """Accept 'YYYY-MM-DD' or a full ISO timestamp; always return UTC-aware."""
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime(value.year, value.month, value.day)
    else:
        text = value.strip()
        if not text:
            return None
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def is_blank(value: Any) -> bool:
    """The text-emptiness rule shared with analytics.js and v_planning_completeness."""
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    return stripped == "" or stripped in BLANK_TEXT_SENTINELS


def missing_fields(activity: Activity) -> list[str]:
    """Required fields this activity is still missing, in declaration order."""
    required = list(REQUIRED_COMMON_FIELDS)
    if activity.source_type == "internal":
        required += list(REQUIRED_INTERNAL_FIELDS)
    missing = []
    for field in required:
        value = getattr(activity, field)
        if field in DATE_FIELDS:
            if value is None:
                missing.append(field)
        elif is_blank(value):
            missing.append(field)
    return missing


def _summarize(activity: Activity) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for field in SUMMARY_FIELDS:
        value = getattr(activity, field)
        if isinstance(value, datetime):
            row[field] = _iso(value)
        elif isinstance(value, uuid.UUID):
            row[field] = str(value)
        else:
            row[field] = value
    return row


def _apply_filters(
    statement,
    *,
    text_query: str | None,
    channel: str | None,
    source_type: str | None,
    priority: str | None,
    lead: str | None,
    campaign: str | None,
    start_after: str | None,
    start_before: str | None,
    include_archived: bool,
):
    if text_query:
        needle = f"%{text_query.strip().lower()}%"
        statement = statement.where(
            or_(
                func.lower(Activity.activity_name).like(needle),
                func.lower(func.coalesce(Activity.tracking_id, "")).like(needle),
                func.lower(func.coalesce(Activity.activity_description, "")).like(needle),
            )
        )
    # Case-insensitive equality throughout: the columns are free text, so an
    # agent that guesses "Email" for a stored "email" should still get its rows.
    for column, value in (
        (Activity.channel, channel),
        (Activity.source_type, source_type),
        (Activity.priority, priority),
        (Activity.lead, lead),
        (Activity.campaign, campaign),
    ):
        if value:
            statement = statement.where(func.lower(column) == value.strip().lower())
    after = _parse_boundary(start_after)
    if after is not None:
        statement = statement.where(Activity.start_date >= after)
    before = _parse_boundary(start_before)
    if before is not None:
        statement = statement.where(Activity.start_date <= before)
    if not include_archived:
        statement = statement.where(Activity.is_archive.is_(False))
    return statement


def _truncation_note(total: int, returned: int, limit: int) -> str | None:
    if returned >= total:
        return None
    return (
        f"Showing {returned} of {total} matching activities (limit={limit}). "
        "Narrow the filters rather than raising the limit -- this tool never "
        "returns the whole table."
    )


def search_activities(
    session: Session,
    *,
    query: str | None = None,
    channel: str | None = None,
    source_type: str | None = None,
    priority: str | None = None,
    lead: str | None = None,
    campaign: str | None = None,
    start_after: str | None = None,
    start_before: str | None = None,
    include_archived: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    capped = _clamp_limit(limit)
    filters = dict(
        text_query=query,
        channel=channel,
        source_type=source_type,
        priority=priority,
        lead=lead,
        campaign=campaign,
        start_after=start_after,
        start_before=start_before,
        include_archived=include_archived,
    )
    total = session.scalar(
        _apply_filters(select(func.count()).select_from(Activity), **filters)
    )
    rows = session.scalars(
        _apply_filters(select(Activity), **filters)
        .order_by(Activity.start_date, Activity.id)
        .limit(capped)
    ).all()
    items = [_summarize(activity) for activity in rows]
    return {
        "total_matches": int(total or 0),
        "returned": len(items),
        "truncated": len(items) < int(total or 0),
        "note": _truncation_note(int(total or 0), len(items), capped),
        "activities": items,
    }


def _lookup(session: Session, identifier: str) -> Activity | None:
    text = (identifier or "").strip()
    if not text:
        return None
    try:
        as_uuid = uuid.UUID(text)
    except (ValueError, AttributeError):
        as_uuid = None
    if as_uuid is not None:
        found = session.get(Activity, as_uuid)
        if found is not None:
            return found
    return session.scalars(
        select(Activity)
        .where(func.lower(Activity.tracking_id) == text.lower())
        .order_by(Activity.updated_at.desc())
        .limit(1)
    ).first()


def get_activity(session: Session, identifier: str) -> dict[str, Any]:
    activity = _lookup(session, identifier)
    if activity is None:
        return {
            "found": False,
            "identifier": identifier,
            "note": "No activity with that id or tracking_id. Use search_activities to find one.",
        }
    # Serialized through the API's own read model rather than field by field:
    # that keeps the MCP's full record byte-identical to what GET
    # /api/activities/{id} returns, and inherits planning_lead_days and
    # tracking_pack_id instead of reimplementing them here.
    record: dict[str, Any] = ActivityRead.model_validate(activity).model_dump(mode="json")
    gaps = missing_fields(activity)
    record["missing_required_fields"] = gaps
    record["is_complete"] = not gaps
    return {"found": True, "activity": record}


def planning_gaps(
    session: Session,
    *,
    source_type: str | None = None,
    start_after: str | None = None,
    start_before: str | None = None,
    include_archived: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    """Activities failing the unified completeness rule, worst offenders first.

    The rule is evaluated in Python rather than SQL so it holds identically on
    SQLite and PostgreSQL; the candidate set is narrowed in SQL first.
    """
    capped = _clamp_limit(limit)
    filters = dict(
        text_query=None,
        channel=None,
        source_type=source_type,
        priority=None,
        lead=None,
        campaign=None,
        start_after=start_after,
        start_before=start_before,
        include_archived=include_archived,
    )
    candidates = session.scalars(
        _apply_filters(select(Activity), **filters).order_by(Activity.start_date, Activity.id)
    ).all()

    incomplete = []
    field_tally: dict[str, int] = {}
    for activity in candidates:
        gaps = missing_fields(activity)
        if not gaps:
            continue
        for field in gaps:
            field_tally[field] = field_tally.get(field, 0) + 1
        incomplete.append((activity, gaps))

    incomplete.sort(key=lambda pair: (-len(pair[1]), pair[0].start_date is None))
    shown = incomplete[:capped]
    return {
        "checked": len(candidates),
        "complete": len(candidates) - len(incomplete),
        "incomplete": len(incomplete),
        "returned": len(shown),
        "truncated": len(shown) < len(incomplete),
        "missing_field_counts": dict(
            sorted(field_tally.items(), key=lambda item: (-item[1], item[0]))
        ),
        "activities": [
            {
                **_summarize(activity),
                "missing_required_fields": gaps,
                "missing_count": len(gaps),
            }
            for activity, gaps in shown
        ],
    }


def _month_key(value: datetime | None) -> str:
    normalized = as_utc(value)
    if normalized is None:
        return "unscheduled"
    return f"{normalized.year:04d}-{normalized.month:02d}"


def activity_counts(
    session: Session,
    *,
    dimension: str,
    source_type: str | None = None,
    start_after: str | None = None,
    start_before: str | None = None,
    include_archived: bool = False,
) -> dict[str, Any]:
    if dimension not in GROUPABLE_FIELDS:
        return {
            "error": f"Unknown dimension {dimension!r}.",
            "supported_dimensions": list(GROUPABLE_FIELDS),
        }
    filters = dict(
        text_query=None,
        channel=None,
        source_type=source_type,
        priority=None,
        lead=None,
        campaign=None,
        start_after=start_after,
        start_before=start_before,
        include_archived=include_archived,
    )
    if dimension == "month":
        # Month bucketing is the one dimension without a portable SQL spelling
        # (date_trunc vs strftime), so it is grouped in Python over a
        # single-column select rather than branching per dialect.
        values = session.scalars(
            _apply_filters(select(Activity.start_date), **filters)
        ).all()
        tally: dict[str, int] = {}
        for value in values:
            key = _month_key(value)
            tally[key] = tally.get(key, 0) + 1
        buckets = [{"value": key, "count": count} for key, count in sorted(tally.items())]
        total = len(values)
    else:
        column = getattr(Activity, dimension)
        # Unassigned rows are surfaced as their own bucket, never dropped.
        label = func.coalesce(column, "Unassigned").cast(String)
        statement = _apply_filters(
            select(label.label("value"), func.count().label("count")), **filters
        ).group_by(label)
        rows = session.execute(statement).all()
        buckets = sorted(
            ({"value": value, "count": int(count)} for value, count in rows),
            key=lambda bucket: (-bucket["count"], str(bucket["value"])),
        )
        total = sum(bucket["count"] for bucket in buckets)
    return {"dimension": dimension, "total": total, "buckets": buckets}


def field_values(
    session: Session, *, field: str, limit: int | None = None
) -> dict[str, Any]:
    """Distinct stored values for a free-text column, with row counts.

    The schema stores channel/priority/region and friends as free text, so this
    is what an agent should call before filtering on a value it invented.

    Counts span archived activities as well, so a value occurring only on
    archived rows is still discoverable -- unlike `search_activities`, which
    hides archived rows by default.
    """
    if field not in ENUMERABLE_FIELDS:
        return {
            "error": f"Field {field!r} is not enumerable.",
            "supported_fields": list(ENUMERABLE_FIELDS),
        }
    capped = _clamp_limit(limit)
    column = getattr(Activity, field)
    rows = session.execute(
        select(column, func.count()).group_by(column).order_by(func.count().desc()).limit(capped)
    ).all()
    return {
        "field": field,
        "values": [
            {"value": value, "count": int(count)}
            for value, count in rows
            if not is_blank(value)
        ],
        "blank_count": sum(int(count) for value, count in rows if is_blank(value)),
    }


def database_status(session: Session, engine: Engine) -> dict[str, Any]:
    total = int(session.scalar(select(func.count()).select_from(Activity)) or 0)
    archived = int(
        session.scalar(
            select(func.count()).select_from(Activity).where(Activity.is_archive.is_(True))
        )
        or 0
    )
    by_source = {
        (value or "unknown"): int(count)
        for value, count in session.execute(
            select(Activity.source_type, func.count()).group_by(Activity.source_type)
        ).all()
    }
    earliest, latest = session.execute(
        select(func.min(Activity.start_date), func.max(Activity.start_date))
    ).one()
    changes = int(session.scalar(select(func.count()).select_from(ActivityChange)) or 0)
    latest_sync = session.scalars(
        select(SyncRun).order_by(SyncRun.ran_at.desc()).limit(1)
    ).first()
    return {
        "backend": engine.dialect.name,
        "read_only": True,
        "activities": {
            "total": total,
            "archived": archived,
            "by_source_type": by_source,
            "earliest_start_date": _iso(earliest),
            "latest_start_date": _iso(latest),
        },
        "change_log_entries": changes,
        "latest_sync_run": (
            None
            if latest_sync is None
            else {
                "ran_at": _iso(latest_sync.ran_at),
                "created": latest_sync.created,
                "updated": latest_sync.updated,
                "unchanged": latest_sync.unchanged,
                "conflicts": latest_sync.conflicts,
            }
        ),
    }
