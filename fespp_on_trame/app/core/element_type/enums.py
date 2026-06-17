"""Contract value types for the ElementType hierarchy: the policy enums,
the eye descriptor, the tracking-bucket tokens, and the SINGLETON eye
descriptors (returned by reference so the contract allocates nothing on a
hot path)."""

from enum import Enum


class TreeRole(Enum):
    """Where the node sits in the treeview interaction model."""
    FOLDER = "folder"            # tri-state checkbox, no own eye (groupings + frames)
    REPRESENTATION = "rep"       # eye-bearing renderable
    LEAF = "leaf"                # property / marker under a rep


class VisibilityPolicy(Enum):
    """How the per-view source is shown / hidden."""
    NONE = "none"                # groupings — no source
    STANDARD = "standard"        # one extractor, plain show/hide
    IJK_MODAL = "ijk_modal"      # IjkGrid: slicer/range modal pipeline
    ONE_AT_A_TIME = "one"        # channel frame: exclusive child (one log shown)
    MULTI = "multi"              # marker frame: many children shown at once


class ColorPolicy(Enum):
    """Whether/how the element takes colour."""
    NONE = "none"                # groupings
    COLORABLE = "colorable"      # reps + property leaves (ColorBy / SolidColor)
    VISIBILITY_ONLY = "vis_only"  # markers — SolidColor tint, never a ColorArray


class EyeKind(Enum):
    """Which eye control the node carries (and which controller it wires)."""
    REP = "rep"                  # toggle_rep_visibility
    ARRAY = "array"              # toggle_dataarray_color (purple)
    MARKER = "marker"            # toggle_marker_visibility (deep-orange)


class EyeDescriptor:
    """Describes a node's eye affordance for the tree view.

    `kind`  — REP / ARRAY / MARKER.
    `color` — the Vuetify colour the active eye uses (UI hint).
    `multi` — True when several of this eye can be active in one panel at
              once (markers); False when activating one supersedes the
              others on the same rep (a rep's single colour array, a
              frame's single shown log).

    Instances are SINGLETONS (see EYE_* below) — never mutate them."""

    __slots__ = ("kind", "color", "multi")

    def __init__(self, kind: EyeKind, color: str = "", multi: bool = False):
        self.kind = kind
        self.color = color
        self.multi = multi

    def __repr__(self) -> str:
        return f"EyeDescriptor({self.kind.value}, color={self.color!r}, multi={self.multi})"


# Tracking-bucket tokens (which `state.ui_loaded_*` list the kind feeds).
BUCKET_REP = "rep"
BUCKET_ARRAY = "array"
BUCKET_MARKER = "marker"


# Singleton eye descriptors — returned by reference from `eye_descriptor()`
# so building a large tree allocates nothing per node.
EYE_REP = EyeDescriptor(EyeKind.REP)
EYE_ARRAY = EyeDescriptor(EyeKind.ARRAY, color="purple", multi=False)
EYE_MARKER = EyeDescriptor(EyeKind.MARKER, color="deep-orange", multi=True)
