"""What a path of the tree IS — one answer for the whole application.

"Is this path a property?", "which representation does it belong to?" and
"what is it called?" were written five or six ways across the app layer,
the dispatchers, the health check and the scenario runner, and the copies
disagreed: a derived recipe had no representation for the app layer, a
multi-realization property whose name holds a space was missed by one name
rule, a type tested by "contains 'Property'" took in what is no property.
They are answered here, from the tree the reader built and the calculator's
store, and nowhere else (slice 1 of the overhaul, 16/10/2026,
doc/private/assainissement-2026-10-16/05-decisions-et-cible.md).

A path is an assembly path (``/data/_gridfolder_<uuid>/...``) or a derived
recipe (``derived://<rep path>#<name>``, see derived_props). No function
here raises: an unknown path is "not a property", has no representation
(``""``) and no title (``""``).

The reader's series nodes: a property met once per realization, or per
realization and time step, is folded by FESPP into ONE synthetic node typed
``MultiRealization`` / ``MultiRealizationTimeSeries``, whose ``title`` is
the VTK array name it made and whose ``propTitle`` is the property's name
in the file. A ``TimeSeries`` node carries its name in ``title``.
"""
from fespp_on_trame.engine import node_kinds
from fespp_on_trame.engine.utils.naming import make_valid_vtk_name

#: the type a derived recipe answers to (it is no node of the tree)
DERIVED_KIND = "DerivedProperty"

#: the reader's nodes folding the time steps or realizations of a property
SERIES_KINDS = ("TimeSeries", "MultiRealization", "MultiRealizationTimeSeries")


def _derived():
    from fespp_on_trame.engine import derived_props
    return derived_props


def _node(tree, path):
    """The node id of an assembly path, None for none (or no tree)."""
    if tree is None or not path:
        return None
    try:
        return tree.find_node_id(path)
    except Exception as exc:
        print(f"[fespp] node facts: {path!r} not resolved: {exc}", flush=True)
        return None


def is_derived(path):
    """A derived recipe of the calculator (``derived://…``): no node of
    the tree, its values computed on its grid."""
    return _derived().is_derived(path)


def is_property_kind(kind):
    """A node type that carries values: a property leaf, a series node of
    the reader, or a derived recipe. A folder, a grid, a well, a feature or
    a marker has none."""
    return kind in node_kinds.PROPERTY_KINDS or kind == DERIVED_KIND


def kind_of(tree, path):
    """The node's type (``"ContinuousProperty"``, ``"IjkGrid"``…),
    ``DERIVED_KIND`` for a derived recipe, ``""`` for an unknown path."""
    if _derived().is_derived(path):
        return DERIVED_KIND
    nid = _node(tree, path)
    return (tree.find_type(nid) or "") if nid is not None else ""


def is_property(tree, path):
    """A path that carries values: a property leaf, a series node, or a
    derived recipe."""
    return bool(path) and is_property_kind(kind_of(tree, path))


def rep_path_for(tree, path):
    """The representation `path` belongs to: a property's parent
    representation, a representation itself, the grid a derived recipe is
    written on; ``""`` for a folder above any representation or an unknown
    path."""
    d = _derived()
    if d.is_derived(path):
        return d.parse_path(path)[0] or ""
    nid = _node(tree, path)
    if nid is None:
        return ""
    rid = tree.find_representation_node(nid)
    return (tree.find_path(rid) or "") if rid is not None else ""


def is_log(tree, path):
    """A well's log: a property of a log frame, a block of its own under
    it (read, it is drawn as a graph or a tube; never a cell of the frame)."""
    rep = rep_path_for(tree, path)
    return (bool(rep) and rep != path and is_property(tree, path)
            and kind_of(tree, rep) in node_kinds.LOG_FRAMES)


def log_view_focus(tree, path):
    """What the log view brings to its middle for the active node `path` of
    its tree: ``{"well": wellbore title, "curve": log title}`` — a log, its
    own track; any other node of a wellbore, that wellbore (``"curve": ""``)
    —; None for a node of no wellbore."""
    nid = tree.find_node_id(path) if path else None
    if nid is None:
        return None
    wid = nid if (tree.find_type(nid) or "") == "Wellbore" else tree.find_parent_node_id_with_type(nid, "Wellbore")
    if wid is None:
        return None
    return {"well": tree.find_title(wid) or "", "curve": (tree.find_title(nid) or "") if is_log(tree, path) else ""}


def frame_logs(tree, path):
    """The logs of the log frame at `path`, sorted; [] for a node that is no
    log frame."""
    nid = tree.find_node_id(path) if path else None
    if nid is None or kind_of(tree, path) not in node_kinds.LOG_FRAMES:
        return []
    out = []
    for child, _kids in tree.iter_nodes(nid):
        if child != nid:
            log = tree.find_path(child)
            if log and is_log(tree, log):
                out.append(log)
    return sorted(out)


def sampled_logs(tree, path, by_samples):
    """The logs a row of the Values view reading `path` is a sample of: the
    log itself, or every log of a log frame read sample by sample
    (`by_samples`); [] for anything else (a frame read log by log: a row is
    a log)."""
    if not path:
        return []
    if is_log(tree, path):
        return [path]
    return frame_logs(tree, path) if by_samples else []


def is_unread_log(tree, path, loaded):
    """A well's log not read: its own block is not loaded (`loaded`, the
    property paths read). Its frame read with other logs holds no values of
    it — the Values view offers to read it, never a table of NaN."""
    return is_log(tree, path) and path not in set(loaded or ())


def is_under(path, roots):
    """`path` is one of `roots` or lies under one of them."""
    return any(path == r or path.startswith(r + "/") for r in roots)


def title_of(tree, path):
    """The node's own title — a property's name as the tree shows it — or
    a derived recipe's name; ``""`` for none."""
    d = _derived()
    if d.is_derived(path):
        store = d.get_store()
        return (store.title(path) if store is not None else "") or ""
    nid = _node(tree, path)
    return (tree.find_title(nid) or "") if nid is not None else ""


def property_title(tree, path):
    """A property's name in the file: the ``propTitle`` of a series node
    (its ``title`` is the VTK name the reader made), the title otherwise,
    a derived recipe's name."""
    if _derived().is_derived(path):
        return title_of(tree, path)
    nid = _node(tree, path)
    if nid is None:
        return ""
    if (tree.find_type(nid) or "") in SERIES_KINDS:
        pt = tree.find_attribute_value(nid, "propTitle")
        if pt:
            return pt
    return tree.find_title(nid) or ""


def vtk_base_name(tree, path):
    """The VTK array name a property is read under, without the
    ``_real_<n>`` suffix one realization adds (realization_dispatch); a
    derived recipe's own array name; ``""`` for none."""
    d = _derived()
    if d.is_derived(path):
        store = d.get_store()
        rec = store.get(path) if store is not None else None
        return (rec or {}).get("vtk_name") or ""
    title = property_title(tree, path)
    return make_valid_vtk_name(title) if title else ""


def rep_title(tree, path):
    """The name a user knows the representation of `path` by — a
    property's grid, a derived recipe's grid, a representation itself — by
    the tree's own rule (``Tree.find_rep_title``: a grid's geometry leaf,
    titled "SolidColor", by its grid); the last segment of the rep path
    when the tree has no title; ``""`` when `path` has no representation."""
    rp = rep_path_for(tree, path)
    if not rp:
        return ""
    rid = _node(tree, rp)
    title = (tree.find_rep_title(rid) or "") if rid is not None else ""
    return title or rp.rstrip("/").rsplit("/", 1)[-1]


def display_title(tree, path, fallback=""):
    """The name to SHOW for a node of a representation: a grid's geometry
    leaf, titled "SolidColor" under the grid's properties folder, is named
    by its grid folder, which is what the reader calls the grid."""
    name_path = (path or "").split("/_propsfolder_", 1)[0]
    nid = _node(tree, name_path)
    return ((tree.find_title(nid) or "") if nid is not None else "") or fallback


def unit_of(tree, path):
    """The unit of measure the file declares for a property (the ``uom``
    FESPP writes on the node), or the one a derived recipe was given; the
    reader's series nodes carry none; ``""`` for none."""
    d = _derived()
    if d.is_derived(path):
        store = d.get_store()
        rec = store.get(path) if store is not None else None
        return (rec or {}).get("uom") or ""
    nid = _node(tree, path)
    return (tree.find_attribute_value(nid, "uom") or "") if nid is not None else ""
