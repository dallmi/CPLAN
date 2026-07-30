# Calendar Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone Python script that reads the SharePoint activity CSV exports from the OneDrive sync folder and writes a seven-sheet `.xlsx` whose core sheet is a collapsible quarter → month → ISO-week calendar matrix over planning dimensions.

**Architecture:** A thin CLI script holds the editable `CONFIG` block and orchestrates. A `pipeline/report/` package holds the parts: `config.py` (the dataclass), `data.py` (loading, filtering, derived columns, the week grid), `style.py` (palette and write primitives), `calendar_sheet.py` (the matrix), `table_sheets.py` (the six flat sheets). Loading reuses the existing ETL read path from `process_cplan.py`, which gains one extracted function so the report and the pipeline share a single definition of "the activity dataset".

**Tech Stack:** Python 3, pandas 3.0.5, openpyxl 3.1.5, pytest 9.1.1 (all already in `.venv`).

## Global Constraints

- **No employer brand name anywhere in the repository.** Not in code, identifiers, comments, docs, test data, or commit messages. Use generic terms: `organisation`, `corporate`, `internal platform`. No absolute local paths in committed files.
- **Packs are never a grouping dimension.** They appear only as an attribute on the Activities sheet and as measured figures on the Data Quality sheet.
- **Every share, ratio and subtotal is an Excel formula with a zero guard** (`=IF(B10=0,0,B6/B10)`), referencing tracked row numbers. Raw counts and order statistics (median, min, max, longest run) are the only literals.
- **Total rows recompute ratios from the totals**, never sum a ratio column.
- **Counting rule:** each activity is counted once, in the ISO week of its `start_date`. Never spread across its runtime.
- **A week belongs to the month containing its Thursday** (ISO 8601); a month to that month's quarter.
- Run tests with `PYTHONPATH=. .venv/bin/python -m pytest`. There is no `pytest.ini` and no `conftest.py`; tests import via the `pipeline.` package path, matching `tests/test_daily_refresh.py`.
- Field names follow the ETL, not the ORM: `is_archived`, not `is_archive`.
- Python identifiers and sheet labels use `executives` / "senior executives" for the `bod_geb` source field. Do not expand the source abbreviation anywhere.

---

### Task 1: Extract `load_activities()` from the ETL

The four-CSV merge currently sits inline in `main()`. The report needs the same
dataset, and two copies of this logic would drift.

**Files:**
- Modify: `pipeline/scripts/process_cplan.py:1071-1105`
- Test: `tests/test_process_cplan_load.py` (create)

**Interfaces:**
- Produces: `process_cplan.load_activities(files: dict[str, Path]) -> ActivityLoad`, where `ActivityLoad` is a `NamedTuple` with fields `frame: pd.DataFrame`, `raw_columns: dict[str, list[str]]`, `files: dict[str, Path]`. `frame` is an empty `pd.DataFrame()` when no activity files are present.
- Produces: `process_cplan.ACTIVITY_KEYS: dict[str, tuple[str, bool]]` at module level.

- [ ] **Step 1: Write the failing test**

Create `tests/test_process_cplan_load.py`:

```python
"""Tests for the activity-loading step shared by the ETL and the calendar report."""

from pathlib import Path

import pytest

pytest.importorskip("pandas")

import pipeline.scripts.process_cplan as process_cplan


INTERNAL_CSV = (
    "ID,Tracking ID,Title,Start date,Region,Modified\n"
    "1,IC-0001,Active row,2025-03-05,EMEA,2025-03-01\n"
)
ARCHIVE_CSV = (
    "ID,Tracking ID,Title,Start date,Region,Modified\n"
    "1,IC-0001,Stale duplicate,2025-03-05,EMEA,2025-01-01\n"
    "2,IC-0002,Archived row,2025-04-09,APAC,2025-04-01\n"
)


def _write(tmp_path: Path) -> dict[str, Path]:
    internal = tmp_path / "InternalCommunicationActivities.csv"
    archive = tmp_path / "InternalCommunicationActivitiesArchive.csv"
    internal.write_text(INTERNAL_CSV, encoding="utf-8")
    archive.write_text(ARCHIVE_CSV, encoding="utf-8")
    return {"internal": internal, "internal_archive": archive}


def test_load_activities_merges_archive_and_flags_it(tmp_path):
    load = process_cplan.load_activities(_write(tmp_path))

    assert set(load.frame["tracking_id"]) == {"IC-0001", "IC-0002"}
    archived = load.frame.set_index("tracking_id")["is_archived"]
    assert archived["IC-0002"] is True or archived["IC-0002"] == True  # noqa: E712


def test_load_activities_keeps_the_most_recently_modified_duplicate(tmp_path):
    load = process_cplan.load_activities(_write(tmp_path))

    row = load.frame.set_index("tracking_id").loc["IC-0001"]
    assert row["activity_name"] == "Active row"


def test_load_activities_reports_raw_columns_per_file(tmp_path):
    load = process_cplan.load_activities(_write(tmp_path))

    assert "Tracking ID" in load.raw_columns["internal"]
    assert set(load.files) == {"internal", "internal_archive"}


def test_load_activities_with_no_activity_files_returns_an_empty_frame(tmp_path):
    load = process_cplan.load_activities({"packs": tmp_path / "CommunicationPacks.csv"})

    assert load.frame.empty
    assert load.raw_columns == {}
    assert load.files == {}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_process_cplan_load.py -v`
Expected: FAIL with `AttributeError: module 'pipeline.scripts.process_cplan' has no attribute 'load_activities'`

- [ ] **Step 3: Extract the function**

Add at module level in `pipeline/scripts/process_cplan.py`, above `main()`:

```python
# Which activity CSVs exist and what each one means: (source_type, is_archived).
# The archive lists are a SharePoint view-size workaround, not a different kind
# of record, so they are merged into the same dataset and only flagged.
ACTIVITY_KEYS = {
    "internal":         ("internal", False),
    "external":         ("external", False),
    "internal_archive": ("internal", True),
    "external_archive": ("external", True),
}


class ActivityLoad(NamedTuple):
    """The merged activity dataset plus what it took to build it.

    `raw_columns` and `files` exist for the ETL's --preview column comparison;
    the calendar report uses `frame` alone.
    """

    frame: "pd.DataFrame"
    raw_columns: dict
    files: dict


def load_activities(files):
    """Read, transform, merge and de-duplicate the four activity CSVs.

    Shared by the ETL and the calendar report so the two can never disagree
    about how many activities exist.
    """
    activity_files = {k: v for k, v in files.items() if k in ACTIVITY_KEYS}
    frames = []
    raw_columns = {}
    for key, path in activity_files.items():
        source_type, is_archived = ACTIVITY_KEYS[key]
        log(f"Reading {path.name}...")
        df = read_csv_auto(path)
        log(f"  {key}: {len(df)} rows, {len(df.columns)} columns")
        raw_columns[key] = [c.strip() for c in df.columns]
        df = transform(df, source_type=source_type)
        df["is_archived"] = is_archived
        frames.append(df)

    if not frames:
        return ActivityLoad(pd.DataFrame(), raw_columns, activity_files)

    combined = pd.concat(frames, ignore_index=True)
    log(f"Combined activities: {len(combined)} rows")

    # Deduplicate: active + archive lists can overlap.
    # Keep the most recently modified row per tracking_id.
    if "tracking_id" in combined.columns:
        before = len(combined)
        sort_col = "modified" if "modified" in combined.columns else None
        if sort_col:
            combined = combined.sort_values(sort_col, ascending=False, na_position="last")
        combined = combined.drop_duplicates(subset=["tracking_id"], keep="first")
        combined = combined.reset_index(drop=True)
        dupes = before - len(combined)
        if dupes:
            log(f"  Removed {dupes} duplicate rows (by tracking_id)")

    return ActivityLoad(combined, raw_columns, activity_files)
```

Add `NamedTuple` to the existing `typing` import, or add `from typing import NamedTuple` near the other imports.

- [ ] **Step 4: Rewrite the `main()` block to call it**

Replace `pipeline/scripts/process_cplan.py:1071-1105` (from the
`# --- Communication activities ...` comment down to and including the
`if preview:` / `else:` dispatch) with:

```python
    # --- Communication activities (internal + external, active + archive) ---
    load = load_activities(files)
    combined = load.frame

    if not combined.empty:
        if preview:
            print_column_comparison(load.raw_columns, load.files)
            print_data_preview(combined)
        else:
            write_table(combined, "communications", "communications", full_refresh=full_refresh)
```

Delete the now-unused local `ACTIVITY_KEYS` dict inside `main()`.

- [ ] **Step 5: Run the new test and the full suite**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_process_cplan_load.py -v`
Expected: PASS (4 tests)

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/ -q`
Expected: no new failures compared to the pre-change baseline.

- [ ] **Step 6: Verify the ETL still runs**

Run: `PYTHONPATH=. .venv/bin/python pipeline/scripts/process_cplan.py --preview`
Expected: the column comparison and data preview print as before, or the
"No input files found" error if no CSVs are present locally. Either outcome
proves the refactor did not break the entry point; a traceback does not.

- [ ] **Step 7: Commit**

```bash
git add pipeline/scripts/process_cplan.py tests/test_process_cplan_load.py
git commit -m "Give the activity merge a name the report can call"
```

---

### Task 2: Report configuration

**Files:**
- Create: `pipeline/report/__init__.py`
- Create: `pipeline/report/config.py`
- Test: `tests/test_report_config.py`

**Interfaces:**
- Produces: `pipeline.report.config.ReportConfig`, a frozen dataclass with fields `date_from: date`, `date_to: date`, `executives: str`, `audience_bands: tuple[str, ...] | None`, `include_unknown_audience: bool`, `include_archived: bool`, `detail_rows: bool`, `breakdown_fields: tuple[str, ...]`.
- Produces: `AUDIENCE_BANDS: tuple[str, ...]`, `BAND_UNKNOWN: str`, `EXECUTIVES_CHOICES: frozenset[str]`.
- Produces: `ReportConfig.describe() -> list[tuple[str, str]]` — label/value pairs for the Executive Summary's REPORT section.

- [ ] **Step 1: Write the failing test**

Create `tests/test_report_config.py`:

```python
"""The report's configuration block validates itself at startup."""

from datetime import date

import pytest

from pipeline.report.config import AUDIENCE_BANDS, BAND_UNKNOWN, ReportConfig


def _config(**overrides):
    base = dict(date_from=date(2025, 1, 1), date_to=date(2025, 12, 31))
    base.update(overrides)
    return ReportConfig(**base)


def test_defaults_keep_everything_in_scope():
    config = _config()

    assert config.executives == "any"
    assert config.audience_bands is None
    assert config.include_archived is True
    assert config.breakdown_fields == ("business_division", "region")


def test_reversed_dates_are_rejected():
    with pytest.raises(ValueError, match="date_from"):
        _config(date_from=date(2025, 12, 31), date_to=date(2025, 1, 1))


def test_an_unknown_executives_choice_is_rejected():
    with pytest.raises(ValueError, match="executives"):
        _config(executives="yes")


def test_a_misspelled_audience_band_is_rejected():
    with pytest.raises(ValueError, match="audience band"):
        _config(audience_bands=("10-50k",))


def test_every_real_band_is_accepted():
    config = _config(audience_bands=AUDIENCE_BANDS)

    assert config.audience_bands == AUDIENCE_BANDS
    assert BAND_UNKNOWN not in AUDIENCE_BANDS


def test_an_empty_band_tuple_is_rejected_rather_than_filtering_everything_away():
    with pytest.raises(ValueError, match="at least one"):
        _config(audience_bands=())


def test_describe_reports_the_applied_criteria():
    labels = dict(_config(executives="with").describe())

    assert labels["Period"] == "2025-01-01 to 2025-12-31"
    assert labels["Senior executives"] == "with"
    assert labels["Audience bands"] == "all"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_report_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pipeline.report'`

- [ ] **Step 3: Write the implementation**

Create `pipeline/report/__init__.py`:

```python
"""Calendar report: reads the activity CSV exports and writes an .xlsx."""
```

Create `pipeline/report/config.py`:

```python
"""The calendar report's configuration and its vocabulary.

The three criteria the report is built around -- start date, senior-executive
involvement, audience size -- are hard filters: a row that fails any of them is
absent from every sheet. They are validated here rather than at use, so a typo
stops the run instead of silently emptying the workbook.
"""

from dataclasses import dataclass, field
from datetime import date

BAND_UNDER_1K = "< 1000"
BAND_1_10K = "1–10k"
BAND_10_50K = "10–50k"
BAND_50_100K = "50–100k"
BAND_OVER_100K = "> 100k"
BAND_UNKNOWN = "Unknown"

# In ascending order of size. The two largest are what "large audience" means
# on the Executive Summary and the Audience sheet.
AUDIENCE_BANDS = (BAND_UNDER_1K, BAND_1_10K, BAND_10_50K, BAND_50_100K, BAND_OVER_100K)
LARGE_AUDIENCE_BANDS = (BAND_50_100K, BAND_OVER_100K)

EXECUTIVES_CHOICES = frozenset({"any", "with", "without"})

SHORT_NOTICE_DAYS = 7


@dataclass(frozen=True)
class ReportConfig:
    date_from: date
    date_to: date
    executives: str = "any"
    audience_bands: tuple = None
    include_unknown_audience: bool = True
    include_archived: bool = True
    detail_rows: bool = True
    breakdown_fields: tuple = ("business_division", "region")

    def __post_init__(self):
        if self.date_from > self.date_to:
            raise ValueError(
                f"date_from ({self.date_from}) is after date_to ({self.date_to})"
            )
        if self.executives not in EXECUTIVES_CHOICES:
            raise ValueError(
                f"executives must be one of {sorted(EXECUTIVES_CHOICES)}, got {self.executives!r}"
            )
        if self.audience_bands is not None:
            if not self.audience_bands:
                raise ValueError(
                    "audience_bands must name at least one band; use None for all bands"
                )
            unknown = [b for b in self.audience_bands if b not in AUDIENCE_BANDS]
            if unknown:
                raise ValueError(
                    f"unknown audience band(s): {unknown}. Known bands: {list(AUDIENCE_BANDS)}"
                )
        if not self.breakdown_fields:
            raise ValueError("breakdown_fields must name at least one field")

    def describe(self):
        """Label/value pairs for the Executive Summary's REPORT section."""
        bands = "all" if self.audience_bands is None else ", ".join(self.audience_bands)
        return [
            ("Period", f"{self.date_from.isoformat()} to {self.date_to.isoformat()}"),
            ("Senior executives", self.executives),
            ("Audience bands", bands),
            ("Unknown audience band", "included" if self.include_unknown_audience else "excluded"),
            ("Archived activities", "included" if self.include_archived else "excluded"),
            ("Activity detail rows", "on" if self.detail_rows else "off"),
            ("Breakdown dimensions", ", ".join(self.breakdown_fields)),
        ]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_report_config.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add pipeline/report/__init__.py pipeline/report/config.py tests/test_report_config.py
git commit -m "Let a typo in the report criteria fail loudly, not silently"
```

---

### Task 3: Derived values

Five per-row derivations. Each is one function so it can be tested and adjusted
without touching a sheet builder.

**Files:**
- Create: `pipeline/report/derive.py`
- Test: `tests/test_report_derive.py`

**Interfaces:**
- Produces: `split_multi(value) -> list[str]`
- Produces: `classify_reach(business_division, region) -> str`, returning one of `REACH_ORDER`
- Produces: `REACH_ORDER: tuple[str, ...]` and the five constants `REACH_GROUP_WIDE`, `REACH_MULTI_DIVISION`, `REACH_SINGLE_DIVISION`, `REACH_REGIONAL_ONLY`, `REACH_UNCLASSIFIED`
- Produces: `audience_band(value) -> str`
- Produces: `has_executives(value) -> bool`
- Produces: `priority_rank(value) -> int`
- Produces: `GROUP_WIDE_MIN_DIVISIONS: int`, `GLOBAL_REGION_TOKENS: frozenset[str]`

- [ ] **Step 1: Write the failing test**

Create `tests/test_report_derive.py`:

```python
"""Per-row derivations: reach, audience band, executive involvement, priority."""

import pytest

from pipeline.report.config import (
    BAND_10_50K,
    BAND_1_10K,
    BAND_50_100K,
    BAND_OVER_100K,
    BAND_UNDER_1K,
    BAND_UNKNOWN,
)
from pipeline.report.derive import (
    REACH_GROUP_WIDE,
    REACH_MULTI_DIVISION,
    REACH_REGIONAL_ONLY,
    REACH_SINGLE_DIVISION,
    REACH_UNCLASSIFIED,
    audience_band,
    classify_reach,
    has_executives,
    priority_rank,
    split_multi,
)


# --- split_multi -------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("IB, P&C", ["IB", "P&C"]),
    ("IB; P&C", ["IB", "P&C"]),
    ("  IB  ", ["IB"]),
    ("", []),
    (None, []),
    (float("nan"), []),
    ("IB, , P&C", ["IB", "P&C"]),
])
def test_split_multi(value, expected):
    assert split_multi(value) == expected


# --- classify_reach ----------------------------------------------------------

def test_three_or_more_divisions_is_group_wide():
    assert classify_reach("IB, P&C, GWM", "EMEA") == REACH_GROUP_WIDE


def test_a_global_region_is_group_wide_even_with_one_division():
    assert classify_reach("IB", "Global") == REACH_GROUP_WIDE


def test_two_divisions_is_multi_division():
    assert classify_reach("IB, P&C", "EMEA") == REACH_MULTI_DIVISION


def test_one_division_is_single_division():
    assert classify_reach("IB", "EMEA") == REACH_SINGLE_DIVISION


def test_a_region_without_a_division_is_regional_only():
    assert classify_reach("", "APAC") == REACH_REGIONAL_ONLY


def test_neither_field_is_unclassified():
    assert classify_reach(None, None) == REACH_UNCLASSIFIED


# --- audience_band -----------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("250", BAND_UNDER_1K),
    ("999", BAND_UNDER_1K),
    ("1000", BAND_1_10K),
    ("9999", BAND_1_10K),
    ("12000", BAND_10_50K),
    ("50000", BAND_50_100K),
    ("100000", BAND_50_100K),
    ("100001", BAND_OVER_100K),
    ("12,000", BAND_10_50K),
    ("12'000", BAND_10_50K),
    (4200, BAND_1_10K),
])
def test_numeric_audience_values_map_to_bands(value, expected):
    assert audience_band(value) == expected


@pytest.mark.parametrize("value,expected", [
    ("10–50k", BAND_10_50K),
    ("10-50k", BAND_10_50K),
    ("10 - 50k", BAND_10_50K),
    ("> 100k", BAND_OVER_100K),
    ("<1000", BAND_UNDER_1K),
])
def test_band_labels_survive_dash_and_spacing_variants(value, expected):
    assert audience_band(value) == expected


@pytest.mark.parametrize("value", ["", None, "all staff", "n/a", float("nan")])
def test_anything_unrecognised_is_unknown(value):
    assert audience_band(value) == BAND_UNKNOWN


# --- has_executives ----------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("A. Person", True),
    ("   ", False),
    ("", False),
    (None, False),
    (float("nan"), False),
])
def test_executive_involvement_is_a_non_empty_field(value, expected):
    assert has_executives(value) is expected


# --- priority_rank -----------------------------------------------------------

def test_a_leading_integer_wins_with_one_as_most_urgent():
    assert priority_rank("1 - some label") == 4
    assert priority_rank("4 - some label") == 1


def test_the_studio_words_are_the_fallback():
    assert priority_rank("Critical") == 4
    assert priority_rank("low") == 0


def test_an_unknown_value_lands_mid_rank_rather_than_reading_as_low():
    assert priority_rank("whatever") == 1
    assert priority_rank(None) == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_report_derive.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pipeline.report.derive'`

- [ ] **Step 3: Write the implementation**

Create `pipeline/report/derive.py`:

```python
"""Per-row derivations for the calendar report.

Each of these turns one or two raw source fields into a value the report groups
or filters on. They are deliberately small and separately tested: the reach
constants in particular are guesses against the live vocabulary and are expected
to be adjusted after the first real run.
"""

import math
import re

from pipeline.report.config import (
    BAND_10_50K,
    BAND_1_10K,
    BAND_50_100K,
    BAND_OVER_100K,
    BAND_UNDER_1K,
    BAND_UNKNOWN,
)

REACH_GROUP_WIDE = "Group-wide"
REACH_MULTI_DIVISION = "Multi-division"
REACH_SINGLE_DIVISION = "Single division"
REACH_REGIONAL_ONLY = "Regional only"
REACH_UNCLASSIFIED = "Unclassified"

# Ordered widest-first, which is the order the Calendar sheet lists them in.
REACH_ORDER = (
    REACH_GROUP_WIDE,
    REACH_MULTI_DIVISION,
    REACH_SINGLE_DIVISION,
    REACH_REGIONAL_ONLY,
    REACH_UNCLASSIFIED,
)

# Naming this many divisions or more is treated as addressing the whole
# organisation. A guess against the live vocabulary -- revisit after a real run.
GROUP_WIDE_MIN_DIVISIONS = 3
GLOBAL_REGION_TOKENS = frozenset({"global", "worldwide", "all regions"})


def _text(value):
    """Source values arrive as str, None, or pandas NaN. Normalise to a string."""
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def split_multi(value):
    """SharePoint multi-value lookups arrive joined, e.g. "IB, P&C"."""
    text = _text(value)
    if not text:
        return []
    return [part.strip() for part in re.split(r"[;,]", text) if part.strip()]


def classify_reach(business_division, region):
    """One mutually exclusive bucket per activity, so the block sums to the total."""
    divisions = split_multi(business_division)
    regions = [r.lower() for r in split_multi(region)]

    if any(r in GLOBAL_REGION_TOKENS for r in regions):
        return REACH_GROUP_WIDE
    if len(divisions) >= GROUP_WIDE_MIN_DIVISIONS:
        return REACH_GROUP_WIDE
    if len(divisions) > 1:
        return REACH_MULTI_DIVISION
    if len(divisions) == 1:
        return REACH_SINGLE_DIVISION
    if regions:
        return REACH_REGIONAL_ONLY
    return REACH_UNCLASSIFIED


# Boundaries in ascending order: (upper bound inclusive, band).
_BAND_BOUNDS = (
    (999, BAND_UNDER_1K),
    (9_999, BAND_1_10K),
    (49_999, BAND_10_50K),
    (100_000, BAND_50_100K),
)

_NUMERIC = re.compile(r"^\d[\d\s.,']*$")

_BAND_LOOKUP = {
    "<1000": BAND_UNDER_1K,
    "under1000": BAND_UNDER_1K,
    "1-10k": BAND_1_10K,
    "10-50k": BAND_10_50K,
    "50-100k": BAND_50_100K,
    ">100k": BAND_OVER_100K,
    "over100k": BAND_OVER_100K,
}


def _as_number(text):
    if not _NUMERIC.match(text):
        return None
    digits = re.sub(r"[\s.,']", "", text)
    return int(digits) if digits else None


def _normalise_band(text):
    """Fold dash variants and whitespace so label matching is not typography."""
    folded = text.lower()
    folded = re.sub(r"[‐-―−]", "-", folded)
    return re.sub(r"\s+", "", folded)


def audience_band(value):
    """Map a raw count or a band label onto one of the five known bands.

    The source field is heterogeneous: raw counts from some exports, band labels
    from the studio. Whether it carries the "Estimated audience size" value at
    all is an assumption recorded in the knowledge base; concentrating it here
    means there is one place to correct it.
    """
    text = _text(value)
    if not text:
        return BAND_UNKNOWN

    number = _as_number(text)
    if number is not None:
        for upper, band in _BAND_BOUNDS:
            if number <= upper:
                return band
        return BAND_OVER_100K

    return _BAND_LOOKUP.get(_normalise_band(text), BAND_UNKNOWN)


def has_executives(value):
    """Involvement means the source field carries anything after stripping."""
    return bool(_text(value))


_PRIORITY_WORDS = {"critical": 4, "high": 3, "medium": 2, "normal": 1, "low": 0}


def priority_rank(value):
    """Rank a priority the way the studio does (analytics.js::priorityRank).

    Two vocabularies are live at once: the studio's words, and the source
    system's numbered labels where 1 is most urgent. A leading integer wins
    because it is unambiguous; the words are the fallback; anything else lands
    mid-rank rather than silently reading as low.
    """
    text = _text(value)
    numbered = re.match(r"^(\d+)", text)
    if numbered:
        return max(0, 5 - int(numbered.group(1)))
    return _PRIORITY_WORDS.get(text.lower(), 1)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_report_derive.py -v`
Expected: PASS (all parametrised cases)

- [ ] **Step 5: Commit**

```bash
git add pipeline/report/derive.py tests/test_report_derive.py
git commit -m "Turn raw source fields into the buckets the report groups on"
```

---

### Task 4: The week grid

The time axis. Derived from the filter window, not from a calendar year, so
every activity that survives the filter is guaranteed a column.

**Files:**
- Create: `pipeline/report/grid.py`
- Test: `tests/test_report_grid.py`

**Interfaces:**
- Produces: `Week` — frozen dataclass, fields `iso_year: int`, `iso_week: int`, `monday: date`; properties `thursday: date`, `label: str` (`"W01"`), `sublabel: str` (`"30 Dec"`).
- Produces: `GridColumn` — frozen dataclass, fields `kind: str` (`"quarter" | "month" | "week"`), `level: int`, `label: str`, `sublabel: str`, `key`.
- Produces: `Grid` — frozen dataclass, field `weeks: tuple[Week, ...]`; methods `columns() -> list[GridColumn]`, `week_index(day: date) -> int | None`, `month_of(week: Week) -> tuple[int, int]`, `quarter_of(week: Week) -> tuple[int, int]`.
- Produces: `build_grid(date_from: date, date_to: date) -> Grid`

- [ ] **Step 1: Write the failing test**

Create `tests/test_report_grid.py`:

```python
"""The quarter / month / ISO-week column grid."""

from datetime import date

from pipeline.report.grid import build_grid


def test_a_full_year_spans_from_its_first_iso_week_to_the_next_years_first():
    grid = build_grid(date(2025, 1, 1), date(2025, 12, 31))

    assert grid.weeks[0].iso_year == 2025
    assert grid.weeks[0].iso_week == 1
    assert grid.weeks[0].monday == date(2024, 12, 30)
    assert grid.weeks[-1].iso_year == 2026
    assert grid.weeks[-1].iso_week == 1
    assert len(grid.weeks) == 53


def test_the_last_day_of_the_year_has_a_column():
    grid = build_grid(date(2025, 1, 1), date(2025, 12, 31))

    index = grid.week_index(date(2025, 12, 31))

    assert index == len(grid.weeks) - 1


def test_a_day_outside_the_window_has_no_column():
    grid = build_grid(date(2025, 1, 1), date(2025, 12, 31))

    assert grid.week_index(date(2024, 6, 1)) is None
    assert grid.week_index(date(2026, 6, 1)) is None


def test_a_week_belongs_to_the_month_of_its_thursday():
    grid = build_grid(date(2025, 1, 1), date(2025, 12, 31))

    # 2025-W01 runs Mon 30 Dec 2024 to Sun 5 Jan 2025; its Thursday is 2 Jan.
    assert grid.month_of(grid.weeks[0]) == (2025, 1)
    # 2026-W01 runs Mon 29 Dec 2025 to Sun 4 Jan 2026; its Thursday is 1 Jan.
    assert grid.month_of(grid.weeks[-1]) == (2026, 1)
    assert grid.quarter_of(grid.weeks[-1]) == (2026, 1)


def test_columns_nest_quarter_then_month_then_its_weeks():
    grid = build_grid(date(2025, 1, 1), date(2025, 3, 31))
    columns = grid.columns()

    assert columns[0].kind == "quarter"
    assert columns[0].level == 0
    assert columns[0].label == "Q1 2025"
    assert columns[1].kind == "month"
    assert columns[1].level == 1
    assert columns[1].label == "Jan 2025"
    assert columns[2].kind == "week"
    assert columns[2].level == 2
    assert columns[2].label == "W01"
    assert columns[2].sublabel == "30 Dec"


def test_every_week_appears_exactly_once_across_the_columns():
    grid = build_grid(date(2025, 1, 1), date(2025, 12, 31))
    week_columns = [c for c in grid.columns() if c.kind == "week"]

    assert len(week_columns) == len(grid.weeks)
    assert len({c.key for c in week_columns}) == len(grid.weeks)


def test_a_single_week_window_produces_one_of_each_column():
    grid = build_grid(date(2025, 3, 3), date(2025, 3, 7))
    kinds = [c.kind for c in grid.columns()]

    assert kinds == ["quarter", "month", "week"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_report_grid.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pipeline.report.grid'`

- [ ] **Step 3: Write the implementation**

Create `pipeline/report/grid.py`:

```python
"""The report's time axis: ISO weeks nested under months under quarters.

The grid is derived from the filter window rather than from a calendar year, so
every activity that survives the filter is guaranteed a column. For a full year
that means the first ISO week of the year through the first ISO week of the
next -- 53 columns for 2025 -- and a thirteenth month column. That is correct,
not an off-by-one: the last days of December belong to the next year's week 1.
"""

from dataclasses import dataclass
from datetime import date, timedelta

MONTH_NAMES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


@dataclass(frozen=True)
class Week:
    iso_year: int
    iso_week: int
    monday: date

    @property
    def thursday(self):
        return self.monday + timedelta(days=3)

    @property
    def label(self):
        return f"W{self.iso_week:02d}"

    @property
    def sublabel(self):
        return f"{self.monday.day:02d} {MONTH_NAMES[self.monday.month - 1]}"

    @property
    def key(self):
        return (self.iso_year, self.iso_week)


@dataclass(frozen=True)
class GridColumn:
    kind: str      # "quarter" | "month" | "week"
    level: int     # outline level: quarter 0, month 1, week 2
    label: str
    sublabel: str
    key: tuple


@dataclass(frozen=True)
class Grid:
    weeks: tuple

    def month_of(self, week):
        """ISO 8601: a week belongs to the month containing its Thursday."""
        thursday = week.thursday
        return (thursday.year, thursday.month)

    def quarter_of(self, week):
        year, month = self.month_of(week)
        return (year, (month - 1) // 3 + 1)

    def week_index(self, day):
        """Position of `day`'s week in the grid, or None if outside it."""
        if day is None:
            return None
        monday = day - timedelta(days=day.weekday())
        for index, week in enumerate(self.weeks):
            if week.monday == monday:
                return index
        return None

    def columns(self):
        """Ordered columns: each quarter, then its months, each with its weeks.

        Summary columns sit to the LEFT of what they summarise, which is what
        `summaryRight = False` on the sheet expects.
        """
        columns = []
        seen_quarters = []
        by_quarter = {}
        for week in self.weeks:
            quarter = self.quarter_of(week)
            month = self.month_of(week)
            if quarter not in by_quarter:
                by_quarter[quarter] = {}
                seen_quarters.append(quarter)
            by_quarter[quarter].setdefault(month, []).append(week)

        for quarter in seen_quarters:
            columns.append(GridColumn(
                kind="quarter", level=0,
                label=f"Q{quarter[1]} {quarter[0]}", sublabel="Total", key=quarter,
            ))
            for month, weeks in by_quarter[quarter].items():
                columns.append(GridColumn(
                    kind="month", level=1,
                    label=f"{MONTH_NAMES[month[1] - 1]} {month[0]}", sublabel="Total", key=month,
                ))
                for week in weeks:
                    columns.append(GridColumn(
                        kind="week", level=2,
                        label=week.label, sublabel=week.sublabel, key=week.key,
                    ))
        return columns


def build_grid(date_from, date_to):
    first_monday = date_from - timedelta(days=date_from.weekday())
    weeks = []
    cursor = first_monday
    while cursor <= date_to:
        iso = cursor.isocalendar()
        weeks.append(Week(iso_year=iso[0], iso_week=iso[1], monday=cursor))
        cursor += timedelta(days=7)
    return Grid(weeks=tuple(weeks))
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_report_grid.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add pipeline/report/grid.py tests/test_report_grid.py
git commit -m "Derive the time axis from the window, not from the calendar year"
```

---

### Task 5: Loading, filtering and the in-scope dataset

**Files:**
- Create: `pipeline/report/data.py`
- Test: `tests/test_report_data.py`

**Interfaces:**
- Consumes: `process_cplan.load_activities` (Task 1), `ReportConfig` (Task 2), `derive` (Task 3), `build_grid` (Task 4).
- Produces: `Scope` — dataclass with `frame: pd.DataFrame`, `grid: Grid`, `rows_read: int`, `excluded: dict[str, int]`, `source_files: list[tuple[str, str]]`, `completeness_fields: list[str]`, `skipped_completeness_fields: list[str]`.
- Produces: `build_scope(load, config) -> Scope`
- Produces: `COMPLETENESS_FIELDS_COMMON: tuple[str, ...]`, `COMPLETENESS_FIELDS_INTERNAL: tuple[str, ...]`
- Derived columns added to `frame`: `reach`, `audience_band`, `has_executives`, `week_index`, `_quarter`, `priority_rank_value`, `lead_time_days`, `completeness`, `start_day`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_report_data.py`:

```python
"""Filtering the loaded activities down to the report's scope."""

from datetime import date

import pytest

pytest.importorskip("pandas")
import pandas as pd

from pipeline.report.config import BAND_10_50K, BAND_OVER_100K, ReportConfig
from pipeline.report.data import build_scope
from pipeline.report.derive import REACH_SINGLE_DIVISION
from pipeline.scripts.process_cplan import ActivityLoad


def _frame(rows):
    columns = [
        "tracking_id", "activity_name", "source_type", "start_date", "end_date",
        "created", "business_division", "region", "channel", "priority",
        "target_audience", "audience", "bod_geb", "communication_pack_cpid",
        "communication_pack", "campaign", "lead", "lead_team",
        "strategic_objectives", "activity_description", "is_archived",
    ]
    frame = pd.DataFrame(rows, columns=columns)
    for column in ("start_date", "end_date", "created"):
        frame[column] = pd.to_datetime(frame[column], errors="coerce")
    return frame


def _row(**overrides):
    base = dict(
        tracking_id="IC-0001", activity_name="A", source_type="internal",
        start_date="2025-03-05", end_date="2025-03-06", created="2025-02-01",
        business_division="IB", region="EMEA", channel="Email", priority="2 - label",
        target_audience="All staff", audience="12000", bod_geb="",
        communication_pack_cpid="CP-1", communication_pack="Pack", campaign="C",
        lead="L", lead_team="T", strategic_objectives="O",
        activity_description="D", is_archived=False,
    )
    base.update(overrides)
    return base


def _load(*rows):
    return ActivityLoad(_frame([list(r.values()) for r in rows] if rows else []),
                        {"internal": ["Tracking ID"]}, {})


def _config(**overrides):
    base = dict(date_from=date(2025, 1, 1), date_to=date(2025, 12, 31))
    base.update(overrides)
    return ReportConfig(**base)


def test_rows_inside_the_window_survive_and_carry_derived_columns():
    scope = build_scope(_load(_row()), _config())

    assert len(scope.frame) == 1
    row = scope.frame.iloc[0]
    assert row["reach"] == REACH_SINGLE_DIVISION
    assert row["audience_band"] == BAND_10_50K
    assert row["has_executives"] is False or row["has_executives"] == False  # noqa: E712
    assert row["week_index"] == scope.grid.week_index(date(2025, 3, 5))
    assert row["_quarter"] == (2025, 1)
    assert row["lead_time_days"] == 32


def test_a_row_outside_the_window_is_excluded_and_counted():
    scope = build_scope(_load(_row(start_date="2024-06-01")), _config())

    assert len(scope.frame) == 0
    assert scope.excluded["date window"] == 1


def test_a_row_without_a_start_date_is_excluded_and_counted_separately():
    scope = build_scope(_load(_row(start_date=None)), _config())

    assert len(scope.frame) == 0
    assert scope.excluded["no start date"] == 1


def test_the_executive_filter_keeps_only_involved_rows():
    load = _load(_row(tracking_id="A", bod_geb="Someone"), _row(tracking_id="B", bod_geb=""))

    scope = build_scope(load, _config(executives="with"))

    assert list(scope.frame["tracking_id"]) == ["A"]
    assert scope.excluded["senior executives"] == 1


def test_the_executive_filter_can_be_inverted():
    load = _load(_row(tracking_id="A", bod_geb="Someone"), _row(tracking_id="B", bod_geb=""))

    scope = build_scope(load, _config(executives="without"))

    assert list(scope.frame["tracking_id"]) == ["B"]


def test_the_audience_filter_keeps_only_the_named_bands():
    load = _load(_row(tracking_id="A", audience="12000"), _row(tracking_id="B", audience="250000"))

    scope = build_scope(load, _config(audience_bands=(BAND_OVER_100K,),
                                      include_unknown_audience=False))

    assert list(scope.frame["tracking_id"]) == ["B"]
    assert scope.excluded["audience band"] == 1


def test_unknown_audience_rows_can_be_kept_alongside_a_band_filter():
    load = _load(_row(tracking_id="A", audience=""), _row(tracking_id="B", audience="250000"))

    scope = build_scope(load, _config(audience_bands=(BAND_OVER_100K,),
                                      include_unknown_audience=True))

    assert sorted(scope.frame["tracking_id"]) == ["A", "B"]


def test_archived_rows_can_be_excluded():
    load = _load(_row(tracking_id="A", is_archived=True), _row(tracking_id="B", is_archived=False))

    scope = build_scope(load, _config(include_archived=False))

    assert list(scope.frame["tracking_id"]) == ["B"]
    assert scope.excluded["archived"] == 1


def test_completeness_ignores_fields_the_export_does_not_carry():
    scope = build_scope(_load(_row()), _config())

    # time_zone is required in the studio but is not mapped by the ETL, so it
    # must not permanently cap every row's score.
    assert "time_zone" in scope.skipped_completeness_fields
    assert "time_zone" not in scope.completeness_fields
    assert scope.frame.iloc[0]["completeness"] == 100


def test_a_missing_required_field_lowers_completeness_below_100():
    scope = build_scope(_load(_row(channel="")), _config())

    assert scope.frame.iloc[0]["completeness"] < 100


def test_an_empty_load_produces_an_empty_scope_rather_than_an_error():
    scope = build_scope(ActivityLoad(pd.DataFrame(), {}, {}), _config())

    assert scope.frame.empty
    assert scope.rows_read == 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_report_data.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pipeline.report.data'`

- [ ] **Step 3: Write the implementation**

Create `pipeline/report/data.py`:

```python
"""From the loaded CSV dataset to the report's scope.

Filters are applied in a fixed order and each step's removals are counted, so
the Executive Summary can say why a row is not in the file. A row removed by an
earlier filter is not counted again by a later one -- the figures are a
partition of what was read, not overlapping tallies.
"""

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from pipeline.report import derive
from pipeline.report.config import BAND_UNKNOWN
from pipeline.report.grid import build_grid

# The fields the studio requires, from analytics.js. `time_zone` is on that list
# but is not mapped by the ETL, so it is dropped from the denominator here and
# reported as skipped -- otherwise every row from a CSV export would be capped
# below 100% by a field the export cannot carry.
COMPLETENESS_FIELDS_COMMON = (
    "activity_name", "channel", "priority", "strategic_objectives",
    "activity_description", "region", "start_date", "end_date", "time_zone",
    "lead", "lead_team",
)
COMPLETENESS_FIELDS_INTERNAL = COMPLETENESS_FIELDS_COMMON + (
    "target_audience", "audience", "business_division",
)

EXCLUSION_ORDER = (
    "no start date", "date window", "archived", "senior executives", "audience band",
)


@dataclass
class Scope:
    frame: pd.DataFrame
    grid: object
    rows_read: int
    excluded: dict
    source_files: list = field(default_factory=list)
    completeness_fields: list = field(default_factory=list)
    skipped_completeness_fields: list = field(default_factory=list)


def _is_blank(series):
    return series.isna() | (series.astype(str).str.strip().isin(["", "nan", "NaT"]))


def _completeness(frame, fields):
    """Percentage of required fields that carry a value, per row."""
    if not fields:
        return pd.Series([100] * len(frame), index=frame.index)
    filled = pd.Series(0, index=frame.index)
    for name in fields:
        filled += (~_is_blank(frame[name])).astype(int)
    return (filled / len(fields) * 100).round().astype(int)


def build_scope(load, config):
    frame = load.frame
    rows_read = len(frame)
    grid = build_grid(config.date_from, config.date_to)
    excluded = {key: 0 for key in EXCLUSION_ORDER}

    source_files = [
        (key, path.name) for key, path in sorted(load.files.items())
    ]

    if frame.empty:
        return Scope(frame=frame, grid=grid, rows_read=0, excluded=excluded,
                     source_files=source_files)

    frame = frame.copy()
    frame["start_day"] = pd.to_datetime(frame["start_date"], errors="coerce").dt.date

    def drop(mask, reason):
        nonlocal frame
        removed = int(mask.sum())
        if removed:
            excluded[reason] += removed
            frame = frame[~mask].copy()

    drop(frame["start_day"].isna(), "no start date")
    drop(
        frame["start_day"].apply(lambda d: d < config.date_from or d > config.date_to),
        "date window",
    )

    if not config.include_archived and "is_archived" in frame.columns:
        drop(frame["is_archived"].fillna(False).astype(bool), "archived")

    frame["has_executives"] = frame.get(
        "bod_geb", pd.Series([""] * len(frame), index=frame.index)
    ).apply(derive.has_executives)
    if config.executives == "with":
        drop(~frame["has_executives"], "senior executives")
    elif config.executives == "without":
        drop(frame["has_executives"], "senior executives")

    frame["audience_band"] = frame.get(
        "audience", pd.Series([""] * len(frame), index=frame.index)
    ).apply(derive.audience_band)
    if config.audience_bands is not None:
        allowed = set(config.audience_bands)
        if config.include_unknown_audience:
            allowed.add(BAND_UNKNOWN)
        drop(~frame["audience_band"].isin(allowed), "audience band")

    frame["reach"] = [
        derive.classify_reach(division, region)
        for division, region in zip(frame.get("business_division", ""), frame.get("region", ""))
    ]
    frame["week_index"] = frame["start_day"].apply(grid.week_index)
    frame["_quarter"] = [
        grid.quarter_of(grid.weeks[int(i)]) if i is not None and i == i else None
        for i in frame["week_index"]
    ]
    frame["priority_rank_value"] = frame.get(
        "priority", pd.Series([""] * len(frame), index=frame.index)
    ).apply(derive.priority_rank)

    created = pd.to_datetime(frame.get("created"), errors="coerce")
    start = pd.to_datetime(frame["start_date"], errors="coerce")
    frame["lead_time_days"] = (start - created).dt.days

    present = set(frame.columns)
    internal_fields = [f for f in COMPLETENESS_FIELDS_INTERNAL if f in present]
    external_fields = [f for f in COMPLETENESS_FIELDS_COMMON if f in present]
    skipped = sorted(set(COMPLETENESS_FIELDS_INTERNAL) - present)

    is_internal = frame.get("source_type", "") == "internal"
    completeness = pd.Series(0, index=frame.index, dtype=int)
    if is_internal.any():
        completeness[is_internal] = _completeness(frame[is_internal], internal_fields)
    if (~is_internal).any():
        completeness[~is_internal] = _completeness(frame[~is_internal], external_fields)
    frame["completeness"] = completeness

    frame = frame.reset_index(drop=True)
    return Scope(
        frame=frame, grid=grid, rows_read=rows_read, excluded=excluded,
        source_files=source_files,
        completeness_fields=sorted(set(internal_fields) | set(external_fields)),
        skipped_completeness_fields=skipped,
    )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_report_data.py -v`
Expected: PASS (11 tests)

- [ ] **Step 5: Commit**

```bash
git add pipeline/report/data.py tests/test_report_data.py
git commit -m "Filter to scope and say what each criterion removed"
```

---

### Task 6: Workbook styling primitives

**Files:**
- Create: `pipeline/report/style.py`
- Test: `tests/test_report_style.py`

**Interfaces:**
- Produces: number formats `NUM_FMT_INT = "#,##0"`, `NUM_FMT_PCT = "0.0%"`, `NUM_FMT_RATIO = "0.0"`, `NUM_FMT_DATE = "YYYY-MM-DD"`
- Produces: `write_header_row(ws, row, headers, col_start=1) -> int`
- Produces: `write_data_rows(ws, row, rows, fmt_map=None, col_start=1) -> int`
- Produces: `write_section_header(ws, row, title, span, col_start=1) -> int`
- Produces: `write_kpi_row(ws, row, label, value, fmt=NUM_FMT_INT, sub=False) -> int`
- Produces: `write_formula(ws, row, col, formula, fmt=None, fill=None, bold=False)`
- Produces: `note_missing(ws, message)`
- Produces: `finalize_sheet(ws, freeze="A2", widths=None)`
- All row-writing helpers return the next free row number.

- [ ] **Step 1: Write the failing test**

Create `tests/test_report_style.py`:

```python
"""The shared write primitives every sheet is composed from."""

import pytest

pytest.importorskip("openpyxl")
from openpyxl import Workbook

from pipeline.report import style


def _sheet():
    wb = Workbook()
    return wb.active


def test_write_header_row_returns_the_next_row_and_styles_the_cells():
    ws = _sheet()

    nxt = style.write_header_row(ws, 1, ["A", "B"])

    assert nxt == 2
    assert ws.cell(row=1, column=1).value == "A"
    assert ws.cell(row=1, column=1).font.bold is True


def test_write_data_rows_applies_the_format_map_and_stripes():
    ws = _sheet()

    nxt = style.write_data_rows(ws, 1, [["x", 1], ["y", 2]], fmt_map={2: style.NUM_FMT_PCT})

    assert nxt == 3
    assert ws.cell(row=1, column=2).number_format == style.NUM_FMT_PCT
    assert ws.cell(row=2, column=1).fill.start_color.rgb.endswith(style.ROW_ALT)


def test_write_data_rows_falls_back_to_a_number_format_by_type():
    ws = _sheet()

    style.write_data_rows(ws, 1, [["x", 3, 1.5]])

    assert ws.cell(row=1, column=2).number_format == style.NUM_FMT_INT
    assert ws.cell(row=1, column=3).number_format == style.NUM_FMT_RATIO


def test_write_section_header_spans_the_requested_columns():
    ws = _sheet()

    nxt = style.write_section_header(ws, 1, "VOLUME", 3)

    assert nxt == 2
    assert ws.cell(row=1, column=1).value == "VOLUME"
    assert ws.cell(row=1, column=3).fill.start_color.rgb.endswith(style.PASTEL_I)


def test_write_formula_writes_the_formula_verbatim():
    ws = _sheet()

    style.write_formula(ws, 2, 2, "=IF(B1=0,0,B2/B1)", fmt=style.NUM_FMT_PCT)

    assert ws.cell(row=2, column=2).value == "=IF(B1=0,0,B2/B1)"
    assert ws.cell(row=2, column=2).number_format == style.NUM_FMT_PCT


def test_note_missing_writes_one_explanatory_cell():
    ws = _sheet()

    style.note_missing(ws, "No audience data available (audience column missing)")

    assert ws.cell(row=1, column=1).value.startswith("No audience data")


def test_finalize_sheet_freezes_and_clamps_column_widths():
    ws = _sheet()
    ws.cell(row=1, column=1, value="x")
    ws.cell(row=2, column=1, value="y" * 200)

    style.finalize_sheet(ws, freeze="A2")

    assert ws.freeze_panes == "A2"
    assert ws.column_dimensions["A"].width == style.MAX_WIDTH
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_report_style.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pipeline.report.style'`

- [ ] **Step 3: Write the implementation**

Create `pipeline/report/style.py`:

```python
"""Palette and write primitives.

Every sheet is composed from these six writers plus finalize_sheet; that is the
only reason the workbook reads as one document rather than seven.

Colours come from the corporate design system and match what the studio's own
.xlsx export already writes -- white dominates, greys carry structure, the
accent appears only on the summary tab.
"""

from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

WHITE = "FFFFFF"
BLACK = "000000"
GRAY_I = "CCCABC"     # borders
GRAY_IV = "7A7870"    # tab colour, sub-labels
GRAY_VI = "404040"    # header fill
PASTEL_I = "ECEBE4"   # section bands and total rows
ROW_ALT = "F8F7F2"    # zebra striping
BRONZE_I = "B98E2C"   # the summary tab only

NUM_FMT_INT = "#,##0"
NUM_FMT_PCT = "0.0%"
NUM_FMT_RATIO = "0.0"
NUM_FMT_DATE = "YYYY-MM-DD"

MIN_WIDTH = 10
MAX_WIDTH = 40

HEADER_FONT = Font(bold=True, color=WHITE, size=11)
HEADER_FILL = PatternFill(start_color=GRAY_VI, end_color=GRAY_VI, fill_type="solid")
SECTION_FONT = Font(bold=True, color=GRAY_VI, size=11)
SECTION_FILL = PatternFill(start_color=PASTEL_I, end_color=PASTEL_I, fill_type="solid")
ALT_FILL = PatternFill(start_color=ROW_ALT, end_color=ROW_ALT, fill_type="solid")
TOTAL_FILL = SECTION_FILL
TOTAL_FONT = Font(bold=True, color=BLACK, size=11)
LABEL_FONT = Font(bold=True, color=GRAY_VI, size=11)
SUB_FONT = Font(italic=True, color=GRAY_IV, size=10)
BODY_FONT = Font(size=11)
_SIDE = Side(style="thin", color=GRAY_I)
THIN_BORDER = Border(left=_SIDE, right=_SIDE, top=_SIDE, bottom=_SIDE)


def write_header_row(ws, row, headers, col_start=1):
    for offset, header in enumerate(headers):
        cell = ws.cell(row=row, column=col_start + offset, value=header)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = THIN_BORDER
    return row + 1


def write_data_rows(ws, row, rows, fmt_map=None, col_start=1):
    fmt_map = fmt_map or {}
    for index, values in enumerate(rows):
        fill = ALT_FILL if index % 2 == 1 else None
        for offset, value in enumerate(values):
            column = col_start + offset
            cell = ws.cell(row=row + index, column=column, value=value)
            cell.border = THIN_BORDER
            if fill:
                cell.fill = fill
            if column in fmt_map:
                cell.number_format = fmt_map[column]
            elif isinstance(value, bool):
                pass
            elif isinstance(value, float):
                cell.number_format = NUM_FMT_RATIO
            elif isinstance(value, int):
                cell.number_format = NUM_FMT_INT
    return row + len(rows)


def write_section_header(ws, row, title, span, col_start=1):
    for offset in range(span):
        cell = ws.cell(row=row, column=col_start + offset)
        cell.fill = SECTION_FILL
        if offset == 0:
            cell.value = title
            cell.font = SECTION_FONT
    return row + 1


def write_kpi_row(ws, row, label, value, fmt=NUM_FMT_INT, sub=False):
    """Label in column A, value in column B. `sub` indents and italicises."""
    label_cell = ws.cell(row=row, column=1, value=label)
    label_cell.font = SUB_FONT if sub else LABEL_FONT
    label_cell.alignment = Alignment(indent=4 if sub else 1)
    value_cell = ws.cell(row=row, column=2, value=value)
    value_cell.font = SUB_FONT if sub else BODY_FONT
    value_cell.alignment = Alignment(horizontal="right")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        value_cell.number_format = fmt
    return row + 1


def write_formula(ws, row, col, formula, fmt=None, fill=None, bold=False):
    cell = ws.cell(row=row, column=col, value=formula)
    cell.border = THIN_BORDER
    if fmt:
        cell.number_format = fmt
    if fill:
        cell.fill = fill
    if bold:
        cell.font = TOTAL_FONT
    return cell


def note_missing(ws, message):
    """Graceful degradation: one honest cell instead of a traceback."""
    cell = ws.cell(row=1, column=1, value=message)
    cell.font = SUB_FONT
    return 2


def auto_fit_columns(ws, min_width=MIN_WIDTH, max_width=MAX_WIDTH):
    for column_cells in ws.columns:
        letter = get_column_letter(column_cells[0].column)
        longest = max(
            (len(str(cell.value)) for cell in column_cells if cell.value is not None),
            default=0,
        )
        ws.column_dimensions[letter].width = min(max(longest + 2, min_width), max_width)


def finalize_sheet(ws, freeze="A2", widths=None):
    """Freeze, then set widths. Explicit widths win over the auto fit."""
    if freeze:
        ws.freeze_panes = freeze
    auto_fit_columns(ws)
    for letter, width in (widths or {}).items():
        ws.column_dimensions[letter].width = width
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_report_style.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add pipeline/report/style.py tests/test_report_style.py
git commit -m "Give every sheet the same six ways to write a row"
```

---

### Task 7: Raw-CSV fixture builder

Every later task's tests need a realistic dataset. Build it once, in the shape
the source system actually exports.

**Files:**
- Create: `tests/report_fixtures.py`
- Test: `tests/test_report_fixtures.py`

**Interfaces:**
- Produces: `write_activity_csvs(directory: Path) -> dict[str, Path]` — writes the four CSVs and returns the mapping `find_input_files` would return.
- Produces: `FIXTURE_ROW_COUNT: int` — activities after de-duplication.
- Produces: `load_fixture_scope(directory, config) -> Scope` — convenience wrapper over `load_activities` + `build_scope`.

- [ ] **Step 1: Write the fixture builder**

Create `tests/report_fixtures.py`:

```python
"""Synthetic SharePoint-shaped activity exports for the report tests.

Raw source column names and lookup JSON, so the tests exercise the same
transform path the real run does. All content is synthetic and
organisation-neutral: generic division, region and audience values, no personal
names, no production identifiers.
"""

import json
from pathlib import Path

HEADER = [
    "ID", "Tracking ID", "Title", "Activity", "Target audience", "Business Division",
    "Region", "Channel", "Priority", "Strategic Objectives", "Lead", "Lead Team",
    "Start date", "End date", "Created", "Modified", "Communication pack:C",
    "Communication pack", "Campaign", "BOD*GEB", "Audience",
]


def _lookup(*values):
    return json.dumps([{"Id": i + 1, "Value": v} for i, v in enumerate(values)])


def _row(sp_id, tracking_id, name, start, **overrides):
    row = {
        "ID": sp_id, "Tracking ID": tracking_id, "Title": name,
        "Activity": "<p>Synthetic description</p>", "Target audience": "All staff",
        "Business Division": _lookup("Division A"), "Region": _lookup("EMEA"),
        "Channel": _lookup("Email"), "Priority": "2 - label",
        "Strategic Objectives": "Objective", "Lead": "Lead person",
        "Lead Team": "Team", "Start date": start, "End date": start,
        "Created": "2025-01-05", "Modified": "2025-06-01",
        "Communication pack:C": "CP-100", "Communication pack": "Pack one",
        "Campaign": "Campaign one", "BOD*GEB": "", "Audience": "4200",
    }
    row.update(overrides)
    return row


# One row per situation the report has to survive. Kept small and explicit so a
# failing assertion points at a named case rather than at row 37 of a blob.
INTERNAL_ROWS = [
    _row(1, "IC-0001", "Single division Q1", "2025-02-12"),
    _row(2, "IC-0002", "Three divisions is group-wide", "2025-02-13",
         **{"Business Division": _lookup("Division A", "Division B", "Division C")}),
    _row(3, "IC-0003", "Global region is group-wide", "2025-05-07",
         **{"Region": _lookup("Global")}),
    _row(4, "IC-0004", "Two divisions", "2025-08-20",
         **{"Business Division": _lookup("Division A", "Division B")}),
    _row(5, "IC-0005", "Region only", "2025-11-04",
         **{"Business Division": "", "Region": _lookup("APAC")}),
    _row(6, "IC-0006", "Neither dimension", "2025-11-05",
         **{"Business Division": "", "Region": ""}),
    _row(7, "IC-0007", "With senior executives", "2025-03-19",
         **{"BOD*GEB": "<p>An executive</p>", "Audience": "250000"}),
    _row(8, "IC-0008", "Audience as a band label", "2025-06-11",
         **{"Audience": "10–50k"}),
    _row(9, "IC-0009", "No audience value", "2025-06-12", **{"Audience": ""}),
    _row(10, "IC-0010", "No start date", None, **{"Start date": ""}),
    _row(11, "IC-0011", "Outside the window", "2024-06-04"),
    _row(12, "IC-0012", "Incomplete record", "2025-09-24",
         **{"Channel": "", "Lead Team": "", "Communication pack:C": ""}),
    _row(13, "IC-0013", "Last week of the year", "2025-12-31"),
]

# Same tracking ID as IC-0001 with an older Modified: must lose the de-dup.
INTERNAL_ARCHIVE_ROWS = [
    _row(1, "IC-0001", "Stale archived duplicate", "2025-02-12",
         **{"Modified": "2025-01-01"}),
    _row(20, "IC-0020", "Genuinely archived", "2025-04-02"),
]

EXTERNAL_ROWS = [
    _row(30, "EC-0001", "External single division", "2025-02-19",
         **{"Channel": _lookup("Press")}),
    _row(31, "EC-0002", "External group-wide", "2025-07-16",
         **{"Region": _lookup("Worldwide"), "Audience": "150000"}),
]

EXTERNAL_ARCHIVE_ROWS = []

# 13 internal + 1 surviving archive + 2 external, minus the losing duplicate.
FIXTURE_ROW_COUNT = 16


def _write_csv(path, rows):
    lines = [",".join(f'"{h}"' for h in HEADER)]
    for row in rows:
        cells = []
        for header in HEADER:
            value = row.get(header, "")
            text = "" if value is None else str(value)
            cells.append('"' + text.replace('"', '""') + '"')
        lines.append(",".join(cells))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_activity_csvs(directory):
    """Write the four activity exports and return the find_input_files mapping."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    files = {
        "internal": _write_csv(
            directory / "InternalCommunicationActivities.csv", INTERNAL_ROWS),
        "internal_archive": _write_csv(
            directory / "InternalCommunicationActivitiesArchive.csv", INTERNAL_ARCHIVE_ROWS),
        "external": _write_csv(
            directory / "ExternalCommunicationActivities.csv", EXTERNAL_ROWS),
        "external_archive": _write_csv(
            directory / "ExternalCommunicationActivitiesArchive.csv", EXTERNAL_ARCHIVE_ROWS),
    }
    return files


def load_fixture_scope(directory, config):
    from pipeline.report.data import build_scope
    from pipeline.scripts.process_cplan import load_activities

    return build_scope(load_activities(write_activity_csvs(directory)), config)
```

- [ ] **Step 2: Write the test that proves the fixture round-trips**

Create `tests/test_report_fixtures.py`:

```python
"""The fixture must survive the real transform path, or nothing built on it means anything."""

from datetime import date

import pytest

pytest.importorskip("pandas")

from pipeline.report.config import ReportConfig
from pipeline.report.derive import (
    REACH_GROUP_WIDE,
    REACH_REGIONAL_ONLY,
    REACH_UNCLASSIFIED,
)
from tests.report_fixtures import FIXTURE_ROW_COUNT, load_fixture_scope, write_activity_csvs
from pipeline.scripts.process_cplan import load_activities


def _config(**overrides):
    base = dict(date_from=date(2025, 1, 1), date_to=date(2025, 12, 31))
    base.update(overrides)
    return ReportConfig(**base)


def test_the_fixture_loads_and_deduplicates(tmp_path):
    load = load_activities(write_activity_csvs(tmp_path))

    assert len(load.frame) == FIXTURE_ROW_COUNT
    name = load.frame.set_index("tracking_id").loc["IC-0001", "activity_name"]
    assert name == "Single division Q1"


def test_lookup_json_becomes_readable_values(tmp_path):
    load = load_activities(write_activity_csvs(tmp_path))
    row = load.frame.set_index("tracking_id").loc["IC-0002"]

    assert "Division A" in row["business_division"]
    assert "Division C" in row["business_division"]


def test_the_scope_covers_every_reach_bucket(tmp_path):
    scope = load_fixture_scope(tmp_path, _config())

    reaches = set(scope.frame["reach"])
    assert REACH_GROUP_WIDE in reaches
    assert REACH_REGIONAL_ONLY in reaches
    assert REACH_UNCLASSIFIED in reaches


def test_the_scope_excludes_the_undated_and_out_of_window_rows(tmp_path):
    scope = load_fixture_scope(tmp_path, _config())

    assert scope.excluded["no start date"] == 1
    assert scope.excluded["date window"] == 1
    assert "IC-0011" not in set(scope.frame["tracking_id"])
```

- [ ] **Step 3: Run the tests**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_report_fixtures.py -v`
Expected: PASS (4 tests). If `FIXTURE_ROW_COUNT` is wrong, fix the constant to
match the loader rather than the other way round — but first confirm the
de-duplication kept `Single division Q1`, which is the behaviour under test.

- [ ] **Step 4: Commit**

```bash
git add tests/report_fixtures.py tests/test_report_fixtures.py
git commit -m "Build source-shaped fixtures so the report tests hit the real path"
```

---

### Task 8: The Calendar sheet

The matrix: dimension rows against a quarter → month → week column outline.

**Files:**
- Create: `pipeline/report/calendar_sheet.py`
- Test: `tests/test_report_calendar_sheet.py`

**Interfaces:**
- Consumes: `Scope` (Task 5), `Grid`/`GridColumn` (Task 4), `style` (Task 6), `REACH_ORDER` (Task 3).
- Produces: `build_calendar(wb, scope, config) -> None` — appends a sheet named `Calendar`.
- Produces: `FIRST_DATA_ROW = 3`, `LABEL_COL = 1`, `TOTAL_COL = 2`, `FIRST_GRID_COL = 3`.

**Layout contract** (later tasks and tests depend on it):
- Row 1 carries the period label per grid column; row 2 carries the sublabel.
  `A1:A2` merged as `Scope / activity`, `B1:B2` merged as `Total`.
- Data starts at row 3. Freeze panes `C3`.
- Column outline levels: quarter 0, month 1, week 2. Levels 1 and 2 start hidden.
  `ws.sheet_properties.outlinePr.summaryRight = False`, `summaryBelow = False`.
- Row outline levels: block header 0, dimension value 1, activity 2.
  Levels 1 and 2 start hidden.
- Week cells: literal counts. Month, quarter and Total cells: `SUM` formulas.
- Block header rows: `SUM` down the column for the Reach block only.

- [ ] **Step 1: Write the failing test**

Create `tests/test_report_calendar_sheet.py`:

```python
"""The calendar matrix: outline levels, formulas, and the double-count trap."""

from datetime import date

import pytest

pytest.importorskip("openpyxl")
from openpyxl import Workbook

from pipeline.report.calendar_sheet import (
    FIRST_GRID_COL,
    LABEL_COL,
    TOTAL_COL,
    build_calendar,
)
from pipeline.report.config import ReportConfig
from tests.report_fixtures import load_fixture_scope


def _config(**overrides):
    base = dict(date_from=date(2025, 1, 1), date_to=date(2025, 12, 31))
    base.update(overrides)
    return ReportConfig(**base)


def _sheet(tmp_path, **overrides):
    scope = load_fixture_scope(tmp_path, _config(**overrides))
    wb = Workbook()
    wb.remove(wb.active)
    build_calendar(wb, scope, _config(**overrides))
    return wb["Calendar"], scope


def _labels(ws):
    return {
        ws.cell(row=r, column=LABEL_COL).value: r
        for r in range(3, ws.max_row + 1)
        if ws.cell(row=r, column=LABEL_COL).value
    }


def test_the_header_names_the_axes(tmp_path):
    ws, _ = _sheet(tmp_path)

    assert ws.cell(row=1, column=LABEL_COL).value == "Scope / activity"
    assert ws.cell(row=1, column=TOTAL_COL).value == "Total"
    assert ws.cell(row=1, column=FIRST_GRID_COL).value == "Q1 2025"
    assert ws.freeze_panes == "C3"


def test_columns_carry_the_three_outline_levels_and_open_collapsed(tmp_path):
    ws, _ = _sheet(tmp_path)
    levels = {}
    for letter, dimension in ws.column_dimensions.items():
        levels.setdefault(dimension.outline_level, []).append(letter)

    assert set(levels) >= {0, 1, 2}
    month_letter = levels[1][0]
    week_letter = levels[2][0]
    assert ws.column_dimensions[month_letter].hidden is True
    assert ws.column_dimensions[week_letter].hidden is True
    assert ws.sheet_properties.outlinePr.summaryRight is False


def test_rows_carry_block_dimension_and_activity_levels(tmp_path):
    ws, _ = _sheet(tmp_path)
    labels = _labels(ws)
    block_row = labels["BY REACH"]

    assert ws.row_dimensions[block_row].outline_level == 0
    child_rows = [r for r in range(block_row + 1, ws.max_row + 1)
                  if ws.row_dimensions[r].outline_level == 1]
    assert child_rows
    assert ws.row_dimensions[child_rows[0]].hidden is True


def test_month_and_quarter_cells_are_sum_formulas_over_their_children(tmp_path):
    ws, _ = _sheet(tmp_path)
    row = _labels(ws)["ALL ACTIVITIES"]

    quarter_cell = ws.cell(row=row, column=FIRST_GRID_COL).value
    assert isinstance(quarter_cell, str) and quarter_cell.startswith("=SUM(")
    total_cell = ws.cell(row=row, column=TOTAL_COL).value
    assert isinstance(total_cell, str) and total_cell.startswith("=SUM(")


def test_week_cells_are_literal_counts(tmp_path):
    ws, scope = _sheet(tmp_path)
    row = _labels(ws)["ALL ACTIVITIES"]
    week_columns = [c for c in range(FIRST_GRID_COL, ws.max_column + 1)
                    if ws.column_dimensions[
                        ws.cell(row=1, column=c).column_letter].outline_level == 2]
    values = [ws.cell(row=row, column=c).value for c in week_columns]
    numeric = [v for v in values if isinstance(v, int)]

    assert sum(numeric) == len(scope.frame)


def test_the_reach_block_header_sums_its_children(tmp_path):
    ws, _ = _sheet(tmp_path)
    row = _labels(ws)["BY REACH"]

    assert str(ws.cell(row=row, column=TOTAL_COL).value).startswith("=SUM(")


def test_the_division_block_header_is_a_distinct_count_not_a_sum(tmp_path):
    ws, scope = _sheet(tmp_path)
    labels = _labels(ws)
    header = next(label for label in labels if label.startswith("BY BUSINESS DIVISION"))
    row = labels[header]

    assert "multiple values possible" in header
    assert isinstance(ws.cell(row=row, column=TOTAL_COL).value, str) is False
    assert ws.cell(row=row, column=TOTAL_COL).value == len(scope.frame)


def test_detail_rows_can_be_switched_off(tmp_path):
    with_detail, _ = _sheet(tmp_path, detail_rows=True)
    without_detail, _ = _sheet(tmp_path, detail_rows=False)

    assert with_detail.max_row > without_detail.max_row
    levels = {without_detail.row_dimensions[r].outline_level
              for r in range(3, without_detail.max_row + 1)}
    assert 2 not in levels
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_report_calendar_sheet.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pipeline.report.calendar_sheet'`

- [ ] **Step 3: Write the implementation**

Create `pipeline/report/calendar_sheet.py`:

```python
"""The calendar matrix.

Rows are planning dimensions, columns are quarters that expand into months that
expand into ISO weeks. Both axes are Excel outlines, so the sheet opens as a
handful of quarter columns against a handful of block rows and expands on click.

Two rules keep the arithmetic honest:

* Horizontal aggregation is ALWAYS a formula -- a month is the sum of its week
  cells, a quarter the sum of its months, the total the sum of its quarters. The
  sheet cannot contradict itself and the reader can click any figure.
* Vertical aggregation is a formula only where it is valid. The reach buckets
  partition the portfolio, so that block header is a real SUM. The division and
  region blocks overlap -- an activity naming two divisions appears twice -- so
  their headers carry a distinct count computed here, and say so in the label.
  A SUM there would print a bold number larger than the portfolio.
"""

from openpyxl.formatting.rule import DataBarRule
from openpyxl.utils import get_column_letter

from pipeline.report import style
from pipeline.report.derive import REACH_ORDER, split_multi

SHEET_NAME = "Calendar"
LABEL_COL = 1
TOTAL_COL = 2
FIRST_GRID_COL = 3
FIRST_DATA_ROW = 3

NOT_SPECIFIED = "Not specified"

FIELD_TITLES = {
    "business_division": "BUSINESS DIVISION",
    "region": "REGION",
}


def _column_positions(columns):
    """Map each grid column to its sheet column index, and group the children."""
    positions = {}
    for offset, column in enumerate(columns):
        positions[(column.kind, column.key)] = FIRST_GRID_COL + offset
    return positions


def _children(columns, grid):
    """For each month column, its week columns; for each quarter, its months."""
    month_weeks = {}
    quarter_months = {}
    current_quarter = None
    current_month = None
    for column in columns:
        if column.kind == "quarter":
            current_quarter = column.key
            quarter_months.setdefault(current_quarter, [])
        elif column.kind == "month":
            current_month = column.key
            month_weeks.setdefault(current_month, [])
            quarter_months[current_quarter].append(current_month)
        else:
            month_weeks[current_month].append(column.key)
    return month_weeks, quarter_months


def _write_grid_row(ws, row, counts, columns, positions, month_weeks, quarter_months,
                    bold=False):
    """Literal week counts, SUM formulas everywhere else."""
    fill = style.TOTAL_FILL if bold else None
    for column in columns:
        col = positions[(column.kind, column.key)]
        if column.kind == "week":
            value = counts.get(column.key, 0)
            cell = ws.cell(row=row, column=col, value=value or None)
            cell.border = style.THIN_BORDER
            if value:
                cell.number_format = style.NUM_FMT_INT
            if bold:
                cell.font = style.TOTAL_FONT
                cell.fill = style.TOTAL_FILL
            continue

        if column.kind == "month":
            child_keys = [("week", key) for key in month_weeks[column.key]]
        else:
            child_keys = [("month", key) for key in quarter_months[column.key]]
        letters = [get_column_letter(positions[key]) for key in child_keys]
        formula = "=SUM(" + ",".join(f"{letter}{row}" for letter in letters) + ")"
        style.write_formula(ws, row, col, formula, fmt=style.NUM_FMT_INT,
                            fill=fill, bold=bold)

    quarter_letters = [
        get_column_letter(positions[("quarter", column.key)])
        for column in columns if column.kind == "quarter"
    ]
    total_formula = "=SUM(" + ",".join(f"{letter}{row}" for letter in quarter_letters) + ")"
    style.write_formula(ws, row, TOTAL_COL, total_formula, fmt=style.NUM_FMT_INT,
                        fill=fill, bold=bold)


def _counts(frame, grid):
    """Week key -> number of activities starting in that week."""
    counts = {}
    for index in frame["week_index"]:
        if index is None or (isinstance(index, float) and index != index):
            continue
        key = grid.weeks[int(index)].key
        counts[key] = counts.get(key, 0) + 1
    return counts


def _label_cell(ws, row, text, level, bold=False, hidden=False):
    cell = ws.cell(row=row, column=LABEL_COL, value=text)
    cell.border = style.THIN_BORDER
    if bold:
        cell.font = style.TOTAL_FONT
        cell.fill = style.TOTAL_FILL
    ws.row_dimensions[row].outline_level = level
    if hidden:
        ws.row_dimensions[row].hidden = True


def build_calendar(wb, scope, config):
    ws = wb.create_sheet(SHEET_NAME)
    grid = scope.grid
    columns = grid.columns()
    positions = _column_positions(columns)
    month_weeks, quarter_months = _children(columns, grid)

    ws.sheet_properties.outlinePr.summaryRight = False
    ws.sheet_properties.outlinePr.summaryBelow = False

    # --- header -------------------------------------------------------------
    ws.merge_cells(start_row=1, start_column=LABEL_COL, end_row=2, end_column=LABEL_COL)
    ws.merge_cells(start_row=1, start_column=TOTAL_COL, end_row=2, end_column=TOTAL_COL)
    style.write_header_row(ws, 1, ["Scope / activity", "Total"])
    for column in columns:
        col = positions[(column.kind, column.key)]
        style.write_header_row(ws, 1, [column.label], col_start=col)
        style.write_header_row(ws, 2, [column.sublabel], col_start=col)
        letter = get_column_letter(col)
        ws.column_dimensions[letter].outline_level = column.level
        ws.column_dimensions[letter].hidden = column.level > 0
        ws.column_dimensions[letter].width = 11 if column.kind == "week" else 13

    if scope.frame.empty:
        style.note_missing(ws, "No activities in scope for the configured criteria")
        style.finalize_sheet(ws, freeze="C3", widths={"A": 52, "B": 12})
        return

    row = FIRST_DATA_ROW
    bar_ranges = []

    # --- all activities -----------------------------------------------------
    _label_cell(ws, row, "ALL ACTIVITIES", level=0, bold=True)
    _write_grid_row(ws, row, _counts(scope.frame, grid), columns, positions,
                    month_weeks, quarter_months, bold=True)
    row += 1

    def write_value_row(label, subset, level, hidden):
        nonlocal row
        _label_cell(ws, row, label, level=level, hidden=hidden)
        _write_grid_row(ws, row, _counts(subset, grid), columns, positions,
                        month_weeks, quarter_months)
        value_row = row
        row += 1
        if config.detail_rows:
            ordered = subset.sort_values("start_day", kind="stable")
            for _, activity in ordered.iterrows():
                _label_cell(ws, row, f"  {activity.get('activity_name') or 'Untitled'}",
                            level=level + 1, hidden=True)
                week_key = grid.weeks[int(activity["week_index"])].key
                _write_grid_row(ws, row, {week_key: 1}, columns, positions,
                                month_weeks, quarter_months)
                row += 1
        return value_row

    # --- reach: a partition, so its header is a genuine SUM ------------------
    _label_cell(ws, row, "BY REACH", level=0, bold=True)
    header_row = row
    row += 1
    member_rows = []
    for bucket in REACH_ORDER:
        subset = scope.frame[scope.frame["reach"] == bucket]
        if subset.empty:
            continue
        member_rows.append(write_value_row(bucket, subset, level=1, hidden=True))
    _sum_down(ws, header_row, member_rows, columns, positions)
    bar_ranges.append(member_rows)

    # --- breakdown fields: overlapping, so a distinct count -----------------
    for field in config.breakdown_fields:
        if field not in scope.frame.columns:
            continue
        title = f"BY {FIELD_TITLES.get(field, field.upper())} — multiple values possible"
        _label_cell(ws, row, title, level=0, bold=True)
        header_row = row
        row += 1
        values = {}
        for _, activity in scope.frame.iterrows():
            names = split_multi(activity.get(field)) or [NOT_SPECIFIED]
            for name in names:
                values.setdefault(name, []).append(activity.name)
        member_rows = []
        for name in sorted(values, key=lambda n: (n == NOT_SPECIFIED, n)):
            subset = scope.frame.loc[values[name]]
            member_rows.append(write_value_row(name, subset, level=1, hidden=True))
        _distinct_count(ws, header_row, len(scope.frame), columns, positions,
                        month_weeks, quarter_months, scope, grid)
        bar_ranges.append(member_rows)

    for member_rows in bar_ranges:
        if not member_rows:
            continue
        sqref = " ".join(f"B{r}" for r in member_rows)
        ws.conditional_formatting.add(sqref, DataBarRule(
            start_type="num", start_value=0, end_type="max",
            color=style.GRAY_IV, showValue=True))

    style.finalize_sheet(ws, freeze="C3", widths={"A": 52, "B": 12})


def _sum_down(ws, header_row, member_rows, columns, positions):
    """Valid only for a partition: the reach block."""
    targets = [TOTAL_COL] + [positions[(c.kind, c.key)] for c in columns]
    for col in targets:
        letter = get_column_letter(col)
        formula = "=SUM(" + ",".join(f"{letter}{r}" for r in member_rows) + ")" \
            if member_rows else "=0"
        style.write_formula(ws, header_row, col, formula, fmt=style.NUM_FMT_INT,
                            fill=style.TOTAL_FILL, bold=True)


def _distinct_count(ws, header_row, total, columns, positions, month_weeks,
                    quarter_months, scope, grid):
    """Overlapping block: distinct activities, computed here, never summed."""
    _write_grid_row(ws, header_row, _counts(scope.frame, grid), columns, positions,
                    month_weeks, quarter_months, bold=True)
    cell = ws.cell(row=header_row, column=TOTAL_COL, value=total)
    cell.font = style.TOTAL_FONT
    cell.fill = style.TOTAL_FILL
    cell.number_format = style.NUM_FMT_INT
    cell.border = style.THIN_BORDER
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_report_calendar_sheet.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Open the file in Excel and check the outline controls**

Write a scratch workbook and open it:

```bash
PYTHONPATH=. .venv/bin/python -c "
from datetime import date
from openpyxl import Workbook
from pipeline.report.config import ReportConfig
from pipeline.report.calendar_sheet import build_calendar
from tests.report_fixtures import load_fixture_scope
import tempfile, pathlib
tmp = pathlib.Path(tempfile.mkdtemp())
cfg = ReportConfig(date_from=date(2025,1,1), date_to=date(2025,12,31))
wb = Workbook(); wb.remove(wb.active)
build_calendar(wb, load_fixture_scope(tmp, cfg), cfg)
out = tmp / 'calendar_check.xlsx'; wb.save(out); print(out)
"
```

Expected: the file opens without a repair prompt; the sheet shows four quarter
columns and a handful of bold block rows; the `+` controls in the column margin
sit to the **left** of each group; expanding a quarter reveals its months, and a
month its weeks.

- [ ] **Step 6: Commit**

```bash
git add pipeline/report/calendar_sheet.py tests/test_report_calendar_sheet.py
git commit -m "Lay the year out as a matrix that opens one level at a time"
```

---

### Task 9: Metrics for the flat sheets

The figures the four table sheets present, computed and tested separately from
their presentation.

**Files:**
- Create: `pipeline/report/metrics.py`
- Test: `tests/test_report_metrics.py`

**Interfaces:**
- Produces: `load_stats(scope) -> dict` with keys `median_per_week`, `peak_week_label`, `peak_week_count`, `zero_weeks`, `longest_zero_run`, `top5_share`
- Produces: `lead_time_stats(frame) -> dict` with keys `counted`, `median_days`, `short_notice`, `min_days`, `max_days`
- Produces: `pack_stats(frame) -> dict` with keys `with_pack`, `without_pack`, `packs`, `singleton_packs`, `small_packs`, `medium_packs`, `oversized_packs`, `largest_pack`
- Produces: `field_completeness(scope) -> list[tuple[str, int, int]]` — `(field, filled, missing)`
- Produces: `anomalies(frame) -> list[tuple[str, int]]`

- [ ] **Step 1: Write the failing test**

Create `tests/test_report_metrics.py`:

```python
"""The figures behind the flat sheets."""

from datetime import date

import pytest

pytest.importorskip("pandas")

from pipeline.report import metrics
from pipeline.report.config import ReportConfig
from tests.report_fixtures import load_fixture_scope


def _scope(tmp_path):
    return load_fixture_scope(tmp_path, ReportConfig(
        date_from=date(2025, 1, 1), date_to=date(2025, 12, 31)))


def test_load_stats_finds_the_peak_and_the_empty_weeks(tmp_path):
    scope = _scope(tmp_path)

    stats = metrics.load_stats(scope)

    assert stats["peak_week_count"] >= 1
    assert stats["zero_weeks"] > 0
    assert stats["longest_zero_run"] >= 1
    assert 0 <= stats["top5_share"] <= 1


def test_load_stats_on_an_empty_scope_does_not_divide_by_zero(tmp_path):
    scope = _scope(tmp_path)
    scope.frame = scope.frame.iloc[0:0]

    stats = metrics.load_stats(scope)

    assert stats["peak_week_count"] == 0
    assert stats["top5_share"] == 0
    assert stats["median_per_week"] == 0


def test_lead_time_counts_only_rows_with_both_dates(tmp_path):
    scope = _scope(tmp_path)

    stats = metrics.lead_time_stats(scope.frame)

    assert stats["counted"] == int(scope.frame["lead_time_days"].notna().sum())
    assert stats["median_days"] is not None


def test_pack_stats_size_the_buckets(tmp_path):
    scope = _scope(tmp_path)

    stats = metrics.pack_stats(scope.frame)

    assert stats["with_pack"] + stats["without_pack"] == len(scope.frame)
    assert stats["packs"] >= 1
    assert stats["largest_pack"] >= 1


def test_field_completeness_lists_filled_and_missing_per_field(tmp_path):
    scope = _scope(tmp_path)

    rows = metrics.field_completeness(scope)

    by_field = {name: (filled, missing) for name, filled, missing in rows}
    assert "channel" in by_field
    filled, missing = by_field["channel"]
    assert filled + missing == len(scope.frame)
    assert missing >= 1  # the fixture's incomplete record


def test_anomalies_report_the_undated_and_the_blank_tracking_ids(tmp_path):
    scope = _scope(tmp_path)

    names = dict(metrics.anomalies(scope.frame))

    assert "End date before start date" in names
    assert "Archived" in names
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_report_metrics.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pipeline.report.metrics'`

- [ ] **Step 3: Write the implementation**

Create `pipeline/report/metrics.py`:

```python
"""Figures for the flat sheets, computed apart from how they are presented.

Order statistics (median, min, max, longest run) are literals in the workbook:
an Excel formula for them would need the underlying series on the sheet, which
these sheets do not carry. Everything derived from two figures already on the
sheet stays a formula, written by the sheet builder.
"""

import statistics

from pipeline.report.config import SHORT_NOTICE_DAYS
from pipeline.report.data import _is_blank
from pipeline.report.derive import split_multi


def _week_counts(scope):
    counts = [0] * len(scope.grid.weeks)
    for index in scope.frame["week_index"]:
        if index is None or (isinstance(index, float) and index != index):
            continue
        counts[int(index)] += 1
    return counts


def load_stats(scope):
    counts = _week_counts(scope)
    total = sum(counts)
    if not counts or total == 0:
        return {"median_per_week": 0, "peak_week_label": "—", "peak_week_count": 0,
                "zero_weeks": len(counts), "longest_zero_run": len(counts),
                "top5_share": 0}

    peak_index = max(range(len(counts)), key=lambda i: counts[i])
    peak_week = scope.grid.weeks[peak_index]

    longest = current = 0
    for count in counts:
        current = current + 1 if count == 0 else 0
        longest = max(longest, current)

    top5 = sum(sorted(counts, reverse=True)[:5])
    return {
        "median_per_week": statistics.median(counts),
        "peak_week_label": f"{peak_week.label} ({peak_week.sublabel})",
        "peak_week_count": counts[peak_index],
        "zero_weeks": sum(1 for c in counts if c == 0),
        "longest_zero_run": longest,
        "top5_share": top5 / total,
    }


def lead_time_stats(frame):
    days = [int(d) for d in frame["lead_time_days"].dropna()]
    if not days:
        return {"counted": 0, "median_days": None, "short_notice": 0,
                "min_days": None, "max_days": None}
    return {
        "counted": len(days),
        "median_days": int(statistics.median(days)),
        "short_notice": sum(1 for d in days if d < SHORT_NOTICE_DAYS),
        "min_days": min(days),
        "max_days": max(days),
    }


def pack_stats(frame):
    """Size the pack buckets. An oversized pack is the data problem, quantified."""
    ids = frame.get("communication_pack_cpid")
    if ids is None:
        return {"with_pack": 0, "without_pack": len(frame), "packs": 0,
                "singleton_packs": 0, "small_packs": 0, "medium_packs": 0,
                "oversized_packs": 0, "largest_pack": 0}

    blank = _is_blank(ids)
    sizes = {}
    for value in ids[~blank]:
        key = str(value).strip()
        sizes[key] = sizes.get(key, 0) + 1

    counts = list(sizes.values())
    return {
        "with_pack": int((~blank).sum()),
        "without_pack": int(blank.sum()),
        "packs": len(sizes),
        "singleton_packs": sum(1 for c in counts if c == 1),
        "small_packs": sum(1 for c in counts if 2 <= c <= 10),
        "medium_packs": sum(1 for c in counts if 11 <= c <= 50),
        "oversized_packs": sum(1 for c in counts if c > 50),
        "largest_pack": max(counts, default=0),
    }


REPORTED_FIELDS = (
    "activity_name", "start_date", "end_date", "channel", "priority", "lead",
    "lead_team", "target_audience", "strategic_objectives", "activity_description",
    "business_division", "region", "audience", "bod_geb", "communication_pack_cpid",
)


def field_completeness(scope):
    rows = []
    for name in REPORTED_FIELDS:
        if name not in scope.frame.columns:
            continue
        blank = _is_blank(scope.frame[name])
        rows.append((name, int((~blank).sum()), int(blank.sum())))
    return rows


def anomalies(frame):
    import pandas as pd

    start = pd.to_datetime(frame.get("start_date"), errors="coerce")
    end = pd.to_datetime(frame.get("end_date"), errors="coerce")
    tracking = frame.get("tracking_id")
    archived = frame.get("is_archived")
    return [
        ("End date before start date", int((end < start).sum())),
        ("Missing end date", int(end.isna().sum())),
        ("Blank tracking ID", int(_is_blank(tracking).sum()) if tracking is not None else 0),
        ("Duplicate tracking ID",
         int(len(frame) - frame["tracking_id"].nunique()) if tracking is not None else 0),
        ("Archived", int(archived.fillna(False).astype(bool).sum()) if archived is not None else 0),
    ]
```

The `split_multi` import is used by the sheet builders that group by a
multi-valued field; drop it from this module's imports if your editor flags it
as unused here.

- [ ] **Step 4: Run the test to verify it passes**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_report_metrics.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add pipeline/report/metrics.py tests/test_report_metrics.py
git commit -m "Compute the planner figures apart from how they are shown"
```

---

### Task 10: Executive Summary and Glossary sheets

**Files:**
- Create: `pipeline/report/table_sheets.py`
- Test: `tests/test_report_summary_sheet.py`

**Interfaces:**
- Consumes: `Scope`, `ReportConfig`, `metrics`, `style`.
- Produces: `build_executive_summary(wb, scope, config) -> None` — sheet `Executive Summary`, tab colour `style.BRONZE_I`.
- Produces: `build_glossary(wb, scope, config) -> None` — sheet `Glossary`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_report_summary_sheet.py`:

```python
"""The summary carries the criteria, the volume, the load and the caveats."""

from datetime import date

import pytest

pytest.importorskip("openpyxl")
from openpyxl import Workbook

from pipeline.report.config import ReportConfig
from pipeline.report.table_sheets import build_executive_summary, build_glossary
from tests.report_fixtures import load_fixture_scope


def _build(tmp_path, builder):
    config = ReportConfig(date_from=date(2025, 1, 1), date_to=date(2025, 12, 31))
    scope = load_fixture_scope(tmp_path, config)
    wb = Workbook()
    wb.remove(wb.active)
    builder(wb, scope, config)
    return wb.worksheets[0], scope


def _pairs(ws):
    return {ws.cell(row=r, column=1).value: ws.cell(row=r, column=2).value
            for r in range(1, ws.max_row + 1)}


def test_the_summary_states_the_applied_criteria(tmp_path):
    ws, _ = _build(tmp_path, build_executive_summary)
    pairs = _pairs(ws)

    assert pairs["Period"] == "2025-01-01 to 2025-12-31"
    assert pairs["Senior executives"] == "any"


def test_the_summary_names_every_source_file(tmp_path):
    ws, scope = _build(tmp_path, build_executive_summary)
    text = "\n".join(str(ws.cell(row=r, column=2).value) for r in range(1, ws.max_row + 1))

    for _, name in scope.source_files:
        assert name in text


def test_the_summary_reports_what_each_criterion_excluded(tmp_path):
    ws, _ = _build(tmp_path, build_executive_summary)
    pairs = _pairs(ws)

    assert pairs["Excluded: no start date"] == 1
    assert pairs["Excluded: date window"] == 1


def test_shares_are_formulas_not_baked_numbers(tmp_path):
    ws, _ = _build(tmp_path, build_executive_summary)
    labels = [str(ws.cell(row=r, column=1).value) for r in range(1, ws.max_row + 1)]

    assert any(label.startswith("=TEXT(IF(") for label in labels)


def test_the_summary_reports_load_and_discipline(tmp_path):
    ws, _ = _build(tmp_path, build_executive_summary)
    pairs = _pairs(ws)

    assert "Peak week" in pairs
    assert "Weeks with no activity" in pairs
    assert "Median lead time (days)" in pairs


def test_the_glossary_records_the_counting_rule_and_the_pack_caveat(tmp_path):
    ws, _ = _build(tmp_path, build_glossary)
    text = "\n".join(
        f"{ws.cell(row=r, column=1).value} {ws.cell(row=r, column=2).value}"
        for r in range(1, ws.max_row + 1)
    )

    assert "Thursday" in text
    assert "start date" in text.lower()
    assert "pack" in text.lower()
    assert "studio" in text.lower()
    assert ws.sheet_view.showGridLines is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_report_summary_sheet.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pipeline.report.table_sheets'`

- [ ] **Step 3: Write the implementation**

Create `pipeline/report/table_sheets.py` with the two builders (the remaining
three follow in Tasks 11–13, in the same file):

```python
"""The flat sheets: summary, data quality, audience, mix, activities, glossary.

The calendar lives in its own module; this file holds the six sheets that are
label/value lists and tables. They share the style primitives, so adding a block
is a handful of lines rather than a new layout.
"""

from openpyxl.utils import get_column_letter

from pipeline.report import metrics, style
from pipeline.report.config import (
    AUDIENCE_BANDS,
    BAND_UNKNOWN,
    LARGE_AUDIENCE_BANDS,
    SHORT_NOTICE_DAYS,
)
from pipeline.report.data import EXCLUSION_ORDER
from pipeline.report.derive import (
    GLOBAL_REGION_TOKENS,
    GROUP_WIDE_MIN_DIVISIONS,
    REACH_ORDER,
)


def _share_label(total_row, value_row, text):
    """The share rides in the label so the value column stays a column of counts."""
    return f'=TEXT(IF(B${total_row}=0,0,B{value_row}/B${total_row}),"0%") & "  {text}"'


def build_executive_summary(wb, scope, config):
    ws = wb.create_sheet("Executive Summary")
    ws.sheet_properties.tabColor = style.BRONZE_I
    frame = scope.frame
    row = 1

    row = style.write_section_header(ws, row, "REPORT", 2)
    for label, value in config.describe():
        row = style.write_kpi_row(ws, row, label, value)
    row = style.write_kpi_row(ws, row, "Weeks covered", len(scope.grid.weeks))
    for key, name in scope.source_files:
        row = style.write_kpi_row(ws, row, f"Source: {key}", name)
    row = style.write_kpi_row(ws, row, "Rows read", scope.rows_read)
    for reason in EXCLUSION_ORDER:
        row = style.write_kpi_row(ws, row, f"Excluded: {reason}", scope.excluded[reason])
    row = style.write_kpi_row(ws, row, "Activities in scope", len(frame))
    row += 1

    row = style.write_section_header(ws, row, "VOLUME", 2)
    total_row = row
    row = style.write_kpi_row(ws, row, "Activities in scope", len(frame))
    for source_type in ("internal", "external"):
        count = int((frame.get("source_type") == source_type).sum()) if len(frame) else 0
        ws.cell(row=row, column=1, value=_share_label(total_row, row, source_type.title()))
        ws.cell(row=row, column=1).font = style.SUB_FONT
        style.write_kpi_row(ws, row, None, count)
        ws.cell(row=row, column=2).font = style.SUB_FONT
        row += 1
    for bucket in REACH_ORDER:
        count = int((frame.get("reach") == bucket).sum()) if len(frame) else 0
        ws.cell(row=row, column=1, value=_share_label(total_row, row, bucket))
        ws.cell(row=row, column=1).font = style.SUB_FONT
        style.write_kpi_row(ws, row, None, count)
        ws.cell(row=row, column=2).font = style.SUB_FONT
        row += 1
    row += 1

    stats = metrics.load_stats(scope)
    row = style.write_section_header(ws, row, "LOAD", 2)
    row = style.write_kpi_row(ws, row, "Median activities per week",
                              stats["median_per_week"], fmt=style.NUM_FMT_RATIO)
    row = style.write_kpi_row(ws, row, "Peak week", stats["peak_week_label"])
    row = style.write_kpi_row(ws, row, "Activities in the peak week", stats["peak_week_count"])
    row = style.write_kpi_row(ws, row, "Weeks with no activity", stats["zero_weeks"])
    row = style.write_kpi_row(ws, row, "Longest run of empty weeks", stats["longest_zero_run"])
    row = style.write_kpi_row(ws, row, "Share in the five busiest weeks",
                              stats["top5_share"], fmt=style.NUM_FMT_PCT)
    row += 1

    row = style.write_section_header(ws, row, "LEADERSHIP & AUDIENCE", 2)
    exec_total = row
    executives = int(frame["has_executives"].sum()) if len(frame) else 0
    row = style.write_kpi_row(ws, row, "With senior-executive involvement", executives)
    large = int(frame["audience_band"].isin(LARGE_AUDIENCE_BANDS).sum()) if len(frame) else 0
    row = style.write_kpi_row(ws, row, "Large audience (top two bands)", large)
    unknown = int((frame["audience_band"] == BAND_UNKNOWN).sum()) if len(frame) else 0
    row = style.write_kpi_row(ws, row, "Audience band unknown", unknown)
    style.write_formula(ws, exec_total, 3,
                        f"=IF(B${total_row}=0,0,B{exec_total}/B${total_row})",
                        fmt=style.NUM_FMT_PCT)
    row += 1

    lead = metrics.lead_time_stats(frame) if len(frame) else {
        "counted": 0, "median_days": None, "short_notice": 0}
    row = style.write_section_header(ws, row, "PLANNING DISCIPLINE", 2)
    row = style.write_kpi_row(ws, row, "Median lead time (days)",
                              lead["median_days"] if lead["median_days"] is not None else "—")
    row = style.write_kpi_row(ws, row,
                              f"Planned at under {SHORT_NOTICE_DAYS} days' notice",
                              lead["short_notice"])
    row = style.write_kpi_row(ws, row, "Lead time not measurable",
                              len(frame) - lead["counted"])
    row += 1

    packs = metrics.pack_stats(frame) if len(frame) else {"without_pack": 0}
    row = style.write_section_header(ws, row, "DATA QUALITY", 2)
    median_completeness = int(frame["completeness"].median()) if len(frame) else 0
    row = style.write_kpi_row(ws, row, "Median planning completeness (%)", median_completeness)
    row = style.write_kpi_row(ws, row, "Without a pack link", packs["without_pack"])

    style.finalize_sheet(ws, freeze="A2", widths={"A": 44, "B": 24, "C": 12})


GLOSSARY_SECTIONS = (
    ("SCOPE", (
        ("In scope", "Activities whose start date falls inside the configured window and "
                     "that pass the senior-executive and audience-band criteria. All three "
                     "are hard filters: a row that fails any of them is absent from every sheet."),
        ("Source", "The SharePoint CSV exports in the OneDrive sync folder, internal and "
                   "external, active and archive lists merged and de-duplicated by tracking ID."),
        ("Not included", "Activities created only in the planning studio. They live in the "
                         "local database and are never written back to the source system, so "
                         "they are invisible to this report."),
    )),
    ("TIME", (
        ("Counting rule", "Each activity is counted once, in the ISO week of its start date. "
                          "Nothing is spread across an activity's runtime: a figure that is "
                          "also a duration cannot be summed."),
        ("Week to month", "A week belongs to the month containing its Thursday (ISO 8601). "
                          "A full-year window therefore carries a thirteenth month column for "
                          "the last days of December, which belong to the next year's week 1."),
        ("Aggregation", "Month, quarter and total cells are SUM formulas over the cells they "
                        "aggregate, so the grid cannot contradict its own totals."),
    )),
    ("DIMENSIONS", (
        ("Group-wide", f"Names {GROUP_WIDE_MIN_DIVISIONS} or more business divisions, or a "
                       f"global region ({', '.join(sorted(GLOBAL_REGION_TOKENS))})."),
        ("Multi-division", "Names two business divisions."),
        ("Single division", "Names exactly one business division."),
        ("Regional only", "Names no division but at least one region."),
        ("Unclassified", "Names neither a division nor a region. Kept visible rather than "
                         "folded into a neighbouring bucket."),
        ("Overlap", "The reach buckets partition the portfolio and sum to the total. The "
                    "division and region blocks do not: an activity naming two divisions "
                    "appears in both rows, so those block totals are distinct counts."),
    )),
    ("MEASURES", (
        ("Audience band", "Mapped from the source audience field, which carries raw counts in "
                          "some exports and band labels in others. Whether that field records "
                          "the estimated audience size is an assumption still to be verified "
                          "against the source system."),
        ("Senior executives", "The source system's executive-involvement field carries a "
                              "value after HTML is stripped."),
        ("Lead time", "Days between the record's creation date and its start date. Rows "
                      "missing either date are not counted."),
        ("Planning completeness", "Share of the fields the entry form requires that carry a "
                                  "value. Fields the CSV export does not carry are excluded "
                                  "from the denominator and listed on the Data Quality sheet."),
        ("Packs", "Never a grouping dimension in this report. Source pack identifiers collapse "
                  "large parts of the portfolio into oversized buckets, so a pack-based "
                  "roll-up describes the portfolio rather than a planning unit. Pack coverage "
                  "is measured on the Data Quality sheet instead."),
    )),
)


def build_glossary(wb, scope, config):
    ws = wb.create_sheet("Glossary")
    ws.sheet_view.showGridLines = False
    row = 1
    for title, terms in GLOSSARY_SECTIONS:
        row = style.write_section_header(ws, row, title, 2)
        for term, definition in terms:
            style.write_kpi_row(ws, row, term, None)
            cell = ws.cell(row=row, column=2, value=definition)
            cell.font = style.BODY_FONT
            cell.alignment = cell.alignment.copy(wrap_text=True, vertical="top")
            row += 1
        row += 1

    if scope.skipped_completeness_fields:
        row = style.write_section_header(ws, row, "FIELDS NOT IN THIS EXPORT", 2)
        for name in scope.skipped_completeness_fields:
            row = style.write_kpi_row(
                ws, row, name,
                "Required by the entry form but not carried by the CSV export; "
                "excluded from the completeness denominator.")

    style.finalize_sheet(ws, freeze=None, widths={"A": 28, "B": 90})
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_report_summary_sheet.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add pipeline/report/table_sheets.py tests/test_report_summary_sheet.py
git commit -m "Open with the criteria and close with the caveats"
```

---

### Task 11: Data Quality sheet

**Files:**
- Modify: `pipeline/report/table_sheets.py`
- Test: `tests/test_report_quality_sheet.py`

**Interfaces:**
- Produces: `build_data_quality(wb, scope, config) -> None` — sheet `Data Quality`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_report_quality_sheet.py`:

```python
"""Data Quality turns the pack problem into a figure."""

from datetime import date

import pytest

pytest.importorskip("openpyxl")
from openpyxl import Workbook

from pipeline.report.config import ReportConfig
from pipeline.report.table_sheets import build_data_quality
from tests.report_fixtures import load_fixture_scope


def _sheet(tmp_path):
    config = ReportConfig(date_from=date(2025, 1, 1), date_to=date(2025, 12, 31))
    scope = load_fixture_scope(tmp_path, config)
    wb = Workbook()
    wb.remove(wb.active)
    build_data_quality(wb, scope, config)
    return wb["Data Quality"], scope


def _column_a(ws):
    return [ws.cell(row=r, column=1).value for r in range(1, ws.max_row + 1)]


def test_the_sheet_has_the_three_blocks(tmp_path):
    ws, _ = _sheet(tmp_path)
    labels = _column_a(ws)

    assert "FIELD COMPLETENESS" in labels
    assert "PACK COVERAGE" in labels
    assert "RECORD ANOMALIES" in labels


def test_field_rows_carry_a_missing_share_formula(tmp_path):
    ws, _ = _sheet(tmp_path)
    formulas = [ws.cell(row=r, column=4).value for r in range(1, ws.max_row + 1)]

    assert any(isinstance(v, str) and v.startswith("=IF(") for v in formulas)


def test_pack_coverage_names_the_oversized_bucket(tmp_path):
    ws, _ = _sheet(tmp_path)
    labels = [str(v) for v in _column_a(ws)]

    assert any("more than 50" in label for label in labels)
    assert any("exactly one" in label for label in labels)


def test_the_counts_add_up_to_the_scope(tmp_path):
    ws, scope = _sheet(tmp_path)
    rows = {ws.cell(row=r, column=1).value: r for r in range(1, ws.max_row + 1)}
    with_pack = ws.cell(row=rows["Activities with a pack link"], column=2).value
    without_pack = ws.cell(row=rows["Activities without a pack link"], column=2).value

    assert with_pack + without_pack == len(scope.frame)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_report_quality_sheet.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_data_quality'`

- [ ] **Step 3: Add the builder to `pipeline/report/table_sheets.py`**

```python
def build_data_quality(wb, scope, config):
    ws = wb.create_sheet("Data Quality")
    frame = scope.frame
    if frame.empty:
        style.note_missing(ws, "No activities in scope for the configured criteria")
        style.finalize_sheet(ws, freeze="A2")
        return

    row = style.write_section_header(ws, 1, "FIELD COMPLETENESS", 4)
    row = style.write_header_row(ws, row, ["Field", "Filled", "Missing", "% missing"])
    first = row
    for name, filled, missing in metrics.field_completeness(scope):
        style.write_data_rows(ws, row, [[name, filled, missing]])
        style.write_formula(ws, row, 4, f"=IF(B{row}+C{row}=0,0,C{row}/(B{row}+C{row}))",
                            fmt=style.NUM_FMT_PCT)
        row += 1
    style.write_data_rows(ws, row, [["Median completeness (%)",
                                     int(frame["completeness"].median())]])
    row += 2

    packs = metrics.pack_stats(frame)
    row = style.write_section_header(ws, row, "PACK COVERAGE", 4)
    row = style.write_header_row(ws, row, ["Measure", "Count", "", ""])
    pack_rows = [
        ("Activities with a pack link", packs["with_pack"]),
        ("Activities without a pack link", packs["without_pack"]),
        ("Distinct packs", packs["packs"]),
        ("Packs holding exactly one activity", packs["singleton_packs"]),
        ("Packs holding 2 to 10", packs["small_packs"]),
        ("Packs holding 11 to 50", packs["medium_packs"]),
        ("Packs holding more than 50", packs["oversized_packs"]),
        ("Largest pack", packs["largest_pack"]),
    ]
    row = style.write_data_rows(ws, row, [[label, value] for label, value in pack_rows])
    row += 1

    row = style.write_section_header(ws, row, "RECORD ANOMALIES", 4)
    row = style.write_header_row(ws, row, ["Anomaly", "Count", "", ""])
    row = style.write_data_rows(ws, row, [[label, count]
                                          for label, count in metrics.anomalies(frame)])

    style.finalize_sheet(ws, freeze="A2", widths={"A": 40, "B": 14, "C": 14, "D": 14})
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_report_quality_sheet.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add pipeline/report/table_sheets.py tests/test_report_quality_sheet.py
git commit -m "Measure the pack problem instead of describing it"
```

---

### Task 12: Audience & Executives sheet

**Files:**
- Modify: `pipeline/report/table_sheets.py`
- Test: `tests/test_report_audience_sheet.py`

**Interfaces:**
- Produces: `build_audience(wb, scope, config) -> None` — sheet `Audience & Executives`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_report_audience_sheet.py`:

```python
"""Audience bands and executive involvement, by period and by division."""

from datetime import date

import pytest

pytest.importorskip("openpyxl")
from openpyxl import Workbook

from pipeline.report.config import AUDIENCE_BANDS, BAND_UNKNOWN, ReportConfig
from pipeline.report.table_sheets import build_audience
from tests.report_fixtures import load_fixture_scope


def _sheet(tmp_path):
    config = ReportConfig(date_from=date(2025, 1, 1), date_to=date(2025, 12, 31))
    scope = load_fixture_scope(tmp_path, config)
    wb = Workbook()
    wb.remove(wb.active)
    build_audience(wb, scope, config)
    return wb["Audience & Executives"], scope


def _column_a(ws):
    return [str(ws.cell(row=r, column=1).value) for r in range(1, ws.max_row + 1)]


def test_every_band_gets_a_row_including_unknown(tmp_path):
    ws, _ = _sheet(tmp_path)
    labels = _column_a(ws)

    for band in AUDIENCE_BANDS:
        assert band in labels
    assert BAND_UNKNOWN in labels


def test_the_band_table_totals_are_formulas(tmp_path):
    ws, _ = _sheet(tmp_path)
    row = _column_a(ws).index(AUDIENCE_BANDS[0]) + 1
    last_column = ws.max_column

    assert str(ws.cell(row=row, column=last_column - 1).value).startswith("=SUM(")
    assert str(ws.cell(row=row, column=last_column).value).startswith("=IF(")


def test_the_sheet_reports_executives_by_quarter_and_by_division(tmp_path):
    ws, _ = _sheet(tmp_path)
    labels = _column_a(ws)

    assert "SENIOR EXECUTIVES BY QUARTER" in labels
    assert "SENIOR EXECUTIVES BY DIVISION" in labels


def test_division_rows_report_the_share_of_that_divisions_own_volume(tmp_path):
    ws, _ = _sheet(tmp_path)
    headers = [str(ws.cell(row=r, column=4).value) for r in range(1, ws.max_row + 1)]

    assert any("of the division" in header for header in headers)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_report_audience_sheet.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_audience'`

- [ ] **Step 3: Add the builder to `pipeline/report/table_sheets.py`**

```python
def _quarter_label(quarter):
    return f"Q{quarter[1]} {quarter[0]}"


def build_audience(wb, scope, config):
    ws = wb.create_sheet("Audience & Executives")
    frame = scope.frame
    if frame.empty or "audience_band" not in frame.columns:
        style.note_missing(ws, "No audience data available (audience column missing)")
        style.finalize_sheet(ws, freeze="A2")
        return

    quarters = sorted({q for q in frame["_quarter"] if q is not None})
    headers = ["Audience band"] + [_quarter_label(q) for q in quarters] + ["Total", "% of total"]
    total_col = len(headers) - 1
    share_col = len(headers)

    row = style.write_section_header(ws, 1, "AUDIENCE BAND BY QUARTER", len(headers))
    row = style.write_header_row(ws, row, headers)
    first_row = row
    for band in list(AUDIENCE_BANDS) + [BAND_UNKNOWN]:
        counts = [int(((frame["audience_band"] == band) & (frame["_quarter"] == q)).sum())
                  for q in quarters]
        style.write_data_rows(ws, row, [[band] + counts])
        span = f"{get_column_letter(2)}{row}:{get_column_letter(total_col - 1)}{row}"
        style.write_formula(ws, row, total_col, f"=SUM({span})", fmt=style.NUM_FMT_INT)
        row += 1
    total_row = row
    for col in range(2, total_col + 1):
        letter = get_column_letter(col)
        style.write_formula(ws, total_row, col, f"=SUM({letter}{first_row}:{letter}{row - 1})",
                            fmt=style.NUM_FMT_INT, fill=style.TOTAL_FILL, bold=True)
    ws.cell(row=total_row, column=1, value="TOTAL").font = style.TOTAL_FONT
    for value_row in range(first_row, total_row):
        letter = get_column_letter(total_col)
        style.write_formula(
            ws, value_row, share_col,
            f"=IF({letter}${total_row}=0,0,{letter}{value_row}/{letter}${total_row})",
            fmt=style.NUM_FMT_PCT)
    style.write_formula(ws, total_row, share_col, "=1", fmt=style.NUM_FMT_PCT,
                        fill=style.TOTAL_FILL, bold=True)
    row = total_row + 2

    row = style.write_section_header(ws, row, "LARGE AUDIENCE BY MONTH", 4)
    row = style.write_header_row(ws, row, ["Month", "Large audience", "All activities",
                                           "Share of the month"])
    months = sorted({scope.grid.month_of(scope.grid.weeks[int(i)])
                     for i in frame["week_index"] if i == i and i is not None})
    for month in months:
        in_month = frame["week_index"].apply(
            lambda i: i == i and i is not None
            and scope.grid.month_of(scope.grid.weeks[int(i)]) == month)
        large = int((in_month & frame["audience_band"].isin(LARGE_AUDIENCE_BANDS)).sum())
        style.write_data_rows(ws, row, [
            [f"{month[0]}-{month[1]:02d}", large, int(in_month.sum())]])
        style.write_formula(ws, row, 4, f"=IF(C{row}=0,0,B{row}/C{row})",
                            fmt=style.NUM_FMT_PCT)
        row += 1
    row += 1

    row = style.write_section_header(ws, row, "SENIOR EXECUTIVES BY QUARTER", 4)
    row = style.write_header_row(ws, row, ["Quarter", "With executives", "All activities",
                                           "Share of the quarter"])
    for quarter in quarters:
        in_quarter = frame["_quarter"] == quarter
        style.write_data_rows(ws, row, [
            [_quarter_label(quarter),
             int((in_quarter & frame["has_executives"]).sum()),
             int(in_quarter.sum())]])
        style.write_formula(ws, row, 4, f"=IF(C{row}=0,0,B{row}/C{row})",
                            fmt=style.NUM_FMT_PCT)
        row += 1
    row += 1

    row = style.write_section_header(ws, row, "SENIOR EXECUTIVES BY DIVISION", 4)
    row = style.write_header_row(ws, row, ["Division", "With executives",
                                           "All activities", "Share of the division"])
    divisions = {}
    for index, activity in frame.iterrows():
        for name in (split_multi(activity.get("business_division")) or ["Not specified"]):
            divisions.setdefault(name, []).append(index)
    for name in sorted(divisions):
        subset = frame.loc[divisions[name]]
        style.write_data_rows(ws, row, [
            [name, int(subset["has_executives"].sum()), len(subset)]])
        style.write_formula(ws, row, 4, f"=IF(C{row}=0,0,B{row}/C{row})",
                            fmt=style.NUM_FMT_PCT)
        row += 1

    style.finalize_sheet(ws, freeze="B3", widths={"A": 26})
```

Add `split_multi` to the imports at the top of `table_sheets.py`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_report_audience_sheet.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add pipeline/report/table_sheets.py tests/test_report_audience_sheet.py
git commit -m "Show who is being reached and how often leaders are on the hook"
```

---

### Task 13: Mix & Lead Time sheet and Activities sheet

**Files:**
- Modify: `pipeline/report/table_sheets.py`
- Test: `tests/test_report_mix_sheet.py`

**Interfaces:**
- Produces: `build_mix(wb, scope, config) -> None` — sheet `Mix & Lead Time`.
- Produces: `build_activities(wb, scope, config) -> None` — sheet `Activities`.
- Produces: `ACTIVITY_COLUMNS: tuple[tuple[str, str], ...]` — `(field, header)` pairs.

- [ ] **Step 1: Write the failing test**

Create `tests/test_report_mix_sheet.py`:

```python
"""Mix over time, lead time by division, and the traceable detail list."""

from datetime import date

import pytest

pytest.importorskip("openpyxl")
from openpyxl import Workbook

from pipeline.report.config import ReportConfig
from pipeline.report.table_sheets import ACTIVITY_COLUMNS, build_activities, build_mix
from tests.report_fixtures import load_fixture_scope


def _build(tmp_path, builder, name):
    config = ReportConfig(date_from=date(2025, 1, 1), date_to=date(2025, 12, 31))
    scope = load_fixture_scope(tmp_path, config)
    wb = Workbook()
    wb.remove(wb.active)
    builder(wb, scope, config)
    return wb[name], scope


def _column_a(ws):
    return [str(ws.cell(row=r, column=1).value) for r in range(1, ws.max_row + 1)]


def test_mix_covers_channel_priority_and_source_type(tmp_path):
    ws, _ = _build(tmp_path, build_mix, "Mix & Lead Time")
    labels = _column_a(ws)

    assert "CHANNEL BY QUARTER" in labels
    assert "PRIORITY BY QUARTER" in labels
    assert "INTERNAL VS EXTERNAL BY QUARTER" in labels
    assert "LEAD TIME BY DIVISION" in labels


def test_the_delta_column_names_the_two_quarters_it_compares(tmp_path):
    ws, _ = _build(tmp_path, build_mix, "Mix & Lead Time")
    headers = [str(ws.cell(row=r, column=c).value)
               for r in range(1, ws.max_row + 1) for c in range(1, ws.max_column + 1)]

    assert any(h.startswith("Δ ") and "−" in h for h in headers)


def test_the_activities_sheet_lists_every_in_scope_row(tmp_path):
    ws, scope = _build(tmp_path, build_activities, "Activities")

    assert ws.max_row == len(scope.frame) + 1
    assert ws.auto_filter.ref is not None
    assert ws.freeze_panes == "A2"


def test_the_activities_sheet_carries_the_derived_columns(tmp_path):
    ws, _ = _build(tmp_path, build_activities, "Activities")
    headers = [ws.cell(row=1, column=c).value for c in range(1, ws.max_column + 1)]

    assert headers == [header for _, header in ACTIVITY_COLUMNS]
    assert "Reach" in headers
    assert "Audience band" in headers
    assert "Senior executives" in headers
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_report_mix_sheet.py -v`
Expected: FAIL with `ImportError: cannot import name 'ACTIVITY_COLUMNS'`

- [ ] **Step 3: Add both builders to `pipeline/report/table_sheets.py`**

```python
def _crosstab_block(ws, row, scope, title, field):
    """One label × quarter table with a Total and a first-to-last-quarter delta."""
    frame = scope.frame
    quarters = sorted({q for q in frame["_quarter"] if q is not None})
    if not quarters:
        return style.write_section_header(ws, row, f"{title} — no data", 3)

    delta_header = f"Δ {_quarter_label(quarters[-1])} − {_quarter_label(quarters[0])}"
    headers = ["Value"] + [_quarter_label(q) for q in quarters] + ["Total", delta_header]
    total_col = len(headers) - 1

    row = style.write_section_header(ws, row, title, len(headers))
    row = style.write_header_row(ws, row, headers)

    values = {}
    for index, activity in frame.iterrows():
        for name in (split_multi(activity.get(field)) or ["Not specified"]):
            values.setdefault(name, []).append(index)

    for name in sorted(values):
        subset = frame.loc[values[name]]
        counts = [int((subset["_quarter"] == q).sum()) for q in quarters]
        style.write_data_rows(ws, row, [[name] + counts])
        span = f"{get_column_letter(2)}{row}:{get_column_letter(total_col - 1)}{row}"
        style.write_formula(ws, row, total_col, f"=SUM({span})", fmt=style.NUM_FMT_INT)
        first = get_column_letter(2)
        last = get_column_letter(total_col - 1)
        style.write_formula(ws, row, total_col + 1, f"={last}{row}-{first}{row}",
                            fmt=style.NUM_FMT_INT)
        row += 1
    return row + 1


def build_mix(wb, scope, config):
    ws = wb.create_sheet("Mix & Lead Time")
    frame = scope.frame
    if frame.empty:
        style.note_missing(ws, "No activities in scope for the configured criteria")
        style.finalize_sheet(ws, freeze="A2")
        return

    row = _crosstab_block(ws, 1, scope, "CHANNEL BY QUARTER", "channel")
    row = _crosstab_block(ws, row, scope, "PRIORITY BY QUARTER", "priority")
    row = _crosstab_block(ws, row, scope, "INTERNAL VS EXTERNAL BY QUARTER", "source_type")

    row = style.write_section_header(ws, row, "LEAD TIME BY DIVISION", 6)
    row = style.write_header_row(ws, row, [
        "Division", "Measurable", "Median days",
        f"Under {SHORT_NOTICE_DAYS} days", "Share short notice", "Min / max days"])
    divisions = {}
    for index, activity in frame.iterrows():
        for name in (split_multi(activity.get("business_division")) or ["Not specified"]):
            divisions.setdefault(name, []).append(index)
    for name in sorted(divisions):
        stats = metrics.lead_time_stats(frame.loc[divisions[name]])
        span = "—" if stats["min_days"] is None else f"{stats['min_days']} / {stats['max_days']}"
        style.write_data_rows(ws, row, [[
            name, stats["counted"],
            stats["median_days"] if stats["median_days"] is not None else "—",
            stats["short_notice"], None, span]])
        style.write_formula(ws, row, 5, f"=IF(B{row}=0,0,D{row}/B{row})",
                            fmt=style.NUM_FMT_PCT)
        row += 1

    style.finalize_sheet(ws, freeze="B3", widths={"A": 30})


ACTIVITY_COLUMNS = (
    ("tracking_id", "Tracking ID"),
    ("activity_name", "Activity"),
    ("source_type", "Type"),
    ("channel", "Channel"),
    ("start_date", "Start"),
    ("end_date", "End"),
    ("_iso_week", "ISO week"),
    ("_quarter_label", "Quarter"),
    ("priority", "Priority"),
    ("lead", "Lead"),
    ("lead_team", "Lead team"),
    ("target_audience", "Target audience"),
    ("audience_band", "Audience band"),
    ("business_division", "Divisions"),
    ("region", "Regions"),
    ("reach", "Reach"),
    ("_executives", "Senior executives"),
    ("communication_pack_cpid", "Pack ID"),
    ("campaign", "Campaign"),
    ("strategic_objectives", "Communications pillars"),
    ("completeness", "Completeness %"),
    ("lead_time_days", "Lead time (days)"),
    ("is_archived", "Archived"),
)


def build_activities(wb, scope, config):
    ws = wb.create_sheet("Activities")
    frame = scope.frame
    style.write_header_row(ws, 1, [header for _, header in ACTIVITY_COLUMNS])
    if frame.empty:
        style.finalize_sheet(ws, freeze="A2")
        return

    rows = []
    for _, activity in frame.iterrows():
        index = activity["week_index"]
        week = scope.grid.weeks[int(index)] if index == index and index is not None else None
        quarter = activity["_quarter"]
        values = []
        for field, _ in ACTIVITY_COLUMNS:
            if field == "_iso_week":
                values.append(f"{week.iso_year}-{week.label}" if week else "")
            elif field == "_quarter_label":
                values.append(_quarter_label(quarter) if quarter else "")
            elif field == "_executives":
                values.append("Yes" if activity["has_executives"] else "No")
            elif field in ("start_date", "end_date"):
                value = activity.get(field)
                values.append(value.date() if hasattr(value, "date") else value)
            elif field == "lead_time_days":
                value = activity.get(field)
                values.append(int(value) if value == value and value is not None else None)
            else:
                value = activity.get(field)
                values.append("" if value is None or value != value else value)
        rows.append(values)

    date_columns = {
        i + 1: style.NUM_FMT_DATE
        for i, (field, _) in enumerate(ACTIVITY_COLUMNS)
        if field in ("start_date", "end_date")
    }
    style.write_data_rows(ws, 2, rows, fmt_map=date_columns)
    ws.auto_filter.ref = f"A1:{get_column_letter(len(ACTIVITY_COLUMNS))}{len(rows) + 1}"
    style.finalize_sheet(ws, freeze="A2")
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_report_mix_sheet.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add pipeline/report/table_sheets.py tests/test_report_mix_sheet.py
git commit -m "Track the mix over the year and keep every figure traceable"
```

---

### Task 14: The entry point

**Files:**
- Create: `pipeline/scripts/report_calendar.py`
- Modify: `README.md`
- Test: `tests/test_report_calendar_script.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `CONFIG: ReportConfig` — the editable block.
- Produces: `build_workbook(scope, config) -> Workbook`
- Produces: `default_output_path(config) -> Path`
- Produces: `build_parser() -> argparse.ArgumentParser` with `--out` and `--input-dir`
- Produces: `main(argv=None) -> int`

- [ ] **Step 1: Write the failing test**

Create `tests/test_report_calendar_script.py`:

```python
"""End to end: raw CSVs in, a seven-sheet workbook out."""

from datetime import date

import pytest

pytest.importorskip("openpyxl")
from openpyxl import load_workbook

import pipeline.scripts.report_calendar as report_calendar
from tests.report_fixtures import write_activity_csvs

EXPECTED_SHEETS = [
    "Executive Summary", "Calendar", "Data Quality",
    "Audience & Executives", "Mix & Lead Time", "Activities", "Glossary",
]


def test_the_script_writes_all_seven_sheets(tmp_path):
    write_activity_csvs(tmp_path / "input")
    out = tmp_path / "report.xlsx"

    code = report_calendar.main(["--input-dir", str(tmp_path / "input"), "--out", str(out)])

    assert code == 0
    assert out.exists()
    assert load_workbook(out).sheetnames == EXPECTED_SHEETS


def test_the_workbook_reopens_without_repair(tmp_path):
    write_activity_csvs(tmp_path / "input")
    out = tmp_path / "report.xlsx"
    report_calendar.main(["--input-dir", str(tmp_path / "input"), "--out", str(out)])

    wb = load_workbook(out)

    # Reading the calendar back proves the outline and merged-cell XML is valid.
    assert wb["Calendar"].cell(row=1, column=1).value == "Scope / activity"


def test_an_empty_input_directory_fails_loudly(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()

    code = report_calendar.main(["--input-dir", str(empty), "--out", str(tmp_path / "x.xlsx")])

    assert code == 1


def test_the_default_output_path_names_the_year(tmp_path):
    path = report_calendar.default_output_path(report_calendar.CONFIG)

    assert str(report_calendar.CONFIG.date_from.year) in path.name
    assert path.suffix == ".xlsx"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_report_calendar_script.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pipeline.scripts.report_calendar'`

- [ ] **Step 3: Write the implementation**

Create `pipeline/scripts/report_calendar.py`:

```python
"""Calendar report: the planning year as a collapsible .xlsx.

Reads the activity CSV exports straight from the OneDrive sync folder -- no
database, no API process, no sync run has to be up first.

Usage:
    python pipeline/scripts/report_calendar.py
    python pipeline/scripts/report_calendar.py --out /path/to/report.xlsx

Edit CONFIG below to change what the report covers. The three criteria are hard
filters: a row that fails any of them is absent from every sheet.
"""

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

from openpyxl import Workbook

SCRIPT_DIR = Path(__file__).resolve().parent
PIPELINE_DIR = SCRIPT_DIR.parent
REPO_DIR = PIPELINE_DIR.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from pipeline.report.calendar_sheet import build_calendar          # noqa: E402
from pipeline.report.config import ReportConfig                    # noqa: E402
from pipeline.report.data import build_scope                       # noqa: E402
from pipeline.report.table_sheets import (                         # noqa: E402
    build_activities,
    build_audience,
    build_data_quality,
    build_executive_summary,
    build_glossary,
    build_mix,
)
from pipeline.scripts.process_cplan import (                       # noqa: E402
    INPUT_FILES,
    find_input_dir,
    find_input_files,
    load_activities,
    log,
)

OUTPUT_DIR = PIPELINE_DIR / "output"


# ---------------------------------------------------------------------------
# CONFIGURATION -- this is the block to edit.
# ---------------------------------------------------------------------------
CONFIG = ReportConfig(
    date_from=date(2025, 1, 1),      # filters on start_date, inclusive
    date_to=date(2025, 12, 31),      # inclusive
    executives="any",                # "any" | "with" | "without"
    audience_bands=None,             # None = all bands; else e.g. ("50–100k", "> 100k")
    include_unknown_audience=True,   # applies only when audience_bands is set
    include_archived=True,           # archiving is a view-size workaround, not a status
    detail_rows=True,                # activity rows under each dimension value
    breakdown_fields=("business_division", "region"),
)
# ---------------------------------------------------------------------------


# Build order is reading order. The calendar is second: the summary frames it.
SHEET_BUILDERS = (
    build_executive_summary,
    build_calendar,
    build_data_quality,
    build_audience,
    build_mix,
    build_activities,
    build_glossary,
)


def build_workbook(scope, config):
    wb = Workbook()
    wb.remove(wb.active)
    for builder in SHEET_BUILDERS:
        log(f"  {builder.__name__.replace('build_', '').replace('_', ' ').title()}")
        builder(wb, scope, config)
    return wb


def default_output_path(config):
    stamp = datetime.now().strftime("%Y_%m_%d")
    return OUTPUT_DIR / f"CPLAN_calendar_{config.date_from.year}_{stamp}.xlsx"


def build_parser():
    parser = argparse.ArgumentParser(description="Generate the calendar .xlsx report")
    parser.add_argument("--out", type=str, default=None,
                        help="Output path (default: pipeline/output/CPLAN_calendar_<year>_<date>.xlsx)")
    parser.add_argument("--input-dir", type=str, default=None,
                        help="Read the CSV exports from here instead of discovering OneDrive")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    config = CONFIG

    log("CPLAN calendar report")
    input_dir = Path(args.input_dir) if args.input_dir else find_input_dir()
    files = find_input_files(input_dir)
    if not files:
        log(f"ERROR: no input files found in {input_dir}")
        log(f"Expected one of: {', '.join(INPUT_FILES.values())}")
        return 1

    load = load_activities(files)
    if load.frame.empty:
        log("ERROR: the input files contain no activities")
        return 1

    scope = build_scope(load, config)
    log(f"{len(scope.frame)} of {scope.rows_read} activities in scope")
    for reason, count in scope.excluded.items():
        if count:
            log(f"  excluded ({reason}): {count}")

    wb = build_workbook(scope, config)

    output_path = Path(args.out) if args.out else default_output_path(config)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    log(f"Done: {output_path} ({output_path.stat().st_size / 1024:.1f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_report_calendar_script.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Run the whole suite**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/ -q`
Expected: no failures.

- [ ] **Step 6: Generate a real workbook and open it**

```bash
PYTHONPATH=. .venv/bin/python -c "
from pathlib import Path; import tempfile
from tests.report_fixtures import write_activity_csvs
import pipeline.scripts.report_calendar as r
tmp = Path(tempfile.mkdtemp()); write_activity_csvs(tmp / 'input')
r.main(['--input-dir', str(tmp / 'input'), '--out', str(tmp / 'report.xlsx')])
print(tmp / 'report.xlsx')
"
```

Open the file. Expected: no repair prompt; seven tabs in the order above; the
Calendar opens showing four quarter columns and bold block rows; the `+`
controls sit left of each column group and above each row group; the Executive
Summary's share labels render as `12%  Internal` rather than as formula text.

- [ ] **Step 7: Add the prerequisite to `README.md`**

In the Prerequisites section, change:

```
pip install pandas duckdb pyarrow
```

to:

```
pip install pandas duckdb pyarrow openpyxl
```

and add below the Usage block:

```markdown
### Calendar report

```bash
# Generate the .xlsx planning report from the CSV exports (no database needed)
python pipeline/scripts/report_calendar.py
```

Edit the `CONFIG` block at the top of
[`pipeline/scripts/report_calendar.py`](pipeline/scripts/report_calendar.py) to
change the period, the senior-executive criterion and the audience-size
criterion. The design is documented in
[`docs/superpowers/specs/2026-07-30-calendar-report-design.md`](docs/superpowers/specs/2026-07-30-calendar-report-design.md).
```

- [ ] **Step 8: Check no brand name leaked**

Run a whole-word, case-insensitive `git grep -Inwi` for the employer's
three-letter name across the repository, excluding lock files. Do not write the
name into this document, into a script, or into a commit message in order to
search for it — that is itself the leak this step exists to catch.

Expected: no output.

- [ ] **Step 9: Commit**

```bash
git add pipeline/scripts/report_calendar.py tests/test_report_calendar_script.py README.md
git commit -m "Turn a year of activities into one workbook from one command"
```

---

## Self-Review Notes

**Spec coverage:** every spec section maps to a task — data source and the
`load_activities` refactor (Task 1), configuration (Task 2), the four derivations
(Tasks 3–4), filtering and the completeness caveat (Task 5), formatting
primitives (Task 6), fixtures (Task 7), the Calendar sheet's full layout contract
(Task 8), metrics (Task 9), the six flat sheets (Tasks 10–13), the entry point,
README and brand check (Task 14). The deferred Clashes sheet stays deferred.

**Naming consistency:** `Scope`, `Grid`, `Week`, `GridColumn`, `ActivityLoad`,
`ReportConfig`, `build_scope`, `build_grid`, `build_calendar`, `build_*` sheet
builders and `style.write_*` are used with the same signatures in every task that
references them. The frame's derived columns — `reach`, `audience_band`,
`has_executives`, `week_index`, `_quarter`, `priority_rank_value`,
`lead_time_days`, `completeness`, `start_day` — are introduced in Task 5 (with
`_quarter` added in Task 9) and only read afterwards.

**Removed during review:** a `crosstab` helper drafted into Task 9 that no sheet
builder ended up calling — Tasks 12 and 13 build their tables inline against the
`_quarter` column. Dead on arrival, so it is gone rather than shipped and
maintained.
