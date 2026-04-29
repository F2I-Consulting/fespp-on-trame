import re
import time

from trame.app import get_server
from paraview import simple as pvsimple

from fespp_on_trame.app.core.fespp_tree import Tree


# Mirror of FESPP's C++ MakeValidNodeName
# (ResqmlDataRepositoryToVtkPartitionedDataSetCollection.cxx). FESPP strips any
# character outside [-.0-9A-Z_a-z] from property titles before using them as
# VTK array names. The tree's `title` attribute keeps the original RESQML
# title (with spaces, parentheses, etc.), so a direct GetArray(title) lookup
# fails when the title contains stripped characters. This helper produces the
# sanitized variant used to retry the lookup.
_VTK_NAME_INVALID_RE = re.compile(r"[^\-.0-9A-Z_a-z]")


def _make_valid_vtk_name(name: str) -> str:
    if not name:
        return ""
    return _VTK_NAME_INVALID_RE.sub("", name)


def _find_array_in_store(store, name):
    """Look up a VTK array by name with fallback to the sanitized variant."""
    if store is None or not name:
        return None
    arr = store.GetArray(name)
    if arr is not None:
        return arr
    sanitized = _make_valid_vtk_name(name)
    if sanitized != name:
        return store.GetArray(sanitized)
    return None

server = get_server()
state = server.state
controller = server.controller

def _nan_opacity_from_state():
    """Read NaN opacity from state.nan_color (#RRGGBBAA), default 0.2."""
    try:
        hex_val = (state.nan_color or "").lstrip("#")
        if len(hex_val) >= 8:
            return int(hex_val[6:8], 16) / 255
    except (ValueError, IndexError):
        pass
    return 0.2


def _drill_to_inner(vtk_out):
    """If vtk_out is a vtkPartitionedDataSetCollection (e.g. for sources
    whose output is the global multiblock), drill down to the first inner
    partition. Otherwise return as-is. Defensive helper: the rep_data
    filter outputs single-piece so this is a no-op there, but kept in case
    a downstream wrapping ever adds a composite layer."""
    if vtk_out is None:
        return None
    if hasattr(vtk_out, 'GetPartitionedDataSet'):
        try:
            pds = vtk_out.GetPartitionedDataSet(0)
            if pds is not None and pds.GetNumberOfPartitions() > 0:
                return pds.GetPartitionAsDataObject(0)
        except Exception:
            return vtk_out
    return vtk_out


class Activator:
    def __init__(self, tree: Tree, rep_sources=None):
        self._tree = tree
        self._rep_sources = rep_sources

        # Track the array currently colorized per rep. ParaView keys color
        # bars by LUT (one per array name globally), so when a rep switches
        # property A → B we must hide A's color bar — otherwise it stacks
        # on top of B's bar in the view. We only hide A's bar if NO other
        # rep is still colored by A (multiple reps can share a LUT/bar).
        self._current_array_by_rep = {}

        # ----- Helper: validate that the active node belongs to a checked
        # subtree before letting the activation proceed. Reuses tree paths
        # rather than walking parents (cheap; assembly paths are cached on
        # the C++ side). Catches both directions:
        #   - node_id is/under a selected node (checked rep, click property)
        #   - node_id is an ancestor of a selected node (checked property,
        #     click parent rep — the rep loads as a side effect)
        # Works in both auto and manual show modes since `select_list` is
        # the raw checkbox state (`state.ui_select_node_*`), updated as soon
        # as the user toggles a checkbox regardless of show_mode.
        def _is_node_active_able(node_id, select_list):
            if not select_list or node_id is None or node_id == 0:
                return False
            rep_node_id = self._tree.find_representation_node(node_id)
            anchor = rep_node_id if rep_node_id is not None else node_id
            anchor_path = self._tree.find_path(anchor)
            if not anchor_path:
                return False
            for sel_id in select_list:
                sel_path = self._tree.find_path(sel_id)
                if not sel_path:
                    continue
                if sel_path == anchor_path:
                    return True
                if sel_path.startswith(anchor_path + "/"):
                    return True
                if anchor_path.startswith(sel_path + "/"):
                    return True
            return False
        self._is_node_active_able = _is_node_active_able
        
        state.setdefault("ui_active_node_reservoir", [])
        state.setdefault("ui_active_node_surface", [])
        state.setdefault("ui_active_node_well", [])
        state.setdefault("ui_active_node_reservoir_type_rep", "")
        state.setdefault("ui_active_node_reservoir_type", "")
        state.setdefault("ui_active_node_reservoir_title", "")
        # Underlying property kind of the active node — drives the editor
        # switch in solid_color_panel (continuous LUT vs categorical list).
        # Resolved directly for plain ContinuousProperty/DiscreteProperty/
        # CategoricalProperty leaves, and via the C++-emitted `propKind`
        # attribute for synthetic TS / MR / MRTS leaves.
        state.setdefault("active_property_kind", "")

        # Realization widget state
        state.setdefault("realization_selected_index", 0)
        state.setdefault("realization_parent_node_id", None)
        state.setdefault("realization_ts_node_id", None)  # Set when a RealizationTimeSeries node is active
        # Must be setdefault'd here so Vue subscribes — without it the slicer's
        # v_if="realization_labels && realization_labels.length > 0" stays false
        # forever even after we assign state.realization_labels later.
        state.setdefault("realization_labels", [])

        # Locked LUT range for consistent legend across realizations: (min, max) or None
        self._realization_locked_range = None

        state.setdefault("active_representation_has_properties", False)

        # Saved as attributes (after definition below) so refresh_active()
        # can re-run them directly. Needed because Trame batches state
        # mutations within a flush window — a clear-then-restore on
        # ui_active_node_X collapses to "no change" and the @state.change
        # callback never fires. Calling the handler explicitly bypasses
        # the diff check.
        @state.change("ui_active_node_reservoir")
        def on_ui_active_node_reservoir_change(ui_active_node_reservoir, **kwargs):
            # Top-level timing — fires on EVERY active change (including
            # resets and non-property activations) so we can see why a click
            # feels slow even when the active branch below short-circuits.
            _t_total = time.perf_counter()
            _ms = lambda t: int((time.perf_counter() - t) * 1000)
            _ms_tree_lookup = 0
            _ms_pipeline_pre = 0
            _ms_colorby = 0
            _ms_pipeline_post = 0
            _ms_on_active = 0
            _ms_on_loaded = 0
            _ms_update_coe = 0
            _ms_render = 0
            _branch = "unknown"
            is_property = False
            array_name = ""
            try:
                if not ui_active_node_reservoir or len(ui_active_node_reservoir) == 0:
                    state.update({
                        "ptc_show_vcr": False,
                        "active_color_array_name": "",
                        "active_property_kind": "",
                        "coe_panels": [],
                        "active_representation_path": "",
                        "active_representation_has_properties": False,
                        "ui_active_node_reservoir_type_rep": "",
                        "ui_active_node_reservoir_type": "",
                        "ui_active_node_reservoir_title": "",
                    })
                    _branch = "cleared"
                    return
                node_id = ui_active_node_reservoir[0]
                # Reject activation of a node whose subtree isn't checked.
                # Trame batches the mutation and re-fires this handler with
                # the empty value on next flush, going through the reset
                # branch above.
                if not self._is_node_active_able(node_id, state.ui_select_node_reservoir):
                    state.ui_active_node_reservoir = []
                    _branch = "rejected"
                    return
                _t = time.perf_counter()
                type_node_rep = self._tree.find_representation_type(node_id)
                type_node = self._tree.find_type(node_id)
                title_node = self._tree.find_title(node_id)
                _ms_tree_lookup = _ms(_t)

                # Multi-realization synthetic nodes act as property leaves:
                # the actual array name lives in the propTitle attribute
                # (resolved below). Plain TimeSeries nodes are also property
                # leaves (one per property title, the per-timestep nodes were
                # collapsed in C++ searchProperties).
                is_multireal = type_node in ("MultiRealization", "MultiRealizationTimeSeries")
                is_property = bool(
                    type_node and (
                        "Property" in type_node
                        or is_multireal
                        or type_node == "TimeSeries"
                    )
                )
                ts_ancestor_id = self._tree.find_parent_node_id_with_type(node_id, "TimeSeries")
                is_ts_property = is_property and (
                    ts_ancestor_id is not None or type_node == "MultiRealizationTimeSeries"
                )
                # Resolve the underlying property kind: directly for plain
                # property nodes, via the C++-emitted `propKind` attribute for
                # synthetic TS/MR/MRTS leaves. Drives the editor switch in
                # solid_color_panel (continuous LUT vs categorical list).
                property_kind = ""
                if type_node in ("ContinuousProperty", "DiscreteProperty", "CategoricalProperty"):
                    property_kind = type_node
                elif type_node in ("TimeSeries", "MultiRealization", "MultiRealizationTimeSeries"):
                    pk = self._tree.find_attribute_value(node_id, "propKind")
                    if pk:
                        property_kind = pk
                state.update({
                    "ui_active_node_reservoir_type_rep": type_node_rep,
                    "ui_active_node_reservoir_type": type_node,
                    "ui_active_node_reservoir_title": title_node,
                    "active_property_kind": property_kind,
                    "ptc_show_vcr": is_ts_property,
                    "active_color_array_name": "" if not is_property else state.active_color_array_name,
                    "coe_panels": [] if not is_property else state.coe_panels,
                })

                # Resolve the active representation (UnstructuredGrid, TriangulatedSet, …)
                # and, for non-IjkGrid representations, switch the ParaView active source
                # to its dedicated ExtractBlock proxy. IjkGrid keeps its slicer-based flow.
                rep_node_id = self._tree.find_representation_node(node_id)
                rep_block_path = ""
                rep_type = None
                rep_source = None
                rep_has_properties = False
                if rep_node_id is not None:
                    rep_type = self._tree.find_type(rep_node_id)
                    rep_has_properties = self._tree.has_property_descendant(rep_node_id)
                    block_path = self._tree.find_path(rep_node_id)
                    if block_path:
                        rep_block_path = block_path
                        if rep_type != 'IjkGrid' and self._rep_sources is not None:
                            rep_source = self._rep_sources.get(block_path)
                            if rep_source is not None:
                                pvsimple.SetActiveSource(rep_source)
                                try:
                                    controller.on_active_proxy_change()
                                except Exception:
                                    pass
                state.active_representation_has_properties = rep_has_properties
                state.active_representation_path = rep_block_path

                # Handle multi-realization nodes (single tree node, slider drives
                # the source's RealizationIndex which the C++ layer uses to swap
                # the property values without renaming arrays).
                if type_node in ("MultiRealization", "MultiRealizationTimeSeries"):
                    is_ts = type_node == "MultiRealizationTimeSeries"
                    state.realization_parent_node_id = node_id
                    state.realization_ts_node_id = node_id if is_ts else None
                    if is_ts:
                        state.ptc_show_vcr = True

                    range_min = self._tree.find_attribute_value(node_id, "minvalue")
                    range_max = self._tree.find_attribute_value(node_id, "maxvalue")
                    if range_min is not None and range_max is not None:
                        try:
                            self._realization_locked_range = (float(range_min), float(range_max))
                        except (ValueError, TypeError):
                            self._realization_locked_range = None
                    else:
                        self._realization_locked_range = None

                    # Real indices CSV from C++ (e.g. "23,24"). Fall back to 0..N-1
                    # when the attribute is missing (older data with sequential indices).
                    indices_csv = self._tree.find_attribute_value(node_id, "realization_indices")
                    realization_count_str = self._tree.find_attribute_value(node_id, "realization_count")
                    try:
                        realization_count = int(realization_count_str) if realization_count_str else 1
                    except (ValueError, TypeError):
                        realization_count = 1

                    if indices_csv:
                        labels = [s.strip() for s in indices_csv.split(",") if s.strip()]
                    else:
                        labels = [str(i) for i in range(realization_count)]
                    if not labels:
                        labels = ["0"]

                    state.ui_range_real = [0, max(0, len(labels) - 1)]
                    # Lock carries the *value* (e.g. "23") so it survives switches
                    # between properties whose index sets differ.
                    initial_index = 0
                    if state.ui_slices_real_locked and getattr(state, 'ui_slices_real_locked_value', None) is not None:
                        locked_value = str(state.ui_slices_real_locked_value)
                        if locked_value in labels:
                            initial_index = labels.index(locked_value)
                    state.realization_selected_index = initial_index
                    state.ui_slices_real = initial_index
                    state.realization_labels = labels

                else:
                    # Clear realization state for non-Realization nodes
                    state.realization_selected_index = 0
                    state.realization_parent_node_id = None
                    state.ui_range_real = [0, 0]
                    state.ui_slices_real = 0
                    state.realization_labels = []
                    state.realization_ts_node_id = None

                # If a Property node is selected, configure color mapping.
                # Multi-realization synthetic nodes act as property leaves:
                # the C++-emitted array name is in the propTitle attribute
                # (the title attribute holds the vtk-sanitized variant which
                # may differ).
                array_name = title_node
                if is_multireal:
                    prop_title = self._tree.find_attribute_value(node_id, "propTitle")
                    if prop_title:
                        array_name = prop_title
                if is_property and array_name:
                    # Selecting a property is the user's "I want property
                    # coloring on this rep" intent. Flip the chip mode now,
                    # regardless of whether ColorBy below succeeds in this
                    # tick (data may still be loading on a separate thread).
                    if rep_block_path:
                        modes = dict(state.solid_color_mode_by_rep or {})
                        if modes.get(rep_block_path) != "property":
                            modes[rep_block_path] = "property"
                            state.solid_color_mode_by_rep = modes
                        if rep_block_path == state.active_representation_path:
                            state.solid_color_mode = "property"
                    try:
                        active_view = pvsimple.GetActiveView()

                        # Non-IjkGrid: the extracted rep source IS the target. No lookup.
                        target_source = rep_source if (rep_type and rep_type != 'IjkGrid') else None

                        if target_source is None:
                            all_sources = pvsimple.GetSources()

                            # IjkGrid path — find the visible source.
                            # Priority:
                            #   1. rep_data filter (used in volume mode now;
                            #      we bypass slicervolume because PV6's
                            #      vtkExplicitStructuredGridCrop produces
                            #      degenerate output with the IjkGrid input).
                            #   2. sliceri/j/k_* (slice mode, individual axis crops)
                            #   3. slicervolume (legacy fallback if user reverted
                            #      to the old volume slicer flow)
                            #   4. IjkGrid_* (legacy)
                            # The rep_data filter for the IjkGrid is registered
                            # by SetExtractRepPath as `rep<sanitized_path>`
                            # (slashes → underscores).
                            expected_rep_data_name = "rep" + (rep_block_path or "").replace('/', '_')
                            for source_id, source in all_sources.items():
                                if source_id[0] == expected_rep_data_name:
                                    display = pvsimple.GetDisplayProperties(source, view=active_view)
                                    if display and display.Visibility:
                                        target_source = source
                                        break

                            if not target_source:
                                for source_id, source in all_sources.items():
                                    if source_id[0].startswith(('sliceri_', 'slicerj_', 'slicerk_')):
                                        display = pvsimple.GetDisplayProperties(source, view=active_view)
                                        if display and display.Visibility:
                                            target_source = source
                                            break

                            if not target_source:
                                for source_id, source in all_sources.items():
                                    if source_id[0] == 'slicervolume':
                                        display = pvsimple.GetDisplayProperties(source, view=active_view)
                                        if display and display.Visibility:
                                            target_source = source
                                            break

                            if not target_source:
                                for source_id, source in all_sources.items():
                                    if source_id[0].startswith('IjkGrid_'):
                                        display = pvsimple.GetDisplayProperties(source, view=active_view)
                                        if display and display.Visibility:
                                            target_source = source
                                            break

                        if target_source and active_view:
                            target_name = ""
                            for (sid, _), s in pvsimple.GetSources().items():
                                if s is target_source:
                                    target_name = sid
                                    break
                            print(f"[PERF active.reservoir] target={target_name!r} rep_type={rep_type!r}")
                            _t = time.perf_counter()
                            pvsimple.SetActiveSource(target_source)
                            # Force the producer's MTime to advance so the proxy
                            # info cache (otherwise sticky on TrivialProducer when
                            # its output is mutated externally by the C++ side)
                            # is invalidated, then re-run RequestInformation.
                            try:
                                target_source.GetClientSideObject().Modified()
                            except Exception:
                                pass
                            target_source.UpdatePipelineInformation()
                            target_source.UpdatePipeline()
                            _ms_pipeline_pre = _ms(_t)
                            display = pvsimple.GetDisplayProperties(target_source, view=active_view)

                            if display:
                                # Query the underlying VTK object directly — the
                                # proxy info cache (target_source.GetCellDataInformation)
                                # is unreliable when arrays were added in place
                                # by the C++ pipeline. Going through the
                                # client-side VTK object is always fresh.
                                # The rep_data filter outputs single-piece
                                # (vtkPolyData / vtkUnstructuredGrid /
                                # vtkExplicitStructuredGrid). _drill_to_inner
                                # is a no-op for these — kept defensively in
                                # case a downstream change ever wraps the
                                # output in a composite.
                                vtk_out = target_source.GetClientSideObject().GetOutputDataObject(0)
                                vtk_inner = _drill_to_inner(vtk_out)
                                vtk_cd = vtk_inner.GetCellData() if vtk_inner is not None and hasattr(vtk_inner, 'GetCellData') else None
                                vtk_pd = vtk_inner.GetPointData() if vtk_inner is not None and hasattr(vtk_inner, 'GetPointData') else None
                                cell_arr = _find_array_in_store(vtk_cd, array_name)
                                pt_arr = _find_array_in_store(vtk_pd, array_name)
                                has_cell = cell_arr is not None
                                has_pt = pt_arr is not None
                                # If the array was found via the sanitized
                                # name (spaces/specials stripped), use that
                                # form for ColorBy / GetColorTransferFunction.
                                if has_cell or has_pt:
                                    found_arr = cell_arr if has_cell else pt_arr
                                    if found_arr is not None:
                                        actual_name = found_arr.GetName()
                                        if actual_name and actual_name != array_name:
                                            array_name = actual_name
                                # When the slicer's CellData doesn't have the
                                # array, dump everything we know to diagnose:
                                # walk to the slicer's input (the rep_data
                                # filter for IjkGrid) and check there too.
                                if not has_cell and not has_pt:
                                    cell_names = []
                                    pt_names = []
                                    if vtk_cd:
                                        cell_names = [vtk_cd.GetArrayName(i) for i in range(vtk_cd.GetNumberOfArrays())]
                                    if vtk_pd:
                                        pt_names = [vtk_pd.GetArrayName(i) for i in range(vtk_pd.GetNumberOfArrays())]
                                    target_ncells = vtk_inner.GetNumberOfCells() if vtk_inner is not None and hasattr(vtk_inner, 'GetNumberOfCells') else -1
                                    target_extent = list(vtk_inner.GetExtent()) if vtk_inner is not None and hasattr(vtk_inner, 'GetExtent') else None
                                    output_whole_extent = None
                                    try:
                                        output_whole_extent = list(target_source.OutputWholeExtent) if hasattr(target_source, 'OutputWholeExtent') else None
                                    except Exception:
                                        pass
                                    print(f"[DEBUG active.reservoir] target.NumberOfCells={target_ncells} extent={target_extent} OutputWholeExtent={output_whole_extent}")
                                    print(f"[DEBUG active.reservoir] target.CellData={cell_names} PointData={pt_names}")
                                    try:
                                        upstream = target_source.Input
                                        if upstream is not None:
                                            up_obj = upstream.GetClientSideObject() if hasattr(upstream, 'GetClientSideObject') else None
                                            if up_obj is None and hasattr(upstream, 'GetProducer'):
                                                # OutputPort wrapper case
                                                up_obj = upstream.GetProducer().GetClientSideObject()
                                            if up_obj is not None:
                                                up_out = up_obj.GetOutputDataObject(getattr(upstream, 'Port', 0) if hasattr(upstream, 'Port') else 0)
                                                up_inner = _drill_to_inner(up_out) if up_out is not None else None
                                                up_cd = up_inner.GetCellData() if up_inner is not None and hasattr(up_inner, 'GetCellData') else None
                                                up_cell_names = [up_cd.GetArrayName(i) for i in range(up_cd.GetNumberOfArrays())] if up_cd else []
                                                up_ncells = up_inner.GetNumberOfCells() if up_inner is not None and hasattr(up_inner, 'GetNumberOfCells') else -1
                                                up_extent = list(up_inner.GetExtent()) if up_inner is not None and hasattr(up_inner, 'GetExtent') else None
                                                up_class = up_inner.GetClassName() if up_inner is not None else None
                                                print(f"[DEBUG active.reservoir] upstream class={up_class} NumberOfCells={up_ncells} extent={up_extent}")
                                                print(f"[DEBUG active.reservoir] upstream.CellData={up_cell_names}")
                                    except Exception as _e:
                                        print(f"[DEBUG active.reservoir] upstream inspect failed: {_e}")
                                print(f"[PERF active.reservoir] array={array_name!r} has_cell={has_cell} has_pt={has_pt}")
                                array_type = None
                                _t = time.perf_counter()
                                if has_cell:
                                    array_type = "CELLS"
                                    pvsimple.ColorBy(display, (array_type, array_name))
                                elif has_pt:
                                    array_type = "POINTS"
                                    pvsimple.ColorBy(display, (array_type, array_name))
                                _ms_colorby = _ms(_t)
                                lut = None
                                if array_type:
                                    # Hide the previous color bar for this rep
                                    # unless another rep still references the
                                    # same array.
                                    prev_array = self._current_array_by_rep.get(rep_block_path)
                                    if prev_array and prev_array != array_name:
                                        still_used = any(
                                            arr == prev_array
                                            for r, arr in self._current_array_by_rep.items()
                                            if r != rep_block_path
                                        )
                                        if not still_used:
                                            try:
                                                prev_lut = pvsimple.GetColorTransferFunction(prev_array)
                                                if prev_lut:
                                                    prev_bar = pvsimple.GetScalarBar(prev_lut, active_view)
                                                    if prev_bar:
                                                        prev_bar.Visibility = 0
                                            except Exception:
                                                pass
                                    self._current_array_by_rep[rep_block_path] = array_name

                                    lut = pvsimple.GetColorTransferFunction(array_name)
                                    if lut:
                                        lut.NanOpacity = _nan_opacity_from_state()
                                        color_bar = pvsimple.GetScalarBar(lut, active_view)
                                        if color_bar:
                                            color_bar.Title = array_name
                                            color_bar.Visibility = 1
                                            color_bar.RangeLabelFormat = '%-#6.3g'
                                            color_bar.Resizable = 1

                                _t = time.perf_counter()
                                target_source.UpdatePipeline()
                                _ms_pipeline_post = _ms(_t)

                                _t = time.perf_counter()
                                controller.on_active_proxy_change()
                                _ms_on_active = _ms(_t)
                                # `on_data_loaded` is ParaView-Trame TimeControl's
                                # refresh hook — only useful when activating a
                                # time-series property (the time slider needs to
                                # reset its range / labels). For non-TS property
                                # activations it does heavy Vue work for nothing
                                # (50-100ms in profiling), so skip it.
                                _t = time.perf_counter()
                                if is_ts_property:
                                    controller.on_data_loaded()
                                _ms_on_loaded = _ms(_t)
                                _t = time.perf_counter()
                                controller.update_color_editor(array_name)
                                _ms_update_coe = _ms(_t)

                                # Force the LUT range LAST, after every other
                                # caller (ColorBy internal, on_active_proxy_change,
                                # update_color_editor) has had a chance to touch
                                # it. The proxy info cache used by their internal
                                # RescaleTransferFunctionToDataRange is stale for
                                # arrays added in place by the C++ pipeline, so
                                # they silently fall back to [0,1] which makes
                                # the rendering look like Solid mode. Computing
                                # the range directly from the VTK array and
                                # pushing it as the very last operation guarantees
                                # nothing else can override it within this tick.
                                if array_type and lut is not None:
                                    try:
                                        vtk_arr = vtk_cd.GetArray(array_name) if has_cell else vtk_pd.GetArray(array_name)
                                        if vtk_arr is not None:
                                            rng = vtk_arr.GetRange()
                                            if rng[0] < rng[1]:
                                                lut.RescaleTransferFunction(float(rng[0]), float(rng[1]))
                                    except Exception:
                                        pass

                                # Single Render at the very end — after all
                                # LUT/ColorBy/cache mutations have settled.
                                _t = time.perf_counter()
                                pvsimple.Render(view=active_view)
                                _ms_render = _ms(_t)
                    except Exception as e:
                        print(f"[WARNING] Could not configure color mapping for property {array_name}: {e}")
                        import traceback
                        traceback.print_exc()
                _branch = "property" if (is_property and array_name) else "non-property"
            finally:
                # Always print timing — fires for cleared/rejected/property/
                # non-property paths so we can see the full activation cost.
                _ms_total = _ms(_t_total)
                print(
                    f"[PERF active.reservoir] branch={_branch} "
                    f"tree_lookup={_ms_tree_lookup}ms "
                    f"pipeline_pre={_ms_pipeline_pre}ms "
                    f"colorby={_ms_colorby}ms "
                    f"pipeline_post={_ms_pipeline_post}ms "
                    f"on_active={_ms_on_active}ms "
                    f"on_loaded={_ms_on_loaded}ms "
                    f"update_coe={_ms_update_coe}ms "
                    f"render={_ms_render}ms "
                    f">>> TOTAL={_ms_total}ms"
                )

        @state.change("ui_active_node_surface")
        def on_ui_active_node_surface_change(ui_active_node_surface, **kwargs):
            if ui_active_node_surface and len(ui_active_node_surface) > 0:
                node_id = ui_active_node_surface[0]
                if not self._is_node_active_able(node_id, state.ui_select_node_surface):
                    state.ui_active_node_surface = []
                    return
                type_node = self._tree.find_type(node_id)

                state.update({
                    "ui_active_node_surface_type": type_node,
                })
                self._activate_rep_source(node_id)
            else:
                state.update({
                    "ui_active_node_surface_type": "",
                })
                state.active_representation_path = ""
                state.active_representation_has_properties = False

        @state.change("ui_active_node_well")
        def on_ui_active_node_well_change(ui_active_node_well, **kwargs):
            if ui_active_node_well and len(ui_active_node_well) > 0:
                node_id = ui_active_node_well[0]
                if not self._is_node_active_able(node_id, state.ui_select_node_well):
                    state.ui_active_node_well = []
                    return
                type_node = self._tree.find_type(node_id)

                state.update({
                    "ui_active_node_well_type": type_node,
                })
                self._activate_rep_source(node_id)
            else:
                state.update({
                    "ui_active_node_well_type": "",
                })
                state.active_representation_path = ""
                state.active_representation_has_properties = False

        # Stash the three handlers as instance attributes so refresh_active()
        # below can re-run them directly without going through state mutation
        # (which Trame would batch / coalesce into a no-op).
        self._reservoir_active_handler = on_ui_active_node_reservoir_change
        self._surface_active_handler = on_ui_active_node_surface_change
        self._well_active_handler = on_ui_active_node_well_change

    def notify_active_reps(self, current_rep_paths):
        """Hide the color bars of reps that are no longer in the active
        selection. Called by the engine after the load + sync, so we can
        clean up stale color bars left behind when the user switches between
        reps (e.g., between two IjkGrids — without this, both grids' bars
        stack in the view).

        Only hides a bar if NO other still-present rep references the same
        array (multiple reps can share a LUT/bar)."""
        if not self._current_array_by_rep:
            return
        view = pvsimple.GetActiveView()
        if view is None:
            return
        present = set(current_rep_paths or [])
        gone = [r for r in list(self._current_array_by_rep.keys()) if r not in present]
        for rep_path in gone:
            arr_name = self._current_array_by_rep.pop(rep_path, None)
            if not arr_name:
                continue
            still_used = any(
                a == arr_name
                for r, a in self._current_array_by_rep.items()
                if r in present
            )
            if still_used:
                continue
            try:
                lut = pvsimple.GetColorTransferFunction(arr_name)
                if lut is not None:
                    bar = pvsimple.GetScalarBar(lut, view)
                    if bar is not None:
                        bar.Visibility = 0
            except Exception:
                pass

    def refresh_active(self):
        """Re-run the active-node handlers for whatever is currently active.
        Used after a manual Show: the active state changed BEFORE the load
        (so the rep didn't exist when the @state.change fired and the ColorBy
        wiring short-circuited). Now that the rep exists we want to re-run
        the same logic.

        Skip the call when the active node is not consistent with the current
        selection — VTreeview's `update_selected` will sync ui_active to the
        new value on the next flush and the handler will fire then. Without
        this guard we'd cause a wasted reject → reset → cleared → property
        chain (3 handler fires) for every grid switch.
        """
        try:
            active = state.ui_active_node_reservoir
            if active and self._is_node_active_able(active[0], state.ui_select_node_reservoir):
                self._reservoir_active_handler(active)
        except Exception as e:
            print(f"[WARNING] refresh_active reservoir failed: {e}")
            import traceback
            traceback.print_exc()
        try:
            active = state.ui_active_node_surface
            if active and self._is_node_active_able(active[0], state.ui_select_node_surface):
                self._surface_active_handler(active)
        except Exception as e:
            print(f"[WARNING] refresh_active surface failed: {e}")
            import traceback
            traceback.print_exc()
        try:
            active = state.ui_active_node_well
            if active and self._is_node_active_able(active[0], state.ui_select_node_well):
                self._well_active_handler(active)
        except Exception as e:
            print(f"[WARNING] refresh_active well failed: {e}")
            import traceback
            traceback.print_exc()

    def _set_active_block_selector(self, path: str):
        """Set BlockSelectors on the active representation to the given assembly path."""
        try:
            view = pvsimple.GetActiveView()
            source = pvsimple.GetActiveSource()
            if view and source:
                display = pvsimple.GetDisplayProperties(source, view=view)
                if display:
                    display.BlockSelectors = [path]
        except Exception:
            pass

    def _activate_rep_source(self, node_id):
        """Set active_representation_path and activate the matching extracted
        source for a surface/well tree node. IjkGrid is never expected here."""
        rep_node_id = self._tree.find_representation_node(node_id)
        if rep_node_id is None:
            state.active_representation_path = ""
            state.active_representation_has_properties = False
            return
        block_path = self._tree.find_path(rep_node_id)
        state.active_representation_has_properties = self._tree.has_property_descendant(rep_node_id)
        state.active_representation_path = block_path or ""
        if not block_path or self._rep_sources is None:
            return
        rep_source = self._rep_sources.get(block_path)
        if rep_source is not None:
            try:
                pvsimple.SetActiveSource(rep_source)
                try:
                    controller.on_active_proxy_change()
                except Exception:
                    pass
            except Exception:
                pass
