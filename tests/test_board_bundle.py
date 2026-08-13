"""The bundle and the repository draw the same board, or the build fails.

A bundler is the place a second copy of the code quietly becomes the real one.
So the equivalence is not argued, it is rendered: this suite executes the
bundle exactly as the sandbox does -- `exec` over the text, no imports, no
package -- draws from the sample, draws again through the modules, and compares
the two PNGs byte for byte.

That comparison is safe here in a way it is not across machines: both renders
run in this process, on this font. What travels is the code, and this is what
proves the code that travels is the code that was tested.
"""

import hashlib
import json
import re
from pathlib import Path

import pytest

pytest.importorskip("PIL")

from pipeline.report import board_bundle, board_image  # noqa: E402
from pipeline.report.dashboard_render import THRESHOLDS, build_view  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE = REPO_ROOT / "pipeline" / "dashboard" / "campaign-activity.sample.json"


@pytest.fixture(scope="module")
def bundle():
    return board_bundle.build()


@pytest.fixture(scope="module")
def sandbox(bundle):
    """The bundle executed the way `/mnt/data` will execute it."""
    namespace = {"__name__": "board_draw"}
    exec(compile(bundle, board_bundle.BUNDLE_NAME, "exec"), namespace)
    return namespace


@pytest.fixture
def data():
    raw = SAMPLE.read_text(encoding="utf-8")
    return json.loads(re.sub(r'"_comment":\s*\[[^\]]*\],', "", raw))


# ---------------------------------------------------------------------------
# The claim the bundler exists to keep
# ---------------------------------------------------------------------------
def test_the_bundle_draws_the_same_bytes_as_the_modules(sandbox, data, tmp_path):
    through_bundle = tmp_path / "bundle.png"
    through_modules = tmp_path / "modules.png"

    sandbox["draw"](data, str(through_bundle))
    board_image.save(build_view(data, THRESHOLDS), through_modules)

    assert (hashlib.sha256(through_bundle.read_bytes()).hexdigest()
            == hashlib.sha256(through_modules.read_bytes()).hexdigest()), (
        "the bundle and the repository drew different boards. Rebuild the "
        "bundle rather than editing it: it is assembled, not authored."
    )


def test_the_bundle_carries_no_repository_imports(bundle):
    """It runs where `pipeline` does not exist."""
    assert "from pipeline" not in bundle
    assert "import pipeline" not in bundle


def test_it_executes_with_no_package_and_no_file(bundle):
    """`exec` gives code neither `__file__` nor a package, and the font
    resolver wants the first. The shim supplies it rather than the module
    growing a branch for a caller it should not know about."""
    namespace = {"__name__": "board_draw"}
    exec(compile(bundle, "board-draw.txt", "exec"), namespace)
    assert callable(namespace["draw"])
    assert callable(namespace["draw_from_json"])
    assert namespace["__file__"].endswith("board-draw.txt")


def test_the_json_entry_point_tolerates_the_sample_comment(sandbox, tmp_path):
    """The data object may carry `_comment`; JSON has no comments and the
    samples need several."""
    out = tmp_path / "from-json.png"
    path, name, weights = sandbox["draw_from_json"](SAMPLE, str(out))
    assert Path(path).exists() and name and weights >= 1


# ---------------------------------------------------------------------------
# What the bundle must not become
# ---------------------------------------------------------------------------
def test_the_html_renderer_refuses_rather_than_half_working(sandbox):
    """The page renderer's helpers are stubbed. A call that should never happen
    in a sandbox says what it was, instead of surfacing later as a NameError
    about a template nobody shipped."""
    with pytest.raises(RuntimeError, match="does not write pages"):
        sandbox["substitute"]("{{ x }}", {}, where="nowhere")
    with pytest.raises(RuntimeError, match="does not write pages"):
        sandbox["load_template"]()


def test_the_bundle_holds_one_build_view_and_one_threshold_block(bundle):
    """Two copies of either is the drift this bundler exists to prevent."""
    assert bundle.count("\ndef build_view(") == 1
    assert bundle.count("\nTHRESHOLDS = {") == 1


def test_the_bundle_stays_small_enough_to_upload(bundle):
    """Not a hard limit, a canary. The sandbox reads this as a file, so size is
    cheap -- but a bundle that has quietly doubled is a bundle that has taken
    something it does not need."""
    assert len(bundle.encode("utf-8")) < 120_000


# ---------------------------------------------------------------------------
# The environment it was built for
# ---------------------------------------------------------------------------
def test_the_font_ladder_leads_with_what_the_sandbox_has(bundle):
    """Measured, not assumed: the sandbox reported 23 DejaVu faces including
    ExtraLight and Bold. The ladder prefers them over anything local so the
    board a reader gets is the board this machine can see."""
    assert "DejaVuSans-ExtraLight.ttf" in bundle
    assert "DejaVuSans-Bold.ttf" in bundle
    assert bundle.index("DejaVuSans.ttf") < bundle.index("HelveticaNeue.ttc")
