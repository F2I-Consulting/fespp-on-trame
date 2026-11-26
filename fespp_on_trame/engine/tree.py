import re
import unicodedata

from trame.app import get_server

from fespp_on_trame.engine import element_type as _et
from fespp_on_trame.engine import node_facts
from fespp_on_trame.engine import node_kinds
from fespp_on_trame.app.ui.tree_icons import get_primary_icon

server = get_server()
state = server.state

state.setdefault("ui_subtree_reservoir", [])
state.setdefault("ui_subtree_surface", [])
state.setdefault("ui_subtree_well", [])


_NATURAL_SPLIT_RE = re.compile(r"(\d+)")
_PARTIAL_PREFIX = "!!!PARTIAL!!!"

# Grid-folder layout: the grid geometry rep kinds, and the organizational
# per-grid folders that are never individually selected (excluded from a
# grouping's tri-state universe, but recursed into).
# The geometry leaf a container (GridContainer) wraps in its "properties"
# folder (engine/node_kinds)
_GRID_GEOMETRY_KINDS = node_kinds.CONTAINED_KINDS
_GRID_KINDS = ("IjkGrid", "UnstructuredGrid", "ExplicitStructuredGrid")
_SURFACE_KINDS = ("Grid2d", "Grid2dRepresentation", "PointSet", "Polyline",
                  "PolylineSet", "TriangulatedSet")
_GRID_SUBFOLDER_KINDS = (
    "PropertiesFolder", "BlockedWellboreFolder", "SubRepresentationFolder",
)


def _sibling_sort_key(node):
    """Case-insensitive, natural (numeric-aware) sort key for a treeview
    node dict, by its display title, so siblings render alphabetically
    at every level and 'Grid2' sorts before 'Grid10'. The
    '!!!PARTIAL!!!' display marker is stripped so a partial stub sorts by
    its real name among its siblings.

    PRESENTATIONAL ONLY: reorders the emitted `ui_subtree_*` dicts (what
    the VTreeview renders). Node identity everywhere else is by
    `id` / `path`, never by sibling list position, so reordering is
    safe."""
    title = str(node.get("title") or "")
    if title.startswith(_PARTIAL_PREFIX):
        title = title[len(_PARTIAL_PREFIX):]
    # Strip accents (NFKD → drop combining marks) so an accented initial
    # sorts with its base letter rather than after 'Z'; dependency-free,
    # no locale needed.
    title = "".join(
        c for c in unicodedata.normalize("NFKD", title.strip())
        if not unicodedata.combining(c)
    ).casefold()
    natural = [
        int(part) if part.isdigit() else part
        for part in _NATURAL_SPLIT_RE.split(title)
    ]
    # Markers carry an `md` field (FESPP's "md" node attribute): they
    # sort by DEPTH among their siblings (the geologist's reading
    # order), falling back to the title on equal MDs. Non-marker nodes
    # get +inf there, so mixed levels keep pure alphabetical order.
    try:
        md_key = float(node.get("md")) if node.get("md") is not None else float("inf")
    except (TypeError, ValueError):
        md_key = float("inf")
    # A node flagged `_sort_first` (the hoisted grid geometry) sorts before
    # every sibling at its level; others keep natural alphabetical order.
    return [0 if node.get("_sort_first") else 1, md_key, *natural]


def _hoist_grid_geometry(node_type, children):
    """Grid-folder layout DISPLAY re-map: lift a grid's geometry rep (kind
    IjkGrid/UnstructuredGrid, titled 'SolidColor') OUT of its PropertiesFolder
    so it shows as a top-level node under the GridContainer, leaving the
    PropertiesFolder to hold only the real properties.

    DISPLAY-ONLY: the live vtkDataAssembly still holds the rep under the
    PropertiesFolder (its mapper key / find_node_id path), so every
    id/path/uuid lookup is untouched; only the emitted treeview dicts move.
    `children` (the GridContainer's child-dict list) is mutated in place."""
    if node_type != "GridContainer":
        return
    props_folder = next(
        (c for c in children if c.get("type") == "PropertiesFolder"), None)
    if props_folder is None:
        return
    folder_children = props_folder.get("children") or []
    geom = next(
        (c for c in folder_children if c.get("type") in _GRID_GEOMETRY_KINDS),
        None,
    )
    if geom is None:
        return
    folder_children.remove(geom)
    # Frontend-only display label: FESPP names this rep "SolidColor" (grid drawn
    # with no property = solid colour). Show it as "geometry" to match the
    # user's mental model. Identity (id / path / uuid) is untouched.
    geom["title"] = "geometry"
    # Pin geometry above the properties/ · block wellbore/ · SubRep/ folders
    # (see _sibling_sort_key) instead of letting it sort alphabetically.
    geom["_sort_first"] = True
    if not folder_children:
        # Geometry-only grid (no real properties): the props folder is left
        # empty, so drop it and the tree shows just the hoisted geometry,
        # with no empty 'properties/' folder.
        children.remove(props_folder)
    children.append(geom)


def _eye_field(element_type):
    """Map an ElementType to the per-node `eye` token the tree view reads
    to decide which eye block (rep / array / marker) to render.

    Returns the EyeKind value string ('rep' / 'array' / 'marker') or None
    when the node carries no eye of its own (groupings, Frame/MarkerFrame
    folders — their children carry the eyes)."""
    desc = element_type.eye_descriptor()
    return desc.kind.value if desc is not None else None


class Tree():
    """Wraps the C++ vtkDataAssembly built by FESPP and exposes Python
    helpers used by the rest of the app. set_tree() re-parses the live
    assembly into the three Trame state lists ui_subtree_*; everything
    else is read-only lookup."""

    def __init__(self, data_assembly):
        self._data_assembly = data_assembly
        # {code: label} of FESPP's TreeViewNodeType enum, published by the
        # plugin itself (repo_query.type_enum). Empty until fed, and stays
        # empty with a plugin build that does not publish it; `renders` and
        # `find_role` then fall back (see `_type_entry`).
        self._type_enum = {}
        self._data_hierarchy_reservoir = []
        self._data_hierarchy_well = []
        self._data_hierarchy_surface = []

        # Kinds that count as "representations", i.e. have a VTK source
        # behind them. find_representation_node() relies on it (through
        # renders()) to walk up from a leaf (Property, Marker, ...) to its
        # rep parent.
        # 'Wellbore' (the WellboreFeature, e.g. "55/33-3") is NOT a
        # representation: it is a pure folder with no geometry of its own.
        # It stays a grouping (expand/collapse + bulk-select); only its
        # child Trajectory/Frame/Marker/Completion reps carry an eye +
        # colour.
        # FALLBACK ONLY: `renders()` asks the plugin (MapperType) and comes
        # here just for a plugin build that does not publish its enum table.
        # Do not extend it; extend the C++ enum instead.
        self._representation_type_in = ['IjkGrid', 'Sub', 'UnstructuredGrid', 'Trajectory', 'Completion', 'Perfo', 'Frame', 'MarkerFrame', 'WellboreMarker', 'SeismicWellboreFrame', 'Grid2d', 'PointSet', 'Polyline', 'PolylineSet', 'TriangulatedSet', 'BlockedWellbore', 'partial']

    def set_type_enum(self, mapping) -> None:
        """Feed the plugin's own {code: label} table (repo_query.type_enum)."""
        self._type_enum = dict(mapping or {})

    def _node_type(self, node_id):
        """The node's FINE type: "IjkGrid", "PolylineSet", "TriangulatedSet",
        "ContinuousProperty", "Trajectory", "Frame"...

        This is the FESAPI-derived name, `SimplifyXmlTag(getXmlTag())` on the
        C++ side, and it is what the whole app matches on.

        NOT resolvable from "typeCode": the numeric enum is a much COARSER
        tree ROLE (every PolylineSet and every TriangulatedSet carries code 2,
        "Representation"). Reading the type from the code would collapse every
        geometry into one. See find_role.

        Older plugin builds publish this string as "kind", although in RESQML
        kind means the PropertyKind (depth, volume, pressure), which lives on
        "propertyKind". Those builds also carry the numeric code under the
        name "type", so a bare read of "type" there returns "2" instead of
        "PolylineSet": hence the digit test and the "kind" fallback rather
        than a plain `or`."""
        value = self._data_assembly.GetAttributeOrDefault(node_id, "type", None)
        if value is None or str(value).isdigit():
            return self._data_assembly.GetAttributeOrDefault(node_id, "kind", None)
        return value

    def find_role(self, node_id):
        """The node's coarse tree ROLE ("Representation", "Properties",
        "Wellbore", "PropertiesFolder"...) from the numeric "typeCode",
        resolved through the table the plugin publishes.

        This is the axis the enum actually describes: what the node IS in the
        tree, not which RESQML class it wraps. None when the plugin build does
        not publish either the code or the table."""
        entry = self._type_entry(node_id)
        return entry.get("label") if entry else None

    def _type_entry(self, node_id):
        """The plugin's table row for this node, or None when either the code
        or the table is missing (a plugin build that does not publish them)."""
        code = self._data_assembly.GetAttributeOrDefault(node_id, "typeCode", None)
        if code is None:
            # Older plugin builds carry the same number under "type", where it
            # is a digit string; current builds put the fine type name there.
            legacy = self._data_assembly.GetAttributeOrDefault(node_id, "type", None)
            code = legacy if legacy is not None and str(legacy).isdigit() else None
        if code is None or not self._type_enum:
            return None
        return self._type_enum.get(str(code))

    def renders(self, node_id) -> bool:
        """True when the node has geometry of ITS OWN, what the plugin calls
        MapperType Mapper or MapperSet.

        Asked of the plugin rather than matched against a list of type names;
        the `_representation_type_in` list is only the fallback for a plugin
        build without the enum table. A property or a marker is NOT one of
        these: it carries data but rides on a parent rep, which the plugin
        calls MapperType Data."""
        entry = self._type_entry(node_id)
        if entry is not None:
            return entry.get("mapper") in ("Mapper", "MapperSet")
        return (self.find_type(node_id) or "") in self._representation_type_in

    def find_prop_type(self, node_id):
        """The property's own type (Continuous / Discrete / Categorical),
        which decides the icon and which colour editor applies. Older plugin
        builds name it "propKind" (see `_node_type` on the word kind)."""
        return (self._data_assembly.GetAttributeOrDefault(node_id, "propType", None)
                or self._data_assembly.GetAttributeOrDefault(node_id, "propKind", None))

    def add_subtreeview_data(self, parent_id: int, child_index: int, treeview_type, disabled=False) -> None:
        """Recursive walker that builds the nested treeview dict for a
        single child of `parent_id`. Returns
        `{"treeview": {...}, "treeview_type": str}`."""
        node_id = self._data_assembly.GetChild(parent_id, child_index)
        node_label = self._data_assembly.GetAttributeOrDefault(node_id, "label", None)
        node_title = self._data_assembly.GetAttributeOrDefault(node_id, "title", None)
        node_type = self._node_type(node_id)
        # The property's own type, set by FESPP on synthetic TS / MR / MRTS
        # leaves so they show the right primary icon (the synthetic wrapper
        # aspect goes on a secondary badge).
        node_prop_kind = self.find_prop_type(node_id)
        node_path = self._data_assembly.GetNodePath(node_id)

        # Mark ANY partial node (a partial rep stub OR a partial property
        # leaf, e.g. a WellboreChannel with no data). Use a per-node LOCAL
        # flag; do NOT mutate the function-scoped `disabled` forwarded to
        # children, else a partial rep's real descendants would be wrongly
        # disabled. A partial object has only Title + UUID, no data, so it
        # must show "!!!PARTIAL!!!" and be uncheckable.
        node_is_partial = not _et.for_kind(node_type).is_selectable()
        if node_is_partial and not (node_title or '').startswith('!!!PARTIAL!!!'):
            node_title = '!!!PARTIAL!!! ' + (node_title or node_label or '')

        if treeview_type == "unknown":
            if (node_type in ['IjkGrid', 'UnstructuredGrid']
                    or (node_type == 'GridContainer'
                        and self.family_type(node_id) not in _SURFACE_KINDS)):
                treeview_type = "reservoir"
            elif node_type == 'GridContainer':
                treeview_type = "surface"
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
        # the per-view eye rendering on the Vue side can, for an array
        # node, look up "is this array the active one for this view's
        # parent rep" without a Python round-trip. For a rep node
        # itself, rep_path == path.
        rep_ancestor_id = self.find_representation_node(node_id)
        rep_path_attr = self.find_path(rep_ancestor_id) if rep_ancestor_id is not None else None

        # is_grouping: node that behaves as a FOLDER in the tree; the
        # custom checkbox renders a tri-state indicator from
        # descendant_ids ∩ ui_select_node_*, and checking it bulk-selects
        # its children. Two sub-cases:
        #   - pure organisational nodes (Collection / Wellbore / Feature /
        #     Interpretation / Partial), with no VTK source of their own.
        #   - frames (Frame = WellboreFrame logs, MarkerFrame = marker
        #     set): these DO own a per-view source, but in the TREE they
        #     are folders (no eye of their own). They still count as
        #     representations (see `renders`) so `find_representation_node`
        #     on a channel/marker leaf resolves UP to the frame.
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
        # Marker depth: drives the depth-first sibling sort (see
        # `_sibling_sort_key`); absent on every other node kind.
        node_md = self._data_assembly.GetAttributeOrDefault(node_id, "md", None)
        if node_md:
            data["treeview"]["md"] = node_md
        # is_ts / is_mr drive the secondary badges of the tree widget
        # (clock + "MR" chip). Only synthetic node types have them.
        data["treeview"]["is_ts"] = _et.for_kind(node_type).is_time_series()
        data["treeview"]["is_mr"] = _et.for_kind(node_type).is_multi_realization()
        data["treeview"]["is_grouping"] = is_grouping
        data["treeview"]["eye"] = eye
        if is_grouping:
            # Only populated for groupings: the leaves / reps do not
            # need it (their checkbox is binary on their own id).
            # Exclude partial descendants so the grouping's tri-state can
            # still reach "all selected" (a partial can never be selected).
            data["treeview"]["descendant_ids"] = self.find_all_selectable_descendant_ids(node_id)
        if disabled or node_is_partial:
            data["treeview"]["disabled"] = True

        data["treeview_type"] = treeview_type

        children_count = self._data_assembly.GetNumberOfChildren(node_id)
        # Multi-realization synthetic nodes are leaves: their internals are
        # not exposed.
        if children_count > 0 and not _et.for_kind(node_type).is_multi_realization():
            data["treeview"]["children"] = []
            for i in range(children_count):
                subTreeview = self.add_subtreeview_data(node_id, i, treeview_type, disabled)
                data["treeview"]["children"].append(subTreeview["treeview"])
                data["treeview_type"] = subTreeview["treeview_type"]
            # Grid-folder layout: lift the grid geometry rep out of its
            # properties folder to a top-level GridContainer child (display).
            _hoist_grid_geometry(node_type, data["treeview"]["children"])
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
            child_kind = self._node_type(child_id)
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
                node_type = self._node_type(node_id)
                node_prop_kind = self.find_prop_type(node_id)
                node_path = self._data_assembly.GetNodePath(node_id)

                # Per-iteration reset: a previous partial sibling must
                # not leave `disabled` latched True for the nodes after it.
                disabled = False
                node_is_partial = not _et.for_kind(node_type).is_selectable()
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
                if dispatch_kind == 'GridContainer':
                    # filed by the geometry it wraps (a surface's container
                    # goes to the Surface tab, 27/10)
                    dispatch_kind = self.family_type(node_id)
                if dispatch_kind in ['IjkGrid', 'UnstructuredGrid', 'GridContainer']:
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
                # this is its own path. See the matching comment in
                # add_subtreeview_data for why it is published on every node.
                top_rep_ancestor = self.find_representation_node(node_id)
                top_rep_path = self.find_path(top_rep_ancestor) if top_rep_ancestor is not None else None

                treeview["parent_id"] = root_id
                treeview["id"] = node_id
                treeview["title"] = node_title
                treeview["path"] = node_path
                treeview["rep_path"] = top_rep_path
                treeview["type"] = node_type
                treeview["icon"] = get_primary_icon(node_type, node_prop_kind)
                node_md = self._data_assembly.GetAttributeOrDefault(node_id, "md", None)
                if node_md:
                    treeview["md"] = node_md
                treeview["is_ts"] = _et.for_kind(node_type).is_time_series()
                treeview["is_mr"] = _et.for_kind(node_type).is_multi_realization()
                # Eye token (rep / array / marker / None): drives which eye
                # block the tree view renders. Keyed on the node's own kind
                # (NOT dispatch_kind, which is only for tab routing).
                top_et = _et.for_kind(node_type)
                treeview["eye"] = _eye_field(top_et)
                # Same tri-state fields as add_subtreeview_data, so a
                # TOP-LEVEL envelope (a Wellbore folder, the GridContainer)
                # shows the tri-state checkbox like its nested folders.
                treeview["is_grouping"] = top_et.is_grouping()
                if top_et.is_grouping():
                    treeview["descendant_ids"] = self.find_all_selectable_descendant_ids(node_id)
                treeview["parent_id"] = 0
                if disabled or node_is_partial:
                    treeview["disabled"] = True

                children_count = self._data_assembly.GetNumberOfChildren(node_id)
                if children_count > 0 and not _et.for_kind(node_type).is_multi_realization():
                    treeview["children"] = []
                    for i in range(children_count):
                        subTreeview = self.add_subtreeview_data(node_id, i, treeview_type, disabled)
                        treeview["children"].append(subTreeview["treeview"])
                        treeview_type = subTreeview["treeview_type"]
                    # Grid-folder layout: hoist grid geometry to a top-level
                    # GridContainer child (display only).
                    _hoist_grid_geometry(node_type, treeview["children"])
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

        node_type = self._node_type(node_id)
        if node_type:
            if _et.for_kind(node_type).is_ijk_grid():
                return self._data_assembly.GetAttributeOrDefault(node_id, "label", None)
            else:
                return self.find_ijkgrid(self._data_assembly.GetParent(node_id))
        return

    def find_parent_node_id_with_type(self, node_id, type) -> None:
        """Walk up from `node_id` and return the first ancestor of the
        given kind, or None."""
        if node_id == 0 or self._data_assembly is None:
            return

        node_type = self._node_type(node_id)
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
            child_type = self._node_type(child)
            if child_type == type:
                return child
        return None

    def iter_nodes(self, root=0):
        """``(node id, its children)`` for every node at or under `root`, a
        parent before its children. The shared walk for a reader that scans
        the whole file: the health findings and the Statistics tree's list of
        the properties the file holds use it instead of each keeping a stack
        of its own."""
        asm = self._data_assembly
        if asm is None:
            return
        stack = [root]
        while stack:
            nid = stack.pop()
            try:
                # The DIRECT children: vtkDataAssembly.GetChildNodes walks the
                # whole subtree by default, which hands a node back once per
                # ancestor it hangs under.
                children = [asm.GetChild(nid, i)
                            for i in range(asm.GetNumberOfChildren(nid))]
            except Exception:
                children = []
            yield nid, children
            stack.extend(reversed(children))

    def find_all_descendant_ids(self, node_id) -> list:
        """Collect every descendant node id under `node_id`, recursively.
        Used by the UI dependency expansion when the user checks a
        grouping (Wellbore / Collection / Partial / Feature /
        Interpretation): all descendants must be added to the
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
        cannot be loaded), and the parent grouping can still reach
        'all selected'."""
        if node_id is None or self._data_assembly is None:
            return []
        # Grid-folder layout: when the walk STARTS at a grid's PropertiesFolder,
        # exclude the geometry rep (displayed + toggled as a top-level sibling,
        # so bulk-toggling 'properties/' leaves the geometry in place).
        # At a GridContainer the geometry IS included so a bulk-toggle moves it.
        exclude_geometry = (
            self._node_type(node_id)
            == "PropertiesFolder"
        )
        out = []

        def _walk(nid):
            try:
                n = self._data_assembly.GetNumberOfChildren(nid)
            except Exception:
                return
            for i in range(n):
                c = self._data_assembly.GetChild(nid, i)
                kind = self._node_type(c)
                if not _et.for_kind(kind).is_selectable():
                    continue
                # Organizational grid sub-folders are never individually
                # selected: exclude them (else a GridContainer tri-state can
                # never reach 'all selected') but still recurse INTO them.
                if kind not in _GRID_SUBFOLDER_KINDS and not (
                    exclude_geometry and kind in _GRID_GEOMETRY_KINDS
                ):
                    out.append(c)
                _walk(c)

        _walk(node_id)
        return out

    def find_path(self, node_id) -> None:
        if node_id == 0 or self._data_assembly is None:
            return
        return self._data_assembly.GetNodePath(node_id)

    def find_type(self, node_id) -> None:
        """Return the node's fine type set by the C++ side
        (IjkGrid / ContinuousProperty / ...); see `_node_type`."""
        if node_id == 0 or self._data_assembly is None:
            return
        return self._node_type(node_id)

    def container_geometry_type(self, node_id):
        """The type of the geometry a container (GridContainer) wraps — an
        IjkGrid, a TriangulatedSet... — or "" when none is found. The
        container "_gridfolder_<uuid>" names its geometry node "_<uuid>";
        a geometry known by reference only says its type in supporttype."""
        if node_id is None or node_id == 0 or self._data_assembly is None:
            return ""
        name = self._data_assembly.GetNodeName(node_id) or ""
        if not name.startswith("_gridfolder_"):
            return ""
        geom = self._data_assembly.FindFirstNodeWithName("_" + name[len("_gridfolder_"):])
        if geom is None or geom < 0:
            return ""
        kind = self._node_type(geom) or ""
        if kind.lower() == "partial":
            kind = self._data_assembly.GetAttributeOrDefault(geom, "supporttype", "") or ""
        return kind

    #: the rows of the IJK grids whose geometry is a lattice, their container's
    #: path each (app/features/time_depth_models reads them off the grids'
    #: XML): the Seismic family (engine/tree_families.name_of)
    lattice_rows = frozenset()

    def family_type(self, node_id):
        """The type a node is filed under in the tabs (node_kinds.FAMILIES):
        its own, a container's being that of its geometry — since 27/10 a
        surface sits in a container like a grid, and goes to the Surface
        tab."""
        kind = self.find_type(node_id) or ""
        if kind == "GridContainer":
            return self.container_geometry_type(node_id) or kind
        return kind

    def find_title(self, node_id) -> None:
        if node_id == 0 or self._data_assembly is None:
            return
        return self._data_assembly.GetAttributeOrDefault(node_id, "title", None)

    def find_rep_title(self, rep_id) -> str:
        """The name a user knows the representation `rep_id` by. A grid's
        rep node is its geometry LEAF, literally titled "SolidColor" (the
        grid-folder layout): the enclosing GridContainer carries the grid's
        actual name, so that one is returned instead. "" without a title."""
        title = self.find_title(rep_id) or ""
        if title == "SolidColor":
            container = self.find_parent_node_id_with_type(rep_id, "GridContainer")
            if container is not None:
                title = self.find_title(container) or title
        return title

    def find_label(self, node_id) -> None:
        if node_id == 0 or self._data_assembly is None:
            return
        label = self._data_assembly.GetAttributeOrDefault(node_id, "label", None)
        if label:
            return label
        return

    def find_node_id(self, path) -> None:
        # A None / empty path is an ACCESS VIOLATION inside
        # vtkDataAssembly::GetFirstNodeByPath (kills the whole process).
        if not path or self._data_assembly is None:
            return None
        nid = self._data_assembly.GetFirstNodeByPath(path)
        return None if nid is None or nid < 0 else nid

    def find_representation_node(self, node_id) -> None:
        """Walk up from `node_id` until a representation kind is found
        (one that renders, see `renders`). Returns None if no rep
        ancestor exists."""
        if node_id == 0 or self._data_assembly is None:
            return

        node_type = self._node_type(node_id)
        if node_type:
            if self.renders(node_id):
                return node_id
            # Grid-folder layout: a grid sub-folder groups MULTIPLE sub-objects
            # (SubReps / BlockedWellbores) with no single enclosing rep, so do
            # NOT climb to the GridContainer and resolve to the grid geometry.
            # Mirrors the C++ resolveGridGeometryRepId early-return.
            if node_type in ("SubRepresentationFolder", "BlockedWellboreFolder"):
                return
            # Grid-folder layout: a grid's geometry rep is a SIBLING under its
            # PropertiesFolder, not an ancestor of its props. When the up-walk
            # reaches the props folder / grid container, descend to the
            # GridContainer's geometry rep child instead of climbing past it
            # (which would return None and break a property's colour eye / stats).
            if node_type in ("PropertiesFolder", "GridContainer"):
                container = node_id if node_type == "GridContainer" \
                    else self.find_parent_node_id_with_type(node_id, "GridContainer")
                if container is not None:
                    # a grid's, a surface's, a point set's... (27/10: a
                    # point set's property found no geometry, so it neither
                    # ticked it nor coloured it)
                    for kind in _GRID_GEOMETRY_KINDS:
                        rep = self.find_first_child_of_type(container, kind)
                        if rep is None:
                            props = self.find_first_child_of_type(container, "PropertiesFolder")
                            if props is not None:
                                rep = self.find_first_child_of_type(props, kind)
                        if rep is not None:
                            return rep
                return
            return self.find_representation_node(self._data_assembly.GetParent(node_id))
        return

    def has_property_descendant(self, node_id) -> bool:
        """True if any descendant is a property (engine/node_facts)."""
        if node_id is None or self._data_assembly is None:
            return False
        children_count = self._data_assembly.GetNumberOfChildren(node_id)
        for i in range(children_count):
            child_id = self._data_assembly.GetChild(node_id, i)
            child_type = self.find_type(child_id) or ""
            if node_facts.is_property_kind(child_type):
                return True
            if self.has_property_descendant(child_id):
                return True
        return False

    def find_attribute_value(self, node_id, attribute_name) -> None:
        if node_id is not None:
            return self._data_assembly.GetAttributeOrDefault(node_id, attribute_name, None)
        return

    def ijk_grids_of(self, paths):
        """{uuid: path of its geometry node} of the IJK grids `paths` show
        (a grid's row, its geometry, a property under it)."""
        from fespp_on_trame.engine import row_object
        out = {}
        for p in paths or ():
            nid = self.find_node_id(p)
            rid = self.find_representation_node(nid) if nid is not None else None
            if rid is None or self.find_type(rid) != "IjkGrid":
                continue
            path = self.find_path(rid) or ""
            uuid = row_object.uuid_of(path.rsplit("/", 1)[-1])
            if uuid:
                out[uuid] = path
        return out

    def find_node_id_by_uuid(self, uuid):
        """Resolve a tree node id from a RESQML uuid. Node names are the
        uuid prefixed with '_'. Returns None if no such node exists."""
        if not uuid or self._data_assembly is None:
            return None
        node_id = self._data_assembly.FindFirstNodeWithName("_" + uuid)
        return node_id if node_id and node_id > 0 else None

    def find_parent_attribute_value(self, node_id, attribute_name) -> None:
        """Walk up from `node_id` and return the value of the nearest
        ancestor's attribute, or None."""
        if node_id is None or node_id == 0:
            return

        attribute_value = self._data_assembly.GetAttributeOrDefault(node_id, attribute_name, None)

        if attribute_value is not None:
            return attribute_value

        return self.find_parent_attribute_value(self._data_assembly.GetParent(node_id), attribute_name)

    def find_ancestor_title_of_kind(self, node_id, kind):
        """Walk up from `node_id` (inclusive) and return the title of the
        nearest ancestor whose kind == `kind`, else None. Used to get the
        WellboreFeature name (kind 'Wellbore') from a Trajectory node."""
        if node_id is None or node_id == 0 or self._data_assembly is None:
            return None
        if self.find_type(node_id) == kind:
            return self.find_title(node_id)
        return self.find_ancestor_title_of_kind(
            self._data_assembly.GetParent(node_id), kind)
