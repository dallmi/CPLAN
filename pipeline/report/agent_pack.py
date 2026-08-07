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

Same `scope` and `config` as `build_workbook`, and the figures come from the
same `metrics` functions the sheets call rather than from a second
implementation -- `tests/test_agent_pack.py` holds the two to each other.
"""

import csv
import re
import zipfile
from datetime import date

from openpyxl import Workbook

from pipeline.report import metrics
from pipeline.report.calendar_sheet import (
    NOT_SPECIFIED,
    SPLIT_FIELDS,
    _sort_key,
    _split_for,
)
from pipeline.report.config import (
    AUDIENCE_BAND_ORDER,
    FIELD_TITLES,
    LARGE_AUDIENCE_BANDS,
    SHORT_NOTICE_DAYS,
)
from pipeline.report.data import EXCLUSION_ORDER
from pipeline.report.table_sheets import ACTIVITY_COLUMNS, GLOSSARY_SECTIONS

# The folder that gets uploaded, and the two artefacts that do not. Keeping the
# uploaded set in its own directory is the whole point: "select this folder" is
# a instruction someone can follow, "select these seven of nine files" is not,
# and the checklist is an answer key -- inside the pack the agent would ground
# on it and pass the test by reading the answers.
PACK_DIRNAME = "pack"
SKILL_ZIP_NAME = "cplan-skill.zip"
# A second, data-free skill: the visual rules that only apply once something is
# drawn. Its own archive rather than a folder inside the first, because the two
# are uploaded as two skills and load independently -- an image can need the
# chart rules on a turn that never touches the calendar.
BRAND_SKILL_ZIP_NAME = "chart-standards-skill.zip"
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
ACTIVITIES_XLSX_NAME = "05-activities.xlsx"

# The block name for the row that carries the portfolio itself. Upper case
# because it is not a field: every other block names the column it groups by,
# and a reader (or an agent) filtering `block == "TOTAL"` is asking for the one
# set of rows that genuinely sums to the portfolio.
TOTAL_BLOCK = "TOTAL"
TOTAL_VALUE = "all activities"

CALENDAR_HEADER = ("block", "value", "overlaps", "iso_year", "iso_week",
                   "week_start", "activities")


def _rule(text):
    """A rule line for the prose files: one blank line, then the sentence."""
    return ["", text]


# --------------------------------------------------------------------------
# The blocks, derived exactly as the calendar sheet derives them
# --------------------------------------------------------------------------

def iter_blocks(scope, config):
    """Yield `(block, value, overlaps, subset)` for every calendar row.

    The same three groups the sheet writes, in the same order and by the same
    rules: the portfolio, the audience bands (a partition -- every activity
    carries exactly one, Unknown included), then one group per configured
    breakdown field (overlapping -- an activity naming two divisions appears
    under both).

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
            for name in names:
                values.setdefault(name, []).append(activity.name)
        for name in sorted(values, key=lambda n: _sort_key(field, n)):
            yield field, name, True, frame.loc[values[name]]


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
    leadership = [("With GEB/GEB-1 involvement", executives),
                  ("Large audience (top two bands)", large)]

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
        ("LOAD", load),
        ("LEADERSHIP AND AUDIENCE", leadership),
        ("PLANNING DISCIPLINE", discipline),
        ("DATA QUALITY", quality),
    ]


def summary_text(scope, config, generated=None):
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

    The definitions come from `GLOSSARY_SECTIONS` rather than being written
    again here: the workbook's glossary is already the vetted wording, under a
    hard length cap, and a second copy could only drift.
    """
    lines = ["CPLAN - HOW TO READ THIS DATA", "",
             "Read this before answering anything from the other files."]
    for title, terms in GLOSSARY_SECTIONS:
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
        f"appears under both. Only block={TOTAL_BLOCK} is a true total.",
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
        "GEB/GEB-1 is one field holding both levels, with nothing in the data "
        "saying which. Never name someone as a GEB member, and never answer "
        '"how many activities involve the GEB" -- the honest answer is '
        '"GEB or GEB-1".',
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

    lines += ["", "RECORD ANOMALIES", "-" * 16, "  anomaly | count"]
    for label, count in metrics.anomalies(scope.frame, scope.duplicates_removed):
        lines.append(f"  {label} | {count}")
    lines.append("")
    return "\n".join(lines)


def readme_text(scope, config, activity_rows, generated):
    return f"""CPLAN AGENT PACK

Machine-readable companion to the CPLAN calendar workbook. Same pipeline run,
same figures -- a different rendering, not a different report.

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
  {ACTIVITIES_CSV_NAME}    one row per activity, {activity_rows} rows
  {ACTIVITIES_XLSX_NAME}   the same rows as a single-sheet workbook

Figures here are computed, not spreadsheet formulas. Percentages are of the
in-scope total unless the line says otherwise.

Prefer {SUMMARY_NAME} and {CALENDAR_NAME} for any counting question: those
figures were computed by tested code. A figure derived from
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

## Axes, lines and legends

- Drop the y-axis when every bar carries its own data label. Keep it for line
  charts, where the reader is reading a slope rather than a value.
- Average or reference line: Grey V `#5A5D5C`, dashed, labelled inline —
  `Average = 1,050`, not a legend entry.
- Prefer a donut with a large white centre to a pie. Avoid both above five
  categories.
- Legends: square swatches, text to the right. When several charts share the
  same categories, draw one legend for the image rather than one per chart.
- Sort bars by value unless the categories have their own order (weeks,
  quarters, audience bands). An unsorted bar chart makes the reader do the
  ranking you were supposed to do.

## Laying out more than one chart

A single chart fails by being wrong. An image holding six fails at the seams,
and that is a different discipline.

- **A panel is one block**: heading, business question, plot, footnote. Reserve
  the vertical space for all four *before* drawing the plot. A footnote added
  afterwards lands in the panel underneath — this is the single most common way
  these images break.
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

Read your own image once against this list. Fix what fails; do not caption it.

1. Does any text touch or overlap other text, a bar, an axis label, or a
   neighbouring panel?
2. Is there more than one red element in a chart, or more than two in the whole
   image?
3. Any capitals used for emphasis, any underline, any coloured text?
4. Any gridlines, rounded corners, shadows, or a colour outside the palette?
5. Is at least half the image white?
6. Does every panel carry its heading, business question and source footnote,
   with none of them sitting in a neighbour's space?
7. Does any figure appear twice in the image?

An image failing one of these is redrawn, not explained.
"""


SKILL_TEXT = f"""---
name: cplan-reporting
description: Answers questions about the CPLAN communication plan - volumes, timing, leadership involvement, planning quality - from the report pack in this skill. Use for any question about planned communication activities, packs, channels, audiences, leads or planning gaps.
---

# CPLAN reporting

You answer questions about a communication plan from four files shipped with
this skill. They come from one pipeline run: same figures, same scope.

## Which file answers what

| Question | File |
|---|---|
| Totals, load, lead time, leadership involvement | `{SUMMARY_NAME}` |
| Completeness, pack coverage, anomalies | `{QUALITY_NAME}` |
| Volume over time by any dimension | `{CALENDAR_NAME}` |
| A single named activity | `{ACTIVITIES_CSV_NAME}` |

Prefer `{SUMMARY_NAME}` and `{CALENDAR_NAME}` for any counting question. Those
figures were computed by tested code. A number you derive yourself from
`{ACTIVITIES_CSV_NAME}` has not been through the report's rules.

## Rules you must not break

Read `{GLOSSARY_NAME}` first. It carries the definitions and the seven rules
this data does not survive without, and the two that cost the most are:

**Scope is a hard filter, and an overlap test.** The period is named at the top
of `{SUMMARY_NAME}`. An activity outside it is absent from every file here, so a
question about a date outside the period is OUT OF SCOPE -- never answer it with
zero. An activity whose run merely touches the period IS in scope, so a quarter
or ISO week naming the year before the period is normal, not an anomaly: those
columns label the start, and the start may lie outside.

**Overlapping rows do not sum.** In `{CALENDAR_NAME}`, a row with
`overlaps=yes` belongs to a block where one activity can appear under two
values. Adding such a block up gives a number larger than the portfolio. Only
`block={TOTAL_BLOCK}` is a true total.

## When you count from `{ACTIVITIES_CSV_NAME}`

State how many rows you examined, every time. If you cannot see every row, say
so plainly instead of estimating. A count from part of the file is not an
answer - it is a guess wearing a number.

## When to stop

If the answer is not in these files, say so and point the user at the planning
studio. Do not reason your way to a plausible figure: in this domain a wrong
number costs more than a missing one.

## Who is asking

Three audiences use this data, and the same figure serves them differently.

**Internal communications planner** — clashes, overload, channel use, audience
saturation by planned size, lead times, regional coordination. Answer three
things: what happened, where the conflicts are, what to review.

**Communication executive** — themes, executive participation (GEB or GEB-1,
which the data does not separate), division activity, planned audience size
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

The pack contains:

- `01-summary.txt` — portfolio figures: volume, load, lead time, leadership involvement
- `02-glossary.txt` — definitions and reading rules. Read this first.
- `03-data-quality.txt` — completeness, pack coverage, record anomalies
- `04-calendar.csv` — one row per block × value × week
- `05-activities.csv` — one row per activity

There is no Excel workbook behind this agent. Prefer `01-summary.txt` and `04-calendar.csv` for any figure they already state: those were computed by tested code. A figure you derive yourself from `05-activities.csv` has not been through the report's rules.

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
- **Overlapping rows do not sum.** In `04-calendar.csv`, a row marked `overlaps=yes` sits in a block where one activity can appear under two values (two divisions, two regions). Adding such a block up gives a number larger than the portfolio. Only `block=TOTAL` is a true total.
- **Audience is a planning estimate, never measured reach.** CPLAN holds no measured reach at all. Summing audience counts contacts, not people — one person inside six activities counts six times. Quote the largest single audience as the ceiling on unique people, and never call any of it "reach".
- **GEB/GEB-1 is one field holding both levels**, with nothing in the data saying which. Never name someone as a GEB member, and never answer "how many activities involve the GEB" — the honest answer is "GEB or GEB-1".
- **`channel` and `target_audience` hold several values in one string.** A value like "Email, Intranet" is one combination, not one channel.
- **Weekly counts place each activity once, in the week it starts.** A six-week campaign is one activity in one week, not six.
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
short list, phrased the way the user would type them:

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

def activity_rows(scope):
    """Every in-scope activity, one row each, exactly as the sheet writes them.

    Same columns in the same order as the workbook's Activities sheet, so the
    two can be read side by side. Dates become ISO strings rather than Excel
    serials: a retrieval index reads text, and `2025-03-05` is the only form
    that is unambiguous in one.
    """
    frame = scope.frame
    headers = [header for _, header in ACTIVITY_COLUMNS]
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
        rows.append(values)
    return headers, rows


# --------------------------------------------------------------------------
# Writing
# --------------------------------------------------------------------------

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
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def _write_activities_xlsx(path, header, rows):
    """The activities as a single-sheet workbook.

    One sheet, because Microsoft's own guidance for grounding on Excel is that
    agents respond best when the data is in one sheet within a workbook. No
    styling and no formulas: this file exists to be read by a machine, and the
    workbook next door already exists to be read by a person.
    """
    book = Workbook()
    sheet = book.active
    sheet.title = "Activities"
    sheet.append(list(header))
    for row in rows:
        sheet.append(["" if value is None else value for value in row])
    sheet.freeze_panes = "A2"
    book.save(path)


def write_pack(scope, config, out_dir, generated=None):
    """Write the pack, the skill package and the checklist under `out_dir`.

    Returns the pack directory. The uploaded files go in `pack/`; the skill
    ZIP and the checklist sit beside it, because neither belongs in a folder
    someone is told to point a knowledge source at.
    """
    generated = generated or date.today()
    out_dir.mkdir(parents=True, exist_ok=True)
    pack_dir = out_dir / PACK_DIRNAME
    pack_dir.mkdir(parents=True, exist_ok=True)

    headers, rows = activity_rows(scope)
    _write_csv(pack_dir / CALENDAR_NAME, CALENDAR_HEADER, calendar_rows(scope, config))
    _write_csv(pack_dir / ACTIVITIES_CSV_NAME, headers, rows)
    _write_activities_xlsx(pack_dir / ACTIVITIES_XLSX_NAME, headers, rows)
    (pack_dir / SUMMARY_NAME).write_text(summary_text(scope, config, generated),
                                         encoding="utf-8")
    (pack_dir / GLOSSARY_NAME).write_text(glossary_text(scope, config), encoding="utf-8")
    (pack_dir / QUALITY_NAME).write_text(data_quality_text(scope, config), encoding="utf-8")
    (pack_dir / README_NAME).write_text(
        readme_text(scope, config, len(rows), generated), encoding="utf-8")

    _write_skill_zip(pack_dir, out_dir / SKILL_ZIP_NAME)
    _write_brand_skill_zip(out_dir / BRAND_SKILL_ZIP_NAME)
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
    """
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("SKILL.md", SKILL_TEXT)
        for name in (GLOSSARY_NAME, SUMMARY_NAME, QUALITY_NAME,
                     CALENDAR_NAME, ACTIVITIES_CSV_NAME):
            archive.write(pack_dir / name, name)


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
    haystack = summary_text(scope, config) + data_quality_text(scope, config)

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
