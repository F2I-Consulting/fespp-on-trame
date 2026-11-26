"""Wellbore-frame element types: a folder in the tree, a rep in the source layer.

A frame is a FOLDER in the tree (tri-state, no own eye, checking selects all
children) BUT a Representation in the source layer (owns the clone + render
anchor; children render via their OWN per-(child, view) extractors, so the
frame's PRIMARY extractor stays hidden). C++ side = ``MapperType::MapperSet``.

These classes also OWN the per-type child behaviour: `RepInScene` keeps the
per-(rep, view) state (the `_channel_extractors` / `_marker_extractors`
dicts, the scene), and passes itself (`ris`) to these methods. The ONLY
behavioural difference between a log frame and a marker frame — EXCLUSIVE
one-at-a-time vs MULTI — is the `set_child_visible` override below;
everything else (building a child extractor, listing the shown ones) is
shared on `FrameRep`.

All ``paraview`` / ``trame`` / ``sources.*`` imports are LOCAL to the
methods so this package stays a leaf (no import cycle with the source
layer) and importable without a ParaView runtime (the tests rely on it)."""

from .representation import Representation
from .enums import TreeRole, VisibilityPolicy


class FrameRep(Representation):
    """Abstract base for wellbore frames; the registry uses ChannelFrameRep
    and MarkerFrameRep.

    Subclasses set ``_child_store_attr`` (the RepInScene dict holding their
    child extractors) and ``_reg_prefix`` (the proxy registration prefix)."""

    #: RepInScene attribute holding this frame's child extractors
    #: registration-name prefix for a child's per-view extractor proxy

    def tree_role(self) -> TreeRole:
        return TreeRole.FOLDER

    def is_grouping(self) -> bool:
        return True

    def eye_descriptor(self):
        return None

    def tracking_bucket(self):
        # The frame itself is not tracked; its children are (array/marker).
        return None

    # --- child management (shared) --------------------------------------


class ChannelFrameRep(FrameRep):
    """WellboreFrame of logs — ONE log shown at a time. Each channel owns its
    own per-(channel, view) EnergisticsExtractor (exclusive show); children
    are PropertyLeaf (colourable, array bucket). The source PERSISTS once
    created (hidden when a sibling is shown) so its scoped LUT / COE / stats
    read directly with no retarget."""

    KINDS = ("Frame",)

    def is_channel_frame(self) -> bool:
        return True

    def visibility_policy(self) -> VisibilityPolicy:
        return VisibilityPolicy.ONE_AT_A_TIME


class MarkerFrameRep(FrameRep):
    """WellboreMarkerFrame — N markers shown at once. Each marker owns its own
    per-(marker, view) extractor; children are MarkerLeaf (visibility-only),
    each independently recolourable."""

    KINDS = ("MarkerFrame",)

    def visibility_policy(self) -> VisibilityPolicy:
        return VisibilityPolicy.MULTI
