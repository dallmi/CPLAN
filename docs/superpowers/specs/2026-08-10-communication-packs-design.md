# Read the pack list, instead of inferring packs from the activities

**Date:** 2026-08-10
**Status:** draft

## Problem

The pack knows a communication pack only as a number on an activity row.
`metrics.pack_stats()` counts distinct values of `communication_pack_cpid` and
sorts them into size buckets, and that is the whole of it. The agent can say
how many packs hold exactly one activity. It cannot say what any of them is
called, who leads it, when it launches, or what it is for.

The sharper gap is the one that cannot be closed by counting at all. A pack
that holds no activity in scope has no row to be counted, so it is not merely
undescribed — it is absent. "Which packs have nothing planned against them"
is the question a planner asks first, and the pack cannot be asked it.

The glossary states the position plainly today: packs are "Not used as a
grouping dimension". `CPLAN_KNOWLEDGE_BASE.md` has carried the remedy as a
known gap for as long — "model communication packs and tracking clusters as
first-class records". This closes the pack half of it.

## The activities already carry the name

`communication_pack` is mapped in `COLUMN_MAP`, parsed as a SharePoint lookup
like every other reference field, and present on every activity row that has a
pack. It is simply not in `ACTIVITY_COLUMNS`, the tuple that decides what
`05-activities.csv` holds — that file exports `communication_pack_cpid` under
the header "Pack ID" and stops there.

So the agent has been reading bare identifiers while the display names sat one
tuple entry away. Adding `("communication_pack", "Pack")` before the Pack ID
entry is the first change and depends on nothing else here. It ships on its
own.

## What the pack list carries, and what the mapping misses

`CommunicationPacks*.csv` arrives in the same synced folder as the activity
exports and is already globbed by `find_input_files()`. `transform_packs()`
harmonises it — the same decode-and-longest-label-first matching the activities
use, the same lookup parsing, the same CET date handling. That code is proven
and moves into the shared load path unchanged.

`PACKS_COLUMN_MAP` is the part that is not ready. It maps sixteen labels onto
thirteen columns and carries none of these, all of which the pack form is
documented to have:

    Name of communication pack · Tracking cluster · Category · End date

It also maps a column labelled `Campaign` onto `lead` and carries the source's
`Campaing` misspelling beside it, which is a sign the list's semantics were
inferred once and never checked against an export. Widening the map is part of
this work, not a follow-up, and step 0 below is what says exactly how far.

## Which column joins

Three columns are candidates and the code cannot settle between them:

| Candidate | Comes from | Why it is plausible |
|---|---|---|
| `communication_pack_cpid` | `Communication pack:C` | What `pack_stats()` already treats as pack identity |
| `campaign_ltid` | `Campaign LTID` | The pack list names its own identifier column `LTID` |
| `tracking_pack_id` | Split from `tracking_id` | Independent of SharePoint lookups entirely |

Picking one by reasoning would put an unverified assumption under everything
downstream, where it would surface as a plausible-looking pack file that is
quietly joined wrong. So it is measured first.

`pipeline/scripts/check_pack_link.py`, with a `packlink.cmd`/`packlink.ps1`
pair beside it, follows the shape `check_time_zones.py` and
`check_tracking_ids.py` already set: read-only, reads what a refresh would
read, prints a verdict, exits non-zero when the answer is bad. It reports two
things.

First, the raw column names of the pack export, decoded, each marked mapped or
unmapped. That is what turns "the mapping is probably incomplete" into a list.

Second, for each candidate: how many activities carry a value at all, how many
of those match a pack row, how many pack rows are hit, the orphans on both
sides, and three sample values per side so a format mismatch is visible rather
than inferred from a zero.

Exit 0 only when exactly one candidate matches at least 80% of the activities
that carry any pack reference. When none does, that result is the finding: the
data does not link, and no amount of code makes it link.

The winner becomes `PACK_LINK_COLUMN`, a named constant carrying the measured
rate and the date in its docstring. The load path then reports the live match
rate on every run and warns when it falls below what was measured. An
assumption that is checked once is an assumption that will be wrong later
without anyone noticing.

## The new file

`07-packs.csv`, one row per pack, every pack in the list:

    Pack ID · Pack · Cluster · Category · Lead · Lead team · Partner team
    Divisions · Regions · Objective · Start · End · Launch · Description
    activities_in_scope · activities_total · in_report

Every pack, including those with `activities_in_scope = 0`. That is the whole
point of the file, and it follows the rule the activity rows already follow:
widen the scope, then mark each row with whether the narrower instrument holds
it. `in_report` says whether the workbook would have carried the pack — that
is, whether any of its activities survive the report's own filters.

Two counts rather than one because they answer different questions.
`activities_in_scope` is what the agent should quote; `activities_total` says
whether a zero means "nothing planned this period" or "nothing at all", and
those read very differently to a planner.

Duplicate `cpid` values resolve the way duplicate `tracking_id` values already
do: the most recently `modified` row wins and the number dropped is logged.

The file is numbered 07 because it is data and the data files run 00–06. The
rule documents shift up behind it — reading guide to 08, chart standards to 09,
the three boards to 10, 11 and 12. The upload folder grows from eleven files to
twelve against a limit of twenty.

## What the activity rows gain

One column: `pack_known`, Yes or No. It says whether the row's pack reference
resolved to a pack in the list, which is a data-quality finding that is
invisible today.

Nothing else. Copying the pack's lead, objective or dates onto the activity row
would put the same field in two files, and two copies of a field are two
truths as soon as one of them is stale. The activity file is already
twenty-six columns wide. The cost is real and is paid in the reading guide: to
answer "who leads the pack behind this activity" the agent has to look the Pack
ID up in `07-packs.csv`, and the guide says so in those words.

## What the texts say

`01-summary.txt` gains three figures under PACK COVERAGE, which today reports
only what the activity rows themselves reveal: packs in the list, packs with no
activity in scope, and activities whose pack reference resolved to nothing.

The first of those sits beside the existing "Distinct packs", and the two are
not the same number — one counts pack rows in the export, the other counts
distinct identifiers seen on activities. They differ by exactly the packs
nobody has planned against, which is the figure this whole change exists to
produce, so both stay and the labels say which is which.

When the pack export is absent the section reads as it does today.

The glossary entry stating that packs are not a grouping dimension becomes
false and is replaced.

The reading guide, at 08, carries the substance: what a pack is, when to open
`07-packs.csv` instead of `05-activities.csv`, how the two connect through the
Pack ID, and that a pack with zero activities is an answer rather than a
defect.

The Agent Builder instructions carry a pointer of roughly 150 characters and
nothing more. `INSTRUCTIONS_TEXT` stands at 7,764 characters against a field
that holds 8,000, and `test_the_prompt_still_has_its_margin` reserves 200 of
the remaining 236 for the organisation rename — so 36 characters are genuinely
free and the pointer has to be paid for out of existing text. Which passage
gives way is settled while writing it; the test fails if it is not settled.

The Copilot Studio skill has no such limit and takes the fuller wording. The
two surfaces diverging here is deliberate and already has precedent in
`agent_builder.INSTRUCTIONS_TEXT`, which says less than its Studio counterpart
for a reason about the surface.

## When the export is not there

No `CommunicationPacks*.csv` in the input folder means no `07-packs.csv`, no
`pack_known` column, and a run that is otherwise identical to today's. A
missing optional input does not fail a run — the same rule `geb-members` set,
for the same reason: most machines will not have every file, and a pipeline
that stops on an absent optional is a pipeline nobody can run.

A match rate below the recorded threshold is different. The file is still
written, because a badly joined pack file is still evidence, but the run warns
loudly and the summary carries the rate. Silence is the one response that would
let a wrong join reach an agent unremarked.

## Tests

`report_fixtures.py` gains a pack export alongside the four activity CSVs. The
new cases: the link resolves at the expected rate and a lower rate warns; a
pack with no activities appears with a zero rather than being dropped; an
activity whose reference resolves to nothing carries `pack_known = No`; a run
without the pack export produces today's output exactly; the instruction limit
holds after the pointer is added; the upload folder stays within twenty files.

## Not in scope

`TrackingCluster*.csv` as a second entity. Packs as a breakdown dimension in
`06-breakdowns.csv`. Pack fields on the calendar workbook. A fourth board.
Each is a separate decision that reads better once the pack link is measured
rather than assumed.
