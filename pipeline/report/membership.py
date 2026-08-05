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


def load_membership(path):
    """The configured members, or None when there is no file.

    None is the normal state on a machine that has not been given the list, and
    it must stay cheap and silent: the report is expected to run without it.
    """
    path = Path(path)
    if not path.exists():
        return None

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
            for column in REQUIRED_COLUMNS:
                if column not in fieldnames:
                    raise MembershipError(
                        f"{path}: missing the required column {column!r} "
                        f"(found: {', '.join(fieldnames) or 'nothing'})"
                    )

            entries = []
            # DictReader yields the first data row as row 2 of the file; naming
            # the file's own line number is what makes the message actionable.
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
                email = normalise_email(_cell(raw, fieldnames, "email"))
                name = normalise_name(_cell(raw, fieldnames, "name"))
                if not email and not name:
                    raise MembershipError(
                        f"{path}: row {offset} carries neither an email nor a name"
                    )
                entries.append(Entry(email=email, name=name))
    except (OSError, UnicodeDecodeError) as error:
        raise MembershipError(f"{path}: {error}") from error

    if not entries:
        raise MembershipError(f"{path}: no entries")
    return Membership(entries=tuple(entries))


def _cell(raw, fieldnames, wanted):
    """The named cell, tolerating the header's original case and spacing."""
    for key, value in raw.items():
        if key is not None and key.strip().lower() == wanted:
            return value or ""
    return ""
