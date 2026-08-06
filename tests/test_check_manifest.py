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

Both are checked here. The first needs nothing but the file: every entry names
a file that exists and contains its marker, which is what catches a marker
chosen from a version of the file that never landed.

The second was long treated as a review question, and review lost: thirty of
the fifty-five listed files were simultaneously in that state, including three
changed the same day the count was taken. It is mechanically detectable after
all -- git holds the version each file's current state replaced, and a marker
that is also in *that* version cannot tell the two apart. That is the whole
test. It needs a git checkout, so it is the one assertion here that does not
hold on a hand-copied directory; it is skipped there rather than passed, since
the machine that commits is the machine it has to fail on.

No PowerShell required -- the manifest is parsed out of the script text, which
is also why the shape it accepts is asserted (a silently unparsed manifest
would make every assertion below vacuous).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CHECK_PS1 = REPO_ROOT / "check.ps1"

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


def test_every_entry_line_in_the_script_was_parsed():
    """One entry the regex misses is one file no test here says anything about.

    PowerShell would still read that entry -- it is the tests that would go
    blind, and silently: a typo in the quoting, an extra space, a `Why` before
    the `Marker`, and the file drops out of every assertion above while the
    manifest itself keeps working. Counting the hash-table lines in the script
    against the entries parsed out of it is the only way to notice.
    """
    lines = [line.strip() for line in CHECK_PS1.read_text(encoding="utf-8").splitlines()]
    entry_lines = [line for line in lines if line.startswith("@{")]
    assert len(entry_lines) == len(ENTRIES), (
        f"{len(entry_lines)} manifest lines in check.ps1, but {len(ENTRIES)} parsed -- "
        "an entry the tests here cannot see is an entry they do not check"
    )


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


def _git(*args: str) -> str | None:
    """`git <args>` in this repository, or None if it fails (or git is absent).

    Decoded with `errors="replace"`, like every other file read here: a blob
    that is not valid UTF-8 must produce a comparison, not a crash.
    """
    try:
        done = subprocess.run(
            ["git", "-C", str(REPO_ROOT), *args], capture_output=True, timeout=30
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    return done.stdout.decode("utf-8", errors="replace")


IN_GIT_CHECKOUT = _git("rev-parse", "--git-dir") is not None

MANIFEST_PATHS = sorted({path for path, _, _ in ENTRIES})


def _superseded_version(path: str, current: str) -> str | None:
    """The committed content this file's current content replaced.

    Uncommitted edits count: the version being superseded is then HEAD's, and
    the marker has to be added *with* the change rather than in a later commit
    that only fixes the manifest. Returns None when there is nothing to compare
    against -- an untracked file, or one that has never changed since it was
    added.
    """
    last = _git("log", "-1", "--format=%H", "--", path)
    if not last or not last.strip():
        return None  # untracked: no earlier version can exist anywhere
    sha = last.strip()
    committed = _git("show", f"{sha}:{path}")
    if committed is not None and committed != current:
        return committed  # the file has uncommitted changes
    return _git("show", f"{sha}^:{path}")  # None when the file is new in that commit


@pytest.mark.skipif(not IN_GIT_CHECKOUT, reason="needs a git checkout: compares against the superseded version")
@pytest.mark.parametrize("path", MANIFEST_PATHS)
def test_every_listed_file_has_a_marker_the_version_it_replaced_lacked(path: str):
    """A changed file must gain a marker in the same change.

    Fix by adding a second entry rather than editing the existing marker, so
    each file keeps every claim already made about it -- check.ps1's own
    comments say why, and the module docstring says what this catches.
    """
    relative = path.replace("\\", "/")
    current = (REPO_ROOT / relative).read_text(encoding="utf-8", errors="replace")
    superseded = _superseded_version(relative, current)
    if superseded is None:
        return  # new or untracked file: every marker in it is necessarily new

    markers = [marker for entry_path, marker, _ in ENTRIES if entry_path == path]
    fix = (
        "bump $manifestVersion at the top of check.ps1 -- the date, or the suffix when the date "
        "is already today's"
        if relative == CHECK_PS1.name
        else "add a second entry whose marker is unique to the new version"
    )
    assert any(marker not in superseded for marker in markers), (
        f"{path} changed, but every marker check.ps1 has for it ({markers}) was already in the "
        f"version this one replaced -- so a copy from before that change reports CURRENT. To fix: {fix}."
    )


def test_no_manifest_path_is_absolute():
    """`check.ps1` joins every path onto its own location with `Join-Path`.

    An absolute path survives that join unchanged, so the entry would silently
    check a file outside the copy being verified -- on the author's machine it
    passes, on the operator's it reports MISSING for a reason no one can see
    from the output.
    """
    absolute = [path for path, _, _ in ENTRIES
                if path.startswith(("/", "\\")) or ":" in path[:3]]

    assert not absolute, f"absolute paths in the manifest: {absolute}"
