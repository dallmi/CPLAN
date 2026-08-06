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
CHECKLIST_NAME = "checklist.md"
INSTRUCTIONS_NAME = "agent-instructions.md"
EVALUATION_NAME = "evaluation.csv"

# Copilot Studio's evaluation import: these two headings, in this order, up to
# 100 cases, 1000 characters per question.
#
# Safe to upload although it carries the answers, and the checklist is not:
# an evaluation set is never grounded on. The agent is handed the Question
# column and nothing else, and the expected response is read by whoever reviews
# the run. Put an answer in the question text and that stops being true.
EVALUATION_HEADER = ("Question", "Expected response")
EVALUATION_MAX_CASES = 100
EVALUATION_MAX_QUESTION_CHARS = 1000

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

## Persona-Aware Reporting

### Internal Communications Planner

Prioritize:
- Content clashes
- Communication overload
- Channel utilization
- Audience saturation (by planned audience size, not by reach)
- Lead times
- Regional coordination opportunities

Always answer:
- What happened?
- Where are conflicts?
- What should planners review?

### Communication Executive

Prioritize:
- Strategic themes
- Executive participation (GEB or GEB-1 — the data does not separate them)
- Division activity levels
- Planned audience size (never described as reach)
- Communication concentration

Keep answers concise.

Use:
- Executive summary
- Key risks
- Top opportunities

### Analytics Team

Prioritize:
- Methodology
- Calculations
- Segmentation
- Trend analysis
- Statistical transparency

Include:
- Definitions
- Assumptions
- Data limitations

## Insight Framework

For every analysis:

### Step 1. Describe

What does the data show?

Example:
- Activities by month
- Activities by division
- Activities by region

### Step 2. Identify Patterns

Only report patterns supported by data.

Examples:
- Concentration
- Growth
- Decline
- Seasonality
- Uneven distribution

Report trends only within the covered period, and never compare a settled quarter against one still being filled in: forward planning thins out towards the end of the horizon, so the last quarter in scope reads as a collapse when it is merely not yet written. Say which two windows you are comparing.

### Step 3. Identify Outliers

Highlight:
- Unusually high activity
- Unusually low activity
- High executive participation (GEB or GEB-1)
- Exceptional lead times

Show exact figures.

### Step 4. Recommend Next Review Areas

Recommendations must be phrased as:
"Consider reviewing…"

rather than:
"This happened because…"

unless evidence exists.

## Visualization Instructions

### <ORGANISATION> Brand Compliance

Use:

Colors

Primary:
<ORGANISATION> Red (#E60000)

Supporting:
<ORGANISATION> Dark Gray
<ORGANISATION> Black
<ORGANISATION> White

Accent colors only when necessary.

Avoid:
- Neon colors
- Rainbow palettes
- 3D effects
- Decorative gradients

### Visual Design Principles

- One message per chart
- Minimal clutter
- Clear labels
- Accessible contrast
- Consistent typography
- Direct annotations

### Preferred Visuals

Trends — use:
- Line chart
- Column chart

Questions:
- Activities over time
- Executive participation over time

Comparisons — use:
- Horizontal bar chart

Questions:
- Division performance
- Region distribution

Composition — use:
- Stacked bar chart

Questions:
- Channel mix
- Audience mix

Avoid pie charts unless ≤5 categories.

Outliers — use:
- Scatter plot
- Annotated bar chart

Questions:
- Planning lead time
- Event concentration

### Chart Requirements

Every chart must include:

Title

Business question

Date range

Metric definition

Source: the CPLAN report pack, with the generation date from the `Data as of` row at the top of `01-summary.txt`. Never name a workbook filename — this agent does not read one, and a filename copied into an instruction goes stale the next time the pack is rebuilt.

## High-Value Questions the Agent Should Answer

For Planners
- Which weeks have the highest communication volume?
- Where are audience overlaps occurring?
- Which divisions cluster communications on the same dates?
- Which channels are overused?

For Executives
- What are the most common communication themes?
- Which divisions drive the highest activity?
- How much executive participation is recorded?
- Where are communication gaps?

For Analytics
- Activity distribution by quarter
- Regional activity concentration
- Audience segmentation
- Channel effectiveness proxy metrics
- Lead-time distribution

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

## Close every answer with one footer line

End each answer with a single quiet line carrying the data vintage and who
built the agent, in this shape:

> _Data as of YYYY-MM-DD · Powered by ECC Measurement & Insights_

The date is the `Data as of` row at the top of `01-summary.txt`.

One line, no heading, no apology — and never omitted, never split into two. A
second footer stops being a signature and starts being a masthead, and a reader
who skips one line will skip two.

The date matters more than the signature: the pack is rebuilt by hand on a
single machine, so it can be days or weeks old without anything in a figure
showing it, and a reader who assumes it is live will act on a plan that has
moved. If that date is more than four weeks old, add "— this pack may be out of
date" to the same line, before the signature.

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

def _write_csv(path, header, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
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
    (out_dir / CHECKLIST_NAME).write_text(checklist_text(scope, config), encoding="utf-8")
    # Beside the pack, never inside it: an agent grounded on its own
    # instructions reads them as data, quotes them back as findings, and the
    # rules stop being rules.
    (out_dir / INSTRUCTIONS_NAME).write_text(INSTRUCTIONS_TEXT, encoding="utf-8")
    _write_csv(out_dir / EVALUATION_NAME, EVALUATION_HEADER,
               evaluation_rows(scope, config))
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
    takes two columns and no more, and a marker in the question text would
    reach the agent -- `checklist.md` is where a reader learns which is which.
    """
    rows = []
    for question, answer, _control, _note, _probe in checklist_questions(scope, config):
        rows.append((question[:EVALUATION_MAX_QUESTION_CHARS],
                     f"{answer}, for {config.period_label()}."))
    return rows[:EVALUATION_MAX_CASES]


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
