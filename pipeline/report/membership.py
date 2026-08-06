"""Who is on the GEB -- the one thing the source data cannot say.

`bod_geb` carries people at GEB and GEB-1 level with no marker distinguishing
them. The distinction cannot be derived, so it is supplied: a local list names
the members, and everyone else in the field is GEB-1.

The list is read as either a workbook or a CSV, chosen by the file extension.
The workbook is the easier file to keep by hand, and the reason is specific:
the two ways a hand-edited CSV breaks -- Excel's "CSV (Comma delimited)" save
writing Windows-1252 rather than UTF-8, and its semicolon separator on a German
locale -- are both properties of the CSV *export*, not of the data. A workbook
carries its own encoding and needs no separator, so neither failure exists
there. The CSV path stays because the committed `.example` is a CSV: it is the
one copy that has to stay readable in a diff.

The file names real people, so it never enters git. It sits beside a committed
`.example` carrying placeholders, the same pairing `cplan.config` uses.

Deliberately free of pandas and of any report import beyond `derive`: this is a
small pure function over a file, and keeping it that way is what makes it
testable without building a frame. openpyxl is not a new dependency -- the
report is written with it.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from pipeline.report.derive import person_name

# Searched in this order, so a directory holding one of them needs no flag.
# The workbook comes first only to make the search deterministic; holding both
# is an error rather than a precedence question -- see default_path.
DEFAULT_FILENAMES = ("geb-members.xlsx", "geb-members.csv")

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

        The mirror case is one person written two different ways -- "Mueller"
        on one activity, "Müller" on another. Once either spelling matches the
        entry, the entry counts as matched and this stays 0, while the other
        spelling is filed under GEB-1 unflagged. Giving the entry an email, or
        adding the second spelling as its own row, removes it too.
        """
        keys = [(normalise_name(name), normalise_email(email)) for name, email in people]
        return sum(
            1 for entry in self.entries
            if not any(entry.matches(name_key, email_key) for name_key, email_key in keys)
        )


def default_path(directory):
    """Which default list a directory holds, or None when it holds neither.

    Holding both is an error rather than a precedence rule. The two files would
    only both exist because one was converted from the other, and the moment
    they disagree, quietly reading the one the operator is not editing splits
    the report on a list nobody checked -- the same silent-wrong-answer failure
    the rest of this module is built to refuse.
    """
    directory = Path(directory)
    found = [directory / name for name in DEFAULT_FILENAMES
             if (directory / name).exists()]
    if len(found) > 1:
        raise MembershipError(
            f"{directory} holds both {DEFAULT_FILENAMES[0]} and "
            f"{DEFAULT_FILENAMES[1]}; keep one, or name the one to use"
        )
    return found[0] if found else None


def load_membership(path):
    """The configured members, or None when there is no file.

    None is the normal state on a machine that has not been given the list, and
    it must stay cheap and silent: the report is expected to run without it.
    """
    path = Path(path)
    if not path.exists():
        return None

    read = _read_xlsx if path.suffix.lower() == ".xlsx" else _read_csv

    entries = []
    for offset, raw_email, raw_name in read(path):
        email = normalise_email(raw_email)
        name = normalise_name(raw_name)
        if not email and not name:
            raise MembershipError(
                f"{path}: row {offset} carries neither an email nor a name"
            )
        entries.append(Entry(email=email, name=name))

    if not entries:
        raise MembershipError(f"{path}: no entries")
    return Membership(entries=tuple(entries))


def _require_columns(path, fieldnames):
    for column in REQUIRED_COLUMNS:
        if column not in fieldnames:
            raise MembershipError(
                f"{path}: missing the required column {column!r} "
                f"(found: {', '.join(fieldnames) or 'nothing'})"
            )


def _read_csv(path):
    """(row number, email, name) per data row, or a MembershipError.

    Row numbers are the file's own: the first data row is row 2, which is what
    makes a message actionable in the editor the operator is looking at.
    """
    # A directory where a file was expected, a permissions problem, or a CSV
    # saved by Excel as "CSV (Comma delimited)" (Windows-1252) rather than
    # "CSV UTF-8" -- one accented name is enough -- must all become a message
    # naming the file, not a raw traceback. report.ps1's catch block otherwise
    # prints its "no input files found / OneDrive placeholders" hint, which is
    # actively misleading for a problem that has nothing to do with OneDrive.
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            fieldnames = [(name or "").strip().lower() for name in (reader.fieldnames or [])]
            _require_columns(path, fieldnames)

            rows = []
            for offset, raw in enumerate(reader, start=2):
                # DictReader stashes any field past the header count under the
                # None key instead of raising. The one way a row grows an extra
                # field is an unquoted "Last, First" name -- its comma reads as
                # a column separator -- so a silent .get() here would truncate
                # the name and file a real member under GEB-1 with no trace.
                if None in raw:
                    raise MembershipError(
                        f"{path}: row {offset} has more fields than the header "
                        f"-- a \"Last, First\" name likely needs quotes"
                    )
                rows.append((offset,
                             _cell(raw, fieldnames, "email"),
                             _cell(raw, fieldnames, "name")))
            return rows
    except (OSError, UnicodeDecodeError) as error:
        raise MembershipError(f"{path}: {error}") from error


def _read_xlsx(path):
    """The same, from the first sheet of a workbook.

    Imported here rather than at module scope so the CSV path -- and every
    caller that only ever touches it -- keeps working if openpyxl is missing.
    """
    import zipfile

    import openpyxl
    from openpyxl.utils.exceptions import InvalidFileException

    workbook = None
    try:
        # data_only: a formula cell must yield what Excel last displayed, not
        # its source text. read_only: the list is small, but the flag also
        # keeps openpyxl from materialising the blank rows Excel leaves behind.
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
        sheet = workbook.worksheets[0]
        rows = sheet.iter_rows(values_only=True)
        header = next(rows, None) or ()
        fieldnames = [_text(value).lower() for value in header]
        _require_columns(path, fieldnames)

        found = []
        for offset, raw in enumerate(rows, start=2):
            cells = [_text(value) for value in raw]
            # Excel hands back every row the sheet has ever held, so a list
            # edited down from a longer one arrives with blank rows below the
            # data. Skipping them is what makes the format usable by hand --
            # but only when the whole row is blank. A row with a note and no
            # name falls through to the "neither an email nor a name" error,
            # because that one is a real member about to be filed under GEB-1.
            if not any(cells):
                continue
            found.append((offset,
                          _column(cells, fieldnames, "email"),
                          _column(cells, fieldnames, "name")))
        return found
    except (OSError, zipfile.BadZipFile, InvalidFileException,
            ValueError, KeyError, TypeError) as error:
        # A CSV saved and renamed to .xlsx is the obvious wrong move; an .xls
        # renamed likewise is the other one. They surface as BadZipFile (which
        # descends straight from Exception, so it needs naming) and as
        # InvalidFileException respectively. Same reasoning as the CSV path:
        # name the file, never let a traceback escape.
        raise MembershipError(f"{path}: {error}") from error
    finally:
        if workbook is not None:
            workbook.close()


def _text(value):
    """A cell as the string a person would have typed into it.

    Excel decides on its own that some cells are numbers or dates; whatever it
    hands back has to compare against the source data as text.
    """
    if value is None:
        return ""
    return str(value).strip()


def _column(cells, fieldnames, wanted):
    """The named cell of a row, tolerating a short row.

    Excel stops a row at its last non-empty cell, so a row whose name is blank
    can arrive with fewer cells than the header has columns.
    """
    if wanted not in fieldnames:
        return ""
    index = fieldnames.index(wanted)
    return cells[index] if index < len(cells) else ""


def _cell(raw, fieldnames, wanted):
    """The named cell, tolerating the header's original case and spacing."""
    for key, value in raw.items():
        if key is not None and key.strip().lower() == wanted:
            return value or ""
    return ""
