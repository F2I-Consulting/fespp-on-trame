# Widget: Attributes panel (per-view)

Slice / clip / threshold / representation / solid colour / z-scale for the
**active rep of this view**. Replaces the v1 global attributes card (which used
`drawer_target_view_id` to know which view it edited). Each view panel can
**open/close** its attributes panel.

## Scope
Per-view — scoped to a `view_id`.

## Input
- `view_id`.
- The view's **active rep** (the node activated in this view's tree).

## Behaviour
Sections, all acting on the active `(rep, view)`:
- **Representation** — Surface / Wireframe / Points.
- **Solid colour** — override colour when no array is active.
- **Slice** — X/Y/Z plane + offset slider + 3D edit widget.
- **Clip** — plane + inside/outside invert + offset + 3D widget.
- **Threshold chain** — add / remove / toggle entries, per-entry range sliders.
- **IJK slicers** (IjkGrid reps only) — I/J/K slicers + volume crop.
- **Z-scale** — vertical exaggeration.

Each control edits the per-`(rep, view)` state on this view's `RepInScene`
(slice/clip/threshold filters) and triggers a single render of this view.

## Reads
- The active rep's per-view slice/clip/threshold/representation/solid-colour
  state (from `RepInScene` and its per-view UI mirror vars) **[per-view]**.
- `ui_scale_z__<vid>` (per view).

## Writes (back-end / global)
- **[per-view]** slice / clip / threshold / representation / solid-colour of the
  active `(rep, view)` → render this view.
- **z-scale**: **[per view]** since 2026-11-04 (`ui_scale_z__<vid>`). **Decision:** keep
  global, or make it **[per-view]** in v2 (likely per-view — each view exaggerates
  independently).

## Notes / open
- **The XML shown is fesapi's view of the object, not the file's bytes.** It
  comes from `serializeIntoString()` through the reader's query channel
  (`engine/repo_query`), which is what makes it identical over EPC and ETP
  and correct for a multi-EPC data set (the collector's `Files` property only
  ever held the last path). Compared with the on-disk part: the root loses
  its `obj_` prefix, every element carries an `xsi:type`, namespaces are
  declared per subtree, and anything fesapi did not deserialize is absent. A
  node the reader only holds as a reference stub shows a `<PartialObject>`
  marker rather than a blank card. On a plugin build that predates the
  channel the panel falls back to the zip bytes (local files only).
- No `drawer_target_view_id`: the panel acts on **its** view directly — this is
  the main code deletion vs v1.
- The active rep is chosen in **this** view's tree (label click), so attributes
  and tree are paired within the panel.
