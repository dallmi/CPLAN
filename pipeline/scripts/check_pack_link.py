#!/usr/bin/env python3
"""Say which column links an activity to a communication pack, and how well.

Three activity columns could carry the pack's identifier -- `communication_
pack_cpid`, `campaign_ltid`, and the `tracking_pack_id` split out of the
tracking ID -- and the exports do not say which one the pack list answers to.
Choosing by reasoning would put an unverified assumption under `07-packs.csv`,
where a wrong join does not look wrong: it looks like a pack file with
plausible numbers in it.

So it is measured. This reads the same exports a refresh reads, read-only, and
reports which columns of the pack export the ETL does not yet map, then scores
each candidate against the pack list. Three sample values are printed per side,
because the outcome worth diagnosing is the one where every candidate reads 0%:
an export that does not link and one whose identifiers are merely spelled
differently produce the same zero, and only seeing both sides tells them apart.

Scoring a raw column is not enough on its own, because one of the candidates is
derived from an identifier every activity carries. A tracking ID is
`<cluster>-<pack number>-<date>-<activity>-<channel>`, and the knowledge base
says that "for standalone activities, generic cluster and pack identifiers are
used" -- so its pack segment is never empty, and an activity with no pack
carries a placeholder rather than nothing. Counted as references, those
placeholders turn the share of activities that have a pack into a number that
reads like a broken join. A pack is attached only to the larger
communications, so most activities have none, and that is the normal state
rather than a defect.

The rest of the report follows from that. The placeholders are measured and
named, never assumed; the rate is reported again without them; each reference
says what it turned out to be -- resolved, generic, a cluster prefix that
differs, zero padding that differs, a number two packs share, or nothing at
all; and the fallback chain `communication_pack_cpid` then `tracking_pack_id`
is scored beside the real columns. The chain never wins here: it needs code the
ETL does not have, and whether it may be built is decided by the last figure,
which counts the activities where both columns name a pack and disagree.

Usage (from the repo root, or just double-click packlink.cmd):
    python -m pipeline.scripts.check_pack_link
    python -m pipeline.scripts.check_pack_link --input <folder>
    python -m pipeline.scripts.check_pack_link --csv out.csv
    python -m pipeline.scripts.check_pack_link --detail identifiers.csv

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
from pipeline.report.packs import MIN_LINK_RATE, key  # noqa: E402
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

# The second floor. A candidate must also answer for this share of the pack
# list, however cleanly the references it does carry resolve.
#
# Set from a real export where the rate alone could not decide: two
# candidates both resolved 100% of their references, one reaching 203 of 342
# packs and the other 12. A quarter sits far from both, so the rule survives
# the ratio moving without becoming a number tuned to one measurement. It
# lives here rather than in `packs.py` because it governs the choice between
# candidates, which is this tool's business; `MIN_LINK_RATE` is shared
# because the runtime re-checks that one on every run.
MIN_PACK_REACH = 0.25

SAMPLE_COUNT = 3


class Score(NamedTuple):
    column: str
    referenced: int
    matched: int
    packs_hit: int
    packs_total: int
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

    @property
    def reach(self) -> float:
        """Share of the pack list this column answers for.

        The second half of the question, and the half the rate cannot see. A
        column can resolve every reference it carries and still be an
        identifier from a different namespace that touches a handful of pack
        rows -- on a real export two candidates both scored 100%, one
        reaching 203 packs of 342 and the other 12. Rate says "does this
        resolve"; reach says "does it explain the pack list".
        """
        return self.packs_hit / self.packs_total if self.packs_total else 0.0


def select_winners(scores) -> list:
    """The candidates that clear both floors, best reach first.

    Both floors, because each catches a kind of wrong answer the other lets
    through: a narrow identifier that resolves perfectly, and a broad one
    that mostly resolves to nothing.
    """
    winners = [s for s in scores
               if s.rate >= MIN_LINK_RATE and s.reach >= MIN_PACK_REACH]
    return sorted(winners, key=lambda s: s.reach, reverse=True)


def _keys(series) -> set[str]:
    """Non-empty values in their comparable form, as a set.

    Keyed through `packs.key` rather than trimmed and upper-cased here, so
    the tool that chooses the join and the join itself cannot disagree about
    what counts as the same identifier -- a value this module reads as a
    match and the report reads as two different packs would make every figure
    in this output describe a join nobody runs.
    """
    if series is None:
        return set()
    return {identifier for identifier in (key(value) for value in series)
            if identifier}


# The share of an identifier column one value has to hold, while matching no
# pack row, before it is read as a generic identifier rather than as a
# reference to a pack.
#
# The knowledge base is what makes this measurable at all: a tracking ID is
# `<cluster>-<pack number>-<date>-<activity>-<channel>`, and "for standalone
# activities, generic cluster and pack identifiers are used". So the pack
# segment is never empty -- an activity with no pack carries a placeholder --
# and a diagnostic that counts every non-empty segment as a reference measures
# the share of standalone activities and calls it a link rate.
#
# Derived rather than hard-coded, because the placeholder's value is a
# property of the source system and not of this repository: writing
# `0000000` here would be the same unverified assumption the module was built
# to avoid. Five percent is deliberately far from both ends of what a real
# export shows -- a placeholder sits on most rows, a dead pack id on a
# handful -- so the rule survives the ratio moving. Every value it selects is
# named in the output, because a stale pack export can put a genuine
# identifier over the line and that is a finding, not a placeholder.
GENERIC_SHARE = 0.05

# And the floor under that share, in rows. A share is a ratio, and a ratio
# inverts on small input: in an eight-row export every distinct unmatched
# value holds a large share of its column, so share alone would wave all of
# them through as "no pack" -- the one category this report presents as
# expected and not worth acting on. The dead references it exists to surface
# would vanish into it exactly when the export is small enough to check by
# hand. Twenty-five rows is not a tuned number: it is the point below which
# "many activities share this value" stops being a claim the data supports.
GENERIC_MIN_ROWS = 25


def value_counts(series) -> dict:
    """How many activities carry each identifier, in comparable form.

    The rows behind an identifier, not the identifier count: one placeholder
    on sixteen thousand activities and one dead pack id on three are the same
    single value, and only the row counts tell them apart.
    """
    counts: dict[str, int] = {}
    for value in series if series is not None else []:
        identifier = key(value)
        if identifier:
            counts[identifier] = counts.get(identifier, 0) + 1
    return counts


def generic_values(series, pack_ids, share: float = GENERIC_SHARE,
                   min_rows: int = GENERIC_MIN_ROWS) -> dict:
    """The identifiers in `series` that stand for "no pack", with their counts.

    A value qualifies on two conditions together: no pack row answers to it,
    and it sits on at least `share` of the rows that carry any value at all.
    Either alone is wrong -- a real pack id is popular and matched, a dead
    one is unmatched and rare, and only the pair separates the placeholder
    from both.
    """
    counts = value_counts(series)
    total = sum(counts.values())
    if not total:
        return {}
    floor = max(total * share, min_rows)
    return {value: count for value, count in counts.items()
            if value not in pack_ids and count >= floor}


# What a reference turned out to be. Two of these are not defects: a resolved
# reference is the join working, and a generic one is an activity with no pack,
# which the knowledge base describes as the normal case -- a pack is attached
# only to the larger communications. The middle two are repairable joins, the
# last two are findings.
RESOLVED = "resolved"
GENERIC = "generic"
CLUSTER_DIFFERS = "cluster differs"
PADDING_DIFFERS = "padding differs"
AMBIGUOUS = "ambiguous number"
NO_PACK = "no pack"

# Report order: what worked, what is expected, what could be repaired, what is
# left over.
CATEGORIES = (RESOLVED, GENERIC, CLUSTER_DIFFERS, PADDING_DIFFERS,
              AMBIGUOUS, NO_PACK)


class PackIndex(NamedTuple):
    """The pack list keyed three ways, so a miss can say how it missed.

    `exact` answers "is this the pack". The other two answer "is this pack
    here under a different spelling", which is the difference between a
    missing pack and a mapping decision -- and both look identical to a set
    membership test.
    """

    exact: frozenset
    by_number: dict
    by_unpadded: dict


def _number(identifier: str) -> str:
    """The pack number out of `<cluster>-<number>`, or the whole value.

    Split from the right: the cluster segment is the prefix and the number is
    what follows the last separator. A value with no separator is its own
    number rather than an error -- the diagnostic's job is to describe what
    the export carries, not to reject it.
    """
    _, _, number = identifier.rpartition("-")
    return number or identifier


def _unpadded(number: str) -> str:
    return number.lstrip("0") or "0"


def build_index(pack_ids) -> PackIndex:
    by_number: dict = {}
    by_unpadded: dict = {}
    for cpid in pack_ids:
        number = _number(cpid)
        by_number.setdefault(number, set()).add(cpid)
        by_unpadded.setdefault(_unpadded(number), set()).add(cpid)
    return PackIndex(frozenset(pack_ids), by_number, by_unpadded)


def classify(value: str, index: PackIndex, generic: dict) -> str:
    """What one reference is, on the first rung of the ladder it answers to.

    Ambiguity outranks both repairable categories. Where two packs in
    different clusters carry the same number, matching on the number alone
    would assign one of them with no evidence for either -- and the result is
    indistinguishable from a clean match, which is the failure this whole
    module exists to keep out of `07-packs.csv`.
    """
    identifier = key(value)
    if identifier in index.exact:
        return RESOLVED
    if identifier in generic:
        return GENERIC

    number = _number(identifier)
    for table, lookup, verdict in ((index.by_number, number, CLUSTER_DIFFERS),
                                   (index.by_unpadded, _unpadded(number),
                                    PADDING_DIFFERS)):
        packs_hit = table.get(lookup)
        if packs_hit:
            return AMBIGUOUS if len(packs_hit) > 1 else verdict
    return NO_PACK


# The chain, in the order it consults its two columns. The first is the field
# the source system fills deliberately; the second is derived from an
# identifier that is generated for every activity, whether it has a pack or
# not. That asymmetry is the whole reason for the order: the derived value
# speaks only where the deliberate one is silent.
CHAIN_PRIMARY = "communication_pack_cpid"
CHAIN_SECONDARY = "tracking_pack_id"
CHAIN_COLUMN = f"{CHAIN_PRIMARY} then {CHAIN_SECONDARY}"


def _column(frame, name):
    """The column's values, or empty strings where the frame has no such column."""
    if name in getattr(frame, "columns", []):
        return [key(value) for value in frame[name]]
    return [""] * len(frame)


def with_chain(frame, generic: dict):
    """`frame` with the fallback chain added as one more scoreable column.

    Added to a copy as a column rather than returned on its own, so the chain
    is measured by the same `score()` the three real columns are measured by.
    A candidate scored by its own private arithmetic is a candidate that
    cannot be compared with the others, which is the only thing this run is
    for.
    """
    primary = _column(frame, CHAIN_PRIMARY)
    secondary = _column(frame, CHAIN_SECONDARY)
    frame = frame.copy()
    frame[CHAIN_COLUMN] = [
        first or ("" if second in generic else second)
        for first, second in zip(primary, secondary)
    ]
    return frame


# The pack number on its own, second segment of the tracking ID, as the ETL
# already splits it out. A candidate in its own right and not a variant of
# `tracking_pack_id`: where a pack's cluster prefix differs between the
# tracking ID and the pack list -- the live export carries the generic cluster
# `CCCCC` over real pack numbers -- cluster-and-number misses the pack and the
# number alone finds it.
NUMBER_COLUMN = "tracking_pack_number"


class NumberJoin(NamedTuple):
    """What a join on the pack number alone would do, and what it would cost.

    The benefit and the risk in one result, because they are the same
    decision. Dropping the cluster prefix is what lets this variant find a
    pack whose prefix drifted; it is also what leaves nothing to tell two
    packs with the same number apart.
    """

    score: Score
    ambiguous_packs: int
    ambiguous_refs: int


def number_join(frame, packs, generic: dict) -> NumberJoin:
    """Score `NUMBER_COLUMN` against the pack list's numbers, prefix ignored.

    Ambiguous numbers are neither matched nor quietly dropped: a reference
    landing on a number two packs carry is counted on its own, because
    resolving it would pick one of them with no evidence and produce a row
    indistinguishable from a clean match.

    Numbers are compared with leading zeros stripped, so `58` and `0000058`
    are one pack rather than two -- the padding difference this tool already
    reports as its own category.
    """
    pack_ids = _keys(packs.get("cpid") if packs is not None else None)
    by_number: dict = {}
    for cpid in pack_ids:
        by_number.setdefault(_unpadded(_number(cpid)), set()).add(cpid)
    unique = {number: next(iter(hit)) for number, hit in by_number.items()
              if len(hit) == 1}
    ambiguous = {number for number, hit in by_number.items() if len(hit) > 1}

    referenced = matched = ambiguous_refs = 0
    reached: set = set()
    seen: set = set()
    for value in frame.get(NUMBER_COLUMN, []):
        identifier = key(value)
        if not identifier or identifier in generic:
            continue
        referenced += 1
        number = _unpadded(identifier)
        seen.add(number)
        if number in ambiguous:
            ambiguous_refs += 1
        elif number in unique:
            matched += 1
            reached.add(unique[number])

    return NumberJoin(
        score=Score(column=NUMBER_COLUMN, referenced=referenced, matched=matched,
                    packs_hit=len(reached), packs_total=len(pack_ids),
                    orphan_activities=len(seen - set(unique) - ambiguous),
                    orphan_packs=len(pack_ids - reached),
                    samples=tuple(sorted(seen)[:SAMPLE_COUNT])),
        ambiguous_packs=sum(len(by_number[number]) for number in ambiguous),
        ambiguous_refs=ambiguous_refs)


class Bucket(NamedTuple):
    """One category of one column: how many identifiers, on how many rows."""

    column: str
    category: str
    identifiers: int
    activities: int
    samples: tuple


def buckets(frame, column: str, index: PackIndex, generic: dict) -> list:
    """Every reference in `column`, grouped by what it turned out to be.

    Both counts are carried because they answer different questions. A
    category holding two identifiers on nine thousand rows is a placeholder
    or a stale pack; one holding nine thousand identifiers on nine thousand
    rows is a namespace that has nothing to do with the pack list. The
    distinct count alone cannot tell those apart, and the row count alone
    cannot either.
    """
    grouped: dict = {}
    for identifier, count in value_counts(frame.get(column)).items():
        found = grouped.setdefault(classify(identifier, index, generic),
                                   {"ids": 0, "rows": 0, "samples": []})
        found["ids"] += 1
        found["rows"] += count
        if len(found["samples"]) < SAMPLE_COUNT:
            found["samples"].append(identifier)
    return [Bucket(column=column, category=category,
                   identifiers=found["ids"], activities=found["rows"],
                   samples=tuple(found["samples"]))
            for category, found in ((c, grouped[c]) for c in CATEGORIES
                                    if c in grouped)]


DETAIL_COLUMNS = ("column", "identifier", "activities", "category")


def detail_rows(frame, index: PackIndex, generic_by_column: dict) -> list:
    """One row per identifier per candidate column, with its category.

    The whole measurement at row level, so the verdict can be checked
    against the export instead of believed. It is also the only form of this
    report that can leave the machine it ran on -- the console output has to
    be read where it was produced.
    """
    rows = []
    for column, generic in generic_by_column.items():
        for identifier, count in sorted(value_counts(frame.get(column)).items()):
            rows.append((column, identifier, count,
                         classify(identifier, index, generic)))
    return rows


class Agreement(NamedTuple):
    """Where both columns speak, how often they say the same thing."""

    both: int
    agree: int
    disagree: int
    samples: tuple


def agreement(frame, generic: dict, sample_count: int = SAMPLE_COUNT) -> Agreement:
    """Compare the two columns on the rows where both name a pack.

    Placeholders are not a statement, so a row whose tracking ID carries one
    is not a disagreement -- it is the ordinary case of an activity with no
    pack, and counting it as a conflict would put the veto number in the
    thousands on an export with nothing wrong with it.
    """
    both = agree = 0
    samples: list = []
    for first, second in zip(_column(frame, CHAIN_PRIMARY),
                             _column(frame, CHAIN_SECONDARY)):
        if not first or not second or second in generic:
            continue
        both += 1
        if first == second:
            agree += 1
        elif len(samples) < sample_count:
            samples.append((first, second))
    return Agreement(both=both, agree=agree, disagree=both - agree,
                     samples=tuple(samples))


def score(frame, packs, column: str, ignore=()) -> Score:
    """Measure one candidate column against the pack list.

    `ignore` holds the identifiers that stand for "no pack" -- see
    `generic_values`. They leave the measurement entirely rather than
    counting as misses: a placeholder is not a reference that failed to
    resolve, and in the denominator it turns the share of activities that
    have a pack into something that reads like a broken join.
    """
    pack_ids = _keys(packs.get("cpid") if packs is not None else None)
    activity_ids = {identifier for identifier in _keys(frame.get(column))
                    if identifier not in ignore}

    referenced = 0
    matched = 0
    if column in frame.columns:
        for value in frame[column]:
            identifier = key(value)
            if not identifier or identifier in ignore:
                continue
            referenced += 1
            if identifier in pack_ids:
                matched += 1

    hit = activity_ids & pack_ids
    return Score(column=column, referenced=referenced, matched=matched,
                 packs_hit=len(hit), packs_total=len(pack_ids),
                 orphan_activities=len(activity_ids - pack_ids),
                 orphan_packs=len(pack_ids - activity_ids),
                 samples=tuple(sorted(activity_ids)[:SAMPLE_COUNT]))


SCORE_COLUMNS = ("column", "referenced", "matched", "rate", "packs_hit",
                 "packs_total", "reach", "orphan_activities", "orphan_packs")


def _write_scores(path: Path, scores: list[Score]) -> None:
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv_module.writer(handle)
        writer.writerow(SCORE_COLUMNS)
        for s in scores:
            writer.writerow([s.column, s.referenced, s.matched, f"{s.rate:.4f}",
                             s.packs_hit, s.packs_total, f"{s.reach:.4f}",
                             s.orphan_activities, s.orphan_packs])
    log(f"Scores written to {path}")


def _write_detail(path: Path, rows: list) -> None:
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv_module.writer(handle)
        writer.writerow(DETAIL_COLUMNS)
        writer.writerows(rows)
    log(f"Detail written to {path}")


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


def build_parser() -> argparse.ArgumentParser:
    """The flags this check accepts.

    A function rather than a block inside `main()` so the launcher's
    parameters can be checked against it. The machine holding the production
    export runs `packlink.cmd`, and a flag only the Python entry point knows
    about is a flag nobody there can reach.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", type=Path, default=None,
                        help="read the CSVs from this folder instead of the "
                             "usual OneDrive/local discovery")
    parser.add_argument("--csv", type=Path, default=None,
                        help="also write the candidate scores to this CSV")
    parser.add_argument("--detail", type=Path, default=None,
                        help="write one row per identifier, with the category "
                             "it fell into, to this CSV")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

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
        ["Column", "Referenced", "Matched", "Rate", "Packs hit", "Reach",
         "Orphan IDs", "Orphan packs"],
        [(s.column, s.referenced, s.matched, f"{s.rate:.0%}", s.packs_hit,
          f"{s.reach:.0%}", s.orphan_activities, s.orphan_packs)
         for s in scores],
        col_widths=[26, 11, 9, 7, 10, 7, 12, 13])
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

    # Everything below reads the same three columns a second time, through
    # the one fact the table above cannot know: a tracking ID always carries
    # a pack segment, and a standalone activity's is generic. Without that,
    # every activity without a pack is counted as a reference that failed to
    # resolve, and the resulting rate describes how many activities have a
    # pack while reading like a broken join.
    generic_by_column = {name: generic_values(load.frame.get(name), pack_ids)
                         for name in PACK_LINK_CANDIDATES}
    for name in PACK_LINK_CANDIDATES:
        found = generic_by_column[name]
        filled = sum(value_counts(load.frame.get(name)).values())
        named = ", ".join(
            f"{value} ({count} activities, {count / filled:.0%})"
            for value, count in sorted(found.items(), key=lambda item: -item[1]))
        log(f"{name} generic identifiers: {named or 'none'}")
    print()

    real = {name: score(load.frame, packs, name, ignore=generic_by_column[name])
            for name in PACK_LINK_CANDIDATES}
    for scored in scores:
        honest = real[scored.column]
        log(f"{scored.column}: {scored.rate:.0%} of {scored.referenced} "
            f"references, {honest.rate:.0%} of the {honest.referenced} that "
            "are not placeholders")
    print()

    # The chain is measured here and nowhere near `select_winners`. It is a
    # proposal that needs code the ETL does not have, not a column
    # `PACK_LINK_COLUMN` could be pointed at -- and it resolves at least as
    # well as its first column by construction, so scored as a candidate it
    # would tie with it on every healthy export and make this tool report
    # "pick by hand" on a run where nothing is wrong.
    generic_secondary = generic_by_column[CHAIN_SECONDARY]
    chain_score = score(with_chain(load.frame, generic_secondary), packs,
                        CHAIN_COLUMN, ignore=generic_secondary)

    # The pack number on its own, scored in the same table so it can be
    # compared instead of argued about. Its placeholders are found the same
    # way, but against the pack list's numbers rather than its full
    # identifiers: keyed on the identifiers, every bare number would match
    # nothing and the frequent ones would all read as generic.
    pack_numbers = {_unpadded(_number(cpid)) for cpid in pack_ids}
    generic_numbers = generic_values(load.frame.get(NUMBER_COLUMN), pack_numbers)
    numbered = number_join(load.frame, packs, generic_numbers)

    print_table(
        "Without the generic identifiers, plus the fallback chain",
        ["Column", "Real refs", "Matched", "Rate", "Packs hit", "Reach"],
        [(s.column, s.referenced, s.matched, f"{s.rate:.0%}", s.packs_hit,
          f"{s.reach:.0%}")
         for s in ([real[name] for name in PACK_LINK_CANDIDATES]
                   + [numbered.score, chain_score])],
        # Wide enough for `CHAIN_COLUMN` whole: `print_table` truncates with
        # an ellipsis, and a chain named half-way is a row a reader cannot
        # tell from one of the three real columns.
        col_widths=[len(CHAIN_COLUMN) + 2, 11, 9, 7, 10, 7])
    print()

    # The price of that row, printed with it. The prefix is what let two packs
    # with the same number be told apart, and a reader weighing what the
    # variant finds without weighing what it can no longer distinguish is
    # weighing half the decision.
    log(f"{NUMBER_COLUMN} generic identifiers: "
        f"{', '.join(sorted(generic_numbers)) or 'none'}")
    log(f"{numbered.ambiguous_packs} packs share a number with another pack; "
        f"{numbered.ambiguous_refs} references land on one of those numbers "
        "and are left unresolved rather than assigned to one of them")
    print()

    index = build_index(pack_ids)
    print_table(
        "What each reference turned out to be",
        ["Column", "Category", "IDs", "Activities", "Examples"],
        [(b.column, b.category, b.identifiers, b.activities,
          ", ".join(b.samples))
         for name in PACK_LINK_CANDIDATES
         for b in buckets(load.frame, name, index, generic_by_column[name])],
        col_widths=[26, 17, 6, 11, 34])
    print()

    # The veto. Every other figure here says how much a column resolves;
    # only this one can say it resolves to the wrong pack, and a chain built
    # over a column that disagrees with the deliberate one would look clean
    # doing it.
    verdict = agreement(load.frame, generic_secondary)
    log(f"Both columns name a pack on {verdict.both} activities: "
        f"{verdict.agree} agree, {verdict.disagree} disagree")
    for first, second in verdict.samples:
        log(f"  disagreement: {first} vs {second}")
    if verdict.disagree:
        log("  The chain is not safe while these disagree: on those rows it "
            "would resolve to a pack the source system does not name.")
    print()

    if args.detail is not None:
        _write_detail(args.detail, detail_rows(load.frame, index,
                                               generic_by_column))
        print()

    winners = select_winners(scores)
    if len(winners) == 1:
        log(f"PACK_LINK_COLUMN = {winners[0].column}  "
            f"({winners[0].rate:.0%} of {winners[0].referenced} referenced, "
            f"reaching {winners[0].reach:.0%} of the pack list)")
        print()
        if args.csv is not None:
            _write_scores(args.csv, scores)
        return 0

    if not winners:
        log(f"No candidate clears both floors ({MIN_LINK_RATE:.0%} of its own "
            f"references, {MIN_PACK_REACH:.0%} of the pack list). The exports "
            "do not link on any of these columns -- that is the finding.")
    else:
        log(f"{len(winners)} candidates clear both floors: "
            f"{', '.join(w.column for w in winners)}. Pick by hand, and say why.")
    print()
    if args.csv is not None:
        _write_scores(args.csv, scores)
    return 1


if __name__ == "__main__":
    sys.exit(main())
