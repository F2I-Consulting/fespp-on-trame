# V2 M1 — engine map (per-view attributes)

Findings from auditing `fespp_on_trame/engine` for the per-view model. The big
takeaway: **the per-view engine is largely already built** (inherited from the
earlier multi-view / FesppMultiView work). M1 is mostly *wiring widgets to existing
per-view state* + one genuinely new piece (per-view z-scale).

## The per-view stack (already there)

Three tightly-coupled layers, all keyed by `view_id` / `panel_id`:

1. **Trame state buckets** (per-view):
   - `ui_hidden_rep_paths_by_view[panel_id]` — hidden reps
   - `ui_active_array_by_rep_by_view[panel_id][rep_path]` — per-view ColorBy
   - `ui_visible_marker_paths_by_view[panel_id]` — visible markers
   - `ui_active_realization_by_array_by_view`, `ui_panel_active_mr_specs_by_id`,
     `panel_has_ts_by_id`, `panel_has_mr_by_id`
2. **`ViewScene`** (one per RenderView) — `SceneRegistry._scenes[view_id]` →
   `ViewScene(view_id, pv_view)`; owns a per-view `vtkEPCCollectorClone` and
   **per-(scene, array) scoped LUT/PWF proxies** registered as `"{name}__{view_id}"`.
3. **`RepInScene`** (per rep per view) — `scene.get_rep(rep_path)`; owns
   `_extractor` (per-view EnergisticsExtractor), `_slice_plane`/`_clip_plane`
   (per-view filters), `_chain` (per-view threshold), `_per_view_ijk`,
   `_channel_extractors`/`_marker_extractors`.

Show/hide always targets a specific `scene.pv_view` via
`panel_resolver.resolve_view_and_html_view(panel_id)`.

## Status per M1 attribute

| Attribute | Status | Notes |
|-----------|--------|-------|
| **Visibility** (eye) | ✅ per-view | `visibility.toggle_rep_visibility(panel_id)` |
| **Coloring** (array+colormap) | ✅ per-view, functionally complete | `swap_to_scene_tfs(displays, view, array)` reassigns `display.LookupTable` to the view-scoped LUT; scalar bar per-view. View A = X/cmap1, View B = Y/cmap2 already works. `display.ColorArrayName` stays global (array name), `LookupTable` is view-local. |
| **Slice / clip / threshold** | ✅ per-view pipelines exist | `RepInScene._slice_plane/_clip_plane/_chain`; dispatch routes via `scene_registry.get_rep(view_id, rep_path)`. UI controls missing. |
| **Z-scale** | ✅ | `ui_scale_z__<vid>`, read by `state_defaults.z_scale_of`; `_apply_zscale(z, vid)` sets the view's displays `Scale = [1,1,zs]`. |
| **Multi-view render** | ⚠️ single-view render | `data_load.run` ends with `pvsimple.Render(view=_view)` only; non-active views update on interaction/activation (ties to the IjkGrid first-paint limit). |

## M1 work items

1. ~~**Per-view z-scale (new)**~~ — built on 2026-11-04: `ui_scale_z__<vid>`,
   see the table above; the items below are the plan as it stood before.
   - add `ui_scale_z_by_view` dict to `state_defaults.py`
   - `slicer_dispatch.apply_z_scale_per_view(view_id, zs)` — iterate that scene's
     reps only, Scale = `[1,1,zs]`, render that view
   - rep construction reads `ui_scale_z_by_view[panel_id]` with fallback to
     global `ui_scale_z`
   - wire `AttributesPanel` `set_zscale` → `v2_set_zscale(z, view_id)`
2. **Per-view coloring (wire existing)**:
   - the colorBy is OWNED by the tree's property eyes (`v2_on_eye_changed`:
     open eye = color by that array, exclusive per rep; last eye closed =
     back to SolidColor). No `set_array` in the UI — the AttributesPanel
     only DISPLAYS the current coloring (`active_array`, read-only).
   - `set_colormap` → apply preset to the view's scoped LUT (`ViewScene._luts`)
   - guard the color editor so edits touch only the view-scoped LUT (avoid bleed)
3. **Active rep per view** — `AttributesPanel` needs an "active rep" to edit:
   tree `activate` event → `ui_active_node_by_view[view_id]` → feeds the panel's
   `active_node` / `active_array` / `active_colormap` / `z_scale`.
4. **Multi-view render loop (for true 2-view)** — replace the single
   `Render(view=_view)` with a loop over `scene_registry.all_scenes()` →
   `Render(view=scene.pv_view)`.

## Key symbols

- `sources/scene_registry.py` — `add_view`, `get_scene`, `all_scenes`,
  `sync_loaded_reps`, `_eager_setup_rep_in_scene`
- `sources/view_scene.py` — `_luts`/`_pwfs`, `get_or_create_lut`, `_scoped_tf_name`,
  `replicate_tfs_from`
- `sources/rep_in_scene.py` — `_extractor`, `_slice_plane`, `_clip_plane`,
  `_chain`, `_current_z_scale` (~310)
- `engine/source_resolver.py` — `apply_color_array(view=...)`, `swap_to_scene_tfs`,
  `resolve_array_for_path(..., view=...)`
- `engine/visibility.py` — `toggle_rep_visibility(panel_id)`
- `engine/slicer_dispatch.py` — `apply_z_scale` (~247-318) → split per-view
- `engine/state_defaults.py` (~390), `engine/boot.py` (~305-309)
