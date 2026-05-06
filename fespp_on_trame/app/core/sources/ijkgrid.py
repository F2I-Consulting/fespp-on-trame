from trame.app import get_server
from paraview import simple as pvsimple
from paraview.servermanager import vtkSMPropertyHelper

from fespp_on_trame.app.core.sources.collector import Collector
from fespp_on_trame.app.core.fespp_tree import Tree
from fespp_on_trame.app.core.sources.rep_sources import _apply_default_tint, _find_registered_proxy


server = get_server()
state = server.state
ctrl = server.controller


class IjkGrid:
    """Slicer / volume rendering for the *currently active* IJK grid.
    Owns one rep_data filter (the EnergisticsExtractor on the
    collector) plus an ExplicitStructuredGridCrop per slicer position
    on each axis and one for the volume mode. Only one IJK grid can be
    active at a time; switching grids tears down all sources and
    rebuilds them."""

    def __init__(self, collector: Collector, tree: Tree):
        self._collector = collector
        self._tree = tree
        self._node_id = None
        self._title = None
        self._property_path = None
        self._current_array_type = None
        self._current_property_type = None
        self._current_extent = None  # [x0,x1,y0,y1,z0,z1]

        self._src_extract_init = None
        self._src_slicers_i = []
        self._src_slicers_j = []
        self._src_slicers_k = []
        self._src_slicer_volume = None

        # Threshold pipeline: one Threshold proxy per upstream source
        # (rep_data in range mode; each slicer crop in slice mode).
        # Settings (array / low / high / visible) are shared across the
        # filters so all visible cuts of the active grid use the same
        # threshold.
        self._thresholds = {}  # id(src_proxy) -> Threshold proxy
        self._threshold_assoc = None    # 'CELLS' or 'POINTS'
        self._threshold_array = None    # str, vtk array name
        self._threshold_low = 0.0
        self._threshold_high = 1.0
        self._threshold_visible = False

    def color_array_type(self, name) -> None:
        """Return 'CELLS' / 'POINTS' / 'FIELD' depending on which data
        store of the first I-axis slicer holds the named array."""
        src = self._src_slicers_i[0] if self._src_slicers_i else None
        if src is None:
            return None
        for i in range(src.CellData.GetNumberOfArrays()):
            if src.CellData.GetArray(i).Name == name:
                return 'CELLS'
        for i in range(src.PointData.GetNumberOfArrays()):
            if src.PointData.GetArray(i).Name == name:
                return 'POINTS'
        for i in range(src.FieldData.GetNumberOfArrays()):
            if src.FieldData.GetArray(i).Name == name:
                return 'FIELD'
        return None

    def _all_slice_sources(self):
        return self._src_slicers_i + self._src_slicers_j + self._src_slicers_k

    def _delete_threshold_for(self, src):
        """Delete the Threshold proxy attached to src, if any."""
        if src is None:
            return
        thr = self._thresholds.pop(id(src), None)
        if thr is None:
            return
        view = pvsimple.GetActiveView()
        try:
            pvsimple.Hide(proxy=thr, view=view)
        except Exception:
            pass
        try:
            pvsimple.Delete(thr)
        except Exception:
            pass

    def _delete_all_thresholds(self):
        for thr in list(self._thresholds.values()):
            view = pvsimple.GetActiveView()
            try:
                pvsimple.Hide(proxy=thr, view=view)
            except Exception:
                pass
            try:
                pvsimple.Delete(thr)
            except Exception:
                pass
        self._thresholds = {}

    def _delete_all_sources(self):
        view = pvsimple.GetActiveView()
        pvsimple.SetActiveSource(None)
        # Thresholds reference the slicer/rep_data proxies; delete them
        # FIRST so the upstream Delete calls don't trip on dangling
        # downstream filters.
        self._delete_all_thresholds()
        for src in self._all_slice_sources():
            try:
                pvsimple.Hide(proxy=src, view=view)
                pvsimple.Delete(src)
            except Exception:
                pass
        self._src_slicers_i = []
        self._src_slicers_j = []
        self._src_slicers_k = []
        if self._src_slicer_volume is not None:
            try:
                pvsimple.Hide(proxy=self._src_slicer_volume, view=view)
                pvsimple.Delete(self._src_slicer_volume)
            except Exception:
                pass
            self._src_slicer_volume = None
        if self._src_extract_init is not None:
            try:
                pvsimple.Delete(self._src_extract_init)
            except Exception:
                pass
            self._src_extract_init = None

    def _create_slice_source(self, axis: str, idx: int):
        """Create and return a new ExplicitStructuredGridCrop for
        (axis, idx)."""
        src = pvsimple.ExplicitStructuredGridCrop(
            registrationName=f'slicer{axis}_{idx}',
            Input=self._src_extract_init,
        )
        if self._current_extent:
            src.OutputWholeExtent = list(self._current_extent)
        src.UpdatePipelineInformation()
        view = pvsimple.GetActiveView()
        rep = pvsimple.GetRepresentation(proxy=src, view=view)
        rep.Representation = state.representation_active or 'Surface'
        if self._title and self._current_array_type:
            self.update_colors(src, self._current_array_type, self._title,
                               self._current_property_type)
        return src

    def _sync_slice_sources(self, axis: str, count: int):
        """Ensure exactly `count` slicer sources exist for the given
        axis."""
        if self._src_extract_init is None:
            return
        srcs = getattr(self, f'_src_slicers_{axis}')
        while len(srcs) < count:
            src = self._create_slice_source(axis, len(srcs))
            srcs.append(src)
            # If a threshold is currently active, attach one to the new slicer.
            if self._threshold_visible and self._threshold_array:
                self._create_threshold_for(src)
        view = pvsimple.GetActiveView()
        while len(srcs) > count:
            src = srcs.pop()
            self._delete_threshold_for(src)
            try:
                pvsimple.Hide(proxy=src, view=view)
                pvsimple.Delete(src)
            except Exception:
                pass

    def set_node_id(self, node_id):
        """Switch the active IJK grid. Passing None tears everything
        down. Passing a node id:
        - If it points to a different IJK grid than the current one,
          delete all sources and rebuild from scratch.
        - Otherwise, treat it as a property change within the same
          grid (refresh ColorBy on every slicer)."""
        if node_id is None:
            if self._node_id is not None:
                self._delete_all_sources()
            self._node_id = None
            return

        ijkgrid_node_id = self._tree.find_parent_node_id_with_type(node_id, 'IjkGrid')
        if ijkgrid_node_id is None:
            return

        if self._node_id != ijkgrid_node_id:
            if self._node_id is not None:
                self._delete_all_sources()

            self._node_id = ijkgrid_node_id
            self._property_path = self._tree.find_path(node_id)
            # Trigger the FESPP-side extract via the proxy property
            # mechanism (same path as RepSources). The producer's
            # output preserves the real VTK type
            # (vtkExplicitStructuredGrid), which
            # ExplicitStructuredGridCrop below requires.
            ijkgrid_rep_path = self._tree.find_path(ijkgrid_node_id)
            coll_proxy = self._collector.get_source().SMProxy
            vtkSMPropertyHelper(coll_proxy, "ExtractRepPath").Set(ijkgrid_rep_path)
            coll_proxy.UpdateVTKObjects()
            coll_proxy.UpdatePropertyInformation()
            reg_name = vtkSMPropertyHelper(coll_proxy, "ExtractedRepProducerName").GetAsString()
            if not reg_name:
                self._node_id = None
                return
            self._src_extract_init = _find_registered_proxy(reg_name)
            if self._src_extract_init is None:
                self._node_id = None
                return

            view = pvsimple.GetActiveView()
            for axis in ('i', 'j', 'k'):
                src = pvsimple.ExplicitStructuredGridCrop(
                    registrationName=f'slicer{axis}_0',
                    Input=self._src_extract_init,
                )
                getattr(self, f'_src_slicers_{axis}').append(src)

            self._src_slicer_volume = pvsimple.ExplicitStructuredGridCrop(
                registrationName='slicervolume',
                Input=self._src_extract_init,
            )

            self._src_extract_init.UpdatePipelineInformation()
            for src in self._all_slice_sources() + [self._src_slicer_volume]:
                src.UpdatePipelineInformation()

            rep_type = state.representation_active or 'Surface'
            grid_color = (state.solid_color_by_rep or {}).get(ijkgrid_rep_path)
            # Configure the rep_data filter's display too — for volume
            # mode we display IT directly instead of slicervolume (PV6's
            # vtkExplicitStructuredGridCrop produces a degenerate 1-cell
            # output even with OutputWholeExtent set to the full grid).
            for src in self._all_slice_sources() + [self._src_slicer_volume, self._src_extract_init]:
                disp = pvsimple.GetRepresentation(proxy=src, view=view)
                disp.Representation = rep_type
                _apply_default_tint(disp, grid_color)

            self.update_block_visibility()
            self.show()

            data_info = self._src_extract_init.GetDataInformation()
            extent = list(data_info.GetExtent())
            self._current_extent = extent

            mid_i = (extent[0] + extent[1]) // 2
            mid_j = (extent[2] + extent[3]) // 2
            mid_k = (extent[4] + extent[5]) // 2

            state.update({
                "ui_range_i": [extent[0], extent[1]],
                "ui_range_j": [extent[2], extent[3]],
                "ui_range_k": [extent[4], extent[5]],
            })
            state.ui_slices_i_list = [mid_i]
            state.ui_slices_j_list = [mid_j]
            state.ui_slices_k_list = [mid_k]
            state.ui_slices_i_visible_list = [True]
            state.ui_slices_j_visible_list = [True]
            state.ui_slices_k_visible_list = [True]
            state.ui_slices_range_i = [extent[0], extent[1]]
            state.ui_slices_range_j = [extent[2], extent[3]]
            state.ui_slices_range_k = [extent[4], extent[5]]

            for src in self._all_slice_sources() + [self._src_slicer_volume]:
                src.OutputWholeExtent = extent
            # The slicers ran their first RequestData via Show() above
            # but at that point OutputWholeExtent was still the default
            # (often empty / invalid), producing an empty output. Now
            # that we've set the real extent, force a re-execute so the
            # cached output reflects the cropped grid (with CellData
            # arrays propagated from the rep_data filter). Without
            # this, the slicer's CellData stays empty until something
            # else triggers UpdatePipeline downstream.
            for src in self._all_slice_sources() + [self._src_slicer_volume]:
                try:
                    src.UpdatePipeline()
                except Exception:
                    pass

        property_title = self._tree.find_title(node_id)
        property_type = self._tree.find_type(node_id)
        if property_title != self._title:
            array_type = self.color_array_type(property_title)
            if array_type is not None:
                self._current_array_type = array_type
                self._current_property_type = property_type
                for src in self._all_slice_sources() + [self._src_slicer_volume]:
                    self.update_colors(src, array_type, property_title, property_type)

            self._title = property_title

            for src in self._all_slice_sources() + [self._src_slicer_volume]:
                src.UpdatePipelineInformation()

            pvsimple.Hide(proxy=self._src_extract_init)
            self.show()

    def _is_range_full_extent(self):
        """True when the range slider equals the grid's full extent. PV6's
        ExplicitStructuredGridCrop produces a degenerate 1-cell output at
        full extent, so we fall back to rep_data in that case (the
        non-cropped equivalent) and only switch to slicervolume once the
        user actually cropped something."""
        if not self._current_extent:
            return True
        full = self._current_extent
        ri = state.ui_slices_range_i or [full[0], full[1]]
        rj = state.ui_slices_range_j or [full[2], full[3]]
        rk = state.ui_slices_range_k or [full[4], full[5]]
        return (
            int(ri[0]) <= full[0] and int(ri[1]) >= full[1]
            and int(rj[0]) <= full[2] and int(rj[1]) >= full[3]
            and int(rk[0]) <= full[4] and int(rk[1]) >= full[5]
        )

    def _primary_range_source(self):
        """The source that's actually rendered in range mode."""
        if self._is_range_full_extent() or self._src_slicer_volume is None:
            return self._src_extract_init
        return self._src_slicer_volume

    def show(self):
        """Show / hide the right combination of sources for the current
        slicer mode. Slice mode displays the per-axis crops; range mode
        displays slicervolume when the slider is on a subset of the grid,
        and rep_data when it spans the full extent (slicervolume's output
        is degenerate at full extent on PV6 — see _is_range_full_extent).

        Fallback: when the user hides every visible slicer (slice mode)
        or the volume eye (range mode), we show rep_data — the parent
        un-cropped grid — instead of leaving an empty view.

        When a threshold is enabled, each "would-be visible" source is
        replaced by its downstream Threshold filter."""
        if self._node_id is None:
            return
        view = pvsimple.GetActiveView()
        use_threshold = bool(self._threshold_visible and self._threshold_array)

        if state.ui_slices_range_mode == 'slice':
            if self._src_slicer_volume is not None:
                pvsimple.Hide(proxy=self._src_slicer_volume, view=view)
                self._hide_threshold_for(self._src_slicer_volume, view)

            vis_i = list(state.ui_slices_i_visible_list or [])
            vis_j = list(state.ui_slices_j_visible_list or [])
            vis_k = list(state.ui_slices_k_visible_list or [])
            any_visible = False
            for axis_srcs, vis_list in (
                (self._src_slicers_i, vis_i),
                (self._src_slicers_j, vis_j),
                (self._src_slicers_k, vis_k),
            ):
                for idx, src in enumerate(axis_srcs):
                    visible = vis_list[idx] if idx < len(vis_list) else True
                    self._show_source_or_threshold(src, view, visible, use_threshold)
                    if visible:
                        any_visible = True

            if self._src_extract_init is not None:
                # Parent fallback: show rep_data when no slicer is visible.
                self._show_source_or_threshold(
                    self._src_extract_init, view, not any_visible, use_threshold,
                )
        else:
            for src in self._all_slice_sources():
                pvsimple.Hide(proxy=src, view=view)
                self._hide_threshold_for(src, view)

            primary = self._primary_range_source()
            volume_visible = bool(getattr(state, 'ui_slices_volume_visible', True))
            # Parent fallback: volume eye OFF means "bypass the crop" —
            # always show rep_data (the un-cropped parent), regardless of
            # whether we were on a subset or full extent.
            if not volume_visible:
                primary = self._src_extract_init
                volume_visible = True

            for s in (self._src_extract_init, self._src_slicer_volume):
                if s is not None and s is not primary:
                    pvsimple.Hide(proxy=s, view=view)
                    self._hide_threshold_for(s, view)
            if primary is not None:
                self._show_source_or_threshold(primary, view, volume_visible, use_threshold)

    def _show_source_or_threshold(self, src, view, visible, use_threshold):
        """Show src OR its downstream Threshold (mutually exclusive),
        gated by the user's eye state for that source."""
        thr = self._thresholds.get(id(src)) if use_threshold else None
        if thr is not None:
            pvsimple.Hide(proxy=src, view=view)
            (pvsimple.Show if visible else pvsimple.Hide)(proxy=thr, view=view)
        else:
            self._hide_threshold_for(src, view)
            (pvsimple.Show if visible else pvsimple.Hide)(proxy=src, view=view)

    def _hide_threshold_for(self, src, view):
        thr = self._thresholds.get(id(src))
        if thr is not None:
            try:
                pvsimple.Hide(proxy=thr, view=view)
            except Exception:
                pass

    def available_arrays(self):
        """Return [(assoc, name), ...] for the active grid's data arrays.
        Used by the engine to populate the threshold VSelect."""
        src = self._src_extract_init
        if src is None:
            return []
        out = []
        seen = set()
        for store_attr, assoc in (("CellData", "CELLS"), ("PointData", "POINTS")):
            try:
                store = getattr(src, store_attr)
                for i in range(store.GetNumberOfArrays()):
                    a = store.GetArray(i)
                    if a is None:
                        continue
                    name = a.Name
                    key = (assoc, name)
                    if name and key not in seen:
                        seen.add(key)
                        out.append(key)
            except Exception:
                pass
        return out

    def array_data_range(self, array_name):
        """Return (min, max) for the named array on the active grid, or
        None if the array isn't found."""
        src = self._src_extract_init
        if src is None or not array_name:
            return None
        for store_attr in ("CellData", "PointData"):
            try:
                store = getattr(src, store_attr)
                for i in range(store.GetNumberOfArrays()):
                    a = store.GetArray(i)
                    if a is not None and a.Name == array_name:
                        rng = a.GetRange()
                        return (float(rng[0]), float(rng[1]))
            except Exception:
                pass
        return None

    def set_threshold(self, array, low, high, visible):
        """Drive the per-source Threshold filters from the UI state.
        Rebuilds the filter set whenever the array changes (Threshold's
        Scalars property can change but it's simpler to recreate, and the
        underlying VTK caches the upstream output)."""
        if self._node_id is None:
            return
        prev_array = self._threshold_array
        new_assoc = None
        if array:
            for assoc, name in self.available_arrays():
                if name == array:
                    new_assoc = assoc
                    break

        self._threshold_array = array if new_assoc else None
        self._threshold_assoc = new_assoc
        self._threshold_low = float(low) if low is not None else 0.0
        self._threshold_high = float(high) if high is not None else 1.0
        self._threshold_visible = bool(visible) and bool(self._threshold_array)

        # Recreate when the array changes — Scalars on Threshold can be
        # mutated in place but recreating side-steps any stale cached
        # output and keeps the registrationName tied to the source id.
        if array != prev_array:
            self._delete_all_thresholds()

        if self._threshold_visible:
            for src in self._sources_for_threshold_attach():
                thr = self._thresholds.get(id(src))
                if thr is None:
                    self._create_threshold_for(src)
                else:
                    self._update_threshold_props(thr)
        self.show()

    def refresh_threshold_pipeline(self):
        """Re-attach thresholds to the current set of "active sources" —
        called when the slicer mode flips (the source set changes)."""
        if not (self._threshold_visible and self._threshold_array):
            self._delete_all_thresholds()
            return
        target_srcs = self._sources_for_threshold_attach()
        target_ids = {id(s) for s in target_srcs}
        for src_id in list(self._thresholds.keys()):
            if src_id not in target_ids:
                thr = self._thresholds.pop(src_id)
                view = pvsimple.GetActiveView()
                try:
                    pvsimple.Hide(proxy=thr, view=view)
                except Exception:
                    pass
                try:
                    pvsimple.Delete(thr)
                except Exception:
                    pass
        for src in target_srcs:
            if id(src) not in self._thresholds:
                self._create_threshold_for(src)
            else:
                self._update_threshold_props(self._thresholds[id(src)])

    def _sources_for_threshold_attach(self):
        # Always attach to rep_data — it's the fallback rendered when
        # the user hides every per-axis slicer (slice mode) or the volume
        # eye (range mode), and we want the threshold to follow.
        out = []
        if self._src_extract_init is not None:
            out.append(self._src_extract_init)
        if state.ui_slices_range_mode == 'slice':
            out.extend(self._all_slice_sources())
        else:
            if self._src_slicer_volume is not None:
                out.append(self._src_slicer_volume)
        return out

    def _create_threshold_for(self, src):
        if src is None or not self._threshold_array or not self._threshold_assoc:
            return None
        try:
            thr = pvsimple.Threshold(
                registrationName=f"thr_{id(src)}",
                Input=src,
            )
        except Exception as e:
            print(f"[WARNING] Threshold creation failed: {e}")
            return None
        self._thresholds[id(src)] = thr
        self._update_threshold_props(thr)
        # Mirror the source's CURRENT display state (representation,
        # ColorArrayName, LUT, scale) directly. self._title only tracks
        # the property the IjkGrid was loaded with (set_node_id) — it's
        # stale after the user switches active property through the
        # tree eye, so reading the source's display is the authoritative
        # source.
        view = pvsimple.GetActiveView()
        try:
            src_disp = pvsimple.GetDisplayProperties(src, view=view)
            thr_disp = pvsimple.GetRepresentation(proxy=thr, view=view)
            if src_disp is not None and thr_disp is not None:
                for attr, as_list in (
                    ("Representation", False),
                    ("Scale", True),
                    ("ColorArrayName", True),
                    ("LookupTable", False),
                ):
                    try:
                        val = getattr(src_disp, attr)
                        if as_list:
                            val = list(val)
                        setattr(thr_disp, attr, val)
                    except Exception:
                        pass
        except Exception:
            pass
        return thr

    def _update_threshold_props(self, thr):
        if thr is None or not self._threshold_array or not self._threshold_assoc:
            return
        try:
            thr.Scalars = [self._threshold_assoc, self._threshold_array]
            thr.LowerThreshold = float(self._threshold_low)
            thr.UpperThreshold = float(self._threshold_high)
            thr.UpdatePipeline()
        except Exception as e:
            print(f"[WARNING] Threshold property update failed: {e}")

    def all_threshold_sources(self):
        """Used by the engine / activator to walk threshold proxies."""
        return list(self._thresholds.values())

    def _nan_opacity_from_state(self):
        """Read NaN opacity from state.nan_color (#RRGGBBAA), default 0.2."""
        try:
            hex_val = (state.nan_color or "").lstrip("#")
            if len(hex_val) >= 8:
                return int(hex_val[6:8], 16) / 255
        except (ValueError, IndexError):
            pass
        return 0.2

    def update_colors(self, src, array_type, property_title, property_type):
        """Apply a ColorBy on a single slicer source: set the lookup
        table, the scalar bar's title / format, and hide the scalar
        bar of the previously selected array."""
        representation = pvsimple.GetRepresentation(proxy=src, view=pvsimple.GetActiveView())
        representation.ColorArrayName = [array_type, property_title]
        lut = pvsimple.GetColorTransferFunction(property_title)
        lut.NanOpacity = self._nan_opacity_from_state()
        representation.LookupTable = lut
        representation.RescaleTransferFunctionToDataRange(True)
        bar = pvsimple.GetScalarBar(ctf=lut, view=pvsimple.GetActiveView())
        bar.Visibility = True
        bar.RangeLabelFormat = '%-#6.3g'
        bar.Resizable = 1
        bar.DrawNanAnnotation = 1
        bar.ComponentTitle = ''
        bar.Title = property_title
        if self._title:
            try:
                old_lut = pvsimple.GetColorTransferFunction(self._title, representation)
                pvsimple.GetScalarBar(ctf=old_lut, view=pvsimple.GetActiveView()).Visibility = False
            except Exception:
                pass

    def update_block_visibility(self):
        """Mirror the property selection on the parent multiblock's
        BlockSelectors (excluding the property path itself, which is
        rendered through the per-axis slicers)."""
        if self._property_path is not None and self._property_path in state.fespp_data_selectors:
            blockSelectors = state.fespp_data_selectors.copy()
            blockSelectors.remove(self._property_path)
            self._collector.get_representation().BlockSelectors = blockSelectors
            print(f"Updated block selectors for {self._property_path}: {blockSelectors}")

    def update_slices(self, slices_i_list, slices_j_list, slices_k_list):
        """Sync the per-axis slicer sources with the position lists,
        creating / deleting sources as needed and updating
        OutputWholeExtent on each one."""
        if self._node_id is None:
            return
        self._sync_slice_sources('i', len(slices_i_list))
        self._sync_slice_sources('j', len(slices_j_list))
        self._sync_slice_sources('k', len(slices_k_list))

        ri = state.ui_range_i
        rj = state.ui_range_j
        rk = state.ui_range_k

        for idx, pos in enumerate(slices_i_list):
            self._src_slicers_i[idx].OutputWholeExtent = [pos, pos, rj[0], rj[1], rk[0], rk[1]]
        for idx, pos in enumerate(slices_j_list):
            self._src_slicers_j[idx].OutputWholeExtent = [ri[0], ri[1], pos, pos, rk[0], rk[1]]
        for idx, pos in enumerate(slices_k_list):
            self._src_slicers_k[idx].OutputWholeExtent = [ri[0], ri[1], rj[0], rj[1], pos, pos]

    def update_volume(self, range_i, range_j, range_k):
        if self._node_id is not None and self._src_slicer_volume is not None:
            self._src_slicer_volume.OutputWholeExtent = [
                range_i[0], range_i[1],
                range_j[0], range_j[1],
                range_k[0], range_k[1],
            ]
