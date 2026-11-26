"""Objects without an extent: every point at one place.

A store can serve a representation whose coordinates are all zero (ADME
served the Volve grid so on 12/10: 1 454 979 points at the CRS origin). It
loads, it is "visible", it draws NOTHING, and a camera framed on it sits a
few metres from a point kilometres away from the data. The 3D view cannot
say why nothing shows; this module finds such objects among the ticked
paths, from the collector's output in this process (no round trip), so the
load can name them in its note. The camera side is in app/views/camera.py
(a frame on no extent is refused).
"""


def is_flat(bounds, n_points):
    """True for a dataset with points whose bounding box has no size at
    all: xmin == xmax and ymin == ymax and zmin == zmax. A dataset without
    points is empty, not flat (an unread property, a grid still loading)."""
    if not n_points or not bounds or len(bounds) < 6:
        return False
    return bounds[0] == bounds[1] and bounds[2] == bounds[3] and bounds[4] == bounds[5]


def no_extent_paths(pdc, paths):
    """The (path, title) of every ticked path whose datasets, in the
    partitioned dataset collection `pdc`, all have points and all are
    flat. `paths` are data-assembly node paths ("/data/_uuid/…"); a path
    the assembly does not know, or without datasets, is skipped."""
    out = []
    if pdc is None:
        return out
    try:
        asm = pdc.GetDataAssembly()
    except Exception as exc:
        print("[fespp] extent: no data assembly to read:", exc, flush=True)
        return out
    if asm is None:
        return out
    for path in paths or ():
        try:
            nid = asm.GetFirstNodeByPath(path)
            if nid is None or nid < 0:
                continue
            indices = list(asm.GetDataSetIndices(nid, True) or [])
        except Exception as exc:
            print("[fespp] extent: cannot read the node of", path, ":", exc, flush=True)
            continue
        seen, flat = 0, 0
        for i in indices:
            try:
                pds = pdc.GetPartitionedDataSet(i)
                for j in range(pds.GetNumberOfPartitions() if pds is not None else 0):
                    ds = pds.GetPartition(j)
                    if ds is None or not ds.IsA("vtkDataSet"):
                        continue
                    n = ds.GetNumberOfPoints()
                    if not n:
                        continue
                    seen += 1
                    if is_flat(ds.GetBounds(), n):
                        flat += 1
            except Exception as exc:
                print("[fespp] extent: cannot read partition", i, "of", path, ":", exc, flush=True)
                continue
        if seen and flat == seen:
            try:
                title = asm.GetAttributeOrDefault(nid, "title", "") or asm.GetNodeName(nid)
            except Exception as exc:
                print("[fespp] extent: no title for", path, ":", exc, flush=True)
                title = path
            out.append((path, title))
    return out


def note(titles):
    """The sentence of the load note for objects without an extent."""
    titles = [t for t in titles if t]
    if not titles:
        return ""
    names = ", ".join(f"“{t}”" for t in titles[:3]) + (" and others" if len(titles) > 3 else "")
    verb = "has" if len(titles) == 1 else "have"
    return (f"{names} {verb} every point at one place (the store served empty coordinates):"
            " nothing to draw, and the camera stays where it was.")
