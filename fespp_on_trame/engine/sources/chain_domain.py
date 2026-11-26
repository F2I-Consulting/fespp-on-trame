"""The domain of a threshold chain entry (overhaul slice 7).

The kind of an array as the tree and the data say it (`resolve_chain_kind`:
Continuous, Discrete or Categorical), the slider's domain (`chain_domain`),
the integer NullValue sentinels of inactive cells, the distinct values a
discrete slider is built from. The isolates (`ijkgrid`, whose
`_IjkChainEntry` is one filter of a grid's threshold chain), the categorical
palette and the threshold cards read them here.
"""
import re

from fespp_on_trame.engine import node_facts
from fespp_on_trame.engine.blockscope import assembly_index
from fespp_on_trame.engine.utils.naming import make_valid_vtk_name


# Max number of unique values for which an array is treated as
# Categorical / Discrete in the threshold UI. Beyond that the slider
# becomes unreadable (too many ticks), so the entry degrades to
# Continuous and is still thresholded through its low / high bounds.
_MAX_DISCRETE_UNIQUES = 64


def resolve_chain_kind(tree, rep_path, array_name, source_proxy, assoc,
                       reader=None):
    """Property kind, unique-value list and categorical labels for a
    fresh chain entry.

    Returns `(kind, unique_values, labels)`:

      - `kind` is `"Continuous"` / `"Discrete"` / `"Categorical"`,
        taken from the property type the tree reports for the node
        whose VTK array name matches `array_name`. Falls back to
        `"Continuous"` when the lookup fails, so the UI renders a plain
        range slider.
      - `unique_values` is the sorted list of distinct values found
        on the VTK array. Populated only for Discrete / Categorical.
        Capped to `_MAX_DISCRETE_UNIQUES`; an array exceeding the
        cap is demoted to `"Continuous"`.
      - `labels` is the `{value: label}` mapping of a Categorical
        property: the LUT's annotations, else the file's string lookup
        through `reader` (`utils.categories`). Empty otherwise."""
    kind = _kind_from_tree(tree, rep_path, array_name)
    if kind == "Continuous":
        return ("Continuous", [], {})

    uniques = _scan_unique_values(source_proxy, array_name, assoc)
    if not uniques or len(uniques) > _MAX_DISCRETE_UNIQUES:
        return ("Continuous", [], {})

    labels = {}
    if kind == "Categorical":
        from fespp_on_trame.engine.utils import categories
        labels = categories.labels_for(
            tree, categories.array_path_for_vtk_name(tree, rep_path, array_name),
            array_name, reader)
    return (kind, uniques, labels)


# RESQML integer properties cannot carry NaN, so writers declare
# `<NullValue>` = INT32_MAX (or the int64 / MIN variants) for inactive
# cells, and FESPP delivers those cells verbatim in the VTK array: the
# array's `GetRange()` then reaches 2147483647. Only the double-array
# path gets the C++ integer-null to NaN conversion.
INT_NULL_SENTINELS = frozenset({
    float(2 ** 31 - 1), float(-(2 ** 31)),
    float(2 ** 63 - 1), float(-(2 ** 63)),
})


def is_null_sentinel(value):
    """True when `value` is a RESQML integer NullValue sentinel (an
    inactive cell, never a real category)."""
    try:
        return float(value) in INT_NULL_SENTINELS
    except (TypeError, ValueError):
        return False


def chain_domain(kind, unique_values, labels, fallback_range):
    """Slider domain plus cleaned uniques / labels for a fresh chain entry.

    The NullValue sentinel (see `INT_NULL_SENTINELS`) lands in the raw
    array range and would stretch a categorical threshold slider over
    ±2^31, collapsing the real categories into the first pixels of the
    track with their tick labels piled up. Discrete / Categorical: drop
    the sentinels from the unique scan and the label map; a Categorical
    entry with labels additionally spans ALL annotated keys, so every
    lookup category gets a tick whether present in the data or not.
    Continuous passes through untouched (float nulls are NaN and never
    reach `GetRange()`).

    Returns `(range, unique_values, labels)`."""
    if kind == "Continuous":
        return fallback_range, list(unique_values or []), dict(labels or {})
    cleaned = [v for v in (unique_values or []) if not is_null_sentinel(v)]
    kept_labels = {
        k: v for k, v in (labels or {}).items() if not is_null_sentinel(k)
    }
    domain_values = set(cleaned)
    if kind == "Categorical" and kept_labels:
        domain_values |= set(kept_labels)
    if not domain_values:
        return fallback_range, cleaned, kept_labels
    lo = float(min(domain_values))
    hi = float(max(domain_values))
    if hi <= lo:
        # Degenerate single-category domain: VRangeSlider needs a
        # non-zero span to place its thumbs.
        hi = lo + 1.0
    return (lo, hi), cleaned, kept_labels


def _kind_in_subtree(tree, root_id, sanitized):
    """Property TYPE of the property whose sanitized title is `sanitized`
    anywhere under `root_id`, or None when there is no match."""
    from fespp_on_trame.engine import element_type
    for nid in tree.find_all_descendant_ids(root_id):
        try:
            kind = tree.find_type(nid) or ""
        except Exception:
            continue
        if not element_type.for_kind(kind).is_property():
            continue
        title = tree.find_title(nid) or ""
        if element_type.for_kind(kind).is_multi_realization():
            pt = tree.find_attribute_value(nid, "propTitle")
            if pt:
                title = pt
        if make_valid_vtk_name(title) != sanitized:
            continue
        # Multi-realization / time series: the kind is the container's,
        # the threshold UI needs the embedded property type.
        if kind in node_facts.SERIES_KINDS:
            pk = tree.find_prop_type(nid) or ""
            return _normalise_kind(pk)
        return _normalise_kind(kind)
    return None


def _kind_from_tree(tree, rep_path, array_name):
    """Property type of the node under the rep whose title (or propTitle
    for a multi-realization property) matches `array_name`.

    A grid's properties are SIBLINGS of its geometry rep (both sit under
    the GridContainer's PropertiesFolder), so the rep's own subtree is
    empty for a grid and the walk retries from the enclosing
    GridContainer. A non-grid rep has no GridContainer ancestor, and the
    retry only runs after the rep's own subtree missed. Without it every
    grid Discrete / Categorical property would fall back to "Continuous"
    and get a plain range slider.

    Mirrors `threshold_dispatch._find_property_path_by_title`, inlined
    so that extract_block does not import engine.threshold_dispatch."""
    if tree is None or not rep_path or not array_name:
        return "Continuous"
    try:
        rep_id = tree.find_node_id(rep_path)
    except Exception:
        return "Continuous"
    if rep_id is None:
        return "Continuous"
    # Strip the realization suffix `_real_<idx>` so a multi-realization
    # array matches its property node by propTitle. Other arrays carry
    # no suffix, so this is a no-op for them.
    bare = re.sub(r"_real_\d+$", "", array_name)
    sanitized = make_valid_vtk_name(bare)
    kind = _kind_in_subtree(tree, rep_id, sanitized)
    if kind is not None:
        return kind
    try:
        container = tree.find_parent_node_id_with_type(rep_id, "GridContainer")
    except Exception:
        container = None
    if container is not None:
        kind = _kind_in_subtree(tree, container, sanitized)
        if kind is not None:
            return kind
    return "Continuous"


def _normalise_kind(kind_str):
    """Map a property-type string to one of the three threshold UI
    kinds. Anything unrecognised maps to Continuous."""
    if not kind_str:
        return "Continuous"
    s = kind_str.lower()
    if "categorical" in s:
        return "Categorical"
    if "discrete" in s:
        return "Discrete"
    return "Continuous"


def _scan_unique_values(source_proxy, array_name, assoc):
    """Sorted distinct values of the source's CellData or PointData
    array, used to populate the slider ticks of Discrete / Categorical
    entries.

    Returns an empty list on failure (no array, no client-side object)
    or past `_MAX_DISCRETE_UNIQUES` values; the caller then demotes the
    entry to Continuous."""
    if source_proxy is None or not array_name:
        return []
    try:
        client = source_proxy.GetClientSideObject()
        out = client.GetOutputDataObject(0)
    except Exception:
        return []
    inner = assembly_index.inner(out)
    if inner is None:
        return []
    store = None
    if assoc == "POINTS" and hasattr(inner, "GetPointData"):
        store = inner.GetPointData()
    elif hasattr(inner, "GetCellData"):
        store = inner.GetCellData()
    if store is None:
        return []
    arr = store.GetArray(array_name)
    if arr is None:
        return []
    # the one distinct-values rule (engine/ranges), vectorised: NaN is not
    # a category, past the cap the entry is continuous
    from fespp_on_trame.engine import ranges
    out = ranges.distinct(arr, cap=_MAX_DISCRETE_UNIQUES)
    if not out:
        return []
    # Integer-valued floats become ints so the UI labels read "3",
    # not "3.0".
    return [int(v) if float(v).is_integer() else v for v in out]
