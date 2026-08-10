# Tracking-ID Check Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A read-only command that takes a text file of tracking IDs and reports which of them the source activity CSVs actually contain, naming a near-miss for each one it cannot find.

**Architecture:** One module, `pipeline/scripts/check_tracking_ids.py`, built the same way as `pipeline/scripts/check_time_zones.py`: it imports the ETL's own input discovery, CSV reader and `transform()` rather than re-implementing them, prints a boxed report through the ETL's print helpers, and returns an exit code from `main(argv)` so tests drive it as a function and the PowerShell launcher drives it as a process. Pure functions do the work — list parsing, index building, near-miss search — and `main()` only wires them together and prints.

**Tech Stack:** Python 3, pandas (via the ETL's `read_csv_auto`/`transform`), pytest, PowerShell 5 launchers.

**Spec:** `docs/superpowers/specs/2026-08-10-tracking-id-check-design.md`

## Global Constraints

- **The employer's brand name must never enter the repository** — not in code, identifiers, comments, docs, test data or commit messages. Write "the organisation" or "internal platform". A commit guard enforces this; `forbidden-terms.txt` must exist locally for the full check to run.
- **No absolute local paths in committed files.** Resolve from `Path(__file__).resolve().parents[2]`.
- Code, comments, docstrings, docs and commit messages in **English**.
- The check is **read-only**. It writes nothing except the CSV it is explicitly asked for.
- Scripts live in `pipeline/scripts/`, are run as `python -m pipeline.scripts.<name>`, and get a `<name>.ps1` + `<name>.cmd` launcher pair at the repository root.
- Launchers resolve Python in this fixed order: `CPLAN_PYTHON`, then `VIRTUAL_ENV`, then the repo-local `.venv`.
- Every new file added to the `check.ps1` manifest needs a marker string that occurs in the file; `tests/test_check_manifest.py` fails otherwise.
- Exit code 0 only when every listed ID was found. Every other outcome exits 1.
- The tracking ID shape is `CLUSTER-PACKNUM-YYMMDD-ACTNUM-CHANNEL`, e.g. `QRREP-0000058-240709-0000060-EMI`.

---

### Task 1: Read the ID list

**Files:**
- Create: `pipeline/scripts/check_tracking_ids.py`
- Create: `tests/test_check_tracking_ids.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `normalise(value: str) -> str` — strip and upper-case; the single definition of "the same ID".
  - `read_id_list(path: Path) -> tuple[list[str], Counter]` — the IDs in first-seen order (raw, stripped, one entry per distinct normalised ID) and a `Counter` keyed by normalised ID.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_check_tracking_ids.py`:

```python
"""Tests for the tracking-ID check.

The question it answers is whether a list of IDs someone was handed exists in
the export at all -- and, when one does not, whether it is absent because the
activity was never created or because a suffix is wrong.
"""

import csv
from pathlib import Path

import pytest

pytest.importorskip("pandas")

from pipeline.scripts import check_tracking_ids


def _ids(tmp_path: Path, *lines: str, name: str = "ids.txt") -> Path:
    path = tmp_path / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_the_list_keeps_its_order_and_drops_blanks_and_comments(tmp_path):
    path = _ids(
        tmp_path,
        "# the ones from the mail",
        "QRREP-0000058-240709-0000060-EMI",
        "",
        "   ",
        "  QRREP-0000058-240709-0000061-INT  ",
        "   # indented comment",
    )

    listed, counts = check_tracking_ids.read_id_list(path)

    assert listed == [
        "QRREP-0000058-240709-0000060-EMI",
        "QRREP-0000058-240709-0000061-INT",
    ]
    assert all(count == 1 for count in counts.values())


def test_a_repeated_id_is_listed_once_and_counted_twice(tmp_path):
    path = _ids(
        tmp_path,
        "QRREP-0000058-240709-0000060-EMI",
        "qrrep-0000058-240709-0000060-emi",
    )

    listed, counts = check_tracking_ids.read_id_list(path)

    assert listed == ["QRREP-0000058-240709-0000060-EMI"]
    assert counts["QRREP-0000058-240709-0000060-EMI"] == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_check_tracking_ids.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.scripts.check_tracking_ids'`

- [ ] **Step 3: Write the module head and the list reader**

Create `pipeline/scripts/check_tracking_ids.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_check_tracking_ids.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add pipeline/scripts/check_tracking_ids.py tests/test_check_tracking_ids.py
git commit -m "Read the list the way a person writes one"
```

---

### Task 2: Build the index over the activity exports

**Files:**
- Modify: `pipeline/scripts/check_tracking_ids.py`
- Modify: `tests/test_check_tracking_ids.py`

**Interfaces:**
- Consumes: `normalise` (Task 1).
- Produces:
  - `ACTIVITY_SOURCES: tuple[tuple[str, str], ...]` — `(input-file key, source_type)` pairs in duplicate-resolution order.
  - `Entry` dataclass with fields `tracking_id: str`, `source: str`, `sp_id: str`, `activity_name: str`.
  - `build_index(files: dict[str, Path]) -> dict[str, Entry]` — normalised tracking ID to the row that carries it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_check_tracking_ids.py`:

```python
def _export(tmp_path: Path, name: str, *rows: tuple[str, str, str]) -> Path:
    """One activity export. Each row is (tracking_id, sp_id, title)."""
    path = tmp_path / name
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["ID", "Tracking ID", "Title", "Start date"])
        for tracking_id, sp_id, title in rows:
            writer.writerow([sp_id, tracking_id, title, "2026-03-05"])
    return path


LIVE = "QRREP-0000058-240709-0000060-EMI"
OTHER_CHANNEL = "QRREP-0000058-240709-0000060-INT"
SAME_PACK = "QRREP-0000058-240709-0000099-EMI"
ARCHIVED = "TOWNH-0000012-240301-0000004-TMS"


def test_every_activity_export_is_indexed_and_names_its_own_source(tmp_path):
    _export(tmp_path, "InternalCommunicationActivities.csv", (LIVE, "1", "Quarterly report"))
    _export(tmp_path, "ExternalCommunicationActivities.csv", (SAME_PACK, "2", "Press note"))
    _export(tmp_path, "InternalCommunicationActivitiesArchive.csv", (ARCHIVED, "3", "Town hall"))

    files = check_tracking_ids.find_input_files(tmp_path)
    index = check_tracking_ids.build_index(files)

    assert index[LIVE].source == "internal"
    assert index[LIVE].sp_id == "1"
    assert index[LIVE].activity_name == "Quarterly report"
    assert index[SAME_PACK].source == "external"
    assert index[ARCHIVED].source == "internal_archive"


def test_a_live_row_wins_over_an_archived_one_with_the_same_id(tmp_path):
    """Both exports can carry an ID mid-archival. The live row is the answer."""
    _export(tmp_path, "InternalCommunicationActivities.csv", (LIVE, "1", "Live"))
    _export(tmp_path, "InternalCommunicationActivitiesArchive.csv", (LIVE, "9", "Archived"))

    index = check_tracking_ids.build_index(check_tracking_ids.find_input_files(tmp_path))

    assert index[LIVE].source == "internal"


def test_the_index_is_keyed_on_the_normalised_id(tmp_path):
    _export(tmp_path, "InternalCommunicationActivities.csv", (f"  {LIVE.lower()}  ", "1", "A"))

    index = check_tracking_ids.build_index(check_tracking_ids.find_input_files(tmp_path))

    assert LIVE in index


def test_the_pack_and_channel_exports_are_not_searched(tmp_path):
    """A pack ID is not an activity, and reporting one as found would be a lie."""
    _export(tmp_path, "InternalCommunicationActivities.csv", (LIVE, "1", "A"))
    packs = tmp_path / "CommunicationPacks.csv"
    with open(packs, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["ID", "Tracking ID", "Title"])
        writer.writerow(["7", ARCHIVED, "A pack"])

    index = check_tracking_ids.build_index(check_tracking_ids.find_input_files(tmp_path))

    assert ARCHIVED not in index
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_check_tracking_ids.py -v`
Expected: FAIL — `AttributeError: module 'pipeline.scripts.check_tracking_ids' has no attribute 'build_index'`

- [ ] **Step 3: Write the index builder**

Append to `pipeline/scripts/check_tracking_ids.py`, after `read_id_list`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_check_tracking_ids.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add pipeline/scripts/check_tracking_ids.py tests/test_check_tracking_ids.py
git commit -m "Index the four exports that carry an activity, and only those"
```

---

### Task 3: The near-miss ladder

**Files:**
- Modify: `pipeline/scripts/check_tracking_ids.py`
- Modify: `tests/test_check_tracking_ids.py`

**Interfaces:**
- Consumes: `Entry`, `build_index` (Task 2).
- Produces:
  - `PART_COUNT: int` — 5.
  - `find_hint(wanted: str, index: dict[str, Entry]) -> str` — the first rung that hits, as a sentence; `""` when nothing does.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_check_tracking_ids.py`:

```python
def _index(*ids: str) -> dict:
    return {
        check_tracking_ids.normalise(value): check_tracking_ids.Entry(
            tracking_id=check_tracking_ids.normalise(value),
            source="internal",
            sp_id="1",
            activity_name="An activity",
        )
        for value in ids
    }


def test_a_wrong_channel_suffix_is_named_as_such():
    hint = check_tracking_ids.find_hint(LIVE, _index(OTHER_CHANNEL))

    assert "channel" in hint.lower()
    assert OTHER_CHANNEL in hint


def test_a_missing_activity_in_an_existing_pack_names_the_pack():
    hint = check_tracking_ids.find_hint(LIVE, _index(SAME_PACK))

    assert "QRREP-0000058" in hint
    assert "pack" in hint.lower()


def test_the_channel_rung_wins_when_both_would_hit():
    """Rung 1 is the more specific answer, so it must be reached first."""
    hint = check_tracking_ids.find_hint(LIVE, _index(SAME_PACK, OTHER_CHANNEL))

    assert OTHER_CHANNEL in hint
    assert SAME_PACK not in hint


def test_one_character_off_is_named_as_a_typo():
    """A different cluster, so rungs 1 and 2 cannot fire -- only the distance does.

    An ID one letter off *within* the same pack is rung 1's case, not this one.
    """
    wanted = "QRREQ-0000058-240709-0000060-EMI"  # QRREQ, not QRREP
    hint = check_tracking_ids.find_hint(wanted, _index(LIVE))

    assert LIVE in hint
    assert "one character" in hint.lower()


def test_a_dropped_character_counts_as_one_edit():
    hint = check_tracking_ids.find_hint("QRREP-000058-240709-0000060-EMI", _index(LIVE))

    assert LIVE in hint


def test_an_id_of_the_wrong_shape_is_called_that():
    hint = check_tracking_ids.find_hint("QRREP-58", _index(LIVE))

    assert "shape" in hint.lower() or "part" in hint.lower()


def test_nothing_close_produces_no_hint():
    hint = check_tracking_ids.find_hint("ZZZZZ-0000001-200101-0000001-XXX", _index(LIVE))

    assert hint == ""
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_check_tracking_ids.py -v`
Expected: FAIL — `AttributeError: ... has no attribute 'find_hint'`

- [ ] **Step 3: Write the ladder**

Append to `pipeline/scripts/check_tracking_ids.py`:

```python
# CLUSTER-PACKNUM-YYMMDD-ACTNUM-CHANNEL
PART_COUNT = 5


def _within_one_edit(left: str, right: str) -> bool:
    """True when one substitution, insertion or deletion turns one into the other."""
    if abs(len(left) - len(right)) > 1:
        return False
    if len(left) == len(right):
        differences = sum(1 for a, b in zip(left, right) if a != b)
        return differences == 1
    shorter, longer = (left, right) if len(left) < len(right) else (right, left)
    i = j = 0
    skipped = False
    while i < len(shorter) and j < len(longer):
        if shorter[i] == longer[j]:
            i += 1
            j += 1
            continue
        if skipped:
            return False
        skipped = True
        j += 1
    return True


def find_hint(wanted: str, index: dict[str, Entry]) -> str:
    """Why this ID may be missing -- the first rung that hits, or "".

    Never a verdict. The row still reads `missing`; this only says where to
    look, because "not found" and "found, spelled differently" lead somewhere
    completely different.
    """
    key = normalise(wanted)
    parts = key.split("-")
    notes: list[str] = []

    if len(parts) == PART_COUNT:
        pack = f"{parts[0]}-{parts[1]}"
        activity_number = parts[3]

        # Rung 1: the same activity, published on another channel.
        for candidate in index:
            other = candidate.split("-")
            if len(other) != PART_COUNT:
                continue
            if f"{other[0]}-{other[1]}" == pack and other[3] == activity_number:
                return f"same activity on channel {other[4]}: {candidate}"

        # Rung 2: the pack exists, this activity within it does not.
        in_pack = sum(
            1
            for candidate in index
            if candidate.startswith(f"{pack}-")
        )
        if in_pack:
            return f"pack {pack} exists with {in_pack} activity(ies), this one is not among them"
    else:
        notes.append(f"not the {PART_COUNT}-part shape ({len(parts)} part(s))")

    # Rung 3: one character off.
    for candidate in index:
        if _within_one_edit(key, candidate):
            notes.append(f"one character from {candidate}")
            break

    return "; ".join(notes)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_check_tracking_ids.py -v`
Expected: PASS (13 tests)

- [ ] **Step 5: Commit**

```bash
git add pipeline/scripts/check_tracking_ids.py tests/test_check_tracking_ids.py
git commit -m "Say why an ID is missing, not only that it is"
```

---

### Task 4: The report, and the exit code

**Files:**
- Modify: `pipeline/scripts/check_tracking_ids.py`
- Modify: `tests/test_check_tracking_ids.py`

**Interfaces:**
- Consumes: `read_id_list`, `build_index`, `find_hint`.
- Produces:
  - `Result` dataclass: `listed: str`, `entry: Entry | None`, `hint: str`, `times_listed: int`, and a `status` property returning `"found"` or `"missing"`.
  - `check(listed: list[str], counts: Counter, index: dict[str, Entry]) -> list[Result]`
  - `report(results: list[Result], show_all: bool) -> None`
  - `main(argv: list[str] | None = None) -> int`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_check_tracking_ids.py`:

```python
def test_every_id_present_exits_zero_and_says_so(tmp_path, capsys):
    _export(tmp_path, "InternalCommunicationActivities.csv", (LIVE, "1", "Quarterly report"))
    ids = _ids(tmp_path, LIVE)

    exit_code = check_tracking_ids.main(["--ids", str(ids), "--input", str(tmp_path)])

    assert exit_code == 0
    assert "OK:" in capsys.readouterr().out


def test_a_missing_id_is_printed_with_its_hint_and_exits_nonzero(tmp_path, capsys):
    _export(tmp_path, "InternalCommunicationActivities.csv", (OTHER_CHANNEL, "1", "A"))
    ids = _ids(tmp_path, LIVE)

    exit_code = check_tracking_ids.main(["--ids", str(ids), "--input", str(tmp_path)])

    assert exit_code == 1
    out = capsys.readouterr().out
    assert LIVE in out
    assert "channel" in out.lower()


def test_the_found_ids_stay_a_number_until_all_is_asked_for(tmp_path, capsys):
    """The list is something the reader already has; the missing rows are not."""
    _export(tmp_path, "InternalCommunicationActivities.csv", (LIVE, "1", "Quarterly report"))
    ids = _ids(tmp_path, LIVE)

    check_tracking_ids.main(["--ids", str(ids), "--input", str(tmp_path)])
    quiet = capsys.readouterr().out
    check_tracking_ids.main(["--ids", str(ids), "--input", str(tmp_path), "--all"])
    loud = capsys.readouterr().out

    assert "Quarterly report" not in quiet
    assert "Quarterly report" in loud


def test_a_repeat_in_the_list_is_named_rather_than_shown_twice(tmp_path, capsys):
    _export(tmp_path, "InternalCommunicationActivities.csv", (LIVE, "1", "A"))
    ids = _ids(tmp_path, LIVE, LIVE)

    assert check_tracking_ids.main(["--ids", str(ids), "--input", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "Searched" in out
    assert "listed more than once" in out


def test_an_empty_list_is_an_error_not_a_pass(tmp_path, capsys):
    _export(tmp_path, "InternalCommunicationActivities.csv", (LIVE, "1", "A"))
    ids = _ids(tmp_path, "# nothing but a heading")

    assert check_tracking_ids.main(["--ids", str(ids), "--input", str(tmp_path)]) == 1
    assert "no tracking IDs" in capsys.readouterr().out


def test_a_missing_id_file_says_which_one(tmp_path, capsys):
    _export(tmp_path, "InternalCommunicationActivities.csv", (LIVE, "1", "A"))
    absent = tmp_path / "nope.txt"

    assert check_tracking_ids.main(["--ids", str(absent), "--input", str(tmp_path)]) == 1
    assert "nope.txt" in capsys.readouterr().out


def test_a_folder_without_an_activity_export_says_so(tmp_path, capsys):
    ids = _ids(tmp_path, LIVE)

    assert check_tracking_ids.main(["--ids", str(ids), "--input", str(tmp_path)]) == 1
    assert "no activity export found" in capsys.readouterr().out
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_check_tracking_ids.py -v`
Expected: FAIL — `AttributeError: ... has no attribute 'main'`

- [ ] **Step 3: Write the result model, the report and main**

Append to `pipeline/scripts/check_tracking_ids.py`:

```python
@dataclass(frozen=True)
class Result:
    """One listed ID, and what the export had to say about it."""

    listed: str
    entry: Entry | None
    hint: str
    times_listed: int

    @property
    def status(self) -> str:
        return "found" if self.entry else "missing"


def check(listed: list[str], counts: Counter, index: dict[str, Entry]) -> list[Result]:
    """Each listed ID against the index, in the order the list gave them."""
    results = []
    for value in listed:
        key = normalise(value)
        entry = index.get(key)
        results.append(
            Result(
                listed=value,
                entry=entry,
                hint="" if entry else find_hint(key, index),
                times_listed=counts[key],
            )
        )
    return results


def report(results: list[Result], show_all: bool) -> None:
    """The three numbers, then the rows that need doing something about."""
    missing = [r for r in results if r.entry is None]
    found = [r for r in results if r.entry is not None]

    print_kv([
        ("Searched", len(results)),
        ("Found", len(found)),
        ("Missing", len(missing)),
    ])
    print()

    repeated = [r for r in results if r.times_listed > 1]
    if repeated:
        log(f"{len(repeated)} ID(s) listed more than once; each was searched once")

    if missing:
        print_table(
            "Missing",
            ["Tracking ID", "Why it may be missing"],
            [(r.listed, r.hint or "nothing close in the export") for r in missing],
            col_widths=[36, 62],
        )

    if show_all and found:
        print_table(
            "Found",
            ["Tracking ID", "Source", "SP ID", "Activity"],
            [(r.listed, r.entry.source, r.entry.sp_id, r.entry.activity_name) for r in found],
            col_widths=[36, 20, 9, 42],
        )

    if missing:
        log(f"{len(missing)} of {len(results)} ID(s) are not in the export.")
    else:
        log(f"OK: all {len(results)} ID(s) are in the export.")
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--ids",
        type=Path,
        required=True,
        help="text file listing the tracking IDs, one per line",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="read the CSVs from this folder instead of the usual OneDrive/local discovery",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="also list the IDs that were found, not only the count",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=None,
        help="also write the full result to this CSV",
    )
    args = parser.parse_args(argv)

    print_banner("CPLAN tracking-ID check")

    if not args.ids.is_file():
        log(f"ERROR: no such ID list: {args.ids}")
        print()
        return 1

    listed, counts = read_id_list(args.ids)
    if not listed:
        log(f"ERROR: no tracking IDs in {args.ids.name} -- only blank or commented lines.")
        print()
        return 1
    print_kv([("ID list", str(args.ids)), ("IDs to search", len(listed))])
    print()

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
    if not any(key in files for key, _ in ACTIVITY_SOURCES):
        log("ERROR: no activity export found.")
        print_kv([("Input dir", str(input_dir))])
        print()
        return 1

    index = build_index(files)
    print()
    results = check(listed, counts, index)
    report(results, args.all)

    return 0 if all(r.entry for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_check_tracking_ids.py -v`
Expected: PASS (20 tests)

- [ ] **Step 5: Commit**

```bash
git add pipeline/scripts/check_tracking_ids.py tests/test_check_tracking_ids.py
git commit -m "Report the misses, count the hits"
```

---

### Task 5: The result CSV

**Files:**
- Modify: `pipeline/scripts/check_tracking_ids.py`
- Modify: `tests/test_check_tracking_ids.py`

**Interfaces:**
- Consumes: `Result` (Task 4).
- Produces: `write_csv(path: Path, results: list[Result]) -> None`, called from `main()` when `--csv` is given.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_check_tracking_ids.py`:

```python
def test_the_csv_carries_found_and_missing_rows_without_all(tmp_path, capsys):
    """A file is read by a spreadsheet, not by a person -- --all does not gate it."""
    _export(tmp_path, "InternalCommunicationActivities.csv", (LIVE, "1", "Quarterly report"))
    ids = _ids(tmp_path, LIVE, ARCHIVED)
    out_csv = tmp_path / "result.csv"

    exit_code = check_tracking_ids.main(
        ["--ids", str(ids), "--input", str(tmp_path), "--csv", str(out_csv)]
    )

    assert exit_code == 1
    with open(out_csv, newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))

    assert [r["id"] for r in rows] == [LIVE, ARCHIVED]
    assert rows[0]["status"] == "found"
    assert rows[0]["source_file"] == "internal"
    assert rows[0]["sp_id"] == "1"
    assert rows[0]["activity_name"] == "Quarterly report"
    assert rows[0]["hint"] == ""
    assert rows[1]["status"] == "missing"
    assert rows[1]["source_file"] == ""
    assert rows[1]["activity_name"] == ""


def test_the_csv_path_is_named_in_the_report(tmp_path, capsys):
    _export(tmp_path, "InternalCommunicationActivities.csv", (LIVE, "1", "A"))
    ids = _ids(tmp_path, LIVE)
    out_csv = tmp_path / "result.csv"

    check_tracking_ids.main(["--ids", str(ids), "--input", str(tmp_path), "--csv", str(out_csv)])

    assert "result.csv" in capsys.readouterr().out
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_check_tracking_ids.py -v`
Expected: FAIL — `FileNotFoundError` on `result.csv`. `--csv` is already in the parser from Task 4, and nothing acts on it yet.

- [ ] **Step 3: Write the CSV writer and call it**

Append to `pipeline/scripts/check_tracking_ids.py`, before `main`:

```python
CSV_COLUMNS = ("id", "status", "source_file", "sp_id", "activity_name", "hint")


def write_csv(path: Path, results: list[Result]) -> None:
    """Every row, found and missing alike -- a file is read by a spreadsheet."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv_module.writer(handle)
        writer.writerow(CSV_COLUMNS)
        for result in results:
            entry = result.entry
            writer.writerow([
                result.listed,
                result.status,
                entry.source if entry else "",
                entry.sp_id if entry else "",
                entry.activity_name if entry else "",
                result.hint,
            ])
```

In `main()`, between `report(results, args.all)` and the `return`:

```python
    if args.csv is not None:
        write_csv(args.csv, results)
        log(f"Result written to {args.csv}")
        print()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_check_tracking_ids.py -v`
Expected: PASS (22 tests)

- [ ] **Step 5: Commit**

```bash
git add pipeline/scripts/check_tracking_ids.py tests/test_check_tracking_ids.py
git commit -m "Write the answer to a file the spreadsheet can open"
```

---

### Task 6: The launcher, the manifest and the README

**Files:**
- Create: `trackids.ps1`
- Create: `trackids.cmd`
- Modify: `check.ps1` (manifest, beside the `timezones.ps1` entries around line 147)
- Modify: `README.md` (a section after "Time-zone check", which ends before `### Standalone studio`)

**Interfaces:**
- Consumes: `python -m pipeline.scripts.check_tracking_ids` with `--ids`, `--input`, `--all`, `--csv`.
- Produces: nothing other code imports.

- [ ] **Step 1: Write `trackids.ps1`**

```powershell
<#
CPLAN tracking-ID check - are the IDs on this list actually in the export?

Takes a text file of tracking IDs, one per line, and says which of them the
source activity CSVs contain. A match is exact; an ID that does not match is
reported with the nearest thing found - the same activity on another channel,
the pack it should have been in, or an ID one character away - because "never
created" and "spelled wrong" lead somewhere completely different.

Read-only. Touches nothing but the CSVs it reads, and the -Csv file if asked.

Usage (from the repo root, or just double-click trackids.cmd):
  .\trackids.ps1 -Ids ".\ids.txt"
  .\trackids.ps1 -Ids ".\ids.txt" -All            # also list the ones that were found
  .\trackids.ps1 -Ids ".\ids.txt" -Csv ".\result.csv"
  .\trackids.ps1 -Ids ".\ids.txt" -InputDir "C:\path\to\Input"

Exit code 0 only when every listed ID was found.
#>
param(
    [Parameter(Mandatory = $true)][string]$Ids,
    [string]$InputDir,
    [string]$Csv,
    [switch]$All
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
# Same resolution order as the other launchers: CPLAN_PYTHON override, then an
# active venv, then a repo-local .venv.
function Resolve-CplanPython {
    if ($env:CPLAN_PYTHON -and (Test-Path $env:CPLAN_PYTHON)) { return $env:CPLAN_PYTHON }
    if ($env:VIRTUAL_ENV) {
        $p = Join-Path $env:VIRTUAL_ENV "Scripts\python.exe"
        if (Test-Path $p) { return $p }
    }
    $p = Join-Path $root ".venv\Scripts\python.exe"
    if (Test-Path $p) { return $p }
    return $null
}

$python = Resolve-CplanPython
if (-not $python) {
    Write-Host "No Python environment found for CPLAN." -ForegroundColor Red
    Write-Host "Point the launcher at your existing venv once, then open a NEW window:" -ForegroundColor Yellow
    Write-Host '  setx CPLAN_PYTHON "C:\path\to\your\venv\Scripts\python.exe"'
    exit 1
}
Write-Host "Using Python: $python" -ForegroundColor DarkGray

# Resolved before the Push-Location, so a relative path means what the caller
# meant by it - the folder they typed it in, not the repository root.
$idsPath = [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $Ids))
if ($Csv) { $csvPath = [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $Csv)) }

Push-Location $root
$env:PYTHONPATH = "."
try {
    $args = @("-m", "pipeline.scripts.check_tracking_ids", "--ids", $idsPath)
    if ($InputDir) { $args += @("--input", $InputDir) }
    if ($csvPath) { $args += @("--csv", $csvPath) }
    if ($All) { $args += "--all" }

    & $python @args
    $code = $LASTEXITCODE

    if ($code -eq 0) {
        Write-Host "Every ID on the list is in the export." -ForegroundColor Green
    }
    else {
        # Not thrown: the check did its job, and the report above is the answer.
        Write-Host "Read the report above - some IDs were not found." -ForegroundColor Yellow
    }
    exit $code
}
finally {
    Pop-Location
}
```

- [ ] **Step 2: Write `trackids.cmd`**

```bat
@echo off
REM Double-clickable tracking-ID check: reads a text file of tracking IDs and
REM says which of them the source activity CSVs actually contain, naming a
REM near-miss for each one it cannot find. Pass the list with -Ids.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0trackids.ps1" %*
echo.
pause
```

- [ ] **Step 3: Add the manifest entries**

In `check.ps1`, immediately after the two `timezones.ps1` entries (around line 148), keeping the column alignment of the surrounding block:

```powershell
    @{ Path = "pipeline\scripts\check_tracking_ids.py"; Marker = "def find_hint";            Why = "says why a listed ID is missing - without it a wrong channel suffix and a never-created activity read identically" },
    @{ Path = "pipeline\scripts\check_tracking_ids.py"; Marker = "ACTIVITY_SOURCES";         Why = "searches the four activity exports and only those - an older copy can report a pack ID as a found activity" },
    @{ Path = "trackids.ps1";                  Marker = "check_tracking_ids";                Why = "the launcher for that check - double-clickable via trackids.cmd" },
    @{ Path = "trackids.ps1";                  Marker = "GetFullPath";                       Why = "-Ids is resolved against the caller's folder; without it a relative list path is looked for in the repository root and reads as a missing file" },
```

- [ ] **Step 4: Run the manifest test**

Run: `python -m pytest tests/test_check_manifest.py -v`
Expected: PASS — every entry names a file that exists and contains its marker.

- [ ] **Step 5: Add the README section**

In `README.md`, after the time-zone check section (the paragraph ending "…would carry that mistake into the database.") and before `### Standalone studio (read-only)`:

````markdown
### Tracking-ID check (are these IDs real?)

```bash
# Which of the IDs in this list are actually in the export
python -m pipeline.scripts.check_tracking_ids --ids ids.txt

# ...and list the ones that were found too, and keep the result as a CSV
python -m pipeline.scripts.check_tracking_ids --ids ids.txt --all --csv result.csv
```

Tracking IDs travel by hand — in a mail, on a slide, pasted out of a planning
sheet — and the question asked of them is whether the activities behind them
exist at all. This takes the list (one ID per line; blank lines and `#` lines
are ignored), reads the four activity exports the pipeline itself reads, and
reports the ones it could not find. On Windows, `trackids.cmd`.

A match is exact. The work is in the misses: an unfound ID is reported with the
nearest thing in the export — the same activity on another channel, the pack it
should have belonged to, or an ID one character away — because "never created"
and "spelled wrong" lead somewhere completely different. The hint is never a
verdict; the row still reads missing.

Only the activity exports are searched, live and archived. The pack, channel
and cluster exports carry their own identifiers, and searching them would let a
pack ID report as a found activity. Exit code 0 only when every listed ID was
found.
````

- [ ] **Step 6: Run the full test suite**

Run: `python -m pytest tests/test_check_tracking_ids.py tests/test_check_manifest.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

The commit guard in `.githooks` refuses staged content containing any term in
`forbidden-terms.txt`, so this step is the brand check. It needs that file to
exist locally — copy it from `forbidden-terms.txt.example` in a fresh clone or
worktree, otherwise the guard only checks paths and says so.

```bash
git add trackids.ps1 trackids.cmd check.ps1 README.md
git commit -m "Give the check a launcher, a manifest entry and a paragraph"
```

---

## Self-Review

**Spec coverage**

| Spec requirement | Task |
|---|---|
| Exact match, trimmed and upper-cased | 1 (`normalise`), 2 (index keying) |
| Near-miss ladder, rungs 1–3, first hit wins | 3 |
| Malformed ID named rather than silently falling through | 3 |
| Hint is never a verdict (row still `missing`) | 4 (`Result.status`) |
| `find_input_dir()`, four activity exports only | 2 (`ACTIVITY_SOURCES`), 4 (`main`) |
| `read_csv_auto()` + `transform()`, typo variant folded in | 2 |
| Header numbers, missing-only table, `--all` | 4 (`report`) |
| Duplicates looked up once, named in the header | 1 (counts), 4 (`report`) |
| `--csv` writes every row, six columns | 5 |
| Exit 0 only when all found; 1 for every error | 4 |
| `-Ids` required, `#`/blank lines ignored, Python resolution order | 1, 6 |
| Tests against self-written CSVs, no OneDrive | 1–5 |
| Reverse direction and DuckDB out of scope | not implemented, as specified |

**Placeholders:** none — every step carries the code it asks for.

**Type consistency:** `Entry(tracking_id, source, sp_id, activity_name)` is constructed in Task 2 and read in Tasks 3–5 under those names. `Result(listed, entry, hint, times_listed)` is constructed in Task 4 and read in Task 5. `find_hint(wanted, index)` and `build_index(files)` keep their Task 2/3 signatures at every call site. `find_input_files` is re-exported through the module's own namespace by the `from … import` in Task 1, which is what Task 2's tests call as `check_tracking_ids.find_input_files`.
