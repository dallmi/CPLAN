"""The substitution machinery every frozen board is rendered through.

This is the half of `dashboard_render` that was never about the campaign
activity page: split a template file into its page and its row templates,
replace `{{ name }}`, refuse to leave one behind. It moved here when the
leadership attention board arrived and would otherwise have carried a second
copy -- and a second copy is a second answer to "what does an unfilled
placeholder do", which is exactly the question a shipped page must not have two
answers to.

Nothing in this module knows a board. It holds no path, no threshold and no
figure, so a board file is the only place a board is described.

The rule the machinery exists to enforce: **every style literal in a finished
page comes from that page's template file.** A renderer builds strings -- a
width, a colour, a count -- and never a tag. That boundary is what lets a
golden file stand as a complete description of how a page looks.
"""

import html
import re
from pathlib import Path

_PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")
_ROWS_BLOCK = re.compile(r"\n?<!--ROWS\n(.*?)\n-->\s*$", re.DOTALL)
_ROW_HEADER = re.compile(r"^\[(\w+)\]$", re.MULTILINE)


class TemplateError(RuntimeError):
    """A placeholder had no value, or a row template was missing."""


def load_template(path):
    """Split a template file into the page and its row templates.

    The row templates sit in a trailing `<!--ROWS ... -->` comment so the file
    stays a single artefact: one thing to review, one thing to freeze, one
    thing a diff can be read against.
    """
    text = Path(path).read_text(encoding="utf-8")
    match = _ROWS_BLOCK.search(text)
    if match is None:
        raise TemplateError(f"no <!--ROWS ... --> block in {path}")
    page = text[: match.start()].rstrip("\n") + "\n"
    return page, _parse_rows(match.group(1))


def _parse_rows(block):
    rows = {}
    headers = list(_ROW_HEADER.finditer(block))
    for index, header in enumerate(headers):
        end = headers[index + 1].start() if index + 1 < len(headers) else len(block)
        body = block[header.end() : end]
        # A row template is joined with "\n", so it must not carry its own
        # leading or trailing blank lines -- they would show up as drifting
        # whitespace between rows and make the golden file churn.
        rows[header.group(1)] = body.strip("\n")
    return rows


def substitute(template, values, *, where):
    """Replace every `{{ name }}` in `template`, refusing to leave one behind.

    Silently rendering an unresolved placeholder is how a dashboard ends up
    shipping the literal text "{{ leadership_value }}" to a management audience.
    """
    missing = set()

    def replace(match):
        name = match.group(1)
        if name not in values:
            missing.add(name)
            return match.group(0)
        return str(values[name])

    result = _PLACEHOLDER.sub(replace, template)
    if missing:
        raise TemplateError(
            f"{where}: no value for {', '.join(sorted(missing))}"
        )
    return result


def render_rows(rows, name, items, *, indent=""):
    """Expand one row template once per item and join the results."""
    if name not in rows:
        raise TemplateError(f"no row template named [{name}]")
    rendered = [
        substitute(rows[name], item, where=f"row [{name}] #{index}")
        for index, item in enumerate(items)
    ]
    if not indent:
        return "\n".join(rendered)
    return "\n".join(indent + line if line else line
                     for chunk in rendered for line in chunk.split("\n"))


def render_chosen_rows(rows, items, *, key="template"):
    """Expand a list whose items each name the row template they need.

    `render_rows` is the common case: one shape, many rows. A bar chart is the
    other case -- a long bar carries its value label inside itself and a short
    one carries it outside, so two rows of the same chart are two shapes. The
    choice is the renderer's (it knows the width), the markup is the template's
    (it knows what a bar looks like), and this function is the seam. The key is
    removed before substitution so a template never sees it.
    """
    rendered = []
    for index, item in enumerate(items):
        if key not in item:
            raise TemplateError(f"row #{index} names no template under '{key}'")
        name = item[key]
        if name not in rows:
            raise TemplateError(f"no row template named [{name}]")
        values = {field: value for field, value in item.items() if field != key}
        rendered.append(substitute(rows[name], values, where=f"row [{name}] #{index}"))
    return "\n".join(rendered)


def esc(text):
    """Escape a data string for HTML.

    Everything a template receives is escaped, including prose, so a data
    object never carries markup or entities. Write "&" and "—" literally in the
    data; the file is UTF-8 and the page declares it.
    """
    return html.escape(str(text), quote=False)
