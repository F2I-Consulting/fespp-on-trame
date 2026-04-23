from trame.app import get_server
from paraview import simple as pvsimple

from fespp_on_trame.app.core.fespp_tree import Tree

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

class Activator:
    def __init__(self, tree: Tree, rep_sources=None):
        self._tree = tree
        self._rep_sources = rep_sources
        
        state.setdefault("ui_active_node_reservoir", [])
        state.setdefault("ui_active_node_surface", [])
        state.setdefault("ui_active_node_well", [])
        state.setdefault("ui_active_node_reservoir_type_rep", "")
        state.setdefault("ui_active_node_reservoir_type", "")
        state.setdefault("ui_active_node_reservoir_title", "")

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

        @state.change("ui_active_node_reservoir")
        def on_ui_active_node_reservoir_change(ui_active_node_reservoir, **kwargs):
            if not ui_active_node_reservoir or len(ui_active_node_reservoir) == 0:
                state.ptc_show_vcr = False
                state.active_color_array_name = ""
                state.coe_panels = []
                state.active_representation_path = ""
                state.active_representation_has_properties = False
                return
            if ui_active_node_reservoir and len(ui_active_node_reservoir) > 0:
                node_id = ui_active_node_reservoir[0]
                type_node_rep = self._tree.find_representation_type(node_id)
                type_node = self._tree.find_type(node_id)
                title_node = self._tree.find_title(node_id)

                # Multi-realization nodes (Realization / RealizationTimeSeries) act as
                # property leaves: their label IS the array name produced by the C++ layer.
                is_multireal = type_node in ("Realization", "RealizationTimeSeries")
                is_property = bool(type_node and ("Property" in type_node or is_multireal))
                ts_ancestor_id = self._tree.find_parent_node_id_with_type(node_id, "TimeSeries")
                is_ts_property = is_property and (
                    ts_ancestor_id is not None or type_node == "RealizationTimeSeries"
                )
                state.update({
                    "ui_active_node_reservoir_type_rep": type_node_rep,
                    "ui_active_node_reservoir_type": type_node,
                    "ui_active_node_reservoir_title": title_node,
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
                if type_node in ("Realization", "RealizationTimeSeries"):
                    is_ts = type_node == "RealizationTimeSeries"
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
                # Multi-realization nodes (Realization / RealizationTimeSeries) act
                # as property leaves: their array name lives in the propTitle
                # attribute (find_title would yield "TimeSeries_<name>" for the TS
                # variant since it splits on the first underscore).
                array_name = title_node
                if is_multireal:
                    prop_title = self._tree.find_attribute_value(node_id, "propTitle")
                    if prop_title:
                        array_name = prop_title
                if is_property and array_name:
                    try:
                        active_view = pvsimple.GetActiveView()

                        # Non-IjkGrid: the extracted rep source IS the target. No lookup.
                        target_source = rep_source if (rep_type and rep_type != 'IjkGrid') else None

                        if target_source is None:
                            all_sources = pvsimple.GetSources()

                            # IjkGrid path — find the visible source
                            # (priority: slicervolume > slicers > IjkGrid_*)
                            for source_id, source in all_sources.items():
                                if source_id[0] == 'slicervolume':
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
                                    if source_id[0].startswith('IjkGrid_'):
                                        display = pvsimple.GetDisplayProperties(source, view=active_view)
                                        if display and display.Visibility:
                                            target_source = source
                                            break

                        if target_source and active_view:
                            pvsimple.SetActiveSource(target_source)
                            # Force pipeline update BEFORE reading data information so
                            # the ExtractBlock has actually pulled the upstream array.
                            target_source.UpdatePipelineInformation()
                            target_source.UpdatePipeline()
                            display = pvsimple.GetDisplayProperties(target_source, view=active_view)

                            if display:
                                cell_info = target_source.GetCellDataInformation()
                                pt_info = target_source.GetPointDataInformation()
                                array_info = cell_info
                                array_type = None
                                if array_info and array_info.GetArray(array_name):
                                    array_type = "CELLS"
                                    pvsimple.ColorBy(display, (array_type, array_name))
                                else:
                                    array_info = pt_info
                                    if array_info and array_info.GetArray(array_name):
                                        array_type = "POINTS"
                                        pvsimple.ColorBy(display, (array_type, array_name))

                                if array_type:
                                    lut = pvsimple.GetColorTransferFunction(array_name)
                                    if lut:
                                        lut.NanOpacity = _nan_opacity_from_state()
                                        display.RescaleTransferFunctionToDataRange(True)
                                        color_bar = pvsimple.GetScalarBar(lut, active_view)
                                        if color_bar:
                                            color_bar.Visibility = 1
                                            color_bar.RangeLabelFormat = '%-#6.3g'
                                            color_bar.Resizable = 1

                                target_source.UpdatePipeline()
                                pvsimple.Render(view=active_view)
                                controller.on_active_proxy_change()
                                controller.on_data_loaded()
                                controller.update_color_editor(array_name)
                    except Exception as e:
                        print(f"[WARNING] Could not configure color mapping for property {array_name}: {e}")
                        import traceback
                        traceback.print_exc()
            else:
                state.update({
                    "ui_active_node_reservoir_type_rep": "",
                    "ui_active_node_reservoir_type": "",
                    "ui_active_node_reservoir_title": "",
                })

        @state.change("ui_active_node_surface")
        def on_ui_active_node_surface_change(ui_active_node_surface, **kwargs):
            if ui_active_node_surface and len(ui_active_node_surface) > 0:
                node_id = ui_active_node_surface[0]
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
