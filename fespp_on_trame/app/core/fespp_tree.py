from trame.app import get_server

from fespp_on_trame.app.ui.config.tree_icons import get_icon_for_type, get_primary_icon

server = get_server()
state = server.state

state.setdefault("ui_subtree_reservoir", [])
state.setdefault("ui_subtree_surface", [])
state.setdefault("ui_subtree_well", [])


class Tree():
    """Wraps the C++ vtkDataAssembly built by FESPP and exposes Python
    helpers used by the rest of the app. set_tree() re-parses the live
    assembly into the three Trame state lists ui_subtree_*; everything
    else is read-only lookup."""

    def __init__(self, data_assembly):
        self._data_assembly = data_assembly
        self._data_hierarchy_reservoir = []
        self._data_hierarchy_well = []
        self._data_hierarchy_surface = []

        # Kinds that count as "representations" — i.e. have a VTK source
        # behind them. Used by find_representation_node() to walk up
        # from a leaf (Property, Marker, ...) to its rep parent.
        self._representation_type_in = ['IjkGrid', 'Sub', 'UnstructuredGrid', 'Wellbore', 'Trajectory', 'Completion', 'Perfo', 'Frame', 'MarkerFrame', 'WellboreMarker', 'SeismicWellboreFrame', 'Grid2d', 'PointSet', 'Polyline', 'PolylineSet', 'TriangulatedSet', 'partial']

    def add_subtreeview_data(self, parent_id: int, child_index: int, treeview_type, disabled=False) -> None:
        """Recursive walker that builds the nested treeview dict for a
        single child of `parent_id`. Returns
        `{"treeview": {...}, "treeview_type": str}`."""
        node_id = self._data_assembly.GetChild(parent_id, child_index)
        node_label = self._data_assembly.GetAttributeOrDefault(node_id, "label", None)
        node_title = self._data_assembly.GetAttributeOrDefault(node_id, "title", None)
        node_type = self._data_assembly.GetAttributeOrDefault(node_id, "kind", None)
        # propKind: underlying property type set by FESPP on synthetic
        # TS / MR / MRTS leaves so we can show the right primary icon
        # (the synthetic wrapper aspect goes on a secondary badge).
        node_prop_kind = self._data_assembly.GetAttributeOrDefault(node_id, "propKind", None)
        node_path = self._data_assembly.GetNodePath(node_id)

        if treeview_type == "unknown":
            if node_type in ['IjkGrid', 'UnstructuredGrid']:
                treeview_type = "reservoir"
            elif node_type in ['Wellbore', 'Trajectory', 'Completion', 'Perfo', 'Frame', 'MarkerFrame', 'WellboreMarker', 'SeismicWellboreFrame']:
                treeview_type = "well"
            elif node_type in ['Grid2d', 'PointSet', 'Polyline', 'PolylineSet', 'TriangulatedSet']:
                treeview_type = "surface"
            elif node_type in ['partial', 'Partial']:
                disabled = True
                node_supportType = self._data_assembly.GetAttributeOrDefault(node_id, "supporttype", None)
                if node_supportType in ['IjkGrid', 'UnstructuredGrid']:
                    node_title = '!!!PARTIAL!!! ' + (node_title or "")
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
        data["treeview"]["icon"] = get_primary_icon(node_type, node_prop_kind)
        # is_ts / is_mr drive the secondary badges in tree_views.py
        # (clock + "MR" chip). Only synthetic node types have them.
        data["treeview"]["is_ts"] = node_type in ("TimeSeries", "MultiRealizationTimeSeries")
        data["treeview"]["is_mr"] = node_type in ("MultiRealization", "MultiRealizationTimeSeries")
        if disabled:
            data["treeview"]["disabled"] = True

        data["treeview_type"] = treeview_type

        children_count = self._data_assembly.GetNumberOfChildren(node_id)
        # Multi-realization synthetic nodes are leaves: don't expose
        # their internals.
        if children_count > 0 and node_type not in ("MultiRealization", "MultiRealizationTimeSeries"):
            data["treeview"]["children"] = []
            for i in range(children_count):
                subTreeview = self.add_subtreeview_data(node_id, i, treeview_type, disabled)
                data["treeview"]["children"].append(subTreeview["treeview"])
                data["treeview_type"] = subTreeview["treeview_type"]
        return data

    def _resolve_dispatch_kind(self, node_id):
        """Walk into a grouping subtree (Feature / Interpretation) to
        find the first non-grouping descendant kind. Used to route a
        top-level grouping node to the right tab (reservoir / surface /
        well) based on the kind of its first real representation child."""
        try:
            children_count = self._data_assembly.GetNumberOfChildren(node_id)
        except Exception:
            return None
        for i in range(children_count):
            child_id = self._data_assembly.GetChild(node_id, i)
            child_kind = self._data_assembly.GetAttributeOrDefault(child_id, "kind", None)
            if child_kind in ("Feature", "Interpretation"):
                inner = self._resolve_dispatch_kind(child_id)
                if inner:
                    return inner
                continue
            if child_kind:
                return child_kind
        return None

    def set_tree(self, data_assembly):
        """Re-parse the live vtkDataAssembly into the three Trame state
        lists (ui_subtree_reservoir / surface / well). Top-level
        Feature / Interpretation grouping nodes (created by the
        non-Flat tree-hierarchy modes) are kept at top level and
        dispatched via the kind of their first real descendant."""
        self._data_hierarchy_reservoir = []
        self._data_hierarchy_well = []
        self._data_hierarchy_surface = []
        disabled = False
        self._data_assembly = data_assembly
        if self._data_assembly is not None:
            root_id = 0
            for i in range(data_assembly.GetNumberOfChildren(root_id)):
                node_id = self._data_assembly.GetChild(root_id, i)
                node_label = self._data_assembly.GetAttributeOrDefault(node_id, "label", None)
                node_title = self._data_assembly.GetAttributeOrDefault(node_id, "title", None)
                node_type = self._data_assembly.GetAttributeOrDefault(node_id, "kind", None)
                node_prop_kind = self._data_assembly.GetAttributeOrDefault(node_id, "propKind", None)
                node_path = self._data_assembly.GetNodePath(node_id)

                # When the top-level node is a grouping inserted by an
                # alternate tree-hierarchy mode (Feature /
                # Interpretation), use the first real descendant's kind
                # for dispatching to the correct tab.
                dispatch_kind = node_type
                if node_type in ("Feature", "Interpretation"):
                    dispatch_kind = self._resolve_dispatch_kind(node_id) or node_type

                treeview = {}
                treeview_type = "unknown"
                if dispatch_kind in ['IjkGrid', 'UnstructuredGrid']:
                    treeview_type = "reservoir"
                elif dispatch_kind in ['Wellbore', 'Trajectory', 'Completion', 'Perfo', 'Frame', 'MarkerFrame', 'WellboreMarker', 'SeismicWellboreFrame']:
                    treeview_type = "well"
                elif dispatch_kind in ['Grid2d', 'PointSet', 'Polyline', 'PolylineSet', 'TriangulatedSet']:
                    treeview_type = "surface"
                elif node_type in ['partial', 'Partial']:
                    disabled = True
                    node_supportType = self._data_assembly.GetAttributeOrDefault(node_id, "supporttype", None)
                    treeview["disabled"] = True,
                    if node_supportType in ['IjkGrid', 'UnstructuredGrid']:
                        node_title = '!!!PARTIAL!!! ' + (node_title or "")
                        treeview_type = "reservoir"
                    elif node_supportType in ['Wellbore', 'Trajectory', 'Completion', 'Perfo', 'Frame', 'MarkerFrame', 'WellboreMarker', 'SeismicWellboreFrame']:
                        node_title = node_label
                        treeview_type = "well"
                    elif node_supportType in ['Grid2d', 'PointSet', 'Polyline', 'PolylineSet', 'TriangulatedSet']:
                        node_title = node_label
                        treeview_type = "surface"
                treeview["parent_id"] = root_id
                treeview["id"] = node_id
                treeview["title"] = node_title
                treeview["path"] = node_path
                treeview["type"] = node_type
                treeview["icon"] = get_primary_icon(node_type, node_prop_kind)
                treeview["is_ts"] = node_type in ("TimeSeries", "MultiRealizationTimeSeries")
                treeview["is_mr"] = node_type in ("MultiRealization", "MultiRealizationTimeSeries")
                treeview["parent_id"] = 0
                if disabled:
                    treeview["disabled"] = True

                children_count = self._data_assembly.GetNumberOfChildren(node_id)
                if children_count > 0 and node_type not in ("MultiRealization", "MultiRealizationTimeSeries"):
                    treeview["children"] = []
                    for i in range(children_count):
                        subTreeview = self.add_subtreeview_data(node_id, i, treeview_type, disabled)
                        treeview["children"].append(subTreeview["treeview"])
                        treeview_type = subTreeview["treeview_type"]
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

    def find_ijkgrid(self, node_id) -> None:
        """Walk up from `node_id` and return the label of the first
        ancestor of kind IjkGrid (or None)."""
        if node_id == 0 or self._data_assembly is None:
            return

        node_type = self._data_assembly.GetAttributeOrDefault(node_id, "kind", None)
        if node_type:
            if node_type == 'IjkGrid':
                return self._data_assembly.GetAttributeOrDefault(node_id, "label", None)
            else:
                return self.find_ijkgrid(self._data_assembly.GetParent(node_id))
        return

    def find_parent_node_id_with_type(self, node_id, type) -> None:
        """Walk up from `node_id` and return the first ancestor of the
        given kind, or None."""
        if node_id == 0 or self._data_assembly is None:
            return

        node_type = self._data_assembly.GetAttributeOrDefault(node_id, "kind", None)
        if node_type:
            if node_type == type:
                return node_id
            else:
                return self.find_parent_node_id_with_type(self._data_assembly.GetParent(node_id), type)
        return

    def find_first_child_of_type(self, node_id, type) -> None:
        """Return the node id of the first direct child of `node_id`
        with the given kind, or None. Used by the UI dependency
        expansion (e.g. Wellbore → its WellboreTrajectory child)."""
        if node_id is None or self._data_assembly is None:
            return None
        try:
            n = self._data_assembly.GetNumberOfChildren(node_id)
        except Exception:
            return None
        for i in range(n):
            child = self._data_assembly.GetChild(node_id, i)
            child_type = self._data_assembly.GetAttributeOrDefault(child, "kind", None)
            if child_type == type:
                return child
        return None

    def find_all_descendant_ids(self, node_id) -> list:
        """Collect every descendant node id under `node_id`, recursively.
        Used by the UI dependency expansion when the user checks a
        grouping (Wellbore / Collection / Partial / Feature /
        Interpretation) — all descendants must be added to the
        selection so the UI checkboxes mirror what FESPP loads."""
        if node_id is None or self._data_assembly is None:
            return []
        out = []

        def _walk(nid):
            try:
                n = self._data_assembly.GetNumberOfChildren(nid)
            except Exception:
                return
            for i in range(n):
                c = self._data_assembly.GetChild(nid, i)
                out.append(c)
                _walk(c)

        _walk(node_id)
        return out

    def find_ijkgrid_property_name(self, node_label, list_selected) -> None:
        """Among the given selectors, find one whose IjkGrid ancestor
        has `node_label` as label, and return the title of the selector
        node (typically a property)."""
        if node_label is None or self._data_assembly is None:
            return
        for selected in list_selected:
            node_id = self._data_assembly.GetFirstNodeByPath(selected)
            if node_id:
                ijkgrid_node = self.find_parent_node_id_with_type(node_id, 'IjkGrid')
                if ijkgrid_node:
                    ijkgrid_label = self._data_assembly.GetAttributeOrDefault(ijkgrid_node, "label", None)
                    if ijkgrid_label is not None and node_label == ijkgrid_label:
                        return self._data_assembly.GetAttributeOrDefault(node_id, "title", None)
        return

    def find_path(self, node_id) -> None:
        if node_id == 0 or self._data_assembly is None:
            return
        return self._data_assembly.GetNodePath(node_id)

    def find_type(self, node_id) -> None:
        """Return the `kind` attribute set by the C++ side
        (IjkGrid / ContinuousProperty / ...)."""
        if node_id == 0 or self._data_assembly is None:
            return
        return self._data_assembly.GetAttributeOrDefault(node_id, "kind", None)

    def find_title(self, node_id) -> None:
        if node_id == 0 or self._data_assembly is None:
            return
        return self._data_assembly.GetAttributeOrDefault(node_id, "title", None)

    def find_label(self, node_id) -> None:
        if node_id == 0 or self._data_assembly is None:
            return
        label = self._data_assembly.GetAttributeOrDefault(node_id, "label", None)
        if label:
            return label
        return

    def find_node_id(self, path) -> None:
        return self._data_assembly.GetFirstNodeByPath(path)

    def find_representation_node(self, node_id) -> None:
        """Walk up from `node_id` until a representation kind is found
        (one of self._representation_type_in). Returns None if no rep
        ancestor exists."""
        if node_id == 0 or self._data_assembly is None:
            return

        node_type = self._data_assembly.GetAttributeOrDefault(node_id, "kind", None)
        if node_type:
            if node_type in self._representation_type_in:
                return node_id
            else:
                return self.find_representation_node(self._data_assembly.GetParent(node_id))
        return

    def find_representation_type(self, node_id) -> None:
        """Same as find_representation_node but returns the kind string
        of the rep ancestor instead of its node id."""
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

    def has_property_descendant(self, node_id) -> bool:
        """True if any descendant has a property kind (anything
        containing "Property", or MultiRealization / MR-TS)."""
        if node_id is None or self._data_assembly is None:
            return False
        children_count = self._data_assembly.GetNumberOfChildren(node_id)
        for i in range(children_count):
            child_id = self._data_assembly.GetChild(node_id, i)
            child_type = self.find_type(child_id) or ""
            if "Property" in child_type or child_type in ("MultiRealization", "MultiRealizationTimeSeries"):
                return True
            if self.has_property_descendant(child_id):
                return True
        return False

    def find_attribute_value(self, node_id, attribute_name) -> None:
        if node_id is not None:
            return self._data_assembly.GetAttributeOrDefault(node_id, attribute_name, None)
        return

    def find_parent_attribute_value(self, node_id, attribute_name) -> None:
        """Walk up from `node_id` and return the value of the nearest
        ancestor's attribute, or None."""
        if node_id is None or node_id == 0:
            return

        attribute_value = self._data_assembly.GetAttributeOrDefault(node_id, attribute_name, None)

        if attribute_value is not None:
            return attribute_value

        return self.find_parent_attribute_value(self._data_assembly.GetParent(node_id), attribute_name)
