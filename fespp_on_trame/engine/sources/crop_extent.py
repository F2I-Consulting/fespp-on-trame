"""The point extent of an I/J/K crop — ParaView's ExtractSubset on a
structured grid (a lattice IJK grid, a surface on a 2D grid), its
ExplicitStructuredGridCrop on a corner-point grid — read and written the
same way whatever the crop."""


def is_subset(src):
    # ExtractSubset's proxy is named "ExtractGrid": told by its VOI
    return src.SMProxy.GetProperty("VOI") is not None


# the extent the app gave each ExtractSubset (its VOI may differ, below)
SUBSET_EXTENTS = {}


def crop_extent(src):
    if is_subset(src):
        return list(SUBSET_EXTENTS.get(id(src)) or src.VOI)
    return list(src.OutputWholeExtent)


def put_crop_extent(src, ext, whole=None):
    """A crop's point extent. A cut ([a, a] on an axis) is the layer of cells
    a, as the explicit grid's crop draws it: ExtractSubset is given [a, a+1]
    there (the last layer at the far end of `whole`), which keeps cells with
    a volume rather than the plane of their faces."""
    ext = [int(v) for v in ext]
    if not is_subset(src):
        src.OutputWholeExtent = ext
        return
    SUBSET_EXTENTS[id(src)] = list(ext)
    voi = list(ext)
    for n in range(3):
        lo, hi = voi[2 * n], voi[2 * n + 1]
        if lo == hi and not (whole and whole[2 * n] == whole[2 * n + 1]):
            top = whole[2 * n + 1] if whole else None
            voi[2 * n], voi[2 * n + 1] = (top - 1, top) if top is not None and lo >= top else (lo, lo + 1)
    src.VOI = voi
