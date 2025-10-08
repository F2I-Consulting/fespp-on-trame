
# Need the * import for grid extractor plugin (ParaView requirement)
#from paraview.simple import *
from paraview import simple as pvsimple
from trame_server import Server
from pathlib import Path

from fespp_on_trame.app.core.fespp_tree import Tree
from fespp_on_trame.app.core.reservoir.fespp_ijkgrid import IjkGrid
from fespp_on_trame.app.core.sources.collector import Collector
from fespp_on_trame.app.core.fespp_selection import Selector
import fespp_on_trame.app.core.fespp_active as fespp_active

def initialize_fespp_engine(
    server: Server, *, fespp_plugin_path: Path
) -> None:
    # Get references to the Trame server's state and controller
    state = server.state
    controller = server.controller

    # Load the custom FESPP ParaView plugin
    pvsimple.LoadPlugin(str(fespp_plugin_path))
    # Load the ExplicitStructuredGrid plugin for handling explicit grid slicing
    pvsimple.LoadPlugin('/opt/paraview/lib/paraview-5.13/plugins/ExplicitStructuredGrid/ExplicitStructuredGrid.so')

    # Get or create the active ParaView render view
    _view = pvsimple.GetActiveViewOrCreate("RenderView")

    # Initialize FESPP core components
    _tree = Tree(None)

    _collector = Collector()                     # SOURCE: Collects and loads data (e.g., from an EPC file)
    _ijkGrid = IjkGrid(_collector, _tree)        # SOURCE: Handles IJK grid manipulation (slicing, volume)
    
    # FESPP engine components for selection and activation
    _selector = Selector(_ijkGrid, _tree)
    fespp_active.Activator(_tree)
    
    #=> Initialize UI state variables <=
    # Initialize Trame state variables for UI selection (TreeView selections)
    state.setdefault("ui_select_node_reservoir", [])
    state.setdefault("ui_select_node_surface", [])
    state.setdefault("ui_select_node_well", [])
    
    
    # State variable to hold the list of node paths selected for FESPP loading
    state.setdefault("fespp_data_selectors", []) 

    # Flag to track if data has been loaded at least once (used for camera reset logic)
    state.setdefault("has_data_loaded_once", False)
    
    # State flags to trigger view updates and camera resets from Trame
    state.setdefault("view_update", False)
    state.setdefault("view_reset_camera", False)
    
    # Ensure all state changes are synchronized
    state.flush()

    # Define controller action to trigger a view update
    @controller.add("on_data_change")
    def update():
        server.controller.view_update()
        
    # Define controller action to load an EPC file
    @controller.set("load_epc_file")
    def load_epc_file(epc_file_path: str):
        # Update state variable 'file_loaded' based on the success of adding the file
        state.file_loaded = _collector.add_file(epc_file_path)

    # Define controller action to update data information and build the tree structure
    # Create the treeview structure from the FESPP vtkdatasembly
    @controller.set("update_data_information")
    def update_data_information():
        # Get the underlying source object (the EPC collector)
        collector = _collector.get_source() #get_epc_collector()
        client_side_object = collector.GetClientSideObject()
        if hasattr(client_side_object, "GetOutput"):
            output = client_side_object.GetOutput()
            if hasattr(output, "GetDataAssembly"):
                # Extract the DataAssembly structure and set up the FESPP Tree
                assembly = output.GetDataAssembly()
        _tree.set_tree(assembly)
        
    # Handler for changes to the selected FESPP data nodes (Trame state variable)
    @state.change("fespp_data_selectors")
    def on_change_fespp_data_selectors( **kwargs):
        if _collector is None:
            return
        # Set the 'Selectors' property on the ParaView source to load selected data
        _collector.get_source().SetPropertyWithName('Selectors', state.fespp_data_selectors)
        _collector.get_source().UpdatePipelineInformation()
        
        pvsimple.Render(view=_view)
        
        # Configure representation for partitioned dataset (e.g., show assembly structure)
        # Hide objects in vtkPartitionedDataSet: extracted object
        representation = _collector.get_representation()
        representation.Assembly='Assembly'

        # Update IJK Grid visibility if a reservoir node is selected
        if len(state.ui_select_node_reservoir) > 0:
            _ijkGrid.set_node_id(state.ui_select_node_reservoir[0])
        _ijkGrid.update_block_visibility()
        
        # Trigger Trame view replacement and general update
        controller.view_replace
        state.view_update = True

        # Show the data source and set it as active
        _collector.show()
        pvsimple.SetActiveSource(_collector.get_source())
        # Notify Trame components (like TimeControl and ColorBy) that data has loaded
        server.controller.on_data_loaded() # for ptc.TimeControl()
        server.controller.on_active_proxy_change() # for ptc.RepresentBy() / ptc.ColorBy
        
        # =========================================================
        # CAMERA RESET LOGIC (ONLY ON FIRST LOAD)
        if (not state.has_data_loaded_once) and (len(state.fespp_data_selectors) > 0):
            # 1. TRIGGER RESET VIA TRAME STATE
            # This will trigger the @state.change("view_reset_camera") function
            state.view_reset_camera = True # <--- New approach
            
            # 2. Mark the load as complete
            state.has_data_loaded_once = True  
        # =========================================================
        # ----------------------------------------------------
        # Final render to display the scene with the new camera
        pvsimple.Render(view=_view)
        # ----------------------------------------------------

    #======================= Main Properties
    # Handler for Z-scaling changes
    @state.change("ui_scale_z")
    def ui_scale_z_update(ui_scale_z, **kwargs):
        scale = [1.0,1.0, float(ui_scale_z)]
        if _collector is not None:
            _collector.scale_z = scale
            _collector.show()
        if _ijkGrid is not None:
            _ijkGrid.scale = scale
            _ijkGrid.show()
        pvsimple.Render(view=_view)
        controller.view_update()
        
    # Handler for representation type changes (e.g., Surface, Wireframe)
    @state.change("representation_active")
    def update_ui_representation(representation_active, **kwargs):
        if _collector is not None:
            _collector.representationType = representation_active
            _collector.show()
        if _ijkGrid is not None:
            _ijkGrid.representationType = representation_active
            _ijkGrid.show()
        pvsimple.Render(view=_view)
        controller.view_update()

    #======================= UI: change Slicer
    # Handler for IJK slices position changes
    @state.change("ui_slices_i", "ui_slices_j", "ui_slices_k")
    def update_slice(ui_slices_i, ui_slices_j, ui_slices_k, **kwargs):
        if _ijkGrid is not None:
            _ijkGrid.update_slices(ui_slices_i, ui_slices_j, ui_slices_k)
            _ijkGrid.show()
        pvsimple.Render(view=_view)
        controller.view_update()
        
    # Handler for IJK volume range changes
    @state.change("ui_slices_range_i", "ui_slices_range_j", "ui_slices_range_k")
    def update_range_slicer(ui_slices_range_i, ui_slices_range_j, ui_slices_range_k, **kwargs):
        if _ijkGrid is not None:
            _ijkGrid.update_volume(ui_slices_range_i, ui_slices_range_j, ui_slices_range_k)
            _ijkGrid.show()
        pvsimple.Render(view=_view)
        controller.view_update()
        
    # Handler for slicer mode changes (e.g., slice vs. volume)
    @state.change("ui_slices_range_mode")
    def update_mode_slicer(**kwargs):
        if _ijkGrid is not None:
            _ijkGrid.show()
        pvsimple.Render(view=_view)
        controller.view_update()

    #======================= UI: change time
    # Handler for time step index changes
    @state.change("time_index")
    def changeTimeLabel( **kwargs):
        try:
            index = state.time_index
            if index is not None:
                # Find time label in the tree based on the timestep value
                time_value = pvsimple.GetTimeKeeper().TimestepValues[index]
                label = _tree.find_attribute_value(0, f"time{time_value:.6f}")
                if label is not None:
                    state.ui_time_label = label
                else:
                    # Fallback label if no custom label is found
                    state.ui_time_label = f"time{time_value:.6f}"
        except:
            state.ui_time_label = ""

    #======================= TreeView: change selection
    # Handler for surface node selection changes
    @state.change("ui_select_node_surface")
    def on_change_ui_select_node_surface(**kwargs):
        if _selector is not None:
            _selector.select_node_surface()
        
    # Handler for well node selection changes
    @state.change("ui_select_node_well")
    def on_change_ui_select_node_well(**kwargs):
        if _selector is not None:
            _selector.select_node_well()
    
    # Handler for reservoir node selection changes
    @state.change("ui_select_node_reservoir")
    def on_change_ui_select_node_reservoir(**kwargs):
        if _selector is not None:
            _selector.select_node_reservoir()
        
    #======================= View Controls
    # Handler for camera reset flag
    @state.change("view_reset_camera")
    def view_reset_camera(view_reset_camera, **kwargs):
        if view_reset_camera == True:
            # Ensure the IJK grid visibility is correct before resetting the camera
            _ijkGrid.update_block_visibility()
            controller.view_reset_camera()
            controller.view_update()
            # Reset the flag after the action is performed
            state.view_reset_camera = False
            state.flush()
            
    # Handler for general view update flag
    @state.change("view_update")
    def view_update(view_update, **kwargs):
        if view_update == True:
            controller.view_update()
            # Reset the flag after the action is performed
            state.view_update = False
            state.flush()