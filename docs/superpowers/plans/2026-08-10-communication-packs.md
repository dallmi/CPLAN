# Communication Packs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give a communication pack a row of its own in the agent pack, so the agent can name a pack, describe it, and see the ones nobody has planned against.

**Architecture:** Three independent moves. The pack's display name is already in the activity frame and only needs exporting. The pack list is then sourced through the transform that already exists for it, joined to the activities on a column chosen by measurement rather than by reasoning, and written as `07-packs.csv` with every pack in it including the empty ones. The texts follow.

**Tech Stack:** Python 3, pandas, pytest. `openpyxl` is on the workbook path only and is not needed by anything this plan adds.

**Spec:** `docs/superpowers/specs/2026-08-10-communication-packs-design.md`

## Global Constraints

- **The organisation's name must never enter a committed file** — not in code, comments, docs, test data or commit messages. `.githooks/pre-commit` reads the staged diff and refuses both forbidden terms and absolute local paths. Run `.githooks/pre-commit` before every commit in this plan.
- **No absolute paths in committed files.** Use relative paths or a variable.
- **English** for code, comments and docs.
- **Test command,** from the repository root: `PYTHONPATH=. .venv/bin/python -m pytest <path> -q`
- **`agent_builder.INSTRUCTIONS_TEXT` must stay ≤ 8000 characters with ≥ 200 to spare** (`test_the_prompt_still_has_its_margin`). It stands at 7,764, so 36 characters are genuinely free.
- **The upload folder must stay ≤ `KNOWLEDGE_SOURCE_LIMIT` (20) files.** It stands at 11 and becomes 12.
- **An absent optional input never fails a run.** The `geb-members` rule: no pack export means no pack file and a run otherwise identical to today's.
- **`MIN_LINK_RATE = 0.8`** — the floor both the diagnostic and the load path hold the join to.
- Data files in the pack are numbered `00`–`07`; rule documents follow at `08` and up.

---

### Task 1: Export the pack name the activity rows already carry

`communication_pack` is mapped in `COLUMN_MAP` and lookup-parsed like every other reference field. It has been in the frame the whole time and was never written out, so `05-activities.csv` shows `CP-100` and nothing else. This task depends on no other task and can ship alone.

**Files:**
- Modify: `pipeline/report/table_sheets.py` (`ACTIVITY_COLUMNS`, around line 630)
- Test: `tests/test_agent_pack.py`

**Interfaces:**
- Consumes: nothing
- Produces: `05-activities.csv` gains a `Pack` column immediately before `Pack ID`. The workbook's Activities sheet gains the same column, since both read `ACTIVITY_COLUMNS`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_agent_pack.py`, beside the other activity-row tests:

```python
def test_the_activities_file_names_the_pack_it_only_numbered(tmp_path):
    """A bare identifier is not something a reader can ask about.

    `communication_pack` has been in the frame all along -- mapped in
    `COLUMN_MAP`, lookup-parsed like every other reference field -- and was
    simply never exported. An agent handed `CP-100` can group by pack but
    cannot say which pack it grouped, and no question a planner actually
    asks is phrased in identifiers.
    """
    pack_dir, _, _, _ = _pack(tmp_path)
    with (pack_dir / agent_pack.ACTIVITIES_CSV_NAME).open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    assert "Pack" in rows[0], "the activities file still carries only the identifier"
    packed = [row for row in rows if row["Pack ID"] == "CP-100"]
    assert packed, "the fixture's packed activities vanished"
    assert all(row["Pack"] == "Pack one" for row in packed)

    # The identifier stays. It is what `07-packs.csv` is joined on, and a
    # name is not unique the way a key is.
    assert "Pack ID" in rows[0]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_agent_pack.py::test_the_activities_file_names_the_pack_it_only_numbered -q`
Expected: FAIL — `AssertionError: the activities file still carries only the identifier`

- [ ] **Step 3: Add the column**

In `pipeline/report/table_sheets.py`, replace the single `communication_pack_cpid` entry in `ACTIVITY_COLUMNS` with:

```python
    # The name beside the number. `communication_pack` is mapped and
    # lookup-parsed exactly like every other reference field; it was simply
    # never exported, so the pack has always shown the identifier alone. A
    # reader asks about "Pack one", never about "CP-100". The identifier
    # stays because it is what `07-packs.csv` joins on, and because a pack
    # name is not unique the way a key is.
    ("communication_pack", "Pack"),
    ("communication_pack_cpid", "Pack ID"),
```

- [ ] **Step 4: Run the new test**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_agent_pack.py::test_the_activities_file_names_the_pack_it_only_numbered -q`
Expected: PASS

- [ ] **Step 5: Run every suite that reads these columns**

`ACTIVITY_COLUMNS` also drives the workbook's Activities sheet, so a column count asserted anywhere will move.

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_agent_pack.py tests/test_report_calendar_script.py tests/test_report_summary_sheet.py tests/test_agent_builder.py -q`
Expected: PASS. If a test asserts a column count or a header list, update it to include `Pack` — the column is intended, the assertion is stale.

- [ ] **Step 6: Commit**

```bash
.githooks/pre-commit
git add pipeline/report/table_sheets.py tests/test_agent_pack.py
git commit -m "Name the pack the activity rows have only numbered"
```

---

### Task 2: A pack fixture, and the diagnostic's column inventory

The pack export's columns are mapped by `PACKS_COLUMN_MAP`, which carries none of the identity fields the pack form is documented to have. Before anything joins, the diagnostic says which columns the ETL does not yet see.

**Files:**
- Modify: `tests/report_fixtures.py`
- Create: `pipeline/scripts/check_pack_link.py`
- Create: `tests/test_check_pack_link.py`

**Interfaces:**
- Consumes: `process_cplan.find_input_dir`, `find_input_files`, `read_csv_auto`, `log`, `print_banner`, `print_kv`, `print_table`, `decode_sp_column_name`, `PACKS_COLUMN_MAP`
- Produces:
  - `report_fixtures.PACK_HEADER`, `PACK_ROWS`, `write_pack_csv(directory) -> Path`
  - `check_pack_link.unmapped_columns(raw_columns) -> list[tuple[str, str, str]]` returning `(raw, decoded, "mapped"|"unmapped")` per column
  - `check_pack_link.main(argv=None) -> int`

- [ ] **Step 1: Write the fixture**

Add to `tests/report_fixtures.py`, after `EXTERNAL_ARCHIVE_ROWS`:

```python
# The pack export, in the source's own column names. `LTID` is what the pack
# list calls its identifier -- the name is why `campaign_ltid` is a candidate
# link column and why the choice has to be measured rather than assumed.
PACK_HEADER = [
    "LTID", "Name of communication pack", "Tracking cluster", "Category",
    "Business Division", "Region", "Campaign", "Lead Team", "Partner team",
    "Objective", "Start date", "End date", "Date of launch", "Brief",
    "Created", "Modified",
]


def _pack_row(cpid, name, **overrides):
    row = {
        "LTID": cpid, "Name of communication pack": name,
        "Tracking cluster": _lookup("QRREP"), "Category": "Campaign",
        "Business Division": _lookup("Division A"), "Region": _lookup("EMEA"),
        "Campaign": "Pack lead", "Lead Team": "Team", "Partner team": "",
        "Objective": _lookup("Objective"), "Start date": "2025-01-06",
        "End date": "2025-12-19", "Date of launch": "2025-02-03",
        "Brief": "<p>Synthetic pack description</p>",
        "Created": "2024-11-01", "Modified": "2025-06-01",
    }
    row.update(overrides)
    return row


PACK_ROWS = [
    _pack_row("CP-100", "Pack one"),
    # Nothing in the activity fixture points here. This is the row the whole
    # file exists for: a pack with nothing planned against it.
    _pack_row("CP-200", "Pack with nothing planned"),
    # The same identifier twice, the older losing on Modified -- the way the
    # activity de-dup already resolves a repeated tracking ID.
    _pack_row("CP-100", "Stale pack one", **{"Modified": "2024-12-01"}),
]

# CP-100 and CP-200 survive the de-dup; the stale CP-100 loses.
FIXTURE_PACK_COUNT = 2


def write_pack_csv(directory):
    """Write the pack export and return its path.

    Separate from `write_activity_csvs` on purpose: a scope built without a
    pack list is the state every machine that syncs only the activity exports
    is in, and the tests have to be able to build it.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    return _write_csv(directory / "CommunicationPacks.csv", PACK_ROWS, PACK_HEADER)
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_check_pack_link.py`:

```python
"""The diagnostic that chooses the pack link, instead of assuming it.

Three activity columns could carry the pack identifier and the exports do not
say which one the pack list answers to. A wrong join does not look wrong --
it looks like a pack file with plausible numbers in it -- so the choice is
measured, and these tests hold the measurement honest.
"""

import pytest

pytest.importorskip("pandas")

from pipeline.scripts import check_pack_link
from tests.report_fixtures import PACK_HEADER, write_pack_csv, write_activity_csvs


def test_it_names_the_columns_the_etl_does_not_map():
    """The mapping carries none of the pack form's identity fields.

    An unmapped column is invisible twice over: absent from the harmonised
    frame, and absent from any error, because nothing asked for it. Listing
    them is what turns "the mapping is probably incomplete" into a decision
    someone can take.
    """
    rows = check_pack_link.unmapped_columns(PACK_HEADER)
    by_name = {raw: status for raw, _, status in rows}

    assert by_name["LTID"] == "mapped"
    assert by_name["Name of communication pack"] == "unmapped"
    assert by_name["Tracking cluster"] == "unmapped"
    assert by_name["Category"] == "unmapped"
    assert by_name["End date"] == "unmapped"


def test_every_export_column_is_accounted_for():
    """One row per column, so a column cannot be silently skipped."""
    rows = check_pack_link.unmapped_columns(PACK_HEADER)
    assert [raw for raw, _, _ in rows] == PACK_HEADER


def test_it_reports_when_there_is_no_pack_export(tmp_path, capsys):
    """A missing optional export is a message, not a traceback."""
    write_activity_csvs(tmp_path)
    assert check_pack_link.main(["--input", str(tmp_path)]) == 1
    assert "no pack export" in capsys.readouterr().out.lower()
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_check_pack_link.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.scripts.check_pack_link'`

- [ ] **Step 4: Write the script**

Create `pipeline/scripts/check_pack_link.py`:

```python
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
```

- [ ] **Step 5: Run the tests**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_check_pack_link.py tests/test_report_fixtures.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
.githooks/pre-commit
git add pipeline/scripts/check_pack_link.py tests/test_check_pack_link.py tests/report_fixtures.py
git commit -m "Ask the pack export which of its columns the pipeline cannot see"
```

---

### Task 3: Score the three candidate link columns

**Files:**
- Modify: `pipeline/scripts/check_pack_link.py`
- Modify: `tests/test_check_pack_link.py`
- Create: `packlink.ps1`, `packlink.cmd`

**Interfaces:**
- Consumes: Task 2's `unmapped_columns`; `process_cplan.load_activities`, `transform_packs`
- Produces: `check_pack_link.PACK_LINK_CANDIDATES`, `check_pack_link.MIN_LINK_RATE`, `check_pack_link.Score` (NamedTuple with `column`, `referenced`, `matched`, `packs_hit`, `orphan_activities`, `orphan_packs`, `samples`, and a `rate` property), `check_pack_link.score(frame, packs, column) -> Score`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_check_pack_link.py`:

```python
from pipeline.scripts.process_cplan import load_activities, transform_packs, read_csv_auto


def _frames(tmp_path):
    files = write_activity_csvs(tmp_path)
    packs = transform_packs(read_csv_auto(write_pack_csv(tmp_path)))
    return load_activities(files).frame, packs


def test_the_winning_candidate_is_the_one_that_matches(tmp_path):
    """The fixture links on `communication_pack_cpid` and on nothing else.

    Every activity but one carries `CP-100`; no activity carries a campaign
    LTID or a tracking pack id that a pack row answers to. A candidate that
    scores above zero on those would mean the scoring is matching something
    other than what it claims.
    """
    frame, packs = _frames(tmp_path)

    winner = check_pack_link.score(frame, packs, "communication_pack_cpid")
    assert winner.referenced > 0
    assert winner.matched == winner.referenced
    assert winner.rate == 1.0
    # CP-100 only. CP-200 is the pack nobody planned against.
    assert winner.packs_hit == 1
    assert winner.orphan_packs == 1

    for other in ("campaign_ltid", "tracking_pack_id"):
        assert check_pack_link.score(frame, packs, other).rate == 0.0


def test_an_activity_naming_no_pack_is_not_counted_against_the_rate(tmp_path):
    """`referenced` is the denominator, not the row count.

    One fixture activity carries no pack reference at all. Counting it as a
    miss would drag every candidate below the floor and report a linking
    problem where there is only an unplanned activity.
    """
    frame, packs = _frames(tmp_path)
    scored = check_pack_link.score(frame, packs, "communication_pack_cpid")
    assert scored.referenced < len(frame), "the fixture's unpacked row vanished"


def test_it_exits_non_zero_when_no_candidate_clears_the_floor(tmp_path, capsys):
    """A pack list that links to nothing is a finding, not a crash."""
    frame, packs = _frames(tmp_path)
    packs = packs.assign(cpid="NOTHING-MATCHES-THIS")
    scores = [check_pack_link.score(frame, packs, name)
              for name in check_pack_link.PACK_LINK_CANDIDATES]
    assert all(s.rate < check_pack_link.MIN_LINK_RATE for s in scores)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_check_pack_link.py -q`
Expected: FAIL — `AttributeError: module 'pipeline.scripts.check_pack_link' has no attribute 'score'`

- [ ] **Step 3: Add the scoring**

Add to `pipeline/scripts/check_pack_link.py`, above `main`:

```python
from typing import NamedTuple  # noqa: E402  (with the other imports)

# The three columns that could carry the pack identifier, in the order they
# are reported. Named here rather than in the report module because this is
# the tool that decides between them; `pipeline/report/packs.py` holds only
# the answer.
PACK_LINK_CANDIDATES = ("communication_pack_cpid", "campaign_ltid",
                        "tracking_pack_id")

# Below this a candidate is not a link. It is the same floor the load path
# warns against once a winner has been chosen.
MIN_LINK_RATE = 0.8

SAMPLE_COUNT = 3


class Score(NamedTuple):
    column: str
    referenced: int
    matched: int
    packs_hit: int
    orphan_activities: int
    orphan_packs: int
    samples: tuple

    @property
    def rate(self):
        """Matched over *referenced*, never over the row count.

        An activity that names no pack is not a failed link, it is an
        unplanned activity. Putting it in the denominator would report a
        linking problem where there is only an empty field.
        """
        return self.matched / self.referenced if self.referenced else 0.0


def _keys(series):
    """Non-empty values, trimmed and upper-cased, as a set."""
    if series is None:
        return set()
    values = set()
    for value in series:
        if value is None or value != value:
            continue
        text = str(value).strip().upper()
        if text and text != "NAN":
            values.add(text)
    return values


def score(frame, packs, column):
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
```

- [ ] **Step 4: Report the scores in `main`**

Replace the `return 0` at the end of `main` with:

```python
    from pipeline.scripts.process_cplan import load_activities, transform_packs

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
        ["Column", "Referenced", "Matched", "Rate", "Packs hit",
         "Orphan act.", "Orphan packs"],
        [(s.column, s.referenced, s.matched, f"{s.rate:.0%}", s.packs_hit,
          s.orphan_activities, s.orphan_packs) for s in scores],
        col_widths=[26, 11, 9, 7, 10, 12, 13])
    print()
    for scored in scores:
        log(f"{scored.column} sample values: "
            f"{', '.join(scored.samples) if scored.samples else '(none)'}")
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
```

And add the CSV writer beside `score`:

```python
SCORE_COLUMNS = ("column", "referenced", "matched", "rate", "packs_hit",
                 "orphan_activities", "orphan_packs")


def _write_scores(path, scores):
    import csv as csv_module

    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv_module.writer(handle)
        writer.writerow(SCORE_COLUMNS)
        for s in scores:
            writer.writerow([s.column, s.referenced, s.matched, f"{s.rate:.4f}",
                             s.packs_hit, s.orphan_activities, s.orphan_packs])
    log(f"Scores written to {path}")
```

- [ ] **Step 5: Run the tests**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_check_pack_link.py -q`
Expected: PASS

- [ ] **Step 6: Add the Windows entry points**

Create `packlink.cmd`:

```bat
@echo off
REM Double-clickable pack-link check: says which columns of the pack export the
REM pipeline cannot see, and which activity column actually links to the pack
REM list. Reads only; writes nothing but the optional -Csv.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0packlink.ps1" %*
echo.
pause
```

Create `packlink.ps1` by copying `trackids.ps1` and making exactly these changes: replace the comment header with the usage block from `check_pack_link.py`'s docstring; drop the `-Ids` parameter and every line that validates or forwards it, since this diagnostic takes no ID list; change the invoked module from `pipeline.scripts.check_tracking_ids` to `pipeline.scripts.check_pack_link`. Keep `-InputDir` and `-Csv` and the interpreter resolution unchanged.

- [ ] **Step 7: Verify the wrapper runs**

Run: `PYTHONPATH=. .venv/bin/python -m pipeline.scripts.check_pack_link --input pipeline/input`
Expected: exit 1 with "no pack export in the input folder" — `pipeline/input` is empty in a fresh checkout, and that is the message an operator should get.

- [ ] **Step 8: Commit**

```bash
.githooks/pre-commit
git add pipeline/scripts/check_pack_link.py tests/test_check_pack_link.py packlink.ps1 packlink.cmd
git commit -m "Measure which column links an activity to its pack"
```

---

### Task 4: Widen the pack column map

The diagnostic from Task 2 reports `Name of communication pack`, `Tracking cluster`, `Category` and `End date` as unmapped. Without them `07-packs.csv` cannot name a pack.

**Files:**
- Modify: `pipeline/scripts/process_cplan.py` (`PACKS_COLUMN_MAP` and the sets below it, around lines 914–943)
- Modify: `tests/test_check_pack_link.py`

**Interfaces:**
- Produces: the harmonised pack frame gains `pack_name`, `tracking_cluster`, `category`, `end_date`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_check_pack_link.py`:

```python
def test_the_map_now_covers_every_column_the_fixture_exports():
    """The fixture is the documented pack form. A column it carries and the
    map does not is a field the pack file cannot show.
    """
    unmapped = [raw for raw, _, status in check_pack_link.unmapped_columns(PACK_HEADER)
                if status == "unmapped"]
    assert unmapped == [], f"still unmapped: {unmapped}"


def test_the_harmonised_pack_frame_carries_the_identity_fields(tmp_path):
    packs = transform_packs(read_csv_auto(write_pack_csv(tmp_path)))
    for column in ("cpid", "pack_name", "tracking_cluster", "category", "end_date"):
        assert column in packs.columns, f"{column} is missing"
    assert set(packs["pack_name"]) >= {"Pack one", "Pack with nothing planned"}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_check_pack_link.py -q`
Expected: FAIL — `still unmapped: ['Name of communication pack', 'Tracking cluster', 'Category', 'End date']`

- [ ] **Step 3: Widen the map**

In `pipeline/scripts/process_cplan.py`, add to `PACKS_COLUMN_MAP`:

```python
    # The pack's own identity. Absent from this map until the pack list was
    # sourced as an entity rather than counted through the activities, which
    # is why a pack could be sized but never named.
    "Name of communication pack": "pack_name",
    "Tracking cluster":         "tracking_cluster",
    "Category":                 "category",
    "End date":                 "end_date",
```

and extend the sets below it:

```python
PACKS_LOOKUP_COLUMNS = {
    "business_division", "region", "lead", "lead_team",
    "strategic_objective", "communication_pack_lookup",
    "partner_team", "tracking_cluster",
}

PACKS_DATE_COLUMNS = {"start_date", "end_date", "launch_date", "created", "modified"}
```

- [ ] **Step 4: Run the tests**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_check_pack_link.py tests/test_process_cplan_load.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
.githooks/pre-commit
git add pipeline/scripts/process_cplan.py tests/test_check_pack_link.py
git commit -m "Map the pack columns that say what a pack is"
```

---

### Task 5: Load the pack export

**Files:**
- Modify: `pipeline/scripts/process_cplan.py` (beside `load_activities`, around line 1290)
- Modify: `tests/test_process_cplan_load.py`

**Interfaces:**
- Produces: `process_cplan.PACK_KEY = "packs"`, `process_cplan.PackLoad` (NamedTuple: `frame`, `raw_columns`, `path`, `duplicates_removed`), `process_cplan.load_packs(files) -> PackLoad | None`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_process_cplan_load.py`:

```python
def test_loading_packs_without_an_export_is_not_an_error(tmp_path):
    """The state every machine that syncs only the activity lists is in.

    A missing optional input returns None so callers can carry on, the same
    rule the GEB member list follows. Raising here would stop a run over a
    file most deployments will never have.
    """
    from pipeline.scripts.process_cplan import load_packs
    from tests.report_fixtures import write_activity_csvs

    assert load_packs(write_activity_csvs(tmp_path)) is None


def test_the_pack_load_de_duplicates_on_the_identifier(tmp_path):
    """Two rows for one pack, newest Modified winning -- the rule the
    activity load already applies to a repeated tracking ID.
    """
    from pipeline.scripts.process_cplan import find_input_files, load_packs
    from tests.report_fixtures import (FIXTURE_PACK_COUNT, write_activity_csvs,
                                       write_pack_csv)

    write_activity_csvs(tmp_path)
    write_pack_csv(tmp_path)
    load = load_packs(find_input_files(tmp_path))

    assert load is not None
    assert len(load.frame) == FIXTURE_PACK_COUNT
    assert load.duplicates_removed == 1
    surviving = load.frame.set_index("cpid")["pack_name"].to_dict()
    assert surviving["CP-100"] == "Pack one", "the stale row won the de-dup"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_process_cplan_load.py -k pack -q`
Expected: FAIL — `ImportError: cannot import name 'load_packs'`

- [ ] **Step 3: Implement the loader**

Add to `pipeline/scripts/process_cplan.py`, directly after `load_activities`:

```python
PACK_KEY = "packs"


class PackLoad(NamedTuple):
    """The harmonised pack list plus what it took to build it.

    `raw_columns` exists for `check_pack_link.py`, which reports which of them
    the map does not cover; the report path uses `frame` alone.
    """

    frame: "pd.DataFrame"
    raw_columns: list
    path: object
    duplicates_removed: int = 0


def load_packs(files):
    """Read and harmonise the pack export, or return None when there is none.

    None rather than an empty frame, and never an exception: a machine that
    syncs only the activity lists has no pack export, and that is a normal
    state rather than a fault. Every caller treats None as "no pack list" --
    the same rule the GEB member list follows, for the same reason.
    """
    path = files.get(PACK_KEY)
    if path is None:
        return None

    log(f"Reading {path.name}...")
    df = read_csv_auto(path)
    log(f"  packs: {len(df)} rows, {len(df.columns)} columns")
    raw_columns = [c.strip() for c in df.columns]
    df = transform_packs(df)

    # Same rule as the activity de-dup: the most recently modified row wins,
    # and the number dropped is reported rather than swallowed.
    dupes = 0
    if "cpid" in df.columns:
        before = len(df)
        if "modified" in df.columns:
            df = df.sort_values("modified", ascending=False, na_position="last")
        df = df.drop_duplicates(subset=["cpid"], keep="first").reset_index(drop=True)
        dupes = before - len(df)
        if dupes:
            log(f"  Removed {dupes} duplicate pack rows (by cpid)")

    return PackLoad(df, raw_columns, path, dupes)
```

- [ ] **Step 4: Run the tests**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_process_cplan_load.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
.githooks/pre-commit
git add pipeline/scripts/process_cplan.py tests/test_process_cplan_load.py
git commit -m "Load the pack export through the transform it already had"
```

---

### Task 6: Join the packs to the activities

**Files:**
- Create: `pipeline/report/packs.py`
- Create: `tests/test_report_packs.py`
- Modify: `pipeline/report/data.py` (`Scope`, `build_scope`)
- Modify: `pipeline/scripts/report_calendar.py` (`resolve_scope`)
- Modify: `tests/report_fixtures.py` (`load_fixture_scope`)

**Interfaces:**
- Consumes: Task 5's `load_packs`
- Produces:
  - `packs.PACK_LINK_COLUMN`, `packs.MIN_LINK_RATE`, `packs.LinkResult` (NamedTuple: `referenced`, `matched`, plus a `rate` property), `packs.link(frame, pack_frame) -> LinkResult`, `packs.mark(frame, pack_frame) -> DataFrame`, `packs.activity_counts(frame, pack_frame) -> dict[str, int]`
  - `Scope` gains `packs=None` (the harmonised pack frame or None), `pack_link=None` (a `LinkResult` or None), `pack_counts_all=None` (dict of cpid → activity count before filtering)
  - `build_scope(load, config, membership=None, pack_load=None)`
  - `load_fixture_scope(directory, config, membership=None, with_packs=False)`

- [ ] **Step 1: Write the failing test**

Create `tests/test_report_packs.py`:

```python
"""Linking an activity to its pack, and saying how well it linked."""

import pytest

pytest.importorskip("pandas")

import pandas as pd

from pipeline.report import packs


def _frame(*values):
    return pd.DataFrame({packs.PACK_LINK_COLUMN: list(values)})


def _packs(*ids):
    return pd.DataFrame({"cpid": list(ids), "pack_name": [f"Pack {i}" for i in ids]})


def test_an_activity_naming_no_pack_is_not_a_failed_link():
    """Three states, not two. An empty reference is an unplanned activity;
    a reference resolving to nothing is a broken one. Folding the first into
    the second would report a data problem that is not there.
    """
    marked = packs.mark(_frame("CP-1", "", None), _packs("CP-1"))
    assert list(marked["pack_known"]) == ["Yes", "", ""]


def test_a_reference_to_a_pack_that_is_not_in_the_list_says_so():
    marked = packs.mark(_frame("CP-1", "CP-9"), _packs("CP-1"))
    assert list(marked["pack_known"]) == ["Yes", "No"]


def test_the_rate_is_over_referenced_rows_only():
    result = packs.link(_frame("CP-1", "CP-9", ""), _packs("CP-1"))
    assert result.referenced == 2
    assert result.matched == 1
    assert result.rate == 0.5


def test_matching_ignores_case_and_padding():
    """The identifier travels through SharePoint lookups and CSV round-trips.
    A link that breaks on a trailing space is a link that breaks in
    production and nowhere else.
    """
    marked = packs.mark(_frame(" cp-1 "), _packs("CP-1"))
    assert list(marked["pack_known"]) == ["Yes"]


def test_no_pack_list_leaves_the_frame_alone():
    """No export means no column. An empty `pack_known` on every row would
    assert a check nobody ran.
    """
    marked = packs.mark(_frame("CP-1"), None)
    assert "pack_known" not in marked.columns


def test_activity_counts_are_per_pack_identifier():
    counts = packs.activity_counts(_frame("CP-1", "CP-1", "CP-2", ""), _packs("CP-1", "CP-2"))
    assert counts == {"CP-1": 2, "CP-2": 1}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_report_packs.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.report.packs'`

- [ ] **Step 3: Write the module**

Create `pipeline/report/packs.py`:

```python
"""Linking an activity to its communication pack, and saying how well it linked.

Which activity column carries the pack identifier is not obvious from the
exports: three are plausible, and picking one by reasoning would put an
unverified assumption under `07-packs.csv`, where a wrong join does not look
wrong. `pipeline/scripts/check_pack_link.py` measures all three against a real
export. This module holds the answer it produced and the rule that keeps it
honest -- a rate reported on every run, and a warning when it drops.
"""

from typing import NamedTuple

# Chosen by `pipeline/scripts/check_pack_link.py`. It is also the column
# `metrics.pack_stats` has always treated as pack identity, so this is the
# status quo made explicit rather than a new assumption.
#
# Re-run the diagnostic when the export changes shape, and change this line
# if it names a different winner.
PACK_LINK_COLUMN = "communication_pack_cpid"

# Below this the run says so rather than presenting a badly joined file as a
# clean one. The same floor `check_pack_link.py` exits non-zero on.
MIN_LINK_RATE = 0.8


class LinkResult(NamedTuple):
    referenced: int
    matched: int

    @property
    def rate(self):
        """Matched over *referenced*, never over the row count.

        An activity that names no pack is an unplanned activity, not a failed
        link. In the denominator it would report a linking problem where
        there is only an empty field.
        """
        return self.matched / self.referenced if self.referenced else 0.0


def key(value):
    """The comparable form of an identifier, or "" when there is none.

    Trimmed and upper-cased on both sides: the identifier travels through
    SharePoint lookups and CSV round-trips, and a link that breaks on a
    trailing space breaks in production and nowhere else.

    Public because `agent_pack` keys its per-pack counts the same way. Two
    modules deriving the same key by two spellings is how a join starts
    disagreeing with the count printed beside it.
    """
    if value is None or value != value:
        return ""
    text = str(value).strip().upper()
    return "" if text in ("", "NAN", "NAT") else text


def _pack_keys(pack_frame):
    if pack_frame is None or "cpid" not in getattr(pack_frame, "columns", []):
        return None
    return {key(value) for value in pack_frame["cpid"]} - {""}


def link(frame, pack_frame):
    """Count how many pack references resolve to a row in the pack list."""
    known = _pack_keys(pack_frame)
    if known is None or PACK_LINK_COLUMN not in frame.columns:
        return LinkResult(0, 0)
    referenced = matched = 0
    for value in frame[PACK_LINK_COLUMN]:
        identifier = key(value)
        if not identifier:
            continue
        referenced += 1
        if identifier in known:
            matched += 1
    return LinkResult(referenced, matched)


def mark(frame, pack_frame):
    """Add `pack_known` -- "Yes", "No", or "" where no pack is named.

    Three states rather than two. An empty reference and a reference to a
    pack that is not in the list are different facts, and the second is the
    data-quality finding; folding them together would hide it inside the
    ordinary business of activities that belong to no pack.

    Without a pack list the column is absent entirely, because an empty
    `pack_known` on every row would assert a check nobody ran.
    """
    known = _pack_keys(pack_frame)
    if known is None or PACK_LINK_COLUMN not in frame.columns:
        return frame
    frame = frame.copy()
    frame["pack_known"] = [
        "" if not key(value) else ("Yes" if key(value) in known else "No")
        for value in frame[PACK_LINK_COLUMN]
    ]
    return frame


def activity_counts(frame, pack_frame):
    """Activities per pack identifier, over the rows in `frame`.

    Keyed on the pack list's own identifiers so a count can be looked up
    while writing the pack rows. References that match no pack are not
    counted here -- `pack_known` is where those are reported.
    """
    known = _pack_keys(pack_frame)
    if known is None or PACK_LINK_COLUMN not in frame.columns:
        return {}
    by_key = {}
    for value in frame[PACK_LINK_COLUMN]:
        identifier = key(value)
        if identifier and identifier in known:
            by_key[identifier] = by_key.get(identifier, 0) + 1
    return {
        key(cpid): by_key.get(key(cpid), 0)
        for cpid in pack_frame["cpid"] if key(cpid)
    }
```

- [ ] **Step 4: Run the module tests**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_report_packs.py -q`
Expected: PASS

- [ ] **Step 5: Write the failing scope test**

Add to `tests/test_report_data.py`:

```python
def test_the_scope_carries_the_pack_list_and_the_link_rate(tmp_path):
    """The pack file needs the pre-filter counts, so the scope has to hold
    them: a pack showing zero in scope and zero overall is a different
    finding from one showing zero in scope and forty overall.
    """
    from tests.report_fixtures import load_fixture_scope

    config = ReportConfig(date_from=date(2025, 1, 1), date_to=date(2025, 12, 31))
    scope = load_fixture_scope(tmp_path / "csv", config, with_packs=True)

    assert scope.packs is not None
    assert scope.pack_link.rate == 1.0
    assert scope.pack_counts_all["CP-100"] > 0
    assert scope.pack_counts_all["CP-200"] == 0
    assert "pack_known" in scope.frame.columns


def test_a_scope_without_a_pack_export_is_unchanged(tmp_path):
    """Today's output, exactly, on a machine that has no pack list."""
    from tests.report_fixtures import load_fixture_scope

    config = ReportConfig(date_from=date(2025, 1, 1), date_to=date(2025, 12, 31))
    scope = load_fixture_scope(tmp_path / "csv", config)

    assert scope.packs is None
    assert scope.pack_link is None
    assert "pack_known" not in scope.frame.columns
```

- [ ] **Step 6: Run it to verify it fails**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_report_data.py -k pack -q`
Expected: FAIL — `TypeError: load_fixture_scope() got an unexpected keyword argument 'with_packs'`

- [ ] **Step 7: Widen the scope**

In `pipeline/report/data.py`, add to the `Scope` dataclass, after `unmatched_members`:

```python
    # None when no pack export was supplied -- the state every machine that
    # syncs only the activity lists is in, and the one that must still render
    # today's pack.
    packs: object = None
    pack_link: object = None
    # Activities per pack *before* the filters, so a pack showing zero in
    # scope can say whether it has zero overall. Those read very differently
    # to a planner and one number cannot carry both.
    pack_counts_all: object = None
```

Change the signature and the two return sites:

```python
def build_scope(load, config, membership=None, pack_load=None):
    frame = load.frame
    rows_read = len(frame)
    excluded = {key: 0 for key in EXCLUSION_ORDER}
    pack_frame = pack_load.frame if pack_load is not None else None
    # Counted on the unfiltered frame, before any filter has run.
    pack_counts_all = (packs_module.activity_counts(frame, pack_frame)
                       if pack_frame is not None else None)
```

Import at the top of `data.py`, beside the others:

```python
from pipeline.report import packs as packs_module
```

Pass the new fields into both `Scope(...)` constructions — the early empty-frame return and the final one — as:

```python
                     packs=pack_frame,
                     pack_link=(packs_module.link(frame, pack_frame)
                                if pack_frame is not None else None),
                     pack_counts_all=pack_counts_all,
```

and immediately before the final `Scope(...)` is built, mark the filtered frame:

```python
    frame = packs_module.mark(frame, pack_frame)
```

- [ ] **Step 8: Wire the fixture and the real caller**

In `tests/report_fixtures.py`, replace `load_fixture_scope`:

```python
def load_fixture_scope(directory, config, membership=None, with_packs=False):
    from pipeline.report.data import build_scope
    from pipeline.scripts.process_cplan import find_input_files, load_activities, load_packs

    files = write_activity_csvs(directory)
    pack_load = None
    if with_packs:
        write_pack_csv(directory)
        pack_load = load_packs(find_input_files(directory))
    return build_scope(load_activities(files), config, membership, pack_load)
```

In `tests/test_agent_pack.py`, `_scope` forwards every keyword to `ReportConfig`, so `with_packs=True` would reach the dataclass and raise. Split it out — later tasks depend on this:

```python
def _scope(tmp_path, with_packs=False, **overrides):
    config = _config(**overrides)
    return load_fixture_scope(tmp_path / "csv", config,
                              with_packs=with_packs), config
```

In `pipeline/scripts/report_calendar.py`, add `load_packs` to the `process_cplan` import list, and in `resolve_scope` replace the `build_scope` call with:

```python
    pack_load = load_packs(files)
    if pack_load is None:
        log("No pack export found; pack rows and pack_known are omitted")
    else:
        log(f"Pack list: {len(pack_load.frame)} packs from {pack_load.path.name}")

    scope = build_scope(load, config, members, pack_load)
    if scope.pack_link is not None and scope.pack_link.referenced:
        rate = scope.pack_link.rate
        log(f"Pack link: {scope.pack_link.matched} of {scope.pack_link.referenced} "
            f"references resolved ({rate:.0%})")
        if rate < packs_module.MIN_LINK_RATE:
            log(f"  WARNING: below the {packs_module.MIN_LINK_RATE:.0%} floor. "
                "Re-run packlink.ps1 -- the link column may have changed.")
```

with `from pipeline.report import packs as packs_module` added to its imports.

- [ ] **Step 9: Run the tests**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_report_packs.py tests/test_report_data.py tests/test_report_calendar_script.py tests/test_agent_pack.py -q`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
.githooks/pre-commit
git add pipeline/report/packs.py pipeline/report/data.py pipeline/scripts/report_calendar.py tests/test_report_packs.py tests/test_report_data.py tests/report_fixtures.py
git commit -m "Join the pack list to the activities, and report how well it joined"
```

---

### Task 7: Write `07-packs.csv`

**Files:**
- Modify: `pipeline/report/agent_pack.py` (constants near line 112, `pack_rows` beside `activity_rows`, `write_pack`)
- Modify: `tests/test_agent_pack.py` (including the file-list assertion at line 1235)

**Interfaces:**
- Consumes: `Scope.packs`, `Scope.pack_counts_all`, `packs.activity_counts`
- Produces: `agent_pack.PACKS_CSV_NAME = "07-packs.csv"`, `agent_pack.PACKS_HEADER`, `agent_pack.pack_rows(scope, report_config=None) -> list[list]`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_agent_pack.py`:

```python
def _packs_file(pack_dir):
    with (pack_dir / agent_pack.PACKS_CSV_NAME).open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_the_pack_file_holds_the_pack_nobody_planned_against(tmp_path):
    """The row the file exists for.

    A pack with no activity has nothing to be counted through, so before this
    file it was not merely undescribed -- it was absent. "Which packs have
    nothing planned" is the question that only a row per pack can answer.
    """
    scope, config = _scope(tmp_path, with_packs=True)
    pack_dir = agent_pack.write_pack(scope, agent_pack.pack_config(config),
                                     tmp_path / "out")
    rows = {row["Pack ID"]: row for row in _packs_file(pack_dir)}

    assert set(rows) == {"CP-100", "CP-200"}
    assert rows["CP-200"]["Pack"] == "Pack with nothing planned"
    assert rows["CP-200"]["activities_in_scope"] == "0"
    assert rows["CP-200"]["activities_total"] == "0"
    assert int(rows["CP-100"]["activities_in_scope"]) > 0


def test_the_two_activity_counts_are_not_the_same_number(tmp_path):
    """A pack with nothing this period reads differently from a pack with
    nothing at all, and one column cannot carry both.
    """
    scope, config = _scope(tmp_path, with_packs=True,
                           date_from=date(2025, 1, 1), date_to=date(2025, 3, 31))
    pack_dir = agent_pack.write_pack(scope, agent_pack.pack_config(config),
                                     tmp_path / "out")
    row = {r["Pack ID"]: r for r in _packs_file(pack_dir)}["CP-100"]
    assert int(row["activities_total"]) > int(row["activities_in_scope"])


def test_without_a_pack_export_the_file_is_not_written(tmp_path):
    """A missing optional input leaves today's pack exactly as it was."""
    pack_dir, _, _, _ = _pack(tmp_path)
    assert not (pack_dir / agent_pack.PACKS_CSV_NAME).exists()
```

Then update the file-list assertion at line 1235 so the packed case expects the new file. Leave the no-pack-export case listing `00`–`06` only.

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_agent_pack.py -k pack_file -q`
Expected: FAIL — `AttributeError: module 'pipeline.report.agent_pack' has no attribute 'PACKS_CSV_NAME'`

- [ ] **Step 3: Add the constants**

In `pipeline/report/agent_pack.py`, add `packs as packs_module` to the existing `from pipeline.report import ...` line — `packs.py` imports only `typing`, so there is no cycle — then add beside the other file-name constants:

```python
PACKS_CSV_NAME = "07-packs.csv"

PACKS_HEADER = ("Pack ID", "Pack", "Cluster", "Category", "Lead", "Lead team",
                "Partner team", "Divisions", "Regions", "Objective",
                "Start", "End", "Launch", "Description",
                "activities_in_scope", "activities_total", "in_report")

# The pack frame's column behind each header above, in the same order. Two
# are computed rather than read and are handled at the call site.
PACK_FIELDS = ("cpid", "pack_name", "tracking_cluster", "category", "lead",
               "lead_team", "partner_team", "business_division", "region",
               "strategic_objective", "start_date", "end_date", "launch_date",
               "short_description")
```

- [ ] **Step 4: Write `pack_rows`**

Add beside `activity_rows`:

```python
def pack_rows(scope, report_config=None):
    """One row per pack in the list, including the ones with nothing planned.

    Every pack, not only those an activity points at. A pack that holds no
    activity has nothing to be counted through, so before this file it was
    absent rather than merely undescribed -- and "which packs have nothing
    planned" is the first question a planner asks of a pack list.

    `activities_in_scope` is the figure to quote. `activities_total` says
    whether a zero means "nothing this period" or "nothing at all", which
    read very differently and cannot share one column. `in_report` follows
    the activity rows: the pack is in the report when any of its activities
    survives the workbook's own filters.
    """
    if scope.packs is None:
        return []

    in_scope = packs_module.activity_counts(scope.frame, scope.packs)
    overall = scope.pack_counts_all or {}

    reported = set()
    if report_config is not None and packs_module.PACK_LINK_COLUMN in scope.frame.columns:
        for _, activity in scope.frame.iterrows():
            if not report_exclusion(activity, report_config):
                identifier = packs_module.key(
                    activity.get(packs_module.PACK_LINK_COLUMN))
                if identifier:
                    reported.add(identifier)

    rows = []
    for _, pack in scope.packs.iterrows():
        identifier = packs_module.key(pack.get("cpid"))
        values = []
        for field in PACK_FIELDS:
            value = pack.get(field)
            if field in ("start_date", "end_date", "launch_date"):
                values.append(value.date().isoformat()
                              if hasattr(value, "date") and value == value else "")
            else:
                values.append("" if value is None or value != value else value)
        values.append(in_scope.get(identifier, 0))
        values.append(overall.get(identifier, 0))
        if report_config is not None:
            values.append("Yes" if identifier in reported else "No")
        else:
            values.append("")
        rows.append(values)
    return rows
```

- [ ] **Step 5: Write the file**

In `write_pack`, after the `BREAKDOWN_NAME` write:

```python
    # Only when there is a list. An empty pack file would assert that the
    # organisation has no packs, which is a much stronger claim than "this
    # machine does not sync the pack export".
    if scope.packs is not None:
        _write_csv(pack_dir / PACKS_CSV_NAME, PACKS_HEADER,
                   pack_rows(scope, report_config))
```

- [ ] **Step 6: Run the tests**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_agent_pack.py -q`
Expected: PASS. The skill-archive test will also need `PACKS_CSV_NAME` in its expected member list — add it; the archive is built from `pack_dir`, so the file travels automatically.

- [ ] **Step 7: Commit**

```bash
.githooks/pre-commit
git add pipeline/report/agent_pack.py tests/test_agent_pack.py
git commit -m "Give every pack a row, including the ones with nothing planned"
```

---

### Task 8: Renumber the rule documents and upload the pack file

**Files:**
- Modify: `pipeline/report/agent_builder.py` (lines 34–35, 45–61, 94–101)
- Modify: `tests/test_agent_builder.py`

**Interfaces:**
- Produces: `READING_GUIDE_NAME = "08-reading-guide.txt"`, `CHART_STANDARDS_NAME = "09-chart-standards.txt"`, boards at `10`–`12`, `UPLOAD_DATA_FILES` gaining `agent_pack.PACKS_CSV_NAME`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_agent_builder.py`:

This module has no `_config` helper — it builds the config inline in `_builder`. Add a pack-carrying sibling beside `_builder`, then the test:

```python
def _builder_with_packs(tmp_path):
    """`_builder`, on a run that has the pack export too."""
    config = ReportConfig(date_from=date(2025, 1, 1), date_to=date(2025, 12, 31))
    scope = load_fixture_scope(tmp_path / "csv", config, with_packs=True)
    pack_dir = agent_pack.write_pack(scope, config, tmp_path / "pack-out")
    out_dir = tmp_path / "builder-out"
    upload_dir = agent_builder.write_builder_pack(pack_dir, out_dir, scope, config)
    return pack_dir, upload_dir, out_dir


def test_the_upload_folder_carries_the_pack_file_in_reading_order(tmp_path):
    """Data files first, rules behind them. An operator uploads a folder, and
    a folder that sorts into reading order is one fewer thing to explain.
    """
    _, upload_dir, _ = _builder_with_packs(tmp_path)

    names = sorted(p.name for p in upload_dir.iterdir())
    assert agent_pack.PACKS_CSV_NAME in names
    assert names.index("07-packs.csv") < names.index("08-reading-guide.txt")
    assert len(names) <= agent_builder.KNOWLEDGE_SOURCE_LIMIT


def test_a_run_without_the_pack_export_still_delivers(tmp_path):
    """The copy step runs one stage after the run that tolerated the missing
    input. Turning it into a crash there would undo the tolerance.
    """
    _, upload_dir, _ = _builder(tmp_path)
    names = [p.name for p in upload_dir.iterdir()]
    assert agent_pack.PACKS_CSV_NAME not in names
    assert "08-reading-guide.txt" in names
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_agent_builder.py -k reading_order -q`
Expected: FAIL — `07-packs.csv` not in the upload folder

- [ ] **Step 3: Renumber and add**

In `pipeline/report/agent_builder.py`:

```python
READING_GUIDE_NAME = "08-reading-guide.txt"
CHART_STANDARDS_NAME = "09-chart-standards.txt"
```

```python
BOARD_FILE_NAMES = {
    "board-head-of-communications-overview.md":
        "10-board-head-of-communications-overview.txt",
    "board-leadership-attention.md": "11-board-leadership-attention.txt",
    "board-plan-trust.md": "12-board-plan-trust.txt",
}
```

```python
UPLOAD_DATA_FILES = (
    agent_pack.SUMMARY_NAME,
    agent_pack.GLOSSARY_NAME,
    agent_pack.QUALITY_NAME,
    agent_pack.CALENDAR_NAME,
    agent_pack.ACTIVITIES_CSV_NAME,
    agent_pack.BREAKDOWN_NAME,
    agent_pack.PACKS_CSV_NAME,
)
```

- [ ] **Step 4: Make the copy tolerate an absent pack file**

In `write_builder_pack`, replace the copy loop:

```python
    for name in UPLOAD_DATA_FILES:
        source = pack_dir / name
        # The pack file is absent when no pack export was synced. Copying it
        # unconditionally would turn a missing optional input into a crash in
        # the delivery step, one stage after the run that tolerated it.
        if source.exists():
            shutil.copyfile(source, upload_dir / name)
```

- [ ] **Step 5: Run the tests**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_agent_builder.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
.githooks/pre-commit
git add pipeline/report/agent_builder.py tests/test_agent_builder.py
git commit -m "Seat the pack file with the data, and move the rules behind it"
```

---

### Task 9: Report pack coverage, and correct the glossary

**Files:**
- Modify: `pipeline/report/agent_pack.py` (`_summary_sections`, the PACK COVERAGE block around line 613)
- Modify: `pipeline/report/table_sheets.py` (the `Packs` glossary entry, around line 469)
- Modify: `tests/test_agent_pack.py`

- [ ] **Step 1: Write the failing test**

```python
def test_the_summary_separates_packs_in_the_list_from_packs_seen(tmp_path):
    """Two numbers that look alike and are not.

    "Distinct packs" counts identifiers seen on activities; "Packs in the
    list" counts rows in the export. They differ by exactly the packs nobody
    has planned against -- which is the figure this whole change exists to
    produce, so both stay and the labels say which is which.
    """
    scope, config = _scope(tmp_path, with_packs=True)
    pack_dir = agent_pack.write_pack(scope, agent_pack.pack_config(config),
                                     tmp_path / "out")
    pairs = _summary_pairs((pack_dir / agent_pack.SUMMARY_NAME).read_text(encoding="utf-8"))

    assert pairs["Packs in the list"] == "2"
    assert pairs["Packs with no activity in scope"] == "1"
    assert pairs["Activities whose pack is not in the list"] == "0"


def test_the_summary_omits_the_pack_list_figures_without_a_list(tmp_path):
    pack_dir, _, _, _ = _pack(tmp_path)
    text = (pack_dir / agent_pack.SUMMARY_NAME).read_text(encoding="utf-8")
    assert "Packs in the list" not in text
    assert "PACK COVERAGE" in text, "the activity-derived figures still belong"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_agent_pack.py -k summary_separates -q`
Expected: FAIL — `KeyError: 'Packs in the list'`

- [ ] **Step 3: Extend the summary block**

In `agent_pack.py`, after the existing PACK COVERAGE loop:

```python
    if scope.packs is not None:
        counts = scope.pack_counts_all or {}
        empty = sum(1 for _, pack in scope.packs.iterrows()
                    if not in_scope_counts.get(packs_module.key(pack.get("cpid")), 0))
        unmatched = int((scope.frame.get("pack_known") == "No").sum()) \
            if "pack_known" in scope.frame.columns else 0
        lines.append(f"  Packs in the list | {len(scope.packs)}")
        lines.append(f"  Packs with no activity in scope | {empty}")
        lines.append(f"  Activities whose pack is not in the list | {unmatched}")
```

with `in_scope_counts = packs_module.activity_counts(scope.frame, scope.packs)` computed just above it, and `from pipeline.report import packs as packs_module` added to the module's imports.

- [ ] **Step 4: Correct the glossary**

In `pipeline/report/table_sheets.py`, replace the `Packs` entry. The wording stays surface-neutral because this glossary is shared with the workbook, which has no `07-packs.csv`:

```python
        # Says what a pack is. The old wording ("Not used as a grouping
        # dimension") described a limitation that the pack file removed, and
        # a definition that describes the tool rather than the thing goes
        # stale the moment the tool changes.
        ("Packs", "A communications pack: activities grouped around one "
                  "communication objective, with its own lead and period."),
```

- [ ] **Step 5: Run the tests**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_agent_pack.py tests/test_report_summary_sheet.py tests/test_report_quality_sheet.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
.githooks/pre-commit
git add pipeline/report/agent_pack.py pipeline/report/table_sheets.py tests/test_agent_pack.py
git commit -m "Count the packs in the list, not only the ones an activity named"
```

---

### Task 10: Tell the agent the file exists

A knowledge file cannot announce itself. The substance goes in the reading guide, which has no limit; the instructions get a pointer and have to pay for it.

**Files:**
- Modify: `pipeline/report/agent_builder.py` (`READING_GUIDE_TEXT`, `INSTRUCTIONS_TEXT`)
- Modify: `pipeline/report/agent_pack.py` (`SKILL_TEXT`)
- Modify: `tests/test_agent_builder.py`

- [ ] **Step 1: Write the failing test**

```python
def test_the_prompt_tells_the_agent_the_pack_file_exists():
    """Retrieval answers a question; it does not say which questions have a
    file waiting. The pointer is the only thing that does.
    """
    assert agent_pack.PACKS_CSV_NAME in agent_builder.INSTRUCTIONS_TEXT


def test_the_reading_guide_says_how_the_two_files_join():
    """The cost of not copying the pack's lead onto the activity row is that
    the agent has to be told where to look instead.
    """
    text = agent_builder.READING_GUIDE_TEXT
    assert agent_pack.PACKS_CSV_NAME in text
    assert "Pack ID" in text
    assert "nothing planned" in text.lower()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_agent_builder.py -k "pack_file_exists or two_files_join" -q`
Expected: FAIL on both

- [ ] **Step 3: Extend the reading guide**

Add a section to `READING_GUIDE_TEXT`, after "How to work through an analysis":

```
## Packs

A communication pack groups activities around one objective, with its own
lead, period and brief. `07-packs.csv` has one row per pack.

It holds every pack, including those with no activity in the period. A pack
showing `activities_in_scope = 0` is an answer -- nothing is planned against
it -- and not a defect. Check `activities_total` before calling it dormant:
zero in scope with a positive total means nothing *this period*.

To go from an activity to its pack, match the activity's `Pack ID` to the
pack row's `Pack ID`. The pack's lead, dates and objective are in that row
and nowhere else; the activity row carries the pack's name and identifier
only. `pack_known = No` on an activity means its pack is not in the list,
which is a data-quality finding worth reporting when it is common.
```

- [ ] **Step 4: Add the pointer, and pay for it**

In `INSTRUCTIONS_TEXT`'s file list, after the `BREAKDOWN_NAME` line:

```
- `{agent_pack.PACKS_CSV_NAME}` — one row per pack, including packs with nothing planned
```

The board line's numbers move from `` `09`–`11` `` to `` `10`–`12` `` — same length, no cost.

- [ ] **Step 5: Run the length test and read the overflow**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_agent_builder.py::test_the_prompt_still_has_its_margin -q`
Expected: FAIL, reporting the exact shortfall. The pointer costs about 74 characters against 36 free.

- [ ] **Step 6: Take the cut**

Shorten rule 2's illustration, which is example text rather than a rule:

```
"74 activities in Q3, 22% of all recorded" — not "Q3 was very active".
```

If the test still fails, shorten the pointer to:

```
- `{agent_pack.PACKS_CSV_NAME}` — one row per pack, empty ones included
```

Do not cut the three board names — `test_the_prompt_is_what_tells_the_agent_boards_exist` requires them verbatim.

- [ ] **Step 7: Mirror it in the Studio skill**

`agent_pack.SKILL_TEXT` has no character limit and takes the fuller wording. Add to its file list, after the breakdowns line:

```
- `{PACKS_CSV_NAME}` — one row per communication pack: name, lead, period, objective, and how many activities sit in it. Every pack is here, including those with nothing planned against them (`activities_in_scope = 0`), which is the only place that fact appears. Join it to `{ACTIVITIES_CSV_NAME}` on `Pack ID`.
```

The two surfaces differing in length here is deliberate and already has precedent in `agent_builder.INSTRUCTIONS_TEXT`, which says less than its Studio counterpart for a reason about the surface.

- [ ] **Step 8: Run everything**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests -q`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
.githooks/pre-commit
git add pipeline/report/agent_builder.py pipeline/report/agent_pack.py tests/test_agent_builder.py
git commit -m "Point the agent at the pack file, and say how to read it"
```

---

## Before merging

The link column is set to `communication_pack_cpid` because that is what `metrics.pack_stats` has always treated as pack identity — the status quo made explicit, not a new assumption. It has not been measured against a real export, because no export exists on a development machine.

Run the diagnostic on a machine that syncs the real folder:

```
.\packlink.ps1
```

Then:

1. If the reported winner is `communication_pack_cpid` at or above 80%, replace the comment above `PACK_LINK_COLUMN` in `pipeline/report/packs.py` with the measured rate and the date of the export.
2. If a different candidate wins, change `PACK_LINK_COLUMN` to it and re-run the full suite.
3. If no candidate clears 80%, stop and report it. The exports do not link, and that finding belongs in front of a person before any pack file is delivered.
4. If the column inventory lists columns beyond the four added in Task 4, add them to `PACKS_COLUMN_MAP` and decide per column whether it belongs in `PACKS_HEADER`.
