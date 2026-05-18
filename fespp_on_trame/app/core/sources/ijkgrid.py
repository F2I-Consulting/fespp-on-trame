from trame.app import get_server
from paraview import simple as pvsimple
from paraview.servermanager import vtkSMPropertyHelper

from fespp_on_trame.app.core.sources.collector import Collector
from fespp_on_trame.app.core.fespp_tree import Tree
from fespp_on_trame.app.core.sources.rep_sources import (
    _apply_default_tint, _find_registered_proxy, _sanitize,
)


server = get_server()
state = server.state
ctrl = server.controller


class _IjkChainEntry:
    """One node in the IjkGrid threshold chain.

    Unlike RepSources where each chain entry has a single PV proxy,
    an IjkGrid entry must attach to *every* currently-active upstream
    (rep_data + slicers in slice mode, rep_data + slicervolume in
    range mode). `pv_proxies` is keyed by id(upstream_source) and
    holds the per-upstream Threshold proxy."""

    __slots__ = ("name", "parent_name", "array", "assoc",
                 "visible", "low", "high", "data_range", "pv_proxies")

    def __init__(self, name, parent_name, array, assoc,
                 visible, low, high, data_range):
        self.name = name
        self.parent_name = parent_name
        self.array = array
        self.assoc = assoc
        self.visible = visible
        self.low = low
        self.high = high
        self.data_range = data_range
        self.pv_proxies = {}  # id(upstream_proxy) -> Threshold proxy

    def to_dict(self):
        return {
            "name": self.name,
            "parent_name": self.parent_name,
            "array": self.array,
            "visible": self.visible,
            "low": self.low,
            "high": self.high,
            "data_range": list(self.data_range),
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

    def __init__(self, collector: Collector, tree: Tree):
        self._collector = collector
        self._tree = tree
        self._node_id = None
        self._title = None
        self._property_path = None
        self._current_array_type = None
        self._current_property_type = None
        self._current_extent = None  # [x0,x1,y0,y1,z0,z1]
        # Per-grid token used to suffix PV registration names so
        # multiple IjkGrids don't collide on slicer / volume names.
        self._rep_token = ""

        self._src_extract_init = None
        self._src_slicers_i = []
        self._src_slicers_j = []
        self._src_slicers_k = []
        self._src_slicer_volume = None

        # Threshold chain (ordered, parent-child by name).
        self._chain = []  # list[_IjkChainEntry]

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
        view = pvsimple.GetActiveView()
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
        view = pvsimple.GetActiveView()
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
        view = pvsimple.GetActiveView()
        pvsimple.SetActiveSource(None)
        # Chain references slicer/rep_data proxies; delete it FIRST so
        # the upstream Delete calls don't trip on dangling downstream
        # filters.
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
        view = pvsimple.GetActiveView()
        rep = pvsimple.GetRepresentation(proxy=src, view=view)
        rep.Representation = state.representation_active or 'Surface'
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
        view = pvsimple.GetActiveView()
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
            self._rep_token = _sanitize(ijkgrid_rep_path or "")
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

            view = pvsimple.GetActiveView()
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
            for src in self._all_slice_sources() + [self._src_slicer_volume, self._src_extract_init]:
                disp = pvsimple.GetRepresentation(proxy=src, view=view)
                disp.Representation = rep_type
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

    def show(self):
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
        the deepest visible chain leaf."""
        if self._node_id is None:
            return
        view = pvsimple.GetActiveView()
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
        src = self._src_extract_init
        if src is None:
            return []
        out = []
        seen = set()
        for store_attr, assoc in (("CellData", "CELLS"), ("PointData", "POINTS")):
            try:
                store = getattr(src, store_attr)
                for i in range(store.GetNumberOfArrays()):
                    a = store.GetArray(i)
                    if a is None:
                        continue
                    name = a.Name
                    key = (assoc, name)
                    if name and key not in seen:
                        seen.add(key)
                        out.append(key)
            except Exception:
                pass
        return out

    def array_data_range(self, array_name):
        """Return (min, max) for the named array on the active grid, or
        None if the array isn't found."""
        src = self._src_extract_init
        if src is None or not array_name:
            return None
        for store_attr in ("CellData", "PointData"):
            try:
                store = getattr(src, store_attr)
                for i in range(store.GetNumberOfArrays()):
                    a = store.GetArray(i)
                    if a is not None and a.Name == array_name:
                        rng = a.GetRange()
                        return (float(rng[0]), float(rng[1]))
            except Exception:
                pass
        return None

    def _resolve_assoc(self, array_name):
        for a, n in self.available_arrays():
            if n == array_name:
                return a
        return None

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
            print(f"[WARNING] add_threshold: unknown parent {parent_name!r}")
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
        entry = _IjkChainEntry(
            name=base_name,
            parent_name=parent_name,
            array=array,
            assoc=assoc,
            visible=True,
            low=float(rng[0]),
            high=float(rng[1]),
            data_range=(float(rng[0]), float(rng[1])),
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
        view = pvsimple.GetActiveView()
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
                        print(f"[WARNING] set_range({name}): {exc}")
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
        view = pvsimple.GetActiveView()

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
                        print(f"[WARNING] Threshold create {entry.name}: {exc}")
                        continue
                    entry.pv_proxies[id(src)] = proxy
                    self._inherit_display(proxy, src)
                else:
                    try:
                        if proxy.Input is not effective:
                            proxy.Input = effective
                    except Exception as exc:
                        print(f"[WARNING] Threshold rewire {entry.name}: {exc}")
                # Push current Scalars + bounds.
                try:
                    proxy.Scalars = [entry.assoc, entry.array]
                    proxy.LowerThreshold = float(entry.low)
                    proxy.UpperThreshold = float(entry.high)
                    proxy.UpdatePipeline()
                except Exception as exc:
                    print(f"[WARNING] Threshold props {entry.name}: {exc}")

    def _inherit_display(self, thr_proxy, src):
        """Copy Representation / Scale / ColorArrayName / LookupTable /
        DiffuseColor / Opacity from src's display onto thr_proxy's
        display so the threshold output mirrors its parent visually
        (both in property-color mode and SolidColor mode) from the
        moment it appears."""
        view = pvsimple.GetActiveView()
        if view is None:
            return
        try:
            src_disp = pvsimple.GetDisplayProperties(src, view=view)
            thr_disp = pvsimple.GetRepresentation(proxy=thr_proxy, view=view)
            if src_disp is None or thr_disp is None:
                return
            for attr, as_list in (
                ("Representation", False),
                ("Scale", True),
                ("ColorArrayName", True),
                ("LookupTable", False),
                ("DiffuseColor", True),
                ("AmbientColor", True),
                ("Opacity", False),
            ):
                try:
                    val = getattr(src_disp, attr)
                    if as_list:
                        val = list(val)
                    setattr(thr_disp, attr, val)
                except Exception:
                    pass
        except Exception:
            pass

    # Mode-flip / slicer-add hook. Kept for engine compatibility.
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
        representation = pvsimple.GetRepresentation(proxy=src, view=pvsimple.GetActiveView())
        representation.ColorArrayName = [array_type, property_title]
        lut = pvsimple.GetColorTransferFunction(property_title)
        lut.NanOpacity = self._nan_opacity_from_state()
        representation.LookupTable = lut
        representation.RescaleTransferFunctionToDataRange(True)
        bar = pvsimple.GetScalarBar(ctf=lut, view=pvsimple.GetActiveView())
        bar.Visibility = True
        bar.RangeLabelFormat = '%-#6.3g'
        bar.Resizable = 1
        bar.DrawNanAnnotation = 1
        bar.ComponentTitle = ''
        bar.Title = property_title
        if self._title:
            try:
                old_lut = pvsimple.GetColorTransferFunction(self._title, representation)
                pvsimple.GetScalarBar(ctf=old_lut, view=pvsimple.GetActiveView()).Visibility = False
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
