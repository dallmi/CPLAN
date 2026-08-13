"""The drawn board: pinned by content, because pixels do not travel.

The HTML page has a golden file -- byte comparison, exact, and it works because
the same bytes come out of any machine that runs the renderer. A raster has no
such luxury: the same code on two machines rasterises differently the moment
the font, the version or the DPI differs, so a checked-in PNG would fail for
reasons that say nothing about whether the board is right.

So this suite pins what does travel:

* every string the view produces reaches the canvas, and nothing else does;
* every colour is an approved token;
* no text overlaps text, measured off the ink Pillow actually laid down;
* the status marks are drawn as shapes and never typed as glyphs;
* the renderer says which font it used, because two runs match only if that did.

Together they are the golden file's promise in the one currency a raster keeps.
"""

import json
import re
from pathlib import Path

import pytest

pytest.importorskip("PIL")

from pipeline.report import board_image  # noqa: E402
from pipeline.report.dashboard_render import (  # noqa: E402
    THRESHOLDS, build_view, validate as dashboard_validate)

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE = REPO_ROOT / "pipeline" / "dashboard" / "campaign-activity.sample.json"

# The tokens the design review closed on. Bordeaux II and Lake50 are absent
# because they are link colours, and a raster has no links.
APPROVED = {
    "#ffffff", "#000000",
    "#404040", "#5a5d5c", "#7a7870", "#8e8d83", "#cccabc",
    "#ecebe4", "#f8f7f2",
    "#e60000", "#bd000c", "#6f7a1a",
}


@pytest.fixture
def view():
    raw = SAMPLE.read_text(encoding="utf-8")
    data = json.loads(re.sub(r'"_comment":\s*\[[^\]]*\],', "", raw))
    return build_view(data, THRESHOLDS)


# ---------------------------------------------------------------------------
# The freeze, in the currency a raster keeps
# ---------------------------------------------------------------------------
def test_the_board_draws_without_text_colliding(view):
    """The failure a raster has and a page does not.

    In HTML a long insight pushes its panel taller. Here it draws over whatever
    sits beneath it, which is how `agent_pack`'s chart standards came to record
    186 collisions across twelve test renders. `render` refuses rather than
    returning an image with one.
    """
    _, _, overlaps = board_image.render(view)
    assert overlaps == []


def test_squeezing_a_panel_is_caught_rather_than_shipped(view, monkeypatch):
    """The guard has to fire, or it is decoration.

    Row two at 300px is exactly the height that put the reach panel's split
    figures under its insight sentence while the prototype was being built.
    """
    monkeypatch.setattr(board_image, "PANEL_ROW2_H", 300)
    with pytest.raises(RuntimeError, match="collides"):
        board_image.render(view)


def test_every_figure_in_the_view_reaches_the_canvas(view):
    """The content golden. A figure the view computed and the drawing dropped
    is the silent half of a wrong board -- nothing looks broken, one number is
    simply absent."""
    _, _, _ = board_image.render(view)
    canvas = _canvas(view)
    drawn = " ".join(item.text for item in canvas.drawn)

    for key in ("shortnotice_value", "leadership_value",
                "volume_value", "priority_total", "reach_executive_value",
                "reach_large_value", "period_label", "data_as_of",
                "leadership_average_label", "timing_peak_detail"):
        assert board_image.plain(view["scalars"][key]) in drawn, f"{key} never drawn"

    for row in view["rows"]["ownership_rows"]:
        assert board_image.plain(row["label"]) in drawn
        assert row["share"] in drawn
    for row in view["rows"]["priority_legend"]:
        assert board_image.plain(row["label"]) in drawn


def test_every_colour_the_renderer_asks_for_is_an_approved_token(view):
    """Asserted on what was requested, not on what the file ends up holding.

    A LANCZOS downscale blends white into Pastel I across a dozen intermediate
    tones, none of them a token and none of them a mistake. Reading the palette
    off the finished image would measure the resampler; the canvas records the
    colours it was handed, which is the claim worth making.
    """
    canvas = _canvas(view)
    assert canvas.inks <= APPROVED, f"off-palette: {sorted(canvas.inks - APPROVED)}"
    assert "#e60000" in canvas.inks, "the accent never reached the canvas"


def test_status_marks_are_drawn_and_never_typed(view):
    """Helvetica Neue has no triangle. Typed, it renders as a replacement box
    on one machine and a triangle on another -- a font-dependent difference in
    the one place the page states whether something is a breach."""
    canvas = _canvas(view)
    for item in canvas.drawn:
        assert not set(item.text) & set("▲▼●"), (
            f"{item.text!r} types a status mark instead of drawing it")


# ---------------------------------------------------------------------------
# Fonts
# ---------------------------------------------------------------------------
def test_the_renderer_reports_which_face_it_drew_with(view):
    _, chosen, _ = board_image.render(view)
    assert chosen.name
    assert set(chosen.faces) == {"light", "regular", "medium", "bold"}
    for path, _index in chosen.faces.values():
        assert Path(path).exists()
    assert isinstance(chosen.graded, bool)


def test_the_ladder_prefers_a_bundled_face_then_the_sandbox_one():
    """Order is a decision, not an accident.

    `bundled` first because dropping a licensed face into fonts/ is a
    deliberate act. DejaVu next -- ahead of anything local -- because it is what
    the agent's sandbox has, and a ladder that preferred this machine's fonts
    would give whoever renders here a prettier board than the readers get.
    """
    names = [name for name, _ in board_image.FONT_LADDER]
    assert names[0] == "bundled"
    assert names[1] == "DejaVu Sans"
    assert names.index("DejaVu Sans") < names.index("Helvetica Neue")


def test_a_family_missing_one_weight_is_skipped_whole(tmp_path):
    """A family that opens for body text and fails for the light face would
    draw a board whose hero figures silently changed weight."""
    real = board_image.resolve_font()
    crippled = dict(real.faces)
    crippled["light"] = ("/nowhere/absent.ttf", 0)
    with pytest.raises(RuntimeError, match="no drawable font"):
        board_image.resolve_font(ladder=(("half a family", crippled),))


def test_no_drawable_font_is_an_error_not_a_blank_page():
    absent = {w: ("/nowhere/none.ttf", 0)
              for w in ("light", "regular", "medium", "bold")}
    with pytest.raises(RuntimeError, match="no drawable font"):
        board_image.resolve_font(ladder=(("nothing", absent),))


def test_the_face_report_counts_distinct_files_not_entries(view):
    """A single-weight family maps four weights onto one file. `weights` says
    1 there and 4 for a graded family, which is what a caller comparing two
    runs needs to know."""
    _, chosen, _ = board_image.render(view)
    assert chosen.weights == len(set(chosen.faces.values()))
    assert chosen.graded is (chosen.weights > 1)


# ---------------------------------------------------------------------------
# Determinism and output
# ---------------------------------------------------------------------------
def test_the_same_view_draws_the_same_bytes_twice(view):
    """Byte-identical within one machine. Across machines the font decides,
    which is why `FontChoice` is returned rather than swallowed."""
    first, _, _ = board_image.render(view)
    second, _, _ = board_image.render(view)
    assert first.tobytes() == second.tobytes()


def test_it_writes_both_a_png_and_a_pdf(view, tmp_path):
    for name in ("board.png", "board.pdf"):
        chosen, overlaps = board_image.save(view, tmp_path / name)
        assert (tmp_path / name).stat().st_size > 10_000
        assert overlaps == []
        assert chosen.name


def test_the_drawn_board_and_the_page_share_one_view(view):
    """Neither renderer computes anything the other does not. The HTML page and
    the PNG can disagree about how a figure looks; they cannot disagree about
    what it is."""
    from pipeline.report import dashboard_render
    page = dashboard_render.render(view)
    canvas = _canvas(view)
    drawn = " ".join(item.text for item in canvas.drawn)
    for key in ("shortnotice_value", "leadership_value", "volume_value"):
        value = board_image.plain(view["scalars"][key])
        assert value in drawn and value in board_image.plain(page)


def _canvas(view):
    """Re-run the drawing to get at the recorded strings.

    `render` returns the image rather than the canvas, because a caller wants a
    board and not the bookkeeping; the tests want the bookkeeping.
    """
    captured = {}
    original = board_image.Canvas

    class Recording(original):
        def __post_init__(self):
            super().__post_init__()
            captured["canvas"] = self

    board_image.Canvas = Recording
    try:
        board_image.render(view, check=False)
    finally:
        board_image.Canvas = original
    return captured["canvas"]


# ---------------------------------------------------------------------------
# Real data is not the sample
# ---------------------------------------------------------------------------
_TEAMS = ("Group Communications", "Wealth Management",
          "Personal & Corporate Banking", "Asset Management", "Investment Bank",
          "Group Functions", "Other / Central Teams", "Technology & Operations",
          "Risk and Compliance Communications", "Human Resources Communications",
          "Sustainability & Impact", "Regional Communications EMEA",
          "Regional Communications APAC", "Investor Relations")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _sized(base, weeks, teams):
    data = json.loads(json.dumps(base))
    data["weeks"] = [{"commencing": f"{(i * 7) % 28 + 1} {_MONTHS[(i // 4) % 12]}",
                      "activities": 120 + (i * 37) % 260} for i in range(weeks)]
    total = data["activities_total"]
    data["teams"] = [{"name": _TEAMS[i % len(_TEAMS)],
                      "activities": max(1, total // (i + 2))} for i in range(teams)]
    data["leadership_by_team"] = [{"name": _TEAMS[i % len(_TEAMS)],
                                   "share": max(0.01, 0.30 - i * 0.013)}
                                  for i in range(teams)]
    return data


@pytest.mark.parametrize("weeks, teams", [
    (3, 2), (13, 7), (26, 10), (52, 14), (70, 20),
])
def test_the_board_fits_whatever_the_period_turns_out_to_hold(view, weeks, teams):
    """The sample is thirteen weeks and seven teams; the plan is not.

    The first version refused when the labels would not fit, which sounds
    careful and was not: refusing does not stop a board being produced, it
    moves the cutting to whoever holds the data. A real run dropped four of
    seven teams to get an image, and the board it produced said nothing about
    the four.
    """
    raw = SAMPLE.read_text(encoding="utf-8")
    base = json.loads(re.sub(r'"_comment":\s*\[[^\]]*\],', "", raw))
    _, _, overlaps = board_image.render(
        build_view(_sized(base, weeks, teams), THRESHOLDS))
    assert overlaps == []


def test_what_will_not_fit_is_named_on_the_page(view):
    """Capping is honest; capping quietly is not. The distribution panel sums
    its remainder, the rate panel says how many of how many it drew -- shares
    add up and rates do not, so an "others" bar there would be invented."""
    raw = SAMPLE.read_text(encoding="utf-8")
    base = json.loads(re.sub(r'"_comment":\s*\[[^\]]*\],', "", raw))
    canvas = _canvas(build_view(_sized(base, 52, 14), THRESHOLDS))
    drawn = " ".join(item.text for item in canvas.drawn)
    assert "more team" in drawn
    assert "showing the" in drawn and "of 14 teams" in drawn


def test_one_left_over_team_is_singular(view):
    raw = SAMPLE.read_text(encoding="utf-8")
    base = json.loads(re.sub(r'"_comment":\s*\[[^\]]*\],', "", raw))
    canvas = _canvas(build_view(_sized(base, 13, 14), THRESHOLDS))
    drawn = " ".join(item.text for item in canvas.drawn)
    assert "1 more teams" not in drawn


def test_a_long_name_is_clipped_rather_than_run_under_the_bars(view):
    """The collision check compares text with text, and a bar track is not
    text -- so a name overflowing its column passes the check and covers the
    chart anyway. Width is its own rule."""
    raw = SAMPLE.read_text(encoding="utf-8")
    base = json.loads(re.sub(r'"_comment":\s*\[[^\]]*\],', "", raw))
    canvas = _canvas(build_view(_sized(base, 13, 10), THRESHOLDS))
    ownership = [item.text for item in canvas.drawn if item.zone == "ownership"]

    assert "Risk and Compliance Communications" not in ownership, (
        "the longest team name reached the canvas whole and now runs under the bars")
    assert any(t.startswith("Risk and Compliance") and t.endswith("\u2026")
               for t in ownership), "the name was dropped rather than clipped"


def test_a_long_priority_label_is_clipped_to_its_legend(view):
    """The source's own priority labels are governance wording and long -- the
    legend ran off the panel because only the ownership column was clipped. A
    legend is a column too."""
    raw = SAMPLE.read_text(encoding="utf-8")
    base = json.loads(re.sub(r'"_comment":\s*\[[^\]]*\],', "", raw))
    wordy = json.loads(json.dumps(base))
    for i, row in enumerate(wordy["priorities"]):
        row["label"] = f"{i + 1} - a governance label long enough to overflow its column"
    canvas = _canvas(build_view(wordy, THRESHOLDS))
    legend = [item for item in canvas.drawn if item.zone == "priority"]
    assert any("…" in item.text for item in legend), "nothing was clipped"
    for item in legend:
        assert item.box[2] <= 900, f"{item.text!r} runs past the panel"


def test_the_average_line_survives_the_bars_it_crosses(view):
    """It was drawn under them, which held while the average sat mid-plot and
    failed the moment it sat below every bar -- the ordinary case, since a
    portfolio average is usually lower than the teams a panel is ranking. Real
    data put it at 14% against bars of 50 to 100 and it vanished entirely.
    """
    raw = SAMPLE.read_text(encoding="utf-8")
    base = json.loads(re.sub(r'"_comment":\s*\[[^\]]*\],', "", raw))
    low = json.loads(json.dumps(base))
    low["leadership_activities"] = int(low["activities_total"] * 0.14)
    low["leadership_by_team"] = [{"name": "ALL", "share": 1.00},
                                 {"name": "Group Legal", "share": 0.67}]
    view2 = build_view(low, THRESHOLDS)
    image, _, _ = board_image.render(view2)

    # Where the line crosses the first bar, which is black.
    offset = float(view2["scalars"]["leadership_average_offset"])
    y = int(board_image.PANEL_ROW1_H + 20 + 200 + 20 + 78 + 26
            + board_image.LEADERSHIP_PLOT_H - offset) + board_image.PAD + 140
    strip = [image.getpixel((x, y)) for x in range(80, 170)]
    assert any(sum(px) > 300 for px in strip), (
        "no light pixel where the reference line crosses the black bar -- "
        "it is behind the bars again")


def test_a_split_that_does_not_add_up_draws_rather_than_raising(view):
    """`validate` already reports it. A share above 1 drove the split bar to a
    negative width and Pillow raises on that, so a board became a stack trace
    over a data fault the run had already named."""
    raw = SAMPLE.read_text(encoding="utf-8")
    base = json.loads(re.sub(r'"_comment":\s*\[[^\]]*\],', "", raw))
    broken = json.loads(json.dumps(base))
    broken["activities_total"] = 849          # internal + external now exceed it
    complaints = dashboard_validate(broken)
    assert any("internal + external" in c for c in complaints)

    view3 = build_view(broken, THRESHOLDS)
    board_image.render(view3)                 # must not raise
    assert float(view3["scalars"]["reach_internal_width"].rstrip("%")) <= 100
