"""THE property-value seam: one function every analysis consumer reads
through (stats, distribution, crossplot, derived recipes), so changing
where values come from means changing this one function.

`values_for` returns a 1-D float64 array of the property's values,
index-aligned with any other property of the same rep, or None.

Two rules are enforced HERE for every consumer at once:
  - GHOST MASK — an IjkGrid's inactive cells are blanked via a
    `vtkGhostType` cell array (bit 32 = HIDDENCELL) with a 0.0 FILL in
    the property arrays, not NaN. VTK filters (Threshold, statistics)
    skip them; a raw vtk_to_numpy read keeps them as bogus zeros.
    Ghost-flagged entries are folded to NaN so numpy paths agree with
    the native filters.
  - COPY BEFORE RESTORE — vtk_to_numpy is a view over the pipeline's
    buffer; reading X at t1 then Y at t2 through the same view silently
    hands back t2's values for both.
"""
from contextlib import contextmanager

from paraview import simple as pvsimple

from fespp_on_trame.engine import stats_dispatch
from fespp_on_trame.engine.blockscope import assembly_index

# Why the last derived read returned None — the consumers' notes.
_LAST_ERROR = {"msg": ""}


def last_error():
    """Why the last `values_for` call returned None, when it says; else ""."""
    return _LAST_ERROR["msg"]


_UNSET = object()


def component_choice(state, array_path):
    """Which component of a vector property the session looks at: an
    integer index, or None for the magnitude (the default). One choice per
    array, session-wide (`ui_vector_component`), so the colour, the
    statistics, every plot and the synthetic logs show the same thing."""
    m = getattr(state, "ui_vector_component", None) or {}
    c = m.get(array_path)
    if c is None or str(c) == "magnitude":
        return None
    try:
        return int(c)
    except (TypeError, ValueError):
        return None


def axis_key(state, array_path):
    """What a plot axis of `array_path` stands for, as a string: the path
    and the component read. The plotly `uirevision` keys are built on it,
    so a zoom survives a refresh of the same values and goes away when the
    component changes — the numbers on the axis are then other numbers."""
    comp = component_choice(state, array_path)
    return f"{array_path}#{'mag' if comp is None else comp}"


#: How a component is named to the user, by number of values per element.
#: The Colormap card's component select spells them the same way
#: (`componentLabel` in widgets/colormap/vue-components/src/ColormapPanel.vue)
#: — a label and the select the reader picked it in must agree.
_COMPONENT_NAMES = {3: ("X", "Y", "Z"),
                    6: ("XX", "YY", "ZZ", "XY", "YZ", "XZ")}

#: Between a property's title and the component read of it, on every site
#: at once — "velocity · X (Euc)" on the colour bar, the cards, the
#: statistics, the axes and the chips. The scenario probes look for it.
COMPONENT_SEP = " · "


def component_count(state, tree, array_path):
    """How many values per element the property carries (1 = a scalar).

    The count the ARRAY itself reports wins: the Colormap card counts the
    components of the live VTK array and publishes what it counted
    (`ui_vector_component_count`) next to the choice it wrote, so a label
    and the select the reader picked the component in cannot disagree.
    The assembly's `componentCount` attribute is the fallback — it names
    the count of a plain property leaf, but the collector's synthetic
    time-series and multi-realization leaves carry no such attribute."""
    live = getattr(state, "ui_vector_component_count", None) or {}
    try:
        n = int(live.get(array_path) or 0)
        if n > 1:
            return n
    except (AttributeError, TypeError, ValueError):
        pass
    try:
        nid = tree.find_node_id(array_path)
        if nid is None:
            return 1
        return int(tree.find_attribute_value(nid, "componentCount") or 1)
    except (AttributeError, TypeError, ValueError):
        return 1


def component_label(state, tree, array_path):
    """Name of the component the session reads — "" for the magnitude.
    X / Y / Z for a 3-component vector, XX / YY / ZZ / XY / YZ / XZ for a
    symmetric tensor's 6, "Component <n>" otherwise."""
    comp = component_choice(state, array_path)
    if comp is None:
        return ""
    names = _COMPONENT_NAMES.get(component_count(state, tree, array_path))
    if names and 0 <= comp < len(names):
        return names[comp]
    return f"Component {comp}"


def labelled(state, tree, array_path, label):
    """`label` with the component read after a middle dot — "velocity · X".
    The magnitude adds nothing: it is the default, and the numbers of a card
    titled by the bare name are the ones the reader expects. Anything else
    changes the values with no visible cause unless it is said here.

    The separator must be one every site draws as it is: the colour bar is
    VTK text, which renders brackets as parentheses — "velocity [X] (Euc)"
    on a card would read "velocity (X) (Euc)" on the bar."""
    comp = component_label(state, tree, array_path)
    return f"{label}{COMPONENT_SEP}{comp}" if comp else label


def display_label(state, tree, array_path, fallback=""):
    """THE name of a property wherever it is shown — the colour bar, the
    Colormap card, a card's title bar, a row of the Statistics view, a plot axis:
    the RESQML title, the component read after a middle dot, the unit of
    measure in parentheses — "Total Porosity · X (m3/m3)". The unit is left
    out when the tree carries none, the component when the magnitude (the
    default) is read. A screenshot of the colour bar then says what the
    numbers are.
    `fallback` (the VTK array name, say) stands in for a title the tree does
    not know; "" when there is neither."""
    name, uom = name_and_unit(state, tree, array_path, fallback)
    if not name:
        return ""
    return f"{name} ({uom})" if uom else name


def name_and_unit(state, tree, array_path, fallback=""):
    """The two halves `display_label` joins: the name (the RESQML title,
    the component read after a middle dot) and the unit of measure, ""
    when the tree carries none. A readout that writes a VALUE wants them
    apart — "Total Porosity = 0.23 m3/m3", the unit after the number it
    qualifies, and once."""
    title = stats_dispatch._title_and_kind(tree, array_path)[0] or fallback
    if not title:
        return "", ""
    return (labelled(state, tree, array_path, title),
            stats_dispatch._unit_for_array_path(tree, array_path) or "")


def reduce_components(raw, component):
    """1-D float64 from a VTK-shaped array: a scalar as it is; a vector
    (an ``(n, c)`` array) reduced to the chosen component, or to its
    magnitude. Flattening a vector would hand back c values per element,
    interleaved — every statistic on it would be silently wrong."""
    np, _ = _numpy()
    a = np.array(raw, dtype=float, copy=True)
    if a.ndim < 2 or a.shape[1] <= 1:
        return a.ravel()
    if component is None or not 0 <= int(component) < a.shape[1]:
        return np.sqrt((a * a).sum(axis=1))
    return np.ascontiguousarray(a[:, int(component)])


def _numpy():
    """(numpy, vtk_to_numpy), imported on first use."""
    import numpy as np
    from vtkmodules.util.numpy_support import vtk_to_numpy
    return np, vtk_to_numpy


def _named_and_ghost(source, vtk_name):
    """Locate `vtk_name` on the source's inner dataset and the matching
    ghost array FROM THE SAME field data (cell ghosts for a cell array,
    point ghosts for a point array). Returns (array, ghost_or_None)."""
    if source is None or not vtk_name:
        return None, None
    try:
        source.UpdatePipeline()
        client = source.GetClientSideObject()
        out = client.GetOutputDataObject(0) if client else None
        inner = assembly_index.inner(out)
        if inner is None:
            return None, None
        for getter in ("GetCellData", "GetPointData"):
            try:
                fd = getattr(inner, getter)()
            except Exception:
                continue
            if fd is None:
                continue
            arr = fd.GetArray(vtk_name)
            if arr is not None:
                return arr, fd.GetArray("vtkGhostType")
    except Exception:
        return None, None
    return None, None


def values_of(arr, ghost, component):
    """1-D float64 of a VTK array, one value per element
    (`reduce_components`), NaN where the ghost array blanks the element."""
    np, vtk_to_numpy = _numpy()
    vals = reduce_components(vtk_to_numpy(arr), component)
    if ghost is not None:
        gm = np.array(vtk_to_numpy(ghost), copy=True).ravel()
        if len(gm) == len(vals):
            vals[gm != 0] = np.nan
    return vals


def named_values(source, vtk_name, component):
    """`values_of` the array `vtk_name` on `source`; None when the source does
    not carry the array."""
    arr, ghost = _named_and_ghost(source, vtk_name)
    return None if arr is None else values_of(arr, ghost, component)


# Several reads at other time steps in a row (the Statistics matrix, fifty
# pinned dates): inside a batch the pipeline goes back to the session's
# time ONCE, at the end, instead of after every read — each move is a full
# run of the reader.
_BATCH = {"on": False, "saved": None, "at": {}, "sources": {}}


@contextmanager
def time_batch():
    """Run several `values_for` reads as one batch: the session's time is
    restored once, when the block exits, on every source a read moved."""
    _BATCH.update(on=True, saved=None, at={}, sources={})
    try:
        yield
    finally:
        saved, sources = _BATCH["saved"], list(_BATCH["sources"].values())
        _BATCH.update(on=False, saved=None, at={}, sources={})
        if saved is not None:
            try:
                tk = pvsimple.GetTimeKeeper()
                tk.Time = saved
                for src in sources:
                    src.UpdatePipeline(saved)
            except Exception as exc:
                print("[fespp] time batch: the session's time could not be"
                      " restored:", exc, flush=True)


def values_for(state, tree, source_registry, array_path, rep_path,
               real_idx=None, ts_idx=None, component=_UNSET):
    """1-D numpy float64 of the property's values (NaN = missing/blanked),
    index-aligned with any other property of the same rep, or None.

    Channel-aware (Frame ring sampling), MR-aware (`real_idx` picks the
    suffixed array), TS-aware (`ts_idx` moves the TimeKeeper for the read
    and restores it), derived-aware (a `derived://` path evaluates its
    recipe — same alignment, since its inputs come through here).
    Vector-aware: a property with several values per element comes back as
    ONE value per element — the session's chosen component, or the magnitude
    (`component` overrides the session's choice when given)."""
    _LAST_ERROR["msg"] = ""
    np, _ = _numpy()

    from fespp_on_trame.engine import derived_props
    if derived_props.is_derived(array_path):
        store = derived_props.get_store()
        if store is None:
            _LAST_ERROR["msg"] = "Derived-property store not ready."
            return None
        try:
            return store.evaluate(state, tree, source_registry, array_path,
                                  real_idx=real_idx, ts_idx=ts_idx)
        except derived_props.DerivedError as exc:
            _LAST_ERROR["msg"] = str(exc)
            return None

    rep_kind = ""
    rid = tree.find_node_id(rep_path) if rep_path else None
    if rid is not None:
        rep_kind = tree.find_type(rid) or ""
    if rep_kind == "Frame":
        # a channel is its own block; ring sampling reads it one value per
        # frame node, in a stable order (see welllog_dispatch._ring_samples)
        from fespp_on_trame.engine import welllog_dispatch as wd
        from fespp_on_trame.engine.utils.naming import make_valid_vtk_name
        title = stats_dispatch._title_and_kind(tree, array_path)[0] or ""
        try:
            shared = source_registry.shared_source()
        except Exception:
            shared = None
        if shared is None:
            return None
        samples = wd._ring_samples(wd._fetch_block(shared, array_path),
                                   make_valid_vtk_name(title))
        if not samples:
            return None
        return np.array([np.nan if v is None else float(v)
                         for v, *_rest in samples], dtype=float)

    if real_idx is None:
        real_idx = stats_dispatch._default_real_idx(state, tree, array_path)
    _t, _k, vtk_name = stats_dispatch._resolve_vtk_name(
        tree, array_path, real_idx)
    if not vtk_name:
        return None
    source, real_name = stats_dispatch._original_source_and_name(
        state, source_registry, tree, array_path, rep_path, vtk_name, _t)
    if source is None:
        return None
    saved_time = None
    try:
        if ts_idx is not None or _BATCH["on"]:
            try:
                tk = pvsimple.GetTimeKeeper()
                values = list(tk.TimestepValues or [])
                if _BATCH["on"]:
                    # inside a batch the session's time is remembered once
                    # and restored when the batch ends; a source is moved
                    # only when it is not at the wanted time — a read that
                    # names no time step wants the SESSION's time and, on a
                    # source a previous read moved, moves it back
                    session = (_BATCH["saved"] if _BATCH["saved"] is not None
                               else float(tk.Time))
                    want = session
                    if ts_idx is not None and 0 <= int(ts_idx) < len(values):
                        want = float(values[int(ts_idx)])
                    at = _BATCH["at"].get(id(source), session)
                    if at != want:
                        if _BATCH["saved"] is None:
                            _BATCH["saved"] = session
                        tk.Time = want
                        source.UpdatePipeline(want)
                        _BATCH["at"][id(source)] = want
                        _BATCH["sources"][id(source)] = source
                elif 0 <= int(ts_idx) < len(values):
                    want = float(values[int(ts_idx)])
                    saved_time = float(tk.Time)
                    tk.Time = want
                    source.UpdatePipeline(want)
            except Exception:
                saved_time = None
        return named_values(source, real_name or vtk_name,
                            component_choice(state, array_path)
                            if component is _UNSET else component)
    finally:
        if saved_time is not None:
            try:
                tk = pvsimple.GetTimeKeeper()
                tk.Time = saved_time
                source.UpdatePipeline(saved_time)
            except Exception:
                pass
