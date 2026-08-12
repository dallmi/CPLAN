"""The same report pack, delivered to a surface that has no skills.

Copilot Studio takes the rules as skill archives that load before a turn, and
takes as many characters of Instructions as the prompt needs. Agent Builder in
Microsoft 365 Copilot takes 8,000 characters and no archives at all: the only
place a rule can live outside the prompt is a knowledge file, which is
retrieved rather than loaded.

So this module is not a smaller `agent_pack`. The data files are the same
files, from the same run -- `agent_pack` writes them and this module delivers
them. What differs is everything around them, and the difference has one
governing rule: what is wrong on sight goes in the prompt, and what merely
guides goes in a document. If the document is missed the agent draws an ugly
chart; if the palette were in it, the agent would draw an off-brand one.
"""

import re
import shutil

from pipeline.report import agent_pack, dashboard_contract, dashboard_skill

# The surface's own numbers, from the Microsoft Learn documentation for Agent
# Builder. Named rather than inlined because a test asserts against them and a
# reader deserves to see what is being obeyed rather than a bare 8000.
INSTRUCTIONS_LIMIT = 8000
DESCRIPTION_LIMIT = 1000
KNOWLEDGE_SOURCE_LIMIT = 20

UPLOAD_DIRNAME = "upload"
INSTRUCTIONS_NAME = "instructions.md"
DESCRIPTION_NAME = "description.txt"
STARTER_PROMPTS_NAME = "starter-prompts.md"
README_NAME = "README.txt"

READING_GUIDE_NAME = "09-reading-guide.txt"
CHART_STANDARDS_NAME = "10-chart-standards.txt"

# One file per board rather than one catalogue, because a skill package loads
# whole and a knowledge file is retrieved in chunks. A hit that returns panel 3
# of one board and panel 1 of another produces the blended board the
# definitions exist to prevent, so each board is its own retrieval target and
# small enough -- around 3,500 characters -- to come back entire.
#
# Numbered on from the two rule documents: an operator uploads a folder, and a
# folder that sorts into reading order is one fewer thing to explain.
BOARD_FILE_NAMES = {
    "board-leadership-attention.md": "11-board-leadership-attention.txt",
    "board-plan-trust.md": "12-board-plan-trust.txt",
}

# The board that is rendered rather than drawn. It sits after the three drawn
# ones because a reader scanning the numbered folder meets the boards first and
# this is the exception to them, not a fourth of the same kind.
CONTRACT_FILE_NAMES = {
    dashboard_contract.CONTRACT_NAME:
        "13-contract-head-of-communications-overview.txt",
}


# Repeated into all three files, and that is the design rather than a
# concession. In the skill package these rules sit once in SKILL.md because the
# index always loads; here nothing loads, so a fourth file holding them would
# be a fourth thing retrieval can miss -- and it would be missed exactly when a
# board WAS found, which is the case that matters. About eleven hundred
# characters three times costs nothing against nine spare knowledge slots.
#
# It carries only what a board needs and the prompt does not already state. The
# palette, the ratio and the typography rules are in Instructions, where a
# breach is wrong on sight.
BOARD_RULES_TEXT = """# How to draw a board

Draw the panels this file lists, in the order it lists them, and no others. A
panel you add is a panel nobody asked for; a panel you drop takes its question
with it.

Exactly one panel is red -- the one marked `Highlight: yes`. Every other panel
is grey throughout: bars, lines, markers and numbers. Tile numbers are black
on every board.

A `Source:` line says where to read the figure. It is not the footnote and is
never printed. The printed source footnote is the one your instructions
require: the CPLAN Agent with the `Data as of` date, never a filename. It names
you rather than the pack you read, because a reader holding the board and
wanting the next question answered has to know what to come back to.

Each panel's own `Footnote:` line is a different line, and it prints under
that panel, as the caveat this figure carries. The vintage footer above closes
the board once, after the last panel. Neither line stands in for the other:
printing the vintage is not printing the panel's caveat.

The read-out states only the figures its own `Source:` line names. Anything
else has already been said better by the panel that plots it.

If you cannot see this file whole, say so and draw nothing rather than filling
in the panels you cannot see.

"""


# The seven the skill archive carries, in the order they are numbered. `00-README`
# is left out for the reason the archive leaves it out: it explains the pack to
# a person, and the reading guide does that job for the agent. `07-packs.csv`
# is last of the data files and, unlike the other six, optional -- the copy
# loop below skips it when no pack export was synced.
UPLOAD_DATA_FILES = (
    agent_pack.SUMMARY_NAME,
    agent_pack.GLOSSARY_NAME,
    agent_pack.QUALITY_NAME,
    agent_pack.CALENDAR_NAME,
    agent_pack.ACTIVITIES_CSV_NAME,
    agent_pack.BREAKDOWN_NAME,
    agent_pack.PACKS_CSV_NAME,
    agent_pack.PERIODS_CSV_NAME,
)


# No comment header addressed to the operator. The Studio file opens with one,
# and it is right to: that file is long enough that 330 characters of guidance
# cost nothing. Here they cost four percent of the field, and a reader who
# selects-all and pastes takes the comment into the prompt with them. What the
# operator needs to know is in the run output and in README.txt beside this.
#
# No "offer the next three questions" block either, and that is the one place
# this prompt deliberately says LESS than the Studio one rather than shorter.
# The Studio block exists for a reason that is about the surface and not about
# the agent: Copilot Studio has no follow-up chips, so an answer that does not
# carry its own suggestions ends in a dead end. Agent Builder offers its own
# follow-ups under every answer. Instructing the model to write three more
# would put two sets of suggestions on one turn, the model's above the
# surface's, and the reader then has to work out which of them the agent
# actually stands behind.
#
# It came across in the original cut because the block was copied with the
# rest; what did not come across was the sentence in check.ps1 saying why it
# was ever there. A rule justified by one surface is not a rule until the next
# surface has been asked the same question.
#
# The pack file's line describes BOTH states rather than asserting either, and
# that is the one thing this text cannot do the way the knowledge files beside
# it do. They are rewritten on every run; this is pasted into a field once and
# stays there while the pack is rebuilt underneath it, so a machine that starts
# syncing the pack export next month would otherwise be left with a prompt that
# denies the file it now holds. The same reason the GEB wording here describes
# both states while `02-glossary.txt` follows the run.
INSTRUCTIONS_TEXT = f"""You are the Communications Planning Insight Agent.

You answer questions about communications planning activity using only the CPLAN report pack in your knowledge.

## Your files

- `{agent_pack.SUMMARY_NAME}` — portfolio figures, the period, and the `Data as of` date
- `{agent_pack.GLOSSARY_NAME}` — definitions and reading rules. Read first.
- `{agent_pack.QUALITY_NAME}` — completeness, coverage, anomalies
- `{agent_pack.CALENDAR_NAME}` — one row per block × value × week
- `{agent_pack.ACTIVITIES_CSV_NAME}` — one row per activity
- `{agent_pack.BREAKDOWN_NAME}` — one row per block × value × measure, for crossing two dimensions
- `{agent_pack.PACKS_CSV_NAME}` — one row per pack, including packs with nothing planned. Present only where a pack list was synced; if it is not in your knowledge, this build had none
- `{READING_GUIDE_NAME}` — audiences, analysis steps, good follow-up questions
- `{CHART_STANDARDS_NAME}` — chart choice and multi-panel layout
- `11`–`13-board-*.txt` — one per named executive board: head of communications overview, leadership attention, plan trust

Prefer `{agent_pack.SUMMARY_NAME}`, `{agent_pack.CALENDAR_NAME}` and `{agent_pack.BREAKDOWN_NAME}` for any figure they already state: those were computed by tested code, and a figure you derive from `{agent_pack.ACTIVITIES_CSV_NAME}` has not been through the report's rules. There is no Excel workbook behind this agent.

Open `{READING_GUIDE_NAME}` before you answer and `{CHART_STANDARDS_NAME}` before you draw. The rules below hold whether or not you reach them. Draw a board only from its own file; if none is named, say which three there are and ask.

## Non-negotiable rules

### 1. Evidence first

Every conclusion traces to the data. Never invent causes, trends, benchmarks, forecasts or recommendations. Where the data does not support a conclusion, say: "The dataset does not contain sufficient evidence to answer this question." Separate facts, interpretation and suggested actions.

### 2. Quantify

Report count, percentage, change against a named comparison, and sample size. "74 activities in Q3, 22% of all recorded" — not "Q3 was very active".

Name a row, cite its ID — lists included: `Tracking ID`, `Pack ID`, `Cluster ID`.

### 3. Show the calculation

For every insight give the fields used, filters applied, date range and calculation logic. When you count over `{agent_pack.ACTIVITIES_CSV_NAME}`, state how many rows you examined. If you cannot see every row, say so instead of estimating.

### 4. Surface data quality

Check for missing values, duplicates, empty categories, invalid dates and inconsistent naming; flag what affects interpretation.

Do NOT flag these — the report working as designed:
- A quarter or ISO week naming the year before the period. Scope is an overlap test; those columns label the start, and the start may lie outside.
- Archived activities. Archiving is a list-size workaround in the source, not a relevance signal.

### 5. CPLAN data rules

These come from the data, and they override general analytical instinct.

- **Scope is a hard filter.** The period is at the top of `{agent_pack.SUMMARY_NAME}`. An activity outside it is absent, not zero — a question about a date outside the period is out of scope, not an answer of nought.
- **Overlapping rows do not sum.** `overlaps=yes` blocks let one activity count twice. `overlaps=no` blocks, including `block={agent_pack.TOTAL_BLOCK}`, sum to the portfolio.
- **Audience is a planning estimate, never measured reach.** Summing it counts contacts, not people — one person in six activities counts six times. Quote the largest single audience as the ceiling on unique people, and never call any of it "reach".
- **GEB/GEB-1 is one field holding both levels.** `executives_geb` / `executives_geb1` blocks mean a supplied list separated them — cite it, never add the two. Without them, never name a GEB member: answer "GEB or GEB-1".
- **`channel` and `target_audience` hold several values in one string.** "Email, Intranet" is one combination, not one channel.
- **Weekly counts place each activity once, in the week it starts.** A six-week campaign is one activity in one week.
- **This pack is wider than the distributed workbook**: it covers every year, and keeps the deprioritised bucket and rows tagged only with the catch-all objective. Every row in `{agent_pack.ACTIVITIES_CSV_NAME}` carries `in_report` and `report_exclusion`; counting `in_report = Yes` reproduces the workbook. Quote the full count and name which one: "1,385 in the plan; 1,362 in the report, which leaves out 23 deprioritised."
- **When the answer is not in the pack**, say so and point to the planning studio. Do not reason your way to a figure.

## Charts

### The {agent_pack.ORGANISATION_PLACEHOLDER} brand palette — these values and no others

- White `#FFFFFF` — every background, and the dominant colour
- Black `#000000` — text, axis line, rules, labels
- Accent red `#E60000` — the one highlighted element
- Grey III `#8E8D83` — lighter series
- Grey IV `#7A7870` — default series and footnotes
- Grey V `#5A5D5C` — average and reference lines
- Grey VI `#404040` — darkest series, dark fills
- Bordeaux I `#BD000C` — a second red, where red must appear twice
- Bronze I `#B98E2C` — a third series
- Pastel I `#ECEBE4` — tile fills, alternate rows

The greys are warm: a cool grey (`#808080`, a library default) is wrong though it reads as grey. Status colours are for data-driven status only — red `#BD000C`, amber `#E4A911`, green `#6F7A1A`.

### How much of each

- **At least half the image is unmarked white.** Margins and space around type count; a filled panel does not.
- **One red element per chart, at most two in an image** — the answer to that chart's business question.
- **Red never covers the largest area.** If what you would highlight is already the biggest, leave it grey.
- **Highlight only where one thing is the answer.** Where the categories are peers and the split is the answer (donut, stacked bar), nothing is highlighted.
- **Everything else is grey.** Never fill a tile, header band or panel with red.

### Typography and mechanics

- **Never capitals for emphasis.** Sentence case throughout. Never underline, never bold with italic.
- **Text is black**; subtitles and footnotes Grey IV.
- Title about 2.5x body at light weight, panel heading 1.2x bold, footnote 0.8x. One body size per image. Left-align everything.
- **No gridlines.** A single black baseline of about 1pt is the entire frame.
- **Flat and two-dimensional.** No 3D, shadows, gradients, rounded corners.

### Every chart carries

Title · business question · date range · metric definition · source · scope, wherever the image states a total: `Activities in scope: N — includes M the report excludes`. One message per chart; a chart carrying two is two charts.

Source is the CPLAN Agent with the `Data as of` date from `{agent_pack.SUMMARY_NAME}`, never a filename and never the pack.

## Answer format

Executive summary (3–5 bullets) · Key findings, with numbers · Visualizations (1–3 {agent_pack.ORGANISATION_PLACEHOLDER}-compliant charts) · Implications · Data limitations · Recommended follow-up analysis.

**Say each figure once.** These sections divide the work; they do not each get a turn at the same sentence. A figure belongs to one place: the chart if it has a shape worth seeing, otherwise a line of prose.

## Close every answer with one footer line

End every answer with this line, and nothing after it:

> _Data as of YYYY-MM-DD · Powered by {agent_pack.TEAM_SIGNATURE}_

The date is the `Data as of` row at the top of `{agent_pack.SUMMARY_NAME}`. **Every turn carries it, not just the first** — a follow-up, a correction, an answer drawing on no figure at all. It usually goes missing because a later turn never re-opens the summary; the vintage does not change inside a conversation, so restate the date you already gave.

If that date is more than four weeks old, add "— this pack may be out of date" before the signature.
"""


# Names the domain rather than praising the agent. This field is what the
# orchestrator reads when it decides whether a question belongs here, so a
# sentence about how thorough the agent is buys nothing and a sentence about
# what it holds buys the routing. Saying what the pack does NOT hold is worth
# as much: an agent picked for a question about measured reach answers it from
# a plan that has none. No placeholder -- the description is not a brand
# surface, and one more find-and-replace is one more chance to forget.
DESCRIPTION_TEXT = """Answers questions about the internal communication plan \
- volumes, timing by week and quarter, channels, audiences, divisions and \
regions, leadership involvement, and planning quality - from a report pack \
generated by the CPLAN pipeline. Every answer states the figures it used, the \
rows it examined and the date the pack was built. Use it for any question \
about planned communication activities; it does not hold measured reach, \
engagement, or any post-delivery result.
"""

# Five rather than the documented minimum of three: one per audience the pack
# serves, one that crosses two dimensions -- the answer most likely to expose
# whether retrieval reached the whole file rather than a chunk of it -- and one
# naming a board, because the prompt only reacts to a dashboard being asked
# for and a user who has never heard the word has no other way to find one.
STARTER_PROMPTS_TEXT = """# Starter prompts

Add each as its own starter prompt on the Configure tab.

- Which weeks in the current quarter carry the most activities?
- Which divisions have the most activities with executive involvement?
- How complete is the plan, and which fields are most often missing?
- How many activities are in scope, and how many does the distributed report leave out?
- Show me the leadership attention board.
"""


# `agent_pack.SKILL_TEXT` minus its front matter and minus the four sections
# that moved into the prompt above: the file list, the rules that must not be
# broken, the row-count rule, and when to stop. What is left is the guidance
# half -- who is asking, how to work an analysis, what to offer as a follow-up.
# It is not repeated in the prompt because an answer that misses it is duller
# rather than wrong, and 8,000 characters cannot hold both halves.
#
# Split into three so the Packs section can follow the run, as SKILL.md does
# next door: it describes a file and a column that exist only where a pack
# export was synced, and a knowledge file is delivered whether or not what it
# describes was.
_READING_GUIDE_HEAD = """# Reading the CPLAN pack

Your instructions carry the file list and the rules that must not be broken.
This is the rest: how to read for the person asking, and how to work through
an analysis rather than answering the first thing you find.

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
"""

_READING_GUIDE_PACKS = f"""
## Packs

A communication pack groups activities around one objective, with its own
lead, period and brief. `{agent_pack.PACKS_CSV_NAME}` has one row per pack.

It holds every pack, including those with no activity in the period. A pack
showing `activities_in_scope = 0` is an answer — nothing planned against it,
not a defect. Check `activities_total` before calling it dormant: zero in
scope with a positive total means nothing *this period*.

## Always cite the identifier

Whenever you name an activity, a pack or a cluster, put its identifier beside
the name -- in a sentence, in a table, in a list of forty. Activities carry
`Tracking ID`, packs carry `Pack ID`, and both carry `Cluster ID`.

A name is not unique and cannot be looked up: two activities can be called
"Q3 town hall", and nobody can find either in the planning system from that
name. A list of names is a list nobody can act on; the identifier is what
makes an answer usable once the conversation is over.

To go from an activity to its pack, match the activity's `Pack ID` to the
pack row's `Pack ID`. The pack's lead, dates and objective are in that row
and nowhere else; the activity row carries the pack's name and identifier
only. `pack_known = No` on an activity means its pack is not in the list,
which is a data-quality finding worth reporting when it is common.
"""

_READING_GUIDE_TAIL = """
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


def reading_guide_text(with_packs):
    """The guide for the folder that is about to be written, not for both."""
    return (_READING_GUIDE_HEAD
            + (_READING_GUIDE_PACKS if with_packs else "")
            + _READING_GUIDE_TAIL)


# The packed rendering, for anything that wants the text without a run behind
# it. The uploaded copy always goes through `reading_guide_text`.
READING_GUIDE_TEXT = reading_guide_text(True)


# `agent_pack.BRAND_SKILL_TEXT` minus its front matter, with the opening
# reworded: the original tells the reader the palette is in the instructions,
# which is still true, and calls itself a skill, which on this surface names a
# mechanism that does not exist. The palette table itself is NOT repeated here
# -- two statements of one hex value is two things to keep in step, and the
# copy that drifts is the one nobody re-reads.
CHART_STANDARDS_TEXT = """# Chart standards

The palette, the red-to-white ratio and the typography rules are in your
instructions and apply whether or not you reach this file. What follows is the
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
tallest bar, the peak, the outlier — the accent red.

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
- **Place nothing at a coordinate you worked out yourself.** Use a layout
  mechanism that reserves space and refuses to overlap -- a grid with
  constrained layout in a plotting library, a CSS grid in HTML. Every rule
  here is one you cannot verify afterwards on a surface where you never see
  the image, so the layout has to make overlap impossible rather than
  forbidden. That is the only version of "nothing overlaps" that survives
  being unable to look.
- **The image carries panels, not loose prose.** A bulleted block of findings
  dropped into the canvas is the one element with no fixed height: it grows
  with what it says, runs into whatever was placed beneath it, and arrives
  twice over, because the answer beside the image already carries those
  sentences. Findings go in the answer.
  Two things are not loose prose. A panel's own heading, question and
  footnote belong to the panel and are reserved with it. So does a read-out
  panel a board declares -- it is a panel like any other and gets its
  rectangle before it gets its words. Set it one line per sentence, so its
  height is one you reserved rather than one it grew into.
- **An element with no curve, bar or area is not a plot. Do not build it as
  one.** A number tile, a caption band, a coloured backing panel: none of them
  needs a coordinate system, and every one your tool creates arrives with
  ticks, spines and their labels, which land straight across the caption. If
  your tool makes one anyway, strip it in the same statement that creates the
  element -- never in a later tidying step.
  That last clause is the rule, and it is written that way for a measured
  reason. Across twelve test renders the runs that carried no leftover
  coordinate systems scored between zero and two text collisions; the two that
  did scored seventy-two and seventy-eight. Both of those reported having
  checked every text artist including the tick labels, and one of them quoted
  the rule requiring it. A step that can be skipped is a step that gets
  skipped and reported as done.
- **Measure what the library drew, not only what you wrote.** Three of those
  six renders reported having verified the layout programmatically, and all
  three collided anyway: each had walked the text artists it placed itself
  and never the tick labels the library generated beside them. A check that
  enumerates your own artists confirms your intentions, not the image.
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
- **A bar's value label goes inside the bar once the bar is long.** Past about
  two thirds of the axis there is no room outside it, and a label put there
  anyway leaves the plot and lands in whatever is beside it. Inside, set it
  right-aligned against the bar's end; outside only while the bar is short
  enough that the whole label still falls within the axis.
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
- **A panel restating its neighbour is a panel to drop.** The white space left
  behind is worth more than the repetition.

## Before you send it

This list is what a reader does to the image in its first five seconds. On most
surfaces you cannot see what you have drawn, so it is not an inspection you can
carry out afterwards — which is why everything above is written as a rule for
building the image rather than for judging it.

The first two are arithmetic, not judgement, and they are the two that fail in
practice. Do them by measuring, before you hand the image over:

* Collect EVERY text the image will carry — your own, plus every tick label,
  axis label and title the library added — ask each for its rendered extent,
  and compare all of them pairwise. Any pair whose boxes intersect is a fault,
  and the pair is almost always one you did not write.
* Compare each of those extents against the canvas. Anything crossing the edge
  is clipped in the file even though nothing complains while you draw.

Fix what fails; do not caption it.

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


README_TEXT = f"""CPLAN agent, Agent Builder delivery
===================================

Four things to do, in this order. Nothing here is uploaded except the contents
of {UPLOAD_DIRNAME}\\.

1. Instructions
   Open {INSTRUCTIONS_NAME}, replace every {agent_pack.ORGANISATION_PLACEHOLDER} with the organisation's
   name, and paste the whole file into the Instructions field on the Configure
   tab. Paste it as it stands: it is written to fit the field's
   {INSTRUCTIONS_LIMIT}-character limit as delivered, and it is the whole prompt rather
   than an addendum to one.

2. Description
   Paste {DESCRIPTION_NAME} into the Description field. No replacement needed.

3. Knowledge
   Upload every file in {UPLOAD_DIRNAME}\\ -- all of them, and nothing else. The folder
   is the instruction: what is in it is what the agent is grounded on.

4. Starter prompts
   {STARTER_PROMPTS_NAME} holds five, one per line. Add each as its own starter
   prompt.

{agent_pack.CHECKLIST_NAME} is NOT uploaded and NOT pasted. It is the answer key: questions
with their computed answers, for checking the agent by hand once it is built.
An agent that can read it passes every question without computing anything.

Rebuild both deliveries together with agentpack.cmd. The pack next door and
this folder are two renderings of one run; uploading one built on a different
day than the other hands the agent two vintages of the same figure.
"""


def write_builder_pack(pack_dir, out_dir, scope=None, config=None):
    """The delivery Agent Builder takes, from the pack `agent_pack` just wrote.

    `pack_dir` is the source of every data file, copied rather than
    regenerated: regenerating would mean a second pass over the same scope, and
    two passes are two chances to differ. A copy can only be wrong by being
    stale, which the shared run already rules out.

    The upload folder is the instruction. An operator uploading knowledge
    uploads a folder, so anything sitting in it becomes knowledge whether or
    not it should -- which is why the answer key and the README are written
    outside it, beside the file that is pasted rather than uploaded.

    `scope` and `config` are needed only for the checklist. They are optional
    so that refreshing the upload set needs nothing but the pack it is built
    from.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    upload_dir = out_dir / UPLOAD_DIRNAME
    upload_dir.mkdir(parents=True, exist_ok=True)

    # The pack file is absent when no pack export was synced. Copying it
    # unconditionally would turn a missing optional input into a crash in the
    # delivery step, one stage after the run that tolerated it.
    #
    # Only that one name is guarded. The other six are required, and a guard
    # over them would turn a failed write upstream into a quietly incomplete
    # upload folder -- which is uploaded whole and grounded on, with nothing on
    # the surface saying a file is missing. A crash here is the cheap failure.
    with_packs = (pack_dir / agent_pack.PACKS_CSV_NAME).exists()
    written = set()
    for name in UPLOAD_DATA_FILES:
        if name == agent_pack.PACKS_CSV_NAME and not with_packs:
            continue
        shutil.copyfile(pack_dir / name, upload_dir / name)
        written.add(name)
    # The guide is written per run, so it follows the folder the way SKILL.md
    # does next door: its Packs section explains a file and a column that only
    # a pack export produces, and a knowledge file describing a document the
    # agent does not hold is answered from whatever it does hold.
    (upload_dir / READING_GUIDE_NAME).write_text(reading_guide_text(with_packs),
                                                 encoding="utf-8")
    (upload_dir / CHART_STANDARDS_NAME).write_text(CHART_STANDARDS_TEXT,
                                                   encoding="utf-8")
    for key, name in BOARD_FILE_NAMES.items():
        (upload_dir / name).write_text(
            BOARD_RULES_TEXT + dashboard_skill.BOARDS[key], encoding="utf-8")
    # The contract carries no board rules. Nothing in it is drawn, so the rules
    # about red elements and tile colours would be eleven hundred characters of
    # advice against a mistake this file cannot produce.
    for key, name in CONTRACT_FILE_NAMES.items():
        (upload_dir / name).write_text(
            dashboard_contract.CONTRACTS[key], encoding="utf-8")
    written.update({READING_GUIDE_NAME, CHART_STANDARDS_NAME,
                    *BOARD_FILE_NAMES.values(), *CONTRACT_FILE_NAMES.values()})

    # Sweep what this run did not write. `mirror_upload` has done this for the
    # mirror all along and its docstring names the reason; the folder the
    # operator actually uploads from was never swept, which is the half that
    # matters more -- most machines have no mirror configured.
    #
    # The numbering shifts every time a data file is added: the boards went
    # 09-11, then 10-12, then 11-13. Writing this run's names over the last
    # run's leaves both sets side by side, so the operator uploads what he
    # sees, twelve files arrive as fourteen, and two of them are the same
    # rules under a number the prompt no longer names. It also spends
    # knowledge slots on a surface that allows twenty.
    #
    # `MIRRORED_NAME` and nothing else: a note or a screenshot the operator
    # keeps in that folder is his, and this run has no business deleting it.
    for path in sorted(upload_dir.iterdir()):
        if (path.is_file() and path.name not in written
                and MIRRORED_NAME.match(path.name)):
            path.unlink()

    # Beside the upload folder, never inside it: an agent grounded on its own
    # instructions reads them as data, quotes them back as findings, and the
    # rules stop being rules.
    (out_dir / INSTRUCTIONS_NAME).write_text(INSTRUCTIONS_TEXT, encoding="utf-8")
    (out_dir / DESCRIPTION_NAME).write_text(DESCRIPTION_TEXT, encoding="utf-8")
    (out_dir / STARTER_PROMPTS_NAME).write_text(STARTER_PROMPTS_TEXT,
                                                encoding="utf-8")
    (out_dir / README_NAME).write_text(README_TEXT, encoding="utf-8")
    if scope is not None and config is not None:
        (out_dir / agent_pack.CHECKLIST_NAME).write_text(
            agent_pack.checklist_text(scope, config), encoding="utf-8")
    return upload_dir


# Every file the upload folder holds is numbered, and nothing else this mirror
# meets is. That is what makes the set removable without a manifest: a file of
# this shape in the destination came from an earlier run of this same step, and
# a file of any other shape was put there by the operator.
MIRRORED_NAME = re.compile(r"^\d{2}-.+\.(txt|csv)$")


def mirror_upload(upload_dir, target):
    """This run's upload set, in the folder the agent is really fed from.

    `upload_dir` is written where the pipeline can write -- a OneDrive Output
    folder, or the checkout. The agent is fed from wherever its knowledge is
    synced, which is a different folder chosen by whoever set the agent up, and
    the two were joined by a manual copy. A copy outside the run is a copy that
    can be forgotten, and forgetting it produces exactly the failure this
    module already names in another form: two vintages of one figure, with
    nothing on either folder saying which is which.

    Superseded files are removed, and that half cannot be skipped. The
    numbering shifts whenever a file is added -- the boards moved from 09-11 to
    10-12 when the chart rules became a knowledge file -- so copying alone
    leaves the previous run's board sitting beside this run's, both retrievable
    and both looking current. Only `MIRRORED_NAME` is removed; a note or a
    screenshot the operator keeps in that folder is left alone.

    Never creates `target`. A folder conjured inside a sync that is not really
    set up takes the upload set nowhere while looking like it worked, which is
    the rule the resolvers in `build_agent_pack` follow for the same reason --
    and why this one is handed a folder that already exists.

    Returns `(copied, removed)`, both as sorted file names, so the run can say
    what it did to a folder the operator is not looking at.
    """
    copied = []
    for path in sorted(upload_dir.iterdir()):
        if path.is_file():
            shutil.copyfile(path, target / path.name)
            copied.append(path.name)

    current = set(copied)
    removed = []
    for path in sorted(target.iterdir()):
        if (path.is_file() and path.name not in current
                and MIRRORED_NAME.match(path.name)):
            path.unlink()
            removed.append(path.name)
    return copied, removed
