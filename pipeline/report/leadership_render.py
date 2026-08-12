"""Render the Leadership attention board from a frozen template and figures.

The board answers one decision -- where is executive time going, and where is
it missing from communication that would warrant it -- and its panel list is
fixed before any drawing starts, in
`pipeline/output/agent-builder/upload/12-board-leadership-attention.txt`. This
module draws that list and nothing else. The same discipline as the campaign
activity dashboard, for the same reason: a board improvised per request loses a
rule per request, and the rule it loses is never the same one twice.

What lives where:

* the markup, every style literal of it, in
  `pipeline/dashboard/leadership-attention.template.html`;
* the panel headings, business questions and footnotes in that same file --
  they are the board's definition, so no data file can rewrite the question a
  panel answers;
* the figures in a data object, counts and labels only;
* the rules that turn one into the other, here.

Two of those rules are the board's own and are enforced rather than trusted:

**Exactly one bar on the whole board is red** -- the tallest bar of the
division panel. The instructions permit two red elements in an image; a board
permits one. "At most two" is a budget an improvising agent spends without
noticing, while "this bar, no other" is a property that can be checked, and
`tests/test_report_leadership.py` checks it.

**Panel 3 is never sorted.** Divisions and regions are ranked here, so the data
file may list them in any order; the audience bands keep the order they arrive
in, because their order is a size and re-ranking them by value destroys the one
thing the reader came to read off that panel.
"""

import re
from pathlib import Path

from pipeline.report.template_engine import (
    TemplateError,
    esc,
    load_template as _load_template,
    render_chosen_rows,
    render_rows,
    substitute,
)

PIPELINE_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = PIPELINE_DIR / "dashboard" / "leadership-attention.template.html"

__all__ = [
    "TemplateError", "build_view", "load_template", "render", "validate",
]

# ---------------------------------------------------------------------------
# BOARD DEFINITION -- not data, and not presentation either.
# ---------------------------------------------------------------------------
# The tile captions say what the tile counts. They sit here rather than in the
# data file for the same reason the panel questions sit in the template: a
# board that lets its figures relabel themselves is a board that can be made to
# say anything. The order is the order of the tiles.
TILE_CAPTIONS = (
    "Activities with GEB/GEB-1 involvement",
    "Activities in scope",
    "Share of the plan",
)

# Which panel carries the board's single red bar. One panel, named, checkable.
HIGHLIGHT_PANEL = "divisions"

# The printed source line. It names what produced the board and the vintage it
# was produced from, never a filename -- a filename goes stale the next time the
# pack is rebuilt -- and the signature travels with it, because an image is
# forwarded without its author and it is the copy that arrives without a date.
#
# "CPLAN Agent" rather than the pack it read: a reader holding this board and
# wanting the next question answered has to know what to go back to, and the
# pack is a directory nobody can ask anything. The vintage still travels in the
# same line, so naming the producer gives up nothing about provenance.
SOURCE_PREFIX = "Source: CPLAN Agent"
SIGNATURE = "Powered by ECC Measurement & Insights"

# ---------------------------------------------------------------------------

# Approved tokens only, the same restriction the campaign dashboard renders
# under. Four is the whole set this board needs: it is a grey board with one
# red bar on it.
BLACK = "#000000"
WHITE = "#ffffff"
GREY_4 = "#7a7870"
ACCENT = "#e60000"    # Corporate Red

# Past this share of the axis a value label no longer fits outside its bar, so
# it is set inside instead. Two thirds is where the chart standards put it.
LABEL_INSIDE_FROM = 2 / 3


# ---------------------------------------------------------------------------
# Template loading
# ---------------------------------------------------------------------------
def load_template(path=None):
    """Split this board's template file into the page and its row templates."""
    return _load_template(path or TEMPLATE_PATH)


def render(view, *, template_path=None):
    """Render the whole board from a view built by `build_view`."""
    page, rows = load_template(template_path)
    scalars = dict(view["scalars"])
    for name, items in view["rows"].items():
        scalars[name] = render_rows(rows, name, items)
    for name, items in view["chosen_rows"].items():
        scalars[name] = render_chosen_rows(rows, items)
    return substitute(page, scalars, where="page")


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------
def swiss(number):
    """1234567 -> 1'234'567, the separator the rest of CPLAN already prints."""
    return f"{int(round(number)):,}".replace(",", "’")


def percent(share, digits=0):
    return f"{share * 100:.{digits}f}%"


def bar_width(value, axis_max):
    """A bar's width as a CSS percentage of the panel's longest bar.

    One decimal, with a bare ".0" dropped: an axis reading "100.0%" in the
    markup and "100%" beside it is two spellings of one number, and a golden
    file records whichever the last edit happened to produce.
    """
    share = (value / axis_max) if axis_max else 0.0
    text = f"{share * 100:.1f}"
    if text.endswith(".0"):
        text = text[:-2]
    return text + "%"


# ---------------------------------------------------------------------------
# Validation -- things that are true of the data, not of the design
# ---------------------------------------------------------------------------
_NUMBER = re.compile(r"\d[\d’]*%?")


def validate(data):
    """Return the list of complaints about `data`, empty when it is sound.

    These are the arithmetic the pack guarantees and a hand-edited data file
    can break. The audience bands are exclusive, so their counts must close on
    the portfolio total; divisions and regions overlap, so theirs must not be
    required to -- an activity naming two divisions is counted under both, and
    demanding that those bars sum to the total would be demanding the data lie.
    What can still be said about an overlapping block is that no part of it
    exceeds the whole.
    """
    complaints = []

    total = data["activities_total"]
    leadership = data["leadership_activities"]

    if leadership > total:
        complaints.append(
            f"{swiss(leadership)} activities record leadership involvement, "
            f"but only {swiss(total)} are in scope"
        )

    if data["large_audience_activities"] > total:
        complaints.append(
            f"{swiss(data['large_audience_activities'])} activities fall in the "
            f"top two audience bands, but only {swiss(total)} are in scope"
        )

    band_leadership = sum(band["leadership"] for band in data["audience_bands"])
    if band_leadership != leadership:
        complaints.append(
            f"the audience bands account for {swiss(band_leadership)} activities "
            f"with leadership involvement, but the portfolio records "
            f"{swiss(leadership)} -- the bands are exclusive and must close on it"
        )

    band_total = sum(band["activities"] for band in data["audience_bands"])
    if band_total != total:
        complaints.append(
            f"the audience bands cover {swiss(band_total)} activities of "
            f"{swiss(total)} -- the bands are exclusive and must close on it"
        )

    for block in ("divisions", "regions"):
        for item in data[block]:
            if item["leadership"] > item["activities"]:
                complaints.append(
                    f"{item['name']}: {swiss(item['leadership'])} activities with "
                    f"leadership involvement out of {swiss(item['activities'])}"
                )
            elif item["leadership"] > leadership:
                complaints.append(
                    f"{item['name']} alone records {swiss(item['leadership'])} "
                    f"activities with leadership involvement, more than the "
                    f"portfolio's {swiss(leadership)}"
                )

    complaints.extend(_readout_complaints(data, total, leadership))
    return complaints


def _readout_complaints(data, total, leadership):
    """Every figure the read-out quotes must be one the board holds.

    The read-out is the one panel whose figures are written rather than
    plotted, so it is the one panel that can go stale silently: next quarter's
    counts arrive, the prose keeps last quarter's, and the board contradicts
    itself in the only place a reader takes a sentence at face value.
    """
    known = {
        swiss(total),
        swiss(leadership),
        swiss(data["large_audience_activities"]),
        percent(leadership / total if total else 0.0),
    }
    for block in ("divisions", "regions", "audience_bands"):
        for item in data[block]:
            known.add(swiss(item["activities"]))
            known.add(swiss(item["leadership"]))

    quoted = set(_NUMBER.findall(data["readout"]))
    stale = sorted(quoted - known)
    if stale:
        return [
            "the read-out quotes " + ", ".join(stale)
            + ", which no figure on this board states"
        ]
    return []


# ---------------------------------------------------------------------------
# View construction
# ---------------------------------------------------------------------------
def _bars(items, prefix, *, highlight):
    """Turn one panel's figures into its rows, longest bar first in the markup.

    The caller has already put the items in the order the panel wants them;
    the axis is the largest value among them, so the longest bar fills the
    plot and every other bar is read against it.
    """
    axis_max = max((item["leadership"] for item in items), default=0)
    rows = []
    for index, item in enumerate(items):
        width = bar_width(item["leadership"], axis_max)
        inside = axis_max and item["leadership"] / axis_max >= LABEL_INSIDE_FROM
        rows.append({
            "template": f"{prefix}_bar_{'inside' if inside else 'outside'}",
            "label": esc(item["name"]),
            "width": width,
            "colour": ACCENT if (highlight and index == 0) else GREY_4,
            "value": swiss(item["leadership"]),
        })
    return rows


def _ranked(items):
    """Sort by value, descending -- an unsorted bar chart makes the reader do
    the ranking the board was supposed to do."""
    return sorted(items, key=lambda item: item["leadership"], reverse=True)


def build_view(data):
    """Turn the figures into every string the template asks for.

    `data` carries counts and labels only -- no colours, no widths, no
    percentages. Everything presentational is derived here, so that swapping
    one quarter's figures for another's cannot change how the board looks.
    """
    total = data["activities_total"]
    leadership = data["leadership_activities"]
    share = leadership / total if total else 0.0

    tiles = [
        {"value": swiss(leadership), "caption": TILE_CAPTIONS[0]},
        {"value": swiss(total), "caption": TILE_CAPTIONS[1]},
        {"value": percent(share), "caption": TILE_CAPTIONS[2]},
    ]

    scalars = {
        "eyebrow": esc(data["eyebrow"]),
        "title": esc(data["title"]),
        "subtitle": esc(data["subtitle"]),
        "period_label": esc(data["period_label"]),
        "data_as_of": esc(data["data_as_of"]),
        "base_label": f"{swiss(total)} activities in scope",
        "readout": esc(data["readout"]),
        "footer_source": esc(
            f"{SOURCE_PREFIX} · Data as of {data['data_as_of']} · {SIGNATURE}"
        ),
    }

    return {
        "scalars": scalars,
        "rows": {"tiles": tiles},
        "chosen_rows": {
            # Ranked: one thing is the answer, and the answer goes on top.
            "division_bars": _bars(
                _ranked(data["divisions"]), "division",
                highlight=HIGHLIGHT_PANEL == "divisions",
            ),
            # Not ranked. The bands arrive in band order and keep it.
            "audience_bars": _bars(
                data["audience_bands"], "audience",
                highlight=HIGHLIGHT_PANEL == "audience_bands",
            ),
            "region_bars": _bars(
                _ranked(data["regions"]), "region",
                highlight=HIGHLIGHT_PANEL == "regions",
            ),
        },
    }
