# Architecture

> **Orientation.** `fespp-on-trame` is a [Trame](https://kitware.github.io/trame/) (Vue 3 + websocket) web application that drives ParaView Server in-process. ParaView loads the **FESPP** C++ plugin, which reads RESQML / EPC geoscience data through FESAPI (from a local file, or from an OSDU dataspace over ETP) and emits one partitioned dataset collection plus a `vtkDataAssembly` describing the object tree. On the Python side there are four layers: the **shell and the views** (`fespp_on_trame/__main__.py`, `app/views`), the **session handlers** (`app/boot.py`), the **engine** (`engine/`, stateless modules the handlers call) and the **scene** (`engine/blockscope`, which owns the ParaView proxies). In the browser, every panel and every tool card is a **widget** of its own (`widgets/`), a Vue component bundled once and mounted by a few lines of Python.
>
> The defining decision is the **BlockScope scene model**: ONE partitioned dataset collection (the FESPP collector) shared by the whole session, and ONE composite representation of it per 3D view, driven by a desired-state table. A "rep" is a selector string into the assembly, never a proxy of its own — so a session with a thousand objects still holds one proxy per view. See [[Glossary]] for the vocabulary (rep, rep_path, selector, PdcScene, BlockEntry, isolate, LUT, PWF, collector, IjkGrid, MR, channel, marker).

| Term | One-line meaning |
|---|---|
| **rep / representation** | A renderable RESQML object (grid, surface, well tube, frame). Has geometry, an eye and a colour, per view. |
| **rep_path** | The `vtkDataAssembly` node path of a rep — the identity key for everything below the UI. |
| **selector** | The assembly selector `AssemblyIndex` derives from a rep_path: what the composite representation's `Block*` lists are written in. |
| **PdcScene** | One 3D view's composite representation of the shared collector + its `block_state` table (`engine/blockscope/pdc_scene.py`). |
| **BlockEntry** | One row of that table: visible, colour array, association, label, LUT key, opacity, solid colour, categories. |
| **isolate** | A per-(view, grid) `IjkGrid` pipeline chained on the collector while the Slicers or the Thresholds card cut that grid; the composite swaps the grid's block out meanwhile. |
| **GlobeScene** | A `PdcScene` whose source re-projects the collector onto the Earth (`engine/blockscope/globe_scene.py`). |
| **LUT / PWF** | Colour lookup table / opacity transfer function, scoped per `(array, view)`. |
| **view kind** | What a dockview panel holds: a 3D `render` view, or a session panel (`compare` — the Statistics view —, `welllog`, `xml`, …) — `app/views/views_config.py`. |
| **tool card** | A floating card of a 3D view's toolbar (Data tree, Colormap, Slicers, …) — `app/views/tools_config.py`. |

---

## 1. Big picture

### 1.1 The layers and how they talk

```
                 ┌──────────────────────────────────────────────────────────────────────┐
  BROWSER        │  top bar (Vuetify) · dockview layout · one WIDGET per panel or card   │
  (Vue 3)        │  widgets/<name>/vue-components  +  widgets/_shared (charter components)│
                 └───────────────┬────────────────────────────────┬───────────────────────┘
                                 │ state.* (two-way bind, per-view │ controller.* and
                                 │ vars suffixed `__<view_id>`)    │ server.trigger(...)
                 ┌───────────────▼────────────────────────────────▼───────────────────────┐
  TRAME SERVER   │  __main__.py — the shell (top bar, dockview, snackbars, the one dialog) │
                 │  app/views — MultiView (dockview), RenderPanel → ViewPanel, the mounts  │
                 │  app/boot.py — boot_engine: start-up, then app/features/* registered    │
                 └───────────────┬─────────────────────────────────────────────────────────┘
                                 │ plain function calls
                 ┌───────────────▼─────────────────────────────────────────────────────────┐
  ENGINE         │  engine/*_dispatch.py, tree.py, selector.py, data_load.py, view_resources│
  (stateless)    │  engine/blockscope — PdcScene / GlobeScene / AssemblyIndex (the scene)   │
                 │  engine/sources — collector, ETP connector, IjkGrid, the source registry │
                 │  engine/wire — RenderScheduler, StateBatcher                             │
                 └───────────────┬─────────────────────────────────────────────────────────┘
                                 │ paraview.simple / servermanager
                 ┌───────────────▼─────────────────────────────────────────────────────────┐
  PARAVIEW       │  FESPP plugin: EPCCollector (local), ETP store, EnergisticsExtractor,    │
  + FESPP        │  vtkDataAssembly · one composite vtkSMPVRepresentationProxy per view     │
                 └─────────────────────────────────────────────────────────────────────────┘
```

- **Browser → server.** A widget emits an event; the Python mount binds it to a controller method (`set=(ctrl.crossplot_set, "[$event[0], $event[1], '<pid>']")`) or to a state write (`select="ui_strati_selected = $event"`). Session-wide state (`selected_paths`, `ui_loaded_rep_paths`, `ui_has_data`) is watched with `@state.change`; per-view state lives in vars suffixed by the view id (`active_path__view_3`, `ui_colormap__view_3`) or in dict buckets keyed by it (`ui_open_tools_by_view`).
- **Server → browser.** Handlers write state; the `StateBatcher` (`engine/wire/state_batcher.py`) and trame's flush push it. A 3D frame is pushed per dirty view by the `RenderScheduler` (`engine/wire/render_scheduler.py`): handlers `mark_dirty(view_id)` as they mutate, then one `flush()` renders each dirty view exactly once.
- **Handlers → engine.** `app/boot.py` and the feature modules of `app/features/` own the session (the tree, the collector, the scenes, the per-view state); the engine modules are pure functions over what they are handed (`compare_dispatch.matrix(...)`, `volumetrics_dispatch.payload(...)`) and know nothing of trame. They are documented on [[Engine — Lifecycle and State|Engine-Lifecycle-and-State]] and [[Engine — Dispatchers|Engine-Dispatchers]].
- **Engine → ParaView.** Only the scene layer (`engine/blockscope`, `engine/sources`) touches proxies. A handler never calls `pvsimple.Show` itself.

### 1.2 Entry point and boot

`python -m fespp_on_trame --fespp-plugin-path <Fespp.so> [--local-epc-file-path <x.epc>]` — in the container the launcher runs `pvpython /deploy/fespp_on_trame` with the trame venv made visible by `paraview.web.venv`.

`fespp_on_trame/__main__.py`:
1. **Strict mode first.** `engine/strict.py` is installed before any other import: with `FESPP_STRICT=1` it reports every exception a silent `except` swallows (`[fespp-strict] …` lines), which both test harnesses fail on. Off in production.
2. `boot_engine(server, fespp_plugin_path)` (below).
3. **Widget modules, eagerly.** Every widget module (`trame_fespp_*`, `trame_welllog`, `trame_plotly`, the colour-opacity editor, the Vuetify lab) is `server.enable_module`d before `server.start()`: a panel or a card is built lazily, after the client has mounted, and a module enabled then never reaches the client — its tag renders blank. `_check_widget_bundles` fails the boot on a missing bundle. **Adding a widget means adding it here AND to `setup/apps.yml`** (the `www` bake).
4. **The shell** (`SinglePageLayout`): the F2I theme, the title, the top bar — one button per session panel (`controller.open_render_view`, `open_xml_explorer`, `open_compare`, `open_calculator`, `open_stratigraphy`, `open_welllog`, `open_reconcile`, `open_health`; disabled with a reason until `ui_has_data`), the reload button, the import door (`UploadData`, the `widgets/upload` widget: local EPC / HDF5, or an OSDU dataspace over ETP). The content is `MultiView(server)` plus the two snackbars (`empty_color_snackbar_*`, the session-wide "what no panel is there to carry"; `load_error`), the busy bars, the loading scrim (`ui_loading`) and the ONE confirmation dialog of the application (`ui_tick_confirm`, R7 — a tick that would read more than the click shows asks first).
5. `server.start()`; with `--local-epc-file-path` the file is loaded on `on_server_ready`.

`app/boot.py` → `boot_engine(server, *, fespp_plugin_path)` stands the session up in phases and stashes the engine objects on `server.context` (`ctx`) for the views to reach:

| Phase | What | Where it lands |
|---|---|---|
| 1 | `LoadPlugin(Fespp)`, the optional ExplicitStructuredGrid plugin (`engine/plugins.resolve_esg_plugin`), `leaf_rep.install()` (leaf representations instead of ParaView's composite ones on every `Show` — the per-rep 100-`vtkTextMapper` allocation that OOMed mass loads), the first `RenderView`, the stderr tee (`engine/vtk_log`). | — |
| 2 | `Tree` (the assembly mirror, `engine/tree.py`), `Collector` (the EPC collector), `ETPConnector`, `ActiveSource` (the facade every pipeline chains on — the collector, or the ETP store once connected; `get_display_source()` is the derived-arrays filter over it, §2.1), `SourceRegistry` (§2.3), the `ViewResourcesRegistry` (`engine/view_resources.py`: each 3D view's colour tables, its clone and its render view, made with the view and released with it); with the flag off only, the legacy `SceneRegistry` (§2.3). | `ctx.source_registry`, `ctx.view_resources`, `ctx.scene_registry` (None under BlockScope) |
| 4 (before 3) | `init_state_defaults(state)` (`engine/state_defaults.py`) — every session-wide var with its default, so the phase-3 reads have one. | `state.*` |
| 3 | `Selector` (what a tick means, `engine/selector.py`), the `RenderScheduler` and `StateBatcher`; the `AssemblyIndex` and the empty `blockscope_scenes` map. | `ctx.assembly_index`, `ctx.blockscope_scenes`, `ctx.grid_isolates` |
| handlers | grouped by feature in `app/features/<feature>.py` (45 modules since the overhaul's slice 10): loading (`epc_load`, `osdu_etp`, `osdu_explorer`, `tick_question`, `stepped_read`, `load_reactions`), the views (`view_wiring`, `eye_pass`, `globe`, `navigation`, `view_context_menu`, `title_bar`, `exact_colours`, `time_realization`, `panels`), colour (`colormap_card`, `colormap_edits`, `colormap_session`, `legends_card`), selection (`selection_state`, `picking`, `cursor`, `values_highlights`, `rep_highlight`, `session_rows`, `extracts`), grids (`slicers`, `thresholds`, `volumetrics`), formulas (`formulas`, `calculator`, `calculator_panel`), panels (`view_doors`, `crossplot_charts`, `distribution_controls`, `crossplot_panel`, `compare`, `compare_tree`, `compare_parts`, `reconcile`, `reconcile_tree`, `data_health`, `stratigraphy`, `xml_explorer`), and the shared helpers (`node_helpers`, `heavy`). Each is wired by `register(core, *, <what it calls in other features>)`, its body as it was in `boot_engine`: `core` is the typed context (`app/core/context.Core`, a frozen dataclass of the shared services — the trame server, state and controller, the tree, the sources and registries, the selector, the render scheduler and state batcher, the lifecycle, the notifier, the eyes, the active nodes, the cards, the displays, the selection, the derived store, the multi-view), read at the top of `register` (`state = core.state`); what a feature calls in another one stays an explicit keyword argument, so the order of the registrations in `boot_engine` still says who needs whom. `boot_engine` keeps the start-up phases, makes the shared services and `core`, and calls the registrations in order. | `server.controller`, `server.state` watchers |

The per-view part is entered once per 3D view by `wire_view(vid, pv_view, kind)`: it seeds the view's state (`per_view_state.seed`), makes its `PdcScene`, refreshes its toolbar (`_refresh_view_tools`, the `needs` gates of the tools) and registers the view's watchers (`colour_request__<vid>`, `active_path__<vid>`, the colour-editor vars, the pick events). `on_panel_closed` is the symmetric exit (§3g).

---

## 2. The scene model

### 2.1 BlockScope: one collector, one composite representation per view

The FESPP collector produces ONE partitioned dataset collection for the whole selection (`Selectors` on the source, one `UpdatePipeline`). Each 3D view holds a `PdcScene` (`engine/blockscope/pdc_scene.py`):

```
ctx.blockscope_scenes : {view_id → PdcScene}
        │
        ▼
PdcScene(view_id, pv_view, active_source, scheduler)
   ├─ main_rep     : the ONE composite vtkSMPVRepresentationProxy of the collector in this view
   ├─ block_state  : {selector → BlockEntry}   the desired-state table (pure Python)
   ├─ isolated     : {selector}                blocks handed to a per-view isolate (§2.2)
   └─ reconcile()  : regenerates EVERY Block* list of main_rep from the table, then marks the view dirty
```

**The composite shows the reader's collection through the derived-arrays filter** (`engine/derived_arrays.py`, overhaul slice 4b, decision Q12). `ActiveSource.get_source()` is the READER: selectors, XML and the reader's own data are asked of it. `ActiveSource.get_display_source()` is ONE `ProgrammableFilter` per reader that ShallowCopies the collection and attaches the computed properties as arrays of their grid's blocks (`DerivedArrays.put(name, rep_path, values, assoc)` / `drop(name)`; empty, it is a pass-through). The composite, the per-view clone the isolates chain on, the Globe's projection filter, the selection (ParaView keeps ONE per source: it is set on the filter), the pick id checks, the selection extracts and the colour ranges read the filter. The values are computed by the app (`property_values.values_for`) and only attached: the filter never asks the pipeline for anything while it runs. Its script finds its store by a key, so the sessions of one server process never share computed arrays. A formula's eye is an eye like a property's: its `derived://` path sits in the view's eye set (`app/scene/eyes.py`, the one writer of `visible_paths__<vid>`), the one-colouring-eye-per-grid rule covers it, and the eye pass colours the grid's block by `derived__<name>` (on the Earth too, the Globe's projection filter reading the derived-arrays filter); the grid's isolate and extracts follow the block's colour as for any property, and a session saves the formula's eye with the others.

Every mutator is desired-state first: `set_visible`, `set_color(selector, array, assoc, label, categories, …)`, `set_opacity`, `set_solid_rgb`, `set_isolated` edit the table, then `reconcile()` writes `BlockSelectors`, `BlockColorArrayNames`, `BlockLookupTables`, `BlockOpacities`, … as a projection of the dict — idempotent, so the repair after any structural change (a new load, an ETP reconnect) is the same call. The per-block API lives ONLY on the composite representation (it is the MultiBlock Inspector's mechanism), which is why the one ~13 MB composite per view is accepted: its cost is constant in the number of reps, which is the whole point.

- **Identity.** `AssemblyIndex` (`engine/blockscope/assembly_index.py`) maps a rep_path to the selector the composite understands and back; it is refreshed once per `Selectors` commit (`_on_loaded_reps`).
- **Colour.** PER BLOCK since 2026-09-19: `reconcile()` writes one `BlockColorArrayNames` triplet (selector, association, array) and one `BlockLookupTables` entry per coloured shown block, paired index-wise, plus a global `ColorArrayName` anchor naming any real array (ParaView ignores the triplets without one — Probe Day P1; which array no longer matters). Before that the reconcile painted the global anchor alone, the first coloured block in selector order: with a well loaded, the log channel came first and the grid went white with one bar (the PO's bug of 2026-09-19; the July "8x loss on a grid" was this arrangement misread). One colour bar per table in use (`_sync_scalar_bars`: the first bar at ParaView's lower-right corner, the next ones one corner each — `BAR_CORNERS` — a free `Position` only reaches the widget on a later push, measured); the Colormap card's box hides ONE table's bar (`scene.hidden_bars`, `set_bar_visible(array, on)`); an isolate's `after_show` hook calls `scene.resync_bars()` because ParaView's `Hide` sweeps away the bar of a table no VISIBLE display names globally. The range of a block's array is read on the block's own datasets (`_block_range`, hidden cells skipped as ParaView's data information does), because the composite's information spans every block carrying an array of that name (a log channel's name is shared by the placeholder blocks of the other frames: 0 to 1e-38 on a real curve). One LUT per `(array, view)` (`BlockEntry.lut_key = "array__viewId"`), seeded from ParaView's template and rescaled from the array's range (the union over the blocks it paints; a constant array widened half a unit each side); a discrete or categorical property is painted **by code** (`engine/categorical_palette.py`: an indexed LUT, one colour per code, the codes annotated on the colour bar, a qualitative preset) when the codes fit the rules (`MAX_CATEGORIES`, the index rule), and the card says why when they do not (`categories_note`).
- **Globe.** A `GlobeScene` is a `PdcScene` whose source is a `GeoSource` — one ProgrammableFilter re-projecting the collector to Earth-centred coordinates (`engine/geo.py`, the projected CRS and EPSG code the reader reports or the user types) — plus the textured WGS84 globe, the marks and the framings. It is the scene of the Globe view (kind `globe`, one per session, opened from the top bar beside the 3D view in use with its eyes): built one turn after its view (`view_wiring.globe_build`, behind the view's wait bar), its camera linked to none.
- **Frames and markers.** A log frame shows one channel at a time (exclusive eyes), a marker frame many at once; the rule is decided by the element type of the rep (`engine/element_type`, `VisibilityPolicy`) and applied in `_apply_eye_change`.

### 2.2 Isolates: cutting one grid in one view

The composite cannot crop or threshold one block. When the Slicers or the Thresholds card acts on a grid in a view, boot builds a **GridIsolate** (`engine/sources/grid_isolate.py`, the per-view mode of `IjkGrid` in `engine/sources/ijkgrid.py`: crops, I/J/K cut planes, a threshold chain, its own leaf displays in that view only) chained on the view's clone (`engine/view_resources`) — and the composite swaps the grid's block out (`scene.set_isolated`). Mode `full` releases the isolate and the composite takes the block back. The isolate paints what the composite paints (`_sync_isolate_colour`), so a colour change on the tree reaches both. `ctx.grid_isolates : {(view_id, rep_path) → GridIsolate}`; `_release_isolates(vid)` on close. From outside, an isolate is read through `snapshot()` (its slicing as plain data: mode, extent, single-volume ranges, volumes and their eyes, cuts and their eyes) and its public methods (`set_volume_range`, `apply_*`, `colourable_sources`, `visible_leaf_tips`), never its private fields. The Slicers card sends one gesture at a time (`slicer_edit`: add, remove, show / hide or move ONE cut or box), applied to the isolate's current state, never a whole list rebuilt from its props.

### 2.3 The per-representation model: gone

Until 19/10/2026 a second model existed behind the `FESPP_BLOCKSCOPE` flag: one `ViewScene` per view holding one `RepInScene` per (representation, view), with its own extractor, ColorBy fan-out, slice / clip planes and per-representation visibility. Production ran with the flag on for months; the model was quarantined in `engine/legacy/` (overhaul slice 7), then deleted with the flag (decision Q2 bis, some 8 000 lines). What remains of its data layer serves the composite: `SourceRegistry` keeps one data-only source per representation (the shared `IjkGrid` of a grid — its extent and the values the statistics read — or an `ExtractBlockRepresentation`), never drawn; `engine/view_resources` keeps what a view owns besides its scene; `engine/element_type` keeps the per-kind policies (tree role, eye, one channel at a time on a log frame, colourable or not).

---

### 2.4 One owner per concern (the overhaul of 16-18/10)

Each concern below used to be written from several places that had to agree; it now has ONE owner, and the other places call it. `boot` creates them and stashes them on `ctx`.

| Owner | Owns | Instead of |
|---|---|---|
| `engine/node_facts.py` | what a tree node is: property or not, its representation, its titles, its unit | a dozen copies of the same predicates |
| `engine/blockscope/assembly_index.py` | the reader's assembly: datasets and flat indices of a path, the path of a picked flat index | three walks of the collection, 24 `selector_for(x) or x` |
| `engine/derived_arrays.py` | the computed properties as arrays of their grid's blocks (`ActiveSource.get_display_source()`, §2.1) | a copy of the grid per formula, copies of extracts |
| `app/core/lifecycle.py` | the app's events: `view_closed`, `new_data`, `session_rows` (the rows the session adds to a view's tree), `view_cuts` (what a 3D view draws may have moved: the Statistics view's rows weigh whether it did), with their subscribers | each feature cleaning up (or not) on its own |
| `app/core/notifier.py` | telling the reader: the snackbar (`say`), a view's note line (`note`, `ui_view_note__<vid>`, gone after 8 s), a pick's readout (`readout`, `ui_pick_info__<vid>`) | six hand-pulsed snackbars, notes overwriting the readout |
| `app/core/state_registry.py` | the panels' state families (distribution, cross-plot, calculator, the Statistics view's payload): seeding, teardown, what a session keeps | four tuples in `boot`, two in `session_host` |
| `app/features/session_api.py` + `engine/session_query.py` | the session document as the application's language (2026-10-21): a partial document applied on the live session (`session_apply_doc`), the state as one (`session_state`), the page's query opened at mount (`?epc=`, `?etp=&dataspace=`, `&uuid=`, `?state=`); objects named `uuid:<uuid>` | `widgets/session` (`format.document`, `resolve_uuids`, `open_document`), `session_host.restore` (partial, `reset`), the REST front and the host page to come |
| `app/scene/displays.py` | every display a view draws outside its composite (isolates, extracts, overlay, contact planes, wellheads) and the gestures that walk them (Z, close, Represent By) | five lists walked one by one |
| `app/scene/occupancy.py` | who draws a grid in a view: an extract, its isolate, or the composite; the only writer of `scene.isolated`; tells the selection overlay after each decision | eleven `iso.show()` calls, hidden grids coming back |
| `app/scene/eyes.py` | `visible_paths__<vid>`, formulas included: the eye pass runs once per gesture — the watcher reads the state's set and skips the echo of a pass (W1) | double passes; a formula's own eye store |
| `app/scene/activation.py` | the active node (`active_path__`, `active_by_tab__`) and the one rule for the representation a grid card acts on (`target_of`: Slicers, Thresholds, Volumetrics) | eight writers, three targeting functions |
| `app/scene/selection.py` | the cells selected in the 3D views, per view: the highlighted cells, the Navigation card's pick target, the extract they were picked on, the proxies given a selection, the view owning the source's one selection, the selection extracts (`Selection`, in `core`); the blocks whose ids are POINTS (`points` / `points_of`: a point set, one poly-vertex cell in FESPP, is selected by its points) | eight writers across picking, the Values card, the tree's highlight, the extracts and the panels |
| `app/scene/selection_sources.py` | the ParaView selection of a held one: which blocks are point clouds (`is_point_cloud`), cells and points split (`split`), one composite id source each appended by ParaView's own AppendSelections (`set_on`) | the pick (`picking._with_points` asks the gesture again for points), the tree's unselect, the Values card's highlights |
| `app/scene/cards.py` | `ui_open_tools_by_view` and the selection modes that follow it | nine writers |
| `engine/view_axes.py` | the realization a view shows for a property, the session's time, a view's title | three, two and two copies |
| `engine/ranges.py` | an array's range (hidden cells skipped), the bar's widening of a constant, its distinct values, which elements hold no value (NaN, a log's counted negative zeros) | copies in `PdcScene`, the slider scan, the palette |
| `engine/blockscope/bars.py` | a view's one colour bar among the tables painting it (`ViewBars`, composed by `PdcScene`, which keeps its methods as delegations) | the bar half of `PdcScene` |
| `engine/luts.py` | a view's colour tables and opacity functions (`ViewLuts`) | the LUT half of `ViewScene` |
| `engine/view_resources.py` | what a 3D view owns besides its scene: its tables (`ViewLuts`), its clone, its render view (`get`, `pv_view_of`) | the `ViewScene` of the removed per-representation model, built for every view only to carry them |
| `engine/values.py` | a read at a time step (`TimeScope`) | copies in the statistics and the distribution |
| `engine/stats_supports.py` | a statistic on a PART of a grid — a sub-representation, a blocked wellbore, a selection extract — whose eye is open in the Statistics tree (`ui_compare_parts`): the part mapped once onto its grid's cells (`vtkOriginalCellIds` for an extract, the located centres otherwise), then any property of the grid, a formula included, read on it by indexing the grid's own values and weights; a blocked wellbore counts one value per interval and adds a mean along the hole (`Mean (L)`) | statistics on the whole grid only |
| `engine/compare_rows.py` | the rows of the Statistics view that follow an item: a part's, from its eye, a 3D view's, automatic, while the view cuts or filters the grid; `with_following`, the reads, `cuts_read` (what no state says: did what a view draws move) | none: the old cards read these rows apart from the selection |
| `engine/compare_tree.py` | the docked tree of the Statistics view (`kind_tree_xml`, `tick_plan`, `settle_pending`) | the tree's section of `compare_dispatch` |
| `engine/drawn_cells.py` | what a 3D view draws of a grid, cell by cell, each once: what a view's row reads (`Drawn`, `of_isolate`, `of_scene`, `values`) | a merge of the displays by AppendDatasets |
| `engine/session_older.py` | a session document written with two views for the statistics, in today's words (`current_views`, pure): `kind: stats` is read as the one view | none |
| `engine/sources/chain_domain.py` | a threshold chain entry's domain: its kind, its slider, the NullValue sentinels | the top of `extract_block` (now a data-only extractor) |

What is still to come is in the overhaul's plan (doc/private, slices 7-10): the grid isolate out of `ijkgrid.py` with the plane modules and the threshold chain it still imports, a facade for the gestures the assistant and the session replay, the widgets' shared kit.

## 3. End-to-end flows

### (a) A tick in the tree → load → render

```
tree widget (widgets/tree)  ──►  state.selected_paths                (session-wide)
    @state.change("selected_paths") → _apply_selection(paths)
        app/ui/selection_deps._expand_selection_with_deps   the cascade: a folder takes its
            children, a property pulls its representation, a blocked wellbore pulls its
            trajectory, a removal cascades down, an empty shell is collected
        engine/tick_confirm                                  above MAX_TICK_LOAD unread properties
            → state.ui_tick_confirm → the one dialog → controller.tick_confirm_answer
        Selector → state.fespp_data_selectors
    @state.change("fespp_data_selectors") → engine/data_load.run(...)
        the collector's Selectors + ONE UpdatePipeline; ui_loaded_rep_paths, ui_loaded_array_paths,
        ui_loaded_marker_paths; solid colours reserved per new rep
    @state.change("ui_loaded_rep_paths") → _on_loaded_reps
        AssemblyIndex.refresh(); every PdcScene prunes its table to the loaded set and reconciles;
        a rep loaded by a PANEL's tree (Statistics, the well log, Log <-> Grid) is born with a closed eye
        (`_panel_reads`): read into the panel, shown in no 3D view until an eye is clicked (R4)
    scheduler.flush()
```

`selected_paths` is the ONE selection of the session, and `_apply_selection` keeps the invariant `state.selected_paths == _prev_selected["paths"]` after every call — a panel's tree calls it directly with `push=True` (see [[Engine — Lifecycle and State|Engine-Lifecycle-and-State]], "the selection invariant").

### (b) An eye → show / hide, per view

The eye column of a view's tree is per view. The `DataTree` mount injects `controller.on_eye_changed(vid, paths)`; `_apply_eye_change` turns the eye set into `PdcScene.set_visible` calls (a property eye also colours its rep — the last colouring leaf wins per rep, the exclusive frames close their siblings), reconciles and flushes THAT view. Visibility and colour are orthogonal: hiding a rep never drops its array, and colouring a hidden rep is a legal state.

### (c) Colour

The active property of a view (`active_path__<vid>`) drives the Attributes card ("Colored by"), the Colormap card (`_push_colormap_state → ui_colormap__<vid>`: preset, range, data range, scale, the out-of-range and NaN colours, the codes) and the card frame's target. A colour request (`colour_request__<vid>`, the colour-editor vars) goes to `PdcScene.set_color` → the `(array, view)` LUT; `cmap_*` controllers (`cmap_preset`, `cmap_range`, `cmap_rescale`, `cmap_category_color`, …) edit the LUT and say what they refuse (a preset missing, nothing to rescale) through the card's note.

### (d) Z scale

`ui_scale_z__<vid>` (the slider and the field of the view's title bar, `Title3dView`) → `controller.set_zscale(value, vid)` → that view's `PdcScene` `Scale = [1, 1, z]` (radial on a Globe, inside the projection), its wellheads, its displays (`displays.set_zscale(z, vid)`), its camera and its axes grid's `DataScale`. Per view (the PO, 04/11); `engine/state_defaults.z_scale_of(state, vid)` is the one reader. No view named: every 3D view (a document's session-wide `z_scale`, a script).

### (e) Slicers and thresholds

Both cards act on the view's IJK grid (`_slicer_grid(vid)`: the active grid, else the first loaded one) and name it in their title bar (`_set_tool_target`). `slicer_*` / `threshold_*` controllers build or reuse the view's isolate (§2.2), edit it (`ijkgrid.py` crops and cut planes; `threshold_chain.py` for the chain of unions and intersections), push the card state (`ui_slicers__<vid>`, `ui_thresholds__<vid>`) and flush the view. The Thresholds card says its precondition in its empty state when the active object is not the grid.

### (f) A second 3D view

`controller.open_render_view` → `MultiView.add_view(kind="render")` → a new `RenderView`, a `ViewPanel` (toolbar + cards), then `wire_view` (a fresh `PdcScene`); opened beside a 3D view, it inherits that view's eyes (`controller.inherit_eyes`), takes its camera (`MultiView.copy_camera`) and links the two (`view_link_menu.toggle_link`, symmetric — the Link cameras card lists the other views and `camlink_toggle` refuses a closed one). Every session-wide load appears in every view; visibility, colour, camera, cuts and cards are per view.

### (g) Panels: open, follow, close

A session panel (`views_config.VIEW_KINDS`: `values`, `timedepth`, `welllog`, `reconcile`, `health`, `xml`, `stratigraphy`, `calculator`, `compare` — the Statistics view, one word in the code and another on screen, as `Cube` for the velocity model) is a dockview panel built by its kind's builder — a ~30-line Python mount of one widget (`app/views/<kind>_panel.py`), its data computed by the matching `engine/*_dispatch.py` and pushed as one `ui_<kind>*` payload. Singletons (`welllog`, `reconcile`, `health`, `calculator`, `compare`) reopen in place; multi-instance kinds (`distribution`, `xml`, `stratigraphy`, `crossplot`) take a panel id each. A panel that follows what the reader points at (a Distribution panel) is retitled by `MultiView.retitle`. `on_panel_closed(panel_id)` tears the panel's state down symmetrically — `per_view_state.teardown` for a 3D view (marks it dead first, so the never-unregistered `@state.change` closures early-exit on `is_live`), the per-panel vars and listeners for an analysis panel (`per_view_state.drop_listeners`), the isolates and camera links of a view.

---

## 4. State conventions

- **Session-wide vs per-view.** A var is session-wide when the data is (`selected_paths`, `ui_loaded_*`, `ui_has_data`, `ui_derived_props`, the ETP status). Per-view state is either a **suffixed var** (`<prefix>__<view_id>`: `visible_paths__`, `active_path__`, `ui_scale_z__`, `ui_colormap__`, `ui_slicers__`, `ui_tool_target__`, `ui_nav_axes_grid__`, …) or a **dict bucket** keyed by view id (`ui_open_tools_by_view`, `ui_active_node_by_view`, `ui_card_geometry__`). `app/views/per_view_state.py` is the ONE inventory of both (`SUFFIXED_VARS`, `DICT_BUCKETS`): every per-view key seeded anywhere in boot must be listed there, and the close path stays symmetric for free.
- **Per-panel payloads.** An analysis panel gets its suffixed vars from a key list shared by the seeding site and the teardown (`_DIST_PANEL_KEYS`, `_dist_panel_vars(panel_id)`), and one controller per gesture that names the key (`distribution_set(panel_id, key, value)`, `compare_set(key, value)`, `crossplot_set(key, value, pid)`): the widget names what it wants, the server owns the routing and refuses an unknown key out loud.
- **Controllers vs triggers.** A widget event binds to a `controller.*` method; the few `server.trigger`s serve the client-side helpers (the upload endpoint, the pick events). A coroutine controller is awaited (the ETP connect / select), so a slow connection blocks neither the state nor the other triggers.
- **Nothing silent.** Every refusal, fallback or omission is said where it happens: a per-panel note (`ui_compare_note` + severity + next step, `cmap.note`, `ui_thresholds_note__`), a card's empty state with its why, or the session snackbar (`_say`) when no panel is there to carry it. A handler that catches an exception prints `[fespp] … error:` and leaves the state saying so; the strict reporter and the ratchet test (`tests/unit/test_silent_handlers_ratchet.py`) hold the count of silent handlers from growing.
- **Numbers and files.** One writing rule for a number (`engine/utils/numfmt.py`, mirrored by `widgets/_shared/numfmt.js`: four significant digits, a thin space, an en dash for none) and one CSV layout (`engine/utils/csv_export.py`, `widgets/_shared/csvexport.js`: a dated provenance header the server writes, raw values). The server decides the file name and header (`csv: {name, header}` in every table payload); the widget writes the rows and hands the text over (clipboard, else a download — and says which).

---

## 5. Invariants

1. **One selection, one load.** `selected_paths` is the session's selection; a load is the collector's `Selectors` plus ONE `UpdatePipeline`. A panel's tree reads through the same path (`_apply_selection(..., push=True, shown=False)`).
2. **One composite per view.** No proxy per (rep, view); a rep is a selector string. The exceptions are explicit and refcounted: the isolates (§2.2) and the Globe's own producers.
3. **Desired state first, then reconcile.** Every scene mutation edits `block_state` and calls `reconcile()`; the representation is a projection of the table.
4. **One render per dirty view per handler.** `mark_dirty` while mutating, `flush()` once at the tail; never `pvsimple.Render()` in the middle of a handler.
5. **Symmetric per-view lifecycle.** What `seed` creates, `teardown` removes; what a panel seeds, its close removes; watchers registered per view early-exit on `is_live`.
6. **The widget is the UI.** A panel or a card is a `.vue` in `widgets/<name>`, mounted by a Python file that binds state and controllers and draws nothing itself; no Vuetify in a panel or a card ([[UI — Content|UI-Content]]); the shared components hold the charter's rules ([[UI — Shell, Widgets and Charter|UI-Drawer-Toolbar-Shared]]).
7. **Nothing silent** (§4).
