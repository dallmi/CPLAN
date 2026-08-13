"""Render the campaign-activity dashboard from a frozen template and a data object.

The dashboard used to be regenerated: a model was asked for "the dashboard" and
wrote the markup each time. Four revision rounds were needed to reach a page
that met the design system, and one of those rounds regressed two things an
earlier round had already got right. That is what generation does -- it samples
-- so the fix is not a better prompt but a shorter path: the markup is frozen in
`pipeline/dashboard/campaign-activity.template.html`, and everything that varies
arrives as data.

Nothing in this module writes markup. Every style literal in the finished page,
including the repeating rows, comes out of the template file; the renderer only
substitutes scalars and joins rows. That boundary is the point -- it is what
makes `tests/test_report_dashboard.py` able to pin the output byte for byte, and
what stops a future edit here from quietly changing how the page looks.

The thresholds live in THRESHOLDS below rather than as prose inside the markup,
where they sat until this module existed. "target 12 wks" is the organisation's
target, not a presentation detail, and a regenerated page was re-inventing it
every time.
"""

import math
from pathlib import Path

from pipeline.report.template_engine import (
    TemplateError,
    esc,
    load_template as _load_template,
    render_rows,
    substitute,
)

PIPELINE_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = PIPELINE_DIR / "dashboard" / "campaign-activity.template.html"

__all__ = [
    "THRESHOLDS", "TemplateError", "axis_scale", "build_view", "esc",
    "load_template", "percent", "render", "render_rows", "substitute", "swiss",
    "validate", "wrap_label",
]

# ---------------------------------------------------------------------------
# CONFIGURATION -- this is the block to edit.
# ---------------------------------------------------------------------------
THRESHOLDS = {
    # The pack counts an activity as short notice when its lead time is under
    # this many days -- `metrics.lead_time_stats` against
    # `config.SHORT_NOTICE_DAYS` -- and states it as "Planned at under 7 days'
    # notice". One number answering the question everywhere beats two that
    # quietly disagree, so this is that number and not the mock's fortnight.
    "short_notice_window_days": 7,
    "short_notice_limit_share": 0.15,
    # Share of activities with executive board involvement.
    "leadership_share": 0.20,
}

# No lead-time threshold either, and that one was learned the expensive way.
# The card shipped, drew against real data, and read -367 days: the pack states
# a median over the whole plan, the plan is mostly past, and a lead time
# measured backwards is not a lead time. A forward-looking median would need a
# figure the pack does not compute, so the card is gone rather than labelled.
#
# No planning-horizon threshold, and no large-audience contact threshold.
#
# The pack states neither. Its HORIZON section splits the plan into "planned to
# date", "next 30 days from the data date" and "rest of the period" -- three
# counts, not an average distance -- so a card reading "15.2 weeks planned
# beyond period end" had nothing behind it. And "large audience" is the top two
# audience *bands*, not a contact count: the pack bands an activity, it never
# compares it to 100k. A threshold here would have been a second definition of
# a word the pack already defines.
# ---------------------------------------------------------------------------

# Approved tokens only. The design review closed with thirteen values in the
# page and every one of them from the corporate palette; keeping the set here
# means a future edit cannot drift off it without editing this list first.
BLACK = "#000000"
GREY_3 = "#8e8d83"
GREY_4 = "#7a7870"
GREY_5 = "#5a5d5c"
GREY_6 = "#404040"
GREY_1 = "#cccabc"
SUCCESS = "#6f7a1a"   # RAG green
DANGER = "#bd000c"    # RAG red / Bordeaux I
ACCENT = "#e60000"    # Corporate Red

# Rank ramps for the categorical charts. Black marks the leading category in
# panels 02, 03 and 04 alike -- one rule across the page, which is why the
# priority donut's top segment is black rather than red: "share price
# sensitive" is a regulatory class, not a defect, and RAG red means defect.
PRIORITY_COLOURS = (BLACK, GREY_5, GREY_3, GREY_1)
OWNERSHIP_COLOURS = (BLACK, GREY_5, GREY_5, GREY_3, GREY_3, GREY_1)
LEADERSHIP_COLOURS = (BLACK, GREY_5, GREY_5, GREY_5, GREY_3, GREY_3, GREY_1)
LEADERSHIP_LABEL_COLOURS = (BLACK, GREY_6, GREY_6, GREY_6, GREY_5)

# Chart geometry. These are the dimensions the template's own containers are
# built at; changing one here without changing the template produces bars that
# overflow their box, so they are named rather than repeated as magic numbers.
TIMING_PLOT_HEIGHT = 180
TIMING_BAR_PITCH = 28
TIMING_BAR_ORIGIN = 9
LEADERSHIP_PLOT_HEIGHT = 160
# No fixed ceiling for the leadership axis. It was 0.40, which held for the
# sample and broke on the first real quarter: a team at 100% drew a 400px bar
# in a 160px plot, climbed out of its panel and over the one above it. The
# collision check could not see it -- a bar is not text -- so the ceiling now
# comes from the data, like the timing axis already did.
OWNERSHIP_AXIS_MAX_SHARE = 0.30
MOVING_AVERAGE_WEEKS = 4

# ---------------------------------------------------------------------------
# Template loading
# ---------------------------------------------------------------------------
def load_template(path=None):
    """Split this page's template file into the page and its row templates.

    The machinery lives in `template_engine`, which knows no board. What
    belongs here is only which file this dashboard is frozen into.
    """
    return _load_template(path or TEMPLATE_PATH)


def render(view, *, template_path=None):
    """Render the whole page from a view built by `build_view`."""
    page, rows = load_template(template_path)
    scalars = dict(view["scalars"])
    for name, items in view["rows"].items():
        scalars[name] = render_rows(rows, name, items)
    for name, text in view["insights"].items():
        scalars[name] = (
            render_rows(rows, "insight", [{"text": text}]) if text else ""
        )
    return substitute(page, scalars, where="page")


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------
def swiss(number):
    """1234567 -> 1'234'567, the separator the source data already uses."""
    return f"{int(round(number)):,}".replace(",", "’")


def _round_half_up(value):
    """Python's round() goes to even on a .5 tie; a bar chart should not.

    Two weeks with the same audience must produce the same bar, and 172.5px
    rounding down while 173.5px rounds up is the kind of one-pixel difference
    that shows up in a golden file and in nobody's understanding of why.
    """
    return int(value + 0.5) if value >= 0 else -int(-value + 0.5)


def percent(share, digits=0):
    return f"{share * 100:.{digits}f}%"


def axis_scale(max_value, max_intervals=4):
    """A round ceiling at or above `max_value`, and the step that divides it.

    Returns `(ceiling, step)` where `ceiling` is a multiple of `step` and the
    axis needs no more than `max_intervals` of them. Picking the ceiling from
    the data rather than fixing it means a quiet quarter is not drawn against
    a busy quarter's scale -- and picking a round step is what lets the ticks
    read 400 / 300 / 200 / 100 rather than 354 / 266 / 177 / 89.
    """
    if max_value <= 0:
        return 1, 1
    magnitude = 10 ** math.floor(math.log10(max_value / max_intervals))
    for factor in (1, 2, 5, 10):
        step = int(magnitude * factor) or 1
        ceiling = math.ceil(max_value / step) * step
        if ceiling // step <= max_intervals:
            return int(ceiling), step
    # Unreachable for positive input: factor 10 always divides the magnitude
    # into at most `max_intervals`, but a bare fallback beats a None.
    return int(max_value), int(max_value)


def wrap_label(name):
    """Break a team name across two lines at the space nearest the middle.

    The axis under panel 04 gives each team a narrow column, so the names are
    set on two lines. Choosing the break by measure rather than by "after the
    first word" is what keeps "Personal & Corporate Banking" from stranding a
    lone ampersand at the end of line one.
    """
    words = name.split(" ")
    if len(words) < 2:
        return esc(name)
    midpoint = len(name) / 2
    best, best_distance = 1, None
    for index in range(1, len(words)):
        cut = len(" ".join(words[:index]))
        distance = abs(cut - midpoint)
        if best_distance is None or distance < best_distance:
            best, best_distance = index, distance
    return esc(" ".join(words[:best])) + "<br>" + esc(" ".join(words[best:]))




def _rank_colour(rank, ramp):
    return ramp[min(rank, len(ramp) - 1)]


# ---------------------------------------------------------------------------
# Validation -- things that are true of the data, not of the design
# ---------------------------------------------------------------------------
def validate(data):
    """Return the list of complaints about `data`, empty when it is sound.

    The team-distribution panel is titled a distribution and carries a row
    called "Other / Central Teams", which together promise that the shares
    account for everything. In the design mock they summed to 90%. That is
    harmless in a mock and wrong in a report, so it is checked here rather
    than left to be noticed.
    """
    complaints = []

    total = data["activities_total"]
    priority_sum = sum(item["activities"] for item in data["priorities"])
    if priority_sum != total:
        complaints.append(
            f"priority counts sum to {swiss(priority_sum)}, "
            f"but the period holds {swiss(total)} activities"
        )

    split = data["internal_activities"] + data["external_activities"]
    if split != total:
        complaints.append(
            f"internal + external is {swiss(split)}, "
            f"but the period holds {swiss(total)} activities"
        )

    team_sum = sum(item["activities"] for item in data["teams"])
    if team_sum != total:
        complaints.append(
            f"team distribution covers {swiss(team_sum)} activities of "
            f"{swiss(total)} -- the residual is unnamed"
        )

    if data["activities_in_plan"] < total:
        complaints.append(
            f"the plan holds {swiss(data['activities_in_plan'])} activities, "
            f"fewer than the {swiss(total)} in this period -- a period cannot "
            f"be larger than the plan that contains it"
        )

    weeks = data["weeks"]
    if not weeks:
        complaints.append("no weeks in the reporting period")

    return complaints


# ---------------------------------------------------------------------------
# View construction
# ---------------------------------------------------------------------------
def _status(label, colour):
    return {"label": label, "colour": colour}



def _short_notice_status(share, thresholds):
    if share > thresholds["short_notice_limit_share"]:
        return _status("▲ Above limit", DANGER)
    return _status("● Within limit", SUCCESS)


def _leadership_status(share, thresholds):
    if share >= thresholds["leadership_share"]:
        return _status("▲ Above target", SUCCESS)
    return _status("▼ Below target", DANGER)


def _moving_average(values, window):
    """Trailing mean, with a partial window until there is enough history.

    Trailing rather than centred: a planner reads this chart to see what has
    been building up to now, and a centred average would need weeks that have
    not happened yet to place the point.
    """
    out = []
    for index in range(len(values)):
        chunk = values[max(0, index - window + 1) : index + 1]
        out.append(sum(chunk) / len(chunk))
    return out


def _timing_section(data, axis_max, axis_step):
    """Panel 01: activities per week.

    Activities, not summed audience. The pack refuses to sum audience size on
    purpose -- `agent_pack` states it in as many words: summing it counts
    contacts, not people, because one person inside six activities counts six
    times. A chart whose y-axis the pack will not supply is a chart that cannot
    be grounded, so the panel plots the thing the pack does count.
    """
    counts = [week["activities"] for week in data["weeks"]]
    peak_index = max(range(len(counts)), key=counts.__getitem__)

    bars = [
        {
            "height": _round_half_up(value / axis_max * TIMING_PLOT_HEIGHT),
            "colour": "var(--accent, #e60000)" if index == peak_index else GREY_3,
        }
        for index, value in enumerate(counts)
    ]

    labels = [
        {
            "label": esc(week["commencing"]),
            "emphasis": " font-weight: 600; color: #000000;" if index == peak_index else "",
        }
        for index, week in enumerate(data["weeks"])
    ]

    # Ticks top to bottom, matching the template's space-between column.
    axis = [
        {"label": swiss(value)}
        for value in range(axis_max, -1, -axis_step)
    ]

    averages = _moving_average(counts, MOVING_AVERAGE_WEEKS)
    points = " ".join(
        f"{TIMING_BAR_ORIGIN + TIMING_BAR_PITCH * index},"
        f"{TIMING_PLOT_HEIGHT - _round_half_up(value / axis_max * TIMING_PLOT_HEIGHT)}"
        for index, value in enumerate(averages)
    )

    peak = data["weeks"][peak_index]
    return bars, labels, axis, points, peak_index, peak


def build_view(data, thresholds=None):
    """Turn the raw figures into every string the template asks for.

    `data` carries counts and labels only -- no colours, no pixel heights, no
    percentages. Everything presentational is derived here, so that swapping
    one quarter's figures for another's cannot change how the page looks.
    """
    thresholds = dict(THRESHOLDS if thresholds is None else thresholds)
    total = data["activities_total"]

    # --- KPI row --------------------------------------------------------
    short_notice_share = data["short_notice_activities"] / total
    leadership_share = data["leadership_activities"] / total

    short_notice_status = _short_notice_status(short_notice_share, thresholds)
    leadership_status = _leadership_status(leadership_share, thresholds)

    # What the volume card says instead of a year-on-year change. The export is
    # a snapshot of now: last year's rows survive in it, but only as they stand
    # today, and rows deleted since leave no trace at all.
    #
    # It said "N excluded of M rows read" while the board was a year view. At
    # quarter grain that reads as a filter rejecting rows, when most of the
    # difference is simply the other quarters -- so the card sets the quarter
    # against the plan instead. Both figures are stated by the pack, at their
    # own grain, and the sentence says which is which.
    in_plan = data["activities_in_plan"]
    plan_share = total / in_plan if in_plan else 0.0

    # --- Panel 01: timing ----------------------------------------------
    axis_max, axis_step = axis_scale(
        max(week["activities"] for week in data["weeks"])
    )
    bars, labels, axis, points, _, peak = _timing_section(data, axis_max, axis_step)

    # --- Panel 02: priority mix ----------------------------------------
    priority_rows = []
    stops = []
    cumulative = 0
    for rank, item in enumerate(data["priorities"]):
        share = _round_half_up(item["activities"] / total * 100)
        colour = _rank_colour(rank, PRIORITY_COLOURS)
        priority_rows.append({
            "colour": colour,
            "label": esc(item["label"]),
            "share": f"{share}%",
            "detail": f"{swiss(item['activities'])} activities",
        })
        stops.append(f"{colour} {cumulative}% {cumulative + share}%")
        cumulative += share
    if stops:
        # The last stop closes the ring: rounding the shares individually can
        # leave the total a point short or long, and a donut with a gap in it
        # would be read as a fifth category.
        head, _, _ = stops[-1].partition(" ")
        stops[-1] = f"{head} {cumulative - _round_half_up(data['priorities'][-1]['activities'] / total * 100)}% 100%"

    # --- Panel 03: ownership -------------------------------------------
    ownership_rows = []
    for rank, item in enumerate(data["teams"]):
        share = item["activities"] / total
        ownership_rows.append({
            "label": esc(item["name"]),
            "share": percent(share),
            "width": percent(min(share / OWNERSHIP_AXIS_MAX_SHARE, 1.0), 1),
            "colour": _rank_colour(rank, OWNERSHIP_COLOURS),
            "emphasis": " font-weight: 600;" if rank == 0 else f" color: {GREY_6};",
        })
    ownership_scale = [
        {"label": percent(step / 100)}
        for step in range(0, int(OWNERSHIP_AXIS_MAX_SHARE * 100) + 1, 10)
    ]

    # --- Panel 04: leadership by team ----------------------------------
    lead_ceiling_pct, _ = axis_scale(
        max((item["share"] for item in data["leadership_by_team"]), default=0) * 100)
    lead_ceiling = lead_ceiling_pct / 100
    leadership_rows = []
    for rank, item in enumerate(data["leadership_by_team"]):
        share = item["share"]
        leadership_rows.append({
            "share": percent(share),
            "height": _round_half_up(
                share / lead_ceiling * LEADERSHIP_PLOT_HEIGHT
            ),
            "colour": _rank_colour(rank, LEADERSHIP_COLOURS),
            "label_colour": _rank_colour(rank, LEADERSHIP_LABEL_COLOURS),
        })
    leadership_labels = [
        {
            "label": wrap_label(item["name"]),
            "emphasis": " font-weight: 600;" if rank == 0 else f" color: {GREY_5};",
        }
        for rank, item in enumerate(data["leadership_by_team"])
    ]
    average_offset = _round_half_up(
        min(leadership_share, lead_ceiling) / lead_ceiling * LEADERSHIP_PLOT_HEIGHT
    )

    # --- Panel 05: reach ------------------------------------------------
    large_share = data["large_audience_activities"] / total
    internal_share = data["internal_activities"] / total

    scalars = {
        "accent": ACCENT,
        "eyebrow": esc(data["eyebrow"]),
        "title": esc(data["title"]),
        "subtitle": esc(data["subtitle"]),
        "period_label": esc(data["period_label"]),
        "data_as_of": esc(data["data_as_of"]),
        "base_label": f"{swiss(total)} activities",

        "shortnotice_definition":
            "Planned at under "
            f"{thresholds['short_notice_window_days']} days’ notice",
        "shortnotice_value": percent(short_notice_share),
        "shortnotice_unit": f"{swiss(data['short_notice_activities'])} activities",
        "shortnotice_value_colour":
            DANGER if short_notice_status["colour"] == DANGER else BLACK,
        "shortnotice_status": short_notice_status["label"],
        "shortnotice_status_colour": short_notice_status["colour"],
        "shortnotice_target":
            f"limit ≤{percent(thresholds['short_notice_limit_share'])}",

        "leadership_definition": "Activities with executive board participation",
        "leadership_value": percent(leadership_share),
        "leadership_unit": f"{swiss(data['leadership_activities'])} activities",
        "leadership_value_colour":
            DANGER if leadership_status["colour"] == DANGER else BLACK,
        "leadership_status": leadership_status["label"],
        "leadership_status_colour": leadership_status["colour"],
        "leadership_target": f"target ≥{percent(thresholds['leadership_share'])}",

        "volume_value": swiss(total),
        # Scope, not growth. Black because it is neither good nor bad: it says
        # how much of the plan this period holds, which is the caveat the
        # agent's own instructions require beside any stated total.
        "volume_delta": f"{percent(plan_share)} of the plan",
        "volume_delta_colour": BLACK,
        "volume_compare": f"{swiss(in_plan)} activities in total",

        "timing_measure": "Activities",
        "timing_average_label": f"{MOVING_AVERAGE_WEEKS}-week moving average",
        "timing_axis_caption": "Week commencing",
        "timing_viewbox_width":
            TIMING_BAR_ORIGIN * 2 + TIMING_BAR_PITCH * (len(data["weeks"]) - 1),
        "timing_average_points": points,
        "timing_peak_label": f"week of {esc(peak['commencing'])}",
        "timing_peak_detail": f"{swiss(peak['activities'])} activities",

        "priority_gradient": ", ".join(stops),
        "priority_total": swiss(total),

        "leadership_average_offset": average_offset,
        "leadership_average_label_offset": average_offset + 4,
        "leadership_average_label": f"Average = {percent(leadership_share)}",

        "reach_executive_value": swiss(data["leadership_activities"]),
        "reach_executive_colour":
            DANGER if leadership_status["colour"] == DANGER else BLACK,
        "reach_executive_detail":
            f"{percent(leadership_share)} of total activities · "
            f"target ≥{percent(thresholds['leadership_share'])}",
        "reach_large_value": swiss(data["large_audience_activities"]),
        "reach_large_detail":
            f"{percent(large_share)} of total · top two audience bands",
        "reach_internal_share": percent(internal_share),
        "reach_external_share": percent(1 - internal_share),
        # The printed share and the drawn width are separate on purpose. A data
        # object whose internal and external counts do not sum to the total is
        # already reported by `validate`, and the honest thing on the page is to
        # print what it says -- but a share above 1 drove the split bar to a
        # negative width, and Pillow raises on that. A wrong-looking bar beside
        # a complaint beats a stack trace where a board should be.
        "reach_internal_width": percent(min(max(internal_share, 0.0), 1.0)),
        "reach_external_width": percent(1 - min(max(internal_share, 0.0), 1.0)),
        "reach_split_detail":
            f"{swiss(data['internal_activities'])} internal · "
            f"{swiss(data['external_activities'])} external",

        "footer_notes": esc(data["footer_notes"]),
        # Two lines, and the only place the renderer inserts a <br> into prose
        # -- the data carries them as separate strings rather than as markup.
        "footer_source": "<br>".join(esc(line) for line in data["footer_source"]),
    }

    return {
        "scalars": scalars,
        "rows": {
            "timing_axis": axis,
            "timing_bars": bars,
            "timing_labels": labels,
            "priority_legend": priority_rows,
            "ownership_rows": ownership_rows,
            "ownership_scale": ownership_scale,
            "leadership_bars": leadership_rows,
            "leadership_labels": leadership_labels,
        },
        "insights": {
            f"{panel}_insight": esc(data["insights"][panel]) if data["insights"].get(panel) else ""
            for panel in ("timing", "priority", "ownership", "leadership", "reach")
        },
    }
