"""check.ps1's manifest actually matches the files it names.

`check.ps1` is the only thing that tells an operator on a machine without git
which files to hand-copy, and the only thing that prints their download URLs.
It decides "current" vs "stale" by looking for one marker string per file, and
that pairing is maintained by hand -- so it has exactly two failure modes, and
the repository has seen both:

* **A marker that is no longer in the file.** The entry then reports STALE on
  every run, on every machine, forever. Two of the comments in check.ps1 are
  about precisely this ("Marker was 'kit-pass', a class the design-system
  adoption deleted"), and it is worse than useless: it trains an operator to
  read a red result as normal, which is the habit the entries that *do* matter
  depend on not existing.
* **A file changed without its marker being updated**, so a pre-change copy and
  a post-change copy look identical to the check. That is the half-copied
  upgrade the manifest exists to catch, reported as "all files current".

Only the first is mechanically detectable, and that is what this checks: every
entry names a file that exists and contains its marker. The second is a review
question, but pinning the first makes the manifest a thing that can be *tested*
rather than only read, and it is what catches a marker chosen from a version of
the file that never landed.

No PowerShell required -- the manifest is parsed out of the script text, which
is also why the shape it accepts is asserted (a silently unparsed manifest
would make every assertion below vacuous).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

CHECK_PS1 = Path(__file__).resolve().parents[1] / "check.ps1"

# @{ Path = "a\b.py"; Marker = "..."; Why = "..." }, with the marker in either
# quoting style -- both are in use, because a marker containing a double quote
# has to be single-quoted and vice versa.
_ENTRY = re.compile(
    r"""@\{\s*Path\s*=\s*"(?P<path>[^"]+)"\s*;\s*Marker\s*=\s*(?P<quote>["'])(?P<marker>.*?)(?P=quote)\s*;""",
)


def manifest_entries() -> list[tuple[str, str, str]]:
    """(repo-relative path, marker, quote character) for every manifest entry."""
    text = CHECK_PS1.read_text(encoding="utf-8")
    return [(m.group("path"), m.group("marker"), m.group("quote")) for m in _ENTRY.finditer(text)]


ENTRIES = manifest_entries()


def test_the_manifest_was_actually_parsed():
    """Guards every other test here: a regex that matched nothing would make
    them all pass while checking exactly nothing."""
    assert len(ENTRIES) > 20, f"parsed only {len(ENTRIES)} manifest entries out of {CHECK_PS1.name}"
    assert any(path.endswith("scram.py") for path, _, _ in ENTRIES)


@pytest.mark.parametrize("path,marker,quote", ENTRIES, ids=[f"{p}::{m}" for p, m, _ in ENTRIES])
def test_every_manifest_entry_names_a_file_that_contains_its_marker(path: str, marker: str, quote: str):
    target = CHECK_PS1.parent / Path(path.replace("\\", "/"))
    assert target.is_file(), f"check.ps1 lists {path}, which does not exist -- it would report MISSING forever"
    body = target.read_text(encoding="utf-8", errors="replace")
    assert marker in body, (
        f"check.ps1's marker {marker!r} is not in {path} -- that entry reports STALE on every machine, "
        "on every run, and teaches operators to ignore a red result"
    )


@pytest.mark.parametrize("path,marker,quote", ENTRIES, ids=[f"{p}::{m}" for p, m, _ in ENTRIES])
def test_a_double_quoted_marker_carries_no_powershell_expansion(path: str, marker: str, quote: str):
    """`"$foo"` and `"a`b"` are not literals in PowerShell.

    A marker is compared with `[regex]::Escape($entry.Marker)`, so the *regex*
    is safe -- but the string reaches that call already expanded. A `$` or a
    backtick in a double-quoted marker therefore silently becomes something
    other than what is written here, and the entry reports STALE forever. The
    obvious marker for `pipeline\\api\\scram.py` -- its `SCRAM-SHA-256$` prefix
    -- is exactly this trap.
    """
    if quote != '"':
        return  # single-quoted PowerShell strings are literal
    assert "$" not in marker and "`" not in marker, (
        f"{path}: the double-quoted marker {marker!r} would be expanded by PowerShell before it is "
        "compared; single-quote it instead"
    )
