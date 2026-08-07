# The agent pack for Agent Builder, where there are no skills

**Date:** 2026-08-07
**Status:** draft

## Problem

The agent this repository builds cannot reach its users yet. Publishing it
through Copilot Studio inside the organisation needs registration and review,
and that runs on someone else's calendar. Agent Builder — the lightweight agent
surface in Microsoft 365 Copilot — needs none of that: an agent built there can
be shared with named people, or exported as a ZIP for an administrator, on the
day it is finished. A small group of test users can have it this week.

The price is a much smaller box, and the box is the wrong shape rather than
merely smaller.

## What Agent Builder allows

From the Microsoft Learn documentation for Agent Builder and for declarative
agents, read 2026-08-07:

| | |
|---|---|
| Instructions | **8,000 characters** |
| Description | 1,000 characters |
| Name | 30 characters |
| Knowledge sources | up to 20: ≤100 SharePoint files, ≤50 OneDrive files, device uploads, ≤4 public URLs, ≤5 Teams chats |
| Capabilities | code interpreter, image generator, web search |
| Skill packages | **none** |

The last row is the one that decides this design. "Skills" in Agent Builder
means the built-in capabilities above, or MCP and API plugins registered as
actions. There is no equivalent of the `.zip` archives this repository writes,
and no mechanism that loads a document at the start of a turn.

## Why this is not a smaller version of the same thing

What the repository ships today for Copilot Studio:

| Artefact | Characters |
|---|---|
| `agent-instructions.md` | 14,423 |
| `cplan-skill.zip` (`SKILL.md` plus six data files) | 4,388 + data |
| `chart-standards-skill.zip` | 5,612 |

Twenty-four thousand characters of prose against a field that holds eight
thousand. But the arithmetic is the easy part. Two decisions this repository
made deliberately are unavailable here, and both were made for reasons that
have not stopped being true.

**The rules were moved out of Instructions and into skills** (c508b22,
a63a299). What survives in Instructions is the floor — the rules a chart is
wrong on sight for breaking — and everything else lives where a skill loads it.
Agent Builder has nowhere for the second half to go except a knowledge file,
which is retrieved rather than loaded.

**The knowledge source was removed** (1595874). Two probes showed it was never
reached for: a needle question found its row by reading the file, and a counting
question answered by examining all 1,385 rows, which is the one thing chunked
retrieval cannot do. A second grounding path never taken still has to be
re-uploaded on every refresh, and a pack refreshed on one path and not the other
hands the agent two vintages of the same figure.

In Agent Builder the knowledge source is not a second path. It is the only one.

So this variant inverts both decisions, and it does so because the surface
leaves no alternative, not because the reasoning behind them was wrong.

## Decisions

**The data files do not change.** `agent_pack.py` keeps producing
`00-README` through `06-breakdowns` exactly as it does now, through the same
`resolve_scope` and the same `pack_config`. Both variants render one pipeline
run. A second scope would be a second set of figures, and the whole repository
is built to prevent that.

**`06-breakdowns.csv` is cherry-picked onto this branch** (`fd4982d`, from
`dashboard-boards-skill`). It crosses two dimensions in a file because the
calendar crosses none, and it is the only route to a question like which
division binds the most executive attention that does not require counting the
activities file by hand. On main that is a convenience. Here it is load-bearing:
counting by hand is the thing this surface is least able to do. The commit
touches `check.ps1`, `agent_pack.py` and `tests/test_agent_pack.py` and nothing
the boards own, so it lifts cleanly — at the price of one conflict in
`agent_pack.py` to resolve when `dashboard-boards-skill` reaches main.

**The delivery shape is a separate module.** `pipeline/report/agent_builder.py`
composes what Agent Builder needs — compressed instructions, a description, the
knowledge file set — beside `agent_pack.py` rather than inside it. The data
layer is shared; the delivery shapes have almost nothing in common, and a flag
threaded through `write_pack` would put two audiences in one function.

**The compressed instructions are hand-written, not derived.** A second literal
constant, not a transform over the existing one. Which rules survive a
four-fifths cut is an editorial judgement about what a reader can be trusted to
infer, and a mechanical compressor would produce prose that reads like a
mechanical compressor. The two are held together by a test, not by a function.

**The floor carries more weight here.** In Copilot Studio the palette can sit in
a skill because the skill loads before the agent draws. Here it would sit in a
document that may or may not be retrieved. So the palette, the ratio, the
typography rules and the chart mechanics move into Instructions, and only the
chart-type guidance — which chart answers which question, how to place panels —
stays in a document. If the document is missed, the agent draws an ugly chart
that is still on-brand. That is the failure worth engineering for.

**The rule documents are `.txt`, not `.md`.** The same reason the pack already
gives: Markdown is not on the crawled-extension list, and a file that is not
crawled is not retrievable.

**The instructions file carries no header for a human.** The Studio version
opens with an HTML comment telling the operator to replace `<ORGANISATION>`.
Here that comment would spend 330 of 8,000 characters on a sentence the model
does not need, and a pasted comment is a paste that includes it. The instruction
moves to the console output and to the README beside the file. What is in
`instructions.md` is exactly what goes in the field.

**`<ORGANISATION>` stays a placeholder.** One find-and-replace, same as today.
This file ships through a public repository.

**The output lands in `Projekte/CPLAN/Output/agent-builder`.** The Studio pack
lands in `Input` because it sits beside the Power Automate export it is built
from, and nothing there deletes or collides with it. This variant is not an
input to anything, and its folder is a set of files to upload rather than a set
to read. `ONEDRIVE_OUTPUT_DIR` joins `ONEDRIVE_INPUT_DIR` in
`process_cplan.py`; the local fallback is `pipeline/output/agent-builder/`.

**`Output/` is created, but only when `Input/` proves the sync is real.**
`resolve_output_dir` never creates its target today, and the reason is good: a
path conjured inside a OneDrive that is not really set up syncs nowhere while
looking like it worked. But `Output/` may legitimately not exist yet, and under
the unmodified rule the pack would fall silently back to a folder inside a git
checkout — which is exactly the failure that rule exists to prevent, arriving
by the other door. Anchoring on `Input/` keeps the property being bought: if the
CPLAN folder is really there, its sibling can be created safely; if it is not,
nothing is created and the fallback is reported.

## What gets built

`<OneDrive>/Projekte/CPLAN/Output/agent-builder/`, or
`pipeline/output/agent-builder/` when OneDrive is not set up:

| | |
|---|---|
| `upload/` | the eight files that go into **Knowledge**, and nothing else |
| `instructions.md` | ≤ 8,000 characters. Exactly what is pasted into Instructions |
| `description.txt` | ≤ 1,000 characters, for the Description field |
| `starter-prompts.md` | four conversation starters |
| `README.txt` | what to upload where, and the one find-and-replace |
| `checklist.md` | questions with computed answers. **Not for uploading** |

`upload/` holds the same six data files `cplan-skill.zip` carries —
`01-summary` through `06-breakdowns` — and two documents converted from the
skills:

- `07-reading-guide.txt` — from `cplan-reporting`: which file answers what, how
  to read for each audience, the four analysis steps, the questions this pack
  answers well. Minus whatever has moved into Instructions.
- `08-chart-standards.txt` — from `chart-standards`: chart-type selection,
  multi-panel layout, the checklist to read an image against. Minus the palette
  and the ratio, which are now in Instructions.

`00-README.txt` is not uploaded, for the reason `cplan-skill.zip` already
leaves it out: it explains the pack to a person, and `07-reading-guide.txt`
does that job for the agent.

Eight sources against a limit of twenty, which leaves room for the boards if
`dashboard-boards-skill` lands on main and this branch takes them.

`checklist.md` stays outside `upload/` for the reason it stays outside `pack/`
today: an agent that can read the answer key passes without computing anything.

`evaluation.csv` is dropped. It exists because Copilot Studio imports an
evaluation set; Agent Builder documents no equivalent. The checklist covers the
same questions for a human running them by hand.

## How the 8,000 characters are spent

Budgeted with `<ORGANISATION>` still in place, leaving headroom for an
organisation whose name is longer than the placeholder:

| | Characters |
|---|---|
| Identity, purpose, which file answers what | 900 |
| Evidence first, quantify, explain the calculation, surface data quality | 1,200 |
| CPLAN data rules: scope, overlaps, audience is not reach, GEB/GEB-1, multi-value fields, weekly placement, wider than the workbook | 1,800 |
| Chart floor: the palette table, the ratio, typography, mechanics | 1,800 |
| Output format, and saying each figure once | 700 |
| The three follow-up questions | 500 |
| The footer line | 500 |
| Pointers to the two rule documents | 300 |
| | **7,700** |

## Tests

`tests/test_agent_builder.py`, in the spirit of `test_agent_pack.py` holding the
pack and the workbook to each other:

- The instructions fit 8,000 characters and the description fits 1,000, both
  measured with the placeholder in and both with headroom stated as a number
  rather than assumed.
- Every non-negotiable rule the Studio instructions state also appears in the
  compressed version. A named list of markers, so an edit that drops one fails
  loudly instead of shipping an agent that is quietly missing a rule.
- `upload/` holds exactly the eight expected files, and does not hold
  `checklist.md` or `00-README.txt`. The answer key cannot become knowledge.
- The knowledge file count stays at or under twenty.
- The data files in `upload/` are byte-identical to what `agent_pack.write_pack`
  produces. Two renderings of one report, or the divergence is a bug.
- The builder's own output resolver — not `build_agent_pack.resolve_output_dir`,
  which keeps pointing at `Input/` — creates `Output/agent-builder` when
  `Input/` exists, creates nothing when it does not, and reports the fallback
  either way.
- No organisation name appears in any emitted file.

## What this design cannot promise

**Counting may break, and the test build is what finds out.** The Studio agent
counts correctly because it reads all 1,385 rows of `05-activities.csv` as a
file. Chunked retrieval is named in the README as the one thing that cannot do
that, and Agent Builder offers no other path. Three mitigations are real but
partial: `06-breakdowns.csv` pre-computes the measures, `01-summary.txt` carries
the portfolio figures, and the instructions push harder toward both than the
Studio version needs to. Code interpreter may rescue it — but whether a
knowledge-source file reaches the Python sandbox is documented neither way, and
a design cannot assume it.

The signal to watch is the one the README already names: the agent stops writing
"examined all N rows" and starts naming a subset. If that happens, the honest
response is to widen `06-breakdowns.csv` rather than to let the agent estimate.

**The chart-type guidance is a hope, not a load.** "Load that skill before you
draw, every time" has no equivalent instruction here. This is why the palette
moved into Instructions, and it is the reason to expect this agent's charts to
be more conservative than the Studio agent's rather than merely worse.

**The two agents will answer slightly differently.** Same figures, different
prose, because the instructions differ. That is acceptable while this is a test
build for a small group and would not be acceptable if both ran in production
for overlapping audiences.

## Out of scope

- The three named boards. They live on `dashboard-boards-skill`, which has not
  merged to main. This branch forks from main and picks them up in a normal
  merge if and when they land. Only `06-breakdowns.csv` was lifted early, and
  only because the counting risk here makes it load-bearing rather than
  convenient.
- Moving the Studio pack out of `Input/`. Its reason for being there still
  holds.
- MCP or API plugins as actions. The repository has an MCP server, and pointing
  Agent Builder at it would remove the counting problem entirely — but it needs
  a reachable endpoint and the registration this whole variant exists to avoid.
