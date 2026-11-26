"""Element-type hierarchy: how a RESQML element of a given runtime kind behaves.

Single source of truth for the tree / tracking / eye / visibility / colour /
source behaviour of each runtime ``kind``, so callers ask the element type
instead of branching on ``if kind == "..."``. Each type is a stateless
singleton (see registry.py).

Layout: a class is indented UNDER the file it lives in (so "where is this
class?" is the left column); the ``(BaseClass)`` in each name is its Python
parent, so the **general → family → unit** inheritance reads too. A parent
that lives in another file is visible at a glance, e.g.
``FrameRep(Representation)`` is defined in ``frames.py`` but inherits from
``representation.py``:

    enums.py
        TreeRole, VisibilityPolicy, ColorPolicy, EyeKind, EyeDescriptor,
        BUCKET_* / EYE_* constants
    base.py
        ElementType                          base contract + neutral defaults
    grouping.py
        Grouping(ElementType)                folder, no source, tri-state selection
        PartialType(Grouping)                Partial: folder, NOT selectable
    representation.py
        Representation(ElementType)          geometry + eye + per-view source
        GridRep(Representation)              UnstructuredGrid, Sub — standard
        IjkGridRep(GridRep)                  IjkGrid — I/J/K slicers + volume, modal
        SurfaceRep(Representation)           Grid2d, PointSet, Polyline*, TriangulatedSet
        WellboreGeometryRep(Representation)  Trajectory, Completion, Perfo/Perforation
        SeismicFrameRep(Representation)      SeismicWellboreFrame — a real rep
        BlockedWellboreRep(Representation)   BlockedWellbore — own geometry under its grid
    frames.py
        FrameRep(Representation)             folder-for-tree, representation-for-source
        ChannelFrameRep(FrameRep)            Frame — logs, ONE log at a time
        MarkerFrameRep(FrameRep)             MarkerFrame — N markers at once
    leaf.py
        Leaf(ElementType)                    sub-element of a rep, not a rep itself
        PropertyLeaf(Leaf)                   colours the parent rep; a channel is this
        TimeSeriesLeaf(PropertyLeaf)         TimeSeries property (time slider)
        MultiRealizationLeaf(PropertyLeaf)   MultiRealization property (realization picker)
        MultiRealizationTimeSeriesLeaf(PropertyLeaf)  both time + realization
        MarkerLeaf(Leaf)                     toggles ONE marker's visibility
    registry.py
        for_kind / for_path / registered_kinds   (+ _REGISTRY / _CONCRETE / _FALLBACK)

This ``__init__`` re-exports the full public API (``element_type.for_kind``,
``element_type.IjkGridRep``, ``element_type.BUCKET_ARRAY``,
``element_type.VisibilityPolicy``, …). The private registry tables are
importable too (the tests audit ``_CONCRETE``) but stay out of ``__all__``.

The golden rule when adding behaviour: write it at the HIGHEST level where
it is correct, and never higher.

The ``KINDS`` strings are the RUNTIME kinds (``SimplifyXmlTag`` output:
'Frame', 'MarkerFrame', 'Marker', 'Sub', …), NOT the C++ enum names.
"""

from .enums import (
    TreeRole, VisibilityPolicy, ColorPolicy, EyeKind, EyeDescriptor,
    BUCKET_REP, BUCKET_ARRAY, BUCKET_MARKER,
    EYE_REP, EYE_ARRAY, EYE_MARKER,
)
from .base import ElementType
from .grouping import Grouping, PartialType
from .representation import (
    Representation, GridRep, IjkGridRep, SurfaceRep,
    WellboreGeometryRep, SeismicFrameRep, BlockedWellboreRep,
)
from .frames import FrameRep, ChannelFrameRep, MarkerFrameRep
from .leaf import (
    Leaf, PropertyLeaf, TimeSeriesLeaf, MultiRealizationLeaf,
    MultiRealizationTimeSeriesLeaf, MarkerLeaf,
)
from .registry import (
    for_kind, for_path, registered_kinds,
    _CONCRETE, _REGISTRY, _FALLBACK,
)

__all__ = [
    # enums + descriptors
    "TreeRole", "VisibilityPolicy", "ColorPolicy", "EyeKind", "EyeDescriptor",
    "BUCKET_REP", "BUCKET_ARRAY", "BUCKET_MARKER",
    "EYE_REP", "EYE_ARRAY", "EYE_MARKER",
    # hierarchy
    "ElementType",
    "Grouping", "PartialType",
    "Representation", "GridRep", "IjkGridRep", "SurfaceRep",
    "WellboreGeometryRep", "SeismicFrameRep", "BlockedWellboreRep",
    "FrameRep", "ChannelFrameRep", "MarkerFrameRep",
    "Leaf", "PropertyLeaf", "TimeSeriesLeaf", "MultiRealizationLeaf",
    "MultiRealizationTimeSeriesLeaf", "MarkerLeaf",
    # resolvers
    "for_kind", "for_path", "registered_kinds",
]
