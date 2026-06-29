"""Registry + resolvers: map a runtime `kind` string (or a tree path) to the
stateless ElementType singleton. `for_kind` is an O(1) dict lookup; unknown
/ None kinds fall back to a generic standard Representation."""

from .base import ElementType  # noqa: F401 (re-exported via package __init__)
from .representation import (
    Representation, IjkGridRep, GridRep, SurfaceRep,
    WellboreGeometryRep, SeismicFrameRep, BlockedWellboreRep,
)
from .grouping import Grouping, PartialType
from .frames import ChannelFrameRep, MarkerFrameRep
from .leaf import (
    PropertyLeaf, TimeSeriesLeaf, MultiRealizationLeaf,
    MultiRealizationTimeSeriesLeaf, MarkerLeaf,
)


# Concrete classes — each instantiated ONCE (stateless singleton) and
# registered under each of its KINDS. More-specific subclasses (IjkGridRep,
# the TimeSeries / MultiRealization property leaves) are listed before their
# base for clarity; kinds never overlap.
_CONCRETE = (
    Grouping, PartialType,
    IjkGridRep, GridRep, SurfaceRep, WellboreGeometryRep, SeismicFrameRep,
    BlockedWellboreRep,
    ChannelFrameRep, MarkerFrameRep,
    TimeSeriesLeaf, MultiRealizationLeaf, MultiRealizationTimeSeriesLeaf,
    PropertyLeaf, MarkerLeaf,
)

_REGISTRY: dict = {}
for _cls in _CONCRETE:
    _singleton = _cls()
    for _k in _cls.KINDS:
        if _k in _REGISTRY:
            raise RuntimeError(
                f"ElementType kind collision: {_k!r} claimed by "
                f"{type(_REGISTRY[_k]).__name__} and {_cls.__name__}"
            )
        _REGISTRY[_k] = _singleton

# Fallback for an unknown / None kind: a generic standard representation so
# callers never crash on a kind the table doesn't list yet.
_FALLBACK = Representation()


def for_kind(kind):
    """Resolve a runtime `kind` string to its ElementType singleton.
    Unknown / None kinds resolve to a generic standard Representation."""
    if not kind:
        return _FALLBACK
    return _REGISTRY.get(kind, _FALLBACK)


def for_path(tree, path):
    """Resolve the ElementType for a tree node by its assembly `path`.
    Reads the node's runtime kind via the live assembly (position-
    independent)."""
    try:
        node_id = tree.find_node_id(path)
        kind = tree.find_type(node_id) if node_id is not None else None
    except Exception:
        kind = None
    return for_kind(kind)


def registered_kinds():
    """Every runtime kind the hierarchy currently maps (for tests / audits)."""
    return frozenset(_REGISTRY)
