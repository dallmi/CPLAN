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

### V6 local database

V6 introduces a local database API with create, list, and versioned patch operations. Its current dashboard form covers only a subset of the source-system fields. PostgreSQL is the preferred backend; SQLite is the explicit fallback.

## Implementation gaps to resolve

Before implementing feature-complete creation, align the database, API, and UI with the source forms:

- model communication packs and tracking clusters as first-class records;
- add the missing internal/external activity fields, including audience size, time zone, visibility, communication pillars, executive involvement, and Pitch state;
- add the missing pack fields, including category, launch date, alignment dimensions, and cluster relation;
- define lookup-list sources and whether fields are single- or multi-select;
- define required fields separately for internal activity, external activity, and pack creation;
- generate tracking IDs centrally and enforce uniqueness;
- preserve source identifiers and optimistic-concurrency metadata during migration;
- decide whether current post-creation relationship immutability remains a business rule in V6;
- keep internal and external form differences explicit rather than forcing one universal form.

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
- the V6 API and dashboard implementation.

The images are reference evidence only, are excluded from Git, and are not linked from this document. Form labels and required-field status are a dated snapshot and may change in SharePoint.