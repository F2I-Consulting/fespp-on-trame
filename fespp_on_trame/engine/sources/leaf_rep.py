"""Leaf representations: show each source with a bare surface representation.

Why
---
Every ``pvsimple.Show`` / ``GetRepresentation`` builds a *composite*
representation (``vtkSMPVRepresentationProxy``). That composite eagerly creates
a ``vtkSelectionRepresentation`` -> ``vtkDataLabelRepresentation`` whose two
``vtkLabeledDataMapper`` constructors each hard-code ``AllocateLabels(50)``, so
**100 real ``vtkTextMapper`` objects per representation**, each dragging a cell
array and a pipeline executive, *even though this app never shows ParaView data
labels* (selection is driven by the tree). With one representation per source
(the deliberate N-source design, kept for type-specific filters), loading a
hundred or more sources floods the glibc heap arena with hundreds of thousands
of tiny objects until a small ``new`` throws ``std::bad_alloc`` while plenty of
RAM is free: arena fragmentation, not a memory limit.

How
---
Show a **leaf** representation instead: a bare ``SurfaceRepresentation``
(``vtkSMRepresentationProxy``) with no selection or label sub-representations,
more than an order of magnitude lighter than the composite. ``install()``
monkeypatches the three pvsimple entry points the app uses (``Show`` /
``GetRepresentation`` / ``GetDisplayProperties``) so the swap is global and
every call site benefits unchanged: a leaf carries all the display properties
the app sets (``Representation``, ``DiffuseColor``, ``Scale``, ``Opacity``,
``Visibility``, ``EdgeColor`` …) and, once appended to the view,
``GetRepresentation`` returns *it*, so code that fetches the display and
mutates it is unaffected. ``pvsimple.Hide`` and ``pvsimple.Delete(source)``
also work and clean the leaf up without a leak.

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
    ``view``.

    ``servermanager.GetRepresentation`` is ParaView's C++
    ``view.FindRepresentation`` map lookup (O(1)): it returns None when there
    is no rep (it never creates one; creation lives only in the pvsimple
    wrapper via the controller) and finds both our manually registered leaf and
    any stock composite. The O(N) Python scan is only a fallback if it errors.
    This keeps the patched Show/GetRepresentation O(1), so the app's per-view
    fan-outs (z-scale, representation type) do not go quadratic at the high
    rep counts that leaf representations make possible."""
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
    # BlockScope: a leaf must be born INVISIBLE. The composite main_rep is
    # the only renderer, and lookups like GetDisplayProperties (colour
    # fan-out) reach here and would otherwise paint strays over it. A caller
    # that wants the leaf on screen Shows it explicitly (sets Visibility).
    try:
        leaf.Visibility = 0
    except Exception:
        pass
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


# ---------------------------------------------------------------------------
# Opt-out + leaf-safe replacements for the composite-only API

def show_composite(proxy=None, view=None):
    """Create the FULL composite representation (stock ``pvsimple.Show``).

    Use for Text/Billboard/Flagpole reps (e.g. the wellhead) whose display
    properties a leaf ``SurfaceRepresentation`` does not expose. A leaf a
    display lookup left for (proxy, view) is taken out first: the stock Show
    hands back the representation the view already holds, and the caller
    would be given that leaf for a composite."""
    show = _orig.get("Show", pvsimple.Show)
    if proxy is not None and view is not None:
        held = _existing_rep(proxy, view)
        if held is not None and held.GetXMLName() == "SurfaceRepresentation":
            try:
                held.Visibility = 0
                pvsimple.Delete(held)
            except Exception as exc:
                print(f"[fespp] leaf rep of {proxy.GetXMLName()} not taken out: {exc!r}", flush=True)
    return show(proxy, view)


def range_is_pinned(lut):
    """True when the user pinned this LUT's scalar range (the colour
    editor's Min/Max Apply).

    The pin IS a ParaView property, ``AutomaticRescaleRangeMode == 'Never'``
    on the LUT proxy, so it travels with the scoped LUT (per view × array),
    needs no side bookkeeping, and every auto-rescale helper can honour it.
    The enum stringifies WITH quotes, so test membership, not equality."""
    try:
        return "Never" in str(getattr(lut, "AutomaticRescaleRangeMode", ""))
    except Exception:
        return False


def rescale_to_range(rep):
    """Leaf-safe ``rep.RescaleTransferFunctionToDataRange(True)``.

    Reads the range of the rep's currently bound colour array off the rep
    input and rescales the rep's lookup table. For a multi-component
    (vector/tensor) array it honours the LUT's vector mode (magnitude or a
    specific component), the same as ParaView's rescale, so vectors do not
    paint flat. On a user-pinned LUT (`range_is_pinned`) the range is still
    computed and returned but not applied. Returns (lo, hi) or None."""
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

