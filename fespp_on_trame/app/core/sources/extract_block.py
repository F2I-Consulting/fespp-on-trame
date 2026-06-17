"""Per-rep data source for non-IjkGrid representations.

DEPRECATED: the per-(rep, view) equivalents on `RepInScene` supersede the
slice / clip / threshold methods here. This class remains as a fallback used
only when `vtkEPCCollectorClone` isn't available (the scene's clone is the
collector source itself); `_chain` stays empty unless that fallback fires. Do
not call the slice/clip/threshold methods from new code.

One `ExtractBlockRepresentation` instance per loaded RESQML rep
(UnstructuredGrid, Trajectory, Grid2d, PointSet, Polyline, PolylineSet,
TriangulatedSet, …). (`Wellbore` is NOT a rep — it's a grouping folder; only
its child Trajectory/Frame/Marker reps load.) Each instance owns:

  - a single `ExtractBlock` proxy created via the collector's
    `ExtractRepPath` / `ExtractedRepProducerName` properties (C++
    "WithoutCopy" semantics: ShallowCopy in RequestData, no real data
    duplication);
  - an ordered list of `ChainEntry` describing a deletable threshold chain.
    Each entry has its own Threshold proxy chained onto its parent (or onto
    the rep source if the parent is None / hidden).

Visibility rules:
  - An entry is shown iff `entry.visible` AND it has no visible descendant
    (otherwise the descendant subsumes the entry's rendered contribution).
  - The rep source is hidden when at least one chain tip is shown, or when
    the user toggled the rep's eye off (`state.ui_hidden_rep_paths`).

The class is independent of `SourceRegistry` (in `source_registry.py`), which
holds a dict of instances and forwards the per-rep calls."""
import re

from trame.app import get_server
from paraview import simple as pvsimple
from paraview.servermanager import vtkSMPropertyHelper

from fespp_on_trame.app.core.sources.representation import (
    _sanitize,
    _find_registered_proxy,
    _apply_default_tint,
    inherit_display,
    arrays_from_source,
    array_range_from_source,
    resolve_assoc,
)
from fespp_on_trame.app.utils.naming import make_valid_vtk_name
from fespp_on_trame.app.core.sources import threshold_chain


server = get_server()
state = server.state


class ChainEntry:
    """One node in an `ExtractBlockRepresentation`'s threshold chain.

    `parent_name` is None when the parent is the rep's source (root
    of the chain); otherwise it points to another entry by name.
    `proxy.Input` reflects the *effective* input — when an ancestor
    is hidden, the proxy is dynamically rewired to skip it. The
    logical parent (`parent_name`) stays immutable for the entry's
    lifetime.

    Property-kind dispatch:
      - `kind` is one of `"Continuous"` / `"Discrete"` / `"Categorical"`.
        Drives the threshold panel's slider widget (range slider vs.
        integer-stepped vs. labeled-ticks).
      - `unique_values` is a sorted list of distinct values in the
        underlying VTK array — used to render ticks for Discrete /
        Categorical entries. Empty for Continuous (the range slider
        works on continuous bounds instead).
      - `labels` is a `{value: label}` dict for Categorical entries
        (value→category-name), read from the LUT's `Annotations`
        property at threshold creation. Empty for the other kinds."""

    __slots__ = ("name", "parent_name", "array", "assoc", "proxy",
                 "visible", "low", "high", "data_range",
                 "kind", "unique_values", "labels")

    def __init__(self, name, parent_name, array, assoc, proxy,
                 visible, low, high, data_range,
                 kind="Continuous", unique_values=None, labels=None):
        self.name = name
        self.parent_name = parent_name
        self.array = array
        self.assoc = assoc
        self.proxy = proxy
        self.visible = visible
        self.low = low
        self.high = high
        self.data_range = data_range
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


_DEPRECATED_WARNED: set = set()


def _warn_deprecated(name: str) -> None:
    """Single-fire deprecation print. Keeps the log readable when a
    legacy path is hit in a tight loop (e.g. ColorBy fan-out)."""
    if name in _DEPRECATED_WARNED:
        return
    _DEPRECATED_WARNED.add(name)


# Max number of unique values for which we treat an array as
# Categorical / Discrete in the threshold UI. Beyond that the slider
# becomes unreadable (too many ticks) so we degrade to Continuous —
# the user can still threshold via low/high bounds.
_MAX_DISCRETE_UNIQUES = 64


def resolve_chain_kind(tree, rep_path, array_name, source_proxy, assoc):
    """Determine the property kind + unique-value list + categorical
    labels for a fresh chain entry.

    Returns `(kind, unique_values, labels)`:

      - `kind` is `"Continuous"` / `"Discrete"` / `"Categorical"`.
        Derived from the tree's `propKind` attribute on the property
        node whose VTK array name matches `array_name`. Falls back to
        `"Continuous"` when the lookup fails (defensive — UI then
        renders a plain range slider).
      - `unique_values` is the sorted list of distinct values found
        on the VTK array. Populated only for Discrete / Categorical.
        Capped to `_MAX_DISCRETE_UNIQUES`; an array exceeding the
        cap is demoted to `"Continuous"`.
      - `labels` is the `{value: label}` mapping read from the LUT's
        `Annotations` property — set only for Categorical and only
        when the LUT has annotations (typically populated by the
        CategoricalColorEditor on first activation). Empty otherwise."""
    kind = _kind_from_tree(tree, rep_path, array_name)
    if kind == "Continuous":
        return ("Continuous", [], {})

    uniques = _scan_unique_values(source_proxy, array_name, assoc)
    if not uniques or len(uniques) > _MAX_DISCRETE_UNIQUES:
        return ("Continuous", [], {})

    labels = {}
    if kind == "Categorical":
        labels = _read_lut_annotations(array_name)
    return (kind, uniques, labels)


def _kind_from_tree(tree, rep_path, array_name):
    """Walk the rep's subtree for a property node whose title (or
    propTitle for MR) matches `array_name`, return its `propKind`.

    Mirrors `threshold_dispatch._find_property_path_by_title` but
    inlined here to keep the dependency graph tidy (extract_block
    shouldn't import from engine.threshold_dispatch)."""
    if tree is None or not rep_path or not array_name:
        return "Continuous"
    try:
        rep_id = tree.find_node_id(rep_path)
    except Exception:
        return "Continuous"
    if rep_id is None:
        return "Continuous"
    # Strip the MR realization suffix `_real_<idx>` (if any) so we
    # match the MR property node by its propTitle. Non-MR arrays
    # don't have the suffix so this is a no-op for them.
    bare = re.sub(r"_real_\d+$", "", array_name)
    sanitized = make_valid_vtk_name(bare)
    from fespp_on_trame.app.core import element_type
    for nid in tree.find_all_descendant_ids(rep_id):
        try:
            kind = tree.find_type(nid) or ""
        except Exception:
            continue
        if not element_type.for_kind(kind).is_property():
            continue
        title = tree.find_title(nid) or ""
        if kind in ("MultiRealization", "MultiRealizationTimeSeries"):
            pt = tree.find_attribute_value(nid, "propTitle")
            if pt:
                title = pt
        if make_valid_vtk_name(title) != sanitized:
            continue
        # MR / TimeSeries: pull the embedded propKind attribute.
        if kind in ("MultiRealization", "MultiRealizationTimeSeries", "TimeSeries"):
            pk = tree.find_attribute_value(nid, "propKind") or ""
            return _normalise_kind(pk)
        return _normalise_kind(kind)
    return "Continuous"


def _normalise_kind(kind_str):
    """Map a `propKind` / type string to one of the three threshold
    UI kinds we dispatch on. Anything unrecognised → Continuous."""
    if not kind_str:
        return "Continuous"
    s = kind_str.lower()
    if "categorical" in s:
        return "Categorical"
    if "discrete" in s:
        return "Discrete"
    return "Continuous"


def _scan_unique_values(source_proxy, array_name, assoc):
    """Iterate the source's CellData or PointData array and collect
    the sorted set of distinct values. Used by Discrete / Categorical
    entries to populate the slider's ticks.

    Returns an empty list on failure (no array, no client-side
    object) — the caller demotes to Continuous in that case."""
    if source_proxy is None or not array_name:
        return []
    try:
        client = source_proxy.GetClientSideObject()
        out = client.GetOutputDataObject(0)
    except Exception:
        return []
    inner = _drill_inner_partition(out)
    if inner is None:
        return []
    store = None
    if assoc == "POINTS" and hasattr(inner, "GetPointData"):
        store = inner.GetPointData()
    elif hasattr(inner, "GetCellData"):
        store = inner.GetCellData()
    if store is None:
        return []
    arr = store.GetArray(array_name)
    if arr is None:
        return []
    seen = set()
    n = arr.GetNumberOfTuples()
    for i in range(n):
        try:
            v = arr.GetTuple1(i)
        except Exception:
            continue
        # Skip NaN — they don't belong in a discrete value set.
        if v != v:  # NaN-ne-NaN
            continue
        seen.add(float(v))
        if len(seen) > _MAX_DISCRETE_UNIQUES:
            return []  # Too many uniques → caller demotes to Continuous
    out = sorted(seen)
    # Normalise integer-valued floats to int when round-trip is exact —
    # makes the UI labels cleaner ("3" vs "3.0").
    return [int(v) if float(v).is_integer() else v for v in out]


def _drill_inner_partition(vtk_out):
    """Same shape as `activator._drill_to_inner`. Duplicated here to
    keep the dependency graph tidy."""
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


def _read_lut_annotations(array_name):
    """Read the `Annotations` property of the LUT bound to
    `array_name` and return a `{value: label}` dict.

    The CategoricalColorEditor populates this on first activation of
    a Discrete / Categorical property. Returns an empty dict when
    the LUT has no annotations yet — the threshold UI then falls
    back to `str(value)` labels."""
    if not array_name:
        return {}
    try:
        from paraview import simple as pvsimple
        lut = pvsimple.GetColorTransferFunction(array_name)
        if lut is None or lut.SMProxy is None:
            return {}
        prop = lut.SMProxy.GetProperty("Annotations")
        if prop is None:
            return {}
        n = prop.GetNumberOfElements()
        out = {}
        for i in range(0, n - 1, 2):
            try:
                val_str = prop.GetElement(i)
                label = prop.GetElement(i + 1)
                v = float(val_str)
                key = int(v) if v.is_integer() else v
                out[key] = str(label)
            except (ValueError, TypeError):
                continue
        return out
    except Exception:
        return {}


class ExtractBlockRepresentation:
    """One non-IjkGrid representation backed by an ExtractBlock filter on
    the FESPP collector, plus its threshold chain.

    DEPRECATED: per-(rep, view) slice / clip / threshold ownership lives on
    `RepInScene` (anchored on the per-view `EnergisticsExtractor` chained on
    `vtkEPCCollectorClone`). This class is kept solely as a fallback when the
    plugin DLL pre-dates `vtkEPCCollectorClone` (so `ViewScene._create_clone`
    falls back to the shared collector source), and as a back-compat target
    for the `SourceRegistry` compat shims. The slice/clip/threshold methods
    emit a single `[DEPRECATED]` log line on first use so any remaining caller
    is identifiable."""

    def __init__(self, collector, tree, rep_path: str):
        self._collector = collector
        self._tree = tree
        self._rep_path = rep_path
        self._source = None  # set by _create_source()
        self._chain: list = []
        # Plane slice / clip. Lazily bound after `_create_source` succeeds so
        # the ExtractBlock proxy can be passed as upstream.
        self._slice = None
        self._clip = None
        if not self._create_source():
            # Caller checks `self.source is None` and discards a half-built
            # instance.
            return

    # ------------------------------------------------------------------
    # Public accessors

    @property
    def rep_path(self) -> str:
        return self._rep_path

    @property
    def source(self):
        """The ExtractBlock proxy. None when creation failed."""
        return self._source

    @property
    def chain(self):
        """Live list of ChainEntry. Mutate via add_threshold etc."""
        return self._chain

    # ------------------------------------------------------------------
    # Source lifecycle

    def _create_source(self) -> bool:
        """Create the per-rep `EnergisticsExtractor` chained on the collector
        source.

        Built via `_create_plugin_filter_proxy` (not the collector's
        `ExtractRepPath` C++ command): its register-direct fallback
        (`spm->NewProxy + spm->RegisterProxy`) publishes the proxy reliably
        on every call, including re-selecting a `rep_path` previously released
        via `pvsimple.Delete`. See PARAVIEW.md "LoadPlugin doesn't always
        refresh pvsimple namespace"."""
        from fespp_on_trame.app.core.sources.representation import (
            _create_plugin_filter_proxy,
        )

        collector_src = self._collector.get_source()
        # Match the C++-side `rep_<rep_path-with-_>` naming so code that
        # references that name still resolves.
        reg_name = "rep" + self._rep_path.replace("/", "_")
        ext = _create_plugin_filter_proxy(
            proxy_class="EnergisticsExtractor",
            registration_name=reg_name,
            inputs={"Input": collector_src},
        )
        if ext is None:
            return False
        vtkSMPropertyHelper(ext.SMProxy, "ExtractPath").Set(self._rep_path)
        ext.SMProxy.UpdateVTKObjects()
        try:
            ext.UpdatePipelineInformation()
        except Exception:
            pass
        self._source = ext
        src = ext

        view = pvsimple.GetActiveView()
        if view is not None:
            rep = pvsimple.GetRepresentation(proxy=src, view=view)
            if rep is not None:
                rep.Representation = state.representation_active or "Surface"
                zs = self._current_z_scale()
                rep.Scale = [1.0, 1.0, zs]
                _apply_default_tint(rep, (state.solid_color_by_rep or {}).get(self._rep_path))
            pvsimple.Show(proxy=src, view=view)
        return True

    def delete(self):
        """Tear down: drop the slice + clip + chain (children-first)
        then hide and delete the ExtractBlock proxy. Idempotent."""
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
        src = self._source
        self._source = None
        if src is None:
            return
        try:
            view = pvsimple.GetActiveView()
            if view is not None:
                pvsimple.Hide(proxy=src, view=view)
            pvsimple.Delete(src)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Slice plane (MVP — single axis-aligned plane per rep)

    def _ensure_slice(self):
        """Lazily build a `SlicePlane` once the rep's source exists.
        Called by the public slice_state / slice_set entry points."""
        if self._slice is not None or self._source is None:
            return
        from fespp_on_trame.app.core.sources.slice_plane import SlicePlane
        self._slice = SlicePlane(self._rep_path, self._source, state)

    def slice_state(self) -> dict:
        """Slice descriptor (enabled, axis, offset, bounds) for the UI panel.
        Always returns a dict, even pre-slice: the UI reads bounds to seed the
        range slider. DEPRECATED: superseded by `RepInScene.slice_state()`."""
        _warn_deprecated("ExtractBlockRepresentation.slice_state")
        self._ensure_slice()
        if self._slice is None:
            return {
                "enabled": False, "axis": "X", "offset": 0.0,
                "bounds": [0.0, 1.0, 0.0, 1.0, 0.0, 1.0],
            }
        return self._slice.to_dict()

    def slice_set(self, enabled=None, axis=None, offset=None):
        """Patch the plane params and re-render. Flipping `enabled` re-runs the
        chain-visibility resolver so the rep source / chain tips are hidden
        (slice replaces them) or restored.
        DEPRECATED: superseded by `RepInScene.slice_set()`."""
        _warn_deprecated("ExtractBlockRepresentation.slice_set")
        self._ensure_slice()
        if self._slice is None:
            return
        was_enabled = self._slice.enabled
        self._slice.set(enabled=enabled, axis=axis, offset=offset)
        if self._slice.enabled != was_enabled:
            self._refresh_chain_visibility()

    # ------------------------------------------------------------------
    # Clip plane (MVP — single plane per rep)

    def _ensure_clip(self):
        if self._clip is not None or self._source is None:
            return
        from fespp_on_trame.app.core.sources.clip_plane import ClipPlane
        self._clip = ClipPlane(self._rep_path, self._source, state)

    def clip_state(self) -> dict:
        """DEPRECATED: superseded by `RepInScene.clip_state()` (per-view)."""
        _warn_deprecated("ExtractBlockRepresentation.clip_state")
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
        """Patch the clip params and re-render. Flipping `enabled` re-runs the
        visibility resolver so the rep source / chain tip is replaced by the
        clip's output (or restored).
        DEPRECATED: superseded by `RepInScene.clip_set()`."""
        _warn_deprecated("ExtractBlockRepresentation.clip_set")
        self._ensure_clip()
        if self._clip is None:
            return
        was_enabled = self._clip.enabled
        self._clip.set(enabled=enabled, axis=axis, offset=offset,
                       inside_out=inside_out)
        if self._clip.enabled != was_enabled:
            self._refresh_chain_visibility()

    def clip_output(self):
        """The Clip filter proxy when one exists — exposed so the
        ColorBy fan-out (`source_resolver.color_sources_for_rep_path`)
        can refresh the clip's display whenever the user picks a new
        property. Without this the clip stays coloured by whatever
        array was active when the clip was created."""
        return self._clip.output if self._clip is not None else None

    def refresh_planes_after_property_change(self):
        """Re-apply slice / clip if enabled, then re-assert the rep
        hide. ColorBy fan-out updates the clip's display via
        `clip_output()`, but it doesn't re-run our visibility
        resolver — so this hook does both."""
        if self._slice is not None and self._slice.enabled:
            self._slice.set()
        if self._clip is not None and self._clip.enabled:
            self._clip.set()
        if ((self._slice is not None and self._slice.enabled)
                or (self._clip is not None and self._clip.enabled)):
            self._refresh_chain_visibility()

    def _delete_chain(self):
        view = pvsimple.GetActiveView()
        # Children-first deletion to keep PV happy (no dangling Input).
        for entry in reversed(self._chain):
            try:
                if view is not None:
                    pvsimple.Hide(proxy=entry.proxy, view=view)
            except Exception:
                pass
            try:
                pvsimple.Delete(entry.proxy)
            except Exception:
                pass
        self._chain = []

    # ------------------------------------------------------------------
    # Array introspection

    def available_arrays(self):
        """Return [(assoc, name), ...] for the rep's data arrays."""
        return arrays_from_source(self._source)

    def array_data_range(self, array_name: str):
        return array_range_from_source(self._source, array_name)

    def _resolve_assoc(self, array_name: str):
        return resolve_assoc(self._source, array_name)

    # ------------------------------------------------------------------
    # Threshold chain — public API

    def get_chain(self):
        """Read-only view of the chain (list of dicts) for the UI."""
        return [e.to_dict() for e in self._chain]

    def add_threshold(self, parent_name, array: str):
        """Create a new threshold node attached under `parent_name` (or under
        the rep's source if None). Returns the new node's name, or None on
        failure. DEPRECATED: superseded by `RepInScene.add_threshold()`."""
        _warn_deprecated("ExtractBlockRepresentation.add_threshold")
        if self._source is None or not array:
            return None
        if parent_name is not None and not any(e.name == parent_name for e in self._chain):
            return None
        assoc = self._resolve_assoc(array)
        if not assoc:
            return None

        rng = self.array_data_range(array) or (0.0, 1.0)
        rep_token = _sanitize(self._rep_path)
        if parent_name is None:
            base_name = f"thr_{rep_token}_{_sanitize(array)}"
        else:
            base_name = f"{parent_name}_{_sanitize(array)}"

        # Multiple thresholds on the same array under the same parent
        # are valid — their outputs render in parallel (UNION of the
        # ranges), which is the only way to display two disjoint
        # intervals of the same property. The chain entry name is the
        # PV registration name, so we have to suffix duplicates.
        existing_names = {e.name for e in self._chain}
        if base_name in existing_names:
            suffix = 2
            while f"{base_name}_{suffix}" in existing_names:
                suffix += 1
            base_name = f"{base_name}_{suffix}"

        # Effective input = parent's effective input (parent.proxy if
        # parent is visible, else walk up).
        upstream = self._effective_input_for_parent(parent_name)
        try:
            proxy = pvsimple.Threshold(
                registrationName=base_name,
                Input=upstream,
            )
            proxy.Scalars = [assoc, array]
            proxy.LowerThreshold = float(rng[0])
            proxy.UpperThreshold = float(rng[1])
            proxy.UpdatePipeline()
        except Exception as e:
            return None

        entry = ChainEntry(
            name=base_name,
            parent_name=parent_name,
            array=array,
            assoc=assoc,
            proxy=proxy,
            visible=True,
            low=float(rng[0]),
            high=float(rng[1]),
            data_range=(float(rng[0]), float(rng[1])),
        )
        self._chain.append(entry)

        # Inherit display props from upstream so the chain proxy mirrors its
        # parent visually (color array + LUT in property-color mode,
        # Diffuse/Ambient + Opacity in SolidColor mode) from the moment it
        # appears. Legacy path → the active view.
        inherit_display(upstream, proxy, pvsimple.GetActiveView())

        self._refresh_chain_visibility()
        return base_name

    def delete_threshold(self, name: str):
        """Delete the named node, rewiring its children onto the
        deleted node's parent (transparent "remove from chain").

        DEPRECATED: superseded by `RepInScene.delete_threshold()` (per-view)."""
        _warn_deprecated("ExtractBlockRepresentation.delete_threshold")
        idx = next((i for i, e in enumerate(self._chain) if e.name == name), -1)
        if idx < 0:
            return False
        target = self._chain[idx]
        # Children of `target` adopt target.parent_name as new logical parent.
        for e in self._chain:
            if e.parent_name == name:
                e.parent_name = target.parent_name
        self._chain.pop(idx)
        view = pvsimple.GetActiveView()
        try:
            if view is not None:
                pvsimple.Hide(proxy=target.proxy, view=view)
        except Exception:
            pass
        try:
            pvsimple.Delete(target.proxy)
        except Exception:
            pass
        self._refresh_chain_visibility()
        return True

    def set_range(self, name: str, low: float, high: float):
        """DEPRECATED: superseded by `RepInScene.set_range()` (per-view)."""
        _warn_deprecated("ExtractBlockRepresentation.set_range")
        for e in self._chain:
            if e.name == name:
                e.low = float(low)
                e.high = float(high)
                try:
                    e.proxy.LowerThreshold = e.low
                    e.proxy.UpperThreshold = e.high
                    e.proxy.UpdatePipeline()
                except Exception as exc:
                    pass
                return

    def set_visible(self, name: str, visible: bool):
        """DEPRECATED: superseded by `RepInScene.set_visible()` (per-view)."""
        _warn_deprecated("ExtractBlockRepresentation.set_visible")
        for e in self._chain:
            if e.name == name:
                e.visible = bool(visible)
                break
        else:
            return
        self._refresh_chain_visibility()

    def all_visible_thresholds(self):
        """Visible threshold proxies in chain order — used by the
        engine to know what to render in place of the rep source."""
        return [e.proxy for e in self._chain if e.visible]

    def all_chain_proxies(self):
        """Every threshold proxy in the chain (visible or not) — used
        for representation propagation, z-scale, ColorBy fan-out."""
        return [e.proxy for e in self._chain]

    def deepest_visible_threshold(self):
        """Deepest visible chain leaf, or None if no entry is visible."""
        visible = self.all_visible_thresholds()
        return visible[-1] if visible else None

    # ------------------------------------------------------------------
    # Chain plumbing

    def _entry_by_name(self, name):
        return threshold_chain.entry_by_name(self._chain, name)

    def _effective_input_for_parent(self, parent_name):
        """Resolve the upstream proxy a new/refreshed child should read
        from. parent_name=None → rep source. Otherwise walk up the chain
        skipping hidden ancestors. Graph logic shared via threshold_chain;
        the ROOT here is the rep source."""
        return threshold_chain.effective_input_for_parent(
            self._chain, parent_name, self._source)

    def _has_visible_descendant(self, name: str):
        return threshold_chain.has_visible_descendant(self._chain, name)

    def _refresh_chain_visibility(self):
        """Recompute Input wiring + display.Visibility for every node in the
        chain, then re-assert the rep source. Legacy policy → the ACTIVE view,
        the GLOBAL rep-hidden bucket, and `self._source` as both the chain head
        and the primary to hide/show. Delegates to
        threshold_chain.refresh_chain_visibility (shared with RepInScene)."""
        rep_hidden = (
            self._rep_path in (state.ui_hidden_rep_paths or [])
            or (self._slice is not None and self._slice.enabled)
            or (self._clip is not None and self._clip.enabled)
        )
        threshold_chain.refresh_chain_visibility(
            self._chain, pvsimple.GetActiveView(), self._source, self._source,
            rep_hidden,
        )

    # ------------------------------------------------------------------
    # Display helpers (z-scale, representation type)

    def _current_z_scale(self) -> float:
        try:
            return float(getattr(state, "ui_scale_z", 1.0) or 1.0)
        except (TypeError, ValueError):
            return 1.0

    def apply_z_scale(self, zscale: float):
        view = pvsimple.GetActiveView()
        if view is None or self._source is None:
            return
        for proxy in [self._source] + [e.proxy for e in self._chain]:
            rep = pvsimple.GetRepresentation(proxy=proxy, view=view)
            if rep is not None:
                rep.Scale = [1.0, 1.0, float(zscale)]

    def apply_representation(self, representation_type: str):
        view = pvsimple.GetActiveView()
        if view is None or not representation_type or self._source is None:
            return
        for proxy in [self._source] + [e.proxy for e in self._chain]:
            rep = pvsimple.GetRepresentation(proxy=proxy, view=view)
            if rep is None:
                continue
            try:
                rep.Representation = representation_type
            except AttributeError:
                pass
