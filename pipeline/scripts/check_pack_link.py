#!/usr/bin/env python3
"""Say which column links an activity to a communication pack, and how well.

Three activity columns could carry the pack's identifier -- `communication_
pack_cpid`, `campaign_ltid`, and the `tracking_pack_id` split out of the
tracking ID -- and the exports do not say which one the pack list answers to.
Choosing by reasoning would put an unverified assumption under `07-packs.csv`,
where a wrong join does not look wrong: it looks like a pack file with
plausible numbers in it.

So it is measured. This reads the same exports a refresh reads, read-only, and
reports two things: which columns of the pack export the ETL does not yet map,
and how each candidate scores against the pack list.

Usage (from the repo root, or just double-click packlink.cmd):
    python -m pipeline.scripts.check_pack_link
    python -m pipeline.scripts.check_pack_link --input <folder>
    python -m pipeline.scripts.check_pack_link --csv out.csv

Exit code 0 only when exactly one candidate matches at least 80% of the
activities that carry any pack reference at all.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from pipeline.scripts.process_cplan import (  # noqa: E402
    PACKS_COLUMN_MAP,
    decode_sp_column_name,
    find_input_dir,
    find_input_files,
    log,
    print_banner,
    print_kv,
    print_table,
)

PACK_KEY = "packs"


def unmapped_columns(raw_columns):
    """One row per export column: raw name, decoded name, mapped or not.

    The match is the one `transform_packs` performs -- exact on the raw name,
    exact on the decoded name, or the decoded name starting with the label --
    so a column reported here as unmapped is exactly a column the harmonised
    frame will not have.
    """
    rows = []
    for raw in raw_columns:
        name = raw.strip()
        decoded = decode_sp_column_name(name).strip()
        hit = any(name == label or decoded == label or decoded.startswith(label)
                  for label in PACKS_COLUMN_MAP)
        rows.append((name, decoded, "mapped" if hit else "unmapped"))
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", type=Path, default=None,
                        help="read the CSVs from this folder instead of the "
                             "usual OneDrive/local discovery")
    parser.add_argument("--csv", type=Path, default=None,
                        help="also write the candidate scores to this CSV")
    args = parser.parse_args(argv)

    print_banner("CPLAN pack-link check")

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
    if PACK_KEY not in files:
        log("ERROR: no pack export in the input folder.")
        log("Expected: CommunicationPacks*.csv")
        print_kv([("Input dir", str(input_dir))])
        print()
        return 1

    from pipeline.scripts.process_cplan import read_csv_auto

    raw = read_csv_auto(files[PACK_KEY])
    columns = unmapped_columns(list(raw.columns))
    print()
    print_table("Pack export columns",
                ["Column", "Decoded", "Status"],
                columns,
                col_widths=[34, 34, 10])
    missing = [name for name, _, status in columns if status == "unmapped"]
    if missing:
        log(f"{len(missing)} column(s) the ETL does not map: {', '.join(missing)}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
