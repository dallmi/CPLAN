# Calendar report — design

Status: 2026-07-30

An `.xlsx` report over internal and external communication activities, read
directly from the SharePoint CSV exports in the OneDrive sync folder. The core
sheet is a calendar matrix: rows are planning dimensions, columns are quarters
that expand into months that expand into ISO weeks. Six further sheets carry the
metrics a planner needs to act on what the matrix shows.

## Why this exists

The studio already exports activities and packs ([`pipeline/studio/xlsx.js`](../../../pipeline/studio/xlsx.js)),
but both answer "what is in the list". Neither answers "how is the year loaded,
and for whom" — the question a planner opens a spreadsheet for.

Pack data in the source system is unreliable: `communication_pack_cpid` collapses
large parts of the portfolio into a handful of oversized buckets, so any roll-up
built on packs describes the whole portfolio rather than a planning unit (the
same effect is documented at [`analytics.js:278`](../../../pipeline/studio/analytics.js#L278)).
**Packs are therefore never a grouping dimension in this report.** They appear as
an attribute on the detail sheet and as a measured quality problem on the Data
Quality sheet. Every roll-up rests on division, region, time, audience and
senior-executive involvement instead — fields the source system fills reliably.

## Scope

In scope: a standalone Python script producing one workbook from the CSV
exports, with three filter criteria configurable in code.

Out of scope: any change to the studio, the API, the database, the daily sync,
or the existing `.xlsx` exports. No new UI. No chart objects in the workbook.

## Data source

The script reuses the ETL's read path from
[`pipeline/scripts/process_cplan.py`](../../../pipeline/scripts/process_cplan.py)
rather than the database, so no Postgres instance, API process or sync run is
needed:

- `find_input_dir()` — corporate OneDrive first (`~/OneDrive - *` on Windows,
  `~/Library/CloudStorage/OneDrive-*` on macOS), falling back to
  `pipeline/input/`.
- `find_input_files()` — the four activity globs: `InternalCommunicationActivities*.csv`,
  `ExternalCommunicationActivities*.csv` and their `…Archive*.csv` counterparts.
- `read_csv_auto()` then `transform(df, source_type=…)` — decode and map column
  names, resolve SharePoint lookup JSON (multi-value fields arrive comma-joined,
  e.g. `"IB, P&C"`), strip HTML from `bod_geb`, parse dates.

### Required refactor

Merging the four files — appending the archive lists, setting `is_archived`,
de-duplicating by `tracking_id` keeping the most recent `modified` — currently
sits inline in `main()` at
[`process_cplan.py:1071-1105`](../../../pipeline/scripts/process_cplan.py#L1071-L1105).
It moves into a module-level function:

```python
def load_activities(files) -> pd.DataFrame:
    """Read, transform, merge and de-duplicate the four activity CSVs."""
```

`main()` calls it and behaves identically; the report calls the same function.
Two definitions of "the activity dataset" would drift, and the report would
quietly disagree with the dashboard about how many activities exist.

### Consequences of reading CSVs rather than the database

- Field names follow the ETL, not the ORM: `is_archived`, not `is_archive`.
- **Activities created only in the studio are invisible.** They live in the
  database and are never written back to SharePoint. For a retrospective year
  this is immaterial — that data is entirely SharePoint-sourced. For a
  forward-looking run it is a real gap, so the Executive Summary names every
  source file it read together with that file's modification time.

## Configuration

A single `ReportConfig` instance at the top of
`pipeline/scripts/report_calendar.py` is the only thing a user edits:

```python
CONFIG = ReportConfig(
    date_from=date(2025, 1, 1),      # filters on start_date, inclusive
    date_to=date(2025, 12, 31),      # inclusive
    executives="any",                # "any" | "with" | "without"
    audience_bands=None,             # None = all bands; else a tuple of band labels
    include_unknown_audience=True,   # applies only when audience_bands is set
    include_archived=True,           # archived is a view-size workaround, not a status
    detail_rows=True,                # activity rows under each dimension value
    breakdown_fields=("business_division", "region"),
)
```

All three criteria are **hard filters**: a row that fails any of them is absent
from every sheet. `ReportConfig.__post_init__` validates the date order and that
every named band is a known band, so a typo fails at startup rather than silently
filtering everything away.

`breakdown_fields` is what makes a fourth dimension (channel, priority, lead
team) a one-line change.

The only CLI arguments are `--out` (override the output path) and `--input-dir`
(override input discovery, used by the tests). The criteria deliberately have no
CLI form: they belong to the report definition, and a run must be reproducible
from the file alone.

## Derived values

Four derivations, each one function, each independently tested.

### Reach classification

A mutually exclusive bucket per activity, so the Reach block sums to the total:

```python
GROUP_WIDE_MIN_DIVISIONS = 3
GLOBAL_REGION_TOKENS = {"global", "worldwide", "all regions"}
```

1. `len(divisions) >= GROUP_WIDE_MIN_DIVISIONS` or any region in
   `GLOBAL_REGION_TOKENS` → **Group-wide**
2. `len(divisions) > 1` → **Multi-division**
3. `len(divisions) == 1` → **Single division**
4. no division but at least one region → **Regional only**
5. neither → **Unclassified**

Divisions and regions are split on commas and trimmed. Both constants are
guesses against the live vocabulary and are expected to be adjusted after the
first real run; `Unclassified` exists so that gaps are visible rather than
absorbed into a neighbouring bucket.

### Audience band

`audience` is heterogeneous: raw counts from some sources (`"250"`, `"12000"`),
band labels from the studio (`"10–50k"`). One function maps both onto the five
known bands and everything else onto `Unknown`:

```python
AUDIENCE_BANDS = ("< 1000", "1–10k", "10–50k", "50–100k", "> 100k")
```

Numeric values use the band boundaries 1 000 / 10 000 / 50 000 / 100 000. Band
labels are matched after normalising dashes and whitespace. This concentrates
the mapping assumption already recorded in the knowledge base into one place
instead of spreading it across seven sheets.

### Senior-executive involvement

`bod_geb` is a rich-text field, HTML-stripped by the ETL
([`process_cplan.py:509`](../../../pipeline/scripts/process_cplan.py#L509)).
Involvement means non-empty after stripping. The local synthetic seed has this
field empty on every row, so the filter is exercised only by the CSV fixtures
described under Testing.

### Week grid

The grid covers every ISO week containing at least one day of
`[date_from, date_to]` — derived from the window, not from a calendar year, so
every activity that survives the filter is guaranteed a column. For
2025-01-01 … 2025-12-31 that is 2025-W01 through 2026-W01, 53 columns.

A week belongs to the month containing its **Thursday** (ISO 8601), and a month
to its quarter. Consequently the grid for a full year can carry a thirteenth
month column; this is correct, not a bug, and is stated on the Glossary sheet.

Every activity is counted **once, in the ISO week of its `start_date`**. Nothing
is spread across its runtime: a count that is also a duration cannot be summed,
and the totals are the point of the sheet. Rows without a `start_date` are
excluded and reported as an explicit figure, never dropped silently.

## Workbook

Seven sheets. Build order matches reading order.

Every share, ratio and subtotal is written as an **Excel formula with a zero
guard** (`=IF(B10=0,0,B6/B10)`) referencing tracked row numbers, not as a value
computed in Python. The reader can click any figure and see where it came from,
and the workbook stays internally consistent if a row is deleted.

Two kinds of figure stay literal: raw counts, and order statistics (median, min,
max, longest run of zero weeks) — the latter because an Excel formula for them
would need the underlying series present on the sheet, which these sheets do not
carry. Where a literal appears next to formulas, the Glossary names how it was
derived.

Where a total row carries a ratio, the ratio is **recomputed from the totals**,
never summed down the column — an average of averages is wrong and looks right.

### 1. Executive Summary

Two columns, label and value, in six banded sections. Shares appear in the label
cell rather than claiming a column, so the value column stays a clean column of
counts:

```
=TEXT(IF(B$6=0,0,B7/B$6),"0%") & "  Internal"
```

- **REPORT** — period, weeks covered, each source file with its modification
  time, applied criteria, rows read, rows in scope, rows excluded by each
  criterion, rows excluded for a missing start date.
- **VOLUME** — activities in scope; internal/external split; the five reach
  buckets.
- **LOAD** — median activities per week, peak week and its count, weeks with
  zero activities, longest run of zero weeks, share of the year falling in the
  five busiest weeks.
- **LEADERSHIP & AUDIENCE** — activities with senior-executive involvement,
  activities in the two largest audience bands, activities with an unknown band.
- **PLANNING DISCIPLINE** — median lead time in days (`start_date` − `created`),
  activities planned at under seven days' notice, activities missing either date.
- **DATA QUALITY** — median planning completeness, activities without a pack
  link, activities missing division, region or audience.

### 2. Calendar

The matrix. Two header rows:

| | A | B | C | D | E … |
|---|---|---|---|---|---|
| 1 | Scope / activity | Total | Q1 2025 | Jan 2025 | W01 |
| 2 | *(merged)* | *(merged)* | Total | Total | 30 Dec |

Column order per quarter: the quarter total column, then for each of its months
the month total column, then that month's week columns. Outline levels: quarter
0, month 1, week 2, with `summaryRight = False` so each summary column sits to
the left of the group it summarises. The file opens collapsed to quarters; one
click gives months, another gives weeks. Rows freeze below the header, columns
freeze after B.

Row blocks, `summaryBelow = False` so a block header sits above its members:

1. **ALL ACTIVITIES** — level 0.
2. **BY REACH** — level 0 section, five level-1 rows (the reach buckets). This
   block is a partition, so its header row is a genuine `SUM` of its members.
3. **BY DIVISION** — level 0 section, one level-1 row per division value plus
   `Not specified`.
4. **BY REGION** — same shape.

Blocks 3 and 4 **overlap by construction**: an activity naming two divisions
appears in both rows. Their header rows therefore carry a Python-computed
distinct count, never a `SUM`, and the header label says
`multiple values possible`. Getting this wrong would produce a total larger than
the portfolio, printed in bold.

With `detail_rows=True`, each level-1 row is followed by its activities at
level 2, sorted by start date, name indented by two spaces so the nesting
survives a copy-paste out of the outline.

Cell rules:

- Week cells on level-1 and level-2 rows: literal counts (an activity row
  carries `1` in its start week and nothing elsewhere).
- Month, quarter and Total cells on **every** row: `SUM` over the cells they
  aggregate. Horizontal aggregation is always a formula.
- Vertical aggregation is a formula only in block 2, where it is arithmetically
  valid.

No colour scale. Column B carries data bars, applied per block over the
space-separated ranges of that block's level-1 rows, so the bars compare like
with like instead of being flattened by the ALL ACTIVITIES row.

### 3. Data Quality

Three blocks. This sheet is the one that turns the pack problem into a number.

- **Field completeness** — one row per field (the eight planning-completeness
  fields, plus division, region, audience, `bod_geb`, pack link): filled,
  missing, `% missing` as a formula.
- **Pack coverage** — activities with and without a pack link and their shares;
  distinct packs; packs holding exactly one activity; 2–10; 11–50; more than 50;
  the largest pack's size. The oversized buckets are the measurable form of the
  data problem.
- **Record anomalies** — no start date, end date before start date, duplicate
  `tracking_id`, blank `tracking_id`, archived rows.

### 4. Audience & Executives

- Audience band × quarter matrix, rows the five bands plus `Unknown`, with a
  Total column and a `% of total` formula column.
- Large-audience activities (the two largest bands) per month, with each month's
  share of that month's volume.
- Senior-executive involvement by quarter: count and share.
- Senior-executive involvement by division: count, share of all
  executive-involved activities, and share of that division's own volume. The
  third figure is the one that matters — a large division with many such
  activities may still be using that access less than a small one.

### 5. Mix & Lead Time

- Channel × quarter, priority × quarter, and internal/external × quarter, each
  with a Total column and a `Δ Q4−Q1` column (an absolute difference of counts,
  labelled as such).
- Lead time by division: activities with both dates, median days, share planned
  at under seven days' notice, minimum and maximum.

Priority is ranked with the same rule the studio uses
([`analytics.js:219`](../../../pipeline/studio/analytics.js#L219)): a leading
integer wins (1 is most urgent), the words `Critical/High/Medium/Low` are the
fallback, anything else lands mid-rank. Both vocabularies are live at once and
matching only the words has already produced a metric reading zero against
thousands of matching records.

### 6. Activities

The flat detail list of everything in scope, with an autofilter and a frozen
header, so every figure elsewhere is traceable to rows: tracking ID, activity,
type, channel, start, end, ISO week, quarter, priority, lead, lead team, target
audience, audience band, divisions, regions, reach class, senior executives
(Yes/No), pack ID, campaign, pillars, completeness %, lead time in days,
archived.

### 7. Glossary

Definitions and caveats, gridlines off: the five reach buckets and their
constants; the audience band mapping and its unverified assumption; counting by
start-date week; the Thursday rule and the possible thirteenth month column; lead
time; planning completeness; what "in scope" means; why packs are not a grouping
dimension; and that studio-only activities are not in the file.

### Graceful degradation

Every sheet checks for the columns it needs and writes one explanatory cell
instead of raising if they are absent — `"No audience data available (audience
column missing)"`. A source export missing a column must produce a workbook with
one honest gap, not a traceback.

## Formatting

A shared style module carries the palette and six primitives —
`write_header_row`, `write_data_rows`, `write_section_header`, `write_kpi_row`,
`write_total_row`, `write_formula` — plus `finalize_sheet` (freeze panes and
content-based column auto-fit clamped to 10–40 characters). Every sheet is
composed from these; that uniformity is the reason the workbook reads as one
document.

Palette from the corporate design system, matching what
[`xlsx.js`](../../../pipeline/studio/xlsx.js) already writes: dark grey header
band with white bold text, pastel `ECEBE4` section bands and total rows, zebra
striping, thin light-grey borders. Number formats `#,##0`, `0.0%`, `0.0`,
`YYYY-MM-DD`. The Executive Summary tab is the only one with a distinct tab
colour.

`openpyxl` does the writing. It supports nested column outlines, row outlines,
freeze panes, conditional formatting and merged cells; hand-rolling that in
OOXML would be several hundred lines for no gain. It is already present in the
repository virtualenv and joins the prerequisites in `README.md`.

## Module layout

```
pipeline/scripts/report_calendar.py   CONFIG block, CLI, orchestration
pipeline/report/config.py             ReportConfig dataclass and validation
pipeline/report/data.py               loading, filtering, derived columns, week grid
pipeline/report/style.py              palette and the write primitives
pipeline/report/calendar_sheet.py     the matrix
pipeline/report/table_sheets.py       the six flat sheets
pipeline/scripts/process_cplan.py     gains load_activities()
```

Splitting the matrix from the flat sheets keeps the one genuinely intricate
builder — nested column outlines, two header rows, mixed literal and formula
cells — in a file that can be read in one sitting.

Output goes to `pipeline/output/CPLAN_calendar_<date_from.year>_<YYYY_MM_DD>.xlsx`.
`.gitignore` covers `pipeline/output/` per file extension, not as a directory, so
`*.xlsx` has to be listed there alongside `*.parquet`, `*.json` and `*.html` —
without that line the workbook is a tracked file, and the Activities sheet is by
design a complete audit trail of real activity names, lead names, divisions,
regions, pack IDs and campaigns. Console output follows the ETL's existing
`log()` convention: a banner, one line per sheet, a final size report.

## Testing

`pytest`, alongside the existing suite. No database fixture.

`tests/test_report_data.py` covers the derivations in isolation: reach
classification across all five buckets and the constant boundaries; audience band
mapping for numeric strings, band labels, empty and junk values; the
executive-involvement predicate against HTML-stripped input; the week grid at
both year boundaries, including that 2025-12-31 lands in 2026-W01 and has a
column; the Thursday month attribution; and each of the three filters
independently.

`tests/test_report_workbook.py` runs the whole path end to end. The test writes
**raw** SharePoint-shaped CSVs into a temporary input directory — real source
column names, lookup JSON, multi-valued and empty divisions, a global region,
`bod_geb` set and empty, audience as number and as band label, rows without a
start date, and one row duplicated between the active and archive lists — then
reads the workbook back with `openpyxl` and asserts: the seven sheets exist;
column and row outline levels; that each quarter cell equals the sum of its
months and each month the sum of its weeks; that the Reach block sums to the
grand total while the Division block's header does not; that a filter removes
exactly the expected rows; and that a missing optional column produces the
explanatory cell rather than an exception.

No such raw-CSV fixture exists in the repository today — `process_cplan.py` has
never been tested against real input files. The builder is written to be
reusable for that.

`generate_seed.py` is not touched: it seeds the database, which this report does
not read.

## Assumptions to revisit after the first real run

- `GROUP_WIDE_MIN_DIVISIONS = 3` and `GLOBAL_REGION_TOKENS` are guesses against
  the live division and region vocabularies.
- The `audience` field is assumed to carry the "Estimated audience size" value.
  The knowledge base already flags this as unverified against the source system.
- Counting by start-date week ignores activity duration. If long-running
  activities turn out to matter, that is a change to the counting rule, not to
  the sheet layout.
- `Δ Q4−Q1` assumes the window spans four quarters. For a shorter window it
  compares the first and last quarter present, which the column header states.

## Deferred

A **Clashes** sheet — activities sharing a channel and a target audience within
a few days, with the severity grading from
[`analytics.js:233`](../../../pipeline/studio/analytics.js#L233) — is the
strongest remaining candidate and was consciously left out of this release. It
would require porting roughly forty lines of collision logic to Python, creating
a second definition of what a clash is; adding it later should come with a test
pinning the Python and JavaScript rules against the same fixture.
