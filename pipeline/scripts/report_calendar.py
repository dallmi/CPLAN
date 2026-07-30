"""Calendar report: the planning year as a collapsible .xlsx.

Reads the activity CSV exports straight from the OneDrive sync folder -- no
database, no API process, no sync run has to be up first.

Usage:
    python pipeline/scripts/report_calendar.py
    python pipeline/scripts/report_calendar.py --out /path/to/report.xlsx

Edit CONFIG below to change what the report covers. The three criteria are hard
filters: a row that fails any of them is absent from every sheet.
"""

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

from openpyxl import Workbook

SCRIPT_DIR = Path(__file__).resolve().parent
PIPELINE_DIR = SCRIPT_DIR.parent
REPO_DIR = PIPELINE_DIR.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from pipeline.report.calendar_sheet import build_calendar          # noqa: E402
from pipeline.report.config import ReportConfig                    # noqa: E402
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

OUTPUT_DIR = PIPELINE_DIR / "output"


# ---------------------------------------------------------------------------
# CONFIGURATION -- this is the block to edit.
# ---------------------------------------------------------------------------
CONFIG = ReportConfig(
    date_from=date(2025, 1, 1),      # filters on start_date, inclusive
    date_to=date(2025, 12, 31),      # inclusive
    executives="any",                # "any" | "with" | "without"
    audience_bands=None,             # None = all bands; else e.g. ("50–100k", "> 100k")
    include_unknown_audience=True,   # applies only when audience_bands is set
    include_archived=True,           # archiving is a view-size workaround, not a status
    detail_rows=True,                # activity rows under each dimension value
    breakdown_fields=("business_division", "region"),
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


def build_workbook(scope, config):
    wb = Workbook()
    wb.remove(wb.active)
    for builder in SHEET_BUILDERS:
        log(f"  {builder.__name__.replace('build_', '').replace('_', ' ').title()}")
        builder(wb, scope, config)
    return wb


def default_output_path(config):
    stamp = datetime.now().strftime("%Y_%m_%d")
    return OUTPUT_DIR / f"CPLAN_calendar_{config.date_from.year}_{stamp}.xlsx"


def build_parser():
    parser = argparse.ArgumentParser(description="Generate the calendar .xlsx report")
    parser.add_argument("--out", type=str, default=None,
                        help="Output path (default: pipeline/output/CPLAN_calendar_<year>_<date>.xlsx)")
    parser.add_argument("--input-dir", type=str, default=None,
                        help="Read the CSV exports from here instead of discovering OneDrive")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    config = CONFIG

    print_banner("CPLAN Calendar Report")
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

    scope = build_scope(load, config)
    log(f"{len(scope.frame)} of {scope.rows_read} activities in scope")
    for reason, count in scope.excluded.items():
        if count:
            log(f"  excluded ({reason}): {count}")

    log("Building sheets:")
    wb = build_workbook(scope, config)

    output_path = Path(args.out) if args.out else default_output_path(config)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    log(f"Done: {output_path} ({output_path.stat().st_size / 1024:.1f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
