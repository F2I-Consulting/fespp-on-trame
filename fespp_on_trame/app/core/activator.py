import time

from trame.app import get_server
from paraview import simple as pvsimple

from fespp_on_trame.app.core.tree import Tree
from fespp_on_trame.app.core.engine import source_resolver
from fespp_on_trame.app.utils.naming import make_valid_vtk_name


def _find_array_in_store(store, name):
    """Look up a VTK array by name with fallback to the sanitized
    variant. FESPP's C++ side names arrays via `MakeValidNodeName`
    (strip chars outside `[-.0-9A-Z_a-z]`); the tree's `title`
    attribute keeps the original RESQML title with spaces / parens /
    etc., so a direct lookup by title may miss the array. Retry with
    the sanitized name to catch that case."""
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


# Grouping kinds (mirror of tree_views.py grouping list / C++ enum.h
# isGroupingType). A grouping / representation node may legitimately
# become active by virtue of a checked DESCENDANT; a property leaf may
# NOT — it has to be checked on its own id. Duplicated here (rather than
# imported from the UI module) to avoid a circular import.
# 'Frame'/'MarkerFrame' are folders-for-selection (see tree_views.py):
# they become active via a checked child log/marker, so include them.
_GROUPING_KINDS = (
    "Collection", "Wellbore", "Partial", "Feature", "Interpretation",
    "Frame", "MarkerFrame",
)


def _nan_opacity_from_state():
    """Read NaN opacity from state.nan_color (#RRGGBBAA), default 0.0
    (NaN cells fully transparent unless the user dials in an alpha)."""
    try:
        hex_val = (state.nan_color or "").lstrip("#")
        if len(hex_val) >= 8:
            return int(hex_val[6:8], 16) / 255
    except (ValueError, IndexError):
        pass
    return 0.0


def _all_displays_for_rep(rep_block_path, rep_type, view, target_source=None, target_display=None,
                          source_registry=None, ijk_lookup=None):
    """Every display proxy that renders rep_block_path. Used to fan-out
    ColorBy so chain proxies stay in sync with their parent source even
    when one of them is hidden.

    Source resolution:
      * UG: rep<sanitized_path> filter + every chain proxy registered
        for the rep (via source_registry.all_chain_proxies).
      * IJK: every source owned by the matching IjkGrid instance
        (rep_data + slicers + volume + chain proxies), resolved via
        ijk_lookup(rep_block_path). This is per-grid so we never grab
        sources from a different IJK grid that happens to be loaded
        in parallel."""
    if view is None:
        return []
    sanitized = (rep_block_path or "").replace('/', '_')
    expected_rep_filter = "rep" + sanitized
    is_ijk = rep_type == 'IjkGrid'
    sources = []
    # Pull non-IjkGrid chain proxies directly from source_registry — name
    # patterns can collide once chains are nested (thr_grid_a vs
    # thr_grid_a_b), so the authoritative list is the one the data
    # layer maintains.
    chain_set = set()
    if not is_ijk and source_registry is not None:
        try:
            chain_proxies = source_registry.all_chain_proxies(rep_block_path)
        except AttributeError:
            chain_proxies = []
        for p in chain_proxies:
            sources.append(p)
            chain_set.add(id(p))
    elif is_ijk and ijk_lookup is not None:
        ijk = ijk_lookup(rep_block_path)
        if ijk is not None:
            try:
                for s in ijk.all_render_sources():
                    sources.append(s)
                    chain_set.add(id(s))
            except Exception:
                pass
    # rep<sanitized_path> filter — for UG it's the ExtractBlock; for
    # IJK it's the rep_data extractor which the lookup above may have
    # already added (chain_set dedupes).
    for source_id, source in pvsimple.GetSources().items():
        if id(source) in chain_set:
            continue
        if source_id[0] == expected_rep_filter:
            sources.append(source)
            chain_set.add(id(source))
    out = []
    seen_displays = set()
    if target_display is not None:
        seen_displays.add(id(target_display))
        out.append(target_display)
    for s in sources:
        if s is target_source:
            continue
        try:
            d = pvsimple.GetDisplayProperties(s, view=view)
        except Exception:
            continue
        if d is not None and id(d) not in seen_displays:
            seen_displays.add(id(d))
            out.append(d)
    return out


def _drill_to_inner(vtk_out):
    """If vtk_out is a vtkPartitionedDataSetCollection, return its first
    inner partition; otherwise return as-is. Defensive helper kept in
    case a downstream wrapping ever adds a composite layer."""
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
    """Reacts to active-node changes in the three trees and updates the
    Attributes panel + LUT/PWF for the active node. ColorBy itself is
    owned by ui_active_array_by_rep (the eye state) — this class just
    refreshes the panel and re-applies ColorBy when the eye is open."""

    def __init__(self, tree: Tree, source_registry=None, ijk_lookup=None):
        self._tree = tree
        self._source_registry = source_registry
        # Callable resolving rep_path → IjkGrid instance (or None).
        # Lets us enumerate a specific grid's sources without globbing
        # registration names across the global proxy manager.
        self._ijk_lookup = ijk_lookup

        # Track the array currently colorized per rep. ParaView keys
        # color bars by LUT (one per array name globally), so when a rep
        # switches property A → B we must hide A's bar — otherwise it
        # stacks on top of B's bar in the view. We only hide A's bar if
        # NO other rep is still colored by A (multiple reps can share a
        # LUT/bar).
        self._current_array_by_rep = {}

        state.setdefault("ui_active_node_reservoir", [])
        state.setdefault("ui_active_node_surface", [])
        state.setdefault("ui_active_node_well", [])
        state.setdefault("ui_active_node_reservoir_type_rep", "")
        state.setdefault("ui_active_node_reservoir_type", "")
        state.setdefault("ui_active_node_reservoir_title", "")
        # Underlying property kind of the active node — drives the
        # editor switch in solid_color_panel (continuous LUT vs
        # categorical list). Resolved directly for plain
        # ContinuousProperty / DiscreteProperty / CategoricalProperty
        # leaves, and via the C++-emitted `propKind` attribute for
        # synthetic TS / MR / MRTS leaves.
        state.setdefault("active_property_kind", "")

        state.setdefault("active_representation_has_properties", False)

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

        Semantics (per user requirement 2026-06-05):
          - A PROPERTY leaf (Property* / TimeSeries / MultiRealization*)
            is activatable ONLY when its OWN id is checked. Being under
            a checked rep is NOT enough: the dependency expansion
            (`tree_views._expand_selection_with_deps`) auto-adds the rep
            id to the select list whenever ANY one of its properties is
            checked, so an "under a checked rep" rule would let every
            unchecked sibling property activate — the reported bug.
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
        is_property = (
            "Property" in kind
            or kind in ("TimeSeries", "MultiRealization", "MultiRealizationTimeSeries")
        )
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
        _t_total = time.perf_counter()
        _ms = lambda t: int((time.perf_counter() - t) * 1000)
        _ms_tree_lookup = 0
        _ms_pipeline_pre = 0
        _ms_colorby = 0
        _ms_pipeline_post = 0
        _ms_on_active = 0
        _ms_on_loaded = 0
        _ms_update_coe = 0
        _ms_render = 0
        _branch = "unknown"
        is_property = False
        array_name = ""
        try:
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
                })
                _branch = "cleared"
                return
            node_id = ui_active_node_reservoir[0]
            # Reject activation of a node whose subtree isn't checked.
            # Trame batches the mutation and re-fires this handler with
            # the empty value on next flush, going through the reset
            # branch above.
            if not self._is_node_active_able(node_id, state.ui_select_node_reservoir):
                state.ui_active_node_reservoir = []
                _branch = "rejected"
                return
            _t = time.perf_counter()
            type_node_rep = self._tree.find_representation_type(node_id)
            type_node = self._tree.find_type(node_id)
            title_node = self._tree.find_title(node_id)
            _ms_tree_lookup = _ms(_t)

            # Multi-realization synthetic nodes act as property leaves:
            # the actual array name lives in propTitle. Plain TimeSeries
            # nodes are also property leaves (one per property title;
            # per-timestep nodes were collapsed in C++ searchProperties).
            is_multireal = type_node in ("MultiRealization", "MultiRealizationTimeSeries")
            is_property = bool(
                type_node and (
                    "Property" in type_node
                    or is_multireal
                    or type_node == "TimeSeries"
                )
            )
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
                # Active node path (used by the COE channel retarget; a no-op
                # for grid properties, but kept current so a stale wellbore
                # channel path doesn't linger).
                "active_color_array_path": (self._tree.find_path(node_id) or "") if is_property else "",
                "coe_panels": [] if not is_property else state.coe_panels,
            })

            rep_block_path, rep_type, rep_source = self._activate_reservoir_rep(node_id)

            # Multi-realization synthetic nodes carry the actual VTK
            # array name in propTitle (the title attribute is the
            # vtk-sanitized variant which may differ).
            array_name = title_node
            if is_multireal:
                prop_title = self._tree.find_attribute_value(node_id, "propTitle")
                if prop_title:
                    array_name = prop_title
            if is_property and array_name:
                try:
                    timings = self._apply_color_for_active_property(
                        node_id, rep_block_path, rep_type, rep_source,
                        array_name, is_ts_property,
                    )
                    (
                        array_name, _ms_pipeline_pre, _ms_colorby,
                        _ms_pipeline_post, _ms_on_active, _ms_on_loaded,
                        _ms_update_coe, _ms_render,
                    ) = timings
                except Exception as e:
                    print(f"[WARNING] Could not configure color mapping for property {array_name}: {e}")
                    import traceback
                    traceback.print_exc()
            _branch = "property" if (is_property and array_name) else "non-property"
        finally:
            _ms_total = _ms(_t_total)
            print(
                f"[PERF active.reservoir] branch={_branch} "
                f"tree_lookup={_ms_tree_lookup}ms "
                f"pipeline_pre={_ms_pipeline_pre}ms "
                f"colorby={_ms_colorby}ms "
                f"pipeline_post={_ms_pipeline_post}ms "
                f"on_active={_ms_on_active}ms "
                f"on_loaded={_ms_on_loaded}ms "
                f"update_coe={_ms_update_coe}ms "
                f"render={_ms_render}ms "
                f">>> TOTAL={_ms_total}ms"
            )

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
                if rep_type != 'IjkGrid' and self._source_registry is not None:
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
        if rep_type and rep_type != 'IjkGrid':
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
            target_source = _pick_visible([ijk._src_slicer_volume])
        return target_source

    def _apply_color_for_active_property(self, node_id, rep_block_path, rep_type,
                                         rep_source, array_name, is_ts_property):
        """Heavy ColorBy / LUT / scalar-bar configuration for a property
        activation. Returns the timing breakdown tuple (and the
        possibly-rewritten array_name when the array was found under a
        sanitized variant).

        Sequence:
          1. Resolve the visible target source via
             `_resolve_color_target_source`.
          2. Force MTime advance + UpdatePipelineInformation to bypass
             the stale proxy info cache for arrays added in place by
             the C++ pipeline.
          3. Query the underlying VTK object directly (Cell/Point data)
             — the proxy info cache is unreliable; the client-side
             object is always fresh.
          4. Apply ColorBy to every display rendering the rep (fan-out
             across chain / slicer proxies) — but only when the eye is
             open for this exact array.
          5. Hide the previous color bar if no other rep is still
             using it; configure the new LUT's bar.
          6. Force-rescale the LUT range LAST from the VTK array
             directly — every other caller's internal
             RescaleTransferFunctionToDataRange uses the stale proxy
             info cache and silently falls back to [0,1]."""
        _ms = lambda t: int((time.perf_counter() - t) * 1000)
        _ms_pipeline_pre = _ms_colorby = _ms_pipeline_post = 0
        _ms_on_active = _ms_on_loaded = _ms_update_coe = _ms_render = 0

        active_view = pvsimple.GetActiveView()
        target_source = self._resolve_color_target_source(
            rep_block_path, rep_type, rep_source, active_view,
        )
        if not (target_source and active_view):
            return (
                array_name, _ms_pipeline_pre, _ms_colorby,
                _ms_pipeline_post, _ms_on_active, _ms_on_loaded,
                _ms_update_coe, _ms_render,
            )

        target_name = ""
        for (sid, _), s in pvsimple.GetSources().items():
            if s is target_source:
                target_name = sid
                break
        print(f"[PERF active.reservoir] target={target_name!r} rep_type={rep_type!r}")
        _t = time.perf_counter()
        pvsimple.SetActiveSource(target_source)
        # Force the producer's MTime to advance so the proxy info cache
        # (otherwise sticky on TrivialProducer when its output is
        # mutated externally by the C++ side) is invalidated, then
        # re-run RequestInformation.
        try:
            target_source.GetClientSideObject().Modified()
        except Exception:
            pass
        target_source.UpdatePipelineInformation()
        target_source.UpdatePipeline()
        _ms_pipeline_pre = _ms(_t)
        display = pvsimple.GetDisplayProperties(target_source, view=active_view)

        if not display:
            return (
                array_name, _ms_pipeline_pre, _ms_colorby,
                _ms_pipeline_post, _ms_on_active, _ms_on_loaded,
                _ms_update_coe, _ms_render,
            )

        # Query the underlying VTK object directly — the proxy info
        # cache is unreliable when arrays are added in place by the C++
        # pipeline. Going through the client-side object is always
        # fresh.
        vtk_out = target_source.GetClientSideObject().GetOutputDataObject(0)
        vtk_inner = _drill_to_inner(vtk_out)
        vtk_cd = vtk_inner.GetCellData() if vtk_inner is not None and hasattr(vtk_inner, 'GetCellData') else None
        vtk_pd = vtk_inner.GetPointData() if vtk_inner is not None and hasattr(vtk_inner, 'GetPointData') else None
        cell_arr = _find_array_in_store(vtk_cd, array_name)
        pt_arr = _find_array_in_store(vtk_pd, array_name)
        has_cell = cell_arr is not None
        has_pt = pt_arr is not None
        # If the array was found via the sanitized name (specials
        # stripped), use that form for ColorBy / GetColorTransferFunction.
        if has_cell or has_pt:
            found_arr = cell_arr if has_cell else pt_arr
            if found_arr is not None:
                actual_name = found_arr.GetName()
                if actual_name and actual_name != array_name:
                    array_name = actual_name
        if not has_cell and not has_pt:
            self._debug_missing_array(target_source, vtk_inner, vtk_cd, vtk_pd)
        print(f"[PERF active.reservoir] array={array_name!r} has_cell={has_cell} has_pt={has_pt}")

        # ColorBy is owned by the eye state (ui_active_array_by_rep),
        # not by activation. We re-apply ColorBy here only when the eye
        # is open for this exact array — harmless if it's already
        # applied.
        array_node_path = self._tree.find_path(node_id)
        eye_open_for_this = (
            array_node_path is not None
            and (state.ui_active_array_by_rep or {}).get(rep_block_path) == array_node_path
        )
        _t = time.perf_counter()
        array_type = None
        if has_cell:
            array_type = "CELLS"
        elif has_pt:
            array_type = "POINTS"
        color_displays = []
        if array_type and eye_open_for_this:
            # Apply ColorBy to every display rendering this rep
            # (source + downstream Threshold filter, IJK slicers +
            # their thresholds, etc.). Without the fan-out the visible
            # threshold and the hidden source drift apart on a property
            # switch.
            color_displays = _all_displays_for_rep(
                rep_block_path, rep_type, active_view,
                target_source, display,
                source_registry=self._source_registry,
                ijk_lookup=self._ijk_lookup,
            )
            for d in color_displays:
                try:
                    pvsimple.ColorBy(d, (array_type, array_name))
                except Exception:
                    pass
        _ms_colorby = _ms(_t)
        lut = None
        if array_type:
            prev_array = self._current_array_by_rep.get(rep_block_path)
            if eye_open_for_this and prev_array and prev_array != array_name:
                still_used = any(
                    arr == prev_array
                    for r, arr in self._current_array_by_rep.items()
                    if r != rep_block_path
                )
                if not still_used:
                    try:
                        # Hide the previous bar — prefer the scene-
                        # scoped LUT for `prev_array` (we likely
                        # created one earlier), fall back to the
                        # global singleton.
                        prev_lut = source_resolver.scene_lut_for_view(
                            active_view, prev_array,
                        )
                        if prev_lut:
                            prev_bar = pvsimple.GetScalarBar(prev_lut, active_view)
                            if prev_bar:
                                # NOTE: do NOT raw-write prev_bar.Visibility = 0 here. The
                                # hide_unused_scalar_bars sweep in source_resolver.apply_color_array
                                # (line ~607) hides previous bars view-correctly through the manager;
                                # raw writes bypass vtkSMTransferFunctionManager bookkeeping and
                                # desync from the view's representation list under per-view LUT
                                # scope, leaving stale bars visible on OTHER views.
                                pass
                    except Exception:
                        pass
            if eye_open_for_this:
                self._current_array_by_rep[rep_block_path] = array_name

            # Per-view LUT / PWF: swap each display from the global
            # singleton to the active view's scene-scoped pair so a
            # COE edit in this view doesn't bleed across other views
            # showing the same array. Returns the scoped LUT so the
            # bar binding below targets the same proxy.
            if color_displays:
                lut, _scene_pwf = source_resolver.swap_to_scene_tfs(
                    color_displays, active_view, array_name,
                )
            if lut is None:
                lut = pvsimple.GetColorTransferFunction(array_name)
            if lut:
                lut.NanOpacity = _nan_opacity_from_state()
                color_bar = pvsimple.GetScalarBar(lut, active_view)
                if color_bar:
                    color_bar.Title = array_name
                    # NOTE: do NOT raw-write color_bar.Visibility = 1 here.
                    # apply_color_array above already invoked
                    # display.SetScalarBarVisibility(target_view, True) which goes
                    # through vtkSMTransferFunctionManager. Raw writes desync from
                    # the view's representation list under per-view LUT scope and
                    # cause duplicate bars on render views when other state.change
                    # handlers (e.g. apply_panel_coloring on MultiView.add_view of
                    # the Stats / Distribution panel) re-fire the same write path.
                    # (Title / format / Resizable writes below stay - they are
                    # appearance, not the visibility toggle.)
                    color_bar.RangeLabelFormat = '%-#6.3g'
                    color_bar.Resizable = 1

            # Retire any scalar bar that was attached to a now-orphaned LUT
            # on this view. The manager keys bars by (lut, view); when
            # `swap_to_scene_tfs` returns a different scoped-LUT proxy than
            # the prior activation used, the prior bar lingers in
            # `view.Representations` because nothing in this path reaped it.
            # `apply_color_array` (source_resolver) handles this via
            # `hide_unused_scalar_bars` — mirror the same call here.
            try:
                if active_view is not None:
                    from paraview.servermanager import vtkSMTransferFunctionManager
                    vtkSMTransferFunctionManager().UpdateScalarBars(
                        active_view.SMProxy, 1,
                    )
            except Exception:
                pass

        _t = time.perf_counter()
        target_source.UpdatePipeline()
        _ms_pipeline_post = _ms(_t)

        _t = time.perf_counter()
        controller.on_active_proxy_change()
        _ms_on_active = _ms(_t)
        # on_data_loaded is ParaView-Trame TimeControl's refresh hook —
        # only useful for time-series properties (the time slider needs
        # to reset its range). For non-TS activations it does heavy Vue
        # work for nothing (~50-100ms).
        _t = time.perf_counter()
        if is_ts_property:
            controller.on_data_loaded()
        _ms_on_loaded = _ms(_t)
        _t = time.perf_counter()
        controller.update_color_editor(array_name)
        _ms_update_coe = _ms(_t)

        # Force the LUT range LAST, after every other caller (ColorBy
        # internal, on_active_proxy_change, update_color_editor) has
        # had a chance to touch it. The proxy info cache used by their
        # internal RescaleTransferFunctionToDataRange is stale for
        # arrays added in place by the C++ pipeline, so they silently
        # fall back to [0,1] and the rendering looks like Solid mode.
        # Computing the range directly from the VTK array and pushing
        # it last guarantees nothing else can override it within this
        # tick.
        if array_type and lut is not None:
            try:
                vtk_arr = vtk_cd.GetArray(array_name) if has_cell else vtk_pd.GetArray(array_name)
                if vtk_arr is not None:
                    rng = vtk_arr.GetRange()
                    if rng[0] < rng[1]:
                        lut.RescaleTransferFunction(float(rng[0]), float(rng[1]))
            except Exception:
                pass

        _t = time.perf_counter()
        pvsimple.Render(view=active_view)
        _ms_render = _ms(_t)
        return (
            array_name, _ms_pipeline_pre, _ms_colorby,
            _ms_pipeline_post, _ms_on_active, _ms_on_loaded,
            _ms_update_coe, _ms_render,
        )

    def _debug_missing_array(self, target_source, vtk_inner, vtk_cd, vtk_pd):
        """Diagnostic dump for the "array not found in target source"
        case — walk to the slicer's upstream input (the rep_data filter
        for IjkGrid) and report what arrays IT has, so we can pinpoint
        whether the array exists upstream and got dropped, or never
        existed at all."""
        cell_names = []
        pt_names = []
        if vtk_cd:
            cell_names = [vtk_cd.GetArrayName(i) for i in range(vtk_cd.GetNumberOfArrays())]
        if vtk_pd:
            pt_names = [vtk_pd.GetArrayName(i) for i in range(vtk_pd.GetNumberOfArrays())]
        target_ncells = vtk_inner.GetNumberOfCells() if vtk_inner is not None and hasattr(vtk_inner, 'GetNumberOfCells') else -1
        target_extent = list(vtk_inner.GetExtent()) if vtk_inner is not None and hasattr(vtk_inner, 'GetExtent') else None
        output_whole_extent = None
        try:
            output_whole_extent = list(target_source.OutputWholeExtent) if hasattr(target_source, 'OutputWholeExtent') else None
        except Exception:
            pass
        print(f"[DEBUG active.reservoir] target.NumberOfCells={target_ncells} extent={target_extent} OutputWholeExtent={output_whole_extent}")
        print(f"[DEBUG active.reservoir] target.CellData={cell_names} PointData={pt_names}")
        try:
            upstream = target_source.Input
            if upstream is not None:
                up_obj = upstream.GetClientSideObject() if hasattr(upstream, 'GetClientSideObject') else None
                if up_obj is None and hasattr(upstream, 'GetProducer'):
                    up_obj = upstream.GetProducer().GetClientSideObject()
                if up_obj is not None:
                    up_out = up_obj.GetOutputDataObject(getattr(upstream, 'Port', 0) if hasattr(upstream, 'Port') else 0)
                    up_inner = _drill_to_inner(up_out) if up_out is not None else None
                    up_cd = up_inner.GetCellData() if up_inner is not None and hasattr(up_inner, 'GetCellData') else None
                    up_cell_names = [up_cd.GetArrayName(i) for i in range(up_cd.GetNumberOfArrays())] if up_cd else []
                    up_ncells = up_inner.GetNumberOfCells() if up_inner is not None and hasattr(up_inner, 'GetNumberOfCells') else -1
                    up_extent = list(up_inner.GetExtent()) if up_inner is not None and hasattr(up_inner, 'GetExtent') else None
                    up_class = up_inner.GetClassName() if up_inner is not None else None
                    print(f"[DEBUG active.reservoir] upstream class={up_class} NumberOfCells={up_ncells} extent={up_extent}")
                    print(f"[DEBUG active.reservoir] upstream.CellData={up_cell_names}")
        except Exception as _e:
            print(f"[DEBUG active.reservoir] upstream inspect failed: {_e}")

    def _publish_active_color_state(self, node_id):
        """Publish the COE-mode state (`active_color_array_name` /
        `active_property_kind`) for the active node of the WELL / SURFACE
        tab — mirroring what `_handle_reservoir_change` does inline.

        The COE / SolidColor panel reads `active_color_array_name` to
        decide colormap-vs-solid mode; without this a wellbore LOG
        channel (a property leaf living in the WELL tree) shows as
        SolidColor even though its eye colors the tube. For a property
        leaf we set the kind + array name and push the per-view LUT into
        the COE; for anything else (frame folder, marker, wellbore,
        trajectory geometry) we clear so the panel falls back to Solid.

        The actual ColorBy for a channel is done by
        `toggle_dataarray_color` (the eye), so this only publishes the
        editor STATE — it does not re-color."""
        type_node = self._tree.find_type(node_id) or ""
        is_multireal = type_node in ("MultiRealization", "MultiRealizationTimeSeries")
        is_property = bool(
            type_node and (
                "Property" in type_node or is_multireal or type_node == "TimeSeries"
            )
        )
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
            except Exception as exc:
                print(f"[WARNING] update_color_editor({array_name}) (well/surface): {exc}")

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

    def notify_active_reps(self, current_rep_paths):
        """Hide stale color bars left behind when a rep is no longer in
        the active selection. Only hides a bar if NO other still-present
        rep references the same array (multiple reps can share a
        LUT/bar)."""
        if not self._current_array_by_rep:
            return
        view = pvsimple.GetActiveView()
        if view is None:
            return
        present = set(current_rep_paths or [])
        gone = [r for r in list(self._current_array_by_rep.keys()) if r not in present]
        for rep_path in gone:
            arr_name = self._current_array_by_rep.pop(rep_path, None)
            if not arr_name:
                continue
            still_used = any(
                a == arr_name
                for r, a in self._current_array_by_rep.items()
                if r in present
            )
            if still_used:
                continue
            try:
                lut = pvsimple.GetColorTransferFunction(arr_name)
                if lut is not None:
                    bar = pvsimple.GetScalarBar(lut, view)
                    if bar is not None:
                        bar.Visibility = 0
            except Exception:
                pass

    def refresh_active(self):
        """Re-run the active-node handlers for whatever is currently
        active. Used after a manual Show: the active state changed
        BEFORE the load (so the rep didn't exist when the @state.change
        fired and the ColorBy wiring short-circuited). Now that the rep
        exists we want to re-run the same logic.

        Skip the call when the active node is not consistent with the
        current selection — VTreeview's update_selected will sync
        ui_active to the new value on the next flush and the handler
        will fire then. Without this guard we'd cause a wasted
        reject → reset → cleared → property chain (3 handler fires)
        for every grid switch."""
        try:
            active = state.ui_active_node_reservoir
            if active and self._is_node_active_able(active[0], state.ui_select_node_reservoir):
                self._handle_reservoir_change(active)
        except Exception as e:
            print(f"[WARNING] refresh_active reservoir failed: {e}")
            import traceback
            traceback.print_exc()
        try:
            active = state.ui_active_node_surface
            if active and self._is_node_active_able(active[0], state.ui_select_node_surface):
                self._handle_surface_change(active)
        except Exception as e:
            print(f"[WARNING] refresh_active surface failed: {e}")
            import traceback
            traceback.print_exc()
        try:
            active = state.ui_active_node_well
            if active and self._is_node_active_able(active[0], state.ui_select_node_well):
                self._handle_well_change(active)
        except Exception as e:
            print(f"[WARNING] refresh_active well failed: {e}")
            import traceback
            traceback.print_exc()

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
