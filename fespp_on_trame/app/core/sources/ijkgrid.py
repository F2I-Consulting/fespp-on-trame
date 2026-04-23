from trame.app import get_server
from paraview import simple as pvsimple

from fespp_on_trame.app.core.sources.collector import Collector
from fespp_on_trame.app.core.fespp_tree import Tree


server = get_server()
state = server.state
ctrl = server.controller


class IjkGrid:
    def __init__(self, collector: Collector, tree: Tree):
        self._collector = collector
        self._tree = tree
        self._node_id = None
        self._title = None
        self._property_path = None
        # Current coloring state — needed to apply colors to dynamically added sources
        self._current_array_type = None
        self._current_property_type = None
        self._current_extent = None  # [x0,x1,y0,y1,z0,z1]

        # ParaView sources — lists for multi-slice support (one list per axis)
        self._src_extract_init = None
        self._src_slicers_i = []
        self._src_slicers_j = []
        self._src_slicers_k = []
        self._src_slicer_volume = None

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def color_array_type(self, name) -> None:
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

    def _delete_all_sources(self):
        """Delete every slice source and the extract source."""
        view = pvsimple.GetActiveView()
        pvsimple.SetActiveSource(None)
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
        """Create and return a new ExplicitStructuredGridCrop for (axis, idx)."""
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
        """Ensure exactly `count` slicer sources exist for the given axis."""
        if self._src_extract_init is None:
            return
        srcs = getattr(self, f'_src_slicers_{axis}')
        # Add missing sources
        while len(srcs) < count:
            src = self._create_slice_source(axis, len(srcs))
            srcs.append(src)
        # Remove excess sources
        view = pvsimple.GetActiveView()
        while len(srcs) > count:
            src = srcs.pop()
            try:
                pvsimple.Hide(proxy=src, view=view)
                pvsimple.Delete(src)
            except Exception:
                pass

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def set_node_id(self, node_id):
        if node_id is None:
            if self._node_id is not None:
                self._delete_all_sources()
            self._node_id = None
            return

        ijkgrid_node_id = self._tree.find_parent_node_id_with_type(node_id, 'IjkGrid')
        if ijkgrid_node_id is None:
            return

        if self._node_id != ijkgrid_node_id:  # new IjkGrid — rebuild all sources
            if self._node_id is not None:
                self._delete_all_sources()

            self._node_id = ijkgrid_node_id
            label = self._tree.find_label(self._node_id)
            self._collector.extract_block(label)
            self._property_path = self._tree.find_path(node_id)
            self._src_extract_init = pvsimple.FindSource(label)

            if self._src_extract_init is None:
                self._node_id = None  # reset so next call retries
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
            for src in self._all_slice_sources() + [self._src_slicer_volume]:
                pvsimple.GetRepresentation(proxy=src, view=view).Representation = rep_type

            self.update_block_visibility()
            pvsimple.Show(proxy=self._src_extract_init, view=view)
            self.show()
            pvsimple.Hide(proxy=self._src_extract_init)

            # Initialise ranges and list state from grid extent
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

        # Property change within the same grid
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

    def show(self):
        if self._node_id is None:
            return
        view = pvsimple.GetActiveView()
        if state.ui_slices_range_mode == 'slice':
            pvsimple.Hide(proxy=self._src_slicer_volume, view=view)
            vis_i = list(state.ui_slices_i_visible_list or [])
            vis_j = list(state.ui_slices_j_visible_list or [])
            vis_k = list(state.ui_slices_k_visible_list or [])
            for idx, src in enumerate(self._src_slicers_i):
                visible = vis_i[idx] if idx < len(vis_i) else True
                (pvsimple.Show if visible else pvsimple.Hide)(proxy=src, view=view)
            for idx, src in enumerate(self._src_slicers_j):
                visible = vis_j[idx] if idx < len(vis_j) else True
                (pvsimple.Show if visible else pvsimple.Hide)(proxy=src, view=view)
            for idx, src in enumerate(self._src_slicers_k):
                visible = vis_k[idx] if idx < len(vis_k) else True
                (pvsimple.Show if visible else pvsimple.Hide)(proxy=src, view=view)
        else:
            pvsimple.Show(proxy=self._src_slicer_volume, view=view)
            for src in self._all_slice_sources():
                pvsimple.Hide(proxy=src, view=view)

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
        if self._property_path is not None and self._property_path in state.fespp_data_selectors:
            blockSelectors = state.fespp_data_selectors.copy()
            blockSelectors.remove(self._property_path)
            self._collector.get_representation().BlockSelectors = blockSelectors
            print(f"Updated block selectors for {self._property_path}: {blockSelectors}")

    def update_slices(self, slices_i_list, slices_j_list, slices_k_list):
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
