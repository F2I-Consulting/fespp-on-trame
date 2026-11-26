"""AssemblyIndex — what the assembly of the data says, asked in one place.

The reader's output is a ``vtkPartitionedDataSetCollection`` whose
``vtkDataAssembly`` names every object by a path (``/data/_gridfolder_…/…``,
the tree's own paths). Three questions are asked of it all the time: which
datasets does a path own (to colour, select or read them), which composite
(flat) indices do they carry (a ParaView ID selection is keyed by them), and
which path owns the dataset a pick reports by its flat index. Each used to
be answered by its own walk of the collection — four walks and ten loops
over the leaves, some redone on every pick — while this index was built on
ParaView's ``/Root/…`` hierarchy and never found a ``/data`` path
(04-verification, slice 2 of the overhaul).

The index is built from the collection itself and rebuilt when the
collection changes (another output object, or the same one modified): no
caller has to remember to refresh it.

Flat numbering, ParaView's: 0 is the collection; each partitioned dataset
takes the next number and its partitions the ones after it, in order.

``pdc_provider`` is a zero-argument callable returning the collection, or
None when nothing is loaded; a fake collection with the same duck-typed
methods serves the unit tests.
"""


class AssemblyIndex:
    def __init__(self, pdc_provider=None):
        self._provider = pdc_provider
        self._pdc = None
        self._mtime = None
        self._clear()

    def _clear(self):
        self._own = {}          # path -> tuple(partitioned dataset indices it owns)
        self._names = {}        # path -> node name
        self._pds_flat = []     # pds index -> its flat index
        self._leaf = {}         # leaf flat index -> (pds index, partition index)
        self._owner = {}        # pds index -> the deepest path owning it

    # ------------------------------------------------------------ build
    def refresh(self, pdc=None):
        """Rebuild now, from `pdc` or the provider's collection. True when a
        collection with an assembly was indexed."""
        if pdc is None and self._provider is not None:
            try:
                pdc = self._provider()
            except Exception as exc:
                print(f"[fespp] assembly index: no collection ({exc})", flush=True)
                pdc = None
        self._build(pdc)
        return bool(self._own)

    def _fresh(self):
        """The index of the current collection, rebuilt when it changed."""
        pdc = None
        if self._provider is not None:
            try:
                pdc = self._provider()
            except Exception as exc:
                print(f"[fespp] assembly index: no collection ({exc})", flush=True)
        mtime = pdc.GetMTime() if pdc is not None else None
        if pdc is not self._pdc or mtime != self._mtime:
            self._build(pdc)
        return self

    def _build(self, pdc):
        self._clear()
        self._pdc = pdc
        self._mtime = pdc.GetMTime() if pdc is not None else None
        if pdc is None:
            return
        flat = 1
        for i in range(pdc.GetNumberOfPartitionedDataSets()):
            pds = pdc.GetPartitionedDataSet(i)
            n = pds.GetNumberOfPartitions() if pds is not None else 0
            self._pds_flat.append(flat)
            for j in range(n):
                self._leaf[flat + 1 + j] = (i, j)
            flat += 1 + n
        asm = pdc.GetDataAssembly()
        if asm is None:
            return
        depth = {}
        stack = [asm.GetRootNode()]
        while stack:
            node = stack.pop()
            path = asm.GetNodePath(node)
            self._names[path] = asm.GetNodeName(node)
            own = tuple(asm.GetDataSetIndices(node, False))
            self._own[path] = own
            d = path.count("/")
            for i in own:
                if d > depth.get(i, -1):
                    depth[i] = d
                    self._owner[i] = path
            stack.extend(asm.GetChildNodes(node, False))

    # ------------------------------------------------------------ lookups
    def _pds_of(self, path, subtree):
        if path not in self._own:
            return []
        if not subtree:
            return list(self._own[path])
        prefix = path.rstrip("/") + "/"
        out = list(self._own[path])
        for p, own in self._own.items():
            if p.startswith(prefix):
                out.extend(own)
        return sorted(set(out))

    def flat_indices(self, path, subtree=True):
        """The flat indices of the leaf datasets `path` owns (its subtree's
        too when `subtree`), in collection order."""
        self._fresh()
        out = []
        for i in self._pds_of(path, subtree):
            pds = self._pdc.GetPartitionedDataSet(i)
            n = pds.GetNumberOfPartitions() if pds is not None else 0
            out += [self._pds_flat[i] + 1 + j for j in range(n)]
        return out

    def datasets(self, path, subtree=True):
        """[(dataset, flat index)] of the leaf datasets `path` owns — the
        currency of a composite ID selection; [] when none is loaded."""
        self._fresh()
        out = []
        for i in self._pds_of(path, subtree):
            pds = self._pdc.GetPartitionedDataSet(i)
            for j in range(pds.GetNumberOfPartitions() if pds is not None else 0):
                ds = pds.GetPartition(j)
                if ds is not None:
                    out.append((ds, self._pds_flat[i] + 1 + j))
        return out

    def dataset(self, flat):
        """The leaf dataset with that flat index, or None."""
        self._fresh()
        at = self._leaf.get(flat)
        if at is None:
            return None
        return self._pdc.GetPartitionedDataSet(at[0]).GetPartition(at[1])

    def selector_for_flat(self, flat):
        """The deepest path owning the dataset a pick reports by its flat
        index (a leaf's, or a partitioned dataset's own); None if unknown."""
        self._fresh()
        at = self._leaf.get(flat)
        if at is not None:
            return self._owner.get(at[0])
        if flat in self._pds_flat:
            return self._owner.get(self._pds_flat.index(flat))
        return None

    def selector_for(self, path):
        """`path` itself when the assembly has it, else None."""
        self._fresh()
        return path if path in self._own else None

    def rep_path_for(self, selector):
        return self.selector_for(selector)

    def node_name(self, path):
        self._fresh()
        return self._names.get(path, "")

    def selectors(self):
        self._fresh()
        return list(self._own)

    def __contains__(self, path):
        self._fresh()
        return path in self._own

    def __len__(self):
        self._fresh()
        return len(self._own)


def inner(vtk_out):
    """The first partition of the first partitioned dataset of a collection,
    or `vtk_out` itself when it is not one (or holds nothing there)."""
    if vtk_out is None:
        return None
    if hasattr(vtk_out, 'GetPartitionedDataSet'):
        try:
            pds = vtk_out.GetPartitionedDataSet(0)
            if pds is not None and pds.GetNumberOfPartitions() > 0:
                return pds.GetPartitionAsDataObject(0)
        except Exception as exc:
            print(f"[fespp] inner dataset: {exc}", flush=True)
            return vtk_out
    return vtk_out


def leaves(composite, skip_empty=True):
    """(flat index, dataset) of each leaf of a composite dataset, in the flat
    numbering above; an empty leaf comes as (flat, None) unless `skip_empty`."""
    it = composite.NewIterator()
    it.SetVisitOnlyLeaves(True)
    it.SetSkipEmptyNodes(bool(skip_empty))
    it.InitTraversal()
    while not it.IsDoneWithTraversal():
        yield it.GetCurrentFlatIndex(), it.GetCurrentDataObject()
        it.GoToNextItem()
