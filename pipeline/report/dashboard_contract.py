"""What the agent produces for a board that is rendered rather than drawn.

Three boards are drawn by the agent from `dashboard_skill`. This one is not.
Its markup is frozen in `pipeline/dashboard/campaign-activity.template.html`
and rendered by `pipeline/scripts/report_dashboard.py`, byte for byte from a
data object -- so the agent's job is to produce that object, not a picture.

The trade is deliberate. Drawing is where a rule gets dropped: it took four
revision rounds to reach a conformant page, and one of them undid two
corrections an earlier one had made. Filling a form from cited lines is the
thing a retrieval agent is reliable at, and it is checkable -- every `Source:`
line here resolves against the pack generated in the same run, the same way
`tests/test_agent_pack.py` holds the board files to theirs.

Data-free, like the board catalogue: no figure, no period, no generation date.
It is rebuilt identically every run and re-uploaded only when the contract
changes.

The grain rule below is not a preference. `08-periods.csv` carries every
measure at year grain and the count alone at quarter grain, and
`01-summary.txt` describes the whole run because `agent_pack.pack_config`
drops the report's period on purpose. A board that took its total from one
grain and its leadership share from another would be mixing periods without
saying so, which is the one failure a management page must not have.
"""

CONTRACT_NAME = "contract-campaign-activity-overview.md"

CONTRACT_TEXT = """# Data contract — Campaign activity overview

This board is **rendered, not drawn**. Produce the data object below; a tested
renderer turns it into the page. Do not draw this board, and do not describe
what it would look like.

## What to return

One JSON object and nothing else — no prose above it, no commentary below it,
no code fence language other than `json`. Every field is required. A field you
cannot read from the pack is a field to say you cannot read, in a sentence
after the object, rather than a figure to estimate.

## One grain, one board

Every count in the object comes from **year grain** in `08-periods.csv`, for
the one year the reader asked about.

That is forced, not chosen. `08-periods.csv` carries every measure at year
grain and the activity count alone at quarter grain, and `01-summary.txt`
describes the whole plan rather than a period. So a quarterly version of this
board can state its volume and nothing else, and a board mixing a quarterly
total with a yearly leadership share would be comparing two different periods
without saying which.

Two fields are the stated exceptions, and both are whole-plan figures. They are
marked below and their labels on the page say so.

## The object

```json
{
  "eyebrow": "Communications portfolio · Management view",
  "title": "Campaign activity overview",
  "subtitle": "Where leadership intervention may be needed — and with which teams or audiences.",
  "period_label": "<the year, e.g. 2026>",
  "data_as_of": "<YYYY-MM-DD>",

  "activities_total": 0,
  "rows_read": 0,
  "lead_time_median_days": 0,
  "short_notice_activities": 0,
  "leadership_activities": 0,
  "large_audience_activities": 0,
  "internal_activities": 0,
  "external_activities": 0,

  "weeks": [{"commencing": "<D Mon>", "activities": 0}],
  "priorities": [{"label": "<source label>", "activities": 0}],
  "teams": [{"name": "<team>", "activities": 0}],
  "leadership_by_team": [{"name": "<team>", "share": 0.0}],

  "insights": {
    "timing": "", "priority": "", "ownership": "",
    "leadership": "", "reach": ""
  },

  "footer_notes": "Audience size is a planning estimate, never measured reach, and is used here only to band an activity as large. Scope is based on period overlap, not start date. Targets set by the Communications Leadership Team.",
  "footer_source": ["Source: CPLAN Agent (calendar, activities, breakdowns)",
                    "Powered by ECC Measurement & Insights"]
}
```

The first three fields and the last two are fixed text. Copy them exactly.

## Where every figure comes from

### period_label
The year you filtered on, as four digits. Not a range, not a quarter.

### data_as_of
Source: 01-summary.txt · REPORT · Data as of

### activities_total
Source: 08-periods.csv · block=TOTAL · grain=year · measure=activities

### rows_read — whole plan, not the year
Source: 01-summary.txt · REPORT · Rows read
The page prints this beside the total as "N excluded of M rows read", which is
the scope caveat your instructions require beside any stated total.

### lead_time_median_days — whole plan, not the year
Source: 01-summary.txt · PLANNING DISCIPLINE · Median lead time (days)
The only lead-time statistic the pack states, and it is a median in days. Never
convert it to an average or to weeks.

### short_notice_activities
Source: 08-periods.csv · block=TOTAL · grain=year · measure=short_notice
Counts a lead time *under* the pack's short-notice threshold. The page words
the card from the same number, so do not reword it.

### leadership_activities
Source: 08-periods.csv · block=TOTAL · grain=year · measure=with_executives

### large_audience_activities
Source: 08-periods.csv · block=TOTAL · grain=year · measure=large_audience
The top two audience bands. Not a contact threshold — the pack bands an
activity, it never compares one to a number of contacts.

### internal_activities and external_activities
Source: 08-periods.csv · block=source_type · grain=year · measure=activities
Two rows, one per value. They partition the total.

### weeks
Source: 04-calendar.csv · block=TOTAL
One entry per week of the year that has a row, in date order. `commencing` is
the `week_start` date written as day and short month, e.g. `17 Aug`.
`activities` is the row's count. Weeks with no activity have no row and are
left out here too.

### priorities
Source: 08-periods.csv · block=priority · grain=year · measure=activities
One entry per value, ordered most urgent first — the source's numbered labels
lead with their number, so ordering is by that number. **Print the source's own
label.** Do not translate it, shorten it, or fold it onto Critical / High /
Medium / Low: the numbering carries the meaning for the code and the wording
carries it for the reader.

### teams
Source: 08-periods.csv · block=lead_team · grain=year · measure=activities
Ordered by count, largest first.

### leadership_by_team
Source: 08-periods.csv · block=lead_team · grain=year · measure=with_executives; 08-periods.csv · block=lead_team · grain=year · measure=activities
A share per team: involvement divided by that team's activities, as a decimal
between 0 and 1. Two cited figures divided, which is allowed — both are audited
counts. Ordered by share, highest first.

### insights
One sentence per panel, in your own words, saying what the reader should do
about what the panel shows. Name no figure the panel does not already plot.
Leave a string empty to drop that panel's insight line.

## Before you return the object

1. Does every count come from the same year?
2. Are `rows_read` and `lead_time_median_days` the only whole-plan figures?
3. Do `internal_activities` and `external_activities` sum to `activities_total`?
4. Do the `priorities` counts sum to `activities_total`?
5. Do the `teams` counts sum to `activities_total`? If not, say so in a
   sentence after the object — the renderer reports the residual and a reader
   deserves to know it was expected.
6. Is every priority label the source's own?
7. Is the object valid JSON with no trailing commas?

An object failing one of these is corrected, not explained.
"""

CONTRACTS = {CONTRACT_NAME: CONTRACT_TEXT}
