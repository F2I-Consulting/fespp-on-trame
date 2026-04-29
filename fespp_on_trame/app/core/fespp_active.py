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


def _drill_to_inner(vtk_out):
    """If vtk_out is a vtkPartitionedDataSetCollection (e.g. when dumping the
    EPCCollector output, which is the global multiblock), drill down to the
    first inner partition. Otherwise return as-is. Used by the dump helper
    so it can read CellData/PointData uniformly across source types."""
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


def _debug_dump_sources(label: str):
    """Dump every ParaView source: its data arrays + the color config of its
    display in the active view. Call at key moments in the active handler to
    see what the pipeline actually has versus what we *think* it has."""
    try:
        view = pvsimple.GetActiveView()
        sources = pvsimple.GetSources()
        active = pvsimple.GetActiveSource()
        active_name = ""
        if active is not None:
            for (sid, _), s in sources.items():
                if s is active:
                    active_name = sid
                    break
        print(f"[DUMP {label}] active_source={active_name!r} count={len(sources)}")
        for (sid, _), src in sources.items():
            try:
                vtk_obj = src.GetClientSideObject()
                vtk_out = vtk_obj.GetOutputDataObject(0) if vtk_obj is not None else None
                vtk_inner = _drill_to_inner(vtk_out)
                cd = vtk_inner.GetCellData() if vtk_inner is not None and hasattr(vtk_inner, 'GetCellData') else None
                pd = vtk_inner.GetPointData() if vtk_inner is not None and hasattr(vtk_inner, 'GetPointData') else None
                cell_arrays = []
                if cd is not None:
                    for i in range(cd.GetNumberOfArrays()):
                        a = cd.GetArray(i)
                        if a is not None:
                            rng = a.GetRange()
                            cell_arrays.append(f"{a.GetName()}[{rng[0]:.3g},{rng[1]:.3g}]")
                pt_arrays = []
                if pd is not None:
                    for i in range(pd.GetNumberOfArrays()):
                        a = pd.GetArray(i)
                        if a is not None:
                            rng = a.GetRange()
                            pt_arrays.append(f"{a.GetName()}[{rng[0]:.3g},{rng[1]:.3g}]")
                color_info = "no_view"
                if view is not None:
                    try:
                        disp = pvsimple.GetDisplayProperties(src, view=view)
                        if disp is not None:
                            can = list(disp.ColorArrayName) if disp.ColorArrayName else []
                            vis = bool(disp.Visibility)
                            color_info = f"vis={vis} ColorArrayName={can}"
                            if can and len(can) >= 2 and can[1]:
                                lut = pvsimple.GetColorTransferFunction(can[1])
                                if lut is not None:
                                    try:
                                        rgbpts = list(lut.RGBPoints)
                                        if len(rgbpts) >= 8:
                                            lut_range = [rgbpts[0], rgbpts[-4]]
                                            color_info += f" LUTrange=[{lut_range[0]:.3g},{lut_range[1]:.3g}]"
                                    except Exception:
                                        pass
                    except Exception as _de:
                        color_info = f"display_err={_de}"
                print(f"[DUMP {label}]   src={sid!r} cell={cell_arrays} point={pt_arrays} {color_info}")
            except Exception as _e:
                print(f"[DUMP {label}]   src={sid!r} ERR={_e}")
    except Exception as e:
        print(f"[DUMP {label}] FATAL {e}")

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

        # Saved as attributes (after definition below) so refresh_active()
        # can re-run them directly. Needed because Trame batches state
        # mutations within a flush window — a clear-then-restore on
        # ui_active_node_X collapses to "no change" and the @state.change
        # callback never fires. Calling the handler explicitly bypasses
        # the diff check.
        @state.change("ui_active_node_reservoir")
        def on_ui_active_node_reservoir_change(ui_active_node_reservoir, **kwargs):
            print(f"[DEBUG active.reservoir] enter active={ui_active_node_reservoir}")
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
                print(f"[DEBUG active.reservoir] node_id={node_id} type_node={type_node!r} title={title_node!r} type_rep={type_node_rep!r}")

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
                print(f"[DEBUG active.reservoir] rep_node_id={rep_node_id} rep_type={rep_type!r} rep_block_path={rep_block_path!r} rep_source={'YES' if rep_source else 'None'} has_props={rep_has_properties}")
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
                print(f"[DEBUG active.reservoir] is_property={is_property} is_multireal={is_multireal} array_name={array_name!r}")
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

                        print(f"[DEBUG active.reservoir] target_source={'YES' if target_source else 'None'} active_view={'YES' if active_view else 'None'}")
                        _debug_dump_sources(f"reservoir.before_colorby({array_name})")
                        if target_source and active_view:
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
                                cell_arrays = [vtk_cd.GetArrayName(i) for i in range(vtk_cd.GetNumberOfArrays())] if vtk_cd else []
                                pt_arrays = [vtk_pd.GetArrayName(i) for i in range(vtk_pd.GetNumberOfArrays())] if vtk_pd else []
                                print(f"[DEBUG active.reservoir] looking for array={array_name!r} CellData={cell_arrays} PointData={pt_arrays}")
                                has_cell = vtk_cd is not None and vtk_cd.GetArray(array_name) is not None
                                has_pt = vtk_pd is not None and vtk_pd.GetArray(array_name) is not None
                                array_type = None
                                if has_cell:
                                    array_type = "CELLS"
                                    pvsimple.ColorBy(display, (array_type, array_name))
                                    print(f"[DEBUG active.reservoir] ColorBy CELLS {array_name!r} OK")
                                elif has_pt:
                                    array_type = "POINTS"
                                    pvsimple.ColorBy(display, (array_type, array_name))
                                    print(f"[DEBUG active.reservoir] ColorBy POINTS {array_name!r} OK")
                                if array_type is None:
                                    print(f"[DEBUG active.reservoir] !! array {array_name!r} not found in CellData or PointData → no ColorBy")
                                lut = None
                                if array_type:
                                    lut = pvsimple.GetColorTransferFunction(array_name)
                                    if lut:
                                        lut.NanOpacity = _nan_opacity_from_state()
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
                                                print(f"[DEBUG active.reservoir] LUT range (final) = [{rng[0]}, {rng[1]}]")
                                            else:
                                                print(f"[DEBUG active.reservoir] LUT range degenerate {rng}, skip rescale")
                                    except Exception as _e:
                                        print(f"[DEBUG active.reservoir] LUT rescale fallback failed: {_e}")
                                    # Verify the display's LookupTable points to the LUT we just rescaled
                                    try:
                                        disp_lut = display.LookupTable
                                        same = disp_lut is lut or (disp_lut and lut and disp_lut.SMProxy == lut.SMProxy)
                                        print(f"[DEBUG active.reservoir] display.LookupTable is same as rescaled lut: {same}")
                                    except Exception as _e:
                                        print(f"[DEBUG active.reservoir] LookupTable check failed: {_e}")
                                    # Render AFTER the rescale so the frame uses the
                                    # corrected range. The earlier Render() above ran
                                    # while the LUT was still on its default [0,1]
                                    # (post-ColorBy + on_active_proxy_change garbage),
                                    # which mapped everything to the LUT extreme and
                                    # looked like solid color.
                                    pvsimple.Render(view=active_view)
                                _debug_dump_sources(f"reservoir.after_all({array_name})")
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

        # Stash the three handlers as instance attributes so refresh_active()
        # below can re-run them directly without going through state mutation
        # (which Trame would batch / coalesce into a no-op).
        self._reservoir_active_handler = on_ui_active_node_reservoir_change
        self._surface_active_handler = on_ui_active_node_surface_change
        self._well_active_handler = on_ui_active_node_well_change

    def refresh_active(self):
        """Re-run the active-node handlers for whatever is currently active.
        Used after a manual Apply: the active state changed BEFORE the load
        (so the rep didn't exist when the @state.change fired and the ColorBy
        wiring short-circuited). Now that the rep exists we want to re-run
        the same logic."""
        print(f"[DEBUG refresh_active] enter ui_active_reservoir={state.ui_active_node_reservoir!r} surface={state.ui_active_node_surface!r} well={state.ui_active_node_well!r}")
        try:
            if state.ui_active_node_reservoir:
                print(f"[DEBUG refresh_active] -> reservoir_handler")
                self._reservoir_active_handler(state.ui_active_node_reservoir)
        except Exception as e:
            print(f"[WARNING] refresh_active reservoir failed: {e}")
            import traceback
            traceback.print_exc()
        try:
            if state.ui_active_node_surface:
                print(f"[DEBUG refresh_active] -> surface_handler")
                self._surface_active_handler(state.ui_active_node_surface)
        except Exception as e:
            print(f"[WARNING] refresh_active surface failed: {e}")
            import traceback
            traceback.print_exc()
        try:
            if state.ui_active_node_well:
                print(f"[DEBUG refresh_active] -> well_handler")
                self._well_active_handler(state.ui_active_node_well)
        except Exception as e:
            print(f"[WARNING] refresh_active well failed: {e}")
            import traceback
            traceback.print_exc()
        print(f"[DEBUG refresh_active] done")

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
