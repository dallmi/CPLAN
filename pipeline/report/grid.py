"""The report's time axis: ISO weeks nested under months under quarters.

The grid is derived from a span of days rather than from a calendar year, so
every activity that survives the period filter is guaranteed a column. That span
is the report's period where one was asked for, and the extent of the data
otherwise (`data._resolve_window`).

For a full year the span means the first ISO week of the year through the first
ISO week of the next -- 53 columns for 2025 -- and a thirteenth month column.
That is correct, not an off-by-one: the last days of December belong to the next
year's week 1.
"""

from dataclasses import dataclass
from datetime import date, timedelta

MONTH_NAMES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


@dataclass(frozen=True)
class Week:
    iso_year: int
    iso_week: int
    monday: date

    @property
    def thursday(self):
        return self.monday + timedelta(days=3)

    @property
    def label(self):
        return f"W{self.iso_week:02d}"

    @property
    def sublabel(self):
        return f"{self.monday.day:02d} {MONTH_NAMES[self.monday.month - 1]}"

    @property
    def key(self):
        return (self.iso_year, self.iso_week)


@dataclass(frozen=True)
class GridColumn:
    kind: str      # "quarter" | "month" | "week"
    level: int     # outline level: quarter 0, month 1, week 2
    label: str
    sublabel: str
    key: tuple


@dataclass(frozen=True)
class Grid:
    weeks: tuple

    def month_of(self, week):
        """ISO 8601: a week belongs to the month containing its Thursday."""
        thursday = week.thursday
        return (thursday.year, thursday.month)

    def quarter_of(self, week):
        year, month = self.month_of(week)
        return (year, (month - 1) // 3 + 1)

    def week_index(self, day):
        """Position of `day`'s week in the grid, or None if outside it.

        Looked up, not scanned. This is called once per activity, and the scan
        it replaces was linear in the number of weeks -- fine for one year,
        thousands of times slower on a grid that spans a decade. The map is
        built on first use and cached on the (frozen) instance.
        """
        if day is None:
            return None
        lookup = self.__dict__.get("_by_monday")
        if lookup is None:
            lookup = {week.monday: index for index, week in enumerate(self.weeks)}
            object.__setattr__(self, "_by_monday", lookup)
        return lookup.get(day - timedelta(days=day.weekday()))

    def active_week_indices(self, start, end=None):
        """Every grid position the run `start`..`end` touches, clamped to the grid.

        `week_index` answers where an activity STARTS; this answers where it is
        RUNNING. The two differ for every activity that outlives its own start
        week, and the difference is the whole of "what is on this week" -- a
        question the pack could not express while a single start week was the
        only week an activity carried.

        Mirrors `ReportConfig.covers` on both edge cases: no end date reads as a
        point in time, and an end before its start uses the later of the two
        rather than dropping the row, so a typo cannot silently empty a week.

        Clamped to the grid rather than reaching past it. A week the grid does
        not carry is a calendar column that does not exist, and a row placed in
        one would be read as a week of the report that nobody can look up. The
        arithmetic is positional rather than a scan because `build_grid` steps
        exactly seven days at a time, so the weeks are contiguous by
        construction.
        """
        if start is None or not self.weeks:
            return ()
        last = start if end is None else max(start, end)
        grid_first = self.weeks[0].monday
        grid_last = self.weeks[-1].monday
        first_monday = max(start - timedelta(days=start.weekday()), grid_first)
        last_monday = min(last - timedelta(days=last.weekday()), grid_last)
        if first_monday > last_monday:
            return ()
        return tuple(range((first_monday - grid_first).days // 7,
                           (last_monday - grid_first).days // 7 + 1))

    def columns(self):
        """Ordered columns: each quarter, then its months, each with its weeks.

        Summary columns sit to the LEFT of what they summarise, which is what
        `summaryRight = False` on the sheet expects.
        """
        columns = []
        seen_quarters = []
        by_quarter = {}
        for week in self.weeks:
            quarter = self.quarter_of(week)
            month = self.month_of(week)
            if quarter not in by_quarter:
                by_quarter[quarter] = {}
                seen_quarters.append(quarter)
            by_quarter[quarter].setdefault(month, []).append(week)

        for quarter in seen_quarters:
            columns.append(GridColumn(
                kind="quarter", level=0,
                label=f"Q{quarter[1]} {quarter[0]}", sublabel="Total", key=quarter,
            ))
            for month, weeks in by_quarter[quarter].items():
                columns.append(GridColumn(
                    kind="month", level=1,
                    label=f"{MONTH_NAMES[month[1] - 1]} {month[0]}", sublabel="Total", key=month,
                ))
                for week in weeks:
                    columns.append(GridColumn(
                        kind="week", level=2,
                        label=week.label, sublabel=week.sublabel, key=week.key,
                    ))
        return columns


def build_grid(date_from, date_to):
    first_monday = date_from - timedelta(days=date_from.weekday())
    weeks = []
    cursor = first_monday
    while cursor <= date_to:
        iso = cursor.isocalendar()
        weeks.append(Week(iso_year=iso[0], iso_week=iso[1], monday=cursor))
        cursor += timedelta(days=7)
    return Grid(weeks=tuple(weeks))
