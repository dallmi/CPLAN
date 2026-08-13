"""The drawing code, as one file the agent's sandbox can execute.

The sandbox has a filesystem, Pillow 12 and 23 DejaVu faces, and the knowledge
files land in `/mnt/data` which is also the working directory -- all measured,
see `docs/agent-builder-sandbox-probe.md`. So the drawing code does not have to
be reproduced into a code cell by a model. It ships as a knowledge file and is
read and executed, which removes the size ceiling and, with it, the reason C
looked fragile.

Assembled from the modules rather than written twice. A second copy of
`build_view` is a second answer to what a threshold means, and it would drift
the first time a target moved. The bundler strips the repository imports,
supplies the two helpers those imports provided, and appends an entry point --
and `tests/test_board_bundle.py` renders through the bundle and through the
modules and fails if the two images differ by a byte.

What the bundle deliberately does not carry: the HTML renderer. The names its
functions reference are stubbed to raise, so a call that should never happen in
a sandbox says so instead of failing later with a confusing NameError.
"""

import re
from pathlib import Path

REPORT_DIR = Path(__file__).resolve().parent
SOURCES = ("dashboard_render.py", "board_image.py")

BUNDLE_NAME = "board-draw.txt"

# `esc` is the one thing `build_view` takes from the template engine, and it is
# six lines. Importing the engine into the bundle would drag the whole HTML
# substitution machinery along for one function.
_SHIM = '''
import html as _html
import os as _os

# A module has `__file__`; code handed to exec() does not, and the font
# resolver uses it to find the bundled-face slot. Point it at the directory the
# bundle was run from, which in the sandbox is where the knowledge files are.
if "__file__" not in globals():
    __file__ = _os.path.join(_os.getcwd(), "board-draw.txt")


def esc(text):
    """Escape a data string for HTML. The view is built for a page; the drawn
    board undoes this again in `plain`. Kept so the bundle and the repository
    produce the same view rather than two that agree by accident."""
    return _html.escape(str(text), quote=False)


def _html_only(name):
    def refuse(*_args, **_kwargs):
        raise RuntimeError(
            f"{name} belongs to the HTML renderer and is not in this bundle. "
            f"This file draws; it does not write pages."
        )
    return refuse


TemplateError = RuntimeError
load_template = _html_only("load_template")
render_rows = _html_only("render_rows")
substitute = _html_only("substitute")
_load_template = _html_only("load_template")
'''

_ENTRY = '''

# ---------------------------------------------------------------------------
# Entry point. The agent calls this with the data object the contract
# specifies; everything above is the same code the repository renders with.
# ---------------------------------------------------------------------------
def draw(data, out_path="board.png", thresholds=None):
    """Data object in, image file out. Returns (path, font name, weights)."""
    view = build_view(data, thresholds or THRESHOLDS)
    chosen, overlaps = save(view, out_path)
    if overlaps:                                    # save() already refuses,
        raise RuntimeError(overlaps)                # but never rely on that.
    return out_path, chosen.name, chosen.weights


def draw_from_json(json_path, out_path="board.png"):
    # Imported here rather than at the top: neither bundled module needs `re`
    # or `json` at module scope, and a bundle that imports what it does not use
    # invites the next reader to trim it and break this.
    import json
    import re
    text = Path(json_path).read_text(encoding="utf-8")
    data = json.loads(re.sub(r'"_comment":\\s*\\[[^\\]]*\\],', "", text))
    return draw(data, out_path)
'''

_IMPORT_BLOCK = re.compile(
    r"^from pipeline\.report[^\n]*\((?:[^)]*)\)\n|^from pipeline\.[^\n]*\n",
    re.MULTILINE)


def _strip_repo_imports(source):
    """Remove the imports the bundle supplies itself.

    Only `from pipeline...` lines, including the parenthesised multi-line form.
    Nothing else is rewritten: a bundler that edits code is a second author of
    it, and the equivalence test would be checking the bundler's opinion.
    """
    return _IMPORT_BLOCK.sub("", source)


def build(report_dir=None):
    """The bundle text: shim, both modules, entry point."""
    root = Path(report_dir) if report_dir else REPORT_DIR
    parts = [
        '"""CPLAN board renderer, bundled for a sandbox.\n\n'
        "Assembled by pipeline/report/board_bundle.py from the modules the\n"
        "repository renders with. Do not edit here -- edit there and rebuild,\n"
        "or the drawn board and the page stop agreeing about a figure.\n"
        '"""\n',
        _SHIM,
    ]
    for name in SOURCES:
        source = (root / name).read_text(encoding="utf-8")
        parts.append(f"\n# {'-' * 70}\n# {name}\n# {'-' * 70}\n")
        parts.append(_strip_repo_imports(source))
    parts.append(_ENTRY)
    return "".join(parts)


def write(path):
    text = build()
    Path(path).write_text(text, encoding="utf-8")
    return len(text)
