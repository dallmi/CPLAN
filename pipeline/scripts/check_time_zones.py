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
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from pipeline.scripts.process_cplan import (  # noqa: E402
    COLUMN_MAP,
    decode_sp_column_name,
    find_input_dir,
    find_input_files,
    log,
    parse_sp_lookup,
    print_banner,
    print_kv,
    print_table,
    read_csv_auto,
)

# The width to assume when the model cannot be imported -- the API's own
# packages are not installed in every environment that can run the ETL. Kept as
# a floor, not as the answer: `column_limit()` prefers the model.
FALLBACK_LIMIT = 64

# Every export the sync feeds from. Archive rows are imported like any other, so
# an over-long value there stops the same refresh.
ACTIVITY_FILES = ("internal", "external", "internal_archive", "external_archive")


def _time_zone_label() -> str:
    """The label the ETL matches the column with, read from the ETL's own table.

    Derived rather than repeated: if the source ever renames the column and
    COLUMN_MAP is updated, this check follows without a second edit, and it can
    never disagree with what the pipeline actually reads.
    """
    return next(label for label, field in COLUMN_MAP.items() if field == "time_zone")


def is_time_zone_column(name: str) -> bool:
    """Mirror `transform()`'s wildcard rule: decoded starts with the prefix and contains the suffix."""
    label = _time_zone_label()
    prefix, suffix = label.split("*", 1) if "*" in label else (label, "")
    decoded = decode_sp_column_name(name).strip().upper()
    return decoded.startswith(prefix.upper()) and suffix.upper() in decoded


def collect(files: dict) -> Counter:
    """Every time-zone value across the activity exports, unwrapped, with its row count.

    Unwrapped through `parse_sp_lookup`, the same function the ETL uses, so what
    is measured here is the string that would actually be stored -- not the JSON
    around it, and not a second opinion about how to read it.
    """
    values: Counter = Counter()
    for key in ACTIVITY_FILES:
        path = files.get(key)
        if path is None:
            continue
        frame = read_csv_auto(path)
        columns = [column for column in frame.columns if is_time_zone_column(column)]
        if not columns:
            log(f"  {path.name}: no time-zone column")
            continue
        for column in columns:
            for raw in frame[column]:
                value = parse_sp_lookup(raw).strip()
                if value:
                    values[value] += 1
    return values


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="read the CSVs from this folder instead of the usual OneDrive/local discovery",
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

    return 0 if report(collect(files), column_limit()) else 1


if __name__ == "__main__":
    sys.exit(main())
