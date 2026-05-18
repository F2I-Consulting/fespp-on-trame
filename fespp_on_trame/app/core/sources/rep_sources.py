"""Per-representation ParaView sources via the EnergisticsExtractor
filter pattern.

Each non-IjkGrid resqml representation is materialised through an
EnergisticsExtractor filter chained on the FESPP collector (registered
in the "filters" group). The filter outputs a single-piece dataset of
the partition's actual VTK type (vtkPolyData / vtkUnstructuredGrid /
vtkExplicitStructuredGrid) and does a ShallowCopy in RequestData — no
real data duplication. Standard VTK pipeline propagation handles
upstream changes (selector add, realization swap, property
addDataArray) automatically.

This is the C++ "WithoutCopy" semantics, exposed programmatically via
the ExtractRepPath / ExtractedRepProducerName proxy properties on
vtkEPCCollector.

Threshold pipeline (chained, deletable):
  Each rep owns an *ordered list* of Threshold proxies forming a
  parent-child chain. Identity = ParaView registration name
  ``thr_<rep_sanitized>_<array1>[_<array2>...]``. The chain is stored
  in `_chains[rep_path]` as a list of ChainEntry. Visibility toggling
  on a node re-parents its children to the node's *current effective
  input* — hidden ancestors are skipped, so a child can be displayed
  "complete" (without the upstream filter applied) while its parent
  stays in the chain definition.
"""
import re

from trame.app import get_server
from paraview import simple as pvsimple
from paraview import servermanager as _sm
from paraview.servermanager import vtkSMPropertyHelper

server = get_server()
state = server.state


_NAME_INVALID_RE = re.compile(r"[^\-.0-9A-Z_a-z]")


def _sanitize(name: str) -> str:
    return _NAME_INVALID_RE.sub("_", name or "")


def _find_registered_proxy(reg_name: str):
    """Resolve a registration name to a pvsimple proxy. The C++ side
    registers the per-rep extract filter in the "filters" group via
    RegisterPipelineProxy; pvsimple.FindSource only searches "sources",
    so we widen the lookup to "filters" first, then fall back to
    "sources" for compatibility with the legacy producer registration."""
    if not reg_name:
        return None
    pm = _sm.ProxyManager()
    for group in ("filters", "sources"):
        sm_proxy = pm.GetProxy(group, reg_name)
        if sm_proxy is not None:
            try:
                return _sm._getPyProxy(sm_proxy)
            except Exception:
                return sm_proxy
    return None


def _apply_default_tint(display, color_hex):
    """Set DiffuseColor + AmbientColor (and Opacity if alpha is given)
    on a display. Does NOT touch ColorArrayName, so a later ColorBy
    will take over while this stays the fallback when no array is
    bound."""
    if display is None or not color_hex:
        return
    h = color_hex.lstrip('#')
    if len(h) < 6:
        return
    try:
        r = int(h[0:2], 16) / 255.0
        g = int(h[2:4], 16) / 255.0
        b = int(h[4:6], 16) / 255.0
        display.DiffuseColor = [r, g, b]
        display.AmbientColor = [r, g, b]
        if len(h) >= 8:
            display.Opacity = int(h[6:8], 16) / 255.0
    except Exception:
        pass


class ChainEntry:
    """One node in a rep's threshold chain.

    `parent_name` is None when the parent is the rep's source (root of
    the chain); otherwise it points to another entry by name.
    `proxy.Input` reflects the *effective* input — when an ancestor is
    hidden, the proxy is dynamically rewired to skip it. The logical
    parent (parent_name) remains immutable for the entry's lifetime."""

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


class RepSources:
    """Maintains one per-rep ExtractBlock proxy for every non-IjkGrid
    representation that's currently loaded. Each proxy is created
    lazily via SetExtractRepPath on the collector and released when its
    rep_path leaves the selection.

    Each rep also owns a chained list of Threshold proxies (see
    `_chains`); chain nodes can be added, deleted, made visible, etc.
    independently."""

    def __init__(self, collector, tree):
        self._collector = collector
        self._tree = tree
        self._sources: dict = {}
        # Per-rep ordered chain of threshold entries.
        # rep_path -> list[ChainEntry]
        self._chains: dict = {}
        # Cache selector path → rep_path | None (None = IjkGrid or
        # unresolved). Tree walks are stable for a given assembly; this
        # avoids re-walking on every selector change when most
        # selectors haven't moved.
        self._selector_cache: dict = {}

    # ------------------------------------------------------------------
    # Source lifecycle

    def _rep_path_for(self, selector_path: str):
        """Return the representation block path for a selector, or None
        if the selector maps to an IjkGrid (handled by IjkGrid class)
        or to no representation at all."""
        if selector_path in self._selector_cache:
            return self._selector_cache[selector_path]
        node_id = self._tree.find_node_id(selector_path)
        if node_id is None:
            self._selector_cache[selector_path] = None
            return None
        rep_node_id = self._tree.find_representation_node(node_id)
        if rep_node_id is None:
            self._selector_cache[selector_path] = None
            return None
        if self._tree.find_type(rep_node_id) == "IjkGrid":
            self._selector_cache[selector_path] = None
            return None
        rp = self._tree.find_path(rep_node_id)
        self._selector_cache[selector_path] = rp
        return rp

    def get_or_create(self, rep_path: str):
        """Look up or create the ExtractBlock proxy for `rep_path`.
        ExtractRepPath is a string proxy property whose command runs
        the C++ ExtractRepWithoutCopy logic and stores the resulting
        producer's registration name; UpdatePropertyInformation
        refreshes the info-only ExtractedRepProducerName so we can
        read it back."""
        if not rep_path:
            return None
        src = self._sources.get(rep_path)
        if src is not None:
            return src
        coll_proxy = self._collector.get_source().SMProxy
        vtkSMPropertyHelper(coll_proxy, "ExtractRepPath").Set(rep_path)
        coll_proxy.UpdateVTKObjects()
        coll_proxy.UpdatePropertyInformation()
        reg_name = vtkSMPropertyHelper(coll_proxy, "ExtractedRepProducerName").GetAsString()
        if not reg_name:
            return None
        src = _find_registered_proxy(reg_name)
        if src is None:
            return None
        self._sources[rep_path] = src

        view = pvsimple.GetActiveView()
        if view is not None:
            rep = pvsimple.GetRepresentation(proxy=src, view=view)
            if rep is not None:
                rep.Representation = state.representation_active or "Surface"
                zs = self._current_z_scale()
                rep.Scale = [1.0, 1.0, zs]
                _apply_default_tint(rep, (state.solid_color_by_rep or {}).get(rep_path))
            pvsimple.Show(proxy=src, view=view)
        return src

    def release(self, rep_path: str):
        # Drop the threshold chain first so its Inputs don't dangle.
        self._delete_chain(rep_path)
        src = self._sources.pop(rep_path, None)
        if src is None:
            return
        try:
            view = pvsimple.GetActiveView()
            if view is not None:
                pvsimple.Hide(proxy=src, view=view)
            pvsimple.Delete(src)
        except Exception:
            pass

    def _delete_chain(self, rep_path: str):
        chain = self._chains.pop(rep_path, None)
        if not chain:
            return
        view = pvsimple.GetActiveView()
        # Children-first deletion to keep PV happy (no dangling Input).
        for entry in reversed(chain):
            try:
                if view is not None:
                    pvsimple.Hide(proxy=entry.proxy, view=view)
            except Exception:
                pass
            try:
                pvsimple.Delete(entry.proxy)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Array introspection

    def available_arrays(self, rep_path: str):
        """Return [(assoc, name), ...] for the rep's data arrays."""
        src = self._sources.get(rep_path)
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

    def array_data_range(self, rep_path: str, array_name: str):
        src = self._sources.get(rep_path)
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

    def _resolve_assoc(self, rep_path: str, array_name: str):
        for a, n in self.available_arrays(rep_path):
            if n == array_name:
                return a
        return None

    # ------------------------------------------------------------------
    # Threshold chain — public API

    def get_chain(self, rep_path: str):
        """Read-only view of the chain (list of dicts) for the UI."""
        return [e.to_dict() for e in self._chains.get(rep_path, [])]

    def chain_entries(self, rep_path: str):
        """Internal — returns the live ChainEntry list."""
        return self._chains.get(rep_path, [])

    def add_threshold(self, rep_path: str, parent_name, array: str):
        """Create a new threshold node attached under `parent_name`
        (or under the rep's source if None). Returns the new node's
        name, or None on failure."""
        src = self._sources.get(rep_path)
        if src is None or not array:
            return None
        chain = self._chains.setdefault(rep_path, [])
        if parent_name is not None and not any(e.name == parent_name for e in chain):
            print(f"[WARNING] add_threshold: unknown parent {parent_name!r}")
            return None
        assoc = self._resolve_assoc(rep_path, array)
        if not assoc:
            return None

        rng = self.array_data_range(rep_path, array) or (0.0, 1.0)
        rep_token = _sanitize(rep_path)
        if parent_name is None:
            base_name = f"thr_{rep_token}_{_sanitize(array)}"
        else:
            base_name = f"{parent_name}_{_sanitize(array)}"

        # Multiple thresholds on the same array under the same parent
        # are valid — their outputs render in parallel (UNION of the
        # ranges), which is the only way to display two disjoint
        # intervals of the same property. The chain entry name is the
        # PV registration name, so we have to suffix duplicates.
        existing_names = {e.name for e in chain}
        if base_name in existing_names:
            suffix = 2
            while f"{base_name}_{suffix}" in existing_names:
                suffix += 1
            base_name = f"{base_name}_{suffix}"

        # Effective input = parent's effective input (parent.proxy if
        # parent is visible, else walk up).
        upstream = self._effective_input_for_parent(rep_path, parent_name)
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
            print(f"[WARNING] Threshold creation for {rep_path}/{array}: {e}")
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
        chain.append(entry)

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

        self._refresh_chain_visibility(rep_path)
        return base_name

    def delete_threshold(self, rep_path: str, name: str):
        """Delete the named node, rewiring its children onto the
        deleted node's parent (transparent "remove from chain")."""
        chain = self._chains.get(rep_path)
        if not chain:
            return False
        idx = next((i for i, e in enumerate(chain) if e.name == name), -1)
        if idx < 0:
            return False
        target = chain[idx]
        # Children of `target` adopt target.parent_name as new logical parent.
        for e in chain:
            if e.parent_name == name:
                e.parent_name = target.parent_name
        chain.pop(idx)
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
        self._refresh_chain_visibility(rep_path)
        return True

    def set_range(self, rep_path: str, name: str, low: float, high: float):
        chain = self._chains.get(rep_path)
        if not chain:
            return
        for e in chain:
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

    def set_visible(self, rep_path: str, name: str, visible: bool):
        chain = self._chains.get(rep_path)
        if not chain:
            return
        for e in chain:
            if e.name == name:
                e.visible = bool(visible)
                break
        else:
            return
        self._refresh_chain_visibility(rep_path)

    def all_visible_thresholds(self, rep_path: str):
        """Visible threshold proxies in chain order — used by the
        engine to know what to render in place of the rep source."""
        chain = self._chains.get(rep_path) or []
        return [e.proxy for e in chain if e.visible]

    def all_chain_proxies(self, rep_path: str):
        """Every threshold proxy in the chain (visible or not) — used
        for representation propagation, z-scale, ColorBy fan-out."""
        return [e.proxy for e in (self._chains.get(rep_path) or [])]

    # Legacy compat shims (deprecated, kept for the engine during
    # migration). Prefer get_chain / add_threshold / set_range.
    def get_threshold(self, rep_path: str):
        # Returns the deepest visible chain leaf, or None.
        visible = self.all_visible_thresholds(rep_path)
        return visible[-1] if visible else None

    def all_thresholds(self):
        out = []
        for rep_path, chain in self._chains.items():
            for e in chain:
                out.append((rep_path, e.proxy))
        return out

    # ------------------------------------------------------------------
    # Chain plumbing

    def _entry_by_name(self, rep_path, name):
        for e in self._chains.get(rep_path, []) or []:
            if e.name == name:
                return e
        return None

    def _effective_input_for_parent(self, rep_path, parent_name):
        """Resolve the upstream proxy a new/refreshed child should read
        from. parent_name=None → rep source. Otherwise walk up the
        chain skipping hidden ancestors."""
        if parent_name is None:
            return self._sources.get(rep_path)
        cursor = self._entry_by_name(rep_path, parent_name)
        while cursor is not None and not cursor.visible:
            cursor = self._entry_by_name(rep_path, cursor.parent_name)
        if cursor is None:
            return self._sources.get(rep_path)
        return cursor.proxy

    def _has_visible_descendant(self, rep_path: str, name: str):
        """True iff at least one entry transitively rooted at `name`
        (excluding name itself) is visible."""
        chain = self._chains.get(rep_path) or []
        # BFS over the chain.
        descendants = []
        for e in chain:
            cursor = e
            while cursor is not None and cursor.parent_name != name:
                cursor = self._entry_by_name(rep_path, cursor.parent_name)
            if cursor is not None and e is not cursor:
                # `e` descends from `name` (parent path passes through it).
                descendants.append(e)
        # Direct children where parent_name == name:
        direct = [e for e in chain if e.parent_name == name]
        for child in direct:
            if child.visible:
                return True
            if self._has_visible_descendant(rep_path, child.name):
                return True
        return False

    def _refresh_chain_visibility(self, rep_path: str):
        """Recompute Input wiring + display.Visibility for every node
        in the chain. Called after add/delete/set_visible.

        Display rule: an entry is shown iff entry.visible AND it has no
        visible descendant (otherwise the descendant subsumes the
        entry's contribution to the rendered scene). The rep source is
        hidden when at least one chain entry is shown."""
        chain = self._chains.get(rep_path) or []
        view = pvsimple.GetActiveView()
        rep_src = self._sources.get(rep_path)
        rep_hidden_by_user = rep_path in (state.ui_hidden_rep_paths or [])

        any_shown = False
        for entry in chain:
            upstream = self._effective_input_for_parent(rep_path, entry.parent_name)
            try:
                if entry.proxy.Input is not upstream:
                    entry.proxy.Input = upstream
                    entry.proxy.UpdatePipeline()
            except Exception as exc:
                print(f"[WARNING] rewire {entry.name}: {exc}")
            if view is None:
                continue
            try:
                tip = entry.visible and not self._has_visible_descendant(rep_path, entry.name)
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
        if view is not None and rep_src is not None:
            try:
                if rep_hidden_by_user or any_shown:
                    pvsimple.Hide(proxy=rep_src, view=view)
                else:
                    pvsimple.Show(proxy=rep_src, view=view)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Sync / housekeeping

    def release_all(self):
        for path in list(self._sources.keys()):
            self.release(path)

    def sync(self, selectors):
        """Ensure one extracted source exists per non-IjkGrid rep path
        present in `selectors`; drop sources whose rep path is no
        longer selected."""
        wanted = set()
        for sel in selectors or []:
            rp = self._rep_path_for(sel)
            if rp:
                wanted.add(rp)
        current = set(self._sources.keys())
        for gone in current - wanted:
            self.release(gone)
        for new_path in wanted - current:
            self.get_or_create(new_path)

    def get(self, rep_path: str):
        return self._sources.get(rep_path)

    def all_sources(self):
        return list(self._sources.values())

    def items(self):
        return list(self._sources.items())

    def _current_z_scale(self) -> float:
        try:
            return float(getattr(state, "ui_scale_z", 1.0) or 1.0)
        except (TypeError, ValueError):
            return 1.0

    def apply_z_scale(self, zscale: float):
        view = pvsimple.GetActiveView()
        if view is None:
            return
        for src in self._sources.values():
            rep = pvsimple.GetRepresentation(proxy=src, view=view)
            if rep is not None:
                rep.Scale = [1.0, 1.0, float(zscale)]
        for chain in self._chains.values():
            for entry in chain:
                rep = pvsimple.GetRepresentation(proxy=entry.proxy, view=view)
                if rep is not None:
                    rep.Scale = [1.0, 1.0, float(zscale)]

    def apply_representation(self, representation_type: str):
        view = pvsimple.GetActiveView()
        if view is None or not representation_type:
            return
        proxies = list(self._sources.values())
        for chain in self._chains.values():
            proxies.extend(e.proxy for e in chain)
        for src in proxies:
            rep = pvsimple.GetRepresentation(proxy=src, view=view)
            if rep is not None:
                try:
                    rep.Representation = representation_type
                except AttributeError:
                    pass
