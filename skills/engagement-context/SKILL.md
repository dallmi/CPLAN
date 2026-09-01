---
name: engagement-context
description: How to read the per-engagement context pack exported from the communication plan (CPLAN) and turn it into the Context and environment section of a speaker brief. Load before writing that section, and whenever someone asks what else is happening around an appearance, what this audience heard recently, or whether appearances collide.
---

# Engagement context

The Context and environment section is assembled, not imagined. Its only
source is the context pack — a set of files exported from the communication
plan for this one engagement. Nothing in this section may come from anywhere
else: no general knowledge, no memory of other engagements, no news.

## The pack contract (draft)

One directory per engagement. File names are the contract; a file that is
missing is reported as missing, never silently skipped.

| File | Carries |
|---|---|
| `00-engagement.md` | The engagement record: speaker, event, date, format, audience, owner |
| `01-recent-comms.csv` | Communications in the trailing window to the same audience or on the same topic: date, channel, audience, title, owner |
| `02-upcoming-comms.csv` | Same shape, forward window — including the executive's own other appearances |
| `03-collisions.csv` | Pairs from the plan's collision detection that involve this engagement: counterpart, shared channel/audience, severity |
| `04-sources/` | The engagement's supplied documents (event invitation, host material, prior briefs) |

Window lengths, and whether "same topic" is matched by campaign, pack or
free text: `TBD` in Phase 0. The pack is generated fresh per run and carries
its generation date in `00-engagement.md`; cite that date, never "today".

## Writing the section

Four paragraphs, in this order, each answerable from one file:

1. **What this audience heard recently** — from `01`. Name the two or three
   most recent items with their dates and channels. If the file is empty,
   write that: "No recorded communication to this audience in the window"
   is information the speaker uses.
2. **What is coming** — from `02`. The speaker's own next appearances first
   (nothing is worse than a speaker announcing something a colleague
   announces first tomorrow), then other executives into the same audience.
3. **Collisions** — from `03`. State each pair and its shared surface in one
   sentence. Severity language comes from the file; do not re-grade it.
4. **Sensitivities** — only what the supplied sources in `04` support. This
   is the one paragraph that may be omitted entirely when the sources give
   nothing; an invented sensitivity is worse than none.

## Discipline

- Every date, count and title is read from the pack verbatim. Nothing is
  computed — no "roughly", no totals the files do not print.
- Every paragraph names the file it came from in a trailing footnote line,
  so the reviewer can check it in one step.
- An empty pack does not fail the brief: the section is written with what
  is there, and the gaps are stated as gaps.
- The pack is planning data. It says what is scheduled, not what was
  actually published or how it landed — do not claim reach, sentiment or
  outcome from it.
