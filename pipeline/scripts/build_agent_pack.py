"""Agent pack: the calendar report in a shape a retrieval agent can read.

Reads the same CSV exports as `report_calendar.py`, through the same scope
resolution, and writes the figures as plain text and CSV instead of as a
styled workbook -- over a scope wider by two filters, with every row saying
whether the workbook holds it. Why this is a different artefact rather than a
second sheet is in `pipeline/report/agent_pack.py`'s module docstring.

Usage:
    python pipeline/scripts/build_agent_pack.py
    python pipeline/scripts/build_agent_pack.py --year 2026
    python pipeline/scripts/build_agent_pack.py --from 2026-01-01 --to 2026-06-30
    python pipeline/scripts/build_agent_pack.py --out /path/to/folder
    python pipeline/scripts/build_agent_pack.py --agent-dir /path/to/CPLAN/agent

Takes the same period flags as the report, which is what keeps the two about
the same year. Only the period: the pack keeps the deprioritised bucket and the
catch-all-only rows that the report plans past, so its totals are larger by
design. `in_report = Yes` in the activities file reproduces the workbook.
"""

import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PIPELINE_DIR = SCRIPT_DIR.parent
REPO_DIR = PIPELINE_DIR.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from pipeline.report import agent_builder, agent_pack              # noqa: E402
from pipeline.scripts.process_cplan import (                       # noqa: E402
    ONEDRIVE_INPUT_DIR,
    ONEDRIVE_OUTPUT_DIR,
    find_onedrive_root,
    log,
    print_banner,
)
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
#
# This is now the fallback rather than the destination -- see resolve_output_dir.
LOCAL_OUTPUT_DIR = PIPELINE_DIR / "output" / "agent-pack"


def resolve_output_dir():
    """The OneDrive CPLAN folder when it is there, the local one otherwise.

    The pack is the only artefact here that has to leave the machine: it is
    uploaded to the agent by hand, and a folder inside a git checkout is both
    unsynced and unfindable from anywhere else. It lands in the same OneDrive
    folder the source CSVs arrive in -- one path, already synced, already
    backed up, already known to whoever runs this.

    Nothing in the pipeline deletes from that folder, and no file the pack
    writes matches an input glob, so the two sets sit side by side without
    either reading or overwriting the other. `test_the_pack_cannot_be_mistaken
    _for_its_own_input` holds that second half, which is the one a later
    rename could quietly break.

    The folder is used only when it exists and is never created: a path
    conjured inside a OneDrive that is not really set up syncs nowhere while
    looking like it worked. That is `find_input_dir`'s rule, for its reason.
    """
    root = find_onedrive_root()
    if root:
        target = root / ONEDRIVE_INPUT_DIR
        if target.exists():
            return target
        log(f"OneDrive root found ({root}) but {ONEDRIVE_INPUT_DIR} does not exist")
    return LOCAL_OUTPUT_DIR


BUILDER_DIRNAME = "agent-builder"
BUILDER_LOCAL_OUTPUT_DIR = PIPELINE_DIR / "output" / BUILDER_DIRNAME


def resolve_builder_output_dir():
    """`Output/agent-builder`, created -- but only where `Input/` proves it can be.

    `resolve_output_dir` never creates its target, and the reason holds: a path
    conjured inside a OneDrive that is not really set up syncs nowhere while
    looking like it worked. `Output/` is different only in that it may
    legitimately not exist yet, and refusing to create it would drop this
    delivery into the checkout on every first run -- unsynced, and uploaded
    from the wrong machine, which is the failure the rule is there to prevent.

    `Input/` is the evidence. The pipeline reads from it, so its presence means
    the CPLAN folder is really syncing; a sibling of a real folder is safe to
    create. Without it nothing is conjured and the fallback is reported,
    exactly as next door.
    """
    root = find_onedrive_root()
    if root:
        if (root / ONEDRIVE_INPUT_DIR).exists():
            target = root / ONEDRIVE_OUTPUT_DIR / BUILDER_DIRNAME
            target.mkdir(parents=True, exist_ok=True)
            return target
        log(f"OneDrive root found ({root}) but {ONEDRIVE_INPUT_DIR} does not exist, "
            f"so {ONEDRIVE_OUTPUT_DIR} is not created either")
    return BUILDER_LOCAL_OUTPUT_DIR


# The folder the agent's knowledge is synced from, which is not a folder this
# repository can name. It sits in a synced document library -- beside OneDrive
# rather than inside it -- under a tenant and a site that differ per machine,
# per person and per agent, so the path cannot be written down here and a
# hardcoded one would be wrong on every machine but one.
#
# Its *shape* can be written down: two named segments at the end of a path,
# created by hand by whoever wants the mirror. Creating that folder is the
# whole instruction, and it is one the operator gives in Explorer without
# touching a config file.
AGENT_DIR_ENV = "CPLAN_AGENT_DIR"
AGENT_DIR_TAIL = Path("CPLAN") / "agent"

# Its own exit code, because "the pack was not built" and "the pack was built
# and not mirrored" ask for different things from whoever reads it, and the
# launcher's advice for the first ("the export has not landed yet") sends the
# operator looking in the wrong folder for the second. Not 1, which is a failed
# run, and not 2, which argparse already uses for a mistyped flag.
MIRROR_MISSING_EXIT = 3


def find_agent_dirs():
    """Every `CPLAN\\agent` folder under the user profile, sorted.

    Searched one and two folders deep, which is where both layouts put it: a
    synced library lands at `<profile>\\<tenant>\\<site> - <library>\\`, and the
    OneDrive the exports already use is one level shallower. Deeper than that
    is not guessed at -- `--agent-dir` names it instead, and the run says so.

    Nothing is created, and nothing inside the checkout counts: a repository
    that one day grows an `agent/` folder must not silently become the
    destination for a knowledge upload.
    """
    home = Path.home()
    tail = AGENT_DIR_TAIL.as_posix()
    found = []
    for depth in ("*", "*/*"):
        for path in home.glob(f"{depth}/{tail}"):
            if path.is_dir() and REPO_DIR not in path.parents and path not in found:
                found.append(path)
    return sorted(found)


def named_agent_dir(explicit=None):
    """The folder the operator named -- by flag, then by environment."""
    named = explicit or os.environ.get(AGENT_DIR_ENV)
    return Path(named).expanduser() if named else None


def resolve_agent_dir(explicit=None):
    """Where to mirror the upload set, or None -- with the reason said out loud.

    A named folder that is not there is an error rather than a fallback: the
    operator asked for the mirror, and a run that quietly does not mirror hands
    them a folder that looks maintained and holds last week's figures. A folder
    that was never named is not an error at all -- nothing was asked for -- and
    the run says how to ask.

    Two candidates end the same way as none. Guessing between them would feed
    an agent nobody meant to feed, and the wrong knowledge in the right place
    is not visible from either folder.
    """
    named = named_agent_dir(explicit)
    if named:
        if named.is_dir():
            return named
        log(f"The agent folder {named} does not exist, so nothing was mirrored. "
            "Create it, or name another one.")
        return None

    found = find_agent_dirs()
    if len(found) == 1:
        return found[0]
    if not found:
        log(f"No {AGENT_DIR_TAIL} folder under {Path.home()}, so the upload set was "
            "not mirrored anywhere.")
        log(f"  Create that folder in your synced library, or name it with "
            f"--agent-dir / {AGENT_DIR_ENV}.")
        return None
    log(f"{len(found)} agent folders found, so none was written to:")
    for path in found:
        log(f"  {path}")
    log(f"  Name the one you mean with --agent-dir or {AGENT_DIR_ENV}.")
    return None


def build_pack_parser():
    """The report's own parser, with `--out` renamed to what it means here."""
    parser = build_parser()
    for action in parser._actions:
        if action.dest == "out":
            action.help = (f"Output folder (default: OneDrive\\{ONEDRIVE_INPUT_DIR}, "
                           f"or {LOCAL_OUTPUT_DIR} when that is not present)")
    parser.add_argument("--agent-dir",
                        help=(f"Folder to mirror the upload set into (default: the "
                              f"{AGENT_DIR_TAIL} folder under your user profile, when "
                              f"exactly one exists)"))
    parser.description = "Generate the agent pack from the CSV exports"
    return parser


def main(argv=None):
    parser = build_pack_parser()
    args = parser.parse_args(argv)
    config = resolve_config(CONFIG, args, parser)

    print_banner("CPLAN Agent Pack")
    log(f"Period: {config.period_label()}")

    # The workbook plans and the pack answers questions, so they want different
    # scopes: priority 4 is the bucket nobody plans against, and the objectives
    # filter drops rows tagged with nothing but the catch-all. Both belong in a
    # planning instrument and neither belongs in front of someone asking which
    # deprioritised activities are coming up. `report_config` is kept so every
    # row can still say whether the workbook would have held it.
    report_config = config
    config = agent_pack.pack_config(config)
    scope, config = resolve_scope(args, config)
    if scope is None:
        return 1
    if report_config.exclude_priorities or report_config.exclude_objectives:
        log("Pack scope is wider than the workbook's: "
            f"priorities {report_config.exclude_priorities or 'none'} and "
            f"objectives {report_config.exclude_objectives or 'none'} are kept "
            "here and marked with in_report=No")

    out_dir = Path(args.out) if args.out else resolve_output_dir()
    pack_dir = agent_pack.write_pack(scope, config, out_dir,
                                     report_config=report_config)

    # Listed under the folder each file is actually in, not as one flat list:
    # which of the artefacts may be uploaded is the only decision this command
    # leaves to the reader, and a flat list hides it.
    log(f"{agent_pack.PACK_DIRNAME}\\  -- what the skill archive is built from. Nothing to upload")
    for path in sorted(pack_dir.iterdir()):
        log(f"  {path.name:<22} {path.stat().st_size / 1024:>8.1f} KB")
    log(f"{out_dir.name}\\  -- beside it")
    for name, note in (
            (agent_pack.SKILL_ZIP_NAME, "the same content as a skill package"),
            (agent_pack.BRAND_SKILL_ZIP_NAME, "second skill: the chart rules -- upload once, re-upload only when they change"),
            (agent_pack.DASHBOARD_SKILL_ZIP_NAME, "third skill: the named boards -- upload once, re-upload only when a board changes"),
            (agent_pack.INSTRUCTIONS_NAME, "the agent's Instructions -- replace <ORGANISATION>"),
            (agent_pack.EVALUATION_NAME, "import under Evaluate (safe: never grounded on)"),
            (agent_pack.CHECKLIST_NAME, "ANSWER KEY -- do NOT upload as knowledge")):
        path = out_dir / name
        log(f"  {name:<22} {path.stat().st_size / 1024:>8.1f} KB  {note}")
    log("")
    log(f"Written to {out_dir}")

    # The second delivery, from the same pack in the same run. Two commands
    # would let one be rebuilt and the other forgotten, and two packs built on
    # two days are two vintages of one figure -- invisible, because both
    # folders look freshly built.
    builder_dir = resolve_builder_output_dir()
    upload_dir = agent_builder.write_builder_pack(pack_dir, builder_dir,
                                                  scope, config)
    log("")
    log(f"{builder_dir.name}\\  -- the Agent Builder delivery, for a surface with no skills")
    log(f"  {agent_builder.UPLOAD_DIRNAME + chr(92):<22} "
        f"{len(list(upload_dir.iterdir())):>8} files  upload ALL of these as Knowledge")
    for name, note in (
            (agent_builder.INSTRUCTIONS_NAME,
             f"paste into Instructions -- replace {agent_pack.ORGANISATION_PLACEHOLDER}"),
            (agent_builder.DESCRIPTION_NAME, "paste into Description"),
            (agent_builder.STARTER_PROMPTS_NAME, "four prompts, one per line"),
            (agent_builder.README_NAME, "these four steps, in order"),
            (agent_pack.CHECKLIST_NAME, "ANSWER KEY -- not uploaded, not pasted")):
        path = builder_dir / name
        log(f"  {name:<22} {path.stat().st_size / 1024:>8.1f} KB  {note}")
    log("")
    log(f"Written to {builder_dir}")

    # The last step of the delivery, and the one that used to be done by hand.
    # It runs after both folders are written and reported, so a mirror that
    # cannot happen costs the operator a line of output rather than the run.
    agent_dir = resolve_agent_dir(args.agent_dir)
    log("")
    if agent_dir is None:
        log("The agent's own folder was not written to. Nothing else changed.")
        # Named and missing is the operator's own instruction going unfollowed,
        # and a zero exit code would report it as a clean run.
        return MIRROR_MISSING_EXIT if named_agent_dir(args.agent_dir) else 0

    copied, removed = agent_builder.mirror_upload(upload_dir, agent_dir)
    log(f"{agent_dir}")
    log(f"  {len(copied):>3} files mirrored from {agent_builder.UPLOAD_DIRNAME}\\ "
        "-- the upload is already done for a folder-backed knowledge source")
    if removed:
        # Named rather than counted: a removal is the only thing this step does
        # that the operator cannot undo by running it again.
        log(f"  {len(removed):>3} superseded by this run's numbering, removed: "
            f"{', '.join(removed)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
