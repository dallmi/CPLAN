"""The same report, in a shape a retrieval agent can actually read.

The workbook is a presentation artefact. Its meaning lives in cell coordinates,
merged headers, collapsed outlines and formulas -- and a grounding index keeps
none of those. A share cell written by `style.write_formula` carries no cached
value at all until Excel opens the file and recalculates, so an indexer reads
the literal string `=TEXT(IF(B$23=0,0,B24/B$23),"0%") & "  Internal"` where a
reader sees `71%  Internal`. On the Executive Summary that formula IS the row
label, so the percentage and the label are lost together.

So this module renders the same figures again, with the opposite priorities:

* **Values, never formulas.** Every share is computed here.
* **Long, never wide.** The calendar matrix needs a row label AND a column
  label to make a cell mean anything, and chunked retrieval reliably keeps
  neither. One row per block x value x week carries its own labels, so the
  file can be split at any line without a row losing its meaning.
* **Said out loud, never implied by layout.** Three rules the workbook states
  by omission -- the absent TOTAL row under an overlapping block, the scope
  criteria that make a filtered-out activity look like a zero, the audience
  estimate that is not reach -- are sentences here. An absence cannot ground.
* **Plain text, never Markdown.** `.md` is not on SharePoint's crawled-
  extension list, and files that are not crawled are not retrievable. The
  prose files carry Markdown's shape and a `.txt` extension.

Same `metrics` functions the sheets call rather than a second implementation,
so a figure computed for both is computed once -- `tests/test_agent_pack.py`
holds the two to each other.

The scope is deliberately NOT the same. The workbook plans and leaves out what
nobody plans against; the pack answers questions and leaves it in, so
`pack_config` drops the priority and objectives filters. Every activity row
then says whether the workbook holds it, and the summary says how many it does
not -- a divergence that can be reconciled from either end rather than a second
total nobody can explain.
"""

import csv
import io
import re
import zipfile
from dataclasses import replace
from datetime import date, timedelta

from pipeline.report import dashboard_skill, derive, metrics, packs as packs_module
from pipeline.report.calendar_sheet import (
    NOT_SPECIFIED,
    PARTITION_BREAKDOWN_FIELDS,
    SPLIT_FIELDS,
    _sort_key,
    _split_for,
)
from pipeline.report.config import (
    AUDIENCE_BAND_ORDER,
    BAND_UNKNOWN,
    FIELD_TITLES,
    LARGE_AUDIENCE_BANDS,
    SHORT_NOTICE_DAYS,
)
from pipeline.report.data import EXCLUSION_ORDER
from pipeline.report.table_sheets import ACTIVITY_COLUMNS, _glossary_sections

# What the skill archive is built from, and the readable copy of what the agent
# is holding. It was a knowledge source too until two probes showed the agent
# never reached for it; the README records what they were and where the size
# limit of reading a file whole would put it back.
#
# It stays in its own directory regardless: the checklist is an answer key, and
# anywhere inside this folder it would travel into the archive and let the
# agent pass the test by reading the answers.
PACK_DIRNAME = "pack"
SKILL_ZIP_NAME = "cplan-skill.zip"
# A second, data-free skill: the visual rules that only apply once something is
# drawn. Its own archive rather than a folder inside the first, because the two
# are uploaded as two skills and load independently -- an image can need the
# chart rules on a turn that never touches the calendar.
BRAND_SKILL_ZIP_NAME = "chart-standards-skill.zip"
# A third skill: which panels make up a named board. Its own archive for the
# reason the chart rules have one -- the three load independently, and a
# request for a board needs all three while a one-line factual answer needs
# none of them.
DASHBOARD_SKILL_ZIP_NAME = "cplan-dashboards-skill.zip"
CHECKLIST_NAME = "checklist.md"
INSTRUCTIONS_NAME = "agent-instructions.md"
EVALUATION_NAME = "evaluation.csv"

# Copilot Studio's evaluation import, taken from the template the product
# itself hands out -- not from the documentation, which describes a different
# harness and got every one of these wrong on the first attempt.
#
# `conversationNumber` groups rows into one multi-turn test case. Every
# question here is independent, so each takes its own number rather than
# sharing one: rows sharing a number run as a single conversation, and seven
# unrelated questions asked in sequence would carry each other's context.
#
# Safe to upload although it carries the answers, and the checklist is not:
# an evaluation set is never grounded on. The agent is handed the question
# column and nothing else, and the reference reply is read by whoever reviews
# the run -- the template says outright that the agent's response "isn't
# compared to this reference answer". Put an answer in the question and that
# stops being true.
EVALUATION_HEADER = ("conversationNumber", "question", "response")
EVALUATION_MAX_CASES = 100
EVALUATION_MAX_QUESTION_CHARS = 500

README_NAME = "00-README.txt"
SUMMARY_NAME = "01-summary.txt"
GLOSSARY_NAME = "02-glossary.txt"
QUALITY_NAME = "03-data-quality.txt"
CALENDAR_NAME = "04-calendar.csv"
ACTIVITIES_CSV_NAME = "05-activities.csv"
BREAKDOWN_NAME = "06-breakdowns.csv"
PACKS_CSV_NAME = "07-packs.csv"
PERIODS_CSV_NAME = "08-periods.csv"

# No `Category` column: the form is documented to have one, the export does
# not carry it, and a header over permanently empty cells asserts a
# distinction the data never made -- the same reason the leadership split
# columns arrive with a member list and not before.
PACKS_HEADER = ("Pack ID", "Pack", "Cluster", "Lead", "Lead team",
                "Partner team", "Divisions", "Regions", "Objective",
                "Start", "End", "Launch", "Description",
                "activities_in_scope", "activities_total", "in_report")

# The pack frame's column behind each header above, in the same order. Two
# are computed rather than read and are handled at the call site.
PACK_FIELDS = ("cpid", "pack_name", "tracking_cluster", "lead",
               "lead_team", "partner_team", "business_division", "region",
               "strategic_objective", "start_date", "end_date", "launch_date",
               "short_description")

# The block name for the row that carries the portfolio itself. Upper case
# because it is not a field: every other block names the column it groups by,
# and a reader (or an agent) filtering `block == "TOTAL"` is asking for the one
# set of rows that genuinely sums to the portfolio.
TOTAL_BLOCK = "TOTAL"
TOTAL_VALUE = "all activities"

CALENDAR_HEADER = ("block", "value", "overlaps", "iso_year", "iso_week",
                   "week_start", "activities")

BREAKDOWN_HEADER = ("block", "value", "overlaps", "measure", "figure")

# `figure`, not `count`: six of the seven measures are counts and one is a
# median, and a column named `count` holding a median is a lie in the header
# row of a file whose whole point is that a machine reads it.
BREAKDOWN_MEASURES = ("activities", "with_executives", "large_audience",
                      "without_pack", "unknown_audience", "median_completeness",
                      "short_notice")

# Measures that restate the block they sit in. `large_audience` and
# `unknown_audience` under the audience bands are the band's own definition;
# `with_executives` under an executive block is every row in it.
#
# Left out for the reason `calendar_rows` leaves out empty week/value pairs: a
# row that cannot be wrong cannot inform either, and it competes for the same
# retrieval budget as one that can.
TAUTOLOGICAL_MEASURES = {
    "audience_band": ("large_audience", "unknown_audience"),
    "executives": ("with_executives",),
    "executives_geb": ("with_executives",),
    "executives_geb1": ("with_executives",),
}


def _rule(text):
    """A rule line for the prose files: one blank line, then the sentence."""
    return ["", text]


# The one glossary rule that is a property of the RUN rather than of the data.
#
# Every other rule here holds on any pack. This one depends on whether the
# operator supplied a GEB member list at build time, and the two versions
# contradict each other on purpose: printing the combined wording beside an
# `executives_geb` block would tell the agent the blocks in front of it cannot
# exist, which is the failure `.loop.md` records three times over -- prose that
# claims a data shape the files disprove is believed, because that is what it
# is for.
GEB_RULE_COMBINED = (
    "GEB/GEB-1 is one field holding both levels, with nothing in the data "
    "saying which. Never name someone as a GEB member, and never answer "
    '"how many activities involve the GEB" -- the honest answer is '
    '"GEB or GEB-1".')

GEB_RULE_SPLIT = (
    "GEB and GEB-1 are separated in this pack, and only because a GEB member "
    "list was supplied when it was built -- the source field holds both levels "
    f"mixed, exactly as before. In {BREAKDOWN_NAME} and {CALENDAR_NAME}, "
    "block=executives_geb names the people on that list and "
    "block=executives_geb1 everyone else in the field. Naming someone as a GEB "
    "member is allowed here, and says where it comes from: the supplied list, "
    "not the source data. The two blocks do NOT sum -- one activity naming "
    "people at both levels counts in both.")


def geb_rule(scope):
    """Which of the two leadership rules this run is entitled to state."""
    return GEB_RULE_SPLIT if scope.membership is not None else GEB_RULE_COMBINED


# --------------------------------------------------------------------------
# The blocks, derived exactly as the calendar sheet derives them
# --------------------------------------------------------------------------

def iter_blocks(scope, config):
    """Yield `(block, value, overlaps, subset)` for every calendar row.

    The same three groups the sheet writes, in the same order and by the same
    rules: the portfolio, the audience bands (a partition -- every activity
    carries exactly one, Unknown included), then one group per configured
    breakdown field -- overlapping for the workbook's own fields (an activity
    naming two divisions appears under both, which is why the Calendar sheet
    titles every one of these blocks "multiple values possible" regardless of
    what any particular run's data does), a partition for the two the pack
    adds on top (`PARTITION_BREAKDOWN_FIELDS`) -- an activity has one priority
    and one lead team, never several.

    `overlaps` is the machine-readable form of the sentence the sheet writes
    into its block header. A consumer that adds up an overlapping block gets a
    number larger than the portfolio, and this column is what lets it know
    before it does.
    """
    frame = scope.frame
    yield TOTAL_BLOCK, TOTAL_VALUE, False, frame
    if frame.empty:
        return

    for band in AUDIENCE_BAND_ORDER:
        subset = frame[frame["audience_band"] == band]
        if not subset.empty:
            yield "audience_band", band, False, subset

    for field in config.breakdown_fields:
        if field not in frame.columns:
            continue
        values = {}
        for _, activity in frame.iterrows():
            names = _split_for(field, activity.get(field))
            if not names:
                # A split field carries no catch-all: an activity with nothing
                # on this side of the split is already accounted for by the
                # unsplit field, and a "Not specified" row in both halves would
                # count it twice. The sheet skips it for the same reason.
                if field in SPLIT_FIELDS:
                    continue
                names = [NOT_SPECIFIED]
            # `PARTITION_BREAKDOWN_FIELDS` is a claim, not just a label: every
            # reader of `overlaps=no` is told this block's rows sum to the
            # portfolio. `_split_for` keeps a comma inside these values for
            # exactly that reason -- a team name may carry one -- but the
            # semicolon still separates, so a cell holding two teams would put
            # one activity under both and make the claim false: the exact
            # failure the `overlaps` column exists to catch, arriving from a
            # field that isn't supposed to need it. Caught here, at the one
            # place both `calendar_rows` and `breakdown_rows` derive these
            # values from, rather than shipping a pack whose priority or
            # lead-team total quietly exceeds it.
            if field in PARTITION_BREAKDOWN_FIELDS and len(names) > 1:
                tracking_id = activity.get("tracking_id", "<no tracking_id>")
                raise ValueError(
                    f"{field} is declared in PARTITION_BREAKDOWN_FIELDS, which "
                    f"tells every reader of {BREAKDOWN_NAME} and {CALENDAR_NAME} "
                    f"that this block's rows sum to the portfolio -- a board "
                    f"sums it. Activity {tracking_id!r} breaks that: its {field} "
                    f"value split into {len(names)} values {tuple(names)!r} "
                    f"instead of one. Fix the source value for {tracking_id!r} "
                    f"(a semicolon separates two values here; a comma is read "
                    f"as part of the name), or remove {field!r} from "
                    f"PARTITION_BREAKDOWN_FIELDS if it is genuinely allowed to "
                    f"carry more than one value."
                )
            # Priority is grouped on the source's own text, like every other
            # field here. It used to be folded onto Critical/High/Medium/Low
            # to keep a donut inside the five slices the chart rules cap it
            # at -- a presentation constraint deciding what the data says.
            #
            # The label IS the meaning: a numbered source label names which
            # category of urgency applies, and "High" names only that someone
            # mapped it onto a word the source never uses. The workbook never
            # did this; its Mix sheet prints the source label and orders by
            # `priority_rank`, and the pack was the one instrument answering
            # in a vocabulary nobody could look up. Ordering is `_sort_key`'s
            # job and follows the same rank, so the block still reads from
            # most urgent to least. A chart with more slices than the rules
            # allow is a chart-type problem, not a reason to rename the data.
            for name in names:
                values.setdefault(name, []).append(activity.name)
        overlaps = field not in PARTITION_BREAKDOWN_FIELDS
        for name in sorted(values, key=lambda n: _sort_key(field, n)):
            yield field, name, overlaps, frame.loc[values[name]]


def calendar_rows(scope, config):
    """One row per block x value x week, weeks with no activity left out.

    A zero row would be true but useless: it multiplies the file by the number
    of empty week/value pairs -- on a year and a few dozen values that is most
    of them -- and every one of them competes for the same retrieval budget as
    a row that says something.
    """
    weeks = {week.key: week for week in scope.grid.weeks}
    rows = []
    for block, value, overlaps, subset in iter_blocks(scope, config):
        if subset.empty or "week_index" not in subset.columns:
            continue
        counts = {}
        for index in subset["week_index"]:
            counts[scope.grid.weeks[int(index)].key] = (
                counts.get(scope.grid.weeks[int(index)].key, 0) + 1)
        for key in sorted(counts):
            week = weeks[key]
            rows.append((block, value, "yes" if overlaps else "no",
                         week.iso_year, week.label, week.monday.isoformat(),
                         counts[key]))
    return rows


def _measures(subset):
    """The seven figures a breakdown value carries, in written order."""
    return (
        ("activities", len(subset)),
        ("with_executives", int(subset["has_executives"].sum())),
        ("large_audience",
         int(subset["audience_band"].isin(LARGE_AUDIENCE_BANDS).sum())),
        ("without_pack", metrics.pack_stats(subset)["without_pack"]),
        ("unknown_audience", int((subset["audience_band"] == BAND_UNKNOWN).sum())),
        ("median_completeness", int(subset["completeness"].median())),
        ("short_notice", metrics.lead_time_stats(subset)["short_notice"]),
    )


def breakdown_rows(scope, config):
    """One row per block x value x measure -- the crosses the calendar cannot make.

    `04-calendar.csv` carries one dimension at a time against the weeks, so a
    question crossing two of them -- "which division binds the most executive
    attention" -- can only be answered by counting `05-activities.csv` by hand,
    which the instructions rightly discourage. These are the same blocks, from
    the same `iter_blocks`, with the week dimension traded for a few measures.

    Empty subsets are skipped rather than written as zeros. An empty scope
    yields the TOTAL block over an empty frame, and a median over no rows is
    not a figure at all.
    """
    rows = []
    for block, value, overlaps, subset in iter_blocks(scope, config):
        if subset.empty:
            continue
        suppressed = TAUTOLOGICAL_MEASURES.get(block, ())
        for measure, figure in _measures(subset):
            if measure in suppressed:
                continue
            rows.append((block, value, "yes" if overlaps else "no", measure, figure))
    return rows


PERIODS_HEADER = ("block", "value", "overlaps", "grain", "period", "measure",
                  "figure")

# Quarters carry the count alone. Every measure at quarter grain multiplies
# the file sevenfold to answer questions nobody asks by quarter -- "was
# leadership involvement higher in Q2" is a year-grain question wearing a
# quarter's clothes, and the year grain answers it.
QUARTER_MEASURES = ("activities",)

# Not every block earns a row here. This file's size is decided by how many
# distinct values its blocks carry, multiplied by every year and quarter in
# the data, so the cut is made on cardinality against what the three
# audiences in the reading guide actually ask over time.
#
# `country` is out: unbounded -- it grows with every new market -- and a
# country is a detail behind one question rather than a trend axis.
#
# The combined `executives` block is out, and it is the important one. It
# carries a row per person, the largest of them all, and the question only it
# answers is "which person", which is a snapshot. What the executive audience
# asks over time is whether leadership involvement grew, and that is the
# `with_executives` measure, which every block below already carries. The
# dimension goes; the question stays.
#
# `executives_geb` is in and `executives_geb1` is not: a supplied member list
# splits the field into a small fixed group and everyone else, and only the
# first is a fair trend axis. It appears solely on a run that has the list --
# without one there is no split and no such block, which is the same
# condition the GEB rule in the glossary already follows.
PERIOD_BLOCKS = (TOTAL_BLOCK, "business_division", "region_group", "priority",
                 "lead_team", "executives_geb")


def _ytd_cut(day, cut):
    """Is `day` on or before `cut`'s day-of-year, in whichever year it falls?

    Compared as (month, day) rather than by subtracting dates, so the same
    calendar cut applies to both years. A 29 February cut simply keeps
    everything up to the 29th in a year that has one and up to the 28th in a
    year that does not, which is the behaviour a reader expects and the one
    that cannot silently shift a year's worth of rows.
    """
    return (day.month, day.day) <= (cut.month, cut.day)


def period_rows(scope, config, generated=None):
    """One row per block x value x grain x period x measure.

    The level that was missing. `06-breakdowns.csv` collapses time entirely
    and `04-calendar.csv` is at week grain, so a question comparing two years
    meant summing fifty-odd week rows per value per year -- measured on the
    real agent at over two minutes and repeated timeouts for a single
    priority comparison. These are the same blocks from the same
    `iter_blocks`, cut by period instead of by week.

    Three grains, each earning its place:

    * `year`, with every measure, because the year is the comparison people
      actually make and "did leadership involvement grow" is as common as
      "how many were there".
    * `quarter`, with the count alone -- see `QUARTER_MEASURES`.
    * `ytd`, the current year and the one before it, both cut on the data
      date's day-of-year. This is the only grain the agent cannot derive
      safely: it would have to know the cut and apply it identically to both
      years, and getting it wrong sets a full prior year against a part-year
      and reports a collapse that is an artefact of the cut. The reading
      guide has warned against that comparison all along without offering a
      safe way to make it.
    """
    generated = generated or date.today()
    rows = []
    for block, value, overlaps, subset in iter_blocks(scope, config):
        if block not in PERIOD_BLOCKS or subset.empty:
            continue
        suppressed = TAUTOLOGICAL_MEASURES.get(block, ())
        flag = "yes" if overlaps else "no"
        days = subset["start_day"]

        def emit(grain, period, frame, measures, zero_when_empty=False):
            # An empty subset is skipped everywhere else in this pack, and
            # rightly: a median over no rows is not a figure. The year-to-date
            # pair is the exception, because the comparison IS the file's
            # purpose -- with one side absent an agent cannot tell a year that
            # had nothing from a year the file forgot, and the safest thing it
            # can then say is nothing at all. So the count is written as zero
            # and the other six are still left out.
            if frame.empty:
                if zero_when_empty and "activities" not in suppressed:
                    rows.append((block, value, flag, grain, period,
                                 "activities", 0))
                return
            for measure, figure in _measures(frame):
                if measure in suppressed or measure not in measures:
                    continue
                rows.append((block, value, flag, grain, period, measure, figure))

        every = {name for name, _ in _measures(subset)}
        for year in sorted({day.year for day in days if day == day}):
            emit("year", str(year), subset[[d == d and d.year == year
                                            for d in days]], every)
        for label in sorted({f"{d.year}-Q{(d.month - 1) // 3 + 1}"
                             for d in days if d == d}):
            emit("quarter", label,
                 subset[[d == d and f"{d.year}-Q{(d.month - 1) // 3 + 1}" == label
                         for d in days]], set(QUARTER_MEASURES))
        # Both years, always in the same order, so the pair reads as a pair.
        for year in (generated.year, generated.year - 1):
            emit("ytd", f"{year} YTD",
                 subset[[d == d and d.year == year and _ytd_cut(d, generated)
                         for d in days]], every, zero_when_empty=True)
    return rows


# --------------------------------------------------------------------------
# The prose files
# --------------------------------------------------------------------------

def vintage(generated):
    """The one line that says how old these figures are.

    The pack is rebuilt by hand, on one machine, by one person -- who takes
    holidays. Between two runs every figure here silently ages, and nothing in
    the files said so: the period tells a reader which activities are covered,
    never when anyone last looked.
    """
    return f"Data as of {generated.isoformat()} (CPLAN pack generation date)"


def _summary_sections(scope, config, generated):
    """The Executive Summary's sections, as (title, [(label, value)]) pairs.

    Same order and same figures as `build_executive_summary`, from the same
    `metrics` calls -- the shares are computed here because the sheet's are
    formulas with no cached value.
    """
    frame = scope.frame
    total = len(frame)

    report = list(config.describe())
    report.append(("Data as of", generated.isoformat()))
    report.append(("Weeks covered", len(scope.grid.weeks)))
    # No "Source: <file>" rows, for the reason the workbook dropped them on
    # 2026-08-06 and then some: they name the operator's export files to an
    # audience that has never seen that directory, and this file is uploaded
    # to where that audience reads. A filename carrying a date or someone's
    # initials invites a question the pack cannot answer, and hands an agent a
    # local path to quote. `build_agent_pack.py` logs them to the console, in
    # front of the person who chose them.
    report.append(("Rows read", scope.rows_read))
    for reason in EXCLUSION_ORDER:
        report.append((f"Excluded: {reason}", scope.excluded[reason]))
    report.append(("Activities in scope", total))

    volume = [("Activities in scope", total)]
    for source_type in ("internal", "external"):
        count = int((frame.get("source_type") == source_type).sum()) if total else 0
        volume.append((source_type.title(), count))
    for band in AUDIENCE_BAND_ORDER:
        count = int((frame.get("audience_band") == band).sum()) if total else 0
        volume.append((band, count))

    # Where the plan stands relative to its own generation date. Stated rather
    # than left to be summed out of the calendar: these are headline figures,
    # the pack is retrieved in chunks on both delivery surfaces, and a partial
    # read of forty week rows yields a confident wrong number. A missing figure
    # costs less than a wrong one, and a stated figure costs neither.
    #
    # A partition, not a sample: "no start date" is its own exclusion reason,
    # so every in-scope activity has one and the three counts sum to the total.
    if total:
        starts = frame["start_date"].dt.date
        to_date = int((starts <= generated).sum())
        soon = int(((starts > generated)
                    & (starts <= generated + timedelta(days=30))).sum())
    else:
        to_date = soon = 0
    # "Next 30 days" alone is a claim about today, and a pack that is weeks
    # old by the time anyone reads it is not describing today: the label has
    # to carry its own anchor so a reader (or an agent quoting only this
    # tile) is not told a mostly-elapsed window is still ahead. "Planned to
    # date" and "Rest of the period" do not have the same failure -- neither
    # implies a window starting now -- so only this one is renamed.
    horizon = [
        ("Planned to date", to_date),
        ("Next 30 days from the data date", soon),
        ("Rest of the period", total - to_date - soon),
    ]

    stats = metrics.load_stats(scope)
    load = [
        ("Median activities per week", stats["median_per_week"]),
        ("Peak week", stats["peak_week_label"]),
        ("Activities in the peak week", stats["peak_week_count"]),
        ("Weeks with no activity", stats["zero_weeks"]),
        ("Longest run of empty weeks", stats["longest_zero_run"]),
        ("Share in the five busiest weeks", f"{stats['top5_share']:.0%}"),
    ]

    executives = int(frame["has_executives"].sum()) if total else 0
    large = int(frame["audience_band"].isin(LARGE_AUDIENCE_BANDS).sum()) if total else 0
    leadership = [("With GEB/GEB-1 involvement", executives)]
    if scope.membership is not None:
        # The workbook prints this as a sub-row indented under the line above.
        # Indentation is exactly what this file may not rely on -- a chunked
        # read can keep this line and lose its parent -- so the relationship
        # goes into the label instead.
        #
        # No GEB-1 line beside it, and not as an oversight: an activity can
        # name people at both levels, so a GEB and a GEB-1 count would not
        # partition the line above, and a reader subtracting one from it would
        # get a number that means nothing. The rosters in the breakdowns
        # answer "who", and that is where the second half belongs.
        geb = int((frame["executives_geb"] != "").sum()) if total else 0
        leadership.append(
            ("With GEB involvement (a subset of GEB/GEB-1 involvement)", geb))
    leadership.append(("Large audience (top two bands)", large))

    lead = metrics.lead_time_stats(frame) if total else {
        "counted": 0, "median_days": None, "short_notice": 0}
    discipline = [
        ("Median lead time (days)",
         lead["median_days"] if lead["median_days"] is not None else "not measurable"),
        (f"Planned at under {SHORT_NOTICE_DAYS} days' notice", lead["short_notice"]),
        ("Lead time not measurable", total - lead["counted"]),
    ]

    packs = metrics.pack_stats(frame) if total else {"without_pack": 0}
    quality = [
        ("Median planning completeness (%)",
         int(frame["completeness"].median()) if total else 0),
        ("Without a pack link", packs["without_pack"]),
    ]

    return [
        ("REPORT", report),
        ("VOLUME", volume),
        ("HORIZON", horizon),
        ("LOAD", load),
        ("LEADERSHIP AND AUDIENCE", leadership),
        ("PLANNING DISCIPLINE", discipline),
        ("DATA QUALITY", quality),
    ]


def _wider_than_the_report(scope, report_config):
    """The lines that own up to the pack and the workbook disagreeing.

    They disagree by construction: the pack drops two of the report's filters
    so that a question about the deprioritised bucket has an answer. Two
    artefacts with one name and two totals is the failure mode this repository
    spends most of its rules preventing, and the only thing that makes it
    survivable is saying so where nobody can miss it -- with the count, the
    reasons, and the column that reproduces the workbook's figure.
    """
    if not report_config:
        return []
    counts = {}
    for _, activity in scope.frame.iterrows():
        reason = report_exclusion(activity, report_config)
        if reason:
            counts[reason] = counts.get(reason, 0) + 1
    extra = sum(counts.values())
    lines = _rule(
        "THIS PACK IS WIDER THAN THE DISTRIBUTED WORKBOOK. The workbook plans, "
        "and leaves out what nobody plans against; this pack answers questions, "
        f"and leaves it in. The workbook does not contain {extra} of the "
        "activities counted here.")
    if counts:
        lines.append("")
        for reason in sorted(counts):
            lines.append(f"  Kept here, dropped by the workbook - {reason}: "
                         f"{counts[reason]}")
    lines += _rule(
        "Every row in the activities file carries `in_report` (Yes/No) and "
        "`report_exclusion`. Counting only `in_report = Yes` reproduces the "
        "workbook's figures exactly. Quote the full count unless the question "
        "is about the workbook, and say which of the two you used whenever the "
        "difference could matter.")
    return lines


def summary_text(scope, config, generated=None, report_config=None):
    generated = generated or date.today()
    total = len(scope.frame)
    lines = [
        "CPLAN REPORT - EXECUTIVE SUMMARY",
        "",
        f"Period covered: {config.period_label()}. Every figure is a count of "
        "activities.",
        "",
        vintage(generated) + ". Activities entered in the source system after "
        "that date are not represented here.",
    ]
    lines += _rule(
        "Scope is a hard filter. An activity that fails any criterion in REPORT "
        "below is absent from every figure in this pack, so a question about a "
        "date outside the period is OUT OF SCOPE -- not zero.")
    lines += _wider_than_the_report(scope, report_config)
    for title, rows in _summary_sections(scope, config, generated):
        lines += ["", title, "-" * len(title)]
        for label, value in rows:
            share = ""
            if (title == "VOLUME" and total and isinstance(value, int)
                    and label != "Activities in scope"):
                share = f"  ({value / total:.0%} of the {total} in scope)"
            lines.append(f"  {label}: {value}{share}")
    lines.append("")
    return "\n".join(lines)


def glossary_text(scope, config):
    """The workbook's glossary, plus the rules it states only by layout.

    The definitions come from the workbook's own `_glossary_sections` rather
    than being written again here: that wording is already vetted and under a
    hard length cap, and a second copy could only drift. Going through the
    function rather than the constant is what gives the pack the `GEB` term on
    a membership build -- the workbook prints it there, and a pack that defined
    fewer terms than the sheet it mirrors would be answering the same question
    two ways.
    """
    lines = ["CPLAN - HOW TO READ THIS DATA", "",
             "Read this before answering anything from the other files."]
    for title, terms in _glossary_sections(scope):
        lines += ["", title, "-" * len(title)]
        for term, definition in terms:
            lines.append(f"  {term}: {definition}")
    if scope.skipped_completeness_fields:
        lines += ["", "FIELDS NOT IN THIS EXPORT", "-" * 24]
        for name in scope.skipped_completeness_fields:
            lines.append(f"  {name}: not in the export, so not counted.")

    title = "RULES THE WORKBOOK STATES ONLY BY LAYOUT"
    lines += ["", title, "-" * len(title)]
    for rule in (
        "Scope is an overlap test, not a start-date test. An activity whose run "
        "touches the period is in scope even when it starts before it, so a "
        "report for one year legitimately contains activities whose quarter or "
        "ISO week names the year before: those columns label the START, and the "
        "start may lie outside the period. That is not a data error, and it "
        "does not need reviewing.",
        f"Overlapping rows do not sum. In {CALENDAR_NAME} a row with "
        "overlaps=yes belongs to a block where an activity naming two values "
        f"appears under both. block={TOTAL_BLOCK} is the portfolio, and an "
        "overlaps=no block -- priority or lead_team, for instance -- sums to "
        "it just the same; only an overlapping block does not.",
        f"Only counts answer \"how many\". In {BREAKDOWN_NAME}, "
        "measure=median_completeness is a median per value: it does not "
        "combine, on an overlapping block or a partitioning one. The overlap "
        "rule above is about a different mistake and does not cover this one.",
        f"{BREAKDOWN_NAME} states a measure only where it can vary. A measure "
        "that would restate its own block -- the unknown-audience count inside "
        "the Unknown band, executive involvement inside an executive block -- "
        "is not written. Its absence is not a zero.",
        "Audience is a planning estimate, never measured reach. CPLAN holds no "
        "measured reach at all. Summing it counts contacts, not people: one "
        "person inside six activities counts six times. The largest single "
        "audience is the ceiling on unique people.",
        "Archived activities are included. Archiving is a list-size workaround "
        "in the source system, not a relevance signal, so an archived activity "
        "is not an obsolete one.",
        "A weekly count places each activity once, in the week it starts. A "
        "six-week campaign is one activity in one week, not six.",
        "channel and target_audience hold several values in one string. A value "
        'like "Email, Intranet" is one combination, not one channel.',
        geb_rule(scope),
        f"{ACTIVITIES_CSV_NAME} is the full row set. If you answer a counting "
        "question from it, state how many rows you actually examined -- and if "
        "you cannot see every row, say so instead of estimating.",
    ):
        lines.append(f"  - {rule}")
    lines.append("")
    return "\n".join(lines)


def data_quality_text(scope, config):
    lines = ["CPLAN REPORT - DATA QUALITY", "",
             f"Period covered: {config.period_label()}."]

    total = len(scope.frame)
    lines += ["", "FIELD COMPLETENESS", "-" * 18,
              "  field | filled | missing | % missing"]
    for name, filled, missing in metrics.field_completeness(scope):
        share = f"{missing / total:.0%}" if total else "0%"
        lines.append(f"  {name} | {filled} | {missing} | {share}")

    packs = metrics.pack_stats(scope.frame) if total else {}
    lines += ["", "PACK COVERAGE", "-" * 13, "  measure | count"]
    for label, key in (("With a pack link", "with_pack"),
                       ("Without a pack link", "without_pack"),
                       ("Distinct packs", "packs"),
                       ("Packs holding one activity", "singleton_packs"),
                       ("Packs holding 2-10", "small_packs"),
                       ("Packs holding 11-50", "medium_packs"),
                       ("Packs holding more than 50", "oversized_packs"),
                       ("Largest pack", "largest_pack")):
        lines.append(f"  {label} | {packs.get(key, 0)}")

    # Only once a list exists: what it says should exist, versus what an
    # activity happened to name above. "Distinct packs" is not restated here
    # -- it is three lines up in this same section -- so the two counts sit
    # close enough for a reader to notice the gap between them without either
    # being duplicated.
    if scope.packs is not None:
        in_scope_counts = packs_module.activity_counts(scope.frame, scope.packs)
        # A pack whose in-scope count is zero has nothing counted through it
        # this period -- not necessarily nothing ever, activities_total in
        # 07-packs.csv says that.
        no_activity_in_scope = sum(
            1 for _, pack in scope.packs.iterrows()
            if not in_scope_counts.get(packs_module.key(pack.get("cpid")), 0))
        # Only "No" -- a broken reference -- counts here. An empty
        # `pack_known` is an activity that names no pack at all, which is
        # ordinary and not this figure's business; folding it in would report
        # a data problem that does not exist.
        unmatched = (int((scope.frame["pack_known"] == "No").sum())
                    if "pack_known" in scope.frame.columns else 0)
        lines.append(f"  Packs in the list | {len(scope.packs)}")
        lines.append(f"  Packs with no activity in scope | {no_activity_in_scope}")
        lines.append(f"  Activities whose pack is not in the list | {unmatched}")

    lines += ["", "RECORD ANOMALIES", "-" * 16, "  anomaly | count"]
    for label, count in metrics.anomalies(scope.frame, scope.duplicates_removed):
        lines.append(f"  {label} | {count}")

    # Its own section, as on the Data Quality sheet, and only on a membership
    # build -- these two figures are about the list, not about the export, and
    # a machine with no list has no measurement to report.
    #
    # The unmatched count is the only thing that tells a typo apart from a real
    # GEB-1 person: both put someone under GEB-1, and only this side can see
    # that a configured entry matched nothing at all.
    if scope.membership is not None:
        lines += ["", "GEB LIST", "-" * 8, "  measure | count",
                  f"  GEB list entries | {len(scope.membership)}",
                  f"  GEB list entries never matched | {scope.unmatched_members}"]
    lines.append("")
    return "\n".join(lines)


def readme_text(scope, config, activity_rows, generated):
    # The table of contents follows the folder, exactly as the figures above it
    # follow the run. `write_pack` writes the pack file only where a pack list
    # was synced, so naming it unconditionally would send a reader looking for
    # a file that is not there -- the failure `06-breakdowns.csv` caused once
    # in the other direction, when the file shipped and no table of contents
    # mentioned it.
    packs_entry = (f"\n  {PACKS_CSV_NAME}         one row per pack, "
                   "including the ones with nothing planned against them"
                   if scope.packs is not None else "")
    return f"""CPLAN AGENT PACK

Machine-readable companion to the CPLAN calendar workbook. Same pipeline run
and the same figures for what both cover -- but a wider scope: the workbook
plans and leaves out what nobody plans against, this pack answers questions and
keeps it. See `in_report` in the activities file.

Period covered: {config.period_label()}
Activities in scope: {len(scope.frame)}
{vintage(generated)}

The pack is rebuilt by hand rather than on a schedule, so this date is the one
figure here that no other file can imply. Say it in every answer, and treat
anything entered in the source system after it as not represented.

  {README_NAME}        this file
  {GLOSSARY_NAME}      definitions and reading rules - READ FIRST
  {SUMMARY_NAME}       portfolio figures: volume, load, lead time, leadership
  {QUALITY_NAME}  completeness, pack coverage and record anomalies
  {CALENDAR_NAME}      one row per block x value x week
  {BREAKDOWN_NAME}    one row per block x value x measure - the crosses the calendar cannot make
  {ACTIVITIES_CSV_NAME}    one row per activity, {activity_rows} rows{packs_entry}
  {PERIODS_CSV_NAME}      the same blocks by year, quarter and year-to-date

Figures here are computed, not spreadsheet formulas. Percentages are of the
in-scope total unless the line says otherwise.

Prefer {SUMMARY_NAME}, {CALENDAR_NAME}, {BREAKDOWN_NAME} and
{PERIODS_CSV_NAME} for any counting question: those figures were computed
by tested code. A figure derived from
{ACTIVITIES_CSV_NAME} has not been through the report's rules.

The rules this data does not survive without are in {GLOSSARY_NAME}, stated
once and only there. Read it before answering anything from the other files.
"""


# The visual rules that are only needed when something is actually drawn.
#
# The split is not by subject but by cost of being missed. The palette, the
# red-to-white ratio and the typography rules stay in the instructions: a
# capitalised heading or a red KPI number is wrong on sight, on every chart,
# and instructions apply to every turn. What lives here is the half that only
# matters once a plot exists -- chart type per question, panel geometry, the
# self-check -- and that half is long enough to crowd out the rest of the
# prompt if it were carried on every turn.
#
# A skill loads when the model judges it relevant, so the description below is
# the whole retrieval mechanism and is written as a list of trigger scenarios
# rather than a topic. The instructions name this skill in the same breath as
# the report pack, which is the phrasing observed to make a load happen even
# on a turn whose subject is unrelated.
#
# No organisation name anywhere: this text ships inside a zip that the operator
# uploads unmodified, so a placeholder here could not be filled in the way the
# instructions file's one is.
BRAND_SKILL_NAME = "chart-standards"
BRAND_SKILL_TEXT = """---
name: chart-standards
description: The visual standards for anything this agent draws - charts, dashboards, diagrams, executive images. Covers which chart type answers which question, axis and legend mechanics, multi-panel layout and spacing, and the checklist to read an image against before sending it. Load whenever a request asks to show, plot, chart, graph, map, visualise or compare something, whenever a dashboard or an executive image is wanted, and whenever an answer would land better as a picture than as a sentence.
---

# Chart standards

The palette, the red-to-white ratio and the typography rules are in your
instructions and apply whether or not you load this skill. What follows is the
rest: the part that only matters once something is actually being drawn.

## Which chart answers which question

| The question is about | Use | Typical case |
|---|---|---|
| Change over time | Line chart, or column chart for few periods | Activities over time; participation over time |
| Comparing named things | Horizontal bar chart, sorted by value | Division performance; region distribution |
| Parts of a whole | Stacked bar; donut only at five categories or fewer | Channel mix; audience mix |
| Spread and outliers | Scatter plot, or a bar chart with the outlier annotated | Planning lead time; event concentration |

## Colouring the two kinds of chart

The first two rows above and the last one are **comparisons**: one thing is the
answer. Draw the series in Grey IV `#7A7870` and give that one thing — the
tallest bar, the peak, the outlier — Corporate Red `#E60000`.

The third row is **composition**: the categories are peers and the shape of
the split is the answer, so there is nothing to single out. Take the segments
in this order and leave red out of it entirely:

`#404040` · `#B98E2C` · `#8E8D83` · `#6C5312` · `#B8B3A2` · `#5A5D5C` · `#946F29`

Dark grey, bronze, mid grey, dark bronze, light grey, grey, bronze again —
enough separation for seven segments without a brand colour competing with the
data. Above seven, the categories are too many for a donut before they are too
many for the palette: group the tail into "Other" and say how many it holds.

That list is the order of the colours, not permission to reorder the
categories. The segments keep the order the data has — an urgency, a size, a
band order — running clockwise from twelve o'clock, and a mix chart whose
levels arrive shuffled has lost the one thing the reader came to read off it.

Red enters a composition chart only when one named segment *is* the question —
"how much of the plan is share-price-sensitive?" makes that segment the answer
and the rest context. "How does this split by priority?" does not. Even then
your instructions' area rule applies: a segment that is already the largest is
carrying the message by size, and colouring it too says nothing new.

## Axes, lines and legends

- Drop the y-axis when every bar carries its own data label. Keep it for line
  charts, where the reader is reading a slope rather than a value.
- Average or reference line: Grey V `#5A5D5C`, dashed, labelled inline —
  `Average = 1,050`, not a legend entry.
- Prefer a donut with a large white centre to a pie. Avoid both above five
  categories.
- Label directly wherever the count allows. At five categories or fewer, write
  each name and its value beside the segment, bar or line end it belongs to and
  draw no legend at all: a legend makes the reader carry a colour across the
  panel and back for something the label could have said in place.
- Where a legend is unavoidable — several charts sharing one set of categories
  — draw one legend for the image rather than one per chart, square swatches
  with text to the right, and place it outside every plot area. A legend laid
  over a donut hides the shape the donut exists to show.
- Sort bars by value unless the categories have their own order (weeks,
  quarters, audience bands). An unsorted bar chart makes the reader do the
  ranking you were supposed to do.

## Laying out more than one chart

A single chart fails by being wrong. An image holding six fails at the seams,
and that is a different discipline.

- **Cut the canvas into panel rectangles first, then fill them.** Every part of
  a panel is placed against its own rectangle, never against the whole image. A
  heading given an image coordinate does not know which panel it landed in: on
  the 2026-08-10 test render one panel's heading, its question, its chart and
  its legend were all drawn across the category labels of the panel beside it,
  while its own rectangle stood empty.
- **A panel is one block**: heading, business question, plot, footnote. Reserve
  the vertical space for all four *before* drawing the plot. A footnote added
  afterwards lands in the panel underneath — this is the single most common way
  these images break.
- **A heading and the line beneath it are two lines.** Reserve a full line for
  each, descenders included. A business question set at a guessed offset from
  its heading is written across the heading's own tails, and the board title
  fails this first because its type is the largest on the image.
- **A horizontal bar panel is as wide as its longest category name.** Names sit
  outside the plot area and grow outwards into whatever is beside them, so
  measure the longest one and give the panel the width it needs. If the width
  is not available, shorten the names and say in the footnote that you did — a
  name is never clipped, and never travels into a neighbour.
- **Leave a gutter at least as tall as a panel heading** between panels, both
  horizontally and vertically. Nothing is ever drawn inside a gutter, including
  an axis label that happens to be long.
- **Nothing overlaps anything.** An annotation sits inside its own plot area,
  clear of the axis labels below it and the subtitle above it. If a peak label
  will not fit above the peak, put it beside the peak.
- **Align the row.** Panels in a row share a top edge and a plot height, and
  their axes line up.
- **Number tiles align on the baseline of their numbers**, not on the centre of
  their boxes. A caption wrapping to two lines must not push its number up, or
  the row of figures reads as a staircase.
- **Every annotation carries its value.** A divider labelled `data as of` says
  nothing. `data as of <date>` says the thing.

Your instructions carry one more layout rule, under "Say each figure once": a
panel that restates what its neighbour already gives is a panel to drop, and
the white space left behind is worth more than the repetition. It is checked
below rather than repeated here.

## Before you send it

This list is what a reader does to the image in its first five seconds. On most
surfaces you cannot see what you have drawn, so it is not an inspection you can
carry out afterwards — which is why everything above is written as a rule for
building the image rather than for judging it. Check what can be checked while
drawing: measure the text, let the layout engine fit the panels, and place
nothing at an offset you guessed. Fix what fails; do not caption it.

1. Does any text touch or overlap other text, a bar, an axis label, or a
   neighbouring panel?
2. Is there more than one red element in a chart, or more than two in the whole
   image? Is red covering the largest area, or sitting on a donut or stacked
   bar that has nothing to single out?
3. Any capitals used for emphasis, any underline, any coloured text?
4. Any gridlines, rounded corners, shadows, or a colour outside the palette?
5. Is at least half the image white?
6. Does every panel carry its heading, business question and source footnote,
   with none of them sitting in a neighbour's space? Where it states a total,
   does the footnote say what that total counts? An image is forwarded without
   its author, and there is nobody in it to ask which of two true totals it
   meant.
7. Does any figure appear twice in the image?
8. Does the image close with the footer line your instructions require — the
   data vintage and the signature? An image travels further than the answer it
   came with, and it is the copy that arrives without a date.

An image failing one of these is redrawn, not explained.
"""


# SKILL.md, in the two shapes the archive is really built in.
#
# Two renderings rather than one text with a hedge in it, for the reason
# `geb_rule` already gives: this file ships inside the archive and is rebuilt
# with every run, so it can state what the archive actually holds. Prose that
# travels with the data follows the data; prose that is pasted once and left
# behind -- the instructions, on both surfaces -- describes both states,
# because it cannot follow anything.
#
# A routing table row naming a file the archive does not carry is the worse
# half of that. The agent looks, fails, and answers from whichever row looked
# closest, and the pack file is the one row whose questions nothing else can
# answer.
#
# The count sentence is written out twice rather than interpolated, so both
# numbers are legible in the source next to the table they have to agree with.
# `tests/test_agent_pack.py` derives both sides of that agreement from each
# rendering at run time.
_SKILL_HEAD = """---
name: cplan-reporting
description: Answers questions about the CPLAN communication plan - volumes, timing, leadership involvement, planning quality - from the report pack in this skill. Use for any question about planned communication activities, packs, channels, audiences, leads or planning gaps.
---

# CPLAN reporting
"""

_SKILL_INTRO_WITH_PACKS = """
You answer questions about a communication plan from seven files shipped with
this skill. They come from one pipeline run: same figures, same scope.
"""

_SKILL_INTRO_WITHOUT_PACKS = """
You answer questions about a communication plan from six files shipped with
this skill. They come from one pipeline run: same figures, same scope.
"""

_SKILL_ROUTING = f"""
## Which file answers what

| Question | File |
|---|---|
| Totals, load, lead time, leadership involvement | `{SUMMARY_NAME}` |
| Completeness, pack coverage, anomalies | `{QUALITY_NAME}` |
| Volume over time by any dimension | `{CALENDAR_NAME}` |
| Any figure crossing two dimensions | `{BREAKDOWN_NAME}` |
| A single named activity | `{ACTIVITIES_CSV_NAME}` |
| Any comparison of periods: year over year, quarters, year to date | `{PERIODS_CSV_NAME}` |
"""

_SKILL_PACK_ROUTING = f"""\
| Per-pack detail, or which packs have nothing planned | `{PACKS_CSV_NAME}` |

- `{PACKS_CSV_NAME}` — one row per communication pack: name, lead, period,
  objective, and how many activities sit in it. Every pack is here, including
  those with nothing planned against them (`activities_in_scope = 0`), which
  is the only place that fact appears. Join it to `{ACTIVITIES_CSV_NAME}` on
  `Pack ID`, which every activity row carries beside `pack_known`.
"""

_SKILL_BODY = f"""
Prefer `{SUMMARY_NAME}`, `{CALENDAR_NAME}` and `{BREAKDOWN_NAME}` for any
counting question. Those figures were computed by tested code. A number you
derive yourself from `{ACTIVITIES_CSV_NAME}` has not been through the report's
rules.

## Rules you must not break

Read `{GLOSSARY_NAME}` first. It carries the definitions and the ten rules
this data does not survive without, and the two that cost the most are:

**Scope is a hard filter, and an overlap test.** The period is named at the top
of `{SUMMARY_NAME}`. An activity outside it is absent from every file here, so a
question about a date outside the period is OUT OF SCOPE -- never answer it with
zero. An activity whose run merely touches the period IS in scope, so a quarter
or ISO week naming the year before the period is normal, not an anomaly: those
columns label the start, and the start may lie outside.

**Overlapping rows do not sum.** In `{CALENDAR_NAME}`, a row with
`overlaps=yes` belongs to a block where one activity can appear under two
values. Adding such a block up gives a number larger than the portfolio.
`block={TOTAL_BLOCK}` is the portfolio, and any `overlaps=no` block -- priority
and lead_team included -- sums to it too; only an overlapping block does not.

## When you count from `{ACTIVITIES_CSV_NAME}`

State how many rows you examined, every time. If you cannot see every row, say
so plainly instead of estimating. A count from part of the file is not an
answer - it is a guess wearing a number.

## Name a row, cite its identifier

Every time you name an activity, a pack or a cluster - in a sentence, in a
table, in a list of forty - give its identifier beside the name. Activities
carry `Tracking ID`, packs carry `Pack ID`, and both carry `Cluster ID`.

A name is not unique and cannot be looked up. Two activities can be called
"Q3 town hall"; nobody can find either of them in the planning system from
that name, and a list of forty names is a list nobody can act on. The
identifier is what makes an answer usable after the conversation ends.

## When to stop

If the answer is not in these files, say so and point the user at the planning
studio. Do not reason your way to a plausible figure: in this domain a wrong
number costs more than a missing one.

## Who is asking

Three audiences use this data, and the same figure serves them differently.

**Internal communications planner** — clashes, overload, channel use, audience
saturation by planned size, lead times, regional coordination. Answer three
things: what happened, where the conflicts are, what to review.

**Communication executive** — themes, executive participation (GEB or GEB-1;
separated only where the pack carries an `executives_geb` block, and then only
because a member list was supplied), division activity, planned audience size
(never described as reach), concentration. Keep it short: summary, key risks,
top opportunities.

**Analytics** — method, calculation, segmentation, trend, transparency.
Include definitions, assumptions and limitations.

## How to work through an analysis

1. **Describe** what the data shows — by month, by division, by region.
2. **Identify patterns**, but only ones the data supports: concentration,
   growth, decline, seasonality, uneven distribution. Name the two windows you
   are comparing, and never set a settled quarter against one still being
   filled in. Forward planning thins towards the end of the horizon, so the
   last quarter in scope reads as a collapse when it is merely not yet written.
3. **Identify outliers** — unusually high or low activity, high executive
   participation, exceptional lead times. Show exact figures.
4. **Recommend next review areas**, phrased as "Consider reviewing…" rather
   than "This happened because…" unless the evidence is there.

## What this pack answers well

Use these when you need a follow-up worth offering, or when a question is too
vague to answer as asked.

*Planners* — Which weeks have the highest volume? Where are audience overlaps
occurring? Which divisions cluster on the same dates? Which channels are
overused?

*Executives* — What are the most common themes? Which divisions drive the
highest activity? How much executive participation is recorded? Where are the
gaps?

*Analytics* — Activity distribution by quarter. Regional concentration.
Audience segmentation. Channel proxy metrics. Lead-time distribution.
"""


def skill_text(with_packs):
    """SKILL.md for the archive that is about to be written, not for both.

    `with_packs` is read off the pack directory by `_write_skill_zip`, from
    the same `.exists()` call that decides whether the file goes in -- so the
    routing table and the payload cannot disagree, whatever a future caller
    does.
    """
    intro = _SKILL_INTRO_WITH_PACKS if with_packs else _SKILL_INTRO_WITHOUT_PACKS
    routing = _SKILL_ROUTING + (_SKILL_PACK_ROUTING if with_packs else "")
    return _SKILL_HEAD + intro + routing + _SKILL_BODY


# The packed rendering, for everything that wants the text without a run
# behind it. The archive itself always goes through `skill_text`.
SKILL_TEXT = skill_text(True)


# The agent's complete instructions, not an addendum: the whole of what was in
# place is known, and the corrections are woven through it rather than bolted
# after it -- a rule contradicted three sections above it does not hold just
# because a later paragraph is right.
#
# Kept at agent level rather than only in SKILL.md because a skill is SELECTED
# when the orchestrator judges it relevant, while instructions apply to every
# turn: a turn the skill misses is otherwise a turn with no rules at all.
#
# Organisation-neutral by force. This repository is public, so the name and the
# palette live in a placeholder here and are filled in on the machine that
# pastes the text. `tests/test_agent_pack.py` fails if a name creeps back in.
#
# Carries no period and no figures either. It is pasted into a field once and
# stays there while the pack is rebuilt underneath it; a period named here
# would be wrong by the next run, in the one place nobody re-reads.
ORGANISATION_PLACEHOLDER = "<ORGANISATION>"

# Literal, not a placeholder, and deliberately so: 2322df5 signed the portal,
# the project page and the studio with this one name, and the manifest entry
# for it says why -- a mark on one surface is not a brand. The agent is the
# fourth surface. It is the team's own name rather than the organisation's,
# which is the line this repository draws.
TEAM_SIGNATURE = "ECC Measurement & Insights"

INSTRUCTIONS_TEXT = """<!-- Before pasting, replace throughout:
       <ORGANISATION>  your organisation's name (brand and chart sections)
     One find-and-replace. This file ships through a public repository, so
     the organisation's name lives on your machine and not in its history. -->

You are the Communications Planning Insight Agent.

Your purpose is to answer questions about communications planning activity using only the CPLAN report pack supplied by the `cplan-reporting` skill. Your outputs must help Internal Communication Planners, Communication Executives, and Analytics teams make better decisions.

That skill also carries how to read for each audience, the four analysis steps, and the questions this pack answers well. The rules below are what holds whether or not it loads.

Anything you draw — a chart, a dashboard, an image — follows the visual standards supplied by the `chart-standards` skill. Load that skill before you draw, every time, the same way you load the report pack before you answer.

When a dashboard, a board or a one-page executive overview is asked for, load the `cplan-dashboards` skill as well. It names the three boards this agent draws and fixes each one's panels, so the layout is not decided again per request. If no board is named, say which three exist and ask — a blended board answers none of the three decisions.

The pack contains:

- `01-summary.txt` — portfolio figures: volume, load, lead time, leadership involvement
- `02-glossary.txt` — definitions and reading rules. Read this first.
- `03-data-quality.txt` — completeness, pack coverage, record anomalies
- `04-calendar.csv` — one row per block × value × week
- `06-breakdowns.csv` — one row per block × value × measure. The crosses `04-calendar.csv` cannot make: activities, leadership involvement, large audiences, missing pack links, unknown audience and median completeness, per division, region, country and audience band
- `05-activities.csv` — one row per activity

There is no Excel workbook behind this agent. Prefer `01-summary.txt`, `04-calendar.csv` and `06-breakdowns.csv` for any figure they already state: those were computed by tested code. A figure you derive yourself from `05-activities.csv` has not been through the report's rules.

## Non-Negotiable Rules

### 1. Evidence First

Every conclusion must be traceable to the dataset.

Never invent causes, trends, explanations, benchmarks, forecasts, or recommendations.

If the data does not support a conclusion, explicitly state:
"The dataset does not contain sufficient evidence to answer this question."

Separate:
- Facts from the data
- Interpretation
- Suggested actions

### 2. Quantify Everything

Whenever possible report:
- Count
- Percentage
- Change vs. comparison group
- Sample size

Example:
Correct: "74 activities were planned in Q3, representing 22% of all recorded activities."
Incorrect: "Q3 was very active."

### 3. Explain How Results Were Calculated

For every insight include:
- Fields used
- Filters applied
- Date range
- Calculation logic

Example: Based on Activity Date grouped by Quarter and counted by Activity ID.

When you count over `05-activities.csv`, also state how many rows you examined. If you cannot see every row, say so instead of estimating.

### 4. Surface Data Quality Issues

Before answering, check for:
- Missing values
- Duplicates
- Empty categories
- Invalid dates
- Inconsistent naming

Always flag issues that may affect interpretation.

Do NOT flag the following, which are the report working as designed:
- A quarter or ISO week naming the year before the reporting period. Scope is an overlap test: an activity that starts earlier and runs into the period belongs in it, and those columns label the start.
- Archived activities being included. Archiving is a list-size workaround in the source system, not a relevance signal.

### 5. CPLAN Data Rules

These come from the data rather than from good reporting practice, and they override general analytical instinct.

- **Scope is a hard filter.** The period is named at the top of `01-summary.txt`. An activity outside it is absent from the pack, not zero — a question about a date outside the period is out of scope, not an answer of nought.
- **Overlapping rows do not sum.** In `04-calendar.csv`, a row marked `overlaps=yes` sits in a block where one activity can appear under two values (two divisions, two regions). Adding such a block up gives a number larger than the portfolio. `block=TOTAL` is the portfolio, and any `overlaps=no` block -- priority and lead_team included -- sums to it too; only an overlapping block does not.
- **Audience is a planning estimate, never measured reach.** CPLAN holds no measured reach at all. Summing audience counts contacts, not people — one person inside six activities counts six times. Quote the largest single audience as the ceiling on unique people, and never call any of it "reach".
- **GEB/GEB-1 is one field holding both levels**, and the source data never says which. Look at the blocks the pack actually carries before you answer. Where it carries `executives_geb` and `executives_geb1`, a GEB member list was supplied when the pack was built: that list is the only thing separating the two, so name it as the source, and never add the two blocks together — one activity naming people at both levels counts in both. Where it carries only `executives`, nothing separates them: never name someone as a GEB member, and never answer "how many activities involve the GEB" — the honest answer is "GEB or GEB-1".
- **`channel` and `target_audience` hold several values in one string.** A value like "Email, Intranet" is one combination, not one channel.
- **Weekly counts place each activity once, in the week it starts.** A six-week campaign is one activity in one week, not six.
- **This pack is wider than the distributed workbook.** It keeps activities the report leaves out — the deprioritised bucket, and rows tagged with nothing but the catch-all objective — so that a question about them has an answer. Every row in `05-activities.csv` carries `in_report` (Yes/No) and `report_exclusion`; counting only `in_report = Yes` reproduces the workbook exactly. `01-summary.txt` states how many rows the difference covers.
- **Quote the full count, and name which one you used** whenever someone might be holding the workbook — a total that silently disagrees with the document in the reader's hand costs more than the extra clause. If a figure is questioned, give both: "1,385 in the plan; 1,362 in the report, which leaves out 23 deprioritised."
- **When the answer is not in the pack**, say so and point to the planning studio, which holds the full record and can filter it. Do not reason your way to a figure.

## Visualization Instructions

A chart is the part of an answer a reader screenshots and forwards, so it
carries the brand further than the prose does. What follows is the
organisation's design system restated so this agent can follow it without
having the style guide to hand. Where a rule gives a number, the number is the
rule: "sparingly", "clean" and "minimal clutter" have never survived a render.

### <ORGANISATION> brand compliance — the palette

Use these values and no others. Do not sample a colour from a template, do not
let a plotting library choose its own defaults, and do not invent a shade
because two bars ended up side by side.

| Role | Hex | What it is for |
|---|---|---|
| White | `#FFFFFF` | Every background, and the dominant colour of every image |
| Black | `#000000` | Body text, axis line, rules, data labels |
| Accent red | `#E60000` | The one highlighted element — nothing else |
| Grey III | `#8E8D83` | Lighter series, secondary bars |
| Grey IV | `#7A7870` | The default series colour, and footnote text |
| Grey V | `#5A5D5C` | Average and reference lines |
| Grey VI | `#404040` | The darkest series, dark fills |
| Bordeaux I | `#BD000C` | A second red where red genuinely must appear twice |
| Bronze I | `#B98E2C` | A third series once grey and red are taken |
| Pastel I | `#ECEBE4` | Tile and panel fills, highlight blocks, alternate table rows |

The greys are warm, not neutral. A cool grey — `#808080`, `#999999`, a library
default — is off-brand even though it reads as grey on screen. Pure black is
for type and rules, not for filling bars.

Status colours are for data-driven status only, never decoration: red
`#BD000C`, amber `#E4A911`, green `#6F7A1A`.

### How much of each — the ratio

White dominates, greys carry the data, red is an accent. In numbers:

- **At least half the image is unmarked white.** Margins, gutters and the
  space around type count towards it; a filled panel background does not.
- **One red element per chart. At most two in a whole image.** The red element
  is the answer to that chart's business question — the tallest bar, the peak,
  the segment under discussion. Two red bars make the reader work out which
  one was meant, and at that point the accent has stopped accenting.
- **Red never covers the largest area in the image.** Counting elements is not
  enough: one segment of a donut can be half the picture, and half a picture
  in red is not an accent whatever the count says. If the thing you would
  highlight is already the biggest, leave it grey — the eye lands there
  anyway, and red spends the whole page saying what the size already said.
- **Highlight only where one thing is the answer.** That is a comparison: a
  ranked bar chart, a line with a peak. Where the categories are peers and the
  distribution itself is the answer — a donut, a stacked bar, a share split —
  nothing is highlighted and the whole chart is neutral.
- **Everything else is grey.** A bar chart is grey bars with one red bar. A
  line chart is a Grey IV line with one red marker at the point being
  discussed, not a red marker on every point.
- Do not fill a tile, a header band or a panel with red.

### Typography

- **Never use capitals for emphasis** — not in titles, not in section labels,
  not in tile captions. `EXECUTIVE READ-OUT` is off-brand; `Executive
  read-out` is correct. Sentence case throughout.
- **Never underline. Never combine bold and italic.**
- **Text is black.** Headings, tile numbers and labels are black; subtitles
  and footnotes are Grey IV `#7A7870`. Colour is not an emphasis tool in this
  brand — there is no case in which a red heading or a red number is right.
- Relative to the chart's body text: image title about 2.5x at light weight,
  panel heading about 1.2x bold, body 1x, footnote about 0.8x. Every chart in
  one image shares one body size.
- Left-align everything. Never justify, never centre a block of text.

### Chart mechanics

- **No gridlines** — neither horizontal nor vertical. A single black baseline
  of about 1pt is the entire frame.
- **Flat and two-dimensional.** No 3D, no shadows, no gradients, no rounded
  corners, no decorative shapes, nothing placed behind text.

### Chart Requirements

One message per chart. A chart carrying two is two charts.

Every chart must include:

Title

Business question

Date range

Metric definition

Source: the CPLAN report pack, with the generation date from the `Data as of` row at the top of `01-summary.txt`. Never name a workbook filename — this agent does not read one, and a filename copied into an instruction goes stale the next time the pack is rebuilt.

Scope, whenever the image carries a total. This pack is wider than the distributed workbook, so two different totals are true of the same portfolio on the same day, and an image is forwarded without its author: nobody can ask it which one it meant. The footnote answers before it is asked, in the shape `Activities in scope: N — includes M the report excludes`, with both figures from the summary's own lines. An image whose total silently disagrees with the workbook in someone's hand is the one failure here that survives being forwarded.

### The rest of the rules are in a skill

What is written above is the floor. It applies to every chart, and a chart
breaking one of these rules is wrong on sight, which is why it lives here where
nothing can miss it.

Everything else — which chart type answers which kind of question, how to place
more than one chart in an image without the panels colliding, and the checklist
to read your own image against before you send it — is in the `chart-standards`
skill. Load it before you draw. It is the half of the rules that stops an image
from running into itself, and it is short.

## Preferred Output Format

Executive Summary
- 3-5 bullets

Key Findings
- Evidence with numbers

Visualizations
- 1-3 <ORGANISATION>-compliant charts

Implications
- Business interpretation

Data Limitations
- Explicitly stated

Recommended Follow-up Analysis
- Evidence-based next questions

### Say each figure once

These sections divide the work; they do not each get a turn at the same
sentence. Three impressions of one fact read as three facts.

- A figure belongs to **one** place: the chart, if it has a shape worth
  seeing; otherwise a line of prose.
- A number tile is for a figure that has **no** chart in the image. A tile
  restating the tallest bar beside it is a tile to delete.
- A caption beside a chart says what the chart *means*, not what it shows.
  "Volume is concentrated in the first quarter" earns its line; "the peak week
  holds 60 activities" does not — the chart said it better.
- A panel restating its neighbour is a panel to drop; the white space is worth
  more than the repetition.

## Offer the next three questions

After the answer and before the footer, offer three follow-up questions as a
short list, phrased the way the user would type them.

Shape — copy the formatting, not only the wording. The block quote and the bold
heading are the part that makes the suggestions read as an offer rather than as
more of the answer, and they are what a reader's eye finds when scanning back:

> **You might also ask**
> - How does that split by division?
> - Which weeks in that quarter are the busiest?
> - Which channels carry most of that volume?

This applies to every answer, including a one-line factual one — when you
compress a report format for a short answer, the follow-ups are the part to
keep.

Three, every time; never two, and never a question you have just answered. If a
third is hard to find, widen the angle rather than dropping one: the same
figure by another dimension, over another window, or at the next level of
detail.

Suggest only questions this pack can actually answer. A suggestion ending in
"the dataset does not contain sufficient evidence" spends the reader's trust on
a dead end you could see coming.

## Close every answer with one footer line

End every answer with this line, and nothing after it:

> _Data as of YYYY-MM-DD · Powered by ECC Measurement & Insights_

The date is the `Data as of` row at the top of `01-summary.txt`. One line, no
heading, no apology, never omitted, never split into two — a second footer
stops being a signature and becomes a masthead.

**Every turn carries it, not just the first.**
A follow-up answer, a one-line correction,
a clarifying reply, an answer drawing on no figure at all —
each ends with the same line. A footer that appears once and then stops is
worse than none: the reader has learnt to expect a vintage, so its absence
reads as "still current".

It usually goes missing because a later turn never re-opens `01-summary.txt`
and the date is no longer in front of you. That is not a reason to drop the
line: the vintage does not change inside a conversation, so
restate the date you already gave.

If that date is more than four weeks old, add "— this pack may be out of date"
before the signature. The pack is rebuilt by hand, so it can be weeks stale
with nothing in a figure showing it.

---

This instruction set should produce answers that are far more useful than generic BI summaries because it forces the agent to be evidence-based, auditable, persona-specific, visualization-aware, and explicitly compliant with <ORGANISATION> communication standards while avoiding unsupported conclusions.
"""


# --------------------------------------------------------------------------
# Activities
# --------------------------------------------------------------------------

def pack_config(config):
    """The report's config with the two filters the pack does not apply.

    The workbook plans; the pack answers questions, and the two want different
    scopes. Priority 4 is the bucket nobody plans against and the objectives
    filter drops rows tagged with nothing but the catch-all -- both right for a
    planning instrument, both wrong for an agent someone asks "which
    deprioritised activities are coming up".

    The period goes too, and that reverses what this docstring used to argue.
    The old reasoning was that the period is what the report *is* about, so a
    pack covering every year answers a question nobody asked. What that missed
    is who asks the questions: the workbook is handed to someone planning a
    year, while the agent is asked "when did we last run this" and "what is
    already in the diary for next year", and a period boundary turns both into
    "the dataset does not contain sufficient evidence" -- the one answer that
    is worse than a wrong one, because it sounds careful.

    Every figure keeps meaning what it says: the pack states its span at the
    top, and `report_exclusion` marks each row the workbook's own window would
    have dropped, so the two can still be reconciled row by row.
    """
    # Two dimensions the workbook has no block for and the pack needs: a board
    # that names a team or a priority level has nowhere else to read one, and
    # deriving it from the activities file is the thing the instructions
    # refuse. Appended rather than substituted, and appended HERE rather than
    # in `ReportConfig`, for the reason the priority and objective filters are
    # dropped here: the workbook is a planning instrument and the pack answers
    # questions, and only the second one needs these.
    extra = tuple(field for field in ("priority", "lead_team")
                  if field not in config.breakdown_fields)
    return replace(config, exclude_priorities=(), exclude_objectives=(),
                   date_from=None, date_to=None,
                   breakdown_fields=config.breakdown_fields + extra)


def report_exclusion(activity, report_config):
    """Why the distributed workbook would drop this row, or "" if it keeps it.

    The pack is deliberately wider than the workbook, which means the two
    disagree about "how many activities are there" -- the failure this
    repository is otherwise built to prevent. It is survivable only because it
    is visible: this column lets an answer reconcile itself with a workbook
    somebody is holding, instead of contradicting it with no way to see why.
    """
    if not report_config:
        return ""
    # First, because it is the widest of the three and the only one the pack
    # did not always drop. `covers` is the workbook's own overlap test, called
    # rather than restated: a second implementation of "is this row in the
    # period" is how this column would start disagreeing with the workbook it
    # exists to reconcile against.
    start = activity.get("start_day")
    if start is not None and start == start:
        end = activity.get("end_day")
        if not report_config.covers(start, end if end == end else None):
            return "date window"
    if report_config.exclude_priorities:
        if derive.priority_number(activity.get("priority")) in set(
                report_config.exclude_priorities):
            return "priority"
    if report_config.exclude_objectives:
        if derive.only_excluded_objectives(activity.get("strategic_objectives"),
                                           report_config.exclude_objectives):
            return "objectives"
    return ""


def activity_rows(scope, report_config=None):
    """Every in-scope activity, one row each, exactly as the sheet writes them.

    Same columns in the same order as the workbook's Activities sheet, so the
    two can be read side by side. Dates become ISO strings rather than Excel
    serials: a retrieval index reads text, and `2025-03-05` is the only form
    that is unambiguous in one.

    Two columns the sheet does not have come last, and only when a report
    config is supplied: whether the workbook keeps the row, and why not.

    Two more sit in front of those on a membership build. They split the
    combined `GEB/GEB-1 members` column rather than replacing it: the combined
    column is the one every pack has, the workbook prints it, and a column set
    that changed shape under the reader would be worse than one that grows.
    The three are consistent by construction -- the two halves partition the
    combined value -- and `06-breakdowns.csv` is still where a count belongs.

    And one more on a pack-list build: `pack_known`, which `packs.mark` put on
    the frame and nothing carried out of it. The reading guide tells the agent
    to treat `pack_known = No` as a data-quality finding, so leaving it in the
    frame instructed the agent to filter on a column no delivered file had.
    """
    frame = scope.frame
    headers = [header for _, header in ACTIVITY_COLUMNS]
    # Without a list these would be two empty columns asserting a distinction
    # nothing made, which is the same lie the workbook refuses when it leaves
    # the GEB glossary term out.
    split = scope.membership is not None
    if split:
        headers += ["GEB members", "GEB-1 members"]
    # Conditional for that same reason, and read off the frame rather than off
    # `scope.packs`: `packs.mark` adds the column only where it could actually
    # compare the two sides, so this column exists exactly where a value in it
    # means something. An always-present, always-blank `pack_known` would say
    # "checked, and nothing was wrong" on every machine that never checked.
    show_pack_known = "pack_known" in frame.columns
    if show_pack_known:
        headers += ["pack_known"]
    if report_config:
        headers += ["in_report", "report_exclusion"]
    rows = []
    for _, activity in frame.iterrows():
        index = activity["week_index"]
        week = scope.grid.weeks[int(index)] if index == index and index is not None else None
        quarter = activity["_quarter"]
        values = []
        for field, _ in ACTIVITY_COLUMNS:
            if field == "_iso_week":
                values.append(f"{week.iso_year}-{week.label}" if week else "")
            elif field == "_quarter_label":
                values.append(f"Q{quarter[1]} {quarter[0]}" if quarter else "")
            elif field == "_executives":
                values.append("Yes" if activity["has_executives"] else "No")
            elif field in ("start_date", "end_date"):
                value = activity.get(field)
                values.append(value.date().isoformat()
                              if hasattr(value, "date") and value == value else "")
            elif field == "lead_time_days":
                value = activity.get(field)
                values.append(int(value) if value == value and value is not None else "")
            else:
                value = activity.get(field)
                values.append("" if value is None or value != value else value)
        if split:
            values += [activity.get("executives_geb", ""),
                       activity.get("executives_geb1", "")]
        if show_pack_known:
            values.append(activity.get("pack_known", ""))
        if report_config:
            reason = report_exclusion(activity, report_config)
            values += ["No" if reason else "Yes", reason]
        rows.append(values)
    return headers, rows


def pack_rows(scope, report_config=None):
    """One row per pack in the list, including the ones with nothing planned.

    Every pack, not only those an activity points at. A pack that holds no
    activity has nothing to be counted through, so before this file it was
    absent rather than merely undescribed -- and "which packs have nothing
    planned" is the first question a planner asks of a pack list.

    `activities_in_scope` is the figure to quote. `activities_total` says
    whether a zero means "nothing this period" or "nothing at all", which
    read very differently and cannot share one column. `in_report` follows
    the activity rows: the pack is in the report when any of its activities
    survives the workbook's own filters.
    """
    if scope.packs is None:
        return []

    in_scope = packs_module.activity_counts(scope.frame, scope.packs)
    overall = scope.pack_counts_all or {}

    reported = set()
    if report_config is not None and packs_module.PACK_LINK_COLUMN in scope.frame.columns:
        for _, activity in scope.frame.iterrows():
            if not report_exclusion(activity, report_config):
                identifier = packs_module.key(
                    activity.get(packs_module.PACK_LINK_COLUMN))
                if identifier:
                    reported.add(identifier)

    rows = []
    for _, pack in scope.packs.iterrows():
        identifier = packs_module.key(pack.get("cpid"))
        values = []
        for field in PACK_FIELDS:
            value = pack.get(field)
            if field in ("start_date", "end_date", "launch_date"):
                values.append(value.date().isoformat()
                              if hasattr(value, "date") and value == value else "")
            else:
                values.append("" if value is None or value != value else value)
        values.append(in_scope.get(identifier, 0))
        values.append(overall.get(identifier, 0))
        if report_config is not None:
            values.append("Yes" if identifier in reported else "No")
        else:
            values.append("")
        rows.append(values)
    return rows


# --------------------------------------------------------------------------
# Writing
# --------------------------------------------------------------------------

def _csv_text(header, rows):
    """The exact text `_write_csv` would write, without touching disk.

    `checklist_questions` searches this to decide whether a question is
    already answered by a shipped CSV, so it has to be the same serialisation
    an agent actually reads -- not a hand-rolled approximation that could
    disagree with the file on a quoting or delimiter edge case.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue()


def _write_csv(path, header, rows, bom=False):
    """Write a CSV, optionally with the byte-order mark Windows tooling wants.

    The pack's own CSVs are read by a code interpreter, where a BOM is one more
    thing for a naive parser to trip over, so they stay without one. The
    evaluation set is read by Excel and by an import dialog, both of which fall
    back to Windows-1252 without it -- which turned an em dash in a team name
    into `â€"` and made the file look corrupt before it was even rejected.
    """
    encoding = "utf-8-sig" if bom else "utf-8"
    with path.open("w", newline="", encoding=encoding) as handle:
        handle.write(_csv_text(header, rows))


def write_pack(scope, config, out_dir, generated=None, report_config=None):
    """Write the pack, the skill package and the checklist under `out_dir`.

    Returns the pack directory. The data files go in `pack/`; the skill
    archives, the instructions, the evaluation set and the checklist sit
    beside it, because none of them belongs in the folder the archive is
    built from -- least of all the answer key, which would travel into the
    archive and let the agent pass the test by reading it.
    """
    generated = generated or date.today()
    out_dir.mkdir(parents=True, exist_ok=True)
    pack_dir = out_dir / PACK_DIRNAME
    pack_dir.mkdir(parents=True, exist_ok=True)

    headers, rows = activity_rows(scope, report_config)
    _write_csv(pack_dir / CALENDAR_NAME, CALENDAR_HEADER, calendar_rows(scope, config))
    _write_csv(pack_dir / ACTIVITIES_CSV_NAME, headers, rows)
    _write_csv(pack_dir / BREAKDOWN_NAME, BREAKDOWN_HEADER,
               breakdown_rows(scope, config))
    # Only when there is a list. An empty pack file would assert that the
    # organisation has no packs, which is a much stronger claim than "this
    # machine does not sync the pack export".
    if scope.packs is not None:
        _write_csv(pack_dir / PACKS_CSV_NAME, PACKS_HEADER,
                   pack_rows(scope, report_config))
    # Unconditional: it needs no optional export, only the activities every
    # run already has. The grain between "one week" and "the whole period"
    # was missing, and its absence cost the agent minutes per question.
    _write_csv(pack_dir / PERIODS_CSV_NAME, PERIODS_HEADER,
               period_rows(scope, config, generated))
    (pack_dir / SUMMARY_NAME).write_text(
        summary_text(scope, config, generated, report_config), encoding="utf-8")
    (pack_dir / GLOSSARY_NAME).write_text(glossary_text(scope, config), encoding="utf-8")
    (pack_dir / QUALITY_NAME).write_text(data_quality_text(scope, config), encoding="utf-8")
    (pack_dir / README_NAME).write_text(
        readme_text(scope, config, len(rows), generated), encoding="utf-8")

    _write_skill_zip(pack_dir, out_dir / SKILL_ZIP_NAME)
    _write_brand_skill_zip(out_dir / BRAND_SKILL_ZIP_NAME)
    dashboard_skill.write_zip(out_dir / DASHBOARD_SKILL_ZIP_NAME)
    (out_dir / CHECKLIST_NAME).write_text(checklist_text(scope, config), encoding="utf-8")
    # Beside the pack, never inside it: an agent grounded on its own
    # instructions reads them as data, quotes them back as findings, and the
    # rules stop being rules.
    (out_dir / INSTRUCTIONS_NAME).write_text(INSTRUCTIONS_TEXT, encoding="utf-8")
    _write_csv(out_dir / EVALUATION_NAME, EVALUATION_HEADER,
               evaluation_rows(scope, config), bom=True)
    return pack_dir


def _write_skill_zip(pack_dir, zip_path):
    """The skill package: SKILL.md at the archive root, plus its data files.

    The prose files are not shipped twice -- SKILL.md replaces the README, and
    the glossary travels as a supporting file because the skill instructions
    point at it by name. The .xlsx is left out: a skill package is read as
    text, and the CSV beside it already carries the same rows.

    Called unconditionally from `write_pack`, one stage after the write that
    tolerates a pack export that was never synced -- so `PACKS_CSV_NAME` is
    included only when `pack_dir` actually has it. `zipfile.ZipFile.write` on
    a path that does not exist raises `FileNotFoundError`, and without that
    guard the supported no-pack-export case would crash here instead of
    producing the absence the file's own writer already allows for.

    The guard covers the pack file and nothing else. Extended over the six
    required names it would swallow the opposite bug: a write that failed
    upstream would leave a silently incomplete archive, uploaded and grounded
    on, where a `FileNotFoundError` at the moment of packing is the cheapest
    possible failure.

    The same `.exists()` answers what SKILL.md says, so the archive's own
    routing table cannot name a file the archive does not carry.
    """
    packs_source = pack_dir / PACKS_CSV_NAME
    with_packs = packs_source.exists()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("SKILL.md", skill_text(with_packs))
        for name in (GLOSSARY_NAME, SUMMARY_NAME, QUALITY_NAME,
                     CALENDAR_NAME, BREAKDOWN_NAME, ACTIVITIES_CSV_NAME,
                     PERIODS_CSV_NAME):
            archive.write(pack_dir / name, name)
        if with_packs:
            archive.write(packs_source, PACKS_CSV_NAME)


def _write_brand_skill_zip(zip_path):
    """The chart rules, alone in an archive with no data beside them.

    Nothing here is derived from a run, so it is rebuilt identically every
    time and only needs re-uploading when the rules themselves change. That is
    the point of separating it: the report pack goes stale weekly, the visual
    standards do not.
    """
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("SKILL.md", BRAND_SKILL_TEXT)


# --------------------------------------------------------------------------
# The checklist -- deliberately not part of the pack
# --------------------------------------------------------------------------

def _states(haystack, *parts):
    """Does one line of the pack carry all of `parts`, each as a whole word?

    Line by line rather than anywhere-in-the-file: a figure is only
    "pre-computed" if the pack states it *about the thing being asked*. The
    number 275 appearing somewhere and the line `External: 275` are different
    claims, and only the second makes a question answerable by reading.

    Whole words rather than substrings, because both halves collide otherwise.
    A team called "Team" is inside every `lead_team` label, and 18 is inside
    180 -- and a single line carrying `lead_team | 18 | 1 | 5%` then "states"
    that Team owns 18 activities, which it does not.

    Lookarounds rather than `\\b`, because a probe need not end in a word
    character: `\\bW07 (10 Feb)\\b` never matches the line it was built from,
    since `\\b` after the closing bracket demands a word character that is not
    there. That failure is silent and one-directional -- it grades a question
    the pack does answer as one only counting can -- so it has to be the
    boundary that does not care what the probe ends in.
    """
    patterns = [re.compile(rf"(?<!\w){re.escape(str(part))}(?!\w)", re.IGNORECASE)
                for part in parts]
    return any(all(pattern.search(line) for pattern in patterns)
               for line in haystack.splitlines())


def checklist_questions(scope, config):
    """Questions with a computed answer, split into controls and the rest.

    Which is which is DERIVED from the pack rather than asserted here. Hand
    labelling got it wrong on the first real run: "how many external activities"
    was written down as a counting question while `01-summary.txt` states
    `External: 275` outright, so an agent that only ever reads files answered it
    correctly and looked like it had counted. A control is exactly a question
    the pack already answers, and the only way to know that is to look.
    """
    frame = scope.frame
    total = len(frame)
    # The haystack was `summary_text + data_quality_text` alone from the day
    # this grading was added (3c270fd, 2026-08-06) until the day after
    # (fd4982d, 2026-08-07): at the time, those two prose files were the only
    # place a FINISHED figure -- as opposed to one row of many -- was ever
    # written down, so searching anywhere else could only have added false
    # matches. `06-breakdowns.csv` did not exist yet.
    #
    # It does now, and that reasoning no longer covers it. Once a field is a
    # breakdown block, its per-value totals are stated in `06-breakdowns.csv`
    # exactly as finished as the prose figures are -- `lead_team,Team,no,
    # activities,19` states "Team: 19" as plainly as `External: 275` does --
    # and leaving it out of the haystack does not make that question harder,
    # it just makes the checklist wrong about whether reading answers it.
    #
    # `04-calendar.csv` is deliberately still left out. It carries the same
    # blocks split by ISO week, and no single line in it ever states a
    # value's total for the whole period -- that figure only exists after
    # summing the value's rows across every week, which is the counting this
    # checklist exists to require. Including it would risk the opposite
    # mistake `_states` already guards against once: a value's count in one
    # particular week coincidentally matching a probe's number would grade a
    # counting question as a control on a line that never actually answers it.
    haystack = (summary_text(scope, config) + data_quality_text(scope, config)
                + _csv_text(BREAKDOWN_HEADER, breakdown_rows(scope, config)))

    # (question, answer, probe, reason). The probe is what the pack would have
    # to state, on one line, for reading to be enough.
    candidates = [("How many activities does the report cover in total?", total,
                   ("Activities in scope", total), "the portfolio total")]

    stats = metrics.load_stats(scope)
    candidates.append(("Which week has the most activities starting in it?",
                       f"{stats['peak_week_label']} with {stats['peak_week_count']}",
                       ("Peak week", stats["peak_week_label"]), "the busiest week"))

    if total:
        external = int((frame["source_type"] == "external").sum())
        candidates.append(("How many external activities are in scope?", external,
                           ("External", external), "one condition over every row"))

        teams = {}
        for value in frame.get("lead_team", []):
            name = str(value).strip()
            if name and name.lower() not in ("nan", "none", "null"):
                teams[name] = teams.get(name, 0) + 1
        if teams:
            top = max(sorted(teams), key=lambda n: teams[n])
            candidates.append(("Which lead team owns the most activities, and how many?",
                               f"{top} with {teams[top]}", (top, teams[top]),
                               "an aggregation over every row"))

        blank_lead = sum(
            1 for value in frame.get("lead", [])
            if str(value).strip().lower() in ("", "nan", "none", "null"))
        candidates.append(("For how many activities is the lead missing?", blank_lead,
                           ("lead", blank_lead), "a data-quality question, row by row"))

        # Only where a list makes the question answerable at all. It grades as
        # a control, and that is the point: the summary states this figure on
        # its own line, one line below the combined one, so an agent quoting
        # the combined figure here has read the wrong line rather than failed
        # to count -- which is the mistake worth catching about a distinction
        # nothing in the source data makes.
        if scope.membership is not None:
            geb = int((frame["executives_geb"] != "").sum())
            candidates.append(
                ("How many activities involve a GEB member, rather than GEB-1?",
                 geb, ("With GEB involvement", geb),
                 "the split the supplied member list makes"))

        quarters = {}
        for quarter in frame["_quarter"]:
            if quarter:
                label = f"Q{quarter[1]} {quarter[0]}"
                quarters[label] = quarters.get(label, 0) + 1
        if quarters:
            label = sorted(quarters)[0]
            candidates.append((f"How many activities start in {label}?", quarters[label],
                               (label, quarters[label]), "one condition over every row"))
            internal = sum(1 for q, source in zip(frame["_quarter"], frame["source_type"])
                           if q and f"Q{q[1]} {q[0]}" == label and source == "internal")
            candidates.append((f"How many INTERNAL activities start in {label}?", internal,
                               (label, internal), "two conditions combined"))

    questions = []
    for question, answer, probe, reason in candidates:
        control = _states(haystack, *probe)
        note = (f"{reason} -- stated in the pack, so reading it is enough"
                if control else f"{reason} -- stated nowhere; only counting answers it")
        questions.append((question, answer, control, note, probe))
    return questions


def evaluation_rows(scope, config):
    """The same questions as the checklist, as an importable test set.

    A sentence rather than a bare figure in the expected response: the graders
    that do compare against it work on meaning or on text, and "1380" alone
    gives either of them nothing to match a sentence against.

    Which questions are controls is deliberately NOT encoded here. The import
    takes the three columns it takes, and a marker in the question text would
    reach the agent -- `checklist.md` is where a reader learns which is which.
    """
    rows = []
    for number, (question, answer, _control, _note, _probe) in enumerate(
            checklist_questions(scope, config)[:EVALUATION_MAX_CASES], 1):
        rows.append((number,
                     question[:EVALUATION_MAX_QUESTION_CHARS],
                     f"{answer}, for {config.period_label()}."))
    return rows


def checklist_text(scope, config):
    questions = checklist_questions(scope, config)
    total = len(scope.frame)
    controls = [i for i, question in enumerate(questions, 1) if question[2]]
    lines = [
        f"# Does the agent really compute over all {total} rows?",
        "",
        f"Data: {config.period_label()}, {total} activities in scope.",
        "",
        "This file is deliberately NOT part of the pack. An answer key inside "
        "the pack would be retrieved like any other file, and the agent would "
        "pass by reading the answers.",
        "",
        f"Question{'s' if len(controls) != 1 else ''} "
        f"{', '.join(str(i) for i in controls)} "
        f"{'are' if len(controls) != 1 else 'is'} answered by the pack itself, "
        "so reading is enough -- they are the controls. The rest are stated "
        "nowhere and can only be answered by computing over the rows. An agent "
        "that gets the controls right and the rest wrong has retrieved rather "
        "than counted, which is the whole distinction being measured.",
        "",
        "Which question is which is worked out by searching the pack, not "
        "asserted by hand -- a question is a control exactly when the pack "
        "already answers it.",
        "",
        'Ask after every answer: "How many rows did you examine for that?"',
        "",
    ]
    for number, (question, answer, _control, why, _probe) in enumerate(questions, 1):
        lines += [f"## {number}. {question}",
                  f"- **Correct:** {answer}",
                  f"- {why}",
                  ""]
    lines += [
        "## What this does and does not prove",
        "",
        f"This list was computed over {total} rows. A green result here says "
        "nothing about a portfolio several times that size, which is where the "
        "open question actually lies. Regenerate it against the real data "
        "before deciding.",
        "",
    ]
    return "\n".join(lines)
