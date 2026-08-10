"""Leaf representations — the mass-load ``std::bad_alloc`` fix.

Background
----------
Every ``pvsimple.Show`` / ``GetRepresentation`` builds a *composite*
representation (``vtkSMPVRepresentationProxy``). That composite eagerly creates
a ``vtkSelectionRepresentation`` -> ``vtkDataLabelRepresentation`` whose two
``vtkLabeledDataMapper`` constructors each hard-code ``AllocateLabels(50)`` — so
**100 real ``vtkTextMapper`` objects per representation**, each dragging a cell
array + pipeline executive, *even though this app never shows ParaView data
labels* (selection is driven by the tree). With one representation per source
(the deliberate N-source design, kept for type-specific filters), mass-loading
~100-150 sources floods the glibc heap arena with hundreds of thousands of tiny
objects and a small ``new`` throws ``std::bad_alloc`` — despite GBs of free RAM
(it is arena fragmentation, not a memory limit).

The fix
-------
Show a **leaf** representation instead — a bare ``SurfaceRepresentation``
(``vtkSMRepresentationProxy``) with no selection/label sub-reps. Measured
~0.75 MB/rep vs ~13.5 MB/rep for the composite (~18x), and 250 reps load with
no crash. ``install()`` monkeypatches the three pvsimple entry points the app
uses (``Show`` / ``GetRepresentation`` / ``GetDisplayProperties``) so the swap
is global and every existing call site benefits without edits: a leaf carries
all the display properties the app sets (``Representation``, ``DiffuseColor``,
``Scale``, ``Opacity``, ``Visibility``, ``EdgeColor`` …) and, once appended to
the view, ``GetRepresentation`` returns *it* — so downstream code that fetches
the display and mutates it is unaffected. ``pvsimple.Hide`` and
``pvsimple.Delete(source)`` also work and clean the leaf up with no leak.

Two things a leaf does NOT support, with helpers here to replace them:
  * the composite colour API (``ColorBy`` / ``SetScalarColoring`` /
    ``RescaleTransferFunctionToDataRange`` / ``SetScalarBarVisibility``) —
    use :func:`color_by`, :func:`uncolor`, :func:`rescale_to_range`,
    :func:`scalar_bar_visibility`;
  * Text/Billboard/Flagpole reps (the wellhead) — those need the composite, so
    create them via :func:`show_composite` (explicit opt-out).
"""
from paraview import simple as pvsimple
from paraview import servermanager as _sm

# Original pvsimple callables, captured by install() so the patched versions
# (and show_composite) can fall back to them.
_orig: dict = {}
# Monotonic counter for unique leaf-rep registration names.
_counter = [0]


# ---------------------------------------------------------------------------
# Core: find-or-create the leaf representation for (source, view)

def _find_rep(proxy, view):
    """Return the representation already showing ``proxy`` in ``view`` (leaf OR
    composite), without creating one. None if there is none yet."""
    try:
        target = proxy.SMProxy
    except Exception:
        target = None
    for rep in list(getattr(view, "Representations", []) or []):
        try:
            inp = rep.Input
        except Exception:
            continue
        if inp is None:
            continue
        try:
            if inp is proxy or (target is not None and inp.SMProxy is target):
                return rep
        except Exception:
            continue
    return None


def _existing_rep(proxy, view):
    """Fast, non-creating lookup of the rep already showing ``proxy`` in
    ``view``. ``servermanager.GetRepresentation`` is ParaView's C++
    ``view.FindRepresentation`` map lookup (O(1)) — it returns None when there
    is no rep (it never creates one; creation lives only in the pvsimple
    wrapper via the controller) and finds both our manually-registered leaf and
    any stock composite. The O(N) Python scan is only a fallback if it errors.
    This keeps the patched Show/GetRepresentation O(1), so the app's per-view
    fan-outs (z-scale, representation-type) don't go quadratic at high rep
    counts — the very workload this fix enables."""
    try:
        return _sm.GetRepresentation(proxy, view)
    except Exception:
        return _find_rep(proxy, view)


def _ensure_leaf(proxy, view):
    """Return the existing rep for (proxy, view), else build a leaf
    ``SurfaceRepresentation``, register it and attach it to the view. Returns
    None only if the leaf proxy can't be created (caller then falls back to the
    original composite path)."""
    existing = _existing_rep(proxy, view)
    if existing is not None:
        return existing
    pxm = _sm.ProxyManager()
    leaf_sm = pxm.NewProxy("representations", "SurfaceRepresentation")
    if leaf_sm is None:
        return None
    leaf = _sm._getPyProxy(leaf_sm)
    try:
        leaf.Input = proxy
    except Exception:
        return None
    _counter[0] += 1
    try:
        pxm.RegisterProxy("representations", "FesppLeafRep%d" % _counter[0], leaf_sm)
    except Exception:
        pass
    try:
        view.Representations.append(leaf)
        leaf.UpdateVTKObjects()
        view.UpdateVTKObjects()
    except Exception:
        return None
    return leaf


# ---------------------------------------------------------------------------
# Patched pvsimple entry points (signatures mirror paraview.simple.rendering)

def _patched_get_representation(proxy=None, view=None):
    view = view if view is not None else pvsimple.GetActiveView()
    proxy = proxy if proxy is not None else pvsimple.GetActiveSource()
    if view is None or proxy is None:
        return _orig["GetRepresentation"](proxy, view)
    rep = _ensure_leaf(proxy, view)
    return rep if rep is not None else _orig["GetRepresentation"](proxy, view)


def _patched_show(proxy=None, view=None, representationType=None, **params):
    if proxy is None:
        proxy = pvsimple.GetActiveSource()
    if view is None:
        view = pvsimple.GetActiveView()
    if view is None or proxy is None:
        return _orig["Show"](proxy, view, representationType, **params)
    rep = _ensure_leaf(proxy, view)
    if rep is None:
        return _orig["Show"](proxy, view, representationType, **params)
    try:
        rep.Visibility = 1
    except Exception:
        pass
    if representationType is not None:
        try:
            rep.Representation = representationType
        except Exception:
            pass
    for key, value in params.items():
        try:
            setattr(rep, key, value)
        except Exception:
            pass
    try:
        rep.SMProxy.UpdateVTKObjects()
    except Exception:
        pass
    return rep


def install():
    """Redirect ``pvsimple.Show`` / ``GetRepresentation`` /
    ``GetDisplayProperties`` to build leaf representations. Idempotent; call
    once at engine startup, before any source is shown."""
    for name, fn in (
        ("Show", _patched_show),
        ("GetRepresentation", _patched_get_representation),
        ("GetDisplayProperties", _patched_get_representation),
    ):
        if name not in _orig:
            _orig[name] = getattr(pvsimple, name)
        setattr(pvsimple, name, fn)
    return True


def is_installed() -> bool:
    return bool(_orig)


# ---------------------------------------------------------------------------
# Opt-out + leaf-safe replacements for the composite-only API

def show_composite(proxy=None, view=None):
    """Create the FULL composite representation (the pre-patch behaviour).
    Use for Text/Billboard/Flagpole reps (e.g. the wellhead) whose display
    properties a leaf ``SurfaceRepresentation`` does not expose."""
    show = _orig.get("Show", pvsimple.Show)
    return show(proxy, view)


def color_by(rep, association, array):
    """Leaf-safe ``pvsimple.ColorBy(rep, (association, array))``: bind the array
    + its lookup table directly (the composite's ``SetScalarColoring`` is absent
    on a leaf). Returns the lookup table."""
    if rep is None:
        return None
    lut = pvsimple.GetColorTransferFunction(array)
    try:
        rep.ColorArrayName = [association, array]
        rep.LookupTable = lut
        rep.MapScalars = 1
        rep.SMProxy.UpdateVTKObjects()
    except Exception:
        pass
    return lut


def uncolor(rep):
    """Leaf-safe ``pvsimple.ColorBy(rep, None)`` / ``SetScalarColoring('', 0)``:
    clear the colour array so the rep falls back to its solid tint. (Setting
    ``ColorArrayName = ['', '']`` raises on an empty association, so use a valid
    association with an empty array name.)"""
    if rep is None:
        return
    try:
        rep.ColorArrayName = ["POINTS", ""]
        rep.SMProxy.UpdateVTKObjects()
    except Exception:
        pass


def range_is_pinned(lut):
    """True when the user pinned this LUT's scalar range (the COE
    Min/Max Apply). The pin IS a ParaView property —
    ``AutomaticRescaleRangeMode == 'Never'`` on the LUT proxy — so it
    travels with the scoped LUT (per view × array), needs no side
    bookkeeping, and every auto-rescale helper can honour it. The enum
    stringifies WITH quotes, so test membership, not equality."""
    try:
        return "Never" in str(getattr(lut, "AutomaticRescaleRangeMode", ""))
    except Exception:
        return False


def rescale_to_range(rep):
    """Leaf-safe ``rep.RescaleTransferFunctionToDataRange(True)``: read the
    range of the rep's currently bound colour array off the rep input and
    rescale the rep's lookup table. For a multi-component (vector/tensor) array
    it honours the LUT's vector mode — magnitude vs a specific component — the
    same as ParaView's rescale, so vectors don't paint flat. Stands down on a
    user-pinned LUT (`range_is_pinned`) — the range is still computed and
    returned, just not applied. Returns (lo, hi) or None."""
    if rep is None:
        return None
    try:
        assoc, array = rep.ColorArrayName[0], rep.ColorArrayName[1]
        if not array or assoc not in ("POINTS", "CELLS"):
            return None
        info = rep.Input.GetDataInformation()
        attrs = (info.GetPointDataInformation() if assoc == "POINTS"
                 else info.GetCellDataInformation())
        array_info = attrs.GetArrayInformation(array)
        if array_info is None:
            return None
        lut = rep.LookupTable
        # A ParaView enumeration property stringifies WITH quotes
        # ("'Magnitude'"), so test membership, not equality.
        vmode = str(getattr(lut, "VectorMode", "Magnitude"))
        if array_info.GetNumberOfComponents() <= 1:
            lo, hi = array_info.GetComponentRange(0)
        elif "Magnitude" in vmode:
            lo, hi = array_info.GetComponentRange(-1)   # -1 == magnitude
        else:
            try:
                comp = int(str(getattr(lut, "VectorComponent", 0)).strip("'\" "))
            except Exception:
                comp = 0
            lo, hi = array_info.GetComponentRange(comp)
        if lut is not None and not range_is_pinned(lut):
            lut.RescaleTransferFunction(lo, hi)
        return (lo, hi)
    except Exception:
        return None


def scalar_bar_visibility(lut, view, visible):
    """Leaf-safe ``rep.SetScalarBarVisibility(view, visible)``: toggle the
    colour legend for ``lut`` in ``view`` (the same GetScalarBar path IjkGrid
    already uses). Pass the SAME lookup table the rep is wired to — e.g.
    ``display.LookupTable`` after any per-view scene-LUT swap — so per-view
    scalar bars track correctly. Returns True if it acted (so a caller can
    ``break`` after the first display that carries a lookup table)."""
    try:
        if lut is None or view is None:
            return False
        pvsimple.GetScalarBar(lut, view).Visibility = 1 if visible else 0
        return True
    except Exception:
        return False
