"""The frozen dashboard: same data in, the same page out, every time.

These tests exist because the dashboard used to be regenerated on request and
took four revision rounds to reach a page that met the design system -- during
which one round undid two corrections an earlier round had made. The template
is frozen precisely so that cannot recur, and a freeze nobody checks is a
convention, not a guarantee.

So the suite pins three separate things:

* the exact bytes of the page, against a committed golden file;
* the *boundary* -- that data can only supply figures, never presentation, which
  is what makes the first guarantee survive next quarter's numbers;
* the thresholds, which moved out of the markup into THRESHOLDS and would
  otherwise silently drift back to being prose someone edits by hand.
"""

import json
import re
from pathlib import Path

import pytest

import pipeline.scripts.report_dashboard as report_dashboard
from pipeline.report import dashboard_render, template_engine
from pipeline.report.dashboard_render import (
    THRESHOLDS,
    TemplateError,
    axis_scale,
    build_view,
    render,
    validate,
    wrap_label,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE = REPO_ROOT / "pipeline" / "dashboard" / "campaign-activity.sample.json"
GOLDEN = REPO_ROOT / "pipeline" / "dashboard" / "campaign-activity.golden.html"

# The thirteen values the brand conformance review closed on. A hex outside
# this set is the exact failure the review spent four rounds removing, so it
# fails the build rather than waiting to be noticed by eye.
APPROVED_PALETTE = {
    "#ffffff", "#000000",
    "#404040", "#5a5d5c", "#7a7870", "#8e8d83", "#cccabc",
    "#ecebe4", "#f8f7f2",
    "#e60000", "#bd000c", "#8a000a",
    "#6f7a1a",
}

HEX = re.compile(r"#[0-9a-fA-F]{6}\b")


@pytest.fixture
def data():
    return report_dashboard.load_data(SAMPLE)


def _render(data):
    return render(build_view(data, THRESHOLDS))


# ---------------------------------------------------------------------------
# The freeze itself
# ---------------------------------------------------------------------------
def test_the_sample_data_reproduces_the_golden_file(data):
    assert _render(data) == GOLDEN.read_text(encoding="utf-8"), (
        "The rendered page no longer matches the golden file. If the change was "
        "intended, run `python pipeline/scripts/report_dashboard.py "
        "--update-golden` and commit the result."
    )


def test_rendering_twice_produces_the_same_bytes(data):
    assert _render(data) == _render(data)


def test_check_mode_agrees_with_the_committed_golden(capsys):
    assert report_dashboard.main(["--check"]) == 0
    assert "matches" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# The boundary: data supplies figures, the template supplies presentation
# ---------------------------------------------------------------------------
def test_every_colour_in_the_page_is_an_approved_token(data):
    found = {match.group(0).lower() for match in HEX.finditer(_render(data))}
    assert found <= APPROVED_PALETTE, f"off-palette: {sorted(found - APPROVED_PALETTE)}"


def test_different_figures_do_not_change_the_page_furniture(data):
    """Doubling every count must not introduce or remove a single style rule.

    This is the property the freeze is for. Bar heights and status colours are
    *supposed* to move with the data; the borders, paddings, fonts and grid
    definitions are not, and nothing in the data object should be able to
    reach them.
    """
    def furniture(page):
        # Style attributes with every number stripped: what is left is the
        # page's construction, independent of the quarter it describes.
        return sorted(
            re.sub(r"[\d.]+", "#", attribute)
            for attribute in re.findall(r'style="([^"]*)"', page)
        )

    before = furniture(_render(data))

    louder = json.loads(json.dumps(data))
    for key in ("activities_total", "rows_read", "short_notice_activities",
                "leadership_activities", "large_audience_activities",
                "internal_activities", "external_activities"):
        louder[key] *= 2
    for row in louder["priorities"] + louder["teams"]:
        row["activities"] *= 2
    for week in louder["weeks"]:
        week["activities"] *= 2

    assert furniture(_render(louder)) == before


def test_an_unfilled_placeholder_is_an_error_not_a_page(data):
    """A page that ships the literal text "{{ leadership_value }}" is worse
    than no page, so the renderer refuses rather than substituting blanks."""
    view = build_view(data, THRESHOLDS)
    del view["scalars"]["leadership_value"]
    with pytest.raises(TemplateError, match="leadership_value"):
        render(view)


def test_the_data_object_carries_no_markup(data):
    """Escaping is the renderer's job, so a name with an ampersand in it
    reaches the page escaped and a template injection cannot ride in on data."""
    hostile = json.loads(json.dumps(data))
    hostile["teams"][0]["name"] = 'Group <script>alert("x")</script> & Co'
    page = _render(hostile)
    assert "<script>alert" not in page
    assert "&lt;script&gt;" in page
    assert "&amp; Co" in page


# ---------------------------------------------------------------------------
# Thresholds -- the numbers that used to be prose inside the markup
# ---------------------------------------------------------------------------
def test_the_leadership_target_drives_both_the_label_and_the_colour(data):
    """16% against a 20% target is a breach; against a 10% target it is not.

    Nothing about that judgement lives in the template, which is the point --
    the target moved out of the markup, where every regeneration used to
    re-invent it.
    """
    breaching = _render(data)
    assert "▼ Below target" in breaching
    assert "target ≥20%" in breaching

    relaxed = dict(THRESHOLDS, leadership_share=0.10)
    page = render(build_view(data, relaxed))
    assert "▲ Above target" in page
    assert "target ≥10%" in page
    assert "▼ Below target" not in page


def test_the_short_notice_card_is_worded_as_the_pack_states_it(data):
    """The pack's own line is "Planned at under 7 days' notice", and
    `metrics.lead_time_stats` counts exactly that -- a lead time under
    `SHORT_NOTICE_DAYS`. Wording the card from the same number the filter uses
    is what stops the two drifting into counting different things under one
    name, which is what "within the next two weeks" was doing."""
    assert "Planned at under 7 days’ notice" in _render(data)

    fortnight = dict(THRESHOLDS, short_notice_window_days=14)
    assert "under 14 days’ notice" in render(build_view(data, fortnight))


def test_the_volume_card_states_scope_rather_than_a_year_on_year_change(data):
    """The export is a snapshot of now, so a prior-period figure would be last
    year as it stands today, missing every row deleted since. Rows read and the
    scope total are both stated by the pack, and the difference between them is
    the caveat the agent's instructions require beside any total."""
    page = _render(data)
    excluded = data["rows_read"] - data["activities_total"]
    assert f'color: #000000;">{excluded} excluded' in page
    assert f"of {data['rows_read']:,}".replace(",", "\u2019") in page
    assert "vs Q3 2025" not in page


def test_reading_fewer_rows_than_are_in_scope_is_reported(data):
    """A negative exclusion would render as a minus sign nobody could explain."""
    impossible = dict(data, rows_read=data["activities_total"] - 1)
    assert any("fewer than" in c for c in validate(impossible))


# ---------------------------------------------------------------------------
# Data validation -- gaps in the figures, not in the design
# ---------------------------------------------------------------------------
def test_the_unnamed_team_residual_is_reported(data):
    """The sample carries the design's own gap: seven teams covering 90% of a
    panel titled "Team distribution". It renders, and it says so every run."""
    complaints = validate(data)
    assert any("residual is unnamed" in complaint for complaint in complaints)


def test_data_that_adds_up_produces_no_complaints(data):
    sound = json.loads(json.dumps(data))
    covered = sum(team["activities"] for team in sound["teams"])
    sound["teams"][-1]["activities"] += sound["activities_total"] - covered
    assert validate(sound) == []


def test_a_priority_mix_that_misses_activities_is_caught(data):
    short = json.loads(json.dumps(data))
    short["priorities"][0]["activities"] -= 100
    assert any("priority counts" in complaint for complaint in validate(short))


# ---------------------------------------------------------------------------
# Panel 01 plots what the pack will actually supply
# ---------------------------------------------------------------------------
def test_the_timing_panel_counts_activities_and_never_sums_audience(data):
    """`agent_pack` refuses to sum audience size, in as many words: summing it
    counts contacts, not people, because one person inside six activities
    counts six times. A y-axis the pack will not supply cannot be grounded, so
    the panel plots activities -- and the data object carries no contacts at
    all, which is what stops one being reintroduced by accident."""
    assert all("contacts" not in week for week in data["weeks"])

    page = _render(data)
    assert "Activity load by week" in page
    assert ">Activities<" in page
    assert "contacts" not in page


def test_the_peak_marker_names_the_busiest_week_by_activities(data):
    busiest = max(data["weeks"], key=lambda week: week["activities"])
    page = _render(data)
    assert f"Peak · week of {busiest['commencing']}" in page
    assert f"{busiest['activities']} activities" in page


@pytest.mark.parametrize("largest, expected", [
    (354, (400, 100)),
    (18_000, (20_000, 5_000)),
    (7, (8, 2)),
    (0, (1, 1)),
])
def test_the_axis_ceiling_is_round_and_never_below_the_data(largest, expected):
    """A tick column reading 354 / 266 / 177 / 89 is arithmetic done at the
    reader. The ceiling is picked from the data so a quiet quarter is not drawn
    against a busy quarter's scale, but the step is always round."""
    ceiling, step = axis_scale(largest)
    assert (ceiling, step) == expected
    assert ceiling >= largest
    assert ceiling % step == 0


# ---------------------------------------------------------------------------
# Label wrapping
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name, expected", [
    ("Group Communications", "Group<br>Communications"),
    ("Wealth Management", "Wealth<br>Management"),
    # The break is chosen by measure, not after the first word -- otherwise
    # this one strands a lone ampersand at the end of the first line.
    ("Personal & Corporate Banking", "Personal &amp;<br>Corporate Banking"),
    ("Other / Central Teams", "Other /<br>Central Teams"),
    ("Communications", "Communications"),
])
def test_team_names_break_near_the_middle(name, expected):
    assert wrap_label(name) == expected


# ---------------------------------------------------------------------------
# The template file itself
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("module", [dashboard_render, template_engine])
def test_the_renderer_contains_no_markup(module):
    """Every style literal in the finished page comes from the template file.

    If a tag ever appears in the renderer, the golden file stops being a
    complete description of how the page looks and the freeze leaks.

    Both modules are checked over their whole source. This used to skip past
    everything above `class TemplateError` on the grounds that the imports and
    constants could not hold markup -- then the substitution machinery moved to
    `template_engine` and the anchor vanished, taking the check with it. There
    is nothing above the constants worth exempting, so nothing is.
    """
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "<div" not in source and "<span" not in source and "style=" not in source


def test_every_row_template_is_used(data):
    _, rows = dashboard_render.load_template()
    view = build_view(data, THRESHOLDS)
    used = set(view["rows"]) | {"insight"}
    assert set(rows) == used, f"unused row templates: {sorted(set(rows) - used)}"
