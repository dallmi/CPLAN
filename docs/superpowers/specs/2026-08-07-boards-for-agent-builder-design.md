# The boards on a surface that retrieves instead of loading

**Date:** 2026-08-07
**Status:** approved

## Problem

`dashboard-boards-skill` landed on main, so three named executive boards now
ship to Copilot Studio as `cplan-dashboards-skill.zip`. The Agent Builder
delivery cannot take it: that surface has no skill packages at all, which is
the fact its whole design turns on.

The obvious move — convert the skill into a knowledge file, as
`07-reading-guide.txt` and `08-chart-standards.txt` already were — does not
survive contact with what a board is for.

**A skill loads whole. A knowledge file is retrieved in chunks.** A board is a
fixed list of panels, and its value is that the list arrives complete: an agent
handed panel 3 of Leadership attention and panel 1 of Plan trust draws a
blended board, which is precisely the failure the boards were built to prevent.
Converting the catalogue to one document would put the whole catalogue —
4,516 characters of index plus three boards of roughly 2,500 each — into one
retrieval target, where any hit returns a fragment of it.

The second constraint is arithmetic, and tighter than it first looks.
`INSTRUCTIONS_TEXT` is 7,779 of the surface's 8,000 characters, so 221 appear
free — but `test_the_instructions_fit_the_field_with_room_to_spare` requires
200 of those to stay spare, because the text is pasted after replacing
`<ORGANISATION>` and an organisation whose name is longer than the 14-character
placeholder must not be the thing that pushes it over. The real budget is
**21 characters**.

And the routing has to live in the prompt: a knowledge file cannot tell an
agent that boards exist. Retrieval answers a question; it never says which
questions have a fixed answer waiting.

## Decisions

**One file per board, never a catalogue.** `09-board-portfolio-overview.txt`,
`10-board-leadership-attention.txt`, `11-board-plan-trust.txt`. Each is small
enough — around 3,000 characters — that a retrieval hit has a real chance of
returning the board entire, and a hit on one board cannot drag in a fragment of
another. Eleven knowledge sources against a limit of twenty.

**Each board file is self-contained, and repeats the shared rules.** This
inverts the Copilot Studio design deliberately. There the rules sit once in
`SKILL.md` and the board files stay lean, because the index always loads. Here
nothing loads: a fourth file holding the shared rules would be a fourth thing
retrieval might miss, and it would be missed exactly when a board *was* found —
the case that matters. Repeating roughly 700 characters three times costs
nothing on a surface with nine spare knowledge slots, and it makes every board
file answer on its own.

The repeated block carries only what a board needs and the prompt does not
already state: draw the listed panels in that order and no others; exactly one
panel is red and the rest are grey throughout; a `Source:` line says where to
read a figure and is never printed as the panel's footnote; and if the file
cannot be seen whole, say so rather than filling in the rest.

**The panel text is not re-authored — it is `dashboard_skill.BOARDS` verbatim.**
Each file is the shared-rules block followed by the board's existing text,
unchanged. Two products must not ship two versions of the same board, and the
citation test that resolves every `Source:` line against a generated pack
already covers this text — re-authoring it would need a second such test and
would still drift.

**The routing joins the `## Your files` list, where the other two rule
documents already are.** That list names `07-reading-guide.txt` and
`08-chart-standards.txt` beside the six data files, and closes with a sentence
saying when to open each. The boards belong in exactly that shape — one line
naming the set, and a clause on the sentence that already says when to open a
rule document. Two hundred characters:

> `- 09–11-board-*.txt — one per named executive board: portfolio overview, leadership attention, plan trust`
>
> …appended to the existing "Open `07`… before you answer and `08`… before you
> draw" sentence: *Draw a board only from its own file; if none is named, say
> which three there are and ask.*

The list line does double duty: it is the routing entry, and it is how the
agent knows the three names without retrieving anything — so it can answer
"which boards are there?" even on a turn where retrieval finds nothing.

**Two hundred and four characters come from cutting two justifications, not
two rules.** The prompt has no room otherwise, and these are the only passages
in it that explain rather than instruct:

- In the footer section: *"A footer that appears once and then stops is worse
  than none: the reader has learnt to expect a vintage, so its absence reads as
  'still current'."* — 146 characters of reasoning for a rule that survives it.
  The obligation itself (**every turn carries it**, the four-week staleness
  note, the restate-the-date instruction) stays.
- In the answer format: *"A caption says what the chart means, not what it
  shows."* — 58 characters refining a rule whose statement stays.

Neither absence makes an answer wrong, which is the test the compression
already applies to everything in this field. Net effect: 204 freed, 200 spent,
headroom moves from 221 to 225.

The truncation case needs no prompt characters. The instructions already say to
say so rather than estimate when a file cannot be seen whole, and the repeated
block in each board file states it again for the board.

**A fifth starter prompt names a board.** The four existing ones deliberately
cover one per audience plus one crossing two dimensions. A user who does not
know boards exist has no way to discover them — the prompt only reacts to a
dashboard being asked for. One starter prompt is the discovery path, and the
Configure tab has room.

## What changes

`pipeline/report/agent_builder.py`:

| | |
|---|---|
| `BOARD_FILE_PREFIXES` | `09`, `10`, `11`, paired with `dashboard_skill.BOARDS` keys in their existing order |
| `BOARD_RULES_TEXT` | the repeated block, one constant, prepended to every board file |
| `INSTRUCTIONS_TEXT` | the board line and clause in `## Your files` (+200), minus the two justifications (−204) |
| `STARTER_PROMPTS_TEXT` | plus one board prompt |
| `README_TEXT` | its starter-prompt count moves from four to five. It states no upload count, so nothing else there changes |
| `write_builder_pack` | writes the three board files into `upload/` |

`tests/test_agent_builder.py` gains: the instructions still fit 8,000; the
upload folder holds eleven files and no more than `KNOWLEDGE_SOURCE_LIMIT`;
each board file contains its board's text unmodified from `dashboard_skill`;
each contains the shared-rules block; each still carries exactly one
`Highlight: yes`; and the prompt names all three boards.

`check.ps1` gains a marker for the changed file and a version bump, as every
change to a manifest-listed file must.

## Out of scope

**The index's other content.** The Copilot Studio `SKILL.md` also explains the
five-field panel contract and the `Source` citation grammar in detail. A board
file demonstrates both by its own layout, and the parts that are rules rather
than explanation are in the repeated block. Shipping the explanation three
times would triple the cost of the thing most likely to be skimmed.

**A board-specific evaluation set.** Agent Builder documents no evaluation
import, which is why `evaluation.csv` is already dropped from this delivery.

**Deferring to `07-reading-guide.txt`.** It could name the boards, but it is
the guidance document for how to work an analysis, and a pointer there would be
a fourth place retrieval might or might not reach. The prompt is the only
routing surface that always applies.
