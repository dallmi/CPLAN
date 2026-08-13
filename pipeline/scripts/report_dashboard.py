"""Executive boards: a data file in, one standalone HTML page out.

No model sits in this path. Each board's markup is frozen in a template under
`pipeline/dashboard/`, its rules live in a renderer under `pipeline/report/`,
and this script only joins the two. Same data in, byte-identical page out --
which is the whole reason these pages stopped being regenerated.

Usage:
    python pipeline/scripts/report_dashboard.py
    python pipeline/scripts/report_dashboard.py --board leadership-attention
    python pipeline/scripts/report_dashboard.py --data path/to/quarter.json
    python pipeline/scripts/report_dashboard.py --out /path/to/dashboard.html
    python pipeline/scripts/report_dashboard.py --check      # golden-file check
    python pipeline/scripts/report_dashboard.py --strict     # fail on data gaps
    python pipeline/scripts/report_dashboard.py --image board.png   # drawn, not HTML

`--check` renders and compares against the committed golden file without
writing anything. It is the guard that makes "frozen" mean something: any edit
to a template, a renderer or the sample data that changes a page has to be
accompanied by a deliberate `--update-golden`.

Boards are registered in BOARDS below rather than each getting a launcher of
its own. A second script would be a second answer to what `--check` means, and
the check is the one thing every board has to agree about.

`--image` draws the board to PNG or PDF instead of writing HTML, through a
second renderer over the same view -- so the two media cannot disagree about a
figure. It needs Pillow, which the HTML path deliberately does not: a checkout
without it renders every page and is told plainly that only `--image` is
missing.
"""

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PIPELINE_DIR = SCRIPT_DIR.parent
REPO_DIR = PIPELINE_DIR.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from pipeline.report import dashboard_render, leadership_render  # noqa: E402

DASHBOARD_DIR = PIPELINE_DIR / "dashboard"
REPORTS_DIR = PIPELINE_DIR / "output" / "reports"


def _campaign_activity(data):
    return dashboard_render.render(
        dashboard_render.build_view(data, dashboard_render.THRESHOLDS)
    )


def _leadership_attention(data):
    return leadership_render.render(leadership_render.build_view(data))


BOARDS = {
    "campaign-activity": {
        "summary": "the communications portfolio, for a management audience",
        "sample": DASHBOARD_DIR / "campaign-activity.sample.json",
        "golden": DASHBOARD_DIR / "campaign-activity.golden.html",
        "validate": dashboard_render.validate,
        "render": _campaign_activity,
        # Kept as it was before there was more than one board: the file name is
        # what people have in their downloads folder and in links to it.
        "stem": "CPLAN_dashboard",
    },
    "leadership-attention": {
        "summary": "where executive time goes, and where it is missing",
        "sample": DASHBOARD_DIR / "leadership-attention.sample.json",
        "golden": DASHBOARD_DIR / "leadership-attention.golden.html",
        "validate": leadership_render.validate,
        "render": _leadership_attention,
        "stem": "CPLAN_leadership",
    },
}

DEFAULT_BOARD = "campaign-activity"

# Kept for the callers that imported these before the registry existed.
SAMPLE_DATA = BOARDS[DEFAULT_BOARD]["sample"]
GOLDEN_PATH = BOARDS[DEFAULT_BOARD]["golden"]


def load_data(path):
    """Read the data object, dropping the `_comment` key the sample carries.

    JSON has no comments and the sample files need several, so they keep them
    in a key the reader ignores. Stripping it here rather than in a renderer
    means a hand-written data file may carry notes too.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    data.pop("_comment", None)
    return data


def default_output_path(data, board):
    slug = (
        str(data.get("period_label", "period"))
        .replace(" ", "-").replace("·", "").replace("--", "-")
    )
    slug = "".join(ch for ch in slug if ch.isalnum() or ch in "-_")
    return REPORTS_DIR / f"{board['stem']}_{slug}.html"


def build_parser():
    parser = argparse.ArgumentParser(
        description="Render an executive board from a data file."
    )
    parser.add_argument("--board", choices=sorted(BOARDS), default=DEFAULT_BOARD,
                        help=f"which board to render (default: {DEFAULT_BOARD})")
    parser.add_argument("--data", type=Path,
                        help="data object to render (default: the board's sample)")
    parser.add_argument("--out", type=Path,
                        help="where to write the page (default: pipeline/output/reports)")
    parser.add_argument("--check", action="store_true",
                        help="compare against the golden file, write nothing")
    parser.add_argument("--update-golden", action="store_true",
                        help="rewrite the golden file from the sample data")
    parser.add_argument("--strict", action="store_true",
                        help="exit non-zero when the data does not add up")
    parser.add_argument("--image", type=Path, metavar="PATH",
                        help="draw the board to a .png or .pdf instead of HTML")
    return parser


def _draw(name, data, out, complaints, strict):
    """Draw the board rather than writing it.

    Only the campaign activity board has a raster renderer so far; the others
    say so rather than falling back to a page the caller did not ask for.
    """
    if name != "campaign-activity":
        print(f"--image is not available for {name} yet", file=sys.stderr)
        return 1
    try:
        from pipeline.report import board_image
    except ImportError:
        print("--image needs Pillow: pip install -r requirements-dev.txt",
              file=sys.stderr)
        return 1

    view = dashboard_render.build_view(data, dashboard_render.THRESHOLDS)
    out.parent.mkdir(parents=True, exist_ok=True)
    chosen, _ = board_image.save(view, out)
    print(f"Wrote {out}")
    # The face decides whether two machines drew the same board, so the run
    # says which one it used rather than leaving the reader to assume.
    print(f"  drawn with {chosen.name}"
          f"{'' if chosen.graded else ' (single weight: hierarchy is size only)'}")
    return 1 if (complaints and strict) else 0


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    board = BOARDS[args.board]

    data = load_data(args.data or board["sample"])
    complaints = board["validate"](data)
    for complaint in complaints:
        print(f"  data: {complaint}", file=sys.stderr)

    if args.image:
        return _draw(args.board, data, args.image, complaints, args.strict)

    page = board["render"](data)
    golden = board["golden"]

    if args.check:
        if not golden.exists():
            print(f"no golden file at {golden}", file=sys.stderr)
            return 1
        if golden.read_text(encoding="utf-8") == page:
            print(f"matches {golden.name}")
            return 1 if (complaints and args.strict) else 0
        print(
            f"differs from {golden.name}. If the change was intended, "
            f"rerun with --update-golden and commit the result.",
            file=sys.stderr,
        )
        return 1

    if args.update_golden:
        golden.write_text(page, encoding="utf-8")
        print(f"Wrote {golden}")
        return 1 if (complaints and args.strict) else 0

    out = args.out or default_output_path(data, board)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"Wrote {out}")
    return 1 if (complaints and args.strict) else 0


if __name__ == "__main__":
    raise SystemExit(main())
