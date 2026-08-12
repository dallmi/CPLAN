"""The frozen Plan trust board: same figures in, the same image out.

This suite pins the same three things `test_report_dashboard.py` pins -- the
bytes, the boundary, the palette -- and one more that only a *board* needs.

A board is defined twice over. `dashboard_skill.PLAN_TRUST` tells the agent
which five panels to draw, with the business question and the footnote each one
must print; this template draws the same five for a reader who never talks to
the agent. Two renderings of one board is exactly the arrangement that drifts:
someone rewords a footnote in the skill, the rendered board keeps the old
sentence, and the two artefacts disagree in front of the same audience. So the
words are read out of both files and compared.
"""

import json
import re
from pathlib import Path

import pytest

import pipeline.scripts.report_plan_trust as report_plan_trust
from pipeline.report import board_render
from pipeline.report.board_render import (
    ACCENT,
    TemplateError,
    build_view,
    render,
    validate,
)
from pipeline.report.dashboard_skill import PLAN_TRUST

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE = REPO_ROOT / "pipeline" / "dashboard" / "plan-trust.sample.json"
GOLDEN = REPO_ROOT / "pipeline" / "dashboard" / "plan-trust.golden.html"
TEMPLATE = REPO_ROOT / "pipeline" / "dashboard" / "plan-trust.template.html"

# Warm greys, white, one red. `#f7f7f5` is the page ground the board sits on;
# every other value is a corporate token the campaign dashboard already uses.
APPROVED_PALETTE = {
    "#ffffff", "#000000",
    "#404040", "#7a7870", "#cccabc", "#ecebe4", "#f7f7f5",
    "#e60000",
}

HEX = re.compile(r"#[0-9a-fA-F]{6}\b")


@pytest.fixture
def data():
    return report_plan_trust.load_data(SAMPLE)


def _render(data):
    return render(build_view(data))


# ---------------------------------------------------------------------------
# The freeze itself
# ---------------------------------------------------------------------------
def test_the_sample_data_reproduces_the_golden_file(data):
    assert _render(data) == GOLDEN.read_text(encoding="utf-8"), (
        "The rendered board no longer matches the golden file. If the change "
        "was intended, run `python pipeline/scripts/report_plan_trust.py "
        "--update-golden` and commit the result."
    )


def test_rendering_twice_produces_the_same_bytes(data):
    assert _render(data) == _render(data)


def test_check_mode_agrees_with_the_committed_golden(capsys):
    assert report_plan_trust.main(["--check"]) == 0
    assert "matches" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# The board's own rules
# ---------------------------------------------------------------------------
def test_exactly_one_element_on_the_board_is_red(data):
    """The instructions allow two red elements in an image; a board allows one.

    "At most two" is a budget an improvising renderer spends without noticing.
    This is the same rule expressed as a count, checked on the finished bytes.
    """
    assert _render(data).count(ACCENT) == 1


def test_the_red_bar_is_the_worst_field_and_nothing_else(data):
    """Panel 1 marks the highlight; panels 2-4 are grey throughout."""
    page = _render(data)
    field_panel, rest = page.split("Activities without a pack link", 1)
    assert field_panel.count(ACCENT) == 1
    assert ACCENT not in rest

    # And it is the first bar of the panel, which is the sorted maximum.
    first_bar = field_panel.index("width: 100%")
    assert field_panel.index(ACCENT) - first_bar < 40


def test_no_number_on_the_board_is_red(data):
    """Tile and label numbers are black, or white where they sit on a bar.
    There is no board on which a red number is right."""
    page = _render(data)
    assert f"color: {ACCENT}" not in page


def test_every_colour_in_the_board_is_an_approved_token(data):
    found = {match.group(0).lower() for match in HEX.finditer(_render(data))}
    assert found <= APPROVED_PALETTE, f"off-palette: {sorted(found - APPROVED_PALETTE)}"


def test_the_read_out_states_only_the_two_figures_it_may(data):
    """The board file's `Source:` line for panel 5 names `Rows read` and
    `Unknown`. A read-out repeating a figure another panel plots has said it
    twice, so the prose is checked for digits rather than trusted."""
    page = _render(data)
    read_out = page.split("The report read", 1)[1].split("</div>", 1)[0]
    figures = set(re.findall(r"[\d’]+", read_out))
    assert figures == {"2’014", "431"}, figures


def test_the_footer_carries_the_data_vintage(data):
    """A board travels further than the answer it came with, and it is the
    copy that arrives without a date."""
    assert f"Data as of {data['data_as_of']}" in _render(data)

    undated = dict(data)
    del undated["data_as_of"]
    with pytest.raises(KeyError):
        build_view(undated)


def test_every_figure_is_grouped_the_same_way(data):
    """One number format per image. A bar reading 1204 beside a header reading
    1'842 makes the reader decide which is the house style."""
    page = _render(data)
    assert ">1’204<" in page
    assert ">1204<" not in page


# ---------------------------------------------------------------------------
# Anti-drift: the board is defined twice and the two must agree
# ---------------------------------------------------------------------------
def _panel_field(board_text, panel_heading, field):
    """Pull one `Field: ...` line out of one panel of a board definition."""
    section = board_text.split(f"— {panel_heading}\n", 1)[1]
    section = section.split("\n### ", 1)[0]
    line = next(l for l in section.splitlines() if l.startswith(f"{field}: "))
    return line[len(field) + 2:].strip()


PANELS = [
    "Field completeness",
    "Activities without a pack link, by division",
    "Median planning completeness by division",
    "Record anomalies",
    "Executive read-out",
]


def test_the_template_draws_the_panels_the_board_file_lists():
    """Five panels, in the order the board names them, and no sixth."""
    template = TEMPLATE.read_text(encoding="utf-8")
    headings = re.findall(
        r'font-size: 17px; font-weight: 600;[^"]*">([^<]+)</div>', template
    )
    assert headings == PANELS


@pytest.mark.parametrize("panel", PANELS)
def test_every_business_question_matches_the_board_file(panel):
    question = _panel_field(PLAN_TRUST, panel, "Business question")
    assert question in TEMPLATE.read_text(encoding="utf-8"), (
        f"panel {panel!r}: the template does not print the board file's "
        f"business question {question!r}"
    )


@pytest.mark.parametrize("panel", PANELS[:4])
def test_every_footnote_matches_the_board_file(panel):
    """Panel 5 carries `Footnote: none`, so only the four charted panels."""
    footnote = " ".join(_panel_field(PLAN_TRUST, panel, "Footnote").split())
    assert footnote in TEMPLATE.read_text(encoding="utf-8"), (
        f"panel {panel!r}: the template does not print the board file's "
        f"footnote {footnote!r}"
    )


def test_the_board_file_marks_exactly_one_highlight():
    """The template spends one accent; this is the other half of that pair."""
    assert PLAN_TRUST.count("Highlight: yes") == 1


# ---------------------------------------------------------------------------
# The boundary: data supplies figures, the template supplies presentation
# ---------------------------------------------------------------------------
def test_different_figures_do_not_change_the_board_furniture(data):
    """Halving every count must not introduce or remove a single style rule."""
    def furniture(page):
        return sorted(
            re.sub(r"[\d.]+", "#", attribute)
            for attribute in re.findall(r'style="([^"]*)"', page)
        )

    before = furniture(_render(data))

    quieter = json.loads(json.dumps(data))
    for row in quieter["field_completeness"]:
        row["missing"] = row["missing"] // 2
        row["filled"] = quieter["activities_in_scope"] - row["missing"]
    for row in quieter["without_pack_by_division"]:
        row["activities"] = max(1, row["activities"] // 2)
    for row in quieter["record_anomalies"]:
        row["count"] = max(1, row["count"] // 2)

    assert furniture(_render(quieter)) == before


def test_an_unfilled_placeholder_is_an_error_not_a_board(data):
    view = build_view(data)
    del view["scalars"]["complete_fields"]
    with pytest.raises(TemplateError, match="complete_fields"):
        render(view)


def test_the_data_object_carries_no_markup(data):
    hostile = json.loads(json.dumps(data))
    hostile["without_pack_by_division"][0]["division"] = (
        'Group <script>alert("x")</script> & Co'
    )
    page = _render(hostile)
    assert "<script>alert" not in page
    assert "&lt;script&gt;" in page
    assert "&amp; Co" in page


def test_the_renderer_contains_no_markup():
    """Every style literal in the finished board comes from the template file."""
    source = Path(board_render.__file__).read_text(encoding="utf-8")
    body = source[source.index("def render("):]
    assert "<div" not in body and "<span" not in body and "style=" not in body


def test_every_row_template_is_used(data):
    _, templates = board_render.load_template()
    used = {
        item["template"]
        for items in build_view(data)["chosen_rows"].values()
        for item in items
    }
    assert set(templates) == used, (
        f"unused row templates: {sorted(set(templates) - used)}"
    )


# ---------------------------------------------------------------------------
# Axis choices that are judgements, not styling
# ---------------------------------------------------------------------------
def test_planning_completeness_is_drawn_against_a_full_scale(data):
    """A percentage scaled to its own maximum exaggerates the spread: 62
    against a top bar of 91 would be drawn at 68% of the axis. On a board about
    what can be trusted, that is the wrong direction to be wrong in."""
    page = _render(data)
    median_panel = page.split("Median planning completeness", 1)[1]
    median_panel = median_panel.split("Record anomalies", 1)[0]
    widths = re.findall(r"width: ([\d.]+)%", median_panel)
    assert widths == ["91", "88", "79", "74", "62"]


def test_counts_are_drawn_against_the_tallest_bar(data):
    """A count has no natural ceiling, so the panel maximum sets the axis."""
    page = _render(data)
    pack_panel = page.split("Activities without a pack link", 1)[1]
    pack_panel = pack_panel.split("Median planning completeness", 1)[0]
    assert re.findall(r"width: ([\d.]+)%", pack_panel)[0] == "100"


def test_a_long_bar_carries_its_value_inside_itself(data):
    """Past about two thirds of the axis there is no room outside the bar, and
    a label put there anyway leaves the plot."""
    page = _render(data)
    field_panel = page.split("Activities without a pack link", 1)[0]
    # The top bar is full width: its label is white, inside the bar.
    assert 'background: #e60000;"><span style="font-size: 13px; color: #ffffff;">1’204</span>' in field_panel
    # The shortest is well inside the axis: black, after the bar.
    assert '</div><span style="font-size: 13px; color: #000000;">31</span>' in field_panel


# ---------------------------------------------------------------------------
# Data validation -- gaps in the figures, not in the design
# ---------------------------------------------------------------------------
def test_the_sample_data_adds_up(data):
    assert validate(data) == []


def test_a_field_that_does_not_add_up_to_the_scope_is_caught(data):
    broken = json.loads(json.dumps(data))
    broken["field_completeness"][0]["missing"] += 1
    assert any("is not the" in complaint for complaint in validate(broken))


def test_a_field_cannot_be_both_missing_and_not_counted(data):
    """The distinction is the whole point of panel 1's footnote: a field absent
    from the export is not counted, rather than counted as missing."""
    broken = json.loads(json.dumps(data))
    broken["fields_not_counted"].append("region")
    assert any("cannot be both" in complaint for complaint in validate(broken))


def test_a_division_present_in_only_one_panel_is_caught(data):
    """Panels 2 and 3 are read side by side and the contrast is the point."""
    broken = json.loads(json.dumps(data))
    broken["median_completeness_by_division"].pop()
    assert any(
        "one division panel and not the other" in complaint
        for complaint in validate(broken)
    )


def test_reading_fewer_rows_than_the_board_reports_is_caught(data):
    broken = dict(data, rows_read=data["activities_in_scope"] - 1)
    assert any("rows but reports" in complaint for complaint in validate(broken))
