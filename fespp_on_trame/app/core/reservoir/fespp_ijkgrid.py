from trame.app import get_server
from paraview import simple as pvsimple

import fespp_on_trame.app.core.fespp_engine as fespp_engine
from fespp_on_trame.app.core.sources.collector import Collector

server = get_server()
state = server.state
ctrl = server.controller

class IjkGrid:
    def __init__(self, collector: Collector):
        
        self._collector = collector
        
        self._node_id = None
        self._title = None
        self._property_path = None
        self._representationType = None
        self._scale = None
            
        # paraview source
        self._src_extract_init = None
        self._src_slicer_i = None
        self._src_slicer_j = None
        self._src_slicer_k = None
        self._src_slicer_volume = None

    @property
    def representationType(self):
        return self._representationType

    @representationType.setter
    def representationType(self, value):
        if value != self._representationType:
            self._representationType = value
            self.update_representation()

    @property
    def scale(self):
        return self._scale

    @scale.setter
    def scale(self, scale):
        if scale != self._scale:
            self._scale = scale
            self.update_scale()
            
    def update_representation(self):
        pvsimple.GetRepresentation(proxy=self._src_slicer_volume, view=pvsimple.GetActiveView()).Representation = self._representationType
        pvsimple.GetRepresentation(proxy=self._src_slicer_i, view=pvsimple.GetActiveView()).Representation = self._representationType
        pvsimple.GetRepresentation(proxy=self._src_slicer_j, view=pvsimple.GetActiveView()).Representation = self._representationType
        pvsimple.GetRepresentation(proxy=self._src_slicer_k, view=pvsimple.GetActiveView()).Representation = self._representationType
        
    def update_scale(self):
        pvsimple.GetRepresentation(proxy=self._src_slicer_volume, view=pvsimple.GetActiveView()).Scale = self._scale
        pvsimple.GetRepresentation(proxy=self._src_slicer_i, view=pvsimple.GetActiveView()).Scale = self._scale
        pvsimple.GetRepresentation(proxy=self._src_slicer_j, view=pvsimple.GetActiveView()).Scale = self._scale
        pvsimple.GetRepresentation(proxy=self._src_slicer_k, view=pvsimple.GetActiveView()).Scale = self._scale

        
    def color_array_type(self, name) -> None:
        for i in range(self._src_slicer_i.CellData.GetNumberOfArrays()):
            if self._src_slicer_i.CellData.GetArray(i).Name == name:
                return 'CELLS'
        for i in range(self._src_slicer_i.PointData.GetNumberOfArrays()):
            if self._src_slicer_i.PointData.GetArray(i).Name == name:
                return 'POINTS'
        for i in range(self._src_slicer_i.FieldData.GetNumberOfArrays()):
            if self._src_slicer_i.FieldData.GetArray(i).Name == name:
                return 'FIELD'
        return
            
    def set_node_id(self, node_id):
        if node_id is None:
            if self._node_id is not None: # remove last sources slicers
                pvsimple.Delete(self._src_extract_init)
                pvsimple.Delete(self._src_slicer_i)
                pvsimple.Delete(self._src_slicer_j)
                pvsimple.Delete(self._src_slicer_k)
                pvsimple.Delete(self._src_slicer_volume)
            return
        
        ijkgrid_node_id = state.tree.find_parent_node_id_with_type(node_id, 'IjkGrid')
        if ijkgrid_node_id is None:
            return
        
        if self._node_id != ijkgrid_node_id: # new IjkGrid
            if self._node_id is not None: # remove last sources slicers
                pvsimple.Delete(self._src_extract_init)
                pvsimple.Delete(self._src_slicer_i)
                pvsimple.Delete(self._src_slicer_j)
                pvsimple.Delete(self._src_slicer_k)
                pvsimple.Delete(self._src_slicer_volume)

            self._node_id = ijkgrid_node_id
            # create sources slicers
            self._collector.extract_block(state.tree.find_label(self._node_id))
            self._property_path = state.tree.find_path(node_id)


            self._src_extract_init = pvsimple.FindSource(state.tree.find_label(self._node_id))
            self._src_slicer_i = pvsimple.ExplicitStructuredGridCrop(registrationName='sliceri', Input=self._src_extract_init)
            self._src_slicer_j = pvsimple.ExplicitStructuredGridCrop(registrationName='slicerj', Input=self._src_extract_init)
            self._src_slicer_k = pvsimple.ExplicitStructuredGridCrop(registrationName='slicerk', Input=self._src_extract_init)
            self._src_slicer_volume = pvsimple.ExplicitStructuredGridCrop(registrationName='slicervolume', Input=self._src_extract_init)

            self._src_extract_init.UpdatePipelineInformation()
            self._src_slicer_i.UpdatePipelineInformation()
            self._src_slicer_j.UpdatePipelineInformation()
            self._src_slicer_k.UpdatePipelineInformation()
            self._src_slicer_volume.UpdatePipelineInformation()
            
            self.update_block_visibility()
            
            pvsimple.Show(proxy=self._src_extract_init, view=pvsimple.GetActiveView())
            self.show()
            pvsimple.Hide(proxy=self._src_extract_init)
            
            # init range by extent
            data_info = self._src_extract_init.GetDataInformation()
            extent = data_info.GetExtent()
            state.update({
                "ui_range_i" : [extent[0], extent[1]]
            })
            state.update({
                "ui_range_j" : [extent[2], extent[3]]
            })
            state.update({
                "ui_range_k" : [extent[4], extent[5]]
            })
            state.ui_slices_i = (extent[0]+extent[1])//2
            state.ui_slices_j = (extent[2]+extent[3])//2
            state.ui_slices_k = (extent[4]+extent[5])//2
            state.ui_slices_range_i = [extent[0], extent[1]]
            state.ui_slices_range_j = [extent[2], extent[3]]
            state.ui_slices_range_k = [extent[4], extent[5]]
            
            self._src_slicer_i.OutputWholeExtent = [extent[0], extent[1], extent[2], extent[3], extent[4], extent[5]]
            self._src_slicer_j.OutputWholeExtent = [extent[0], extent[1], extent[2], extent[3], extent[4], extent[5]]
            self._src_slicer_k.OutputWholeExtent = [extent[0], extent[1], extent[2], extent[3], extent[4], extent[5]]
            self._src_slicer_volume.OutputWholeExtent = [extent[0], extent[1], extent[2], extent[3], extent[4], extent[5]]

        property_title = state.tree.find_title(node_id)
        property_type = state.tree.find_type(node_id)
        if property_title != self._title: # => is a property
            array_type = self.color_array_type(property_title)
            if array_type is not None:
                self.update_colors(self._src_slicer_i, array_type, property_title, property_type)
                self.update_colors(self._src_slicer_j, array_type, property_title, property_type)
                self.update_colors(self._src_slicer_k, array_type, property_title, property_type)
                self.update_colors(self._src_slicer_volume, array_type, property_title, property_type)

            self._title = property_title
                
            self._src_slicer_i.UpdatePipelineInformation()
            self._src_slicer_j.UpdatePipelineInformation()
            self._src_slicer_k.UpdatePipelineInformation()
            self._src_slicer_volume.UpdatePipelineInformation()

            pvsimple.Hide(proxy=self._src_extract_init)
            self.show()

    #==
    def show(self):
        if self._node_id is not None:
            self.update_representation()
            self.update_scale()
            if state.ui_slices_range_mode == 'slice':
                pvsimple.Hide(proxy=self._src_slicer_volume, view=pvsimple.GetActiveView())
                pvsimple.Show(proxy=self._src_slicer_i, view=pvsimple.GetActiveView())
                pvsimple.Show(proxy=self._src_slicer_j, view=pvsimple.GetActiveView())
                pvsimple.Show(proxy=self._src_slicer_k, view=pvsimple.GetActiveView())
            else:
                pvsimple.Show(proxy=self._src_slicer_volume, view=pvsimple.GetActiveView())
                pvsimple.Hide(proxy=self._src_slicer_i, view=pvsimple.GetActiveView())
                pvsimple.Hide(proxy=self._src_slicer_j, view=pvsimple.GetActiveView())
                pvsimple.Hide(proxy=self._src_slicer_k, view=pvsimple.GetActiveView())
#            ctrl.view_update()

    def update_colors(self, src, array_type, property_title, property_type): 
        representation = pvsimple.GetRepresentation(proxy=src, view=pvsimple.GetActiveView())
        representation.ColorArrayName= [array_type,property_title]
        lut=pvsimple.GetColorTransferFunction(property_title)
        lut.NanOpacity = 0.2
        representation.LookupTable = lut
        representation.RescaleTransferFunctionToDataRange(True)
        bar=pvsimple.GetScalarBar(ctf=lut, view=pvsimple.GetActiveView())
        bar.Visibility = True
        bar.RangeLabelFormat='%-#6.3g'
        bar.Resizable = 1
        bar.DrawNanAnnotation = 1
        bar.ComponentTitle = ''
        bar.Title = property_title
        old_lut = pvsimple.GetColorTransferFunction(self._title, representation)
        pvsimple.GetScalarBar(ctf=old_lut, view=pvsimple.GetActiveView()).Visibility = False
 
    def update_block_visibility(self): # change BlockSelectors 
        if self._property_path is not None and self._property_path in state.fespp_data_selectors:
            blockSelectors = state.fespp_data_selectors.copy()
            blockSelectors.remove(self._property_path)
            self._collector.get_representation().BlockSelectors = blockSelectors

    def update_slices(self, slice_i, slice_j, slice_k):
        if self._node_id is not None:
            if self._src_slicer_i is not None:
                self._src_slicer_i.OutputWholeExtent = [slice_i, slice_i, state.ui_range_j[0], state.ui_range_j[1], state.ui_range_k[0], state.ui_range_k[1]]
            if self._src_slicer_j is not None:
                self._src_slicer_j.OutputWholeExtent = [state.ui_range_i[0], state.ui_range_i[1], slice_j, slice_j, state.ui_range_k[0], state.ui_range_k[1]]
            if self._src_slicer_k is not None:
                self._src_slicer_k.OutputWholeExtent = [state.ui_range_i[0], state.ui_range_i[1], state.ui_range_j[0], state.ui_range_j[1], slice_k, slice_k]

    def update_volume(self, range_i, range_j, range_k):
        if self._node_id is not None:
            if self._src_slicer_volume is not None:
                self._src_slicer_volume.OutputWholeExtent = [range_i[0], range_i[1], range_j[0], range_j[1], range_k[0], range_k[1]]
                
