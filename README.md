# Speaker Brief

Greenfield project for preparing **briefing packs for high-profile speaking
engagements**: one place to capture an engagement (event, date, format,
audience), assemble the speaker's brief (key messages, Q&A, logistics,
biographies), route it for review, and hand over an approved pack.

This repository starts fresh. The only thing carried over from CPLAN is the
corporate **design system** — see [`docs/DESIGN_SYSTEM.md`](docs/DESIGN_SYSTEM.md)
and its implementation in [`app/static/styles.css`](app/static/styles.css).
No CPLAN code, data model, or history is included.

## Current state

- `app/index.html` — static starter screen (engagement list with brief status),
  built on the design system with synthetic sample data. Open it directly in a
  browser; there is no build step and no backend yet.
- `app/static/styles.css` — design tokens plus the core component set
  (shell, navigation, type scale, buttons, KPI tiles, tables, badges, forms,
  notices).
- `docs/DESIGN_SYSTEM.md` — the rules new screens must follow.
- `skills/` — draft skill packages for the AI that assembles briefs
  (brief anatomy, key messages, Q&A anticipation, context-pack reading,
  voice), following the CPLAN agent-skill pattern. Pre-Phase-0 drafts; see
  [`skills/README.md`](skills/README.md).

## Next steps (open)

- Domain model: engagement, brief, section catalogue, review workflow, speaker profiles.
- Backend/persistence decision (CPLAN uses FastAPI + PostgreSQL/SQLite; nothing is decided here yet).
- Brief editor and export (print-ready pack).

## Content policy

Same rule as CPLAN: repository content stays organisation-neutral with
synthetic examples only — no company branding, personal names, production
identifiers, or confidential source content.
