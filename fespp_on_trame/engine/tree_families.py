"""The families a view's tree is cut into, one tree card each — the grids, the
surfaces, the wells, the seismic — and which of them the loaded data holds.

ONE table for both ends: the tree widget files a row under a family by its
node type (`tabs`, a container counted as the geometry it wraps), the toolbar
greys the card of a family the data does not hold.

The Seismic family is filed by ROW: an IJK grid whose geometry is a lattice
(a velocity model, a seismic cube) has the node type of a reservoir grid, so
its row says where it goes — `lattice`, the rows of those grids
(app/features/time_depth_models, ``ui_cube_grid_rows``). The Seismic tab
takes them with what they hold, the Reservoir tab leaves them out.
"""
import re
import xml.etree.ElementTree as ET

from fespp_on_trame.engine import node_facts, node_kinds

SEISMIC = "tree_seismic"
_CARD = {"Reservoir": "tree", "Surface": "tree_surface", "Well": "tree_well",
         node_kinds.SEISMIC_FAMILY: SEISMIC}
# (card key, title, the node types filed there): node_kinds.FAMILIES, keyed;
# then Seismic, which lists no type
FAMILIES = (tuple((_CARD[name], name, types) for name, types in node_kinds.FAMILIES)
            + ((SEISMIC, node_kinds.SEISMIC_FAMILY, ()),))
KEYS = tuple(key for key, _title, _types in FAMILIES)
NAMES = tuple(title for _key, title, _types in FAMILIES)
# the Log ↔ Grid panel's cards: a surface has no value to set a log against
LOG_GRID = ("Reservoir", "Well")
# the tab the lattice grids leave for the Seismic one
_LEFT = "Reservoir"

_TYPE = re.compile(r'\btype="([A-Za-z0-9_]+)"')
_present = {}


def name_of(tree, nid):
    """The NAME of the family the node `nid` is filed under, "" when none
    files it: Seismic for the row of a lattice grid (`tree.lattice_rows`),
    else its type's. ONE rule for whatever sorts by family: the data tree's
    cards, the Statistics tree, the legends, the assistant's catalogue."""
    rows = getattr(tree, "lattice_rows", None)
    if rows and (tree.find_path(nid) or "") in rows:
        return node_kinds.SEISMIC_FAMILY
    return node_kinds.family_of_type(tree.family_type(nid) or "")


def of_path(tree, path):
    """(family name, node id) of the FIRST node on `path` a family files —
    a card keeps a matching node with its whole subtree, so a log frame is a
    Well through its wellbore, a sub-representation a Reservoir through its
    grid, a lattice grid's property Seismic through its grid. ("", None) when
    no node of the path is filed."""
    parts = str(path or "").split("/")
    for i in range(2, len(parts) + 1):
        nid = tree.find_node_id("/".join(parts[:i]))
        if nid is None:
            continue
        name = name_of(tree, nid)
        if name:
            return name, nid
    return "", None


def tab_of(key):
    """The tree widget's `tabs` for the family of card `key`: one tab, so the
    widget draws no tab row and files nothing else. `lattice` tells the
    widget what the tab does with the lattice grids' rows: "take" them or
    "leave" them out (words: the list reaches the browser as a Python repr,
    where True is no JavaScript)."""
    for k, title, types in FAMILIES:
        if k == key:
            tab = {"name": title, "types": list(types)}
            if k == SEISMIC:
                tab["lattice"] = "take"
            elif title == _LEFT:
                tab["lattice"] = "leave"
            return [tab]
    return []


def tab_named(title):
    """`tab_of` for the family named `title` (a panel's card is named so)."""
    return tab_of(next((k for k, t, _types in FAMILIES if t == title), None))


def _types_outside(xml, rows):
    """The node types `xml` holds outside the rows `rows` and what is under them."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        print("[fespp] tree families: assembly not parsed:", exc, flush=True)
        return set(_TYPE.findall(xml))
    types = set()
    todo = [(root, "/" + root.tag)]
    while todo:
        el, path = todo.pop()
        if path in rows:
            continue
        kind = el.get("type")
        if kind:
            types.add(kind)
        todo.extend((child, path + "/" + child.tag) for child in el)
    return types


def present(xml, lattice=()):
    """The card keys of the families `xml` (the published assembly) holds an
    object of: a container alone says nothing, the geometry it wraps does.
    `lattice`: the rows of the lattice grids, which make the Seismic family
    and count for no other."""
    if not xml:
        return set()
    rows = frozenset(lattice or ())
    hit = _present.get("last")
    if hit is not None and hit[0] is xml and hit[1] == rows:
        return hit[2]
    types = _types_outside(xml, rows) if rows else set(_TYPE.findall(xml))
    out = {key for key, _title, kinds in FAMILIES if types & (set(kinds) - {"GridContainer"})}
    if rows:
        out.add(SEISMIC)
    _present["last"] = (xml, rows, out)
    return out


def key_of(xml, path, lattice=()):
    """The card key of the family `path` (a tree path) is filed under; the
    first family's when it cannot be told."""
    if path and node_facts.is_under(str(path), list(lattice or ())):
        return SEISMIC
    parts = [p for p in str(path or "").split("/") if p]
    if xml and len(parts) >= 2:
        try:
            root = ET.fromstring(xml)
        except ET.ParseError as exc:
            print("[fespp] tree families: assembly not parsed:", exc, flush=True)
            return KEYS[0]
        top = root.find(parts[1])
        if top is not None:
            kinds = {el.get("type") for el in top.iter()}
            for key, _title, types in FAMILIES:
                if kinds & (set(types) - {"GridContainer"}):
                    return key
    return KEYS[0]


def present_names(xml, lattice=()):
    """The names of the families `xml` holds, in the table's order."""
    held = present(xml, lattice)
    return [title for key, title, _types in FAMILIES if key in held]


def open_cards(value, present_, known=NAMES):
    """The family cards (by name) a panel opens from `value`: a list as it
    is (the families of `known` it names), True the first family of `known`
    the data holds (`present_`, the tree open, as a document older than the
    cards says), anything else none."""
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value if str(v) in known]
    if value is True:
        return [n for n in known if n in present_][:1] or list(known[:1])
    return []


def first_present(xml, lattice=()):
    """The first family the data holds, in the table's order; the first
    family's key when it holds none."""
    held = present(xml, lattice)
    return next((key for key in KEYS if key in held), KEYS[0])


def title_of_key(key):
    """The family named by the card `key` ("tree_surface" -> "Surface"), "" for no family card."""
    return next((title for k, title, _types in FAMILIES if k == key), "")


#: the tree layouts that draw the objects under rows of their owners
_OWNER_LAYOUTS = ("by_interpretation", "by_feature_and_interpretation")


def _row_key(tree, nid, top, layout):
    """Where the family's card draws the row `nid` (under the top row `top`):
    siblings by natural title, as the tree widget sorts them; in the
    Interpretation and Feature layouts the top row under the row of its
    interpretation, itself under its feature's, those by title too, an object
    with none after them (DataExplorerTree.byOwner)."""
    from fespp_on_trame.engine.tree import _sibling_sort_key

    def by_title(text):
        return _sibling_sort_key({"title": text or ""})

    def attr(name):
        return tree.find_attribute_value(top, name) or ""

    own = [by_title(tree.find_title(n) or tree.find_label(n)) for n in ((top,) if nid == top else (top, nid))]
    if layout not in _OWNER_LAYOUTS:
        return (0, *own)
    if not attr("interpretation"):
        return (1, *own)
    owners = [by_title(attr("interpretationTitle"))]
    if layout == "by_feature_and_interpretation" and attr("feature"):
        owners.insert(0, by_title(attr("featureTitle")))
    return (0, *owners, *own)


def family_rows(tree, title, layout="flat"):
    """The paths of the rows the card of the family `title` holds, in the
    order it draws them: the first node of each path the family files (an
    object at the top, a container counted as the geometry it wraps, a
    lattice grid's row as Seismic), a row of no family looked into."""
    def children(nid):
        return next(tree.iter_nodes(nid), (nid, []))[1]

    found = []
    todo = [(nid, nid) for nid in reversed(children(0))]
    while todo:
        nid, top = todo.pop()
        name = name_of(tree, nid)
        if name == title:
            found.append((_row_key(tree, nid, top, layout), len(found), nid))
        elif not name:
            todo.extend((kid, top) for kid in reversed(children(nid)))
    return [tree.find_path(nid) or "" for _key, _i, nid in sorted(found)]


def node_brought_back(tree, title, active, remembered, read, layout="flat"):
    """The node a family's tree card brings back when it becomes the card in
    use: none to change ("") when the active node is already one of its tree;
    else the one it had last (`remembered`, still in the file), else its first
    object read (`read`: the paths ticked), else its first row — in the order
    the card draws them (`layout`: the view's tree layout) — so the cards of
    the view follow a node of the tree in use, never another family's, and a
    card opened with nothing active has its first row active."""
    if active and of_path(tree, active)[0] == title:
        return ""
    if remembered and tree.find_node_id(remembered) is not None and of_path(tree, remembered)[0] == title:
        return remembered
    rows = family_rows(tree, title, layout)
    ticked = set(read or ())
    for row in rows if ticked else ():
        if not any(p == row or p.startswith(row + "/") for p in ticked):
            continue
        for nid, _kids in tree.iter_nodes(tree.find_node_id(row)):
            if (tree.find_path(nid) or "") in ticked:
                return tree.find_path(nid)
    return rows[0] if rows else ""
