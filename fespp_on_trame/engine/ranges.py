"""The range and the distinct values of an array: one rule each (overhaul
slice 7).

- `finite_range(arr, ghost=None)`: (min, max) over the finite values that
  are not hidden — a blanked cell of an IJK grid carries a value too (a
  zero, mostly) and ParaView's own data information leaves it out, so must
  a colour bar; the magnitude of a vector array.
- `widen_for_bar(lo, hi)`: a constant array (an indicator that never
  fires) has a range of no width; ParaView would open it to 1e-38 and the
  bar would read a nonsense top. Opened by half a unit (or half a percent
  of the value) on each side, the constant sits mid-bar.
- `distinct(arr, cap=None)`: the sorted distinct finite values (the first
  component of a vector array), or None past `cap` of them — what a
  categorical palette and a discrete threshold slider are built from.
  Vectorised: the slider's scan used to walk the cells in Python (0.79 s on
  a million cells).
- `gap_count(ds, array_name)` and `no_value(values, gaps)`: which elements
  hold no value. NaN everywhere; on a well log's channel, also the samples
  the plugin wrote as NEGATIVE zeros — a NaN cannot stay in the array that
  sets the radius of the tube drawn from it — and counted in
  `<array>_nanCount`. A zero is a gap only on a block that counted gaps: a
  zero of a log without gaps, or of a grid, is a value. What the readers of
  a log's values go by: the statistics and the log view, through
  welllog_dispatch's ring sampling; the codes of a discrete log read the
  count.

They used to live in PdcScene (`_range_skipping_hidden`, `_widened`),
`extract_block._scan_unique_values` and `categorical_palette.scan_codes`."""


def _numpy_of(arr):
    import numpy as np
    from vtkmodules.util.numpy_support import vtk_to_numpy
    return np, vtk_to_numpy(arr)


def finite_range(arr, ghost=None):
    """(lo, hi) of `arr` over its finite, not hidden tuples; None when
    nothing is left or the array is not numeric."""
    try:
        np, v = _numpy_of(arr)
    except Exception as exc:
        # a string array, or one numpy cannot read: no range, the caller's
        # fallback takes over
        print(f"[fespp] range: array {arr.GetName()!r} unreadable:", exc, flush=True)
        return None
    if v.dtype.kind not in "fiu" or v.size == 0:
        return None
    v = v.astype(float, copy=False)
    if v.ndim > 1:
        v = np.sqrt((v * v).sum(axis=1))
    if ghost is not None:
        try:
            _np, g = _numpy_of(ghost)
            if g.shape[0] == v.shape[0]:
                v = v[g == 0]
        except Exception as exc:
            # hidden cells counted then: the range may reach a blank
            print("[fespp] range: ghost array unreadable:", exc, flush=True)
    v = v[np.isfinite(v)]
    if v.size == 0:
        return None
    return (float(v.min()), float(v.max()))


def widen_for_bar(lo, hi):
    """(lo, hi), opened when it has no width."""
    if hi - lo > 1e-12 * max(1.0, abs(hi), abs(lo)):
        return (lo, hi)
    pad = max(0.5, 0.005 * abs(lo))
    return (lo - pad, hi + pad)


def distinct(arr, cap=None):
    """Sorted distinct finite values of `arr` as floats, or None past `cap`
    of them; [] when the array cannot be read."""
    try:
        np, v = _numpy_of(arr)
    except Exception as exc:
        print("[fespp] distinct values: array unreadable:", exc, flush=True)
        return []
    if v.ndim > 1:
        v = v[:, 0]
    if v.dtype.kind == "f":
        v = v[np.isfinite(v)]
    elif v.dtype.kind not in "iu":
        return []
    uniques = np.unique(v)
    if cap is not None and uniques.size > cap:
        return None
    return [float(x) for x in uniques]


def gap_count(ds, array_name):
    """How many samples of the block `ds` hold no value in `array_name`, as
    the plugin counted them in the field array `<array>_nanCount` (one
    tuple) of a well log's channel; 0 when the block counts none or says
    nothing — a grid's array."""
    fd = ds.GetFieldData() if ds is not None and hasattr(ds, "GetFieldData") else None
    count = fd.GetArray(f"{array_name}_nanCount") if fd is not None else None
    if count is None or not count.GetNumberOfTuples():
        return 0
    return max(0, int(count.GetTuple1(0)))


def no_value(values, gaps=0):
    """Boolean mask of the elements of `values` (array-like) holding no
    value: NaN and the infinities and, when the block counted `gaps` > 0
    (`gap_count`), the negative zeros the plugin wrote for them. A positive
    zero is a value, beside the gaps as anywhere else. An integer array holds
    a value everywhere."""
    import numpy as np
    v = np.asarray(values)
    if v.dtype.kind != "f":
        return np.zeros(v.shape, dtype=bool)
    out = ~np.isfinite(v)
    if gaps > 0:
        out |= (v == 0) & np.signbit(v)
    return out
