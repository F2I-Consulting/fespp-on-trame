"""Category labels — the names behind the codes of a categorical property.

A facies, a zone, a fault block is stored as an integer code whose name
lives in the RESQML `StringTableLookup` the property points at. Two places
carry those names once loaded: the lookup's own XML, reachable through the
reader's query channel (`repo_query`), and the annotations of the ParaView
lookup table bound to the array. The file's lookup is the authority:
the ParaView table is keyed by the bare array name and shared by the whole
session, so two properties of one name (two grids, two files) leave it
holding the names of whichever loaded last. `labels_for` reads the file
first, the table when the file cannot be asked, and answers `{}` when
neither has them — the caller then prints the code (`label_of`) and says
so (`labels_note`). A `DiscreteProperty` has no names by definition.
"""
import re

from fespp_on_trame.engine.utils.naming import make_valid_vtk_name

_UUID_RE = re.compile(r"_?([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
                      r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$")
_CATEGORICAL = "CategoricalProperty"


def _key(v):
    f = float(v)
    return int(f) if f.is_integer() else f


def lut_labels(vtk_name):
    """`{value: label}` from the `Annotations` of the lookup table bound to
    `vtk_name`; `{}` when there is no such table or it has none yet."""
    if not vtk_name:
        return {}
    try:
        from paraview import simple as pvsimple
        lut = pvsimple.GetColorTransferFunction(vtk_name)
        if lut is None or lut.SMProxy is None:
            return {}
        prop = lut.SMProxy.GetProperty("Annotations")
        if prop is None:
            return {}
        n = prop.GetNumberOfElements()
        out = {}
        for i in range(0, n - 1, 2):
            try:
                out[_key(prop.GetElement(i))] = str(prop.GetElement(i + 1))
            except (ValueError, TypeError):
                continue
        return out
    except Exception:
        return {}


def _local(tag):
    return str(tag).rsplit("}", 1)[-1]


def _find_local(elem, name):
    """The first descendant whose local name matches, case-insensitively."""
    want = name.lower()
    for e in elem.iter():
        if _local(e.tag).lower() == want:
            return e
    return None


def _node_title(tree, array_path):
    """The RESQML title of the property node, "" when unknown."""
    try:
        nid = tree.find_node_id(array_path)
        if nid is None:
            return ""
        return (tree.find_attribute_value(nid, "propTitle")
                or tree.find_title(nid) or "")
    except Exception:
        return ""


def _property_xml(tree, array_path, reader, repo_query):
    """The XML of the categorical property behind `array_path`: by the
    uuid its node name ends with, or — for a realization set or a time
    series, whose node names carry no property uuid — the file's
    categorical property of the same title (one round trip for all)."""
    m = _UUID_RE.search(array_path.rsplit("/", 1)[-1])
    if m:
        return repo_query.object_xml(reader, m.group(1))
    title = _node_title(tree, array_path)
    if not title:
        return ""
    from xml.etree import ElementTree as ET
    uuids = repo_query.object_uuids(reader, _CATEGORICAL)
    for xml in repo_query.object_xml(reader, uuids):
        if not xml or repo_query.is_partial_marker(xml):
            continue
        try:
            t = _find_local(ET.fromstring(xml), "Title")
        except ET.ParseError:
            continue
        if t is not None and (t.text or "").strip() == title:
            return xml
    return ""


def lookup_labels(tree, array_path, reader):
    """`{code: name}` read from the property's StringTableLookup through
    the reader's query channel: the property XML names its `Lookup`, the
    lookup XML lists `<Value><Key>…</Key><Value>…</Value></Value>`. `{}`
    on any failure, a plugin built without the channel included."""
    if reader is None or not array_path:
        return {}
    try:
        from xml.etree import ElementTree as ET
        from fespp_on_trame.engine import repo_query
        if not repo_query.has_channel(reader):
            return {}
        xml = _property_xml(tree, array_path, reader, repo_query)
        if not xml:
            return {}
        lookup = _find_local(ET.fromstring(xml), "Lookup")
        if lookup is None:
            return {}
        uuid_el = _find_local(lookup, "UUID")
        lookup_uuid = (uuid_el.text or "").strip() if uuid_el is not None else ""
        if not lookup_uuid:
            return {}
        lxml = repo_query.object_xml(reader, lookup_uuid)
        if not lxml:
            return {}
        out = {}
        for e in ET.fromstring(lxml).iter():
            if _local(e.tag) != "Value":
                continue
            key = value = None
            for c in list(e):
                ln = _local(c.tag)
                if ln == "Key":
                    key = (c.text or "").strip()
                elif ln == "Value":
                    value = (c.text or "").strip()
            if key is None or value is None:
                continue
            try:
                out[_key(key)] = value
            except ValueError:
                continue
        return out
    except Exception:
        return {}


def _prop_type(tree, array_path):
    from fespp_on_trame.engine import derived_props
    if derived_props.is_derived(array_path) or tree is None or not array_path:
        return ""
    try:
        nid = tree.find_node_id(array_path)
        if nid is None:
            return ""
        return tree.find_prop_type(nid) or tree.find_type(nid) or ""
    except Exception:
        return ""


def _lut_names(tree, array_path, vtk_name):
    """The lookup-table names to try: the array's, and for a realization
    set the arrays actually loaded (`<name>_real_<idx>`)."""
    if not vtk_name:
        return []
    names = [vtk_name]
    if not re.search(r"_real_\d+$", vtk_name):
        try:
            from fespp_on_trame.engine import realization_dispatch as rd
            names += [rd.suffixed_array_name(vtk_name, i)
                      for i in rd.available_realization_indices(tree, array_path)]
        except Exception:
            pass
    return names


def labels_for(tree, array_path, vtk_name=None, reader=None):
    """`{value: label}` of a categorical property: the file's string
    lookup first (when `reader` is given), the lookup table's annotations
    next, else `{}`. A discrete property, a derived one or an unknown
    node has no names."""
    if _prop_type(tree, array_path) != _CATEGORICAL:
        return {}
    labels = lookup_labels(tree, array_path, reader) if reader is not None else {}
    if labels:
        return labels
    for name in _lut_names(tree, array_path, vtk_name):
        labels = lut_labels(name)
        if labels:
            return labels
    return {}


NO_NAMES_NOTE = "category names not readable for this property: its codes are shown"


def labels_note(tree, array_path, labels):
    """What to say on screen when a categorical property's names could not
    be read (`labels` empty): `NO_NAMES_NOTE`; "" for any other node — a
    discrete property has no names to miss."""
    if labels or _prop_type(tree, array_path) != _CATEGORICAL:
        return ""
    return NO_NAMES_NOTE


def label_of(labels, value):
    """The name of a code, else the code itself as an identifier
    (`3`, not `3.0`, never grouped); a non-integral value is written
    like any number."""
    from fespp_on_trame.engine.utils import numfmt
    try:
        f = float(value)
    except (TypeError, ValueError):
        return str(value)
    if f != f:
        return numfmt.DASH
    key = int(f) if f.is_integer() else f
    hit = (labels or {}).get(key)
    if hit is not None:
        return str(hit)
    return str(key) if isinstance(key, int) else numfmt.fmt(f)


def array_path_for_vtk_name(tree, rep_path, vtk_name):
    """The path of the property node under `rep_path` — or, for a grid
    whose properties sit beside its geometry under the GridContainer,
    under that container — whose VTK array name is `vtk_name`; None when
    nothing matches."""
    if tree is None or not rep_path or not vtk_name:
        return None
    from fespp_on_trame.engine import element_type
    try:
        rep_id = tree.find_node_id(rep_path)
    except Exception:
        rep_id = None
    if rep_id is None:
        return None
    bare = re.sub(r"_real_\d+$", "", vtk_name)
    wanted = make_valid_vtk_name(bare)

    def _under(root):
        for nid in tree.find_all_descendant_ids(root):
            kind = tree.find_type(nid) or ""
            if not element_type.for_kind(kind).is_property():
                continue
            title = tree.find_title(nid) or ""
            if element_type.for_kind(kind).is_multi_realization():
                title = tree.find_attribute_value(nid, "propTitle") or title
            if make_valid_vtk_name(title) == wanted:
                return tree.find_path(nid)
        return None

    found = _under(rep_id)
    if found:
        return found
    try:
        container = tree.find_parent_node_id_with_type(rep_id, "GridContainer")
    except Exception:
        container = None
    return _under(container) if container is not None else None
