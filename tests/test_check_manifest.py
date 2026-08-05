"""The Windows preflight's manifest, checked against the tree it describes.

`check.ps1` is how an operator on a machine without `git pull` learns whether the
files they hand-copied are the current ones. It works by looking for a marker
string that only the current version of each listed file contains.

That makes it a claim about the repository, and claims rot. Two ways, both of
which had already happened when this test was written:

* a listed file is renamed or removed, and the entry points at nothing;
* a marker is edited out of the file it identifies, so the entry reports STALE
  forever, on a file that is in fact current.

Either way the operator sees red on something that is fine, learns that red
means nothing, and stops reading the output -- at which point the preflight has
become worse than not having one, because it still looks like assurance.

Nothing here checks that the manifest is *complete*; no test can know which
files matter. It checks only that every claim it does make is true.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CHECK_SCRIPT = REPO_ROOT / "check.ps1"

# Mirrors the PowerShell hashtable literal:
#     @{ Path = "a\b.py"; Marker = "x"; Why = "..." }
# Either quote style, because the manifest uses single quotes where the marker
# itself contains a double quote.
ENTRY = re.compile(
    r'Path\s*=\s*(["\'])(?P<path>.+?)\1\s*;\s*'
    r'Marker\s*=\s*(["\'])(?P<marker>.+?)\3'
)


def _entries():
    text = CHECK_SCRIPT.read_text(encoding="utf-8")
    return [(m.group("path"), m.group("marker")) for m in ENTRY.finditer(text)]


def test_the_manifest_parses_at_all():
    """A parser that silently matches nothing would make every test below pass.

    The count is a floor, not a pin: entries are added as the project grows, and
    a test that had to be edited for every addition would be edited without
    thought. It only has to be high enough that a broken regex cannot slip by.
    """
    entries = _entries()

    assert len(entries) >= 30, f"only parsed {len(entries)} manifest entries"


@pytest.mark.parametrize("path,marker", _entries(),
                         ids=[f"{p}::{m[:24]}" for p, m in _entries()])
def test_every_manifest_entry_names_a_file_that_carries_its_marker(path, marker):
    """One case per entry, so a failure names the offender rather than a count.

    The marker test is a literal substring search, matching what `check.ps1`
    does: `Select-String -Pattern ([regex]::Escape($entry.Marker))`.
    """
    target = REPO_ROOT / Path(path.replace("\\", "/"))

    assert target.exists(), (
        f"check.ps1 lists {path}, which does not exist. An entry pointing at a "
        f"renamed or deleted file reports MISSING on every run."
    )
    body = target.read_text(encoding="utf-8", errors="replace")
    assert marker in body, (
        f"check.ps1 identifies {path} by {marker!r}, which the file does not "
        f"contain. The entry reports STALE forever, on a file that is current."
    )


def test_no_manifest_path_is_absolute():
    """Paths are repo-relative; `check.ps1` joins them onto its own location."""
    absolute = [path for path, _ in _entries()
                if path.startswith(("/", "\\")) or ":" in path[:3]]

    assert not absolute, f"absolute paths in the manifest: {absolute}"
