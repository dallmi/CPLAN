"""From the loaded CSV dataset to the report's scope.

Filters are applied in a fixed order and each step's removals are counted, so
the Executive Summary can say why a row is not in the file. A row removed by an
earlier filter is not counted again by a later one -- the figures are a
partition of what was read, not overlapping tallies.
"""

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from pipeline.report import derive
from pipeline.report.config import BAND_UNKNOWN
from pipeline.report.grid import build_grid

# The fields the studio requires, from analytics.js. Any of them the export did
# not carry is dropped from the denominator and reported as skipped, so a row is
# never capped below 100% by a field nothing could have filled. `time_zone` was
# the standing example -- present in the source but unmapped, so every activity
# looked as if it were missing a time zone; it is mapped now, and this stays
# general rather than naming it, because the next gap will be a different field.
COMPLETENESS_FIELDS_COMMON = (
    "activity_name", "channel", "priority", "strategic_objectives",
    "activity_description", "region", "start_date", "end_date", "time_zone",
    "lead", "lead_team",
)
COMPLETENESS_FIELDS_INTERNAL = COMPLETENESS_FIELDS_COMMON + (
    "target_audience", "audience", "business_division",
)

EXCLUSION_ORDER = (
    "no start date", "date window", "archived", "GEB", "audience band",
    "objectives", "priority",
)


@dataclass
class Scope:
    frame: pd.DataFrame
    grid: object
    rows_read: int
    excluded: dict
    source_files: list = field(default_factory=list)
    completeness_fields: list = field(default_factory=list)
    skipped_completeness_fields: list = field(default_factory=list)
    duplicates_removed: int = 0


def _is_blank(series):
    return series.isna() | (series.astype(str).str.strip().isin(["", "nan", "NaT"]))


def _column(frame, name, default=""):
    """The named column, or a full-length column of `default` if it is absent.

    A source export missing a column is a real shape, not a hypothetical one:
    `transform()` narrows the frame to the columns the CSV actually carried, so
    anything optional here may simply not exist. `frame.get(name, "")` looks
    like it defaults but returns the bare scalar `""`, which then silently
    misbehaves downstream -- `zip("", series)` yields nothing and the
    assignment raises on the length mismatch, `"" == "internal"` is a plain
    bool with no `.any()`. Always hand the callers a Series of the right
    length instead.
    """
    column = frame.get(name)
    if column is None:
        return pd.Series([default] * len(frame), index=frame.index)
    return column


def _completeness(frame, fields):
    """Percentage of required fields that carry a value, per row."""
    if not fields:
        return pd.Series([100] * len(frame), index=frame.index)
    filled = pd.Series(0, index=frame.index)
    for name in fields:
        filled += (~_is_blank(frame[name])).astype(int)
    return (filled / len(fields) * 100).round().astype(int)


def _resolve_window(days, config):
    """The first and last day the time axis has to reach.

    A bound the run asked for is kept even when no activity reaches it: asking
    for 2026 means seeing all of 2026, empty weeks included. Only where the run
    named no bound does the axis take its edge from the data. With neither a
    bound nor a dated row there is nothing to span, so the axis falls back to
    the current week and the sheets come out empty rather than column-less.
    """
    first, last = config.date_from, config.date_to
    if days:
        # The lower edge widens to reach every surviving row. Under the period's
        # overlap rule an activity can start before the window and still be in
        # scope, and the calendar guarantees a column for every activity it
        # lists -- `build_calendar` asserts exactly that.
        first = min(days) if first is None else min(first, min(days))
        last = max(days) if last is None else max(last, max(days))
    if first is None and last is None:
        first = last = date.today()
    return first or last, last or first


def build_scope(load, config):
    frame = load.frame
    rows_read = len(frame)
    excluded = {key: 0 for key in EXCLUSION_ORDER}

    source_files = [
        (key, path.name) for key, path in sorted(load.files.items())
    ]

    if frame.empty:
        return Scope(frame=frame, grid=build_grid(*_resolve_window([], config)),
                     rows_read=0, excluded=excluded,
                     source_files=source_files,
                     duplicates_removed=load.duplicates_removed)

    frame = frame.copy()
    # pandas 3: `.dt.date` on a column that is entirely NaT returns dtype
    # datetime64[s] instead of the usual object dtype of date/NaT values (the
    # element-wise conversion is skipped when there is nothing to convert). If
    # a later filter then empties the frame while that dtype is still
    # datetime64, `.apply()` on the empty slice preserves it, and `.sum()` on
    # an empty DatetimeArray raises TypeError -- it does not support that
    # reduction. Casting to object here keeps the column's dtype stable
    # (and NaT-safe) regardless of how many rows are missing a start date.
    frame["start_day"] = pd.to_datetime(
        frame["start_date"], errors="coerce"
    ).dt.date.astype(object)

    def drop(mask, reason):
        nonlocal frame
        removed = int(mask.sum())
        if removed:
            excluded[reason] += removed
            frame = frame[~mask].copy()

    drop(frame["start_day"].isna(), "no start date")
    # The period is an overlap test, so it needs the end date too. An export
    # without one is a real shape; every row then reads as a point in time.
    frame["end_day"] = pd.to_datetime(
        _column(frame, "end_date", default=None), errors="coerce"
    ).dt.date.astype(object)
    # A plain loop over two columns, not `.apply(axis=1)`: that builds a Series
    # per row, and this runs once per activity on every run.
    covered = pd.Series(
        [config.covers(start, end if end == end else None)
         for start, end in zip(frame["start_day"], frame["end_day"])],
        index=frame.index)
    drop(~covered, "date window")

    # The axis is settled here, on the rows the period let through. The filters
    # below narrow *who* appears, not *when* the report is about; letting them
    # move the time axis would make it shift for surprising reasons.
    grid = build_grid(*_resolve_window(list(frame["start_day"]), config))

    if not config.include_archived and "is_archived" in frame.columns:
        drop(frame["is_archived"].fillna(False).astype(bool), "archived")

    # One derivation feeds both: the names shown on the sheets and the yes/no
    # the filters and shares count. Deriving the flag from the normalised list
    # rather than from the raw field means the two cannot disagree about a row.
    frame["executives"] = _column(frame, "bod_geb").apply(derive.executive_names)
    frame["has_executives"] = frame["executives"] != ""

    # The other half of the leadership pair: senior executives who are not on
    # the GEB. Same derivation, a different source field -- the two never mix,
    # and the `executives` filter above deliberately still means GEB only.
    frame["senior_executives"] = (
        _column(frame, "other_executives").apply(derive.executive_names))
    if config.executives == "with":
        drop(~frame["has_executives"], "GEB")
    elif config.executives == "without":
        drop(frame["has_executives"], "GEB")

    # `audience` now carries the source's "Estimated audience size", which is
    # what it was always meant to hold; the source's own "Audience" column is a
    # different field and lands in `audience_type` (see process_cplan's
    # COLUMN_MAP). The external export has no size column at all, so external
    # rows band as Unknown -- honestly, rather than by reading the wrong field.
    frame["audience_band"] = _column(frame, "audience").apply(derive.audience_band)
    if config.audience_bands is not None:
        allowed = set(config.audience_bands)
        if config.include_unknown_audience:
            allowed.add(BAND_UNKNOWN)
        drop(~frame["audience_band"].isin(allowed), "audience band")

    if config.exclude_objectives:
        drop(
            _column(frame, "strategic_objectives").apply(
                lambda value: derive.only_excluded_objectives(
                    value, config.exclude_objectives)),
            "objectives",
        )

    if config.exclude_priorities:
        excluded_priorities = set(config.exclude_priorities)
        drop(
            _column(frame, "priority").apply(
                lambda value: derive.priority_number(value) in excluded_priorities),
            "priority",
        )

    frame["week_index"] = frame["start_day"].apply(grid.week_index)
    frame["_quarter"] = [
        grid.quarter_of(grid.weeks[int(i)]) if i is not None and i == i else None
        for i in frame["week_index"]
    ]
    # No `priority_rank` column here: the one place the ranking is needed is the
    # Mix sheet's PRIORITY BY QUARTER block, which groups by the priority label
    # and so ranks the *label*, not the row (`table_sheets._priority_sort_key`).
    # A per-row column would be computed on every run and read by nothing.
    created = pd.to_datetime(_column(frame, "created", default=None), errors="coerce")
    start = pd.to_datetime(frame["start_date"], errors="coerce")
    frame["lead_time_days"] = (start - created).dt.days

    present = set(frame.columns)
    internal_fields = [f for f in COMPLETENESS_FIELDS_INTERNAL if f in present]
    external_fields = [f for f in COMPLETENESS_FIELDS_COMMON if f in present]
    skipped = sorted(set(COMPLETENESS_FIELDS_INTERNAL) - present)

    is_internal = _column(frame, "source_type") == "internal"
    completeness = pd.Series(0, index=frame.index, dtype=int)
    if is_internal.any():
        completeness[is_internal] = _completeness(frame[is_internal], internal_fields)
    if (~is_internal).any():
        completeness[~is_internal] = _completeness(frame[~is_internal], external_fields)
    frame["completeness"] = completeness

    frame = frame.reset_index(drop=True)
    return Scope(
        frame=frame, grid=grid, rows_read=rows_read, excluded=excluded,
        source_files=source_files,
        completeness_fields=sorted(set(internal_fields) | set(external_fields)),
        skipped_completeness_fields=skipped,
        duplicates_removed=load.duplicates_removed,
    )
