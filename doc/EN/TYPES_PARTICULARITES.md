# Particularities of each type (Python side)

> Comprehensive catalogue of how every runtime \`kind\` behaves on the Python side
> — the spine every type follows, the per-family deviations, the C++↔Python
> contract, and a decision guide for *at which level* to place a change without
> breaking siblings. Companion to
> [REFACTOR_ELEMENT_TYPE_HIERARCHY.md](REFACTOR_ELEMENT_TYPE_HIERARCHY.md)
> (*what we want*); this doc is *what is*.

---

## Pitfall 0: runtime `kind` ≠ C++ enum name (`SimplifyXmlTag` strips `Wellbore` prefix / `Representation` suffix)

The `kind` attribute every Python lookup reads (`tree.find_type`, the `_representation_type_in` membership test, every `== "Frame"` / `== "Marker"` comparison) is **not** the C++ `TreeViewNodeType` enum name. For all representation/property nodes it is `SimplifyXmlTag(object->getXmlTag())` ([ResqmlDataRepository…cxx:690](../../../../fespp/work/src/Plugin/Energistics/Mapping/ResqmlDataRepositoryToVtkPartitionedDataSetCollection.cxx#L690)), which strips the `Representation` suffix **first**, then the `Wellbore` prefix ([SimplifyXmlTag](../../../../fespp/work/src/Plugin/Energistics/Mapping/ResqmlDataRepositoryToVtkPartitionedDataSetCollection.cxx#L265-L280)). Only `Collection` / `Partial` / `Wellbore` are enum-driven via `treeViewNodeTypeName` ([:674](../../../../fespp/work/src/Plugin/Energistics/Mapping/ResqmlDataRepositoryToVtkPartitionedDataSetCollection.cxx#L674)); the synthetic property wrappers (`TimeSeries`, `MultiRealization`, `MultiRealizationTimeSeries`) and `Perforation` are also enum-driven.

| RESQML / FESAPI XML tag (`getXmlTag()`) | C++ enum name (`enum.h`, dead in Python) | **Runtime `kind` (what Python sees)** | Notes |
|---|---|---|---|
| `WellboreTrajectoryRepresentation` | `WellboreTrajectory` | **`Trajectory`** | prefix+suffix stripped |
| `WellboreFrameRepresentation` | `WellboreFrame` | **`Frame`** | the log-channel container; `_is_wellbore_frame()` tests `== "Frame"` |
| `WellboreMarkerFrameRepresentation` | `WellboreMarkerFrame` | **`MarkerFrame`** | `Wellbore`+`Representation` stripped → `MarkerFrame` |
| `WellboreMarker` (marker leaf) | `WellboreMarker` | **`Marker`** | prefix `Wellbore` stripped; `data_load._update_marker_tracking` tests `== "Marker"` |
| a channel = `ContinuousProperty` / `DiscreteProperty` / `CategoricalProperty` on a frame | `WellboreChannel` | **`ContinuousProperty` / `DiscreteProperty` / `CategoricalProperty`** | a channel is just an `AbstractValuesProperty`; its `kind` is the property kind. "Channel-ness" is derived structurally (property whose rep ancestor is a `Frame`), never from a `kind` string |
| `IjkGridRepresentation` | — | **`IjkGrid`** | suffix stripped (no `Wellbore` prefix) |
| `UnstructuredGridRepresentation` | — | **`UnstructuredGrid`** | |
| `SubRepresentation` | `SubRepresentation` | **`Sub`** | suffix stripped |
| `Grid2dRepresentation` | — | **`Grid2d`** | |
| `PolylineSetRepresentation` / `TriangulatedSetRepresentation` / `PointSetRepresentation` | — | **`PolylineSet` / `TriangulatedSet` / `PointSet`** | |
| `SeismicWellboreFrameRepresentation` | — | **`SeismicWellboreFrame`** | ⚠ suffix `Representation` stripped, but `SeismicWellbore` does **not** start with `Wellbore` (starts with `Seismic`), so the prefix strip is a no-op → kind stays `SeismicWellboreFrame`. See debt. |

### DEAD strings still in Python

These enum-name literals can **never** match a runtime `kind`; every test against them is unreachable code:

- **`'WellboreMarker'`** — runtime kind is `Marker`. Dead in [tree.py:34](../../fespp_on_trame/app/core/tree.py#L34) (`_representation_type_in`), [tree.py:64](../../fespp_on_trame/app/core/tree.py#L64), [:74](../../fespp_on_trame/app/core/tree.py#L74), [:205](../../fespp_on_trame/app/core/tree.py#L205), [:213](../../fespp_on_trame/app/core/tree.py#L213); [tree_selection.py:7](../../fespp_on_trame/app/ui/drawer/config/tree_selection.py#L7); the live marker rep is `MarkerFrame` and the live leaf is `Marker`.
- **`'WellboreChannel'`** — channels surface as `ContinuousProperty`/`DiscreteProperty`/`CategoricalProperty`. Dead in [tree.py:74](../../fespp_on_trame/app/core/tree.py#L74) & [:213](../../fespp_on_trame/app/core/tree.py#L213) (`supporttype` partial-routing only — harmless, never hit for a real node); the only *live* use is the structural dependency rule in [tree_views.py:33](../../fespp_on_trame/app/ui/drawer/tree_views.py#L33) which keys off the partial-stub `supporttype` attribute, not `kind`. Note `tree_selection.py` lists `"WellboreFrame"` (also dead — runtime kind is `Frame`).

> When adding a new wellbore type, register the **stripped** runtime kind, not the enum name.

## Master table (one row per runtime `kind`)

`Tree role` = grouping (folder) vs representation (eye-bearing) vs property-leaf. `Source/pipeline` is the **per-(rep,view)** model in [rep_in_scene.py](../../fespp_on_trame/app/core/sources/rep_in_scene.py). `Bucket` = which `state` visibility list governs it. COE = does the Color Editor light up.

| Runtime kind | Family | Tree role | Eye | Selection | Source / pipeline | Visibility bucket | Color | Bucket of "active array" | COE |
|---|---|---|---|---|---|---|---|---|---|
| `IjkGrid` | reservoir | rep | ✔ rep eye | own id or checked descendant | per-view `_per_view_ijk` (IjkGrid: rep_data + slicers + volume + chain), legacy mirror | `ui_hidden_rep_paths*` | property ColorBy or SolidColor | `ui_active_array_by_rep*` | ✔ (continuous LUT / categorical) |
| `UnstructuredGrid` | reservoir | rep | ✔ | id/descendant | per-view `_extractor` + `_chain` | `ui_hidden_rep_paths*` | ColorBy / Solid | `ui_active_array_by_rep*` | ✔ |
| `Sub` | reservoir | rep | ✔ | id/descendant | per-view `_extractor` | `ui_hidden_rep_paths*` | ColorBy / Solid | `ui_active_array_by_rep*` | ✔ |
| `Grid2d`, `PointSet`, `Polyline`, `PolylineSet`, `TriangulatedSet` | surface | rep | ✔ | id/descendant | per-view `_extractor` + `_chain` | `ui_hidden_rep_paths*` | ColorBy / Solid | `ui_active_array_by_rep*` | ✔ |
| `Trajectory` | well | rep | ✔ | id/descendant | per-view `_extractor` | `ui_hidden_rep_paths*` | SolidColor (geometry; usually no props) | — | ✖ (cleared by `_publish_active_color_state`) |
| `Completion`, `Perfo` | well | rep | ✔ | id/descendant | per-view `_extractor` | `ui_hidden_rep_paths*` | SolidColor | — | ✖ (COE path **unverified** — see debt) |
| `Frame` (WellboreFrame logs) | well | **grouping** (`is_grouping`, `_GROUPING_KINDS`) — folder in tree, rep in source | ✖ folder (tri-state from child logs) | checked child log | **primary `_extractor` stays HIDDEN** (`_channelless_frame`). Each **channel** owns its **own** persistent per-(channel,view) `EnergisticsExtractor` in `_channel_extractors`, **EXCLUSIVE** one-shown-at-a-time (`set_channel_visible`) | child log via `ui_active_array_by_rep*` (the eye = the active-array, not a visibility chip) | ColorBy on the visible channel's own extractor | child log path in `ui_active_array_by_rep*` | ✔ on the channel (continuous/discrete/categorical) |
| `MarkerFrame` | well | **grouping** | ✖ folder | checked child marker | primary `_extractor` HIDDEN (`_channelless_frame`). Each **visible** marker owns its own per-(marker,view) `EnergisticsExtractor` in `_marker_extractors`, **MULTI** shown-at-once (`set_marker_visible`) | `ui_visible_marker_paths_by_view` (+ `ui_loaded_marker_paths`) | per-marker `solid_color_by_marker` → falls back to `solid_color_by_rep` | n/a (markers are geometry leaves, not arrays) | ✖ |
| `Marker` (leaf) | well | property-like leaf | ✔ per-marker visibility eye (MULTI) | own id | rendered by parent `MarkerFrame`'s `_marker_extractors[marker_path]` | `ui_visible_marker_paths_by_view` | `solid_color_by_marker` | — | ✖ |
| `SeismicWellboreFrame` | well | rep (auto-show path) | ✔ | id/descendant | per-view `_extractor` (normal auto-show — NOT in `_channelless_frame`) | `ui_hidden_rep_paths*` | SolidColor | — | ✖ (ambiguous — see debt) |
| `Wellbore`, `Collection`, `Feature`, `Interpretation`, `Partial` | (per tab) | **grouping** only | ✖ | bulk-select descendants | none (pure folder) | — | — | — | — |
| `ContinuousProperty` / `DiscreteProperty` / `CategoricalProperty` | (rep's tab) | property leaf | ✔ data-array eye (`ui_active_array_by_rep`) | own id (NOT "under checked rep") | colors the rep's source; **if the rep is a `Frame`, this leaf IS a channel** → its own `_channel_extractors` entry | `ui_active_array_by_rep*` | the rep's ColorBy | self | ✔ |
| `TimeSeries`, `MultiRealization`, `MultiRealizationTimeSeries` | (rep's tab) | synthetic property leaf | ✔ data-array eye | own id | colors rep via suffixed `<title>_real_<idx>` (MR) | `ui_active_array_by_rep*` | ColorBy | self | ✔ (kind via `propKind` attr) |

**Key shift from the old model:** a frame no longer has "one shared frame extractor whose `ExtractPath` is retargeted". Each channel's source is created once and *persists* (hidden when another channel is shown), so its scoped LUT / COE / stats read it directly with **no retarget** — `visible_channel_extractor()` returns the one with `Visibility=1`, `channel_extractor_for(create=True)` materialises a hidden one for off-screen reads.

## C++ ↔ Python contract (the invariants)

### 1. Array naming — `MakeValidNodeName` ⇔ `make_valid_vtk_name` (byte-for-byte mirror)

The C++ attaches VTK array names via `ResqmlPropertyToVtkDataArray::MakeValidNodeName`; Python recomputes the same name from the RESQML title via [`make_valid_vtk_name`](../../fespp_on_trame/app/utils/naming.py#L33-L50). The rule (both sides):

> strip every char outside `[-.0-9A-Z_a-z]`; then prepend `_` iff the result is empty **or** its first surviving char is a digit / `-` / `.`.

Both must stay identical or the COE / LUT key / ColorBy silently miss (e.g. `"123abc"` → `"_123abc"`). `sanitize_proxy_name` ([:53](../../fespp_on_trame/app/utils/naming.py#L53)) is the **opposite** sanitizer (replace→`_`) for PV proxy registration names only — never use it for array lookup.

**Channels are now sanitized too.** [`ResqmlWellboreChannelToVtkPolyData.cxx:100-101`](../../../../fespp/work/src/Plugin/Energistics/Mapping/ResqmlWellboreChannelToVtkPolyData.cxx#L100-L101) routes the tube's scalar-array name through `MakeValidNodeName` (and `SetActiveScalars` with the same sanitized name, [:153](../../../../fespp/work/src/Plugin/Energistics/Mapping/ResqmlWellboreChannelToVtkPolyData.cxx#L153)). Before this fix a channel's POINT array was named with the **raw** title, so the render path keyed its scoped LUT on the raw name while the COE sanitized → two different LUTs, blank COE graph.

**Why this matters for the scoped LUT key / COE:** the per-view scoped LUT is keyed `f"{array_name}__{view_id}"` on whichever name *actually exists on the source*. `real_base_name` ([source_resolver.py:189-217](../../fespp_on_trame/app/core/engine/source_resolver.py#L189-L217)) still probes raw-vs-sanitized defensively (un-rebuilt plugin), but with the rebuilt plugin channels are sanitized like grids and the probe collapses to the sanitized branch. `stats_dispatch._original_source_and_name` already prefers the sanitized name first for channels ([stats_dispatch.py:514-519](../../fespp_on_trame/app/core/engine/stats_dispatch.py#L514)).

### 2. Partitions & dataset indices; `ExtractPath` addressing

- A **frame node has no partition / dataset index of its own** — only its child channels/markers do. The frame is `isGroupingType` / a folder. Rendering the frame's primary `_extractor` (whose `ExtractPath` = the frame node) makes the C++ extractor surface the frame's *first child partition*, so the primary is deliberately kept hidden for any frame (`_channelless_frame`, [rep_in_scene.py:746-756](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L746)).
- `EnergisticsExtractor.ExtractPath` addresses a node by its **assembly path** (`panel_visibility="never"`, set via `vtkSMPropertyHelper(...,"ExtractPath").Set(path)`). A per-channel/per-marker extractor sets `ExtractPath` = the **leaf** node path so only that one partition's tube/geometry + its point array surfaces ([_create_channel_extractor](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L547-L599), [_create_marker_extractor](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L636-L699)).

### 3. NaN → 0 in channels (degenerate range) → COE `nondegenerate_range` guard

The C++ replaces NaN (continuous) / overflow-int (discrete/categorical) channel values with **0** ([ResqmlWellboreChannelToVtkPolyData.cxx:112-138](../../../../fespp/work/src/Plugin/Energistics/Mapping/ResqmlWellboreChannelToVtkPolyData.cxx#L112-L138)) and warns. An all-NaN log therefore yields a constant-0 array → `lo == hi`. The COE's CanvasGradient normalises stops as `(v-lo)/(hi-lo)` → division by zero → client throws "addColorStop: non-finite double", blanking the editor. [`nondegenerate_range`](../../fespp_on_trame/app/core/engine/source_resolver.py#L147-L170) widens any `lo==hi` (or non-finite) range to a tiny finite band so the gradient renders near-flat instead of crashing. Same guard also covers a genuinely constant grid property.

## Cross-cutting state variables

| State var | Shape | Filled by | Read by |
|---|---|---|---|
| `ui_subtree_reservoir` / `_surface` / `_well` | list of nested treeview dicts | `Tree.set_tree` ([tree.py:165](../../fespp_on_trame/app/core/tree.py#L165)) | `tree_views.py` Vue render |
| `ui_select_node_reservoir` / `_surface` / `_well` | list[node_id] (checkbox state) | tree checkbox + `_expand_selection_with_deps` | `Activator._is_node_active_able`, selectors |
| `ui_active_node_reservoir` / `_surface` / `_well` | list[node_id] (≤1) | tree click | `Activator._handle_*_change` |
| `fespp_data_selectors` | list[path] | selectors | `data_load.run` (the load driver) |
| `ui_loaded_rep_paths` | list[rep_path] | `data_load._update_visibility_tracking` | scene sync, chips |
| `ui_hidden_rep_paths` | list[rep_path] (active panel) | `_update_visibility_tracking` | eye chips |
| `ui_hidden_rep_paths_by_view` | `{panel_id: [rep_path]}` | `_update_visibility_tracking` | `RepInScene._hidden_in_scene` / `_refresh_parent_rep_visibility`, eager setup |
| `ui_loaded_array_paths` | list[array_path] | `_update_data_array_tracking` | active-map maintenance |
| `ui_active_array_by_rep` | `{rep_path: array_path}` (global = active panel) | `_update_active_array_maps`, `active_array` toggle | Activator ColorBy gate, `_ensure_extractor` |
| `ui_active_array_by_rep_by_view` | `{panel_id: {rep_path: array_path}}` | `_update_active_array_maps`, `active_array` toggle | per-view ColorBy |
| `ui_active_realization_by_array_by_view` | `{panel_id: {array_path: idx}}` | `_update_active_array_maps`, realization dispatch | `resolve_array_for_path` suffix |
| `ui_loaded_marker_paths` | list[marker_path] (kind `Marker`) | `_update_marker_tracking` | marker eye render |
| `ui_visible_marker_paths_by_view` | `{panel_id: [marker_path]}` | `visibility.toggle_marker_visibility` | `set_marker_visible` |
| `solid_color_by_rep` | `{rep_path: hex}` | `data_load` color loop | tint at extractor creation |
| `solid_color_by_marker` | `{marker_path: hex}` | solid-color panel | `_create_marker_extractor` tint |
| **`active_color_array_path`** *(new)* | str (active node's assembly path) | `Activator` ([:317](../../fespp_on_trame/app/core/activator.py#L317), [:774](../../fespp_on_trame/app/core/activator.py#L774)), `active_array` channel toggle ([:406](../../fespp_on_trame/app/core/engine/active_array.py#L406)) | `color_editor.py:155`, `solid_color_panel.py:400` — lets the COE read the **active channel's own** extractor (`channel_source_for`) even when a sibling channel is the one displayed |
| `active_color_array_name` | str (UI title) | Activator / channel toggle | COE mode switch, scoped-LUT key |
| `active_property_kind` | str | Activator | COE continuous-vs-categorical editor |
| `active_representation_path` | str (rep_path) | Activator / channel toggle | COE / stats target |
| `drawer_target_view_id`, `fespp_active_panel_id` | str (panel id) | UI panel focus / pin | `target_view_and_panel`, scoped-LUT resolution |

**Removed / gone:** there is no `_extractor_channel_path` state (the old single-extractor retarget cursor). The COE no longer "retargets" — it reads `channel_source_for(active_color_array_path)`.

## Where the per-type logic lives (file map)

| Concern | File · symbol |
|---|---|
| runtime-kind classification, rep-ancestor walk, grouping set | [tree.py](../../fespp_on_trame/app/core/tree.py): `_representation_type_in` (L34), `is_grouping` (L103), `find_representation_node` (L395) |
| C++ runtime `kind` derivation | `…/Mapping/ResqmlDataRepositoryToVtkPartitionedDataSetCollection.cxx`: `addDefaultToDataAssemblyNode` (L659), `SimplifyXmlTag` (L265) |
| channel tube + sanitized array + NaN→0 | `…/Mapping/ResqmlWellboreChannelToVtkPolyData.cxx` |
| array-name mirror | [naming.py](../../fespp_on_trame/app/utils/naming.py): `make_valid_vtk_name` (L33), `sanitize_proxy_name` (L53) |
| **per-(channel,view) source model** | [rep_in_scene.py](../../fespp_on_trame/app/core/sources/rep_in_scene.py): `_channel_extractors` dict (L61), `set_channel_visible` **EXCLUSIVE** (L468), `channel_extractor_for(create=)` (L511), `visible_channel_extractor` (L526), `_create_channel_extractor` (L547) |
| per-(marker,view) source model | same file: `_marker_extractors` (L70), `set_marker_visible` **MULTI** (L601), `_create_marker_extractor` (L636), `visible_marker_displays` (L721), `set_marker_color` (L701) |
| primary-stays-hidden rule | same file: `_channelless_frame` (L746); frame/marker tests `_is_wellbore_frame`==`'Frame'` (L126), `_is_marker_frame`==`'MarkerFrame'` (L148) |
| per-view IjkGrid + chain | same file: `_ensure_per_view_ijk` (L188), `_chain` / `_add_threshold_local` (L1245) |
| channel source for COE/stats (no retarget) | [source_resolver.py](../../fespp_on_trame/app/core/engine/source_resolver.py): `channel_source_for` (L118), `_scene_rep_for_view` (L99), `real_base_name` (L189), `nondegenerate_range` (L147) |
| rendered/colorable source dispatch (frame → `visible_channel_extractor`) | source_resolver: `sources_for_rep_path` (L220, L275), `color_sources_for_rep_path` (L317, L376), `resolve_array_for_path` (L433, L468-481) |
| channel eye toggle → `set_channel_visible` + COE publish | [active_array.py](../../fespp_on_trame/app/core/engine/active_array.py): channel branch (L380, L400-420) |
| marker eye toggle | [visibility.py](../../fespp_on_trame/app/core/engine/visibility.py): `toggle_marker_visibility` (L77) |
| load-time tracking | [data_load.py](../../fespp_on_trame/app/core/engine/data_load.py): `_update_marker_tracking` ==`'Marker'` (L375), `_update_active_array_maps` (L418) |
| active node → COE state | [activator.py](../../fespp_on_trame/app/core/activator.py): `_publish_active_color_state` (L742), reservoir inline (L307-319) |

**Removed symbols** (do not look for them): `set_extract_channel`, `_extractor_channel_path`, `read_only_channel_retarget`. The switch is now a plain hide/show.

## Decision guide: at which level do I place a modification?

Three altitudes. Place a change at the **lowest** level that fully contains its blast radius.

**General spine** — `tree.py`, `naming.py`, the `data_load.run` order, `source_resolver`'s dispatch skeleton, `RepInScene.delete`/`source()`. A change here touches **every** family. Only edit here for genuinely universal concerns (array-name mirror, assembly-path addressing, load ordering). *Trap: editing the spine to fix one family.*

**Family** — the branch in a dispatcher for IjkGrid vs UG/surface vs **frame** vs marker. E.g. the `if rep_in_scene._is_wellbore_frame(): … visible_channel_extractor()` arms in `sources_for_rep_path` / `color_sources_for_rep_path`. Add a new well-type behaviour by adding a branch here, not by widening a shared function's contract.

**Unit** — one runtime kind / one method. `_create_channel_extractor`, `set_channel_visible`, a single COE publish.

### Worked example — the log change that broke reservoir + surface

The **wrong** level was a *shared* function. The old design had **one frame extractor whose `ExtractPath` was retargeted** to the selected channel, and the COE/stats "read-only retarget" temporarily re-pointed that *same* shared extractor to read a hidden channel's data, then restored it. Because the retarget mutated a source that other code paths assumed stable, and because the generic visibility refreshers (`_refresh_parent_rep_visibility`, `_refresh_chain_visibility` — used by **every** rep including reservoir + surface) would `Show()` the frame's primary, the frame logic leaked into the shared spine: a fan-out refresh re-surfaced the frame's first channel in every view, and the retarget-restore dance raced with reservoir/surface ColorBy on the same shared LUT.

The **right** level was the *family/unit*: give each channel its **own** persistent per-(channel,view) extractor (mirror of markers), make the switch a plain exclusive hide/show, and gate the primary with `_channelless_frame()`. Now:
- nothing retargets, so the COE/stats just read `channel_source_for(path)` directly (a hidden-but-materialised source) — reservoir/surface paths are untouched;
- the only spine change is the `_channelless_frame()` guard inside the shared refreshers — a *narrow* family hook, not a behavioural change to the generic Show/Hide.

**Rule of thumb:** if your fix for wellbore logs forces you to widen a function that IjkGrid/surface also call, you are at the wrong altitude — add a `_is_*_frame()`-gated branch (family) or a dedicated per-child method (unit) instead.

## Identified debt / to-clean

- **Dead enum-name strings.** `'WellboreMarker'` (runtime kind is `Marker`) and `'WellboreChannel'` (runtime kinds are the property kinds) are unreachable in [tree.py:34](../../fespp_on_trame/app/core/tree.py#L34), [:64](../../fespp_on_trame/app/core/tree.py#L64), [:74](../../fespp_on_trame/app/core/tree.py#L74), [:205](../../fespp_on_trame/app/core/tree.py#L205), [:213](../../fespp_on_trame/app/core/tree.py#L213). `tree_selection.py:7` lists `"WellboreFrame"` / `"WellboreMarker"` (both dead; live kinds are `Frame` / `Marker`). The `supporttype`-based partial routing entries for `'WellboreChannel'`/`'WellboreMarker'` *might* be live (partial stubs carry the unstripped supporttype) — verify before deleting those two specifically; the rest are safe to drop.
- **Stale comments mentioning `set_extract_channel`.** [rep_in_scene.py:132](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L132) (`_is_wellbore_frame` docstring still says "selected via the channel's data-array eye (`set_extract_channel`)") and [active_array.py:350](../../fespp_on_trame/app/core/engine/active_array.py#L350) ("The per-view extractor Show below (set_extract_channel)…") reference the deleted method. Update to `set_channel_visible`.
- **Distribution `_restore_channel` no-ops.** Since channels no longer retarget, `_original_source_and_name` returns a `noop` restore for channels ([stats_dispatch.py:509](../../fespp_on_trame/app/core/engine/stats_dispatch.py#L509), [:523](../../fespp_on_trame/app/core/engine/stats_dispatch.py#L523)) and `distribution_dispatch.py` still threads `_restore_channel` ([:406](../../fespp_on_trame/app/core/engine/distribution_dispatch.py#L406), [:456](../../fespp_on_trame/app/core/engine/distribution_dispatch.py#L456), [:538](../../fespp_on_trame/app/core/engine/distribution_dispatch.py#L538)) — now always a do-nothing lambda. The "restore the channel extractor's ExtractPath" comment at [stats_dispatch.py:594](../../fespp_on_trame/app/core/engine/stats_dispatch.py#L594) is obsolete. The plumbing can be removed once confirmed no caller relies on the tuple arity.
- **`SeismicWellboreFrame` ambiguity.** `SimplifyXmlTag` strips `Representation` but **not** `Wellbore` (the tag starts with `Seismic`), so the kind is `SeismicWellboreFrame` — it stays on the normal auto-show path, **not** `_channelless_frame`. It is listed in `_representation_type_in` and the tab dispatch, but it is unclear whether a seismic wellbore frame should behave like a `Frame` (channel container, primary hidden) or a plain geometry rep. No channel/marker handling exists for it. Decide and document; currently it would auto-surface its first partition like any rep.
- **`Completion` / `Perfo` COE unverified.** Both are in `_representation_type_in` and treated as SolidColor geometry reps, but there is no explicit test that their COE state is cleared (they have no property children in the cases seen). `_publish_active_color_state` clears COE for any non-property active node, so it *should* fall back to Solid — but this path is **untested** for these two kinds; confirm a Completion/Perfo activation doesn't leave a stale `active_color_array_name`.
- **`_is_wellbore_frame` docstring drift.** [rep_in_scene.py:126-137](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L126) still describes "only one channel renders at a time, selected via … `set_extract_channel`" — accurate on exclusivity, wrong on mechanism. Reword to the persistent-per-channel-extractor model.

---

I now have a complete and accurate picture of the current code. Let me write the two assigned sections.

## The full lifecycle spine (every type follows this; per-type differences are deviations from it)

This is the canonical end-to-end path a RESQML object travels, from EPC selection to teardown. Every kind (IjkGrid, surface, polyline, wellbore Frame/MarkerFrame, …) runs the *same* numbered stages; type-specific behaviour is always a **deviation at one stage**, never a parallel pipeline. Place a change at the lowest stage that owns the concern.

| # | Stage | Function(s) | Key state var(s) | Notes |
|---|-------|-------------|------------------|-------|
| 1 | **Load** | [`data_load.run`](../../fespp_on_trame/app/core/engine/data_load.py#L40) → `active_source.SetPropertyWithName('Selectors', …)` + one `UpdatePipeline`; `source_registry.sync(...)` | `fespp_data_selectors` (input); `_selector_rep_cache`, `solid_color_by_rep`, `solid_color_next_idx` | Pushes selectors to the EPCCollector once, hides the parent multiblock rep, reserves a chip colour per new rep *before* registry sync so sources tint immediately. |
| 1b | **Load — visibility bucket tracking** | [`_update_visibility_tracking`](../../fespp_on_trame/app/core/engine/data_load.py#L283) | `ui_loaded_rep_paths`, `ui_hidden_rep_paths`, `ui_hidden_rep_paths_by_view` | New reps stay visible in the **active panel**, are appended to every **non-active** panel's hidden bucket. This is the gate every later "should I Show here?" check reads. |
| 1c | **Load — data-array / marker / active-array tracking** | [`_update_data_array_tracking`](../../fespp_on_trame/app/core/engine/data_load.py#L342), [`_update_marker_tracking`](../../fespp_on_trame/app/core/engine/data_load.py#L375), [`_update_active_array_maps`](../../fespp_on_trame/app/core/engine/data_load.py#L418) | `ui_loaded_array_paths`, `ui_loaded_marker_paths`, `ui_active_array_by_rep` (+`_by_view`), `ui_active_realization_by_array_by_view` | "Last array added to a rep auto-becomes its active eye" — but **only in the active panel**. MR auto-activation also seeds the realization bucket *before* the active-array write (handler ordering is load-bearing). |
| 2 | **Tree build** | [`Tree.set_tree`](../../fespp_on_trame/app/core/tree.py#L165) / [`add_subtreeview_data`](../../fespp_on_trame/app/core/tree.py#L36); [`find_representation_node`](../../fespp_on_trame/app/core/tree.py#L395), [`find_type`](../../fespp_on_trame/app/core/tree.py#L372), [`is_grouping`](../../fespp_on_trame/app/core/tree.py#L103) | `ui_subtree_reservoir/well/surface` | `kind` drives everything downstream. `_representation_type_in` (incl. `Frame`, `MarkerFrame`) decides which ancestor a leaf's eye resolves UP to; `is_grouping` makes Frame/MarkerFrame *folders for the tree but reps for the source*. Each node also publishes `rep_path` so the Vue side resolves "is this array active for my rep" with no Python round-trip. |
| 3 | **Selection** | `Selector.select_node_*` (writes `fespp_data_selectors`, triggering stage 1) | `ui_select_node_reservoir/well/surface`, `fespp_data_selectors` | Checkbox state. Grouping check bulk-selects descendants via `find_all_selectable_descendant_ids` (partials excluded). |
| 4 | **Activation** | [`Activator._handle_reservoir_change`](../../fespp_on_trame/app/core/activator.py#L240) / `_handle_well_change` / `_handle_surface_change`; gated by [`_is_node_active_able`](../../fespp_on_trame/app/core/activator.py#L194); `refresh_active()` re-runs post-load | `ui_active_node_reservoir/well/surface`, `active_representation_path`, `active_representation_has_properties`, `ui_active_node_reservoir_type[_rep]`, `active_property_kind`, `active_color_array_name/path` | Active **node** ≠ active **eye**. A property leaf activates only when its own id is checked; reps/groupings activate via a checked descendant. Reservoir tab does ColorBy inline ([`_apply_color_for_active_property`](../../fespp_on_trame/app/core/activator.py#L451)); well/surface only *publish* COE state ([`_publish_active_color_state`](../../fespp_on_trame/app/core/activator.py#L742)) and let the eye own ColorBy. |
| 5 | **Per-view source creation** | [`SceneRegistry.sync_loaded_reps`](../../fespp_on_trame/app/core/sources/scene_registry.py#L133) → [`_eager_setup_rep_in_scene`](../../fespp_on_trame/app/core/sources/scene_registry.py#L169) → [`RepInScene.source()`](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L169) → [`_ensure_extractor`](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L346) / [`_ensure_per_view_ijk`](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L188) | (no state var — the proxy graph itself) | One `RepInScene` per (rep, view), lazily creating its per-view `EnergisticsExtractor` (non-IJK) or per-view `IjkGrid` (IJK). Eager setup also replicates the active panel's ColorBy onto split views and honours the hidden-bucket via [`hide_in_scene_view`](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L779). |
| 6 | **Rendering / visibility** | [`visibility.toggle_rep_visibility`](../../fespp_on_trame/app/core/engine/visibility.py#L140); [`sources_for_rep_path`](../../fespp_on_trame/app/core/engine/source_resolver.py#L220); per-view [`_refresh_parent_rep_visibility`](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L1020) | `ui_hidden_rep_paths_by_view` (gate), `ui_hidden_rep_paths` (mirror) | 3-state eye chip (hidden / SolidColor / array). The **hidden-in-scene gate** ([`_hidden_in_scene`](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L758)) is checked at every Show site so a first selection appears only in the active view while still building everywhere. |
| 7 | **Color** | [`source_resolver.apply_color_array`](../../fespp_on_trame/app/core/engine/source_resolver.py#L757) → [`displays_for_rep_path`](../../fespp_on_trame/app/core/engine/source_resolver.py#L420) → [`color_sources_for_rep_path`](../../fespp_on_trame/app/core/engine/source_resolver.py#L317) → `ColorBy`; [`resolve_array_for_path`](../../fespp_on_trame/app/core/engine/source_resolver.py#L433); per-view LUT via [`swap_to_scene_tfs`](../../fespp_on_trame/app/core/engine/source_resolver.py#L545) | `ui_active_array_by_rep[_by_view]`, `ui_active_realization_by_array_by_view` | Driven by [`active_array.on_active_array_change`](../../fespp_on_trame/app/core/engine/active_array.py#L44) and [`toggle_dataarray_color`](../../fespp_on_trame/app/core/engine/active_array.py#L231). LUT is per-(scene, array) (`name__view_id`) so a COE edit doesn't bleed across views. |
| 8 | **COE (color editor)** | `controller.update_color_editor(...)`; [`resolve_target_scoped_lut`](../../fespp_on_trame/app/core/engine/source_resolver.py#L584), [`real_base_name`](../../fespp_on_trame/app/core/engine/source_resolver.py#L189) | `active_color_array_name`, `active_property_kind`, `active_color_array_path`, `coe_panels` | COE keys its LUT on whichever VTK name **actually exists** (sanitized for grids/surfaces, raw title for channels — see the channel sanitize note below). The eye click ([`toggle_dataarray_color`](../../fespp_on_trame/app/core/engine/active_array.py#L400)) republishes these so the COE follows the channel actually viewed. |
| 9 | **Stats / distribution** | `channel_source_for` / `visible_channel_extractor` / `slice_output` / `clip_output` feed the rendered-source list | (panel state) | Reads the same per-view source set the render path uses (per-view extractor, visible channel extractor, deepest visible threshold leaf). |
| 10 | **Split / replicate** | [`SceneRegistry.replicate_view`](../../fespp_on_trame/app/core/sources/scene_registry.py#L390); per-concern [`snapshot_*` / `apply_*`](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L1518); [`apply_visible_markers`](../../fespp_on_trame/app/core/sources/scene_registry.py#L265); [`ViewScene.replicate_tfs_from`](../../fespp_on_trame/app/core/sources/view_scene.py#L312) | `ui_active_array_by_rep_by_view`, `ui_visible_marker_paths_by_view`, `fespp_active_panel_id` | Bootstrap (per-view extractor + ColorBy) comes from `_eager_setup_rep_in_scene`; `replicate_view` adds per-concern copy (threshold/slice/clip/ijk_slicers) in dependency order (ijk_slicers first). |
| 11 | **Teardown** | [`RepInScene.delete`](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L849); [`ViewScene.remove_rep`/`destroy`](../../fespp_on_trame/app/core/sources/view_scene.py#L141); **synchronous deselect teardown** in [`data_load.run`](../../fespp_on_trame/app/core/engine/data_load.py#L230) | `ui_loaded_rep_paths` (drives deferred `sync_loaded_reps`) | Order matters: chain → slice/clip → per-view IjkGrid → primary `_extractor` → per-child extractors. Deselected reps are torn down **synchronously inside `run()` before any render** — rendering a stale source against a clone whose partition is gone segfaults natively. |

**Per-type deviations from the spine (each is a branch at one stage, by `kind`):**

- **IjkGrid** — stage 5/6/7 delegate to a per-view [`IjkGrid`](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L188) (slicers + volume + threshold chain) instead of a single `_extractor`; `source()` returns the rep_data extractor; visibility defers to `ijk.show(view=…)` (it owns slice-vs-range mode). Legacy shared IjkGrid is hidden per-view to avoid Z-fighting.
- **Wellbore Frame (logs)** / **MarkerFrame** — stage 6 keeps the primary `_extractor` permanently hidden ([`_channelless_frame`](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L746)); children render via per-child extractors (see next section). Stage 1c routes them through `ui_loaded_array_paths` (channels) vs `ui_loaded_marker_paths` (markers).
- **Non-IJK surfaces / polylines** — the "default" path with no deviation: one `_extractor`, optional per-view threshold chain, slice/clip.

---

## The per-view scene architecture (clone, RepInScene, child extractors, chain)

Each render panel owns one [`ViewScene`](../../fespp_on_trame/app/core/sources/view_scene.py#L24); the [`SceneRegistry`](../../fespp_on_trame/app/core/sources/scene_registry.py#L40) maps `view_id → ViewScene` and is the façade the engine calls. A scene owns a **clone**, a dict of `RepInScene`, and per-(scene, array) LUT/PWF proxies.

### Clone — the per-view structural anchor

- [`ViewScene._create_clone`](../../fespp_on_trame/app/core/sources/view_scene.py#L69) instantiates a `vtkEPCCollectorClone` proxy (reg name `EPCCollector_View{view_id}`) chained on the global `EPCCollector` source. It is a ShallowCopy passthrough — **zero data duplication**, propagation 100% native PV (any collector update invalidates the clone → invalidates downstream filters).
- The clone is **never shown** — it's a structural SM-graph node, forced `Visibility=0` in every view so PV's lazy default display doesn't paint a phantom Outline.
- **Phase 2 fallback:** when the plugin DLL lacks `EPCCollectorClone`, `clone` falls back to `collector.get_source()` (the shared source). Every per-view filter-creation method ([`_ensure_extractor`](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L366), `_ensure_per_view_ijk`, `_create_channel_extractor`, `_create_marker_extractor`) explicitly checks `clone is collector.get_source()` and **bails to legacy** in that case — chaining per-view filters on the shared collector would collide on `id()` across views.

### RepInScene — the per-(rep, view) owner

[`RepInScene`](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L33) is one rep as seen from one view. It owns every proxy that must diverge across views. Type detection is cached (`_is_ijk_cache`, `_is_frame_cache`, `_is_marker_frame_cache`) because the dispatch hot path branches on it every call.

| Field | What it holds | When created |
|-------|---------------|--------------|
| `_extractor` | Primary per-view `EnergisticsExtractor` (ExtractPath = rep_path) | Lazy, non-IJK only, on first `source()`/slice/clip/ColorBy |
| `_per_view_ijk` | Per-view `IjkGrid` pipeline (rep_data + slicers + volume + chain) | Lazy, IJK only |
| `_channel_extractors: dict` | One extractor per wellbore **channel** (log), keyed by channel path | Lazy, on first show / COE-stats read |
| `_marker_extractors: dict` | One extractor per visible **marker**, keyed by marker path | Lazy, on first show |
| `_chain: list[ChainEntry]` | Per-view threshold chain (non-IJK; IJK uses `_per_view_ijk._chain`) | On `add_threshold` |
| `_slice_plane` / `_clip_plane` | Per-(rep, view) Slice / Clip filters chained on the per-view source | On first `slice_set` / `clip_set` |

### Primary `_extractor` vs per-child extractor dicts

The primary `_extractor` represents the *whole rep*. But a **Frame** (wellbore log container) and a **MarkerFrame** are containers whose first child partition would auto-surface if the primary were shown (ExtractPath = frame path → C++ resolves to the frame's first child). So both kinds keep the primary **permanently hidden** via [`_channelless_frame`](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L746) (returns `_is_marker_frame() or _is_wellbore_frame()`), and render their children through dedicated per-child extractors, each with its **own** `ExtractPath` pointed at the child leaf.

**`_channel_extractors` (EXCLUSIVE) vs `_marker_extractors` (MULTI) — the precise difference:**

| | `_channel_extractors` (logs) | `_marker_extractors` (markers) |
|---|---|---|
| Rep kind | `Frame` (`_is_wellbore_frame`) | `MarkerFrame` (`_is_marker_frame`) |
| Display cardinality | **EXCLUSIVE — one at a time** | **MULTI — many at once** |
| Show entry point | [`set_channel_visible`](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L468) | [`set_marker_visible`](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L601) |
| Show side-effect | **Hides every OTHER channel of the frame** before showing the picked one | No side-effect — independent toggle |
| Builder | [`_create_channel_extractor`](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L547) | [`_create_marker_extractor`](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L636) |
| Persistence | Source **persists** once created (hidden when another is shown) → scoped LUT/COE/stats read it directly, no retarget | Persists; each independently recolourable (`solid_color_by_marker`) |
| "Currently shown" accessor | [`visible_channel_extractor`](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L526) (the single visible one) | [`visible_marker_displays`](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L721) (the list of visible ones) |
| Materialise-while-hidden | [`channel_extractor_for(create=True)`](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L511) — lets COE/stats read the active channel even when a *different* one is displayed | n/a (markers shown are the ones read) |
| Per-entry colour state | frame's `solid_color_by_rep` | per-marker `solid_color_by_marker`, falling back to frame |

**Why both use per-child extractors:** a frame/markerframe has **no meaningful geometry of its own** — only its children do, and each child is a distinct partition in the collector's composite output. Giving each child its own `EnergisticsExtractor` (instead of retargeting one shared frame extractor's ExtractPath) means each child's source is **persistent and independently addressable**: its scoped LUT, COE graph, and stats all read it directly with **no retarget dance**. This is the big recent refactor — the old "single shared frame extractor whose ExtractPath is RETARGETED" (`set_extract_channel`, `read_only_channel_retarget`) is **deleted**; the channel switch is now a plain hide/show.

**How exclusive-show works:** `set_channel_visible(channel_path, True)` calls `channel_extractor_for(create=True)`, then **iterates `_channel_extractors` and `Hide()`s every sibling** in this scene's `pv_view` before `Show()`ing the picked one. Markers skip that loop entirely. On a plain channel *selection* (no eye click), [`active_array.on_active_array_change`](../../fespp_on_trame/app/core/engine/active_array.py#L84) → `_show_channel_active_view` shows the channel *before* coloring, because `apply_color_array` re-reads the now-visible channel's own arrays via `resolve_array_for_path`.

> **Channel naming (C++ sanitize):** `ResqmlWellboreChannelToVtkPolyData.cxx` now sanitizes the channel array name via `MakeValidNodeName`, so channels are sanitized-named like grids. [`real_base_name`](../../fespp_on_trame/app/core/engine/source_resolver.py#L189) still probes the per-view source to pick the name that *actually exists* (raw vs sanitized) so the COE keys the same LUT the render path keyed.

### The threshold chain (non-IJK)

The per-view chain ([`_add_threshold_local`](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L1245), [`_refresh_chain_visibility`](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L1399)) mirrors `ExtractBlockRepresentation`'s `ChainEntry` design but: upstream is `self._extractor` (per-view), reg-name suffixes `_v{view_id}` so chains from different views don't collide in PV's proxy registry, and Show/Hide targets `self.scene.pv_view`. Visibility rule: an entry shows iff `entry.visible AND no visible descendant`; the **primary** hides when a chain tip is shown OR slice/clip is on OR the user hid the rep OR `_channelless_frame()` forces it. IJK reps return early — they use `_per_view_ijk._chain` instead.

### Slice / clip

Per-(rep, view) [`SlicePlane`](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L916) / [`ClipPlane`](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L953), each aware of its owning `view_id`/`pv_view`, chained on `self.source()` (the per-view extractor or per-view IjkGrid rep_data). Enabling either **hides the rep's primary in this scene's pv_view only** ([`_refresh_parent_rep_visibility`](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L1020)) so the cross-section/clipped chunk is what's visible — other scenes keep the rep visible. For IJK, this method delegates to `ijk.show(view=…)` (the per-view IjkGrid owns its own show/hide policy); for a `_channelless_frame` it force-hides the primary; otherwise it Shows/Hides based on `slice_on | clip_on | chain_visible`. `clip_output()` / `slice_output()` expose the filter proxies so the ColorBy fan-out and stats dispatch include the right rendered output.

---

I now have a comprehensive understanding of the code. Let me write the assigned sections.

## Grouping (Collection / Wellbore / Feature / Interpretation / Partial)

**Tree role.** Pure organisational folders — no VTK source, no eye, no colour of their own. They exist only to bulk-select their subtree and render a tri-state checkbox. C++ stamps them `kind ∈ {Collection, Wellbore, Feature, Interpretation, Partial}` (`Feature`/`Interpretation` only appear in the non-Flat hierarchy modes). The canonical grouping set lives in **three** places that must stay in sync:

| Location | Constant | Used for |
|---|---|---|
| [tree.py#L103](../../fespp_on_trame/app/core/tree.py#L103) `is_grouping` | `Collection, Wellbore, Feature, Interpretation, Partial, Frame, MarkerFrame` | publishes `is_grouping` + `descendant_ids` to the Vue tree |
| [tree_views.py#L19](../../fespp_on_trame/app/ui/drawer/tree_views.py#L19) `_GROUPING_KINDS` | same 7 | UI bulk-select cascade + tri-state checkbox |
| [activator.py#L41](../../fespp_on_trame/app/core/activator.py#L41) `_GROUPING_KINDS` | same 7 | `_is_node_active_able` (a grouping may activate via a checked descendant) |

> **Pitfall (the 3-list trap):** `Frame`/`MarkerFrame` are in all three grouping lists **but are also reps** (in `_representation_type_in`). They are "folder-for-tree, representation-for-source" — see the FrameRep section. A plain grouping (`Collection`/`Wellbore`/`Feature`/`Interpretation`/`Partial`) is grouping in **all** senses and is **never** in `_representation_type_in`.

**Eye type:** none (M/A/R all absent). The grouping carries a tri-state *select* checkbox only ([`_select_checkbox_icon`](../../fespp_on_trame/app/ui/drawer/tree_views.py#L223)): marked when every `descendant_ids` ∩ `ui_select_node_*` is full, `mdi-minus-box` when partial, blank otherwise.

**Selection / bucket cascade.** Checking a grouping bulk-adds its subtree; the cascade is symmetric on removal. Two layers:
- [`tree_toggle_select`](../../fespp_on_trame/app/ui/drawer/tree_views.py#L640): grouping click cycles "some→all" then "all→empty" over `find_all_selectable_descendant_ids`.
- [`_expand_selection_with_deps`](../../fespp_on_trame/app/ui/drawer/tree_views.py#L36): adding a grouping adds all selectable descendants; **removing** a grouping (or any rep) drops every descendant.

**`Wellbore` is special among groupings.** It is the WellboreFeature folder (e.g. `"55/33-3"`) — NOT a rep ([tree.py#L28-L33](../../fespp_on_trame/app/core/tree.py#L28) comment). Its children (Trajectory / Frame / MarkerFrame / Completion) are the reps. A checked `WellboreChannel`/`WellboreMarker` auto-checks the **sibling** `WellboreTrajectory` (the anchoring geometry), via [`_WELLBORE_LEAF_KINDS_NEEDING_TRAJECTORY`](../../fespp_on_trame/app/ui/drawer/tree_views.py#L33).

**`Partial` is special: reference-only.** A partial node (`kind ∈ {partial, Partial}`) has only Title + UUID, no data. It is:
- title-marked `!!!PARTIAL!!!` and `disabled=True` ([tree.py#L57-L59](../../fespp_on_trame/app/core/tree.py#L57)); no checkbox renders.
- **excluded** from every grouping's selectable universe via [`find_all_selectable_descendant_ids`](../../fespp_on_trame/app/core/tree.py#L324) (vs `find_all_descendant_ids`), so a grouping's tri-state can still reach "all selected" and a bulk-select never pulls in an unloadable stub.

> **Pitfall (`disabled` latching):** the per-node partial flag must be local — `set_tree` resets `disabled=False` every top-level iteration ([tree.py#L188](../../fespp_on_trame/app/core/tree.py#L188)) and `add_subtreeview_data` uses a separate `node_is_partial` so it does NOT mutate the function-scoped `disabled` forwarded to children ([tree.py#L52-L59](../../fespp_on_trame/app/core/tree.py#L52)); otherwise a partial rep stub would disable its real descendants.

**Tab dispatch.** Top-level groupings have no own kind to route on. `set_tree` walks into `Feature`/`Interpretation` via [`_resolve_dispatch_kind`](../../fespp_on_trame/app/core/tree.py#L144) to find the first real descendant kind, and routes a top-level `partial` stub by its `supporttype` attribute ([tree.py#L209-L216](../../fespp_on_trame/app/core/tree.py#L209)).

**Source / pipeline / visibility / colour / COE / threshold:** **none** — groupings own nothing. **Where to modify:** changes to bulk-selection or tri-state go in `tree_views.py`; changes to "what counts as a folder" must touch all three `_GROUPING_KINDS`/`is_grouping` lists together. Never add a grouping to `_representation_type_in` unless it also gains a per-view source (the Frame precedent).

---

## GridRep — IjkGrid (the most special) + UnstructuredGrid / Sub

These three are reservoir-tab reps (`kind ∈ {IjkGrid, UnstructuredGrid, Sub}`). They diverge sharply: **IjkGrid is the ONLY rep with a bespoke per-view pipeline class** ([`IjkGrid`](../../fespp_on_trame/app/core/sources/ijkgrid.py)); UnstructuredGrid / Sub are generic non-IJK reps that go through the plain `EnergisticsExtractor` path like surfaces.

### IjkGrid

| Concern | Behaviour | File:line |
|---|---|---|
| Tree role | Rep with property descendants (Continuous/Discrete/Categorical/TS/MR leaves). | — |
| Eye | **R** (rep eye) on the grid + **A** (data-array eye) on each property. | [tree_views.py#L390](../../fespp_on_trame/app/ui/drawer/tree_views.py#L390) |
| Selection | A property is activatable only when checked on its own id; the rep activates via a checked descendant. | [activator.py#L194](../../fespp_on_trame/app/core/activator.py#L194) |
| Source / pipeline | **DUAL**: a legacy shared `IjkGrid` (owned by `SourceRegistry`, drives property selection through the engine) AND a per-`(rep,view)` `IjkGrid` ([`_per_view_ijk`](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L81)) chained on the scene clone. Each grid owns: `_src_extract_init` (rep_data extractor), per-axis `ExplicitStructuredGridCrop` slicers (i/j/k), `_src_slicer_volume`, and an `_IjkChainEntry` threshold chain whose proxies are keyed **per upstream** (`pv_proxies[id(src)]`). | [ijkgrid.py#L66](../../fespp_on_trame/app/core/sources/ijkgrid.py#L66) |
| Visibility | `IjkGrid.show()` is the authority — slice mode shows per-axis crops, range mode shows `slicervolume` (or rep_data at full extent, PV6 degenerates the crop), with a rep_data fallback when every slicer eye is off. | [ijkgrid.py#L527](../../fespp_on_trame/app/core/sources/ijkgrid.py#L527) |
| Colour | ColorBy fans onto slicers + volume + chain leaves (NOT `_src_extract_init`, intentionally excluded). | [source_resolver.py#L347](../../fespp_on_trame/app/core/engine/source_resolver.py#L347) |
| COE mode | property kind from the activated leaf; LUT scoped per `(scene, array)`. | [activator.py#L300](../../fespp_on_trame/app/core/activator.py#L300) |
| Threshold | per-upstream chain; mode-flip / slicer-add rewires via `_refresh_chain_pipeline`. | [ijkgrid.py#L1019](../../fespp_on_trame/app/core/sources/ijkgrid.py#L1019) |

**The legacy↔per-view mirror.** `_ensure_per_view_ijk` ([rep_in_scene.py#L188](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L188)) reads the legacy IjkGrid's `_property_path`, round-trips it to a node id, builds the per-view `IjkGrid(view_id, clone, pv_view)`, then **hides the legacy slicers in this scene's view** (`_hide_legacy_ijk_in_scene_view`). The engine keeps them in step via `SceneRegistry.refresh_per_view_ijk_for_rep` / `mirror_legacy_ijk_state`.

> **Pitfalls (IjkGrid-specific, high-density):**
> - **Empty-assembly → wrong output type.** The clone must be `UpdatePipeline()`-d BEFORE per-view IjkGrid creation, else the extractor's `RequestDataObject` peek returns null, falls back to `vtkPolyData`, and every `ExplicitStructuredGridCrop` rejects the input ([rep_in_scene.py#L234-L253](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L234)).
> - **Z-fight on property swap.** `refresh_per_view_ijk_property` must re-hide the legacy slicers AND re-hide-in-scene if the bucket says hidden — the legacy `set_node_id→show()` re-asserts `Visibility=1` in the active view ([rep_in_scene.py#L307](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L307)).
> - **Never `Show(_src_extract_init)` from the generic refresher.** `_refresh_parent_rep_visibility` delegates the IJK case to `ijk.show(view=...)` ([rep_in_scene.py#L1075](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L1075)); a raw Show rasterises the full uncropped grid with a default SolidColor tint (the "red block Z-fighting the slicers" bug after a 2nd property selector).
> - **Slicer data pass on load.** [data_load.py#L159-L194](../../fespp_on_trame/app/core/engine/data_load.py#L159) does a full `UpdatePipeline()` (not just info) on rep_data + each slicer, or the cached slicer output has the right cell count but **no CellData arrays** and the activator misses the property.
> - **`update_block_visibility`** drops the IJK property path from the parent multiblock `BlockSelectors` so it renders only through the grid's slicers, cumulative-safe across grids ([ijkgrid.py#L1151](../../fespp_on_trame/app/core/sources/ijkgrid.py#L1151)).
> - **Snapshots read per-view ONLY**, never legacy — a copy of slicer/threshold state must not capture shared state ([rep_in_scene.py#L1662](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L1662)).

### UnstructuredGrid / Sub

Generic non-IJK reps: single per-`(rep,view)` `EnergisticsExtractor` (`_extractor`) + a per-view threshold `_chain` of `ChainEntry`, exactly like surfaces. Source resolution: `source() → _ensure_extractor()` ([rep_in_scene.py#L346](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L346)); colour/threshold/visibility go through the non-IJK branches of `source_resolver`, `_refresh_parent_rep_visibility`, `_refresh_chain_visibility`. `Sub` is a sub-representation child but behaves identically at the source layer.

**Where to modify:** IJK-only display logic (slice/range mode, slicer eyes, volume) belongs in `ijkgrid.py` — it is shared by both the legacy and per-view instances (constructor `view_id/clone/pv_view` all-or-none toggle). A change touching "all reservoir grids" but NOT surfaces goes at the `_is_ijk_grid()` branch level in `rep_in_scene.py` / `source_resolver.py`. A change for "all non-IJK reps" goes in the generic extractor/chain path — and will automatically also affect surfaces (see next section); scope it carefully.

---

## SurfaceRep / WellboreGeom (Grid2d, PointSet, Polyline, PolylineSet, TriangulatedSet, Trajectory, Completion, Perfo)

These are the **generic non-IJK, non-frame reps**. Surface-tab kinds (`Grid2d, PointSet, Polyline, PolylineSet, TriangulatedSet`) and well-geometry kinds (`Trajectory, Completion, Perfo`) share one identical pipeline: a single per-`(rep,view)` `EnergisticsExtractor` chained on the scene clone + an optional per-view threshold `_chain`. They differ only in tab routing and which companion objects the Selector spawns.

| Concern | Behaviour | File:line |
|---|---|---|
| Tree role | Leaf-ish reps. `Trajectory` is the wellbore geometry anchor (auto-checked when a channel/marker is checked). | [tree_views.py#L91](../../fespp_on_trame/app/ui/drawer/tree_views.py#L91) |
| Eye | **R** rep eye; **A** array eye on any property descendants (surfaces can carry Continuous/Discrete properties; Trajectory/Completion/Perfo usually don't). | [tree_views.py#L456](../../fespp_on_trame/app/ui/drawer/tree_views.py#L456) |
| Selection | `Trajectory` checked → `Wellhead` companion created; surfaces just push paths. | [selector.py#L84](../../fespp_on_trame/app/core/selector.py#L84) |
| Source | `source() → _ensure_extractor()` (`EnergisticsExtractor`, `ExtractPath = rep_path`). Auto-shown on create unless hidden-in-scene. | [rep_in_scene.py#L346](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L346) |
| Visibility | `_refresh_parent_rep_visibility` Shows the extractor unless slice/clip/chain-tip/eye-hidden. | [rep_in_scene.py#L1091](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L1091) |
| Colour | per-view `_extractor` + `all_chain_proxies` get the ColorBy fan-out + per-view scoped LUT. | [source_resolver.py#L384](../../fespp_on_trame/app/core/engine/source_resolver.py#L384) |
| COE mode | published by `_publish_active_color_state` (well/surface tabs) for property leaves only. | [activator.py#L742](../../fespp_on_trame/app/core/activator.py#L742) |
| Threshold | per-view local chain (`_add_threshold_local`), identical machinery to UG. | [rep_in_scene.py#L1245](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L1245) |
| Slice / Clip | per-`(rep,view)` `SlicePlane` / `ClipPlane`, enabling either hides the primary in that view. | [rep_in_scene.py#L916](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L916) |

> **Pitfalls:**
> - **Z-fight with legacy EB.** On extractor creation the legacy `ExtractBlockRepresentation` Show in this view is hidden ([rep_in_scene.py#L443-L458](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L443)).
> - **Trajectory is the dependency anchor.** Channels/markers need it; deselecting a Trajectory drops dependent leaves via the removal cascade.
> - **`Completion`/`Perfo` carry no properties** — their array-eye branch never renders; only the rep eye. `Perfo` is named `"Perfo"+...` in C++ ([ResqmlDataRepository...cxx#L1176](../../../../fespp/work/src/Plugin/Energistics/Mapping/ResqmlDataRepositoryToVtkPartitionedDataSetCollection.cxx#L1176)).
> - **`Polyline` vs `PolylineSet`.** Both are in `_representation_type_in`; the tree-icon map only has `PolylineSet` so `Polyline` falls through `get_icon_for_type`'s substring match.

**Where to modify:** anything touching "all generic reps" (extractor creation, threshold chain, slice/clip) lives in `RepInScene`'s **non-IJK, non-`_channelless_frame` branch** — this is shared by surfaces, well geometry, UG, **and** the frame primaries (which are forced hidden). To change surface behaviour without touching well geometry you must branch on `kind` (there is no shared "surface family" object — they're unified at the `RepInScene` level). Tab routing only is in `tree.py`'s `treeview_type` lists.

---

## FrameRep — Frame (logs) and MarkerFrame (markers): the dual nature

A frame is **"folder-for-the-tree, representation-for-the-source"**: it appears in BOTH `is_grouping`/`_GROUPING_KINDS` ([tree.py#L103](../../fespp_on_trame/app/core/tree.py#L103), [tree_views.py#L19](../../fespp_on_trame/app/ui/drawer/tree_views.py#L19)) AND `_representation_type_in` ([tree.py#L34](../../fespp_on_trame/app/core/tree.py#L34)). Consequences:
- In the **tree** it is a folder: tri-state checkbox, no rep eye of its own (`_eye_slot` explicitly excludes `Frame`/`MarkerFrame` from the rep-eye gate at [tree_views.py#L390-L393](../../fespp_on_trame/app/ui/drawer/tree_views.py#L390)). Checking it bulk-selects every child log/marker.
- For the **source**, `find_representation_node` on a channel/marker leaf resolves UP to the frame — the frame node is the rendering anchor that **hosts the per-`(child,view)` extractors**. The frame node itself has **no dataset index**; its children do.
- The frame's own primary `_extractor` is **NEVER rendered** (`_channelless_frame()` returns True for both kinds, [rep_in_scene.py#L746](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L746)). If the generic refreshers Show it, the C++ side resolves `ExtractPath = frame_path` to the frame's **first** child partition, re-surfacing a log/marker the user never picked. Hence every generic visibility path force-hides the primary for frames.

The two kinds split on **cardinality**: **Frame channels = exclusive (one log at a time)**; **MarkerFrame markers = multi (many at once)**. C++ stamps the runtime kinds `Frame`, `MarkerFrame`, and the leaves `WellboreChannel`/`Marker` (children); `_is_wellbore_frame` tests `== 'Frame'` and `_is_marker_frame` tests `== 'MarkerFrame'` exactly ([rep_in_scene.py#L126](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L126), [#L148](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L148)).

### The NEW per-channel architecture (Frame, logs)

**Each channel owns its OWN `EnergisticsExtractor`**, keyed by channel path in `_channel_extractors: dict` ([rep_in_scene.py#L61](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L61)) — structurally identical to markers (`_marker_extractors`) but **exclusive** instead of multi. The OLD single-shared-frame-extractor-whose-ExtractPath-is-retargeted design (`set_extract_channel`, `_extractor_channel_path`, `read_only_channel_retarget`) is **DELETED**. The switch is now a plain hide/show; each channel's source PERSISTS so its scoped LUT/COE/stats read it directly with **no retarget**.

| Method | Role | File:line |
|---|---|---|
| `set_channel_visible(channel_path, visible)` | EXCLUSIVE show: materialises the channel's extractor, then **Hides every OTHER channel** of this frame before Show. Visibility-only. | [rep_in_scene.py#L468](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L468) |
| `channel_extractor_for(channel_path, create=True)` | Returns (and MATERIALISES, hidden, if absent) the channel's extractor — so an ACTIVE-but-not-displayed channel's COE/stats still read it. | [rep_in_scene.py#L511](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L511) |
| `visible_channel_extractor()` | The single extractor currently `Visibility=1` — render/color/stats-view anchor. | [rep_in_scene.py#L526](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L526) |
| `_create_channel_extractor(channel_path)` | Builds the proxy (`ExtractPath = channel leaf`, tube + point array), hidden in other views, frame's solid tint. Mirror of `_create_marker_extractor`. | [rep_in_scene.py#L547](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L547) |

**Selection path (no eye click):** `data_load` auto-activates frame→last channel; `on_active_array_change` calls `_show_channel_active_view` to SHOW the channel exclusively BEFORE coloring ([active_array.py#L27](../../fespp_on_trame/app/core/engine/active_array.py#L27), [#L84](../../fespp_on_trame/app/core/engine/active_array.py#L84)). **Eye click:** `toggle_dataarray_color` detects `is_channel` (`rep_kind == 'Frame' and r_id != node_id`), calls `set_channel_visible(...)` first, then `apply_color_array`, then publishes the viewed channel as the COE's active array so the editor follows the displayed log ([active_array.py#L380-L420](../../fespp_on_trame/app/core/engine/active_array.py#L380)).

**Why COE/stats of an active-but-hidden channel still read correctly:** `resolve_array_for_path` and `channel_source_for` call `channel_extractor_for(array_path, create=True)` — the channel's source always exists (just hidden when a sibling is shown), so `GetArrayInformation`/range queries hit a real proxy carrying that channel's array ([source_resolver.py#L468-L475](../../fespp_on_trame/app/core/engine/source_resolver.py#L468), [#L118](../../fespp_on_trame/app/core/engine/source_resolver.py#L118)).

**Toggle OFF** (`new_value is None`) just Hides that channel's extractor and clears COE state back to Solid ([active_array.py#L416-L420](../../fespp_on_trame/app/core/engine/active_array.py#L416)).

### Markers (MarkerFrame) — the multi contrast

`set_marker_visible` ([rep_in_scene.py#L601](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L601)) is identical machinery **minus the exclusivity loop** — it Shows the marker without hiding siblings. Each visible marker keeps its own `solid_color_by_marker` tint ([rep_in_scene.py#L687](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L687)); `visible_marker_displays()` feeds the SolidColor fan-out ([rep_in_scene.py#L721](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L721)). Markers carry **no colour array** — they are visibility-only, tracked in `ui_visible_marker_paths_by_view` and toggled by `visibility.toggle_marker_visibility` ([visibility.py#L75](../../fespp_on_trame/app/core/engine/visibility.py#L75)), with their own `ui_loaded_marker_paths` eye list ([data_load.py#L375](../../fespp_on_trame/app/core/engine/data_load.py#L375)).

**C++ MapperSet & sanitization.** The frame is a `MapperSet` (one partition per child); the frame node carries no dataset index, the children do. The channel's POINT array name **now goes through `MakeValidNodeName`** (sanitized, like grids/UG) while the assembly `title` stays raw ([ResqmlWellboreChannelToVtkPolyData.cxx#L100-L153](../../../../fespp/work/src/Plugin/Energistics/Mapping/ResqmlWellboreChannelToVtkPolyData.cxx#L100)). Hence `real_base_name` ([source_resolver.py#L189](../../fespp_on_trame/app/core/engine/source_resolver.py#L189)) probes the source: it returns the raw title only when that raw name actually exists on the per-view source — for sanitized channels it now correctly falls back to the sanitized name, keying the SAME LUT the render path uses.

> **Pitfalls:**
> - **Never let the primary Show.** Every generic path (`_refresh_parent_rep_visibility`, `_refresh_chain_visibility`, `_ensure_extractor`) gates on `_channelless_frame()` ([rep_in_scene.py#L420](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L420), [#L1100](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L1100), [#L1457](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L1457)).
> - **Rescale-from-fresh.** A channel pick re-points an extractor to a single leaf; `pvsimple.ColorBy`'s internal rescale reads a stale cache → `[0,1]` flat tube. `apply_color_array` re-rescales from the client-side array ([source_resolver.py#L805-L825](../../fespp_on_trame/app/core/engine/source_resolver.py#L805)).
> - **`toggle_rep_visibility` skips the clear-coloring intermediate for `Frame`** ([visibility.py#L154-L175](../../fespp_on_trame/app/core/engine/visibility.py#L154)) — a frame's eye is a plain show/hide.
> - **Split inheritance** shows the active channel exclusively in the new view ([scene_registry.py#L232](../../fespp_on_trame/app/core/sources/scene_registry.py#L232)) and re-applies visible markers via `apply_visible_markers` ([scene_registry.py#L265](../../fespp_on_trame/app/core/sources/scene_registry.py#L265)).

**Where to modify:** channel-exclusivity logic lives entirely in `set_channel_visible` (the only place that hides siblings) — change one-at-a-time→N-at-a-time there. Marker multi-logic is in `set_marker_visible`. "Frame primary stays hidden" is `_channelless_frame()` — adding a new frame-like kind means adding it there AND to the relevant grouping/rep lists. COE-follows-displayed-channel is in `toggle_dataarray_color`'s `is_channel` block.

---

## Leaves — properties (Continuous / Discrete / Categorical / TimeSeries / MultiRealization*) vs Marker

Property leaves and Marker leaves are both tree leaves under a rep, but they are **fundamentally different eye types**: a property carries an **A** (data-array / color) eye; a marker carries an **M** (visibility-only) eye.

### Property leaves

| Aspect | Continuous / Discrete / Categorical | TimeSeries | MultiRealization / MultiRealizationTimeSeries |
|---|---|---|---|
| Synthetic? | No — real RESQML property leaf | Yes (collapses per-timestep nodes; `propKind` carries true kind) | Yes (`propKind` + `propTitle` carry the real kind / VTK name) |
| Tree badge | property icon | clock (`is_ts`) | "MR" chip (`is_mr`) [+ clock for MRTS] |
| `_DATA_ARRAY_KINDS` | all three | yes | both |
| COE kind | `active_property_kind = kind` directly | `propKind` attr | `propKind` attr |
| VTK array name | sanitized title | sanitized title | `<sanitized_propTitle>_real_<idx>` (suffixed) |

- **Eye = A.** Loaded properties appear in `ui_loaded_array_paths` and render the array eye ([data_load.py#L342](../../fespp_on_trame/app/core/engine/data_load.py#L342)). Clicking colors the parent rep by this array in the target view; the previous active array on the same rep/view loses its eye ([active_array.py#L231](../../fespp_on_trame/app/core/engine/active_array.py#L231)).
- **Selection.** A property is activatable ONLY when checked on its OWN id — being under a checked rep is not enough (the dep-expansion auto-adds the rep, so an "under checked rep" rule would activate every sibling — the reported bug, [activator.py#L213-L238](../../fespp_on_trame/app/core/activator.py#L213)).
- **Auto-activation on load.** The last-added array per rep auto-becomes the active eye in the **active panel only** ([data_load.py#L418](../../fespp_on_trame/app/core/engine/data_load.py#L418)). For MR, the realization bucket is seeded with the default idx FIRST, else the resolver can't find any `_real_<idx>` array and the rep stays SolidColor ([data_load.py#L489-L506](../../fespp_on_trame/app/core/engine/data_load.py#L489)).
- **MR realization choice** is per-`(view, array)` in `ui_active_realization_by_array_by_view`; `resolve_array_for_path` tries the suffixed name first ([source_resolver.py#L497](../../fespp_on_trame/app/core/engine/source_resolver.py#L497)).
- **TS drives the TimeControl** — `panel_has_ts_by_id` is derived per panel from whether any active array resolves to a TS / MRTS node or descendant ([active_array.py#L203](../../fespp_on_trame/app/core/engine/active_array.py#L203)); the activator gates `on_data_loaded()` on `is_ts_property` ([activator.py#L296-L299](../../fespp_on_trame/app/core/activator.py#L296)).
- **Source/visibility/COE:** a property has no source of its own — it colors its rep's source. COLOR resolves to whichever rendered proxies the rep exposes (IJK slicers / surface extractor / **the displayed channel extractor for a frame**). COE mode is published by `_handle_reservoir_change` (reservoir) or `_publish_active_color_state` (well/surface) ([activator.py#L307](../../fespp_on_trame/app/core/activator.py#L307), [#L742](../../fespp_on_trame/app/core/activator.py#L742)).

> **Pitfalls:**
> - **MultiRealization nodes are leaves** — `add_subtreeview_data` does NOT recurse into them ([tree.py#L136](../../fespp_on_trame/app/core/tree.py#L136)).
> - **`title` vs `propTitle`.** For MR the VTK array name is in `propTitle`, not `title` ([activator.py#L327](../../fespp_on_trame/app/core/activator.py#L327), [source_resolver.py#L456](../../fespp_on_trame/app/core/engine/source_resolver.py#L456)).
> - **Sanitized lookup fallback.** `_find_array_in_store` / `resolve_array_for_path` retry with `make_valid_vtk_name(title)` because FESPP strips chars outside `[-.0-9A-Z_a-z]` ([activator.py#L11](../../fespp_on_trame/app/core/activator.py#L11), [source_resolver.py#L510](../../fespp_on_trame/app/core/engine/source_resolver.py#L510)).
> - **A wellbore-LOG channel is a property leaf in the WELL tree** — but its rep ancestor is a `Frame`, so it is `is_channel` and routes through the per-channel extractor path, NOT the generic rep-color path. This is the one property-leaf case where the leaf indirectly owns a source (its channel extractor).

### Marker leaves (`WellboreMarker`, runtime kind `Marker`)

- **Eye = M (visibility-only), MULTI.** No colour array. Tracked in `ui_loaded_marker_paths` (eye-render gate) + `ui_visible_marker_paths_by_view` (per-view shown set), mutated by `toggle_marker_visibility` ([data_load.py#L375](../../fespp_on_trame/app/core/engine/data_load.py#L375), [visibility.py#L75](../../fespp_on_trame/app/core/engine/visibility.py#L75)).
- **Source:** each visible marker owns a per-`(marker,view)` `EnergisticsExtractor` on the MarkerFrame's RepInScene (see FrameRep section).
- **Colour:** per-marker SolidColor only, via `solid_color_by_marker`; `_publish_active_color_state` clears COE mode for a marker (not a property) so the panel falls back to Solid ([activator.py#L765](../../fespp_on_trame/app/core/activator.py#L765)).
- **Selection:** a `WellboreMarker` checked auto-checks the Wellbore's Trajectory ([tree_views.py#L33](../../fespp_on_trame/app/ui/drawer/tree_views.py#L33)).

> **Pitfall:** the eye-list kind test is `"Marker"` (runtime kind), but the tree-routing/grouping lists use `"WellboreMarker"` (`supporttype` / dependency kind). Don't conflate them — `_update_marker_tracking` filters on `== "Marker"` ([data_load.py#L393](../../fespp_on_trame/app/core/engine/data_load.py#L393)).

**Where to modify:** property-leaf color/activation logic is split between `activator.py` (publishes COE + active state, reservoir does heavy ColorBy inline) and `active_array.py` (the eye toggle + fan-out). MR/TS specifics concentrate in `realization_dispatch` + the `is_mr`/`is_ts` branches. Marker-leaf logic is entirely separate (visibility tracking in `data_load._update_marker_tracking`, toggle in `visibility.py`, source in `RepInScene._marker_extractors`) — a change to markers never touches the property path and vice-versa.
