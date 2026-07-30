# CPLAN domain and product knowledge base

Status: 2026-07-22

This document captures the domain model and current SharePoint-backed entry experience needed to evolve CPLAN. It intentionally uses organisation-neutral language and excludes screenshots, personal names, confidential identifiers, and company branding.

## Product purpose

CPLAN is a communication planning and monitoring tool. Its core jobs are:

- align messages, timing, and channels across internal and external communication;
- support prioritisation, forward planning, and resource coordination;
- give planners a consolidated view of communication activity;
- support proactive message and communication-risk management;
- connect planned activity with cross-channel performance reporting.

Activities expected in CPLAN include mass communication, communication involving senior leaders, and communication whose performance needs to be tracked.

CPLAN is a planning and communication tool, not a workflow or approval engine.

## Domain hierarchy

CPLAN uses a three-level hierarchy:

1. **Tracking cluster** — groups related communication packs so their performance can be analysed together. A cluster normally contains at least two packs.
2. **Communication pack** — groups activities around one communication objective and a defined start/end period. A pack can belong to a tracking cluster or stand alone.
3. **Communication activity** — a single communication item such as an email, article, event, video, takeover, or social post. An activity can belong to a communication pack or stand alone.

The relationship is:

```text
Tracking cluster
└── Communication pack
    └── Communication activity
```

## Tracking IDs and analytics

A communication activity tracking ID is composed from identifiers carried through the hierarchy plus activity-level attributes:

```text
<cluster ID>-<pack number>-<publication date>-<activity number>-<channel code>
```

For standalone activities, generic cluster and pack identifiers are used. Tracking IDs enable:

- aggregation of activity metrics at pack and cluster level;
- cross-channel unique-visitor measurement;
- views and engagement reporting by channel;
- comparison of packs and clusters;
- analysis of preferred channels for defined audiences.

The SharePoint experience indicates that the activity tracking ID is generated after creation rather than entered manually.

## Current SharePoint-backed record types

The current source system uses separate SharePoint lists and entry forms for:

- internal communication activities;
- external communication activities;
- communication packs.

Asterisks in the current forms mark required fields. Lookup controls commonly display `Find items`; long organisational and location lists are searchable and scrollable.

### Internal communication activity

Observed fields in the current form:

| Group | Fields |
|---|---|
| Identity | Activity name*, Communication pack, generated Tracking ID |
| Classification | Channel*, Priority*, Communications pillars* |
| Content | Activity description* with rich-text controls |
| Visibility | News digest toggle, Hide from public view toggle |
| Audience | Target audience*, Estimated audience size* |
| Organisation | Business Division(s) / function(s)*, Business Area(s), Region(s) / location(s)* |
| Schedule | Start date/time*, End date/time*, Time zone* |
| Ownership | Lead*, Lead Team*, Partner Team |
| Leadership | Senior executives, Other executives involved |
| Delivery | Integrated Pitch action, attachments where enabled, Save and Cancel |

Observed target-audience values include all staff, line managers only, permanent staff only, subscribers, and targeted group.

Observed audience-size bands are `< 1000`, `1–10k`, `10–50k`, `50–100k`, and `> 100k`.

The News digest toggle controls whether the activity should be considered for the digest. The training material also describes the Pitch as integrated into the internal activity and required for the relevant activity type.

### External communication activity

Observed fields in the current form:

| Group | Fields |
|---|---|
| Identity | Activity name*, Communication pack, generated Tracking ID |
| Classification | Channel*, Priority*, Communications pillars* |
| Content | Activity description* with rich-text controls |
| Visibility | Hide from public view toggle |
| Audience | Target audience |
| Organisation | Business Division(s) / function(s), Business Area(s), Region(s) / location(s)* |
| Schedule | Start date/time*, End date/time*, Time zone* |
| Ownership | Lead*, Lead Team*, Partner Team |
| Leadership | Senior executives, Other executives involved |
| Delivery | Save and Cancel |

The external form does not show the internal News digest control.

### Communication pack

Observed fields in the current form:

| Group | Fields |
|---|---|
| Identity | Name of communication pack*, Tracking cluster, Category* |
| Schedule | Start date*, End date*, Launch date |
| Content | Short description* with rich-text controls |
| Ownership | Lead*, Lead team*, Partner team |
| Organisation | Business Division(s) / function(s), Region(s) / location(s)* |
| Alignment | Communication Pillars*, Pillars, Principles, Behaviors |
| Delivery | Save and Cancel |

Observed category guidance distinguishes campaigns, recurring or launch-related events, and internationally recognised days. A pack should be concise but descriptive enough to distinguish it from other packs in the same cluster.

## Creation rules inferred from the supplied guidance

- Select an existing communication pack only when the activity is known to belong to it; do not guess.
- Select an existing tracking cluster only when the pack clearly belongs to it.
- The supplied guidance states that pack membership cannot be added or edited after an activity is created in the current experience.
- The supplied guidance states that tracking-cluster membership cannot be changed after a communication pack is created in the current experience.
- Activity and pack descriptions should explain purpose and content clearly enough for planners to differentiate records.
- Strategic alignment fields should be completed deliberately; an `Other` choice can require further justification.
- Save creates the SharePoint list item; tracking identifiers are system-generated where applicable.

These behavioural rules came from user guidance material and should be verified against the live SharePoint configuration before implementing irreversible validation.

## Current repository implementation

### Snapshot pipeline

`pipeline/scripts/process_cplan.py` imports SharePoint-list CSV exports, normalises encoded column names and lookup values, and produces DuckDB, Parquet, JSON, and HTML dashboard outputs.

### V5 SharePoint draft

The generated V5 draft provides controlled update write-back for existing activities:

- open an existing activity;
- edit an allowlisted subset of scalar fields;
- save the changes as a local draft;
- review queued drafts;
- send eligible updates to SharePoint with item identity, modified-date, and ETag conflict checks.

V5 does **not** currently provide a create-new-activity form or a SharePoint item-create request.

### Local database

The planning studio (formerly the V6 draft) introduces a local database API with create, list, and versioned patch operations. PostgreSQL is the preferred backend; SQLite is the explicit fallback.

The dashboard now includes a create-activity flow with separate internal and external variants, each with its own required-field set. Tracking IDs are no longer entered manually: the API generates them on save (`CLUSTER-PACKNUM-YYMMDD-ACTNUM-CHANNELABBR`, derived from the communication pack, the activity's start date, and its channel) and rejects a client-supplied `tracking_id`, matching the SharePoint behaviour noted above. A `time_zone` field is now stored per activity. The dashboard's "Estimated audience size" band selector (`< 1000`, `1–10k`, `10–50k`, `50–100k`, `> 100k`) is backed by the existing `audience` column — this is a mapping assumption (the ETL only records it as a generic SharePoint lookup field, `"Audience"` → `audience`, with no confirmed link to the "Estimated audience size" label) and should be verified against the live SharePoint field definition. The dashboard form still covers only a subset of the source-system fields; see the gaps below.

Another assumption to verify against the source system: `start_date`/`end_date` are entered through a `datetime-local` field, so the dashboard reads them in whatever wall-clock time zone the browser is running in, converts that to a UTC instant on save, and stores only the instant. The per-activity `time_zone` field is independent, descriptive metadata (e.g. for display) — it does not re-interpret or shift the stored instant, so an activity's displayed local time depends on the viewer's browser time zone, not on its `time_zone` value.

A daily sync job (`pipeline/api/sync_snapshot.py`, orchestrated end-to-end by `pipeline/scripts/daily_refresh.py`) mirrors the SharePoint export into the database — source wins on conflicts, nothing is ever deleted — while leaving activities created directly in the studio untouched. This is the intended migration strategy: rather than a single cutover, the studio runs in **parallel operation** with the SharePoint source for as long as needed, so planners can use it for real work immediately while the mirrored data stays trustworthy, and the source system can be retired only once the studio fully replaces it.

Every write path (studio create/edit, the daily sync, and the one-time seed) also records a field-level change history (`activity_changes` table, one row per created activity or per changed field on an update, tagged with an actor of `studio`/`sync`/`seed`) in the same transaction as the data change itself. The drawer's read-only History panel surfaces this per activity — the demo argument being that the SharePoint source cannot show what changed when, and CPLAN now can. See `pipeline/api/README.md` for the schema and endpoint.

### Planning completeness

Both dashboards score each activity's planning completeness against the fields a planner actually controls in the entry form: activity name, start date, channel, lead team (or lead), target audience, priority, strategic objectives, and activity description. Pack/campaign linkage is intentionally excluded from this score and tracked as its own metric (`missingPackIds`, shown as "Missing pack/campaign"), because pack membership must never be guessed onto an activity — a legitimate standalone activity is fully complete once its own fields are filled in, even with no pack.

### Priority

Two vocabularies reach the dashboards and both are live at once.

Activities created in the studio use its own entry form, which offers **Critical / High / Medium / Low**. Activities mirrored in from the source system do not: their priority is a *numbered label* of the form `<n> - <label>`, with **four levels, 1 the most urgent and 4 the least**. The labels are internal governance wording and are deliberately not reproduced in this repository — only the numbering carries meaning for the code.

The distribution is heavily skewed toward the lowest level: in a production snapshot of roughly 18,000 activities, level 4 held about 65%, level 3 about 18%, level 2 about 16% and level 1 about 1%. Anything that treats "urgent" as levels 1 and 2 is therefore selecting roughly a sixth of the portfolio, which is the intent — not a filter that has gone wrong.

`analytics.js::priorityRank` reads a leading integer first and maps 1 to the top rank, each step down losing one; the words are the fallback, and a value in neither shape lands on the middle rank rather than silently reading as low. `isHighPriority` (rank ≥ 3, i.e. numbered levels 1–2 or the words Critical/High) is the single definition used by both the Overview's "Critical and high" tile and the collision severity in `detectCollisions`, so the two cannot drift apart.

This was a real defect: matching only the words meant every mirrored record fell through to the default rank, the tile read 0 against a portfolio with thousands of level-1 and level-2 activities, and every collision between two top-priority items was scored medium.

### Archiving

The SharePoint source splits internal and external activities into an "active" list and a separate "Archive" list purely because SharePoint list views cap at roughly 5,000 items — archiving is a view-size workaround, not a signal that an activity is less relevant. `pipeline/scripts/process_cplan.py` already merges both lists (de-duplicated) into one dataset with an `is_archived` flag, and the studio's `Activity.is_archive` column carries this forward. The studio treats archived rows as regular data: nothing in the dashboard or its analytics filters on `is_archive`, so archived activities count in every KPI. The intent is to make periodic archiving unnecessary once the studio is the system of record — a database has no 5k-item view limit.

## Implementation gaps to resolve

Before implementing feature-complete creation, align the database, API, and UI with the source forms:

- model communication packs and tracking clusters as first-class records;
- add the still-missing internal/external activity fields: hide-from-public-view visibility, executive involvement, and Pitch state (audience size, time zone, and communication pillars are now implemented — see the audience mapping assumption above);
- add the missing pack fields, including category, launch date, alignment dimensions, and cluster relation;
- define lookup-list sources and whether fields are single- or multi-select;
- define required fields for pack creation (now defined separately for internal and external activity creation);
- preserve source identifiers and optimistic-concurrency metadata during migration;
- decide whether current post-creation relationship immutability remains a business rule in the studio.

## Repository privacy and branding policy

- Do not commit screenshots or other source images. The complete `pictures/` directory is ignored by Git.
- Do not put company names, logos, personal names, production URLs, list IDs, tracking IDs, or confidential source content into code, fixtures, documentation, or generated samples.
- Use generic terms such as `organisation`, `corporate`, `internal`, `external`, and `SharePoint`.
- Use synthetic values in tests and examples.
- Generated dashboard outputs and source exports remain ignored and must not be treated as durable documentation.

## Source and confidence

This knowledge base combines:

- visual review of locally supplied reference images dated 2026-07-22;
- the tracked ETL field mappings;
- the V5 SharePoint draft implementation;
- the planning studio's API and dashboard implementation.

The images are reference evidence only, are excluded from Git, and are not linked from this document. Form labels and required-field status are a dated snapshot and may change in SharePoint.