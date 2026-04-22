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
    _tree = Tree(None)

    _collector = Collector()                     # SOURCE: Collects and loads data (e.g., from an EPC file)
    _etp_connector = ETPConnector()              # SOURCE: Connects to ETP/OSDU servers
    _ijkGrid = IjkGrid(_collector, _tree)        # SOURCE: Handles IJK grid manipulation (slicing, volume)
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

            if hasattr(client_side_object, "GetOutput"):
                output = client_side_object.GetOutput()
                if hasattr(output, "GetDataAssembly"):
                    assembly = output.GetDataAssembly()

            _tree.set_tree(assembly)

    # Controller: Select a specific realization by index
    @controller.set("select_realization")
    def select_realization(index):
        """Select and activate a specific realization by index (0-based)."""
        if not state.realization_list or index >= len(state.realization_list):
            return

        state.realization_play = False
        state.realization_selected_index = index
        state.ui_slices_real = index  # Sync slider value (0-based)
        realization_child = state.realization_list[index]
        _selector.update_realization_selector(realization_child["path"])
        # _activate_realization is called by _on_change_fespp_data_selectors_impl
        # after the data has actually been reloaded

    # Controller: Next realization (for animation)
    @controller.set("next_realization")
    def next_realization():
        """Move to next realization (wraps around)."""
        if not state.realization_list:
            return
        current_index = state.realization_selected_index
        next_index = (current_index + 1) % len(state.realization_list)
        controller.select_realization(next_index)

    # Controller: Previous realization
    @controller.set("previous_realization")
    def previous_realization():
        """Move to previous realization (wraps around)."""
        if not state.realization_list:
            return
        current_index = state.realization_selected_index
        prev_index = (current_index - 1) % len(state.realization_list)
        controller.select_realization(prev_index)

    # Controller: Set realization by label (number)
    @controller.set("set_realization_by_label")
    def set_realization_by_label(label):
        """Set realization by its label/number (extracted from title)."""
        if not state.realization_labels:
            return

        # Find the index of the label in realization_labels
        try:
            index = state.realization_labels.index(str(label))
            controller.select_realization(index)
        except (ValueError, IndexError):
            # Label not found, ignore
            pass

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

    # Controller: Play/pause realization animation
    @controller.set("toggle_realization_play")
    def toggle_realization_play():
        """Toggle play/pause for realization animation."""
        state.realization_play = not state.realization_play
        if state.realization_play:
            server.schedule_task(play_realization_animation)

    # Async animation function
    async def play_realization_animation():
        """Auto-cycle through realizations (async pattern from CustomTimeControl)."""
        import asyncio
        play_delay = state.animation_delay if hasattr(state, 'animation_delay') else 1.0

        while state.realization_play:
            controller.next_realization()
            await asyncio.sleep(play_delay)

            if not state.realization_list or state.realization_parent_node_id is None:
                state.realization_play = False
                break

    # Handler for changes to the selected FESPP data nodes (Trame state variable)
    @state.change("fespp_data_selectors")
    def on_change_fespp_data_selectors( **kwargs):
        with capture_vtk_messages(state):
            _on_change_fespp_data_selectors_impl()

    def _on_change_fespp_data_selectors_impl():
        print("FESPP data selectors changed:", state.fespp_data_selectors)
        # Determine which source is active (ETP or EPC)
        if _etp_connector.is_connected:
            active_source = _etp_connector
        else:
            active_source = _collector

        if active_source is None:
            return

        # Set the 'Selectors' property on the ParaView source to load selected data
        active_source.get_source().SetPropertyWithName('Selectors', state.fespp_data_selectors)
        active_source.get_source().UpdatePipelineInformation()
        active_source.show()

        pvsimple.Render(view=_view)


        # Configure representation for partitioned dataset (e.g., show assembly structure)
        # Hide objects in vtkPartitionedDataSet: extracted object
        representation = active_source.get_representation()
        representation.Assembly='Assembly'
        representation.BlockSelectors = ['/data']
        #active_source.show()
        #pvsimple.Render(view=_view)

        # Update IJK Grid visibility if a reservoir node is selected
        print(f"[DEBUG engine] post-render, ui_select_node_reservoir={state.ui_select_node_reservoir}")
        if len(state.ui_select_node_reservoir) > 0:
            for reservoir_node_id in state.ui_select_node_reservoir:
                if _tree.find_parent_node_id_with_type(reservoir_node_id, 'IjkGrid') is not None:
                    print(f"[DEBUG engine] calling set_node_id({reservoir_node_id})")
                    try:
                        _ijkGrid.set_node_id(reservoir_node_id)
                    except Exception as e:
                        import traceback
                        print(f"[WARNING] _ijkGrid.set_node_id failed: {e}")
                        traceback.print_exc()
                    break
        _ijkGrid.update_block_visibility()

        # Sync per-representation ExtractBlock sources with current selection.
        # Non-IjkGrid representations are rendered from their own extracted proxy;
        # the parent multiblock stops rendering (Visibility forced to 0 below — empty
        # BlockSelectors falls back to "show all" in Assembly mode and would cause
        # double rendering on top of the extracts).
        _rep_sources.sync(state.fespp_data_selectors)

        # Trigger Trame view replacement and general update
        controller.view_replace
        state.view_update = True

        # Show the data source and set it as active
        active_source.show()
        pvsimple.SetActiveSource(active_source.get_source())
        # Notify Trame components (like TimeControl and ColorBy) that data has loaded
        server.controller.on_data_loaded() # for ptc.TimeControl()
        server.controller.on_active_proxy_change() # for ptc.RepresentBy() / ptc.ColorBy

        # CAMERA RESET LOGIC (ONLY ON FIRST LOAD)
        if (not state.has_data_loaded_once) and (len(state.fespp_data_selectors) > 0):
            state.view_reset_camera = True
            state.has_data_loaded_once = True

        # If a realization is active, apply coloring now that data is loaded.
        # Use ui_select_node_reservoir as fallback in case realization_parent_node_id
        # is not yet set (handlers may fire in any order).
        _realization_node_id = state.realization_parent_node_id
        if _realization_node_id is None and state.ui_select_node_reservoir:
            candidate = state.ui_select_node_reservoir[0]
            if _tree.find_type(candidate) == "Realization":
                _realization_node_id = candidate

        print(f"[DEBUG engine] realization_node_id={_realization_node_id}, realization_selected_index={state.realization_selected_index}")
        if _realization_node_id is not None:
            realization_children = _tree.get_realization_children(_realization_node_id)
            print(f"[DEBUG engine] realization_children count={len(realization_children)}")
            if realization_children:
                idx = state.realization_selected_index or 0
                if 0 <= idx < len(realization_children):
                    child = realization_children[idx]
                    print(f"[DEBUG engine] calling _activate_realization with label='{child.get('label')}' vtk_array_name='{child.get('vtk_array_name')}'")
                    _activator._activate_realization(child)

        # Final render to display the scene with the new camera
        state.view_update = True
        active_source.show()
        # Force-hide the parent multiblock display: every visible block is now
        # rendered through its own extracted proxy (or via IjkGrid slicers).
        representation.Visibility = 0
        pvsimple.Render(view=_view)
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
        # Avoid infinite loop by checking if value actually changed
        if ui_slices_real != state.realization_selected_index:
            # RealizationTimeSeries: drive via VTK RealizationIndex property
            ts_node_id = getattr(state, 'realization_ts_node_id', None)
            if ts_node_id is not None and _tree.find_type(ts_node_id) == "RealizationTimeSeries":
                state.realization_selected_index = ui_slices_real
                _collector.set_realization_index(ui_slices_real)
            else:
                controller.select_realization(ui_slices_real)
        # Keep locked value in sync with current slider position
        if state.ui_slices_real_locked:
            state.ui_slices_real_locked_value = ui_slices_real

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
            # Store current realization value when locking
            state.ui_slices_real_locked_value = state.ui_slices_real
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
    # Handler for surface node selection changes
    @state.change("ui_select_node_surface")
    def on_change_ui_select_node_surface(**kwargs):
        if _selector is not None:
            _selector.select_node_surface()
        
    # Handler for well node selection changes
    @state.change("ui_select_node_well")
    def on_change_ui_select_node_well(**kwargs):
        if _selector is not None:
            _selector.select_node_well()
    
    # Handler for reservoir node selection changes
    @state.change("ui_select_node_reservoir")
    def on_change_ui_select_node_reservoir(**kwargs):
        if _selector is not None:
            _selector.select_node_reservoir()
        
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