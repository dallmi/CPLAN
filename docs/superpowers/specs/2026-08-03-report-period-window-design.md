# Calendar report: an optional period, selectable per run

**Date:** 2026-08-03
**Status:** approved

## Problem

The calendar report hard-codes 2025 in the `CONFIG` block of
`pipeline/scripts/report_calendar.py`. Covering a different period means editing
the script, and covering *everything* is not expressible at all. The launcher
deliberately offers no switch, on the reasoning that a run should be
reproducible from the file alone.

That reasoning no longer holds: `ReportConfig.describe()` writes the applied
period into the Executive Summary, so the workbook documents its own scope
regardless of where the value came from.

## Decisions

**The window becomes optional, and each bound stands alone.** `date_from` and
`date_to` default to `None`, meaning "no bound on that side". `--from 2026-01-01`
without `--to` is a valid open-ended window.

**A configured bound wins; the data fills in the rest.** The calendar's time
axis needs a first and a last week. Where the run names a bound, that bound is
the axis edge even if no activity reaches it — asking for 2026 means seeing all
of 2026, empty weeks included. Where the run names no bound, the axis takes the
earliest or latest start date among the rows that survived the date filter.

| Run | Axis spans |
|---|---|
| no flags | earliest to latest activity |
| `--year 2026` | 2026-01-01 to 2026-12-31 (unchanged from today) |
| `--from 2026-01-01` | 2026-01-01 to latest activity |

**The axis is a date question.** The grid is resolved directly after the date
filter, before the archived / executives / audience filters. Those narrow *who*
appears, not *when* the report is about; letting them shrink the time axis would
make it move for surprising reasons. Every surviving activity still has a
column, which is what `grid.py` guarantees.

**The window is contiguous.** 2025 and 2027 without 2026 in one workbook is out
of scope — that is inherent to a from/to window, and two runs cover it.

## Interface

```
--year 2026                        # shorthand for --from 2026-01-01 --to 2026-12-31
--from 2026-01-01 --to 2026-06-30  # free
```

`--year` together with `--from`/`--to` is an error, not a silent winner. Dates
that are not `YYYY-MM-DD` fail at parse time with a message naming the format.
`report.ps1` gains `-Year`, `-From`, `-To` and passes them through; its header
comment, which currently argues that the criteria deliberately have no switches,
is rewritten to match.

## Output filename

`default_output_path` reads `config.date_from.year` today and would raise on an
unbounded run. The window gets a `period_slug()`, so the name says what is
inside without opening the file:

| Window | Slug | Filename |
|---|---|---|
| one full calendar year | `2026` | `CPLAN_calendar_2026_2026_08_03.xlsx` |
| several full calendar years | `2025-2026` | `CPLAN_calendar_2025-2026_2026_08_03.xlsx` |
| partial year | `2026-04-01-2026-09-30` | `CPLAN_calendar_2026-04-01-2026-09-30_2026_08_03.xlsx` |
| one-sided | `from-2026-04-01` / `until-2026-09-30` | `CPLAN_calendar_from-2026-04-01_2026_08_03.xlsx` |
| unbounded | `all` | `CPLAN_calendar_all_2026_08_03.xlsx` |

The slug never contains an underscore. The filename joins name, slug and a
`%Y_%m_%d` stamp with underscores, so an underscore inside the slug would blur
the boundary: `CPLAN_calendar_2025_2026_08_03.xlsx` could be a 2025 run stamped
2026-08-03 or a 2025–2026 run stamped 08-03. The stamp format is an established
convention and stays; the slug uses hyphens instead.

## Deliberately unchanged

- `excluded["date window"]` stays as a counter; an unbounded run reports 0.
- Rows without a start date are still dropped under their own reason.
- The Mix sheet's Δ column still compares the first against the last full
  quarter. Over many years that comparison is thin, but it is not broken, and
  changing it is a separate decision.

## Verification

The existing report tests pass their window explicitly and must stay green
unchanged — that is the regression guard. New coverage: an unbounded run keeps
every dated row and spans the data; `--year` still spans the full year when the
data is narrower; one-sided windows; the `--year`/`--from` conflict; invalid
date strings; the slug table above; an empty result set still producing a
workbook.
