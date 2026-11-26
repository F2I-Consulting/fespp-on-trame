# Widget: Navigation (per-view)

3D navigation of one render view: framing, pivot, axis presets, projection.
Packaged widget — `widgets/navigation` (`trame_fespp_navigation`).

## Scope
Per-view — one tool card per render panel (`kinds: ("render",)`; a Globe view
drives its own framing from the Globe card, in ECEF).

## Input
- `has_pick` — a cell was picked in THIS view (gates centre / zoom on it).
- `has_active` — a node is active in this view's tree (gates "frame object").
- `parallel` — the projection is parallel.
- `note` — the last action's feedback (shares `ui_pick_info__<vid>`).

## Behaviour
- **Reset** — fit everything loaded, pivot re-centred.
- **Frame object** — frame the object active in the tree.
- **Centre here / Zoom here** — act on the LAST picked cells: "centre" moves
  only the pivot, "zoom" also pulls the camera in.
- **Look along ±X ±Y ±Z** — axis presets. ParaView only ships the POSITIVE
  three (`ResetActiveCameraToPositiveX/Y/Z`); the negatives are computed here.
- **Parallel projection** — perspective makes the nearer of two equal
  thicknesses look bigger; parallel is what makes them comparable.

## Why the pivot matters
vtk.js orbits around the view's `CenterOfRotation`, **not** its
`CameraFocalPoint`. Setting it on what the user just clicked is what makes
rotation feel right — and forgetting it is why a linked view used to spin
around the wrong point (see `MultiView._sync_camera_from`).

## Reads / writes
- Reads `ui_nav_has_pick__<vid>`, `active_path__<vid>`,
  `ui_nav_parallel__<vid>`, `ui_pick_info__<vid>` **[per-view]**.
- Writes nothing directly: every camera move is a `nav_*` controller in
  `app.boot`, which resolves bounds through `_blocks_for_rep` — the SAME walk
  the Attributes highlight and the cross-plot lasso use, so "frame this
  object" can never disagree with "highlight this object" about what it is.

## Right-click menu on the scene (ViewContextMenu)
The package also ships `ViewContextMenu` — the render's right-click menu,
the SECOND way into the analysis views (the tree being the first). The
handler on the VtkRemoteView triggers `view_context_menu`, which PICKS the
cell under the pointer server-side (`SelectSurfaceCells`, 1px region), then
publishes `ui_ctx_menu__<vid>` = {open, x, y, w, h, title, path, items}. The
items are computed for the hit object: always pivot/centre/zoom, plus the
tree's own actions (highlight-3d / add-to-stats / distribute / crossplot /
calculator) when a rep was hit, plus add-to-welllog under a Wellbore.
`view_context_action` routes each key to the SAME controllers the tree's
context menu uses, so the two entry points can never drift apart. Picking
here also fills `_last_pick`, so the camera actions act on the clicked cell.

## Rotation-centre cross
`nav_set_pivot` (menu "Set rotation centre here") sets `CenterOfRotation` on
the picked cells WITHOUT moving the camera and turns on ParaView's own
`CenterAxesVisibility` — the little cross marking the pivot. The card's
"Show rotation centre" checkbox (`nav_pivot_toggle`) flips it.

## Notes / open
- Bounds carry RAW Z while the scene draws Z exaggerated, so `_scaled_z`
  re-applies the view's `ui_scale_z__<vid>` before aiming — otherwise the camera frames empty
  space on any exaggerated view.
- The title-bar magnifier buttons call `nav_zoom_step` (dolly in perspective,
  parallel-scale in parallel projection); the wheel stays vtk.js's.
- Not done: zoom toward the cursor (needs a client-side wheel interception)
  and rubber-band zoom (the frustum tool's rubber band could be rebound).
