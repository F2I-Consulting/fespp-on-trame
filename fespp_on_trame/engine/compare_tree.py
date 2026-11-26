"""The docked tree of the Statistics view: kind -> representation -> property,
then the parts of the grids.

Every property the file holds is listed before it is read: the assembly says
its kind, its representation and its title, so a leaf costs no read and says
whether the session has its values. A tick means a load (`tick_plan`), what is
waited for turns failed when the load cycle is over (`settle_pending`). What a
path is comes from engine/compare_dispatch, its facts and its load states.

Pure: no trame, no ParaView at import time.
"""
from xml.sax.saxutils import quoteattr

from fespp_on_trame.engine import compare_dispatch as cd
from fespp_on_trame.engine import derived_props
from fespp_on_trame.engine import node_kinds
from fespp_on_trame.engine import stats_supports
from fespp_on_trame.engine import tree_families

NO_REP = "no representation"
#: the title of the docked tree's folder that lists the parts of a grid
PARTS_KIND = "Parts of a grid"

#: The node kinds the tree widget draws as ONE leaf without recursing their
#: children (a multi-realization property and its per-realization members).
_COLLAPSED_KINDS = ("MultiRealization", "MultiRealizationTimeSeries")

_ROOT_TAG = "compare"
#: the path of that folder: every part of the docked tree lies under it
PARTS_FOLDER = f"/{_ROOT_TAG}/parts"


def assembly_property_paths(tree):
    """Every property the FILE holds, loaded or not — one walk of the
    assembly (Tree.iter_nodes, the walk the health findings take too). The
    kind, the representation and the title are attributes the reader wrote
    on the node: listing them costs no read at all, which is what lets the
    Statistics tree be full the moment it opens. A partial stub (a reference
    whose target is elsewhere) has no values behind it and is left out."""
    from fespp_on_trame.engine import element_type
    out = []
    if tree is None:
        return out
    try:
        nodes = tree.iter_nodes()
    except Exception as exc:
        print("[fespp] the docked tree: the assembly not read:", exc, flush=True)
        return out
    skip = set()
    for nid, children in nodes:
        if nid in skip:
            skip.update(children)
            continue
        try:
            ntype = tree.find_type(nid) or ""
        except Exception as exc:
            print(f"[fespp] the docked tree: node {nid} not read:", exc, flush=True)
            continue
        if ntype in _COLLAPSED_KINDS:
            # ONE leaf per multi-realization property, as the widget draws
            # it: the per-realization children carry the very same title,
            # and their paths are not what a selection is made of
            skip.update(children)
        # the tracking BUCKET, not a list of kinds: `ui_loaded_array_paths`
        # — what says whether a property has been read — only ever holds the
        # kinds whose element type tracks as an array, so any other kind
        # would be offered as a leaf that can never be shown as loaded
        if (element_type.for_kind(ntype).tracking_bucket()
                != element_type.BUCKET_ARRAY):
            continue
        try:
            if (tree.find_title(nid) or "").startswith(
                    node_kinds.PARTIAL_PREFIX):
                continue
            path = tree.find_path(nid) or ""
        except Exception as exc:
            print(f"[fespp] the docked tree: node {nid} not read:", exc, flush=True)
            continue
        if path:
            out.append(path)
    return out


def load_state(path, loaded, pending=None):
    """What the session has of `path`: LOADED, or what it is waiting on.
    `loaded=None` means every listed path is loaded (the caller lists
    nothing else)."""
    if loaded is None or path in loaded:
        return cd.LOADED
    st = (pending or {}).get(path) or ""
    return st if st in (cd.LOADING, cd.FAILED) else cd.UNLOADED


def _say_load_state(attrs, path, loaded, pending):
    """The `loadState` and the sentence of a leaf whose values are not there;
    a loaded one carries neither."""
    st = load_state(path, loaded, pending)
    if st:
        attrs["loadState"] = st
        attrs["info"] = cd._LOAD_INFO[st]


def _owners(tree, rep):
    """What the plugin says `rep` is the interpretation of, on the first node of
    its path that says it: what the widget lays the rows out by."""
    parts = str(rep or "").split("/")
    for i in range(3, len(parts) + 1):
        nid = tree.find_node_id("/".join(parts[:i]))
        uuid = tree.find_attribute_value(nid, "interpretation") if nid is not None else ""
        if uuid:
            return {name: tree.find_attribute_value(nid, name) or ""
                    for name in ("interpretation", "interpretationTitle", "feature", "featureTitle")}
    return {}


def kind_tree_xml(tree, array_paths, loaded=None, pending=None, parts=None, by_kind=True):
    """(xml, path_map) of the selection tree over the property paths given;
    `by_kind` False: with no kind folder, the representations on one level, each
    saying what it is the interpretation of.
    The widget builds a node's path as "/<root tag>/<tag>/<tag>…" from the
    element tag names, so `path_map` maps exactly those synthetic paths
    ("/compare/k0/r0/p0") to the real array path; tag names are ids, unique
    per level, titles carry the display names. Kinds and reps come out in
    first-appearance order — the widget sorts siblings by title itself.

    `loaded` (a set, None = all of them) and `pending` (path -> LOADING /
    FAILED) put a `loadState` on the leaves whose values are not there: a
    property is offered before it is read, and the leaf says so.

    Every rep folder carries its `family` (`rep_family`), the tab the data
    tree would file it under; `tree_tabs` turns the xml into the tab list
    the widget draws.

    `parts` (`stats_supports.assembly_parts`, the paths of the parts of a
    grid) are filed after the kinds, in one folder `PARTS_KIND`, under a rep
    folder per kind of part and family. Their leaves are `ComparePart`, in
    `path_map` like any leaf, named by `stats_supports.leaf_titles`; `loaded`
    says of them what it says of a property. An extract among them (`stats_supports.session_extracts`) has no
    box to tick, so no leaf: only its folder (`extract_folder`), under which
    the session hangs its row."""
    sd = cd._sd()
    # kind label -> rep path, or (kind of part, family) -> [(attrs, real path)]
    groups = {}
    rep_titles = {}
    rep_families = {}
    part_titles = stats_supports.leaf_titles(tree, parts or ())
    for path in array_paths or []:
        if not path:
            continue
        title, ptype = sd._title_and_kind(tree, path)
        if not title and not ptype:
            continue  # nothing behind that path: no leaf to tick
        # an untitled node still gets a leaf named after its path tail — a
        # property absent from the tree could never be ticked at all
        title = title or path.rsplit("/", 1)[-1]
        rep = cd._rep_path(tree, path)
        kind = cd._kind_label(tree, path)
        # `eye`: the widget draws the data tree's visibility eye on a leaf
        # that declares one. Which leaves may carry it is the host's call
        # (`eye_paths` = the properties the session holds), not the type's.
        attrs = {"type": "CompareItem", "title": title, "propType": ptype,
                 "eye": "array"}
        _say_load_state(attrs, path, loaded, pending)
        if derived_props.is_derived(path):
            # a recipe: nothing to read or unload, so no box; its eye holds it
            attrs["noCheck"] = "1"
        uom = sd._unit_for_array_path(tree, path)
        if uom:
            attrs["units"] = uom
        cc = cd._attr(tree, path, "componentCount")
        if cc:
            attrs["componentCount"] = cc
        groups.setdefault(kind, {}).setdefault(rep, []).append((attrs, path))
        rep_titles.setdefault(rep, cd._rep_title(tree, path) or rep)
        rep_families.setdefault(rep, cd.rep_family(tree, rep))
    for part in parts or []:
        label, family = stats_supports.kind_label(tree, part), _part_family(tree, part)
        folder = (label, family)
        leaves = groups.setdefault(PARTS_KIND, {}).setdefault(folder, [])
        rep_titles[folder], rep_families[folder] = label, family
        if stats_supports.is_extract(part):
            continue
        # `propType`: the leaf wears the drawing of what it is, as a property does
        attrs = {"type": "ComparePart", "title": part_titles[part],
                 "propType": sd._title_and_kind(tree, part)[1], "eye": "array"}
        _say_load_state(attrs, part, loaded, pending)
        leaves.append((attrs, part))

    def _el(tag, attrs, children=None):
        head = " ".join(f"{k}={quoteattr(str(v))}" for k, v in attrs.items())
        if children:
            return f"<{tag} {head}>{''.join(children)}</{tag}>"
        return f"<{tag} {head} />"

    path_map = {}
    root = f"/{_ROOT_TAG}"
    k_i = r_i = p_i = 0
    kind_els = []

    def _rep_el(rep, leaves, parent):
        """A representation's folder under `parent`, its leaves under it."""
        nonlocal r_i, p_i
        r_tag = _extract_tag(rep_families[rep])
        if leaves:
            r_tag = f"r{r_i}"
            r_i += 1
        leaf_els = []
        for attrs, path in leaves:
            p_tag = f"p{p_i}"
            p_i += 1
            path_map[f"{parent}/{r_tag}/{p_tag}"] = path
            leaf_els.append(_el(p_tag, attrs))
        # `family`: the tab of the data tree this representation would
        # sit in. The widget files a node under the tab whose name its
        # `family` says, which is how a tree of synthetic folders gets
        # the Reservoir / Surface / Well filter of the data tree without
        # the widget learning what a RepFolder is; a kind folder shows in
        # every tab one of its reps belongs to (the widget keeps the
        # ancestors of a match), a property inherits its rep's.
        rep_attrs = {"type": "RepFolder",
                     "title": rep_titles.get(rep) or rep or NO_REP,
                     "family": rep_families[rep]}
        if not by_kind and rep != NO_REP:
            rep_attrs.update(_owners(tree, rep))
        # nothing under it to tick: a box would be a click that does nothing
        if all(attrs.get("noCheck") for attrs, _path in leaves):
            rep_attrs["noCheck"] = "1"
        return _el(r_tag, rep_attrs, leaf_els)

    if not by_kind:
        # the reps of every kind on one level
        merged, kept = {}, {}
        for kind, reps in groups.items():
            if kind == PARTS_KIND:
                kept[kind] = reps
                continue
            for rep, leaves in reps.items():
                merged.setdefault(rep, []).extend(leaves)
        kind_els = [_rep_el(rep, leaves, root) for rep, leaves in merged.items()]
        groups = kept
    for kind, reps in groups.items():
        k_tag = PARTS_FOLDER.rsplit("/", 1)[-1]
        if kind != PARTS_KIND:
            k_tag = f"k{k_i}"
            k_i += 1
        rep_els = []
        boxes = False
        for rep, leaves in reps.items():
            boxes = boxes or not all(attrs.get("noCheck") for attrs, _path in leaves)
            rep_els.append(_rep_el(rep, leaves, f"{root}/{k_tag}"))
        kind_attrs = {"type": "KindFolder", "title": kind}
        if not boxes:
            kind_attrs["noCheck"] = "1"
        if kind == PARTS_KIND:
            kind_attrs["sortLast"] = "1"
        kind_els.append(_el(k_tag, kind_attrs, rep_els))
    xml = f"<{_ROOT_TAG}>{''.join(kind_els)}</{_ROOT_TAG}>"
    return xml, path_map


def _part_family(tree, part):
    """The tab a part of a grid is filed under: its own place in the assembly,
    its grid's for an extract."""
    return cd.rep_family(tree, stats_supports.grid_rep_of(tree, part) or part)


def _extract_tag(family):
    return f"x{family}"


def extract_folder(tree, part):
    """The docked tree's folder the row of the extract `part` hangs under."""
    return f"{PARTS_FOLDER}/{_extract_tag(_part_family(tree, part))}"


def tree_tabs(xml):
    """The tabs the docked tree draws over `xml`: the data tree's
    families, in its order and whatever the file holds — a family the file
    has nothing of is an empty tab that says so, not a missing one — plus
    `Other` only while a rep folder carries it, so nothing the tree lists is
    out of every tab. The widget keeps a node whose `family` is the tab's
    name; `types` stays empty, a synthetic folder has no assembly type."""
    import xml.etree.ElementTree as ET
    names = list(tree_families.NAMES)
    try:
        root = ET.fromstring(xml) if xml else None
    except ET.ParseError as exc:
        print("[fespp] the docked tree: its xml not read:", exc, flush=True)
        root = None
    if root is not None and any(
            el.get("family") == node_kinds.OTHER_FAMILY
            for el in root.iter() if el.get("type") == "RepFolder"):
        names.append(node_kinds.OTHER_FAMILY)
    return [{"name": name, "types": []} for name in names]


def families_present(xml):
    """The families a rep folder of `xml` is filed under, in the tabs'
    order: the Statistics view's family cards that have something to list."""
    names = [t["name"] for t in tree_tabs(xml)]
    if not xml:
        return []
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        print("[fespp] the docked tree: its xml not read:", exc, flush=True)
        return []
    held = {el.get("family") for el in root.iter() if el.get("type") == "RepFolder"}
    return [n for n in names if n in held]


def card_names():
    """The family cards of the Statistics view's tree: the data tree's, then
    Other (a rep the file holds outside them)."""
    return tuple(tree_families.NAMES) + (node_kinds.OTHER_FAMILY,)


def tick_plan(ticked, items, loaded, pending=None, max_load=None):
    """What a tick in the docked tree means — ``{"items", "to_load",
    "pending", "confirm"}``:

    - a ticked property with no item gets one (default realization and
      time), an unticked one loses every item it had;
    - a ticked property the session has not read yet is LOADED: `to_load`
      goes to the very channel the data tree writes, so the whole load
      pipeline and its cascades apply, and the property waits in `pending`
      meanwhile;
    - an untick NEVER unloads. A 3D view may well be showing that property;
      leaving a comparison is no reason to pull it out of the scene. The
      leaf then simply stops being ticked, still loaded.

    A derived recipe is never in `to_load`: it has no node to select, its
    values are the store's.

    `max_load` is the size above which ONE tick ASKS FIRST: a folder
    standing for more unread properties than that comes back whole in
    `confirm`, with the plan left EXACTLY as it was — no item joins, nothing
    is read — so the caller can state the number and act only on a yes (it
    then replays the same tick without a cap). Without a cap (the default)
    nothing waits for an answer. The threshold itself is
    `engine.tick_confirm.MAX_TICK_LOAD`, shared with every other tree."""
    order = [p for p in dict.fromkeys(ticked or ()) if p]
    loaded = set(loaded or ())
    pending = dict(pending or {})
    items = [it for it in (items or []) if it.get("path")]
    to_load = [p for p in order
               if p not in loaded and p not in pending
               and not derived_props.is_derived(p)]
    if max_load is not None and len(to_load) > max_load:
        # Nothing decided yet: the caller asks, and replays this very tick
        # uncapped on a yes. Leaving the items untouched is what makes
        # stepping back a no-op the user can trust.
        return {"items": items, "to_load": [], "pending": dict(pending),
                "confirm": to_load}
    on = set(order)
    kept = [it for it in items if it["path"] in on]
    have = {it["path"] for it in kept}
    waiting = {p: st for p, st in pending.items()
               if p in on and p not in loaded}
    waiting.update({p: cd.LOADING for p in to_load})
    return {"items": kept + [{"path": p, "real": None, "ts": None}
                             for p in order if p not in have],
            "to_load": to_load, "pending": waiting, "confirm": []}


def settle_pending(pending, loaded, finished=False):
    """``(pending, failed)`` once a load has run: what arrived stops
    waiting. When the load cycle is OVER (`finished`), what did not arrive
    is not waited on for ever — it turns FAILED, and its item says why
    instead of spinning."""
    loaded = set(loaded or ())
    out, failed = {}, []
    for path, st in (pending or {}).items():
        if path in loaded:
            continue
        if finished and st == cd.LOADING:
            failed.append(path)
            st = cd.FAILED
        out[path] = st
    return out, failed
