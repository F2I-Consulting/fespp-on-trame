# Glossary

Vocabulary used throughout the code and this wiki. Grouped by domain.

## Geoscience / Energistics stack

- **RESQML** — Energistics' XML/HDF5 standard for *reservoir* and subsurface earth models (grids, surfaces, wells, properties). The data this app visualizes.
- **EPC** — *Energistics Packaging Conventions*: a `.epc` ZIP container holding the RESQML XML parts. Bulk numeric arrays usually live in a companion **`.h5`** (HDF5) file.
- **FESAPI** — F2I-Consulting's C++ library to read/write RESQML/EPC/HDF5. FESPP uses it under the hood.
- **FETPAPI** — F2I-Consulting's C++ library for **ETP** (Energistics Transfer Protocol) — streaming RESQML over the network (OSDU/RDDMS).
- **FESPP** — *F2I Energistics Standard ParaView Plugin*. The ParaView C++ plugin this app loads; it turns EPC/ETP data into VTK datasets + a `vtkDataAssembly` tree. Repo: <https://github.com/F2I-Consulting/fespp>.
- **OSDU / RDDMS** — an industry data platform / its reservoir domain store, reachable over ETP. Surfaced in the app via the ETP import path (`ETPConnector`, `ETP12Store`).

## RESQML object kinds (as they appear in the tree)

- **Representation ("rep")** — a renderable RESQML object: an IJK grid, a triangulated/grid2d **surface**, a wellbore **trajectory** (tube), a frame, etc. The unit the UI shows/hides/colours.
- **IjkGrid** — a structured (I×J×K) reservoir grid. Rendered through a dedicated modal pipeline supporting per-axis slicing and a volume crop. See `IjkGrid` in [[Core — Sources|Core-Sources]].
- **WellboreFrame / Channel** — a *frame* along a well; a **channel** is one well **log** (a 1-D property along the trajectory, rendered as a coloured tube). One channel shown at a time (EXCLUSIVE).
- **WellboreMarkerFrame / Marker** — *markers* are picks/points along a well (e.g. formation tops), drawn as a sphere or an oriented disk. Many shown at once (MULTI). They are SYMBOLIC glyphs (see *z-scale* below).
- **Property / PropertyKind** — a numeric attribute on a rep (e.g. porosity). Colourable via a LUT.
- **MR (Multi-Realization)** — a property with several stochastic realizations; the UI lets you pick which realization to display per (view, array). VTK array names are suffixed per realization.
- **TimeSeries (TS)** — a property varying over time; driven by ParaView's TimeKeeper.

## ParaView / VTK

- **pvsimple** — `paraview.simple`, the high-level scripting API (Show/Hide/GetRepresentation/ColorBy…). Used everywhere in the source layer.
- **ServerManager (SM) proxy** — ParaView's wrapper around a VTK object (a source, filter, or representation). `proxy.SMProxy` is the low-level handle; `vtkSMPropertyHelper` sets properties.
- **Source / Filter** — a pipeline producer (e.g. `EPCCollector`) / transformer (e.g. `Threshold`, `Clip`, the FESPP `EnergisticsExtractor`).
- **Representation (display)** — *in ParaView terms*, the object controlling how a source is drawn in a given view (colour, opacity, `Scale`, `Translation`, `Representation` style). Note the name clash with RESQML "representation" — in this wiki "rep" = RESQML object, "display" / "disp" = ParaView representation.
- **RenderView** — a ParaView 3-D view. Each app render panel owns one.
- **LUT (Lookup Table)** — colour map for a scalar array (`GetColorTransferFunction`). **PWF / OTF (Piecewise / Opacity Transfer Function)** — the opacity map (`GetOpacityTransferFunction`). In this app both are **scoped per `(scene, array)`** so views colour independently.
- **ColorBy / COE** — colouring a display by an array / the *Color-Opacity Editor* UI that edits its LUT+PWF.
- **`vtkDataAssembly`** — the hierarchical tree FESPP emits describing all objects; the app mirrors it into `state.ui_subtree_*`. A node's path = the **`rep_path`**.
- **`disp.Scale` vs `disp.Translation`** — display transforms. `Scale=[1,1,zs]` is the standard vertical-exaggeration trick. **In ParaView 5.13+ the display `Position` property was removed and renamed `Translation`** (reading the old name — even via `hasattr` — raises `NotSupportedException`). Markers translate via `Translation`; everything else scales.
- **ExplicitStructuredGrid** — a ParaView plugin (loaded alongside FESPP) providing the crop/slice filters the IJK grid pipeline uses.

## Trame

- **Trame** — Kitware's Python web-app framework (Vue 3 client, websocket server, ParaView/VTK integration).
- **`state`** — the reactive, 2-way-bound variable store shared between Python and the Vue client. `@state.change("var")` reacts to changes.
- **`controller`** — registry of Python callables (`@controller.set("name")`) invokable from Python and from Vue templates.
- **`server.trigger("name")`** — Vue-template-reachable callbacks (a template can call a trigger but not an arbitrary Python function).
- **`server.context`** — a non-reactive side channel for inter-module references (`source_registry`, `scene_registry`, `multi_view`), used to dodge circular imports.
- **dockview** — the JS panel/tab manager behind the multi-view; `ptc` (paraview-trame-components) wraps it as `MultiView`, plus editors like `TransformEditor`, `ColorOpacityEditor`, `RepresentBy`, `TimeControl`.
- **vtk.js push** — `controller.view_update*` sends a fresh rendered frame to a panel's browser canvas. A raw `pvsimple.Render` does *not* push to the client.

## Project-specific terms

- **ViewScene** — one render panel's pipeline root: owns a `vtkEPCCollectorClone` + the panel's `RepInScene` dict + per-`(scene, array)` LUT/PWF. See [[Core — Sources|Core-Sources]].
- **RepInScene (`ris`)** — one `(rep, view)` pair's state holder (extractor, threshold chain, slice/clip, per-view IjkGrid, channel/marker extractors). Delegates per-kind behaviour to its `ElementType`.
- **ElementType** — a stateless strategy *singleton* per RESQML `kind`, encoding behaviour (tree role, eye, visibility policy, how to build sources, how children render). Resolved by `registry.for_kind` / `for_path`. See [[Core — Element Types|Core-Element-Types]].
- **clone** — a `vtkEPCCollectorClone` proxy: a per-view, zero-copy passthrough of the `EPCCollector`, used as the structural anchor each view's extractors chain on. Never rendered itself.
- **EnergisticsExtractor** — the FESPP filter that extracts a single subtree (`ExtractPath = rep_path` or a child leaf) from the clone, so only that object's geometry/array surfaces.
- **SourceRegistry (legacy)** — per-`rep_path` registry (`ExtractBlockRepresentation` / shared `IjkGrid`), view-agnostic. The **Phase-2 fallback** path.
- **SceneRegistry (per-view)** — the live model: one `ViewScene` per panel. Owns per-view extractor creation, coloring replication, IjkGrid sync, marker visibility, view replication.
- **Phase 1/2/3a/3b/4/5** — the staged migration from the legacy per-rep model to the per-view scene model, referenced in docstrings. Current state: non-IJK reps fully per-view (3a); IJK per-view mirrors an authoritative legacy `IjkGrid` (3b); legacy slice/clip/threshold are deprecated fallbacks (4); full legacy removal is the pending Phase 5.
- **Registration-name prefixes** — proxy registration names encode role: `rep_<path>_v<view>` (primary extractor), `chn_<path>_v<view>` (channel), `mrk_<path>_v<view>` (marker). Used e.g. by `is_marker_proxy` to classify a raw display.
- **`ui_scale_z`** — the single global vertical-exaggeration state var (source of truth). Written by the Transformation editor; read by every source-creation hook and the on-load re-apply. Real geometry scales; markers translate. See [[Architecture]].
- **bucket (per-view)** — a `state.*_by_view` dict tracking per-panel sets: loaded reps, hidden reps, coloring, visible markers, active arrays.
- **olive** — the failure mode where a marker sphere stretches into an ellipsoid because its display was *scaled* in Z instead of *translated*. Avoided by `apply_marker_z`.
