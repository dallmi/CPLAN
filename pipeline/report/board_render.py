"""Render the Plan trust board from a frozen template and a data object.

The same bargain the campaign dashboard and the leadership attention board
already make, for the third frozen artefact: the markup lives in
`pipeline/dashboard/plan-trust.template.html`, everything that varies arrives
as data, and nothing here writes a tag. `template_engine` does the
substitution, so there is one answer to what an unfilled placeholder does.

What a board adds on top of a dashboard is that it is defined twice.
`dashboard_skill.PLAN_TRUST` tells the agent which five panels to draw and what
question and footnote each must print; this template draws the same five for a
reader who never talks to the agent. Those words therefore sit in the template
beside the styles they are set in -- including the read-out, whose only two
variables are the figures the board file's `Source:` line permits it to state --
and `tests/test_report_plan_trust.py` reads both files and fails when they
drift apart.

The order of the bars is the renderer's, and it is descending everywhere. No
panel here carries a category order of its own: a field, a division and an
anomaly are all things one thing is worst at, unlike the audience bands on the
leadership board, whose order is a size and survives being re-ranked by nobody.
"""

from pathlib import Path

from pipeline.report.template_engine import (
    TemplateError,
    esc,
    load_template as _load_template,
    render_chosen_rows,
    substitute,
)

PIPELINE_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = PIPELINE_DIR / "dashboard" / "plan-trust.template.html"

__all__ = [
    "TemplateError", "build_view", "load_template", "render", "validate",
]

# ---------------------------------------------------------------------------
# BOARD DEFINITION -- not data, and not presentation either.
# ---------------------------------------------------------------------------
# Which panel carries the board's single red bar. One panel, named, checkable.
HIGHLIGHT_PANEL = "field_completeness"

# The one anomaly that is not a fault. Archiving is a list-size workaround in
# the source system rather than a relevance signal, so the row is plotted -- it
# belongs to the block the panel cites -- and carries a qualifier saying what
# it is not. Without it the second-tallest bar on that panel reads as the
# second-worst thing about the records.
ANOMALY_QUALIFIERS = {
    "Archived": "(list-size workaround, not a fault)",
}

# The printed source line. It names what produced the board and the vintage it
# was produced from, never a filename -- a filename goes stale the next time
# the pack is rebuilt -- and the signature travels with it, because an image is
# forwarded without its author.
#
# "CPLAN Agent" rather than the pack: a reader who wants this board again goes
# to the agent, not to the files behind it. Every board and every agent answer
# names the agent here -- a source line that varies by artefact is a source
# line nobody learns to recognise.
SOURCE_PREFIX = "Source: CPLAN Agent"
SIGNATURE = "Powered by ECC Measurement & Insights"

# Planning completeness is a percentage, so its axis runs to 100 rather than to
# the tallest bar. Scaling a percentage to its own maximum would draw 62%
# against a top bar of 91% at 68% of the axis, which reads as a wider spread
# than the data holds. On a board about what can be trusted, that is the wrong
# direction to be wrong in. The counts in the other three panels have no
# natural ceiling and keep an axis set by their own longest bar.
COMPLETENESS_AXIS_MAX = 100

# ---------------------------------------------------------------------------

# Approved tokens only, the same restriction the other two render under. Four
# is the whole set: this is a grey board with one red bar on it.
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
    """Render the whole board from a view built by `build_view`.

    Every list on this board is a chosen-rows list: the four bar panels pick
    between a label inside the bar and one after it, and the anomaly names pick
    between a plain name and one carrying a qualifier. There is no list here
    whose rows are all one shape, so there is no plain `rows` loop to run.
    """
    page, rows = load_template(template_path)
    scalars = dict(view["scalars"])
    for name, items in view["chosen_rows"].items():
        scalars[name] = render_chosen_rows(rows, items)
    return substitute(page, scalars, where="page")


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------
def swiss(number):
    """1234567 -> 1'234'567, the separator the rest of CPLAN already prints."""
    return f"{int(round(number)):,}".replace(",", "’")


def bar_width(value, axis_max):
    """A bar's width as a CSS percentage of its panel's axis.

    One decimal, with a bare ".0" dropped: an axis reading "100.0%" in the
    markup and "100%" beside it is two spellings of one number, and a golden
    file records whichever the last edit happened to produce.
    """
    share = min(value / axis_max, 1.0) if axis_max else 0.0
    text = f"{share * 100:.1f}"
    if text.endswith(".0"):
        text = text[:-2]
    return text + "%"


# ---------------------------------------------------------------------------
# Validation -- things that are true of the data, not of the design
# ---------------------------------------------------------------------------
def validate(data):
    """Return the list of complaints about `data`, empty when it is sound.

    These are the arithmetic the pack guarantees and a hand-edited data file
    can break. The division panels overlap -- an activity naming two divisions
    is counted under both -- so their bars are not required to sum to anything;
    what can still be said is that no part of the portfolio exceeds the whole.
    """
    complaints = []
    total = data["activities_in_scope"]

    for row in data["field_completeness"]:
        if row["filled"] + row["missing"] != total:
            complaints.append(
                f"{row['field']}: {swiss(row['filled'])} filled + "
                f"{swiss(row['missing'])} missing is not the "
                f"{swiss(total)} activities in scope"
            )

    # The distinction panel 1's footnote turns on: a field absent from the
    # export is not counted, rather than counted as missing. A field claiming
    # both would be drawn as a bar and disclaimed underneath it.
    counted = {row["field"] for row in data["field_completeness"]}
    for field in data["fields_not_counted"]:
        if field in counted:
            complaints.append(
                f"{field} is listed as not counted and also carries a "
                f"completeness row -- it cannot be both"
            )

    if data["unknown_audience_band"] > total:
        complaints.append(
            f"{swiss(data['unknown_audience_band'])} activities have an unknown "
            f"audience band, but only {swiss(total)} are in scope"
        )

    # Scope is a filter, so the export the report read is always at least as
    # large as the board it produced.
    if data["rows_read"] < total:
        complaints.append(
            f"the report read {swiss(data['rows_read'])} rows but reports "
            f"{swiss(total)} activities in scope"
        )

    for row in data["without_pack_by_division"]:
        if row["activities"] > total:
            complaints.append(
                f"{row['division']}: {swiss(row['activities'])} activities "
                f"without a pack link, but only {swiss(total)} are in scope"
            )

    for row in data["median_completeness_by_division"]:
        if not 0 <= row["percent"] <= 100:
            complaints.append(
                f"{row['division']}: median completeness {row['percent']} is "
                f"not a percentage"
            )

    # Panels 2 and 3 are both division bars, and the contrast between them is
    # the point -- one counts a hole, the other measures a fill rate. A
    # division present in one and absent from the other makes that comparison
    # silently incomplete for whichever division is missing.
    pack_divisions = {row["division"] for row in data["without_pack_by_division"]}
    median_divisions = {
        row["division"] for row in data["median_completeness_by_division"]
    }
    for division in sorted(pack_divisions ^ median_divisions):
        complaints.append(
            f"{division} appears in one division panel and not the other"
        )

    return complaints


# ---------------------------------------------------------------------------
# View construction
# ---------------------------------------------------------------------------
def _ranked(items):
    """Sort by value, descending -- an unsorted bar chart makes the reader do
    the ranking the board was supposed to do. Ties keep the data file's order,
    so a run is reproducible and a re-ordering is a visible diff."""
    return sorted(items, key=lambda item: item["value"], reverse=True)


def _bars(items, *, axis_max=None, suffix="", highlight=False):
    """Turn one panel's figures into its bar rows.

    `axis_max=None` sets the axis from the panel's own longest bar, which is
    right for a count. A measure with a natural ceiling passes one in.
    """
    ceiling = axis_max if axis_max is not None else max(
        (item["value"] for item in items), default=0
    )
    rows = []
    for index, item in enumerate(items):
        share = (item["value"] / ceiling) if ceiling else 0.0
        rows.append({
            "template": "bar_inside" if share >= LABEL_INSIDE_FROM else "bar_outside",
            "width": bar_width(item["value"], ceiling),
            "colour": ACCENT if (highlight and index == 0) else GREY_4,
            # Grouped the way every other figure on the board is grouped. A bar
            # reading 1204 beside a header reading 1'842 puts two number
            # formats on one image, and the reader has to settle which is the
            # house style before they can read either.
            "value": f"{swiss(item['value'])}{suffix}",
        })
    return rows


def _names(items):
    return [{"template": "name_row", "name": esc(item["name"])} for item in items]


def _qualified_names(items):
    """The anomaly names, each with the qualifier its row has earned."""
    rows = []
    for item in items:
        text = ANOMALY_QUALIFIERS.get(item["name"], "")
        rows.append({
            "template": "name_row_qualified" if text else "name_row",
            "name": esc(item["name"]),
            **({"qualifier": esc(text)} if text else {}),
        })
    return rows


def build_view(data):
    """Turn the figures into every string the template asks for.

    `data` carries counts and labels only -- no colours, no widths, no
    percentages. Everything presentational is derived here, so that swapping
    one period's figures for another's cannot change how the board looks.
    """
    missing = _ranked([
        {"name": row["field"], "value": row["missing"]}
        for row in data["field_completeness"] if row["missing"] > 0
    ])
    # Named rather than dropped. A field with nothing missing is not a bar, and
    # a reader who cannot see it listed cannot tell it from one the export left
    # out -- which is the very distinction the panel's footnote is about.
    complete = [
        row["field"] for row in data["field_completeness"] if row["missing"] == 0
    ]

    pack = _ranked([
        {"name": row["division"], "value": row["activities"]}
        for row in data["without_pack_by_division"]
    ])
    median = _ranked([
        {"name": row["division"], "value": row["percent"]}
        for row in data["median_completeness_by_division"]
    ])
    anomalies = _ranked([
        {"name": row["anomaly"], "value": row["count"]}
        for row in data["record_anomalies"]
    ])

    scalars = {
        "title": esc(data["title"]),
        "subtitle": esc(data["subtitle"]),
        "period_label": esc(data["period_label"]),
        "data_as_of": esc(data["data_as_of"]),
        "base_label": swiss(data["activities_in_scope"]),

        "complete_fields": ", ".join(esc(field) for field in complete),
        "not_counted_fields": ", ".join(
            esc(field) for field in data["fields_not_counted"]
        ),

        "rows_read": swiss(data["rows_read"]),
        "unknown_audience_band": swiss(data["unknown_audience_band"]),

        # Assembled here rather than carried whole, so no data file can ship a
        # board whose footer names no date.
        "footer_line": esc(
            f"{SOURCE_PREFIX} · Data as of {data['data_as_of']} · {SIGNATURE}"
        ),
    }

    return {
        "scalars": scalars,
        "chosen_rows": {
            "field_names": _names(missing),
            "field_bars": _bars(
                missing, highlight=HIGHLIGHT_PANEL == "field_completeness"),

            "pack_names": _names(pack),
            "pack_bars": _bars(pack),

            "median_names": _names(median),
            "median_bars": _bars(
                median, axis_max=COMPLETENESS_AXIS_MAX, suffix="%"),

            "anomaly_names": _qualified_names(anomalies),
            "anomaly_bars": _bars(anomalies),
        },
    }
