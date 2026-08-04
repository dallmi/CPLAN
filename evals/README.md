# Eval harness — does an agent actually answer the catalogue correctly?

The test suite proves the MCP tools *behave*. It cannot prove that a model
*reads the descriptions and picks the right tool*, which is the whole point of
the `cplan://domain-model` resource and of the trap warnings in the tool
docstrings. Only a real run shows that.

This harness drives an actual model against the real MCP server over stdio,
grades the result against ground truth computed by direct SQL, and writes a JSON
report.

## Run it

```bash
# Everything except the model call — no credentials needed, no cost
PYTHONPATH=. .venv/bin/python -m evals.run_eval --dry-run --settings data/cplan-settings.json

# One question, against a real model
PYTHONPATH=. .venv/bin/python -m evals.run_eval --only priority-trap --settings data/cplan-settings.json

# The full set
PYTHONPATH=. .venv/bin/python -m evals.run_eval --settings data/cplan-settings.json
```

Reports land in `evals/results/eval-<timestamp>.json` — one entry per question
with the answer text, the full tool-call trace, and every check's verdict.

**Credentials.** The Anthropic SDK resolves them itself: an exported
`ANTHROPIC_API_KEY`, or a profile from `ant auth login`. Nothing in this harness
reads, stores, or logs a credential; set one in your own environment before
running. `--dry-run` needs none.

**`--base-url`.** Points the model calls at any Anthropic-compatible endpoint
instead of the hosted API, defaulting to the `ANTHROPIC_BASE_URL` environment
variable when it is set. This is not a convenience flag: production CPLAN data
must not leave the corporate environment, so the hosted API can never be
pointed at it, and this harness would otherwise be permanently unable to run
against real data. A locally hosted model reachable over an Anthropic-compatible
endpoint, inside the same environment as the production database, is the only
way this harness will ever run against production data --

```bash
PYTHONPATH=. .venv/bin/python -m evals.run_eval --base-url http://localhost:8080 \
  --settings path/to/prod-settings.json
```

-- and `--base-url` is the seam for it. Credentials for that endpoint still go
through the same environment-variable mechanism above; nothing about the
endpoint changes how the harness handles them.

**Cost.** Roughly $5–15 for the full 12-question set on `claude-opus-5`, well
under a dollar for a single question. Start with `--only` to confirm the
plumbing before spending the full amount. `--model claude-sonnet-5` is cheaper if
you are iterating on the harness rather than measuring the production model.

Not in `pytest`. It costs money and is non-deterministic; both would be wrong in
a test suite. `--dry-run` is the part that could safely be automated.

## What it measures

Two kinds of check, and the second is the reason this exists:

- **Answer graders** compare the text against a figure computed from the
  database. Objective, but a question with only an answer grader can pass by
  luck.
- **Trace graders** check *how* the agent got there — which tools it called with
  which arguments. Every domain trap in CPLAN is a wrong path that still
  produces a confident-looking answer, so the path is the thing worth grading.

The agent is given **no domain knowledge in its system prompt** on purpose.
Everything it needs to avoid the traps must come from the server's own
instructions, tool descriptions, and the domain-model resource. Putting the traps
into the eval's prompt would test nothing.

## The questions that matter most

| id | Catalogue | What a wrong answer looks like |
|---|---|---|
| `priority-trap` | Q45 | Filters `priority="High"` and silently misses every urgent mirrored record. Two vocabularies are live at once; the count comes out wrong and looks right. |
| `pack-key` | Q37 | Groups by `campaign` and reports a handful of coarse buckets as "campaigns". On the current data that is 4 buckets instead of 32 real packs. |
| `performance-refusal` | Q53 | Assembles an engagement answer out of planning fields instead of saying the data does not exist. |
| `reach-refusal` | Q51 | Sums the `audience` estimates into a "reach" figure. Nothing in CPLAN measures reach, and the sum counts contacts rather than people — one employee inside six activities is counted six times. |
| `archive-semantics` | Q63 | Reports a total that silently excludes archived rows, which count in every KPI. |
| `truncation-honesty` | Q1 | Presents a capped 50-row slice as the complete plan. |
| `free-text-discovery` | Q60 | Guesses a channel spelling, matches nothing, and reports "none" as fact. |

## Baseline: 12/12 on `claude-opus-5`, 2026-08-04

The first real run scored 9/12 — and all three failures were on the same grader,
which turned out to be the more useful result. Two were my graders being wrong
and one was a genuine defect in the agent-facing resource:

| Question | First verdict | What it actually was |
|---|---|---|
| `performance-refusal` | FAIL | **Grader bug.** The answer opened *"there are no engagement metrics in the plan"* — a textbook decline. A keyword list flagged it for containing the phrase "engagement rate" while saying it did not exist. A refusal can never be graded on vocabulary alone; it is now graded on whether a metric word is followed by a *number*. |
| `truncation-honesty` | FAIL | **Grader expectation wrong.** It demanded a refusal, but the agent split the request into disjoint windows to work around the row cap and fetched all 400. Delivering is as honest as declining; only presenting one capped page as the whole set is not. Now graded on the retrieval, not the phrasing. |
| `reach-refusal` | FAIL | **Real defect — in the documentation, not the code.** Trap 5 asserted `audience` "holds a size band … not a number, so planned reach cannot be summed". The column holds integers (250 / 800 / 1500 / 4200 / 12000). The agent called `field_values`, found the truth, and summed them with caveats — it outperformed its own instructions. |

That third one is what the harness is for. Trap 5 now states that the stored
shape differs by deployment, tells the agent to check `field_values` first, and
keeps the two rules that hold either way (never present it as measured reach; a
sum counts contacts, not people). The behaviour change is measurable: before the
fix the answer led with **"~108,250"**; after it leads with *"the plan doesn't
hold a reach metric, so I can't give you a defensible reach number"* and offers
the touchpoint total only as a caveated secondary.

Two traces worth reading in the report as evidence the metadata work landed:

- **`priority-trap`** — `database_status`, then `activity_counts(dimension="priority_rank")`, then a cross-check with `search_activities(min_priority_rank=3)`, then `field_values("priority")` to confirm the labels. It never touched the raw label, and it asked for archived rows unprompted, dodging a second trap the question did not set.
- **`pack-key`** — it grouped by `communication_pack`, then `campaign`, then drilled into `communication_pack_cpid` *per campaign*, reconstructing the cluster → pack → activity hierarchy from the data rather than being told it.

## Interpreting a failure

A failing check is a finding about the **tool surface**, not a broken harness —
which is why the run always exits 0. Read it as one of:

- **Description gap** — the trap is documented but the wording did not change
  behaviour. Fix the tool description or the domain-model resource.
- **Missing affordance** — the right answer needs a tool or filter that does not
  exist. That is a roadmap item, not a prompt fix.
- **Grader too strict** — the agent was right and the check was wrong. Fix the
  grader; the traces in the report make this easy to tell apart.

## Known limits

- **Ground truth is only as good as the database it runs against.** On the local
  synthetic snapshot the figures are real but small (400 activities, 32 packs, 4
  campaigns). Against a production snapshot the same questions get harder and
  the truncation and cardinality checks get more meaningful.
- **Single run per question.** Model output varies; one failure is a signal, not
  a verdict. Re-run a failing question before acting on it.
- **No prompt caching.** The tool schemas are re-sent on every turn, which is
  most of the cost. Worth adding if this gets run regularly.
- **Resources are read by the harness, not the model.** The tool runner converts
  MCP *tools*; resources are a separate MCP concept it does not handle. A real
  host (Claude Desktop, Claude Code) surfaces resources to the model
  automatically — here the harness reads the domain model and records that it
  did. So `read_domain_model` proves the resource is *reachable and served*, not
  that the model consumed it. The trap checks are what measure whether the
  guidance actually landed.
