# Core — Element Types (strategy hierarchy)

## Overview

The `element_type` package is the **single source of truth for "how does a RESQML element of this runtime `kind` behave"**. Before this refactor (called *the ElementType refactor* / *Step 3* in the docstrings), the answer was scattered across the tree, tracking, eye, visibility, colour and source layers as `if kind == "IjkGrid"` / `if kind == "Frame"` style branches. The package replaces every one of those branches with a **stateless polymorphic singleton** per kind, selected once via an O(1) dict lookup and then asked questions (`is_grouping()`, `eye_descriptor()`, `tracking_bucket()`, `visibility_policy()`, …) or told to act (`set_child_visible(...)`, `ensure_extractor(...)`, `refresh_primary_visibility(...)`).

The design has two pillars. **(1) A three-level class hierarchy — general → family → unit** — so behaviour is written at the *highest* level where it is correct and never higher: the base `ElementType` holds the neutral contract; `Grouping` / `Representation` / `Leaf` are the families; concrete units (`IjkGridRep`, `ChannelFrameRep`, `MarkerLeaf`, …) override only what deviates. **(2) "Option A" statelessness** — the singletons hold *no* per-(rep, view) state. The state lives on a `RepInScene` object (`ris`) in the source layer (`fespp_on_trame/app/core/sources/rep_in_scene.py`). `RepInScene` resolves its `ElementType` once (cached on `self._element_type_cache`, via `element_type.for_path`) and then delegates every per-kind method to it, **passing itself as the first argument `ris`** so the stateless singleton can read and write the per-(rep, view) state (`ris._extractor`, `ris._per_view_ijk`, `ris._channel_extractors`, `ris._marker_extractors`, `ris.scene`, …). The single most important behavioural fork in the whole package is `FrameRep.set_child_visible`: channels are **EXCLUSIVE** (one log shown at a time) while markers are **MULTI** (N markers at once) — and the secondary fork is `FrameRep._apply_child_z`: channel children **scale** Z (log tubes follow the well) while markers **translate** Z (a sphere must stay a sphere, not stretch into an olive).

> The `KINDS` strings throughout are the **runtime** kinds (the output of the C++ `SimplifyXmlTag`: `'Frame'`, `'MarkerFrame'`, `'Marker'`, `'Sub'`, …), **not** the C++ enum names. The package is import-safe without a ParaView runtime: every `paraview` / `trame` / `sources.*` import is *local to the method*, so the package stays a leaf with no import cycle into the source layer, and the unit tests can import it bare.

Layout (from the package docstring) — a class is indented **under the file
it lives in** (left column = where the class is on disk); the `(BaseClass)`
in each name is its Python parent, so the **general → family → unit**
inheritance reads too. A parent that lives in another file is visible at a
glance — e.g. `FrameRep(Representation)` is defined in `frames.py` but
inherits from `representation.py`:

```
enums.py
    TreeRole, VisibilityPolicy, ColorPolicy, EyeKind, EyeDescriptor,
    BUCKET_* / EYE_* constants
base.py
    ElementType                          base contract + neutral defaults
grouping.py
    Grouping(ElementType)                folder, no source, tri-state selection
    PartialType(Grouping)                Partial: folder, NOT selectable
representation.py
    Representation(ElementType)          geometry + eye + per-view source
    GridRep(Representation)              UnstructuredGrid, Sub — standard
    IjkGridRep(GridRep)                  IjkGrid — I/J/K slicers + volume, modal
    SurfaceRep(Representation)           Grid2d, PointSet, Polyline*, TriangulatedSet
    WellboreGeometryRep(Representation)  Trajectory, Completion, Perfo/Perforation
    SeismicFrameRep(Representation)      SeismicWellboreFrame — a real rep
frames.py
    FrameRep(Representation)             folder-for-tree, representation-for-source
    ChannelFrameRep(FrameRep)            Frame — logs, ONE log at a time
    MarkerFrameRep(FrameRep)             MarkerFrame — N markers at once
leaf.py
    Leaf(ElementType)                    sub-element of a rep, not a rep itself
    PropertyLeaf(Leaf)                   colours the parent rep; a channel is this
    MarkerLeaf(Leaf)                     toggles ONE marker's visibility
registry.py
    for_kind / for_path / registered_kinds   (+ _REGISTRY / _CONCRETE / _FALLBACK)
```

---

### `fespp_on_trame/app/core/element_type/__init__.py`

**Responsibility.** Package entry point: documents the three-level hierarchy and re-exports the entire public API so that legacy `from fespp_on_trame.app.core import element_type` callers keep working unchanged after the module split (`element_type.for_kind`, `element_type.IjkGridRep`, `element_type.BUCKET_ARRAY`, `element_type.VisibilityPolicy`, …).

**Key classes / functions.** No code of its own — pure re-export. It pulls the enums/descriptors from `.enums`, `ElementType` from `.base`, the families/units from `.grouping`, `.representation`, `.frames`, `.leaf`, and the resolvers (`for_kind`, `for_path`, `registered_kinds`) plus the private tables (`_CONCRETE`, `_REGISTRY`, `_FALLBACK`) from `.registry`. `__all__` lists the public names (note: the `_REGISTRY` / `_CONCRETE` / `_FALLBACK` internals are imported but deliberately *not* in `__all__`).

**State.** None.

**Collaborators.** Imports all sibling modules. Imported by every consumer of the subsystem (`rep_in_scene.py`, `source_resolver.py`, `tree.py`, `data_load.py`, `active_array.py`, `stats_dispatch.py`, the unit tests).

**Gotchas.** The module docstring is itself a load-bearing spec — it states the **golden rule**: *write behaviour at the HIGHEST level where it is correct, and never higher*. It also points to `doc/EN|FR/REFACTOR_ELEMENT_TYPE_HIERARCHY.md` (design) and `TYPES_PARTICULARITES.md` (per-type spec this code encodes) — read those before extending the hierarchy.

---

### `fespp_on_trame/app/core/element_type/enums.py`

**Responsibility.** The contract *value types*: the policy enums, the eye descriptor class, the tracking-bucket string tokens, and the three **singleton** eye descriptors returned by reference so building a large tree allocates nothing per node.

**Key classes / functions.**
- `class TreeRole(Enum)` — `FOLDER` (tri-state checkbox, no own eye — groupings + frames), `REPRESENTATION` (eye-bearing renderable), `LEAF` (property/marker under a rep). Where the node sits in the treeview interaction model.
- `class VisibilityPolicy(Enum)` — how the per-view source is shown/hidden: `NONE` (groupings — no source), `STANDARD` (one extractor, plain show/hide), `IJK_MODAL` (IjkGrid slicer/range modal pipeline), `ONE_AT_A_TIME` (channel frame — exclusive child, one log shown), `MULTI` (marker frame — many children shown at once).
- `class ColorPolicy(Enum)` — `NONE` (groupings), `COLORABLE` (reps + property leaves: ColorBy / SolidColor), `VISIBILITY_ONLY` (markers — SolidColor tint, never a ColorArray).
- `class EyeKind(Enum)` — which eye control the node carries and which controller it wires: `REP` (`toggle_rep_visibility`), `ARRAY` (`toggle_dataarray_color`, purple), `MARKER` (`toggle_marker_visibility`, deep-orange).
- `class EyeDescriptor` — `__init__(self, kind: EyeKind, color: str = "", multi: bool = False)`. Uses `__slots__ = ("kind", "color", "multi")`. Describes a node's eye affordance: `kind`, the Vuetify `color` the active eye uses, and `multi` (True when several of this eye can be active in one panel at once — markers; False when activating one supersedes the others — a rep's single colour array, a frame's single shown log). **Instances are singletons — never mutate them.**
- Module constants `BUCKET_REP = "rep"`, `BUCKET_ARRAY = "array"`, `BUCKET_MARKER = "marker"` — tracking-bucket tokens naming which `state.ui_loaded_*` list a kind feeds.
- Singleton descriptors `EYE_REP = EyeDescriptor(EyeKind.REP)`, `EYE_ARRAY = EyeDescriptor(EyeKind.ARRAY, color="purple", multi=False)`, `EYE_MARKER = EyeDescriptor(EyeKind.MARKER, color="deep-orange", multi=True)`.

**State.** None directly. The bucket tokens *name* `state.ui_loaded_*` lists that other modules read/write (e.g. `data_load.py`); the eye colours are pushed into the tree node's `treeview.eye` field by `tree.py`.

**Collaborators.** Imported by `base.py`, `grouping.py`, `representation.py`, `frames.py`, `leaf.py`, and re-exported by `__init__.py`.

**Gotchas.** The eye descriptors are returned *by reference* from every `eye_descriptor()` override — mutating one would corrupt every node of that kind across the whole tree. `multi=True` on `EYE_MARKER` is the descriptor-level expression of the channels-vs-markers fork (it tells the UI several markers may be lit at once).

---

### `fespp_on_trame/app/core/element_type/base.py`

**Responsibility.** Defines `ElementType` — the base contract plus *neutral default* behaviour (a plain standard representation). The base is only ever *directly* instantiated as the unknown-kind fallback; every concrete family overrides its own defaults.

**Key classes / functions.** `class ElementType` with class attr `KINDS: tuple = ()`. Methods (all defaults assume a standard, colourable, eye-bearing rep):
- `matches(cls, kind: str) -> bool` *(classmethod)* — `kind in cls.KINDS`.
- `tree_role(self) -> TreeRole` → `TreeRole.REPRESENTATION`.
- `is_grouping(self) -> bool` → `False`. (A folder that renders a tri-state checkbox and bulk-selects descendants. Orthogonal to owning a source — a `FrameRep` is grouping-for-the-tree yet representation-for-the-source.)
- `propagates_selection(self) -> bool` → returns `self.is_grouping()`. Checking the node selects every selectable descendant.
- `is_selectable(self) -> bool` → `True`. (False only for Partial stubs.)
- `eye_descriptor(self)` → `EYE_REP`, or `None` when the node carries no eye.
- `tracking_bucket(self)` → `BUCKET_REP`. Which `ui_loaded_*` list this kind feeds (or `None`).
- `visibility_policy(self) -> VisibilityPolicy` → `STANDARD`.
- `color_policy(self) -> ColorPolicy` → `COLORABLE`.
- `primary_hidden(self) -> bool` → `False`. True iff the rep's PRIMARY per-view extractor must stay hidden (frames).
- **Child-management no-ops** (only `FrameRep` subclasses own children); all take `ris` first: `set_child_visible(self, ris, child_path, visible)`, `child_source(self, ris, child_path, create=False)`, `visible_child_source(self, ris)`, `visible_child_displays(self, ris)` (returns `[]`), `set_child_color(self, ris, child_path, color_hex)`.
- **Visibility no-ops** (called only on reps): `refresh_primary_visibility(self, ris)`, `hide_in_view(self, ris)`.
- **Source-construction no-ops** (Option A: `ris` keeps the state): `ensure_source(self, ris)` (head proxy for ColorBy + display), `ensure_extractor(self, ris)` (standard per-view `EnergisticsExtractor`), `ensure_per_view_ijk(self, ris)` (per-view IjkGrid pipeline), `rendered_sources(self, ris)` (per-view proxies the rep renders — `None` falls through to the legacy registry lookup in `source_resolver`), `color_sources(self, ris)` (ColorBy fan-out targets — `None` falls through to legacy), `array_candidate_source(self, ris, array_path)` (per-view source carrying `array_path`'s VTK array — default `None`).
- `__repr__(self)` → `<ClassName kinds=[...]>`.

**State.** None of its own — but the docstrings codify the **Option A** convention that these methods read/write `ris._extractor` and `ris._per_view_ijk`.

**Collaborators.** Imports `TreeRole`, `VisibilityPolicy`, `ColorPolicy`, `EYE_REP`, `BUCKET_REP` from `.enums`. Subclassed by `Grouping`, `Representation`, `Leaf`. Methods are invoked by `RepInScene` (which passes `self` as `ris`).

**Gotchas.** The `set_child_visible(ris, ...)` signature is the deliberate seam where channel-vs-marker behaviour is centralised — the comment explicitly says *"This is where the per-type behaviour lives (exclusive log vs multi marker), not a scattered `if kind ==`."* The two-tier return convention of `rendered_sources` / `color_sources` (return a list **or** `None` to *fall through to the legacy registry lookup*) is a phased-migration affordance: a non-migrated path returns `None` and `source_resolver` uses its old logic. The base defaults are a *neutral standard rep* precisely so the fallback singleton behaves like an ordinary surface rather than crashing.

---

### `fespp_on_trame/app/core/element_type/grouping.py`

**Responsibility.** The pure organisational folders (no VTK source of their own; C++ `MapperType::Folder` / `isGroupingType`).

**Key classes / functions.**
- `class Grouping(ElementType)` — `KINDS = ("Collection", "Wellbore", "Feature", "Interpretation")`. Tri-state folder; checking selects all selectable descendants. Overrides: `tree_role()` → `FOLDER`, `is_grouping()` → `True`, `eye_descriptor()` → `None`, `tracking_bucket()` → `None`, `visibility_policy()` → `NONE`, `color_policy()` → `NONE`. (Inherits `propagates_selection()` which now returns `True` because `is_grouping()` is True.)
- `class PartialType(Grouping)` — `KINDS = ("Partial", "partial")`. A partial stub (a partial rep *or* a partial property leaf): only Title + UUID, no data — shown as `!!!PARTIAL!!!` and **not** checkable. Overrides: `is_selectable()` → `False`, `propagates_selection()` → `False`.

**State.** None.

**Collaborators.** Imports `ElementType` and the enums. Resolved/instantiated by `registry.py`; queried by `tree.py` (`is_grouping`, `eye_descriptor`) and `data_load.py`.

**Gotchas.** `PartialType` subclasses `Grouping` (so it's still a folder in the tree) but pins `is_selectable`/`propagates_selection` to `False`, so a partial node is rendered but neither checkable nor able to bulk-select. Both case spellings `"Partial"` and `"partial"` are matched. A partial *property* leaf is also routed here (not to `Leaf`) — the comment notes "a partial rep OR a partial property leaf".

---

### `fespp_on_trame/app/core/element_type/representation.py`

**Responsibility.** The eye-bearing renderables: geometry + an eye + a per-view source. Holds the family defaults (REP eye, rep tracking bucket, STANDARD show/hide, COLORABLE) and the actual ParaView source-construction / visibility logic for standard reps, plus the modal `IjkGridRep` override.

**Key classes / functions.**
- `class Representation(ElementType)` — base of the renderables. `tree_role()` → `REPRESENTATION`, `eye_descriptor()` → `EYE_REP`, `tracking_bucket()` → `BUCKET_REP`, `visibility_policy()` → `STANDARD`, `color_policy()` → `COLORABLE`. Then the real behaviour:
  - `refresh_primary_visibility(self, ris)` — SHOW the primary source in `ris.scene.pv_view` **unless** a slice (`ris._slice_plane.enabled`), a clip (`ris._clip_plane.enabled`), or any visible threshold-chain tip (`any(e.visible for e in ris._chain)`) replaces it; then `pvsimple.Hide`/`Show` the upstream (`ris.source()`).
  - `hide_in_view(self, ris)` — `pvsimple.Hide` the per-view primary extractor `ris._extractor`.
  - `ensure_source(self, ris)` — returns `self.ensure_extractor(ris)` if present, else `ris._fallback_legacy_source()` (Phase-2 fallback).
  - `ensure_extractor(self, ris)` — **the core source builder.** Lazily creates the per-(rep, view) `EnergisticsExtractor` proxy rooted on `scene.clone` (registration name `rep_{_sanitize(rep_path)}_v{view_id}`), sets `ExtractPath` = `ris.rep_path`, hides it in all *other* views, sets its display `Representation`/`Scale` (Z from `ris._current_z_scale()`)/tint, then Shows it unless the type is `primary_hidden()` (a frame) or the rep is `ris._hidden_in_scene()`. Hides the legacy ExtractBlock's display in this view to avoid Z-fighting. Caches on `ris._extractor` and returns it. Returns `None` when there's only the shared collector (Phase-2).
  - `rendered_sources(self, ris)` — `[ris._ensure_extractor()]`, substituting the deepest visible threshold-chain leaf (`ris.all_visible_thresholds()[-1]`) when a chain is active; `None` → legacy.
  - `color_sources(self, ris)` — the extractor plus every chain proxy (`ris.all_chain_proxies()`); `None` → legacy.
  - `array_candidate_source(self, ris, array_path)` → `ris._ensure_extractor()` (the array lives on the rep's primary extractor).
- `class GridRep(Representation)` — `KINDS = ("UnstructuredGrid", "Sub")`. Reservoir grids on the standard extractor path. No overrides (pure tagging).
- `class IjkGridRep(GridRep)` — `KINDS = ("IjkGrid",)`. The only kind that goes through the modal IjkGrid pipeline (I/J/K slicers + volume crop + threshold chain, range vs slice mode). Overrides:
  - `visibility_policy()` → `IJK_MODAL`.
  - `refresh_primary_visibility(self, ris)` — does **not** Show `rep_data`; instead defers to `ris._per_view_ijk.show(view=...)`, which is the authority on which sources render for the current range/slice mode.
  - `hide_in_view(self, ris)` — Hides *every* IJK source: `ijk._all_slice_sources()` + `ijk._src_slicer_volume` + `ijk._src_extract_init` + `ijk.all_threshold_sources()`.
  - `ensure_extractor(self, ris)` → **`None`** (IJK reps don't use the standard extractor).
  - `ensure_source(self, ris)` → the per-view IjkGrid's `ijk.source` (rep_data extractor) or the legacy fallback.
  - `ensure_per_view_ijk(self, ris)` — lazily builds a per-(rep, view) `IjkGrid` instance rooted on `scene.clone`, mirroring the legacy shared IjkGrid's selected property (reads the legacy via `ctx.source_registry.get_ijk_grid(rep_path)`, maps `legacy._property_path` → node id via `scene.tree.find_node_id`, drives `set_node_id`). Forces `clone.UpdatePipeline()` first, then hides the legacy IjkGrid's rendered sources in this view. Caches on `ris._per_view_ijk`. Returns `None` if the legacy isn't initialised (no property selected).
  - `rendered_sources(self, ris)` — every proxy the per-view IjkGrid renders (slicers + volume + rep_data), with each upstream's visible-tip proxies (`ijk._visible_leaf_tips()` → `pv_proxies.get(id(s))`) substituted so union branches all render; `None` → legacy.
  - `color_sources(self, ris)` — slicers + volume + **rep_data** + threshold leaves; `None` → legacy. (rep_data is included because it is the proxy rendered for the *complete* grid — range full-extent, and the slice-mode no-visible-slicer fallback — so the active array must ColorBy it too. Its display already exists from `set_node_id`, so this does not create a phantom outline.)
- `class SurfaceRep(Representation)` — `KINDS = ("Grid2d", "PointSet", "Polyline", "PolylineSet", "TriangulatedSet")`. Simple geometry on one extractor; no overrides.
- `class WellboreGeometryRep(Representation)` — `KINDS = ("Trajectory", "Completion", "Perfo", "Perforation")`. Simple wellbore tube geometry on one extractor; no overrides.
- `class SeismicFrameRep(Representation)` — `KINDS = ("SeismicWellboreFrame",)`. Treated as a real eye-bearing rep (NOT a folder like the log/marker frames); kept on standard defaults — behaviour explicitly flagged as *to be confirmed*.

**State (via `ris`).** *Reads:* `ris.scene.pv_view`, `ris.scene.clone`, `ris.scene.collector`, `ris.scene.view_id`, `ris.rep_path`, `ris._slice_plane`, `ris._clip_plane`, `ris._chain`, `ris._extractor`, `ris._per_view_ijk`, `ris._hidden_in_scene()`, `ris._current_z_scale()`. *trame `state`:* reads `state.representation_active`, `state.solid_color_by_rep`. *Writes:* `ris._extractor`, `ris._per_view_ijk`.

**Collaborators.** Local (in-method) imports: `paraview.simple`, `paraview.servermanager.vtkSMPropertyHelper`, `fespp_on_trame.app.core.sources.representation` (`_sanitize`, `_apply_default_tint`, `_create_plugin_filter_proxy`), `fespp_on_trame.app.core.sources.ijkgrid.IjkGrid`, `trame.app.get_server`. Entry points: `RepInScene.source()` → `ensure_source`; `RepInScene._ensure_extractor()` → `ensure_extractor`; `RepInScene._ensure_per_view_ijk()` → `ensure_per_view_ijk`; `RepInScene.refresh_visibility`/`hide` → `refresh_primary_visibility`/`hide_in_view`; `source_resolver.py` (`rendered_sources_for_rep_path`, `color_sources_for_rep_path`, `resolve_array_for_path`) → `rendered_sources` / `color_sources` / `array_candidate_source`.

**Gotchas.**
- `ensure_extractor` returns `None` when the scene only has the shared collector (Phase-2 fallback): it must *not* chain on the shared collector because `id()` would collide across views — it stays on the legacy path instead.
- `IjkGridRep.refresh_primary_visibility` deliberately does **not** Show `rep_data`; calling Show there clobbers the IjkGrid's own `show()` and rasterises the un-cropped full grid — this was the documented *"red SolidColor Z-fight bug"*.
- `ensure_per_view_ijk` has a CRITICAL ordering requirement: it forces `clone.UpdatePipeline()` *before* constructing the `IjkGrid`, because the IjkGrid peeks at the clone's output assembly to pick the output data type (`ExplicitStructuredGrid` vs the `vtkPolyData` placeholder); if the clone hasn't executed, its assembly is empty and every slicer rejects the `vtkPolyData` input.
- `WellboreGeometryRep` matches **both** `'Perfo'` and `'Perforation'`: the runtime kind of a perforation is `'Perforation'` (C++ sets it via `treeViewNodeTypeName`, bypassing `SimplifyXmlTag`), but legacy Python lists carry the abbreviated `'Perfo'` — both are listed so the type resolves explicitly rather than via the fallback. The class docstring also notes a Trajectory creates a companion Wellhead MD label on activation, but that logic lives elsewhere (not in this class).
- `SeismicFrameRep` is honest debt: kept on standard defaults with a `⚠ Behaviour to be confirmed` note pointing at `TYPES_PARTICULARITES`.

---

### `fespp_on_trame/app/core/element_type/frames.py`

**Responsibility.** The wellbore-frame types and their *dual nature*: a **FOLDER** in the tree (tri-state, no own eye, checking selects all children) but a **Representation** in the source layer (owns the clone + render anchor; children render via their own per-(child, view) extractors, so the frame's primary extractor stays hidden — C++ `MapperType::MapperSet`). These classes also own the per-type *child* behaviour (the strategy pattern, Option A).

**Key classes / functions.**
- `class FrameRep(Representation)` — abstract base; subclasses set `_child_store_attr` (the `RepInScene` dict holding child extractors) and `_reg_prefix` (proxy registration prefix). Both default to `None`.
  - Tree/contract overrides: `tree_role()` → `FOLDER`, `is_grouping()` → `True`, `eye_descriptor()` → `None`, `tracking_bucket()` → `None` (the frame is not tracked; its children are), `primary_hidden()` → `True`.
  - `refresh_primary_visibility(self, ris)` — always `pvsimple.Hide` the primary (`ris.source()`); a generic refresh must never Show it, else the C++ side surfaces the frame's first child in every view.
  - `_child_store(self, ris) -> dict` — `getattr(ris, self._child_store_attr)`.
  - `child_source(self, ris, child_path, create=False)` — the per-(child, view) extractor for `child_path`; with `create=True` it is materialised (hidden) if absent and cached in the store, so a COE/stats read of an active-but-not-displayed child still hits a real proxy carrying that child's array.
  - `visible_child_source(self, ris)` — the single child extractor currently SHOWN (`Visibility=1`) in this view (the one visible log of an exclusive frame).
  - `visible_child_displays(self, ris)` — display proxies of *every* shown child (the SolidColor fan-out targets these; the primary stays hidden).
  - `_child_tint(self, ris, child_path, state)` — SolidColor for a freshly-built child; default = the frame's uniform colour `(state.solid_color_by_rep or {}).get(ris.rep_path)`.
  - `_apply_child_z(self, ris, disp, source, zs)` — default: **scale** Z via `disp.Scale = [1.0, 1.0, zs]` (channel = real log-tube geometry following the well).
  - `_create_child_extractor(self, ris, child_path)` — builds a per-(child, view) `EnergisticsExtractor` pointed at a single child (registration `{_reg_prefix}_{_sanitize(child_path)}_v{view_id}`, `ExtractPath` = the child leaf) so only that child surfaces; clone-rooted, hidden in other views, with `Representation` + `_apply_child_z` + `_apply_default_tint(_child_tint(...))` applied in the target view. Returns `None` on Phase-2 fallback or proxy-build failure. **The caller does the Show** in the owning view.
- `class ChannelFrameRep(FrameRep)` — `KINDS = ("Frame",)`, `_child_store_attr = "_channel_extractors"`, `_reg_prefix = "chn"`. Logs — ONE shown at a time; children are `PropertyLeaf` (colourable, array bucket). `visibility_policy()` → `ONE_AT_A_TIME`.
  - `set_child_visible(self, ris, channel_path, visible)` — **EXCLUSIVE.** On show: materialises the channel extractor (`create=True`), then iterates the store and `pvsimple.Hide`s *every other* channel of this frame in the view before `Show`ing this one. On hide: just Hide this channel's extractor.
  - `rendered_sources(self, ris)` / `color_sources(self, ris)` → `[self.visible_child_source(ris)]` if any (only the visible channel's own extractor; primary stays hidden; chain is N/A for logs).
  - `array_candidate_source(self, ris, array_path)` → `self.child_source(ris, array_path, create=True)` — a channel's array lives on the channel's *own* extractor (materialised hidden so COE resolves it even when not displayed), where `array_path` is the channel leaf.
- `class MarkerFrameRep(FrameRep)` — `KINDS = ("MarkerFrame",)`, `_child_store_attr = "_marker_extractors"`, `_reg_prefix = "mrk"`. N markers shown at once; children are `MarkerLeaf` (visibility-only), each independently recolourable. `visibility_policy()` → `MULTI`.
  - `set_child_visible(self, ris, marker_path, visible)` — **MULTI.** Show/hide one marker *without touching its siblings* (no exclusive-hide loop). On show, materialises + stores the extractor if absent, then `Show`s it.
  - `_child_tint(self, ris, marker_path, state)` — per-marker colour first (`state.solid_color_by_marker.get(marker_path)`), falling back to the frame's uniform default, so a marker shown later keeps its own colour.
  - `_apply_child_z(self, ris, disp, source, zs)` — markers **TRANSLATE** Z via `marker_dispatch.apply_marker_z(disp, source, zs)` (keep the sphere round rather than scaling it into an olive).
  - `set_child_color(self, ris, marker_path, color_hex)` — `_apply_default_tint` on one *shown* marker's display (never a ColorArray); a no-op when the marker isn't shown (the persisted `solid_color_by_marker` entry covers the deferred case).

**State (via `ris`).** *Reads:* `ris.scene.pv_view`, `ris.scene.view_id`, `ris.scene.clone`, `ris.scene.collector`, `ris.rep_path`, `ris._current_z_scale()`, `ris.source()`. *Writes:* the child-store dicts `ris._channel_extractors` / `ris._marker_extractors`. *trame `state`:* reads `state.solid_color_by_rep`, `state.solid_color_by_marker`.

**Collaborators.** Local imports: `paraview.simple`, `paraview.servermanager.vtkSMPropertyHelper`, `fespp_on_trame.app.core.sources.representation` (`_sanitize`, `_apply_default_tint`, `_create_plugin_filter_proxy`), `fespp_on_trame.app.core.engine.marker_dispatch` (`apply_marker_z`), `trame.app.get_server`. Entry points via `RepInScene`: `set_channel_visible`/`set_marker_visible` → `set_child_visible`; `channel_source` → `child_source`; `visible_channel_source` → `visible_child_source`; `set_marker_color` → `set_child_color`; `visible_marker_displays` → `visible_child_displays`. `source_resolver` calls `rendered_sources`/`color_sources`/`array_candidate_source`.

**Gotchas.**
- **The whole point of the hierarchy is the `set_child_visible` override boundary** (per the module docstring): the *only* behavioural difference between a log frame and a marker frame — EXCLUSIVE vs MULTI — is this one override; everything else (building a child extractor, listing the shown ones) is shared on `FrameRep`. Change "one log at a time" here and grids/surfaces/markers cannot be affected.
- The secondary fork is `_apply_child_z`: scale (channels) vs translate (markers). If a marker were Z-*scaled* it would stretch into an "olive"; markers are translated instead so the sphere stays round (delegated to `marker_dispatch.apply_marker_z`).
- The frame's PRIMARY extractor is intentionally kept hidden (`primary_hidden()` → True, and `refresh_primary_visibility` always hides). Children render through their own per-(child, view) extractors. Surfacing the primary would make the C++ side show the frame's first child everywhere.
- `_create_child_extractor` does **not** Show the proxy — the caller (`set_child_visible`) does, in the owning view. `child_source(create=True)` materialises *hidden*. This split lets COE/stats resolve an active-but-not-displayed child without making it visible.
- All ParaView/trame/sources imports are local to methods to keep the package a leaf (no import cycle with the source layer, importable without a ParaView runtime for tests).

---

### `fespp_on_trame/app/core/element_type/leaf.py`

**Responsibility.** Leaf element types — sub-elements of a representation, not reps themselves and with no source of their own. A property *colours* its parent rep; a marker toggles ONE marker's visibility.

**Key classes / functions.**
- `class Leaf(ElementType)` — family default `tree_role()` → `LEAF`; `is_selectable()` → `True`; no per-view source.
- `class PropertyLeaf(Leaf)` — `KINDS = ("ContinuousProperty", "DiscreteProperty", "CategoricalProperty", "TimeSeries", "MultiRealization", "MultiRealizationTimeSeries")`. A property that COLOURS its parent rep. Overrides: `eye_descriptor()` → `EYE_ARRAY` (purple), `tracking_bucket()` → `BUCKET_ARRAY`, `color_policy()` → `COLORABLE`, `visibility_policy()` → `NONE` (a property has no visibility of its own — it colours the rep).
- `class MarkerLeaf(Leaf)` — `KINDS = ("Marker",)`. A single WellboreMarker — visibility-only (no colour array, just a SolidColor tint). Overrides: `eye_descriptor()` → `EYE_MARKER` (deep-orange, multi), `tracking_bucket()` → `BUCKET_MARKER`, `color_policy()` → `VISIBILITY_ONLY`, `visibility_policy()` → `NONE` (the marker's show/hide is driven by its parent `MarkerFrameRep` (MULTI)).

**State.** None of its own. Its `tracking_bucket()` value steers which `state.ui_loaded_*` list the node feeds in `data_load.py` (`BUCKET_ARRAY` vs `BUCKET_MARKER`); its `eye_descriptor()` feeds the tree node's eye field.

**Collaborators.** Imports `ElementType` and the enums/descriptors. Queried by `tree.py` (eye), `data_load.py` (`tracking_bucket()` compared to `BUCKET_ARRAY` / `BUCKET_MARKER`), `active_array.py`, `stats_dispatch.py`. A `PropertyLeaf`'s show/colour is actuated *through* its parent frame's `ChannelFrameRep` / through the rep's ColorBy — the leaf carries no source.

**Gotchas.** "Channel-ness" is **structural, not a distinct kind**: a log channel is just a `PropertyLeaf` whose rep ancestor is a `ChannelFrameRep` — there is no `ChannelLeaf` class. Conversely a `MarkerLeaf` is a distinct kind (`'Marker'`) because its colour/visibility policy genuinely differs (`VISIBILITY_ONLY`, deep-orange multi eye). Both leaf subtypes pin `visibility_policy()` to `NONE` because the actuation lives on the parent rep/frame, not on the leaf. Note `PartialType` (in `grouping.py`), *not* `Leaf`, handles a partial property leaf.

---

### `fespp_on_trame/app/core/element_type/registry.py`

**Responsibility.** Build the kind→singleton registry once at import and expose the resolvers: `for_kind` (O(1) dict lookup) and `for_path` (resolve via a tree node's live runtime kind), with a generic standard `Representation` as the unknown/None fallback.

**Key classes / functions.**
- `_CONCRETE` *(module tuple)* — every concrete class, instantiated once each: `Grouping, PartialType, IjkGridRep, GridRep, SurfaceRep, WellboreGeometryRep, SeismicFrameRep, ChannelFrameRep, MarkerFrameRep, PropertyLeaf, MarkerLeaf`. More-specific subclasses (`IjkGridRep`) are listed before their base (`GridRep`) for clarity; kinds never overlap.
- `_REGISTRY` *(module dict)* — built by instantiating each `_CONCRETE` class **once** (the stateless singleton) and registering that singleton under each of its `KINDS`. A duplicate kind raises `RuntimeError("ElementType kind collision: ...")` at import time.
- `_FALLBACK = Representation()` — the singleton returned for an unknown/None kind so callers never crash on an unlisted kind.
- `for_kind(kind)` — returns `_FALLBACK` if `kind` is falsy, else `_REGISTRY.get(kind, _FALLBACK)`.
- `for_path(tree, path)` — `tree.find_node_id(path)` → `tree.find_type(node_id)` → `for_kind(kind)`, wrapped in try/except so an unresolvable path yields `_FALLBACK`. Position-independent (reads the live assembly).
- `registered_kinds()` — `frozenset(_REGISTRY)`; every runtime kind the hierarchy maps (for tests/audits).

**State.** None.

**Collaborators.** Imports the concrete classes from `.representation`, `.grouping`, `.frames`, `.leaf` (and `ElementType` for re-export). `for_path` calls `tree.find_node_id` / `tree.find_type` (the live assembly tree). `for_kind` is the primary entry point used by `tree.py`, `data_load.py`, etc.; `for_path` is used by `RepInScene.element_type` (cached on `ris._element_type_cache`).

**Gotchas.**
- Singletons are created at *import time* — the registry is global process state, so the hierarchy must remain truly stateless (all per-(rep, view) state lives on `ris`); adding instance state to an `ElementType` would silently share it across every rep of that kind.
- The collision check is a hard `RuntimeError` at import: two classes claiming the same `KINDS` string crash the whole app on import — intended as a fail-fast guard while extending the table.
- The ordering of `_CONCRETE` (specific-before-base) is cosmetic — because kinds never overlap, registration order does not affect resolution (unlike a `matches()`-scan approach). `matches()` exists on the base for completeness/tests but is *not* used by the registry, which is a pure dict.
- `for_path`'s try/except → `_FALLBACK` precisely reproduces the old code's `except → False`/standard-rep behaviour, so a not-yet-resolvable path degrades gracefully to a generic standard `Representation` rather than raising.
