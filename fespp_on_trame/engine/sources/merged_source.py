"""The file reader and the store read TOGETHER: one collection, one tree.

A session reads files (the EPC collector) and a store (the ETP source), each
reader with its own repository: a working file may hold the very objects of
the dataspace it is compared with, and one repository would keep one of the
two. What displays, picks, lists or extracts wants ONE collection and ONE
assembly all the same; this filter makes them of the readers that hold data.

One reader: its collection passes through (a ShallowCopy) — the session
reads as it did with that reader alone. Several: their partitioned datasets
one after the other, their assemblies' top rows under one root, the dataset
indices of every reader after the first shifted by what stands before it.
Nothing is copied but pointers and the tree.

What speaks to a READER — the selectors that say what to read, the query
channel — goes to the reader that holds the object (`ActiveSource`,
engine/repo_query): this filter only joins what they deliver.
"""

# the name vtkDataAssembly keeps for the datasets a node holds
_DATASET = "dataset"


def apply(algorithm):
    """The filter's body: the inputs' collections as one."""
    out = algorithm.GetOutputDataObject(0)
    count = algorithm.GetNumberOfInputConnections(0)
    if out is None or count == 0:
        return
    if count == 1:
        inp = algorithm.GetInputDataObject(0, 0)
        if inp is not None:
            out.ShallowCopy(inp)
        return
    parts = []
    held = 0
    first = True
    for port in range(count):
        inp = algorithm.GetInputDataObject(0, port)
        if inp is None:
            continue
        n = inp.GetNumberOfPartitionedDataSets()
        for i in range(n):
            out.SetPartitionedDataSet(held + i, inp.GetPartitionedDataSet(i))
            if inp.HasMetaData(i):
                out.GetMetaData(held + i).Copy(inp.GetMetaData(i))
        asm = inp.GetDataAssembly()
        if asm is not None:
            parts.append((asm, held))
        if first:
            # the time the collection stands at, the reader's own field data
            out.GetInformation().Copy(inp.GetInformation())
            out.GetFieldData().ShallowCopy(inp.GetFieldData())
            first = False
        held += n
    out.SetDataAssembly(joined(parts))


def joined(parts):
    """One assembly of `parts`, [(assembly, the datasets standing before its
    reader's)]: the top rows of each under the root of the first, their
    dataset indices moved on by what stands before, every node numbered
    again. Written on the trees' XML: `vtkDataAssembly.AddSubtree` moves the
    dataset indices by a count of its own, which is not the collection's."""
    import xml.etree.ElementTree as ET

    from vtkmodules.vtkCommonCore import vtkIndent
    from vtkmodules.vtkCommonDataModel import vtkDataAssembly
    root = None
    node_id = 0
    for assembly, before in parts:
        tree = ET.fromstring(assembly.SerializeToXML(vtkIndent()))
        if root is None:
            root = ET.Element(tree.tag, dict(tree.attrib, id="0"))
        for top in list(tree):
            for node in top.iter():
                if node.tag == _DATASET:
                    node.set("id", str(int(node.get("id")) + before))
                else:
                    node_id += 1
                    node.set("id", str(node_id))
            root.append(top)
    merged = vtkDataAssembly()
    if root is not None and not merged.InitializeFromXML(ET.tostring(root, encoding="unicode")):
        print("[fespp] sources: the readers' trees could not be joined, the tree is left empty", flush=True)
    return merged


_SCRIPT = ("from fespp_on_trame.engine.sources import merged_source\n"
           "merged_source.apply(self)\n")


def _gid(proxy):
    return proxy.SMProxy.GetGlobalIDAsString()


class MergedSource:
    """The one source standing for the readers that hold data."""

    def __init__(self):
        self._proxy = None
        self._inputs = ()
        self._readers = []

    def proxy(self, readers):
        """The filter, made at first use on `readers`; its inputs are those
        readers from then on (`set_inputs`). None when it cannot be built:
        the caller falls back on the first reader."""
        if self._proxy is None:
            try:
                from paraview import simple as pvsimple
                # creating a proxy makes it the active source: give that back
                prev = pvsimple.GetActiveSource()
                pf = pvsimple.ProgrammableFilter(registrationName="fespp_sources", Input=list(readers))
                pf.OutputDataSetType = "vtkPartitionedDataSetCollection"
                pf.Script = _SCRIPT
                try:
                    pvsimple.SetActiveSource(prev)
                except Exception as exc:
                    print(f"[fespp] sources: the active source could not be given back ({exc!r})", flush=True)
            except Exception as exc:
                print(f"[fespp] sources: the readers could not be read together ({exc!r})", flush=True)
                return None
            self._proxy = pf
            self._inputs = self._ids(readers)
            self._readers = list(readers)
            self.keep_readers_time()
        return self._proxy

    @staticmethod
    def _ids(readers):
        return tuple(_gid(r) for r in readers)

    def set_inputs(self, readers):
        """The readers the filter joins from now on. True when that changed."""
        if self._proxy is None:
            return self.proxy(readers) is not None
        ids = self._ids(readers)
        if ids == self._inputs:
            return False
        self._proxy.Input = list(readers)
        self._inputs = ids
        self._readers = list(readers)
        self.keep_readers_time()
        return True

    def keep_readers_time(self, *others):
        """The time steps stay the readers'. A filter registered over a
        source makes the time keeper SUPPRESS that source and listen to the
        filter, and a ProgrammableFilter's steps are only known once it has
        run: the session would be left with none. The readers are listened
        to; this filter, and `others` chained on it, are not."""
        try:
            from paraview import simple as pvsimple
            tk = pvsimple.GetTimeKeeper()
            gid = _gid
            readers = {gid(r) for r in self._readers}
            was = list(tk.SuppressedTimeSources)
            sup = [p for p in was if gid(p) not in readers]
            ids = {gid(p) for p in sup}
            sup += [p for p in (self._proxy, *others) if p is not None and gid(p) not in ids]
            if [gid(p) for p in sup] != [gid(p) for p in was]:
                tk.SuppressedTimeSources = sup
        except Exception as exc:
            print(f"[fespp] sources: the time keeper could not keep the readers' time steps ({exc!r})", flush=True)
