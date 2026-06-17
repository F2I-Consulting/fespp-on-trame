import re
import unicodedata

from trame.app import get_server

from fespp_on_trame.app.core import element_type as _et
from fespp_on_trame.app.ui.drawer.config.tree_icons import get_primary_icon

server = get_server()
state = server.state

state.setdefault("ui_subtree_reservoir", [])
state.setdefault("ui_subtree_surface", [])
state.setdefault("ui_subtree_well", [])


_NATURAL_SPLIT_RE = re.compile(r"(\d+)")
_PARTIAL_PREFIX = "!!!PARTIAL!!!"


def _sibling_sort_key(node):
    """Case-insensitive, natural (numeric-aware) sort key for a treeview
    node dict, by its display title — so siblings render alphabetically
    at every level, and 'Grid2' sorts before 'Grid10'. The
    '!!!PARTIAL!!!' display marker is stripped so a partial stub sorts by
    its real name among its siblings.

    PRESENTATIONAL ONLY: this reorders the emitted `ui_subtree_*` dicts
    (what the VTreeview renders). Node identity everywhere else is by
    `id` / `path`, never by sibling list position (the C++ assembly walk,
    `find_*`, dataset/partition indexing, MR/timeseries, selection are all
    order-independent), so reordering these dicts is safe."""
    title = str(node.get("title") or "")
    if title.startswith(_PARTIAL_PREFIX):
        title = title[len(_PARTIAL_PREFIX):]
    # Strip accents (NFKD → drop combining marks) so 'Éclair' sorts with
    # 'E' rather than after 'Z' — dependency-free, no locale needed.
    title = "".join(
        c for c in unicodedata.normalize("NFKD", title.strip())
        if not unicodedata.combining(c)
    ).casefold()
    return [
        int(part) if part.isdigit() else part
        for part in _NATURAL_SPLIT_RE.split(title)
    ]


def _eye_field(element_type):
    """Map an ElementType to the per-node `eye` token the tree view reads
    to decide which eye block (rep / array / marker) to render.

    Returns the EyeKind value string ('rep' / 'array' / 'marker') or None
    when the node carries no eye of its own (groupings, Frame/MarkerFrame
    folders — their children carry the eyes). This is the single source of
    truth that replaces the scattered `item.type !== 'Frame' …` JS gates."""
    desc = element_type.eye_descriptor()
    return desc.kind.value if desc is not None else None


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
        # NOTE: 'Wellbore' (the WellboreFeature, e.g. "55/33-3") is NOT a
        # representation — it's a pure folder (C++: isGroupingType /
        # MapperType::Folder, no geometry of its own). It stays a grouping
        # via is_grouping/_GROUPING_KINDS (expand/collapse + bulk-select);
        # only its child Trajectory/Frame/Marker/Completion reps carry an
        # eye + colour.
        self._representation_type_in = ['IjkGrid', 'Sub', 'UnstructuredGrid', 'Trajectory', 'Completion', 'Perfo', 'Frame', 'MarkerFrame', 'WellboreMarker', 'SeismicWellboreFrame', 'Grid2d', 'PointSet', 'Polyline', 'PolylineSet', 'TriangulatedSet', 'partial']

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

        # Mark ANY partial node (a partial rep stub OR a partial property
        # leaf, e.g. a WellboreChannel with no data) regardless of the
        # inherited treeview_type. Use a per-node LOCAL flag — do NOT
        # mutate the function-scoped `disabled` that is forwarded to
        # children (line ~116), else a partial rep's real descendants
        # would be wrongly disabled. A partial object has only Title +
        # UUID, no data → it must show "!!!PARTIAL!!!" and be uncheckable.
        node_is_partial = node_type in ('partial', 'Partial')
        if node_is_partial and not (node_title or '').startswith('!!!PARTIAL!!!'):
            node_title = '!!!PARTIAL!!! ' + (node_title or node_label or '')

        if treeview_type == "unknown":
            if node_type in ['IjkGrid', 'UnstructuredGrid']:
                treeview_type = "reservoir"
            elif node_type in ['Wellbore', 'Trajectory', 'Completion', 'Perfo', 'Frame', 'MarkerFrame', 'WellboreMarker', 'SeismicWellboreFrame']:
                treeview_type = "well"
            elif node_type in ['Grid2d', 'PointSet', 'Polyline', 'PolylineSet', 'TriangulatedSet']:
                treeview_type = "surface"
            elif node_is_partial:
                # Route a top-level partial stub to the right tab via its
                # supporttype attribute (the title is already marked above).
                node_supportType = self._data_assembly.GetAttributeOrDefault(node_id, "supporttype", None)
                if node_supportType in ['IjkGrid', 'UnstructuredGrid']:
                    treeview_type = "reservoir"
                elif node_supportType in ['Wellbore', 'Trajectory', 'Completion', 'Perfo', 'Frame', 'MarkerFrame', 'WellboreMarker', 'SeismicWellboreFrame', 'WellboreChannel']:
                    treeview_type = "well"
                elif node_supportType in ['Grid2d', 'PointSet', 'Polyline', 'PolylineSet', 'TriangulatedSet']:
                    treeview_type = "surface"

        # rep_path: the path of the enclosing representation node, so
        # the per-view eye rendering on the Vue side can — for an array
        # node — look up "is this array the active one for this view's
        # parent rep" without a Python round-trip. For a rep node
        # itself, rep_path == path.
        rep_ancestor_id = self.find_representation_node(node_id)
        rep_path_attr = self.find_path(rep_ancestor_id) if rep_ancestor_id is not None else None

        # is_grouping: node that behaves as a FOLDER in the tree — the
        # custom checkbox renders a tri-state indicator (marked /
        # minus-box / blank) from descendant_ids ∩ ui_select_node_*, and
        # checking it bulk-selects its children.
        #
        # Two sub-cases:
        #   - pure organisational nodes (Collection / Wellbore / Feature /
        #     Interpretation / Partial) — no VTK source of their own.
        #   - frames (Frame = WellboreFrame logs, MarkerFrame = marker
        #     set): these DO own a per-view source (C++ MapperSet), but in
        #     the TREE they are folders — no eye of their own, checking
        #     them selects every child log / marker. They stay in
        #     `_representation_type_in` so `find_representation_node` on a
        #     channel/marker leaf still resolves UP to the frame (the
        #     rendering anchor hosting the per-(rep, view) extractor).
        #     i.e. "folder for the tree, representation for the source".
        et = _et.for_kind(node_type)
        is_grouping = et.is_grouping()
        eye = _eye_field(et)

        data = {}
        data["treeview"] = {}
        data["treeview"]["parent_id"] = parent_id
        data["treeview"]["id"] = node_id
        data["treeview"]["title"] = node_title
        data["treeview"]["path"] = node_path
        data["treeview"]["rep_path"] = rep_path_attr
        data["treeview"]["type"] = node_type
        data["treeview"]["icon"] = get_primary_icon(node_type, node_prop_kind)
        # is_ts / is_mr drive the secondary badges in tree_views.py
        # (clock + "MR" chip). Only synthetic node types have them.
        data["treeview"]["is_ts"] = node_type in ("TimeSeries", "MultiRealizationTimeSeries")
        data["treeview"]["is_mr"] = node_type in ("MultiRealization", "MultiRealizationTimeSeries")
        data["treeview"]["is_grouping"] = is_grouping
        data["treeview"]["eye"] = eye
        if is_grouping:
            # Only populated for groupings — the leaves / reps don't
            # need it (their checkbox is binary on their own id).
            # Exclude partial descendants so the grouping's tri-state can
            # still reach "all selected" (a partial can never be selected).
            data["treeview"]["descendant_ids"] = self.find_all_selectable_descendant_ids(node_id)
        if disabled or node_is_partial:
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
            # Alphabetical sibling order at this level (hierarchy kept).
            data["treeview"]["children"].sort(key=_sibling_sort_key)
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

                # Per-iteration reset — a previous partial sibling must
                # not leave `disabled` latched True for the nodes after it.
                disabled = False
                node_is_partial = node_type in ('partial', 'Partial')
                if node_is_partial and not (node_title or '').startswith('!!!PARTIAL!!!'):
                    node_title = '!!!PARTIAL!!! ' + (node_title or node_label or '')

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
                elif node_is_partial:
                    node_supportType = self._data_assembly.GetAttributeOrDefault(node_id, "supporttype", None)
                    if node_supportType in ['IjkGrid', 'UnstructuredGrid']:
                        treeview_type = "reservoir"
                    elif node_supportType in ['Wellbore', 'Trajectory', 'Completion', 'Perfo', 'Frame', 'MarkerFrame', 'WellboreMarker', 'SeismicWellboreFrame', 'WellboreChannel']:
                        treeview_type = "well"
                    elif node_supportType in ['Grid2d', 'PointSet', 'Polyline', 'PolylineSet', 'TriangulatedSet']:
                        treeview_type = "surface"
                # rep_path: enclosing rep's path. For a rep node itself
                # this is its own path. See sibling add_subtreeview_data
                # comment for why we publish this on every node.
                top_rep_ancestor = self.find_representation_node(node_id)
                top_rep_path = self.find_path(top_rep_ancestor) if top_rep_ancestor is not None else None

                treeview["parent_id"] = root_id
                treeview["id"] = node_id
                treeview["title"] = node_title
                treeview["path"] = node_path
                treeview["rep_path"] = top_rep_path
                treeview["type"] = node_type
                treeview["icon"] = get_primary_icon(node_type, node_prop_kind)
                treeview["is_ts"] = node_type in ("TimeSeries", "MultiRealizationTimeSeries")
                treeview["is_mr"] = node_type in ("MultiRealization", "MultiRealizationTimeSeries")
                # eye token (rep / array / marker / None) — drives which eye
                # block the tree view renders. Keyed on the node's own kind
                # (NOT dispatch_kind, which is only for tab routing). A
                # top-level rep (e.g. a Flat-mode IjkGrid) must still get its
                # eye even though set_tree omits is_grouping here.
                treeview["eye"] = _eye_field(_et.for_kind(node_type))
                treeview["parent_id"] = 0
                if disabled or node_is_partial:
                    treeview["disabled"] = True

                children_count = self._data_assembly.GetNumberOfChildren(node_id)
                if children_count > 0 and node_type not in ("MultiRealization", "MultiRealizationTimeSeries"):
                    treeview["children"] = []
                    for i in range(children_count):
                        subTreeview = self.add_subtreeview_data(node_id, i, treeview_type, disabled)
                        treeview["children"].append(subTreeview["treeview"])
                        treeview_type = subTreeview["treeview_type"]
                    # Alphabetical sibling order under this top-level node.
                    treeview["children"].sort(key=_sibling_sort_key)
                if treeview_type == "reservoir":
                    if treeview and treeview not in self._data_hierarchy_reservoir:
                        self._data_hierarchy_reservoir.append(treeview)
                elif treeview_type == "well":
                    if treeview and treeview not in self._data_hierarchy_well:
                        self._data_hierarchy_well.append(treeview)
                elif treeview_type == "surface":
                    if treeview and treeview not in self._data_hierarchy_surface:
                        self._data_hierarchy_surface.append(treeview)
            # Alphabetical order of the TOP-LEVEL siblings within each tab.
            self._data_hierarchy_reservoir.sort(key=_sibling_sort_key)
            self._data_hierarchy_well.sort(key=_sibling_sort_key)
            self._data_hierarchy_surface.sort(key=_sibling_sort_key)
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

    def find_all_selectable_descendant_ids(self, node_id) -> list:
        """Like `find_all_descendant_ids` but EXCLUDES partial nodes
        (kind 'partial'/'Partial'). Used for a grouping's tri-state
        universe and for bulk add/remove so a reference-only partial
        stub is never pulled into the selection (it has no checkbox and
        can't be loaded), and the parent grouping can still reach
        'all selected'."""
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
                kind = self._data_assembly.GetAttributeOrDefault(c, "kind", None)
                if kind in ('partial', 'Partial'):
                    continue
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
