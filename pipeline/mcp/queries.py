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

Laid out in one direction only -- constants, then value helpers, then the filter
machinery, then the public tools -- so nothing forward-references anything and the
file can be read top to bottom.

Every function returns plain JSON-ready dicts and caps its own result size: an
agent's context window is a hard resource, so no query here can reproduce the
unpaginated full-table response that `GET /api/activities` deliberately serves
to the studio.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field as dataclass_field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import String, and_, case, func, or_, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from pipeline.api.app import Activity, ActivityChange, ActivityRead, SyncRun, as_utc


# ------------------------------------------------------------------------
# Constants and vocabularies
# ------------------------------------------------------------------------


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

# Three columns hold several values in one string. The separators follow the ETL
# (`pipeline/scripts/process_cplan.py`): SharePoint lookup and taxonomy values are
# joined with ", " by `parse_sp_lookup`, person values with "; " by `PERSON_JOIN`
# for the columns in `SP_MULTI_PERSON_COLUMNS`.
#
# Person columns split on ";" ONLY -- deliberately unlike
# analytics.js::normalizeMulti, which splits both on /[;,]/. A person name may
# legitimately contain a comma ("Doe, Jane"), and splitting it would invent a
# person who does not exist. Lookup columns accept either, because the sync writes
# ", " while a studio-entered value may use "; ".
#
# Hazard, documented rather than solved: splitting a lookup value on "," is lossy
# -- a single objective whose own name contains a comma is indistinguishable from
# two objectives. Validate any published pillar tally against real values.
#
# `channel` and `target_audience` go through the same ", "-joining ETL path
# (`parse_sp_lookup`) and are just as genuinely multi-valued in the source
# data, but stay OUT of this dict on purpose: it feeds MULTI_VALUE_DIMENSIONS,
# which drives activity_counts's SQL-eligibility gate and `counts_memberships`,
# field_values's splitting, and the groupable/enumerable vocabularies -- for
# every column here, not only the one a future editor is thinking about.
# `detect_collisions` needs real membership semantics for exactly those two
# columns and forks its own separator set for it (`_normalize_multi`, near
# that function) rather than widening this one.
MULTI_VALUE_SEPARATORS: dict[str, tuple[str, ...]] = {
    "strategic_objectives": (",", ";"),
    "bod_geb": (";",),
    "other_executives": (";",),
}

# Executive involvement is split across two columns -- executive-board members and
# senior leaders who are not on that board -- and the `executive` filter spans both.
# Named once, because the SQL prefilter and the Python exact check MUST cover the
# same columns or rows are silently dropped.
EXECUTIVE_COLUMNS: tuple[str, ...] = ("bod_geb", "other_executives")

# The two live priority vocabularies, mirroring analytics.js::priorityRank.
#
# The studio's entry form offers Critical / High / Medium / Low. Rows mirrored in
# from the source system instead carry a numbered label, "<n> - <label>", with four
# levels where 1 is the most urgent and 4 the least. The labels are internal
# governance wording and are deliberately not reproduced here -- only the leading
# digit carries meaning for this code.
#
# A leading integer wins because it is unambiguous. Anything in neither shape
# lands on the middle rank rather than silently reading as low: matching only the
# words was a real defect, and it made every mirrored record score the default
# while the portfolio held thousands of level-1 and level-2 activities.
PRIORITY_WORD_RANKS: dict[str, int] = {
    "critical": 4,
    "high": 3,
    "medium": 2,
    "normal": 1,
    "low": 0,
}

DEFAULT_PRIORITY_RANK = 1

HIGH_PRIORITY_RANK = 3

_LEADING_INTEGER = re.compile(r"^(\d+)")

# Every case-insensitive equality filter an agent may apply. Free text in the
# schema, so `field_values` remains the way to learn the real values first.
FILTERABLE_TEXT_FIELDS: tuple[str, ...] = (
    "source_type",
    "channel",
    "priority",
    "lead",
    "lead_team",
    "partner_team",
    # Three keys describe "which campaign is this part of", at different
    # granularities, and picking the wrong one silently answers a different
    # question. `communication_pack_cpid` is the pack -- the planning unit a
    # planner actually owns. `campaign` is coarser: measured against the same
    # 400-row portfolio the studio's campaignScorecards comment cites, the pack
    # id resolved 32 packs of 2-11 activities while `campaign` collapsed the same
    # rows into 4 buckets of ~60. A bucket of 60 is a category, not a campaign,
    # so every roll-up built on `campaign` describes the portfolio instead of a
    # planning unit. Both stay exposed and the domain-model resource explains
    # the difference; the pack id is the one to group by.
    "communication_pack_cpid",
    "communication_pack",
    "campaign",
    "region",
    "business_division",
    "business_area",
    "target_audience",
    "audience",
    "time_zone",
)

# Columns an agent may group or enumerate. Free-text columns in the schema are not
# enumerated types, so `field_values` is what stops the model from guessing filter
# values that do not exist -- which means every filterable column must appear
# here too (pinned by test_every_filterable_column_is_also_discoverable).
MULTI_VALUE_DIMENSIONS: tuple[str, ...] = tuple(MULTI_VALUE_SEPARATORS)

# The three time grains `activity_counts` can bucket `start_date` into. Ordered
# fine to coarse; `_time_bucket_key` dispatches on these names, and each has no
# portable SQL spelling (day/week have none at all; month would need
# date_trunc on PostgreSQL vs strftime on SQLite), so all three are grouped in
# Python rather than SQL -- the same reason `month` already was before this
# tuple existed.
TIME_BUCKETS: tuple[str, ...] = ("day", "week", "month")

GROUPABLE_FIELDS: tuple[str, ...] = (
    *FILTERABLE_TEXT_FIELDS,
    *MULTI_VALUE_DIMENSIONS,
    "priority_rank",
    *TIME_BUCKETS,
)

# 'day'/'week'/'month' and 'priority_rank' are derived, not stored, so they are
# groupable but not enumerable.
ENUMERABLE_FIELDS: tuple[str, ...] = (
    *FILTERABLE_TEXT_FIELDS,
    *MULTI_VALUE_DIMENSIONS,
)

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

# `detect_collisions`'s sliding window has no cap of its own: the inner loop's
# `break` only fires once the gap exceeds `proximity_days`, so an unbounded
# value lets it accumulate (and `_summarize`) every pair in the filtered set
# BEFORE `_clamp_limit` ever runs -- exactly the unbounded intermediate list
# this module's own docstring promises never to build. 90 days already spans
# a full planning quarter, well past what "activities near each other" means
# for this question.
MAX_PROXIMITY_DAYS = 90

# A cross-tab multiplies two dimensions together (32 packs x 15 channels is 480
# cells), and the flat MAX_LIMIT cap is the wrong shape for that: sorting the
# flat cell list by count and slicing drops whole rows/columns of the table
# rather than showing a smaller-but-complete one, which reads to an agent as
# a full cross-tab that is quietly missing data. Capping each axis to its top
# MAX_CROSS_AXIS values by total count keeps a coherent (if smaller) table
# instead, and `axis_truncated` says which axis, if any, was cut.
MAX_CROSS_AXIS = 20


# ------------------------------------------------------------------------
# Value helpers -- pure, no session, no SQL
# ------------------------------------------------------------------------


def is_blank(value: Any) -> bool:
    """The text-emptiness rule shared with analytics.js and v_planning_completeness."""
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    return stripped == "" or stripped in BLANK_TEXT_SENTINELS


def _split_on(text: str, separators: tuple[str, ...]) -> list[str]:
    """The trimmed, non-blank members of `text` split on any of `separators`.

    The one splitting algorithm shared by every multi-value fork in this
    module: `split_multi` (separator set chosen per column, via
    MULTI_VALUE_SEPARATORS) and `_normalize_multi` (separator set fixed at
    "," and ";" for every call, for `detect_collisions`). Only the separator
    *configuration* forks between the two; the trim-and-drop-blanks rule
    stays written once so it cannot drift between them.
    """
    pattern = "[" + re.escape("".join(separators)) + "]"
    return [member.strip() for member in re.split(pattern, text) if not is_blank(member)]


def split_multi(value: Any, field: str) -> list[str]:
    """The individual members of a possibly multi-valued column.

    Returns [] for a blank value (same rule as `is_blank`), and a single-member
    list for a column that is not multi-valued -- so callers can treat every
    column uniformly. `channel` and `target_audience` deliberately land on
    this scalar branch: they are declared multi-valued in the real data but
    not in MULTI_VALUE_SEPARATORS (see the comment above that dict). Do not
    "fix" this without reading `_normalize_multi` near `detect_collisions`
    first -- two tests pin the scalar behaviour on purpose.

    Individual members are held to the same blank rule as whole values: a
    "Objective A; None" mix drops the sentinel rather than offering it as a
    discoverable filter value in `field_values`, a bucket in `activity_counts`
    and a group in `planning_gaps`.
    """
    if is_blank(value):
        return []
    text = str(value)
    separators = MULTI_VALUE_SEPARATORS.get(field)
    if not separators:
        return [text.strip()]
    return _split_on(text, separators)


def priority_rank(value: Any) -> int:
    """0-4, higher is more urgent, across both live priority vocabularies."""
    text = "" if value is None else str(value).strip()
    numbered = _LEADING_INTEGER.match(text)
    if numbered:
        return max(0, 5 - int(numbered.group(1)))
    return PRIORITY_WORD_RANKS.get(text.lower(), DEFAULT_PRIORITY_RANK)


def is_high_priority(value: Any) -> bool:
    """'Critical and high' in one place -- numbered levels 1-2, or the words."""
    return priority_rank(value) >= HIGH_PRIORITY_RANK


def lead_days(activity: Activity) -> int | None:
    """Whole days between the reference timestamp and start_date.

    Mirrors ActivityRead.planning_lead_days: the reference is source_created_at
    when set, else created_at. Computed here in Python rather than in SQL on
    purpose -- v_lead_times uses PostgreSQL round(), which rounds an exact half
    day away from zero while Python rounds to even, so a SQL implementation would
    disagree with the API by a day on that edge case.
    """
    if activity.start_date is None:
        return None
    reference = activity.source_created_at or activity.created_at
    if reference is None:
        return None
    delta = as_utc(activity.start_date) - as_utc(reference)
    return round(delta.total_seconds() / 86400)


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


def _truncate_to_midnight(value: datetime) -> datetime:
    """`value` at 00:00:00 UTC on the same date -- mirrors the studio's
    `setHours(0, 0, 0, 0)` in `weeklyCoverage`."""
    normalized = as_utc(value)
    return normalized.replace(hour=0, minute=0, second=0, microsecond=0)


def _month_key(value: datetime | None) -> str:
    normalized = as_utc(value)
    if normalized is None:
        return "unscheduled"
    return f"{normalized.year:04d}-{normalized.month:02d}"


def _time_bucket_key(value: datetime | None, bucket: str) -> str:
    """The bucket label for `value` at `bucket` grain -- one of TIME_BUCKETS.

    `day` -> 'YYYY-MM-DD', `week` -> ISO 'YYYY-Www' (via `date.isocalendar()`,
    so the ISO year can differ from the calendar year in late December -- by
    design, not a bug: that is the week the day actually belongs to), `month`
    -> `_month_key`'s existing shape. `None` -> 'unscheduled' on every grain,
    matching `_month_key`.
    """
    if bucket == "month":
        return _month_key(value)
    normalized = as_utc(value)
    if normalized is None:
        return "unscheduled"
    if bucket == "day":
        return f"{normalized.year:04d}-{normalized.month:02d}-{normalized.day:02d}"
    if bucket == "week":
        iso_year, iso_week, _ = normalized.isocalendar()
        return f"{iso_year:04d}-W{iso_week:02d}"
    raise ValueError(f"Unknown time bucket {bucket!r}; expected one of {TIME_BUCKETS}")


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


def _bucket_keys(activity: Activity, field: str) -> list[str]:
    """The group labels one activity contributes for `field`.

    The single labelling rule for every Python-side grouping path, so
    `activity_counts` and `planning_gaps` cannot label the same data differently:
    a multi-value column contributes one label per member, a single-value column
    contributes its trimmed value, and a blank value contributes "Unassigned"
    rather than being dropped.
    """
    return split_multi(getattr(activity, field), field) or ["Unassigned"]


# Dimensions with no stored column to `GROUP BY` on -- each needs a Python rule
# (a time grain, or the two-vocabulary priority rule) rather than a SQL label.
# Shared by the single- and two-dimension paths of `activity_counts` so both
# route the same set of names into the Python-grouped branch.
DERIVED_DIMENSIONS: tuple[str, ...] = (*TIME_BUCKETS, "priority_rank")


def _dimension_keys(activity: Activity, dimension: str) -> list[str]:
    """The group labels one activity contributes for any GROUPABLE_FIELDS name.

    One dispatch point for every grouping path in this module (single- and
    two-dimension `activity_counts` alike): a time grain goes through
    `_time_bucket_key`, `priority_rank` through the two-vocabulary rule, and
    everything else -- stored scalar or multi-value -- through `_bucket_keys`,
    exactly as `planning_gaps` labels its groups.
    """
    if dimension in TIME_BUCKETS:
        return [_time_bucket_key(activity.start_date, dimension)]
    if dimension == "priority_rank":
        return [str(priority_rank(activity.priority))]
    return _bucket_keys(activity, dimension)


def _capped_by_count(
    tally: dict[str, int], *, chronological: bool = False
) -> tuple[list[dict[str, Any]], int, int]:
    """The buckets to report, the true total, and the true bucket count.

    Grouping is capped like every other list-shaped answer here: a real portfolio
    grouped by campaign yields four figures' worth of buckets, which is exactly
    the unbounded response the module refuses to serve. The cap keeps the largest
    buckets; `total` stays the true total across ALL of them, so a truncated
    answer still reports the right volume.
    """
    ordered = sorted(
        ({"value": key, "count": count} for key, count in tally.items()),
        key=lambda bucket: (-bucket["count"], str(bucket["value"])),
    )
    kept = ordered[:MAX_LIMIT]
    if chronological:
        # Months read in time order, but it is still the biggest months that
        # survive the cap rather than an arbitrary prefix of the timeline.
        kept = sorted(kept, key=lambda bucket: str(bucket["value"]))
    return kept, sum(tally.values()), len(ordered)


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
    # Derived, so a mixed-vocabulary result set can be ranked without the model
    # having to know the two priority schemes.
    row["priority_rank"] = priority_rank(activity.priority)
    row["is_high_priority"] = is_high_priority(activity.priority)
    return row


def _truncation_note(
    total: int, returned: int, limit: int, subject: str = "matching activities"
) -> str | None:
    if returned >= total:
        return None
    return (
        f"Showing {returned} of {total} {subject} (limit={limit}). "
        "Narrow the filters rather than raising the limit -- this tool never "
        "returns the whole table."
    )


def _value_truncation_note(distinct: int, returned: int, limit: int) -> str | None:
    """Truncation note for a value list, where 'narrow the filters' does not apply."""
    if returned >= distinct:
        return None
    return (
        f"Showing the {returned} most common of {distinct} distinct values "
        f"(limit={limit}). Values absent from this list still exist in the data -- "
        "do not treat it as the complete vocabulary of this column."
    )


# ------------------------------------------------------------------------
# Filter machinery -- shared by every tool below
# ------------------------------------------------------------------------


@dataclass(frozen=True)
class ActivityFilters:
    """Everything that narrows an activity query, in one object.

    `text` maps a column in FILTERABLE_TEXT_FIELDS to a value compared
    case-insensitively for equality. Keeping it as a mapping rather than one
    attribute per column is what stops the four query functions from each
    carrying a twenty-line signature; the MCP tool layer still exposes explicit
    named parameters, because those are what the model discovers.
    """

    text_query: str | None = None
    text: dict[str, str] = dataclass_field(default_factory=dict)
    start_after: str | None = None
    start_before: str | None = None
    end_after: str | None = None
    end_before: str | None = None
    include_archived: bool = False
    news_digest: bool | None = None
    has_tracking_id: bool | None = None
    has_executive: bool | None = None
    locally_modified: bool | None = None
    # Archived is a source-system view-size workaround, not a relevance signal --
    # so it gets an explicit "only these" mode rather than only a hide/show flag.
    archived_only: bool = False
    # Exact membership in a multi-value column: {column_name: one member value}.
    contains: dict[str, str] = dataclass_field(default_factory=dict)
    # Exact membership in EITHER executive column -- an OR across two columns, which
    # the single-column `contains` mapping cannot express, so it gets its own field
    # rather than a bespoke implementation in one tool.
    executive: str | None = None
    max_lead_days: int | None = None
    min_priority_rank: int | None = None


def _blank_sql(column):
    """`is_blank` in portable SQL: NULL, whitespace-only, or a sentinel string.

    The single spelling of "blank" for every SQL predicate here. Two spellings is
    how `has_tracking_id` came to report an activity whose tracking_id is the
    literal 'None' -- the exact sentinel the sync leaks in -- as HAVING one.
    """
    trimmed = func.trim(column)
    return or_(column.is_(None), trimmed == "", trimmed.in_(BLANK_TEXT_SENTINELS))


def _apply_filters(statement, filters: ActivityFilters):
    if filters.text_query:
        needle = f"%{filters.text_query.strip().lower()}%"
        statement = statement.where(
            or_(
                func.lower(Activity.activity_name).like(needle),
                func.lower(func.coalesce(Activity.tracking_id, "")).like(needle),
                func.lower(func.coalesce(Activity.activity_description, "")).like(needle),
            )
        )
    # Case-insensitive equality throughout: the columns are free text, so an
    # agent that guesses "Email" for a stored "email" should still get its rows.
    for column_name, value in filters.text.items():
        if not value:
            continue
        column = getattr(Activity, column_name)
        statement = statement.where(func.lower(column) == value.strip().lower())
    # A cheap substring prefilter only: "Objective A" also matches "Objective AB",
    # so `passes_post_filter` decides membership exactly. Narrowing here keeps the
    # candidate set small; correctness happens in Python.
    for column_name, member in filters.contains.items():
        if not member:
            continue
        column = getattr(Activity, column_name)
        needle = f"%{member.strip().lower()}%"
        statement = statement.where(func.lower(func.coalesce(column, "")).like(needle))
    if filters.executive:
        # Same prefilter-then-decide shape as `contains`, but OR'd across the two
        # executive columns. `passes_post_filter` spans exactly these columns too.
        needle = f"%{filters.executive.strip().lower()}%"
        statement = statement.where(
            or_(
                *(
                    func.lower(func.coalesce(getattr(Activity, name), "")).like(needle)
                    for name in EXECUTIVE_COLUMNS
                )
            )
        )
    for column, raw, lower_bound in (
        (Activity.start_date, filters.start_after, True),
        (Activity.start_date, filters.start_before, False),
        (Activity.end_date, filters.end_after, True),
        (Activity.end_date, filters.end_before, False),
    ):
        boundary = _parse_boundary(raw)
        if boundary is None:
            continue
        statement = statement.where(column >= boundary if lower_bound else column <= boundary)
    if filters.news_digest is not None:
        statement = statement.where(Activity.news_digest.is_(filters.news_digest))
    if filters.has_tracking_id is not None:
        blank = _blank_sql(Activity.tracking_id)
        statement = statement.where(~blank if filters.has_tracking_id else blank)
    if filters.has_executive is not None:
        # "Any executive involved" is: at least one of the two columns is non-blank.
        no_executive = and_(*(_blank_sql(getattr(Activity, name)) for name in EXECUTIVE_COLUMNS))
        statement = statement.where(
            ~no_executive if filters.has_executive else no_executive
        )
    if filters.locally_modified is not None:
        # synced_version IS NULL means "never synced", which is not divergence.
        diverged = and_(
            Activity.synced_version.is_not(None),
            Activity.version > Activity.synced_version,
        )
        statement = statement.where(diverged if filters.locally_modified else ~diverged)
    if filters.archived_only:
        statement = statement.where(Activity.is_archive.is_(True))
    elif not filters.include_archived:
        statement = statement.where(Activity.is_archive.is_(False))
    return statement


def needs_post_filter(filters: ActivityFilters) -> bool:
    """True when a predicate cannot be evaluated in portable SQL.

    When this is False, the caller keeps the cheap SELECT COUNT path.
    """
    return bool(
        filters.contains
        or filters.executive
        or filters.max_lead_days is not None
        or filters.min_priority_rank is not None
    )


def passes_post_filter(activity: Activity, filters: ActivityFilters) -> bool:
    """The predicates SQL cannot express portably, evaluated exactly."""
    for column_name, member in filters.contains.items():
        if not member:
            continue
        wanted = member.strip().lower()
        members = {value.lower() for value in split_multi(getattr(activity, column_name), column_name)}
        if wanted not in members:
            return False
    if filters.executive:
        wanted = filters.executive.strip().lower()
        # Spans EXECUTIVE_COLUMNS, exactly like the SQL prefilter above.
        members = {
            value.lower()
            for name in EXECUTIVE_COLUMNS
            for value in split_multi(getattr(activity, name), name)
        }
        if wanted not in members:
            return False
    if filters.max_lead_days is not None:
        days = lead_days(activity)
        if days is None or days > filters.max_lead_days:
            return False
    if filters.min_priority_rank is not None:
        if priority_rank(activity.priority) < filters.min_priority_rank:
            return False
    return True


def _build_filters(**kwargs: Any) -> ActivityFilters:
    """Build an ActivityFilters from the flat keyword set the tools expose.

    One place that knows which keyword goes into `text`, which into `contains`
    and which is a scalar, so search, counts and gaps cannot drift apart.
    """
    text = {
        name: kwargs.pop(name, None)
        for name in FILTERABLE_TEXT_FIELDS
    }
    contains = {"strategic_objectives": kwargs.pop("strategic_objective", None)}
    filters = ActivityFilters(
        text_query=kwargs.pop("query", None),
        text={name: value for name, value in text.items() if value},
        contains={name: value for name, value in contains.items() if value},
        executive=kwargs.pop("executive", None),
        start_after=kwargs.pop("start_after", None),
        start_before=kwargs.pop("start_before", None),
        end_after=kwargs.pop("end_after", None),
        end_before=kwargs.pop("end_before", None),
        include_archived=kwargs.pop("include_archived", False),
        archived_only=kwargs.pop("archived_only", False),
        news_digest=kwargs.pop("news_digest", None),
        has_tracking_id=kwargs.pop("has_tracking_id", None),
        has_executive=kwargs.pop("has_executive", None),
        locally_modified=kwargs.pop("locally_modified", None),
        max_lead_days=kwargs.pop("max_lead_days", None),
        min_priority_rank=kwargs.pop("min_priority_rank", None),
    )
    if kwargs:
        # These keywords come from our own call sites, never from raw user
        # input, so an unrecognised one is a programming error -- a typo'd
        # filter name must fail loudly rather than silently return a
        # confidently wrong, unfiltered tally. Same shape as Python's own
        # unexpected-keyword-argument TypeError.
        unexpected = ", ".join(sorted(kwargs))
        raise TypeError(f"_build_filters() got unexpected keyword argument(s): {unexpected}")
    return filters


def _filtered_activities(session: Session, filters: ActivityFilters) -> list[Activity]:
    """Every activity matching `filters`, SQL first then the Python predicates."""
    candidates = session.scalars(
        _apply_filters(select(Activity), filters).order_by(Activity.start_date, Activity.id)
    ).all()
    if not needs_post_filter(filters):
        return list(candidates)
    return [activity for activity in candidates if passes_post_filter(activity, filters)]


# ------------------------------------------------------------------------
# Public tools
# ------------------------------------------------------------------------


def search_activities(
    session: Session,
    *,
    query: str | None = None,
    channel: str | None = None,
    source_type: str | None = None,
    priority: str | None = None,
    lead: str | None = None,
    lead_team: str | None = None,
    partner_team: str | None = None,
    region: str | None = None,
    business_division: str | None = None,
    business_area: str | None = None,
    target_audience: str | None = None,
    audience: str | None = None,
    time_zone: str | None = None,
    communication_pack_cpid: str | None = None,
    communication_pack: str | None = None,
    campaign: str | None = None,
    start_after: str | None = None,
    start_before: str | None = None,
    end_after: str | None = None,
    end_before: str | None = None,
    news_digest: bool | None = None,
    has_tracking_id: bool | None = None,
    has_executive: bool | None = None,
    locally_modified: bool | None = None,
    archived_only: bool = False,
    include_archived: bool = False,
    strategic_objective: str | None = None,
    executive: str | None = None,
    max_lead_days: int | None = None,
    min_priority_rank: int | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    capped = _clamp_limit(limit)
    filters = _build_filters(
        query=query,
        channel=channel,
        source_type=source_type,
        priority=priority,
        lead=lead,
        lead_team=lead_team,
        partner_team=partner_team,
        communication_pack_cpid=communication_pack_cpid,
        communication_pack=communication_pack,
        campaign=campaign,
        region=region,
        business_division=business_division,
        business_area=business_area,
        target_audience=target_audience,
        audience=audience,
        time_zone=time_zone,
        strategic_objective=strategic_objective,
        executive=executive,
        start_after=start_after,
        start_before=start_before,
        end_after=end_after,
        end_before=end_before,
        include_archived=include_archived,
        archived_only=archived_only,
        news_digest=news_digest,
        has_tracking_id=has_tracking_id,
        has_executive=has_executive,
        locally_modified=locally_modified,
        max_lead_days=max_lead_days,
        min_priority_rank=min_priority_rank,
    )
    if needs_post_filter(filters):
        # A Python predicate is active, so the count has to come from the
        # filtered set rather than from SQL. SQL still does the narrowing.
        matching = _filtered_activities(session, filters)
        total = len(matching)
        rows = matching[:capped]
    else:
        total = int(
            session.scalar(_apply_filters(select(func.count()).select_from(Activity), filters)) or 0
        )
        rows = session.scalars(
            _apply_filters(select(Activity), filters)
            .order_by(Activity.start_date, Activity.id)
            .limit(capped)
        ).all()
    items = [_summarize(activity) for activity in rows]
    return {
        "total_matches": int(total),
        "returned": len(items),
        "truncated": len(items) < int(total),
        "note": _truncation_note(int(total), len(items), capped),
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
    record["priority_rank"] = priority_rank(activity.priority)
    record["is_high_priority"] = is_high_priority(activity.priority)
    return {"found": True, "activity": record}


def planning_gaps(
    session: Session,
    *,
    group_by: str | None = None,
    limit: int | None = None,
    **filter_kwargs: Any,
) -> dict[str, Any]:
    """Activities failing the unified completeness rule, worst offenders first.

    The rule is evaluated in Python rather than SQL so it holds identically on
    SQLite and PostgreSQL; the candidate set is narrowed in SQL first.

    `group_by` additionally reports completeness per group -- which team or
    channel is behind, rather than only which records are.
    """
    if group_by is not None and group_by not in ENUMERABLE_FIELDS:
        return {
            "error": f"Cannot group planning gaps by {group_by!r}.",
            "supported_dimensions": list(ENUMERABLE_FIELDS),
        }
    capped = _clamp_limit(limit)
    filters = _build_filters(**filter_kwargs)
    candidates = _filtered_activities(session, filters)

    incomplete: list[tuple[Activity, list[str]]] = []
    field_tally: dict[str, int] = {}
    groups: dict[str, dict[str, int]] = {}
    for activity in candidates:
        gaps = missing_fields(activity)
        if group_by is not None:
            # `_bucket_keys`, so a group label here is the same label
            # `activity_counts` gives the same value.
            for key in _bucket_keys(activity, group_by):
                bucket = groups.setdefault(key, {"checked": 0, "complete": 0, "incomplete": 0})
                bucket["checked"] += 1
                bucket["incomplete" if gaps else "complete"] += 1
        if not gaps:
            continue
        for name in gaps:
            field_tally[name] = field_tally.get(name, 0) + 1
        incomplete.append((activity, gaps))

    incomplete.sort(key=lambda pair: (-len(pair[1]), pair[0].start_date is None))
    shown = incomplete[:capped]
    answer: dict[str, Any] = {
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
    if group_by is not None:
        # Capped like every other list here -- grouping by a high-cardinality
        # column (campaign) yields thousands of groups otherwise. Worst group
        # first, so the cap keeps the groups the answer is about. `groups_truncated`
        # rather than `truncated`, which already reports the activity list.
        ordered_groups = sorted(
            ({"value": key, **counts} for key, counts in groups.items()),
            key=lambda group: (-group["incomplete"], -group["checked"], group["value"]),
        )
        answer["group_by"] = group_by
        answer["group_count"] = len(ordered_groups)
        answer["groups"] = ordered_groups[:MAX_LIMIT]
        answer["groups_truncated"] = len(answer["groups"]) < len(ordered_groups)
        if answer["groups_truncated"]:
            answer["groups_note"] = _truncation_note(
                len(ordered_groups), len(answer["groups"]), MAX_LIMIT, subject=f"{group_by} groups"
            )
    return answer


def _sql_label(column) -> Any:
    """The stored-column SQL label expression shared by both count branches.

    Unassigned rows are surfaced as their own bucket, never dropped. The blank
    rule is `_blank_sql`, the same one every other SQL predicate here uses -- a
    plain `coalesce(column, "Unassigned")` only catches NULL, which let
    identical data land in a literal "None"/"   " bucket here while the Python
    branch folds it into "Unassigned", so the bucket name an agent saw
    depended on which branch happened to run rather than on the data itself.
    Trimmed, because the Python branch's labels are trimmed (`split_multi`
    strips every member): without this, " Email " is a bucket of its own here
    and folds into "Email" there.
    """
    return case((_blank_sql(column), "Unassigned"), else_=func.trim(column)).cast(String)


def activity_counts(
    session: Session,
    *,
    dimension: str,
    second_dimension: str | None = None,
    **filter_kwargs: Any,
) -> dict[str, Any]:
    """Activity volume grouped by one or two dimensions, honouring every search filter.

    With `second_dimension` this is a cross-tab: each returned bucket carries
    both `value` and `second_value`. Without it, the response keeps the exact
    one-dimensional shape this tool has always returned -- no `second_value`
    key anywhere, so a caller that never asked for a second dimension sees no
    difference at all.
    """
    if dimension not in GROUPABLE_FIELDS:
        return {
            "error": f"Unknown dimension {dimension!r}.",
            "supported_dimensions": list(GROUPABLE_FIELDS),
        }
    if second_dimension is not None and second_dimension not in GROUPABLE_FIELDS:
        return {
            "error": f"Unknown dimension {second_dimension!r}.",
            "supported_dimensions": list(GROUPABLE_FIELDS),
        }
    filters = _build_filters(**filter_kwargs)

    if second_dimension is None:
        counts_memberships = dimension in MULTI_VALUE_DIMENSIONS
        if dimension in DERIVED_DIMENSIONS or counts_memberships or needs_post_filter(filters):
            # Grouped in Python: every DERIVED_DIMENSIONS name has no portable
            # SQL spelling (date grains, or the two-vocabulary priority rule),
            # and a multi-value dimension has to be split before it can be
            # tallied.
            rows = _filtered_activities(session, filters)
            tally: dict[str, int] = {}
            for activity in rows:
                for key in _dimension_keys(activity, dimension):
                    tally[key] = tally.get(key, 0) + 1
            buckets, total, bucket_count = _capped_by_count(
                tally, chronological=dimension in TIME_BUCKETS
            )
        else:
            column = getattr(Activity, dimension)
            label = _sql_label(column)
            statement = _apply_filters(
                select(label.label("value"), func.count().label("count")), filters
            ).group_by(label)
            tally = {value: int(count) for value, count in session.execute(statement).all()}
            buckets, total, bucket_count = _capped_by_count(tally)
        return {
            "dimension": dimension,
            "total": total,
            "counts_memberships": counts_memberships,
            "bucket_count": bucket_count,
            "truncated": len(buckets) < bucket_count,
            "buckets": buckets,
            "note": _truncation_note(
                bucket_count, len(buckets), MAX_LIMIT, subject=f"{dimension} buckets"
            ),
        }

    # --- Cross-tab: two dimensions -------------------------------------
    counts_memberships = (
        dimension in MULTI_VALUE_DIMENSIONS or second_dimension in MULTI_VALUE_DIMENSIONS
    )
    sql_eligible = (
        dimension not in DERIVED_DIMENSIONS
        and second_dimension not in DERIVED_DIMENSIONS
        and not counts_memberships
        and not needs_post_filter(filters)
    )
    cross_tally: dict[tuple[str, str], int] = {}
    if sql_eligible:
        # Both axes are stored scalars and no Python post-filter is active, so
        # a single two-column SQL GROUP BY replaces materialising every row --
        # the same condition Phase 1's single-dimension branch uses, extended
        # to both columns at once.
        first_label = _sql_label(getattr(Activity, dimension))
        second_label = _sql_label(getattr(Activity, second_dimension))
        statement = _apply_filters(
            select(
                first_label.label("value"),
                second_label.label("second_value"),
                func.count().label("count"),
            ),
            filters,
        ).group_by(first_label, second_label)
        for first_value, second_value, count in session.execute(statement).all():
            cross_tally[(first_value, second_value)] = int(count)
    else:
        # A derived or multi-value axis (or an active post-filter) forces
        # Python grouping, same as the single-dimension branch. A multi-value
        # axis contributes one label per member on EACH side, so a two-member
        # activity tallies into every (first, second) combination it belongs
        # to -- matching "counts_memberships becomes true if either axis is
        # multi-valued".
        rows = _filtered_activities(session, filters)
        for activity in rows:
            first_keys = _dimension_keys(activity, dimension)
            second_keys = _dimension_keys(activity, second_dimension)
            for first_key in first_keys:
                for second_key in second_keys:
                    pair = (first_key, second_key)
                    cross_tally[pair] = cross_tally.get(pair, 0) + 1

    first_totals: dict[str, int] = {}
    second_totals: dict[str, int] = {}
    for (first_key, second_key), count in cross_tally.items():
        first_totals[first_key] = first_totals.get(first_key, 0) + count
        second_totals[second_key] = second_totals.get(second_key, 0) + count

    def _top_keys(totals: dict[str, int]) -> set[str]:
        ordered = sorted(totals.items(), key=lambda item: (-item[1], str(item[0])))
        return {key for key, _ in ordered[:MAX_CROSS_AXIS]}

    kept_first = _top_keys(first_totals)
    kept_second = _top_keys(second_totals)
    axis_truncated = {
        "dimension": len(first_totals) > MAX_CROSS_AXIS,
        "second_dimension": len(second_totals) > MAX_CROSS_AXIS,
    }
    distinct_values = {
        "dimension": len(first_totals),
        "second_dimension": len(second_totals),
    }
    buckets = sorted(
        (
            {"value": first_key, "second_value": second_key, "count": count}
            for (first_key, second_key), count in cross_tally.items()
            if first_key in kept_first and second_key in kept_second
        ),
        key=lambda bucket: (-bucket["count"], str(bucket["value"]), str(bucket["second_value"])),
    )
    truncated = axis_truncated["dimension"] or axis_truncated["second_dimension"]
    note = None
    if truncated:
        clauses = []
        if axis_truncated["dimension"]:
            clauses.append(f"top {MAX_CROSS_AXIS} of {distinct_values['dimension']} {dimension} values")
        if axis_truncated["second_dimension"]:
            clauses.append(
                f"top {MAX_CROSS_AXIS} of {distinct_values['second_dimension']} {second_dimension} values"
            )
        note = (
            "Showing the " + " by the ".join(clauses) + " (ranked by total count). "
            "Narrow the filters to bring the rest of the table into view -- this is "
            "a smaller, complete cross-tab, not a truncated prefix of a larger one."
        )
    return {
        "dimension": dimension,
        "second_dimension": second_dimension,
        "total": sum(cross_tally.values()),
        "counts_memberships": counts_memberships,
        "distinct_values": distinct_values,
        "axis_truncated": axis_truncated,
        "truncated": truncated,
        "buckets": buckets,
        "note": note,
    }


# `channel` and `target_audience` are genuinely multi-valued in the source data
# (`process_cplan.py` runs both through `parse_sp_lookup`, the same ", "-joining
# lookup path as `strategic_objectives`), but they are deliberately absent from
# MULTI_VALUE_SEPARATORS: Phase 1 treats them as scalar for filtering
# (`search_activities`'s exact-match `text` filter) and for grouping
# (`activity_counts`'s SQL-eligible branch, `counts_memberships`), and two tests
# pin that on purpose -- test_split_multi_returns_a_single_member_for_a_scalar_column
# and test_cross_tab_buckets_a_derived_time_axis (`channel x month` must stay
# `counts_memberships: False`). Reusing `split_multi` for collision detection
# would either silently fail to split (today) or flip those two columns to
# multi-valued everywhere the moment they were added to the shared dict
# (tomorrow) -- exactly the kind of change this function must NOT make as a
# side effect of getting its own rule right. `_normalize_multi` is therefore a
# second, narrower split -- scoped to this one rule -- that mirrors
# analytics.js::normalizeMulti exactly (splits on EITHER "," or ";"
# unconditionally, unlike split_multi's per-column allowlist). It shares
# `_split_on`'s algorithm with `split_multi`; only the separator set forks.
_COLLISION_SEPARATORS: tuple[str, ...] = (",", ";")


def _normalize_multi(value: Any) -> list[str]:
    """The member values of `value`, splitting on `,` OR `;` unconditionally.

    Mirrors analytics.js::normalizeMulti for exactly the two columns
    `detect_collisions` needs it for (`channel`, `target_audience`). See the
    comment above this function for why it is not `split_multi`.
    """
    if is_blank(value):
        return []
    return _split_on(str(value), _COLLISION_SEPARATORS)


def _shared_members(left: Activity, right: Activity, field: str) -> list[str]:
    """The `field` members `left` and `right` have in common, case-insensitively.

    Mirrors analytics.js::sharesDimension's set intersection, but returns the
    members themselves rather than a bare boolean: `detect_collisions` reports
    these as `shared_channels` / `shared_audiences` so an agent can say WHY a
    pair collided, not only that it did. Casing is preserved from `left`'s
    spelling when the two sides disagree ("Email" vs "email") -- an arbitrary
    but deterministic choice, matching `_shares_dimension`'s old left-anchored
    comparison order.
    """
    right_members = {member.lower() for member in _normalize_multi(getattr(right, field))}
    if not right_members:
        return []
    seen: set[str] = set()
    shared: list[str] = []
    for member in _normalize_multi(getattr(left, field)):
        key = member.lower()
        if key in right_members and key not in seen:
            seen.add(key)
            shared.append(member)
    return shared


def _epoch_day(value: datetime) -> int:
    """Whole days between the UTC epoch and `value`'s UTC calendar date.

    Mirrors analytics.js::detectCollisions' `Date.UTC(y, m, d) / 86400000`:
    the gap between two activities is measured in calendar days, not elapsed
    seconds.
    """
    normalized = as_utc(value)
    return (normalized.date() - date(1970, 1, 1)).days


def detect_collisions(
    session: Session,
    *,
    proximity_days: int = 0,
    limit: int | None = None,
    **filter_kwargs: Any,
) -> dict[str, Any]:
    """Activity pairs that would compete for the same audience's attention.

    Ports `analytics.js::detectCollisions` -- the studio's own collision
    view -- rather than inventing a new rule, because a naive port is worse
    than no tool at all here:

    * A pair collides only when it shares BOTH a `channel` member AND a
      `target_audience` member (`_shared_members`, case-insensitively).
      Either alone is not a collision -- that would flag most of the
      portfolio, since sharing a single channel or a single audience with
      SOMETHING is the common case, not the exceptional one. Each entry
      carries the intersections themselves as `shared_channels` /
      `shared_audiences`, so an agent can say WHY a pair collided rather than
      only that it did, without widening `SUMMARY_FIELDS` (shared by every
      other tool) to carry columns only this one needs.
    * `kind` is `"orchestration"`, not `"conflict"`, when both activities
      carry the same non-blank `tracking_pack_id` (the `CLUSTER-PACKNUM`
      prefix of `tracking_id`, from `ActivityRead`) -- two activities in one
      communication pack landing on the same audience is what a pack IS, not
      a problem. Severity is `"info"` for those pairs regardless of
      priority. For a genuine cross-pack collision, severity is the higher
      of the pair's two `priority_rank` values: `>= 4` critical, `>= 3`
      high, else medium.
    * Rows with no `start_date` cannot be paired and are dropped before
      sorting -- silently, like the studio does (`parseDate` returning
      `null` drops the row out of `sortedIdx`).

    Like the studio, this sorts the dated candidates by calendar day once and
    slides a window over them (bounded by `proximity_days`, default 0 -- same
    calendar day) rather than comparing every pair: O(n log n + n*k) instead
    of O(n^2), which matters once the portfolio runs into the thousands.
    `proximity_days` is clamped to `[0, MAX_PROXIMITY_DAYS]` -- an unbounded
    window means the inner loop's `break` never fires, and every pair in the
    filtered set gets compared and `_summarize`d before `_clamp_limit` ever
    runs, which is exactly the unbounded intermediate result this module's
    docstring promises never to build.

    `channel` and `target_audience` narrow membership-aware here, NOT via the
    exact-equality `text` filter every other tool uses (`_apply_filters`
    would drop a row storing `"Email, Intranet"` when asked for `"Email"`,
    then this function's own rule would have called it a match on the
    unfiltered set -- a silent, narrower-than-expected answer). Both keywords
    are pulled out of `filter_kwargs` before `_build_filters` sees them and
    applied afterwards with the same `_normalize_multi` membership test the
    pairing rule itself uses, so a filter and the rule it feeds never
    disagree. This is local to `detect_collisions`; `_apply_filters` and
    `_build_filters` stay exact-match for every other caller.

    `left`/`right` are chronological (`left` starts no later than `right`),
    not the studio's original-row-order convention -- an arbitrary choice
    either way, but the chronological one reads better standalone.

    Ordered worst first: severity descending (critical > high > medium >
    info), then `gap_days` ascending -- the closest, highest-severity
    collisions lead.

    The response has a count and a list that would otherwise collide on the
    same name (`collisions`): `total` is the true pair count across the
    WHOLE filtered set, `collisions` is the (possibly capped) list, and
    `returned` is that list's length -- the same shape `search_activities`
    uses for `total_matches` / `activities`.
    """
    capped = _clamp_limit(limit)
    proximity = max(0, min(int(proximity_days), MAX_PROXIMITY_DAYS))
    # Pulled out before `_build_filters` sees them: these two narrow by
    # membership below, not by the exact-equality `text` filter every other
    # keyword still goes through (see the docstring's filter/rule paragraph).
    channel_filter = filter_kwargs.pop("channel", None)
    audience_filter = filter_kwargs.pop("target_audience", None)
    filters = _build_filters(**filter_kwargs)
    candidates = _filtered_activities(session, filters)
    if channel_filter:
        wanted = channel_filter.strip().lower()
        candidates = [
            activity
            for activity in candidates
            if wanted in {member.lower() for member in _normalize_multi(activity.channel)}
        ]
    if audience_filter:
        wanted = audience_filter.strip().lower()
        candidates = [
            activity
            for activity in candidates
            if wanted in {member.lower() for member in _normalize_multi(activity.target_audience)}
        ]

    dated = sorted(
        (
            (
                activity,
                _epoch_day(activity.start_date),
                ActivityRead.model_validate(activity).tracking_pack_id,
            )
            for activity in candidates
            if activity.start_date is not None
        ),
        key=lambda entry: entry[1],
    )

    severity_order = {"critical": 4, "high": 3, "medium": 2, "info": 1}
    pairs: list[dict[str, Any]] = []
    for i in range(len(dated)):
        left, left_day, left_pack = dated[i]
        for j in range(i + 1, len(dated)):
            right, right_day, right_pack = dated[j]
            gap = right_day - left_day
            if gap > proximity:
                # `dated` is sorted by day, so every later `j` only widens the
                # gap further -- safe to stop scanning this window entirely.
                break
            shared_channels = _shared_members(left, right, "channel")
            if not shared_channels:
                continue
            shared_audiences = _shared_members(left, right, "target_audience")
            if not shared_audiences:
                continue
            same_pack = bool(left_pack) and left_pack == right_pack
            if same_pack:
                severity = "info"
            else:
                rank = max(priority_rank(left.priority), priority_rank(right.priority))
                severity = "critical" if rank >= 4 else "high" if rank >= 3 else "medium"
            pairs.append(
                {
                    "left": _summarize(left),
                    "right": _summarize(right),
                    "gap_days": gap,
                    "kind": "orchestration" if same_pack else "conflict",
                    "severity": severity,
                    "shared_channels": shared_channels,
                    "shared_audiences": shared_audiences,
                }
            )

    pairs.sort(key=lambda pair: (-severity_order[pair["severity"]], pair["gap_days"]))
    shown = pairs[:capped]
    return {
        "checked": len(candidates),
        "total": len(pairs),
        "returned": len(shown),
        "truncated": len(shown) < len(pairs),
        "note": _truncation_note(len(pairs), len(shown), capped, subject="collisions"),
        "collisions": shown,
    }


# The pack key chain, in preference order. Mirrors
# `analytics.js::campaignScorecards` exactly:
#
#   row.communication_pack_cpid || row.tracking_pack_id || row.communication_pack || row.campaign
#
# `test_pack_key_chain_matches_the_studio_implementation` parses that line out of
# the studio source and pins this order against it, so the two cannot drift.
#
# Order is the entire point of this tool. Measured on the same 400-row
# portfolio the studio's own comment cites: grouping by `tracking_pack_id`
# collapses everything into two buckets of 273 and 125 activities, while
# `communication_pack_cpid` resolves 32 real packs of 2-11. A bucket of 273 is
# the portfolio, not a planning unit -- every metric this tool reports (size,
# channel breadth, readiness) would describe the whole book of work instead of
# the thing a planner actually owns if this order were ever loosened.
_PACK_KEY_FIELDS: tuple[str, ...] = (
    "communication_pack_cpid",
    "tracking_pack_id",
    "communication_pack",
    "campaign",
)


def _pack_key(activity: Activity) -> tuple[str | None, str | None]:
    """The pack `activity` belongs to, and which chain link resolved it.

    `tracking_pack_id` is not a stored column -- it is `ActivityRead`'s own
    computed property (the first two `-`-separated segments of `tracking_id`;
    see `ActivityRead.tracking_pack_id`), so it is resolved through the read
    model exactly like `detect_collisions` already does, rather than
    reimplementing the split here.

    Every link is checked with `is_blank`, the same rule `missing_fields` and
    every SQL predicate in this module use, not raw Python/JS truthiness --
    so a synced 'None' sentinel in `communication_pack_cpid` falls through to
    the next link instead of becoming a pack named "None".

    Returns `(None, None)` when every link is blank: the caller must exclude
    the activity entirely, matching `campaignScorecards`' own
    `if (empty(key)) return;` -- a standalone activity is not a pack of one.
    """
    tracking_pack_id = ActivityRead.model_validate(activity).tracking_pack_id
    values = {
        "communication_pack_cpid": activity.communication_pack_cpid,
        "tracking_pack_id": tracking_pack_id,
        "communication_pack": activity.communication_pack,
        "campaign": activity.campaign,
    }
    for field in _PACK_KEY_FIELDS:
        value = values[field]
        if not is_blank(value):
            return value, field
    return None, None


def pack_overview(
    session: Session,
    *,
    limit: int | None = None,
    **filter_kwargs: Any,
) -> dict[str, Any]:
    """Per-communication-pack rollup: size, channel breadth, span, readiness.

    Closes "which packs are live, how large is each, over what period" --
    today answerable only as a raw `activity_counts(dimension=...)` grouped
    count, which cannot report channel/objective/audience breadth, the
    internal/external split, or per-pack readiness in one shot, and which an
    agent could just as easily point at the wrong key in the chain below.

    Grouped in Python, like every other multi-value or derived rollup here:
    `_pack_key` needs `ActivityRead.tracking_pack_id` (a computed property,
    not a column) and `channels`/`objectives`/`audiences` need every member
    of a multi-value column split before they can be counted, neither of
    which a portable SQL GROUP BY can express.

    Splitter choice, deliberately NOT `split_multi`: this tool ports
    `analytics.js::campaignScorecards`, which tallies channels, objectives and
    audiences with `normalizeMulti` -- splitting on `,` OR `;` unconditionally,
    including for `channel` and `target_audience`, which `split_multi` treats
    as scalar (see the comment on `MULTI_VALUE_SEPARATORS`). `_normalize_multi`
    (the same helper `detect_collisions` uses) is therefore the faithful
    choice for all three counts here -- an activity with
    `channel="Email, Intranet"` contributes 2 channels, matching the studio,
    not 1. Widening `MULTI_VALUE_SEPARATORS` instead would reshape
    `activity_counts`, `field_values`, the cross-tab and every filter that
    already treats `channel`/`target_audience` as scalar; Task 3's review
    already rejected that.

    `label` mirrors the studio's own `group.campaign = row.campaign ||
    row.communication_pack || key`: `campaign` if present, else
    `communication_pack`, else the resolved pack id itself (each check is
    `is_blank`, for the same sentinel-safety reason `_pack_key` uses it).
    `campaignScorecards` picks the ROW that supplies this from whichever
    happens to be first in its input array -- a rule this function does
    NOT inherit, deliberately: relying on `_filtered_activities`' incidental
    `(start_date, id)` return order would make the label silently follow
    that other function's ordering choice rather than a rule of this
    function's own. Instead, the source row is chosen explicitly by
    `(start_date is None, start_date, id)` ascending -- the earliest-starting
    activity in the pack wins regardless of scan order, undated activities
    lose to any dated one, and among an all-undated pack the lowest `id`
    wins. `test_pack_overview_label_picks_the_earliest_starting_row_when_campaigns_disagree`
    pins exactly this.

    `internal` / `external` come straight from `source_type`, which is a
    required, non-blank column (`Literal["internal", "external"]"` on
    `ActivityCreate`) -- every counted activity lands in exactly one of the
    two. `incomplete` reuses `missing_fields` unchanged, the same rule
    `planning_gaps` reports against, so the two figures cannot drift apart
    (`test_pack_overview_readiness_agrees_with_planning_gaps` pins that).

    Ordered by `activities` descending, then `pack_id` for a stable tie-break;
    capped like every other list-shaped answer here, with the TRUE pack count
    reported alongside the capped list so truncation is never silent.
    """
    capped = _clamp_limit(limit)
    filters = _build_filters(**filter_kwargs)
    candidates = _filtered_activities(session, filters)

    packs: dict[str, dict[str, Any]] = {}
    for activity in candidates:
        key, key_source = _pack_key(activity)
        if key is None:
            # Every link in the chain is blank -- excluded entirely, not
            # folded into a shared "Unassigned" pack: a standalone activity
            # is not a pack of one.
            continue
        pack = packs.get(key)
        if pack is None:
            pack = {
                "pack_id": key,
                "label": key,
                # The (start_date is None, start_date, id) of whichever
                # activity currently supplies `label` -- see the docstring
                # paragraph on `label` for why this is an explicit rule of
                # this function rather than inherited scan order. `None`
                # start_date sorts after any real one; `id` is the final,
                # always-available tie-break.
                "label_sort_key": None,
                "key_source": key_source,
                "activities": 0,
                "channels": {},  # insertion-ordered set: dict keys, values unused
                "objectives": set(),
                "audiences": set(),
                "dates": [],
                "internal": 0,
                "external": 0,
                "incomplete": 0,
            }
            packs[key] = pack
        label_sort_key = (activity.start_date is None, activity.start_date, activity.id)
        if pack["label_sort_key"] is None or label_sort_key < pack["label_sort_key"]:
            pack["label_sort_key"] = label_sort_key
            if not is_blank(activity.campaign):
                pack["label"] = activity.campaign
            elif not is_blank(activity.communication_pack):
                pack["label"] = activity.communication_pack
            else:
                pack["label"] = key
        pack["activities"] += 1
        for member in _normalize_multi(activity.channel):
            pack["channels"].setdefault(member, None)
        pack["objectives"].update(_normalize_multi(activity.strategic_objectives))
        pack["audiences"].update(_normalize_multi(activity.target_audience))
        if activity.start_date is not None:
            pack["dates"].append(as_utc(activity.start_date))
        if activity.source_type == "internal":
            pack["internal"] += 1
        elif activity.source_type == "external":
            pack["external"] += 1
        if missing_fields(activity):
            pack["incomplete"] += 1

    rows: list[dict[str, Any]] = []
    for pack in packs.values():
        dates = sorted(pack["dates"])
        first_date = dates[0] if dates else None
        last_date = dates[-1] if dates else None
        span_days = (
            _epoch_day(last_date) - _epoch_day(first_date)
            if first_date is not None and last_date is not None
            else None
        )
        rows.append(
            {
                "pack_id": pack["pack_id"],
                "label": pack["label"],
                "key_source": pack["key_source"],
                "activities": pack["activities"],
                "channels": len(pack["channels"]),
                "channel_names": list(pack["channels"]),
                "objectives": len(pack["objectives"]),
                "audiences": len(pack["audiences"]),
                "first_date": _iso(first_date),
                "last_date": _iso(last_date),
                "span_days": span_days,
                "internal": pack["internal"],
                "external": pack["external"],
                "incomplete": pack["incomplete"],
            }
        )

    rows.sort(key=lambda row: (-row["activities"], row["pack_id"]))
    total_packs = len(rows)
    shown = rows[:capped]
    return {
        "pack_count": total_packs,
        "returned": len(shown),
        "truncated": len(shown) < total_packs,
        "note": _truncation_note(total_packs, len(shown), capped, subject="packs"),
        "packs": shown,
    }


def _resolve_anchor(
    session: Session,
    explicit: str | date | datetime | None,
    candidates: list[Activity],
) -> tuple[datetime | None, str]:
    """The deterministic "now" for a time-relative question.

    Resolution order, each stage cheaper to trust than the next: the caller's
    own explicit argument; else the latest sync run (`SyncRun.ran_at`, newest
    first); else the latest `start_date` among the already-filtered
    `candidates`. Deliberately never `datetime.now()` -- a tool whose answer
    depends on the wall clock is not reproducible under test (this suite runs
    on two backends and in CI) and, worse, an agent cannot tell a user what
    "next month" meant without knowing what the database considers "now" to
    be. The caller gets the choice back as `anchor_source` for exactly that
    reason.

    Returns `(None, "none")` when none of the three stages produced anything
    -- no explicit argument, no `SyncRun` row, no dated candidate. There is
    deliberately no fourth, fabricated stage (a fixed epoch, say): that would
    hand back an `anchor_source` claiming a provenance ("latest_start_date")
    that does not exist, which is exactly the confidently-wrong-answer shape
    this whole module exists to avoid. Callers must check for `None` and
    report that they could not anchor rather than inventing a window.
    """
    parsed = _parse_boundary(explicit)
    if parsed is not None:
        return parsed, "argument"
    latest_sync = session.scalars(
        select(SyncRun.ran_at).order_by(SyncRun.ran_at.desc()).limit(1)
    ).first()
    if latest_sync is not None:
        return as_utc(latest_sync), "latest_sync"
    latest_start = max(
        (activity.start_date for activity in candidates if activity.start_date is not None),
        default=None,
    )
    if latest_start is not None:
        return as_utc(latest_start), "latest_start_date"
    return None, "none"


def calendar_load(
    session: Session,
    *,
    weeks: int = 8,
    start_date: str | date | datetime | None = None,
    **filter_kwargs: Any,
) -> dict[str, Any]:
    """Weekly activity volume, mirroring `analytics.js::weeklyCoverage`.

    `weeks` consecutive 7-day spans starting at the anchor date, each a
    half-open window `[from, to)` -- an activity landing exactly on a `to`
    boundary belongs to the NEXT week, matching the studio's
    `date >= from && date < to`. The anchor is truncated to midnight UTC,
    matching the studio's own `setHours(0, 0, 0, 0)`.

    `start_date` resolves via `_resolve_anchor` -- the explicit argument, else
    the latest sync run, else the latest `start_date` among the filtered
    activities -- and is echoed back as `anchor` / `anchor_source` so the
    agent can say what the window actually anchored on. When none of those
    three produce anything (`anchor_source == "none"`), there is nothing in
    the data to anchor a calendar on: the response reports `anchor: None`
    and empty `buckets` / `empty_weeks` rather than inventing a window.
    """
    span_weeks = max(1, min(int(weeks), 52))
    filters = _build_filters(**filter_kwargs)
    candidates = _filtered_activities(session, filters)
    anchor, anchor_source = _resolve_anchor(session, start_date, candidates)
    if anchor is None:
        return {
            "anchor": None,
            "anchor_source": anchor_source,
            "weeks": span_weeks,
            "buckets": [],
            "busiest": None,
            "quietest": None,
            "empty_weeks": [],
            "note": (
                "No sync run and no dated activity in this filtered set -- "
                "there is nothing to anchor a calendar window on."
            ),
        }
    anchor = _truncate_to_midnight(anchor)

    dated = [
        as_utc(activity.start_date) for activity in candidates if activity.start_date is not None
    ]
    buckets: list[dict[str, Any]] = []
    for index in range(span_weeks):
        week_from = anchor + timedelta(days=7 * index)
        week_to = week_from + timedelta(days=7)
        count = sum(1 for value in dated if week_from <= value < week_to)
        buckets.append({"from": _iso(week_from), "to": _iso(week_to), "count": count})

    busiest = max(buckets, key=lambda bucket: bucket["count"])
    quietest = min(buckets, key=lambda bucket: bucket["count"])
    empty_weeks = [bucket for bucket in buckets if bucket["count"] == 0]

    return {
        "anchor": _iso(anchor),
        "anchor_source": anchor_source,
        "weeks": span_weeks,
        "buckets": buckets,
        "busiest": busiest,
        "quietest": quietest,
        "empty_weeks": empty_weeks,
    }


def window_comparison(
    session: Session,
    *,
    days: int = 30,
    reference: str | date | datetime | None = None,
    **filter_kwargs: Any,
) -> dict[str, Any]:
    """Current vs. immediately-preceding window, mirroring
    `analytics.js::comparisonWindow`.

    The current window is the half-open span `[reference, reference + days)`;
    the previous window is the same-length span immediately before it,
    `[reference - days, reference)`. `reference` resolves exactly like
    `calendar_load`'s `start_date` (see `_resolve_anchor`) but is NOT
    truncated to midnight -- `comparisonWindow` uses the raw instant, unlike
    `weeklyCoverage`.

    `change_pct` is `None`, never `inf` and never `0`, when the previous
    window has no activity to compare against -- either of those numbers
    would read to an agent as a real answer about a comparison that cannot be
    made.

    `reference` resolves via the same `_resolve_anchor` as `calendar_load`.
    When it comes back `None` (`anchor_source == "none"`: no sync run, no
    dated activity in this filtered set), `current` and `previous` are also
    `None` rather than a fabricated pair of windows -- there is nothing to
    compare.
    """
    span_days = max(1, int(days))
    filters = _build_filters(**filter_kwargs)
    candidates = _filtered_activities(session, filters)
    anchor, anchor_source = _resolve_anchor(session, reference, candidates)
    if anchor is None:
        return {
            "anchor": None,
            "anchor_source": anchor_source,
            "days": span_days,
            "current": None,
            "previous": None,
            "change": None,
            "change_pct": None,
            "note": (
                "No sync run and no dated activity in this filtered set -- "
                "there is nothing to anchor a comparison window on."
            ),
        }

    dated = [
        as_utc(activity.start_date) for activity in candidates if activity.start_date is not None
    ]

    def _count_between(window_from: datetime, window_to: datetime) -> int:
        return sum(1 for value in dated if window_from <= value < window_to)

    current_from, current_to = anchor, anchor + timedelta(days=span_days)
    previous_from, previous_to = anchor - timedelta(days=span_days), anchor

    current_count = _count_between(current_from, current_to)
    previous_count = _count_between(previous_from, previous_to)
    change = current_count - previous_count
    change_pct = None if previous_count == 0 else round((change / previous_count) * 100, 1)

    return {
        "anchor": _iso(anchor),
        "anchor_source": anchor_source,
        "days": span_days,
        "current": {
            "from": _iso(current_from),
            "to": _iso(current_to),
            "count": current_count,
        },
        "previous": {
            "from": _iso(previous_from),
            "to": _iso(previous_to),
            "count": previous_count,
        },
        "change": change,
        "change_pct": change_pct,
    }


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
    tally: dict[str, int] = {}
    blank_count = 0
    if field in MULTI_VALUE_DIMENSIONS:
        # Split before tallying, or the buckets are combinations rather than values.
        for value in session.scalars(select(column)).all():
            members = split_multi(value, field)
            if not members:
                blank_count += 1
                continue
            for member in members:
                tally[member] = tally.get(member, 0) + 1
    else:
        # No SQL LIMIT here on purpose. Blanks have to be folded into
        # `blank_count` over the WHOLE grouped result -- a LIMIT would let blank
        # groups consume slots and would under-report blank_count (reporting 0
        # while blanks exist) -- and `distinct_values` has to be the true
        # cardinality so the answer can report its own truncation. GROUP BY is
        # bounded by the number of distinct values, far below what
        # `_filtered_activities` already materialises.
        for value, count in session.execute(select(column, func.count()).group_by(column)).all():
            if is_blank(value):
                blank_count += int(count)
            else:
                tally[value] = tally.get(value, 0) + int(count)
    ordered = sorted(
        ({"value": name, "count": count} for name, count in tally.items()),
        key=lambda entry: (-entry["count"], str(entry["value"])),
    )
    values = ordered[:capped]
    return {
        "field": field,
        "values": values,
        "returned": len(values),
        "distinct_values": len(ordered),
        "truncated": len(values) < len(ordered),
        "blank_count": blank_count,
        "note": _value_truncation_note(len(ordered), len(values), capped),
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
