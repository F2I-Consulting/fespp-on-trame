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

# ---------------------------------------------------------------------------
# Per-session VTK message capture via stderr tee
# ---------------------------------------------------------------------------
# VTK/ParaView writes messages to C-level fd 2 (stderr) via vtkLogger.
# We insert a pipe: fd 2 → pipe-write → reader thread → original fd 2 (tee).
# The reader also parses and queues VTK-formatted lines.
# capture_vtk_messages() slices the queue by index (before/after the op)
# so each session only sees its own messages.
# ---------------------------------------------------------------------------

_vtk_log_queue: list = []           # global growing list of {"text", "level"}
_vtk_stderr_tee_done = False

# Module-level handle on the Tree instance built at engine init.
# Exposed so the UI layer (view.py / tree_views.py) can walk the assembly
# for dependency-expansion in the treeview selection.
_tree = None

# Strip ANSI colour codes written by vtkLogger to terminals
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[mGKHJA-Z]")
# Match vtkLogger line format: "(  29.2s) [thread]    file.cxx:67     ERR| message"
_VTK_LINE_RE = re.compile(r"\([\d. ]+s\)\s*\[.*?\].*?\b([A-Z]{3,})\|\s*(.*)")


def _setup_stderr_tee() -> None:
    """Insert a tee on C-level stderr so VTK output reaches both docker logs
    and our in-memory queue — without touching vtkOutputWindow.
    Must be called after ParaView is initialised."""
    global _vtk_stderr_tee_done
    if _vtk_stderr_tee_done:
        return
    try:
        read_fd, write_fd = os.pipe()
        orig_fd = os.dup(2)          # save original stderr
        os.dup2(write_fd, 2)         # redirect fd 2 → pipe write-end
        os.close(write_fd)

        def _reader():
            buf = b""
            with os.fdopen(read_fd, "rb", buffering=0) as src, \
                 os.fdopen(orig_fd,  "wb", buffering=0) as dst:
                while True:
                    chunk = src.read(1024)
                    if not chunk:
                        break
                    dst.write(chunk)   # tee: forward to original stderr
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
                        if not m:       # not a VTK-formatted line — skip queue
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
    """Capture VTK messages emitted during this block into state.vtk_log_messages."""
    start_seq = len(_vtk_log_queue)
    try:
        yield
    finally:
        # Give the reader thread a moment to flush any bytes already in the pipe
        time.sleep(0.05)
        new_messages = list(_vtk_log_queue[start_seq:])
        if new_messages:
            current = list(state.vtk_log_messages or [])
            state.vtk_log_messages = (current + new_messages)[-max_messages:]

def initialize_fespp_engine(
    server: Server, *, fespp_plugin_path: Path
) -> None:
    # Get references to the Trame server's state and controller
    state = server.state
    controller = server.controller

    # Time the user-facing busy spinner: how long the UI is "blocked" between
    # an interaction and the next idle. The busy state is bumped by Trame
    # on every state mutation that triggers a flush; we log start → end
    # transitions to see what's actually freezing the UI.
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

    # Load the custom FESPP ParaView plugin
    pvsimple.LoadPlugin(str(fespp_plugin_path))
    # Load the ExplicitStructuredGrid plugin for handling explicit grid slicing
    pvsimple.LoadPlugin('/opt/paraview/lib/paraview-6.0/plugins/ExplicitStructuredGrid/ExplicitStructuredGrid.so')

    # Get or create the active ParaView render view
    _view = pvsimple.GetActiveViewOrCreate("RenderView")
    _view.Visible = 1
    _view.Location = 'Bottom Left'
    _view.OrientationAxesVisibility = 0

    # Insert stderr tee for per-session VTK message capture
    # (after ParaView init so startup noise doesn't flood the queue)
    _setup_stderr_tee()

    # Initialize FESPP core components
    global _tree
    _tree = Tree(None)

    _collector = Collector()                     # SOURCE: Collects and loads data (e.g., from an EPC file)
    _etp_connector = ETPConnector()              # SOURCE: Connects to ETP/OSDU servers
    _ijkGrid = IjkGrid(_collector, _tree)        # SOURCE: Handles IJK grid manipulation (slicing, volume)

    # Switch the FESPP collector to "explicit selection" mode. In this mode,
    # a selector path is taken literally for non-grouping nodes — selecting
    # a grid does NOT auto-load all its properties, selecting a wellbore
    # frame does NOT auto-load its channels, etc. Only Collection / Wellbore /
    # Partial groupings still propagate to descendants. This pairs with
    # `select_strategy="independent"` in the Trame VTreeview so the user can
    # check exactly what they want without implicit subtree inclusion.
    try:
        from paraview.servermanager import vtkSMPropertyHelper
        _coll_proxy = _collector.get_source().SMProxy
        if _coll_proxy is not None and _coll_proxy.GetProperty("ExplicitSelection") is not None:
            vtkSMPropertyHelper(_coll_proxy, "ExplicitSelection").Set(1)
            _coll_proxy.UpdateVTKObjects()
    except Exception as _e:
        print(f"[WARNING] Could not set ExplicitSelection on FESPP collector: {_e}")

    # Tree hierarchy mode binding. Pushes the chosen mode to the FESPP
    # collector (proxy property TreeHierarchyMode); the C++ side rebuilds
    # the assembly with the new layout the next time a file is loaded.
    # We also reset the per-tab selections (node ids change between
    # layouts) and re-add already-loaded files so the user sees the new
    # layout immediately.
    _MODE_NAME_TO_INT = {
        "flat": 0,
        "by_interpretation": 1,
        "by_feature_and_interpretation": 2,
    }

    def _push_tree_hierarchy_mode(mode_name):
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

    # Push the initial value once the proxy exists (matches the legacy
    # default 0 = Flat — no-op, but keeps the proxy in sync with state).
    _push_tree_hierarchy_mode(state.tree_hierarchy_mode)
    _rep_sources = RepSources(_collector, _tree) # SOURCE: One ExtractBlock per non-IjkGrid representation

    # FESPP engine components for selection and activation
    _selector = Selector(_ijkGrid, _tree)
    _activator = fespp_active.Activator(_tree, _rep_sources)
    
    #=> Initialize UI state variables <=
    # Initialize Trame state variables for UI selection (TreeView selections)
    state.setdefault("ui_select_node_reservoir", [])
    state.setdefault("ui_select_node_surface", [])
    state.setdefault("ui_select_node_well", [])
    
    state.setdefault("animation_delay", 0.1)
    
    # State variable to hold the list of node paths selected for FESPP loading
    state.setdefault("fespp_data_selectors", [])

    # Visibility state — independent from load/select.
    # ui_loaded_rep_paths : rep paths currently materialized in ParaView (the
    #   eye icon is rendered next to those tree nodes).
    # ui_hidden_rep_paths : subset whose display.Visibility was toggled to 0
    #   by the user via the eye icon. Loaded but not in this set → visible.
    state.setdefault("ui_loaded_rep_paths", [])
    state.setdefault("ui_hidden_rep_paths", [])

    # DataArray "eye" state — drives ColorBy/SolidColor per rep.
    # ui_loaded_array_paths : data-array tree nodes whose data is loaded
    #   (paths of Property/TimeSeries/MultiRealization/... selectors). The
    #   eye icon is rendered next to these.
    # ui_active_array_by_rep : at most one entry per rep parent — the
    #   array currently coloring that rep. Absent entry → SolidColor.
    state.setdefault("ui_loaded_array_paths", [])
    state.setdefault("ui_active_array_by_rep", {})

    # Tree hierarchy mode — see TreeHierarchyMode in C++ enum.h.
    # "flat" / "by_interpretation" / "by_feature_and_interpretation".
    state.setdefault("tree_hierarchy_mode", "flat")

    # State variables for ETP/OSDU connection
    state.setdefault("etp_dataspaces", [])  # List of available dataspaces
    state.setdefault("etp_selected_dataspace", None)  # Currently selected dataspace

    # Flag to track if data has been loaded at least once (used for camera reset logic)
    state.setdefault("has_data_loaded_once", False)
    
    # State flags to trigger view updates and camera resets from Trame
    state.setdefault("view_update", False)
    state.setdefault("view_reset_camera", False)
    
    state.setdefault("view_loading_message", "Loading... Please wait.")

    # Per-session VTK log state
    state.setdefault("vtk_log_messages", [])   # list of {text, level}
    state.setdefault("vtk_log_visible", False)  # controls log panel visibility

    # Upload HTTP state
    state.setdefault("upload_uploading", False)
    state.setdefault("upload_progress", 0)
    state.setdefault("upload_file_count", 0)
    state.setdefault("upload_file_names", [])
    state.setdefault("upload_debug", "")

    # Session ID pour construire l'URL d'upload (/api/{sessionId}/upload)
    # Défini dans on_server_ready une fois le port connu (chaque processus
    # cherche l'entrée qui correspond à son propre port dans proxy-mapping.txt)
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

    # Ensure all state changes are synchronized
    state.flush()

    # Enregistrement de l'endpoint /upload (HTTP multipart)
    # Première tentative immédiate (peut échouer si le serveur aiohttp n'est pas encore créé)
    if not register_upload_route(server):
        # Seconde tentative une fois le serveur démarré
        @controller.add("on_server_ready")
        def _register_upload_on_ready(**kwargs):
            register_upload_route(server)

    # Define controller action to trigger a view update
    @controller.add("on_data_change")
    def update():
        server.controller.view_update()
        
    # Define controller action to load an EPC file
    @controller.set("load_epc_file")
    def load_epc_file(epc_file_path: str):
        with capture_vtk_messages(state):
            # Update state variable 'file_loaded' based on the success of adding the file
            state.file_loaded = _collector.add_file(epc_file_path)

    # Define controller action to connect to ETP/OSDU server
    @controller.set("connect_to_etp")
    def connect_to_etp(etp_url: str, data_partition: str, token: str, token_type: str = "Bearer",
                       proxy_url: str = None, proxy_token: str = None, proxy_token_type: str = "Bearer"):
        """Establish connection to an ETP/OSDU server.

        Args:
            etp_url: ETP server URL
            data_partition: OSDU data partition ID
            token: Authentication token
            token_type: Token type ("Bearer" or "Basic")
            proxy_url: Optional proxy URL
            proxy_token: Optional proxy token
            proxy_token_type: Proxy token type ("Bearer" or "Basic")
        """
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

    # Define controller action to select a dataspace
    @controller.set("select_etp_dataspace")
    def select_etp_dataspace(dataspace: str):
        """Select a specific dataspace after ETP connection.

        Args:
            dataspace: Dataspace identifier to select (e.g., "eml:///")
        """
        if _etp_connector.is_connected:
            _etp_connector.set_dataspace(dataspace)
        else:
            print("Error: Not connected to ETP server")

    # Define controller action to force ETP data refresh
    @controller.set("force_etp_refresh")
    def force_etp_refresh():
        """Force refresh of ETP data."""
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

    # Define controller action to update data information and build the tree structure
    # Create the treeview structure from the FESPP vtkdatasembly
    @controller.set("update_data_information")
    def update_data_information():
        with capture_vtk_messages(state):
            # Get the underlying source object (EPC collector or ETP connector)
            # Check if ETP is connected first, otherwise use EPC collector
            if _etp_connector.is_connected:
                source = _etp_connector.get_source()
            else:
                source = _collector.get_source()

            client_side_object = source.GetClientSideObject()

            # Prefer GetLiveAssembly() — it returns the repository's
            # _output->GetDataAssembly() directly. This matters after
            # rebuildAssembly() (TreeHierarchyMode change), which mutates
            # the live assembly without re-running RequestData; the
            # pipeline output (GetOutput()) still holds the previous deep
            # copy until the next render. GetAssembly() exists on the
            # parent class too but isn't always exposed to Python through
            # the override — GetLiveAssembly is unique and always wrapped.
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

    # Controller: Set slider value (for IJK sliders) — met à jour le premier élément de la liste
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

    # Handler for changes to the selected FESPP data nodes (Trame state variable)
    @state.change("fespp_data_selectors")
    def on_change_fespp_data_selectors( **kwargs):
        with capture_vtk_messages(state):
            _on_change_fespp_data_selectors_impl()

    def _on_change_fespp_data_selectors_impl():
        import time as _time
        _t_total_start = _time.perf_counter()
        def _ms(t0):
            return int((_time.perf_counter() - t0) * 1000)
        print("FESPP data selectors changed:", state.fespp_data_selectors)
        # Determine which source is active (ETP or EPC)
        if _etp_connector.is_connected:
            active_source = _etp_connector
        else:
            active_source = _collector

        if active_source is None:
            return

        # Set the 'Selectors' property on the ParaView source to load selected data.
        # SetPropertyWithName triggers ClearSelectors + AddSelector × N on the
        # C++ side; both are now Modified()-only (no per-call Update()) to avoid
        # N full pipeline executions per add. We must explicitly trigger the
        # actual RequestData ONCE here so downstream code (set_node_id,
        # _rep_sources.sync) sees the freshly-loaded multiblock output.
        _t = _time.perf_counter()
        active_source.get_source().SetPropertyWithName('Selectors', state.fespp_data_selectors)
        active_source.get_source().UpdatePipeline()
        active_source.show()
        print(f"[PERF py] SetSelectors+UpdatePipeline+show: {_ms(_t)}ms")

        # Hide the parent multiblock representation BEFORE any render.
        # Each loaded rep is rendered through its own ExtractBlock proxy below;
        # leaving the parent visible at this point caused a Render() that
        # processed all N blocks via the parent rep, scaling O(N) per add
        # (~1100ms per extra grid in the original code).
        _t = _time.perf_counter()
        representation = active_source.get_representation()
        representation.Assembly='Assembly'
        representation.BlockSelectors = ['/data']
        representation.Visibility = 0
        print(f"[PERF py] representation.Assembly+BlockSelectors+Visibility=0: {_ms(_t)}ms")

        # Update IJK Grid visibility if a reservoir node is selected
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

        # Reserve a distinct chip color for every newly loaded representation.
        # Cache (selector → rep_path) to avoid re-walking the tree for
        # selectors we've already seen. Single state mutation per call so
        # Trame reactivity (and the treeview slot re-render) only fires once.
        # Done BEFORE _rep_sources.sync so newly created TrivialProducers can
        # read their assigned color from state.solid_color_by_rep and tint
        # their display straight away — no need for the user to activate a
        # node to get the default solid color.
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

        # Sync per-representation ExtractBlock sources with current selection.
        # Non-IjkGrid representations are rendered from their own extracted proxy;
        # the parent multiblock stops rendering (Visibility forced to 0 below — empty
        # BlockSelectors falls back to "show all" in Assembly mode and would cause
        # double rendering on top of the extracts).
        _t = _time.perf_counter()
        _rep_sources.sync(state.fespp_data_selectors)
        # The C++ side modifies partition data in place (addDataArray for new
        # property selectors, array swap for realization/time changes). The
        # TrivialProducers wrapping those partitions cache their data
        # information at the proxy level — so without an explicit Modified()
        # bump, GetCellDataInformation returns a stale array list and the
        # active handler can't find a freshly-added property like "SOIL".
        # Bump every producer's MTime to invalidate the proxy cache.
        for src in _rep_sources.all_sources():
            try:
                src.GetClientSideObject().Modified()
                src.UpdatePipelineInformation()
            except Exception:
                pass
        # IjkGrid's rep_data filter (created via SetExtractRepPath inside
        # IjkGrid.set_node_id) is NOT tracked by _rep_sources, so the loop
        # above misses it. Bump it + the slicers chained on it so their
        # caches invalidate and the next downstream Update sees the freshly
        # loaded property arrays.
        #
        # ONLY bump if the IjkGrid is in the CURRENT selection — otherwise we
        # risk poking at stale references (the previous IjkGrid's filter
        # whose input is no longer being kept fresh by FESPP), which can
        # hang or error. We use UpdatePipelineInformation (cheap, REQUEST_INFO
        # only) — the actual RequestData re-execution happens lazily on the
        # next render or on the active handler's UpdatePipeline.
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

        # Notify the activator about which reps are still actively displayed
        # so it can hide stale color bars (e.g., switching between two
        # IjkGrids — without this, the previous grid's color bar stays
        # visible alongside the new grid's bar).
        present_paths = set(p for p, _ in _rep_sources.items())
        if ijk_in_selection and ijk_path:
            present_paths.add(ijk_path)
        if _activator is not None:
            try:
                _activator.notify_active_reps(present_paths)
            except Exception as _e:
                print(f"[WARNING] notify_active_reps failed: {_e}")

        # Sync visibility tracking. Newly-loaded reps default to visible
        # (eye open); reps that were hidden but stayed loaded keep their
        # hidden state; reps no longer present are dropped from the hidden
        # set so they don't ghost-hide on a future re-load.
        loaded_sorted = sorted(present_paths)
        if list(state.ui_loaded_rep_paths or []) != loaded_sorted:
            state.ui_loaded_rep_paths = loaded_sorted
        prev_hidden = list(state.ui_hidden_rep_paths or [])
        kept_hidden = [p for p in prev_hidden if p in present_paths]
        if kept_hidden != prev_hidden:
            state.ui_hidden_rep_paths = kept_hidden

        # DataArray tracking — each property/TS/MR selector that lives under
        # a loaded rep is a data-array leaf. The "last added per rep" becomes
        # the active eye by default, mirroring the C++ side which colors by
        # the last array added to the rep.
        DATA_ARRAY_KINDS = {
            "ContinuousProperty", "DiscreteProperty", "CategoricalProperty",
            "TimeSeries", "MultiRealization", "MultiRealizationTimeSeries",
        }
        prev_loaded_arrays = list(state.ui_loaded_array_paths or [])
        prev_loaded_set = set(prev_loaded_arrays)
        loaded_arrays = []
        loaded_arrays_set = set()
        # Order of fespp_data_selectors preserves selection order, so the
        # final entry for a given rep wins as "last added".
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
        # Update active-array map: keep prior choice if its array is still
        # loaded; for reps where the previous active is gone OR the rep just
        # got a newly added array, switch to the last-added.
        prev_active = dict(state.ui_active_array_by_rep or {})
        new_active = {}
        for r_path in present_paths:
            prev_arr = prev_active.get(r_path)
            last_arr = last_array_for_rep.get(r_path)
            # Detect "newly added" by checking if the current last-added
            # was absent before — that's the trigger for the eye to follow.
            newly_added = last_arr is not None and last_arr not in prev_loaded_set
            if newly_added:
                new_active[r_path] = last_arr
            elif prev_arr in loaded_arrays_set:
                new_active[r_path] = prev_arr
            elif last_arr is not None:
                new_active[r_path] = last_arr
            # else: no array on this rep → SolidColor (omit entry)
        if new_active != prev_active:
            state.ui_active_array_by_rep = new_active

        # Trigger Trame view replacement and general update
        controller.view_replace
        state.view_update = True

        # Set the FESPP source as active for ParaView dialogs that look at it.
        # We do NOT call active_source.show() here — that would re-set the
        # parent rep's Visibility to 1 and undo the early hide above (a Render
        # afterwards would then walk all N blocks via the parent, the very
        # O(N) cost we just removed).
        _t = _time.perf_counter()
        pvsimple.SetActiveSource(active_source.get_source())
        # Notify Trame components (like TimeControl and ColorBy) that data has loaded
        server.controller.on_data_loaded() # for ptc.TimeControl()
        server.controller.on_active_proxy_change() # for ptc.RepresentBy() / ptc.ColorBy
        print(f"[PERF py] setActive+notify: {_ms(_t)}ms")

        # CAMERA RESET LOGIC (ONLY ON FIRST LOAD)
        if (not state.has_data_loaded_once) and (len(state.fespp_data_selectors) > 0):
            state.view_reset_camera = True
            state.has_data_loaded_once = True

        # Multi-realization is now driven by the collector's RealizationIndex
        # (set on slider change). Color mapping follows automatically because
        # the array name doesn't change between realizations.

        # Re-run the active-node handlers AFTER the load+sync so newly-loaded
        # reps get their ColorBy / TimeControl wiring even when their @state.change
        # active handler fired before this load handler (handler ordering
        # between ui_select_node_* and ui_active_node_* is not guaranteed).
        # Idempotent: if the active handler already ran successfully on its
        # own (rep already existed), this is a no-op. If it short-circuited
        # because rep_source was None, this is the catch-up.
        if _activator is not None:
            _activator.refresh_active()

        # Single Render at the very end. The parent multiblock was already
        # hidden (Visibility=0) earlier, so this only paints the new
        # ExtractBlock representations + IjkGrid slicers.
        _t = _time.perf_counter()
        state.view_update = True
        pvsimple.Render(view=_view)
        print(f"[PERF py] final Render: {_ms(_t)}ms")
        print(f"[PERF py] >>> TOTAL on_change_fespp_data_selectors: {_ms(_t_total_start)}ms <<<")
        # ----------------------------------------------------

    #======================= Main Properties
    # Handler for Z-scaling changes — broadcast to every extracted rep source
    # (and to IjkGrid slicer sources) so the global vertical exaggeration stays
    # coherent across all representations.
    state.setdefault("ui_scale_z", 1.0)

    @state.change("ui_scale_z")
    def ui_scale_z_update(ui_scale_z, **kwargs):
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

    # Accessor so UI panels (SolidColorPanel, ColorEditor) can resolve a rep
    # path to its extracted ParaView source.
    @controller.set("get_rep_source")
    def get_rep_source(rep_path):
        return _rep_sources.get(rep_path)

    # ---------------------------------------------------------------- Visibility
    # The tree's eye icon → display visibility on every source rendering the rep.
    # Non-IjkGrid: single ExtractBlock proxy in _rep_sources.
    # IjkGrid: rep_data filter named "rep<sanitized_path>", plus slicers/volume
    # tied to the *currently active* IjkGrid (only one at a time, see IjkGrid).
    def _sources_for_rep_path(rep_path):
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
            # Belt-and-braces: the high-level helper attaches/detaches the
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

    # ---------------------------------------------------------------- DataArray eye
    # Resolve the (CELLS|POINTS, vtkArrayName) tuple for an array node path
    # by querying the rep's source pipeline. Falls back to the sanitized
    # title (FESPP strips characters outside [-.0-9A-Z_a-z] from VTK names)
    # if the raw title isn't found. Returns (assoc, name) or (None, None).
    def _resolve_array_for_path(rep_path, array_path):
        node_id = _tree.find_node_id(array_path)
        if node_id is None:
            return None, None
        title = _tree.find_title(node_id) or ""
        # MultiRealization synthetic nodes carry the actual VTK array name
        # in the propTitle attribute, not the title.
        kind = _tree.find_type(node_id) or ""
        if kind in ("MultiRealization", "MultiRealizationTimeSeries"):
            pt = _tree.find_attribute_value(node_id, "propTitle")
            if pt:
                title = pt
        if not title:
            return None, None
        # We need a source whose data we can introspect for the array.
        # For non-IjkGrid use _rep_sources directly; for IjkGrid pick any
        # display source from _displays_for_rep_path (its underlying source
        # has the array attached after FESPP loaded it).
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

    def _apply_color_array(rep_path, array_path):
        """Apply ColorBy(array) — or clear it (SolidColor) — on every display
        that renders rep_path. Called by the active-array state handler and
        by toggle_dataarray_color."""
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
        Reps absent from the map → SolidColor; reps mapped to an array → that
        array. Called whenever the map mutates (load sync, eye toggle)."""
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
        """Eye on a data-array node: if this array is the active one of its
        rep, deactivate (SolidColor); otherwise make it active (the previous
        active array of the same rep loses its eye)."""
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

    # Representation type per-source: handled natively by ptc.RepresentBy inside
    # RepresentationTypePanel. It targets the ParaView active source and re-syncs
    # via controller.on_active_proxy_change — no global broadcast needed.

    #======================= UI: change Slicer
    # Handler for IJK slices position changes (liste multi-slice)
    @state.change("ui_slices_i_list", "ui_slices_j_list", "ui_slices_k_list")
    def update_slice(ui_slices_i_list, ui_slices_j_list, ui_slices_k_list, **kwargs):
        # Sync visibility lists to match slice list lengths (new slicers default to visible)
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
        
    # Handler for IJK volume range changes
    @state.change("ui_slices_range_i", "ui_slices_range_j", "ui_slices_range_k")
    def update_range_slicer(ui_slices_range_i, ui_slices_range_j, ui_slices_range_k, **kwargs):
        if _ijkGrid is not None:
            _ijkGrid.update_volume(ui_slices_range_i, ui_slices_range_j, ui_slices_range_k)
            _ijkGrid.show()
        pvsimple.Render(view=_view)
        controller.view_update()
        
    # Handler for slicer mode changes (e.g., slice vs. volume)
    @state.change("ui_slices_range_mode")
    def update_mode_slicer(**kwargs):
        if _ijkGrid is not None:
            _ijkGrid.show()
        pvsimple.Render(view=_view)
        controller.view_update()

    # Handler for realization slider changes
    @state.change("ui_slices_real")
    def update_realization_slider(ui_slices_real, **kwargs):
        # Single multi-realization node per property: the slider drives the
        # collector's RealizationIndex; the C++ layer swaps the property values
        # under the same array name, so ParaView's color mapping follows.
        # ui_slices_real is the slider position (0..N-1); the actual realization
        # index lives in realization_labels[ui_slices_real] (e.g. "23").
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

    # Handlers for per-slicer visibility changes
    @state.change("ui_slices_i_visible_list", "ui_slices_j_visible_list", "ui_slices_k_visible_list")
    def update_slices_visibility(**kwargs):
        if _ijkGrid is not None:
            _ijkGrid.show()
        pvsimple.Render(view=_view)
        controller.view_update()

    # Handler for realization lock state (store locked value)
    @state.change("ui_slices_real_locked")
    def update_real_lock(ui_slices_real_locked, **kwargs):
        if ui_slices_real_locked:
            # Store current realization *value* (e.g. "23") so the lock survives
            # switches to a property whose index set differs.
            labels = state.realization_labels or []
            pos = state.ui_slices_real
            state.ui_slices_real_locked_value = (
                labels[pos] if 0 <= pos < len(labels) else None
            )
        else:
            # Clear locked value when unlocking
            state.ui_slices_real_locked_value = None

    #======================= UI: change time
    # Handler for time step index changes
    @state.change("time_index")
    def changeTimeLabel( **kwargs):
        try:
            index = state.time_index
            if index is not None:
                # Find time label in the tree based on the timestep value
                time_value = pvsimple.GetTimeKeeper().TimestepValues[index]
                label = _tree.find_attribute_value(0, f"time{time_value:.6f}")
                if label is not None:
                    state.ui_time_label = label
                else:
                    # Fallback label if no custom label is found
                    state.ui_time_label = f"time{time_value:.6f}"
        except:
            state.ui_time_label = ""

    #======================= TreeView: change selection
    # load_mode: "auto" → every checkbox toggle pushes immediately to the
    # ParaView pipeline (the legacy behaviour). "manual" → checkbox toggles
    # only update the per-tab selection state; the user clicks the toolbar
    # "Load" button to push the aggregated selection in one shot.
    # Note: load_mode controls *loading* (data presence in ParaView), not
    # *visibility* — show/hide of an already-loaded rep is driven by the
    # per-node eye icons in the trees.
    state.setdefault("load_mode", "auto")

    # Handler for surface node selection changes
    @state.change("ui_select_node_surface")
    def on_change_ui_select_node_surface(**kwargs):
        if _selector is not None and state.load_mode == "auto":
            _selector.select_node_surface()

    # Handler for well node selection changes
    @state.change("ui_select_node_well")
    def on_change_ui_select_node_well(**kwargs):
        if _selector is not None and state.load_mode == "auto":
            _selector.select_node_well()

    # Handler for reservoir node selection changes
    @state.change("ui_select_node_reservoir")
    def on_change_ui_select_node_reservoir(**kwargs):
        if _selector is not None and state.load_mode == "auto":
            _selector.select_node_reservoir()

    # Toolbar "Load" button entry point — pushes the current (potentially
    # accumulated) per-tab selections to the ParaView pipeline. Used only in
    # load_mode == "manual"; in "auto" mode the per-tab state.change handlers
    # above already push on every toggle.
    @controller.set("apply_pending_selection")
    def apply_pending_selection():
        if _selector is None:
            return
        _selector.select_node_reservoir()
        _selector.select_node_surface()
        _selector.select_node_well()
        # Re-run the active-node handlers in fespp_active.py for any node
        # currently marked active. In manual mode the active change
        # happened BEFORE the Load click (when the user checked the box) — the
        # rep didn't exist yet, so ColorBy / TimeControl wiring
        # short-circuited. Now that the rep exists we re-run the same
        # logic. We can't just bump the state vars (Trame batches the
        # mutations and the diff disappears), so we call the handler
        # methods directly via Activator.refresh_active().
        if _activator is not None:
            _activator.refresh_active()

    # Switching from "manual" back to "auto" must flush any pending selection
    # the user staged while in manual mode — otherwise their already-checked
    # boxes would stay un-applied until the next checkbox toggle.
    @state.change("load_mode")
    def on_load_mode_change(load_mode, **kwargs):
        if load_mode == "auto" and _selector is not None:
            apply_pending_selection()

    # Tree hierarchy mode change → push the mode to the FESPP collector
    # (which triggers a live C++ rebuild of the assembly via SetTreeHierarchyMode
    # → repository.rebuildAssembly()), then re-parse the assembly into the
    # Python tree so the UI shows the new layout. Selections are reset because
    # node ids change between layouts.
    @state.change("tree_hierarchy_mode")
    def on_tree_hierarchy_mode_change(tree_hierarchy_mode, **kwargs):
        if not _push_tree_hierarchy_mode(tree_hierarchy_mode):
            return
        # If anything was selected/loaded under the previous layout, surface
        # a snackbar so the user understands why the tree state appears wiped.
        had_selection = bool(
            (state.ui_select_node_reservoir or [])
            or (state.ui_select_node_surface or [])
            or (state.ui_select_node_well or [])
            or (state.fespp_data_selectors or [])
        )
        # Drop selections — their node ids belong to the OLD assembly.
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
        # Re-parse the freshly rebuilt assembly into state.ui_subtree_*.
        # state.file_loaded may be None (no add_file yet) — only refresh
        # when at least one file has actually been loaded.
        if state.file_loaded:
            # Force a full pipeline update — ParaView is not in auto-apply
            # mode, so the proxy's output keeps the deep copy of the
            # previous assembly until RequestData runs again. UpdatePipeline
            # triggers RequestData which redepth-copies the freshly-rebuilt
            # repository assembly into the output, so the Python tree
            # parser reads the new layout.
            try:
                _collector.get_source().UpdatePipeline()
            except Exception as _e:
                print(f"[WARNING] UpdatePipeline after mode change failed: {_e}")
            try:
                controller.update_data_information()
            except Exception as _e:
                print(f"[WARNING] tree refresh after mode change failed: {_e}")
        print(f"[INFO] Tree hierarchy mode set to {tree_hierarchy_mode!r}.")
        
    #======================= View Controls
    # Handler for camera reset flag
    @state.change("view_reset_camera")
    def view_reset_camera(view_reset_camera, **kwargs):
        if view_reset_camera == True:
            # Ensure the IJK grid visibility is correct before resetting the camera
            _ijkGrid.update_block_visibility()
            controller.view_reset_camera()
            controller.view_update()
            # Reset the flag after the action is performed
            state.view_reset_camera = False
            state.flush()
            
    # Handler for general view update flag
    @state.change("view_update")
    def view_update(view_update, **kwargs):
        if view_update == True:
            controller.view_update()
            # Reset the flag after the action is performed
            state.view_update = False
            state.flush()

    #======================= Session lifecycle - cleanup temp files
    # Register client connect/disconnect hooks to track active sessions.
    # When the last client disconnects, the shared temp directory is cleaned up.
    # Falls back to atexit-only cleanup if the hooks are not available in this
    # version of trame_server.
    try:
        server.controller.on_client_connected.add(on_client_connected)
        server.controller.on_client_exited.add(on_client_exited)
        print("[Session] Hooks de cycle de vie client enregistrés.", flush=True)
    except AttributeError:
        print("[Session] Hooks client non disponibles dans cette version de trame - nettoyage via atexit uniquement.", flush=True)