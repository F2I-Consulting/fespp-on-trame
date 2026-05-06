import contextlib
import os
import re
import sys
import threading
import time

from paraview import simple as pvsimple
from trame_server import Server
from pathlib import Path

from fespp_on_trame.app.core.fespp_tree import Tree
from fespp_on_trame.app.core.sources.ijkgrid import IjkGrid
from fespp_on_trame.app.core.sources.collector import Collector
from fespp_on_trame.app.core.sources.etp_connector import ETPConnector
from fespp_on_trame.app.core.sources.rep_sources import RepSources
from fespp_on_trame.app.core.fespp_selection import Selector
from fespp_on_trame.app.core.color_palette import color_for_index
import fespp_on_trame.app.core.fespp_active as fespp_active
from fespp_on_trame.app.io.drop_files import on_client_connected, on_client_exited
from fespp_on_trame.app.io.upload_endpoint import register_upload_route


# Per-session VTK message capture. VTK/ParaView writes to C-level fd 2
# (stderr) via vtkLogger; we tee that pipe so the reader thread parses
# formatted lines and queues them for the UI log panel, while still
# forwarding raw bytes to docker logs. capture_vtk_messages() slices the
# queue by index so each session only sees its own messages.
_vtk_log_queue: list = []
_vtk_stderr_tee_done = False

# Module-level handle on the Tree built at engine init. Exposed so the
# UI layer (view.py / tree_views.py) can walk the assembly for the
# treeview's dependency-expansion handler.
_tree = None

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[mGKHJA-Z]")
# vtkLogger line format: "(  29.2s) [thread] file.cxx:67  ERR| message"
_VTK_LINE_RE = re.compile(r"\([\d. ]+s\)\s*\[.*?\].*?\b([A-Z]{3,})\|\s*(.*)")


def _setup_stderr_tee() -> None:
    """Tee C-level stderr so VTK output reaches both docker logs and the
    in-memory queue without touching vtkOutputWindow. Must run after
    ParaView is initialised."""
    global _vtk_stderr_tee_done
    if _vtk_stderr_tee_done:
        return
    try:
        read_fd, write_fd = os.pipe()
        orig_fd = os.dup(2)
        os.dup2(write_fd, 2)
        os.close(write_fd)

        def _reader():
            buf = b""
            with os.fdopen(read_fd, "rb", buffering=0) as src, \
                 os.fdopen(orig_fd,  "wb", buffering=0) as dst:
                while True:
                    chunk = src.read(1024)
                    if not chunk:
                        break
                    dst.write(chunk)
                    dst.flush()
                    buf += chunk
                    while b"\n" in buf:
                        raw_line, buf = buf.split(b"\n", 1)
                        line = _ANSI_RE.sub(
                            "", raw_line.decode("utf-8", errors="replace")
                        ).strip()
                        if not line:
                            continue
                        m = _VTK_LINE_RE.search(line)
                        if not m:
                            continue
                        level_tag = m.group(1)
                        text = m.group(2).strip()
                        if not text:
                            continue
                        level = ("error"   if "ERR"  in level_tag else
                                 "warning" if "WARN" in level_tag else
                                 "info")
                        _vtk_log_queue.append({"text": text, "level": level})

        threading.Thread(target=_reader, daemon=True).start()
        _vtk_stderr_tee_done = True
        sys.stdout.write("[VTK log] stderr tee installed\n")
        sys.stdout.flush()
    except Exception as exc:
        sys.stdout.write(f"[VTK log] stderr tee failed: {exc}\n")
        sys.stdout.flush()


@contextlib.contextmanager
def capture_vtk_messages(state, max_messages: int = 500):
    """Capture VTK messages emitted during the block into
    state.vtk_log_messages."""
    start_seq = len(_vtk_log_queue)
    try:
        yield
    finally:
        # Let the reader thread flush the bytes already in the pipe.
        time.sleep(0.05)
        new_messages = list(_vtk_log_queue[start_seq:])
        if new_messages:
            current = list(state.vtk_log_messages or [])
            state.vtk_log_messages = (current + new_messages)[-max_messages:]


def initialize_fespp_engine(
    server: Server, *, fespp_plugin_path: Path
) -> None:
    state = server.state
    controller = server.controller

    # User-facing busy spinner timing — Trame bumps `trame__busy` on every
    # state mutation that triggers a flush, so this logs how long the UI
    # is "blocked" between an interaction and the next idle.
    _busy_start = [None]

    @state.change("trame__busy")
    def _on_trame_busy(trame__busy=None, **_):
        if trame__busy:
            if _busy_start[0] is None:
                _busy_start[0] = time.perf_counter()
        else:
            if _busy_start[0] is not None:
                ms = int((time.perf_counter() - _busy_start[0]) * 1000)
                print(f"[BUSY] {ms}ms")
                _busy_start[0] = None

    pvsimple.LoadPlugin(str(fespp_plugin_path))
    # ExplicitStructuredGrid is needed for IJK volume crop / slicing.
    pvsimple.LoadPlugin('/opt/paraview/lib/paraview-6.0/plugins/ExplicitStructuredGrid/ExplicitStructuredGrid.so')

    _view = pvsimple.GetActiveViewOrCreate("RenderView")
    _view.Visible = 1
    _view.Location = 'Bottom Left'
    _view.OrientationAxesVisibility = 0

    # Run the tee after ParaView init — startup noise would otherwise
    # flood the queue.
    _setup_stderr_tee()

    global _tree
    _tree = Tree(None)

    _collector = Collector()
    _etp_connector = ETPConnector()
    _ijkGrid = IjkGrid(_collector, _tree)

    # Switch the FESPP collector to "explicit selection" mode: a selector
    # path is taken literally for non-grouping nodes (selecting a grid
    # does NOT auto-load its properties). Pairs with `select_strategy=
    # "independent"` in the VTreeview.
    try:
        from paraview.servermanager import vtkSMPropertyHelper
        _coll_proxy = _collector.get_source().SMProxy
        if _coll_proxy is not None and _coll_proxy.GetProperty("ExplicitSelection") is not None:
            vtkSMPropertyHelper(_coll_proxy, "ExplicitSelection").Set(1)
            _coll_proxy.UpdateVTKObjects()
    except Exception as _e:
        print(f"[WARNING] Could not set ExplicitSelection on FESPP collector: {_e}")

    _MODE_NAME_TO_INT = {
        "flat": 0,
        "by_interpretation": 1,
        "by_feature_and_interpretation": 2,
    }

    def _push_tree_hierarchy_mode(mode_name):
        """Push the chosen hierarchy mode to the C++ side. The collector's
        SetTreeHierarchyMode triggers a live rebuild of the assembly via
        repository.rebuildAssembly()."""
        try:
            from paraview.servermanager import vtkSMPropertyHelper
            proxy = _collector.get_source().SMProxy
            if proxy is None or proxy.GetProperty("TreeHierarchyMode") is None:
                return False
            mode_int = _MODE_NAME_TO_INT.get(mode_name, 0)
            vtkSMPropertyHelper(proxy, "TreeHierarchyMode").Set(mode_int)
            proxy.UpdateVTKObjects()
            return True
        except Exception as _e:
            print(f"[WARNING] Could not set TreeHierarchyMode on FESPP collector: {_e}")
            return False

    _push_tree_hierarchy_mode(state.tree_hierarchy_mode)
    _rep_sources = RepSources(_collector, _tree)

    _selector = Selector(_ijkGrid, _tree)
    _activator = fespp_active.Activator(_tree, _rep_sources)

    state.setdefault("ui_select_node_reservoir", [])
    state.setdefault("ui_select_node_surface", [])
    state.setdefault("ui_select_node_well", [])

    state.setdefault("animation_delay", 0.1)

    state.setdefault("fespp_data_selectors", [])

    # ui_loaded_rep_paths: rep paths currently materialised in ParaView
    #   (eye icon rendered next to those tree nodes).
    # ui_hidden_rep_paths: subset whose display.Visibility was toggled
    #   off via the eye. Loaded but not in this set → visible.
    state.setdefault("ui_loaded_rep_paths", [])
    state.setdefault("ui_hidden_rep_paths", [])

    # ui_loaded_array_paths: data-array tree nodes whose data is loaded
    #   (Property/TimeSeries/MultiRealization selectors).
    # ui_active_array_by_rep: at most one entry per rep — the array
    #   currently coloring it. Absent entry → SolidColor.
    state.setdefault("ui_loaded_array_paths", [])
    state.setdefault("ui_active_array_by_rep", {})

    state.setdefault("tree_hierarchy_mode", "flat")

    state.setdefault("etp_dataspaces", [])
    state.setdefault("etp_selected_dataspace", None)

    state.setdefault("has_data_loaded_once", False)

    state.setdefault("view_update", False)
    state.setdefault("view_reset_camera", False)

    state.setdefault("view_loading_message", "Loading... Please wait.")

    state.setdefault("vtk_log_messages", [])
    state.setdefault("vtk_log_visible", False)

    state.setdefault("upload_uploading", False)
    state.setdefault("upload_progress", 0)
    state.setdefault("upload_file_count", 0)
    state.setdefault("upload_file_names", [])
    state.setdefault("upload_debug", "")

    # Filled in on_server_ready once the port is known: each process
    # looks up its own port in proxy-mapping.txt to build /api/{sid}/upload.
    state.setdefault("upload_session_id", "")

    @controller.add("on_server_ready")
    def _set_upload_session_id(**kwargs):
        port = getattr(server, "_running_port", None) or getattr(server, "port", None)
        sid = ""
        try:
            with open("/opt/trame/proxy-mapping.txt") as _f:
                for _ln in _f:
                    parts = _ln.strip().split()
                    if len(parts) == 2 and parts[1].endswith(f":{port}"):
                        sid = parts[0]
                        break
        except Exception:
            pass
        state.upload_session_id = sid
        print(f"[Upload] session_id={sid!r} (port={port})", flush=True)

    state.flush()

    # Register the /upload HTTP route. First try eagerly; if the aiohttp
    # server hasn't been created yet, defer to on_server_ready.
    if not register_upload_route(server):
        @controller.add("on_server_ready")
        def _register_upload_on_ready(**kwargs):
            register_upload_route(server)

    @controller.add("on_data_change")
    def update():
        server.controller.view_update()

    @controller.set("load_epc_file")
    def load_epc_file(epc_file_path: str):
        with capture_vtk_messages(state):
            state.file_loaded = _collector.add_file(epc_file_path)

    @controller.set("connect_to_etp")
    def connect_to_etp(etp_url: str, data_partition: str, token: str, token_type: str = "Bearer",
                       proxy_url: str = None, proxy_token: str = None, proxy_token_type: str = "Bearer"):
        """Connect to an ETP/OSDU server."""
        with capture_vtk_messages(state):
            success = _etp_connector.connect(
                etp_url=etp_url,
                data_partition=data_partition,
                token=token,
                token_type=token_type,
                proxy_url=proxy_url,
                proxy_token=proxy_token,
                proxy_token_type=proxy_token_type
            )

            if success:
                print(f"Connected to ETP server: {etp_url}")
                dataspaces = _etp_connector.get_dataspaces()
                state.etp_dataspaces = dataspaces
            else:
                print(f"Failed to connect to ETP server: {etp_url}")
                state.etp_dataspaces = []

    @controller.set("select_etp_dataspace")
    def select_etp_dataspace(dataspace: str):
        """Pick an ETP dataspace to browse (e.g. "eml:///")."""
        if _etp_connector.is_connected:
            _etp_connector.set_dataspace(dataspace)
        else:
            print("Error: Not connected to ETP server")

    @controller.set("force_etp_refresh")
    def force_etp_refresh():
        """Force-refresh the ETP source's pipeline information."""
        import time
        with capture_vtk_messages(state):
            if _etp_connector.is_connected:
                etp_source = _etp_connector.get_source()
                etp_source.UpdatePipelineInformation()
                time.sleep(0.5)
                etp_source.UpdatePipelineInformation()
                update_data_information()
            else:
                print("Error: Not connected to ETP server")

    @controller.set("update_data_information")
    def update_data_information():
        """Re-parse the live vtkDataAssembly into state.ui_subtree_*."""
        with capture_vtk_messages(state):
            if _etp_connector.is_connected:
                source = _etp_connector.get_source()
            else:
                source = _collector.get_source()

            client_side_object = source.GetClientSideObject()

            # Prefer GetLiveAssembly() — it returns the repository's
            # _output->GetDataAssembly() directly. After rebuildAssembly()
            # (TreeHierarchyMode change) the live assembly is mutated
            # without re-running RequestData, so the pipeline output's
            # deep copy is still the previous one. GetAssembly() exists
            # on the parent class but isn't always exposed to Python
            # through the override; GetLiveAssembly is unique and always
            # wrapped.
            assembly = None
            for getter_name in ("GetLiveAssembly", "GetAssembly"):
                if hasattr(client_side_object, getter_name):
                    try:
                        assembly = getattr(client_side_object, getter_name)()
                        if assembly is not None:
                            break
                    except Exception:
                        assembly = None
            if assembly is None and hasattr(client_side_object, "GetOutput"):
                output = client_side_object.GetOutput()
                if hasattr(output, "GetDataAssembly"):
                    assembly = output.GetDataAssembly()

            if assembly is not None:
                _tree.set_tree(assembly)

    @controller.set("set_slider_value")
    def set_slider_value(index, value):
        """Set the first slice position for the given axis (i, j, or k)."""
        try:
            value = int(value)
            list_var = f"ui_slices_{index}_list"
            current = list(getattr(state, list_var, [0]))
            if current:
                current[0] = value
            else:
                current = [value]
            setattr(state, list_var, current)
        except (ValueError, TypeError):
            pass

    @state.change("fespp_data_selectors")
    def on_change_fespp_data_selectors( **kwargs):
        with capture_vtk_messages(state):
            _on_change_fespp_data_selectors_impl()

    def _on_change_fespp_data_selectors_impl():
        """Driver of the load-time pipeline. Pushes selectors to the
        collector, syncs per-rep extracts, refreshes visibility / coloring
        tracking, runs the active handlers, and renders once at the end."""
        import time as _time
        _t_total_start = _time.perf_counter()
        def _ms(t0):
            return int((_time.perf_counter() - t0) * 1000)
        print("FESPP data selectors changed:", state.fespp_data_selectors)
        if _etp_connector.is_connected:
            active_source = _etp_connector
        else:
            active_source = _collector

        if active_source is None:
            return

        # SetPropertyWithName triggers ClearSelectors + AddSelector × N
        # on the C++ side; both are Modified()-only (no per-call Update())
        # to avoid N full pipeline executions per add. We trigger the
        # actual RequestData ONCE here so downstream code (set_node_id,
        # _rep_sources.sync) sees the freshly-loaded multiblock output.
        _t = _time.perf_counter()
        active_source.get_source().SetPropertyWithName('Selectors', state.fespp_data_selectors)
        active_source.get_source().UpdatePipeline()
        active_source.show()
        print(f"[PERF py] SetSelectors+UpdatePipeline+show: {_ms(_t)}ms")

        # Hide the parent multiblock representation BEFORE any render.
        # Each loaded rep is rendered through its own ExtractBlock proxy
        # below; leaving the parent visible would cause a Render() that
        # processes all N blocks via the parent rep, scaling O(N) per
        # add (~1100ms per extra grid in the original code).
        _t = _time.perf_counter()
        representation = active_source.get_representation()
        representation.Assembly='Assembly'
        representation.BlockSelectors = ['/data']
        representation.Visibility = 0
        print(f"[PERF py] representation.Assembly+BlockSelectors+Visibility=0: {_ms(_t)}ms")

        _t = _time.perf_counter()
        if len(state.ui_select_node_reservoir) > 0:
            for reservoir_node_id in state.ui_select_node_reservoir:
                if _tree.find_parent_node_id_with_type(reservoir_node_id, 'IjkGrid') is not None:
                    try:
                        _ijkGrid.set_node_id(reservoir_node_id)
                    except Exception as e:
                        import traceback
                        print(f"[WARNING] _ijkGrid.set_node_id failed: {e}")
                        traceback.print_exc()
                    break
        _ijkGrid.update_block_visibility()
        print(f"[PERF py] ijkGrid handling: {_ms(_t)}ms")

        # Reserve a distinct chip color for every newly-loaded rep.
        # Cache (selector → rep_path) to avoid re-walking the tree each
        # call. Done BEFORE _rep_sources.sync so newly created
        # TrivialProducers can read their assigned color from
        # solid_color_by_rep and tint their display straight away.
        _t = _time.perf_counter()
        sel_cache = dict(getattr(state, "_selector_rep_cache", {}) or {})
        colors = dict(state.solid_color_by_rep or {})
        next_idx = int(state.solid_color_next_idx or 0)
        for sel in state.fespp_data_selectors or []:
            cached = sel_cache.get(sel)
            if cached is None:
                n_id = _tree.find_node_id(sel)
                if n_id is None:
                    sel_cache[sel] = None
                    continue
                r_id = _tree.find_representation_node(n_id)
                if r_id is None:
                    sel_cache[sel] = None
                    continue
                r_path = _tree.find_path(r_id)
                sel_cache[sel] = r_path
            else:
                r_path = cached
            if not r_path or r_path in colors:
                continue
            colors[r_path] = color_for_index(next_idx)
            next_idx += 1
        state._selector_rep_cache = sel_cache
        state.solid_color_by_rep = colors
        state.solid_color_next_idx = next_idx
        print(f"[PERF py] color assignment loop: {_ms(_t)}ms")

        _t = _time.perf_counter()
        _rep_sources.sync(state.fespp_data_selectors)
        # The C++ side modifies partition data in place (addDataArray for
        # new property selectors, array swap for realization/time changes).
        # TrivialProducers cache their data information at the proxy
        # level — without a Modified() bump, GetCellDataInformation
        # returns a stale array list and the active handler can't find
        # a freshly-added property like "SOIL".
        for src in _rep_sources.all_sources():
            try:
                src.GetClientSideObject().Modified()
                src.UpdatePipelineInformation()
            except Exception:
                pass
        # IjkGrid's rep_data filter is created by SetExtractRepPath
        # inside IjkGrid.set_node_id, so it isn't tracked by _rep_sources.
        # Bump it (and the chained slicers) only when the IJK grid is in
        # the current selection — otherwise we'd poke at stale references
        # of the previous IJK grid's filter, which can hang or error.
        # UpdatePipelineInformation is cheap (REQUEST_INFO only); the
        # actual RequestData happens lazily on the next render.
        _t_ijk = _time.perf_counter()
        ijk_extract = getattr(_ijkGrid, '_src_extract_init', None)
        ijk_node_id = getattr(_ijkGrid, '_node_id', None)
        ijk_path = _tree.find_path(ijk_node_id) if ijk_node_id else None
        ijk_in_selection = bool(
            ijk_path
            and any(s == ijk_path or s.startswith(ijk_path + '/') for s in (state.fespp_data_selectors or []))
        )
        if ijk_extract is not None and ijk_in_selection:
            try:
                ijk_extract.GetClientSideObject().Modified()
                ijk_extract.UpdatePipelineInformation()
            except Exception:
                pass
            try:
                slicer_sources = list(_ijkGrid._all_slice_sources())
                if _ijkGrid._src_slicer_volume is not None:
                    slicer_sources.append(_ijkGrid._src_slicer_volume)
                for slc in slicer_sources:
                    try:
                        slc.GetClientSideObject().Modified()
                        slc.UpdatePipelineInformation()
                    except Exception:
                        pass
            except Exception:
                pass
        print(f"[PERF py] ijk bumps: {_ms(_t_ijk)}ms (in_selection={ijk_in_selection})")
        print(f"[PERF py] _rep_sources.sync: {_ms(_t)}ms")

        # Tell the activator which reps are still actively displayed so
        # it hides stale color bars (e.g. switching between two IJK
        # grids — without this, the previous grid's color bar stays
        # alongside the new grid's bar).
        present_paths = set(p for p, _ in _rep_sources.items())
        if ijk_in_selection and ijk_path:
            present_paths.add(ijk_path)
        if _activator is not None:
            try:
                _activator.notify_active_reps(present_paths)
            except Exception as _e:
                print(f"[WARNING] notify_active_reps failed: {_e}")

        # Visibility tracking: newly-loaded reps default to visible (eye
        # open); reps that were hidden but stayed loaded keep their
        # hidden state; reps no longer present are dropped from the
        # hidden set so they don't ghost-hide on a future re-load.
        loaded_sorted = sorted(present_paths)
        if list(state.ui_loaded_rep_paths or []) != loaded_sorted:
            state.ui_loaded_rep_paths = loaded_sorted
        prev_hidden = list(state.ui_hidden_rep_paths or [])
        kept_hidden = [p for p in prev_hidden if p in present_paths]
        if kept_hidden != prev_hidden:
            state.ui_hidden_rep_paths = kept_hidden

        # DataArray tracking — the "last added per rep" becomes the
        # active eye by default, mirroring the C++ side which colors by
        # the last array added to the rep.
        DATA_ARRAY_KINDS = {
            "ContinuousProperty", "DiscreteProperty", "CategoricalProperty",
            "TimeSeries", "MultiRealization", "MultiRealizationTimeSeries",
        }
        prev_loaded_arrays = list(state.ui_loaded_array_paths or [])
        prev_loaded_set = set(prev_loaded_arrays)
        loaded_arrays = []
        loaded_arrays_set = set()
        last_array_for_rep = {}
        for sel in state.fespp_data_selectors or []:
            n_id = _tree.find_node_id(sel)
            if n_id is None:
                continue
            kind = _tree.find_type(n_id) or ""
            if kind not in DATA_ARRAY_KINDS:
                continue
            r_id = _tree.find_representation_node(n_id)
            r_path = _tree.find_path(r_id) if r_id is not None else None
            if not r_path or r_path not in present_paths:
                continue
            if sel not in loaded_arrays_set:
                loaded_arrays.append(sel)
                loaded_arrays_set.add(sel)
            last_array_for_rep[r_path] = sel
        if loaded_arrays != prev_loaded_arrays:
            state.ui_loaded_array_paths = loaded_arrays
        # Active map: keep the prior choice if its array is still loaded;
        # for reps that just got a newly-added array, switch to the new
        # one (the eye follows the last load).
        prev_active = dict(state.ui_active_array_by_rep or {})
        new_active = {}
        for r_path in present_paths:
            prev_arr = prev_active.get(r_path)
            last_arr = last_array_for_rep.get(r_path)
            newly_added = last_arr is not None and last_arr not in prev_loaded_set
            if newly_added:
                new_active[r_path] = last_arr
            elif prev_arr in loaded_arrays_set:
                new_active[r_path] = prev_arr
            elif last_arr is not None:
                new_active[r_path] = last_arr
            # else: no array on this rep → SolidColor (omit entry).
        if new_active != prev_active:
            state.ui_active_array_by_rep = new_active

        controller.view_replace
        state.view_update = True

        # Set the FESPP source as active for ParaView dialogs that look
        # at it. We do NOT call active_source.show() here — that would
        # re-set the parent rep's Visibility to 1 and undo the early
        # hide above.
        _t = _time.perf_counter()
        pvsimple.SetActiveSource(active_source.get_source())
        server.controller.on_data_loaded()
        server.controller.on_active_proxy_change()
        print(f"[PERF py] setActive+notify: {_ms(_t)}ms")

        if (not state.has_data_loaded_once) and (len(state.fespp_data_selectors) > 0):
            state.view_reset_camera = True
            state.has_data_loaded_once = True

        # Re-run the active handlers AFTER the load+sync so newly-loaded
        # reps get their ColorBy / TimeControl wiring even when their
        # @state.change active handler fired before this load handler
        # (handler ordering between ui_select_node_* and ui_active_node_*
        # is not guaranteed). Idempotent: a no-op if the active handler
        # already ran successfully.
        if _activator is not None:
            _activator.refresh_active()

        # Single Render at the very end. The parent multiblock was hidden
        # earlier, so this only paints the new ExtractBlock reps + IJK
        # slicers.
        _t = _time.perf_counter()
        state.view_update = True
        pvsimple.Render(view=_view)
        print(f"[PERF py] final Render: {_ms(_t)}ms")
        print(f"[PERF py] >>> TOTAL on_change_fespp_data_selectors: {_ms(_t_total_start)}ms <<<")

    state.setdefault("ui_scale_z", 1.0)

    @state.change("ui_scale_z")
    def ui_scale_z_update(ui_scale_z, **kwargs):
        """Broadcast the global vertical exaggeration to every extracted
        rep source and to IjkGrid slicer sources."""
        try:
            zscale = float(ui_scale_z or 1.0)
        except (TypeError, ValueError):
            zscale = 1.0
        _rep_sources.apply_z_scale(zscale)
        ijk_srcs = list(_ijkGrid._all_slice_sources())
        if _ijkGrid._src_slicer_volume is not None:
            ijk_srcs.append(_ijkGrid._src_slicer_volume)
        for src in ijk_srcs:
            rep = pvsimple.GetRepresentation(proxy=src, view=_view)
            if rep is not None:
                rep.Scale = [1.0, 1.0, zscale]
        pvsimple.Render(view=_view)
        controller.view_update()

    @controller.set("get_rep_source")
    def get_rep_source(rep_path):
        """Resolve a rep path to its extracted ParaView source. Used by
        UI panels (SolidColorPanel, ColorEditor)."""
        return _rep_sources.get(rep_path)

    def _sources_for_rep_path(rep_path):
        """Return every (sources, view) pair that renders the given rep.
        Non-IjkGrid: a single ExtractBlock from _rep_sources. IjkGrid:
        the rep_data filter named "rep<sanitized_path>" plus slicers /
        volume tied to the *currently active* IJK grid."""
        view = pvsimple.GetActiveView()
        if view is None:
            return [], None
        out = []
        src = _rep_sources.get(rep_path)
        if src is not None:
            out.append(src)
            return out, view
        expected_rep_filter = "rep" + (rep_path or "").replace('/', '_')
        ijk_node_id = getattr(_ijkGrid, '_node_id', None)
        ijk_path = _tree.find_path(ijk_node_id) if ijk_node_id else None
        is_active_ijk = (ijk_path == rep_path)
        for sid, s in pvsimple.GetSources().items():
            name = sid[0]
            if name == expected_rep_filter or (
                is_active_ijk and (
                    name == 'slicervolume'
                    or name.startswith(('sliceri_', 'slicerj_', 'slicerk_', 'IjkGrid_'))
                )
            ):
                out.append(s)
        return out, view

    @controller.set("toggle_rep_visibility")
    def toggle_rep_visibility(rep_path):
        """Tree eye on a rep: flip ui_hidden_rep_paths and apply the
        change to every source rendering the rep."""
        if not rep_path:
            return
        hidden = list(state.ui_hidden_rep_paths or [])
        if rep_path in hidden:
            hidden.remove(rep_path)
            show = True
        else:
            hidden.append(rep_path)
            show = False
        state.ui_hidden_rep_paths = hidden
        srcs, view = _sources_for_rep_path(rep_path)
        if not srcs:
            print(f"[WARNING] toggle_rep_visibility({rep_path}): no source found")
        for src in srcs:
            # Belt-and-braces: pvsimple.Show/Hide attaches/detaches the
            # source from the view, AND we flip Visibility on the display
            # explicitly. Either path alone has been observed to leave
            # Grid2D reps visible in some pipeline states.
            try:
                if show:
                    pvsimple.Show(src, view=view)
                else:
                    pvsimple.Hide(src, view=view)
            except Exception as _e:
                print(f"[WARNING] Show/Hide raised: {_e}")
            try:
                d = pvsimple.GetDisplayProperties(src, view=view)
                if d is not None:
                    d.Visibility = 1 if show else 0
                    sm = getattr(d, "SMProxy", None)
                    if sm is not None:
                        sm.UpdateVTKObjects()
            except Exception as _e:
                print(f"[WARNING] Visibility flag flip raised: {_e}")
        if view is not None:
            try:
                view.SMProxy.UpdateVTKObjects()
            except Exception:
                pass
            pvsimple.Render(view=view)
        controller.view_update()
        print(
            f"[VIS] {rep_path} → {'show' if show else 'hide'} "
            f"({len(srcs)} sources)"
        )

    def _resolve_array_for_path(rep_path, array_path):
        """Resolve an (assoc, vtkArrayName) tuple for an array node path
        by querying the rep's source pipeline. Falls back to the
        sanitized title (FESPP strips characters outside [-.0-9A-Z_a-z]
        from VTK names) when the raw title doesn't match."""
        node_id = _tree.find_node_id(array_path)
        if node_id is None:
            return None, None
        title = _tree.find_title(node_id) or ""
        # MultiRealization synthetic nodes carry the actual VTK array
        # name in propTitle, not title.
        kind = _tree.find_type(node_id) or ""
        if kind in ("MultiRealization", "MultiRealizationTimeSeries"):
            pt = _tree.find_attribute_value(node_id, "propTitle")
            if pt:
                title = pt
        if not title:
            return None, None
        candidate_sources = []
        src = _rep_sources.get(rep_path)
        if src is not None:
            candidate_sources.append(src)
        else:
            for sid, s in pvsimple.GetSources().items():
                name = sid[0]
                if name == "rep" + (rep_path or "").replace('/', '_'):
                    candidate_sources.append(s)
                    break
        sanitized = re.sub(r"[^\-.0-9A-Z_a-z]", "", title)
        for s in candidate_sources:
            try:
                cell_info = s.GetCellDataInformation()
                point_info = s.GetPointDataInformation()
                for nm in (title, sanitized):
                    if nm and cell_info and cell_info.GetArray(nm):
                        return "CELLS", nm
                    if nm and point_info and point_info.GetArray(nm):
                        return "POINTS", nm
            except Exception:
                pass
        return None, None

    def _displays_for_rep_path(rep_path):
        """Display proxies of every source rendering rep_path."""
        srcs, view = _sources_for_rep_path(rep_path)
        if view is None:
            return []
        out = []
        for s in srcs:
            d = pvsimple.GetDisplayProperties(s, view=view)
            if d is not None:
                out.append(d)
        return out

    def _apply_color_array(rep_path, array_path):
        """Apply ColorBy(array) — or clear it for SolidColor — on every
        display rendering rep_path. pvsimple.ColorBy(display, None) is
        broken in PV6 (raises 'invalid association string NONE'), so we
        clear via SetScalarColoring on the SMProxy."""
        displays = _displays_for_rep_path(rep_path)
        if not displays:
            return
        if not array_path:
            for d in displays:
                try:
                    sm = getattr(d, "SMProxy", None)
                    if sm is not None:
                        sm.SetScalarColoring("", 0)
                        sm.UpdateVTKObjects()
                    else:
                        d.ColorArrayName = ['', '']
                except Exception:
                    pass
            return
        assoc, name = _resolve_array_for_path(rep_path, array_path)
        if not assoc or not name:
            return
        for d in displays:
            try:
                pvsimple.ColorBy(d, (assoc, name))
            except Exception:
                pass

    @state.change("ui_active_array_by_rep")
    def _on_active_array_change(ui_active_array_by_rep, **_):
        """Drive ColorBy on every loaded rep from the active-array map.
        Fires on every map mutation (load sync, eye toggle)."""
        view = pvsimple.GetActiveView()
        loaded = list(state.ui_loaded_rep_paths or [])
        active_map = ui_active_array_by_rep or {}
        for rep_path in loaded:
            _apply_color_array(rep_path, active_map.get(rep_path))
        if view is not None:
            pvsimple.Render(view=view)
        controller.view_update()

    @controller.set("toggle_dataarray_color")
    def toggle_dataarray_color(array_path):
        """Tree eye on a data-array node: if this array is the active
        one of its rep, deactivate (SolidColor); otherwise make it
        active (the previous active array on the same rep loses its
        eye)."""
        if not array_path:
            return
        node_id = _tree.find_node_id(array_path)
        if node_id is None:
            return
        r_id = _tree.find_representation_node(node_id)
        r_path = _tree.find_path(r_id) if r_id is not None else None
        if not r_path:
            return
        active_map = dict(state.ui_active_array_by_rep or {})
        if active_map.get(r_path) == array_path:
            active_map.pop(r_path, None)
        else:
            active_map[r_path] = array_path
        state.ui_active_array_by_rep = active_map

    @state.change("ui_slices_i_list", "ui_slices_j_list", "ui_slices_k_list")
    def update_slice(ui_slices_i_list, ui_slices_j_list, ui_slices_k_list, **kwargs):
        """Sync per-slicer visibility lists with the slice lists, then
        push positions to IjkGrid. New slicers default to visible."""
        for axis, lst in (('i', ui_slices_i_list), ('j', ui_slices_j_list), ('k', ui_slices_k_list)):
            vis_var = f"ui_slices_{axis}_visible_list"
            lst = lst or []
            vis_list = list(getattr(state, vis_var, []) or [])
            while len(vis_list) < len(lst):
                vis_list.append(True)
            while len(vis_list) > len(lst):
                vis_list.pop()
            setattr(state, vis_var, vis_list)

        if _ijkGrid is not None:
            _ijkGrid.update_slices(
                ui_slices_i_list or [],
                ui_slices_j_list or [],
                ui_slices_k_list or [],
            )
            _ijkGrid.show()
        pvsimple.Render(view=_view)
        controller.view_update()

    @state.change("ui_slices_range_i", "ui_slices_range_j", "ui_slices_range_k")
    def update_range_slicer(ui_slices_range_i, ui_slices_range_j, ui_slices_range_k, **kwargs):
        if _ijkGrid is not None:
            _ijkGrid.update_volume(ui_slices_range_i, ui_slices_range_j, ui_slices_range_k)
            _ijkGrid.show()
        pvsimple.Render(view=_view)
        controller.view_update()

    @state.change("ui_slices_range_mode")
    def update_mode_slicer(**kwargs):
        if _ijkGrid is not None:
            _ijkGrid.show()
        pvsimple.Render(view=_view)
        controller.view_update()

    @state.change("ui_slices_real")
    def update_realization_slider(ui_slices_real, **kwargs):
        """Realization slider → drive the collector's RealizationIndex.
        ui_slices_real is the slider position (0..N-1); the actual
        realization index lives in realization_labels[ui_slices_real]
        (e.g. "23"). The C++ layer swaps the property values under the
        same array name, so ParaView's color mapping follows."""
        labels = state.realization_labels or []
        if not labels or ui_slices_real >= len(labels):
            return
        try:
            real_index = int(labels[ui_slices_real])
        except (ValueError, TypeError):
            return
        if ui_slices_real != state.realization_selected_index:
            state.realization_selected_index = ui_slices_real
            _collector.set_realization_index(real_index)
            pvsimple.Render(view=_view)
            controller.view_update()
        if state.ui_slices_real_locked:
            state.ui_slices_real_locked_value = labels[ui_slices_real]

    @state.change("ui_slices_i_visible_list", "ui_slices_j_visible_list", "ui_slices_k_visible_list")
    def update_slices_visibility(**kwargs):
        if _ijkGrid is not None:
            _ijkGrid.show()
        pvsimple.Render(view=_view)
        controller.view_update()

    @state.change("ui_slices_real_locked")
    def update_real_lock(ui_slices_real_locked, **kwargs):
        """Store the locked realization *value* (e.g. "23") so the lock
        survives a switch to a property whose index set differs."""
        if ui_slices_real_locked:
            labels = state.realization_labels or []
            pos = state.ui_slices_real
            state.ui_slices_real_locked_value = (
                labels[pos] if 0 <= pos < len(labels) else None
            )
        else:
            state.ui_slices_real_locked_value = None

    @state.change("time_index")
    def changeTimeLabel( **kwargs):
        """Update ui_time_label from the current time step's label
        attribute on the assembly root, falling back to the formatted
        time value."""
        try:
            index = state.time_index
            if index is not None:
                time_value = pvsimple.GetTimeKeeper().TimestepValues[index]
                label = _tree.find_attribute_value(0, f"time{time_value:.6f}")
                if label is not None:
                    state.ui_time_label = label
                else:
                    state.ui_time_label = f"time{time_value:.6f}"
        except:
            state.ui_time_label = ""

    # load_mode "auto" → every checkbox toggle pushes immediately to
    # ParaView (legacy behaviour). "manual" → toggles only update the
    # per-tab selection state; the toolbar Load button pushes the
    # aggregated selection in one shot. Independent from visibility,
    # which is driven by the per-node eye icons.
    state.setdefault("load_mode", "auto")

    @state.change("ui_select_node_surface")
    def on_change_ui_select_node_surface(**kwargs):
        if _selector is not None and state.load_mode == "auto":
            _selector.select_node_surface()

    @state.change("ui_select_node_well")
    def on_change_ui_select_node_well(**kwargs):
        if _selector is not None and state.load_mode == "auto":
            _selector.select_node_well()

    @state.change("ui_select_node_reservoir")
    def on_change_ui_select_node_reservoir(**kwargs):
        if _selector is not None and state.load_mode == "auto":
            _selector.select_node_reservoir()

    @controller.set("apply_pending_selection")
    def apply_pending_selection():
        """Toolbar Load button entry point — push the aggregated per-tab
        selections to the pipeline. Used only in load_mode == "manual";
        in "auto" the per-tab handlers above already pushed on every
        toggle.

        Re-runs the active-node handlers afterwards: in manual mode the
        active change happened BEFORE the Load click (when the user
        checked the box), so the rep didn't exist yet and the activator
        short-circuited. We re-run the same logic now via
        Activator.refresh_active() — calling state vars directly would
        get coalesced into a no-op by Trame's flush batching."""
        if _selector is None:
            return
        _selector.select_node_reservoir()
        _selector.select_node_surface()
        _selector.select_node_well()
        if _activator is not None:
            _activator.refresh_active()

    @state.change("load_mode")
    def on_load_mode_change(load_mode, **kwargs):
        """Switching from "manual" back to "auto" must flush any pending
        selection the user staged in manual mode."""
        if load_mode == "auto" and _selector is not None:
            apply_pending_selection()

    @state.change("tree_hierarchy_mode")
    def on_tree_hierarchy_mode_change(tree_hierarchy_mode, **kwargs):
        """Push the new mode to the FESPP collector (which triggers the
        live C++ rebuild via SetTreeHierarchyMode → rebuildAssembly()),
        clear every selection / visibility / coloring state var (their
        node ids and paths belong to the old layout), then re-parse the
        assembly into the Python tree."""
        if not _push_tree_hierarchy_mode(tree_hierarchy_mode):
            return
        had_selection = bool(
            (state.ui_select_node_reservoir or [])
            or (state.ui_select_node_surface or [])
            or (state.ui_select_node_well or [])
            or (state.fespp_data_selectors or [])
        )
        state.ui_select_node_reservoir = []
        state.ui_select_node_surface = []
        state.ui_select_node_well = []
        state.ui_active_node_reservoir = []
        state.ui_active_node_surface = []
        state.ui_active_node_well = []
        state.fespp_data_selectors = []
        state.ui_loaded_rep_paths = []
        state.ui_hidden_rep_paths = []
        state.ui_loaded_array_paths = []
        state.ui_active_array_by_rep = {}
        if had_selection:
            state.tree_hierarchy_snackbar_visible = True
        if state.file_loaded:
            # ParaView is not in auto-apply mode; the proxy's output
            # keeps the deep copy of the previous assembly until
            # RequestData runs again. UpdatePipeline triggers RequestData
            # which re-deep-copies the freshly-rebuilt repository
            # assembly into the output, so the Python tree parser reads
            # the new layout.
            try:
                _collector.get_source().UpdatePipeline()
            except Exception as _e:
                print(f"[WARNING] UpdatePipeline after mode change failed: {_e}")
            try:
                controller.update_data_information()
            except Exception as _e:
                print(f"[WARNING] tree refresh after mode change failed: {_e}")
        print(f"[INFO] Tree hierarchy mode set to {tree_hierarchy_mode!r}.")

    @state.change("view_reset_camera")
    def view_reset_camera(view_reset_camera, **kwargs):
        if view_reset_camera == True:
            _ijkGrid.update_block_visibility()
            controller.view_reset_camera()
            controller.view_update()
            state.view_reset_camera = False
            state.flush()

    @state.change("view_update")
    def view_update(view_update, **kwargs):
        if view_update == True:
            controller.view_update()
            state.view_update = False
            state.flush()

    # Drop the shared temp directory when the last client disconnects.
    # Falls back to atexit-only cleanup on trame_server versions that
    # don't expose these hooks.
    try:
        server.controller.on_client_connected.add(on_client_connected)
        server.controller.on_client_exited.add(on_client_exited)
        print("[Session] Client lifecycle hooks registered.", flush=True)
    except AttributeError:
        print("[Session] Client hooks unavailable in this trame version - cleanup via atexit only.", flush=True)
