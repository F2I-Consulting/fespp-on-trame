"""What a property IS for the application (the PO, 12/11: "faudrait pouvoir
typer les propriétés … le déduire du nom n'est pas top"): the kind the
reader set on it (right-click "Type…", any PWLS 4.0 kind), else the kind its
file says (FESPP's `propertyKind` attribute). Set kinds are kept by the
property's uuid, for the session. The name never decides.

`velocity_reading(kind)`: how a velocity of that kind is read as a velocity
model — "average" (an average velocity from the datum: depth = v·t/2),
"rms" (an RMS or stacking velocity, which a velocity model cannot use as it
is), "interval" (an interval velocity, and a bare "velocity" the file does
not detail: the PO's default, 12/11)."""
from fespp_on_trame.engine import pwls_kinds, row_object

# where in its cell a velocity's value stands (engine/velocity_model.Cube
# `at`): the top by default, the time of a seismic sample (the PO, 12/11)
POSITIONS = {"top": 0.0, "centre": 0.5, "bottom": 1.0}
DEFAULT_POSITION = "top"

AVERAGE = ("avg seismic velocity", "avg acoustic velocity")
RMS = ("rms velocity", "stack velocity")


def uuid_of(tree, node):
    """The uuid of the property at `node`, "" when its row names none."""
    path = tree.find_path(node) or "" if node is not None else ""
    return row_object.uuid_of(path.rsplit("/", 1)[-1]) or ""


def file_kind(tree, node):
    """The kind the file gives the property, "" when it gives none."""
    return str(tree.find_attribute_value(node, "propertyKind") or "").strip() if node is not None else ""


def kind_of(tree, node, set_kinds):
    """The property's kind: the one set in the session (`set_kinds`
    {uuid: kind}), else the file's."""
    return (set_kinds or {}).get(uuid_of(tree, node)) or file_kind(tree, node)


def position_of(tree, node, set_positions):
    """"top", "centre" or "bottom": where in its cell the property's value
    stands, the one set in the session or the default."""
    at = (set_positions or {}).get(uuid_of(tree, node))
    return at if at in POSITIONS else DEFAULT_POSITION


def velocity_reading(kind):
    """"interval", "average" or "rms": the nearest of those the kind is, its
    own title first (PWLS files "interval velocity" under "avg acoustic
    velocity": the kind itself decides before its parents)."""
    for k in pwls_kinds.ancestors(kind) or [str(kind or "").strip().lower()]:
        if k == "interval velocity":
            return "interval"
        if k in AVERAGE:
            return "average"
        if k in RMS:
            return "rms"
    return "interval"


def choices():
    """Every PWLS 4.0 kind, sorted: what the "Type…" box offers."""
    return sorted(pwls_kinds._load())
