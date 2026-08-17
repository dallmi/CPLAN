# Exclude what the source says to hide, and say how much was excluded

**Date:** 2026-08-17
**Status:** draft

## Problem

Some communication activities are not for general circulation. The source
system already says which: every activity carries a boolean the planner ticks,
exported under the SharePoint-encoded name `Hide_x0020_from_x0020_public_x00…`
— "Hide from public", `TRUE` when set.

The pipeline never sees it. `transform()` keeps only the columns named in
`COLUMN_MAP` and drops the rest (`process_cplan.py:691`), and no entry in that
map matches this field. So the flag is discarded in the first step of the first
script, while the rows it applies to travel on complete — title, description,
audience, leads, dates — into the Parquet file, into Postgres, into the studio,
into the standalone dashboards, into the calendar report, into the agent pack
that gets uploaded to a retrieval agent, and into every MCP answer.

Nothing downstream can filter these rows today, because by the time anything
downstream sees them, the only thing that marked them is gone.

This is not a request for a new access-control system. The source has already
made the decision; the pipeline is failing to carry it.

## What the field is

A boolean. `TRUE` means "hide from public". The name is the source's own
statement of intent, which is what makes it usable: nothing here has to infer
sensitivity from free text or from a title someone worded carefully.

Two things about it are **not yet verified against real data**, because no
export is present on the machine this was designed on (`pipeline/input` and
`data/` are empty; the exports live on the work machine and in OneDrive):

- Whether the unset state arrives as `FALSE`, as an empty cell, or as both.
  The screenshot that identified the field had the column filtered to `TRUE`,
  so only that side of it was visible.
- Whether all four activity exports carry the column, including the two
  archives.

Both are settled by the rules below rather than by assumption, and both should
be confirmed on first run.

## The rule

A row whose `hide_from_public` is true is **excluded from all further
processing**, and every place that reports a number says how many rows were
excluded.

Excluding rather than redacting is a deliberate choice, and it has a cost worth
naming: every count, every workload figure, every calendar density becomes
smaller than reality. That cost is paid down by the second half of the rule.
An unexplained undercount is a wrong answer; an undercount that says "3
excluded" beside it is a correct answer about a smaller set. The count is not
decoration — it is the thing that makes the exclusion honest, and it is not
optional in any surface that reports a total.

Three sub-rules follow from the field's shape:

**An empty cell is not hidden.** That is what the source means when nobody
ticked the box. Only a truthy value hides a row.

**A missing column is a hard error, naming the file.** If an export arrives
without the column at all, both silent answers are wrong: treating every row as
public leaks exactly what this exists to prevent, and treating every row as
hidden produces an empty report that looks like a real result. The run stops
and says which file lacks the column.

**The marker itself is never exported.** A `hide_from_public` column in any
output would be a map of the interesting rows, which is worse than not having
filtered at all. The step that drops the rows drops the column with them.

## Marking and excluding are two steps

`transform()` gains the mapping and the normalisation, and nothing else. It
produces a frame that still holds every row, now with a real boolean column.

A separate function — `exclude_hidden(frame) -> (frame, excluded_count)` —
removes the rows, removes the marker column, and returns the count. Every
consumer calls it explicitly.

### Why not simply drop the rows inside `transform()`

Because `transform()` has three callers, not one:

| Caller | What it feeds |
|---|---|
| `process_cplan.py:1341` | the ETL proper → Parquet → Postgres, studio, portal, reports, agent pack |
| `check_tracking_ids.py:325` | the tracking-ID check |
| `check_time_zones.py:100` | the time-zone check |

A drop inside `transform()` reaches all three silently. For the tracking-ID
check that is actively harmful: an ID that exists but is hidden would report as
`missing`, and `missing` in that tool means "never created". The documented
purpose of that check is to keep "never created" and "spelled wrong" apart, and
this would introduce a third thing it cannot distinguish — with the worst
possible consequence, someone re-creating an activity that already exists.

Two steps also make the policy greppable. `exclude_hidden` appears at every
place that applies it, so the places that *do not* apply it are found by
looking, rather than by remembering.

## Where the exclusion is applied

Applied — everything downstream of the ETL inherits it:

- `process_cplan.py`, immediately after `transform()` per file, before the
  frames are combined. Everything reading `communications.parquet` is therefore
  covered without knowing this feature exists: the studio and standalone
  builds, `daily_refresh`, `import_snapshot`, `sync_snapshot` → Postgres →
  portal and studio, the calendar report, the dashboards, the board bundle, the
  agent pack, the agent builder, and the MCP server.

Not applied, deliberately:

- `check_time_zones.py`. It is a data-quality check over the export, run
  locally, and a hidden row with a broken time zone is still a broken time
  zone. It prints zone names and counts, not activity content.
- `check_tracking_ids.py`. Its own case, below.

## The count travels with the numbers

Per file during the ETL run, in the existing log line style:

    internal: 412 rows, 7 excluded (hide from public)

In `meta.json` (`process_cplan.py:1522`), which already carries `row_counts`
and is what the dashboard reads for its refresh stamp. A sibling
`excluded_counts` keyed the same way, so any consumer can state the exclusion
without recomputing it.

In the calendar report summary, the dashboards, and — most importantly — in the
agent pack's own prose and in MCP answers. An agent that says "there are 12
activities in March" while 3 were excluded is confidently wrong, and the pack
already has the mechanism for exactly this: it tells the agent in plain text
what it must not claim, the way it does for the GEB/GEB-1 field it cannot
resolve (`agent_pack.py:1426`). The same paragraph, for exclusions.

**The count is reported at total level only** — never per cell, per filter, per
week or per region. "3 excluded" across a quarter says almost nothing. "3
excluded" in one region in one week is close to a statement about what is
happening there, and a number that precise turns the safeguard into a signal.

## The tracking-ID check is its own case

It reads the exports directly and answers "does this ID exist". A hidden
activity does exist, and reporting it as `missing` would be a wrong answer of
the most expensive kind.

So the check keeps hidden rows in its index and gives them a third status,
`excluded`, distinct from both `found` and `missing`. It carries no title, no
description, no lead — the ID and the status, nothing more.

This is a deliberate, bounded disclosure: whoever runs the check has the source
data anyway. But the result file travels. So when a run writes a result
containing excluded rows, it says so on the way out:

    Result written to …\CPLAN_trackids_2026_08_17.xlsx
    2 of 14 rows are excluded activities — check before forwarding this file.

The warning is in the terminal, not in the workbook. A workbook that explains
its own sensitivity is a workbook that has already been forwarded.

## What this deliberately does not do

- **No per-user visibility.** Hidden is hidden for every consumer of the
  pipeline. The Postgres RLS already in place governs *who may use the portal*;
  it is not repurposed here to hold rows this pipeline has decided not to carry.
- **No redaction mode.** Keeping the rows with blanked fields was considered
  and rejected in favour of exclusion plus a count.
- **No retroactive cleanup.** Existing `communications.parquet`, the Postgres
  snapshot, previously built dashboards, agent packs and reports were produced
  before this rule and still contain the rows. Purging them is separate work,
  named in the follow-ups below rather than smuggled in here.

## Failure modes this must not have

| Failure | Guard |
|---|---|
| Column absent from an export, rows treated as public | Hard error naming the file |
| Column present, unset rows treated as hidden | Only a truthy value hides |
| Marker column reaches an output | `exclude_hidden` drops the column with the rows |
| A consumer silently inherits exclusion it should not have | Marking and excluding are separate calls |
| A total reported without its exclusion count | The count is part of every surface that reports a total |
| A hidden ID reported as never created | `excluded` is a third status in the tracking-ID check |
| An excluded-row result file forwarded unknowingly | The run warns on write |

## Testing

Test-first, in the suites that already cover each surface.

- `transform()` maps the encoded header, and maps it through the prefix rule so
  the truncated tail of the internal name is irrelevant.
- Truthy variants (`TRUE`, `True`, `1`, `Yes`) hide; empty and `FALSE` do not.
- A file without the column raises, and the message names the file.
- `exclude_hidden` returns both the reduced frame and the count, and the marker
  column is gone from the frame it returns.
- The ETL's per-file log and `meta.json` carry the count.
- A hidden activity does not appear in the Parquet output.
- The tracking-ID check reports a hidden ID as `excluded`, never as `missing`,
  and warns when writing a result that contains one.
- The agent pack's prose names the exclusion count.

## Follow-ups, not part of this work

1. Purging the rows already in `communications.parquet`, in the Postgres
   snapshot, and in previously built artefacts.
2. Confirming on the work machine whether the unset state is `FALSE`, empty, or
   both, and whether both archive exports carry the column.
