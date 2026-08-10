"""The pre-commit guard, against the two leaks that already happened here.

Both were checked beforehand and both got through, which is why the guard reads
the staged diff and nothing else:

* A plan document quoted an absolute scratch path. On the machine this is
  written on, the directory names spell out the organisation -- so a path is a
  brand leak wearing a different hat, in a repository that is public.
* The check that should have caught it ran `git grep`, which searches TRACKED
  files. The document was new and unstaged, so the search matched nothing and
  printed nothing, and "no output" was read as "clean".

Nothing in this file names a real forbidden term. The guard reads its terms
from a local file precisely so the repository never holds the list, and a test
that hardcoded one would put it back -- while also tripping the guard on its
own commit.
"""

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = REPO_ROOT / ".githooks" / "pre-commit"

# The sample paths below are assembled rather than written out, because this
# file is itself committed and the guard refuses absolute paths with no
# exceptions. Exempting the test that proves the guard works would be the first
# entry on an exemption list, and an exemption list is what a guard is widened
# through. Assembling them costs one line and leaves the rule absolute.
HOME = "/User" + "s/someone"
SCRATCH = "/private/t" + "mp/claude-501/-Users-someone-Documents-Work"
MOUNT = "/Volume" + "s/External"


def _run(diff, terms_file=None):
    """Feed the hook a diff on stdin and return (exit code, combined output)."""
    env = {"PATH": "/usr/bin:/bin:/usr/local/bin"}
    if terms_file is not None:
        env["CPLAN_FORBIDDEN_TERMS"] = str(terms_file)
    result = subprocess.run(
        ["sh", str(HOOK), "--stdin"], input=diff, env=env,
        capture_output=True, text=True)
    return result.returncode, result.stdout + result.stderr


def _diff(path, *added_lines, start=1):
    """A staged diff adding `added_lines` to `path`, in the shape git emits."""
    body = "".join(f"+{line}\n" for line in added_lines)
    return (f"diff --git a/{path} b/{path}\n"
            f"--- a/{path}\n"
            f"+++ b/{path}\n"
            f"@@ -0,0 +{start},{len(added_lines)} @@\n"
            f"{body}")


@pytest.fixture
def terms(tmp_path):
    """A terms file holding invented words, never a real one."""
    path = tmp_path / "forbidden-terms.txt"
    path.write_text("# a comment\n\nExampleCorp\nZZQ\n", encoding="utf-8")
    return path


def test_a_clean_diff_passes(terms):
    code, out = _run(_diff("docs/note.md", "A relative path: docs/plan.md"), terms)
    assert code == 0, out


@pytest.mark.parametrize("line", [
    f"git worktree add --detach {HOME}/projects/thing/scratch HEAD",
    f"SCRATCH={SCRATCH}/scratchpad",
    f"cd {MOUNT}/checkout",
])
def test_an_absolute_local_path_is_refused(terms, line):
    """The exact shape that got through: a real path pasted into a document.

    Refused even when the path names nothing sensitive on its own -- the
    directory names are the payload, and they differ per machine, so the guard
    cannot judge which ones are safe.
    """
    code, out = _run(_diff("docs/superpowers/plans/some-plan.md", line), terms)
    assert code == 1
    assert "absolute local path" in out
    assert "some-plan.md" in out, "the operator is not told which file"


def test_a_forbidden_term_is_refused(terms):
    code, out = _run(_diff("README.md", "Built for ExampleCorp internally."), terms)
    assert code == 1
    assert "forbidden term" in out
    assert "README.md" in out


def test_the_term_match_is_case_insensitive_and_whole_word(terms):
    """`examplecorp` is the same leak; `ZZQuery` is not a leak at all.

    Whole-word matching is what keeps a short term from firing on every longer
    word that contains it -- a guard that cries wolf gets bypassed, and a
    bypassed guard is the state this repository was already in.
    """
    code, _ = _run(_diff("a.md", "shipped to examplecorp last week"), terms)
    assert code == 1

    code, out = _run(_diff("a.md", "the ZZQuery helper returns a frame"), terms)
    assert code == 0, out


def test_the_guard_reports_the_line_the_text_lands_on(terms):
    """A file name is not enough when the file is a thousand lines long."""
    code, out = _run(
        _diff("docs/plan.md", "fine", f"{HOME}/x", "fine", start=618), terms)
    assert code == 1
    assert "docs/plan.md:619" in out, out


def test_removed_lines_are_ignored(terms):
    """Taking the string out must not be blocked by the string being in the diff.

    The commit that removed the path from this repository would otherwise have
    been unable to land -- the guard would have refused the fix for containing
    what it was fixing.
    """
    diff = ("diff --git a/docs/plan.md b/docs/plan.md\n"
            "--- a/docs/plan.md\n"
            "+++ b/docs/plan.md\n"
            "@@ -618,1 +618,1 @@\n"
            f"-git worktree add --detach {HOME}/scratch HEAD\n"
            '+git worktree add --detach "$SCRATCH/t5" HEAD\n')
    code, out = _run(diff, terms)
    assert code == 0, out


def test_paths_are_still_checked_without_a_terms_file(tmp_path):
    """A fresh clone has no terms file, and must not be silently unguarded.

    Half the guard needs no configuration at all, so it runs regardless, and
    the operator is told on stderr that the other half is dormant.
    """
    missing = tmp_path / "not-there.txt"
    code, out = _run(_diff("a.md", f"{HOME}/x"), missing)
    assert code == 1
    assert "absolute local path" in out
    assert "forbidden-terms.txt.example" in out, "no instruction to enable the rest"


def test_the_example_terms_file_is_committed_and_the_real_one_is_not():
    """The pattern `geb-members.csv` sets: placeholders committed, values not."""
    assert (REPO_ROOT / "forbidden-terms.txt.example").exists()
    ignored = subprocess.run(
        ["git", "check-ignore", "forbidden-terms.txt"],
        cwd=REPO_ROOT, capture_output=True, text=True)
    assert ignored.returncode == 0, "forbidden-terms.txt is not ignored"


def test_the_hook_names_no_forbidden_term_itself():
    """Searching for a name by writing it down is the same mistake one level up."""
    text = HOOK.read_text(encoding="utf-8")
    assert "forbidden-terms.txt" in text, "the hook does not read a terms file"
    example = (REPO_ROOT / "forbidden-terms.txt.example").read_text(encoding="utf-8")
    for line in example.splitlines():
        term = line.split("#")[0].strip()
        if term:
            assert term.lower() not in text.lower(), (
                f"the hook hardcodes {term!r} instead of reading the list")
