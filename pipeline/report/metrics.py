"""Figures for the flat sheets, computed apart from how they are presented.

Order statistics (median, min, max, longest run) are literals in the workbook:
an Excel formula for them would need the underlying series on the sheet, which
these sheets do not carry. Everything derived from two figures already on the
sheet stays a formula, written by the sheet builder.
"""

import statistics

from pipeline.report.config import SHORT_NOTICE_DAYS
from pipeline.report.data import _is_blank


def _week_counts(scope):
    counts = [0] * len(scope.grid.weeks)
    # An empty scope (nothing survived the filters, or nothing was read at
    # all) never gets the derived columns attached -- `data.py`'s early
    # return skips them entirely, so "week_index" may not exist. The
    # zero-filled counts are the correct answer for that shape: no activity
    # index below.
    if scope.frame.empty or "week_index" not in scope.frame.columns:
        return counts
    for index in scope.frame["week_index"]:
        if index is None or (isinstance(index, float) and index != index):
            continue
        counts[int(index)] += 1
    return counts


def load_stats(scope):
    counts = _week_counts(scope)
    total = sum(counts)
    if not counts or total == 0:
        return {"median_per_week": 0, "peak_week_label": "—", "peak_week_count": 0,
                "zero_weeks": len(counts), "longest_zero_run": len(counts),
                "top5_share": 0}

    peak_index = max(range(len(counts)), key=lambda i: counts[i])
    peak_week = scope.grid.weeks[peak_index]

    longest = current = 0
    for count in counts:
        current = current + 1 if count == 0 else 0
        longest = max(longest, current)

    top5 = sum(sorted(counts, reverse=True)[:5])
    return {
        "median_per_week": statistics.median(counts),
        "peak_week_label": f"{peak_week.label} ({peak_week.sublabel})",
        "peak_week_count": counts[peak_index],
        "zero_weeks": sum(1 for c in counts if c == 0),
        "longest_zero_run": longest,
        "top5_share": top5 / total,
    }


def lead_time_stats(frame):
    days = [int(d) for d in frame["lead_time_days"].dropna()]
    if not days:
        return {"counted": 0, "median_days": None, "short_notice": 0,
                "min_days": None, "max_days": None}
    return {
        "counted": len(days),
        # Whole days: round to the nearest day rather than truncate, so a
        # median of 157.5 reads as 158, not a systematically low 157.
        "median_days": round(statistics.median(days)),
        "short_notice": sum(1 for d in days if d < SHORT_NOTICE_DAYS),
        "min_days": min(days),
        "max_days": max(days),
    }


def pack_stats(frame):
    """Size the pack buckets. An oversized pack is the data problem, quantified."""
    ids = frame.get("communication_pack_cpid")
    if ids is None:
        return {"with_pack": 0, "without_pack": len(frame), "packs": 0,
                "singleton_packs": 0, "small_packs": 0, "medium_packs": 0,
                "oversized_packs": 0, "largest_pack": 0}

    blank = _is_blank(ids)
    sizes = {}
    for value in ids[~blank]:
        key = str(value).strip()
        sizes[key] = sizes.get(key, 0) + 1

    counts = list(sizes.values())
    return {
        "with_pack": int((~blank).sum()),
        "without_pack": int(blank.sum()),
        "packs": len(sizes),
        "singleton_packs": sum(1 for c in counts if c == 1),
        "small_packs": sum(1 for c in counts if 2 <= c <= 10),
        "medium_packs": sum(1 for c in counts if 11 <= c <= 50),
        "oversized_packs": sum(1 for c in counts if c > 50),
        "largest_pack": max(counts, default=0),
    }


REPORTED_FIELDS = (
    "activity_name", "start_date", "end_date", "channel", "priority", "lead",
    "lead_team", "target_audience", "strategic_objectives", "activity_description",
    "business_division", "region", "audience", "bod_geb", "other_executives",
    "communication_pack_cpid",
)


def field_completeness(scope):
    rows = []
    for name in REPORTED_FIELDS:
        if name not in scope.frame.columns:
            continue
        blank = _is_blank(scope.frame[name])
        rows.append((name, int((~blank).sum()), int(blank.sum())))
    return rows


def anomalies(frame, duplicates_removed=0):
    """Data-quality counts for the frame as it stands after `load_activities`.

    `load_activities` already de-duplicates by `tracking_id` (keeping the most
    recently modified row) before this frame exists, so counting duplicates
    against `frame` itself is a tautological zero, not a measurement. The real
    count is computed there and passed in here instead. For the same reason
    the blank-tracking-ID count below is only ever a post-de-duplication
    figure -- its label says so, so a reader does not mistake it for a
    source-data count.
    """
    import pandas as pd

    def _dates(name):
        """Parsed dates for `name`, or an all-NaT column if the export lacks it.

        `pd.to_datetime(frame.get(name))` on an absent column parses `None` and
        returns the *scalar* `pd.NaT`, not a Series -- `end.isna()` on that
        raises AttributeError and takes the whole workbook build down, not just
        this block. A source export missing a column has to produce one honest
        gap instead.
        """
        column = frame.get(name)
        if column is None:
            return pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns]")
        return pd.to_datetime(column, errors="coerce")

    start = _dates("start_date")
    end = _dates("end_date")
    tracking = frame.get("tracking_id")
    archived = frame.get("is_archived")
    return [
        ("End date before start date", int((end < start).sum())),
        ("Missing end date", int(end.isna().sum())),
        ("Blank tracking ID (after de-duplication)",
         int(_is_blank(tracking).sum()) if tracking is not None else 0),
        ("Duplicate tracking IDs removed on load", int(duplicates_removed)),
        ("Archived", int(archived.fillna(False).astype(bool).sum()) if archived is not None else 0),
    ]
