from trame.app import get_server
from paraview import simple as pvsimple

from fespp_on_trame.app.core.tree import Tree
from fespp_on_trame.app.core.engine import source_resolver
from fespp_on_trame.app.core.element_type import for_kind
from fespp_on_trame.app.utils.naming import make_valid_vtk_name


def _find_array_in_store(store, name):
    """Look up a VTK array by name with fallback to the sanitized
    variant. FESPP's C++ side names arrays via `MakeValidNodeName`
    (strip chars outside `[-.0-9A-Z_a-z]`); the tree's `title`
    attribute keeps the original RESQML title with spaces / parens /
    etc., so a direct lookup by title may miss the array."""
    if store is None or not name:
        return None
    arr = store.GetArray(name)
    if arr is not None:
        return arr
    sanitized = make_valid_vtk_name(name)
    if sanitized != name:
        return store.GetArray(sanitized)
    return None


server = get_server()
state = server.state
controller = server.controller


# Grouping kinds. A grouping / representation node may legitimately
# become active by virtue of a checked DESCENDANT; a property leaf may
# NOT — it has to be checked on its own id.
# 'Frame'/'MarkerFrame' are folders-for-selection: they become active
# via a checked child log/marker, so include them.
from fespp_on_trame.app.core.node_kinds import GROUPING_KINDS as _GROUPING_KINDS


def _drill_to_inner(vtk_out):
    """If vtk_out is a vtkPartitionedDataSetCollection, return its first
    inner partition; otherwise return as-is."""
    if vtk_out is None:
        return None
    if hasattr(vtk_out, 'GetPartitionedDataSet'):
        try:
            pds = vtk_out.GetPartitionedDataSet(0)
            if pds is not None and pds.GetNumberOfPartitions() > 0:
                return pds.GetPartitionAsDataObject(0)
        except Exception:
            return vtk_out
    return vtk_out


class Activator:
    """Reacts to active-node changes in the three trees and refreshes the
    Attributes panel (color editor + active proxy) for the active node.
    ColorBy is owned by `ui_active_array_by_rep` (the eye state) via
    `source_resolver.apply_color_array` — activating a node never colors
    the 3D view."""

    def __init__(self, tree: Tree, source_registry=None, ijk_lookup=None):
        self._tree = tree
        self._source_registry = source_registry
        # Callable resolving rep_path → IjkGrid instance (or None).
        # Lets us enumerate a specific grid's sources without globbing
        # registration names across the global proxy manager.
        self._ijk_lookup = ijk_lookup

        @state.change("ui_active_node_reservoir")
        def on_ui_active_node_reservoir_change(ui_active_node_reservoir, **kwargs):
            self._handle_reservoir_change(ui_active_node_reservoir)

        @state.change("ui_active_node_surface")
        def on_ui_active_node_surface_change(ui_active_node_surface, **kwargs):
            self._handle_surface_change(ui_active_node_surface)

        @state.change("ui_active_node_well")
        def on_ui_active_node_well_change(ui_active_node_well, **kwargs):
            self._handle_well_change(ui_active_node_well)

    def _is_node_active_able(self, node_id, select_list):
        """Return True when `node_id` may become the active node given
        the current checkbox state (`select_list` = `ui_select_node_*`,
        a list of TREE NODE IDS).

        Semantics:
          - A PROPERTY leaf (Property* / TimeSeries / MultiRealization*)
            is activatable ONLY when its OWN id is checked. Being under
            a checked rep is NOT enough: the dependency expansion
            (`tree_views._expand_selection_with_deps`) auto-adds the rep
            id to the select list whenever ANY one of its properties is
            checked, so an "under a checked rep" rule would let every
            unchecked sibling property activate.
          - A REP / grouping / intermediate node is activatable when it
            is checked, OR sits under a checked grouping/rep, OR has a
            checked descendant (the "check a property, click its parent
            rep" case — the rep loads as a side effect).
        Works in both auto and manual load modes since the select list
        is the raw checkbox state."""
        if not select_list or node_id is None or node_id == 0:
            return False
        self_path = self._tree.find_path(node_id)
        if not self_path:
            return False
        sel_paths = [p for p in (self._tree.find_path(s) for s in select_list) if p]
        # The node itself is checked → always activatable.
        if self_path in sel_paths:
            return True
        kind = self._tree.find_type(node_id) or ""
        is_property = for_kind(kind).is_property()
        if is_property:
            # Property leaf must be checked on its own id (handled above).
            return False
        # Rep / grouping / intermediate node.
        is_rep = self._tree.find_representation_node(node_id) == node_id
        is_rep_or_group = is_rep or (kind in _GROUPING_KINDS)
        for sel_path in sel_paths:
            if self_path.startswith(sel_path + "/"):
                return True                       # node under a checked grouping/rep
            if is_rep_or_group and sel_path.startswith(self_path + "/"):
                return True                       # rep/group whose checked descendant loaded it
        return False

    def _handle_reservoir_change(self, ui_active_node_reservoir):
        if not ui_active_node_reservoir or len(ui_active_node_reservoir) == 0:
            state.update({
                "ptc_show_vcr": False,
                "active_color_array_name": "",
                "active_property_kind": "",
                "coe_panels": [],
                "active_representation_path": "",
                "active_representation_has_properties": False,
                "ui_active_node_reservoir_type_rep": "",
                "ui_active_node_reservoir_type": "",
                "ui_active_node_reservoir_title": "",
                "ui_active_node_reservoir_rep_path": "",
                "ui_active_node_reservoir_array_name": "",
            })
            return
        node_id = ui_active_node_reservoir[0]
        # Reject activation of a node whose subtree isn't checked. Trame
        # batches the mutation and re-fires this handler with the empty value
        # on next flush, going through the reset branch above.
        if not self._is_node_active_able(node_id, state.ui_select_node_reservoir):
            state.ui_active_node_reservoir = []
            return
        type_node_rep = self._tree.find_representation_type(node_id)
        type_node = self._tree.find_type(node_id)
        title_node = self._tree.find_title(node_id)

        # Multi-realization synthetic nodes act as property leaves: the actual
        # array name lives in propTitle. Plain TimeSeries nodes are also
        # property leaves (one per property title).
        is_multireal = for_kind(type_node).is_multi_realization()
        is_property = for_kind(type_node).is_property()
        ts_ancestor_id = self._tree.find_parent_node_id_with_type(node_id, "TimeSeries")
        is_ts_property = is_property and (
            ts_ancestor_id is not None or type_node == "MultiRealizationTimeSeries"
        )
        property_kind = ""
        if type_node in ("ContinuousProperty", "DiscreteProperty", "CategoricalProperty"):
            property_kind = type_node
        elif type_node in ("TimeSeries", "MultiRealization", "MultiRealizationTimeSeries"):
            pk = self._tree.find_attribute_value(node_id, "propKind")
            if pk:
                property_kind = pk
        state.update({
            "ui_active_node_reservoir_type_rep": type_node_rep,
            "ui_active_node_reservoir_type": type_node,
            "ui_active_node_reservoir_title": title_node,
            "active_property_kind": property_kind,
            "ptc_show_vcr": is_ts_property,
            "active_color_array_name": "" if not is_property else state.active_color_array_name,
            # Reservoir-scoped twin of `active_color_array_name` — the
            # threshold panel gates on THIS one. The shared var is cleared
            # by any WELL / SURFACE tab activation (a wellbore, a surface,
            # a channel...), which used to grey the reservoir-scoped
            # threshold buttons even though the reservoir active property
            # never changed. Same pattern as `ui_active_node_reservoir_rep_path`.
            # Best-effort seed from the node title (FESPP names VTK arrays
            # via the same sanitizer); `_refresh_active_property_editor`
            # upgrades it to the array name actually found on the data —
            # but if that step short-circuits (rep still loading), the twin
            # must NOT keep the PREVIOUS property's array.
            "ui_active_node_reservoir_array_name": (
                "" if not is_property
                else make_valid_vtk_name(title_node or "")
            ),
            # Active node path (used by the COE channel retarget; a no-op for
            # grid properties, but kept current so a stale wellbore channel
            # path doesn't linger).
            "active_color_array_path": (self._tree.find_path(node_id) or "") if is_property else "",
            "coe_panels": [] if not is_property else state.coe_panels,
        })

        rep_block_path, rep_type, rep_source = self._activate_reservoir_rep(node_id)
        # Pin the reservoir-tab rep path so the reservoir-scoped panels
        # (threshold / IJK slicer) keep resolving the GRID even after a later
        # wellbore / surface selection clobbers `active_representation_path`.
        state.ui_active_node_reservoir_rep_path = rep_block_path or ""

        # Multi-realization synthetic nodes carry the actual VTK array name in
        # propTitle (the title attribute is the vtk-sanitized variant).
        array_name = title_node
        if is_multireal:
            prop_title = self._tree.find_attribute_value(node_id, "propTitle")
            if prop_title:
                array_name = prop_title
        if is_property and array_name:
            try:
                self._refresh_active_property_editor(
                    rep_block_path, rep_type, rep_source,
                    array_name, is_ts_property,
                )
            except Exception:
                pass

    def _activate_reservoir_rep(self, node_id):
        """Resolve the active rep for the reservoir tree node, switch
        the ParaView active source to its dedicated ExtractBlock proxy
        (non-IjkGrid), and update the rep-related state vars. IjkGrid
        keeps its slicer-based flow — no SetActiveSource here.

        Returns `(rep_block_path, rep_type, rep_source)` for downstream
        consumers (color application) — rep_source is None for IjkGrid
        and for any path where the registry has nothing yet."""
        rep_node_id = self._tree.find_representation_node(node_id)
        rep_block_path = ""
        rep_type = None
        rep_source = None
        rep_has_properties = False
        if rep_node_id is not None:
            rep_type = self._tree.find_type(rep_node_id)
            rep_has_properties = self._tree.has_property_descendant(rep_node_id)
            block_path = self._tree.find_path(rep_node_id)
            if block_path:
                rep_block_path = block_path
                if not for_kind(rep_type).is_ijk_grid() and self._source_registry is not None:
                    rep_source = self._source_registry.get(block_path)
                    if rep_source is not None:
                        pvsimple.SetActiveSource(rep_source)
                        try:
                            controller.on_active_proxy_change()
                        except Exception:
                            pass
        state.active_representation_has_properties = rep_has_properties
        state.active_representation_path = rep_block_path
        return rep_block_path, rep_type, rep_source

    def _resolve_color_target_source(self, rep_block_path, rep_type, rep_source, active_view):
        """Find the visible source to color for a property activation.

        Non-IjkGrid: the rep_source is the default render target; if a
        chain proxy is currently visible, that's what the user actually
        sees — colorize the deepest visible one (the others are
        upstream filters in the same pipeline).

        IjkGrid: pick the visible source from the matching IjkGrid
        instance only (no global GetSources glob, otherwise we could
        latch onto a sibling grid's slicer). Priority order:
          0. visible threshold proxy;
          1. rep_data filter (used in volume mode at full extent — PV6's
             vtkExplicitStructuredGridCrop produces degenerate output
             with the IjkGrid input);
          2. per-axis slicers (slice mode);
          3. slicervolume (cropped range mode).
        """
        target_source = None
        if rep_type and not for_kind(rep_type).is_ijk_grid():
            target_source = rep_source
            if (
                active_view and target_source is not None
                and self._source_registry is not None
            ):
                disp = pvsimple.GetDisplayProperties(target_source, view=active_view)
                if disp and not disp.Visibility:
                    visibles = self._source_registry.all_visible_thresholds(rep_block_path)
                    if visibles:
                        target_source = visibles[-1]
            return target_source

        ijk = self._ijk_lookup(rep_block_path) if self._ijk_lookup else None
        if ijk is None:
            return None

        def _pick_visible(proxies):
            for p in proxies:
                if p is None:
                    continue
                try:
                    d = pvsimple.GetDisplayProperties(p, view=active_view)
                except Exception:
                    d = None
                if d is not None and d.Visibility:
                    return p
            return None

        target_source = _pick_visible(ijk.all_threshold_sources())
        if target_source is None:
            target_source = _pick_visible([ijk._src_extract_init])
        if target_source is None:
            target_source = _pick_visible(ijk._all_slice_sources())
        if target_source is None:
            target_source = _pick_visible(ijk._src_volumes)
        return target_source

    def _refresh_active_property_editor(self, rep_block_path, rep_type,
                                        rep_source, array_name, is_ts_property):
        """Activation plumbing for a property node: set the PV active source,
        fire the active-proxy / TimeControl hooks and refresh the
        Attributes-panel color editor. Does NOT color the 3D view — coloring
        is owned by the eye / active-array path
        (`source_resolver.apply_color_array`). Per the activation contract,
        activating a node only highlights it; it never changes the view.

        The proxy info cache is unreliable for arrays the C++ pipeline added
        in place, so the actual (cell/point) VTK array name handed to the
        color editor is read from the client-side object directly."""
        active_view = pvsimple.GetActiveView()
        target_source = self._resolve_color_target_source(
            rep_block_path, rep_type, rep_source, active_view,
        )
        if target_source is None:
            return

        pvsimple.SetActiveSource(target_source)
        # Invalidate the sticky proxy info cache, then resolve the real VTK
        # array name (the sanitized variant) so the color editor binds to the
        # right array. No ColorBy / LUT / Render here — the view is untouched.
        try:
            target_source.GetClientSideObject().Modified()
        except Exception:
            pass
        target_source.UpdatePipelineInformation()
        target_source.UpdatePipeline()
        try:
            vtk_out = target_source.GetClientSideObject().GetOutputDataObject(0)
            vtk_inner = _drill_to_inner(vtk_out)
            vtk_cd = vtk_inner.GetCellData() if vtk_inner is not None and hasattr(vtk_inner, 'GetCellData') else None
            vtk_pd = vtk_inner.GetPointData() if vtk_inner is not None and hasattr(vtk_inner, 'GetPointData') else None
            found_arr = _find_array_in_store(vtk_cd, array_name) or _find_array_in_store(vtk_pd, array_name)
            if found_arr is not None:
                actual_name = found_arr.GetName()
                if actual_name:
                    array_name = actual_name
        except Exception:
            pass

        controller.on_active_proxy_change()
        # on_data_loaded is the TimeControl refresh hook — only needed for
        # time-series properties (the time slider resets its range).
        if is_ts_property:
            controller.on_data_loaded()
        controller.update_color_editor(array_name)
        state.ui_active_node_reservoir_array_name = array_name

    def _publish_active_color_state(self, node_id):
        """Publish the COE-mode state (`active_color_array_name` /
        `active_property_kind`) for the active node of the WELL / SURFACE
        tab.

        The COE / SolidColor panel reads `active_color_array_name` to
        decide colormap-vs-solid mode. For a property leaf we set the kind
        + array name and push the per-view LUT into the COE; for anything
        else (frame folder, marker, wellbore, trajectory geometry) we
        clear so the panel falls back to Solid.

        Only publishes the editor STATE — the actual ColorBy for a channel
        is done by the eye (`toggle_dataarray_color`)."""
        type_node = self._tree.find_type(node_id) or ""
        is_multireal = for_kind(type_node).is_multi_realization()
        is_property = for_kind(type_node).is_property()
        if not is_property:
            state.active_color_array_name = ""
            state.active_property_kind = ""
            state.active_color_array_path = ""
            return
        # The active NODE's own path — drives the COE's read-only channel
        # retarget so a wellbore-channel node shows ITS data even when a
        # sibling channel of the same frame is the one displayed.
        try:
            state.active_color_array_path = self._tree.find_path(node_id) or ""
        except Exception:
            state.active_color_array_path = ""
        property_kind = ""
        if type_node in ("ContinuousProperty", "DiscreteProperty", "CategoricalProperty"):
            property_kind = type_node
        elif type_node in ("TimeSeries", "MultiRealization", "MultiRealizationTimeSeries"):
            pk = self._tree.find_attribute_value(node_id, "propKind")
            if pk:
                property_kind = pk
        array_name = self._tree.find_title(node_id) or ""
        if is_multireal:
            prop_title = self._tree.find_attribute_value(node_id, "propTitle")
            if prop_title:
                array_name = prop_title
        state.active_property_kind = property_kind
        state.active_color_array_name = array_name
        if array_name:
            try:
                controller.update_color_editor(array_name)
            except Exception:
                pass

    def _handle_surface_change(self, ui_active_node_surface):
        if ui_active_node_surface and len(ui_active_node_surface) > 0:
            node_id = ui_active_node_surface[0]
            if not self._is_node_active_able(node_id, state.ui_select_node_surface):
                state.ui_active_node_surface = []
                return
            type_node = self._tree.find_type(node_id)
            state.update({"ui_active_node_surface_type": type_node})
            self._activate_rep_source(node_id)
            self._publish_active_color_state(node_id)
        else:
            state.update({"ui_active_node_surface_type": ""})
            state.active_representation_path = ""
            state.active_representation_has_properties = False
            state.active_color_array_name = ""
            state.active_property_kind = ""
            state.active_color_array_path = ""

    def _handle_well_change(self, ui_active_node_well):
        if ui_active_node_well and len(ui_active_node_well) > 0:
            node_id = ui_active_node_well[0]
            if not self._is_node_active_able(node_id, state.ui_select_node_well):
                state.ui_active_node_well = []
                return
            type_node = self._tree.find_type(node_id)
            state.update({"ui_active_node_well_type": type_node})
            self._activate_rep_source(node_id)
            self._publish_active_color_state(node_id)
        else:
            state.update({"ui_active_node_well_type": ""})
            state.active_representation_path = ""
            state.active_representation_has_properties = False
            state.active_color_array_name = ""
            state.active_property_kind = ""

    def refresh_active(self):
        """Re-run the active-node handlers for whatever is currently
        active. Used after a manual Show: the active state changed
        BEFORE the load (so the rep didn't exist when the @state.change
        fired and the ColorBy wiring short-circuited); re-run now that the
        rep exists.

        Skip the call when the active node is not consistent with the
        current selection — VTreeview's update_selected will sync
        ui_active on the next flush and the handler will fire then. The
        guard avoids a wasted reject → reset → cleared → property handler
        chain on every grid switch."""
        try:
            active = state.ui_active_node_reservoir
            if active and self._is_node_active_able(active[0], state.ui_select_node_reservoir):
                self._handle_reservoir_change(active)
        except Exception:
            pass
        try:
            active = state.ui_active_node_surface
            if active and self._is_node_active_able(active[0], state.ui_select_node_surface):
                self._handle_surface_change(active)
        except Exception:
            pass
        try:
            active = state.ui_active_node_well
            if active and self._is_node_active_able(active[0], state.ui_select_node_well):
                self._handle_well_change(active)
        except Exception:
            pass

    def _activate_rep_source(self, node_id):
        """Set active_representation_path and activate the matching
        extracted source for a surface/well tree node. IjkGrid is never
        expected here."""
        rep_node_id = self._tree.find_representation_node(node_id)
        if rep_node_id is None:
            state.active_representation_path = ""
            state.active_representation_has_properties = False
            return
        block_path = self._tree.find_path(rep_node_id)
        state.active_representation_has_properties = self._tree.has_property_descendant(rep_node_id)
        state.active_representation_path = block_path or ""
        if not block_path or self._source_registry is None:
            return
        rep_source = self._source_registry.get(block_path)
        if rep_source is not None:
            try:
                pvsimple.SetActiveSource(rep_source)
                try:
                    controller.on_active_proxy_change()
                except Exception:
                    pass
            except Exception:
                pass
