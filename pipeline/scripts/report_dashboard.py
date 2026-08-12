"""Campaign activity dashboard: a data file in, one standalone HTML page out.

No model sits in this path. The markup is frozen in
`pipeline/dashboard/campaign-activity.template.html`, the thresholds are in
`THRESHOLDS` in `pipeline/report/dashboard_render.py`, and this script only
joins the two. Same data in, byte-identical page out -- which is the whole
reason the dashboard stopped being regenerated.

Usage:
    python pipeline/scripts/report_dashboard.py
    python pipeline/scripts/report_dashboard.py --data path/to/quarter.json
    python pipeline/scripts/report_dashboard.py --out /path/to/dashboard.html
    python pipeline/scripts/report_dashboard.py --check      # golden-file check
    python pipeline/scripts/report_dashboard.py --strict     # fail on data gaps

`--check` renders and compares against the committed golden file without
writing anything. It is the guard that makes "frozen" mean something: any edit
to the template, the renderer or the sample data that changes the page has to
be accompanied by a deliberate `--update-golden`.
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

from pipeline.report.dashboard_render import (  # noqa: E402
    THRESHOLDS,
    build_view,
    render,
    validate,
)

DASHBOARD_DIR = PIPELINE_DIR / "dashboard"
SAMPLE_DATA = DASHBOARD_DIR / "campaign-activity.sample.json"
GOLDEN_PATH = DASHBOARD_DIR / "campaign-activity.golden.html"
REPORTS_DIR = PIPELINE_DIR / "output" / "reports"


def load_data(path):
    """Read the data object, dropping the `_comment` key the sample carries.

    JSON has no comments and the sample file needs several, so it keeps them in
    a key the reader ignores. Stripping it here rather than in the renderer
    means a hand-written data file may carry notes too.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    data.pop("_comment", None)
    return data


def default_output_path(data):
    slug = (
        str(data.get("period_label", "period"))
        .replace(" ", "-").replace("·", "").replace("--", "-")
    )
    slug = "".join(ch for ch in slug if ch.isalnum() or ch in "-_")
    return REPORTS_DIR / f"CPLAN_dashboard_{slug}.html"


def build_parser():
    parser = argparse.ArgumentParser(
        description="Render the campaign activity dashboard from a data file."
    )
    parser.add_argument("--data", type=Path, default=SAMPLE_DATA,
                        help="data object to render (default: the sample)")
    parser.add_argument("--out", type=Path,
                        help="where to write the page (default: pipeline/output/reports)")
    parser.add_argument("--check", action="store_true",
                        help="compare against the golden file, write nothing")
    parser.add_argument("--update-golden", action="store_true",
                        help="rewrite the golden file from the sample data")
    parser.add_argument("--strict", action="store_true",
                        help="exit non-zero when the data does not add up")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    data = load_data(args.data)
    complaints = validate(data)
    for complaint in complaints:
        print(f"  data: {complaint}", file=sys.stderr)

    page = render(build_view(data, THRESHOLDS))

    if args.check:
        if not GOLDEN_PATH.exists():
            print(f"no golden file at {GOLDEN_PATH}", file=sys.stderr)
            return 1
        if GOLDEN_PATH.read_text(encoding="utf-8") == page:
            print(f"matches {GOLDEN_PATH.name}")
            return 1 if (complaints and args.strict) else 0
        print(
            f"differs from {GOLDEN_PATH.name}. If the change was intended, "
            f"rerun with --update-golden and commit the result.",
            file=sys.stderr,
        )
        return 1

    if args.update_golden:
        GOLDEN_PATH.write_text(page, encoding="utf-8")
        print(f"Wrote {GOLDEN_PATH}")
        return 1 if (complaints and args.strict) else 0

    out = args.out or default_output_path(data)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"Wrote {out}")
    return 1 if (complaints and args.strict) else 0


if __name__ == "__main__":
    raise SystemExit(main())
