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
from pipeline.report.dashboard_render import THRESHOLDS, build_view  # noqa: E402

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

    for key in ("leadtime_value", "shortnotice_value", "leadership_value",
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
    assert Path(chosen.path).exists()
    assert isinstance(chosen.graded, bool)


def test_a_bundled_font_wins_the_ladder(tmp_path):
    """The only entry that makes two machines agree by construction, so it is
    first and stays first."""
    assert board_image.FONT_LADDER[0][0] == "bundled"
    assert board_image.FONT_LADDER[0][1].startswith("fonts/")


def test_no_drawable_font_is_an_error_not_a_blank_page():
    with pytest.raises(RuntimeError, match="no drawable font"):
        board_image.resolve_font(ladder=(("nothing", "/nowhere/none.ttf",
                                          {"light": 0, "regular": 0,
                                           "medium": 0, "bold": 0}),))


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
    for key in ("leadtime_value", "leadership_value", "volume_value"):
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
