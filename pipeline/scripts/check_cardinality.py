#!/usr/bin/env python3
"""Say what each breakdown dimension would cost, and what it is worth.

The pack's files are sized by their blocks: a dimension's distinct values,
multiplied by every week in `04-calendar.csv`, by every measure in
`06-breakdowns.csv`, and by every year and quarter in `08-periods.csv`. A
field with forty values is a different proposition from one with four, and
until now that was settled by estimating -- twice in this project an estimate
about these exports turned out to be wrong.

So it is measured. This reads the same exports a refresh reads, through the
same transform and the same value splitting the report itself uses, and
reports for every candidate dimension:

    values      distinct values, after splitting multi-value fields
    coverage    share of in-scope activities that name the field at all
    top share   share of those held by the single largest value
    calendar    rows this block would add to 04-calendar.csv
    breakdowns  rows it would add to 06-breakdowns.csv
    periods     rows it would add to 08-periods.csv

The row counts are counted, not projected: each block is actually built and
its rows tallied, so the empty week/value pairs the calendar leaves out are
left out here too.

Coverage and top share are the other half of the question. A dimension that
90% of activities leave blank is a weak axis whatever it costs, and one where
a single value holds nine rows in ten has little left to compare.

Usage (from the repo root, or just double-click cardinality.cmd):
    python -m pipeline.scripts.check_cardinality
    python -m pipeline.scripts.check_cardinality --input <folder>
    python -m pipeline.scripts.check_cardinality --csv cardinality.csv

Always exits 0: there is no pass or fail here, only figures for a decision.
"""

from __future__ import annotations

import argparse
import csv as csv_module
import sys
from dataclasses import replace
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from pipeline.report import agent_pack, membership  # noqa: E402
from pipeline.report.config import EXECUTIVES_SPLIT  # noqa: E402
from pipeline.report.calendar_sheet import _split_for  # noqa: E402
from pipeline.report.data import build_scope  # noqa: E402
from pipeline.scripts.process_cplan import (  # noqa: E402
    find_input_dir,
    find_input_files,
    load_activities,
    load_packs,
    log,
    print_banner,
    print_kv,
    print_table,
)

# Every field that could plausibly be a breakdown axis, whether or not it is
# one today. The point of this tool is to weigh candidates, so a field is
# listed because someone might ask for it -- not because the pack already
# carries it.
CANDIDATES = (
    "business_division", "business_area", "region_group", "country",
    "channel", "priority", "lead_team", "partner_team", "lead",
    "target_audience", "audience_band", "campaign", "source_type",
    "executives", "executives_geb", "executives_geb1",
)


def _values(frame, field):
    """Every value of `field`, split exactly as the report splits it.

    Through `_split_for` rather than a plain unique(): `channel` carries
    several values in one string, and counting "Email, Intranet" as one
    distinct value would understate the block by however many combinations
    the data happens to contain.
    """
    counts: dict[str, int] = {}
    named = 0
    for raw in frame.get(field, []):
        if raw is None or raw != raw or not str(raw).strip():
            continue
        parts = [p for p in _split_for(field, raw) if p]
        if not parts:
            continue
        named += 1
        for part in parts:
            counts[part] = counts.get(part, 0) + 1
    return counts, named


def measure(scope, config, field, generated):
    """What one field costs in each file, by building its blocks and counting."""
    counts, named = _values(scope.frame, field)
    if not counts:
        return None

    one = replace(config, breakdown_fields=(field,))

    def rows_for(builder, **kwargs):
        # Counted by block name rather than by subtracting a TOTAL-only run:
        # `ReportConfig` refuses an empty field list, and every row of every
        # builder carries its block first, so this is both simpler and exact.
        return sum(1 for row in builder(scope, one, **kwargs)
                   if row[0] == field)

    rows = len(scope.frame)
    top = max(counts.values())
    return {
        "field": field,
        "values": len(counts),
        "coverage": named / rows if rows else 0.0,
        "top_share": top / named if named else 0.0,
        "calendar": rows_for(agent_pack.calendar_rows),
        "breakdowns": rows_for(agent_pack.breakdown_rows),
        "periods": rows_for(agent_pack.period_rows, generated=generated,
                            blocks=(agent_pack.TOTAL_BLOCK, field)),
    }


CSV_COLUMNS = ("field", "values", "coverage", "top_share", "calendar",
               "breakdowns", "periods", "carried")


def write_csv(path: Path, measured: list[dict]) -> None:
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv_module.writer(handle)
        writer.writerow(CSV_COLUMNS)
        for row in measured:
            writer.writerow([
                row["field"], row["values"], f"{row['coverage']:.4f}",
                f"{row['top_share']:.4f}", row["calendar"], row["breakdowns"],
                row["periods"], "yes" if row["carried"] else "no",
            ])
    log(f"Written to {path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", type=Path, default=None,
                        help="read the CSVs from this folder instead of the "
                             "usual OneDrive/local discovery")
    parser.add_argument("--csv", type=Path, default=None,
                        help="also write the table to this CSV")
    args = parser.parse_args(argv)

    print_banner("CPLAN dimension cardinality")

    if args.input is not None:
        if not args.input.is_dir():
            log(f"ERROR: not a folder: {args.input}")
            print()
            return 1
        input_dir = args.input
        log(f"Using input: {input_dir}")
    else:
        input_dir = find_input_dir()

    files = find_input_files(input_dir)
    load = load_activities(files)
    if load.frame.empty:
        log("ERROR: the activity exports contain no activities.")
        print()
        return 1

    # The agent's own scope, not the workbook's: every filter the pack drops
    # is dropped here too, so the figures describe the files it actually
    # ships rather than a narrower report nobody uploads.
    from pipeline.scripts.report_calendar import CONFIG

    config = agent_pack.pack_config(CONFIG)

    # The member list, loaded exactly as `resolve_scope` loads it. Passing
    # None here was a real defect: without the list the leadership field never
    # splits, so `executives_geb` is absent from the table and the run reads
    # as though the machine had no list at all -- which is what it reported,
    # on a machine that had one.
    try:
        members_path = membership.default_path(_REPO_ROOT)
        members = membership.load_membership(members_path) if members_path else None
    except membership.MembershipError as error:
        log(f"ERROR: {error}")
        print()
        return 1
    if members is not None:
        log(f"GEB list: {len(members)} members from {members_path.name}")
        config = replace(config, breakdown_fields=tuple(
            field for name in config.breakdown_fields
            for field in (EXECUTIVES_SPLIT if name == "executives" else (name,))))
    else:
        log("No GEB member list found, so the leadership field is not split")

    scope = build_scope(load, config, members, load_packs(files))
    generated = agent_pack.date.today()

    log(f"Activities in scope: {len(scope.frame)}")
    weeks = len(scope.grid.weeks) if scope.grid.weeks else 0
    print_kv([("Weeks spanned", weeks),
              ("Period", config.period_label())])
    print()

    measured = []
    for field in CANDIDATES:
        row = measure(scope, config, field, generated)
        if row is None:
            continue
        row["carried"] = field in agent_pack.PERIOD_BLOCKS
        measured.append(row)

    # Most expensive first: the decision this table exists for is what to
    # leave out, and the candidates for that are at the top.
    measured.sort(key=lambda r: r["periods"], reverse=True)

    print_table(
        "What each dimension costs, and what it is worth",
        ["Dimension", "Values", "Coverage", "Top share", "Calendar",
         "Breakdowns", "Periods", "In periods"],
        [(r["field"], r["values"], f"{r['coverage']:.0%}",
          f"{r['top_share']:.0%}", r["calendar"], r["breakdowns"],
          r["periods"], "yes" if r["carried"] else "-") for r in measured],
        col_widths=[22, 8, 10, 11, 10, 12, 9, 11])
    print()

    carried = sum(r["periods"] for r in measured if r["carried"])
    everything = sum(r["periods"] for r in measured)
    log(f"08-periods.csv carries {carried} of the {everything} rows every "
        f"candidate would produce")
    print()

    if args.csv is not None:
        write_csv(args.csv, measured)
    return 0


if __name__ == "__main__":
    sys.exit(main())
