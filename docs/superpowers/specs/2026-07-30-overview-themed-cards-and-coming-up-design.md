# Studio Overview: Themed Collection Cards & Coming-Up Redesign — Design

**Date:** 2026-07-30
**Status:** Approved by Michael (scope: studio Overview only — the standalone
dashboard is not touched)

## Problem

Two separate observations, both about the Overview list view.

**1. The six KPI tiles are flat.** They carry six unrelated figures in one row
of identical tiles, and the reader has to work out which belong together. The
standalone dashboard and the `campaignwe` project both group their figures by
theme; the studio does not. The standalone also carries figures the studio
lacks entirely — the internal/external split of the total, and how many
activities are running right now.

**2. `Coming up` reads worse than the standalone's upcoming list.** The studio
renders `.list-row`s with a severity bar and a text date. The standalone uses a
48px date box (large day, small month, tinted by source type) which is faster to
scan. The studio's version is also capped at eight rows, so on a busy portfolio
most of the horizon is unreachable from the card.

## Prior art and the decision being reversed

`app.js:833-840` records that the Overview *already had* four themed collection
cards holding sixteen rows, and that they were deliberately replaced by the
current six flat tiles. The reasoning on record: the collection cards served a
comms lead scanning the whole portfolio a few times a year, whereas the screen's
owner is the planner who is in it daily and needs "what do I do next"; sixteen
figures cannot rank themselves.

**This design reverses that decision on Michael's explicit instruction.** The
comment is rewritten, not deleted — it must continue to state that the cards
were here before, why they left, and that they are back by choice. Losing that
history twice would invite a third round.

## Decisions from brainstorming

1. Themed collection cards replace the Overview tiles (not the standalone, not a
   separate studio page).
2. Four themes: **Portfolio / In flight / Readiness / Lead time**.
3. Cards are **display only** — no navigation, no movement chips, following
   `campaignwe`.
4. In `Coming up`, the channel colour becomes a **3px edge on the left of the
   row**; the date box stays neutral and tinted by source type.
5. Horizon is a **rolling 7 days**, not the calendar week.
6. The list **scrolls inside the card**, and the card matches the height of
   `Needs you first` beside it.

All user-facing strings are English. The app has no German UI.

---

## Part 1 — Themed collection cards

### Markup

`#overview-kpis` keeps its id and its position but changes class from
`kpi-grid five` to `kpi-groups`. A new helper beside `kpi()` in `app.js`:

```js
function kpiGroup(title, cls, rows) { … }
// rows: [{v, l, derived?}]
// → <div class="kpi-group {cls}"><div class="kpi-group-title">…</div>
//      <div class="kpi-row [derived]"><span class="v">…</span><span class="l">…</span></div>×n
//    </div>
```

`kpi()` itself stays. It is still used by Timeline (`app.js:964`), Health
(`app.js:1147`) and Packs (`app.js:1366`); only the Overview stops calling it.

### Rows and sources

All four cards read `rows` (= `state.rows`), which the global time filter has
already narrowed. That is what makes "total activities for the filtered range"
true without extra work.

| Card | Row | Source |
|---|---|---|
| **Portfolio** | Total activities | `rows.length` |
| | Internal | `internal` |
| | External | `external` |
| | Critical and high | `highPriority.length` |
| **In flight** | Active now | `active.length` |
| | Starts within 7 days | `start_date` within `[now, now+7d]` |
| | Ends within 7 days | `end_date` within `[now, now+7d]` |
| | Next 30 days | `upcoming.length` |

The two seven-day rows are labelled `within 7 days`, not `this week`. The window
is rolling, matching `Coming up`; calling it "this week" would promise a calendar
week the code does not compute — and on a Thursday the two readings differ by
most of their contents.
| **Readiness** | Incomplete | `incompleteRows.length` |
| | Complete \* | `quality.completenessRate` |
| | No pack | `quality.missingPackIds` |
| | Invalid dates | `quality.invalidDateRanges` |
| **Lead time** | Median lead | `lead.median` |
| | On short notice | `lead.shortNotice` |
| | Short-notice rate \* | `lead.shortNoticeRate` |
| | Excluded | `lead.excluded` |

\* renders with the `derived` modifier (dimmed), as in `campaignwe`.

`Ends within 7 days` is the only genuinely new measure; everything else already
exists in `renderOverview`. `active`, `upcoming`, `internal`, `external`,
`quality`, `lead`, `highPriority` and `incompleteRows` are all computed today at
`app.js:640-704` and are reused unchanged.

**Empty-portfolio guards.** With `rows.length === 0`, `Complete` and
`Median lead` render `—`, not `0%` and not `0d`. Nothing is incomplete when
nothing exists, and a median over an empty set is not zero.

### Accent colours

A 3px left border and a matching title colour per card, from the existing
palette in `styles.css`:

| Card | Accent |
|---|---|
| Portfolio | `--primary` |
| In flight | `--grey-6` |
| Readiness | `--warning` while findings are open, `--grey-1` when clean |
| Lead time | `--bronze-1` |

Readiness is the one conditional accent. A permanently amber card is a false
alarm on a clean portfolio; the pattern already exists in this codebase as
`.priority-card.danger` (`app.js:709-710`), which colours the queue's top border
only while the queue is non-empty. "Display only" refers to navigation and
deltas, not to status.

### Layout

```css
.kpi-groups{display:grid;grid-template-columns:repeat(4,minmax(210px,1fr));gap:14px;margin-bottom:16px}
.kpi-group{background:var(--white);border:1px solid var(--surface);border-left:3px solid var(--grey-1);padding:14px 16px}
.kpi-group-title{font-size:10px;font-weight:700;letter-spacing:.02em;margin-bottom:10px}
.kpi-group .kpi-row{display:flex;align-items:baseline;justify-content:space-between;gap:10px;padding:5px 0;font-size:12px}
.kpi-group .kpi-row .v{font-size:19px;font-weight:300}
.kpi-group .kpi-row .l{color:var(--grey-5)}
.kpi-group .kpi-row.derived .v,.kpi-group .kpi-row.derived .l{color:var(--grey-4)}
```

The existing breakpoints collapse the grid to two columns below 1000px and one
below 700px, matching `.kpi-grid` today.

`.kpi-grid.five` (`styles.css:348`) loses its only caller and is removed with it.

### What is removed

The comparison-window wiring in `renderOverview`, `app.js:663-696` and
`795-869`:

`previous30`, `win`, `rangeActive`, `windowCur`, `windowPrev`, `spanDays`,
`windowIsProvisional`, `startedIn`, `cmpCur`, `cmpPrev`, `hasBaseline`,
`comparable`, `windowPhrase`, `windowNoun`, `movements`, `trend`,
`renderMovements`, `leadNow`, `leadBefore`, `highNow`, `highBefore`, `shortNow`,
`shortBefore`, `tone`.

**`A.comparisonWindow` stays live** — Health calls it at `app.js:1469` and
renders its own footnote at `1497`, and `tests/analytics.test.js:306-330` covers
it. Only the Overview stops using it. `.kpi-trend` CSS (`styles.css:369-372`)
stays for the same reason.

**No `kpi-footnote` under the grid.** The global `#range-banner`
(`app.js:3077`) already states the active range and that page horizons count
within it. A second statement of the same fact under the cards would be
duplication.

### Routes lost, and where they went

Four tiles carry `data-goto` today. Three of them (`In selected range`,
`On short notice`, `Incomplete` → `activities:incomplete`) point at findings that
the `Needs you first` queue directly below already lists, grouped by type with an
action per group (`app.js:899-901`) — the route survives one card lower.

`Median lead time` → `health:planning-health` is the one route with no
equivalent nearby. Health remains reachable through the main navigation; this is
a deliberate downgrade from one click to two, accepted as part of decision 3.

---

## Part 2 — `Coming up`

### Window

Rolling 7 days on `start_date`: `[now, now + 7d]`, ascending. **The eight-row
cap is removed.** It existed only to bound the card's height (`app.js:907-912`);
the scroll container now bounds the height directly, so capping the count as
well would hide rows for no remaining reason.

Week headings are dropped. They grouped a 30-day list; over seven days with a
date on every row they are redundant.

### Row

```
┃ ┌────┐  Q2 Results — all-staff mail
┃ │ 12 │  Today · Group Comms                    ● Email
┃ │AUG │
┃ └────┘
```

- `┃` — `.event-channel-edge`, 3px, `background: channelColor(row.channel)`;
  `--grey-1` when the row names no channel.
- `.event-date-box` — 48×48, large day, small uppercase month.
  Internal: `--surface` / `--grey-6`. External: `--surface-alt` / `--bronze-3`.
  (`--bronze-tint` is a standalone-only token and does not exist in the studio;
  `--surface-alt` (#F5F0E1) is the studio's warm surface and takes its place.)
- `.event-title` — `activity_name`, falling back to `Untitled`.
- `.event-meta` — relative day, then lead team or lead. The relative token is
  `Today`, `Tomorrow`, then the weekday name. Over a seven-day window that
  carries more than a date already shown in the box.
- The channel chip with its dot stays at the right, unchanged.
- The row keeps `data-open-id`, so it still opens the drawer.

### Scroll and height

Both cards in `#view-list .grid.two` become flex columns of equal height; the
list scrolls inside `Coming up`.

```css
#view-list .grid.two>.card{display:flex;flex-direction:column;min-height:360px;margin-bottom:0}
#view-list .grid.two>.card>.card-body{flex:1}
#view-list .grid.two>.card>.card-body.scroll-y{min-height:0;overflow-y:auto}
.card-foot{padding:11px 16px;border-top:1px solid var(--surface);font-size:11px;color:var(--grey-5)}
```

`scroll-y` is added to the `Coming up` body only. Both cards stretch to the same
height, but `Needs you first` keeps growing with its content and never gets a
scrollbar — it is bounded already, and giving it one would be the scope creep
ruled out below.

`min-height:0` on the scrolling child is load-bearing: without it a flex child
grows to its content instead of scrolling, and the card silently returns to the
988px problem the cap was invented for.

`min-height:360px` on the card is the floor. `Needs you first` sets the row
height, and when no findings are open it collapses to its empty state (~110px);
without the floor `Coming up` would collapse with it.

The row cannot run away upwards either: `Needs you first` is bounded at three
queue groups plus at most five deadline rows (`app.js:887`), roughly 480px.

### Footer

The `N more …` line moves out of the scroll area into a `.card-foot` sibling, so
it stays visible. Its wording changes to count what lies beyond seven days
inside the next thirty: `N more in the next 30 days · See them on the timeline →`.
The existing `data-goto="overview:timeline"` handler is unchanged. The footer is
omitted when the count is zero.

### Accessibility

The scroll container gets `tabindex="0"`, `role="region"` and
`aria-label="Coming up in the next 7 days"`. A scrollable region without a tab
stop cannot be reached by keyboard at all (WCAG 2.1.1).

A subtle bottom gradient marks the scroll boundary; the partially cut last row
is the primary affordance.

### Empty state

`No activities in the next 7 days`, with the existing `emptyState` helper and
`EMPTY_ICONS.calendar`. Subtext points at the wider horizon rather than
suggesting the user wait.

### Card head

`h3` stays `Coming up`; a `p` subtitle reads `Next 7 days`, matching how other
cards on this page state their horizon.

---

## New helpers in `analytics.js`

`app.js` is a browser IIFE with no exports and can only be checked by asserting
on its source text. Anything with real logic goes to `analytics.js`, which is a
module with a node test file:

- `comingUp(rows, now, days)` — rows whose `start_date` falls in `[now, now+days]`,
  ascending. Returns `[]` for unparseable or missing dates rather than throwing.
- `relativeDayLabel(date, now)` — `Today` / `Tomorrow` / weekday name. Compares
  calendar days, not elapsed hours: an activity at 23:00 tonight is `Today`, one
  at 01:00 tomorrow is `Tomorrow`.
- `endingWithin(rows, now, days)` — rows whose `end_date` falls in the window,
  for the `In flight` card.

Neither names any user-facing copy beyond the three day tokens, consistent with
how `analytics.js` is written today.

## Test plan

**`tests/analytics.test.js`** — unit tests for the three new helpers:
`comingUp` boundary behaviour at exactly `now` and exactly `now+7d`, ordering,
tolerance of missing and malformed dates; `relativeDayLabel` across a midnight
boundary and a month boundary; `endingWithin` for rows with no `end_date`.

**`tests/test_studio.py`** — source-text assertions:

- `#overview-kpis` carries `kpi-groups`, and the four titles `Portfolio`,
  `In flight`, `Readiness`, `Lead time` are present.
- The Overview KPI block emits neither `kpi-trend` nor `data-goto`.
- `renderOverview` no longer references `comparisonWindow`, while
  `renderHealth` still does.
- `.kpi-grid.five` is gone from `styles.css` and unreferenced in `index.html`.
- The upcoming list container carries `tabindex="0"`, `role="region"` and an
  `aria-label`.
- `styles.css` contains `min-height:0` on the `#view-list .grid.two` `.scroll-y`
  rule — the regression that would silently reintroduce the tall-card bug.
- No `UPCOMING_SHOWN` constant remains.

**Manual check** against the local snapshot: filter to a range with no
activities and confirm `Complete` and `Median lead` render `—`; clear all
findings and confirm the Readiness accent goes neutral and `Coming up` holds its
360px floor.

## Out of scope

- The standalone dashboard (`pipeline/dashboard/index.html`) keeps its current
  tiles and its own upcoming list. The two are separate deliveries and share no
  CSS.
- `Needs you first` keeps its current markup and its own height. It is not given
  a scroll container.
- The Timeline and Calendar views of the Overview are untouched.
