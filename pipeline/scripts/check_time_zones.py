#!/usr/bin/env python3
"""List the time zones the export carries, and name any the database cannot hold.

The source column is a lookup into a list the organisation maintains, so its
values are display names -- "Hong Kong, China, Taiwan Time - GMT+8:00" -- and
not IANA zones. `activities.time_zone` is a fixed-width column, and a single
value longer than it ends the daily refresh on the INSERT with
StringDataRightTruncation, before one row is written. Every activity then still
reads as missing a time zone, which looks like a mapping bug and is not one --
that is the failure this script exists to find in five seconds instead of in
the middle of a refresh.

It prints the list itself as well, which is what a display-name-to-IANA mapping
would have to be built from.

Usage (from the repo root, or just double-click timezones.cmd):
    python -m pipeline.scripts.check_time_zones
    python -m pipeline.scripts.check_time_zones --input "C:\\path\\to\\Input"

Exit code 0 only when the refresh cannot die on this field: values were found,
and every one of them fits.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from pipeline.scripts.process_cplan import (  # noqa: E402
    find_input_dir,
    find_input_files,
    log,
    print_banner,
    print_kv,
    print_table,
    read_csv_auto,
    transform,
)

# The width to assume when the model cannot be imported -- the API's own
# packages are not installed in every environment that can run the ETL. Kept as
# a floor, not as the answer: `column_limit()` prefers the model.
FALLBACK_LIMIT = 64

# Every export the sync feeds from, and the source type each is read as. Archive
# rows are imported like any other, so an over-long value there stops the same
# refresh.
SOURCE_TYPES = {
    "internal": "internal",
    "internal_archive": "internal",
    "external": "external",
    "external_archive": "external",
}
ACTIVITY_FILES = tuple(SOURCE_TYPES)

# What --context reports each zone's activities by. Both are filled in beside
# the time zone by the same person: a bucket whose rows all sit in one region
# says which place the label means, and a bucket that disagrees with its own
# rows is a mis-pick rather than a place.
CONTEXT_FIELDS = (("region", "Region"), ("lead_team", "Lead team"))
BLANK = "(blank)"


@dataclass
class Usage:
    """Every time-zone value the export carries, with its row count and who carries it."""

    values: Counter = field(default_factory=Counter)
    context: dict = field(default_factory=dict)  # value -> field name -> Counter


def _text(value) -> str:
    text = str(value).strip() if value is not None else ""
    return "" if text.lower() in {"", "nan", "nat", "none", "null"} else text


def collect(files: dict) -> Usage:
    """What the sync would store for the time-zone field, counted per distinct value.

    Read through the ETL's own `transform()` rather than through a second
    implementation of its column matching. That is what drops the noise columns
    (a lookup exports as a pair -- the JSON and a `#Id` companion -- and both
    match the label), what claims one CSV column per output field, and what
    unwraps the lookup to its Value. Going through it means this file cannot
    drift from the pipeline it is checking, and cannot be wrong about the
    mapping in a way the pipeline is not.
    """
    usage = Usage()
    for key in ACTIVITY_FILES:
        path = files.get(key)
        if path is None:
            continue
        frame = transform(read_csv_auto(path), source_type=SOURCE_TYPES[key])
        if "time_zone" not in frame.columns:
            log(f"  {path.name}: no time-zone column")
            continue
        for row in frame.to_dict(orient="records"):
            value = _text(row.get("time_zone"))
            if not value:
                continue
            usage.values[value] += 1
            per_field = usage.context.setdefault(
                value, {name: Counter() for name, _ in CONTEXT_FIELDS}
            )
            for name, _label in CONTEXT_FIELDS:
                per_field[name][_text(row.get(name)) or BLANK] += 1
    return usage


def column_limit() -> int:
    """The width the database enforces, read from the model rather than repeated here."""
    try:
        from pipeline.api.app import Activity

        return Activity.__table__.c.time_zone.type.length or FALLBACK_LIMIT
    except Exception:
        return FALLBACK_LIMIT


def report(values: Counter, limit: int) -> bool:
    """Print the findings. True when the refresh cannot die on this field."""
    if not values:
        log("No time-zone values found in the export.")
        print_kv([
            ("Meaning", "the column is absent or empty in every row"),
            ("Consequence", "every activity will read as missing a time zone"),
        ])
        print()
        return False

    rows = [
        (str(count), str(len(value)), value)
        for value, count in sorted(values.items(), key=lambda item: (-len(item[0]), item[0]))
    ]
    print_table(
        f"Time zones in the export (column holds {limit} characters)",
        ["Rows", "Chars", "Value"],
        rows,
        col_widths=[8, 8, 76],
    )

    # Printed in full, outside the table: the table truncates a long cell to fit,
    # and the one value worth reading completely is the one that does not.
    too_long = sorted((value for value in values if len(value) > limit), key=len, reverse=True)
    if too_long:
        log(f"ERROR: {len(too_long)} value(s) longer than {limit} characters.")
        for value in too_long:
            print(f"    {len(value):>3}  {value}")
        print()
        print_kv([
            ("Consequence", "the daily refresh dies on the INSERT and writes no row at all"),
            ("Fix", "map the display names to IANA zones in the ETL, or widen the column"),
        ])
        print()
        return False

    log(f"OK: {len(values)} distinct value(s), longest {max(len(v) for v in values)} of {limit} characters.")
    print()
    return True


def report_context(usage: Usage, top: int = 2) -> None:
    """Print who uses each zone: the regions and lead teams its activities sit in.

    The reason to want this is that the labels are inherited descriptions, not
    places the planner typed -- so a bucket can be picked for the offset, or by
    accident, and only its own rows say which. A zone whose activities all sit
    in one region means what it says; one whose rows sit somewhere else entirely
    is a mis-pick, and mapping it to the place in its name would carry the
    mistake into the database.
    """
    rows = []
    for value, count in usage.values.most_common():
        per_field = usage.context.get(value, {})
        cells = [
            "; ".join(f"{key} ({n})" for key, n in per_field.get(name, Counter()).most_common(top)) or "--"
            for name, _label in CONTEXT_FIELDS
        ]
        rows.append((str(count), value, *cells))

    print_table(
        f"Who uses each zone (top {top} per field)",
        ["Rows", "Zone", *(label for _name, label in CONTEXT_FIELDS)],
        rows,
        col_widths=[7, 36, 40, 40],
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="read the CSVs from this folder instead of the usual OneDrive/local discovery",
    )
    parser.add_argument(
        "--context",
        action="store_true",
        help="also show the regions and lead teams whose activities use each zone",
    )
    args = parser.parse_args(argv)

    print_banner("CPLAN time-zone check")

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
    if not any(key in files for key in ACTIVITY_FILES):
        log("ERROR: no activity export found.")
        print_kv([("Input dir", str(input_dir))])
        print()
        return 1

    usage = collect(files)
    fits = report(usage.values, column_limit())
    # After the verdict, not before it: the width answer is what the command is
    # for, and it must not scroll off behind twenty-odd rows of context.
    if args.context and usage.values:
        report_context(usage)
    return 0 if fits else 1


if __name__ == "__main__":
    sys.exit(main())
