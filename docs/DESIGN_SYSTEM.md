# Design system

Speaker Brief adopts the corporate design system used by CPLAN (v1.0). The
implementation lives in [`app/static/styles.css`](../app/static/styles.css);
this document records the rules so new screens stay inside them.

## Hard constraints

- No gradients.
- No tints of the brand red — `--primary` is used at full strength or not at all.
- No drop shadows on layout surfaces (overlays such as modals/drawers may cast one).
- No rounded corners beyond the 2px `--radius` token.
- No ALL CAPS, no underlines.
- Left-aligned throughout. White dominant; red is a small accent only
  (brand mark, active nav underline, primary button, one deliberate accent per screen at most).
- Colour never carries meaning alone — every colour signal has a text or shape twin.

## Tokens

| Token | Value | Role |
| --- | --- | --- |
| `--primary` | `#E60000` | Brand red — accent only |
| `--primary-dark` | `#8A000A` | Hover state of primary |
| `--black` / `--white` | `#000000` / `#FFFFFF` | Text / dominant surface |
| `--grey-1` … `--grey-6` | `#CCCABC` → `#404040` | Warm grey ramp; greys carry the layout |
| `--bordeaux-1..3` | `#BD000C` → `#620004` | Deep-red ramp (charts, danger) |
| `--bronze-1..3` | `#B98E2C` → `#6C5312` | Secondary accent (notices, external) |
| `--bg` | `#F7F7F5` | Page background |
| `--surface` | `#ECEBE4` | Hairlines, quiet fills |
| `--surface-alt` | `#F5F0E1` | Highlighted quiet fill |
| `--row-alt` | `#F8F7F2` | Row striping / hover |
| `--success` / `--warning` / `--danger` | `#6F7A1A` / `#E4A911` / `#BD000C` | Semantic states |
| `--info` / `--info-dark` | `#0C7EC6` / `#07476F` | Focus rings, inline links |
| `--font` | Frutiger stack | Falls back to Helvetica/Arial/system |
| `--radius` | `2px` | The only corner radius |

## Type scale

| Class | Size / weight | Use |
| --- | --- | --- |
| `.page-title` | 40px / 300 | One per page |
| `.page-subtitle` | 14px / 400 grey | Under the title |
| `.section-heading` | 16px / 600 | Section heads |
| body | 13–14px / 400 | Tables, controls, prose |
| `.footnote` | 11px grey | Counts, provenance |
| `.eyebrow` | 10px / 600 letter-spaced grey | Kicker above a title |

Large numbers (KPI values) are light (300), never bold.

## Idioms

- **Hairlines, not boxes.** Sections are separated by a 1px black rule under the
  heading (`.section-head`); tables use a black rule under the header row and
  `--surface` hairlines between rows. Cards are the exception, bordered in
  `--surface` with a 3px left accent bar when they carry a state.
- **Left accent bars** (`3px solid`) carry state on KPI tiles, notices, and
  primary tiles — never a coloured fill.
- **Focus** is always a 2px `--info` outline; it is never removed.
- **Badges** are grey surfaces whose text colour carries the state; red text is
  reserved for genuine errors.
- **Buttons**: white with a grey border by default; one red `.primary` per view.

## Provenance

Extracted from `pipeline/portal/static/styles.css` and
`pipeline/studio/styles.css` in the CPLAN repository. Component CSS specific to
CPLAN's studio (packs, timelines, donuts, drawers) was deliberately not copied —
add components here as Speaker Brief needs them, following the idioms above.
