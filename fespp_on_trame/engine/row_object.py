"""The RESQML object behind a row of the data tree.

The assembly names its nodes after the objects they stand for, and a few
rows stand for no object of their own. The shapes the plugin emits:

- ``_<uuid>`` — the object itself (a representation, a property, a
  wellbore, a frame, a marker, a completion…);
- ``_gridfolder_<uuid>``, ``_propsfolder_<uuid>``, ``_subrepfolder_<uuid>``,
  ``_bwfolder_<uuid>`` — the folders around a grid, named after the grid;
- ``_logsfolder_<uuid>``, ``_markersfolder_<uuid>``,
  ``_completionsfolder_<uuid>`` — the folders under a well, named after
  the wellbore feature;
- ``_feature_<uuid>``, ``_interp_<uuid>`` — the grouping rows of the
  by-interpretation layouts, real Feature / Interpretation objects;
- ``_<ts uuid>TimeSeries_<prop>``, ``_<ts uuid>multirealts_<prop>``,
  ``_<ts uuid>real_<i>_<prop>`` — a time series of one property, and the
  realizations of one: the uuid is the TimeSeries the steps share, the
  properties of the steps are not rows of the tree;
- ``_<completion uuid>_<connection uid>`` — a perforation, which is a
  line of its wellbore completion and no object of its own;
- ``_multireal_<prop>`` — the realizations of one property, no uuid at all.

`resolve` says which object to open and, when the row is not that object
itself, the sentence that must be shown with it — a row that opens
something other than what it names never does so silently.
"""
import re

_UUID = (r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
         r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})")
OBJECT_RE = re.compile(
    r"^_?(?:(?:gridfolder|propsfolder|subrepfolder|bwfolder"
    r"|logsfolder|markersfolder|completionsfolder|feature|interp)_)?"
    + _UUID + r"$")
SERIES_RE = re.compile(r"^_" + _UUID + r"(?:TimeSeries_|multirealts_|real_\d+_)")
PERFORATION_RE = re.compile(r"^_" + _UUID + r"_.")
_NO_OBJECT = "00000000-0000-0000-0000-000000000000"   # the nil uuid names no object


def uuid_of(leaf):
    """The uuid a row leads to, or "" — the object itself, the grid of a
    grid folder, the TimeSeries of a series row, the completion of a
    perforation."""
    for rx in (OBJECT_RE, SERIES_RE, PERFORATION_RE):
        m = rx.match(leaf or "")
        if m and m.group(1).lower() != _NO_OBJECT:
            return m.group(1)
    return ""


def resolve(leaf, title="", parent_title=""):
    """``(uuid, note)`` for the row whose assembly name is `leaf`.

    A row that IS its object: ``(uuid, "")``. A row that leads to another
    object: ``(uuid, why)``. A row with no object: ``("", why)``.
    """
    leaf = leaf or ""
    name = title or "This row"
    m = OBJECT_RE.match(leaf)
    if m and m.group(1).lower() != _NO_OBJECT:
        return m.group(1), ""
    m = SERIES_RE.match(leaf)
    if m and m.group(1).lower() != _NO_OBJECT:
        return m.group(1), (
            f"{name} is a time series of one property: what opens is the"
            " TimeSeries its steps share (the dates); the property of each"
            " step is not a row of the tree.")
    m = PERFORATION_RE.match(leaf)
    if m and m.group(1).lower() != _NO_OBJECT:
        holder = parent_title or "its wellbore completion"
        return m.group(1), (
            f"{name} is a perforation of {holder}: what opens is the"
            " completion that declares it — a perforation is no object of"
            " its own.")
    if leaf.startswith("_multireal_"):
        return "", (f"{name} groups the realizations of one property, a"
                    " row of the tree with no object of its own: explore"
                    " one of the realizations.")
    return "", (f"{name} is not a RESQML object of its own (a synthetic"
                " row of the tree): explore one of its members.")
