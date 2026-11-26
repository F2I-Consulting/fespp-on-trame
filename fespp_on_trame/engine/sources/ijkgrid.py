from trame.app import get_server
from paraview import simple as pvsimple
from paraview.servermanager import vtkSMPropertyHelper

from fespp_on_trame.engine.sources.collector import Collector
from fespp_on_trame.engine.tree import Tree
from fespp_on_trame.engine.sources.representation import (
    _apply_default_tint, _find_registered_proxy, _sanitize, inherit_display,
    arrays_from_source, array_range_from_source, rep_type_for, resolve_assoc,
    suppress_selection_labels,
)
from fespp_on_trame.engine.sources import leaf_rep
from fespp_on_trame.engine.sources.crop_extent import (
    crop_extent as _crop_extent, is_subset as _is_subset, put_crop_extent as _put_crop_extent,
)
from fespp_on_trame.engine.state_defaults import z_scale_of
from fespp_on_trame.engine.utils import numfmt


server = get_server()
state = server.state
ctrl = server.controller


# An I/J/K crop is ParaView's own for the grid's type: ExtractSubset for a
# vtkStructuredGrid (a lattice geometry), the explicit structured grid's crop
# for a corner-point grid. Both take a point extent.
def _new_crop(name, upstream, structured):
    if structured:
        return pvsimple.ExtractSubset(registrationName=name, Input=upstream)
    return pvsimple.ExplicitStructuredGridCrop(registrationName=name, Input=upstream)


class _IjkChainEntry:
    """One node in the IjkGrid threshold chain.

    An entry attaches to *every* currently active upstream (rep_data +
    slicers in slice mode, rep_data + volume crops in range mode).
    `pv_proxies` is keyed by id(upstream_source) and holds the
    per-upstream Threshold proxy.

    `kind` / `unique_values` / `labels` drive the threshold panel's slider
    variant (Continuous range, Discrete integer-stepped, Categorical
    labelled ticks; engine/sources/chain_domain)."""

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

    Any other representation can be isolated too: it gets the same
    extractor and threshold chain, without crops (see `set_node_id`).

    Multi-instance: the engine maintains one IjkGrid per loaded IJK
    grid; each owns its own rep_data filter, per-axis crops, range-mode
    volume crops, threshold chain, and slicer/range UI state. The
    "active" grid (driven by `state.active_representation_path`) is the
    one whose state is mirrored into the trame `ui_slices_*` /
    `ui_range_*` / `ui_volumes_*` vars and whose properties are
    edited by the slicer/threshold panels. Non-active grids continue
    rendering independently with their stored state.

    Threshold pipeline: an *ordered* list of chain entries
    (`_chain`), each entry attached to every active upstream source
    via per-upstream Threshold proxies. Children inherit from their
    parent's per-upstream proxy. Visibility toggling on a chain entry
    re-parents children to the entry's *current effective* upstream
    (skipping hidden ancestors)."""

    def __init__(self, collector: Collector, tree: Tree, *,
                 view_id=None, clone=None, pv_view=None, lut_for=None):
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
        # who decides whether this isolate draws (app/scene/occupancy): a
        # callable taking the isolate; None, the isolate shows itself (the
        # shared, data-only instance and the legacy mode)
        self.shown_by = None
        self._clone = clone
        self._pv_view = pv_view
        # Callable name -> the VIEW's lookup table (the one the composite
        # colours the grid with); None = the global table (legacy shared
        # instance).
        self._lut_for = lut_for
        # Run after every show() / hide_all(): the composite re-asserts its
        # colour bars (see show).
        self.after_show = None
        self._node_id = None
        self._title = None
        self._array_path = None      # the coloured property's tree path
        self._property_path = None
        self._current_array_type = None
        self._current_property_type = None
        self._current_extent = None  # VTK extent [i0,i1,j0,j1,k0,k1]
        # Per-grid token used to suffix PV registration names so
        # multiple IjkGrids don't collide on slicer / volume names.
        # In per-view mode the token also includes the view_id so
        # parallel per-view instances of the same grid coexist.
        self._rep_token = ""

        self._src_extract_init = None
        # "Hide NaN cells" (engine/nan_mask.py): a ParaView Calculator
        # between the extractor and EVERY consumer — the crops, the volumes,
        # the threshold chain, the full-grid display — so they all inherit
        # the mask. None = off: the extractor feeds them directly. See
        # `_render_root` / `set_cell_mask`. The mask hides the NaN cells of
        # `_nan_mask_array` ("Hide NaN cells", `_mask_nan`) and/or the cells
        # of its codes at opacity 0 (`_mask_codes`, a property painted by
        # code).
        self._nan_mask = None
        self._nan_mask_array = None
        self._mask_nan = False
        self._mask_codes = ()
        # How many cells the mask hides that were not hidden already (dead
        # cells are): reported in the log and on the Colormap card.
        self._nan_hidden = None
        # Does this isolate host an IJK grid (crops, slicers, volumes) or any
        # other representation (the extractor alone)? Set by `set_node_id`.
        self._is_ijk = True
        # an IJK grid that came as a vtkStructuredGrid (a lattice geometry):
        # its crops are ExtractSubset. Set by `set_node_id`.
        self._structured = False
        # A point set: the chain reads it one vertex cell per point
        # (`_point_cells`), {id(upstream): ConvertToPointCloud proxy}
        self._is_points = False
        self._point_clouds = {}
        self._src_slicers_i = []
        self._src_slicers_j = []
        self._src_slicers_k = []
        self._src_volumes = []
        # The X/Y/Z crop of a representation without I/J/K
        # (engine/sources/xyz_crop): one CoordCrop per volume (their tips
        # are `_src_volumes`), the object's bounds
        self._xyz_crops = []
        self._current_bounds = None
        # a surface on a 2D grid: its point extent, cut on I and J before X,
        # Y and Z (its volumes [i, j, x, y, z])
        self._ij_extent = None

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
        # Range-mode volumes: parallel lists of per-volume crop ranges
        # ([[i0,i1],[j0,j1],[k0,k1]] each) and per-volume eye state.
        self._volumes = []
        self._volumes_visible = []
        self._range_i = None
        self._range_j = None
        self._range_k = None
        # Full-grid mode by default: the grid shows whole until the user
        # opts into slicing (Slice, the preferred slicer mode) or cropping
        # (Range).
        self._range_mode = "full"

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

    # ------------------------------------------------------------------
    # Read-only views for the headless harness (overhaul slice 8): no
    # private read crosses the class

    @property
    def source_extract(self):
        """The extract of the grid's block the chain starts from, or None."""
        return self._src_extract_init

    @property
    def nan_mask(self):
        """The calculator masking the NaN cells (Hide NaN), or None."""
        return self._nan_mask

    @property
    def range_mode(self):
        """The slicers' mode: "full", "range" or "slice"."""
        return self._range_mode

    def render_root(self):
        """The proxy the view draws (the chain's tip, or the crop)."""
        return self._render_root()

    def _render_root(self):
        """What the crops, the volumes, the threshold chain and the
        full-grid display read: the NaN mask when it is on, else the
        extractor. Ranges, array lists and `source` keep reading the
        extractor — the UNMASKED grid: a hidden cell is still a cell of the
        property, and the colour scale must not move when the box is
        ticked."""
        return self._nan_mask if self._nan_mask is not None else self._src_extract_init

    @property
    def hide_nan_array(self):
        """The CELL array whose NaN cells are hidden, None when off."""
        return self._nan_mask_array if self._mask_nan else None

    @property
    def hidden_codes(self):
        """The codes whose cells the mask hides (opacity 0), () when none."""
        return self._mask_codes

    @property
    def hide_nan_hidden(self):
        """Cells the mask hides beyond the dead ones, None when off or unread."""
        return self._nan_hidden if self._nan_mask is not None else None

    def _count_nan_hidden(self):
        """Hidden cells in the mask's output minus those already hidden in
        the extractor's: what the box actually removed."""
        try:
            import numpy as np
            from vtkmodules.util.numpy_support import vtk_to_numpy
            from fespp_on_trame.engine import nan_mask
            def hidden(proxy):
                obj = proxy.GetClientSideObject().GetOutputDataObject(0)
                arr = obj.GetCellData().GetArray(nan_mask.GHOSTS) if obj is not None else None
                return 0 if arr is None else int(np.count_nonzero(vtk_to_numpy(arr) & nan_mask.HIDDEN))
            return hidden(self._nan_mask) - hidden(self._src_extract_init)
        except Exception as exc:
            print(f"[fespp] hide NaN cells: counting the hidden cells failed: {exc!r}", flush=True)
            return None

    def set_cell_mask(self, array, nan=False, codes=()):
        """Hide the cells where the CELL array `array` is NaN (`nan`, "Hide
        NaN cells") or holds one of `codes` (a property painted by code,
        its codes at opacity 0): their neighbours' faces then show instead
        of a see-through hole. Off when `array` is None or nothing is to
        hide.

        Toggling re-points the crops and volumes and lets the chain
        re-attach (`_refresh_chain_pipeline` drops the slots of an upstream
        no longer active and makes new ones), so nothing downstream is torn
        down. Returns True when something changed."""
        nan = bool(nan)
        codes = tuple(sorted({float(c) for c in codes or ()}))
        if not array or not (nan or codes):
            array, nan, codes = None, False, ()
        if self._src_extract_init is None:
            return False
        if (array == self._nan_mask_array and nan == self._mask_nan
                and codes == self._mask_codes
                and (array is None) == (self._nan_mask is None)):
            return False
        view = self._target_view()
        old_root = self._render_root()
        if array is None:
            mask = self._nan_mask
            self._nan_mask = None
            self._nan_mask_array = None
            self._mask_nan = False
            self._mask_codes = ()
            self._nan_hidden = None
            self._repoint_crops()
            self._refresh_chain_pipeline()
            if mask is not None:
                try:
                    if view is not None:
                        pvsimple.Hide(proxy=mask, view=view)
                    pvsimple.Delete(mask)
                except Exception as exc:
                    print(f"[fespp] hide NaN cells off ({self._title!r}): {exc!r}", flush=True)
            print(f"[fespp] cell mask: off on {self.rep_path[-40:]!r}"
                  f" ({self._view_id})", flush=True)
        else:
            from fespp_on_trame.engine import nan_mask
            if self._resolve_assoc(array) != "CELLS":
                print(f"[fespp] hide NaN cells: {array!r} is not a cell property of"
                      f" {self.rep_path[-40:]!r} — only a cell property hides cells",
                      flush=True)
                return False
            try:
                has_ghosts = nan_mask.GHOSTS in list(self._src_extract_init.CellData.keys())
            except Exception as exc:
                print(f"[fespp] hide NaN cells: reading the grid's cell arrays: {exc!r}", flush=True)
                has_ghosts = False
            settings = nan_mask.calculator_settings(array, has_ghosts, nan=nan, codes=codes)
            if settings is None:
                print(f"[fespp] hide NaN cells: the name {array!r} cannot be written in"
                      " a Calculator expression — cells left as they are", flush=True)
                return False
            if self._nan_mask is None:
                # ParaView's C++ Calculator, not a Python filter:
                # engine/nan_mask.py explains the SIGSEGV that rules Python out.
                self._nan_mask = pvsimple.Calculator(
                    registrationName=f"hidenan__{self._rep_token}",
                    Input=self._src_extract_init,
                )
                if view is not None:
                    disp = pvsimple.GetRepresentation(proxy=self._nan_mask, view=view)
                    suppress_selection_labels(disp)
                    disp.Representation = rep_type_for(state, self.rep_path)
                    disp.Scale = [1.0, 1.0, self._current_z_scale()]
            for prop, value in settings.items():
                setattr(self._nan_mask, prop, value)
            self._nan_mask_array = array
            self._mask_nan = nan
            self._mask_codes = codes
            self._nan_mask.UpdatePipeline()
            self._nan_hidden = self._count_nan_hidden()
            if self._title and self._current_array_type:
                self.update_colors(self._nan_mask, self._current_array_type,
                                   self._title, self._current_property_type)
            if old_root is not self._nan_mask:
                try:
                    if view is not None:
                        pvsimple.Hide(proxy=old_root, view=view)
                except Exception as exc:
                    print(f"[fespp] hide NaN cells: hiding the unmasked grid: {exc!r}", flush=True)
                self._repoint_crops()
                self._refresh_chain_pipeline()
            what = " or ".join((["NaN"] if nan else [])
                               + ([f"code {', '.join(format(c, 'g') for c in codes)}"]
                                  if codes else []))
            print(f"[fespp] cell mask: on {self.rep_path[-40:]!r}, {self._nan_hidden}"
                  f" cell(s) hidden where {array!r} is {what} ({self._view_id})", flush=True)
        self._redraw()
        return True

    def _redraw(self):
        """Draw again after a change: through `shown_by` when the app
        decides who draws the grid (the composite may draw it, an extract may
        replace it, its eye may be closed), else by itself."""
        if self.shown_by is not None:
            self.shown_by(self)
        else:
            self.show()

    def needs_isolation(self):
        """Whether this grid must stay isolated in its view (drawn by its own
        displays, the composite skipping the block): a threshold chain, a
        slicer mode other than full, or the cell mask (NaN cells, codes at
        opacity 0). The ONE release rule
        for every controller that could let the composite paint it again."""
        return bool(self._chain) or self._range_mode != "full" or self._nan_mask is not None

    def _repoint_crops(self):
        """Every crop and volume reads `_render_root()` again — the X/Y/Z
        crops through their region input."""
        root = self._render_root()
        for src in self._all_slice_sources() + (self._src_volumes if self._is_ijk else []):
            try:
                src.Input = root
            except Exception as exc:
                print(f"[fespp] hide NaN cells: re-pointing a crop failed: {exc!r}", flush=True)
        for crop in self._xyz_crops:
            try:
                crop.set_input(self._region_input())
            except Exception as exc:
                print(f"[fespp] hide NaN cells: re-pointing an X/Y/Z crop failed: {exc!r}", flush=True)

    def _region_input(self):
        """What the X/Y/Z crops cut: the grid as drawn, a point set's points
        made cells (a point kept or not, never the whole cloud)."""
        root = self._render_root()
        return self._point_cells(root) if self._is_points else root

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
        """The vertical exaggeration of this grid's view. Applied to every
        display this grid creates so a grid added AFTER the user set a z-scale
        still lands exaggerated like the rest of the scene."""
        return z_scale_of(state, self._view_id)

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

    def _colourable_sources(self):
        """Every proxy whose display can carry a colour — the base sources
        AND the threshold chain's own proxies.

        With a chain active the base sources are HIDDEN and the chain TIPS
        are what the view actually shows (`_show_source_or_chain`).
        Recolouring only the bases would leave a thresholded grid painted
        by the PREVIOUS property while the eye, the composite and the
        isolate's title all moved to the new one."""
        out = (self._all_slice_sources() + self._src_volumes
               + [self._src_extract_init, self._nan_mask])
        for entry in self._chain:
            out.extend(entry.pv_proxies.values())
        return [p for p in out if p is not None]

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
        """Tear down every proxy this grid owns, downstream first."""
        view = self._target_view()
        pvsimple.SetActiveSource(None)
        # The chain references slicer / rep_data proxies; delete it FIRST
        # so the upstream Delete calls do not trip on dangling downstream
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
        if self._xyz_crops:
            # the X/Y/Z crops own their tips: each deletes its chain
            for crop in self._xyz_crops:
                crop.delete(view)
        else:
            for src in self._src_volumes:
                try:
                    pvsimple.Hide(proxy=src, view=view)
                    pvsimple.Delete(src)
                except Exception:
                    pass
        self._xyz_crops = []
        self._src_volumes = []
        # after the crops that read them
        for pc in self._point_clouds.values():
            try:
                pvsimple.Delete(pc)
            except Exception as exc:
                print(f"[fespp] point cloud teardown: {exc!r}", flush=True)
        self._point_clouds = {}
        if self._nan_mask is not None:
            # Downstream of the extractor, upstream of the crops just deleted:
            # it goes after them and before the extractor.
            try:
                pvsimple.Hide(proxy=self._nan_mask, view=view)
                pvsimple.Delete(self._nan_mask)
            except Exception as exc:
                print(f"[fespp] hide NaN cells: teardown: {exc!r}", flush=True)
            self._nan_mask = None
            self._nan_mask_array = None
        if self._src_extract_init is not None:
            try:
                pvsimple.Delete(self._src_extract_init)
            except Exception:
                pass
            self._src_extract_init = None

    # ------------------------------------------------------------------
    # Slicer lifecycle

    def _create_slice_source(self, axis: str, idx: int):
        """Create and return a new I/J/K crop (`_new_crop`) for
        (axis, idx)."""
        src = _new_crop(f'slicer{axis}_{idx}__{self._rep_token}',
                        self._render_root(), self._structured)
        if self._current_extent:
            _put_crop_extent(src, self._current_extent, self._current_extent)
        src.UpdatePipelineInformation()
        view = self._target_view()
        rep = pvsimple.GetRepresentation(proxy=src, view=view)
        suppress_selection_labels(rep)
        rep.Representation = rep_type_for(state, self.rep_path)
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
        """Switch the isolated representation (an IJK grid or any other
        rep). Passing None tears everything down. Passing a node id (the
        rep itself or one of its properties):
        - If it resolves to a different rep than the current one, delete
          all sources and rebuild from scratch.
        - Otherwise, treat it as a property change within the same rep
          (refresh ColorBy on every colourable source)."""
        if node_id is None:
            if self._node_id is not None:
                self._delete_all_sources()
            self._node_id = None
            return

        # A grid property is a SIBLING of its geometry rep under a
        # PropertiesFolder, not a descendant: find_representation_node
        # descends the grid folder to the geometry rep for a property (and
        # returns the rep itself when node_id already is it).
        ijkgrid_node_id = self._tree.find_representation_node(node_id)
        if ijkgrid_node_id is None:
            return
        # Any representation can be isolated, not only an IJK grid. The
        # isolate's own machinery (the generic
        # `EnergisticsExtractor(ExtractPath=...)`, the threshold chain keyed
        # on `id(upstream)`, `_show_source_or_chain`, `_colourable_sources`)
        # knows nothing about structured grids; only the CROPS do
        # (`_new_crop`, by the grid's type).
        # A non-IJK representation therefore gets the same isolate WITHOUT
        # crops: full mode, the extractor as the single upstream, the chain
        # on top.
        self._is_ijk = (self._tree.find_type(ijkgrid_node_id) == 'IjkGrid')
        self._is_points = (self._tree.find_type(ijkgrid_node_id) == 'PointSet')

        if self._node_id != ijkgrid_node_id:
            if self._node_id is not None:
                self._delete_all_sources()

            self._node_id = ijkgrid_node_id
            self._property_path = self._tree.find_path(node_id)
            ijkgrid_rep_path = self._tree.find_path(ijkgrid_node_id)
            # In per-view mode the registration token includes `view_id`, so
            # parallel per-view instances of the same grid do not collide on
            # slicer / volume names.
            base_token = _sanitize(ijkgrid_rep_path or "")
            self._rep_token = (
                f"{base_token}_v{_sanitize(str(self._view_id))}"
                if self._view_id is not None
                else base_token
            )
            # the reader that holds this grid: the file reader or the store
            reader_of = getattr(self._collector, "reader_of", None)
            reader = reader_of(ijkgrid_rep_path) if reader_of is not None else self._collector.get_source()
            if self._view_id is not None and self._clone is not None:
                # Per-view path: create rep_data via EnergisticsExtractor
                # chained on the view's clone. Same data as the
                # collector-anchored extractor (ShallowCopy passthrough) but
                # isolated per view, so downstream slicers / chain proxies
                # do not collide on id() across views.
                from fespp_on_trame.engine.sources.representation import (
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
            elif reader.SMProxy.GetProperty("ExtractRepPath") is None:
                # A reader WITHOUT the EPCCollector's ExtractWithoutCopy
                # surface (the ETP store): chain a plain EnergisticsExtractor
                # on the reader itself — same mechanism as the per-view clone
                # path above, just anchored on the reader.
                from fespp_on_trame.engine.sources.representation import (
                    _create_plugin_filter_proxy,
                )
                ext = _create_plugin_filter_proxy(
                    proxy_class="EnergisticsExtractor",
                    registration_name=f"ijk_rep_data_{self._rep_token}",
                    inputs={"Input": reader},
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
                coll_proxy = reader.SMProxy
                vtkSMPropertyHelper(coll_proxy, "ExtractRepPath").Set(ijkgrid_rep_path)
                coll_proxy.UpdateVTKObjects()
                coll_proxy.UpdatePropertyInformation()
                reg_name = vtkSMPropertyHelper(coll_proxy, "ExtractedRepProducerName").GetAsString()
                if not reg_name:
                    self._node_id = None
                    return
                self._src_extract_init = _find_registered_proxy(reg_name)
                if self._src_extract_init is None:
                    # Stale producer: a prior release() deleted the Python
                    # proxy but the C++ collector still hands back its
                    # dangling name. Force a fresh rebuild by toggling
                    # ExtractRepPath (clear -> re-set) so the collector drops
                    # the stale producer and registers a new one, then re-read.
                    vtkSMPropertyHelper(coll_proxy, "ExtractRepPath").Set("")
                    coll_proxy.UpdateVTKObjects()
                    coll_proxy.UpdatePropertyInformation()
                    vtkSMPropertyHelper(coll_proxy, "ExtractRepPath").Set(ijkgrid_rep_path)
                    coll_proxy.UpdateVTKObjects()
                    coll_proxy.UpdatePropertyInformation()
                    reg_name = vtkSMPropertyHelper(coll_proxy, "ExtractedRepProducerName").GetAsString()
                    self._src_extract_init = _find_registered_proxy(reg_name) if reg_name else None
                    if self._src_extract_init is None:
                        self._node_id = None
                        return

            # Execute the extractor BEFORE anything chains on it, then nudge it
            # once more. Its output type comes from the input's assembly
            # (EnergisticsExtractor::RequestDataObject) and, until the clone has
            # run, is a vtkPolyData placeholder. ParaView puts a vtkPVPostFilter
            # between a source proxy and its consumers, and that filter types
            # its own output ONCE, at its first data-object pass — with the
            # placeholder. It re-types only when the pipeline upstream is
            # modified, hence the Modified() after the first execution: without
            # it every crop chained here is rejected ("is of type vtkPolyData,
            # but a vtkExplicitStructuredGrid is required") and never
            # recovers, so the grid vanishes behind every slicer and threshold.
            try:
                self._src_extract_init.UpdatePipeline()
                alg = self._src_extract_init.GetClientSideObject()
                if alg is not None:
                    alg.Modified()
                self._src_extract_init.UpdatePipeline()
            except Exception:
                pass
            try:
                self._structured = (self._src_extract_init.GetDataInformation()
                                    .GetDataClassName() == "vtkStructuredGrid")
            except Exception as exc:
                print(f"[fespp] isolate: the grid's type not read ({exc})", flush=True)
                self._structured = False
            view = self._target_view()
            if self._view_id is not None and self._is_ijk:
                # Crops are IJK-only (`_new_crop`), so a non-IJK isolate has
                # none and renders through the extractor.
                # BlockScope SHARED instance: no crop sources at all, since
                # every downstream slicer path would (re)create VISIBLE crop
                # displays painting over the composite. PER-VIEW instances
                # (view_id set) ARE the GridIsolate: they keep crops + displays
                # in their own view while the composite swaps the block out.
                for axis in ('i', 'j', 'k'):
                    src = _new_crop(f'slicer{axis}_0__{self._rep_token}',
                                    self._src_extract_init, self._structured)
                    getattr(self, f'_src_slicers_{axis}').append(src)

                # One default range-mode volume; the UI's "+" grows the list
                # via apply_volumes.
                self._src_volumes = [_new_crop(f'slicervolume0__{self._rep_token}',
                                               self._src_extract_init, self._structured)]

            self._src_extract_init.UpdatePipelineInformation()
            # Full data pass on rep_data BEFORE its display is created / shown.
            # rep_data is the sole visible source at the default range /
            # full-extent view; if it is shown against an info-only (unrealised)
            # output its mapper paints empty on the first StillRender push and
            # the geometry only appears after a camera nudge. Same
            # materialise-then-show order as `ensure_extractor` for surfaces.
            try:
                self._src_extract_init.UpdatePipeline()
            except Exception:
                pass
            for src in self._all_slice_sources() + self._src_volumes:
                src.UpdatePipelineInformation()

            if self._view_id is not None:
                # the SHARED instance: NO per-source displays (they
                # double-paint the composite). Per-view isolates create their
                # crop displays in THEIR view — that's the whole point.
                rep_type = rep_type_for(state, ijkgrid_rep_path)
                grid_color = (state.solid_color_by_rep or {}).get(ijkgrid_rep_path)
                zs = self._current_z_scale()
                for src in self._colourable_sources():
                    disp = pvsimple.GetRepresentation(proxy=src, view=view)
                    disp.Representation = rep_type
                    disp.Scale = [1.0, 1.0, zs]
                    _apply_default_tint(disp, grid_color)

            self._redraw()

            if not self._is_ijk:
                # No I/J/K extent: the Geometry slicer cuts it in X/Y/Z
                # (engine/sources/xyz_crop), its crops made when a box
                # narrows it (`apply_volumes`). The isolate starts in
                # `full` mode, where `show()` displays the extractor (or
                # its threshold tips) and nothing else.
                self._range_mode = 'full'
                self._current_extent = None
                info = self._src_extract_init.GetDataInformation()
                b = list(info.GetBounds())
                self._current_bounds = b if b[0] <= b[1] else None
                self._ij_extent = None
                if self._structured and self._tree.find_type(ijkgrid_node_id) == 'Grid2d':
                    ext = [int(v) for v in info.GetExtent()]
                    self._ij_extent = ext if ext[0] <= ext[1] and ext[2] <= ext[3] else None
                if self._current_bounds:
                    self._volumes = [self._whole_ij() + [b[0:2], b[2:4], b[4:6]]]
                    self._volumes_visible = [True]
                self._redraw()
                return
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
            self._volumes = [[
                [extent[0], extent[1]],
                [extent[2], extent[3]],
                [extent[4], extent[5]],
            ]]
            self._volumes_visible = [True]

            for src in self._all_slice_sources() + self._src_volumes:
                _put_crop_extent(src, extent, extent)
            # The per-axis cuts are made and put on their mid-plane by the
            # first switch to slice mode (`apply_mode` → `apply_slice_positions`,
            # before anything shows them), not here: a load never pays for a
            # slicer nobody opens (the PO, 12/11: ~2 s on a 92 M cell grid).

        property_title = self._tree.find_title(node_id)
        property_type = self._tree.find_type(node_id)
        if property_title != self._title:
            array_type = self.color_array_type(property_title)
            if array_type is not None:
                self._current_array_type = array_type
                self._current_property_type = property_type
                self._array_path = self._tree.find_path(node_id)
                if self._view_id is not None:
                    # the shared grid is data-only: colouring
                    # it made an invisible leaf, rescaled the GLOBAL table
                    # (the seed of every view's table) and showed a stray bar
                    for src in self._colourable_sources():
                        self.update_colors(src, array_type, property_title, property_type)
            elif self._current_array_type is not None:
                # The node is the grid itself (its property eye closed): back
                # to the solid colour, or the crops would keep the last array
                # while the composite around them has dropped it.
                self.clear_colors()

            self._title = property_title

            for src in self._all_slice_sources() + self._src_volumes:
                src.UpdatePipelineInformation()

            pvsimple.Hide(proxy=self._src_extract_init, view=self._target_view())
            self._redraw()

    def _is_volume_full_extent(self, vol):
        """True when `vol` ([[i0,i1],[j0,j1],[k0,k1]]) spans the grid's
        full extent. ParaView 6's ExplicitStructuredGridCrop produces a
        degenerate 1-cell output at full extent, so a full-extent volume
        renders through rep_data (the non-cropped equivalent) instead of
        its crop (ExtractSubset alike: the same grid again)."""
        if not self._is_ijk:
            # an X/Y/Z box narrowing no axis (nor a surface's I or J)
            from fespp_on_trame.engine.sources.xyz_crop import narrows
            if vol and len(vol) == 5 and [list(map(int, r)) for r in vol[:2]] != self._whole_ij():
                return False
            return not self._current_bounds or not vol or not narrows(vol, self._current_bounds)
        if not self._current_extent or not vol:
            return True
        full = self._current_extent
        ri, rj, rk = vol
        return (
            int(ri[0]) <= full[0] and int(ri[1]) >= full[1]
            and int(rj[0]) <= full[2] and int(rj[1]) >= full[3]
            and int(rk[0]) <= full[4] and int(rk[1]) >= full[5]
        )

    def _active_upstreams(self):
        """The upstream sources currently rendered (and thus the ones
        the chain should attach to) for the current slicer mode."""
        if self._src_extract_init is None:
            return []
        out = [self._render_root()]
        if self._range_mode == 'slice':
            out.extend(self._all_slice_sources())
        elif self._range_mode == 'range':
            out.extend(self._src_volumes)
        # 'full': rep_data only — nothing else renders.
        return out

    # ------------------------------------------------------------------
    # Show / hide

    def show(self, view=None):
        """Show / hide the right combination of sources for the current
        slicer mode, then run `after_show`.

        `after_show` lets the composite re-assert its colour bars: ParaView's
        Hide sweeps away the bar of a table that no VISIBLE display names in
        its global LookupTable, and a block painted through the composite's
        per-block tables names none.

        Full mode displays rep_data alone; slice mode displays the per-axis
        crops; range mode displays each visible volume's crop, except that a
        visible FULL-EXTENT volume renders through rep_data instead (its
        crop output is degenerate at full extent on ParaView 6, see
        _is_volume_full_extent).

        BlockScope: the SHARED instance (no view_id) is DATA-ONLY (array
        resolution, ranges) and shows nothing. The view renders through the
        per-view composite rep, and a shown rep_data would double-paint the
        grid over it (wrong colours by overdraw, eye apparently dead).
        Per-view instances are the GridIsolate and show their own displays.

        No parent fallback: every eye closed (all slicers in slice mode,
        all volumes in range mode) renders NOTHING. An all-hidden set
        must read as empty, not as the full grid sneaking back.

        When the chain has any visible entry, each "would-be visible"
        source is replaced by the Threshold proxies of every visible
        chain TIP for that upstream (union branches all render; a linear
        intersection chain collapses to its single deepest leaf).

        `view` defaults to `_target_view()` when None. Call sites that
        target a specific panel (multi-view eye toggle) pass that panel's
        render view so the Show/Hide does not leak into the wrong view."""
        if self._node_id is None:
            return
        if self._view_id is None:
            # the shared instance is data-only; per-view isolates show /
            # hide their crop displays
            return
        if view is None:
            view = self._target_view()
        if view is None:
            return
        self._prune_scene_cuts(view)

        # The full grid's display reads the NaN mask when it is on
        # (`_render_root`); the raw extractor then stays hidden, since its
        # display would paint the NaN cells back.
        root = self._render_root()
        if root is not self._src_extract_init and self._src_extract_init is not None:
            try:
                pvsimple.Hide(proxy=self._src_extract_init, view=view)
                self._hide_chain_for(self._src_extract_init, view)
            except Exception as exc:
                print(f"[fespp] hide NaN cells: hiding the raw grid: {exc!r}", flush=True)

        # `set_node_id` sets Representation + tint (DiffuseColor / AmbientColor
        # / Opacity from state.solid_color_by_rep) only in the view active at
        # that moment. In OTHER views (multi-view copies, panels promoted via
        # eye toggle) the display is created later with ParaView's default
        # Representation='Outline' and grey colour, so re-assert
        # Representation + tint on every managed source's display in `view`.
        # the view's Represent By (rep_style, set by the app per view), else
        # the rep's own type (E1)
        rep_type = getattr(self, "rep_style", None) or rep_type_for(state, self.rep_path)
        grid_color = (state.solid_color_by_rep or {}).get(self.rep_path)
        zs = self._current_z_scale()
        for src in (
            list(self._all_slice_sources())
            + list(self._src_volumes)
            + ([root] if root is not None else [])
            + self._scene_cut_tips()
        ):
            try:
                disp = pvsimple.GetRepresentation(proxy=src, view=view)
                if disp is not None:
                    disp.Representation = rep_type
                    disp.Scale = [1.0, 1.0, zs]
                    _apply_default_tint(disp, grid_color)
            except Exception:
                pass

        tips = self._visible_leaf_tips()
        print(f"[fespp] journal isolate show ({self._view_id}, {self._rep_token}): mode={self._range_mode}"
              f" chain={len(self._chain)} tips={len(tips)} volumes={len(self._src_volumes)}"
              f" scene cuts={len(self._scene_crops or {})} root={root.GetXMLName() if root is not None else None}",
              flush=True)

        if self._range_mode == 'full':
            # Full grid: rep_data only — every slicer and volume crop
            # hidden. The default mode: a grid shows whole until the
            # user opts into slicing/cropping.
            for src in self._all_slice_sources() + self._src_volumes:
                pvsimple.Hide(proxy=src, view=view)
                self._hide_chain_for(src, view)
            if root is not None:
                self._show_source_or_chain(
                    root, view, True, tips,
                )
        elif self._range_mode == 'slice':
            for src in self._src_volumes:
                pvsimple.Hide(proxy=src, view=view)
                self._hide_chain_for(src, view)

            vis_i = list(self._slices_i_visible_list or [])
            vis_j = list(self._slices_j_visible_list or [])
            vis_k = list(self._slices_k_visible_list or [])
            for axis_srcs, vis_list in (
                (self._src_slicers_i, vis_i),
                (self._src_slicers_j, vis_j),
                (self._src_slicers_k, vis_k),
            ):
                for idx, src in enumerate(axis_srcs):
                    visible = vis_list[idx] if idx < len(vis_list) else True
                    self._show_source_or_chain(src, view, visible, tips)

            if root is not None:
                # No parent fallback: all slicer eyes closed = nothing
                # renders.
                self._show_source_or_chain(
                    root, view, False, tips,
                )
        else:
            for src in self._all_slice_sources():
                pvsimple.Hide(proxy=src, view=view)
                self._hide_chain_for(src, view)

            # Each visible volume renders its own crop; a visible
            # FULL-EXTENT volume renders through rep_data instead
            # (degenerate crop output at full extent on ParaView 6). Every
            # volume eye closed = nothing renders.
            vis = self._volumes_visible or []
            any_full_visible = False
            for idx, src in enumerate(self._src_volumes):
                visible = bool(vis[idx]) if idx < len(vis) else True
                vol = self._volumes[idx] if idx < len(self._volumes) else None
                is_full = self._is_volume_full_extent(vol)
                if visible and is_full:
                    any_full_visible = True
                self._show_source_or_chain(
                    src, view, visible and not is_full, tips,
                )
            if root is not None:
                self._show_source_or_chain(
                    root, view, any_full_visible, tips,
                )
        self._after_show()

    def _after_show(self):
        """Run the `after_show` hook, if any; a failing hook is logged and
        never breaks the show."""
        hook = getattr(self, "after_show", None)
        if hook is None:
            return
        try:
            hook()
        except Exception as exc:
            print(f"[fespp] isolate after-show hook ({self._view_id}):", exc, flush=True)

    def _show_source_or_chain(self, src, view, visible, tips):
        """Show src OR — when a threshold chain is active for this
        upstream — EVERY visible tip leaf's proxy, gated by the user's
        eye state for that source.

        A linear (intersection) chain has a single tip, so this shows
        just the deepest leaf. Sibling branches (union) each contribute
        a tip, so all disjoint intervals render together instead of the
        last one clobbering the rest. Non-tip chain proxies for this
        upstream are always hidden."""
        tip_proxies = [
            p for p in (t.pv_proxies.get(id(src)) for t in (tips or []))
            if p is not None
        ]
        if tip_proxies:
            # the source AND its scene cut: the cut drawn while the source
            # stood alone would stay, the scene whole again under the tips
            # (the PO, 30/10: a SOIL range on a cut scene "did not work")
            pvsimple.Hide(proxy=src, view=view)
            self._hide_scene_cut(src, view)
            # Hide every non-tip chain proxy for this upstream first.
            for entry in self._chain:
                p = entry.pv_proxies.get(id(src))
                if p is not None and p not in tip_proxies:
                    try:
                        pvsimple.Hide(proxy=p, view=view)
                        self._hide_scene_cut(p, view)
                    except Exception:
                        pass
            for p in tip_proxies:
                self._show_or_hide(p, view, visible, dress=True)
        else:
            self._hide_chain_for(src, view)
            self._show_or_hide(src, view, visible)

    # ------------------------------------------------------------------
    # the scene cut on this isolate's displays (the PO, 29/10 evening: "the
    # whole scene does nothing" on a grid a card had isolated — the scene
    # cut is on the composite, and an isolate draws through its own
    # displays): a prep -> cut stage (engine/blockscope/scene_crop) between
    # each display and what it drew, moved at each step
    _scene_boxes = []
    _scene_bounds = []
    _scene_crops = None     # the proxy's global id -> (proxy, SceneCrop)

    @staticmethod
    def _gid(proxy):
        """A proxy's key: its global id, unique for the session — not
        `id()`, which Python gives again to a new proxy once the old one
        is freed: a chain made again took the scene cut of the chain it
        replaced, and showed stale cells (the PO, 30/10: the Property
        slicer "did not work" on a cut scene until the scene's eye was
        toggled)."""
        gid = getattr(getattr(proxy, "SMProxy", None), "GetGlobalIDAsString", None)
        return gid() if gid is not None else str(id(proxy))

    def set_scene_cut(self, boxes, bounds, live=False):
        """The scene's X/Y/Z boxes ([[x0, x1], [y0, y1], [z0, z1]] each, a
        scene of `bounds`) on every display this isolate shows; a step
        (`live`) moves the cuts, an empty `boxes` drops them."""
        boxes = [[[float(lo), float(hi)] for lo, hi in b] for b in (boxes or [])]
        was = bool(self._scene_boxes)
        self._scene_boxes = boxes
        self._scene_bounds = [float(v) for v in (bounds or [])]
        if self._scene_crops is None:
            self._scene_crops = {}
        if not live or not was:
            print(f"[fespp] journal isolate scene cut ({self._view_id}, {self._rep_token}):"
                  f" boxes={len(boxes)} was={was} live={live}", flush=True)
        if not boxes:
            if was:
                self._drop_scene_cuts()
                self._redraw()
            return
        if was and live:
            for base, crop in self._scene_crops.values():
                crop.set_boxes(base, boxes, self._scene_bounds)
            return
        self._redraw()

    def _scene_cut_for(self, proxy):
        """The cut of `proxy`'s output by the scene's boxes, made or moved;
        None when the scene is whole."""
        if not self._scene_boxes:
            return None
        from fespp_on_trame.engine.blockscope.scene_crop import SceneCrop
        if self._scene_crops is None:
            self._scene_crops = {}
        held = self._scene_crops.get(self._gid(proxy))
        if held is None:
            held = (proxy, SceneCrop(f"{self._view_id}_iso{len(self._scene_crops)}"))
            self._scene_crops[self._gid(proxy)] = held
        base, crop = held
        crop.set_boxes(base, self._scene_boxes, self._scene_bounds)
        crop.drop_stale()
        tips = crop.tips()
        return tips[0] if tips else None

    def scene_cut_of(self, proxy):
        """The scene's cut (`SceneCrop`) drawn for `proxy` when there is one,
        None otherwise."""
        held = (self._scene_crops or {}).get(self._gid(proxy))
        return held[1] if held is not None and held[1].tips() else None

    def _scene_cut_tip(self, proxy):
        """The cut drawn for `proxy` when there is one, None otherwise."""
        cut = self.scene_cut_of(proxy)
        return cut.tips()[0] if cut is not None else None

    def _scene_cut_tips(self):
        out = []
        for base, _crop in (self._scene_crops or {}).values():
            tip = self._scene_cut_tip(base)
            if tip is not None:
                out.append(tip)
        return out

    def _hide_scene_cut(self, proxy, view):
        tip = self._scene_cut_tip(proxy)
        if tip is not None:
            try:
                pvsimple.Hide(proxy=tip, view=view)
            except Exception as exc:
                print(f"[fespp] scene cut on an isolate ({self._view_id}): a cut not hidden ({exc})", flush=True)

    def _show_or_hide(self, proxy, view, visible, dress=False):
        """`proxy` shown or hidden in `view` — through its scene cut when
        the scene is cut: the cut drawn as the proxy would be (its look
        inherited), the proxy itself hidden."""
        cut = self._scene_cut_for(proxy) if visible else None
        if cut is not None:
            pvsimple.Hide(proxy=proxy, view=view)
            pvsimple.Show(proxy=cut, view=view)
            inherit_display(proxy, cut, view)
            self._dress_tip(cut, view)
            return
        self._hide_scene_cut(proxy, view)
        (pvsimple.Show if visible else pvsimple.Hide)(proxy=proxy, view=view)
        if visible and dress:
            self._dress_tip(proxy, view)

    def _prune_scene_cuts(self, view):
        """The cuts of displays that are gone (a volume removed, a chain
        entry dropped) deleted."""
        if not self._scene_crops:
            return
        live = {self._gid(p) for p in list(self._all_slice_sources()) + list(self._src_volumes)}
        for s in (self._render_root(), self._src_extract_init):
            if s is not None:
                live.add(self._gid(s))
        for entry in self._chain:
            live.update(self._gid(p) for p in entry.pv_proxies.values() if p is not None)
        for key in [k for k in self._scene_crops if k not in live]:
            _base, crop = self._scene_crops.pop(key)
            self._hide_scene_cut_of(crop, view)
            crop.release()

    def _drop_scene_cuts(self):
        view = self._target_view()
        for _base, crop in list((self._scene_crops or {}).values()):
            self._hide_scene_cut_of(crop, view)
            crop.release()
        self._scene_crops = {}

    def _hide_scene_cut_of(self, crop, view):
        for tip in crop.tips():
            try:
                pvsimple.Hide(proxy=tip, view=view)
            except Exception as exc:
                print(f"[fespp] scene cut on an isolate ({self._view_id}): a cut not hidden ({exc})", flush=True)

    def _dress_tip(self, proxy, view):
        """A threshold tip drawn as the crops are: the view's exaggeration
        and Represent By (04-verification E2: the tips kept the old
        exaggeration and floated beside the grid)."""
        try:
            disp = pvsimple.GetRepresentation(proxy=proxy, view=view)
            if disp is None:
                return
            disp.Scale = [1.0, 1.0, self._current_z_scale()]
            style = getattr(self, "rep_style", None)
            if style:
                disp.Representation = style
        except Exception as exc:
            print(f"[fespp] threshold tip display ({self._view_id}):", exc, flush=True)

    def _hide_chain_for(self, src, view):
        """Hide, in `view`, every chain proxy attached to upstream `src`,
        and the scene cuts drawn for them."""
        self._hide_scene_cut(src, view)
        for entry in self._chain:
            p = entry.pv_proxies.get(id(src))
            if p is not None:
                try:
                    pvsimple.Hide(proxy=p, view=view)
                    self._hide_scene_cut(p, view)
                except Exception:
                    pass

    def _visible_leaf_tips(self):
        """Every visible chain TIP: entries that are visible, have every
        ancestor on the path to root visible, AND have no visible child.

        A linear chain (each threshold stacked on the previous =
        intersection) has a single tip — the deepest entry. Sibling
        branches off a shared parent (union of disjoint intervals) each
        produce their own tip, so all of them render together. The
        chain's display shows each tip's output; non-tip entries serve
        only as upstream filters. Empty list when nothing is visible."""
        visible = [
            e for e in self._chain
            if e.visible and self._ancestors_all_visible(e)
        ]
        parents_with_visible_child = {
            e.parent_name for e in visible if e.parent_name
        }
        return [e for e in visible if e.name not in parents_with_visible_child]

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

    def array_domain(self, array):
        """What a threshold on `array` works over: {assoc, kind, data_range,
        unique_values, labels}, or None for an array this grid lacks.
        Cached per array while the grid is the same (a scan of the values
        for the integer kinds)."""
        if self._src_extract_init is None or not array:
            return None
        cache = self.__dict__.setdefault("_domain_cache", {})
        key = (id(self._src_extract_init), array)
        if key in cache:
            return cache[key]
        assoc = self._resolve_assoc(array)
        if not assoc:
            return None
        ijkgrid_node_id = self._node_id
        rep_path = self._tree.find_path(ijkgrid_node_id) if ijkgrid_node_id else "ijk"
        rng = self.array_data_range(array) or (0.0, 1.0)
        # Resolve property kind (Continuous / Discrete / Categorical)
        # for the threshold panel slider dispatch. Source proxy: the
        # rep_data extractor — that's the unfiltered VTK array store,
        # so scanning uniques there reflects the data's true value
        # set, not what's left after slicers / chain filtering.
        from fespp_on_trame.engine.sources.chain_domain import (
            chain_domain, resolve_chain_kind,
        )
        kind, unique_values, labels = resolve_chain_kind(
            self._tree, rep_path, array,
            self._src_extract_init, assoc,
        )
        # Discrete / Categorical: shrink the slider domain to the real
        # categories — the raw range includes the NullValue sentinel
        # (INT32_MAX) of inactive cells and spans billions.
        rng, unique_values, labels = chain_domain(
            kind, unique_values, labels, rng,
        )
        cache[key] = {"assoc": assoc, "kind": kind,
                      "data_range": (float(rng[0]), float(rng[1])),
                      "unique_values": unique_values, "labels": labels}
        return cache[key]

    def _entry_name(self, parent_name, array):
        """A chain entry name no entry has: under its parent, by its array.
        Multiple thresholds on the same array under the same parent are
        valid — their outputs render in parallel (UNION of the ranges) — so
        a second one is suffixed, never a PV registration-name collision."""
        if parent_name is None:
            ijkgrid_node_id = self._node_id
            rep_path = self._tree.find_path(ijkgrid_node_id) if ijkgrid_node_id else "ijk"
            base_name = f"thr_{_sanitize(rep_path)}_{_sanitize(array)}"
        else:
            base_name = f"{parent_name}_{_sanitize(array)}"
        existing_names = {e.name for e in self._chain}
        if base_name in existing_names:
            suffix = 2
            while f"{base_name}_{suffix}" in existing_names:
                suffix += 1
            base_name = f"{base_name}_{suffix}"
        return base_name

    def _new_entry(self, parent_name, array, domain, low=None, high=None):
        rng = domain["data_range"]
        return _IjkChainEntry(
            name=self._entry_name(parent_name, array),
            parent_name=parent_name,
            array=array,
            assoc=domain["assoc"],
            visible=True,
            low=float(rng[0] if low is None else low),
            high=float(rng[1] if high is None else high),
            data_range=(float(rng[0]), float(rng[1])),
            kind=domain["kind"],
            unique_values=domain["unique_values"],
            labels=domain["labels"],
        )

    def add_threshold(self, parent_name, array):
        """Append a chain entry under `parent_name` (or at the root if None)
        and create its per-upstream PV proxies on the spot. Returns the new
        entry's name, or None when nothing was added."""
        if parent_name is not None and not any(e.name == parent_name for e in self._chain):
            return None
        domain = self.array_domain(array)
        if domain is None:
            return None
        entry = self._new_entry(parent_name, array, domain)
        self._chain.append(entry)
        self._refresh_chain_pipeline()
        self._redraw()
        return entry.name

    def replace_chain(self, branches):
        """The whole chain at once (the Property slicer, 28/10): `branches`
        [[(array, low, high), ...], ...], each a root-to-tip branch whose
        entries intersect, the branches shown together (their union). Every
        old entry goes; the filters are rebuilt ONCE. Returns, per branch,
        the names of its entries ([] for a branch on an array this grid
        lacks)."""
        for entry in self._chain:
            self._drop_entry(entry)
        self._chain = []
        names = []
        for branch in branches or ():
            parent, path = None, []
            for array, low, high in branch:
                domain = self.array_domain(array)
                if domain is None:
                    path = []
                    break
                entry = self._new_entry(parent, array, domain, low, high)
                self._chain.append(entry)
                parent = entry.name
                path.append(entry.name)
            names.append(path)
        self._refresh_chain_pipeline()
        self._redraw()
        return names

    def _say_unknown_entry(self, action, name):
        """A threshold call naming no entry of this chain did nothing: say
        so in the log, listing the entry names, so a caller holding a stale
        entry name does not lose its change silently."""
        print(f"[fespp] threshold {action}: no entry named {name!r} on"
              f" {self._title!r} (entries: {[e.name for e in self._chain]})",
              flush=True)

    def delete_threshold(self, name):
        idx = next((i for i, e in enumerate(self._chain) if e.name == name), -1)
        if idx < 0:
            self._say_unknown_entry("delete", name)
            return False
        target = self._chain[idx]
        # Children of target adopt target.parent_name as new logical parent.
        for e in self._chain:
            if e.parent_name == name:
                e.parent_name = target.parent_name
        self._chain.pop(idx)
        self._drop_entry(target)
        self._refresh_chain_pipeline()
        self._redraw()
        return True

    def _drop_entry(self, entry):
        """An entry's filters hidden and deleted (the entry leaves the chain
        at the caller's hand)."""
        view = self._target_view()
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

    def set_range(self, name, low, high, update=True):
        """The range entry `name` keeps. `update=False` leaves the filters to
        the next render, which runs only the ones a view shows: the value
        player steps many times a second, and the entry has a filter per
        upstream (the volume and every slicer plane, 5 on a sliced grid,
        ~10 ms each on drogon's 926 808 cells, bench of 27/10) of which
        usually one is on screen."""
        for e in self._chain:
            if e.name == name:
                e.low = float(low)
                e.high = float(high)
                for proxy in e.pv_proxies.values():
                    try:
                        proxy.LowerThreshold = e.low
                        proxy.UpperThreshold = e.high
                        if update:
                            proxy.UpdatePipeline()
                    except Exception as exc:
                        print(f"[fespp] threshold range {name!r}: {exc!r}", flush=True)
                return
        self._say_unknown_entry("range", name)

    def set_visible(self, name, visible):
        for e in self._chain:
            if e.name == name:
                e.visible = bool(visible)
                break
        else:
            self._say_unknown_entry("visibility", name)
            return
        self._refresh_chain_pipeline()
        self._redraw()

    def set_parent(self, name, parent_name):
        """Entry `name` chained under `parent_name` (∩), or a root (∪) with
        None — the Property slicer's operator of a row (28/10). Refused
        (False) for an unknown entry or parent, or a parent among the
        entry's own descendants (a loop)."""
        entry = self._entry_by_name(name)
        if entry is None:
            self._say_unknown_entry("parent", name)
            return False
        cursor = self._entry_by_name(parent_name)
        if parent_name is not None and cursor is None:
            self._say_unknown_entry("parent", parent_name)
            return False
        while cursor is not None:
            if cursor.name == name:
                return False
            cursor = self._entry_by_name(cursor.parent_name)
        if entry.parent_name == parent_name:
            return True
        entry.parent_name = parent_name
        self._refresh_chain_pipeline()
        self._redraw()
        return True

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
        return self._point_cells(src) if self._is_points else src

    def _point_cells(self, src):
        """`src` as one vertex cell per point. FESPP delivers a point set as
        ONE poly-vertex cell, and a threshold keeps or drops a cell whole: on
        the raw set it kept the whole cloud or nothing (decatur_events on
        ADME, 27/10). ParaView's Convert To Point Cloud makes each point a
        cell of its own, so the chain keeps the points whose value passes."""
        pc = self._point_clouds.get(id(src))
        if pc is None:
            try:
                pc = pvsimple.ConvertToPointCloud(
                    registrationName=f"pointcells_{self._rep_token}_{id(src)}", Input=src)
                pc.CellGenerationMode = "Vertex cells"
            except Exception as exc:
                print(f"[fespp] point set as vertex cells: {exc!r} — thresholded as one cell",
                      flush=True)
                return src
            self._point_clouds[id(src)] = pc
        return pc

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
                        print(f"[fespp] threshold {entry.name!r}: not made ({exc!r})", flush=True)
                        continue
                    entry.pv_proxies[id(src)] = proxy
                    self._inherit_display(proxy, src)
                else:
                    try:
                        if proxy.Input is not effective:
                            proxy.Input = effective
                    except Exception as exc:
                        print(f"[fespp] threshold {entry.name!r}: its input not moved ({exc!r})", flush=True)
                # Push current Scalars + bounds.
                try:
                    proxy.Scalars = [entry.assoc, entry.array]
                    proxy.LowerThreshold = float(entry.low)
                    proxy.UpperThreshold = float(entry.high)
                    proxy.UpdatePipeline()
                except Exception as exc:
                    print(f"[fespp] threshold {entry.name!r}: its range not set ({exc!r})", flush=True)

    def _inherit_display(self, thr_proxy, src):
        """Copy the parent's display look onto the threshold output in this
        grid's target view. Delegates to the shared `inherit_display`."""
        inherit_display(src, thr_proxy, self._target_view())

    def refresh_threshold_pipeline(self):
        """Mode-flip / slicer-add hook for the engine: re-sync the chain
        with the active upstream set."""
        self._refresh_chain_pipeline()

    # ------------------------------------------------------------------
    # NaN / colors

    def _lut(self, name):
        """The view's lookup table for `name` — the one the composite
        colours the grid with — else the global one."""
        if self._lut_for is not None:
            try:
                lut = self._lut_for(name)
                if lut is not None:
                    return lut
            except Exception:
                pass
        return pvsimple.GetColorTransferFunction(name)

    def set_color(self, assoc, name):
        """Colour every crop by the array the composite colours the grid
        with — (assoc, name) as the eye resolved it (sanitized VTK name,
        realization suffix), never looked up again by tree title."""
        if self._node_id is None or not name or not assoc:
            return
        if name == self._title and assoc == self._current_array_type:
            return
        self._current_array_type = assoc
        self._current_property_type = None
        self._array_path = None
        for src in self._colourable_sources():
            if src is not None:
                self.update_colors(src, assoc, name, None)
        self._title = name
        self._redraw()

    def hide_all(self, view=None):
        """Every display of this grid off in `view` (the composite paints the
        block again); the crops, the chain and their state stay; then
        `after_show` as show() does."""
        if view is None:
            view = self._target_view()
        if view is None:
            return
        for src in self._colourable_sources():
            if src is None:
                continue
            try:
                pvsimple.Hide(proxy=src, view=view)
                self._hide_chain_for(src, view)
            except Exception:
                pass
        self._after_show()

    def clear_colors(self):
        """Every crop back to the grid's solid colour: no array bound."""
        view = self._target_view()
        grid_color = (state.solid_color_by_rep or {}).get(self.rep_path)
        for src in self._colourable_sources():
            if src is None:
                continue
            try:
                disp = pvsimple.GetRepresentation(proxy=src, view=view)
                disp.ColorArrayName = ['CELLS', '']
                _apply_default_tint(disp, grid_color)
            except Exception:
                pass
        if self._title and self._lut_for is None:
            # Legacy shared instance: nobody else manages the bar.
            try:
                pvsimple.GetScalarBar(ctf=self._lut(self._title), view=view).Visibility = False
            except Exception:
                pass
        self._title = None
        self._array_path = None
        self._current_array_type = None
        self._current_property_type = None

    def update_colors(self, src, array_type, property_title, property_type):
        """Apply a ColorBy on a single source of this grid: set the lookup
        table and, for the legacy shared instance, the scalar bar's title /
        format, hiding the bar of the previously selected array."""
        view = self._target_view()
        representation = pvsimple.GetRepresentation(proxy=src, view=view)
        suppress_selection_labels(representation)
        representation.ColorArrayName = [array_type, property_title]
        # The VIEW's LUT: on another table the crops would paint on a scale
        # of their own, unlike the grid around them.
        lut = self._lut(property_title)
        representation.LookupTable = lut
        cut = self._scene_cut_tip(src)
        if cut is not None:
            # the scene cut drawn for this source colours as it does
            cut_rep = pvsimple.GetRepresentation(proxy=cut, view=view)
            cut_rep.ColorArrayName = [array_type, property_title]
            cut_rep.LookupTable = lut
        if src is self._src_extract_init or (src is not None and src is self._nan_mask):
            # The FULL grid's range: the crops share this table and must not
            # narrow it to their own extent, or the colours would shift as a
            # crop moves.
            leaf_rep.rescale_to_range(representation)
        if self._lut_for is not None:
            # A composite owns the view's single bar (PdcScene._sync_scalar_bar).
            return
        from fespp_on_trame.engine import property_values
        bar = pvsimple.GetScalarBar(ctf=lut, view=view)
        bar.Visibility = True
        bar.RangeLabelFormat = numfmt.SCALAR_BAR_RANGE_FORMAT
        bar.Resizable = 1
        bar.DrawNanAnnotation = 1
        # The property's one display name (title, component, unit); the
        # component is in it, so ParaView's own suffix stays off.
        bar.ComponentTitle = ''
        bar.Title = property_values.display_label(
            state, self._tree, self._array_path, fallback=property_title)
        if self._title and self._title != property_title:
            try:
                pvsimple.GetScalarBar(ctf=self._lut(self._title), view=view).Visibility = False
            except Exception:
                pass

    def _set_extent(self, src, ext):
        """Write a crop's extent only when it changes: the write marks the
        crop modified, so an unconditional write would re-execute every
        volume on each commit."""
        ext = [int(v) for v in ext]
        if _crop_extent(src) != ext:
            _put_crop_extent(src, ext, self._current_extent)

    # ------------------------------------------------------------------
    # The slicing as plain data, and the public reads

    def snapshot(self):
        """The slicing of this grid as plain data: the mode, the grid's
        extent, the single volume's ranges, the volumes and their eyes, the
        cuts and their eyes per axis. What the app, the session and the
        scenarios read, never the private fields."""
        return {
            "mode": self._range_mode,
            # an I/J/K grid (its extent, index volumes) or not (its bounds,
            # X/Y/Z volumes in the scene's coordinates)
            "ijk": self._is_ijk,
            "bounds": list(self._current_bounds or []),
            "extent": list(self._current_extent or []),
            # a surface's I/J point extent ([] when it has none)
            "ij_extent": list(self._ij_extent or []),
            "range": {a: list(getattr(self, f"_range_{a}") or []) for a in "ijk"},
            "volumes": [[list(r) for r in v] for v in (self._volumes or [])],
            "volumes_visible": list(self._volumes_visible or []),
            "positions": {a: list(getattr(self, f"_slices_{a}_list") or []) for a in "ijk"},
            "visible": {a: list(getattr(self, f"_slices_{a}_visible_list") or []) for a in "ijk"},
        }

    def set_volume_range(self, axis, rng):
        """The single volume's [first, last] index kept on one axis
        ('i' / 'j' / 'k'); `apply_volumes` draws it."""
        setattr(self, f"_range_{axis}", [int(rng[0]), int(rng[1])])

    def colourable_sources(self):
        """Every proxy of this grid that takes the view's colouring."""
        return self._colourable_sources()

    def xyz_crop_cells(self):
        """[(narrowed axes, cells kept)] of each X/Y/Z crop, its tip run —
        what the scenarios read (engine/sources/xyz_crop)."""
        out = []
        for crop in self._xyz_crops:
            tip = crop.tip
            try:
                tip.UpdatePipeline()
                cells = tip.GetDataInformation().GetNumberOfCells()
            except Exception as exc:
                print(f"[fespp] xyz crop cells: {exc!r}", flush=True)
                cells = None
            out.append((crop.axes, cells))
        return out

    def visible_leaf_tips(self):
        """The threshold entries at the tip of a visible branch."""
        return self._visible_leaf_tips()

    def root_branch(self, proxy):
        """[(array, assoc, low, high)] of the entries from the tip whose
        filter on the whole grid is `proxy` back up its branch; [] when
        `proxy` is no such filter (a crop's cells say which they are, these
        do not)."""
        root = id(self._render_root())
        entry = next((e for e in self._chain if e.pv_proxies.get(root) is proxy), None)
        out = []
        while entry is not None:
            out.append((entry.array, entry.assoc, entry.low, entry.high))
            entry = self._entry_by_name(entry.parent_name)
        return out

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
            self._set_extent(self._src_slicers_i[idx], [pos, pos, rj[0], rj[1], rk[0], rk[1]])
        for idx, pos in enumerate(slices_j_list):
            self._set_extent(self._src_slicers_j[idx], [ri[0], ri[1], pos, pos, rk[0], rk[1]])
        for idx, pos in enumerate(slices_k_list):
            self._set_extent(self._src_slicers_k[idx], [ri[0], ri[1], rj[0], rj[1], pos, pos])

    def apply_slice_visibility(self, vis_i, vis_j, vis_k):
        """Store the per-slicer eye flags; the next `show()` applies them."""
        self._slices_i_visible_list = list(vis_i or [])
        self._slices_j_visible_list = list(vis_j or [])
        self._slices_k_visible_list = list(vis_k or [])

    def _dress_volume(self, src):
        """A volume's display in the isolate's view, drawn and coloured as
        the grid is."""
        src.UpdatePipelineInformation()
        view = self._target_view()
        rep = pvsimple.GetRepresentation(proxy=src, view=view)
        suppress_selection_labels(rep)
        rep.Representation = rep_type_for(state, self.rep_path)
        rep.Scale = [1.0, 1.0, self._current_z_scale()]
        if self._title and self._current_array_type:
            self.update_colors(src, self._current_array_type, self._title,
                               self._current_property_type)

    def _create_volume_source(self, idx: int):
        """Create a new range-mode volume — a crop chained on rep_data on an
        I/J/K grid, an X/Y/Z crop otherwise (engine/sources/xyz_crop) —
        styled and coloured like a slicer source."""
        if not self._is_ijk:
            from fespp_on_trame.engine.sources import xyz_crop
            b = self._current_bounds or [0.0] * 6
            crop = xyz_crop.CoordCrop(self._region_input(), f"xyzcrop{idx}__{self._rep_token}",
                                      ij=self._ij_extent)
            crop.set_box(self._whole_ij() + [b[0:2], b[2:4], b[4:6]], b)
            self._xyz_crops.append(crop)
            self._dress_volume(crop.tip)
            return crop.tip
        src = _new_crop(f'slicervolume{idx}__{self._rep_token}',
                        self._render_root(), self._structured)
        if self._current_extent:
            _put_crop_extent(src, self._current_extent, self._current_extent)
        self._dress_volume(src)
        return src

    def _sync_volume_sources(self, count: int):
        """Ensure exactly `count` volume crop sources exist."""
        if self._src_extract_init is None:
            return
        while len(self._src_volumes) < count:
            src = self._create_volume_source(len(self._src_volumes))
            self._src_volumes.append(src)
            # New volume joins the active upstream set — reattach the
            # chain to it.
            self._refresh_chain_pipeline()
        view = self._target_view()
        while len(self._src_volumes) > count:
            src = self._src_volumes.pop()
            self._delete_chain_proxies_for_upstream(src)
            if self._xyz_crops:
                self._xyz_crops.pop().delete(view)
                continue
            try:
                pvsimple.Hide(proxy=src, view=view)
                pvsimple.Delete(src)
            except Exception:
                pass

    def apply_volumes(self, volumes, visible_list):
        """Sync the range-mode volume crops with the per-volume range
        list ([[i0,i1],[j0,j1],[k0,k1]] each on an I/J/K grid, [[x0,x1],
        [y0,y1],[z0,z1]] in the scene's coordinates otherwise) and
        visibility flags, creating / deleting crop sources as needed; every
        visible volume renders (their union). Mirrors both lists into the
        instance's stored state."""
        self._volumes = [list(map(list, v)) for v in (volumes or [])]
        if self._ij_extent:
            # an X/Y/Z box on a surface (a session, a copy) keeps its I and J whole
            self._volumes = [self._whole_ij() + v if len(v) == 3 else v for v in self._volumes]
        self._volumes_visible = list(visible_list or [])
        if self._node_id is None:
            return
        self._sync_volume_sources(len(self._volumes))
        if not self._is_ijk:
            self._apply_xyz_boxes()
            return
        for src, vol in zip(self._src_volumes, self._volumes):
            ri, rj, rk = vol
            self._set_extent(src, [ri[0], ri[1], rj[0], rj[1], rk[0], rk[1]])

    def _whole_ij(self):
        """A surface's whole I and J ranges ([] when it has no 2D grid)."""
        e = self._ij_extent
        return [[e[0], e[1]], [e[2], e[3]]] if e else []

    def _apply_xyz_boxes(self):
        """Each X/Y/Z crop on its box (a drag, the player): the cut moved,
        its tip kept — nothing made again whatever axes the box narrows
        (the threshold chain made again on a new axis left the view empty
        while the hand was down, the PO, 29/10 evening)."""
        b = self._current_bounds or [0.0] * 6
        for crop, vol in zip(self._xyz_crops, self._volumes):
            crop.set_box(vol, b)

    def apply_mode(self, mode):
        """Switch the slicer mode ('full', 'slice' or 'range') and prepare
        the newly active sources; the caller runs `show()` afterwards."""
        if not mode or self._range_mode == mode:
            return
        self._range_mode = mode
        if mode == 'slice':
            # The cuts follow the CURRENT positions and in-plane ranges.
            self.apply_slice_positions(self._slices_i_list, self._slices_j_list,
                                       self._slices_k_list)
        # Mode flip changes the active upstream set — rebuild chain
        # attachments before the next show().
        self.refresh_threshold_pipeline()
        # The sources that become active in the NEW mode may carry a
        # stale cached output (range mode pulls only the volume crops,
        # slice mode only the per-axis crops). show() then shows them and
        # the render pulls data: rendering a slicer whose cached output no
        # longer matches its upstream rep_data crashes natively ("Connection
        # closed"). Force a fresh data pass first, like the defensive
        # UpdatePipeline in data_load.run.
        for src in self._active_upstreams():
            try:
                src.UpdatePipeline()
            except Exception:
                pass
