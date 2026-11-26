"""Derived arrays: the computed properties as arrays of their grid's blocks.

ONE ProgrammableFilter per reader source passes the reader's collection
through (a ShallowCopy: geometry and arrays are shared, not copied) and
attaches to each grid's blocks the computed arrays stored here. What
displays, picks or extracts reads its output, so a calculator property can
be coloured, thresholded, picked and extracted like any array the reader
delivers (decision Q12, probed in slice 4a: about 0.1 s per million cells
and per array).

The values are computed OUTSIDE the filter, by the app, and only attached
here: a filter that asked the pipeline for other data while it executes
would re-enter it. With nothing stored the filter is a plain pass-through.

The data information of the reader's own arrays (ranges, components) is
still read off the READER, which the reads update; the filter's is read
for a computed array only, and is current because `put` and `drop` run the
filter at once. Marking the filter dirty after every read instead marked
every display of it too, and changed how translucent NaN cells draw
(scenario `hide_nan`, 17/10).

The filter's script finds its store by a key, not through a module global:
one server process can hold several sessions, each with its own readers
and its own computed properties."""
import itertools
import weakref

CELLS = "CELLS"
POINTS = "POINTS"

# store key -> DerivedArrays, for the filters' scripts
_STORES = weakref.WeakValueDictionary()
_KEYS = itertools.count(1)


def display_source_of(provider):
    """What displays chain on, for a source provider: the ActiveSource's
    derived-arrays filter, or a plain provider's own source."""
    if provider is None:
        return None
    get = getattr(provider, "get_display_source", None)
    return get() if get is not None else provider.get_source()


def apply(algorithm, key):
    """The filter's body: pass the input through, then attach the arrays of
    the store `key` (none when the store is gone)."""
    inp = algorithm.GetInputDataObject(0, 0)
    out = algorithm.GetOutputDataObject(0)
    if inp is None or out is None:
        return
    out.ShallowCopy(inp)
    store = _STORES.get(key)
    if store is not None:
        store.attach(out)


class _Entry:
    __slots__ = ("rep_path", "values", "assoc")

    def __init__(self, rep_path, values, assoc):
        self.rep_path = rep_path
        self.values = values
        self.assoc = assoc


class DerivedArrays:
    """The computed arrays of one session and the filters that attach them.

    `put(name, rep_path, values, assoc)` stores (or replaces) an array,
    `drop(name)` removes it; both re-run the filters. `proxy_for(src)` is
    the filter chained on a reader source, created on first use."""

    def __init__(self, log=None):
        self.key = f"derived-{next(_KEYS)}"
        _STORES[self.key] = self
        self._arrays = {}      # name -> _Entry
        self._filters = {}     # reader proxy global id -> ProgrammableFilter
        self._generation = 0
        self._log = log
        self.notes = []        # the last run's skipped arrays, why

    # ------------------------------------------------------------------
    # The store

    def names(self):
        return list(dict.fromkeys(name for name, _rep in self._arrays))

    def has(self, name, rep_path=None):
        return any(n == name and rep_path in (None, r) for n, r in self._arrays)

    def put(self, name, rep_path, values, assoc=CELLS):
        """Store `values` (1-D, one per cell, or per point with POINTS) as
        the array `name` of the grid at `rep_path`, then re-run."""
        import numpy as np
        if not name or not rep_path or values is None:
            return
        arr = np.ascontiguousarray(values, dtype=np.float64).ravel()
        # keyed by (name, grid): two grids may each carry a formula of the
        # same name, each on its own blocks
        self._arrays[(name, rep_path)] = _Entry(rep_path, arr, POINTS if assoc == POINTS else CELLS)
        self._touch()

    def drop(self, name, rep_path=None):
        """Remove the array `name` of the grid at `rep_path` (of every grid
        when None), then re-run."""
        gone = [k for k in self._arrays if k[0] == name and rep_path in (None, k[1])]
        for k in gone:
            del self._arrays[k]
        if gone:
            self._touch()

    def clear(self):
        if self._arrays:
            self._arrays.clear()
            self._touch()

    # ------------------------------------------------------------------
    # The filters

    def _script(self):
        # the generation comment changes the script, which is what makes
        # ParaView run the filter again
        return ("from fespp_on_trame.engine import derived_arrays\n"
                f"derived_arrays.apply(self, {self.key!r})\n"
                f"# {self._generation}\n")

    def proxy_for(self, src):
        """The filter chained on the reader `src` (None when it cannot be
        built: callers fall back to the reader itself)."""
        if src is None:
            return None
        sm = getattr(src, "SMProxy", None)
        if sm is None:
            self._note(f"no server-manager proxy behind {src!r}: displays use the reader")
            return None
        gid = sm.GetGlobalIDAsString()
        pf = self._filters.get(gid)
        if pf is not None:
            return pf
        try:
            from paraview import simple as pvsimple
            # creating a proxy makes it the active source: give that back
            prev = pvsimple.GetActiveSource()
            pf = pvsimple.ProgrammableFilter(
                registrationName=f"derived_arrays_{len(self._filters) + 1}",
                Input=src)
            pf.OutputDataSetType = "Same as Input"
            pf.Script = self._script()
            try:
                pvsimple.SetActiveSource(prev)
            except Exception as exc:
                self._note(f"the active source could not be given back: {exc!r}")
        except Exception as exc:
            self._note(f"the derived-arrays filter could not be built: {exc!r}")
            return None
        self._filters[gid] = pf
        self._keep_reader_time(pvsimple, src, pf)
        return pf

    def _keep_reader_time(self, pvsimple, src, pf):
        """The time steps stay the reader's. Registering a filter that
        declares time steps of its own (a ProgrammableFilter does) makes the
        time keeper SUPPRESS its input and listen to the filter, whose steps
        are only known once it has run — built before the first load, it
        would leave the session with no time steps at all."""
        try:
            tk = pvsimple.GetTimeKeeper()
            src_id = src.SMProxy.GetGlobalIDAsString()
            pf_id = pf.SMProxy.GetGlobalIDAsString()
            sup = [p for p in tk.SuppressedTimeSources
                   if p.SMProxy.GetGlobalIDAsString() != src_id]
            if all(p.SMProxy.GetGlobalIDAsString() != pf_id for p in sup):
                sup.append(pf)
            tk.SuppressedTimeSources = sup
        except Exception as exc:
            self._note(f"the time keeper could not keep the reader's time steps: {exc!r}")

    def filters(self):
        return list(self._filters.values())

    def _touch(self):
        """Re-run every filter now, not at the next render: the colour range
        of the array just put is read off the filter's data information
        right after (PdcScene), and gathered before the filter ran again it
        would not hold the array. An update without a time runs at the time
        last asked of the filter: the reader is not read again."""
        self._generation += 1
        script = self._script()
        for pf in self._filters.values():
            try:
                pf.Script = script
                pf.UpdatePipeline()
            except Exception as exc:
                self._note(f"the derived-arrays filter could not be re-run: {exc!r}")

    # ------------------------------------------------------------------
    # Inside the filter's run

    def attach(self, out):
        """Attach every stored array to its grid's blocks of `out`, a
        ShallowCopy of the reader's collection. A block that gets an array
        is replaced by a ShallowCopy of itself first: the reader's own
        block is never written to."""
        self.notes = []
        if not self._arrays:
            return
        try:
            from vtkmodules.util.numpy_support import numpy_to_vtk
        except Exception as exc:
            self.notes.append(f"no VTK numpy support: {exc!r}")
            return
        asm = out.GetDataAssembly() if hasattr(out, "GetDataAssembly") else None
        if asm is None:
            return
        copied = {}            # (pds index, partition index) -> the copy
        for (name, _rep), e in self._arrays.items():
            parts = self._partitions(out, asm, e.rep_path)
            if not parts:
                continue      # the grid is not loaded from this reader
            sizes = [ds.GetNumberOfPoints() if e.assoc == POINTS
                     else ds.GetNumberOfCells() for _i, _j, ds in parts]
            if sum(sizes) != len(e.values):
                self.notes.append(
                    f"{name}: {len(e.values)} values for {sum(sizes)} "
                    f"{'points' if e.assoc == POINTS else 'cells'} of {e.rep_path}")
                continue
            off = 0
            for (i, j, ds), n in zip(parts, sizes):
                cp = copied.get((i, j))
                if cp is None:
                    cp = ds.NewInstance()
                    cp.ShallowCopy(ds)
                    out.GetPartitionedDataSet(i).SetPartition(j, cp)
                    copied[(i, j)] = cp
                arr = numpy_to_vtk(e.values[off:off + n], deep=1)
                arr.SetName(name)
                fd = cp.GetPointData() if e.assoc == POINTS else cp.GetCellData()
                fd.AddArray(arr)
                off += n

    @staticmethod
    def _partitions(out, asm, rep_path):
        """[(pds index, partition index, dataset)] of the grid at
        `rep_path`, its blocks and their subtree's, in the collection's
        order — the order the reader's values come in."""
        node = asm.GetFirstNodeByPath(rep_path)
        if node is None or node < 0:
            return []
        parts = []
        for i in sorted(set(asm.GetDataSetIndices(node, True))):
            pds = out.GetPartitionedDataSet(i)
            if pds is None:
                continue
            for j in range(pds.GetNumberOfPartitions()):
                ds = pds.GetPartition(j)
                if ds is not None:
                    parts.append((i, j, ds))
        return parts

    def _note(self, msg):
        if self._log is not None:
            try:
                self._log(msg)
                return
            except Exception as exc:
                msg = f"{msg} (and the log failed: {exc!r})"
        print("[fespp] derived arrays:", msg, flush=True)
