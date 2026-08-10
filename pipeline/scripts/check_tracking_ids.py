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
