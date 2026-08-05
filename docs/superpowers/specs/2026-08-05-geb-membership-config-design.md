# Separating GEB from GEB-1 with a local membership list

**Date:** 2026-08-05
**Status:** approved

## Problem

The source column `BOD / GEB` carries people at GEB *and* GEB-1 level, mixed,
with nothing in the data marking which is which. Commit `00a5a16` stopped the
report claiming otherwise — every label now reads "GEB/GEB-1" — but the report
still cannot answer the question the labels now raise: *which* of these people
are on the GEB.

The distinction cannot be derived. It has to be supplied.

## Decisions

**A local list names the GEB members; everyone else in the field is GEB-1.**
The list is the only source of the distinction. Absent it, the report behaves
exactly as it does today.

**The list never enters git.** It names real people, which the repository rules
forbid. It lives in a gitignored file beside a committed `.example` carrying
placeholders — the pattern `cplan.config` / `cplan.config.example` already
establishes.

**The file sits at the repository root, not in `data/`.** `/data/` is ignored
wholesale, and git cannot re-include a file inside an ignored directory, so an
example placed there could not be committed. Root keeps the pair together.

**Either the email or the display name identifies a member.** Email is stable
across spelling, titles and name changes; the display name is what the pipeline
demonstrably has today. Whether the export carries emails for this column at all
is unverified — the only local database has `bod_geb` filled at 0%, and the real
CSVs live on the corporate machine. Accepting both keys means the feature cannot
fail on that unknown, whichever way it resolves.

**The split is a grouping, not a filter.** `--executives any|with|without` keeps
its present meaning of GEB/GEB-1. A GEB-only workbook is out of scope; it would
be a small follow-up.

**The two levels partition, never overlap.** Each person appears under exactly
one heading, and the two counts sum to today's single figure. A design that
showed a GEB block *beside* the existing combined block would print the same
person with the same count twice, and anyone adding the blocks would double-count
the 13.

**An unmatched configuration entry is reported, not swallowed.** A typo in the
list and a person genuinely at GEB-1 level produce the identical outcome: someone
quietly filed under GEB-1. Only the configuration side can distinguish them — an
entry that matched nothing is either a typo or a member with no activities. That
number is printed rather than left for the reader to notice.

## The configuration file

`geb-members.csv` at the repository root, gitignored.
`geb-members.csv.example` beside it, committed:

```csv
email,name
geb.member.01@example.invalid,"Placeholder-01, Anna"
geb.member.02@example.invalid,"Placeholder-02, Bernd"
...
geb.member.13@example.invalid,"Placeholder-13, Mira"
```

Two columns, header required.

- `email` — the address as the directory holds it. May be empty.
- `name` — **exactly as the source writes it: `Last, First`.** The quotes are
  required because of the comma. May be empty.
- At least one of the two must be non-empty on every row. A row with neither is
  a broken file, not a silently skipped line.

The file's length is whatever it is. Thirteen is today's fact about the board,
not a constant the code enforces.

### Failure modes

| Condition | Behaviour |
|---|---|
| File absent | One combined `BY GEB/GEB-1` block, exactly as today. No error, no warning. |
| File present, unreadable or missing a required column | Abort with a message naming the file and the problem. |
| A row with neither email nor name | Abort. |
| A name in `bod_geb` matching no entry | GEB-1. This is the normal case. |
| A configuration entry matching nothing | Counted and reported on Data Quality. |

Aborting on a malformed file rather than falling back is deliberate: a silent
fallback would produce a workbook that looks correct and is wrong, which is the
failure this whole change exists to prevent.

## Matching

A person named in `bod_geb` is GEB when **either** key matches — their email
equals some configured email, **or** their normalised name equals some
configured name. A plain OR across the two keys, not a precedence rule: either
one alone is sufficient, and neither is consulted only when the other is absent.

The alternative — "email decides whenever both sides have one" — was rejected. It
makes a stale address in the list silently outrank a correct name, which is the
same class of silent wrong answer this change exists to remove.

Name normalisation reuses `derive.person_name()`, the function the report already
applies, so `Last, First` and `First Last` compare equal. Both comparisons are
case-insensitive and ignore surrounding whitespace. No fuzzy matching: a
near-miss must surface as an unmatched entry rather than resolve to a confident
guess.

**Known limitation.** Two different people sharing a display name would both
match a name-only entry, and nothing in the data could distinguish them. Giving
every entry an email removes the risk. The unmatched-entry count does not catch
this — it finds entries that match too little, never one that matches too much.

`bod_geb` joins `SP_PERSON_COLUMNS` in the ETL, which produces `bod_geb_email`
from the SharePoint `Claims` identity the same way `lead_email` is produced
today. The column is added after the `keep` projection, so it needs no schema
change; the report reads the CSVs directly through `load_activities` and never
touches the database.

If that column arrives empty — because the source is a rich-text field rather
than a person picker — every match falls to the name path and the feature still
works. That is the point of the fallback.

## What changes in the workbook

| Sheet | Today | After |
|---|---|---|
| Calendar | `BY GEB/GEB-1` | `BY GEB` and `BY GEB-1` |
| Audience & leadership | `ACTIVITIES BY GEB/GEB-1 MEMBER` | `ACTIVITIES BY GEB MEMBER` and `ACTIVITIES BY GEB-1 MEMBER` |
| Executive Summary | `With GEB/GEB-1 involvement` | plus `With GEB involvement` beneath it |
| Data Quality | — | `GEB list entries never matched` |

Both sheets split, because two sheets grouping the same field differently would
contradict each other.

The calendar's activity detail rows are unchanged: they name everyone from
`bod_geb` without marking a level. The level is a property of the block a person
sits in, and repeating it per row would add width for no answer.

The Glossary gains `GEB` and `GEB-1`, each within the standing 110-character
ceiling, and the existing `GEB/GEB-1` entry states that it is the two combined.

**Every row in this section is conditional on the file being present.** Without
it there is no second block, no `With GEB involvement` line, no Data Quality row
and no new Glossary entries — the workbook is identical to today's, sheet names
and block titles included. Defining terms the workbook never uses would be its
own small lie.

## Testing

Rung 1. New coverage:

- **Loader** — email match, name match, `Last, First` against `First Last`, case
  and whitespace differences, empty email column, empty name column, absent
  file, missing header, a row with neither field.
- **Partition** — the two block totals sum to the combined figure; no person
  appears under both; a person named on two activities counts twice in their own
  block and not at all in the other.
- **Unmatched reporting** — a configured entry nobody carries is counted; a
  correct list reports zero.
- **Absence** — with no configuration file the workbook equals today's, sheet
  names and block titles included. This is the regression that matters most,
  because it is the state every machine without the file is in.

## Out of scope

- A `--executives geb-only` filter, and any GEB-only workbook.
- Distinguishing levels *within* GEB-1.
- Any database schema change; the report path is CSV-driven.
- Storing the membership list anywhere shared. It is per-machine, by design.
