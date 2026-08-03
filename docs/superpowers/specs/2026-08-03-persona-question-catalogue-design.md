# Persona and question catalogue for the CPLAN MCP agent

Status: 2026-08-03. The personas, the ranking and the phasing are agreed; the
individual tool designs are not.

## Purpose

The MCP server (`pipeline/mcp/`) currently exposes six read tools derived from the
schema: what the database can be asked. This document works the other way round —
from the people who would ask. It defines the personas inside a group corporate
communications function, derives the questions each of them needs answered, ranks
them by who asks and what the answer is worth, and scores each against what the
server can answer today.

The intended next step is to take the ranked catalogue and design the closure:
which questions an MCP agent can answer today and how, where the gaps are, and
what to build to close them.

## Personas

Eight personas. The first five are primary — they would use the agent weekly or
daily. The last three are secondary but each owns questions nobody else asks, so
leaving them out would hide real gaps.

These are the agreed working set. They are derived from the domain model and from
how corporate communications functions are typically organised, **not** from
stakeholder interviews — interviews are not available, and this was accepted
rather than overlooked. Treat them as a hypothesis good enough to prioritise
against, and revise if real usage contradicts them.

Every persona shares one goal — more reach, more engagement, less noise — but they
optimise different variables to get there, and that is what makes their questions
different.

### P1 — Head of Internal Communications

Accountable for what the workforce hears. Decides which messages get the all-staff
channels, protects employees from message overload, and answers to the executive
board for whether a strategic message landed.

- **Horizon:** quarter and year, with a weekly load check.
- **Optimises:** signal-to-noise per employee. Fewer, better messages.
- **Decides:** what gets an all-staff slot, what is cut, what is deferred.
- **Frustration today:** cannot see cumulative load on one audience. Every team
  reports its own plan; nobody owns the sum.

### P2 — Head of External Communications

Accountable for what the market, media and public hear. Balances proactive
announcements against reactive capacity, and against the market and results
calendar.

- **Horizon:** quarter, with a hard sensitivity to specific dates.
- **Optimises:** share of voice and timing against external events.
- **Decides:** announcement sequencing, embargo timing, spokesperson allocation.
- **Frustration today:** no consolidated view of what internal comms is doing on
  the same day — internal messages leak, and a mismatched pair costs credibility.

### P3 — Campaign Planner

The core user of the tool. Owns communication packs and tracking clusters, builds
the plan, chases missing fields, and defends slots against other planners.

- **Horizon:** the next six to twelve weeks, activity by activity.
- **Optimises:** plan completeness and internal coherence.
- **Decides:** which activities belong in which pack, and on which day.
- **Frustration today:** completeness chasing is manual and repetitive; conflict
  detection depends on remembering what someone else planned.

### P4 — Editorial Lead / Channel Owner

Owns a channel — intranet, newsletter, news digest, social. Fills a fixed number
of slots per week from a queue of contributions and decides running order.

- **Horizon:** this week and next, at day granularity.
- **Optimises:** channel-level performance — open rates, dwell time, click-through.
- **Decides:** what runs, when, in which order, and what is held.
- **Frustration today:** finds out about a big item too late; cannot see which
  contributions are ready to publish versus still a placeholder.

### P5 — Divisional / Regional Communications Business Partner

Represents one division, function or region inside the group plan. Needs their own
slice, and needs to know when a group-level activity is about to land on their
population.

- **Horizon:** quarter, filtered to their division or region.
- **Optimises:** their stakeholders' visibility inside the group plan.
- **Decides:** what to escalate, what to align, what to schedule around.
- **Frustration today:** the group plan is not sliceable by division or region
  without exporting it and filtering by hand.

### P6 — Communications Analytics & Insights

Owns measurement. Turns tracking IDs into reach and engagement numbers, and feeds
the result back into planning so the next campaign is better than the last.

- **Horizon:** retrospective, plus the forward plan as a measurement pipeline.
- **Optimises:** the evidence base — which channel works for which audience.
- **Decides:** what is reported, what counts as success, what to stop doing.
- **Frustration today:** performance data and planning data live in different
  systems; the tracking ID is the intended join key but the join is manual.

### P7 — Executive Communications Lead

Plans communication carried by named senior leaders — a scarce, highly visible
resource with its own governance.

- **Horizon:** quarter, per named executive.
- **Optimises:** executive time and credibility — no over-exposure, no two leaders
  saying near-identical things in the same week.
- **Decides:** who fronts which message, and how often.
- **Frustration today:** executive involvement is a free-text field on an
  activity, so "how often is this person being used" is not a question the plan
  can answer.

### P8 — CPLAN Data Steward / Product Owner

Keeps the plan trustworthy. Owns the daily sync, the parallel-operation window
against the source system, data quality and access.

- **Horizon:** daily.
- **Optimises:** data currency and correctness.
- **Decides:** when the studio is ready to become the system of record.
- **Frustration today:** divergence between mirrored and locally edited records is
  visible in the schema (`version` versus `synced_version`) but not in any view.

## How the ranking works

Seniority alone is not a good ranking key — it would put a quarterly board-report
question above a daily decision that stops a bad send. The score combines three
transparent factors:

**1. Persona weight** (who asks). Summed over every persona the question serves,
so breadth counts as well as seniority:

| Persona | Weight | Rationale |
|---|---|---|
| P1 Head Internal Comms | 5 | Accountable for the outcome |
| P2 Head External Comms | 5 | Accountable for the outcome |
| P3 Campaign Planner | 4 | The tool's core daily user |
| P5 Divisional/Regional Partner | 3 | Represents a whole population |
| P7 Executive Comms Lead | 3 | Governs a scarce, high-visibility resource |
| P4 Editorial Lead | 2 | Channel-level scope |
| P6 Analytics & Insights | 2 | Advisory rather than deciding |
| P8 Data Steward | 1 | Internal to the tool |

**2. Cadence bonus** (how often it is asked): daily or weekly +3, monthly +2,
quarterly +1. A question asked every Monday is worth more automation than one
asked at quarter end.

**3. Risk premium** (+4) for questions that prevent an error which cannot be taken
back once it happens — a collision, a mistimed external announcement, an
over-exposed executive, two campaigns contradicting each other. Applied to Q11,
Q12, Q13, Q14, Q20, Q25, Q42 and Q48.

`Score = Σ persona weights + cadence + risk`. Tiers: **1** ≥ 14, **2** 10–13,
**3** ≤ 9.

**Known artefact of the method, stated rather than hidden.** A question that
matters existentially to exactly one mid-weight persona scores low, because
nothing adds to its persona weight. Q8 ("what is planned for my division") scores
5 and lands near the bottom, yet it is the single question that makes the tool
useful to P5 at all. The per-persona top three below exists so that a weighted
list does not quietly erase a minority need — read both.

**Question IDs are stable and thematic.** Ranking reorders the rows; the IDs do
not move, so the roadmap and any later gap analysis can reference them safely.

| IDs | Theme |
|---|---|
| 1–10 | Portfolio shape and load |
| 11–21 | Timing, collisions and audience fatigue |
| 22–30 | Planning completeness and readiness |
| 31–36 | Ownership and capacity |
| 37–42 | Campaign, pack and cluster coherence |
| 43–46 | Strategy and priority |
| 47–49 | Senior leadership exposure |
| 50–52 | Audience and reach planning |
| 53–57 | Reach and engagement (vision — see scope note) |
| 58–63 | System and process health |

**Coverage legend.** **A** answerable today, one or two tool calls, no hidden
trap. **P** partial — several calls, client-side arithmetic, or a domain trap the
tools do not warn about. **T** data is in the database, no tool reaches it. **D**
data is not in CPLAN at all.

## The ranked catalogue

### Tier 1 — build for these first

| Rank | ID | Question | Personas | Why answering it matters | Score | Cover |
|---|---|---|---|---|---|---|
| 1 | 1 | What is planned in the next four weeks? | P1 P2 P3 P4 | The weekly planning meeting's opening question; everything else is a follow-up to it | 19 | A |
| 2 | 37 | Which campaigns are live now, how large is each, over what period? | P1 P2 P3 P6 | The only view that shows the plan as campaigns rather than as a list of items — how leadership actually thinks about it | 19 | T |
| 3 | 25 | Which high-priority activities are still incomplete two weeks out? | P1 P3 P4 | The highest-value alert in the tool: catches the expensive failures while there is still time to fix them | 18 | T |
| 4 | 14 | Does an external announcement collide with an internal message that day? | P1 P2 | Prevents the classic credibility failure — staff learning something from the press, or the two versions not matching | 17 | P |
| 5 | 41 | Is this campaign being told both internally and externally? | P1 P2 P3 | A campaign told only one way is half-delivered; catches it while it is still fixable | 17 | P |
| 6 | 2 | How many activities per month across the next two quarters? | P1 P2 P3 | The capacity baseline for every resourcing and deferral decision | 16 | A |
| 7 | 11 | Which two high-priority activities hit the same audience within a few days? | P1 P3 | Direct cannibalisation — two important messages competing, both losing. Cannot be undone after sending | 16 | T |
| 8 | 42 | Are two campaigns saying the same thing to the same audience? | P1 P3 | Duplicate messaging reads as disorganisation and wastes a slot that cannot be reclaimed | 15 | D |
| 9 | 43 | How does the plan distribute across strategic objectives and pillars? | P1 P2 P3 | The question leadership is asked upwards: are we communicating the strategy, or just the traffic? | 15 | T |
| 10 | 62 | What changed across the plan since last week — new, moved, cancelled? | P1 P3 P4 P8 | Turns a static plan into a monitorable one; the standing agenda item for every weekly review | 15 | T |
| 11 | 4 | Which weeks next quarter are overloaded, and which are empty? | P1 P3 P4 | Where load-balancing decisions are actually made — month granularity hides the problem entirely | 14 | T |
| 12 | 12 | On which days does the same audience receive more than N activities? | P1 P4 | The audience-fatigue guardrail; the direct measure of P1's core mandate | 14 | T |
| 13 | 13 | Does my planned date collide with a senior-leader communication that week? | P3 P7 | An executive message and a routine one on the same day devalue the executive one | 14 | T |
| 14 | 45 | How many critical or high-priority activities are in the next quarter? | P1 P2 P4 | Sets the attention budget; also the question most likely to be answered wrongly today (see the priority trap) | 14 | P |

### Tier 2 — the substantial middle

| Rank | ID | Question | Personas | Why answering it matters | Score | Cover |
|---|---|---|---|---|---|---|
| 15 | 54 | Did this campaign perform better than the comparable one last year? | P1 P2 P6 | The learning loop. Without it, planning quality cannot compound | 13 | D |
| 16 | 3 | How does the next four weeks compare with the last four? | P1 P2 | Distinguishes a genuinely busy period from normal volume — stops false alarms | 12 | P |
| 17 | 5 | What is the internal/external split of the forward plan? | P1 P2 | The balance-of-effort check between the two halves of the function | 12 | A |
| 18 | 17 | Which activities were created with less than a week of lead time? | P1 P3 P8 | Short notice is the leading indicator of poor outcomes and of process breakdown | 12 | T |
| 19 | 22 | Which activities next quarter are not fully planned, and what is missing? | P3 P1 | The planner's daily worklist; converts a vague "chase people" into a specific list | 12 | A |
| 20 | 24 | Which teams have the worst completeness? | P1 P3 | Moves the conversation from chasing individual records to fixing a team's habit | 11 | T |
| 21 | 31 | Who owns the most activities next month? | P1 P3 | Spots the overloaded individual before the work slips | 11 | A |
| 22 | 34 | Show me everything one named team owns next month. | P1 P5 | The standing question in every team check-in and partner conversation | 11 | T |
| 23 | 44 | Which strategic pillar is under-served next quarter? | P1 P2 | Turns strategic alignment from a retrospective audit into a forward correction | 11 | T |
| 24 | 9 | What is planned in my region next quarter? | P5 P2 | Regional relevance and local sensitivity checks; also the base for regional sign-off | 10 | T |
| 25 | 18 | What is our median planning lead time, and is it improving? | P1 P3 | The single best process-health metric for a planning function | 10 | T |
| 26 | 20 | Are we planning into a blackout or results period? | P2 | A mistimed announcement here has consequences beyond communications | 10 | D |
| 27 | 21 | Which activities are timed badly for a non-European audience? | P2 P5 | A message that lands overnight is a message half the audience never sees | 10 | D |
| 28 | 32 | Which lead team carries the heaviest load next quarter? | P1 P3 | Resourcing and rebalancing across teams | 10 | A |
| 29 | 33 | Show me everything one named person owns next month. | P3 P5 | The individual worklist — the most frequent one-to-one question | 10 | A |
| 30 | 35 | Which partner teams are we most dependent on? | P1 P3 | Names the dependencies that actually determine whether the plan is deliverable | 10 | T |
| 31 | 47 | Which activities involve an executive-board member next quarter? | P7 P1 | The forward view of the function's most scrutinised output | 10 | T |
| 32 | 49 | Which executive appearances are still missing planning fields? | P7 P3 | An incomplete executive activity is the most expensive kind to leave incomplete | 10 | T |
| 33 | 53 | Which channel actually delivers the best engagement for an all-staff message? | P1 P4 P6 | Turns channel choice from habit into evidence | 10 | D |
| 34 | 56 | Which planned activity types historically underperform and should be dropped? | P1 P4 P6 | Creating capacity by stopping things is the cheapest capacity there is | 10 | D |

### Tier 3 — real, but not what to build for

| Rank | ID | Question | Personas | Why answering it matters | Score | Cover |
|---|---|---|---|---|---|---|
| 35 | 6 | Which channels carry the most volume next month? | P1 P4 | Channel load-balancing input | 9 | A |
| 36 | 10 | Which activities in a window are already past versus still upcoming? | P3 P4 | Separates the reviewable from the still-changeable | 9 | P |
| 37 | 15 | What starts in the next seven days? | P4 P3 | The daily editorial standup list | 9 | A |
| 38 | 16 | What ends or expires in the next fourteen days? | P4 P3 | Catches content going stale in a live channel | 9 | T |
| 39 | 40 | Does this campaign cover the channels we intended? | P3 P4 | Catches a channel gap while the campaign can still be extended | 9 | T |
| 40 | 48 | How often is each named executive being used — is anyone over-exposed? | P7 | Protects executive credibility; over-exposure is only visible in aggregate | 9 | T |
| 41 | 50 | Which target audiences receive the most activities next quarter? | P1 P5 | Shows whose inbox the function is actually filling | 9 | T |
| 42 | 51 | What total estimated reach is planned for next month? | P1 P6 | The forward-looking counterpart to reach reporting — planning data, not performance data | 9 | D |
| 43 | 7 | Is our channel mix shifting quarter over quarter? | P1 P4 | Detects unmanaged drift in how the function communicates | 8 | P |
| 44 | 19 | Which activities have impossible or absurd dates? | P3 P8 | Cheap data-quality win; bad dates corrupt every timeline view | 8 | T |
| 45 | 27 | Which activities look campaign-like but have no pack link? | P3 P6 | Unlinked activities are invisible to campaign-level measurement | 8 | P |
| 46 | 29 | Which descriptions are too thin to tell two activities apart? | P3 P4 | A plan nobody can read is a plan nobody can coordinate against | 8 | D |
| 47 | 39 | Which activities belong to this tracking cluster, across its packs? | P6 P3 | The top level of the hierarchy — the unit cross-channel measurement is designed around | 8 | D |
| 48 | 57 | Does higher assigned priority correlate with higher engagement? | P1 P6 | Validates whether the priority field means anything at all | 8 | D |
| 49 | 58 | How current is the data — when did the last sync run, did it conflict? | P8 P3 | Every other answer's trustworthiness depends on this one | 8 | A |
| 50 | 59 | How big is the plan, and what period does it cover? | P8 P1 | Orientation; also the agent's own sanity check before answering anything else | 8 | A |
| 51 | 61 | What changed on this activity, when, and by whom? | P3 P8 | Settles "who moved this" without a meeting — the source system cannot answer it at all | 8 | T |
| 52 | 23 | Which required field is missing most often across the plan? | P3 P8 | Points at the form or the guidance rather than at individual records | 7 | A |
| 53 | 28 | How ready is one specific campaign, activity by activity? | P3 | The pre-launch checklist | 7 | P |
| 54 | 36 | Which activities have a lead but no lead team, or the reverse? | P3 P8 | A specific, fixable data defect that breaks team-level views | 7 | P |
| 55 | 38 | Which campaigns consist of a single activity and are probably mislabelled? | P3 P8 | Keeps campaign-level analysis honest | 7 | A |
| 56 | 46 | Is our priority mix credible, or is nearly everything the lowest level? | P1 P8 | If priority carries no information, every prioritised view is theatre | 7 | A |
| 57 | 8 | What is planned for my division next quarter? | P5 | **The** question that makes the tool useful to P5 — low score is an artefact of the method, see the caveat above | 5 | T |
| 58 | 26 | Which activities carry no tracking ID and cannot be measured? | P6 P8 | Every one of these is permanently lost to measurement | 5 | T |
| 59 | 52 | How many activities are flagged for the news digest next week? | P4 | The digest's own worklist | 5 | T |
| 60 | 30 | Which mirrored records have been edited locally and now diverge? | P8 | Governs the parallel-operation window and the eventual cutover decision | 4 | T |
| 61 | 63 | Are archived records distorting my numbers? | P8 P6 | Archiving is a source-system view-size workaround, not a relevance signal — misreading it skews every KPI | 4 | A |
| 62 | 55 | What is the unique cross-channel reach of this cluster? | P6 | The measurement the whole tracking-ID scheme was designed to enable | 3 | D |

### Enabler — not persona-facing, but every answer depends on it

| ID | Question | Why it matters | Cover |
|---|---|---|---|
| 60 | Which values does field X actually contain? | `channel`, `priority`, `region` and friends are free text, not enumerations. An agent that guesses "Newsletter" matches nothing and reports zero — confidently. This is the trap-avoidance call that has to precede most filtered questions | A |

### Each persona's top three

So that the weighted list does not bury a minority need:

| Persona | Top three (by score) |
|---|---|
| P1 Head Internal Comms | Q1, Q37, Q25 |
| P2 Head External Comms | Q37, Q14, Q41 |
| P3 Campaign Planner | Q1, Q37, Q25 |
| P4 Editorial Lead | Q1, Q25, Q62 |
| P5 Divisional/Regional Partner | Q34, Q9, Q21 — **plus Q8**, which the score understates |
| P6 Analytics & Insights | Q37, Q54, Q53 |
| P7 Executive Comms Lead | Q13, Q47, Q49 |
| P8 Data Steward | Q62, Q17, Q58 |

P1 and P3 converge on the same three, which is a good sign: the accountable
executive and the daily user want the same tool. P6's top three are two-thirds
outside the data (see the scope note) and P7's are entirely blocked by
unqueryable executive fields — the two personas the current server serves worst.

## What the catalogue shows

**Tally.** Of the 63 questions: 16 answerable today (**A**), 9 partial (**P**), 27
blocked by a missing tool over data CPLAN already holds (**T**), 11 blocked by
data CPLAN does not hold (**D**). More questions are blocked by a missing tool
over data already present (27) than work today (16).

**Ranking makes the gap worse, not better.** Of the 14 Tier 1 questions, **3 work
today** (Q1, Q2, Q5 — and Q5 is rank 17, so really 2 of the top 14). Nine are
blocked by a missing tool over data already in the database. The tools that exist
answer the middle and bottom of the list well and the top of it barely — which is
what happens when tools are derived from a schema rather than from questions.

**The dominant failure is filter/group asymmetry, not missing analytics.**
`activity_counts` can group by `region`, `business_division` and `lead_team`, but
`search_activities` cannot filter by any of them, and `planning_gaps` cannot be
narrowed by anything except `source_type` and a date window. 17 of the 27 **T**
questions disappear by closing that asymmetry alone — the cheapest work in this
document.

**Second: no cross-tabulation.** The real questions are two-dimensional — channel
by month, division by priority, campaign by channel, audience by day. Each one
currently requires the agent to fetch rows and count them itself, which collides
with the 50/200-row caps the server correctly enforces.

**Third: the studio has analytics the agent does not.** `detectCollisions`,
`campaignScorecards`, `leadTimeStats`, `weeklyCoverage`, `comingUp`,
`endingWithin` and `dataQuality` all exist in `pipeline/studio/analytics.js`.
A human at the studio can see collisions; an agent cannot — and collisions are
ranks 7, 12 and 13. Note the hazard before porting any of them: the completeness
rule already lives in three places, held together by tests that pin the MCP copy
against the view. A fourth copy of collision logic needs the same treatment or it
will drift.

**Fourth: the catalogue metadata is thin, and that is a correctness problem, not a
polish problem.** Six tools, no MCP resources, no prompts, and instructions that
omit every domain trap documented in the knowledge base:

- Priority runs on two live vocabularies at once — `Critical/High/Medium/Low` for
  studio rows, a numbered `<n> - <label>` scale for mirrored rows where 1 is most
  urgent. An agent filtering `priority="High"` silently misses the ~16% of the
  portfolio at numbered level 2. This directly corrupts Q45, rank 14.
- Archived is a source-system view-size workaround, not a relevance signal, and
  archived rows count in every KPI — but `search_activities` hides them by default.
- The three-level hierarchy (cluster → pack → activity) is real in the tracking ID
  and absent from the schema, so an agent reads `campaign` as the whole story.
- Executive involvement is split across two fields, counted separately.
- `audience` is a band label whose meaning is an unverified mapping assumption.

None of this is discoverable from the tool list. The failure mode is a confident
wrong answer, which is worse than a refusal.

**Fifth: the shared goal is outside the data, and that is now a decision.** Every
persona is measured on reach and engagement, and the eleven **D** questions are
where those live. Joining performance data is the agreed long-term direction but
out of scope for the next half year, so the agent is a **planning** assistant in
phase one. That has to be in its framing: Q53 and Q54 are ranks 33 and 15 and will
be asked immediately, and an approximation assembled from planning fields would be
worse than a clear refusal.

## Roadmap

Phases 1 and 2 are the planning-only agent. Phase 3 is planning-data modelling.
The vision items are named so the phase-one design does not paint them out, but
nothing in phases 1 to 3 depends on them.

### Phase 1 — make the existing data askable

1. **Filter/group parity.** Extend `search_activities` filters and
   `activity_counts` / `field_values` dimensions to the full descriptive column
   set: `region`, `business_division`, `business_area`, `lead_team`,
   `partner_team`, `target_audience`, `audience`, `strategic_objectives`,
   `news_digest`, and the two executive fields. Add end-date window filters
   alongside the existing start-date ones, plus derived predicates
   (`has_tracking_id`, `is_locally_modified`, `is_archive`, a lead-time bound).
   Add the same narrowing — and a grouping — to `planning_gaps`.
   - Multi-value splitting is required for `strategic_objectives` and the two
     executive fields; see the resolved delimiter note below. Grouping raw strings
     yields *combinations*, not pillars or people.
2. **Catalogue metadata.** Put the five domain traps into the server instructions
   and the individual tool descriptions, and add an MCP resource carrying the
   domain model (hierarchy, vocabularies, completeness rule, archive semantics) so
   the agent reads it once rather than inferring it per question. Include the
   phase-one scope boundary so the agent declines performance questions instead of
   approximating them. This prevents wrong answers rather than enabling new ones,
   which is why it sits in phase one.
3. **Priority-rank projection**, so Q45 (rank 14) and Q46 stop depending on the
   agent independently knowing `priorityRank`.

Unblocks Q8, Q9, Q16, Q17, Q24, Q25, Q26, Q30, Q34, Q35, Q43, Q45, Q47, Q48, Q49,
Q50, Q52 outright and improves Q12, Q13 and Q44. That is 5 of the 14 Tier 1
questions. Projected: **33 A / 11 P / 8 T / 11 D**.

Q13 ("does my date collide with a senior-leader communication that week") only
gets halfway: phase 1 makes executive activities findable by date window, but
*scoring* it as a collision needs the `detectCollisions` port in phase 2.

Planned in detail in
[`../plans/2026-08-03-mcp-phase-1-filter-parity.md`](../plans/2026-08-03-mcp-phase-1-filter-parity.md).

### Phase 2 — the analytics the studio already has

4. **Cross-tabulation** — `activity_counts` over two dimensions.
5. **Calendar tools** — weekly load buckets, `ending_within`, invalid-date
   detection, and window-over-window comparison.
6. **Ported studio analytics** — collisions, campaign/pack scorecards, lead-time
   statistics. Each pinned by tests against its existing implementation the way
   the completeness rule already is.
7. **Change-log tools** — per-activity history, and a plan-level "what changed
   since" diff.

Unblocks Q4, Q11, Q13 (fully), Q18, Q19, Q37, Q40, Q61, Q62 and converts most
remaining partials — which is the rest of Tier 1 except the two **D** questions in
it. Projected: **≈49 A / 3 P / 0 T / 11 D**.

### Phase 3 — planning-data model work

8. **Packs and clusters as first-class records** (already on the knowledge base's
   gap list). Without this, Q39 is unanswerable and `campaign` reads as the whole
   hierarchy.
9. **Audience size as an ordinal column** rather than a free-text band, with the
   band-to-column mapping verified against the source system first. Q51 is the one
   **D** question that is *planning* data, not performance data: it asks what reach
   we are planning, and it is blocked by a text column rather than a missing system.

Projected: **≈51 A / 3 P / 0 T / 9 D**.

### Vision — beyond the half-year horizon

10. **Performance data** — a metrics source joined on tracking ID. Answers Q53–Q57
    and turns a plan-completeness assistant into an effectiveness assistant.
11. **Semantic search** — Q29 and Q42 need embeddings. The
    free-text-is-untrusted-input caveat in the MCP README applies doubly once the
    model compares message content.
12. **External calendar feed** (Q20) and **time-zone semantics** (Q21) — both need
    a decision outside this document. The time-zone behaviour is a documented
    assumption in the knowledge base, not a bug to fix blind.

### Recommended first increment

Phase 1. Small, removes the largest single share of gaps, and item 2 stops the
current server from answering Q45 and Q63 confidently wrong — which it does today.

## Resolved

- **Personas** (2026-08-03): the eight above are the agreed set, accepted without
  stakeholder interviews.
- **Scope** (2026-08-03): planning only for phase one. Performance data is the
  long-term vision, judged unlikely within roughly the next half year; nothing in
  phases 1 to 3 depends on it.
- **Multi-value delimiter** (2026-08-03): resolved from the ETL, which is
  authoritative for what the sync writes. `pipeline/scripts/process_cplan.py`
  joins SharePoint lookup and taxonomy multi-values with **`", "`**
  (`parse_sp_lookup`, default separator) and person multi-values with **`"; "`**
  (`PERSON_JOIN`, applied to `SP_MULTI_PERSON_COLUMNS = {bod_geb,
  other_executives}`). So the executive fields use `"; "` and
  `strategic_objectives` uses `", "`. `analytics.js::normalizeMulti` already
  splits on either (`/[;,]/`), which is the behaviour to mirror.
  - **Hazard:** splitting on `", "` is lossy — a single lookup value containing a
    comma is indistinguishable from two values. The person separator does not have
    this problem. Any pillar tally built on comma-splitting can silently fragment
    one objective into two, so the split must be validated against real values
    before the numbers are published.
  - **Not confirmed against production data:** this machine holds only synthetic
    snapshots (40 parquet rows, 400 SQLite rows, no multi-value instances, and the
    SQLite file predates the `other_executives` column). The code is authoritative
    for what the sync writes; a real snapshot should still be checked once
    available.

## Open questions

- **Multi-user scoping.** The MCP server has no authentication and does not carry
  the studio's per-user role, so PostgreSQL row-level security applies to the
  connecting role rather than an end user. P5 and P7 imply row-level scoping the
  stdio transport cannot provide. Phase 1 does not need it for single-user local
  use, but it gates any shared deployment.
- **Are Tier 3 ranks 57–62 worth building at all,** or should they be accepted as
  permanently manual? Several are one-off data-quality checks rather than recurring
  questions, and Phase 1 happens to unblock most of them as a side effect.
