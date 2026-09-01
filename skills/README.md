# Skills

Draft skill packages for the AI that assembles speaker briefs. The format and
the discipline follow CPLAN's agent skills (`cplan-reporting`,
`chart-standards`, `cplan-dashboards`): **one skill per concern**, a
`description` written as the trigger that selects it, rules stated in plain
words with the reason beside them.

| Skill | Concern | Carries data? |
|---|---|---|
| `brief-anatomy` | Which sections make a brief, in what order, per format | no |
| `key-messages` | How key messages are drafted and what disqualifies one | no |
| `qa-anticipation` | How the anticipated Q&A is built, incl. the referral rule | no |
| `engagement-context` | How to read the per-engagement data pack from CPLAN | no (defines the pack contract) |
| `brief-voice` | Tone, language, and form — organisation-free, liftable | no |

The split is not tidiness. A single instruction blob is where rules get
dropped: CPLAN measured exactly that on 2026-08-06 when an agent asked for "a
dashboard" reinvented the panel list and broke three stated rules in one
render. A skill fixes the decision before the writing starts.

## Status

These are **starting-point drafts, written before Phase 0**. The brief anatomy
in `brief-anatomy` is a hypothesis — it must be corrected against 2–3 real
(anonymised) briefs before anything is built on it. Everything marked `TBD`
is a Phase-0 question.

## Packaging

- **Copilot Studio**: each directory zips to `<name>-skill.zip` with
  `SKILL.md` at the archive root — same shape as CPLAN's
  `pipeline/report/agent_pack.py` produces.
- **Agent Builder** has no skill mechanism (see CPLAN's
  `2026-08-07-agent-builder-variant-design.md`): there, the floor rules from
  these skills are condensed into the 8,000-character Instructions field and
  the rest ships as knowledge files, accepting retrieval instead of loading.
- **Claude / MCP hosts**: the directories work as-is as filesystem skills.

Per-engagement data (the context pack `engagement-context` reads) is generated
per run and is never part of a skill zip — a skill is rebuilt only when a rule
changes, a pack on every run. Mixing the two hands the agent two vintages of
the same fact.
