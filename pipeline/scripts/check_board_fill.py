#!/usr/bin/env python3
"""Does each board panel have something to draw, against a pack that was built?

`tests/test_agent_pack.py` proves every `Source:` citation *resolves* -- the
line it names exists. This asks the next question, which no test can answer
from seed data: does it resolve to a figure worth a chart. A panel citing a
line that reads 0 for every division passes that test and still reaches the
reader as four empty bars.

The distinction this exists for is the one nobody can make by eye. A measure
that is zero everywhere has three different causes, and they need three
different answers:

  carried, and genuinely zero  -- a finding. Say it on the board.
  carried, never filled        -- a source-data problem. Chase the owners.
  not carried by the export    -- not a finding at all. The board must not
                                  imply the plan is empty when the column is.

Only the third is invisible in the breakdown file, because a column the export
never had and a column nobody ever fills produce the same zero there. So this
reads the breakdown *and* the field-completeness table in `03-data-quality.txt`
and crosses them. `without_pack` is where it matters most: that measure counts
absence, so a missing column does not read as zero -- it reads as every
activity in the plan failing to record a pack link, which is the most alarming
figure the board can print and the one least likely to be questioned.

The boards are imported, not restated. Add a panel or change a citation and
this follows without being edited; that is the whole reason it lives beside
them rather than in a runbook.

Reads only. Writes nothing but the optional --csv.

Usage (from the repo root, or just double-click boardfill.cmd):
    python -m pipeline.scripts.check_board_fill
    python -m pipeline.scripts.check_board_fill --pack <folder>
    python -m pipeline.scripts.check_board_fill --csv out.csv

Exit code 0 only when every panel of every board has a figure to draw.
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

from pipeline.report import dashboard_contract, dashboard_skill  # noqa: E402
from pipeline.report.metrics import REPORTED_FIELDS  # noqa: E402

DEFAULT_PACK = _REPO_ROOT / "pipeline" / "output" / "agent-pack" / "pack"

# Which export column each measure counts. Only measures whose emptiness has a
# single nameable cause are listed: `activities` is not here because a zero
# there means the period is empty, which the summary already says outright, and
# `median_completeness` is not here because it spans a dozen fields and its own
# table in `03-data-quality.txt` is the better diagnosis.
#
# The prose files cite a label rather than a measure, so those are mapped too.
# Both maps name the export column, never the derived one: `has_executives` is
# what the pack counts, `bod_geb` is what somebody has to go and fill in.
MEASURE_COLUMN = {
    "with_executives": "bod_geb",
    "without_pack": "communication_pack_cpid",
    "large_audience": "audience",
    "unknown_audience": "audience",
    "short_notice": "created",
}
LABEL_COLUMN = {
    "With GEB/GEB-1 involvement": "bod_geb",
    "Large audience (top two bands)": "audience",
}

# Measures and labels that count what is *not* there. Zero is the healthy
# reading for these, so "every value is zero" is not the fault to look for --
# and a panel with nothing to plot because nothing is wrong is a sentence to
# write, not a chart to draw. The failure mode to catch here is the opposite
# one: a figure covering the whole plan because the column is absent.
COUNTS_ABSENCE = frozenset({
    "without_pack", "unknown_audience",           # 06-breakdowns / 08-periods
    "Unknown",                                    # 01-summary VOLUME
    "RECORD ANOMALIES", "FIELD COMPLETENESS",     # 03-data-quality
})

FILLS, CLEAN = "FILLS", "CLEAN"
EMPTY, UNMEASURABLE, STALE, MISSING = "EMPTY", "UNMEASURABLE", "STALE", "MISSING"


class Panel(NamedTuple):
    """One panel's verdict, and the sentence that explains it."""

    board: str
    heading: str
    verdict: str
    detail: str


def log(message=""):
    print(message, flush=True)


def prose_sections(text):
    """`TITLE -> [line, ...]` for the underlined sections of a prose pack file.

    Both prose files write a title and then a rule of dashes exactly as long,
    which is what makes the shape detectable without a parser per file. Kept
    identical to the one the pack tests use: two parsers that disagree about
    where a section ends would let a board pass one and fail the other.
    """
    lines = text.splitlines()
    sections, current = {}, None
    for index, line in enumerate(lines):
        following = lines[index + 1].strip() if index + 1 < len(lines) else ""
        if line.strip() and following and set(following) == {"-"}:
            current = line.strip()
            sections[current] = []
        elif current is not None and set(line.strip()) != {"-"}:
            sections[current].append(line)
    return sections


def panels(text):
    """`(heading, body)` per `###` panel, in board order."""
    found, heading, body = [], None, []
    for line in text.splitlines():
        if line.startswith("### "):
            if heading is not None:
                found.append((heading, "\n".join(body)))
            heading, body = line[4:].strip(), []
        elif heading is not None:
            body.append(line)
    if heading is not None:
        found.append((heading, "\n".join(body)))
    return found


def citations(text):
    """Every `Source:` citation in a panel, one per returned string."""
    found = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("Source:"):
            continue
        body = stripped[len("Source:"):].strip()
        if body == "none":
            continue
        found += [part.strip() for part in body.split(";") if part.strip()]
    return found


def number(raw):
    """The count at the front of a pack value, or None if there is not one.

    Pack values carry their own gloss -- `0  (0% of the 2400 in scope)` -- and
    a date where a count would be. Both are read here rather than guarded
    against at the call site, because a citation pointing at `Data as of` is
    a legitimate citation that simply has no figure to be empty.
    """
    head = str(raw).strip().split()[0] if str(raw).strip() else ""
    head = head.replace("'", "").replace(",", "").replace("%", "")
    try:
        return int(head)
    except ValueError:
        return None


def field_completeness(pack_dir):
    """`field -> (filled, missing)` from the data-quality table.

    A field the export did not carry has no row here at all, which is the
    signal the breakdown file cannot give.
    """
    path = pack_dir / "03-data-quality.txt"
    if not path.exists():
        return {}
    section = prose_sections(path.read_text(encoding="utf-8")).get(
        "FIELD COMPLETENESS", [])
    fields = {}
    for line in section:
        parts = [part.strip() for part in line.split("|")]
        if len(parts) < 3 or parts[0] in ("field", ""):
            continue
        filled, missing = number(parts[1]), number(parts[2])
        if filled is not None and missing is not None:
            fields[parts[0]] = (filled, missing)
    return fields


def figures(citation, pack_dir):
    """`(figures, error)` -- what a panel would plot for one citation."""
    parts = [part.strip() for part in citation.split("·")]
    name, rest = parts[0], parts[1:]
    path = pack_dir / name
    if not path.exists():
        return None, f"the pack has no {name}"
    if not rest:
        return None, "names a file and nothing in it"

    if name.endswith(".csv"):
        with path.open(encoding="utf-8") as handle:
            rows = list(csv_module.DictReader(handle))
        wanted = dict(part.split("=", 1) for part in rest if "=" in part)
        hits = [row for row in rows
                if all(row.get(key) == value for key, value in wanted.items())]
        if not hits:
            return None, f"no row in {name} matches {wanted}"
        return [number(row.get("figure")) for row in hits], None

    sections = prose_sections(path.read_text(encoding="utf-8"))
    section = rest[0]
    if section not in sections:
        return None, f"{name} has no section {section!r}"
    lines = [line.strip() for line in sections[section] if line.strip()]
    if len(rest) == 1:
        return [number(line.split("|")[-1]) for line in lines], None
    label = rest[1]
    for line in lines:
        if line.startswith(f"{label}:"):
            return [number(line.split(":", 1)[1])], None
        if line.startswith(f"{label} |"):
            return [number(line.split("|")[-1])], None
    return None, f"{section} states no {label!r}"


def subject(citation):
    """`(measure_or_label, column)` -- what a citation counts, and from where.

    CSV citations name a `measure=`; prose citations name a label or a whole
    section. Both are the same question asked of two file shapes.
    """
    parts = [part.strip() for part in citation.split("·")]
    measure = next((part.split("=", 1)[1] for part in parts
                    if part.startswith("measure=")), None)
    if measure is not None:
        return measure, MEASURE_COLUMN.get(measure)
    name = parts[-1] if len(parts) > 1 else ""
    return name, LABEL_COLUMN.get(name)


def diagnose(citation, values, fields, total):
    """Why a measure is zero -- or why a large one is not the finding it looks.

    The whole point of the tool. A verdict without this is a number a reader
    has to interpret, and a zero has four causes that call for four different
    people to do four different things.

    Polarity is a property of the panel, not of the pack: `without_pack` and
    `activities` are both counts, and the pack cannot say that one of them is
    bad news when it is large and the other when it is small. `COUNTS_ABSENCE`
    is where that judgement is written down, once.
    """
    name, column = subject(citation)
    stated = [value for value in values if value is not None]
    inverted = name in COUNTS_ABSENCE

    if not stated:
        return FILLS, "no count on this line, and none expected"

    if inverted:
        # Loudest exactly when least trustworthy: a column the export never
        # carried reads here as the whole plan failing to record it.
        if column and total and column not in fields and max(stated) >= total:
            return UNMEASURABLE, (
                f"{name} covers every activity because the export carries no "
                f"{column} column - not a planning finding")
        if max(stated) > 0:
            return FILLS, ""
        return CLEAN, f"zero throughout, and for {name} that is the good news"

    if max(stated) > 0:
        return FILLS, ""

    if column is None:
        return EMPTY, "zero throughout; no single column explains it"
    if column not in REPORTED_FIELDS:
        # Said rather than guessed. The quality table reports a fixed field
        # list, so a column outside it is invisible there whether the export
        # carries it or not, and calling that "missing from the export" would
        # be the tool inventing a finding.
        return EMPTY, (
            f"zero throughout; the pack does not report how often {column} "
            "is filled, so this one needs checking at the source")
    if column not in fields:
        return UNMEASURABLE, f"the export carries no {column} column"
    filled, missing = fields[column]
    if filled == 0:
        return EMPTY, f"{column} is carried and never filled ({missing} rows)"
    return EMPTY, (
        f"{column} is filled on {filled} rows yet the measure reads zero - "
        "a mapping fault, not a data gap")


def audit(pack_dir):
    """Every panel of every board, in board order."""
    fields = field_completeness(pack_dir)
    total = None
    summary = pack_dir / "01-summary.txt"
    if summary.exists():
        values, _ = figures("01-summary.txt · VOLUME · Activities in scope",
                            pack_dir)
        total = values[0] if values else None

    boards = dict(dashboard_skill.BOARDS)
    boards.update(dashboard_contract.CONTRACTS)

    results = []
    for board, text in boards.items():
        for heading, body in panels(text):
            cited = citations(body)
            if not cited:
                results.append(Panel(board, heading, FILLS,
                                     "prose panel, no figures of its own"))
                continue
            verdicts = []
            for citation in cited:
                values, error = figures(citation, pack_dir)
                if error:
                    verdicts.append(_unresolved(citation, error, pack_dir))
                    continue
                verdict, detail = diagnose(citation, values, fields, total)
                verdicts.append((verdict, detail))
            worst = min(verdicts, key=lambda pair: _RANK[pair[0]])
            results.append(Panel(board, heading, worst[0], worst[1]))
    return results, fields, total


def _unresolved(citation, error, pack_dir):
    """Separate a board that drifted from a pack that is simply older.

    Both arrive as "no row matches", and they are opposite problems: one means
    somebody must fix a citation, the other means somebody must rebuild the
    pack. Asking the same question without the grain constraint tells them
    apart -- a measure the pack states at year but not at quarter is the exact
    signature of a build from before the quarter grain carried it.
    """
    parts = [part.strip() for part in citation.split("·")]
    if any(part.startswith("grain=") for part in parts):
        relaxed = " · ".join(part for part in parts
                             if not part.startswith("grain="))
        values, still_wrong = figures(relaxed, pack_dir)
        if not still_wrong and values:
            grain = next(part.split("=", 1)[1] for part in parts
                         if part.startswith("grain="))
            return STALE, (
                f"the pack states this measure, but not at grain={grain} - "
                "it was built before the boards asked for it. Rebuild it.")
    return MISSING, f"{citation}: {error}"


# Worst-first, so a panel citing one healthy line and one missing one reports
# the missing one. A panel is only as drawable as its weakest citation.
_RANK = {MISSING: 0, STALE: 1, UNMEASURABLE: 2, EMPTY: 3, CLEAN: 4, FILLS: 5}

# Two of these are not faults. `CLEAN` is a panel with nothing to plot because
# nothing is wrong, and `N/A` is a question the export cannot answer -- neither
# is fixed by touching the board, so neither fails the run.
_MARK = {FILLS: "ok", CLEAN: "clean", EMPTY: "EMPTY",
         UNMEASURABLE: "N/A", STALE: "STALE", MISSING: "GONE"}
_HEALTHY = frozenset({FILLS, CLEAN})


def _write_csv(path, results):
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv_module.writer(handle)
        writer.writerow(["board", "panel", "verdict", "detail"])
        for row in results:
            writer.writerow([row.board, row.heading, row.verdict, row.detail])


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Say which board panels have a figure to draw.")
    parser.add_argument("--pack", type=Path, default=DEFAULT_PACK,
                        help="the built pack folder (default: the last build)")
    parser.add_argument("--csv", type=Path, default=None,
                        help="also write the verdicts to this file")
    args = parser.parse_args(argv)

    pack_dir = args.pack
    if not pack_dir.exists():
        log(f"No pack at {pack_dir}. Build one first, or pass --pack.")
        return 2

    results, fields, total = audit(pack_dir)

    log()
    log("=== Board fill check ===")
    log(f"Pack: {pack_dir}")
    log(f"Activities in scope: {total if total is not None else 'unknown'}")
    log()

    board = None
    for row in results:
        if row.board != board:
            board = row.board
            log(f"  {board}")
        log(f"    [{_MARK[row.verdict]:5s}] {row.heading}")
        if row.detail and row.verdict != FILLS:
            log(f"              {row.detail}")
    log()

    log("Source columns behind the measures:")
    for measure, column in sorted(MEASURE_COLUMN.items()):
        if column in fields:
            filled, missing = fields[column]
            share = filled / (filled + missing) if filled + missing else 0
            note = (f"{filled} filled, {missing} missing ({share:.0%})")
        elif column in REPORTED_FIELDS:
            note = "not carried by the export"
        else:
            note = "fill rate not reported by the pack"
        log(f"  {column:24s} {note:38s} <- {measure}")
    log()

    if args.csv is not None:
        _write_csv(args.csv, results)
        log(f"Written: {args.csv}")
        log()

    broken = [row for row in results if row.verdict not in _HEALTHY]
    clean = [row for row in results if row.verdict == CLEAN]
    if clean:
        log(f"{len(clean)} panel(s) marked clean: nothing to plot because "
            "nothing is wrong. Say that in words rather than drawing zeros.")
    if not broken:
        log("Every panel of every board has a figure to draw.")
        return 0
    log(f"{len(broken)} of {len(results)} panels cannot be drawn as specified. "
        "Each line above says which of the four causes it is, and they need "
        "four different answers.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
