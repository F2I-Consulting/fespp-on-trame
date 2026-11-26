# Widget: View panel (per-view host + 3D render)

The dockview panel that **composes** the per-view widgets around the 3D render.
This is the unit that makes V2 "each view is self-contained".

## Scope
Per-view — created with a fresh `view_id` + its own `ViewScene`.

## Input
- `view_id` (assigned at panel creation by the layout / view manager).

## Behaviour
- Hosts the **3D render view** bound to the ParaView view of `view_id`
  (`VtkRemoteView`, or `VtkLocalView` if v2 adopts client-side rendering — see
  the IJK first-paint limitation).
- Provides **open/close** affordances for this view's side widgets:
  [data-explorer-tree](data-explorer-tree.md), [attributes-panel](attributes-panel.md),
  [color-legend](color-legend.md), [time-control](time-control.md) — each scoped
  to this `view_id`.
- Camera controls: reset, orient, 2D↔3D toggle; view-linking membership.

## Reads
- The `ViewScene` of `view_id` (from `scene_registry`), camera-link group.

## Writes (back-end / global)
- **[per-view]** `view_update` / `view_reset_camera` (render this view), 2D/3D
  mode, camera-link group membership.

## Notes / open
- Creating a panel = new `view_id` → new `ViewScene` → the per-view widgets bind
  to it. Destroying a panel tears down that scene.
- This replaces the v1 "one render area + a global drawer retargeted to it".
- Hosting point for **licensed add-on panels** (WellLogCorrelation, etc.) via the
  panel-kind registry.
