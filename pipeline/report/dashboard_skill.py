"""The board catalogue: which panels make up a named executive board.

Three skills reach the agent, split by what each is about. `cplan-reporting`
says what the numbers are. `chart-standards` says how anything is drawn, and is
free of both data and organisation so it can be lifted elsewhere unchanged.
This one says which panels, in which order, from which pack line, make up a
board somebody asked for by name.

The split is not tidiness. Asked for "an executive dashboard" with no board
named, the agent decides every panel afresh, and a fresh decision is where a
rule gets dropped: a test render on 2026-08-06 put five tile numbers in Accent
red, a heading in capitals, and red on all five charts, against instructions
that forbid each in plain words. Naming the board fixes the panel list before
the drawing starts, so the rules apply to a known set.

Data-free, like `chart-standards` and unlike the pack: no figure, no period, no
generation date. It is rebuilt identically every run and re-uploaded only when
a board changes. What it does carry is a citation per panel -- file, block,
label -- and `tests/test_agent_pack.py` resolves every one of them against the
pack generated in the same run, so renaming a summary row breaks the build
rather than leaving a board pointing at a line that no longer exists.
"""

import zipfile

SKILL_NAME = "cplan-dashboards"

SKILL_TEXT = """---
name: cplan-dashboards
description: The named executive boards this agent can draw - which panels make up each one, in what order, and which pack line every figure comes from. Load whenever a dashboard, a board, an executive overview or a one-page summary is asked for, whenever a request names one of the three boards, and before drawing any image holding more than one chart.
---

# CPLAN executive boards

Three boards. Each answers one decision, and a board that tried to answer all
three would answer none — which is what an unnamed "executive dashboard"
becomes.

| Board | The decision it serves | File |
|---|---|---|
| Head of communications overview | Where do I intervene, and with whom? | `board-head-of-communications-overview.md` |
| Leadership attention | Where is executive time going, and where is it missing? | `board-leadership-attention.md` |
| Plan trust | What can I not yet rely on? | `board-plan-trust.md` |

Open the file for the board being asked for and draw exactly the panels it
lists, in the order it lists them. If the request names no board, say which
three exist and what each decides, and ask which one — do not blend them.

You still need the other two skills: `cplan-reporting` for the pack itself, and
`chart-standards` for how anything is drawn. This file says only which panels.

## How to read a panel

Every panel carries five fields, and each does one job.

- **Business question** — printed on the panel, under its heading.
- **Chart** — fixed. Not a choice to make again per run.
- **Source** — where the figure comes from. Read it; do not compute it, and
  do not print it — it is not the footnote.
- **Footnote** — the caveat this figure carries, printed under the panel.
- **Highlight** — whether this is the panel that gets the one red element.

## Reading a Source line

A citation names a file, then a block, then a label:

    01-summary.txt · LOAD · Activities in the peak week

Some name a file and a block only, when the panel plots the whole block:

    03-data-quality.txt · RECORD ANOMALIES

For `06-breakdowns.csv` the block form carries the measure, since a block there
holds several measures and a panel plots one:

    06-breakdowns.csv · block=region_group · measure=activities

Several citations on one line are separated by `;` and each stands alone.

A Source line is not the footnote. It tells you where to read a figure; the
footnote every panel prints is the one your instructions require — the CPLAN
report pack, with the generation date from the `Data as of` row in
`01-summary.txt`, never a filename, since a filename goes stale the next time
the pack is rebuilt.

A percentage of two cited figures is fine, and say both. `01-summary.txt`
prints a share only beside its VOLUME rows, so "39% record leadership
involvement" is one division between two audited counts. That is not the same
as deriving a figure from `05-activities.csv`, which remains the thing not to
do.

## The rules that hold across all three boards

**One red element per board, on the panel marked `Highlight: yes`.** Every
other panel is grey throughout — bars, lines, markers, numbers. Your
instructions allow two in an image; a board allows one. Tile numbers are black,
always: there is no board on which a red number is right.

**A number tile is only for a figure with no chart on the board.** A tile
restating the tallest bar beside it is a tile to delete. This is why no board
carries a peak-week tile next to its volume chart.

**The read-out states only the figures its own `Source:` line names.** Anything
else on the board has already been said better by the panel that plots it.

**Sentence case everywhere**, including the board title and every panel
heading. `Executive read-out`, never `EXECUTIVE READ-OUT`.

**Every board footer is the one your instructions require** — the data vintage
and the team signature, on one line, drawn as ordinary footnote text.

## Before you send a board

On top of the checklist in `chart-standards`:

1. Is exactly one panel red, and is it the one the board file marks?
2. Is every number tile black?
3. Does the board carry a panel the file does not list, or miss one it does?
4. Does any figure appear in two panels?
5. Does every panel print its business question and its footnote?

A board failing one of these is redrawn, not explained.

The scope check in `chart-standards` matters most here: a board is the artefact
most forwarded and least questioned, and its headline figure is larger than the
workbook's by every activity the report excludes.
"""

HEAD_OF_COMMUNICATIONS_OVERVIEW = """# Board — Head of communications overview

**The decision:** where do I intervene, and with whom? This board does not
inventory the plan. Every panel points at something, and the read-out ends by
naming which of the other boards to open.

Five panels. Panel 1 is a tile row across the top, panels 2–4 sit in a row
beneath it, panel 5 closes the board.

### Panel 1 — Where the function stands

Business question: what is behind us, what is imminent, and is the function planning ahead?
Chart: number tiles, one row, aligned on the baseline of the numbers
Source: 01-summary.txt · HORIZON · Planned to date; 01-summary.txt · HORIZON · Next 30 days from the data date; 01-summary.txt · PLANNING DISCIPLINE · Median lead time (days); 01-summary.txt · PLANNING DISCIPLINE · Planned at under 7 days' notice; 01-summary.txt · LEADERSHIP AND AUDIENCE · With GEB/GEB-1 involvement; 01-summary.txt · VOLUME · Activities in scope
Footnote: Split at the generation date stated at the top of the summary. Every record here is a plan — this system holds no delivery and no performance, so "planned to date" is plan whose date has passed and never means an activity ran.
Highlight: no

### Panel 2 — Audience load by start week

Business question: in which weeks does the whole organisation get hit at once?
Chart: line chart, one point per ISO week, two series on one axis — activities in the top two audience bands as the message, all activities as a faint context line; both series solid to the generation date and dashed after it, with a `data as of` divider drawn at that date and a grey marker carrying an inline label at the message series' peak week
Source: 04-calendar.csv · block=audience_band; 04-calendar.csv · block=TOTAL
Footnote: A planning estimate of who is addressed, never measured reach. Solid to the generation date, dashed after it: the forward half thins because it is not written yet, not because activity falls away.
Highlight: no

### Panel 3 — Priority mix

Business question: is the function working on what matters?
Chart: donut with a large white centre, four priority segments plus Not specified where it applies, no highlight
Source: 06-breakdowns.csv · block=priority · measure=activities
Footnote: The levels are peers and the split itself is the answer, so nothing is singled out. block=priority folds the source system's numbered labels and the studio's Critical/High/Medium/Low words onto this same set, in urgency order; Not specified covers an activity naming neither.
Highlight: no

### Panel 4 — Late requests by lead team

Business question: which team absorbs the most work booked at under a week's notice?
Chart: horizontal bar, sorted by value
Source: 06-breakdowns.csv · block=lead_team · measure=short_notice; 01-summary.txt · PLANNING DISCIPLINE · Lead time not measurable
Footnote: Requests received at under 7 days' notice, counted against the team carrying them. The pack knows when an activity was created and when it starts; it does not know who caused the gap, so a team at the top of this bar may be absorbing late work rather than causing it. An activity with no measurable lead time — a missing created date — is not counted here, so a short bar can mean missing dates rather than good planning.
Highlight: yes

### Panel 5 — Executive read-out

Business question: what do I do this month, and which board should be opened next?
Chart: none (prose), four to five sentences ending in a route
Source: 01-summary.txt · HORIZON · Rest of the period; 01-summary.txt · LOAD · Median activities per week; 01-summary.txt · LEADERSHIP AND AUDIENCE · Large audience (top two bands)
Footnote: none
Highlight: no

## What this board does not do

No audience-band distribution and no regional distribution. Both are true and
neither changes what anyone does; the one useful fact inside them — that the
unknown audience band holds the external records, whose form has no such field —
belongs in the read-out where it explains something.

Never call an audience figure reach. Never say "the GEB": the field holds both
levels and nothing separates them. Never read the thinning forward plan as a
decline — say it is unwritten.

End the read-out by naming a board: planning notice and lead time belong to
Planning discipline, missing fields to Plan trust, executive time to Leadership
attention. An overview that ends in observations competes with them; one that
ends in a route makes them a set.
"""


LEADERSHIP_ATTENTION = """# Board — Leadership attention

**The decision:** where is executive time going, and where is it missing from
communication that would warrant it?

Five panels. Panel 1 is a tile row, panels 2–4 sit in a row beneath it, panel 5
closes the board.

### Panel 1 — Number tiles

Business question: How much of the plan records leadership involvement?
Chart: number tiles, one row
Source: 01-summary.txt · LEADERSHIP AND AUDIENCE · With GEB/GEB-1 involvement; 01-summary.txt · VOLUME · Activities in scope
Footnote: The share is the first figure over the second. The source field holds both levels and cannot separate them.
Highlight: no

### Panel 2 — Leadership share by division

Business question: Which divisions bind the most executive attention?
Chart: horizontal bar, sorted by value
Source: 06-breakdowns.csv · block=business_division · measure=with_executives
Footnote: An activity naming several divisions appears under each; the bars do not sum to the portfolio.
Highlight: yes

### Panel 3 — Leadership by audience size

Business question: Does leadership involvement follow audience size?
Chart: horizontal bar, in band order — not sorted by value
Source: 06-breakdowns.csv · block=audience_band · measure=with_executives
Footnote: A planning estimate, never measured reach. Read this beside the band totals, not as a share of anything stated here.
Highlight: no

### Panel 4 — Leadership by region

Business question: Where is leadership involvement recorded?
Chart: horizontal bar, sorted by value
Source: 06-breakdowns.csv · block=region_group · measure=with_executives
Footnote: An activity naming several regions appears under each; the bars do not sum to the portfolio.
Highlight: no

### Panel 5 — Executive read-out

Business question: What should a reader take away?
Chart: none (prose), four to five sentences
Source: 01-summary.txt · LEADERSHIP AND AUDIENCE · Large audience (top two bands); 06-breakdowns.csv · block=business_division · measure=activities
Footnote: none
Highlight: no

## What this board does not do

Never say "the GEB". One field holds both GEB and GEB-1 with nothing in the
data separating them, so every label on this board reads GEB/GEB-1, and no
person is ever named — not in a bar, not in a footnote, not in the read-out.

Never present an audience band as reach. Panel 3 compares planning estimates.

Leadership involvement over time is not on this board: no pack file crosses the
executive dimension with the weeks, and a line drawn from the activities file
has not been through the report's rules.
"""


PLAN_TRUST = """# Board — Plan trust

**The decision:** what can a reader not yet rely on, and what is worth chasing
before the plan is used to decide anything?

Five panels. Panel 1 leads at full width, panels 2–4 sit in a row beneath it,
panel 5 closes the board.

### Panel 1 — Field completeness

Business question: Which fields are missing often enough to matter?
Chart: horizontal bar of missing counts, sorted by value
Source: 03-data-quality.txt · FIELD COMPLETENESS
Footnote: A field absent from the export is listed in the glossary as not counted, rather than counted as missing.
Highlight: yes

### Panel 2 — Activities without a pack link, by division

Business question: Where is pack membership not being recorded?
Chart: horizontal bar, sorted by value
Source: 06-breakdowns.csv · block=business_division · measure=without_pack
Footnote: A standalone activity is complete without a pack, which is why planning completeness excludes pack linkage and this is tracked separately.
Highlight: no

### Panel 3 — Median planning completeness by division

Business question: Which divisions fill in the fields they control?
Chart: horizontal bar, sorted by value
Source: 06-breakdowns.csv · block=business_division · measure=median_completeness
Footnote: A median per division; medians never combine, so these bars are read against each other and never added.
Highlight: no

### Panel 4 — Record anomalies

Business question: What is wrong with the records themselves?
Chart: horizontal bar, sorted by value
Source: 03-data-quality.txt · RECORD ANOMALIES
Footnote: Duplicates are counted before de-duplication; the rows the pack holds are already unique.
Highlight: no

### Panel 5 — Executive read-out

Business question: What is the most expensive gap, and what does it cost?
Chart: none (prose), four to five sentences
Source: 01-summary.txt · VOLUME · Unknown; 01-summary.txt · REPORT · Rows read
Footnote: none
Highlight: no

## What this board does not do

A missing pack link is not bad planning. Neither is an archived activity —
archiving is a list-size workaround in the source system, not a relevance
signal — and neither is a quarter or ISO week labelled with the year before the
period, because scope is an overlap test and those columns label the start.

Panels 2 and 3 are both division bars, and that is the point: one counts a
hole, the other measures a fill rate, and a division can be bad at one and fine
at the other. Do not merge them.
"""


BOARDS = {
    "board-head-of-communications-overview.md": HEAD_OF_COMMUNICATIONS_OVERVIEW,
    "board-leadership-attention.md": LEADERSHIP_ATTENTION,
    "board-plan-trust.md": PLAN_TRUST,
}


def write_zip(zip_path):
    """The board catalogue, alone in an archive with no data beside it.

    Nothing here is derived from a run, so it is rebuilt identically every time
    and only needs re-uploading when a board changes -- the same bargain
    `chart-standards` makes, while the report pack beside it goes stale weekly.
    """
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("SKILL.md", SKILL_TEXT)
        for name, text in BOARDS.items():
            archive.writestr(name, text)
