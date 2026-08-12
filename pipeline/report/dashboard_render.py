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

import html
import re
from pathlib import Path

PIPELINE_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = PIPELINE_DIR / "dashboard" / "campaign-activity.template.html"

# ---------------------------------------------------------------------------
# CONFIGURATION -- this is the block to edit.
# ---------------------------------------------------------------------------
THRESHOLDS = {
    # Weeks of plan beyond the end of the reporting period. Higher is better:
    # it means the calendar is filled in rather than assembled week by week.
    "planning_horizon_weeks": 12,
    # Weeks between now and the average activity start. This one is a band, not
    # a floor -- being far *above* it is not obviously good, so anything within
    # the tolerance reads as on target rather than as a breach in either
    # direction.
    "lead_time_weeks": 4,
    "lead_time_tolerance_weeks": 0.5,
    # An activity counts as short notice if it starts inside this window. The
    # design's card says "within the next two weeks"; the calendar report's
    # own SHORT_NOTICE_DAYS is 7, and the two are genuinely different
    # questions, so this dashboard carries its own number rather than
    # borrowing one that means something else.
    "short_notice_window_days": 14,
    "short_notice_limit_share": 0.15,
    # Share of activities with executive board participation.
    "leadership_share": 0.20,
    # Contacts per activity at or above which the audience counts as large.
    "large_audience_contacts": 100_000,
}
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
LEADERSHIP_AXIS_MAX_SHARE = 0.40
OWNERSHIP_AXIS_MAX_SHARE = 0.30
MOVING_AVERAGE_WEEKS = 4

_PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")
_ROWS_BLOCK = re.compile(r"\n?<!--ROWS\n(.*?)\n-->\s*$", re.DOTALL)
_ROW_HEADER = re.compile(r"^\[(\w+)\]$", re.MULTILINE)


class TemplateError(RuntimeError):
    """A placeholder had no value, or a row template was missing."""


# ---------------------------------------------------------------------------
# Template loading and substitution
# ---------------------------------------------------------------------------
def load_template(path=None):
    """Split the template file into the page and its row templates.

    The row templates sit in a trailing `<!--ROWS ... -->` comment so the file
    stays a single artefact: one thing to review, one thing to freeze, one
    thing a diff can be read against.
    """
    text = Path(path or TEMPLATE_PATH).read_text(encoding="utf-8")
    match = _ROWS_BLOCK.search(text)
    if match is None:
        raise TemplateError(f"no <!--ROWS ... --> block in {path or TEMPLATE_PATH}")
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


def compact_contacts(value):
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f}".rstrip("0").rstrip(".") + "M"
    if value >= 1_000:
        return f"{value / 1_000:.0f}k"
    return str(int(value))


def axis_label(value, axis_max):
    """Tick label in the unit the top of the axis is in.

    `compact_contacts` picks a unit per value, which is right for a figure
    quoted on its own and wrong for a column of ticks: 1.2M above 800k above
    400k asks the reader to convert between units while scanning a scale.
    """
    if value <= 0:
        return "0"
    if axis_max >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if axis_max >= 1_000:
        return f"{value / 1_000:.0f}k"
    return str(int(round(value)))


_SMALL_NUMBERS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}


def window_phrase(days):
    """Word the short-notice window the way a reader would say it.

    The number comes from THRESHOLDS so the card can never disagree with the
    filter behind it, but "within the next two weeks" is what the signed-off
    page says and what a planner reads without converting. Whole weeks are
    spelled; anything else falls back to days.
    """
    if days % 7 == 0 and days // 7 in _SMALL_NUMBERS:
        weeks = days // 7
        return f"{_SMALL_NUMBERS[weeks]} week{'s' if weeks > 1 else ''}"
    return f"{days} days"


def esc(text):
    """Escape a data string for HTML.

    Everything the template receives is escaped, including prose, so the data
    object never carries markup or entities. Write "&" and "—" literally in the
    data; the file is UTF-8 and the page declares it.
    """
    return html.escape(str(text), quote=False)


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


def _nice_ceiling(value, step):
    """Smallest multiple of `step` at or above `value`."""
    if value <= 0:
        return step
    return step * ((int(value) + step - 1) // step)


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

    weeks = data["weeks"]
    if not weeks:
        complaints.append("no weeks in the reporting period")

    return complaints


# ---------------------------------------------------------------------------
# View construction
# ---------------------------------------------------------------------------
def _status(label, colour):
    return {"label": label, "colour": colour}


def _horizon_status(weeks, thresholds):
    target = thresholds["planning_horizon_weeks"]
    if weeks >= target:
        return _status("▲ Above target", SUCCESS)
    return _status("▼ Below target", DANGER)


def _lead_time_status(weeks, thresholds):
    target = thresholds["lead_time_weeks"]
    tolerance = thresholds["lead_time_tolerance_weeks"]
    if abs(weeks - target) <= tolerance:
        return _status("● On target", SUCCESS)
    if weeks > target:
        return _status("▲ Above target", SUCCESS)
    return _status("▼ Below target", DANGER)


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


def _timing_section(data, axis_max):
    contacts = [week["contacts"] for week in data["weeks"]]
    peak_index = max(range(len(contacts)), key=contacts.__getitem__)

    bars = [
        {
            "height": _round_half_up(value / axis_max * TIMING_PLOT_HEIGHT),
            "colour": "var(--accent, #e60000)" if index == peak_index else GREY_3,
        }
        for index, value in enumerate(contacts)
    ]

    labels = [
        {
            "label": esc(week["commencing"]),
            "emphasis": " font-weight: 600; color: #000000;" if index == peak_index else "",
        }
        for index, week in enumerate(data["weeks"])
    ]

    # Four ticks, top to bottom, matching the template's space-between column.
    axis = [
        {"label": axis_label(axis_max * fraction, axis_max)}
        for fraction in (1.0, 2 / 3, 1 / 3, 0.0)
    ]

    averages = _moving_average(contacts, MOVING_AVERAGE_WEEKS)
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
    horizon = data["planning_horizon_weeks"]
    lead_time = data["lead_time_weeks"]
    short_notice_share = data["short_notice_activities"] / total
    leadership_share = data["leadership_activities"] / total

    horizon_status = _horizon_status(horizon, thresholds)
    lead_time_status = _lead_time_status(lead_time, thresholds)
    short_notice_status = _short_notice_status(short_notice_share, thresholds)
    leadership_status = _leadership_status(leadership_share, thresholds)

    prior = data["activities_prior"]
    delta_share = (total - prior) / prior if prior else 0.0

    # --- Panel 01: timing ----------------------------------------------
    axis_max = _nice_ceiling(
        max(week["contacts"] for week in data["weeks"]), 200_000
    )
    bars, labels, axis, points, _, peak = _timing_section(data, axis_max)

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
    leadership_rows = []
    for rank, item in enumerate(data["leadership_by_team"]):
        share = item["share"]
        leadership_rows.append({
            "share": percent(share),
            "height": _round_half_up(
                share / LEADERSHIP_AXIS_MAX_SHARE * LEADERSHIP_PLOT_HEIGHT
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
        leadership_share / LEADERSHIP_AXIS_MAX_SHARE * LEADERSHIP_PLOT_HEIGHT
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

        "horizon_value": f"{horizon:.1f}",
        "horizon_unit": "weeks",
        "horizon_value_colour": BLACK,
        "horizon_status": horizon_status["label"],
        "horizon_status_colour": horizon_status["colour"],
        "horizon_target": f"target {thresholds['planning_horizon_weeks']} wks",

        "leadtime_value": f"{lead_time:.1f}",
        "leadtime_unit": "weeks",
        "leadtime_value_colour": BLACK,
        "leadtime_status": lead_time_status["label"],
        "leadtime_status_colour": lead_time_status["colour"],
        "leadtime_target": f"target {thresholds['lead_time_weeks']} wks",

        "shortnotice_definition":
            "Starting within the next "
            f"{window_phrase(thresholds['short_notice_window_days'])}",
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
        # A change is neither good nor bad and has no target, so it stays
        # black: RAG green here would assert that growth is success.
        "volume_delta": f"{'▲' if delta_share >= 0 else '▼'} "
                        f"{'+' if delta_share >= 0 else ''}{percent(delta_share)}",
        "volume_delta_colour": BLACK,
        "volume_compare": f"vs {esc(data['prior_period_label'])} ({swiss(prior)})",

        "timing_measure": "Estimated audience (contacts)",
        "timing_average_label": f"{MOVING_AVERAGE_WEEKS}-week moving average",
        "timing_axis_caption": "Week commencing",
        "timing_viewbox_width":
            TIMING_BAR_ORIGIN * 2 + TIMING_BAR_PITCH * (len(data["weeks"]) - 1),
        "timing_average_points": points,
        "timing_peak_label": f"week of {esc(peak['commencing'])}",
        "timing_peak_detail":
            f"{compact_contacts(peak['contacts'])} contacts · "
            f"{swiss(peak['activities'])} activities",

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
            f"{percent(large_share)} of total · "
            f"≥{compact_contacts(thresholds['large_audience_contacts'])} contacts each",
        "reach_internal_share": percent(internal_share),
        "reach_external_share": percent(1 - internal_share),
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
