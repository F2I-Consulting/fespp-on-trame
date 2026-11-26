"""Representation element types: geometry, an eye, and a per-view source.

Family defaults: REP eye, rep tracking bucket, STANDARD show/hide,
COLORABLE. Frames live in frames.py: they subclass Representation but are
folders-for-the-tree."""

from .base import ElementType
from .enums import TreeRole, VisibilityPolicy, ColorPolicy, EYE_REP, BUCKET_REP


class Representation(ElementType):
    """Base of the eye-bearing renderables."""

    def tree_role(self) -> TreeRole:
        return TreeRole.REPRESENTATION

    def eye_descriptor(self):
        return EYE_REP

    def tracking_bucket(self):
        return BUCKET_REP

    def visibility_policy(self) -> VisibilityPolicy:
        return VisibilityPolicy.STANDARD

    def color_policy(self) -> ColorPolicy:
        return ColorPolicy.COLORABLE

    # --- visibility behaviour (paraview imported lazily) ----------------

    # --- source construction --------------------------------------------

    # --- rendered / colorable source sets (source_resolver delegation) ---


class GridRep(Representation):
    """Reservoir grids on the standard per-view extractor path
    (UnstructuredGrid, SubRepresentation). IjkGrid is the modal subclass."""

    KINDS = ("UnstructuredGrid", "Sub")


class IjkGridRep(GridRep):
    """The only kind that goes through the modal IjkGrid pipeline (I/J/K
    slicers + volume crop + threshold chain, range vs slice mode), built
    lazily once a property is active."""

    KINDS = ("IjkGrid",)

    def is_ijk_grid(self) -> bool:
        return True

    def visibility_policy(self) -> VisibilityPolicy:
        return VisibilityPolicy.IJK_MODAL


class SurfaceRep(Representation):
    """Simple geometry: one extractor, plain show/hide + colour."""

    KINDS = ("Grid2d", "PointSet", "Polyline", "PolylineSet", "TriangulatedSet")


class WellboreGeometryRep(Representation):
    """Simple wellbore tube geometry on one extractor (Trajectory creates a
    companion Wellhead MD label on activation; Completion/Perfo similar).

    NOTE: a perforation node's RUNTIME kind is ``'Perforation'`` (C++ sets it
    explicitly via ``treeViewNodeTypeName``, bypassing SimplifyXmlTag), while
    other kind lists in the code (engine/tree.py, the tree widgets) carry the
    abbreviated ``'Perfo'``. Both are matched here so the type resolves
    explicitly, not via the fallback."""

    KINDS = ("Trajectory", "Completion", "Perfo", "Perforation")


class SeismicFrameRep(Representation):
    """SeismicWellboreFrame — treated as a real eye-bearing rep (NOT a folder
    like the log/marker frames), on the standard rep defaults."""

    KINDS = ("SeismicWellboreFrame",)


class BlockedWellboreRep(Representation):
    """BlockedWellbore — a real eye-bearing rep with its OWN geometry.

    The geometry is the subset of its supporting grid's cells the wellbore is
    blocked in, produced by the FESPP BlockedWellbore mapper. It sits UNDER
    the grid in the tree but is NOT a property of it: selecting it shows only
    the blocked cells, not the full grid. Standard rep defaults."""

    KINDS = ("BlockedWellbore",)
