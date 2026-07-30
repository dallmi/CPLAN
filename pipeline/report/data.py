"""From the loaded CSV dataset to the report's scope.

Filters are applied in a fixed order and each step's removals are counted, so
the Executive Summary can say why a row is not in the file. A row removed by an
earlier filter is not counted again by a later one -- the figures are a
partition of what was read, not overlapping tallies.
"""

from dataclasses import dataclass, field

import pandas as pd

from pipeline.report import derive
from pipeline.report.config import BAND_UNKNOWN
from pipeline.report.grid import build_grid

# The fields the studio requires, from analytics.js. `time_zone` is on that list
# but is not mapped by the ETL, so it is dropped from the denominator here and
# reported as skipped -- otherwise every row from a CSV export would be capped
# below 100% by a field the export cannot carry.
COMPLETENESS_FIELDS_COMMON = (
    "activity_name", "channel", "priority", "strategic_objectives",
    "activity_description", "region", "start_date", "end_date", "time_zone",
    "lead", "lead_team",
)
COMPLETENESS_FIELDS_INTERNAL = COMPLETENESS_FIELDS_COMMON + (
    "target_audience", "audience", "business_division",
)

EXCLUSION_ORDER = (
    "no start date", "date window", "archived", "senior executives", "audience band",
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


def build_scope(load, config):
    frame = load.frame
    rows_read = len(frame)
    grid = build_grid(config.date_from, config.date_to)
    excluded = {key: 0 for key in EXCLUSION_ORDER}

    source_files = [
        (key, path.name) for key, path in sorted(load.files.items())
    ]

    if frame.empty:
        return Scope(frame=frame, grid=grid, rows_read=0, excluded=excluded,
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
    drop(
        frame["start_day"].apply(lambda d: d < config.date_from or d > config.date_to),
        "date window",
    )

    if not config.include_archived and "is_archived" in frame.columns:
        drop(frame["is_archived"].fillna(False).astype(bool), "archived")

    frame["has_executives"] = _column(frame, "bod_geb").apply(derive.has_executives)
    if config.executives == "with":
        drop(~frame["has_executives"], "senior executives")
    elif config.executives == "without":
        drop(frame["has_executives"], "senior executives")

    frame["audience_band"] = _column(frame, "audience").apply(derive.audience_band)
    if config.audience_bands is not None:
        allowed = set(config.audience_bands)
        if config.include_unknown_audience:
            allowed.add(BAND_UNKNOWN)
        drop(~frame["audience_band"].isin(allowed), "audience band")

    frame["reach"] = [
        derive.classify_reach(division, region)
        for division, region in zip(_column(frame, "business_division"),
                                    _column(frame, "region"))
    ]
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
