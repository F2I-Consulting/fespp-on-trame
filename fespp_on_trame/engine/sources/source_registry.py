"""The data sources of the loaded representations, one per rep.

  - `IjkGrid` (in `ijkgrid.py`): the shared, data-only instance of an IJK
    grid — its extent, its rep_data extractor (the values the statistics
    read); a view's cut / filtered grid is its own GridIsolate;
  - `ExtractBlockRepresentation` (in `extract_block.py`): the extractor of
    any other rep.

  registry.get(rep_path)               → source proxy (either type)
  registry.get_ijk_grid(rep_path)      → IjkGrid instance | None
  registry.get_extract_block(rep_path) → ExtractBlockRepresentation | None
  registry.shared_source()             → the collector (the one PDC)
  registry.available_arrays(rep_path)
  registry.sync(selectors, reservoir_select_node_ids)
  registry.release(rep_path)

Nothing here is drawn: each view's composite is the one visible
representation (engine/blockscope). The threshold shims and display helpers
of the per-representation model went with it (overhaul, Q2 bis).

Internally the registry keeps two dicts (one per concrete type) because an
IjkGrid's lifecycle is driven by a *property* node id (via `set_node_id`)
while an ExtractBlockRepresentation's is driven by a *rep path*. This
asymmetry is hidden from callers."""
from typing import Optional

from fespp_on_trame.engine.sources.extract_block import ExtractBlockRepresentation
from fespp_on_trame.engine.sources.ijkgrid import IjkGrid


class ActiveSource:
    """The session's data source: the file reader (the EPC collector) and the
    store (the ETP source) TOGETHER, each with its own repository, behind
    the Collector duck-type the pipelines consume.

    `get_source()` is the collection as READ: the one reader that holds
    data, or the merge of both (engine/sources/merged_source) — one
    assembly, so every path the tree shows is a path of it, and an extractor
    chained on it never meets a selector its assembly does not hold (which
    crashes inside vtkRemotingServerManager). `get_display_source()` is the
    derived-arrays filter over it. What speaks to a READER goes to the one
    that holds the object: `push_selectors` here, the query channel in
    engine/repo_query (`stands_for`)."""

    def __init__(self, collector, etp_connector):
        self._collector = collector
        self._etp = etp_connector
        from fespp_on_trame.engine.derived_arrays import DerivedArrays
        from fespp_on_trame.engine.sources.merged_source import MergedSource
        self.derived = DerivedArrays()
        self.merged = MergedSource()

    @staticmethod
    def _assembly(reader):
        """The assembly of a reader's output as this process sees it, None
        before it has one."""
        try:
            out = reader.GetClientSideObject().GetOutputDataObject(0)
            return out.GetDataAssembly() if out is not None else None
        except Exception as exc:
            print(f"[fespp] sources: a reader's assembly not read ({exc!r})", flush=True)
            return None

    def _holds_data(self, reader):
        asm = self._assembly(reader)
        return asm is not None and asm.GetNumberOfChildren(0) > 0

    def readers(self):
        """The readers that hold data, the file reader first; the file
        reader alone while nothing is read. A store counts from its first
        dataspace on and past its disconnection: what was read of it stays
        in its repository, so it stays in the tree and in the views."""
        files = self._collector.get_source()
        out = [r for r in (files, self._etp.get_source()) if self._holds_data(r)]
        return out or [files]

    def store_paths(self, paths):
        """Those of the tree rows `paths` the store holds: reading one is a
        request to a server, where a file's is at hand. A path that is no
        row of a reader (a computed property's) is no one's."""
        store = self._etp.get_source()
        readers = self.readers()
        if not any(r is store for r in readers):
            return set()
        rows = [p for p in paths if p and p[0] == "/"]
        if len(readers) == 1:
            return set(rows)
        asm = self._assembly(store)
        return {p for p in rows if asm.GetFirstNodeByPath(p) > 0}

    def sync(self):
        """The source joins the readers that hold data NOW: called when a
        file is read, a store connected, a dataspace loaded."""
        readers = self.readers()
        proxy = self.merged.proxy(readers)
        if proxy is None:
            return
        changed = self.merged.set_inputs(readers)
        from fespp_on_trame.engine import repo_query
        repo_query.stands_for(proxy, readers)
        # a reader's output carries its assembly as soon as it lists a file
        # or a dataspace; the joined one is only made when the filter runs
        try:
            from paraview import simple as pvsimple
            proxy.UpdatePipeline(float(pvsimple.GetTimeKeeper().Time))
        except Exception as exc:
            print(f"[fespp] sources: the readers' collections not joined ({exc!r}; inputs changed: {changed})",
                  flush=True)

    def get_source(self):
        """The collection as read: what bounds, arrays' information, the
        assembly and the reader's questions are asked of."""
        if self.merged._proxy is None:
            self.sync()
        return self.merged._proxy or self._collector.get_source()

    def reader_of(self, path):
        """The reader that holds the tree row `path` — what an extractor of
        one object anchors on, with that reader's own means: the one whose
        assembly has the row, the first that holds data otherwise."""
        readers = self.readers()
        if len(readers) > 1:
            for reader in readers:
                asm = self._assembly(reader)
                if asm is not None and path and asm.GetFirstNodeByPath(path) > 0:
                    return reader
        return readers[0]

    def push_selectors(self, selectors):
        """What to read, said to each reader in its own paths: a reader is
        handed the selectors its assembly holds, never another's."""
        readers = self.readers()
        selectors = list(selectors or ())
        if len(readers) == 1:
            readers[0].SetPropertyWithName("Selectors", selectors)
            return
        for reader in readers:
            asm = self._assembly(reader)
            mine = [s for s in selectors if asm is not None and asm.GetFirstNodeByPath(s) > 0]
            reader.SetPropertyWithName("Selectors", mine)

    def get_display_source(self):
        """What displays, selections, picks and extracts chain on: the
        derived-arrays filter over the source (engine/derived_arrays), so
        computed properties are arrays of their grid's blocks. The source
        itself when the filter cannot be built."""
        src = self.get_source()
        known = len(self.derived.filters())
        pf = self.derived.proxy_for(src)
        if pf is not None and len(self.derived.filters()) != known:
            self.merged.keep_readers_time(pf)
        return pf or src

    def get_representation(self):
        from paraview import simple as pvsimple
        return pvsimple.GetRepresentation(proxy=self.get_source(), view=pvsimple.GetActiveView())


class SourceRegistry:
    """Per-rep registry shared by the whole engine."""

    def __init__(self, collector, tree):
        self._collector = collector
        # the session's source itself (ActiveSource): what a load speaks to
        self.provider = collector
        self._tree = tree
        # rep_path → ExtractBlockRepresentation
        self._extract_blocks: dict = {}
        # rep_path → IjkGrid
        self._ijk_grids: dict = {}
        # selector path -> rep_path, or None when unresolved. Tree walks
        # are stable for a given assembly, so a selector change does not
        # re-walk the selectors that did not move.
        self._selector_cache: dict = {}

    # ------------------------------------------------------------------
    # Selector → rep_path resolution

    def _rep_path_for(self, selector_path: str) -> Optional[str]:
        """Representation block path for a selector, or None when the
        selector does not map to a representation (e.g. unknown path).
        IjkGrid selectors resolve too: the registry handles both
        types."""
        if selector_path in self._selector_cache:
            return self._selector_cache[selector_path]
        from fespp_on_trame.engine import node_facts
        rp = node_facts.rep_path_for(self._tree, selector_path) or None
        self._selector_cache[selector_path] = rp
        return rp

    def _rep_type_for(self, rep_path: str) -> Optional[str]:
        """Node kind at `rep_path` (e.g. 'IjkGrid', 'UnstructuredGrid',
        'TriangulatedSet', …), or None when the path is unknown."""
        rep_node_id = self._tree.find_node_id(rep_path)
        if rep_node_id is None:
            return None
        return self._tree.find_type(rep_node_id)

    @staticmethod
    def _uses_ijk_pipeline(rep_type) -> bool:
        """True when `rep_type` (a node kind) maps to the IJK grid pipeline.
        Resolved via the ElementType strategy rather than a literal
        `rep_type == 'IjkGrid'` compare."""
        from fespp_on_trame.engine import element_type
        return element_type.for_kind(rep_type).is_ijk_grid()

    # ------------------------------------------------------------------
    # Instance accessors

    def get_extract_block(self, rep_path: str) -> Optional[ExtractBlockRepresentation]:
        return self._extract_blocks.get(rep_path)

    def get_ijk_grid(self, rep_path: str) -> Optional[IjkGrid]:
        return self._ijk_grids.get(rep_path)

    def get_instance(self, rep_path: str):
        """The rep's instance of either type, or None. Type-aware callers
        use the get_extract_block / get_ijk_grid pair instead."""
        return self._extract_blocks.get(rep_path) or self._ijk_grids.get(rep_path)

    # ------------------------------------------------------------------
    # Compatibility shims: each method finds the rep's instance (either
    # type) and forwards the call.

    def get(self, rep_path: str):
        """The canonical upstream source proxy for this rep: the per-rep
        extractor of a non-IjkGrid rep, the rep_data extractor of an
        IjkGrid. Used by the ColorBy fan-out and displays-for-rep."""
        eb = self._extract_blocks.get(rep_path)
        if eb is not None:
            return eb.source
        ijk = self._ijk_grids.get(rep_path)
        if ijk is not None:
            return ijk.source
        return None

    def shared_source(self):
        """The one SHARED source every rep is a block of: the EPC collector,
        or the ETP store when connected. Under BlockScope no per-rep extractor
        exists, so this is where a rep's arrays actually live."""
        try:
            return self._collector.get_source()
        except Exception:
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

    # Chain (per-rep)

    # Cross-rep display updates

        # IjkGrid z-scale goes through the view's set_zscale
        # handler (per-axis slicers and volume crop), so it is not
        # applied a second time here.

        # IjkGrid representation propagation is also handled at engine
        # level (rep_data, slicers, volume and threshold proxies), so it
        # is skipped here for the same reason.

    # ------------------------------------------------------------------
    # Lifecycle

    def get_or_create_extract_block(self, rep_path: str) -> Optional[ExtractBlockRepresentation]:
        """Look up or create the ExtractBlockRepresentation of a
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
            from fespp_on_trame.engine.etp_debug import etp_debug
            etp_debug(f"ensure_ijk_grid({rep_path}): set_node_id "
                      f"EXCEPTION {type(e).__name__}: {e}")
        if ijk.source is None:
            # Creation failed at the source level (e.g. extractor proxy
            # unavailable): say so in the ETP debug trace rather than
            # failing silently.
            from fespp_on_trame.engine.etp_debug import etp_debug
            etp_debug(f"ensure_ijk_grid({rep_path}): creation failed (source None)")
            self._ijk_grids.pop(rep_path, None)
            return None
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

    def sync(self, selectors, reservoir_select_node_ids):
        """Bring the registry in line with the current selection.

        `selectors` is the flat list of selector paths (from
        `state.fespp_data_selectors`); it drives the ExtractBlock side.

        `reservoir_select_node_ids` is the per-tab checked node list
        (`state.ui_select_node_reservoir`); it drives the IjkGrid side:
        for each IjkGrid it touches, the first checked property node is
        the "active" property to colorise, else the geometry rep itself.
        """
        # --- ExtractBlock side (non-IjkGrid reps) ---
        eb_wanted = set()
        for sel in selectors or []:
            rp = self._rep_path_for(sel)
            if rp is None:
                continue
            rep_type = self._rep_type_for(rp)
            if self._uses_ijk_pipeline(rep_type):
                continue
            eb_wanted.add(rp)
        eb_current = set(self._extract_blocks.keys())
        for gone in eb_current - eb_wanted:
            self.release(gone)
        for new_path in eb_wanted - eb_current:
            self.get_or_create_extract_block(new_path)

        # --- IjkGrid side ---
        # For each IjkGrid with a selection, pick the colorise target: a real
        # grid PROPERTY if one is checked, else the geometry rep itself
        # (geometry alone, no ColorBy). The geometry rep is a SIBLING of the
        # grid properties under a PropertiesFolder, not their ancestor, so the
        # owning grid is resolved via find_representation_node (which descends
        # the grid folder). A property is PREFERRED over the geometry rep
        # whatever the selection order: the geometry rep is auto-added by
        # _wire_grid_geometry_on_property and would otherwise win the fallback
        # and bind the grid to "SolidColor".
        chosen_prop_for_grid: dict = {}  # rep_path -> colorise node id
        geom_only_for_grid: dict = {}    # rep_path -> geometry rep id (fallback)

        from fespp_on_trame.engine import element_type as _et

        def _consider_ijk(node_id):
            if node_id is None:
                return
            # Grouping folders (properties/ · block wellbore/ · SubRep/ · a
            # Collection property-set) are never colorise targets — their leaf
            # descendants (also in the selection when bulk-checked) are. Skipping
            # them also stops a SubRep/BW folder from resolving to the geometry.
            if _et.for_kind(self._tree.find_type(node_id)).is_grouping():
                return
            rep_node_id = self._tree.find_representation_node(node_id)
            if rep_node_id is None:
                return
            if not self._uses_ijk_pipeline(self._tree.find_type(rep_node_id)):
                return
            rep_path = self._tree.find_path(rep_node_id)
            if not rep_path:
                return
            if node_id == rep_node_id:
                geom_only_for_grid.setdefault(rep_path, node_id)   # geometry-alone
            else:
                chosen_prop_for_grid.setdefault(rep_path, node_id)  # property target

        # Reservoir checkboxes drive targeting; the `selectors` fallback keeps
        # sync self-sufficient when ui_select_node_reservoir hasn't flushed yet
        # on the same tick (fespp_data_selectors can change first).
        for reservoir_node_id in reservoir_select_node_ids or []:
            _consider_ijk(reservoir_node_id)
        for sel in selectors or []:
            _consider_ijk(self._tree.find_node_id(sel))
        # Grids with only the geometry checked (no property) colorise by nothing.
        for rep_path, geom_id in geom_only_for_grid.items():
            chosen_prop_for_grid.setdefault(rep_path, geom_id)

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

    def ijk_grids(self):
        """List of every loaded IjkGrid instance — for callers that
        need to iterate (z-scale, representation propagation, …)."""
        return list(self._ijk_grids.values())
