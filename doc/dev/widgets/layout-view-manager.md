# Widget: Layout / view manager (global)

Owns the dockview layout and the **set of views**. The piece that makes
multi-view real in V2.

## Scope
Global.

## Input
- Add / split / remove / rename view requests (from the toolbar or panel tabs).

## Behaviour
- Creates a view: allocates a `view_id`, a ParaView view, a `ViewScene` in the
  `scene_registry`, and a [view-panel](view-panel.md) bound to it.
- Removes a view: tears down its scene + per-view state.
- Manages **camera-link groups** (broadcast camera across a set of views).
- Persists / restores the dockview layout (which panels, where, open/closed
  side widgets).
- Hosts **panel kinds** via a registry, so licensed add-on panels
  (WellLogCorrelation, …) and the analysis panels register and open like any view.

## Reads
- The current set of `view_id`s, the dockview layout, camera-link groups.

## Writes (back-end / global)
- **[session]** the set of `view_id`s (create/destroy → `scene_registry`), the
  layout, camera-link group membership.
- On destroy: removes that view's per-view state slices.

## Notes / open
- This is where the **panel-kind registry + plugin loader** lives (the hook
  pattern from the OSDU discussion) — the generic extension point that lets
  optional / licensed widgets plug in without the core knowing them.
- Per-view state storage decision (Section 9 of ARCHITECTURE): keep `*_by_view`
  dicts keyed by `view_id`, cleaned up here on view destroy.
