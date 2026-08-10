#!/usr/bin/env python3
"""Say which of a list of tracking IDs the source exports actually contain.

Tracking IDs arrive by hand -- in a mail, on a slide, pasted out of a planning
sheet -- and the question asked of them is always whether the activities behind
them exist. Searching the CSVs answers that for three IDs and stops working at
thirty, and it answers only half the question: an empty search says "not in
this file", not whether the activity was never created or whether the channel
suffix is three letters wrong. Those two answers lead somewhere different.

A match is exact on `tracking_id`, trimmed and upper-cased on both sides.
Nothing else counts as found. Every ID that does not match is then put through
a ladder of near-miss searches, and the first hit is reported as a hint beside
it -- never as a verdict.

Usage (from the repo root, or just double-click trackids.cmd):
    python -m pipeline.scripts.check_tracking_ids --ids ids.txt
    python -m pipeline.scripts.check_tracking_ids --ids ids.txt --all --csv out.csv
    python -m pipeline.scripts.check_tracking_ids --ids ids.txt --input "C:\\path\\to\\Input"

Exit code 0 only when every listed ID was found.
"""

from __future__ import annotations

import argparse
import csv as csv_module
import sys
from collections import Counter
from dataclasses import dataclass
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


def normalise(value: str) -> str:
    """The one definition of "the same ID": trimmed, upper-cased."""
    return str(value).strip().upper()


def read_id_list(path: Path) -> tuple[list[str], Counter]:
    """The IDs the file lists, in first-seen order, once each -- and how often.

    Blank lines and lines whose first non-space character is `#` are dropped,
    so a list can carry its own headings. A repeat is not an error and not a
    second row: it is counted, and the count is what the report names.
    """
    listed: list[str] = []
    counts: Counter = Counter()
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key = normalise(line)
        if key not in counts:
            listed.append(line)
        counts[key] += 1
    return listed, counts


# The exports that carry a `tracking_id`, paired with the source type
# `transform()` reads them as, in the order a duplicate is resolved: an ID that
# is in both a live export and an archive is answered by the live row.
#
# The pack, channel and cluster exports are deliberately absent. They carry
# pack, channel and cluster identifiers, and searching them would let a pack ID
# report as a found activity.
ACTIVITY_SOURCES = (
    ("internal", "internal"),
    ("external", "external"),
    ("internal_archive", "internal"),
    ("external_archive", "external"),
)


@dataclass(frozen=True)
class Entry:
    """One activity the export carries, as much of it as the report shows."""

    tracking_id: str
    source: str
    sp_id: str
    activity_name: str


def _cell(row, column: str) -> str:
    """A column's value as a printable string, or "" where there is none."""
    if column not in row:
        return ""
    value = row[column]
    if value is None or (isinstance(value, float) and value != value):  # NaN
        return ""
    text = str(value).strip()
    return "" if text in ("nan", "None") else text


def build_index(files: dict[str, Path]) -> dict[str, Entry]:
    """Normalised tracking ID to the export row that carries it.

    Each file goes through the ETL's own `read_csv_auto()` and `transform()`.
    `transform()` is what turns the SharePoint-encoded headers into
    `tracking_id`, and what folds the export's long-standing `Tacking ID` typo
    variant into the same column -- reading the raw header would miss every row
    in whichever file carries the typo that week.
    """
    index: dict[str, Entry] = {}
    for key, source_type in ACTIVITY_SOURCES:
        path = files.get(key)
        if path is None:
            continue
        frame = transform(read_csv_auto(path), source_type)
        if "tracking_id" not in frame.columns:
            log(f"  {path.name} carries no tracking ID column")
            continue
        added = 0
        for _, row in frame.iterrows():
            tracking_id = normalise(_cell(row, "tracking_id"))
            if not tracking_id or tracking_id in index:
                continue
            index[tracking_id] = Entry(
                tracking_id=tracking_id,
                source=key,
                sp_id=_cell(row, "sp_id"),
                activity_name=_cell(row, "activity_name"),
            )
            added += 1
        log(f"  {key}: {added} tracking ID(s)")
    return index
