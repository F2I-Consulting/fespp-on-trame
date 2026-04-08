import re

from trame.app import get_server
from paraview import simple as pvsimple

from fespp_on_trame.app.core.fespp_tree import Tree

server = get_server()
state = server.state
controller = server.controller

class Activator:
    def __init__(self, tree: Tree):
        self._tree = tree
        
        state.setdefault("ui_active_node_reservoir", [])
        state.setdefault("ui_active_node_surface", [])
        state.setdefault("ui_active_node_well", [])

        # Realization widget state
        state.setdefault("realization_list", [])
        state.setdefault("realization_selected_index", 0)
        state.setdefault("realization_play", False)
        state.setdefault("realization_parent_node_id", None)

        # Locked LUT range for consistent legend across realizations: (min, max) or None
        self._realization_locked_range = None

        @state.change("ui_active_node_reservoir")
        def on_ui_active_node_reservoir_change(ui_active_node_reservoir, **kwargs):
            if not ui_active_node_reservoir or len(ui_active_node_reservoir) == 0:
                state.ptc_show_vcr = False
                state.active_color_array_name = ""
                state.coe_panels = []
                return
            if ui_active_node_reservoir and len(ui_active_node_reservoir) > 0:
                node_id = ui_active_node_reservoir[0]
                type_node_rep = self._tree.find_representation_type(node_id)
                type_node = self._tree.find_type(node_id)
                title_node = self._tree.find_title(node_id)

                is_property = bool(type_node and "Property" in type_node)
                state.update({
                    "ui_active_node_reservoir_type_rep": type_node_rep,
                    "ui_active_node_reservoir_type": type_node,
                    "ui_active_node_reservoir_title": title_node,
                    "ptc_show_vcr": type_node == "TimeSeries",
                    "active_color_array_name": "" if not is_property else state.active_color_array_name,
                    "coe_panels": [] if not is_property else state.coe_panels,
                })

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
                    children = self._tree.get_realization_children(node_id)
                    state.realization_list = children
                    state.realization_parent_node_id = node_id

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
                else:
                    # Clear realization state for non-Realization nodes
                    state.realization_list = []
                    state.realization_selected_index = 0
                    state.realization_parent_node_id = None
                    state.realization_play = False
                    state.ui_range_real = [0, 0]
                    state.ui_slices_real = 0
                    state.realization_labels = []

                # If a Property node is selected, configure color mapping
                if type_node and "Property" in type_node and title_node:
                    try:
                        all_sources = pvsimple.GetSources()
                        active_view = pvsimple.GetActiveView()

                        # Find the visible source (priority: slicervolume > slicers > IjkGrid_*)
                        target_source = None

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
                                        lut.NanOpacity = 0.2
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
            else:
                state.update({
                    "ui_active_node_surface_type": "",
                })
    
        @state.change("ui_active_node_well")
        def on_ui_active_node_well_change(ui_active_node_well, **kwargs):
            if ui_active_node_well and len(ui_active_node_well) > 0:
                node_id = ui_active_node_well[0]
                type_node = self._tree.find_type(node_id)
                
                state.update({
                    "ui_active_node_well_type": type_node,
                })
            else:
                state.update({
                    "ui_active_node_well_type": "",
                })

    def _activate_realization(self, realization_child):
        """Apply property coloring for a specific realization child."""
        if not realization_child:
            return

        # The VTK array name is the full label (e.g. "MultiRealizationsProp_real0"), not just the title
        property_title = realization_child["label"]

        try:
            active_view = pvsimple.GetActiveView()
            all_sources = pvsimple.GetSources()

            # Find visible source (priority: slicervolume > slicers > IjkGrid_*)
            target_source = None

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

            if target_source and active_view:
                pvsimple.SetActiveSource(target_source)
                display = pvsimple.GetDisplayProperties(target_source, view=active_view)

                if display:
                    # Update pipeline first so new realization data is available
                    target_source.UpdatePipeline()

                    # Try CELLS, then POINTS
                    cell_info = target_source.GetCellDataInformation()
                    point_info = target_source.GetPointDataInformation()

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
                            lut.NanOpacity = 0.2
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

                    pvsimple.Render(view=active_view)
                    controller.on_active_proxy_change()
                    controller.on_data_loaded()
                    controller.update_color_editor(property_title)

        except Exception as e:
            import traceback
            print(f"[WARNING] _activate_realization failed for '{property_title}': {e}")
            traceback.print_exc()
