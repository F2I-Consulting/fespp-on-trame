"""Per-rep data source for non-IjkGrid representations.

One `ExtractBlockRepresentation` instance per loaded RESQML rep
(UnstructuredGrid, Wellbore, Trajectory, Grid2d, PointSet, Polyline,
PolylineSet, TriangulatedSet, …). Each instance owns:

  - a single `ExtractBlock` proxy created via the collector's
    `ExtractRepPath` / `ExtractedRepProducerName` properties (this
    is the C++ "WithoutCopy" semantics: ShallowCopy in RequestData,
    no real data duplication);
  - an ordered list of `ChainEntry` describing a deletable
    threshold chain. Each entry has its own Threshold proxy chained
    onto its parent (or onto the rep source if the parent is None /
    hidden).

Visibility rules:
  - An entry is shown iff `entry.visible` AND it has no visible
    descendant (otherwise the descendant subsumes the entry's
    rendered contribution).
  - The rep source is hidden when at least one chain tip is shown,
    or when the user toggled the rep's eye off
    (`state.ui_hidden_rep_paths`).

The class is independent of `SourceRegistry` (the manager in
`source_registry.py`) — that one holds a dict of instances and
forwards the per-rep calls."""
from trame.app import get_server
from paraview import simple as pvsimple
from paraview.servermanager import vtkSMPropertyHelper

from fespp_on_trame.app.core.sources.representation import (
    _sanitize,
    _find_registered_proxy,
    _apply_default_tint,
)


server = get_server()
state = server.state


class ChainEntry:
    """One node in an `ExtractBlockRepresentation`'s threshold chain.

    `parent_name` is None when the parent is the rep's source (root
    of the chain); otherwise it points to another entry by name.
    `proxy.Input` reflects the *effective* input — when an ancestor
    is hidden, the proxy is dynamically rewired to skip it. The
    logical parent (`parent_name`) stays immutable for the entry's
    lifetime."""

    __slots__ = ("name", "parent_name", "array", "assoc", "proxy",
                 "visible", "low", "high", "data_range")

    def __init__(self, name, parent_name, array, assoc, proxy,
                 visible, low, high, data_range):
        self.name = name
        self.parent_name = parent_name
        self.array = array
        self.assoc = assoc
        self.proxy = proxy
        self.visible = visible
        self.low = low
        self.high = high
        self.data_range = data_range

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


class ExtractBlockRepresentation:
    """One non-IjkGrid representation backed by an ExtractBlock
    filter on the FESPP collector, plus its threshold chain."""

    def __init__(self, collector, tree, rep_path: str):
        self._collector = collector
        self._tree = tree
        self._rep_path = rep_path
        self._source = None  # set by _create_source()
        self._chain: list = []
        if not self._create_source():
            # Caller (SourceRegistry.get_or_create_extract_block) checks `self.source is None`
            # and discards a half-built instance.
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
        """Create the ExtractBlock proxy via the collector's
        ExtractRepPath property. ExtractRepPath is a string proxy
        property whose command runs the C++ ExtractRepWithoutCopy
        logic and stores the resulting producer's registration name;
        UpdatePropertyInformation refreshes the info-only
        ExtractedRepProducerName so we can read it back."""
        coll_proxy = self._collector.get_source().SMProxy
        vtkSMPropertyHelper(coll_proxy, "ExtractRepPath").Set(self._rep_path)
        coll_proxy.UpdateVTKObjects()
        coll_proxy.UpdatePropertyInformation()
        reg_name = vtkSMPropertyHelper(coll_proxy, "ExtractedRepProducerName").GetAsString()
        if not reg_name:
            return False
        src = _find_registered_proxy(reg_name)
        if src is None:
            return False
        self._source = src

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
        """Tear down: drop the chain (children-first) then hide and
        delete the ExtractBlock proxy. Idempotent."""
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
        src = self._source
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

    def array_data_range(self, array_name: str):
        src = self._source
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

    def _resolve_assoc(self, array_name: str):
        for a, n in self.available_arrays():
            if n == array_name:
                return a
        return None

    # ------------------------------------------------------------------
    # Threshold chain — public API

    def get_chain(self):
        """Read-only view of the chain (list of dicts) for the UI."""
        return [e.to_dict() for e in self._chain]

    def add_threshold(self, parent_name, array: str):
        """Create a new threshold node attached under `parent_name`
        (or under the rep's source if None). Returns the new node's
        name, or None on failure."""
        if self._source is None or not array:
            return None
        if parent_name is not None and not any(e.name == parent_name for e in self._chain):
            print(f"[WARNING] add_threshold: unknown parent {parent_name!r}")
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
            print(f"[WARNING] Threshold creation for {self._rep_path}/{array}: {e}")
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

        # Inherit display props from upstream so the chain proxy
        # mirrors its parent visually (color array + LUT in
        # property-color mode, DiffuseColor + Opacity in SolidColor
        # mode) from the moment it appears.
        view = pvsimple.GetActiveView()
        if view is not None:
            try:
                src_disp = pvsimple.GetDisplayProperties(upstream, view=view)
                thr_disp = pvsimple.GetRepresentation(proxy=proxy, view=view)
                if src_disp is not None and thr_disp is not None:
                    for attr in (
                        "Representation", "Scale", "ColorArrayName", "LookupTable",
                        "DiffuseColor", "AmbientColor", "Opacity",
                    ):
                        try:
                            val = getattr(src_disp, attr)
                            if attr in ("Scale", "ColorArrayName", "DiffuseColor", "AmbientColor"):
                                val = list(val)
                            setattr(thr_disp, attr, val)
                        except Exception:
                            pass
            except Exception:
                pass

        self._refresh_chain_visibility()
        return base_name

    def delete_threshold(self, name: str):
        """Delete the named node, rewiring its children onto the
        deleted node's parent (transparent "remove from chain")."""
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
        for e in self._chain:
            if e.name == name:
                e.low = float(low)
                e.high = float(high)
                try:
                    e.proxy.LowerThreshold = e.low
                    e.proxy.UpperThreshold = e.high
                    e.proxy.UpdatePipeline()
                except Exception as exc:
                    print(f"[WARNING] set_range({name}): {exc}")
                return

    def set_visible(self, name: str, visible: bool):
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
        for e in self._chain:
            if e.name == name:
                return e
        return None

    def _effective_input_for_parent(self, parent_name):
        """Resolve the upstream proxy a new/refreshed child should
        read from. parent_name=None → rep source. Otherwise walk up
        the chain skipping hidden ancestors."""
        if parent_name is None:
            return self._source
        cursor = self._entry_by_name(parent_name)
        while cursor is not None and not cursor.visible:
            cursor = self._entry_by_name(cursor.parent_name)
        if cursor is None:
            return self._source
        return cursor.proxy

    def _has_visible_descendant(self, name: str):
        """True iff at least one entry transitively rooted at `name`
        (excluding name itself) is visible."""
        # Direct children where parent_name == name:
        direct = [e for e in self._chain if e.parent_name == name]
        for child in direct:
            if child.visible:
                return True
            if self._has_visible_descendant(child.name):
                return True
        return False

    def _refresh_chain_visibility(self):
        """Recompute Input wiring + display.Visibility for every node
        in the chain. Called after add/delete/set_visible.

        Display rule: an entry is shown iff entry.visible AND it has
        no visible descendant (otherwise the descendant subsumes the
        entry's contribution to the rendered scene). The rep source
        is hidden when at least one chain entry is shown."""
        view = pvsimple.GetActiveView()
        rep_hidden_by_user = self._rep_path in (state.ui_hidden_rep_paths or [])

        any_shown = False
        for entry in self._chain:
            upstream = self._effective_input_for_parent(entry.parent_name)
            try:
                if entry.proxy.Input is not upstream:
                    entry.proxy.Input = upstream
                    entry.proxy.UpdatePipeline()
            except Exception as exc:
                print(f"[WARNING] rewire {entry.name}: {exc}")
            if view is None:
                continue
            try:
                tip = entry.visible and not self._has_visible_descendant(entry.name)
                show = tip and not rep_hidden_by_user
                if show:
                    pvsimple.Show(proxy=entry.proxy, view=view)
                    any_shown = True
                else:
                    pvsimple.Hide(proxy=entry.proxy, view=view)
            except Exception:
                pass

        # Show/hide the rep source: hidden when a chain tip is shown,
        # or when the user barred the rep eye; fully shown otherwise.
        if view is not None and self._source is not None:
            try:
                if rep_hidden_by_user or any_shown:
                    pvsimple.Hide(proxy=self._source, view=view)
                else:
                    pvsimple.Show(proxy=self._source, view=view)
            except Exception:
                pass

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
