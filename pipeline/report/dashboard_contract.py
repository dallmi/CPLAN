"""What the agent returns for a board that is rendered rather than drawn.

The head of communications overview is not drawn. Its markup is frozen in
`pipeline/dashboard/campaign-activity.template.html` -- the page is titled
"Campaign activity overview" -- and `pipeline/scripts/report_dashboard.py`
renders it byte for byte from a data object. So the agent supplies the object,
not the picture, and this file says which pack line fills which field.

The trade is deliberate. Drawing is where a rule gets dropped: it took four
revision rounds to reach a conformant page, and one of them undid two
corrections an earlier round had made. Filling a form from cited lines is what
a retrieval agent is reliable at, and unlike a drawing it is checkable -- every
`Source:` line here resolves against a pack generated in the same run, through
the resolver the board citations already use.

Data-free, like the board catalogue: no figure, no period, no generation date.
Rebuilt identically every run, re-uploaded only when the contract changes.

The grain rule below is the part that would fail silently. `08-periods.csv`
carries the count and three shares at quarter grain and every measure at year
grain, and `01-summary.txt` describes the whole plan because
`agent_pack.pack_config` drops the report's period on purpose. A board taking
its total from one grain and its leadership share from another would put two
periods side by side and print neither, which is the one failure a management
page must not have.
"""

CONTRACT_NAME = "contract-head-of-communications-overview.md"

CONTRACT_TEXT = """# Data contract — Head of communications overview

**The decision:** where do I intervene, and with whom?

This board is **rendered, not drawn**. Produce the data object below; a tested
renderer turns it into the page, which is titled "Campaign activity overview".
Do not draw this board, and do not describe what it would look like.

## What to do with it

Build the object, write it beside you, and draw the board:

```python
import json, pathlib
data = { ... the object below ... }
pathlib.Path("board.json").write_text(json.dumps(data), encoding="utf-8")

src = pathlib.Path("14-board-draw.txt").read_text(encoding="utf-8")
ns = {}
exec(compile(src, "14-board-draw.txt", "exec"), ns)
path, face, weights = ns["draw_from_json"]("board.json", "board.png")
print(path, face, weights)
```

Then show `board.png` in the chat.

`14-board-draw.txt` is the renderer the page itself is drawn with. Do not
rewrite it, do not draw the board yourself, and do not substitute a chart of
your own if it fails — say what failed. It refuses rather than returning an
image when two pieces of text would overlap, which is a real answer and a
picture with a sentence lying across a label is not.

If the file is not beside you, list your working directory, say what you found,
and stop.

## The object itself

One JSON object and nothing else — no prose above it, no commentary below it,
no code fence language other than `json`. Every field is required. A field you
cannot read from the pack is a field to say you cannot read, in a sentence
after the object, rather than a figure to estimate.

## One grain, one board

Every count in the object comes from **quarter grain** in `08-periods.csv`, for
the one quarter the reader asked about.

One field is the stated exception and it describes the **whole plan**, not the
quarter. It is marked below.

`08-periods.csv` carries the activity count and three shares at quarter grain.
Anything else you need by quarter is not there, and the year-grain row beside
it is a different period wearing the same block name.

## The object

```json
{
  "eyebrow": "Communications portfolio · Management view",
  "title": "Campaign activity overview",
  "subtitle": "Where leadership intervention may be needed — and with which teams or audiences.",
  "period_label": "<e.g. 2026 Q3 · 01 Jul – 30 Sep>",
  "data_as_of": "<YYYY-MM-DD>",

  "activities_total": 0,
  "activities_in_plan": 0,
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
The quarter you filtered on, with its dates, e.g. `2026 Q3 · 01 Jul – 30 Sep`.
The quarter labels in the periods file read `2026-Q3`; write the readable form
here and filter on the file's.

### data_as_of
Source: 01-summary.txt · REPORT · Data as of

### activities_total
Source: 08-periods.csv · block=TOTAL · grain=quarter · measure=activities

### activities_in_plan — whole plan, not the quarter
Source: 01-summary.txt · VOLUME · Activities in scope
The page prints the quarter as a share of this. It is not an exclusion count:
most of the difference is the other quarters, and calling it excluded would say
a filter rejected rows it never saw.

### short_notice_activities
Source: 08-periods.csv · block=TOTAL · grain=quarter · measure=short_notice
Counts a lead time *under* the pack's short-notice threshold. The page words
the card from the same number, so do not reword it.

### leadership_activities
Source: 08-periods.csv · block=TOTAL · grain=quarter · measure=with_executives
Both levels together. The source field holds GEB and GEB-1 and nothing in it
separates them, so never call this figure "the GEB". Only an `executives_geb`
block separates the two, and only when a member list was supplied — when it is
present it is a subset of this measure and never a second figure to add to it.
The page says "executive board participation" for the same reason.

### large_audience_activities
Source: 08-periods.csv · block=TOTAL · grain=quarter · measure=large_audience
The top two audience bands. Not a contact threshold — the pack bands an
activity, it never compares one to a number of contacts.

### internal_activities and external_activities
Source: 08-periods.csv · block=source_type · grain=quarter · measure=activities
Two rows, one per value. They partition the total.

### weeks
Source: 04-calendar.csv · block=TOTAL
Every week of the quarter that has a row, in date order. `commencing` is the
`week_start` date written as day and short month, e.g. `17 Aug`. `activities`
is the row's count. Weeks with no activity have no row and are left out here
too.

### priorities
Source: 08-periods.csv · block=priority · grain=quarter · measure=activities
One entry per value, ordered most urgent first — the source's numbered labels
lead with their number, so ordering is by that number. **Print the source's own
label.** Do not translate it, shorten it, or fold it onto Critical / High /
Medium / Low: the numbering carries the meaning for the code and the wording
carries it for the reader.

### teams
Source: 08-periods.csv · block=lead_team · grain=quarter · measure=activities
Ordered by count, largest first.

### leadership_by_team
Source: 08-periods.csv · block=lead_team · grain=quarter · measure=with_executives; 08-periods.csv · block=lead_team · grain=quarter · measure=activities
A share per team: involvement divided by that team's activities, as a decimal
between 0 and 1. Two cited figures divided, which is allowed — both are audited
counts. Ordered by share, highest first.

### insights
One sentence per panel, in your own words, saying what the reader should do
about what the panel shows. Name no figure the panel does not already plot.
Leave a string empty to drop that panel's insight line.

## Before you return the object

1. Does every count come from the same quarter?
2. Is `activities_in_plan` the only whole-plan figure?
3. Is `activities_in_plan` larger than `activities_total`? A period cannot be
   bigger than the plan holding it.
4. Do `internal_activities` and `external_activities` sum to `activities_total`?
5. Do the `priorities` counts sum to `activities_total`?
6. Do the `teams` counts sum to `activities_total`? If not, say so in a
   sentence after the object — the renderer reports the residual and a reader
   deserves to know it was expected.
7. Is every priority label the source's own?
8. Is the object valid JSON with no trailing commas?

An object failing one of these is corrected, not explained.
"""

CONTRACTS = {CONTRACT_NAME: CONTRACT_TEXT}
