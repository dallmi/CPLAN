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
and how each candidate scores against the pack list. Three sample values are
printed per side, because the outcome worth diagnosing is the one where every
candidate reads 0%: an export that does not link and one whose identifiers are
merely spelled differently produce the same zero, and only seeing both sides
tells them apart.

Usage (from the repo root, or just double-click packlink.cmd):
    python -m pipeline.scripts.check_pack_link
    python -m pipeline.scripts.check_pack_link --input <folder>
    python -m pipeline.scripts.check_pack_link --csv out.csv

Exit code 0 only when exactly one candidate matches at least 80% of the
activities that carry any pack reference at all.
"""

from __future__ import annotations

import argparse
import csv as csv_module
import sys
from pathlib import Path
from typing import NamedTuple

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# The floor a candidate must clear to count as the link, imported rather than
# restated. `report_calendar` warns below this value on every run and this tool
# exits non-zero below it before a merge, so the two are one policy: a gate that
# passes at a rate the runtime warns about is drift nobody would see, because
# each side looks internally consistent. Both modules previously carried their
# own `0.8` under a comment calling it "the same floor" as the other one, which
# is a coupling asserted by prose and enforced by nothing.
#
# `PACK_LINK_CANDIDATES` below deliberately does NOT follow it there: which
# columns are worth scoring is this tool's own business, and `packs.py` holds
# only the answer this tool produced.
from pipeline.report.packs import MIN_LINK_RATE  # noqa: E402
from pipeline.scripts.process_cplan import (  # noqa: E402
    _is_noise_col,
    decode_sp_column_name,
    find_input_dir,
    find_input_files,
    load_activities,
    log,
    print_banner,
    print_kv,
    print_table,
    read_csv_auto,
    resolve_pack_columns,
    transform_packs,
)

PACK_KEY = "packs"

# The three columns that could carry the pack identifier, in the order they
# are reported. Named here rather than in the report module because this is
# the tool that decides between them; `pipeline/report/packs.py` holds only
# the answer.
PACK_LINK_CANDIDATES = ("communication_pack_cpid", "campaign_ltid",
                        "tracking_pack_id")

SAMPLE_COUNT = 3


class Score(NamedTuple):
    column: str
    referenced: int
    matched: int
    packs_hit: int
    orphan_activities: int
    orphan_packs: int
    # Activity-side only, and per candidate because each candidate reads a
    # different column. The pack side does not vary that way, so `main()`
    # prints it once rather than repeating one list three times.
    samples: tuple[str, ...]

    @property
    def rate(self) -> float:
        """Matched over *referenced*, never over the row count.

        An activity that names no pack is not a failed link, it is an
        unplanned activity. Putting it in the denominator would report a
        linking problem where there is only an empty field.
        """
        return self.matched / self.referenced if self.referenced else 0.0


def _keys(series) -> set[str]:
    """Non-empty values, trimmed and upper-cased, as a set."""
    if series is None:
        return set()
    values: set[str] = set()
    for value in series:
        if value is None or value != value:
            continue
        text = str(value).strip().upper()
        if text and text != "NAN":
            values.add(text)
    return values


def score(frame, packs, column: str) -> Score:
    """Measure one candidate column against the pack list."""
    pack_ids = _keys(packs.get("cpid") if packs is not None else None)
    activity_ids = _keys(frame.get(column))

    referenced = 0
    matched = 0
    if column in frame.columns:
        for value in frame[column]:
            if value is None or value != value:
                continue
            text = str(value).strip().upper()
            if not text or text == "NAN":
                continue
            referenced += 1
            if text in pack_ids:
                matched += 1

    hit = activity_ids & pack_ids
    return Score(column=column, referenced=referenced, matched=matched,
                 packs_hit=len(hit),
                 orphan_activities=len(activity_ids - pack_ids),
                 orphan_packs=len(pack_ids - activity_ids),
                 samples=tuple(sorted(activity_ids)[:SAMPLE_COUNT]))


SCORE_COLUMNS = ("column", "referenced", "matched", "rate", "packs_hit",
                 "orphan_activities", "orphan_packs")


def _write_scores(path: Path, scores: list[Score]) -> None:
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv_module.writer(handle)
        writer.writerow(SCORE_COLUMNS)
        for s in scores:
            writer.writerow([s.column, s.referenced, s.matched, f"{s.rate:.4f}",
                             s.packs_hit, s.orphan_activities, s.orphan_packs])
    log(f"Scores written to {path}")


def unmapped_columns(raw_columns: list[str]) -> list[tuple[str, str, str]]:
    """One row per export column: raw name, decoded name, mapped or not.

    Routed through `transform_packs`'s own two steps -- `_is_noise_col` drops
    a lookup's `#Id`/`#WssId`/`#Claims`/`@odata.type` companion before
    anything is matched, then `resolve_pack_columns` claims each label for at
    most one column -- rather than re-deriving that rule here. A separate
    implementation of the match once reported a noise companion, and the
    losing half of a duplicate label, as "mapped" when `transform_packs`
    drops both; routing through the same two functions means this cannot
    drift from what the ETL actually keeps.
    """
    names = [raw.strip() for raw in raw_columns]
    survivors = [name for name in names if not _is_noise_col(name)]
    rename_map = resolve_pack_columns(survivors)

    rows = []
    for name in names:
        decoded = decode_sp_column_name(name).strip()
        rows.append((name, decoded, "mapped" if name in rename_map else "unmapped"))
    return rows


def main(argv: list[str] | None = None) -> int:
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

    load = load_activities(files)
    if load.frame.empty:
        log("ERROR: the activity exports contain no activities.")
        print()
        return 1

    packs = transform_packs(raw)
    log(f"Pack rows: {len(packs)}")
    print()

    scores = [score(load.frame, packs, name) for name in PACK_LINK_CANDIDATES]
    print_table(
        "Candidate link columns",
        # "Orphan IDs", not "Orphan act.": the figure counts distinct
        # identifiers a candidate column carries that no pack answers to, not
        # activity rows. A human makes the merge call off this table, and
        # "activities" beside a distinct-value count is a number they would
        # reasonably compare against the row count.
        ["Column", "Referenced", "Matched", "Rate", "Packs hit",
         "Orphan IDs", "Orphan packs"],
        [(s.column, s.referenced, s.matched, f"{s.rate:.0%}", s.packs_hit,
          s.orphan_activities, s.orphan_packs) for s in scores],
        col_widths=[26, 11, 9, 7, 10, 12, 13])
    print()
    for scored in scores:
        log(f"{scored.column} sample values: "
            f"{', '.join(scored.samples) if scored.samples else '(none)'}")
    # Both sides, or the worst outcome this tool can report is unreadable.
    # Three candidates at 0% look identical whether the exports genuinely do
    # not link or the identifiers are merely spelled differently on the two
    # sides -- `CP-100` against `100` -- and those lead somewhere completely
    # different. Printed once rather than per candidate: the pack list's
    # identifiers do not vary by which activity column is being scored.
    pack_ids = _keys(packs.get("cpid") if packs is not None else None)
    pack_samples = sorted(pack_ids)[:SAMPLE_COUNT]
    log(f"pack list sample values: "
        f"{', '.join(pack_samples) if pack_samples else '(none)'}")
    print()

    winners = [s for s in scores if s.rate >= MIN_LINK_RATE]
    if len(winners) == 1:
        log(f"PACK_LINK_COLUMN = {winners[0].column}  "
            f"({winners[0].rate:.0%} of {winners[0].referenced} referenced)")
        print()
        if args.csv is not None:
            _write_scores(args.csv, scores)
        return 0

    if not winners:
        log(f"No candidate reaches {MIN_LINK_RATE:.0%}. The exports do not link "
            "on any of these columns -- that is the finding.")
    else:
        log(f"{len(winners)} candidates clear {MIN_LINK_RATE:.0%}: "
            f"{', '.join(w.column for w in winners)}. Pick by hand, and say why.")
    print()
    if args.csv is not None:
        _write_scores(args.csv, scores)
    return 1


if __name__ == "__main__":
    sys.exit(main())
