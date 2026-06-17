"""Element-type hierarchy (the `ElementType` refactor) — package.

Single source of truth for "how does a RESQML element of this runtime
`kind` behave", replacing the scattered `if kind == "..."` branches across
the tree / tracking / eye / visibility / colour / source layers. See
``doc/EN|FR/REFACTOR_ELEMENT_TYPE_HIERARCHY.md`` for the design and
``TYPES_PARTICULARITES.md`` for the per-type spec this encodes.

Three-level inheritance — **general → family → unit**:

    ElementType                     (base — the contract + neutral defaults)
    ├── Grouping                    (folder, no source, tri-state selection)
    │   └── PartialType             (Partial: folder, NOT selectable)
    ├── Representation              (geometry + eye + per-view source)
    │   ├── GridRep                 (UnstructuredGrid, Sub — standard)
    │   │   └── IjkGridRep          (IjkGrid — I/J/K slicers + volume, modal)
    │   ├── SurfaceRep              (Grid2d, PointSet, Polyline*, TriangulatedSet)
    │   ├── WellboreGeometryRep     (Trajectory, Completion, Perfo/Perforation)
    │   ├── SeismicFrameRep         (SeismicWellboreFrame — a real rep)
    │   └── FrameRep                (folder-for-tree, representation-for-source)
    │       ├── ChannelFrameRep     (Frame — logs, ONE log at a time)
    │       └── MarkerFrameRep      (MarkerFrame — N markers at once)
    └── Leaf                        (sub-element of a rep, not a rep itself)
        ├── PropertyLeaf            (colours the parent rep; a channel is this)
        └── MarkerLeaf              (toggles ONE marker's visibility)

Split across modules (enums / base / grouping / representation / frames /
leaf / registry) for navigability; this ``__init__`` re-exports the full
public API so ``from fespp_on_trame.app.core import element_type`` keeps
working unchanged (``element_type.for_kind``, ``element_type.IjkGridRep``,
``element_type.BUCKET_ARRAY``, ``element_type.VisibilityPolicy``, …).

The golden rule when adding behaviour: write it at the HIGHEST level where
it is correct, and never higher.

⚠ The ``KINDS`` strings are the RUNTIME kinds (``SimplifyXmlTag`` output:
'Frame', 'MarkerFrame', 'Marker', 'Sub', …) — NOT the C++ enum names.
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
    WellboreGeometryRep, SeismicFrameRep,
)
from .frames import FrameRep, ChannelFrameRep, MarkerFrameRep
from .leaf import Leaf, PropertyLeaf, MarkerLeaf
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
    "WellboreGeometryRep", "SeismicFrameRep",
    "FrameRep", "ChannelFrameRep", "MarkerFrameRep",
    "Leaf", "PropertyLeaf", "MarkerLeaf",
    # resolvers
    "for_kind", "for_path", "registered_kinds",
]
