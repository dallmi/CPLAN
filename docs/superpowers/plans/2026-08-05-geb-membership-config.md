# GEB Membership Config Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local, gitignored list of GEB members lets the calendar report split the `bod_geb` field into a `BY GEB` and a `BY GEB-1` block; without the list the workbook is unchanged.

**Architecture:** A new pure-Python module `pipeline/report/membership.py` owns "who is on the GEB" — it reads the CSV, normalises both keys, answers `is_member`, and reports entries that matched nothing. `data.py` uses it to derive two new frame columns beside the existing `executives`; the calendar and audience sheets render one block per column. Everything is conditional on the file existing. The ETL gains positional email extraction so a person's name and email stay paired.

**Tech Stack:** Python 3.13, pandas, openpyxl, pytest. No new dependencies.

## Global Constraints

- **Never expand the abbreviation.** Labels read `GEB`, `GEB-1`, `GEB/GEB-1` and nothing longer, in the code and in the workbook alike. (`docs/superpowers/plans/2026-07-30-calendar-report.md`)
- **No real person names, no employer name, no absolute paths in committed files.** Tests and examples use synthetic names only.
- **Glossary definitions are capped at 110 characters** (`MAX_DEFINITION_CHARS`, `tests/test_report_summary_sheet.py`). Shorten the text; never raise the cap.
- **Excel forbids `/ \ ? * [ ] :` in sheet names.** No sheet may be named with a slash.
- **The check is both suites, always:** `.venv/bin/python -m pytest tests/ -q && node --test tests/*.test.js`. `node --test tests/` (without the glob) silently runs nothing.
- **`check.ps1` carries a marker per listed file.** None of the files in this plan are listed, so no marker needs bumping. Verify with `grep` before committing if that changes.
- **Python identifiers stay English and follow the ETL**, not the ORM.

---

### Task 1: The membership module and its config file

**Files:**
- Create: `pipeline/report/membership.py`
- Create: `geb-members.csv.example`
- Modify: `.gitignore`
- Test: `tests/test_report_membership.py`

**Interfaces:**
- Consumes: `pipeline.report.derive.person_name` (existing).
- Produces:
  - `MembershipError(ValueError)`
  - `Entry(email: str, name: str)` — frozen dataclass, both keys already normalised
  - `Membership(entries: tuple[Entry, ...])` with `__len__`, `is_member(name: str, email: str = "") -> bool`, `unmatched(people: Iterable[tuple[str, str]]) -> int`
  - `DEFAULT_FILENAME = "geb-members.csv"`
  - `load_membership(path) -> Membership | None` — `None` when the file does not exist
  - `normalise_name(value: str) -> str`, `normalise_email(value: str) -> str`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_report_membership.py
"""The GEB membership list: loading it, and matching people against it."""

import pytest

from pipeline.report.membership import (
    Membership,
    MembershipError,
    load_membership,
    normalise_email,
    normalise_name,
)


def _write(tmp_path, text):
    path = tmp_path / "geb-members.csv"
    path.write_text(text, encoding="utf-8")
    return path


def test_an_absent_file_is_not_an_error():
    """Every machine without the list must still produce a workbook."""
    assert load_membership("/nonexistent/geb-members.csv") is None


def test_a_member_matches_on_email(tmp_path):
    path = _write(tmp_path, 'email,name\nm1@example.invalid,"Placeholder-01, Anna"\n')
    members = load_membership(path)

    assert members.is_member("Someone Else", "m1@example.invalid") is True


def test_a_member_matches_on_name_alone(tmp_path):
    """The email path is unverified against the real export; the name path
    is what the pipeline demonstrably has today, so it must stand on its own.
    """
    path = _write(tmp_path, 'email,name\n,"Placeholder-01, Anna"\n')
    members = load_membership(path)

    assert members.is_member("Anna Placeholder-01", "") is True


def test_either_key_alone_is_sufficient(tmp_path):
    """A plain OR, not a precedence rule: a stale address in the list must not
    silently outrank a correct name.
    """
    path = _write(tmp_path, 'email,name\nold@example.invalid,"Placeholder-01, Anna"\n')
    members = load_membership(path)

    assert members.is_member("Anna Placeholder-01", "new@example.invalid") is True
    assert members.is_member("Someone Else", "old@example.invalid") is True
    assert members.is_member("Someone Else", "new@example.invalid") is False


def test_last_first_and_first_last_compare_equal(tmp_path):
    path = _write(tmp_path, 'email,name\n,"Placeholder-01, Anna"\n')
    members = load_membership(path)

    assert members.is_member("Anna Placeholder-01", "") is True
    assert members.is_member("Placeholder-01, Anna", "") is True


def test_case_and_whitespace_are_ignored(tmp_path):
    path = _write(tmp_path, 'email,name\nM1@Example.Invalid,"Placeholder-01, Anna"\n')
    members = load_membership(path)

    assert members.is_member("  anna   placeholder-01 ", "") is True
    assert members.is_member("", "  m1@EXAMPLE.invalid ") is True


def test_the_length_is_the_number_of_rows(tmp_path):
    path = _write(tmp_path, 'email,name\na@example.invalid,\nb@example.invalid,\n')

    assert len(load_membership(path)) == 2


def test_unmatched_counts_entries_nobody_carries(tmp_path):
    path = _write(
        tmp_path,
        'email,name\na@example.invalid,\nb@example.invalid,\n,"Placeholder-03, Clara"\n',
    )
    members = load_membership(path)

    seen = [("Someone Else", "a@example.invalid"), ("Clara Placeholder-03", "")]
    assert members.unmatched(seen) == 1  # only b@ matched nothing


def test_a_correct_list_reports_no_unmatched_entries(tmp_path):
    path = _write(tmp_path, 'email,name\na@example.invalid,\n')
    members = load_membership(path)

    assert members.unmatched([("X", "a@example.invalid")]) == 0


def test_a_missing_header_column_is_an_error(tmp_path):
    path = _write(tmp_path, 'email\na@example.invalid\n')

    with pytest.raises(MembershipError, match="name"):
        load_membership(path)


def test_a_row_with_neither_key_is_an_error(tmp_path):
    """A silently skipped line would leave a member quietly filed under GEB-1 --
    exactly the failure this feature exists to remove.
    """
    path = _write(tmp_path, 'email,name\na@example.invalid,\n,\n')

    with pytest.raises(MembershipError, match="row 3"):
        load_membership(path)


def test_a_file_without_any_row_is_an_error(tmp_path):
    path = _write(tmp_path, 'email,name\n')

    with pytest.raises(MembershipError, match="no entries"):
        load_membership(path)


def test_the_error_names_the_file(tmp_path):
    path = _write(tmp_path, 'email\na@example.invalid\n')

    with pytest.raises(MembershipError, match="geb-members.csv"):
        load_membership(path)


def test_normalisers_are_exported_for_the_caller(tmp_path):
    """data.py normalises the frame side with the same functions, so the two
    sides cannot drift into different notions of equality.
    """
    assert normalise_name("Placeholder-01, Anna") == normalise_name("anna placeholder-01")
    assert normalise_email("  A@B.C ") == "a@b.c"


def test_an_empty_person_never_matches(tmp_path):
    """A blank cell must not match a blank config key."""
    path = _write(tmp_path, 'email,name\n,"Placeholder-01, Anna"\n')
    members = load_membership(path)

    assert members.is_member("", "") is False


def test_the_shipped_example_loads_and_holds_thirteen_rows():
    """The committed example is the thing the user copies. If it does not load,
    the first thing anyone tries fails.
    """
    from pathlib import Path

    example = Path(__file__).resolve().parents[1] / "geb-members.csv.example"
    members = load_membership(example)

    assert len(members) == 13
    assert members.is_member("", "geb.member.01@example.invalid") is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_report_membership.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.report.membership'`

- [ ] **Step 3: Write the module**

```python
# pipeline/report/membership.py
"""Who is on the GEB -- the one thing the source data cannot say.

`bod_geb` carries people at GEB and GEB-1 level with no marker distinguishing
them. The distinction cannot be derived, so it is supplied: a local CSV names
the members, and everyone else in the field is GEB-1.

The file names real people, so it never enters git. It sits beside a committed
`.example` carrying placeholders, the same pairing `cplan.config` uses.

Deliberately free of pandas and of any report import beyond `derive`: this is a
small pure function over a text file, and keeping it that way is what makes it
testable without building a frame.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from pipeline.report.derive import person_name

DEFAULT_FILENAME = "geb-members.csv"

REQUIRED_COLUMNS = ("email", "name")


class MembershipError(ValueError):
    """The list exists but cannot be read as one.

    Raised rather than falling back to "no list": a silent fallback produces a
    workbook that looks right and is wrong, which is the failure this whole
    feature exists to prevent.
    """


def normalise_name(value):
    """A display name reduced to one comparable form.

    `person_name` turns the source's "Last, First" into "First Last"; casefold
    and whitespace collapsing absorb the rest. Both sides of every comparison
    go through here, so they cannot drift into different notions of equality.
    """
    if not value:
        return ""
    return " ".join(person_name(str(value)).split()).casefold()


def normalise_email(value):
    if not value:
        return ""
    return str(value).strip().casefold()


@dataclass(frozen=True)
class Entry:
    """One configured member. Both keys already normalised; either may be ""."""

    email: str
    name: str

    def matches(self, name_key, email_key):
        # A blank key never matches, or every unnamed person would be a member.
        if self.email and self.email == email_key:
            return True
        return bool(self.name and self.name == name_key)


@dataclass(frozen=True)
class Membership:
    entries: tuple

    def __len__(self):
        return len(self.entries)

    def is_member(self, name, email=""):
        name_key = normalise_name(name)
        email_key = normalise_email(email)
        if not name_key and not email_key:
            return False
        return any(entry.matches(name_key, email_key) for entry in self.entries)

    def unmatched(self, people):
        """How many configured entries nothing in the data matched.

        A typo in the list and a person genuinely at GEB-1 level produce the
        same outcome in the workbook. Only this side tells them apart -- an
        entry matching nothing is either a typo or a member with no activities.

        Note what this cannot see: an entry that matches *too much*. Two people
        sharing a display name both match one name-only entry, and nothing in
        the data could separate them. An email on every row removes that risk.
        """
        keys = [(normalise_name(name), normalise_email(email)) for name, email in people]
        return sum(
            1 for entry in self.entries
            if not any(entry.matches(name_key, email_key) for name_key, email_key in keys)
        )


def load_membership(path):
    """The configured members, or None when there is no file.

    None is the normal state on a machine that has not been given the list, and
    it must stay cheap and silent: the report is expected to run without it.
    """
    path = Path(path)
    if not path.exists():
        return None

    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fieldnames = [(name or "").strip().lower() for name in (reader.fieldnames or [])]
        for column in REQUIRED_COLUMNS:
            if column not in fieldnames:
                raise MembershipError(
                    f"{path}: missing the required column {column!r} "
                    f"(found: {', '.join(fieldnames) or 'nothing'})"
                )

        entries = []
        # DictReader yields the first data row as row 2 of the file; naming the
        # file's own line number is what makes the message actionable.
        for offset, raw in enumerate(reader, start=2):
            email = normalise_email(_cell(raw, fieldnames, "email"))
            name = normalise_name(_cell(raw, fieldnames, "name"))
            if not email and not name:
                raise MembershipError(
                    f"{path}: row {offset} carries neither an email nor a name"
                )
            entries.append(Entry(email=email, name=name))

    if not entries:
        raise MembershipError(f"{path}: no entries")
    return Membership(entries=tuple(entries))


def _cell(raw, fieldnames, wanted):
    """The named cell, tolerating the header's original case and spacing."""
    for key, value in raw.items():
        if key is not None and key.strip().lower() == wanted:
            return value or ""
    return ""
```

- [ ] **Step 4: Write the example file**

```
# geb-members.csv.example
email,name
geb.member.01@example.invalid,"Placeholder-01, Anna"
geb.member.02@example.invalid,"Placeholder-02, Bernd"
geb.member.03@example.invalid,"Placeholder-03, Clara"
geb.member.04@example.invalid,"Placeholder-04, Dilan"
geb.member.05@example.invalid,"Placeholder-05, Elif"
geb.member.06@example.invalid,"Placeholder-06, Fabio"
geb.member.07@example.invalid,"Placeholder-07, Greta"
geb.member.08@example.invalid,"Placeholder-08, Hugo"
geb.member.09@example.invalid,"Placeholder-09, Ines"
geb.member.10@example.invalid,"Placeholder-10, Jonas"
geb.member.11@example.invalid,"Placeholder-11, Kaja"
geb.member.12@example.invalid,"Placeholder-12, Liam"
geb.member.13@example.invalid,"Placeholder-13, Mira"
```

Write it without the leading `# geb-members.csv.example` comment line — the file starts at `email,name`. `example.invalid` is the reserved TLD for exactly this, so nothing here can resolve to a real address.

- [ ] **Step 5: Add the real file to .gitignore**

Insert after the `cplan.config` line in the "CPLAN local runtime state" block:

```
cplan.config
# The GEB membership list names real people. The .example beside it carries
# placeholders and is committed; this one never is.
geb-members.csv
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_report_membership.py -q`
Expected: PASS, 16 tests

- [ ] **Step 7: Verify the real file cannot be committed**

Run: `git check-ignore -v geb-members.csv`
Expected: prints the `.gitignore` line number that matches. If it prints nothing, the rule is wrong — fix it before continuing.

- [ ] **Step 8: Commit**

```bash
git add pipeline/report/membership.py tests/test_report_membership.py geb-members.csv.example .gitignore
git commit -m "Add the GEB membership list: loader, matcher and placeholder file"
```

---

### Task 2: Keep a person's name and email paired through the ETL

**Files:**
- Modify: `pipeline/scripts/process_cplan.py` (`parse_sp_person_email` ~385-412, `SP_PERSON_COLUMNS` ~495, transform ~583-585)
- Modify: `pipeline/report/derive.py` (add `split_people_aligned`)
- Test: `tests/test_process_cplan_load.py`, `tests/test_report_derive.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces:
  - `process_cplan.parse_sp_person_emails(val, separator="; ") -> str` — one slot per person, in the same order `parse_sp_lookup` produces display names, empty where no email is known
  - `derive.split_people_aligned(value) -> list[str]` — splits on `;` **keeping** empty slots
  - a `bod_geb_email` column on the activities frame

**Why this task exists:** `parse_sp_person_email` handles a JSON *object* only. For an array — which is what a multi-person field like `bod_geb` exports — it falls through and returns `""`. Adding `bod_geb` to `SP_PERSON_COLUMNS` without this change produces an always-empty column, every match falls to the name path, and nothing says so.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_report_derive.py  -- append
def test_split_people_aligned_keeps_empty_slots():
    """The email column pairs positionally with the name column. Dropping an
    empty slot would shift every later person onto the wrong address.
    """
    from pipeline.report.derive import split_people_aligned

    assert split_people_aligned("a@x; ; c@x") == ["a@x", "", "c@x"]
    assert split_people_aligned("") == []
    assert split_people_aligned("; ;") == ["", "", ""]
```

```python
# tests/test_process_cplan_load.py  -- append
def test_person_emails_are_extracted_for_every_person_in_an_array():
    """A multi-person field exports a JSON array. The single-object parser
    returned "" for it, so a multi-person column silently carried no emails.
    """
    from pipeline.scripts.process_cplan import parse_sp_person_emails

    raw = (
        '[{"Claims": "i:0#.f|membership|a@example.invalid", "DisplayName": "A, One"},'
        ' {"Claims": "i:0#.f|membership|b@example.invalid", "DisplayName": "B, Two"}]'
    )

    assert parse_sp_person_emails(raw) == "a@example.invalid; b@example.invalid"


def test_a_person_without_an_email_keeps_its_slot():
    from pipeline.scripts.process_cplan import parse_sp_person_emails

    raw = (
        '[{"DisplayName": "A, One"},'
        ' {"Claims": "i:0#.f|membership|b@example.invalid", "DisplayName": "B, Two"}]'
    )

    assert parse_sp_person_emails(raw) == "; b@example.invalid"


def test_a_single_person_object_still_works():
    from pipeline.scripts.process_cplan import parse_sp_person_emails

    raw = '{"Claims": "i:0#.f|membership|a@example.invalid", "DisplayName": "A, One"}'

    assert parse_sp_person_emails(raw) == "a@example.invalid"


def test_plain_text_yields_no_emails():
    """A rich-text source column is a real shape -- it must yield nothing
    rather than raise, so the name path can carry the match alone.
    """
    from pipeline.scripts.process_cplan import parse_sp_person_emails

    assert parse_sp_person_emails("Example, Ada; Sample, Ben") == ""
    assert parse_sp_person_emails("") == ""


def test_the_leadership_column_gains_an_email_column():
    row = _mapped_cells(
        ["ID", "Title", "Start date", "BOD / GEB"],
        ["1", "A", "2025-03-05",
         '[{"Claims": "i:0#.f|membership|a@example.invalid", "DisplayName": "A, One"}]'],
    )

    assert row["bod_geb"] == "One A"
    assert row["bod_geb_email"] == "a@example.invalid"
```

`_mapped_cells(headers, values)` already exists at
`tests/test_process_cplan_load.py:97` and takes two lists. It returns the mapped
row as a dict.

**The ETL does not normalise names** — `person_name` runs in `data.py`. So
`row["bod_geb"]` comes back as the source's `"A, One"`, not `"One A"`. Write the
last assertion as:

```python
    assert row["bod_geb"] == "A, One"
    assert row["bod_geb_email"] == "a@example.invalid"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_process_cplan_load.py tests/test_report_derive.py -q`
Expected: FAIL — `ImportError: cannot import name 'parse_sp_person_emails'` and `'split_people_aligned'`

- [ ] **Step 3: Add the aligned splitter**

```python
# pipeline/report/derive.py  -- after split_people
def split_people_aligned(value):
    """Like `split_people`, but keeping empty slots.

    The email column is written one slot per person, in the same order as the
    display names, blank where no address is known. Dropping the blanks -- which
    `split_people` deliberately does, because a blank is not a person -- would
    shift every later person onto somebody else's address. Only the email
    column uses this.
    """
    text = _text(value)
    if not text:
        return []
    return [part.strip() for part in text.split(";")]
```

- [ ] **Step 4: Add the plural email parser**

```python
# pipeline/scripts/process_cplan.py  -- replace parse_sp_person_email
def _claims_email(obj):
    """The address inside one SharePoint person object, or ""."""
    if not isinstance(obj, dict):
        return ""
    if obj.get("Email"):
        return str(obj["Email"])
    claims = obj.get("Claims", "") or ""
    if "|membership|" in claims:
        return claims.split("|membership|")[-1]
    return ""


def parse_sp_person_email(val):
    """Extract the email from a single SharePoint person/Claims field.

    Claims format: "i:0#.f|membership|john@corp.com"

    Single-person fields only (`lead`, `author`). For a multi-person field use
    `parse_sp_person_emails`, which keeps one slot per person.
    """
    parsed = _parse_person_json(val)
    return _claims_email(parsed) if isinstance(parsed, dict) else ""


def parse_sp_person_emails(val, separator=PERSON_JOIN):
    """One email slot per person, aligned with the display names.

    `parse_sp_lookup` renders an array of person objects as their DisplayNames
    joined with the same separator, in list order. This walks the same list and
    emits an address per element, empty where none is known, so position N here
    is position N there.

    Returns "" for a plain-text column: a rich-text source field is a real
    shape, and the caller falls back to matching on the name.
    """
    parsed = _parse_person_json(val)
    if isinstance(parsed, dict):
        return _claims_email(parsed)
    if isinstance(parsed, list):
        emails = [_claims_email(item) for item in parsed]
        return "" if not any(emails) else separator.join(emails)
    return ""


def _parse_person_json(val):
    """The parsed JSON of a person field, or None when it is not JSON."""
    if pd.isna(val) or val == "":
        return None
    if not isinstance(val, str):
        return None
    stripped = val.strip()
    if not (stripped.startswith("{") or stripped.startswith("[")):
        return None
    try:
        return json.loads(stripped)
    except (json.JSONDecodeError, TypeError):
        return None
```

`PERSON_JOIN` is already defined above in this module (`"; "`). Returning `""`
when no element carried an address keeps the common "no emails at all" case
indistinguishable from an absent column, so downstream code has one empty case
to handle rather than `"; ; "`.

- [ ] **Step 5: Wire the multi-person columns**

```python
# pipeline/scripts/process_cplan.py  -- replace the SP_PERSON_COLUMNS extraction
    # Extract person emails BEFORE lookup parsing (which replaces JSON with
    # display names). Multi-person columns need the aligned variant: the
    # single-object parser returns "" for an array, which would leave the
    # leadership columns silently email-less.
    for col in SP_PERSON_COLUMNS:
        if col in df.columns:
            df[f"{col}_email"] = df[col].apply(parse_sp_person_email)
    for col in SP_MULTI_PERSON_COLUMNS:
        if col in df.columns:
            df[f"{col}_email"] = df[col].apply(parse_sp_person_emails)
```

`SP_PERSON_COLUMNS` stays `{"lead", "author"}` — `bod_geb` is *not* added to it.
`SP_MULTI_PERSON_COLUMNS` is already `{"bod_geb", "other_executives"}`, so both
leadership columns gain an aligned email column from the existing set.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_process_cplan_load.py tests/test_report_derive.py -q`
Expected: PASS

- [ ] **Step 7: Run the full check**

Run: `.venv/bin/python -m pytest tests/ -q && node --test tests/*.test.js`
Expected: all green. `bod_geb_email` is a new column and is not in
`metrics.REPORTED_FIELDS`, so the Data Quality completeness table is unchanged.

- [ ] **Step 8: Commit**

```bash
git add pipeline/scripts/process_cplan.py pipeline/report/derive.py tests/test_process_cplan_load.py tests/test_report_derive.py
git commit -m "Extract one email per person for the multi-person leadership columns"
```

---

### Task 3: Derive the two levels on the frame

**Files:**
- Modify: `pipeline/report/data.py` (`Scope` ~39-48, `build_scope` ~105, derivation ~162-176)
- Test: `tests/test_report_data.py`

**Interfaces:**
- Consumes: `membership.Membership`, `membership.load_membership`, `derive.split_people_aligned`, `bod_geb_email`.
- Produces:
  - `build_scope(load, config, membership=None)` — third parameter optional, defaults to today's behaviour
  - `Scope.membership: Membership | None`
  - `Scope.unmatched_members: int`
  - frame columns `executives_geb` and `executives_geb1`, semicolon-joined display names, present **only** when `membership` is not None

- [ ] **Step 1: Write the failing test**

```python
# tests/test_report_data.py  -- append
from pipeline.report.membership import Membership, Entry


def _members(*pairs):
    """A Membership from (email, name) pairs, already normalised by Entry."""
    from pipeline.report.membership import normalise_email, normalise_name
    return Membership(entries=tuple(
        Entry(email=normalise_email(e), name=normalise_name(n)) for e, n in pairs))


def _leadership_row(bod_geb, bod_geb_email=""):
    return {
        "tracking_id": "A", "activity_name": "A",
        "start_date": pd.Timestamp("2025-03-05"),
        "bod_geb": bod_geb, "bod_geb_email": bod_geb_email,
    }


def test_without_a_membership_the_split_columns_are_absent():
    """Every machine without the list gets today's workbook, unchanged."""
    frame = pd.DataFrame([_leadership_row("Person, One")])

    scope = build_scope(ActivityLoad(frame, {}, {}), _config())

    assert "executives_geb" not in scope.frame.columns
    assert "executives_geb1" not in scope.frame.columns
    assert scope.membership is None
    assert scope.unmatched_members == 0


def test_a_configured_member_lands_in_the_geb_column():
    frame = pd.DataFrame([_leadership_row("Person, One")])
    members = _members(("", "Person, One"))

    scope = build_scope(ActivityLoad(frame, {}, {}), _config(), members)
    row = scope.frame.iloc[0]

    assert row["executives_geb"] == "One Person"
    assert row["executives_geb1"] == ""


def test_anyone_else_in_the_field_lands_in_geb1():
    frame = pd.DataFrame([_leadership_row("Other, Two")])
    members = _members(("", "Person, One"))

    scope = build_scope(ActivityLoad(frame, {}, {}), _config(), members)
    row = scope.frame.iloc[0]

    assert row["executives_geb"] == ""
    assert row["executives_geb1"] == "Two Other"


def test_the_two_columns_partition_the_source_field():
    """Every person appears in exactly one column, and none is lost."""
    frame = pd.DataFrame([_leadership_row("Person, One; Other, Two; Third, Three")])
    members = _members(("", "Person, One"), ("", "Third, Three"))

    scope = build_scope(ActivityLoad(frame, {}, {}), _config(), members)
    row = scope.frame.iloc[0]

    assert row["executives_geb"] == "One Person; Three Third"
    assert row["executives_geb1"] == "Two Other"
    assert row["executives"] == "One Person; Two Other; Three Third"


def test_an_email_identifies_a_member_whose_name_differs():
    frame = pd.DataFrame([
        _leadership_row("Married, Anna", "anna@example.invalid")])
    members = _members(("anna@example.invalid", "Maiden, Anna"))

    scope = build_scope(ActivityLoad(frame, {}, {}), _config(), members)

    assert scope.frame.iloc[0]["executives_geb"] == "Anna Married"


def test_emails_pair_positionally_with_names():
    frame = pd.DataFrame([
        _leadership_row("A, One; B, Two", "a@example.invalid; b@example.invalid")])
    members = _members(("b@example.invalid", ""))

    scope = build_scope(ActivityLoad(frame, {}, {}), _config(), members)
    row = scope.frame.iloc[0]

    assert row["executives_geb"] == "Two B"
    assert row["executives_geb1"] == "One A"


def test_a_mismatched_email_count_falls_back_to_names_only():
    """Positional pairing is only safe while the counts agree. Where they do
    not, guessing an alignment would attribute someone else's address.
    """
    frame = pd.DataFrame([_leadership_row("A, One; B, Two", "only@example.invalid")])
    members = _members(("only@example.invalid", ""))

    scope = build_scope(ActivityLoad(frame, {}, {}), _config(), members)
    row = scope.frame.iloc[0]

    assert row["executives_geb"] == ""
    assert row["executives_geb1"] == "One A; Two B"


def test_unmatched_configuration_entries_are_counted():
    frame = pd.DataFrame([_leadership_row("Person, One")])
    members = _members(("", "Person, One"), ("", "Nobody, Zero"))

    scope = build_scope(ActivityLoad(frame, {}, {}), _config(), members)

    assert scope.unmatched_members == 1


def test_unmatched_is_counted_over_rows_in_scope():
    """A member whose only activity was filtered out reads as unmatched, which
    is the honest answer: this workbook shows nothing of theirs.
    """
    frame = pd.DataFrame([
        _leadership_row("Person, One"),
        {"tracking_id": "B", "activity_name": "B", "start_date": None,
         "bod_geb": "Dropped, Two", "bod_geb_email": ""},
    ])
    members = _members(("", "Person, One"), ("", "Dropped, Two"))

    scope = build_scope(ActivityLoad(frame, {}, {}), _config(), members)

    assert scope.unmatched_members == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_report_data.py -q`
Expected: FAIL — `build_scope() takes 2 positional arguments but 3 were given`

- [ ] **Step 3: Extend Scope**

```python
# pipeline/report/data.py  -- Scope
@dataclass
class Scope:
    frame: pd.DataFrame
    grid: object
    rows_read: int
    excluded: dict
    source_files: list = field(default_factory=list)
    completeness_fields: list = field(default_factory=list)
    skipped_completeness_fields: list = field(default_factory=list)
    duplicates_removed: int = 0
    # None when no membership list was supplied -- the state every machine
    # without the file is in, and the one that must render today's workbook.
    membership: object = None
    unmatched_members: int = 0
```

- [ ] **Step 4: Split the field**

Change the signature and the empty-frame early return:

```python
def build_scope(load, config, membership=None):
    ...
    if frame.empty:
        return Scope(frame=frame, grid=build_grid(*_resolve_window([], config)),
                     rows_read=0, excluded=excluded,
                     source_files=source_files,
                     duplicates_removed=load.duplicates_removed,
                     membership=membership)
```

Then, directly after the existing `senior_executives` derivation and after every
filter has run (so the count reflects the rows the workbook actually shows), add:

```python
    # The GEB / GEB-1 split, when a membership list was supplied. Derived from
    # the same normalised names the blocks render, so a person cannot appear in
    # a block under one spelling and be matched under another.
    unmatched = 0
    if membership is not None:
        pairs = frame.apply(
            lambda row: _people_with_emails(row), axis=1)
        frame["executives_geb"] = pairs.apply(
            lambda people: PERSON_SEPARATOR.join(
                name for name, email in people if membership.is_member(name, email)))
        frame["executives_geb1"] = pairs.apply(
            lambda people: PERSON_SEPARATOR.join(
                name for name, email in people if not membership.is_member(name, email)))
        seen = [pair for people in pairs for pair in people]
        unmatched = membership.unmatched(seen)
```

with the helper beside `_column`:

```python
def _people_with_emails(row):
    """(display name, email) for each person in `bod_geb`, in source order.

    The email column is written one slot per person by the ETL. Where the two
    counts disagree -- a hand-edited export, a mixed rich-text and person-picker
    history -- no alignment can be trusted, so every email is dropped and the
    names carry the match alone. Silently guessing an offset would attribute
    one person's address to another.
    """
    names = [person_name(part) for part in split_people(row.get("bod_geb"))]
    emails = split_people_aligned(row.get("bod_geb_email"))
    if len(emails) != len(names):
        emails = [""] * len(names)
    return list(zip(names, emails))
```

Import `person_name` and `split_people_aligned` from `derive` at the top of the
module alongside the existing imports, and place `unmatched_members=unmatched`
on the `Scope(...)` the function returns, together with `membership=membership`.

`PERSON_SEPARATOR` is already imported here by `derive.executive_names`; if it is
not in `data.py`'s namespace, import it from `pipeline.report.derive`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_report_data.py -q`
Expected: PASS

- [ ] **Step 6: Run the full check**

Run: `.venv/bin/python -m pytest tests/ -q && node --test tests/*.test.js`
Expected: all green — `build_scope`'s third parameter is optional, so every
existing caller is unaffected.

- [ ] **Step 7: Commit**

```bash
git add pipeline/report/data.py tests/test_report_data.py
git commit -m "Split the leadership field into GEB and GEB-1 when a list is supplied"
```

---

### Task 4: Two blocks in the calendar

**Files:**
- Modify: `pipeline/report/calendar_sheet.py` (`FIELD_TITLES` ~39-45, `PEOPLE_FIELDS` ~62)
- Modify: `pipeline/scripts/report_calendar.py` (`main`, ~188)
- Test: `tests/test_report_calendar_sheet.py`

**Interfaces:**
- Consumes: frame columns `executives_geb` / `executives_geb1` from Task 3.
- Produces: calendar blocks titled `BY GEB — multiple values possible` and `BY GEB-1 — multiple values possible`; a `breakdown_fields` tuple that names the two split columns when a membership is active.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_report_calendar_sheet.py  -- append
def _split_sheet(sources, member_names, emails=None):
    """A calendar over the split columns, built from `bod_geb` and a list."""
    from pipeline.report.membership import Entry, Membership, normalise_name

    members = Membership(entries=tuple(
        Entry(email="", name=normalise_name(n)) for n in member_names))
    frame = pd.DataFrame({
        "tracking_id": [f"IC-{i:04d}" for i in range(len(sources))],
        "activity_name": [f"A{i}" for i in range(len(sources))],
        "start_date": [pd.Timestamp("2025-03-05")] * len(sources),
        "bod_geb": list(sources),
        "bod_geb_email": list(emails or [""] * len(sources)),
    })
    config = ReportConfig(
        date_from=date(2025, 1, 1), date_to=date(2025, 12, 31),
        breakdown_fields=("executives_geb", "executives_geb1"))
    scope = build_scope(ActivityLoad(frame, {}, {}), config, members)
    wb = Workbook()
    wb.remove(wb.active)
    build_calendar(wb, scope, config)
    return wb["Calendar"]


def test_the_calendar_carries_a_geb_block_and_a_geb1_block():
    ws = _split_sheet(["Member, One", "Other, Two"], ["Member, One"])
    labels = _labels(ws)

    assert "BY GEB — multiple values possible" in labels
    assert "BY GEB-1 — multiple values possible" in labels


def test_a_member_appears_only_under_geb():
    ws = _split_sheet(["Member, One", "Other, Two"], ["Member, One"])
    labels = _labels(ws)
    geb = labels["BY GEB — multiple values possible"]
    geb1 = labels["BY GEB-1 — multiple values possible"]

    names_under_geb = _member_names_under(ws, geb)
    names_under_geb1 = _member_names_under(ws, geb1)

    assert "One Member" in names_under_geb
    assert "One Member" not in names_under_geb1
    assert "Two Other" in names_under_geb1
    assert "Two Other" not in names_under_geb


def test_the_two_block_headers_sum_to_the_combined_figure():
    """The split is a partition. Two activities, one member each, means one
    activity under each header -- never two under both.
    """
    ws = _split_sheet(["Member, One", "Other, Two"], ["Member, One"])
    labels = _labels(ws)

    geb_total = _week_total(ws, labels["BY GEB — multiple values possible"])
    geb1_total = _week_total(ws, labels["BY GEB-1 — multiple values possible"])

    assert geb_total == 1
    assert geb1_total == 1


def test_an_activity_naming_both_levels_counts_once_in_each_block():
    ws = _split_sheet(["Member, One; Other, Two"], ["Member, One"])
    labels = _labels(ws)

    assert _week_total(ws, labels["BY GEB — multiple values possible"]) == 1
    assert _week_total(ws, labels["BY GEB-1 — multiple values possible"]) == 1
```

Add the helper beside the existing `_labels`:

```python
def _member_names_under(ws, header_row):
    """The level-1 labels directly under a block header, stopping at the next.

    The hierarchy lives in `row_dimensions[row].outline_level`, not in the
    label text -- `_label_cell` sets the outline level and writes the text
    unindented, while `_detail_label` happens to prefix two spaces of its own.
    Testing the text would therefore catch detail rows as members.
    """
    names = []
    for row in range(header_row + 1, ws.max_row + 1):
        value = ws.cell(row=row, column=LABEL_COL).value
        if value is None:
            continue
        if str(value).startswith("BY ") or str(value) == "ALL ACTIVITIES":
            break
        if ws.row_dimensions[row].outline_level == 1:
            names.append(str(value).strip())
    return names
```

Member rows are outline level 1; the activity detail rows beneath them are
level 2 and are excluded by that test.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_report_calendar_sheet.py -q`
Expected: FAIL — the blocks are titled `BY EXECUTIVES_GEB`, because `FIELD_TITLES` has no entry for the new fields.

- [ ] **Step 3: Name the two blocks**

```python
# pipeline/report/calendar_sheet.py
FIELD_TITLES = {
    "business_division": "BUSINESS DIVISION",
    "region": "REGION",
    "region_group": "REGION",
    "country": "COUNTRY",
    "executives": "GEB/GEB-1",
    # Present only when a membership list splits the field; the combined
    # title above is what a run without the list still shows.
    "executives_geb": "GEB",
    "executives_geb1": "GEB-1",
}

# People fields split on the semicolon only: a display name contains a comma
PEOPLE_FIELDS = frozenset({
    "executives", "senior_executives", "executives_geb", "executives_geb1"})
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_report_calendar_sheet.py -q`
Expected: PASS

- [ ] **Step 5: Swap the breakdown fields when a list is loaded**

In `pipeline/scripts/report_calendar.py`, in `main`, after loading the
membership (wired fully in Task 7) and before `build_scope`:

```python
    # The split columns replace the combined one, never join it: a GEB block
    # beside a GEB/GEB-1 block would print the same person with the same count
    # twice, and anyone adding the blocks would double-count the members.
    if membership is not None:
        fields = []
        for field in config.breakdown_fields:
            if field == "executives":
                fields.extend(("executives_geb", "executives_geb1"))
            else:
                fields.append(field)
        config = replace(config, breakdown_fields=tuple(fields))
```

`ReportConfig` is frozen, so it cannot be mutated. `report_calendar.py` already
imports `replace` from `dataclasses` at line 19 — no new import.

- [ ] **Step 6: Run the full check**

Run: `.venv/bin/python -m pytest tests/ -q && node --test tests/*.test.js`
Expected: all green

- [ ] **Step 7: Commit**

```bash
git add pipeline/report/calendar_sheet.py pipeline/scripts/report_calendar.py tests/test_report_calendar_sheet.py
git commit -m "Give the calendar a GEB block and a GEB-1 block"
```

---

### Task 5: Two people blocks on Audience & leadership

**Files:**
- Modify: `pipeline/report/table_sheets.py` (`build_audience`, the two `_write_people_block` calls ~326-336)
- Test: `tests/test_report_audience_sheet.py`

**Interfaces:**
- Consumes: `Scope.membership`, frame columns from Task 3.
- Produces: blocks `ACTIVITIES BY GEB MEMBER` and `ACTIVITIES BY GEB-1 MEMBER` when a membership is present; the existing `ACTIVITIES BY GEB/GEB-1 MEMBER` when it is not.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_report_audience_sheet.py  -- append
def _split_audience_sheet(sources, member_names):
    from pipeline.report.membership import Entry, Membership, normalise_name

    members = Membership(entries=tuple(
        Entry(email="", name=normalise_name(n)) for n in member_names))
    frame = pd.DataFrame({
        "tracking_id": [f"IC-{i:04d}" for i in range(len(sources))],
        "activity_name": [f"A{i}" for i in range(len(sources))],
        "start_date": [pd.Timestamp("2025-03-05")] * len(sources),
        "bod_geb": list(sources),
        "bod_geb_email": [""] * len(sources),
        "audience": ["1000"] * len(sources),
    })
    config = ReportConfig(date_from=date(2025, 1, 1), date_to=date(2025, 12, 31))
    scope = build_scope(ActivityLoad(frame, {}, {}), config, members)
    wb = Workbook()
    wb.remove(wb.active)
    build_audience(wb, scope, config)
    return wb["Audience & leadership"]


def test_the_sheet_splits_the_member_block_when_a_list_is_present():
    ws = _split_audience_sheet(["Member, One", "Other, Two"], ["Member, One"])
    labels = _column_a(ws)

    assert "ACTIVITIES BY GEB MEMBER" in labels
    assert "ACTIVITIES BY GEB-1 MEMBER" in labels
    assert "ACTIVITIES BY GEB/GEB-1 MEMBER" not in labels


def test_the_combined_block_returns_without_a_list():
    """The regression that matters most: every machine without the file."""
    ws = _geb_sheet(["Member, One", "Other, Two"])
    labels = _column_a(ws)

    assert "ACTIVITIES BY GEB/GEB-1 MEMBER" in labels
    assert "ACTIVITIES BY GEB MEMBER" not in labels
    assert "ACTIVITIES BY GEB-1 MEMBER" not in labels


def test_a_member_is_listed_under_geb_only():
    ws = _split_audience_sheet(["Member, One", "Other, Two"], ["Member, One"])
    block = _member_block(ws, title="ACTIVITIES BY GEB MEMBER")

    assert list(block) == ["One Member"]


def test_everyone_else_is_listed_under_geb1():
    ws = _split_audience_sheet(["Member, One", "Other, Two"], ["Member, One"])
    block = _member_block(ws, title="ACTIVITIES BY GEB-1 MEMBER")

    assert list(block) == ["Two Other"]
```

`_member_block(ws, title="ACTIVITIES BY GEB/GEB-1 MEMBER")`, `_column_a` and
`_geb_sheet` already exist in this file. Reuse them as they are.

**`_member_block` returns a dict** of label → count, so iterate it with
`list(block)` for the names — `for name, _ in block` would unpack the label
string, not a pair.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_report_audience_sheet.py -q`
Expected: FAIL — `ACTIVITIES BY GEB MEMBER` is absent; only the combined block exists.

- [ ] **Step 3: Render one block per level**

Replace the first `_write_people_block` call in `build_audience`:

```python
    if scope.membership is None:
        row = _write_people_block(
            ws, row, frame, "executives",
            "ACTIVITIES BY GEB/GEB-1 MEMBER", "GEB/GEB-1 member",
            "All activities with GEB/GEB-1",
            "No GEB/GEB-1 member named on any in-scope activity")
        row += 1
    else:
        # One block per level, never a level block beside the combined one:
        # the same person would appear twice with the same count.
        row = _write_people_block(
            ws, row, frame, "executives_geb",
            "ACTIVITIES BY GEB MEMBER", "GEB member",
            "All activities with GEB",
            "No GEB member named on any in-scope activity")
        row += 1
        row = _write_people_block(
            ws, row, frame, "executives_geb1",
            "ACTIVITIES BY GEB-1 MEMBER", "GEB-1 member",
            "All activities with GEB-1",
            "No GEB-1 member named on any in-scope activity")
        row += 1
```

The `other_executives` block below is unchanged and still follows.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_report_audience_sheet.py -q`
Expected: PASS

- [ ] **Step 5: Run the full check**

Run: `.venv/bin/python -m pytest tests/ -q && node --test tests/*.test.js`
Expected: all green

- [ ] **Step 6: Commit**

```bash
git add pipeline/report/table_sheets.py tests/test_report_audience_sheet.py
git commit -m "Split the audience sheet's member block by level"
```

---

### Task 6: Summary line, unmatched count, Glossary

**Files:**
- Modify: `pipeline/report/table_sheets.py` (`build_executive_summary` ~90-97, `build_data_quality`, `build_glossary` / `GLOSSARY_SECTIONS` ~395-415)
- Test: `tests/test_report_summary_sheet.py`, `tests/test_report_quality_sheet.py`

**Interfaces:**
- Consumes: `Scope.membership`, `Scope.unmatched_members`, `frame["executives_geb"]`.
- Produces: an Executive Summary share row `With GEB involvement`; a Data Quality row `GEB list entries never matched`; Glossary terms `GEB` and `GEB-1`. All three appear **only** when a membership is present.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_report_summary_sheet.py  -- append
def _members(*names):
    from pipeline.report.membership import Entry, Membership, normalise_name
    return Membership(entries=tuple(
        Entry(email="", name=normalise_name(n)) for n in names))


def test_the_summary_adds_a_geb_share_when_a_list_is_present(tmp_path):
    config = ReportConfig(date_from=date(2025, 1, 1), date_to=date(2025, 12, 31))
    scope = load_fixture_scope(tmp_path, config, membership=_members("Example, Ada"))
    wb = Workbook()
    wb.remove(wb.active)
    build_executive_summary(wb, scope, config)
    labels = [str(wb.worksheets[0].cell(row=r, column=1).value)
              for r in range(1, wb.worksheets[0].max_row + 1)]

    assert any("With GEB involvement" in label for label in labels)
    assert any("With GEB/GEB-1 involvement" in label for label in labels)


def test_the_summary_omits_the_geb_share_without_a_list(tmp_path):
    ws, _ = _build(tmp_path, build_executive_summary)
    labels = [str(ws.cell(row=r, column=1).value) for r in range(1, ws.max_row + 1)]

    assert not any("With GEB involvement" in label for label in labels)


def test_the_glossary_defines_both_levels_only_with_a_list(tmp_path):
    ws, _ = _build(tmp_path, build_glossary)
    terms = {term for term, _ in _glossary_entries(ws)}

    assert "GEB/GEB-1" in terms
    assert "GEB" not in terms
    assert "GEB-1" not in terms
```

```python
# tests/test_report_quality_sheet.py  -- append
def test_data_quality_reports_unmatched_list_entries(tmp_path):
    """A typo in the list and a genuine GEB-1 person look identical in the
    blocks. This number is the only thing that tells them apart.
    """
    from pipeline.report.membership import Entry, Membership, normalise_name

    members = Membership(entries=(
        Entry(email="", name=normalise_name("Example, Ada")),
        Entry(email="", name=normalise_name("Nobody, Zero")),
    ))
    config = ReportConfig(date_from=date(2025, 1, 1), date_to=date(2025, 12, 31))
    scope = load_fixture_scope(tmp_path, config, membership=members)
    wb = Workbook()
    wb.remove(wb.active)
    build_data_quality(wb, scope, config)
    ws = wb["Data Quality"]
    pairs = {ws.cell(row=r, column=1).value: ws.cell(row=r, column=2).value
             for r in range(1, ws.max_row + 1)}

    assert pairs["GEB list entries never matched"] == 1
    assert pairs["GEB list entries"] == 2


def test_data_quality_omits_the_block_without_a_list(tmp_path):
    config = ReportConfig(date_from=date(2025, 1, 1), date_to=date(2025, 12, 31))
    scope = load_fixture_scope(tmp_path, config)
    wb = Workbook()
    wb.remove(wb.active)
    build_data_quality(wb, scope, config)
    ws = wb["Data Quality"]
    labels = [ws.cell(row=r, column=1).value for r in range(1, ws.max_row + 1)]

    assert "GEB list entries never matched" not in labels
```

`load_fixture_scope` gains an optional `membership=None` parameter in
`tests/report_fixtures.py`, passed straight through to `build_scope`. Add it
in this step — it is test scaffolding, not production code.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_report_summary_sheet.py tests/test_report_quality_sheet.py -q`
Expected: FAIL — `load_fixture_scope() got an unexpected keyword argument 'membership'`

- [ ] **Step 3: Add the Executive Summary row**

In `build_executive_summary`, directly after the existing `With GEB/GEB-1
involvement` row and before `Large audience`:

```python
    _write_share_row(ws, row, total_row, "With GEB/GEB-1 involvement", executives, sub=False)
    row += 1
    if scope.membership is not None:
        # Indented under the combined figure: it is a part of it, not a
        # second independent measure.
        geb = int((frame["executives_geb"] != "").sum()) if len(frame) else 0
        _write_share_row(ws, row, total_row, "With GEB involvement", geb, sub=True)
        row += 1
```

`_write_share_row(ws, row, total_row, text, count, sub=True)` already carries
the parameter: `sub` indents and italicises the row as a member of the count
above. The combined figure passes `sub=False` because it is a headline; the GEB
figure passes `sub=True` because it is a part of that headline.

- [ ] **Step 4: Add the Data Quality block**

At the end of `build_data_quality`, before `style.finalize_sheet`:

```python
    if scope.membership is not None:
        row = style.write_section_header(ws, row, "GEB LIST", 4)
        row = style.write_header_row(ws, row, ["Measure", "Count", "", ""])
        row = style.write_data_rows(ws, row, [
            ["GEB list entries", len(scope.membership)],
            ["GEB list entries never matched", scope.unmatched_members],
        ])
        row += 1
```

A non-zero second figure means the list disagrees with the source: a typo, a
changed name, or a member with no activity in scope. It is printed rather than
left for the reader to notice, because the blocks themselves cannot show it.

- [ ] **Step 5: Make the Glossary conditional**

`GLOSSARY_SECTIONS` is a module constant. Turn the MEASURES entries for the
levels into something `build_glossary` assembles:

```python
# Added to MEASURES only when a membership list is in play -- defining terms
# the workbook never prints would be its own small lie.
GEB_SPLIT_TERMS = (
    ("GEB", "A person named on the GEB list. Everyone else in the field is "
            "GEB-1."),
    ("GEB-1", "Named in the leadership field but not on the GEB list."),
)
```

In `build_glossary`, when writing the `MEASURES` section and
`scope.membership is not None`, insert `GEB_SPLIT_TERMS` directly after the
existing `GEB/GEB-1` entry.

Both definitions are under 110 characters. Verify with:

```bash
.venv/bin/python -c "
from pipeline.report.table_sheets import GEB_SPLIT_TERMS
for t, d in GEB_SPLIT_TERMS: print(len(d), t)"
```

Expected: both numbers ≤ 110.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_report_summary_sheet.py tests/test_report_quality_sheet.py -q`
Expected: PASS

- [ ] **Step 7: Run the full check**

Run: `.venv/bin/python -m pytest tests/ -q && node --test tests/*.test.js`
Expected: all green, including `test_every_glossary_definition_stays_short`

- [ ] **Step 8: Commit**

```bash
git add pipeline/report/table_sheets.py tests/report_fixtures.py tests/test_report_summary_sheet.py tests/test_report_quality_sheet.py
git commit -m "Report the GEB share, the list size and the entries that matched nothing"
```

---

### Task 7: Wire the script end to end

**Files:**
- Modify: `pipeline/scripts/report_calendar.py` (`main`, argument parser)
- Modify: `report.ps1` (pass the flag through)
- Modify: `README.md`, `.loop.md`
- Test: `tests/test_report_calendar_script.py`

**Interfaces:**
- Consumes: everything from Tasks 1-6.
- Produces: `--geb-members PATH` on the CLI, defaulting to `geb-members.csv` beside the repository root; a workbook identical to today's when that file is absent.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_report_calendar_script.py  -- append
GEB_EXAMPLE = 'email,name\n,"Example, Ada"\n'


def test_without_a_list_the_workbook_is_unchanged(tmp_path):
    """The regression that matters most. Every machine without the file must
    get byte-comparable sheet names and the combined block titles.
    """
    write_activity_csvs(tmp_path / "input")
    out = tmp_path / "report.xlsx"

    report_calendar.main(["--input-dir", str(tmp_path / "input"),
                          "--all", "--out", str(out)])
    wb = load_workbook(out)

    assert wb.sheetnames == EXPECTED_SHEETS
    labels = [wb["Calendar"].cell(row=r, column=1).value
              for r in range(1, wb["Calendar"].max_row + 1)]
    assert "BY GEB/GEB-1 — multiple values possible" in labels
    assert "BY GEB — multiple values possible" not in labels


def test_a_list_splits_the_calendar_end_to_end(tmp_path):
    write_activity_csvs(tmp_path / "input")
    members = tmp_path / "geb-members.csv"
    members.write_text(GEB_EXAMPLE, encoding="utf-8")
    out = tmp_path / "report.xlsx"

    code = report_calendar.main([
        "--input-dir", str(tmp_path / "input"), "--all",
        "--geb-members", str(members), "--out", str(out)])

    assert code == 0
    wb = load_workbook(out)
    assert wb.sheetnames == EXPECTED_SHEETS  # no new sheet, only new blocks
    labels = [wb["Calendar"].cell(row=r, column=1).value
              for r in range(1, wb["Calendar"].max_row + 1)]
    assert "BY GEB — multiple values possible" in labels
    assert "BY GEB-1 — multiple values possible" in labels
    assert "BY GEB/GEB-1 — multiple values possible" not in labels


def test_a_broken_list_aborts_with_a_message(tmp_path, capsys):
    """Aborting beats falling back: a fallback produces a workbook that looks
    correct and is wrong.
    """
    write_activity_csvs(tmp_path / "input")
    members = tmp_path / "geb-members.csv"
    members.write_text("email\nonly@example.invalid\n", encoding="utf-8")
    out = tmp_path / "report.xlsx"

    code = report_calendar.main([
        "--input-dir", str(tmp_path / "input"), "--all",
        "--geb-members", str(members), "--out", str(out)])

    assert code == 1
    assert not out.exists()
    assert "name" in capsys.readouterr().out


def test_a_named_list_that_does_not_exist_aborts(tmp_path):
    """An absent default file is normal; an absent *named* file is a typo on
    the command line and must not silently produce the unsplit workbook.
    """
    write_activity_csvs(tmp_path / "input")
    out = tmp_path / "report.xlsx"

    code = report_calendar.main([
        "--input-dir", str(tmp_path / "input"), "--all",
        "--geb-members", str(tmp_path / "nope.csv"), "--out", str(out)])

    assert code == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_report_calendar_script.py -q`
Expected: FAIL — `unrecognized arguments: --geb-members`

- [ ] **Step 3: Add the flag**

Beside the existing `--input-dir` argument:

```python
    parser.add_argument(
        "--geb-members", type=str, default=None,
        help=("CSV naming the GEB members, so the report can split the "
              "leadership field into GEB and GEB-1. Defaults to "
              f"{membership.DEFAULT_FILENAME} beside this repository; without "
              "it the two levels stay combined."))
```

- [ ] **Step 4: Load it in main**

Before `build_scope`:

```python
    # An absent default file is the normal state and stays silent. An absent
    # *named* file is a typo on the command line, and producing the unsplit
    # workbook anyway would answer a question nobody asked.
    members_path = Path(args.geb_members) if args.geb_members else (
        REPO_DIR / membership.DEFAULT_FILENAME)
    if args.geb_members and not members_path.exists():
        log(f"ERROR: no GEB member list at {members_path}")
        return 1
    try:
        members = membership.load_membership(members_path)
    except membership.MembershipError as error:
        log(f"ERROR: {error}")
        return 1
    if members is not None:
        log(f"GEB list: {len(members)} members from {members_path.name}")
```

Then pass it through: `scope = build_scope(load, config, members)`, and apply
the `breakdown_fields` swap from Task 4 Step 5 with `members` as the condition.

`REPO_DIR` is already defined at line 27 of this module (`PIPELINE_DIR.parent`)
and is the repository root. Do not add a second root constant.

Add `from pipeline.report import membership` to the `# noqa: E402` import block
below the `sys.path` insertion, alongside the other `pipeline.report` imports.

- [ ] **Step 5: Log the unmatched count**

After the existing exclusion logging:

```python
    if scope.membership is not None and scope.unmatched_members:
        log(f"  WARNING: {scope.unmatched_members} of {len(scope.membership)} "
            f"GEB list entries matched nothing in scope")
```

A warning on the console as well as the sheet: the operator running the report
is the person who can fix the list.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_report_calendar_script.py -q`
Expected: PASS

- [ ] **Step 7: Pass the flag through the launcher**

In `report.ps1`, add a `-GebMembers` parameter mirroring the existing `-Year` /
`-From` / `-To` handling, appending `--geb-members <path>` when supplied. Match
the file's existing parameter style exactly; do not invent a new one.

- [ ] **Step 8: Document it**

In `README.md`, beside the other report flags, one paragraph: what the file is,
where it goes, that it is gitignored, that `geb-members.csv.example` is the
template, and that without it the two levels stay combined.

In `.loop.md`, extend the existing `bod_geb` STOLPER entry:

```
           Seit 2026-08-05 kann geb-members.csv (Repo-Root, gitignored) die
           13 GEB-Mitglieder benennen und den Block in GEB / GEB-1 teilen.
           Ohne die Datei bleibt alles wie vorher -- diese Regression ist die
           wichtigste im Test, weil jede Maschine ohne Datei in dem Zustand
           ist. parse_sp_person_email kann NUR Einzelpersonen; fuer
           Mehrpersonenspalten gilt parse_sp_person_emails, das pro Person
           einen Slot schreibt. Wer das verwechselt, bekommt eine leere
           Email-Spalte und merkt nichts, weil der Namenspfad still traegt.
```

- [ ] **Step 9: Verify the check.ps1 manifest**

Run: `grep -n "report_calendar\|report.ps1\|table_sheets\|calendar_sheet\|membership" check.ps1`

`report.ps1` is **not** currently in the manifest; if that grep shows it is,
bump its marker in this commit. Otherwise nothing to do.

- [ ] **Step 10: Run the full check**

Run: `.venv/bin/python -m pytest tests/ -q && node --test tests/*.test.js`
Expected: all green

- [ ] **Step 11: Build a real workbook both ways and look at it**

```bash
.venv/bin/python - <<'PY'
import pathlib, tempfile
from openpyxl import load_workbook
import pipeline.scripts.report_calendar as rc
from tests.report_fixtures import write_activity_csvs

tmp = pathlib.Path(tempfile.mkdtemp())
write_activity_csvs(tmp / "input")
members = tmp / "geb-members.csv"
members.write_text('email,name\n,"Example, Ada"\n', encoding="utf-8")

for label, argv in (("without", []), ("with", ["--geb-members", str(members)])):
    out = tmp / f"{label}.xlsx"
    rc.main(["--input-dir", str(tmp / "input"), "--all", "--out", str(out)] + argv)
    ws = load_workbook(out)["Calendar"]
    blocks = [ws.cell(row=r, column=1).value for r in range(1, ws.max_row + 1)
              if str(ws.cell(row=r, column=1).value).startswith("BY ")]
    print(label, "->", blocks)
PY
```

Expected: `without` shows `BY GEB/GEB-1 …`; `with` shows `BY GEB …` and
`BY GEB-1 …` and no combined block.

- [ ] **Step 12: Commit**

```bash
git add pipeline/scripts/report_calendar.py report.ps1 README.md .loop.md tests/test_report_calendar_script.py
git commit -m "Wire the GEB member list into the report script"
```

---

## Cleanup round

Before declaring this done, run the `build` skill's cleanup questions over the
result:

- [ ] **Duplicate:** does any figure now appear in two places? The GEB share is
  on the Executive Summary and the block totals are on Audience & leadership —
  confirm they are the same number derived from the same column, and that the
  calendar does not also print a third version.
- [ ] **Superseded:** with the split active, does the combined `GEB/GEB-1`
  Glossary entry still earn its place? It does — it names what the two add up
  to — but confirm rather than assume.
- [ ] **Wrong place:** the unmatched count sits on Data Quality, which owns
  "what is wrong with this data". Confirm nothing about the list leaked onto the
  Executive Summary beyond the share row.

Then run the full check once more and report `WEGGELASSEN` and `UNGEPRÜFT`.
