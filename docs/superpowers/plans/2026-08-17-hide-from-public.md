# Hide From Public Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Carry the source's "Hide from public" flag into the pipeline, exclude the rows it marks from every consumer, and state how many were excluded wherever a total is reported.

**Architecture:** `transform()` gains the column and normalises it to a real boolean but removes nothing. A separate `exclude_hidden()` drops the rows and the marker column together and returns the count, called explicitly by each consumer so no caller inherits the exclusion by accident. The count rides the same rails `duplicates_removed` already uses — `ActivityLoad` → `Scope` → `metrics.anomalies()` — which is what puts it in the Executive Summary and the agent pack without new plumbing.

**Tech Stack:** Python 3, pandas, openpyxl, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-17-hide-from-public-design.md`

## Global Constraints

- The organisation's name never enters the repository — not in code, identifiers, comments, docs, tests, commit messages or branch names. Use "public", "hidden", "excluded", "the organisation". The pre-commit hook in `.githooks/` reads the ignored `forbidden-terms.txt` and refuses staged content carrying a term; if it fires, reword — never bypass it, and never write the term into a file in order to search for it.
- No absolute local paths in committed files. They carry directory names that name the organisation.
- The marker column `hide_from_public` must not appear in any artefact leaving the ETL. `exclude_hidden()` drops it with the rows.
- The unset state arrives as `FALSE` **and** as an empty cell. Both mean not hidden. All four activity exports carry the column.
- Fail closed: a value that is neither a known-unset form nor a known-true form counts as hidden.
- Every surface that reports a total reports the exclusion count beside it. A total without its count is an incomplete task.
- The count is reported at total level only — never per cell, per filter, per week or per region.
- Run `.venv/bin/python -m pytest tests/ -q` before each commit; the suite is ~65s.

---

### Task 1: Map the column and normalise it to a boolean

Nothing is excluded yet. After this task the frame carries one new column and every existing behaviour is unchanged.

**Files:**
- Modify: `pipeline/scripts/process_cplan.py` (COLUMN_MAP near line 481; new helper beside `strip_control_chars`; normalisation inside `transform()` after the rename)
- Test: `tests/test_process_cplan_load.py`

**Interfaces:**
- Consumes: nothing
- Produces: `process_cplan.HIDE_COLUMN` (str, `"hide_from_public"`), `process_cplan.is_hidden_value(value) -> bool`, and a `hide_from_public` boolean column on every frame `transform()` returns for an activity export

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_process_cplan_load.py
import pandas as pd
import pytest

from pipeline.scripts import process_cplan


def _activity_csv(**overrides):
    """One activity row as the export writes it, SharePoint-encoded headers and all."""
    row = {
        "ID": "101",
        "Tracking ID": "QRREP-0000058-240709-0000060-EMI",
        "Title": "Quarterly report mail",
        "Hide_x0020_from_x0020_public_x0020_view": "FALSE",
    }
    row.update(overrides)
    return pd.DataFrame([row])


def test_the_encoded_hide_header_becomes_the_hide_column():
    frame = process_cplan.transform(_activity_csv(), source_type="internal")

    assert process_cplan.HIDE_COLUMN in frame.columns


def test_a_ticked_box_reads_as_hidden():
    frame = process_cplan.transform(
        _activity_csv(**{"Hide_x0020_from_x0020_public_x0020_view": "TRUE"}),
        source_type="internal",
    )

    assert frame[process_cplan.HIDE_COLUMN].tolist() == [True]


@pytest.mark.parametrize("unset", ["FALSE", "False", "false", "0", "", "   ", None])
def test_every_form_of_not_ticked_reads_as_not_hidden(unset):
    """The export writes FALSE on some rows and leaves others empty. Both occur."""
    frame = process_cplan.transform(
        _activity_csv(**{"Hide_x0020_from_x0020_public_x0020_view": unset}),
        source_type="internal",
    )

    assert frame[process_cplan.HIDE_COLUMN].tolist() == [False]


def test_a_value_nobody_anticipated_counts_as_hidden():
    """Fail closed. An unrecognised value is not a licence to publish."""
    assert process_cplan.is_hidden_value("Restricted") is True
    assert process_cplan.is_hidden_value("?") is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_process_cplan_load.py -q -k "hide or hidden or ticked or anticipated"`
Expected: FAIL with `AttributeError: module 'pipeline.scripts.process_cplan' has no attribute 'HIDE_COLUMN'`

- [ ] **Step 3: Add the mapping**

In `COLUMN_MAP` (`pipeline/scripts/process_cplan.py`, near line 504, beside the other activity fields):

```python
    # The source's own "do not circulate" flag, and the only thing in the
    # export that says an activity is not for general circulation. Matched on
    # the prefix rather than in full: the encoded header reads
    # `Hide_x0020_from_x0020_public_x00...` and decodes to "Hide from public"
    # followed by a SharePoint suffix, so the exact internal name is neither
    # known nor needed -- rule 4 of the matcher below is `decoded.startswith`.
    "Hide from public":         "hide_from_public",
```

- [ ] **Step 4: Add the normaliser**

Beside `strip_control_chars` in the same file:

```python
HIDE_COLUMN = "hide_from_public"

# What the export writes when the box was never ticked. Both forms occur in the
# real exports -- some rows carry FALSE, others are empty -- and a parser that
# handled only one of them would work on most rows and pass the rest straight
# through.
_NOT_HIDDEN = {"", "false", "0", "no", "n", "nan", "none", "nat"}


def is_hidden_value(value):
    """True when this cell means "hide from public".

    Unrecognised values count as hidden. The alternative fails open: a value
    nobody anticipated -- a renamed choice, a localised Yes, a stray note --
    would publish the row it was meant to hold back, and that is the one error
    here that cannot be taken back once an export has left the machine.
    """
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    try:
        if pd.isna(value):
            return False
    except (TypeError, ValueError):
        pass
    return str(value).strip().lower() not in _NOT_HIDDEN
```

- [ ] **Step 5: Normalise inside `transform()`**

In `transform()`, immediately after the `strip_control_chars` loop and before the HTML stripping:

```python
    # To a real boolean before anything reads it, so no consumer has to know
    # what the export writes for "no" -- and so `exclude_hidden` can be a
    # plain mask rather than a second parser that might disagree with this one.
    if HIDE_COLUMN in df.columns:
        df[HIDE_COLUMN] = df[HIDE_COLUMN].map(is_hidden_value)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_process_cplan_load.py -q`
Expected: PASS

- [ ] **Step 7: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS. This task adds a column and removes nothing; a failure here means an existing test asserts an exact column list, and that test's expectation needs the new column added to it.

- [ ] **Step 8: Commit**

```bash
git add pipeline/scripts/process_cplan.py tests/test_process_cplan_load.py
git commit -m "Carry the source's hide-from-public flag into the frame"
```

---

### Task 2: `exclude_hidden()` — drop the rows and the marker together

Still no call sites. A pure function with its own tests.

**Files:**
- Modify: `pipeline/scripts/process_cplan.py` (beside `load_activities`)
- Test: `tests/test_process_cplan_load.py`

**Interfaces:**
- Consumes: `process_cplan.HIDE_COLUMN` from Task 1
- Produces: `process_cplan.exclude_hidden(frame, source_name) -> tuple[pd.DataFrame, int]` and `process_cplan.HiddenColumnMissing` (a `ValueError` subclass)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_process_cplan_load.py
def _frame(*hidden_flags):
    return pd.DataFrame({
        "tracking_id": [f"QRREP-0000058-240709-000006{i}-EMI" for i in range(len(hidden_flags))],
        process_cplan.HIDE_COLUMN: list(hidden_flags),
    })


def test_hidden_rows_are_dropped_and_counted():
    frame, excluded = process_cplan.exclude_hidden(_frame(False, True, False, True), "internal")

    assert len(frame) == 2
    assert excluded == 2


def test_the_marker_leaves_with_the_rows_it_marked():
    """A hide_from_public column in an output would be a map of the interesting rows."""
    frame, _ = process_cplan.exclude_hidden(_frame(False, True), "internal")

    assert process_cplan.HIDE_COLUMN not in frame.columns


def test_a_frame_with_nothing_hidden_keeps_every_row():
    frame, excluded = process_cplan.exclude_hidden(_frame(False, False), "internal")

    assert len(frame) == 2
    assert excluded == 0


def test_the_index_is_reset_so_later_positional_work_is_safe():
    frame, _ = process_cplan.exclude_hidden(_frame(True, False), "internal")

    assert frame.index.tolist() == [0]


def test_an_export_without_the_column_stops_the_run_and_names_the_file():
    """Both silent answers are wrong: publish everything, or report nothing."""
    bare = pd.DataFrame({"tracking_id": ["QRREP-0000058-240709-0000060-EMI"]})

    with pytest.raises(process_cplan.HiddenColumnMissing) as error:
        process_cplan.exclude_hidden(bare, "InternalCommunicationActivities.csv")

    assert "InternalCommunicationActivities.csv" in str(error.value)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_process_cplan_load.py -q -k "hidden_rows or marker_leaves or nothing_hidden or index_is_reset or without_the_column"`
Expected: FAIL with `AttributeError: module 'pipeline.scripts.process_cplan' has no attribute 'exclude_hidden'`

- [ ] **Step 3: Write the implementation**

```python
class HiddenColumnMissing(ValueError):
    """An activity export arrived without the hide-from-public column.

    Neither silent answer is acceptable. Treating every row as public leaks
    exactly what this exists to prevent; treating every row as hidden produces
    an empty result that reads like a real one. All four exports carry the
    column today, so this fires only when an export changes shape -- which is
    precisely when someone needs to be told rather than guessed at.
    """


def exclude_hidden(frame, source_name):
    """The frame without its hidden rows, and how many there were.

    The marker column leaves with the rows it marked: a `hide_from_public`
    column in any artefact would be a map of the interesting rows, which is
    worse than never having filtered.

    Separate from `transform()` on purpose. `transform()` has three callers,
    and the tracking-ID check is one of them -- it must keep hidden rows in
    order to answer "does this ID exist" with something other than "never
    created". Excluding here rather than there means every caller states its
    own choice, and the callers that do not exclude are found by looking
    rather than by remembering.
    """
    if HIDE_COLUMN not in frame.columns:
        raise HiddenColumnMissing(
            f"{source_name}: no '{HIDE_COLUMN}' column -- the export changed shape. "
            f"Refusing to guess whether these rows may be published."
        )
    hidden = frame[HIDE_COLUMN].fillna(False).astype(bool)
    kept = frame.loc[~hidden].drop(columns=[HIDE_COLUMN]).reset_index(drop=True)
    return kept, int(hidden.sum())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_process_cplan_load.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pipeline/scripts/process_cplan.py tests/test_process_cplan_load.py
git commit -m "Add the step that drops hidden rows and the marker with them"
```

---

### Task 3: Apply it in `load_activities`, and carry the counts

`load_activities` is shared by the ETL and the calendar report "so the two can never disagree about how many activities exist" (its own docstring). Applying the exclusion there is what makes that guarantee hold for this rule too.

**Files:**
- Modify: `pipeline/scripts/process_cplan.py:1313-1365` (`ActivityLoad`, `load_activities`)
- Test: `tests/test_process_cplan_load.py`

**Interfaces:**
- Consumes: `exclude_hidden` from Task 2
- Produces: `ActivityLoad.hidden_excluded` (int, total) and `ActivityLoad.hidden_by_file` (tuple of `(key, count)` pairs, per export)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_process_cplan_load.py
def _export_csv(tmp_path, name, *rows):
    """One activity export. Each row is (tracking_id, title, hide_value)."""
    import csv
    path = tmp_path / name
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["ID", "Tracking ID", "Title",
                         "Hide_x0020_from_x0020_public_x0020_view"])
        for index, (tracking_id, title, hide) in enumerate(rows, start=1):
            writer.writerow([str(index), tracking_id, title, hide])
    return path


def test_hidden_activities_never_reach_the_combined_frame(tmp_path):
    _export_csv(
        tmp_path, "InternalCommunicationActivities.csv",
        ("QRREP-0000058-240709-0000060-EMI", "Quarterly report mail", "FALSE"),
        ("QRREP-0000058-240709-0000061-EMI", "Board briefing", "TRUE"),
    )
    files = process_cplan.find_input_files(tmp_path)

    load = process_cplan.load_activities(files)

    assert load.frame["tracking_id"].tolist() == ["QRREP-0000058-240709-0000060-EMI"]
    assert "Board briefing" not in load.frame["activity_name"].tolist()


def test_the_load_says_how_many_it_excluded_and_from_where(tmp_path):
    _export_csv(
        tmp_path, "InternalCommunicationActivities.csv",
        ("QRREP-0000058-240709-0000060-EMI", "A", "FALSE"),
        ("QRREP-0000058-240709-0000061-EMI", "B", "TRUE"),
    )
    _export_csv(
        tmp_path, "ExternalCommunicationActivities.csv",
        ("PRESS-0000012-240301-0000004-EXT", "C", "TRUE"),
    )
    files = process_cplan.find_input_files(tmp_path)

    load = process_cplan.load_activities(files)

    assert load.hidden_excluded == 2
    assert dict(load.hidden_by_file) == {"internal": 1, "external": 1}


def test_the_marker_column_is_not_in_the_loaded_frame(tmp_path):
    _export_csv(tmp_path, "InternalCommunicationActivities.csv",
                ("QRREP-0000058-240709-0000060-EMI", "A", "FALSE"))
    files = process_cplan.find_input_files(tmp_path)

    load = process_cplan.load_activities(files)

    assert process_cplan.HIDE_COLUMN not in load.frame.columns
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_process_cplan_load.py -q -k "never_reach or how_many_it_excluded or marker_column_is_not"`
Expected: FAIL with `AttributeError: 'ActivityLoad' object has no attribute 'hidden_excluded'`

- [ ] **Step 3: Extend `ActivityLoad`**

Replace lines 1313-1323 of `pipeline/scripts/process_cplan.py`:

```python
class ActivityLoad(NamedTuple):
    """The merged activity dataset plus what it took to build it.

    `raw_columns` and `files` exist for the ETL's --preview column comparison;
    the calendar report uses `frame` and `duplicates_removed`.

    `hidden_excluded` is not bookkeeping. Excluding rows makes every count in
    every consumer smaller than reality, and the only thing separating that
    from a wrong answer is a number saying how much smaller and why. It travels
    with the frame so no consumer has to recompute it from data that no longer
    contains the rows.
    """

    frame: "pd.DataFrame"
    raw_columns: dict
    files: dict
    duplicates_removed: int = 0
    hidden_excluded: int = 0
    hidden_by_file: tuple = ()
```

- [ ] **Step 4: Apply the exclusion in `load_activities`**

In the per-file loop (around line 1341), replace the two lines after `df = transform(...)`:

```python
        df = transform(df, source_type=source_type)
        df, excluded = exclude_hidden(df, path.name)
        if excluded:
            log(f"  {key}: {excluded} row(s) excluded (hide from public)")
            hidden_by_file.append((key, excluded))
        df["is_archived"] = is_archived
        frames.append(df)
```

Declare `hidden_by_file = []` beside `frames = []` at the top of the function, and pass the totals into both `ActivityLoad(...)` returns:

```python
    if not frames:
        return ActivityLoad(pd.DataFrame(), raw_columns, activity_files, 0,
                            hidden_excluded=0, hidden_by_file=())
```

```python
    hidden_total = sum(count for _key, count in hidden_by_file)
    if hidden_total:
        log(f"Excluded {hidden_total} hidden activity/activities across {len(hidden_by_file)} file(s)")
    return ActivityLoad(combined, raw_columns, activity_files, dupes,
                        hidden_excluded=hidden_total,
                        hidden_by_file=tuple(hidden_by_file))
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_process_cplan_load.py -q`
Expected: PASS

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS. Existing fixtures build activity CSVs without the hide column, and `exclude_hidden` now raises on those. Every fixture that feeds `load_activities` needs the column added with `FALSE` — that is the intended blast radius of the hard error, and fixing the fixtures is part of this task, not a workaround for it.

- [ ] **Step 7: Commit**

```bash
git add pipeline/scripts/process_cplan.py tests/
git commit -m "Exclude hidden activities where the ETL and the report agree on the count"
```

---

### Task 4: The ETL's own summary — `meta.json` and the closing table

**Files:**
- Modify: `pipeline/scripts/process_cplan.py:1507-1540` (final summary block)
- Test: `tests/test_process_cplan_load.py`

**Interfaces:**
- Consumes: `ActivityLoad.hidden_excluded`, `ActivityLoad.hidden_by_file` from Task 3
- Produces: `meta.json` key `"excluded_counts"` — an object keyed by export name, e.g. `{"internal": 1, "external": 1}` — and `"excluded_total"` (int)

The meta dict is built inline inside a thirty-line summary block, which is not
reachable without running the whole ETL. Extract it into a function first — a
pure dict-builder is testable in a millisecond, and the extraction is the
smaller half of this task.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_process_cplan_load.py
from datetime import datetime

import pandas as pd

from pipeline.scripts import process_cplan


def _load(hidden_by_file=(), hidden_excluded=0):
    return process_cplan.ActivityLoad(
        frame=pd.DataFrame(), raw_columns={}, files={},
        duplicates_removed=0,
        hidden_excluded=hidden_excluded,
        hidden_by_file=hidden_by_file,
    )


def test_meta_states_what_was_excluded_and_from_where():
    """The dashboard already reads meta.json for its refresh stamp."""
    meta = process_cplan.build_meta(
        load=_load(hidden_by_file=(("internal", 1), ("external", 1)), hidden_excluded=2),
        now=datetime(2026, 8, 17, 9, 30),
        full_refresh=True,
        row_counts={"communications": 410},
    )

    assert meta["excluded_total"] == 2
    assert meta["excluded_counts"] == {"internal": 1, "external": 1}


def test_meta_keeps_the_keys_the_dashboard_already_reads():
    """Extraction must not change the contract -- index.html parses this file."""
    meta = process_cplan.build_meta(
        load=_load(), now=datetime(2026, 8, 17, 9, 30),
        full_refresh=False, row_counts={"communications": 410},
    )

    assert meta["generated_at"] == "2026-08-17 09:30"
    assert meta["generated_at_iso"] == "2026-08-17T09:30:00"
    assert meta["mode"] == "incremental"
    assert meta["row_counts"] == {"communications": 410}


def test_a_run_that_excluded_nothing_still_states_the_zero():
    """An absent key reads as "old pipeline"; a zero reads as "nothing hidden"."""
    meta = process_cplan.build_meta(
        load=_load(), now=datetime(2026, 8, 17, 9, 30),
        full_refresh=True, row_counts={},
    )

    assert meta["excluded_total"] == 0
    assert meta["excluded_counts"] == {}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_process_cplan_load.py -q -k "meta_states or meta_keeps or excluded_nothing"`
Expected: FAIL with `AttributeError: module 'pipeline.scripts.process_cplan' has no attribute 'build_meta'`

- [ ] **Step 3: Extract the builder and add the counts**

Add above `main()` in `pipeline/scripts/process_cplan.py`:

```python
def build_meta(load, now, full_refresh, row_counts):
    """The contents of meta.json.

    A function rather than a dict literal buried in the summary block, because
    `index.html` parses this and the exclusion count is now part of what it has
    to be able to say. The zero is written explicitly: a consumer that sees no
    key cannot tell "nothing was hidden" from "written by a pipeline that did
    not yet know about hiding", and those are different facts.
    """
    return {
        "generated_at": now.strftime("%Y-%m-%d %H:%M"),
        "generated_at_iso": now.isoformat(timespec="seconds"),
        "mode": "full" if full_refresh else "incremental",
        "row_counts": row_counts,
        # Beside row_counts on purpose: a consumer reading one without the
        # other reports a total it cannot explain.
        "excluded_total": int(load.hidden_excluded),
        "excluded_counts": dict(load.hidden_by_file),
    }
```

Then replace the inline dict in the summary block (around line 1526) with:

```python
        meta = build_meta(load, now, full_refresh, row_counts)
```

If the `ActivityLoad` is not bound in that scope under the name `load`, use whatever name it has there; do not re-read the exports to recover it.

- [ ] **Step 4: Add the line to the closing table**

Immediately before `log("Done.")`:

```python
        if load.hidden_excluded:
            log(f"{load.hidden_excluded} activity/activities excluded (hide from public) "
                f"and absent from every output above.")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_process_cplan_load.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add pipeline/scripts/process_cplan.py tests/test_process_cplan_load.py
git commit -m "Say in meta.json and on the way out how many rows were excluded"
```

---

### Task 5: The count reaches the report and the agent pack through `anomalies()`

`duplicates_removed` already travels `ActivityLoad` → `Scope` → `metrics.anomalies()` → both `table_sheets.build_executive_summary` (`table_sheets.py:198`) and the agent pack's anomalies block (`agent_pack.py:852`). This rides the same rails; no new plumbing.

**Files:**
- Modify: `pipeline/report/data.py:40-52` (`Scope`), `:181`, `:345` (both constructions)
- Modify: `pipeline/report/metrics.py:130-170` (`anomalies`)
- Test: `tests/test_report_metrics.py`

**Interfaces:**
- Consumes: `ActivityLoad.hidden_excluded` from Task 3
- Produces: `Scope.hidden_excluded` (int, default 0) and a new row from `metrics.anomalies()`: `("Hidden activities excluded on load", int)`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_report_metrics.py
def test_the_anomalies_block_names_the_excluded_activities():
    """A total the reader cannot explain is worse than no total."""
    frame = pd.DataFrame({"tracking_id": ["QRREP-0000058-240709-0000060-EMI"]})

    rows = dict(metrics.anomalies(frame, duplicates_removed=0, hidden_excluded=3))

    assert rows["Hidden activities excluded on load"] == 3
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_report_metrics.py -q -k "excluded_activities"`
Expected: FAIL with `TypeError: anomalies() got an unexpected keyword argument 'hidden_excluded'`

- [ ] **Step 3: Add the row**

In `pipeline/report/metrics.py`, change the signature and the returned list:

```python
def anomalies(frame, duplicates_removed=0, hidden_excluded=0):
```

and add, after the `"Duplicate tracking IDs removed on load"` entry:

```python
        # Counted at load, like the duplicates above and for the same reason:
        # these rows are not in `frame`, so counting them against it would be a
        # tautological zero. Unlike the duplicates, their absence changes every
        # other number on this sheet, which is why it is named here rather than
        # left for the reader to notice.
        ("Hidden activities excluded on load", int(hidden_excluded)),
```

- [ ] **Step 4: Thread it through `Scope`**

In `pipeline/report/data.py`, add to the `Scope` dataclass beside `duplicates_removed` (note: `Scope.excluded` already exists and means the report's own period/region filtering — do not reuse that name):

```python
    hidden_excluded: int = 0
```

and add `hidden_excluded=load.hidden_excluded,` to **both** `Scope(...)` constructions (lines ~181 and ~345), beside the existing `duplicates_removed=load.duplicates_removed,`.

- [ ] **Step 5: Pass it at both call sites**

`pipeline/report/table_sheets.py:198`:

```python
                                          metrics.anomalies(frame, scope.duplicates_removed,
                                                            scope.hidden_excluded)])
```

`pipeline/report/agent_pack.py:852`:

```python
    for label, count in metrics.anomalies(scope.frame, scope.duplicates_removed,
                                          scope.hidden_excluded):
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_report_metrics.py tests/test_report_style.py tests/test_agent_pack.py -q`
Expected: PASS. A golden-file test asserting the exact anomalies rows will fail; add the new row to its expectation.

- [ ] **Step 7: Run the full suite and commit**

```bash
.venv/bin/python -m pytest tests/ -q
git add pipeline/report/ tests/
git commit -m "Name the excluded activities beside the numbers they shrank"
```

---

### Task 6: Tell the agent it is not looking at everything

The pack already tells the agent in plain text what it must not claim — see the GEB/GEB-1 paragraph at `agent_pack.py:1426`, written because the source cannot resolve that distinction. Exclusions need the same treatment: an agent answering "there are 12 activities in March" while 3 were excluded is confidently wrong.

**Files:**
- Modify: `pipeline/report/agent_pack.py` (the guidance prose block containing the GEB/GEB-1 paragraph, around line 1426; and `checklist_text` at line ~2162)
- Test: `tests/test_agent_pack.py`

**Interfaces:**
- Consumes: `Scope.hidden_excluded` from Task 5
- Produces: no new symbols; asserted through the pack's rendered text

- [ ] **Step 1: Write the failing tests**

Add `from dataclasses import replace` to the imports. `Scope` is a dataclass,
so `replace()` gives a scope with the count set without touching the fixture
loader. Assert across the whole pack rather than one named file: the guidance
prose may move between documents, and what matters is that the agent reads it
somewhere.

```python
# tests/test_agent_pack.py
def _pack_text(pack_dir):
    """Every text file the pack ships, as one string."""
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(pack_dir.rglob("*"))
        if path.is_file() and path.suffix in (".txt", ".md")
    )


def test_the_pack_tells_the_agent_some_activities_are_absent(tmp_path):
    """An agent answering "12 activities in March" while 3 are hidden is
    confidently wrong, and nothing in the data can tell it so."""
    scope, config = _scope(tmp_path)
    scope = replace(scope, hidden_excluded=3)

    pack_dir = agent_pack.write_pack(scope, agent_pack.pack_config(config), tmp_path / "out")
    text = _pack_text(pack_dir)

    assert "3" in text
    assert "excluded" in text.lower()
    assert "complete" in text.lower()


def test_a_pack_with_nothing_hidden_says_nothing_about_exclusions(tmp_path):
    """A standing warning nobody needs is a warning that stops being read."""
    scope, config = _scope(tmp_path)

    pack_dir = agent_pack.write_pack(scope, agent_pack.pack_config(config), tmp_path / "out")

    assert "not for general circulation" not in _pack_text(pack_dir)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_agent_pack.py -q -k "some_activities_are_absent or nothing_about_exclusions"`
Expected: the first FAILs (the string is not in the rendered text); the second PASSes already, and is there to keep step 3 from adding an unconditional paragraph

- [ ] **Step 3: Add the paragraph**

Alongside the GEB/GEB-1 paragraph, rendered only when `scope.hidden_excluded` is non-zero:

```python
        f"- **This pack is not the whole plan.** {scope.hidden_excluded} "
        f"activity/activities were excluded before it was built, because the "
        f"source marks them as not for general circulation. They are absent "
        f"from every count, every calendar and every list here. Never describe "
        f"this data as complete, and when a total matters to the answer, say "
        f"that {scope.hidden_excluded} more exist that this pack cannot see. "
        f"You cannot retrieve them, and their titles, dates and owners are not "
        f"in any file you have."
```

- [ ] **Step 4: Add it to the control checklist header**

In `checklist_text` (line ~2162), where the total is stated:

```python
        f"Data: {config.period_label()}, {total} activities in scope"
        + (f" ({scope.hidden_excluded} excluded as not for general circulation)"
           if scope.hidden_excluded else "")
        + ".",
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_agent_pack.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add pipeline/report/agent_pack.py tests/test_agent_pack.py
git commit -m "Tell the agent the pack is not the whole plan"
```

---

### Task 7: The MCP server says the same thing

**Files:**
- Modify: `pipeline/mcp/server.py:40` (`INSTRUCTIONS`)
- Test: `tests/test_mcp_server.py`

**Interfaces:**
- Consumes: nothing at runtime — the database it queries is already filtered by Task 3
- Produces: no new symbols

- [ ] **Step 1: Write the failing test**

```python
# tests/test_mcp_server.py
def test_the_server_instructions_warn_that_hidden_activities_are_absent():
    """The rows are already gone from the database; the agent has to be told."""
    from pipeline.mcp import server

    assert "not for general circulation" in server.INSTRUCTIONS
    assert "complete" in server.INSTRUCTIONS.lower()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_mcp_server.py -q -k "instructions_warn"`
Expected: FAIL

- [ ] **Step 3: Extend `INSTRUCTIONS`**

Add to the `INSTRUCTIONS` block:

```
Activities the source marks as not for general circulation are excluded from
this database entirely. Every count you compute is therefore a count of the
activities that may circulate, not of everything planned. Never call a result
complete or exhaustive, and never conclude from an empty result that nothing
is planned -- you cannot see the difference between "nothing" and "nothing you
may see".
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_mcp_server.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pipeline/mcp/server.py tests/test_mcp_server.py
git commit -m "Tell the MCP client it is querying a filtered database"
```

---

### Task 8: The time-zone check excludes too

**Files:**
- Modify: `pipeline/scripts/check_time_zones.py:100` (`collect`)
- Test: `tests/test_check_time_zones.py`

**Interfaces:**
- Consumes: `process_cplan.exclude_hidden` from Task 2
- Produces: `Usage.hidden_excluded` (int) on the existing `Usage` dataclass in that module

The file's `_export(tmp_path, header, *values)` helper writes a fixed four-column
header and one row per value. Every fixture in the file goes through it, and
after Task 2 every one of them raises `HiddenColumnMissing`. So widen the helper
first: it gains the hide column on every row, plus a keyword naming which rows
are hidden. That single change fixes the whole file.

- [ ] **Step 1: Widen the fixture helper**

```python
# tests/test_check_time_zones.py
HIDE_HEADER = "Hide_x0020_from_x0020_public_x0020_view"


def _export(tmp_path: Path, header: str, *values: str, hidden=()) -> Path:
    """One internal export. `hidden` names 1-based row numbers to mark hidden."""
    path = tmp_path / "InternalCommunicationActivities.csv"
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["ID", "Title", "Start date", header, HIDE_HEADER])
        for index, value in enumerate(values, start=1):
            writer.writerow([str(index), f"Activity {index}", "2025-03-05", value,
                             "TRUE" if index in hidden else "FALSE"])
    return path
```

The other writers in this file (the ones building their own header rows around
lines 111, 129 and 143) each need `HIDE_HEADER` appended to the header row and
`"FALSE"` appended to every data row.

- [ ] **Step 2: Write the failing test**

```python
# tests/test_check_time_zones.py
def test_a_hidden_activity_is_not_counted(tmp_path):
    """The rule is "gone everywhere". A defect in a row that never ships is a
    defect that never ships, and an exception here is one nobody remembers."""
    _export(tmp_path, "Time zone",
            "W. Europe Standard Time",
            "Tokyo Standard Time",
            hidden=(2,))
    files = check_time_zones.find_input_files(tmp_path)

    usage = check_time_zones.collect(files)

    assert "Tokyo Standard Time" not in usage.values
    assert "W. Europe Standard Time" in usage.values
    assert usage.hidden_excluded == 1
```

If `find_input_files` is not re-exported by `check_time_zones`, import it from
`pipeline.scripts.process_cplan` the way the module itself does.

- [ ] **Step 3: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_check_time_zones.py -q -k "hidden_activity_is_not_counted"`
Expected: FAIL with `AttributeError: 'Usage' object has no attribute 'hidden_excluded'`

- [ ] **Step 4: Apply the exclusion**

In `collect`, after the `transform` call:

```python
        frame = transform(read_csv_auto(path), source_type=SOURCE_TYPES[key])
        # Excluded here too, and the cost is real: a hidden row with a broken
        # zone keeps its defect, unreported. Accepted, because this check
        # exists to fix data that flows onward and these rows do not flow
        # onward -- and because "hidden rows are gone everywhere" is a rule
        # that can be held in mind, while "gone everywhere except here" is an
        # exception the first person to forget gets wrong in the direction
        # that leaks.
        frame, excluded = exclude_hidden(frame, path.name)
        usage.hidden_excluded += excluded
```

Add `hidden_excluded: int = 0` to the `Usage` dataclass, import `exclude_hidden` beside the existing `transform` import, and print the total in the check's report where it prints its other totals.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_check_time_zones.py -q`
Expected: PASS. Fixtures in this file build exports without the hide column and will now raise `HiddenColumnMissing`; add the column to them.

- [ ] **Step 6: Commit**

```bash
git add pipeline/scripts/check_time_zones.py tests/test_check_time_zones.py
git commit -m "Exclude hidden rows from the time-zone check as well"
```

---

### Task 9: The tracking-ID check answers `excluded`, never `missing`

The one consumer that keeps the rows. `missing` there means "never created", and answering that about an activity that exists gets it created a second time.

**Files:**
- Modify: `pipeline/scripts/check_tracking_ids.py` (`Entry`, `build_index`, `Result.status`, `report`, `main`)
- Test: `tests/test_check_tracking_ids.py`

**Interfaces:**
- Consumes: `process_cplan.HIDE_COLUMN` from Task 1 (the check calls `transform()`, so the column is present on its frames)
- Produces: `Entry.hidden` (bool) and a third value of `Result.status`: `"excluded"`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_check_tracking_ids.py
def test_a_hidden_activity_reads_as_excluded_not_missing(tmp_path, capsys):
    """"Missing" means never created. Answering that gets it created twice."""
    _export(tmp_path, "InternalCommunicationActivities.csv", (LIVE, "1", "Board briefing"),
            hide=True)
    ids = _ids(tmp_path, LIVE)

    exit_code = check_tracking_ids.main(["--ids", str(ids), "--input", str(tmp_path)])

    out = capsys.readouterr().out
    assert "excluded" in out.lower()
    assert exit_code == 1


def test_an_excluded_row_carries_no_title(tmp_path):
    _export(tmp_path, "InternalCommunicationActivities.csv", (LIVE, "1", "Board briefing"),
            hide=True)
    ids = _ids(tmp_path, LIVE)
    out_csv = tmp_path / "result.csv"

    check_tracking_ids.main(["--ids", str(ids), "--input", str(tmp_path), "--out", str(out_csv)])

    with open(out_csv, newline="", encoding="utf-8-sig") as handle:
        row = next(csv.DictReader(handle))

    assert row["status"] == "excluded"
    assert row["activity_name"] == ""
    assert "Board briefing" not in open(out_csv, encoding="utf-8-sig").read()


def test_a_result_holding_excluded_rows_warns_before_it_is_forwarded(tmp_path, capsys):
    """A workbook that explains its own sensitivity is one already forwarded."""
    _export(tmp_path, "InternalCommunicationActivities.csv", (LIVE, "1", "Board briefing"),
            hide=True)
    ids = _ids(tmp_path, LIVE)
    out = tmp_path / "result.xlsx"

    check_tracking_ids.main(["--ids", str(ids), "--input", str(tmp_path), "--out", str(out)])

    assert "before forwarding" in capsys.readouterr().out
```

Extend the file's `_export` helper with a `hide=False` keyword that writes the
`Hide_x0020_from_x0020_public_x0020_view` column as `TRUE`/`FALSE`, and add
that column to every existing call.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_check_tracking_ids.py -q -k "excluded or forwarded"`
Expected: FAIL — the status reads `found`

- [ ] **Step 3: Carry the flag into the index**

In `Entry`, add `hidden: bool = False`. In `build_index`, set it from the frame and blank the content for hidden rows:

```python
            hidden = bool(row.get(process_cplan.HIDE_COLUMN, False))
            index[tracking_id] = Entry(
                tracking_id=tracking_id,
                source=key,
                # Nothing but the ID for a hidden row. The question this tool
                # answers is "does it exist", and existence is the whole of
                # what may be said about one.
                sp_id="" if hidden else _cell(row, "sp_id"),
                activity_name="" if hidden else _cell(row, "activity_name"),
                hidden=hidden,
            )
```

- [ ] **Step 4: Add the third status**

```python
    @property
    def status(self) -> str:
        if self.entry is None:
            return "missing"
        return "excluded" if self.entry.hidden else "found"
```

Split the three piles in `report()` — excluded rows get their own table with
the ID and the source only — and keep the exit code non-zero for them: a
listed ID that cannot be used is not a pass.

- [ ] **Step 5: Warn on write**

In `main`, after `write_result(...)`:

```python
    excluded = sum(1 for r in results if r.status == "excluded")
    if excluded:
        log(f"{excluded} of {len(results)} row(s) are excluded activities "
            f"-- check before forwarding this file.")
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_check_tracking_ids.py -q`
Expected: PASS

- [ ] **Step 7: Update the docs and the manifest**

Add the third status to the README's tracking-ID section, add a `check.ps1`
manifest entry with marker `"excluded"` for `check_tracking_ids.py`, and bump
`$manifestVersion`.

- [ ] **Step 8: Run the full suite and commit**

```bash
.venv/bin/python -m pytest tests/ -q
git add -A
git commit -m "Answer excluded rather than missing for a hidden activity"
```

---

### Task 10: The dashboard states the exclusion

**Files:**
- Modify: `pipeline/dashboard/index.html` (the block that fetches `meta.json` around line 1565)
- Test: `tests/test_report_dashboard.py`

**Interfaces:**
- Consumes: `meta.json` keys `excluded_total` and `excluded_counts` from Task 4
- Produces: no new symbols

- [ ] **Step 1: Write the failing test**

```python
# tests/test_report_dashboard.py
def test_the_dashboard_reads_the_exclusion_count_from_meta():
    html = (PIPELINE_DIR / "dashboard" / "index.html").read_text(encoding="utf-8")

    assert "excluded_total" in html
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_report_dashboard.py -q -k "exclusion_count_from_meta"`
Expected: FAIL

- [ ] **Step 3: Render it beside the refresh stamp**

In the `meta.json` handler, alongside where the refresh timestamp is placed, add a line shown only when `meta.excluded_total > 0`:

```javascript
                    // Total level only. "3 excluded" over a quarter says
                    // nothing; the same number scoped to one region in one
                    // week is close to a statement about what is happening
                    // there, which would turn the safeguard into a signal.
                    if (meta.excluded_total > 0) {
                        const note = document.getElementById('exclusion-note');
                        if (note) {
                            note.textContent =
                                `${meta.excluded_total} activities excluded (not for general circulation)`;
                        }
                    }
```

Add the `<span id="exclusion-note">` beside the existing refresh stamp element, styled with the same muted treatment the stamp uses. It must not be filtered, faceted or drilled into by any control on the page.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_report_dashboard.py -q`
Expected: PASS

- [ ] **Step 5: Full suite, brand check, commit and push**

```bash
.venv/bin/python -m pytest tests/ -q
git add -A
git commit -m "Show on the dashboard that the plan is larger than the page"
git push
```

After pushing: the work machine cannot pull. Produce the changed-file list with
raw URLs and the new `check.ps1` markers, as after every push.
