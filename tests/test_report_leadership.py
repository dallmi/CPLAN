"""The frozen Leadership attention board: same figures in, the same board out.

The campaign dashboard's suite pins the bytes, the boundary and the thresholds.
This board needs those three and two more, because a *named board* makes two
promises that a dashboard does not:

* **Exactly one bar is red.** Not "at most two red elements" -- that is a budget
  an improvising renderer spends without noticing. One bar, the tallest of the
  division panel, checkable before drawing and after.
* **Panel 3 is never ranked.** The audience bands carry their own order, and a
  chart that re-sorts them by value has destroyed the thing the panel exists to
  show. Divisions and regions, which have no inherent order, must be ranked.
"""

import json
import re
from pathlib import Path

import pytest

import pipeline.scripts.report_dashboard as report_dashboard
from pipeline.report import leadership_render
from pipeline.report.leadership_render import (
    TemplateError,
    bar_width,
    build_view,
    render,
    validate,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE = REPO_ROOT / "pipeline" / "dashboard" / "leadership-attention.sample.json"
GOLDEN = REPO_ROOT / "pipeline" / "dashboard" / "leadership-attention.golden.html"

# A grey board with one red bar on it. Anything else is off-palette by
# construction, not merely by review.
APPROVED_PALETTE = {
    "#ffffff", "#000000", "#404040", "#5a5d5c", "#7a7870", "#cccabc",
    "#ecebe4", "#e60000",
}

HEX = re.compile(r"#[0-9a-fA-F]{6}\b")
BAR = re.compile(
    r'white-space: nowrap;">([^<]*)</div>.*?'
    r'width: ([\d.]+)%; height: 22px; background: (#[0-9a-f]{6})',
    re.DOTALL,
)


@pytest.fixture
def data():
    return report_dashboard.load_data(SAMPLE)


def _render(data):
    return render(build_view(data))


def _bars(page):
    """Every bar on the page as (label, width, colour), in document order."""
    return [(m.group(1), float(m.group(2)), m.group(3)) for m in BAR.finditer(page)]


# ---------------------------------------------------------------------------
# The freeze itself
# ---------------------------------------------------------------------------
def test_the_sample_figures_reproduce_the_golden_board(data):
    assert _render(data) == GOLDEN.read_text(encoding="utf-8"), (
        "The rendered board no longer matches the golden file. If the change "
        "was intended, run `python pipeline/scripts/report_dashboard.py "
        "--board leadership-attention --update-golden` and commit the result."
    )


def test_rendering_twice_produces_the_same_bytes(data):
    assert _render(data) == _render(data)


def test_check_mode_agrees_with_the_committed_golden(capsys):
    assert report_dashboard.main(["--board", "leadership-attention", "--check"]) == 0
    assert "matches" in capsys.readouterr().out


def test_the_board_leaves_no_placeholder_behind(data):
    assert "{{" not in _render(data)


# ---------------------------------------------------------------------------
# The board's own two promises
# ---------------------------------------------------------------------------
def test_exactly_one_bar_is_red_and_it_is_the_tallest_division(data):
    """One red bar, on the highlighted panel, on its longest bar.

    The instructions permit two red elements in an image and this board spends
    one of them on the rule beside the title. That leaves exactly one for the
    data, and a renderer that hands red to a second bar has broken the board
    rather than merely crowded it.
    """
    red = [bar for bar in _bars(_render(data)) if bar[2] == "#e60000"]
    assert len(red) == 1, f"red bars: {red}"

    label, width, _ = red[0]
    tallest = max(data["divisions"], key=lambda item: item["leadership"])
    assert label == tallest["name"]
    assert width == 100.0, "the highlighted bar is the one that fills its axis"


def test_no_number_on_the_board_is_red(data):
    """Tile numbers are black on every board, without exception -- the exact
    failure the 2026-08-06 test render shipped five times over."""
    page = _render(data)
    for figure in ("312", "2’400", "13%"):
        tile = re.search(
            r'font-size: 36px;[^"]*color: (#[0-9a-f]{6});">' + re.escape(figure),
            page,
        )
        assert tile, f"no tile found for {figure}"
        assert tile.group(1) == "#000000"


def test_the_audience_bands_keep_their_own_order(data):
    """Band order is a size. Ranking it by value destroys the one thing the
    panel exists to show, so the renderer must leave this panel alone."""
    page = _render(data)
    labels = [label for label, _, _ in _bars(page)]
    bands = [band["name"] for band in data["audience_bands"]]
    # The bands sit between the division panel and the region panel.
    start = labels.index("&lt; 1000")
    rendered = labels[start:start + len(bands)]
    assert rendered == ["&lt; 1000", "1–10k", "10–50k", "50–100k", "&gt; 100k"]

    # And they are genuinely not in value order, so the test above is not
    # passing by coincidence.
    values = [band["leadership"] for band in data["audience_bands"]]
    assert values != sorted(values, reverse=True)


def test_divisions_and_regions_are_ranked_whatever_order_they_arrive_in(data):
    shuffled = json.loads(json.dumps(data))
    shuffled["divisions"] = list(reversed(shuffled["divisions"]))
    shuffled["regions"] = list(reversed(shuffled["regions"]))
    assert _render(shuffled) == _render(data)


# ---------------------------------------------------------------------------
# The boundary: figures supply values, the template supplies presentation
# ---------------------------------------------------------------------------
def test_every_colour_on_the_board_is_an_approved_token(data):
    found = {match.group(0).lower() for match in HEX.finditer(_render(data))}
    assert found <= APPROVED_PALETTE, f"off-palette: {sorted(found - APPROVED_PALETTE)}"


def test_different_figures_do_not_change_the_board_furniture(data):
    """Doubling every count must not introduce or remove a single style rule."""
    def furniture(page):
        return sorted(
            re.sub(r"[\d.]+", "#", attribute)
            for attribute in re.findall(r'style="([^"]*)"', page)
        )

    before = furniture(_render(data))

    louder = json.loads(json.dumps(data))
    for key in ("activities_total", "leadership_activities",
                "large_audience_activities"):
        louder[key] *= 2
    for block in ("divisions", "regions", "audience_bands"):
        for item in louder[block]:
            item["activities"] *= 2
            item["leadership"] *= 2

    assert furniture(_render(louder)) == before


def test_a_value_label_moves_inside_its_bar_once_the_bar_is_long(data):
    """Past about two thirds of the axis there is no room outside the bar, and
    a label put there anyway leaves the plot and lands in its neighbour."""
    page = _render(data)

    # 118 fills the axis, 96 is 81% of it: both inside, set in white.
    assert 'color: #ffffff;">118' in page
    assert 'color: #ffffff;">96' in page
    # 74 is 63% of the axis -- still short enough to label outside.
    assert 'color: #404040;">74' in page
    assert 'color: #ffffff;">74' not in page


@pytest.mark.parametrize("value, axis_max, expected", [
    (118, 118, "100%"),      # a bare ".0" is dropped, not printed
    (96, 118, "81.4%"),
    (38, 141, "27%"),
    (0, 141, "0%"),
    (0, 0, "0%"),            # an empty panel divides by nothing
])
def test_bar_widths_are_one_decimal_without_a_trailing_zero(value, axis_max, expected):
    assert bar_width(value, axis_max) == expected


def test_an_unfilled_placeholder_is_an_error_not_a_board(data):
    view = build_view(data)
    del view["scalars"]["readout"]
    with pytest.raises(TemplateError, match="readout"):
        render(view)


def test_the_figures_carry_no_markup(data):
    """Escaping is the renderer's job, so a division name with an ampersand in
    it reaches the board escaped and a template injection cannot ride in."""
    hostile = json.loads(json.dumps(data))
    hostile["divisions"][0]["name"] = 'Group <script>alert("x")</script> & Co'
    page = _render(hostile)
    assert "<script>alert" not in page
    assert "&lt;script&gt;" in page
    assert "Personal &amp; Corporate Banking" in page


def test_the_renderer_contains_no_markup():
    source = Path(leadership_render.__file__).read_text(encoding="utf-8")
    assert "<div" not in source and "<span" not in source and "style=" not in source


def test_every_row_template_is_used(data):
    _, rows = leadership_render.load_template()
    view = build_view(data)
    used = set(view["rows"])
    for items in view["chosen_rows"].values():
        used |= {item["template"] for item in items}
    assert set(rows) == used, f"unused row templates: {sorted(set(rows) - used)}"


# ---------------------------------------------------------------------------
# Data validation -- gaps in the figures, not in the design
# ---------------------------------------------------------------------------
def test_the_sample_figures_add_up(data):
    assert validate(data) == []


def test_bands_that_do_not_close_on_the_portfolio_are_caught(data):
    broken = json.loads(json.dumps(data))
    broken["audience_bands"][0]["leadership"] += 5
    complaints = validate(broken)
    assert any("exclusive and must close" in c for c in complaints)


def test_a_division_larger_than_the_portfolio_is_caught(data):
    broken = json.loads(json.dumps(data))
    broken["divisions"][2]["leadership"] = data["leadership_activities"] + 1
    assert any("more than the portfolio" in c for c in validate(broken))


def test_a_part_larger_than_its_own_whole_is_caught(data):
    broken = json.loads(json.dumps(data))
    broken["regions"][0]["leadership"] = broken["regions"][0]["activities"] + 1
    assert any("out of" in c for c in validate(broken))


def test_overlapping_blocks_are_allowed_to_sum_past_the_portfolio(data):
    """An activity naming two divisions is counted under both. Demanding that
    those bars close on the total would be demanding the data lie."""
    total = sum(item["leadership"] for item in data["divisions"])
    assert total > data["leadership_activities"]
    assert validate(data) == []


def test_a_read_out_quoting_a_figure_the_board_does_not_hold_is_caught(data):
    """The read-out is the one panel whose figures are written rather than
    plotted, so it is the one that can go stale in silence."""
    stale = json.loads(json.dumps(data))
    stale["readout"] = stale["readout"].replace("at 118 activities", "at 137 activities")
    assert any("137" in c for c in validate(stale))


def test_the_read_out_may_quote_a_volume_it_does_not_plot(data):
    """Technology's 384 is a division volume, not a leadership count: the board
    never draws it, but the pack states it, so the read-out may cite it."""
    assert "384" in data["readout"]
    assert validate(data) == []
