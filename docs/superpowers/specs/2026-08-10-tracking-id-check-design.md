# Ask the export whether an ID exists, instead of assuming it does

**Date:** 2026-08-10
**Status:** draft

## Problem

Tracking IDs travel by hand. They arrive in a mail, in a slide, in a list
someone pasted from a planning sheet, and the question asked of them is always
the same one: are these activities actually in the export, or am I looking at
IDs that were never created, were renamed, or live in a list this pipeline does
not read?

Today that question is answered by opening the CSVs and searching. That works
for three IDs and stops working at thirty, and it answers only half the
question. A search that comes back empty says "not in this file". It does not
say whether the ID is absent because the activity does not exist, or because
the channel suffix is wrong by three letters — and those two answers lead to
completely different next steps.

The repository already has the shape for this. `check_time_zones.py` reads the
same exports read-only, prints a verdict, and exits non-zero when the answer is
bad. This is the second instance of that pattern, not a new one.

## What counts as a match

A match is an exact match on `tracking_id`, after stripping surrounding
whitespace and upper-casing both sides. Nothing else counts as found. An ID is
an identifier; a tool that reports "close enough" as present is worse than no
tool, because the report then has to be re-verified by hand.

But an unmatched ID is where the useful work is, so each one is put through a
ladder of near-miss searches and the first hit is reported as a hint:

| | Looks for | Reads as |
|---|---|---|
| 1 | Same pack ID and same activity number, different channel abbreviation | The activity exists; the channel suffix is wrong |
| 2 | Same pack ID (`CLUSTER-PACKNUM`) | The pack exists; this activity within it does not |
| 3 | Edit distance 1 over the whole ID | A typo — one character off |

The ladder stops at the first hit. A hint is never a verdict: the row still
reads `missing`, and the hint sits in its own column.

Malformed input is its own answer. An ID that does not split into the five
parts `CLUSTER-PACKNUM-YYMMDD-ACTNUM-CHANNEL` cannot be looked up on rungs 1
and 2, and saying so is more useful than silently falling through to rung 3.

## Where it looks

`find_input_dir()` — the OneDrive sync folder first, the local `pipeline/input`
fallback second — exactly as the ETL resolves it, so the check reads what a
refresh would read and cannot disagree with it by looking somewhere else.

Within that folder, the four activity exports only:

    internal, internal_archive, external, external_archive

`tracking_id` lives on activities. `CommunicationPacks`, the channel lists and
`TrackingCluster` carry pack, channel and cluster identifiers, and searching
them would let a pack ID report as a found activity. Archives are included
because an archived activity is still an activity that existed, and "was it
ever created" is the question being asked.

Each file goes through `read_csv_auto()` and `transform()`. `transform()` is
what turns the SharePoint-encoded column headers into `tracking_id`, and it is
also what folds the export's long-standing `Tacking ID` typo variant into the
same column. Reading the raw header would miss every row in whichever file
carries the typo that week.

## What it reports

A header with the three numbers that matter — searched, found, missing — and
then a table of **the missing IDs only**, with their hint. The found ones stay
a number.

This is deliberate. The list of IDs is something the user already has; printing
it back sorted into two piles makes them read forty rows to find the three that
matter. `-All` prints every row for the times when the full picture is wanted.

If the same ID appears twice in the input file it is looked up once, and the
duplication is named in the header rather than shown as two identical rows.

`-Csv <path>` writes every row regardless of `-All`, because a file is read by
a spreadsheet and not by a person:

    id, status, source_file, sp_id, activity_name, hint

`status` is `found` or `missing`. For a found ID, `source_file` names which of
the four exports it came from and `sp_id` / `activity_name` make it
identifiable; for a missing one those three are empty and `hint` carries the
ladder result.

Exit code 0 only when every searched ID was found. Everything else — a missing
ID, an unreadable input file, no activity export in the folder — exits 1, and
the report above says which. This matches `check_time_zones.py`, whose launcher
already treats non-zero as "read the report".

## Interface

    pipeline/scripts/check_tracking_ids.py     the check
    trackids.ps1 / trackids.cmd                the launcher, double-clickable

```
.\trackids.ps1 -Ids "C:\path\to\my-ids.txt"
.\trackids.ps1 -Ids ".\ids.txt" -All -Csv ".\result.csv"
.\trackids.ps1 -Ids ".\ids.txt" -InputDir "C:\other\Input"
```

`-Ids` is required. The file is one ID per line; blank lines and lines starting
with `#` are ignored, so a list can carry its own headings. The launcher
resolves Python the same way every other launcher in the repository does —
`CPLAN_PYTHON`, then an active virtualenv, then the repo-local `.venv`.

## Testing

`tests/test_check_tracking_ids.py`, against CSVs the test writes itself. The
check must not need a corporate OneDrive to be testable, and on a machine
without one the fixtures are the only way to test it at all.

What the tests have to pin down:

- an exact match found, across all four exports, with the right `source_file`
- whitespace and case differences still matching
- each rung of the near-miss ladder producing its own hint, and rung 1 winning
  when both rung 1 and rung 2 would hit
- a malformed ID reported as malformed rather than silently unmatched
- duplicates in the input counted once
- blank and `#` lines ignored
- the CSV carrying found and missing rows when `-All` was not given
- exit 0 only when nothing is missing

## What this is not

It does not answer the reverse question — which exported activities are absent
from the list. That is a different job with a different report, and the export
has thousands of rows to the list's dozens.

It does not read the DuckDB database or the Parquet output. The question is
about the source CSVs, and a check that reads the processed data would go quiet
exactly when the pipeline is the thing that is broken.

It writes nothing except the CSV it is explicitly asked for.
