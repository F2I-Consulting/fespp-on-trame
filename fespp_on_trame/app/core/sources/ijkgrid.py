from trame.app import get_server
from paraview import simple as pvsimple
from paraview.servermanager import vtkSMPropertyHelper

from fespp_on_trame.app.core.sources.collector import Collector
from fespp_on_trame.app.core.tree import Tree
from fespp_on_trame.app.core.sources.representation import (
    _apply_default_tint, _find_registered_proxy, _sanitize, inherit_display,
    arrays_from_source, array_range_from_source, resolve_assoc,
)


server = get_server()
state = server.state
ctrl = server.controller


class _IjkChainEntry:
    """One node in the IjkGrid threshold chain.

    Unlike ExtractBlockRepresentation where each chain entry has a single PV proxy,
    an IjkGrid entry must attach to *every* currently-active upstream
    (rep_data + slicers in slice mode, rep_data + slicervolume in
    range mode). `pv_proxies` is keyed by id(upstream_source) and
    holds the per-upstream Threshold proxy.

    `kind` / `unique_values` / `labels` mirror the shape of
    `extract_block.ChainEntry` — drive the threshold panel's slider
    variant (Continuous range, Discrete integer-stepped, Categorical
    labeled-ticks)."""

    __slots__ = ("name", "parent_name", "array", "assoc",
                 "visible", "low", "high", "data_range", "pv_proxies",
                 "kind", "unique_values", "labels")

    def __init__(self, name, parent_name, array, assoc,
                 visible, low, high, data_range,
                 kind="Continuous", unique_values=None, labels=None):
        self.name = name
        self.parent_name = parent_name
        self.array = array
        self.assoc = assoc
        self.visible = visible
        self.low = low
        self.high = high
        self.data_range = data_range
        self.pv_proxies = {}  # id(upstream_proxy) -> Threshold proxy
        self.kind = kind
        self.unique_values = list(unique_values or [])
        self.labels = dict(labels or {})

    def to_dict(self):
        return {
            "name": self.name,
            "parent_name": self.parent_name,
            "array": self.array,
            "visible": self.visible,
            "low": self.low,
            "high": self.high,
            "data_range": list(self.data_range),
            "kind": self.kind,
            "unique_values": list(self.unique_values),
            "labels": dict(self.labels),
        }


class IjkGrid:
    """Slicer / volume rendering for one IJK grid.

    Multi-instance: the engine maintains one IjkGrid per loaded IJK
    grid; each owns its own rep_data filter, per-axis crops, volume
    crop, threshold chain, and slicer/range UI state. The "active"
    grid (driven by `state.active_representation_path`) is the one
    whose state is mirrored into the trame `ui_slices_*` /
    `ui_range_*` / `ui_slices_range_*` vars and whose properties are
    edited by the slicer/threshold panels. Non-active grids continue
    rendering independently with their stored state.

    Threshold pipeline: an *ordered* list of chain entries
    (`_chain`), each entry attached to every active upstream source
    via per-upstream Threshold proxies. Children inherit from their
    parent's per-upstream proxy. Visibility toggling on a chain entry
    re-parents children to the entry's *current effective* upstream
    (skipping hidden ancestors)."""

    def __init__(self, collector: Collector, tree: Tree, *,
                 view_id=None, clone=None, pv_view=None):
        """
        collector / tree : engine globals.
        view_id / clone / pv_view (all optional, all-or-none):
            When provided, this IjkGrid runs in per-view mode: rep_data is
            created via `EnergisticsExtractor` chained on `clone` (not via the
            shared `EPCCollector.ExtractRepPath`), and every Show/Hide defaults
            to `pv_view` instead of `pvsimple.GetActiveView()`. Slicers and
            chain proxies follow because they chain on rep_data and use
            `_target_view()`.

            When all three are None, the legacy shared-instance behaviour
            applies: rep_data is created on the shared collector and Show/Hide
            tracks `GetActiveView()`. Used by `SourceRegistry`.
        """
        self._collector = collector
        self._tree = tree
        self._view_id = view_id
        self._clone = clone
        self._pv_view = pv_view
        self._node_id = None
        self._title = None
        self._property_path = None
        self._current_array_type = None
        self._current_property_type = None
        self._current_extent = None  # [x0,x1,y0,y1,z0,z1]
        # Per-grid token used to suffix PV registration names so
        # multiple IjkGrids don't collide on slicer / volume names.
        # In per-view mode the token also includes the view_id so
        # parallel per-view instances of the same grid coexist.
        self._rep_token = ""

        self._src_extract_init = None
        self._src_slicers_i = []
        self._src_slicers_j = []
        self._src_slicers_k = []
        self._src_slicer_volume = None

        # Threshold chain (ordered, parent-child by name).
        self._chain = []  # list[_IjkChainEntry]

        # Plane slice / clip (MVP: single plane per rep). Input is the
        # rep_data extractor — cutting the un-cropped grid so the
        # plane runs through the full geometry independently of the
        # user's current IJK slice/range setup.
        self._slice = None
        self._clip = None

        # Per-instance slicer / range UI state. The engine mirrors this
        # into the trame state vars when this grid is the active one.
        self._slices_i_list = []
        self._slices_j_list = []
        self._slices_k_list = []
        self._slices_i_visible_list = []
        self._slices_j_visible_list = []
        self._slices_k_visible_list = []
        self._slices_range_i = None
        self._slices_range_j = None
        self._slices_range_k = None
        self._range_i = None
        self._range_j = None
        self._range_k = None
        self._range_mode = "slice"
        self._volume_visible = True

    # ------------------------------------------------------------------
    # Symmetry with ExtractBlockRepresentation: both classes expose a
    # `source` property (the upstream filter used as ColorBy anchor /
    # display-resolver target) and a `rep_path` property (this grid's
    # path in the assembly). `SourceRegistry` reads these uniformly
    # without caring about the underlying type.

    @property
    def source(self):
        """The rep_data extractor filter — same role as
        ExtractBlockRepresentation.source: the canonical upstream
        proxy for the ColorBy fan-out / displays-for-rep lookup."""
        return self._src_extract_init

    def _target_view(self):
        """The view this IjkGrid renders into. Per-view mode → the
        captured `pv_view`; legacy mode → whatever's currently active.
        Every Show/Hide/GetRepresentation in this class flows through
        this helper so the per-view variant doesn't leak its output
        into other panels' displays."""
        if self._pv_view is not None:
            return self._pv_view
        from paraview import simple as pvsimple
        return pvsimple.GetActiveView()

    def _current_z_scale(self) -> float:
        """The global vertical exaggeration (state.ui_scale_z). Applied to
        every display this grid creates so a grid added AFTER the user set a
        z-scale still lands exaggerated like the rest of the scene."""
        try:
            return float(getattr(state, "ui_scale_z", 1.0) or 1.0)
        except (TypeError, ValueError):
            return 1.0

    @property
    def rep_path(self):
        """This grid's assembly path, or empty string when no node
        is currently active."""
        if self._node_id is None:
            return ""
        return self._tree.find_path(self._node_id) or ""

    def color_array_type(self, name) -> None:
        """Return 'CELLS' / 'POINTS' / 'FIELD' depending on which data
        store of the first I-axis slicer holds the named array."""
        src = self._src_slicers_i[0] if self._src_slicers_i else None
        if src is None:
            return None
        for i in range(src.CellData.GetNumberOfArrays()):
            if src.CellData.GetArray(i).Name == name:
                return 'CELLS'
        for i in range(src.PointData.GetNumberOfArrays()):
            if src.PointData.GetArray(i).Name == name:
                return 'POINTS'
        for i in range(src.FieldData.GetNumberOfArrays()):
            if src.FieldData.GetArray(i).Name == name:
                return 'FIELD'
        return None

    def _all_slice_sources(self):
        return self._src_slicers_i + self._src_slicers_j + self._src_slicers_k

    # ------------------------------------------------------------------
    # Source teardown

    def _delete_chain(self):
        """Tear down every PV proxy in the chain. Children-first so
        Inputs don't dangle."""
        view = self._target_view()
        for entry in reversed(self._chain):
            for proxy in list(entry.pv_proxies.values()):
                try:
                    if view is not None:
                        pvsimple.Hide(proxy=proxy, view=view)
                except Exception:
                    pass
                try:
                    pvsimple.Delete(proxy)
                except Exception:
                    pass
            entry.pv_proxies.clear()
        self._chain = []

    def _delete_chain_proxies_for_upstream(self, src):
        """Drop the per-upstream slot of every chain entry tied to
        `src` — used when the corresponding slicer is destroyed."""
        if src is None:
            return
        view = self._target_view()
        sid = id(src)
        for entry in reversed(self._chain):
            proxy = entry.pv_proxies.pop(sid, None)
            if proxy is None:
                continue
            try:
                if view is not None:
                    pvsimple.Hide(proxy=proxy, view=view)
            except Exception:
                pass
            try:
                pvsimple.Delete(proxy)
            except Exception:
                pass

    def _delete_all_sources(self):
        view = self._target_view()
        pvsimple.SetActiveSource(None)
        # Slice + chain reference slicer/rep_data proxies; delete them
        # FIRST so the upstream Delete calls don't trip on dangling
        # downstream filters.
        if self._slice is not None:
            try:
                self._slice.delete()
            except Exception:
                pass
            self._slice = None
        if self._clip is not None:
            try:
                self._clip.delete()
            except Exception:
                pass
            self._clip = None
        self._delete_chain()
        for src in self._all_slice_sources():
            try:
                pvsimple.Hide(proxy=src, view=view)
                pvsimple.Delete(src)
            except Exception:
                pass
        self._src_slicers_i = []
        self._src_slicers_j = []
        self._src_slicers_k = []
        if self._src_slicer_volume is not None:
            try:
                pvsimple.Hide(proxy=self._src_slicer_volume, view=view)
                pvsimple.Delete(self._src_slicer_volume)
            except Exception:
                pass
            self._src_slicer_volume = None
        if self._src_extract_init is not None:
            try:
                pvsimple.Delete(self._src_extract_init)
            except Exception:
                pass
            self._src_extract_init = None

    # ------------------------------------------------------------------
    # Slicer lifecycle

    def _create_slice_source(self, axis: str, idx: int):
        """Create and return a new ExplicitStructuredGridCrop for
        (axis, idx)."""
        src = pvsimple.ExplicitStructuredGridCrop(
            registrationName=f'slicer{axis}_{idx}__{self._rep_token}',
            Input=self._src_extract_init,
        )
        if self._current_extent:
            src.OutputWholeExtent = list(self._current_extent)
        src.UpdatePipelineInformation()
        view = self._target_view()
        rep = pvsimple.GetRepresentation(proxy=src, view=view)
        rep.Representation = state.representation_active or 'Surface'
        rep.Scale = [1.0, 1.0, self._current_z_scale()]
        if self._title and self._current_array_type:
            self.update_colors(src, self._current_array_type, self._title,
                               self._current_property_type)
        return src

    def _sync_slice_sources(self, axis: str, count: int):
        """Ensure exactly `count` slicer sources exist for the given
        axis."""
        if self._src_extract_init is None:
            return
        srcs = getattr(self, f'_src_slicers_{axis}')
        while len(srcs) < count:
            src = self._create_slice_source(axis, len(srcs))
            srcs.append(src)
            # New slicer joins the active upstream set — reattach the
            # chain to it.
            self._refresh_chain_pipeline()
        view = self._target_view()
        while len(srcs) > count:
            src = srcs.pop()
            self._delete_chain_proxies_for_upstream(src)
            try:
                pvsimple.Hide(proxy=src, view=view)
                pvsimple.Delete(src)
            except Exception:
                pass

    def set_node_id(self, node_id):
        """Switch the active IJK grid. Passing None tears everything
        down. Passing a node id:
        - If it points to a different IJK grid than the current one,
          delete all sources and rebuild from scratch.
        - Otherwise, treat it as a property change within the same
          grid (refresh ColorBy on every slicer)."""
        if node_id is None:
            if self._node_id is not None:
                self._delete_all_sources()
            self._node_id = None
            return

        ijkgrid_node_id = self._tree.find_parent_node_id_with_type(node_id, 'IjkGrid')
        if ijkgrid_node_id is None:
            return

        if self._node_id != ijkgrid_node_id:
            if self._node_id is not None:
                self._delete_all_sources()

            self._node_id = ijkgrid_node_id
            self._property_path = self._tree.find_path(node_id)
            ijkgrid_rep_path = self._tree.find_path(ijkgrid_node_id)
            # In per-view mode we include `view_id` in the registration
            # token so parallel per-view instances of the same grid
            # don't collide on slicer/volume names.
            base_token = _sanitize(ijkgrid_rep_path or "")
            self._rep_token = (
                f"{base_token}_v{_sanitize(str(self._view_id))}"
                if self._view_id is not None
                else base_token
            )
            if self._view_id is not None and self._clone is not None:
                # Per-view path: create rep_data via EnergisticsExtractor
                # chained on the view's clone. Same data as the
                # collector-anchored extractor (ShallowCopy passthrough) but
                # isolated per view, so downstream slicers / chain proxies
                # don't collide on id() across views.
                from fespp_on_trame.app.core.sources.representation import (
                    _create_plugin_filter_proxy,
                )
                ext_reg = f"ijk_rep_data_{self._rep_token}"
                ext = _create_plugin_filter_proxy(
                    proxy_class="EnergisticsExtractor",
                    registration_name=ext_reg,
                    inputs={"Input": self._clone},
                )
                if ext is None:
                    self._node_id = None
                    return
                vtkSMPropertyHelper(ext.SMProxy, "ExtractPath").Set(ijkgrid_rep_path)
                ext.SMProxy.UpdateVTKObjects()
                ext.UpdatePipelineInformation()
                self._src_extract_init = ext
            else:
                # Legacy shared path: rep_data is created via the
                # EPCCollector.ExtractRepPath property (C++ side
                # calls ExtractWithoutCopy and registers an
                # EnergisticsExtractor chained on the collector).
                coll_proxy = self._collector.get_source().SMProxy
                vtkSMPropertyHelper(coll_proxy, "ExtractRepPath").Set(ijkgrid_rep_path)
                coll_proxy.UpdateVTKObjects()
                coll_proxy.UpdatePropertyInformation()
                reg_name = vtkSMPropertyHelper(coll_proxy, "ExtractedRepProducerName").GetAsString()
                if not reg_name:
                    self._node_id = None
                    return
                self._src_extract_init = _find_registered_proxy(reg_name)
                if self._src_extract_init is None:
                    self._node_id = None
                    return

            view = self._target_view()
            for axis in ('i', 'j', 'k'):
                src = pvsimple.ExplicitStructuredGridCrop(
                    registrationName=f'slicer{axis}_0__{self._rep_token}',
                    Input=self._src_extract_init,
                )
                getattr(self, f'_src_slicers_{axis}').append(src)

            self._src_slicer_volume = pvsimple.ExplicitStructuredGridCrop(
                registrationName=f'slicervolume__{self._rep_token}',
                Input=self._src_extract_init,
            )

            self._src_extract_init.UpdatePipelineInformation()
            for src in self._all_slice_sources() + [self._src_slicer_volume]:
                src.UpdatePipelineInformation()

            rep_type = state.representation_active or 'Surface'
            grid_color = (state.solid_color_by_rep or {}).get(ijkgrid_rep_path)
            zs = self._current_z_scale()
            for src in self._all_slice_sources() + [self._src_slicer_volume, self._src_extract_init]:
                disp = pvsimple.GetRepresentation(proxy=src, view=view)
                disp.Representation = rep_type
                disp.Scale = [1.0, 1.0, zs]
                _apply_default_tint(disp, grid_color)

            self.update_block_visibility()
            self.show()

            data_info = self._src_extract_init.GetDataInformation()
            extent = list(data_info.GetExtent())
            self._current_extent = extent

            mid_i = (extent[0] + extent[1]) // 2
            mid_j = (extent[2] + extent[3]) // 2
            mid_k = (extent[4] + extent[5]) // 2

            # Initialise this grid's own slicer / range state. The
            # engine pushes these into the trame UI vars when this
            # grid becomes the active one.
            self._range_i = [extent[0], extent[1]]
            self._range_j = [extent[2], extent[3]]
            self._range_k = [extent[4], extent[5]]
            self._slices_i_list = [mid_i]
            self._slices_j_list = [mid_j]
            self._slices_k_list = [mid_k]
            self._slices_i_visible_list = [True]
            self._slices_j_visible_list = [True]
            self._slices_k_visible_list = [True]
            self._slices_range_i = [extent[0], extent[1]]
            self._slices_range_j = [extent[2], extent[3]]
            self._slices_range_k = [extent[4], extent[5]]

            for src in self._all_slice_sources() + [self._src_slicer_volume]:
                src.OutputWholeExtent = extent
            for src in self._all_slice_sources() + [self._src_slicer_volume]:
                try:
                    src.UpdatePipeline()
                except Exception:
                    pass

        property_title = self._tree.find_title(node_id)
        property_type = self._tree.find_type(node_id)
        if property_title != self._title:
            array_type = self.color_array_type(property_title)
            if array_type is not None:
                self._current_array_type = array_type
                self._current_property_type = property_type
                for src in self._all_slice_sources() + [self._src_slicer_volume]:
                    self.update_colors(src, array_type, property_title, property_type)

            self._title = property_title

            for src in self._all_slice_sources() + [self._src_slicer_volume]:
                src.UpdatePipelineInformation()

            pvsimple.Hide(proxy=self._src_extract_init)
            self.show()

    def _is_range_full_extent(self):
        """True when the range slider equals the grid's full extent. PV6's
        ExplicitStructuredGridCrop produces a degenerate 1-cell output at
        full extent, so we fall back to rep_data in that case (the
        non-cropped equivalent) and only switch to slicervolume once the
        user actually cropped something."""
        if not self._current_extent:
            return True
        full = self._current_extent
        ri = self._slices_range_i or [full[0], full[1]]
        rj = self._slices_range_j or [full[2], full[3]]
        rk = self._slices_range_k or [full[4], full[5]]
        return (
            int(ri[0]) <= full[0] and int(ri[1]) >= full[1]
            and int(rj[0]) <= full[2] and int(rj[1]) >= full[3]
            and int(rk[0]) <= full[4] and int(rk[1]) >= full[5]
        )

    def _primary_range_source(self):
        """The source that's actually rendered in range mode."""
        if self._is_range_full_extent() or self._src_slicer_volume is None:
            return self._src_extract_init
        return self._src_slicer_volume

    def _active_upstreams(self):
        """The upstream sources currently rendered (and thus the ones
        the chain should attach to) for the current slicer mode."""
        if self._src_extract_init is None:
            return []
        out = [self._src_extract_init]
        if self._range_mode == 'slice':
            out.extend(self._all_slice_sources())
        else:
            if self._src_slicer_volume is not None:
                out.append(self._src_slicer_volume)
        return out

    # ------------------------------------------------------------------
    # Show / hide

    def show(self, view=None):
        """Show / hide the right combination of sources for the current
        slicer mode. Slice mode displays the per-axis crops; range mode
        displays slicervolume when the slider is on a subset of the grid,
        and rep_data when it spans the full extent (slicervolume's output
        is degenerate at full extent on PV6 — see _is_range_full_extent).

        Fallback: when the user hides every visible slicer (slice mode)
        or the volume eye (range mode), we show rep_data — the parent
        un-cropped grid — instead of leaving an empty view.

        When the chain has any visible entry, each "would-be visible"
        source is replaced by its corresponding Threshold proxy from
        the deepest visible chain leaf.

        `view` defaults to the active view when None — call sites that
        target a specific panel (multi-view eye toggle) pass that
        panel's render view to avoid leaking the Show/Hide into the
        wrong view."""
        if self._node_id is None:
            return
        if view is None:
            view = self._target_view()
        if view is None:
            return

        # Slice / clip replace the grid visually — hide every source
        # this grid would normally render so only the plane filter
        # outputs stay on screen. Slice / Clip manage their own
        # display in the same view via SlicePlane._apply / ClipPlane._apply.
        slice_active = self._slice is not None and self._slice.enabled
        clip_active = self._clip is not None and self._clip.enabled
        if slice_active or clip_active:
            for src in (
                list(self._all_slice_sources())
                + ([self._src_slicer_volume] if self._src_slicer_volume is not None else [])
                + ([self._src_extract_init] if self._src_extract_init is not None else [])
            ):
                try:
                    pvsimple.Hide(proxy=src, view=view)
                    self._hide_chain_for(src, view)
                except Exception:
                    pass
            return

        # `set_node_id` set Representation + tint (DiffuseColor / AmbientColor
        # / Opacity from state.solid_color_by_rep) only in the view active at
        # the time. In OTHER views (multi-view copies, panels promoted via eye
        # toggle) the display is created later with PV's default
        # Representation='Outline' and grey colour, so re-assert
        # Representation + tint on every managed source's display in `view`.
        rep_type = state.representation_active or 'Surface'
        grid_color = (state.solid_color_by_rep or {}).get(self.rep_path)
        zs = self._current_z_scale()
        for src in (
            list(self._all_slice_sources())
            + ([self._src_slicer_volume] if self._src_slicer_volume is not None else [])
            + ([self._src_extract_init] if self._src_extract_init is not None else [])
        ):
            try:
                disp = pvsimple.GetRepresentation(proxy=src, view=view)
                if disp is not None:
                    disp.Representation = rep_type
                    disp.Scale = [1.0, 1.0, zs]
                    _apply_default_tint(disp, grid_color)
            except Exception:
                pass

        deepest_leaf = self._deepest_visible_leaf()

        if self._range_mode == 'slice':
            if self._src_slicer_volume is not None:
                pvsimple.Hide(proxy=self._src_slicer_volume, view=view)
                self._hide_chain_for(self._src_slicer_volume, view)

            vis_i = list(self._slices_i_visible_list or [])
            vis_j = list(self._slices_j_visible_list or [])
            vis_k = list(self._slices_k_visible_list or [])
            any_visible = False
            for axis_srcs, vis_list in (
                (self._src_slicers_i, vis_i),
                (self._src_slicers_j, vis_j),
                (self._src_slicers_k, vis_k),
            ):
                for idx, src in enumerate(axis_srcs):
                    visible = vis_list[idx] if idx < len(vis_list) else True
                    self._show_source_or_chain(src, view, visible, deepest_leaf)
                    if visible:
                        any_visible = True

            if self._src_extract_init is not None:
                # Parent fallback: show rep_data when no slicer is visible.
                self._show_source_or_chain(
                    self._src_extract_init, view, not any_visible, deepest_leaf,
                )
        else:
            for src in self._all_slice_sources():
                pvsimple.Hide(proxy=src, view=view)
                self._hide_chain_for(src, view)

            primary = self._primary_range_source()
            volume_visible = bool(self._volume_visible)
            if not volume_visible:
                primary = self._src_extract_init
                volume_visible = True

            for s in (self._src_extract_init, self._src_slicer_volume):
                if s is not None and s is not primary:
                    pvsimple.Hide(proxy=s, view=view)
                    self._hide_chain_for(s, view)
            if primary is not None:
                self._show_source_or_chain(primary, view, volume_visible, deepest_leaf)

    def _show_source_or_chain(self, src, view, visible, deepest_leaf):
        """Show src OR its corresponding deepest visible threshold leaf,
        gated by the user's eye state for that source."""
        proxy = None
        if deepest_leaf is not None:
            proxy = deepest_leaf.pv_proxies.get(id(src))
        if proxy is not None:
            pvsimple.Hide(proxy=src, view=view)
            (pvsimple.Show if visible else pvsimple.Hide)(proxy=proxy, view=view)
            # Hide intermediate chain entries' proxies for this upstream.
            for entry in self._chain:
                if entry is deepest_leaf:
                    continue
                p = entry.pv_proxies.get(id(src))
                if p is not None:
                    try:
                        pvsimple.Hide(proxy=p, view=view)
                    except Exception:
                        pass
        else:
            self._hide_chain_for(src, view)
            (pvsimple.Show if visible else pvsimple.Hide)(proxy=src, view=view)

    def _hide_chain_for(self, src, view):
        for entry in self._chain:
            p = entry.pv_proxies.get(id(src))
            if p is not None:
                try:
                    pvsimple.Hide(proxy=p, view=view)
                except Exception:
                    pass

    def _deepest_visible_leaf(self):
        """The deepest visible chain entry (i.e. last one in chain
        order whose own visibility is on AND every ancestor on the
        path to root is visible). None if nothing is visible. The
        chain's display always shows the deepest visible entry's
        output — intermediate ones serve only as filters in the
        pipeline."""
        leaf = None
        for entry in self._chain:
            if not entry.visible:
                continue
            if not self._ancestors_all_visible(entry):
                continue
            leaf = entry
        return leaf

    def _ancestors_all_visible(self, entry):
        cursor = self._entry_by_name(entry.parent_name)
        while cursor is not None:
            if not cursor.visible:
                return False
            cursor = self._entry_by_name(cursor.parent_name)
        return True

    # ------------------------------------------------------------------
    # Array introspection

    def available_arrays(self):
        """Return [(assoc, name), ...] for the active grid's data arrays.
        Used by the engine to populate the threshold UI."""
        return arrays_from_source(self._src_extract_init)

    def array_data_range(self, array_name):
        """Return (min, max) for the named array on the active grid, or
        None if the array isn't found."""
        return array_range_from_source(self._src_extract_init, array_name)

    def _resolve_assoc(self, array_name):
        return resolve_assoc(self._src_extract_init, array_name)

    # ------------------------------------------------------------------
    # Chain — public API

    def get_chain(self):
        return [e.to_dict() for e in self._chain]

    def chain_entries(self):
        return self._chain

    def add_threshold(self, parent_name, array):
        """Append a chain entry under `parent_name` (or root if None).
        Creates per-upstream PV proxies on the spot."""
        if self._src_extract_init is None or not array:
            return None
        if parent_name is not None and not any(e.name == parent_name for e in self._chain):
            return None
        assoc = self._resolve_assoc(array)
        if not assoc:
            return None

        ijkgrid_node_id = self._node_id
        rep_path = self._tree.find_path(ijkgrid_node_id) if ijkgrid_node_id else "ijk"
        rep_token = _sanitize(rep_path)
        if parent_name is None:
            base_name = f"thr_{rep_token}_{_sanitize(array)}"
        else:
            base_name = f"{parent_name}_{_sanitize(array)}"

        # Multiple thresholds on the same array under the same parent
        # are valid — their outputs render in parallel (UNION of the
        # ranges). Suffix the entry name to avoid PV registration-name
        # collisions when the user adds two intervals of the same
        # property to the same chain level.
        existing_names = {e.name for e in self._chain}
        if base_name in existing_names:
            suffix = 2
            while f"{base_name}_{suffix}" in existing_names:
                suffix += 1
            base_name = f"{base_name}_{suffix}"

        rng = self.array_data_range(array) or (0.0, 1.0)

        # Resolve property kind (Continuous / Discrete / Categorical)
        # for the threshold panel slider dispatch. Source proxy: the
        # rep_data extractor — that's the unfiltered VTK array store,
        # so scanning uniques there reflects the data's true value
        # set, not what's left after slicers / chain filtering.
        from fespp_on_trame.app.core.sources.extract_block import resolve_chain_kind
        kind, unique_values, labels = resolve_chain_kind(
            self._tree, rep_path, array,
            self._src_extract_init, assoc,
        )

        entry = _IjkChainEntry(
            name=base_name,
            parent_name=parent_name,
            array=array,
            assoc=assoc,
            visible=True,
            low=float(rng[0]),
            high=float(rng[1]),
            data_range=(float(rng[0]), float(rng[1])),
            kind=kind,
            unique_values=unique_values,
            labels=labels,
        )
        self._chain.append(entry)
        self._refresh_chain_pipeline()
        self.show()
        return base_name

    def delete_threshold(self, name):
        idx = next((i for i, e in enumerate(self._chain) if e.name == name), -1)
        if idx < 0:
            return False
        target = self._chain[idx]
        # Children of target adopt target.parent_name as new logical parent.
        for e in self._chain:
            if e.parent_name == name:
                e.parent_name = target.parent_name
        self._chain.pop(idx)
        view = self._target_view()
        for proxy in list(target.pv_proxies.values()):
            try:
                if view is not None:
                    pvsimple.Hide(proxy=proxy, view=view)
            except Exception:
                pass
            try:
                pvsimple.Delete(proxy)
            except Exception:
                pass
        target.pv_proxies.clear()
        self._refresh_chain_pipeline()
        self.show()
        return True

    def set_range(self, name, low, high):
        for e in self._chain:
            if e.name == name:
                e.low = float(low)
                e.high = float(high)
                for proxy in e.pv_proxies.values():
                    try:
                        proxy.LowerThreshold = e.low
                        proxy.UpperThreshold = e.high
                        proxy.UpdatePipeline()
                    except Exception as exc:
                        pass
                return

    def set_visible(self, name, visible):
        for e in self._chain:
            if e.name == name:
                e.visible = bool(visible)
                break
        else:
            return
        self._refresh_chain_pipeline()
        self.show()

    def all_visible_threshold_proxies(self):
        """Every PV proxy that's actually rendering threshold output —
        used by the engine for ColorBy fan-out / visibility scans."""
        leaf = self._deepest_visible_leaf()
        if leaf is None:
            return []
        return list(leaf.pv_proxies.values())

    def all_render_sources(self):
        """Every PV source proxy created by this grid: rep_data, the
        per-axis slicers, the volume crop, and every chain proxy.
        Lets callers (Activator, engine fan-out) enumerate this grid's
        own sources without having to glob registration names."""
        out = []
        if self._src_extract_init is not None:
            out.append(self._src_extract_init)
        out.extend(self._all_slice_sources())
        if self._src_slicer_volume is not None:
            out.append(self._src_slicer_volume)
        out.extend(self.all_threshold_sources())
        return out

    # ------------------------------------------------------------------
    # Slice / clip plane — DEPRECATED legacy path.
    #
    # Slice / clip ownership lives on `RepInScene` (per-(rep, view)); the
    # `_slice` / `_clip` fields here stay None in normal use. The methods
    # below are only reachable via the deprecated `SourceRegistry`
    # slice/clip compat shims. Kept as a safety net.

    def _ensure_slice(self):
        """Lazily build a `SlicePlane` once the rep_data extractor exists, so
        the slice's upstream is always the un-cropped grid.
        DEPRECATED: per-(rep, view) slice lives on `RepInScene`."""
        if self._slice is not None or self._src_extract_init is None:
            return
        from fespp_on_trame.app.core.sources.slice_plane import SlicePlane
        self._slice = SlicePlane(self.rep_path, self._src_extract_init, state)

    def slice_state(self) -> dict:
        """Return the slice descriptor for the UI panel."""
        self._ensure_slice()
        if self._slice is None:
            return {
                "enabled": False, "axis": "X", "offset": 0.0,
                "bounds": [0.0, 1.0, 0.0, 1.0, 0.0, 1.0],
            }
        return self._slice.to_dict()

    def slice_set(self, enabled=None, axis=None, offset=None):
        """Patch the plane params and re-render. When the enabled bit
        flips, also re-run `show()` so the grid's rendered sources get
        hidden (slice replaces them visually) or restored."""
        self._ensure_slice()
        if self._slice is None:
            return
        was_enabled = self._slice.enabled
        self._slice.set(enabled=enabled, axis=axis, offset=offset)
        if self._slice.enabled != was_enabled:
            self.show()

    # ------------------------------------------------------------------
    # Clip plane (MVP — single plane per rep)

    def _ensure_clip(self):
        if self._clip is not None or self._src_extract_init is None:
            return
        from fespp_on_trame.app.core.sources.clip_plane import ClipPlane
        self._clip = ClipPlane(self.rep_path, self._src_extract_init, state)

    def clip_state(self) -> dict:
        self._ensure_clip()
        if self._clip is None:
            return {
                "enabled": False, "axis": "X", "offset": 0.0,
                "inside_out": False,
                "bounds": [0.0, 1.0, 0.0, 1.0, 0.0, 1.0],
            }
        return self._clip.to_dict()

    def clip_set(self, enabled=None, axis=None, offset=None,
                 inside_out=None):
        self._ensure_clip()
        if self._clip is None:
            return
        was_enabled = self._clip.enabled
        self._clip.set(enabled=enabled, axis=axis, offset=offset,
                       inside_out=inside_out)
        if self._clip.enabled != was_enabled:
            self.show()

    def clip_output(self):
        """Clip filter proxy — see ExtractBlockRep.clip_output."""
        return self._clip.output if self._clip is not None else None

    def refresh_planes_after_property_change(self):
        """Re-apply slice / clip if enabled, then re-run `show()` so
        the rep stays hidden when slice / clip is enabled. ColorBy
        fan-out updates the clip's display via `clip_output()`."""
        if self._slice is not None and self._slice.enabled:
            self._slice.set()
        if self._clip is not None and self._clip.enabled:
            self._clip.set()
        if ((self._slice is not None and self._slice.enabled)
                or (self._clip is not None and self._clip.enabled)):
            self.show()

    def all_threshold_sources(self):
        """Every chain PV proxy (visible or not) — used for
        representation propagation."""
        out = []
        for entry in self._chain:
            out.extend(entry.pv_proxies.values())
        return out

    # ------------------------------------------------------------------
    # Chain plumbing

    def _entry_by_name(self, name):
        if name is None:
            return None
        for e in self._chain:
            if e.name == name:
                return e
        return None

    def _effective_upstream_for(self, entry, src):
        """For chain entry `entry` and active upstream source `src`,
        resolve the actual PV proxy its Threshold should read from.
        Walk up the chain skipping hidden ancestors; fall back to the
        upstream source itself."""
        cursor = self._entry_by_name(entry.parent_name)
        while cursor is not None:
            if cursor.visible:
                proxy = cursor.pv_proxies.get(id(src))
                if proxy is not None:
                    return proxy
                break
            cursor = self._entry_by_name(cursor.parent_name)
        return src

    def _refresh_chain_pipeline(self):
        """Sync the per-entry per-upstream PV proxy set with the
        currently-active upstream sources, then rewire each proxy's
        Input to reflect visibility-aware parenting.

        Called when:
          - entries are added / removed,
          - visibility changes,
          - the slicer mode flips (active upstream set changes)."""
        upstreams = self._active_upstreams()
        upstream_ids = {id(s) for s in upstreams}
        view = self._target_view()

        for entry in self._chain:
            # Drop slots for upstreams that are no longer active.
            for sid in list(entry.pv_proxies.keys()):
                if sid not in upstream_ids:
                    proxy = entry.pv_proxies.pop(sid)
                    try:
                        if view is not None:
                            pvsimple.Hide(proxy=proxy, view=view)
                    except Exception:
                        pass
                    try:
                        pvsimple.Delete(proxy)
                    except Exception:
                        pass
            # Create / update slots for currently-active upstreams.
            for src in upstreams:
                effective = self._effective_upstream_for(entry, src)
                proxy = entry.pv_proxies.get(id(src))
                if proxy is None:
                    try:
                        proxy = pvsimple.Threshold(
                            registrationName=f"{entry.name}__{id(src)}",
                            Input=effective,
                        )
                    except Exception as exc:
                        continue
                    entry.pv_proxies[id(src)] = proxy
                    self._inherit_display(proxy, src)
                else:
                    try:
                        if proxy.Input is not effective:
                            proxy.Input = effective
                    except Exception as exc:
                        pass
                # Push current Scalars + bounds.
                try:
                    proxy.Scalars = [entry.assoc, entry.array]
                    proxy.LowerThreshold = float(entry.low)
                    proxy.UpperThreshold = float(entry.high)
                    proxy.UpdatePipeline()
                except Exception as exc:
                    pass

    def _inherit_display(self, thr_proxy, src):
        """Copy the parent's display look onto the threshold output in this
        grid's target view. Delegates to the shared `inherit_display`."""
        inherit_display(src, thr_proxy, self._target_view())

    # Mode-flip / slicer-add hook used by the engine.
    def refresh_threshold_pipeline(self):
        self._refresh_chain_pipeline()

    # ------------------------------------------------------------------
    # NaN / colors

    def _nan_opacity_from_state(self):
        """Read NaN opacity from state.nan_color (#RRGGBBAA), default 0.2."""
        try:
            hex_val = (state.nan_color or "").lstrip("#")
            if len(hex_val) >= 8:
                return int(hex_val[6:8], 16) / 255
        except (ValueError, IndexError):
            pass
        return 0.2

    def update_colors(self, src, array_type, property_title, property_type):
        """Apply a ColorBy on a single slicer source: set the lookup
        table, the scalar bar's title / format, and hide the scalar
        bar of the previously selected array."""
        view = self._target_view()
        representation = pvsimple.GetRepresentation(proxy=src, view=view)
        representation.ColorArrayName = [array_type, property_title]
        lut = pvsimple.GetColorTransferFunction(property_title)
        lut.NanOpacity = self._nan_opacity_from_state()
        representation.LookupTable = lut
        representation.RescaleTransferFunctionToDataRange(True)
        bar = pvsimple.GetScalarBar(ctf=lut, view=view)
        bar.Visibility = True
        bar.RangeLabelFormat = '%-#6.3g'
        bar.Resizable = 1
        bar.DrawNanAnnotation = 1
        bar.ComponentTitle = ''
        bar.Title = property_title
        if self._title:
            try:
                old_lut = pvsimple.GetColorTransferFunction(self._title, representation)
                pvsimple.GetScalarBar(ctf=old_lut, view=view).Visibility = False
            except Exception:
                pass

    def update_block_visibility(self):
        """Drop this grid's property path from the parent multiblock's
        BlockSelectors — the property is rendered through this grid's
        slicers, not the parent rep. Cumulative-safe across multiple
        IjkGrid instances: starts from the engine's reset marker
        ['/data'] (rehydrating from `state.fespp_data_selectors`) and
        otherwise pops just its own path so earlier removals stay
        intact."""
        if self._property_path is None:
            return
        if self._property_path not in (state.fespp_data_selectors or []):
            return
        rep = self._collector.get_representation()
        current = list(rep.BlockSelectors or [])
        # Engine sets BlockSelectors=['/data'] before grids are
        # initialised; rehydrate from the full selectors on first call.
        if current == ['/data']:
            current = list(state.fespp_data_selectors or [])
        if self._property_path in current:
            current = [p for p in current if p != self._property_path]
            rep.BlockSelectors = current

    def apply_slice_positions(self, slices_i_list, slices_j_list, slices_k_list):
        """Sync the per-axis slicer sources with the position lists,
        creating / deleting sources as needed and updating
        OutputWholeExtent on each one. Mirrors the lists into the
        instance's stored state."""
        if self._node_id is None:
            return
        self._slices_i_list = list(slices_i_list)
        self._slices_j_list = list(slices_j_list)
        self._slices_k_list = list(slices_k_list)
        self._sync_slice_sources('i', len(slices_i_list))
        self._sync_slice_sources('j', len(slices_j_list))
        self._sync_slice_sources('k', len(slices_k_list))

        ri = self._range_i or [0, 0]
        rj = self._range_j or [0, 0]
        rk = self._range_k or [0, 0]

        for idx, pos in enumerate(slices_i_list):
            self._src_slicers_i[idx].OutputWholeExtent = [pos, pos, rj[0], rj[1], rk[0], rk[1]]
        for idx, pos in enumerate(slices_j_list):
            self._src_slicers_j[idx].OutputWholeExtent = [ri[0], ri[1], pos, pos, rk[0], rk[1]]
        for idx, pos in enumerate(slices_k_list):
            self._src_slicers_k[idx].OutputWholeExtent = [ri[0], ri[1], rj[0], rj[1], pos, pos]

    def apply_slice_visibility(self, vis_i, vis_j, vis_k):
        self._slices_i_visible_list = list(vis_i or [])
        self._slices_j_visible_list = list(vis_j or [])
        self._slices_k_visible_list = list(vis_k or [])

    def apply_range(self, range_i, range_j, range_k):
        self._slices_range_i = list(range_i)
        self._slices_range_j = list(range_j)
        self._slices_range_k = list(range_k)
        if self._node_id is None or self._src_slicer_volume is None:
            return
        self._src_slicer_volume.OutputWholeExtent = [
            range_i[0], range_i[1],
            range_j[0], range_j[1],
            range_k[0], range_k[1],
        ]

    def apply_mode(self, mode):
        if not mode or self._range_mode == mode:
            return
        self._range_mode = mode
        # Mode flip changes the active upstream set — rebuild chain
        # attachments before the next show().
        self.refresh_threshold_pipeline()

    def apply_volume_visible(self, visible):
        self._volume_visible = bool(visible)

    def to_ui_state(self):
        """Snapshot of this grid's slicer/range state, suitable for
        `state.update()`. Returns None when the grid hasn't been
        initialised yet (no extent known)."""
        if self._node_id is None or not self._current_extent:
            return None
        return {
            "ui_range_i": list(self._range_i or []),
            "ui_range_j": list(self._range_j or []),
            "ui_range_k": list(self._range_k or []),
            "ui_slices_i_list": list(self._slices_i_list),
            "ui_slices_j_list": list(self._slices_j_list),
            "ui_slices_k_list": list(self._slices_k_list),
            "ui_slices_i_visible_list": list(self._slices_i_visible_list),
            "ui_slices_j_visible_list": list(self._slices_j_visible_list),
            "ui_slices_k_visible_list": list(self._slices_k_visible_list),
            "ui_slices_range_i": list(self._slices_range_i or []),
            "ui_slices_range_j": list(self._slices_range_j or []),
            "ui_slices_range_k": list(self._slices_range_k or []),
            "ui_slices_range_mode": self._range_mode,
            "ui_slices_volume_visible": self._volume_visible,
        }
