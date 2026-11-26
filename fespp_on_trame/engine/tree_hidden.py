"""What the trees do not show yet: the representations of a seismic feature
(a lattice, a line, a set of lines), until a Seismic tab of their own.

The assembly carries, on a representation's top node, the uuid of the
feature it interprets (the plugin's `feature` attribute), not that feature's
type: the repository index (engine/repo_query) gives the types, and the
nodes whose feature is one of those types leave the published XML. Their
paths do not change those of the others, so a selection made before stays
valid.
"""
import xml.etree.ElementTree as ET

from fespp_on_trame.engine import repo_query

# AbstractSeismicLineFeature and its kin, RESQML 2.0.1 and 2.2 names
SEISMIC_FEATURES = frozenset((
    "SeismicLatticeFeature", "SeismicLineFeature", "SeismicLineSetFeature",
    "ShotPointLineFeature", "AbstractSeismicLineFeature",
))


def seismic_features(source):
    """Uuids (lower case) of the seismic features the repository holds; empty
    when the plugin has no query channel or nothing seismic."""
    if source is None or not repo_query.has_channel(source):
        return set()
    try:
        index = repo_query.object_index(source)
    except Exception as exc:
        print("[fespp] seismic features not read, shown in the trees:", exc, flush=True)
        return set()
    return {e["uuid"].lower() for e in index
            if e.get("type", "").split(":")[-1].replace("obj_", "") in SEISMIC_FEATURES}


def without_features(xml, uuids):
    """`xml` (a vtkDataAssembly) without the nodes whose `feature` is one of
    `uuids`; the text itself when none of them is in it."""
    if not xml or not uuids:
        return xml
    lowered = xml.lower()
    if not any(u in lowered for u in uuids):
        return xml
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        print("[fespp] assembly not parsed, seismic rows kept:", exc, flush=True)
        return xml
    for parent in list(root.iter()):
        for child in list(parent):
            if (child.get("feature") or "").lower() in uuids:
                parent.remove(child)
    return ET.tostring(root, encoding="unicode")
