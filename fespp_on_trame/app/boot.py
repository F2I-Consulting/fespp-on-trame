"""Engine boot: stand up the ParaView engine and wire the session handlers.

`boot_engine` loads the FESPP plugins, builds the engine objects (tree,
EPC collector, ETP connector, source and scene registries, selector,
activator), seeds the trame state and registers the controller handlers the
widgets call: EPC load and OSDU / ETP connection, tree selection and
progressive reads, picks and cursor readouts, the XML explorer, the per-view
wiring, the analysis panels (statistics, volumetrics, ...) and 3D navigation.

The few pure numpy helpers at module level take no server, so the unit
tests exercise them directly."""
import os
import sys
from pathlib import Path

from paraview import simple as pvsimple

from fespp_on_trame.engine.tree import Tree
from fespp_on_trame.engine.sources.collector import Collector
from fespp_on_trame.engine.sources.etp_connector import ETPConnector
from fespp_on_trame.engine.sources.source_registry import SourceRegistry
from fespp_on_trame.engine.selector import Selector
from fespp_on_trame.engine import node_kinds
from fespp_on_trame.engine import node_facts
from fespp_on_trame.engine import derived_props
from fespp_on_trame.engine import osdu_explorer
from fespp_on_trame.engine import tree_hidden
from fespp_on_trame.engine import compare_matrix, compare_dispatch, compare_tree, stats_supports
from fespp_on_trame.engine.state_defaults import init_state_defaults
from fespp_on_trame.engine.vtk_log import setup_stderr_tee
from fespp_on_trame.engine.plugins import resolve_esg_plugin
from fespp_on_trame.app.views import per_view_state
from fespp_on_trame.engine.wire.render_scheduler import RenderScheduler
from fespp_on_trame.engine.wire.state_batcher import StateBatcher

# The panels' state families, declared once (app/core/state_registry): the
# seeding sites, on_panel_closed and the session read the same lists.
from fespp_on_trame.app.core import state_registry
_COMPARE_DIST_OPTS = state_registry.COMPARE_DIST_OPTS
_COMPARE_PAYLOAD = state_registry.COMPARE_PAYLOAD


# `highlight_where` (the assistant's "light the cells where PHIT > 0.2")
# selects the matches one ParaView id each. A selection of several hundred
# thousand ids holds the single-threaded server for seconds and keeps
# hundreds of MB, and the cost grows with the count. The cap keeps a broad
# threshold on a grid of about a million cells (a third of its cells) in
# reach. Above it nothing is selected: the previous highlight is put out, so
# the reply that says so stays true, and the count is given instead.
HIGHLIGHT_MAX_IDS = 500_000


def highlight_plan(values, ghost, lo, hi, limit=HIGHLIGHT_MAX_IDS):
    """What `highlight_where` lights, from the property's values over the
    node's blocks (global index order): {idx, count, total, valid,
    too_many}. A cell matches when its value is within [lo, hi] (None = an
    open bound); NaN never does, nor a cell its ghost array flags (an
    inactive cell's 0.0 fill). `valid` = the cells that carry a value. Past
    `limit` matches, `idx` is None and `too_many` the limit. Pure numpy: no
    Python loop over the cells."""
    import numpy as np
    v = np.asarray(values, dtype=float)
    ok = ~np.isnan(v)
    if ghost is not None:
        g = np.asarray(ghost)
        ok &= (np.nan_to_num(g, nan=0.0) == 0) if g.dtype.kind == "f" else (g == 0)
    hit = ok.copy()
    if lo is not None:
        hit &= v >= lo
    if hi is not None:
        hit &= v <= hi
    count = int(np.count_nonzero(hit))
    out = {"count": count, "total": int(v.shape[0]), "valid": int(np.count_nonzero(ok)),
           "too_many": 0, "idx": None}
    if count > limit:
        out["too_many"] = int(limit)
    else:
        out["idx"] = np.flatnonzero(hit)
    return out


def well_path_samples(points, step=1.0, cap=20000):
    """Points `step` apart along the polyline `points` ((n, 3)), the last
    one included — where a trajectory is looked up in the grid, cell by
    cell (well_cells_where). At most `cap` of them: the step grows on a
    long path. Pure numpy."""
    import numpy as np
    p = np.asarray(points, dtype=float).reshape(-1, 3)
    if len(p) < 2:
        return p
    seg = np.linalg.norm(np.diff(p, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    length = float(s[-1])
    if length <= 0.0:
        return p[:1]
    step = max(float(step), length / float(cap))
    t = np.append(np.arange(0.0, length, step), length)
    return np.column_stack([np.interp(t, s, p[:, k]) for k in range(3)])


def composite_id_triplets(sizes, flats, indices):
    """GLOBAL indices (cumulative over blocks of `sizes` elements, the Values
    table's index column) as the flat [flat_index, 0, local_id, ...] list a
    composite ID selection takes; a block without a flat index (-1) is
    skipped. One searchsorted per block — `_select_ids` walks every id of
    every block in Python, fine for a page of the Values table."""
    import numpy as np
    idx = np.unique(np.asarray(indices, dtype=np.int64))
    parts, start = [], 0
    for n, flat in zip(sizes, flats):
        end = start + int(n)
        if flat >= 0:
            a, b = np.searchsorted(idx, [start, end])
            if b > a:
                t = np.zeros((b - a, 3), dtype=np.int64)
                t[:, 0] = flat
                t[:, 2] = idx[a:b] - start
                parts.append(t.ravel())
        start = end
    return np.concatenate(parts) if parts else np.zeros(0, dtype=np.int64)


def boot_engine(server, *, fespp_plugin_path):
    """Stand up the engine and return the ParaView render view.

    Four phases: plugins, data structures, selector / activator, state
    defaults; then the handlers. Engine objects are stashed on
    `server.context` for the per-view widgets to reach."""
    state = server.state
    controller = server.controller
    fespp_plugin_path = Path(fespp_plugin_path)

    # --- Phase 1: plugins + render view ---
    pvsimple.LoadPlugin(str(fespp_plugin_path))
    # ExplicitStructuredGrid carries the IJK crop filters. It is looked up
    # under the ParaView install (engine/plugins); the fallback is its place
    # beside a FESPP plugin installed in ParaView's own plugin folder, named
    # with the platform's suffix for a loadable module.
    esg = None
    try:
        esg = resolve_esg_plugin(str(
            fespp_plugin_path.parents[1] / "ExplicitStructuredGrid"
            / ("ExplicitStructuredGrid"
               + (".dll" if sys.platform == "win32" else ".so"))))
        pvsimple.LoadPlugin(esg)
    except Exception as exc:
        # without it every IJK slice fails later, far from the cause
        print(f"[fespp] ExplicitStructuredGrid plugin not loaded ({esg}): {exc}",
              file=sys.stderr, flush=True)
    # Leaf representations instead of ParaView's heavy composite ones on every
    # Show/GetRepresentation (see engine/sources/leaf_rep): a composite
    # representation allocates about a hundred vtkTextMappers per
    # (representation, view), which exhausts memory on a mass load, and
    # sooner with split views. Must run before the first Show.
    from fespp_on_trame.engine.sources import leaf_rep
    leaf_rep.install()

    view = pvsimple.GetActiveViewOrCreate("RenderView")
    # Not `view.Visible = 1`: in ParaView 6.1 `Visible` is the XML label of
    # CameraOrientationWidgetVisibility, which would put the camera
    # orientation widget (the X/Y/Z spheres) in the top right of this first
    # view only. Every view carries the classic orientation axes instead,
    # bottom left, named after the data's CRS (view_manager,
    # `_apply_axes_labels`).
    view.OrientationAxesVisibility = 1
    setup_stderr_tee()

    # --- Phase 2: data structures ---
    tree = Tree(None)
    collector = Collector()
    etp_connector = ETPConnector()
    # The registries chain the per-rep pipelines on whichever source is
    # ACTIVE (EPC collector, or the ETP store once connected), never on the
    # collector alone: a selector built under ETP on a collector-chained
    # extractor crashes in the server-manager assembly domain (see
    # ActiveSource).
    from fespp_on_trame.engine.sources.source_registry import ActiveSource
    active_data_source = ActiveSource(collector, etp_connector)
    source_registry = SourceRegistry(active_data_source, tree)
    # each render view's colour tables and clone (engine/view_resources),
    # made with the view and released with it
    from fespp_on_trame.engine.view_resources import ViewResourcesRegistry
    view_resources = ViewResourcesRegistry(active_data_source)
    server.context.source_registry = source_registry

    # --- Phase 4 (seed state first so Phase 3 reads have defaults) ---
    init_state_defaults(state)

    # Session state seeds. The `*_by_view` buckets are keyed by view_id; the
    # attribute ones are read by the Attributes tool and written by the
    # engine.
    _state_seed = {
        "ui_open_tools_by_view": {},
        "ui_active_node_by_view": {},
        "ui_node_xml_by_view": {},
        "ui_node_values_by_view": {},
        "ui_values_key_by_view": {},
        # the Values card's Copy CSV: the last answer, {vid: {n, name, text}}
        "ui_node_values_csv_by_view": {},
        "ui_color_arrays_by_view": {},
        "ui_active_array_by_view": {},
        "ui_active_colormap_by_view": {},
        "assembly_xml": "",      # the assembly as XML: the tree widget builds the tree from it
        "assembly_rev": 0,        # bumped at every assembly refresh: what the watchers follow
        "lazy_rev": 0,            # bumped when objects a lazy ETP load left on the store were read
        # ui_globe_ok / ui_globe_why: is the globe offered, and why not. Set
        # at load time by _publish_globe_availability; True until proven
        # otherwise, so an empty session does not hide it.
        "ui_has_data": False,   # something imported (EPC or ETP dataspace)
        "ui_welllog_wells": [],  # wellbores sent to the correlation panel
        "ui_globe_ok": True,
        "ui_globe_why": "",
        "selected_paths": [],  # session-global (the loaded set, shared by views)
        "fespp_active_panel_id": "",
        # the render views, {id, title, globe} (view_manager): what a 3D view's
        # statistics rows name, and more than one panel's checklist
        "fespp_render_panels": [],
        "ui_crossplot_panels": [],   # the panel ids of the open cross-plots
        # The Statistics view (singleton, `compare` in the code): one free
        # selection of loaded properties, which survives a close of the view.
        "ui_compare_items": [],      # [{path, real, ts}] in selection order
        # One tab per PWLS kind, each showing at once its matrix, its overlaid
        # distributions and the cross-plot of two of its rows. `ui_compare_tab`
        # is a kind label; what follows up to `ui_compare_dist_opts` is the
        # projection of the current kind's own state (`_compare["kinds"]`):
        # baseline, sort, metrics, distribution options, one set per kind.
        "ui_compare_kinds": [],      # [{kind, count}]
        "ui_compare_tab": "",
        "ui_compare_xplot_axes": {},
        "ui_compare_baseline": "",   # item key, "" = the first item of the kind
        "ui_compare_chips": [],
        "ui_compare_blocks": [],
        "ui_compare_rows": {},
        "ui_compare_annotations": {},
        "ui_compare_deltas": {},      # {key: {metric: {abs, rel}}} to the kind's baseline
        "ui_compare_visible_metrics": list(compare_matrix._METRIC_KEYS),
        "ui_compare_sort_key": "",
        "ui_compare_sort_asc": True,
        "ui_compare_dist_opts": dict(_COMPARE_DIST_OPTS),
        "ui_compare_dist_figure": {"data": [], "layout": {}},
        "ui_compare_dist_meta": {},
        "ui_compare_xplot_note": "",
        "ui_compare_note": "",       # what the panel did not do, said on screen
        "ui_compare_note_severity": "warn",   # "warn" | "error"
        "ui_compare_note_next": "",  # an error's next step, said apart (UI rule R10)
        "ui_compare_tree_xml": "",
        "ui_compare_tree_layout": "kind",
        # the tree's Reservoir / Surface / Well tabs (+ Other while needed)
        "ui_compare_tree_tabs": compare_tree.tree_tabs(""),
        "ui_compare_tree_families": [],
        # the families (Reservoir, Surface, Well) the assembly holds: what a
        # panel's tree toolbar greys (engine/tree_families)
        "ui_tree_families": [],
        "ui_compare_csv": {"name": "", "header": []},   # the Copy CSV's file name + header
        "ui_reconcile": {},          # the Log ↔ Grid table (engine/reconcile_dispatch)
        # the Log ↔ Grid panel's OWN logs (channels ticked in its tree) and
        # what its tree took out of the table (channels, grid properties):
        # out of the table, still loaded
        "ui_reconcile_logs": [],
        "ui_reconcile_dropped": [],
        "ui_health": {},             # the Data health table (engine/health_dispatch)
        "ui_health_focus": {},       # {text, n}: show ONE object in it
        "ui_empty_geometry": {},    # path -> title: every point at one place (empty coordinates from the store)
        "ui_calc_panels": [],        # the (singleton) calculator panel id
        "ui_derived_props": [],      # DerivedStore.publish mirror
        # stratigraphy: the column ranks parsed from the loaded EPCs
        "ui_strati_columns": [],
        # what the loaded data holds, for the top bar's gates
        # (app/features/data_facts, app/views/top_gates)
        "ui_data_facts": {},
        "ui_strati_selected_by_view": {},   # view_id -> uuid of the rank shown
        "ui_strati_note": "",        # why the column is empty, when it is
        "ui_strati_titles": {},      # view_id -> unit title to mark
        "context_action": None,  # {action, path, n} from any render tree's menu
        # A tick — in ANY tree — that asks before reading: {title, body, ok}
        # while it waits, {} the rest of the time. The application layout
        # draws the one box from it (engine/tick_confirm).
        "ui_tick_confirm": {},
        # OSDU / ETP (upload widget "OSDU" tab) — server-driven mirror of the
        # ETP12Store connection lifecycle.
        "etp_connected": False,
        "etp_connecting": False,
        # the step of a connection in progress, on the Connect button
        # ("Requesting new ETP session", "Reading the dataspace list"):
        # "" outside a connection
        "etp_step": "",
        "etp_dataspaces": [],
        # what a session file may keep of an OSDU / ETP connection — the
        # server and the dataspaces read, NEVER the token (it stays in
        # `_etp_creds`, in memory, for the reconnect)
        "ui_etp_endpoint": {},
        "ui_etp_loaded_dataspaces": [],
        "etp_status": "",
        # the dataspace explorer of the OSDU door (engine/osdu_explorer): the
        # server's dataspaces with their dates, sizes and facts, filled by a
        # background scan, and the catalogue search; the widget renders it
        "osdu_explorer": osdu_explorer.empty_state(),
        # Snackbars: amber for selection semantics, red for load errors.
        "empty_color_snackbar_visible": False,
        "empty_color_snackbar_text": "",
        "load_error": "",
        "load_error_visible": False,
        # visible_paths__<vid> / active_path__<vid> / colour_request__<vid>
        # are PER VIEW — seeded via per_view_state.seed in controller.wire_view
        # as each view is created (ui_colormaps is seeded next to its consumer,
        # tools_config._build_attributes).
    }
    for _k, _v in _state_seed.items():
        if getattr(state, _k, None) is None:
            setattr(state, _k, _v)

    # Reuse the app's upload path: importing temp_dir creates the session temp
    # dir (+ cleanup hooks), where the uploads and the debug dumps go;
    # register_upload_route patches aiohttp to serve /upload. Must run before
    # server.start() so the patch is in place.
    from fespp_on_trame.engine.io import temp_dir as _temp_dir
    from fespp_on_trame.engine.io.upload_endpoint import (
        register_upload_route,
        resolve_upload_session_id,
    )
    register_upload_route(server)
    # the document routes beside it (/apply, /state: engine/io/session_endpoint)
    from fespp_on_trame.engine.io import session_endpoint
    session_endpoint.register(server)
    # /export?file=: what the session wrote for the reader (the velocity model's EPC)
    from fespp_on_trame.engine.io import export_endpoint
    export_endpoint.register(server)
    state.upload_session_id = ""
    # Diagnostics: GET /debug/etp dumps the live ETP and pipeline state, so a
    # browser-driven ETP session can be inspected from outside. Registered
    # only under FESPP_DEBUG_ROUTES=1: the route has no authentication.
    from fespp_on_trame.engine.io.etp_debug_endpoint import register_debug_routes
    register_debug_routes(server)

    # In a container (wslink launcher) the client must POST to
    # /api/{sid}/upload: Apache's FallbackResource swallows a bare /upload
    # and answers index.html with a 200, so the upload is silently lost and
    # the tree stays empty. The sid is resolved from proxy-mapping.txt once
    # the port is known.
    @controller.add("on_server_ready")
    def _set_upload_session_id(**_kwargs):
        resolve_upload_session_id(server)

    # a frozen view says where the server was in the session log
    # (engine/loop_watch: the loop held over 1.5 s, its stack)
    @controller.add("on_server_ready")
    def _start_loop_watch(**_kwargs):
        from fespp_on_trame.engine import loop_watch
        loop_watch.start()

    # --- Phase 3: explicit-selection + selector + activator ---
    try:
        from paraview.servermanager import vtkSMPropertyHelper
        cp = collector.get_source().SMProxy
        if cp is not None and cp.GetProperty("ExplicitSelection") is not None:
            vtkSMPropertyHelper(cp, "ExplicitSelection").Set(1)
            cp.UpdateVTKObjects()
    except Exception:
        pass
    selector = Selector(tree)

    # Stash for the per-view widgets.
    ctx = server.context
    ctx.view_resources = view_resources
    ctx.tree = tree
    ctx.collector = collector
    ctx.etp_connector = etp_connector
    ctx.selector = selector
    ctx.render_view = view
    # the session door reads each object's Citation through it (app/session_host)
    ctx.active_data_source = active_data_source

    # --- Render plumbing: one render per dirty view + debounced continuous
    # controls (RenderScheduler / StateBatcher, layer S of
    # doc/dev/TARGET_ARCHITECTURE.md).
    scheduler = RenderScheduler(lambda: getattr(server.context, "multi_view", None))
    ctx.render_scheduler = scheduler
    # load_generation stamps every debounced callback; a new data load
    # increments it so stale callbacks no-op at fire time.
    ctx.load_generation = 0
    batcher = StateBatcher(server, generation=lambda: server.context.load_generation)
    ctx.state_batcher = batcher

    def _active_pdc():
        """The ACTIVE source's collection (the reader's output, or the ETP
        store's once connected) — what the assembly index reads."""
        try:
            return active_data_source.get_source().GetClientSideObject().GetOutputDataObject(0)
        except Exception as exc:
            print(f"[fespp] assembly index: no active collection ({exc})", flush=True)
            return None

    from fespp_on_trame.engine.blockscope.assembly_index import AssemblyIndex
    ctx.assembly_index = AssemblyIndex(_active_pdc)
    ctx.blockscope_scenes = {}  # view_id -> PdcScene

    # the application's events (app/core/lifecycle): a view closing, new
    # data — each family subscribes its own clean-up where it keeps its state
    from fespp_on_trame.app.core.lifecycle import Lifecycle
    lifecycle = Lifecycle()
    ctx.lifecycle = lifecycle
    # one way to tell the reader something (app/core/notifier)
    from fespp_on_trame.app.core.notifier import Notifier
    notifier = Notifier(state)
    ctx.notifier = notifier

    @lifecycle.on("new_data")
    def _new_data_caches():
        """The cell geometry the statistics and the volumetrics weigh with,
        and the Statistics rows, belong to the last file's cells."""
        from fespp_on_trame.engine import cell_weights as _cw
        _cw.clear_geometry()
        compare_dispatch.clear_reads()
        stats_supports.clear_caches()

    @state.change("ui_loaded_rep_paths")
    def _locators_of_what_is_read(ui_loaded_rep_paths=None, **_):
        stats_supports.keep_locators(ui_loaded_rep_paths or ())

    # data_load.run() invokes these engine lifecycle hooks; trame raises on an
    # unregistered controller call, so they are registered as no-ops.
    controller.on_data_loaded = lambda *a, **k: None
    controller.on_active_proxy_change = lambda *a, **k: None

    def _refresh_assembly_xml():
        # The tree widget consumes the EPCCollector's vtkDataAssembly as XML.
        # Serialize the same live assembly that drives tree.set_tree.
        # A new assembly is new data: what was read from the last one goes
        lifecycle.emit("new_data")
        try:
            from paraview.vtk.vtkCommonCore import vtkIndent
            src = active_data_source.get_source()
            # The pipeline OUTPUT is the only surface this class shows to
            # Python: FESPP's readers are ClientServer-wrapped, never
            # Python-wrapped, so GetClientSideObject() degrades them to the
            # wrapped base and GetLiveAssembly / GetAssembly are invisible
            # (see engine/repo_query).
            cso = src.GetClientSideObject()
            asm = None
            if hasattr(cso, "GetOutput"):
                out = cso.GetOutput()
                if hasattr(out, "GetDataAssembly"):
                    asm = out.GetDataAssembly()
            if asm is not None:
                try:
                    state.ui_has_data = asm.GetNumberOfChildren(asm.GetRootNode()) > 0
                except Exception:
                    state.ui_has_data = True
                # The XML is the tree widget's payload (widgets/tree reads
                # assembly_xml and builds the browser tree from it): it stays in
                # the synced state, 2.6 MB for a 4 600-node dataspace. The
                # server-side watchers (health, compare tree, assistant
                # examples) follow the revision counter instead.
                xml = tree_hidden.without_features(
                    asm.SerializeToXML(vtkIndent()), tree_hidden.seismic_features(src))
                _put_assembly(xml)
                state.assembly_rev = int(getattr(state, "assembly_rev", 0) or 0) + 1
                if (os.environ.get("FESPP_DEBUG_ASSEMBLY") or "").strip() == "1":
                    # Debug aid: the assembly the trees are built from, as
                    # XML, overwritten on every refresh. In the process's
                    # temp directory, never beside the package: an image
                    # installs it in site-packages.
                    _dump = os.path.join(_temp_dir.temp_dir, "last_assembly.xml")
                    try:
                        with open(_dump, "w", encoding="utf-8") as _fh:
                            _fh.write(xml)
                        print(f"[fespp] assembly_xml {len(xml)} chars -> {_dump}",
                              file=sys.stderr, flush=True)
                    except Exception as exc:
                        print(f"[fespp] assembly_xml not written to {_dump}: {exc}",
                              file=sys.stderr, flush=True)
        except Exception as exc:
            print("[fespp] assembly_xml error:", exc, flush=True)

    def _put_assembly(xml):
        """The trees' assembly, and the families it holds."""
        from fespp_on_trame.engine import tree_families
        state.assembly_xml = xml
        held = tree_families.present_names(xml)
        if held != (getattr(state, "ui_tree_families", None) or []):
            state.ui_tree_families = held

    def _publish_lazy_read(xml=True):
        """Objects a lazy ETP load left on the store were read: their nodes
        now carry kind, unit, range and component count. `lazy_rev` moves
        the watchers that weigh those (health, the Statistics tree, the
        assistant's catalogue) and, with `xml`, the browser tree gets the
        assembly again (its ×N vector tag). Never `assembly_rev`: that one
        means new data and wipes the Statistics reads and the cell geometry
        (_refresh_assembly_xml)."""
        try:
            if xml:
                from paraview.vtk.vtkCommonCore import vtkIndent
                asm = getattr(tree, "_data_assembly", None)
                if asm is not None:
                    src = active_data_source.get_source()
                    _put_assembly(tree_hidden.without_features(
                        asm.SerializeToXML(vtkIndent()), tree_hidden.seismic_features(src)))
            state.lazy_rev = int(getattr(state, "lazy_rev", 0) or 0) + 1
        except Exception as exc:
            print("[fespp] lazy read: tree publish error:", exc, flush=True)

    # Never overwrite controller.view_update per panel (the single-view trap):
    # frames are pushed per panel through the multi_view's html_view registry.
    def _mv():
        return getattr(server.context, "multi_view", None)

    # ONE derived-property store (engine/derived_props): RECIPES, not data
    _derived_store = derived_props.DerivedStore(server)
    derived_props.set_store(_derived_store)
    ctx.derived_store = _derived_store

    # The representation kinds an isolate can host (engine/node_kinds).
    # IjkGrid brings crops and slicers; the others get the extractor alone
    # and can still be thresholded — the chain never needs a structured
    # grid, only the crops do.
    ISOLATABLE = node_kinds.ISOLATABLE_KINDS

    def _card_qualifies(tool, rep_path):
        """Whether the card `tool` can act on `rep_path`: the Slicers and the
        Thresholds isolate any ISOLATABLE representation (a grid, a
        sub-representation, a surface, a polyline or point set — the
        Geometry slicer in I/J/K on an IJK grid, in X/Y/Z on the others,
        29/10), the Volumetrics cube cells with a volume."""
        nid = tree.find_node_id(rep_path) if rep_path else None
        kind = (tree.find_type(nid) or "") if nid is not None else ""
        if tool in ("slicers", "thresholds"):
            return kind in ISOLATABLE
        if tool == "volumetrics":
            from fespp_on_trame.engine import volumetrics_dispatch as vd
            return vd.is_volume_rep(tree, rep_path)
        return False

    # ONE writer of the active nodes, ONE rule for the card targets
    # (app/scene/activation)
    from fespp_on_trame.app.scene.activation import Activation
    activation = Activation(
        state, rep_path_of=lambda *a, **k: _rep_path_of(*a, **k),
        qualifies=_card_qualifies,
        loaded=lambda: list(state.ui_loaded_rep_paths or []),
        views=lambda: [v for v in list(getattr(ctx, "blockscope_scenes", None) or {})
                       if per_view_state.is_live(v)],
        kind_of=lambda p: node_facts.kind_of(tree, p),
        title_of=lambda p: node_facts.display_title(tree, p, ""))
    ctx.activation = activation

    # ONE writer of the open cards (app/scene/cards)
    from fespp_on_trame.app.scene.cards import Cards
    from fespp_on_trame.app.views.tools_config import MODE_TOOLS as _MODE_TOOLS
    cards = Cards(state, _MODE_TOOLS)
    ctx.cards = cards

    # Per-view memory of the colours the EYE set drove last round
    # (vid -> {selector: eyed array path}): closing the last array eye of a
    # rep clears only those, so a colour picked in the Colormap editor is
    # never wiped.
    _eye_driven_colors = {}
    # ONE writer of the eye sets (app/scene/eyes): the explicit callers apply,
    # the state watcher of each view's tree runs only a set no pass has left;
    # made here, the eye pass (`_eye_pass`, below) called late-bound
    from fespp_on_trame.app.scene.eyes import Eyes
    eyes = Eyes(state, lambda vid, paths: _eye_pass(vid, paths),
                is_live=per_view_state.is_live, skip_echoes=True)
    ctx.eyes = eyes

    # the cells selected in the 3D views and the selection extracts, per
    # view (app/scene/selection)
    from fespp_on_trame.app.scene.selection import Selection
    selection = Selection()
    ctx.selection = selection
    # the panels whose tree follows the one grammar — checkbox = loaded,
    # common to every view; eye = in THIS view (app/scene/panel_trees)
    from fespp_on_trame.app.scene.panel_trees import PanelTrees
    panel_trees = PanelTrees()
    ctx.panel_trees = panel_trees

    # every display a view draws outside its composite, walked by the
    # vertical exaggeration, Represent By and the closing of a view
    # (app/scene/displays.py, slice 2 of the overhaul)
    from fespp_on_trame.app.scene.displays import Displays
    displays = Displays()
    ctx.displays = displays

    # the typed context every feature receives (app/core/context, Q10 A)
    from fespp_on_trame.app.core.context import Core
    core = Core(
        server=server, state=state, controller=controller, ctx=ctx,
        tree=tree, collector=collector, etp_connector=etp_connector,
        active_data_source=active_data_source, source_registry=source_registry,
        view_resources=view_resources,
        selector=selector,
        scheduler=scheduler, batcher=batcher, lifecycle=lifecycle,
        notifier=notifier, eyes=eyes, activation=activation, cards=cards,
        displays=displays, selection=selection, panel_trees=panel_trees,
        derived_store=_derived_store,
        mv=_mv)

    # EPC load (app/features/epc_load)
    from fespp_on_trame.app.features import epc_load as _feature_epc_load
    _feature_epc_load.register(
        core,
        _publish_globe_availability=lambda *a, **k: _publish_globe_availability(*a, **k),
        _refresh_assembly_xml=_refresh_assembly_xml)

    # OSDU / ETP (upload widget "OSDU" tab) (app/features/osdu_etp)
    from fespp_on_trame.app.features import osdu_etp as _feature_osdu_etp
    _conn, _etp_creds, _etp_do_connect, _etp_lost, _lost_next, _plugin_rebinds, _token_expired, _watch_session = _feature_osdu_etp.register(
        core,
        _osdu_list=lambda *a, **k: _osdu_list(*a, **k),
        _say=lambda *a, **k: _say(*a, **k))

    # the stepped read's state (see "a big read goes step by step" below),
    # made here: the dataspace explorer reads it too
    _progressive = {"gen": 0, "stop": False, "stepping": False, "expired": False, "lost": False,
                    "disconnected": False, "per_object": {}}

    # the dataspace explorer (engine/osdu_explorer) (app/features/osdu_explorer)
    from fespp_on_trame.app.features import osdu_explorer as _feature_osdu_explorer
    _expand_blocked_well_trajectories, _osdu_list, _panel_reads, _prev_selected = _feature_osdu_explorer.register(
        core,
        _conn=_conn,
        _etp_creds=_etp_creds,
        _etp_do_connect=_etp_do_connect,
        _etp_lost=_etp_lost,
        _lost_next=_lost_next,
        _plugin_rebinds=_plugin_rebinds,
        _progress=lambda *a, **k: _progress(*a, **k),
        _progressive=_progressive,
        _publish_lazy_read=_publish_lazy_read,
        _token_expired=_token_expired,
        _watch_session=_watch_session)

    # one question before a tick reads a lot (app/features/tick_question)
    from fespp_on_trame.app.features import tick_question as _feature_tick_question
    _apply_selection, _ask, _ask_tick, _drop_tick_question, _tree_tick = _feature_tick_question.register(
        core,
        _expand_blocked_well_trajectories=_expand_blocked_well_trajectories,
        _is_object_path=lambda *a, **k: _is_object_path(*a, **k),
        _is_property_path=lambda *a, **k: _is_property_path(*a, **k),
        _panel_reads=_panel_reads,
        _prev_selected=_prev_selected,
        _say=lambda *a, **k: _say(*a, **k),
        _set_selectors=lambda *a, **k: _set_selectors(*a, **k))

    # a big read goes step by step (engine/progressive_load) (app/features/stepped_read)
    from fespp_on_trame.app.features import stepped_read as _feature_stepped_read
    _is_object_path, _is_property_path, _panel_tick_read, _progress, _set_selectors = _feature_stepped_read.register(
        core,
        _apply_selection=_apply_selection,
        _conn=_conn,
        _etp_creds=_etp_creds,
        _etp_lost=_etp_lost,
        _frame_first=lambda *a, **k: _frame_first(*a, **k),
        _lost_next=_lost_next,
        _prev_selected=_prev_selected,
        _progressive=_progressive,
        _say=lambda *a, **k: _say(*a, **k),
        _token_expired=_token_expired)

    # what the cards say about a tree node (app/features/node_helpers)
    from fespp_on_trame.app.features import node_helpers as _feature_node_helpers
    _block_column, _blocks_for_rep, _display_title, _geometry_columns, _node_blocks, _node_title, _property_label, _property_or_note, _push_active_array_label, _push_card_arrays, _push_grid_targets, _rep_path_of, _say, _set_tool_target, _ticked_arrays, _cell_points, _rep_card_arrays = _feature_node_helpers.register(
        core,
        _derived_array_name=lambda *a, **k: _derived_array_name(*a, **k),
        _is_property_path=_is_property_path,
        _real_idx_for=lambda *a, **k: _real_idx_for(*a, **k))

    # the selection state of a view (app/features/selection_state)
    from fespp_on_trame.app.features import selection_state as _feature_selection_state
    _clear_extract_highlights, _clear_selection_of, _display_xy, _leaf_dataset, _own_selection, _path_for_flat_index, _pick_region, _refresh_values, _selection_ids, _selection_off = _feature_selection_state.register(
        core,
        _publish_sel_counts=lambda *a, **k: _publish_sel_counts(*a, **k))

    # (view, grid) whose Slicers card shows Volume mode with no isolate
    # built yet (app/features/slicers): the per-view wiring arms it too
    _slicer_armed = set()

    # the heavy recomputes run one turn later, behind a busy flag (app/features/heavy)
    from fespp_on_trame.app.features import heavy as _feature_heavy
    _defer, _heavy = _feature_heavy.register(core)

    # a derived property seen in 3D: its eye, its values (app/features/formulas)
    from fespp_on_trame.app.features import formulas as _feature_formulas
    _derived_array_name, _derived_forget, _derived_gc, _derived_resolved, _derived_values, _live_render_vids = _feature_formulas.register(
        core,
        _blocks_for_rep=_blocks_for_rep,
        _nav_note=lambda *a, **k: _nav_note(*a, **k))

    # the session's own objects: selection extracts, derived rows (app/features/session_rows)
    from fespp_on_trame.app.features import session_rows as _feature_session_rows
    _extract_colour, _extract_layout, _extract_seq, _pdc_flats, _publish_sel_counts, _publish_session_rows, _row_of_rep, occupancy = _feature_session_rows.register(
        core,
        _derived_forget=_derived_forget,
        _derived_values=_derived_values,
        _live_render_vids=_live_render_vids,
        _path_for_flat_index=_path_for_flat_index,
        _pv_view_of=lambda *a, **k: _pv_view_of(*a, **k),
        _rep_path_of=_rep_path_of)

    # the selection extracts and their session rows (app/features/extracts)
    from fespp_on_trame.app.features import extracts as _feature_extracts
    _feature_extracts.register(
        core,
        _derived_fanout=lambda *a, **k: _derived_fanout(*a, **k),
        _derived_forget=_derived_forget,
        _display_title=_display_title,
        _extract_cells=lambda *a, **k: _extract_cells(*a, **k),
        _extract_colour=_extract_colour,
        _extract_layout=_extract_layout,
        _extract_seq=_extract_seq,
        _globe_scene=lambda *a, **k: _globe_scene(*a, **k),
        _live_render_vids=_live_render_vids,
        _nav_note=lambda *a, **k: _nav_note(*a, **k),
        _pdc_flats=_pdc_flats,
        _publish_session_rows=_publish_session_rows,
        _push_active_array_label=_push_active_array_label,
        _pv_view_of=lambda *a, **k: _pv_view_of(*a, **k),
        _refresh_calculator=lambda *a, **k: _refresh_calculator(*a, **k),
        _refresh_values=_refresh_values,
        _rep_path_of=_rep_path_of,
        _row_of_rep=_row_of_rep)

    # picking in a 3D view and the picked cell's readout (app/features/picking)
    from fespp_on_trame.app.features import picking as _feature_picking
    _cell_ijk, _cell_value_text, _extract_cells, _ids_to_source, _nothing_under, _surface_fallback, _wellbore_title = _feature_picking.register(
        core,
        _clear_extract_highlights=_clear_extract_highlights,
        _clear_selection_of=_clear_selection_of,
        _cmap_array_path=lambda *a, **k: _cmap_array_path(*a, **k),
        _display_title=_display_title,
        _drop_block_highlight=lambda *a, **k: _drop_block_highlight(*a, **k),
        _globe_scene=lambda *a, **k: _globe_scene(*a, **k),
        _leaf_dataset=_leaf_dataset,
        _locator_for=lambda *a, **k: _locator_for(*a, **k),
        _own_selection=_own_selection,
        _path_for_flat_index=_path_for_flat_index,
        _pdc_flats=_pdc_flats,
        _pick_region=_pick_region,
        _publish_sel_counts=_publish_sel_counts,
        _refresh_values=_refresh_values,
        _rep_path_of=_rep_path_of,
        _selection_ids=_selection_ids)

    # One cell locator per dataset the crosshair may hit, keyed by the (app/features/cursor)
    from fespp_on_trame.app.features import cursor as _feature_cursor
    _cursor_pos, _locator_for = _feature_cursor.register(
        core,
        _cell_ijk=_cell_ijk,
        _cell_value_text=_cell_value_text,
        _display_title=_display_title,
        _display_xy=_display_xy,
        _globe_scene=lambda *a, **k: _globe_scene(*a, **k),
        _rep_path_of=_rep_path_of,
        _wellbore_title=_wellbore_title)

    # ---- The XML explorer (overhaul slice 10: the first feature out of app/boot) (app/features/xml_explorer) ----
    from fespp_on_trame.app.features import xml_explorer as _feature_xml_explorer
    _xml_open_from_path = _feature_xml_explorer.register(core)

    # --- per-view wiring: the view manager calls this for each view it creates.
    # selected_paths (load) is session-global; visibility / active / colour are
    # PER VIEW (state vars suffixed by view_id). The eye watcher itself lives in
    # the DataTree widget (app/views/widgets/data_tree.py) and forwards here.
    # values_highlights (app/features/values_highlights)
    from fespp_on_trame.app.features import values_highlights as _feature_values_highlights
    _record_selection, _select_ids = _feature_values_highlights.register(
        core,
        _block_column=_block_column,
        _blocks_for_rep=_blocks_for_rep,
        _clear_selection_of=_clear_selection_of,
        _derived_array_name=_derived_array_name,
        _drop_block_highlight=lambda *a, **k: _drop_block_highlight(*a, **k),
        _is_property_path=_is_property_path,
        _node_blocks=_node_blocks,
        _own_selection=_own_selection,
        _publish_sel_counts=_publish_sel_counts,
        _real_idx_for=lambda *a, **k: _real_idx_for(*a, **k),
        _rep_path_of=_rep_path_of,
        _say_took=lambda *a, **k: _say_took(*a, **k))
    # the Values card (app/features/values_card)
    from fespp_on_trame.app.features import values_card as _feature_values_card
    _feature_values_card.register(
        core,
        _block_column=_block_column,
        _blocks_for_rep=_blocks_for_rep,
        _cell_points=_cell_points,
        _derived_array_name=_derived_array_name,
        _derived_values=_derived_values,
        _eye_driven_colors=_eye_driven_colors,
        _geometry_columns=_geometry_columns,
        _is_property_path=_is_property_path,
        _node_blocks=_node_blocks,
        _real_idx_for=lambda *a, **k: _real_idx_for(*a, **k),
        _refresh_values=_refresh_values,
        _rep_path_of=_rep_path_of,
        _ticked_arrays=_ticked_arrays,
        _panel_tick_read=_panel_tick_read)
    # its Map: a K layer of an IJK grid, coloured (app/features/values_map)
    from fespp_on_trame.app.features import values_map as _feature_values_map
    _feature_values_map.register(core, _rep_path_of=_rep_path_of, _node_blocks=_node_blocks)
    # an object's solid colour and opacity, in the Colormap card
    # (app/features/object_look)
    from fespp_on_trame.app.features import object_look as _feature_object_look
    _feature_object_look.register(core, _rep_path_of=_rep_path_of)

    def _real_idx_for(vid, array_path):
        """This view's chosen realization for an MR property (Time &
        Realizations card), else the default — the first available
        (engine/view_axes, the one rule)."""
        from fespp_on_trame.engine import view_axes
        return view_axes.real_for(state, tree, vid, array_path)

    # A blocked wellbore and a sub-representation are the same thing seen
    # twice: a SUBSET of this grid's cells. The plugin mirrors the grid's
    # cell arrays onto both (declareSupportingCells /
    # syncCellDataFromSupportingGrid), so both are paintable by a property of
    # the grid. `Sub` is what a SubRepresentation arrives as — the plugin
    # strips the "Representation" suffix from the xml tag.
    _DERIVED_KINDS = ("BlockedWellbore", "Sub", "SubRepresentation")

    def _derived_rep_paths(rep_path):
        """Loaded reps DERIVED from this grid (the blocked wellbores and the
        sub-representations under the same grid container): they carry the
        grid's cell properties, so a property eye paints them too — even with
        the grid itself hidden."""
        head = rep_path.rsplit("/", 1)[0]
        container = head.rsplit("/", 1)[0] if "/" in head else ""
        if "_gridfolder_" not in container.rsplit("/", 1)[-1]:
            return []
        out = []
        for lp in (state.ui_loaded_rep_paths or []):
            if lp == rep_path or not lp.startswith(container + "/"):
                continue
            nid = tree.find_node_id(lp)
            if nid is not None and tree.find_type(nid) in _DERIVED_KINDS:
                out.append(lp)
        return out

    # --- multi-view frame-push fan-out -------------------------------------
    @controller.set("view_update_for")
    def view_update_for(panel_id):
        mv = _mv()
        hv = mv.get_html_view(panel_id) if mv is not None else None
        if hv is not None:
            try:
                hv.update()
            except Exception:
                pass

    @controller.set("view_update_all")
    def view_update_all(*_a, **_k):
        mv = _mv()
        if mv is None:
            return
        for hv in mv.html_views():
            try:
                hv.update()
            except Exception:
                pass

    # engine code calls controller.view_update() generically -> push every view
    controller.view_update = view_update_all

    # the eye pass of one view and its memories (app/features/eye_pass)
    from fespp_on_trame.app.features import eye_pass as _feature_eye_pass
    _eye_pass, on_eye_changed = _feature_eye_pass.register(
        core,
        _codes_mask_sync=lambda *a, **k: _codes_mask_sync(*a, **k),
        _derived_array_name=_derived_array_name,
        _derived_gc=_derived_gc,
        _derived_rep_paths=_derived_rep_paths,
        _derived_resolved=_derived_resolved,
        _extract_colour=_extract_colour,
        _eye_driven_colors=_eye_driven_colors,
        _frame_first=lambda *a, **k: _frame_first(*a, **k),
        _globe_refresh_marks=lambda *a, **k: _globe_refresh_marks(*a, **k),
        _globe_scene=lambda *a, **k: _globe_scene(*a, **k),
        _loaded_content=lambda *a, **k: _loaded_content(*a, **k),
        _property_label=_property_label,
        _publish_session_rows=_publish_session_rows,
        _push_active_array_label=_push_active_array_label,
        _push_colormap_state=lambda *a, **k: _push_colormap_state(*a, **k),
        _push_timereal_state=lambda *a, **k: _push_timereal_state(*a, **k),
        _real_idx_for=_real_idx_for,
        _refresh_values=_refresh_values,
        _rep_path_of=_rep_path_of,
        _settle_isolate=lambda *a, **k: _settle_isolate(*a, **k),
        _sync_isolate_colour=lambda *a, **k: _sync_isolate_colour(*a, **k),
        _sync_panel_tree_eyes=lambda *a, **k: _sync_panel_tree_eyes(*a, **k))

    # Globe views (engine/blockscope/globe_scene.py): the projected CRS of (app/features/globe)
    from fespp_on_trame.app.features import globe as _feature_globe
    _any_usable_crs, _detect_crs, _etp_on, _frame_first, _globe_refresh_marks, _globe_scene, _loaded_content, _publish_globe_availability, _push_globe_state = _feature_globe.register(core)

    # the per-view wiring: wire_view, the scene (the Globe's one turn later), the cards (app/features/view_wiring)
    from fespp_on_trame.app.features import view_wiring as _feature_view_wiring
    _volumetrics_rep, _wired_vids = _feature_view_wiring.register(
        core,
        _apply_cmap_nodes=lambda *a, **k: _apply_cmap_nodes(*a, **k),
        _axes_grid_titles=lambda *a, **k: _axes_grid_titles(*a, **k),
        _cursor_mode_off=lambda *a, **k: _cursor_mode_off(*a, **k),
        _cursor_pos=_cursor_pos,
        _defer=_defer,
        _detect_crs=_detect_crs,
        _push_active_array_label=_push_active_array_label,
        _push_card_arrays=_push_card_arrays,
        _push_colormap_state=lambda *a, **k: _push_colormap_state(*a, **k),
        _push_globe_state=_push_globe_state,
        _push_slicer_state=lambda *a, **k: _push_slicer_state(*a, **k),
        _push_threshold_note=lambda *a, **k: _push_threshold_note(*a, **k),
        _push_threshold_state=lambda *a, **k: _push_threshold_state(*a, **k),
        _push_volumetrics=lambda *a, **k: _push_volumetrics(*a, **k),
        _rep_path_of=_rep_path_of,
        _selection_off=_selection_off,
        _set_tool_target=_set_tool_target,
        _slicer_armed=_slicer_armed,
        _slicer_grid=lambda *a, **k: _slicer_grid(*a, **k),
        _threshold_isolate=lambda *a, **k: _threshold_isolate(*a, **k),
        _threshold_target=lambda *a, **k: _threshold_target(*a, **k))

    # the title bar's hand and mouse (widgets/title3dview) (app/features/title_bar)
    import re as _re
    from fespp_on_trame.app.features import title_bar as _feature_title_bar
    _apply_cmap_nodes, _cmap_apply_range, _cmap_array_path, _cmap_data_range, _cmap_done, _cmap_edges, _cmap_exp, _cmap_pushed, _cmap_target, _cmap_tfs, _cursor_mode_off, _hex, _lut_range, _presets, _push_colormap_state, _table_path, cmap_preset = _feature_title_bar.register(
        core,
        _codes_mask_sync=lambda *a, **k: _codes_mask_sync(*a, **k),
        _eye_driven_colors=_eye_driven_colors,
        _hide_nan_grids=lambda *a, **k: _hide_nan_grids(*a, **k),
        _hide_nan_set=lambda *a, **k: _hide_nan_set(*a, **k),
        _is_property_path=_is_property_path,
        _property_label=_property_label,
        _push_active_array_label=_push_active_array_label,
        _real_idx_for=_real_idx_for,
        _refresh_compare=lambda *a, **k: _refresh_compare(*a, **k),
        _refresh_crossplot=lambda *a, **k: _refresh_crossplot(*a, **k),
        _refresh_welllog=lambda *a, **k: _refresh_welllog(*a, **k),
        _rep_path_of=_rep_path_of,
        _selection_off=_selection_off,
        _set_tool_target=_set_tool_target)

    # the session door (widgets/session, app/session_host) (app/features/colormap_session)
    from fespp_on_trame.app.features import colormap_session as _feature_colormap_session
    _feature_colormap_session.register(
        core,
        _cmap_done=_cmap_done,
        _codes_mask_sync=lambda *a, **k: _codes_mask_sync(*a, **k),
        _cmap_edges=_cmap_edges,
        _cmap_exp=_cmap_exp,
        _cmap_target=_cmap_target,
        _cmap_tfs=_cmap_tfs,
        _hide_nan_set=lambda *a, **k: _hide_nan_set(*a, **k),
        _presets=_presets,
        _push_colormap_state=_push_colormap_state)

    # the Legends card (engine/legends) (app/features/legends_card)
    from fespp_on_trame.app.features import legends_card as _feature_legends_card
    _feature_legends_card.register(
        core,
        _cmap_pushed=_cmap_pushed,
        _cmap_target=_cmap_target,
        _eye_driven_colors=_eye_driven_colors,
        _hex=_hex,
        _lut_range=_lut_range,
        _push_colormap_state=_push_colormap_state)

    # exact colours (the title bar's shading toggle) (app/features/exact_colours)
    from fespp_on_trame.app.features import exact_colours as _feature_exact_colours
    _feature_exact_colours.register(
        core,
        _cmap_apply_range=_cmap_apply_range,
        _cmap_data_range=_cmap_data_range,
        _cmap_done=_cmap_done,
        _cmap_target=_cmap_target,
        _cmap_tfs=_cmap_tfs,
        _re=_re,
        _say=_say,
        _table_path=_table_path,
        cmap_preset=cmap_preset)

    # Per-view TIME + REALIZATION application (app/features/time_realization);
    # the card asking for them is the shared slicer card, wired below
    from fespp_on_trame.app.features import time_realization as _feature_time_realization
    _timereal = _feature_time_realization.register(
        core,
        _eye_driven_colors=_eye_driven_colors,
        _push_colormap_state=_push_colormap_state,
        on_eye_changed=on_eye_changed)
    _push_timereal_state = _timereal["push"]

    # Per-view IJK slicers — a GridIsolate: a per-view IjkGrid (crops (app/features/slicers)
    from fespp_on_trame.app.features import slicers as _feature_slicers
    _codes_mask_sync, _ensure_isolate, _hide_nan_grids, _hide_nan_set, _push_slicer_state, _settle_isolate, _slicer_grid, _sync_isolate_colour, _threshold_isolate, _threshold_target = _feature_slicers.register(
        core,
        ISOLATABLE=ISOLATABLE,
        _globe_scene=_globe_scene,
        _push_grid_targets=_push_grid_targets,
        _slicer_armed=_slicer_armed,
        occupancy=occupancy)

    # Per-view thresholds — the chain lives on the view's GridIsolate (app/features/thresholds)
    from fespp_on_trame.app.features import thresholds as _feature_thresholds
    _push_threshold_note, _push_threshold_state, _say_took = _feature_thresholds.register(
        core,
        _axes_grid_scale=lambda *a, **k: _axes_grid_scale(*a, **k),
        _display_title=_display_title,
        _ensure_isolate=_ensure_isolate,
        _nav_blocked=lambda *a, **k: _nav_blocked(*a, **k),
        _push_grid_targets=_push_grid_targets,
        _pv_view_of=lambda *a, **k: _pv_view_of(*a, **k),
        _rep_path_of=_rep_path_of,
        _settle_isolate=_settle_isolate,
        _threshold_isolate=_threshold_isolate,
        _threshold_target=_threshold_target,
        occupancy=occupancy)
    # the Geometry and the Property slicers: the two cards' rows on the
    # isolate above, one shared widget and player (28/10)
    from fespp_on_trame.app.features import geometry_slicer as _feature_geometry_slicer
    _feature_geometry_slicer.register(core, _blocks_for_rep=_blocks_for_rep,
                                      _ensure_isolate=_ensure_isolate,
                                      _push_slicer_state=_push_slicer_state,
                                      # an object's bounds before any isolate
                                      # (app/features/navigation, wired below)
                                      _rep_bounds=lambda *a, **k: _rep_bounds(*a, **k),
                                      _settle_isolate=_settle_isolate,
                                      _slicer_grid=_slicer_grid)
    from fespp_on_trame.app.features import property_slicer as _feature_property_slicer
    _feature_property_slicer.register(core, _threshold_isolate=_threshold_isolate,
                                      _threshold_target=_threshold_target,
                                      _push_threshold_state=_push_threshold_state,
                                      _push_grid_targets=_push_grid_targets,
                                      _rep_card_arrays=_rep_card_arrays,
                                      _ensure_isolate=_ensure_isolate,
                                      occupancy=occupancy)
    # the Time & Realizations card: the same card on the view's time step,
    # its realizations and its vector components (the PO, 29/10)
    from fespp_on_trame.app.features import timereal_slicer as _feature_timereal_slicer
    _feature_timereal_slicer.register(core, timereal=_timereal, _eye_driven_colors=_eye_driven_colors)
    # their doors: a right-click in the tree or the 3D view (28/10)
    from fespp_on_trame.app.features import slicer_doors as _feature_slicer_doors
    _feature_slicer_doors.register(core, _rep_path_of=_rep_path_of, _rep_card_arrays=_rep_card_arrays)
    # depth or time, per 3D view (28/10)
    # what a property is: the kinds the reader sets (app/features/property_types)
    from fespp_on_trame.app.features import property_types as _feature_property_types
    _feature_property_types.register(core)
    from fespp_on_trame.app.features import view_domain as _feature_view_domain
    _feature_view_domain.register(core, _detect_crs=_detect_crs,
                                  _publish_lazy_read=_publish_lazy_read, occupancy=occupancy, _ask=_ask)

    # the doors of the views, their camera links, the tree's layout (app/features/view_doors)
    from fespp_on_trame.app.features import view_doors as _feature_view_doors
    _feature_view_doors.register(
        core,
        _panel_tick_read=_panel_tick_read,
        _refresh_welllog=lambda *a, **k: _refresh_welllog(*a, **k),
        _xml_open_from_path=_xml_open_from_path)

    # well ↔ model reconciliation by kind (engine/reconcile_dispatch) (app/features/reconcile)
    from fespp_on_trame.app.features import reconcile as _feature_reconcile
    _reconcile_inputs, _refresh_reconcile = _feature_reconcile.register(
        core,
        _defer=_defer,
        _wellbore_of=lambda *a, **k: _wellbore_of(*a, **k))

    # the Log ↔ Grid panel's OWN tree (app/features/reconcile_tree)
    from fespp_on_trame.app.features import reconcile_tree as _feature_reconcile_tree
    _feature_reconcile_tree.register(
        core,
        _display_title=_display_title,
        _is_property_path=_is_property_path,
        _panel_tick_read=_panel_tick_read,
        _reconcile_inputs=_reconcile_inputs,
        _refresh_reconcile=_refresh_reconcile,
        _say=_say,
        _wellbore_of=lambda *a, **k: _wellbore_of(*a, **k))

    # data health (engine/health_dispatch) (app/features/data_health)
    from fespp_on_trame.app.features import data_health as _feature_data_health
    _feature_data_health.register(
        core,
        _defer=_defer,
        _any_usable_crs=_any_usable_crs,
        _display_title=_display_title,
        _node_title=_node_title)

    # volumetrics with fluid contacts (engine/volumetrics_dispatch) (app/features/volumetrics)
    from fespp_on_trame.app.features import volumetrics as _feature_volumetrics
    _push_volumetrics, _refresh_welllog, _volumetrics, _wellbore_of = _feature_volumetrics.register(
        core,
        _defer=_defer,
        _display_title=_display_title,
        _globe_scene=_globe_scene,
        _panel_tick_read=_panel_tick_read,
        _push_card_arrays=_push_card_arrays,
        _pv_view_of=lambda *a, **k: _pv_view_of(*a, **k),
        _refresh_values=_refresh_values,
        _say=_say,
        _set_tool_target=_set_tool_target,
        _volumetrics_rep=_volumetrics_rep)

    # the cross-plot's refresh (app/features/crossplot_charts)
    from fespp_on_trame.app.features import crossplot_charts as _feature_crossplot_charts
    _CROSSPLOT_WATCHED, _crossplot_ys, _drop_block_highlight, _drop_crossplot, _drop_crossplot_figures, _hl_state, _refresh_crossplot, _register_crossplot = _feature_crossplot_charts.register(
        core,
        _blocks_for_rep=_blocks_for_rep,
        _clear_extract_highlights=_clear_extract_highlights,
        _clear_selection_of=_clear_selection_of,
        _defer=_defer,
        _heavy=_heavy,
        _nav_note=lambda *a, **k: _nav_note(*a, **k),
        _own_selection=_own_selection,
        _path_for_flat_index=_path_for_flat_index,
        _publish_sel_counts=_publish_sel_counts,
        _record_selection=_record_selection,
        _refresh_values=_refresh_values,
        _rep_path_of=_rep_path_of,
        _row_of_rep=_row_of_rep,
        _select_ids=_select_ids)

    # derived-property calculator (engine/derived_props) (app/features/calculator)
    from fespp_on_trame.app.features import calculator as _feature_calculator
    _CALC_KEYS, _derived_fanout, _refresh_calculator = _feature_calculator.register(
        core,
        _defer=_defer,
        _crossplot_ys=_crossplot_ys,
        _node_title=_node_title,
        _property_or_note=_property_or_note,
        _rebuild_compare_tree=lambda *a, **k: _rebuild_compare_tree(*a, **k),
        _refresh_crossplot=_refresh_crossplot,
        _say=_say)

    # the time-depth law (app/features/time_depth_law): edited in the
    # Stratigraphy view, kept with the session
    from fespp_on_trame.app.features import time_depth_law as _feature_time_depth_law

    def _loaded_bounds():
        """The bounds of the objects ticked, both domains, or None (the
        cube's automatic zone) — the velocity model's own grid left out, its
        extent being the zone's; `_rep_bounds` is navigation's, made below."""
        import math
        b, got = [math.inf, -math.inf] * 3, False
        model_rows = tuple(ctx.time_depth_tree_rows()) if getattr(ctx, "time_depth_tree_rows", None) else ()
        for rep in list(state.ui_loaded_rep_paths or []):
            if node_facts.is_under(rep, model_rows):
                continue
            rb = _rep_bounds(rep)
            if not rb:
                continue
            got = True
            for n in range(3):
                b[2 * n] = min(b[2 * n], rb[2 * n])
                b[2 * n + 1] = max(b[2 * n + 1], rb[2 * n + 1])
        return b if got else None
    from fespp_on_trame.engine import geo as _geo
    _feature_time_depth_law.register(
        core, _data_bounds=_loaded_bounds, _ask=_ask, _defer=_defer,
        _axes=lambda: _geo.axes_grid_titles(_detect_crs("depth", codeless=True)))
    # the velocity model as a grid of the tree (app/features/time_depth_tree)
    from fespp_on_trame.app.features import time_depth_tree as _feature_time_depth_tree
    _feature_time_depth_tree.register(core)
    # its columns drawn in the views where its card is open
    # (app/features/time_depth_pins)
    from fespp_on_trame.app.features import time_depth_pins as _feature_time_depth_pins
    _feature_time_depth_pins.register(core)
    # the wells in a 3D view: logs as graphs, curves or tubes on their hole,
    # markers, wellhead pictograms (app/features/log_tracks)
    from fespp_on_trame.app.features import log_tracks as _feature_log_tracks
    _feature_log_tracks.register(core)

    # stratigraphy (app/features/stratigraphy)
    from fespp_on_trame.app.features import stratigraphy as _feature_stratigraphy
    _feature_stratigraphy.register(
        core,
        _defer=_defer,
        _etp_on=_etp_on)
    # the facts that gate the top bar's panels (app/features/data_facts)
    from fespp_on_trame.app.features import data_facts as _feature_data_facts
    _feature_data_facts.register(core)

    # 3D navigation (app/features/navigation)
    from fespp_on_trame.app.features import navigation as _feature_navigation
    _axes_grid_scale, _axes_grid_titles, _nav_blocked, _nav_note, _pv_view_of, _rep_bounds = _feature_navigation.register(
        core,
        _blocks_for_rep=_blocks_for_rep,
        _cmap_array_path=_cmap_array_path,
        _derived_fanout=_derived_fanout,
        _display_title=_display_title,
        _globe_scene=_globe_scene,
        _hl_state=_hl_state,
        _ids_to_source=_ids_to_source,
        _is_property_path=_is_property_path,
        _leaf_dataset=_leaf_dataset,
        _nothing_under=_nothing_under,
        _path_for_flat_index=_path_for_flat_index,
        _pick_region=_pick_region,
        _refresh_calculator=_refresh_calculator,
        _rep_path_of=_rep_path_of,
        _row_of_rep=_row_of_rep,
        _selection_ids=_selection_ids,
        _surface_fallback=_surface_fallback,
        _xml_open_from_path=_xml_open_from_path)

    # the Statistics view (engine/compare_dispatch) (app/features/compare)
    from fespp_on_trame.app.features import compare as _feature_compare
    _close_compare_view, _compare, _compare_current_kind, _compare_index, _compare_item_key, _compare_items, _compare_loaded_paths, _compare_names, _compare_note, _compare_parts, _compare_published, _compare_request_load, _compare_resort, _compare_set_axis, _compare_tick_note, _compare_uid, _kind_state, _project_kind_state, _rebuild_compare_tree, _refresh_compare, _refresh_compare_now, _refresh_compare_rows, _set_compare_items, _set_compare_parts, _sync_compare_tree_selection, open_compare = _feature_compare.register(
        core,
        _apply_selection=_apply_selection,
        _defer=_defer,
        _drop_crossplot=_drop_crossplot,
        _drop_crossplot_figures=_drop_crossplot_figures,
        _drop_tick_question=_drop_tick_question,
        _property_label=_property_label,
        _refresh_crossplot=_refresh_crossplot,
        _register_crossplot=_register_crossplot,
        _sync_compare_tree_eyes=lambda *a, **k: _sync_compare_tree_eyes(*a, **k))

    # the session door (app/session_host): Compare keeps a state per kind (app/features/compare_tree)
    from fespp_on_trame.app.features import compare_tree as _feature_compare_tree
    _compare_add, _sync_compare_tree_eyes, _sync_panel_tree_eyes = _feature_compare_tree.register(
        core,
        _tree_tick=_tree_tick,
        _ask_tick=_ask_tick,
        _compare=_compare,
        _compare_current_kind=_compare_current_kind,
        _compare_index=_compare_index,
        _compare_item_key=_compare_item_key,
        _compare_items=_compare_items,
        _compare_loaded_paths=_compare_loaded_paths,
        _compare_names=_compare_names,
        _compare_note=_compare_note,
        _compare_parts=_compare_parts,
        _compare_published=_compare_published,
        _compare_request_load=_compare_request_load,
        _compare_resort=_compare_resort,
        _compare_set_axis=_compare_set_axis,
        _compare_tick_note=_compare_tick_note,
        _compare_uid=_compare_uid,
        _kind_state=_kind_state,
        _project_kind_state=_project_kind_state,
        _rebuild_compare_tree=_rebuild_compare_tree,
        _refresh_compare=_refresh_compare,
        _refresh_compare_now=_refresh_compare_now,
        _set_compare_items=_set_compare_items,
        _set_compare_parts=_set_compare_parts,
        _sync_compare_tree_selection=_sync_compare_tree_selection,
        open_compare=open_compare)

    # what the rows of the Statistics view follow beside its selection
    # (app/features/compare_parts)
    from fespp_on_trame.app.features import compare_parts as _feature_compare_parts
    _feature_compare_parts.register(
        core,
        _compare=_compare,
        _compare_add=_compare_add,
        _compare_parts=_compare_parts,
        _property_or_note=_property_or_note,
        _rebuild_compare_tree=_rebuild_compare_tree,
        _refresh_compare=_refresh_compare,
        _refresh_compare_rows=_refresh_compare_rows,
        _set_compare_parts=_set_compare_parts,
        _sync_compare_tree_selection=_sync_compare_tree_selection)

    # a panel closes; the trees' right-click menu (app/features/panels)
    from fespp_on_trame.app.features import panels as _feature_panels
    _feature_panels.register(
        core,
        _CALC_KEYS=_CALC_KEYS,
        _CROSSPLOT_WATCHED=_CROSSPLOT_WATCHED,
        _clear_selection_of=_clear_selection_of,
        _close_compare_view=_close_compare_view,
        _derived_gc=_derived_gc,
        _drop_block_highlight=_drop_block_highlight,
        _slicer_armed=_slicer_armed,
        _volumetrics=_volumetrics,
        _wired_vids=_wired_vids,
        _xml_open_from_path=_xml_open_from_path)

    # what a load sets off, view by view (app/features/load_reactions)
    from fespp_on_trame.app.features import load_reactions as _feature_load_reactions
    _feature_load_reactions.register(
        core,
        _detect_crs=_detect_crs,
        _frame_first=_frame_first,
        _globe_refresh_marks=_globe_refresh_marks,
        _globe_scene=_globe_scene,
        _panel_reads=_panel_reads,
        _progressive=_progressive,
        _push_globe_state=_push_globe_state,
        _push_slicer_state=_push_slicer_state,
        _push_threshold_state=_push_threshold_state,
        _rep_path_of=_rep_path_of,
        view=view)

    _scenario_path = os.environ.get("FESPP_SCENARIO")
    if _scenario_path:
        # the headless harness's driver lives with the tests
        # (tests/visual/runner/scenario.py, overhaul Q9): test-visual.ps1
        # injects it and names it in FESPP_SCENARIO_RUNNER — the product
        # does not ship it
        import importlib.util as _ilu
        _runner = os.environ.get("FESPP_SCENARIO_RUNNER") or ""
        if not os.path.isfile(_runner):
            print(f"[fespp] FESPP_SCENARIO is set but FESPP_SCENARIO_RUNNER"
                  f" ({_runner!r}) names no scenario driver: nothing runs",
                  flush=True)
            return view
        _spec = _ilu.spec_from_file_location("fespp_scenario", _runner)
        _scenario = _ilu.module_from_spec(_spec)
        sys.modules["fespp_scenario"] = _scenario
        _spec.loader.exec_module(_scenario)

        @controller.add("on_server_ready")
        def _launch_scenario(**kwargs):
            _scenario.schedule(
                server, state, controller, tree, view, _scenario_path,
            )

    return view
