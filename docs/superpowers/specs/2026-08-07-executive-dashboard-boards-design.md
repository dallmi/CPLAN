# Named executive boards, defined as a skill

**Date:** 2026-08-07
**Status:** approved

## Problem

Asked for an executive dashboard, the agent improvises one. The result answers
every question at once — volume, audience, channel, region, leadership,
quality — and therefore serves no decision: a reader who wants to know whether
to move an activity out of week 6 reads the same picture as one asking where
executive time is going.

Improvisation also loses the rules. A test render on 2026-08-06 broke three of
the agent's own instructions in one image: five number tiles set in Accent red
against "text is black, there is no case in which a red number is right"; a
title and a panel heading in capitals against "never use capitals for
emphasis"; and red on all five charts plus five red tile numbers and five red
read-out labels, against "at most two in a whole image". Each rule is stated
plainly in the instructions and in `chart-standards`. Stating them again would
not have helped — nothing in the request told the agent *which panels* it was
drawing, so every panel was a fresh decision, and a fresh decision is where a
rule gets dropped.

A named board fixes the panel list before the drawing starts. The rules then
apply to a known set of panels rather than to whatever the turn invents.

## What the pack cannot currently answer

`04-calendar.csv` carries one row per block × value × week, where a block is a
single dimension: activities per division per week, activities per region per
week. Two dimensions never meet. "Which division binds the most executive
attention" is a cross of the `business_division` and `executives` blocks, and
no file states it.

`01-summary.txt` holds portfolio totals only — `With GEB/GEB-1 involvement` is
one number for the whole plan. `03-data-quality.txt` holds completeness per
*field* and pack coverage for the portfolio, never per division.

So the agent would have to derive those figures from `05-activities.csv`, which
its own instructions discourage: "a figure you derive yourself has not been
through the report's rules". A board whose central panel rests on a
self-computed number is the board not to publish.

## Decisions

**Three boards, executive audience only.** Portfolio overview, Leadership
attention, Plan trust. Each answers one decision. The two planner boards this
work identified — load and collision, planning discipline — are deferred until
the panel grammar has survived a real render.

**One skill holding all boards, not one skill per board.** The orchestrator
selects a skill from its description, and three descriptions built from the
same vocabulary — dashboard, executive, communication plan — separate poorly. A
vague request would have to grab one blind. A single skill with an index reads
the request, routes to a board, and can offer the other two.

**Not a section inside `chart-standards`.** That skill is deliberately free of
both data and organisation: it is the visual grammar, reusable by anything that
draws. Board definitions name pack files and column values. Merging them welds
the reusable half to the project-specific half, and the visual standards would
need re-uploading every time a board changed.

**The boards are data-free.** Like `chart-standards` and unlike the pack, a
board file carries no figure and no period — only which figure to read and from
where. It is rebuilt identically every run and only needs re-uploading when a
board changes.

**One new pack file, `06-breakdowns.csv`.** It states, per breakdown value, the
six measures the boards need. Everything a board shows is then pre-computed by
tested code.

**The breakdowns file reuses `iter_blocks`.** The same function
`calendar_rows` already iterates — same blocks, same values, same sort order,
same `overlaps` semantics. Only the aggregation differs. There is no second
understanding of what a block is, and no second place for one to drift.

**Exactly one panel per board carries the highlight.** The instructions permit
two red elements in an image; a board permits one. The remaining panels are
grey throughout. This is stricter than the rule it implements, and deliberately
so: "at most two" is a budget an improvising agent spends without noticing,
while "this panel, no other" is a property of the board that can be checked
before drawing and after.

**Every panel cites its source line.** File, block, label — for example
`01-summary.txt · LOAD · Activities in the peak week`. The agent reads that
figure rather than computing one, and the citation is machine-checkable against
the pack generated in the same run.

## `06-breakdowns.csv`

Long form, like `04-calendar.csv`, without the week dimension:

```csv
block,value,overlaps,measure,figure
TOTAL,all activities,no,activities,1380
business_division,<division>,yes,activities,412
business_division,<division>,yes,with_executives,166
```

The column is `figure`, not `count`: five measures are counts and one is a
median, and a column named `count` holding a median is a lie in the header row.

| measure | What it is |
|---|---|
| `activities` | Rows in the subset |
| `with_executives` | Rows where GEB/GEB-1 involvement is recorded |
| `large_audience` | Rows in the top two audience bands |
| `without_pack` | Rows with no pack link |
| `unknown_audience` | Rows whose audience band is Unknown |
| `median_completeness` | Median planning completeness, as an integer percentage |

Blocks and values come from `iter_blocks` unchanged: the portfolio total, the
audience bands, then one group per configured breakdown field. The `overlaps`
column carries the same meaning and the same warning — a block marked `yes`
sums past the portfolio, because one activity can appear under two divisions.

**A measure true by construction for its block is not written.**
`large_audience` and `unknown_audience` under `block=audience_band` restate the
row they sit in; `with_executives` under `block=executives` is every row in it
by definition. `04-calendar.csv` already leaves out rows that say nothing —
empty week/value pairs — for the same reason: a row that cannot be wrong cannot
be informative either, and it competes for the same retrieval budget as one
that is.

**Only count measures answer "how many".** `median_completeness` is per value
and never combines, on an overlapping block or a partitioning one. This goes in
the glossary beside the existing overlap rule.

## The skill package

`cplan-dashboards-skill.zip`, built beside the two existing archives:

```
SKILL.md                        the index and the shared panel rules
board-portfolio-overview.md
board-leadership-attention.md
board-plan-trust.md
```

`SKILL.md` is short enough to be read whole — which board answers which
decision, the panel contract, and the rules that hold across all three. A board
file is opened only once the board is chosen. This is the progressive
disclosure `cplan-skill.zip` already uses, where `SKILL.md` routes to five data
files.

A panel is written as:

```
### Panel 3 — Leadership share by division

Business question: Which divisions bind the most executive attention?
Chart: horizontal bar, sorted by value
Source: 06-breakdowns.csv · block=business_division · measure=with_executives
Footnote: Multi-division activities appear under each division; the bars do not
sum to the portfolio.
Highlight: yes
```

Five fields, each doing one job. `Business question` and `Footnote` are what
`chart-standards` already demands of every panel — fixed here instead of
invented per turn. `Chart` removes a per-run choice. `Source` is the citation.
`Highlight` is the red budget, spent once per board.

A citation takes one of two forms, and the test resolves both:

- `<file> · <block> · <label>` — one stated figure, such as
  `01-summary.txt · LOAD · Activities in the peak week`.
- `<file> · <block>` — the whole block, when the panel plots all of its rows,
  such as `03-data-quality.txt · RECORD ANOMALIES`. For `06-breakdowns.csv` the
  block form carries the measure instead of a label, since a block there holds
  six measures and a panel plots one:
  `06-breakdowns.csv · block=region_group · measure=activities`.

A panel drawing on more than one figure — a row of number tiles — separates its
citations with `;` on the one `Source:` line, and each must resolve
independently. Each repeats the file and the block in full: the board tables
below abbreviate for a reader, the board file cannot, because a parser reading
`Internal` with no file beside it has nothing to resolve.

The executive read-out keeps all five fields rather than becoming an exception:
`Chart: none (prose)`, `Highlight: no`, and a `Source:` line naming the figures
it is allowed to state. That list is the enforcement of "say each figure once" —
a read-out citing a figure another panel already plots is caught by reading the
board file, without rendering anything.

A percentage of two cited figures is allowed and cites both. `01-summary.txt`
prints a share beside the VOLUME rows only, so "39% of activities record
leadership involvement" has to be divided out of two stated counts. That is one
division between two audited numbers, not a derivation from the row set, and
the rule it must not cross is the one about `05-activities.csv`.

## The three boards

### Portfolio overview

*Is the plan as a whole plausible?* The quarterly read-out.

| # | Panel | Source | Highlight |
|---|---|---|---|
| 1 | Number tiles | `01-summary.txt` · VOLUME · `Activities in scope`; `Internal`; `External`; PLANNING DISCIPLINE · `Median lead time (days)`; LOAD · `Share in the five busiest weeks` | no |
| 2 | Volume by start week | `04-calendar.csv` · `block=TOTAL` | **yes** — the peak marker |
| 3 | Planned audience size | `06-breakdowns.csv` · `block=audience_band` · `measure=activities` | no |
| 4 | Regional distribution | `06-breakdowns.csv` · `block=region_group` · `measure=activities` | no |
| 5 | Executive read-out | `01-summary.txt` · LOAD · `Median activities per week`; `Weeks with no activity`; `Longest run of empty weeks`; LEADERSHIP AND AUDIENCE · `Large audience (top two bands)` | no |

Must not: carry a peak-week tile beside the volume chart — the chart says it
better, and the instructions delete a tile that restates a bar. Must not
restate the five-busiest-weeks share in the read-out; it is already a tile.
No channel panel: channels are their own board.

### Leadership attention

*Where is executive time going, and where is it missing?*

| # | Panel | Source | Highlight |
|---|---|---|---|
| 1 | Number tiles: activities with GEB/GEB-1 involvement, and that share of the portfolio | `01-summary.txt` · LEADERSHIP AND AUDIENCE · `With GEB/GEB-1 involvement`; VOLUME · `Activities in scope` | no |
| 2 | Leadership share by division | `06-breakdowns.csv` · `block=business_division` · `measure=with_executives` | **yes** — the highest |
| 3 | Leadership by audience band | `06-breakdowns.csv` · `block=audience_band` · `measure=with_executives` | no |
| 4 | Leadership by region | `06-breakdowns.csv` · `block=region_group` · `measure=with_executives` | no |
| 5 | Executive read-out | `01-summary.txt` · LEADERSHIP AND AUDIENCE · `Large audience (top two bands)`; `06-breakdowns.csv` · `block=business_division` · `measure=activities` | no |

Must not: say "the GEB". The field holds both levels with nothing separating
them, so every label reads GEB/GEB-1 and no person is ever named. Must not
present panel 3 as reach — an audience band is a planning estimate.

### Plan trust

*What can I not yet rely on?*

| # | Panel | Source | Highlight |
|---|---|---|---|
| 1 | Field completeness | `03-data-quality.txt` · FIELD COMPLETENESS | **yes** — the worst field |
| 2 | Activities without a pack link, by division | `06-breakdowns.csv` · `block=business_division` · `measure=without_pack` | no |
| 3 | Median planning completeness by division | `06-breakdowns.csv` · `block=business_division` · `measure=median_completeness` | no |
| 4 | Record anomalies | `03-data-quality.txt` · RECORD ANOMALIES | no |
| 5 | Executive read-out | `01-summary.txt` · VOLUME · `Unknown`; REPORT · `Rows read` | no |

Must not: read a missing pack link as bad planning. A standalone activity is
complete without one, which is why planning completeness excludes pack linkage
and tracks it separately. Must not read archived rows or a quarter labelled
with the previous year as an anomaly; both are the report working as designed.

Panels 2 and 3 are both division bars, and that is the intended contrast: one
counts a hole, the other measures a fill rate, and a division can be bad at one
and fine at the other.

## Testing

`tests/test_agent_pack.py` extends along the lines it already holds — pack
figures against the `metrics` functions, instructions against the
organisation-neutrality rule.

1. **Every `Source:` line resolves.** Parse the citations out of the three
   board files and assert each label exists in the file it names, in the
   generated pack for the fixture scope. This is the anti-drift test: renaming
   a summary row breaks the build instead of leaving a board pointing at a line
   that no longer exists. It also catches labels carrying an interpolated
   value, such as `Planned at under 7 days' notice`, which changes with
   `SHORT_NOTICE_DAYS`.
2. **Exactly one `Highlight: yes` per board file.**
3. **Every panel carries all five contract fields.**
4. **`breakdown_rows` agrees with the metrics functions** on the same fixture,
   the way the calendar and summary parity tests already work.
5. **Board files name only measures the file emits**, and never a measure
   suppressed as tautological for that block.
6. **No organisation name** in any board file, extending the existing check.

## What else has to move

Adding a sixth pack file touches every place that enumerates them:
`SKILL_TEXT`'s file table, `readme_text`, the pack listing in
`INSTRUCTIONS_TEXT`, and the glossary's rules. `_write_skill_zip` must carry it
into `cplan-skill.zip` as well, or the reporting skill ships a table of
contents naming a file it does not hold. `build_agent_pack.py` gains the third
archive in the list it prints, which is the only place an operator learns what
to upload. The instructions gain one line: load `cplan-dashboards` before
drawing a board, the way they already require `chart-standards` before drawing
anything.

`checklist_text` is deliberately left alone. It grades a question as a
"control" when the pack already states its answer, and it searches
`01-summary.txt` and `03-data-quality.txt` only — not `04-calendar.csv`, and so
not `06-breakdowns.csv` either. Adding the new file to that haystack would
reclassify counting questions as reading questions and blunt the one
measurement the checklist exists to make.

## Out of scope

**Leadership involvement over time.** It needs an `executive_involvement`
block in `iter_blocks`, whose docstring binds it to the calendar sheet's block
structure — so the workbook would gain a block too. That is a change to the
reader-facing artefact and deserves deciding on its own merits, not as a side
effect of a board.

**The planner boards** — load and collision, planning discipline. Both are
served by two further measures in the same file (`short_notice`, and a lead-time
median) and no new mechanism.

**Channel and coverage boards.** Channel is a multi-value combination field and
needs its own reading rules before it carries a board.

**Evaluation cases for boards.** The Copilot Studio harness grades a text
response; it cannot grade an image. The board rules are checked by the tests
above and by the `chart-standards` pre-send list, not by `evaluation.csv`.

**Packs as first-class records.** A campaign-coherence board would report on
gaps that belong to the data model rather than to the plan.
