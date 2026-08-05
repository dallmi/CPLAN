"""Calendar report: the planning year as a collapsible .xlsx.

Reads the activity CSV exports straight from the OneDrive sync folder -- no
database, no API process, no sync run has to be up first.

Usage:
    python pipeline/scripts/report_calendar.py
    python pipeline/scripts/report_calendar.py --year 2026
    python pipeline/scripts/report_calendar.py --from 2026-01-01 --to 2026-06-30
    python pipeline/scripts/report_calendar.py --out /path/to/report.xlsx

Without a period the report covers every dated activity. Edit CONFIG below to
change the rest of what it covers. The criteria are hard filters: a row that
fails any of them is absent from every sheet.
"""

import argparse
import sys
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path

from openpyxl import Workbook

SCRIPT_DIR = Path(__file__).resolve().parent
PIPELINE_DIR = SCRIPT_DIR.parent
REPO_DIR = PIPELINE_DIR.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from pipeline.report.calendar_sheet import build_calendar          # noqa: E402
from pipeline.report.config import EXECUTIVES_SPLIT, ReportConfig   # noqa: E402
from pipeline.report.data import build_scope                       # noqa: E402
from pipeline.report.table_sheets import (                         # noqa: E402
    build_activities,
    build_audience,
    build_data_quality,
    build_executive_summary,
    build_glossary,
    build_mix,
)
from pipeline.scripts.process_cplan import (                       # noqa: E402
    INPUT_FILES,
    find_input_dir,
    find_input_files,
    load_activities,
    log,
    print_banner,
)

# Reports get their own folder, and it holds nothing but .xlsx. The rest of
# pipeline/output is the pipeline's own working data -- parquet the API reads,
# meta.json the dashboard fetches -- and a delivered workbook sitting among
# them was easy to lose. Flat inside `reports/`, not bucketed by month: a run
# is identified by the period it covers, which the filename already carries,
# and two runs on one day can cover completely different periods.
OUTPUT_DIR = PIPELINE_DIR / "output"
REPORTS_DIR = OUTPUT_DIR / "reports"

# Beyond roughly five years the calendar stops being something a planner reads
# and starts being something Excel struggles to open. It is still built -- the
# data is the data -- but an unbounded run says so and names the rows at the
# edges, because the usual cause is one mistyped year, not five years of plans.
WIDE_GRID_WEEKS = 5 * 52


# ---------------------------------------------------------------------------
# CONFIGURATION -- this is the block to edit.
# ---------------------------------------------------------------------------
CONFIG = ReportConfig(
    # An activity is in scope if its run *overlaps* this window -- it may start
    # before it or end after it. --year/--from/--to override, --all clears.
    date_from=date(2026, 1, 1),
    date_to=date(2026, 12, 31),
    executives="any",                # "any" | "with" | "without"
    audience_bands=None,             # None = all bands; else e.g. ("50–100k", "> 100k")
    include_unknown_audience=True,   # applies only when audience_bands is set
    exclude_objectives=("2026: Other",),  # drop rows whose objectives are ONLY these
    exclude_priorities=(4,),         # leading number; word priorities are untouched
    include_archived=True,           # archiving is a view-size workaround, not a status
    detail_rows=True,                # activity rows under each dimension value
    breakdown_fields=("business_division", "region_group", "country",
                      "executives"),
)
# ---------------------------------------------------------------------------


# Build order is reading order. The calendar is second: the summary frames it.
SHEET_BUILDERS = (
    build_executive_summary,
    build_calendar,
    build_data_quality,
    build_audience,
    build_mix,
    build_activities,
    build_glossary,
)


def _edge_activities(frame, count=3):
    """The earliest and latest activities, which is where a typo shows up."""
    dated = frame[["start_day", "activity_name"]].dropna(subset=["start_day"])
    ordered = dated.sort_values("start_day")
    edges = list(ordered.head(count).itertuples(index=False))
    edges += [row for row in ordered.tail(count).itertuples(index=False)
              if row not in edges]
    return [(name or "Untitled", day.isoformat()) for day, name in edges]


def build_workbook(scope, config):
    wb = Workbook()
    wb.remove(wb.active)
    for builder in SHEET_BUILDERS:
        log(f"  {builder.__name__.replace('build_', '').replace('_', ' ').title()}")
        builder(wb, scope, config)
    return wb


def default_output_path(config):
    stamp = datetime.now().strftime("%Y_%m_%d")
    return REPORTS_DIR / f"CPLAN_calendar_{config.period_slug()}_{stamp}.xlsx"


def iso_date(text):
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a date as YYYY-MM-DD, got {text!r}")


def build_parser():
    parser = argparse.ArgumentParser(description="Generate the calendar .xlsx report")
    parser.add_argument("--year", type=int, default=None,
                        help="Cover one calendar year (shorthand for --from YYYY-01-01 --to YYYY-12-31)")
    parser.add_argument("--from", dest="date_from", type=iso_date, default=None,
                        help="Cover activities starting on or after this date (YYYY-MM-DD)")
    parser.add_argument("--to", dest="date_to", type=iso_date, default=None,
                        help="Cover activities starting on or before this date (YYYY-MM-DD)")
    parser.add_argument("--all", dest="all_dates", action="store_true",
                        help="Cover every dated activity, ignoring the period in CONFIG")
    parser.add_argument("--out", type=str, default=None,
                        help="Output path (default: pipeline/output/reports/CPLAN_calendar_<period>_<date>.xlsx)")
    parser.add_argument("--input-dir", type=str, default=None,
                        help="Read the CSV exports from here instead of discovering OneDrive")
    return parser


def resolve_config(config, args, parser):
    """Apply the command line's period to CONFIG.

    A period on the command line replaces the whole window rather than merging
    bound by bound, so `--from` alone means "from there on, no end" no matter
    what CONFIG says. Merging would let an edited CONFIG and a single flag
    combine into a window neither of them names.
    """
    if args.all_dates:
        if args.year is not None or args.date_from is not None or args.date_to is not None:
            parser.error("--all cannot be combined with --year or --from/--to")
        return replace(config, date_from=None, date_to=None)
    if args.year is not None:
        if args.date_from is not None or args.date_to is not None:
            parser.error("--year cannot be combined with --from/--to; use one or the other")
        return replace(config,
                       date_from=date(args.year, 1, 1),
                       date_to=date(args.year, 12, 31))
    if args.date_from is None and args.date_to is None:
        return config
    if (args.date_from is not None and args.date_to is not None
            and args.date_from > args.date_to):
        parser.error(f"--from ({args.date_from}) is after --to ({args.date_to})")
    return replace(config, date_from=args.date_from, date_to=args.date_to)


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    config = resolve_config(CONFIG, args, parser)

    print_banner("CPLAN Calendar Report")
    log(f"Period: {config.period_label()}")
    input_dir = Path(args.input_dir) if args.input_dir else find_input_dir()
    files = find_input_files(input_dir)
    if not files:
        log(f"ERROR: no input files found in {input_dir}")
        log(f"Expected one of: {', '.join(INPUT_FILES.values())}")
        return 1

    load = load_activities(files)
    if load.frame.empty:
        log("ERROR: the input files contain no activities")
        return 1

    members = None  # Task 7 deletes this line and loads the real list instead

    # The split columns replace the combined one, never join it: a GEB block
    # beside a GEB/GEB-1 block would print the same person with the same count
    # twice, and anyone adding the blocks would double-count the members.
    if members is not None:
        fields = []
        for field in config.breakdown_fields:
            if field == "executives":
                fields.extend(EXECUTIVES_SPLIT)
            else:
                fields.append(field)
        config = replace(config, breakdown_fields=tuple(fields))

    scope = build_scope(load, config, members)
    log(f"{len(scope.frame)} of {scope.rows_read} activities in scope")
    for reason, count in scope.excluded.items():
        if count:
            log(f"  excluded ({reason}): {count}")
    if scope.grid.weeks:
        first, last = scope.grid.weeks[0], scope.grid.weeks[-1]
        weeks = len(scope.grid.weeks)
        log(f"Calendar spans {weeks} weeks: "
            f"{first.monday.isoformat()} to {(last.monday + timedelta(days=6)).isoformat()}")
        if weeks > WIDE_GRID_WEEKS and config.date_from is None and config.date_to is None:
            log(f"WARNING: that is {weeks / 52:.0f} years wide. Without --year or")
            log("         --from/--to the calendar spans every dated activity, so a")
            log("         single mistyped date stretches the whole sheet. The dates")
            log("         at the edges are:")
            for label, day in _edge_activities(scope.frame):
                log(f"           {day}  {label}")

    log("Building sheets:")
    wb = build_workbook(scope, config)

    output_path = Path(args.out) if args.out else default_output_path(config)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    log(f"Done: {output_path} ({output_path.stat().st_size / 1024:.1f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
