"""Unified per-representation registry.

One entry per loaded RESQML representation, regardless of its type:
  - `IjkGrid` — slicer + volume + threshold pipeline (in `ijkgrid.py`).
  - `ExtractBlockRepresentation` — ExtractBlock + threshold pipeline
    (in `extract_block.py`).

The engine talks to this registry through a single compat surface:

  registry.get(rep_path)               → source proxy (either type)
  registry.get_ijk_grid(rep_path)      → IjkGrid instance | None
  registry.get_extract_block(rep_path) → ExtractBlockRepresentation | None
  registry.add_threshold(rep_path, parent, array)   # [DEPRECATED]
  registry.delete_threshold(rep_path, name)         # [DEPRECATED]
  registry.set_range(rep_path, name, low, high)     # [DEPRECATED]
  registry.set_visible(rep_path, name, visible)     # [DEPRECATED]
  registry.get_chain(rep_path)                      # [DEPRECATED]
  registry.available_arrays(rep_path)
  registry.array_data_range(rep_path, array_name)
  registry.all_visible_thresholds(rep_path)
  registry.all_chain_proxies(rep_path)
  registry.get_threshold(rep_path)       # deepest visible
  registry.apply_z_scale(zscale)
  registry.apply_representation(rep_type)
  registry.sync(selectors, reservoir_select_node_ids)
  registry.release(rep_path)
  registry.release_all()

The DEPRECATED mutating shims are superseded by per-(rep, view) `RepInScene`
ownership via `scene_registry`; they remain reachable as a fallback when the
per-view pipeline isn't built yet (early boot / `vtkEPCCollectorClone`
unavailable). The read-side methods stay valid as data-layer accessors since
the per-view pipelines share the same EPCCollector and surface the same arrays.

Internally the registry keeps two dicts (one per concrete type) because an
IjkGrid's lifecycle is driven by a *property* node id (via `set_node_id`)
while an ExtractBlockRepresentation's is driven by a *rep path*. This
asymmetry is hidden from callers."""
from typing import Optional

from fespp_on_trame.app.core.sources.extract_block import ExtractBlockRepresentation
from fespp_on_trame.app.core.sources.ijkgrid import IjkGrid


class SourceRegistry:
    """Per-rep registry shared by the whole engine."""

    def __init__(self, collector, tree):
        self._collector = collector
        self._tree = tree
        # rep_path → ExtractBlockRepresentation
        self._extract_blocks: dict = {}
        # rep_path → IjkGrid
        self._ijk_grids: dict = {}
        # Cache selector path → rep_path | None (None = unresolved).
        # Tree walks are stable for a given assembly; this avoids
        # re-walking on every selector change when most selectors
        # haven't moved.
        self._selector_cache: dict = {}

    # ------------------------------------------------------------------
    # Selector → rep_path resolution

    def _rep_path_for(self, selector_path: str) -> Optional[str]:
        """Return the representation block path for a selector, or
        None when the selector doesn't map to a representation at
        all (e.g. unknown path). IjkGrid selectors ARE returned
        here — unlike the old RepSources implementation, this
        registry handles both types."""
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
        rp = self._tree.find_path(rep_node_id)
        self._selector_cache[selector_path] = rp
        return rp

    def _rep_type_for(self, rep_path: str) -> Optional[str]:
        """Lookup the node kind at `rep_path` (e.g. 'IjkGrid',
        'UnstructuredGrid', 'TriangulatedSet', …)."""
        rep_node_id = self._tree.find_node_id(rep_path)
        if rep_node_id is None:
            return None
        return self._tree.find_type(rep_node_id)

    # ------------------------------------------------------------------
    # Instance accessors

    def get_extract_block(self, rep_path: str) -> Optional[ExtractBlockRepresentation]:
        return self._extract_blocks.get(rep_path)

    def get_ijk_grid(self, rep_path: str) -> Optional[IjkGrid]:
        return self._ijk_grids.get(rep_path)

    def get_instance(self, rep_path: str):
        """Either type, or None. Callers that don't care about
        polymorphism use this; type-aware callers use the
        get_extract_block / get_ijk_grid pair."""
        return self._extract_blocks.get(rep_path) or self._ijk_grids.get(rep_path)

    def is_ijk_grid(self, rep_path: str) -> bool:
        return rep_path in self._ijk_grids

    # ------------------------------------------------------------------
    # Compat shims — public API that mirrors the legacy RepSources
    # surface. Each method finds the right instance and forwards.

    def get(self, rep_path: str):
        """The canonical upstream source proxy for this rep — the
        ExtractBlock filter for non-IjkGrid, the rep_data extractor
        for IjkGrid. Used by ColorBy fan-out / displays-for-rep."""
        eb = self._extract_blocks.get(rep_path)
        if eb is not None:
            return eb.source
        ijk = self._ijk_grids.get(rep_path)
        if ijk is not None:
            return ijk.source
        return None

    def all_sources(self):
        out = [r.source for r in self._extract_blocks.values() if r.source is not None]
        out.extend(g.source for g in self._ijk_grids.values() if g.source is not None)
        return out

    def items(self):
        """List of (rep_path, source_proxy) for every loaded rep."""
        out = [(p, r.source) for p, r in self._extract_blocks.items() if r.source is not None]
        out.extend((p, g.source) for p, g in self._ijk_grids.items() if g.source is not None)
        return out

    # Array introspection (per-rep)

    def available_arrays(self, rep_path: str):
        inst = self.get_instance(rep_path)
        return inst.available_arrays() if inst is not None else []

    def array_data_range(self, rep_path: str, array_name: str):
        inst = self.get_instance(rep_path)
        return inst.array_data_range(array_name) if inst is not None else None

    # Chain (per-rep)

    def get_chain(self, rep_path: str):
        """DEPRECATED: superseded by `RepInScene.get_chain()` (per-view).
        Reachable only via the threshold_dispatch fallback before
        scene_registry is ready."""
        from fespp_on_trame.app.core.sources.extract_block import _warn_deprecated
        _warn_deprecated("SourceRegistry.get_chain")
        inst = self.get_instance(rep_path)
        return inst.get_chain() if inst is not None else []

    def add_threshold(self, rep_path: str, parent_name, array: str):
        """DEPRECATED: superseded by per-view threshold ops on `RepInScene`."""
        from fespp_on_trame.app.core.sources.extract_block import _warn_deprecated
        _warn_deprecated("SourceRegistry.add_threshold")
        inst = self.get_instance(rep_path)
        return inst.add_threshold(parent_name, array) if inst is not None else None

    def delete_threshold(self, rep_path: str, name: str):
        """DEPRECATED: superseded by per-view threshold ops on `RepInScene`."""
        from fespp_on_trame.app.core.sources.extract_block import _warn_deprecated
        _warn_deprecated("SourceRegistry.delete_threshold")
        inst = self.get_instance(rep_path)
        return inst.delete_threshold(name) if inst is not None else False

    def set_range(self, rep_path: str, name: str, low: float, high: float):
        """DEPRECATED: superseded by per-view threshold ops on `RepInScene`."""
        from fespp_on_trame.app.core.sources.extract_block import _warn_deprecated
        _warn_deprecated("SourceRegistry.set_range")
        inst = self.get_instance(rep_path)
        if inst is not None:
            inst.set_range(name, low, high)

    def set_visible(self, rep_path: str, name: str, visible: bool):
        """DEPRECATED: superseded by per-view threshold ops on `RepInScene`."""
        from fespp_on_trame.app.core.sources.extract_block import _warn_deprecated
        _warn_deprecated("SourceRegistry.set_visible")
        inst = self.get_instance(rep_path)
        if inst is not None:
            inst.set_visible(name, visible)

    def all_visible_thresholds(self, rep_path: str):
        """ExtractBlockRepresentation only — IjkGrid threshold
        visibility is read per-upstream via the deepest-leaf logic
        inside IjkGrid itself; engine callers use
        `get_ijk_grid(...)._deepest_visible_leaf()` for that."""
        eb = self._extract_blocks.get(rep_path)
        return eb.all_visible_thresholds() if eb is not None else []

    def all_chain_proxies(self, rep_path: str):
        inst = self.get_instance(rep_path)
        if inst is None:
            return []
        # ExtractBlockRepresentation: list[Proxy]. IjkGrid: same name,
        # returns the proxies across every active upstream.
        if hasattr(inst, "all_chain_proxies"):
            return inst.all_chain_proxies()
        if hasattr(inst, "all_threshold_sources"):
            return inst.all_threshold_sources()
        return []

    def get_threshold(self, rep_path: str):
        """Deepest visible chain leaf (single proxy for ExtractBlock,
        None for IjkGrid since its leaf is per-upstream). Used by
        legacy color-resolver code that wants a *single* render target
        when the chain is active."""
        eb = self._extract_blocks.get(rep_path)
        return eb.deepest_visible_threshold() if eb is not None else None

    # Slice plane (per-rep) — DEPRECATED. Slice / clip ownership lives on
    # `RepInScene` (per (rep, view)); the slice/clip dispatchers route
    # through `SceneRegistry.get_rep(view, rep)`, so these shims are
    # unreachable from the engine flow. Kept as a safety net.

    def slice_state(self, rep_path: str) -> dict:
        """DEPRECATED: superseded by `RepInScene.slice_state()`."""
        from fespp_on_trame.app.core.sources.extract_block import _warn_deprecated
        _warn_deprecated("SourceRegistry.slice_state")
        inst = self.get_instance(rep_path)
        if inst is None or not hasattr(inst, "slice_state"):
            return {
                "enabled": False, "axis": "X", "offset": 0.0,
                "bounds": [0.0, 1.0, 0.0, 1.0, 0.0, 1.0],
            }
        return inst.slice_state()

    def slice_set(self, rep_path: str, enabled=None, axis=None, offset=None):
        """DEPRECATED: superseded by `RepInScene.slice_set()`."""
        from fespp_on_trame.app.core.sources.extract_block import _warn_deprecated
        _warn_deprecated("SourceRegistry.slice_set")
        inst = self.get_instance(rep_path)
        if inst is None or not hasattr(inst, "slice_set"):
            return
        inst.slice_set(enabled=enabled, axis=axis, offset=offset)

    # Clip plane (per-rep) — DEPRECATED, mirrors `slice_*`.

    def clip_state(self, rep_path: str) -> dict:
        """DEPRECATED: superseded by `RepInScene.clip_state()`."""
        from fespp_on_trame.app.core.sources.extract_block import _warn_deprecated
        _warn_deprecated("SourceRegistry.clip_state")
        inst = self.get_instance(rep_path)
        if inst is None or not hasattr(inst, "clip_state"):
            return {
                "enabled": False, "axis": "X", "offset": 0.0,
                "inside_out": False,
                "bounds": [0.0, 1.0, 0.0, 1.0, 0.0, 1.0],
            }
        return inst.clip_state()

    def clip_set(self, rep_path: str, enabled=None, axis=None,
                 offset=None, inside_out=None):
        """DEPRECATED: superseded by `RepInScene.clip_set()`."""
        from fespp_on_trame.app.core.sources.extract_block import _warn_deprecated
        _warn_deprecated("SourceRegistry.clip_set")
        inst = self.get_instance(rep_path)
        if inst is None or not hasattr(inst, "clip_set"):
            return
        inst.clip_set(enabled=enabled, axis=axis, offset=offset,
                      inside_out=inside_out)

    def all_thresholds(self):
        """Flat list of (rep_path, proxy) across every chain (both
        types)."""
        out = []
        for rep_path, eb in self._extract_blocks.items():
            for proxy in eb.all_chain_proxies():
                out.append((rep_path, proxy))
        for rep_path, ijk in self._ijk_grids.items():
            try:
                for proxy in ijk.all_threshold_sources():
                    out.append((rep_path, proxy))
            except Exception:
                pass
        return out

    # Cross-rep display updates

    def apply_z_scale(self, zscale: float):
        for eb in self._extract_blocks.values():
            eb.apply_z_scale(zscale)
        # IjkGrid z-scale is wired through the engine's
        # ui_scale_z_update handler (touches per-axis slicers +
        # volume crop independently); we don't double-apply it here.

    def apply_representation(self, representation_type: str):
        for eb in self._extract_blocks.values():
            eb.apply_representation(representation_type)
        # IjkGrid representation propagation is also handled at
        # engine level (touches rep_data + slicers + volume +
        # threshold proxies); skipped here for the same reason.

    # ------------------------------------------------------------------
    # Lifecycle

    def get_or_create_extract_block(self, rep_path: str) -> Optional[ExtractBlockRepresentation]:
        """Look up or create an ExtractBlockRepresentation for a
        non-IjkGrid rep_path. Returns None on failure."""
        if not rep_path:
            return None
        eb = self._extract_blocks.get(rep_path)
        if eb is None:
            eb = ExtractBlockRepresentation(self._collector, self._tree, rep_path)
            if eb.source is None:
                return None
            self._extract_blocks[rep_path] = eb
        return eb

    def ensure_ijk_grid(self, rep_path: str, prop_node_id) -> Optional[IjkGrid]:
        """Look up or create the IjkGrid for `rep_path`, then point
        it at `prop_node_id` (the property to colorise). Returns
        the IjkGrid instance, or None if creation failed."""
        if not rep_path:
            return None
        ijk = self._ijk_grids.get(rep_path)
        if ijk is None:
            ijk = IjkGrid(self._collector, self._tree)
            self._ijk_grids[rep_path] = ijk
        try:
            ijk.set_node_id(prop_node_id)
        except Exception as e:
            pass
        if ijk.source is None:
            # Creation failed at the collector level.
            self._ijk_grids.pop(rep_path, None)
            return None
        # Fan the property change to every per-view IjkGrid owned by scenes so
        # split views stay in step with the active property. Best-effort:
        # scene_registry may not be wired up yet during engine boot.
        try:
            from trame.app import get_server
            scene_reg = getattr(get_server().context, "scene_registry", None)
            if scene_reg is not None and hasattr(scene_reg, "refresh_per_view_ijk_for_rep"):
                scene_reg.refresh_per_view_ijk_for_rep(rep_path, prop_node_id)
        except Exception:
            pass
        return ijk

    def release(self, rep_path: str):
        eb = self._extract_blocks.pop(rep_path, None)
        if eb is not None:
            eb.delete()
            return
        ijk = self._ijk_grids.pop(rep_path, None)
        if ijk is not None:
            try:
                ijk.set_node_id(None)
            except Exception:
                pass

    def release_all(self):
        for path in list(self._extract_blocks.keys()):
            self.release(path)
        for path in list(self._ijk_grids.keys()):
            self.release(path)

    def sync(self, selectors, reservoir_select_node_ids):
        """Bring the registry in line with the current selection.

        `selectors` is the flat list of selector paths (from
        `state.fespp_data_selectors`) — drives the ExtractBlock side.

        `reservoir_select_node_ids` is the per-tab checked node list
        (`state.ui_select_node_reservoir`) — drives the IjkGrid side:
        for each unique IjkGrid ancestor in the list, we keep the
        first property node id as the "active" property to colorise.
        """
        # --- ExtractBlock side (non-IjkGrid reps) ---
        eb_wanted = set()
        for sel in selectors or []:
            rp = self._rep_path_for(sel)
            if rp is None:
                continue
            rep_type = self._rep_type_for(rp)
            if rep_type == "IjkGrid":
                continue
            eb_wanted.add(rp)
        eb_current = set(self._extract_blocks.keys())
        for gone in eb_current - eb_wanted:
            self.release(gone)
        for new_path in eb_wanted - eb_current:
            self.get_or_create_extract_block(new_path)

        # --- IjkGrid side ---
        # Walk the reservoir selection to find each unique IjkGrid +
        # its "first property node" (used as the colorise target).
        chosen_prop_for_grid: dict = {}  # rep_path -> prop_node_id
        for reservoir_node_id in reservoir_select_node_ids or []:
            ijk_id = self._tree.find_parent_node_id_with_type(reservoir_node_id, "IjkGrid")
            if ijk_id is None:
                continue
            ijk_rep_path = self._tree.find_path(ijk_id)
            if not ijk_rep_path:
                continue
            chosen_prop_for_grid.setdefault(ijk_rep_path, reservoir_node_id)
        # Fallback: derive IjkGrid targets from `selectors` directly so sync
        # stays self-sufficient when `state.ui_select_node_reservoir` hasn't
        # flushed yet on the same tick (the `fespp_data_selectors` change can
        # fire before the reservoir state var is observed). Without this the
        # IjkGrid branch sees an empty input and no-ops, leaving the rep
        # unbuilt.
        for sel in selectors or []:
            rp = self._rep_path_for(sel)
            if rp is None or self._rep_type_for(rp) != "IjkGrid":
                continue
            if rp in chosen_prop_for_grid:
                continue
            prop_node_id = self._tree.find_node_id(sel)
            if prop_node_id is not None:
                chosen_prop_for_grid[rp] = prop_node_id
        ijk_current = set(self._ijk_grids.keys())
        for gone in ijk_current - set(chosen_prop_for_grid.keys()):
            self.release(gone)
        for rep_path, prop_node_id in chosen_prop_for_grid.items():
            self.ensure_ijk_grid(rep_path, prop_node_id)

    def ijk_paths(self):
        """List of rep_paths currently loaded as IjkGrid."""
        return list(self._ijk_grids.keys())

    def extract_block_paths(self):
        """List of rep_paths currently loaded as ExtractBlockRepresentation."""
        return list(self._extract_blocks.keys())

    def all_paths(self):
        return self.extract_block_paths() + self.ijk_paths()

    def ijk_grids(self):
        """List of every loaded IjkGrid instance — for callers that
        need to iterate (z-scale, representation propagation, …)."""
        return list(self._ijk_grids.values())

    def extract_blocks(self):
        """List of every loaded ExtractBlockRepresentation instance."""
        return list(self._extract_blocks.values())
