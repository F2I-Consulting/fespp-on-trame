"""Leaf element types — sub-elements of a representation (not reps): no
source of their own. A property COLOURS its parent rep; a marker toggles
ONE marker's visibility."""

from .base import ElementType
from .enums import (
    TreeRole, VisibilityPolicy, ColorPolicy,
    EYE_ARRAY, EYE_MARKER, BUCKET_ARRAY, BUCKET_MARKER,
)


class Leaf(ElementType):
    """Family default tree role = LEAF; no per-view source of its own."""

    def tree_role(self) -> TreeRole:
        return TreeRole.LEAF

    def is_selectable(self) -> bool:
        return True


class PropertyLeaf(Leaf):
    """A property that COLOURS its parent rep. A log CHANNEL is a PropertyLeaf
    whose rep ancestor is a ChannelFrameRep — "channel-ness" is structural
    (the parent), not a distinct kind. Purple data-array eye; array bucket."""

    KINDS = (
        "ContinuousProperty", "DiscreteProperty", "CategoricalProperty",
        "TimeSeries", "MultiRealization", "MultiRealizationTimeSeries",
    )

    def is_property(self) -> bool:
        return True

    def eye_descriptor(self):
        return EYE_ARRAY

    def tracking_bucket(self):
        return BUCKET_ARRAY

    def color_policy(self) -> ColorPolicy:
        return ColorPolicy.COLORABLE

    def visibility_policy(self) -> VisibilityPolicy:
        # A property has no visibility of its own — it colours the rep.
        return VisibilityPolicy.NONE


class MarkerLeaf(Leaf):
    """A single WellboreMarker — visibility-only (no colour array, just a
    SolidColor tint). Deep-orange marker eye; marker bucket; multi-shown."""

    KINDS = ("Marker",)

    def eye_descriptor(self):
        return EYE_MARKER

    def tracking_bucket(self):
        return BUCKET_MARKER

    def color_policy(self) -> ColorPolicy:
        return ColorPolicy.VISIBILITY_ONLY

    def visibility_policy(self) -> VisibilityPolicy:
        # The marker's show/hide is driven by its parent MarkerFrameRep (MULTI).
        return VisibilityPolicy.NONE
