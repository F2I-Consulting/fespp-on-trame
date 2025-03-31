from trame.app import get_server
from paraview import simple as pvsimple

import fespp_on_trame.app.core.fespp_engine as fespp_engine

server = get_server()
state = server.state
ctrl = server.controller

def search_source(name: str) -> None:
    for item in server.state.explicitStructuredGrid_active_crop:
        if item.get("src_name") == name:
            return item
    return None

class IjkGrid:
    def __init__(self):
        self._node_id = None
        self._label = None
            
        # paraview source
        self._src_extract_init = None
        self._src_slicer_i = None
        self._src_slicer_j = None
        self._src_slicer_k = None
        self._src_slicer_volume = None

    def color_array_type(self, name) -> None:
        for i in range(self._src_slicer_i.CellData.GetNumberOfArrays()):
            if self._src_slicer_i.CellData.GetArray(i).Name == name:
                return 'CELL'
        for i in range(self._src_slicer_i.PointData.GetNumberOfArrays()):
            if self._src_slicer_i.PointData.GetArray(i).Name == name:
                return 'POINT'
        for i in range(self._src_slicer_i.FieldData.GetNumberOfArrays()):
            if self._src_slicer_i.FieldData.GetArray(i).Name == name:
                return 'FIELD'
        return
            
    def set_node_id(self, node_id):
        if node_id is None:
            return
        
        property_label = state.tree.find_label(node_id)
            
        ijkgrid_node_id = state.tree.find_parent_node_id_with_type(node_id, 'IjkGrid')
        if ijkgrid_node_id is None:
            return
        
        if self._node_id != ijkgrid_node_id: # new IjkGrid
            if self._node_id is not None: # remove last sources slicers
                fespp_engine.delete_source(self._src_extract_init)
                fespp_engine.delete_source(self._src_slicer_i)
                fespp_engine.delete_source(self._src_slicer_j)
                fespp_engine.delete_source(self._src_slicer_k)
                fespp_engine.delete_source(self._src_slicer_volume)

            self._node_id = ijkgrid_node_id
            # create sources slicers
            #self._label = state.tree.find_label(self._node_id)
            fespp_engine.epc_collector_extract(state.tree.find_label(self._node_id))
            blockSelectors = state.fespp_data_selectors.copy()
            property_path = state.tree.find_path(node_id)
            blockSelectors.remove(property_path)
            fespp_engine.get_representation(fespp_engine.get_epc_collector()).BlockSelectors = blockSelectors
            self._src_extract_init = fespp_engine.get_source(state.tree.find_label(self._node_id))
            self._src_slicer_i = fespp_engine.create_ExplicitStructuredGridCrop_source('sliceri', self._src_extract_init)
            self._src_slicer_j = fespp_engine.create_ExplicitStructuredGridCrop_source('slicerj', self._src_extract_init)
            self._src_slicer_k = fespp_engine.create_ExplicitStructuredGridCrop_source('slicerk', self._src_extract_init)
            self._src_slicer_volume = fespp_engine.create_ExplicitStructuredGridCrop_source('slicervolume', self._src_extract_init)

            self._src_extract_init.UpdatePipelineInformation()
            self._src_slicer_i.UpdatePipelineInformation()
            self._src_slicer_j.UpdatePipelineInformation()
            self._src_slicer_k.UpdatePipelineInformation()
            self._src_slicer_volume.UpdatePipelineInformation()
            
            pvsimple.Show(proxy=self._src_extract_init)
            pvsimple.Hide(proxy=self._src_extract_init)
#            ctrl.view_update()
#            pvsimple.Render(view=pvsimple.GetActiveView())
            
            # init range by extent
            data_info = self._src_extract_init.GetDataInformation()
            extent = data_info.GetExtent()
            state.update({
                "current_range_i" : [extent[0], extent[1]]
            })
            state.update({
                "current_range_j" : [extent[2], extent[3]]
            })
            state.update({
                "current_range_k" : [extent[4], extent[5]]
            })
            state.current_slices_i = (extent[0]+extent[1])//2
            state.current_slices_j = (extent[2]+extent[3])//2
            state.current_slices_k = (extent[4]+extent[5])//2
            state.current_slices_range_i = [extent[0], extent[1]]
            state.current_slices_range_j = [extent[2], extent[3]]
            state.current_slices_range_k = [extent[4], extent[5]]
            
            self._src_slicer_i.OutputWholeExtent = [extent[0], extent[1], extent[2], extent[3], extent[4], extent[5]]
            self._src_slicer_j.OutputWholeExtent = [extent[0], extent[1], extent[2], extent[3], extent[4], extent[5]]
            self._src_slicer_k.OutputWholeExtent = [extent[0], extent[1], extent[2], extent[3], extent[4], extent[5]]
            self._src_slicer_volume.OutputWholeExtent = [extent[0], extent[1], extent[2], extent[3], extent[4], extent[5]]

            fespp_engine.get_representation(self._src_extract_init).SetRepresentationType('Surface')
            fespp_engine.get_representation(self._src_slicer_i).SetRepresentationType('Surface')
            fespp_engine.get_representation(self._src_slicer_j).SetRepresentationType('Surface')
            fespp_engine.get_representation(self._src_slicer_k).SetRepresentationType('Surface')
            fespp_engine.get_representation(self._src_slicer_volume).SetRepresentationType('Surface')

            if property_label != self._label: # => is a property
                array_type = self.color_array_type(property_label)
                fespp_engine.get_representation(self._src_slicer_i).ColorArrayName(array_type,property_label)
                fespp_engine.get_representation(self._src_slicer_j).ColorArrayName(array_type,property_label)
                fespp_engine.get_representation(self._src_slicer_k).ColorArrayName(array_type,property_label)
                fespp_engine.get_representation(self._src_slicer_volume).ColorArrayName(array_type,property_label)
                lut_i = pvsimple.GetColorTransferFunction(property_label, representation=fespp_engine.get_representation(self._src_slicer_i))
                lut_j = pvsimple.GetColorTransferFunction(property_label, representation=fespp_engine.get_representation(self._src_slicer_j))
                lut_k = pvsimple.GetColorTransferFunction(property_label, representation=fespp_engine.get_representation(self._src_slicer_k))
                lut_volume = pvsimple.GetColorTransferFunction(property_label, representation=fespp_engine.get_representation(self._src_slicer_volume))
                pvsimple.GetScalarBar(ctf=lut_i, view=pvsimple.GetActiveView()).Visibility = True
                pvsimple.GetScalarBar(ctf=lut_j, view=pvsimple.GetActiveView()).Visibility = True
                pvsimple.GetScalarBar(ctf=lut_k, view=pvsimple.GetActiveView()).Visibility = True
                pvsimple.GetScalarBar(ctf=lut_volume, view=pvsimple.GetActiveView()).Visibility = True
                self._label = property_label
                
            self._src_slicer_i.UpdatePipelineInformation()
            self._src_slicer_j.UpdatePipelineInformation()
            self._src_slicer_k.UpdatePipelineInformation()
            self._src_slicer_volume.UpdatePipelineInformation()

            pvsimple.Hide(proxy=self._src_extract_init)
            if state.current_slices_range_mode == 'slice':
                pvsimple.Hide(proxy=self._src_slicer_volume)
                pvsimple.Show(proxy=self._src_slicer_i)
                pvsimple.Show(proxy=self._src_slicer_j)
                pvsimple.Show(proxy=self._src_slicer_k)
            else:
                pvsimple.Show(proxy=self._src_slicer_volume)
                pvsimple.Hide(proxy=self._src_slicer_i)
                pvsimple.Hide(proxy=self._src_slicer_j)
                pvsimple.Hide(proxy=self._src_slicer_k)
            ctrl.view_update()
            pvsimple.Render(view=pvsimple.GetActiveView())
            
    def get_source_slider_i(self):
        return self._src_slicer_i

    def get_source_slider_j(self):
        return self._src_slicer_j

    def get_source_slider_k(self):
        return self._src_slicer_k

    def get_source_slider_volume(self):
        return self._src_slicer_volume

    @state.change("current_slices_i")
    def update_slice_i(**kwargs):
        if state.ijk_grid is not None:
            if state.ijk_grid.get_source_slider_i() is not None:
                state.ijk_grid.get_source_slider_i().OutputWholeExtent = [state.current_slices_i, state.current_slices_i, state.current_range_j[0], state.current_range_j[1], state.current_range_k[0], state.current_range_k[1]]
                ctrl.view_update()
                pvsimple.Render(view=pvsimple.GetActiveView())

    @state.change("current_slices_j")
    def update_slice_j(**kwargs):
        if state.ijk_grid is not None:
            if state.ijk_grid.get_source_slider_j() is not None:
                state.ijk_grid.get_source_slider_j().OutputWholeExtent = [state.current_range_i[0], state.current_range_i[1], state.current_slices_j, state.current_slices_j, state.current_range_k[0], state.current_range_k[1]]
                ctrl.view_update()
                pvsimple.Render(view=pvsimple.GetActiveView())

    @state.change("current_slices_k")
    def update_slice_k(**kwargs):
        if state.ijk_grid is not None:
            if state.ijk_grid.get_source_slider_k() is not None:
                state.ijk_grid.get_source_slider_k().OutputWholeExtent = [state.current_range_i[0], state.current_range_i[1], state.current_range_j[0], state.current_range_j[1], state.current_slices_k, state.current_slices_k]
                ctrl.view_update()
                pvsimple.Render(view=pvsimple.GetActiveView())

    @state.change("current_slices_range_i", "current_slices_range_j", "current_slices_range_k")
    def update_volume(**kwargs):
        if state.ijk_grid is not None:
            if state.ijk_grid.get_source_slider_volume() is not None:
                state.ijk_grid.get_source_slider_volume().OutputWholeExtent = [state.current_slices_range_i[0], state.current_slices_range_i[1], state.current_slices_range_j[0], state.current_slices_range_j[1], state.current_slices_range_k[0], state.current_slices_range_k[1]]
                ctrl.view_update()
                pvsimple.Render(view=pvsimple.GetActiveView())
                
    @state.change("current_slices_range_mode")
    def update_mode(**kwargs):
        if state.ijk_grid is not None:
            if state.current_slices_range_mode == 'slice':
                pvsimple.Hide(proxy=state.ijk_grid.get_source_slider_volume())
                pvsimple.Show(proxy=state.ijk_grid.get_source_slider_i())
                pvsimple.Show(proxy=state.ijk_grid.get_source_slider_j())
                pvsimple.Show(proxy=state.ijk_grid.get_source_slider_k())
            else:
                pvsimple.Show(proxy=state.ijk_grid.get_source_slider_volume())
                pvsimple.Hide(proxy=state.ijk_grid.get_source_slider_i())
                pvsimple.Hide(proxy=state.ijk_grid.get_source_slider_j())
                pvsimple.Hide(proxy=state.ijk_grid.get_source_slider_k())
            ctrl.view_update()
            pvsimple.Render(view=pvsimple.GetActiveView())
