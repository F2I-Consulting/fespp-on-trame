from trame.app import get_server
from paraview import simple as pvsimple

server = get_server()
state = server.state
controller = server.controller

EPC_COLLECTOR_GUI_NAME = "EPCCollector"

class Collector:
    def __init__(self):
        
        # create EPC collector Source
        self._collector = pvsimple.EPCCollector(registrationName=EPC_COLLECTOR_GUI_NAME)
        self._representationType = None
        self._scale_z = [1.0, 1.0, 1.0]
        
        self.show()
    
    @property
    def representationType(self):
        return self._representationType

    @representationType.setter
    def representationType(self, value):
        if value != self._representationType:
            self._representationType = value

    @property
    def scale_z(self):
        return self._scale_z

    @scale_z.setter
    def scale_z(self, scale):
        if scale != self._scale_z:
            self._scale_z = scale

#    def update_representation(self):
#        pvsimple.GetRepresentation(proxy=self._collector, view=pvsimple.GetActiveView()).Representation = self._representationType
        
#    def update_scale(self):
#        pvsimple.GetRepresentation(proxy=self._collector, view=pvsimple.GetActiveView()).Scale = self._scale_z
        
    
    #== GETTER
    def get_source(self):
        return self._collector
    
    def get_representation(self):
        return pvsimple.GetRepresentation(proxy=self._collector, view=pvsimple.GetActiveView())
    
    #== SETTER / MODIFY
    def add_file(self, epc_file_path: str) -> bool:
        self._collector.SetPropertyWithName("Files", epc_file_path)
        self._collector.UpdatePipelineInformation()
        controller.update_data_information()
        return True
    
    def set_realization_index(self, index: int):
        """Set the active realization index for RealizationTimeSeries nodes and trigger a pipeline update.
        RealizationIndex is exposed as a StringVectorProperty (dropdown) on the
        XML proxy so the user only sees indices that exist; the C++ setter
        parses the string back to int. We use SetPropertyWithName because
        ParaView aliases the Python attribute to the XML 'label' ('Realization'),
        not the 'name' ('RealizationIndex')."""
        self._collector.SetPropertyWithName("RealizationIndex", str(index))
        self._collector.UpdatePipeline()

    #==
    def show(self):
#        self.update_representation()
#        self.update_scale()
        pvsimple.Show(proxy=self._collector, view=pvsimple.GetActiveView())
    