from trame.app import get_server

server = get_server()
state = server.state

state.setdefault("ui_subtree_reservoir", []) # reservoir tree
state.setdefault("ui_subtree_surface", []) # surface tree
state.setdefault("ui_subtree_well", []) # well tree
    
class Tree():
    def __init__(self, data_assembly):
        # init
        self._data_assembly = data_assembly
        self._data_hierarchy_reservoir = []
        self._data_hierarchy_well = []
        self._data_hierarchy_surface = []

        self._representation_type_in = ['IjkGrid','Sub', 'UnstructuredGrid', 'Wellbore', 'Trajectory', 'Completion', 'Perfo', 'Frame', 'MarkerFrame', 'WellboreMarker', 'SeismicWellboreFrame', 'Grid2d', 'PointSet', 'Polyline','PolylineSet', 'TriangulatedSet', 'partial']

    def add_subtreeview_data(self, parent_id: int, child_index: int, treeview_type, disabled = False)-> None:
        node_id = self._data_assembly.GetChild(parent_id, child_index)
        node_label = None
        node_label = self._data_assembly.GetAttributeOrDefault(node_id, "label", node_label)
        node_title = node_label[node_label.find("_") + 1 :]
        node_type = node_label[:node_label.find("_")]
        node_path = self._data_assembly.GetNodePath(node_id)
            
        if treeview_type == "unknown":
            if node_type in ['IjkGrid','Sub', 'UnstructuredGrid']:
                treeview_type = "reservoir"
            elif node_type in ['Wellbore', 'Trajectory', 'Completion', 'Perfo', 'Frame', 'MarkerFrame', 'WellboreMarker', 'SeismicWellboreFrame']:
                treeview_type = "well"
            elif node_type in ['Grid2d', 'PointSet', 'Polyline', 'PolylineSet', 'TriangulatedSet']:
                treeview_type = "surface"
            elif node_type in ['partial']:
                disabled = True
                node_supportType = None
                node_supportType = self._data_assembly.GetAttributeOrDefault(node_id, "supporttype", node_supportType)
                if node_supportType in ['IjkGrid','Sub', 'UnstructuredGrid']:
                    node_title = '!!!PARTIAL!!! '+ node_title
                    treeview_type = "reservoir"
                elif node_supportType in ['Wellbore', 'Trajectory', 'Completion', 'Perfo', 'Frame', 'MarkerFrame', 'WellboreMarker', 'SeismicWellboreFrame']:
                    node_title = node_label
                    treeview_type = "well"
                elif node_supportType in ['Grid2d', 'PointSet', 'Polyline', 'PolylineSet', 'TriangulatedSet']:
                    node_title = node_label
                    treeview_type = "surface"

        data = {}
        data["treeview"] = {}
        data["treeview"]["parent_id"] = parent_id
        data["treeview"]["id"] = node_id
        data["treeview"]["title"] = node_title
        data["treeview"]["path"] = node_path
        data["treeview"]["type"] = node_type
        if disabled: data["treeview"]["disabled"] = True
            
        data["treeview_type"] = treeview_type

        children_count = self._data_assembly.GetNumberOfChildren(node_id)
        if children_count > 0:
            data["treeview"]["children"]=[]
            for i in range(children_count):
                subTreeview = self.add_subtreeview_data(node_id, i, treeview_type, disabled)
                data["treeview"]["children"].append(subTreeview["treeview"])
                data["treeview_type"] = subTreeview["treeview_type"]
        return data

    def set_tree(self, data_assembly):
        self._data_hierarchy_reservoir = []
        self._data_hierarchy_well = []
        self._data_hierarchy_surface = []
        disabled = False
        self._data_assembly = data_assembly
        if self._data_assembly is not None:
            root_id = 0
            for i in range(data_assembly.GetNumberOfChildren(root_id)):
                node_id = self._data_assembly.GetChild(root_id, i)
                node_label = None
                node_label = self._data_assembly.GetAttributeOrDefault(node_id, "label", node_label)
                node_title=node_label[node_label.find("_") + 1 :]
                node_type=node_label[:node_label.find("_")]
                node_path = self._data_assembly.GetNodePath(node_id)
                
                # dispatch on reservoir/surface/well
                treeview = {}
                treeview_type = "unknown"
                if node_type in ['IjkGrid','Sub', 'UnstructuredGrid']:
                    treeview_type = "reservoir"
                elif node_type in ['Wellbore', 'Trajectory', 'Completion', 'Perfo', 'Frame', 'MarkerFrame', 'WellboreMarker', 'SeismicWellboreFrame']:
                    treeview_type = "well"
                elif node_type in ['Grid2d', 'PointSet', 'Polyline', 'PolylineSet', 'TriangulatedSet']:
                    treeview_type = "surface"
                elif node_type in ['partial']:
                    disabled = True
                    node_supportType = None
                    node_supportType = self._data_assembly.GetAttributeOrDefault(node_id, "supporttype", node_supportType)
                    treeview["disabled"] = True,
                    if node_supportType in ['IjkGrid','Sub', 'UnstructuredGrid']:
                        node_title = '!!!PARTIAL!!! '+ node_title
                        treeview_type = "reservoir"
                    elif node_supportType in ['Wellbore', 'Trajectory', 'Completion', 'Perfo', 'Frame', 'MarkerFrame', 'WellboreMarker', 'SeismicWellboreFrame']:
                        node_title = node_label
                        treeview_type = "well"
                    elif node_supportType in ['Grid2d', 'PointSet', 'Polyline', 'PolylineSet', 'TriangulatedSet']:
                        node_title = node_label
                        treeview_type = "surface"
                # initialize node dict
                treeview["parent_id"] = root_id
                treeview["id"] = node_id
                treeview["title"] = node_title
                treeview["path"] = node_path
                treeview["type"] = node_type
                if disabled: treeview["disabled"] = True
            
                children_count = self._data_assembly.GetNumberOfChildren(node_id)
                if children_count > 0:
                    treeview["children"]=[]
                    for i in range(children_count):
                        subTreeview = self.add_subtreeview_data(node_id, i, treeview_type, disabled)
                        treeview["children"].append(subTreeview["treeview"])
                        treeview_type = subTreeview["treeview_type"]
                        # add subTree in type tree
                if treeview_type == "reservoir":
                    if treeview and treeview not in self._data_hierarchy_reservoir:
                        self._data_hierarchy_reservoir.append(treeview)
                elif treeview_type == "well":
                    if treeview and treeview not in self._data_hierarchy_well:
                        self._data_hierarchy_well.append(treeview)
                elif treeview_type == "surface":
                    if treeview and treeview not in self._data_hierarchy_surface:
                        self._data_hierarchy_surface.append(treeview)
            state.ui_subtree_reservoir = list(self._data_hierarchy_reservoir)
            state.ui_subtree_well = list(self._data_hierarchy_well)
            state.ui_subtree_surface = list(self._data_hierarchy_surface)

    # -----------------------------------------------------------------------------
    # find ijkgrid parent node id
    # -----------------------------------------------------------------------------
    def find_ijkgrid(self, node_id) -> None:
        if node_id == 0 or self._data_assembly is None:
            return
    
        node_label = None
        node_label = self._data_assembly.GetAttributeOrDefault(node_id, "label", node_label)
        node_type = node_label[:node_label.find("_")]

        if node_type:
            if node_type in [ 'IjkGrid' ]:
                return node_label
            else:
                return self.find_ijkgrid(self._data_assembly.GetParent(node_id))
        return

    # -----------------------------------------------------------------------------
    # find ijkgrid parent node id
    # -----------------------------------------------------------------------------
    def find_parent_node_id_with_type(self, node_id, type) -> None:
        if node_id == 0 or self._data_assembly is None:
            return

        node_label = None
        node_label = self._data_assembly.GetAttributeOrDefault(node_id, "label", node_label)
        node_type = node_label[:node_label.find("_")]

        if node_type:
            if node_type == type :
                return node_id
            else:
                return self.find_parent_node_id_with_type(self._data_assembly.GetParent(node_id), type)
        return

    # -----------------------------------------------------------------------------
    # find ijkgrid property name
    # -----------------------------------------------------------------------------
    def find_ijkgrid_property_name(self, node_label, list_selected) -> None:
        if node_label is None or self._data_assembly is None:
            return
        for selected in list_selected:
            node_id = self._data_assembly.GetFirstNodeByPath(selected)
            if node_id:
                ijkgrid_node = self.find_parent_node_id_with_type(node_id, 'IjkGrid')
                if ijkgrid_node:
                    ijkgrid_label = None
                    ijkgrid_label = self._data_assembly.GetAttributeOrDefault(ijkgrid_node, "label", ijkgrid_label)
                    if ijkgrid_label is not None and node_label == ijkgrid_label:
                        property_label = None
                        property_label = self._data_assembly.GetAttributeOrDefault(node_id, "label", property_label)
                        return property_label[property_label.find("_") + 1 :]
        return

    # -----------------------------------------------------------------------------
    # find path by node_id
    # -----------------------------------------------------------------------------
    def find_path(self, node_id) -> None:
        if node_id == 0 or self._data_assembly is None:
            return            
        return self._data_assembly.GetNodePath(node_id)

    # -----------------------------------------------------------------------------
    # find type by node_id
    # -----------------------------------------------------------------------------
    def find_type(self, node_id) -> None:
        if node_id == 0 or self._data_assembly is None:
            return            
        label = None
        label = self._data_assembly.GetAttributeOrDefault(node_id, "label", label)
        if label:
            return label[:label.find("_")]
        return

    # -----------------------------------------------------------------------------
    # find title by node_id
    # -----------------------------------------------------------------------------
    def find_title(self, node_id) -> None:
        if node_id == 0 or self._data_assembly is None:
            return
        label = None
        label = self._data_assembly.GetAttributeOrDefault(node_id, "label", label)
        if label:
            return label[label.find("_") + 1 :]
        return

    # -----------------------------------------------------------------------------
    # find label by node_id
    # -----------------------------------------------------------------------------
    def find_label(self, node_id) -> None:
        if node_id == 0 or self._data_assembly is None:
            return
        label = None
        label = self._data_assembly.GetAttributeOrDefault(node_id, "label", label)
        if label:
            return label
        return
    
    # -----------------------------------------------------------------------------
    # find node_id by path
    # -----------------------------------------------------------------------------
    def find_node_id(self, path) -> None:
        return self._data_assembly.GetFirstNodeByPath(path)

    # -----------------------------------------------------------------------------
    # find representation parent node_id  by node_id child
    # -----------------------------------------------------------------------------
    def find_representation_node(self, node_id) -> None:
        if node_id == 0 or self._data_assembly is None:
            return
    
        node_label = None
        node_label = self._data_assembly.GetAttributeOrDefault(node_id, "label", node_label)
        node_type = node_label[:node_label.find("_")]

        if node_type:
            if node_type in self._representation_type_in:
                return node_id
            else:
                return self.find_representation_node(self._data_assembly.GetParent(node_id))
        return
    
    # -----------------------------------------------------------------------------
    # find representation type by node_id
    # -----------------------------------------------------------------------------
    def find_representation_type(self, node_id) -> None:
        if node_id is not None:
            type = self.find_type(node_id)
            if type is not None:
                if type in self._representation_type_in:
                    return type
                else:
                    rep_node_id = self.find_representation_node(node_id)
                    if rep_node_id is not None:
                        return self.find_type(rep_node_id)
        return
    
    # -----------------------------------------------------------------------------
    # find attribute value by node_id/attribute name
    # -----------------------------------------------------------------------------
    def find_attribute_value(self, node_id, attribute_name) -> None:
        if node_id is not None:
            attribute_value = None
            attribute_value = self._data_assembly.GetAttributeOrDefault(node_id, attribute_name, attribute_value)
            return attribute_value
        return
    
    # -----------------------------------------------------------------------------
    # find the value of the nearest parent's attribute
    # -----------------------------------------------------------------------------
    def find_parent_attribute_value(self, node_id, attribute_name) -> None:
        if node_id is not None:
            attribute_value = None
            attribute_value = self._data_assembly.GetAttributeOrDefault(node_id, attribute_name, attribute_value)
            if attribute_value is None:
                return self.find_parent_attribute_value(self._data_assembly.GetParent(node_id),attribute_name)
            return attribute_value
        return