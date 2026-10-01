# trame-fespp-view-tools — backlog

The per-view **toolbar** (picker). v1 (built): toggle buttons (open/close cards)
+ action buttons. The **FloatingCard** (tool window) was split into its own repo
[`trame-fespp-view-card`](../fespp-on-trame-view-card) — its backlog lives there.

## ViewToolbar
- **Tooltips** on hover (title already passed; render a real tooltip).
- **Groups / separators** — visually group tools (data / display / filters).
- **Orientation** — support top (horizontal) as well as left (vertical).
- **Overflow** — collapse extra buttons into a "⋯" menu when many tools.
- **Active badge** — small dot/count when a tool's card is open.

## Icons
- Today: glyph/emoji passed via `icon`. Add support for an icon set (mdi name
  or inline SVG) so tools look consistent and themable.

## A11y / theming
- Toolbar keyboard navigation + ARIA roles.
- Colors are hardcoded (light); add a dark theme / CSS variables.
