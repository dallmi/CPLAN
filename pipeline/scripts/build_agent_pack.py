"""Agent pack: the calendar report in a shape a retrieval agent can read.

Reads the same CSV exports as `report_calendar.py`, through the same scope
resolution, and writes the same figures as plain text and CSV instead of as a
styled workbook. Why that is a different artefact rather than a second sheet is
in `pipeline/report/agent_pack.py`'s module docstring.

Usage:
    python pipeline/scripts/build_agent_pack.py
    python pipeline/scripts/build_agent_pack.py --year 2026
    python pipeline/scripts/build_agent_pack.py --from 2026-01-01 --to 2026-06-30
    python pipeline/scripts/build_agent_pack.py --out /path/to/folder

Takes the same period flags as the report. Running both with the same flags is
what makes them two renderings of one report rather than two reports.
"""

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PIPELINE_DIR = SCRIPT_DIR.parent
REPO_DIR = PIPELINE_DIR.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from pipeline.report import agent_pack                             # noqa: E402
from pipeline.scripts.process_cplan import log, print_banner       # noqa: E402
from pipeline.scripts.report_calendar import (                     # noqa: E402
    CONFIG,
    build_parser,
    resolve_config,
    resolve_scope,
)

# Beside `reports/`, not inside it: that folder holds nothing but .xlsx by
# deliberate choice, and a delivered workbook was easy to lose among the
# pipeline's working data. The pack is a folder of many small files and would
# have made `reports/` unreadable in exactly the same way.
DEFAULT_OUTPUT_DIR = PIPELINE_DIR / "output" / "agent-pack"


def build_pack_parser():
    """The report's own parser, with `--out` renamed to what it means here."""
    parser = build_parser()
    for action in parser._actions:
        if action.dest == "out":
            action.help = (f"Output folder (default: {DEFAULT_OUTPUT_DIR})")
    parser.description = "Generate the agent pack from the CSV exports"
    return parser


def main(argv=None):
    parser = build_pack_parser()
    args = parser.parse_args(argv)
    config = resolve_config(CONFIG, args, parser)

    print_banner("CPLAN Agent Pack")
    log(f"Period: {config.period_label()}")
    scope, config = resolve_scope(args, config)
    if scope is None:
        return 1

    out_dir = Path(args.out) if args.out else DEFAULT_OUTPUT_DIR
    pack_dir = agent_pack.write_pack(scope, config, out_dir)

    # Listed under the folder each file is actually in, not as one flat list:
    # which of the artefacts may be uploaded is the only decision this command
    # leaves to the reader, and a flat list hides it.
    log(f"{agent_pack.PACK_DIRNAME}\\  -- upload this folder as a knowledge source")
    for path in sorted(pack_dir.iterdir()):
        log(f"  {path.name:<22} {path.stat().st_size / 1024:>8.1f} KB")
    log(f"{out_dir.name}\\  -- beside it")
    for name, note in (
            (agent_pack.SKILL_ZIP_NAME, "the same content as a skill package"),
            (agent_pack.BRAND_SKILL_ZIP_NAME, "second skill: the chart rules -- upload once, re-upload only when they change"),
            (agent_pack.INSTRUCTIONS_NAME, "the agent's Instructions -- replace <ORGANISATION>"),
            (agent_pack.EVALUATION_NAME, "import under Evaluate (safe: never grounded on)"),
            (agent_pack.CHECKLIST_NAME, "ANSWER KEY -- do NOT upload as knowledge")):
        path = out_dir / name
        log(f"  {name:<22} {path.stat().st_size / 1024:>8.1f} KB  {note}")
    log("")
    log(f"Written to {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
