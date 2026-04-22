import re

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
        state.setdefault("realization_list", [])
        state.setdefault("realization_selected_index", 0)
        state.setdefault("realization_play", False)
        state.setdefault("realization_parent_node_id", None)
        state.setdefault("realization_ts_node_id", None)  # Set when a RealizationTimeSeries node is active

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

                is_property = bool(type_node and "Property" in type_node)
                ts_ancestor_id = self._tree.find_parent_node_id_with_type(node_id, "TimeSeries")
                is_ts_property = is_property and ts_ancestor_id is not None
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
                            print(f"[DEBUG RepresentBy] reservoir activate: path={block_path!r} rep_type={rep_type!r} rep_source={rep_source}")
                            if rep_source is not None:
                                pvsimple.SetActiveSource(rep_source)
                                print(f"[DEBUG RepresentBy] SetActiveSource OK; current active={pvsimple.GetActiveSource()}")
                                try:
                                    controller.on_active_proxy_change()
                                except Exception as _e:
                                    print(f"[DEBUG RepresentBy] on_active_proxy_change failed: {_e}")
                            else:
                                print(f"[DEBUG RepresentBy] no extracted source for {block_path!r} — RepresentBy will stay on previous proxy")
                state.active_representation_has_properties = rep_has_properties
                state.active_representation_path = rep_block_path

                # Handle Realization node activation
                if type_node == "Realization":
                    state.realization_play = False  # Stop any animation
                    # Try to read global range from FESPP assembly attributes
                    range_min = self._tree.find_attribute_value(node_id, "minvalue")
                    range_max = self._tree.find_attribute_value(node_id, "maxvalue")
                    if range_min is not None and range_max is not None:
                        try:
                            self._realization_locked_range = (float(range_min), float(range_max))
                        except (ValueError, TypeError):
                            self._realization_locked_range = None
                    else:
                        self._realization_locked_range = None  # Will be set on first activation
                    state.realization_ts_node_id = None  # Pure Realization, not TimeSeries
                    children = self._tree.get_realization_children(node_id)
                    state.realization_list = children
                    state.realization_parent_node_id = node_id

                    # Enable VCR if children are TimeSeries (Realization+TimeSeries case)
                    has_ts_children = any(c.get("prop_title") is not None for c in children)
                    if has_ts_children:
                        state.ptc_show_vcr = True

                    if len(children) > 0:
                        state.ui_range_real = [0, len(children) - 1]  # 0-based indices

                        # Restore locked value if realization is locked, otherwise start at 0
                        initial_index = 0
                        if state.ui_slices_real_locked and hasattr(state, 'ui_slices_real_locked_value') and state.ui_slices_real_locked_value is not None:
                            locked_value = state.ui_slices_real_locked_value
                            if 0 <= locked_value < len(children):
                                initial_index = locked_value

                        state.realization_selected_index = initial_index
                        state.ui_slices_real = initial_index

                        # Extract realization numbers from titles (e.g., "real1" -> "1", "real6" -> "6")
                        realization_labels = []
                        for child in children:
                            title = child.get("title", "")
                            # Extract number from title (assumes format like "real1", "real6", etc.)
                            match = re.search(r'\d+', title)
                            if match:
                                realization_labels.append(match.group())
                            else:
                                realization_labels.append(str(len(realization_labels)))
                        state.realization_labels = realization_labels

                        self._activate_realization(children[initial_index])
                    else:
                        state.realization_list = []
                        state.realization_selected_index = 0
                        state.ui_range_real = [0, 0]
                        state.ui_slices_real = 0
                        state.realization_labels = []

                elif type_node == "RealizationTimeSeries":
                    # Leaf node combining Realization + TimeSeries.
                    # The C++ layer loads (currentRealizationIndex, currentTimesStepIndex).
                    # Python only needs to set up the realization slider.
                    state.realization_play = False
                    state.realization_list = []  # No children — slider drives RealizationIndex
                    state.realization_parent_node_id = node_id
                    state.realization_ts_node_id = node_id  # Track for slider updates

                    range_min = self._tree.find_attribute_value(node_id, "minvalue")
                    range_max = self._tree.find_attribute_value(node_id, "maxvalue")
                    if range_min is not None and range_max is not None:
                        try:
                            self._realization_locked_range = (float(range_min), float(range_max))
                        except (ValueError, TypeError):
                            self._realization_locked_range = None
                    else:
                        self._realization_locked_range = None

                    # Read realization count stored as an assembly attribute
                    realization_count_str = self._tree.find_attribute_value(node_id, "realization_count")
                    try:
                        realization_count = int(realization_count_str) if realization_count_str else 1
                    except (ValueError, TypeError):
                        realization_count = 1

                    state.ui_range_real = [0, max(0, realization_count - 1)]
                    initial_index = 0
                    if state.ui_slices_real_locked and hasattr(state, 'ui_slices_real_locked_value') and state.ui_slices_real_locked_value is not None:
                        locked_value = state.ui_slices_real_locked_value
                        if 0 <= locked_value < realization_count:
                            initial_index = locked_value
                    state.realization_selected_index = initial_index
                    state.ui_slices_real = initial_index
                    state.realization_labels = [str(i) for i in range(realization_count)]

                else:
                    # Clear realization state for non-Realization nodes
                    state.realization_list = []
                    state.realization_selected_index = 0
                    state.realization_parent_node_id = None
                    state.realization_play = False
                    state.ui_range_real = [0, 0]
                    state.ui_slices_real = 0
                    state.realization_labels = []
                    state.realization_ts_node_id = None

                # If a Property node is selected, configure color mapping
                if type_node and "Property" in type_node and title_node:
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
                            display = pvsimple.GetDisplayProperties(target_source, view=active_view)

                            if display:
                                array_info = target_source.GetCellDataInformation()
                                array_type = None
                                if array_info and array_info.GetArray(title_node):
                                    array_type = "CELLS"
                                    pvsimple.ColorBy(display, (array_type, title_node))
                                else:
                                    array_info = target_source.GetPointDataInformation()
                                    if array_info and array_info.GetArray(title_node):
                                        array_type = "POINTS"
                                        pvsimple.ColorBy(display, (array_type, title_node))

                                if array_type:
                                    lut = pvsimple.GetColorTransferFunction(title_node)
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
                                controller.update_color_editor(title_node)
                    except Exception as e:
                        print(f"[WARNING] Could not configure color mapping for property {title_node}: {e}")
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
            print(f"[DEBUG RepresentBy] _activate_rep_source: no block_path or no rep_sources (path={block_path!r})")
            return
        rep_source = self._rep_sources.get(block_path)
        print(f"[DEBUG RepresentBy] _activate_rep_source: path={block_path!r} rep_source={rep_source}")
        if rep_source is not None:
            try:
                pvsimple.SetActiveSource(rep_source)
                print(f"[DEBUG RepresentBy] _activate_rep_source: SetActiveSource OK; active={pvsimple.GetActiveSource()}")
                try:
                    controller.on_active_proxy_change()
                except Exception as _e:
                    print(f"[DEBUG RepresentBy] _activate_rep_source: on_active_proxy_change failed: {_e}")
            except Exception as e:
                print(f"[DEBUG RepresentBy] _activate_rep_source: SetActiveSource failed: {e}")
        else:
            print(f"[DEBUG RepresentBy] _activate_rep_source: no extracted source for {block_path!r}")

    def _activate_realization(self, realization_child):
        """Apply property coloring for a specific realization child."""
        if not realization_child:
            return

        # For pure Realization, label IS the VTK array name (e.g. "SOIL_real0").
        # For Realization+TimeSeries, vtk_array_name holds the actual array (e.g. "SOIL_real23")
        # while label is just "Realization_23".
        property_title = realization_child.get("vtk_array_name") or realization_child["label"]

        print(f"[DEBUG _activate_realization] property_title='{property_title}'")
        try:
            active_view = pvsimple.GetActiveView()
            all_sources = pvsimple.GetSources()
            print(f"[DEBUG _activate_realization] sources: {list(k[0] for k in all_sources.keys())}")

            # Find visible source (priority: slicervolume > slicers > IjkGrid_*)
            target_source = None
            used_extract_block = False

            # NEW: prefer the per-representation ExtractBlock for the active rep
            # when we have one (UnstructuredGrid / Grid2d / etc. case). This is
            # the proxy that's actually visible on screen — and it's what
            # ptc.RepresentBy and SolidColorPanel target via SetActiveSource /
            # controller.get_rep_source. Coloring its display is what makes the
            # rendering, the type toggle and the Solid/Property switch coherent.
            if self._rep_sources is not None:
                active_rep_path = state.active_representation_path or ""
                if active_rep_path:
                    rs = self._rep_sources.get(active_rep_path)
                    if rs is not None:
                        # Make sure the extract block has propagated the latest
                        # array data from its upstream collector.
                        try:
                            rs.UpdatePipeline()
                        except Exception:
                            pass
                        target_source = rs
                        used_extract_block = True
                        print(f"[DEBUG _activate_realization] using rep_source ExtractBlock for path={active_rep_path!r}")

            if not target_source:
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

            if not target_source:
                # Fallback: UnstructuredGrid realization data lives directly in the main FESAPI source
                for source_id, source in all_sources.items():
                    if source_id[0] in ['EPCCollector', 'ETP12Store']:
                        display = pvsimple.GetDisplayProperties(source, view=active_view)
                        if display and display.Visibility:
                            target_source = source
                            break

            print(f"[DEBUG _activate_realization] target_source={getattr(target_source, 'GetGlobalIDAsString', lambda: None)() if target_source else None} used_extract_block={used_extract_block}")
            if target_source and active_view:
                pvsimple.SetActiveSource(target_source)
                display = pvsimple.GetDisplayProperties(target_source, view=active_view)

                if display:
                    # Update pipeline first so new realization data is available
                    target_source.UpdatePipeline()

                    # Try CELLS, then POINTS
                    cell_info = target_source.GetCellDataInformation()
                    point_info = target_source.GetPointDataInformation()
                    cell_arrays = [cell_info.GetArray(i).Name for i in range(cell_info.GetNumberOfArrays())] if cell_info else []
                    print(f"[DEBUG _activate_realization] cell arrays: {cell_arrays}")

                    array_type = None
                    if cell_info and cell_info.GetArray(property_title):
                        array_type = "CELLS"
                        pvsimple.ColorBy(display, (array_type, property_title))
                    elif point_info and point_info.GetArray(property_title):
                        array_type = "POINTS"
                        pvsimple.ColorBy(display, (array_type, property_title))

                    if array_type:
                        lut = pvsimple.GetColorTransferFunction(property_title)
                        if lut:
                            lut.NanOpacity = _nan_opacity_from_state()
                            lut.EnableOpacityMapping = 0
                            if self._realization_locked_range is None:
                                # First realization: rescale to data range and lock it
                                display.RescaleTransferFunctionToDataRange(False)
                                rgb_pts = lut.RGBPoints
                                if rgb_pts and len(rgb_pts) >= 8:
                                    self._realization_locked_range = (rgb_pts[0], rgb_pts[-4])
                            else:
                                # Subsequent realizations: restore the locked range
                                lut.RescaleTransferFunction(
                                    self._realization_locked_range[0],
                                    self._realization_locked_range[1]
                                )
                            # Force PWF to full opacity so that if EnableOpacityMapping
                            # is re-enabled externally (e.g. by on_active_proxy_change),
                            # no cell becomes transparent
                            pwf = pvsimple.GetOpacityTransferFunction(property_title)
                            if pwf and len(pwf.Points) >= 8:
                                min_x = pwf.Points[0]
                                max_x = pwf.Points[-4]
                                pwf.Points = [min_x, 1.0, 0.5, 0.0, max_x, 1.0, 0.5, 0.0]
                            color_bar = pvsimple.GetScalarBar(lut, active_view)
                            if color_bar:
                                color_bar.Visibility = 1
                                color_bar.RangeLabelFormat = '%-#6.3g'
                                color_bar.Resizable = 1

                    # Sync BlockSelectors to the block that has the actual dataset.
                    # Only meaningful when coloring the parent multiblock display —
                    # the ExtractBlock proxy is already constrained to its single
                    # rep block via its own Selectors property.
                    if not used_extract_block:
                        child_path = realization_child.get("path")
                        if child_path:
                            if realization_child.get("vtk_array_name") is not None:
                                # Realization+TimeSeries: go up 2 levels to the Representation path
                                # e.g. /data/_uuid/_realization_X/_tsUuidrealts_N_X  →  /data/_uuid
                                parts = child_path.rsplit("/", 2)
                                block_path = parts[0] if len(parts) == 3 else child_path
                            else:
                                block_path = child_path
                            self._set_active_block_selector(block_path)

                    pvsimple.Render(view=active_view)
                    controller.on_active_proxy_change()
                    controller.on_data_loaded()
                    controller.update_color_editor(property_title)
                    # If the user had toggled Solid for this rep before switching
                    # realization, the ColorBy() above just reverted the render
                    # to property — re-assert solid as the final state.
                    if hasattr(controller, "reapply_active_solid_mode"):
                        controller.reapply_active_solid_mode()

        except Exception as e:
            import traceback
            print(f"[WARNING] _activate_realization failed for '{property_title}': {e}")
            traceback.print_exc()
