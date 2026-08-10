# An overview board designed for the role, not for the data set

**Date:** 2026-08-10
**Status:** approved

## Problem

`Portfolio overview` answers "is the plan as a whole plausible?" with an
inventory: total volume, the audience-band distribution, the regional
distribution. Every panel is true and none of them changes what anyone does.
Asked which week to intervene in, or which team to talk to, the board is silent.

It also carries two defects visible the moment it is drawn:

**Its tile row hides the thing an executive most wants.** "1,380 activities in
scope" mixes 1,153 whose date has already passed with 227 still ahead, and
states neither. Split at the pack's own generation date, the same portfolio
reads: 1,153 planned to date, **66 in the next thirty days**, 161 in the rest of
the year. The forward horizon is nearly empty and the board cannot say so.

**Its volume chart has no vintage marker.** The 2026-08-06 test render carried a
`data as of` divider; the board specification lost it. Without it the curve's
decline reads as activity falling away, when it is a plan not yet written — the
exact misreading the agent's instructions warn about in prose and the board
then invites in a picture.

## What "planned" means, since it decides the tile row

Every record in this system is a plan. It holds no delivery, no performance, no
cancellations; nothing ever confirms that an activity went out. So the elapsed
half of the volume curve is not history — it is **plan whose date has passed,
unverified**. A board may say "planned to date". It may never say "ran".

This is not pedantry. A head of communications reading "1,153 activities" as
work delivered would draw conclusions about a function's output that this data
cannot support in either direction.

## Decisions

**The board is designed for the head of communications, and replaces
`Portfolio overview`.** Two general boards would have no criterion by which the
agent picks one, which is the case where it grabs blindly. That person is
accountable for a function rather than a portfolio, and their day is four
questions: is the organisation being over-communicated to, are the teams
planning far enough ahead, is leadership time going where it counts, is the
plan working on what matters. A panel that serves none of those is inventory.

**Its one decision is: where do I intervene, and with whom.** The read-out
therefore ends by naming which of the other three boards to open. An overview
that ends in observations competes with them; one that ends in a route makes
them a set. This is what resolves the contradiction in having a general board
at all, given the catalogue's own rule that a board answering three questions
answers none.

**The time panel is weighted by audience size.** Forty activities in a week
means nothing; twelve of them addressed to everyone is what costs the function
its credibility. So the panel plots activities in the top two audience bands as
the message, with the total as a faint context line on the same axis — never a
second scale. On the 2026-08-06 figures the peak week holds 60 activities of
which **27 are aimed at 50,000 people or more**, a sentence the current chart
cannot produce.

**Solid to the vintage, dashed after it.** The two halves are different claims —
one is plan whose date has passed, the other is what is written down so far —
and a single continuous line asserts they are the same kind of thing.

**Panel 4 names lead teams, and is worded as work received.** This was the one
contested decision. The alternative was business division, which is cheaper
(that block already exists) and safer when a screenshot is forwarded. It was
declined in favour of the conversation the role actually has, on one condition:
the panel reads **"requests received at under 7 days' notice"**, never "planned
at". The pack knows when an activity was created and when it starts; nothing in
it says who caused the gap, so a team at the top of the bar may be absorbing
late work rather than causing it. The relabel is what makes the panel survive
being cropped away from its footnote.

**The board spends its one red element on panel 4.** The catalogue's rule is one
highlight per board, on the panel that answers its business question. On
`Portfolio overview` that was the volume peak. Here the decision is *where do I
intervene*, so red sits on the team absorbing the most late work, and the
audience-load peak becomes a grey marker with an inline label. The same rule
produces a different answer because the board asks a different question — which
is the argument for named boards.

**A headline figure is stated; only a shape may be summed.** This rule is
sharper than "sum within a block", and the reason is the surface. On both
Copilot Studio and Agent Builder the pack files are **retrieved in chunks, not
loaded**. Summing forty `block=TOTAL` rows to produce "66 in the next thirty
days" is a single number that a partial retrieval gets silently wrong — the
exact failure the whole catalogue exists to prevent, and worse than a missing
figure because nothing on the board looks broken.

So the three horizon figures are stated in `01-summary.txt`, which is short
prose the agent reads whole and which every other stated figure already comes
from. The audience-load series is different in kind: each point needs two band
rows for one week, so a chunk carrying that week is enough, and a partial
retrieval shows up as a visibly broken line rather than a confident wrong
number. That one may be summed.

Deriving anything from `05-activities.csv` remains out of bounds, as before.

## The board

**Head of communications overview** — *where do I intervene, and with whom?*

| # | Panel | Source | Highlight |
|---|---|---|---|
| 1 | Tiles: planned to date · next 30 days · median lead time · arrived at under 7 days' notice · share recording GEB/GEB-1 | `01-summary.txt` · HORIZON · `Planned to date`; HORIZON · `Next 30 days`; PLANNING DISCIPLINE · `Median lead time (days)`; PLANNING DISCIPLINE · `Planned at under 7 days' notice`; LEADERSHIP AND AUDIENCE · `With GEB/GEB-1 involvement`; VOLUME · `Activities in scope` | no |
| 2 | Audience load by start week | `04-calendar.csv` · `block=audience_band` · the two largest bands, with `block=TOTAL` as context | no |
| 3 | Priority mix | `06-breakdowns.csv` · `block=priority` · `measure=activities` | no |
| 4 | Late requests by lead team | `06-breakdowns.csv` · `block=lead_team` · `measure=short_notice` | **yes** — the team absorbing the most |
| 5 | Executive read-out, ending in a route | `01-summary.txt` · LOAD, and the figures no panel plots | no |

Panel 3 is a donut: four categories, so the form is legal, and the question is
the mix. The levels are peers and the split itself is the answer, so nothing is
highlighted and red stays out of it entirely.

Must not: call any audience figure reach. Must not say "the GEB". Must not read
the thinning forward plan as a decline — the read-out says it is unwritten.
Must not print a panel's `Source:` citation as its footnote.

## Dropped from `Portfolio overview`

**Planned audience size.** A distribution nobody acts on — no head of
communications changes anything because 22% of activities target 1–10k. Its one
useful fact, that the 275 unknown bands are the external records whose form has
no such field, moves into the read-out where it explains something.

**Regional distribution.** 62% of the bar is "Global", which is as much an entry
default as a geography. Four small bars under a dominant one says "most things
are global", which is true and not worth a fifth of the board.

**Internal and external tiles.** A structural fact about two source forms, not a
decision.

**Share in the five busiest weeks.** Concentration is visible in the curve, and
the rules already delete a tile that restates a chart. It survives as a
read-out sentence when the number is unusual.

Both dropped distributions are worth keeping somewhere. They are the substance
of a future **Reach and coverage** board, not a reason to carry a seven-panel
overview.

## What the pack needs

Three additions, each required by a named panel, each in a shape the pack
already uses:

| | |
|---|---|
| `priority` as a block | Appended to `breakdown_fields` in the pack's own config, so the distributed workbook is untouched — the same route by which the pack is already wider than the workbook. Yields priority per week and per measure through the same `iter_blocks` everything else runs on. |
| `lead_team` as a block | Same mechanism, same place. |
| `short_notice` as a measure | A seventh measure in `06-breakdowns.csv`: activities whose lead time is under `SHORT_NOTICE_DAYS`. Arrives per team and per division for free, because measures are computed per block value. |
| A `HORIZON` section in `01-summary.txt` | Three stated figures — `Planned to date`, `Next 30 days`, `Rest of the period` — split at the pack's generation date using the week grid the report already builds. Stated rather than summed, for the retrieval reason above: these are headline numbers, and a chunked read of the calendar would get them confidently wrong. |

Nothing else. The audience-load series stays a sum of two band rows the calendar
already writes, per week, which is the one place summing is safe.

## Both surfaces, not one

The boards ship twice: as `cplan-dashboards-skill.zip` to Copilot Studio, and as
three knowledge files to Agent Builder, which has no skill packages. Replacing a
board touches both, and the Agent Builder side is the one with no slack.

`agent_builder.BOARD_FILE_NAMES` maps each `dashboard_skill.BOARDS` key to an
upload filename, and a test asserts the two key sets are equal — so the rename
propagates or the build fails, which is the intended behaviour. The upload file
becomes `09-board-head-of-communications-overview.txt`.

The prompt is the constraint. It names the three boards in its `## Your files`
list, because a knowledge file cannot announce itself, and it sits at 7,775 of
8,000 characters with a test reserving 200 for a longer organisation name —
25 usable. Replacing `portfolio overview` with `head of communications
overview` costs **13 characters and leaves 212**, so the full name fits with
twelve to spare. Measure it rather than trusting this line: if a later edit has
eaten the margin, shorten the board's name in the prompt before shortening
anything else, and never lower the 200 floor.

## A note for whoever implements the tiles

Tile 4 reads **"arrived at under 7 days' notice"** while the summary line it
draws on is labelled `Planned at under 7 days' notice`. That is deliberate, not
a transcription slip: the wording is the condition on which panel 4 names teams
at all, and the tile must not contradict the panel beneath it. The citation
resolves against the section rather than the label, so the test passes; do not
"correct" the caption to match the summary.

## Testing

Extends the existing citation test rather than adding a mechanism: every
`Source:` line on the new board resolves against the pack generated in the same
run, which now includes the two new blocks and the new measure. Plus:

1. `block=priority` and `block=lead_team` appear in both `04-calendar.csv` and
   `06-breakdowns.csv`, and carry `overlaps=no` — an activity has one priority
   and one lead team.
1b. The three `HORIZON` figures sum to `Activities in scope`, and the split
   falls at the generation date the same section header states — the arithmetic
   a reader would do to check it is the arithmetic the test does.
2. `short_notice` agrees with `metrics.lead_time_stats` on the same fixture, and
   the TOTAL block's figure equals the summary's portfolio count.
3. The board carries exactly one `Highlight: yes`, and it is panel 4.
4. The board file says "requests received at" and never "planned at under".
5. `Portfolio overview` is gone from the catalogue: its file is removed, the
   index names three boards, and no citation anywhere still points at it.

## Out of scope

**A Reach and coverage board** for the two dropped distributions.

**Channels.** The field holds several values in one string, so "Email,
Intranet" is a combination rather than a channel. A channel chart before that is
split is a chart of combinations pretending to be channels.

**The division cut of panel 4.** It belongs on `Planning discipline`, where it
can sit beside the team cut without either being a headline. That board is
already deferred.

**Any measure of whether an activity ran.** The source system does not carry it,
and no board can invent it.
