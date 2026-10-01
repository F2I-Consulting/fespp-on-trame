# trame-fespp-view-card — backlog

v1 (built): draggable + resizable card, clamped to the view, click-to-front
z-order, host-set default size, min-size floors. Below = what's left (carried
over from view-tools when the card was split out).

- **Persist position/size per view** — today position/size are internal Vue
  state (reset on reload); lift to per-view state so a card reopens where it was.
- **Collapse** — double-click header (or a chevron) to roll up to the title bar.
- **Snap** — optional edge snapping / "dock to side" affordance.
- **Reset** — double-click an empty header area to reset to default position/size.
- **A11y / keyboard** — Esc closes the focused card; focus trap; ARIA roles.
- **Theming** — header/card colors are hardcoded (light); add a dark theme / CSS
  variables.
- **Decide**: can the same tool open more than one card? (currently one per host.)
