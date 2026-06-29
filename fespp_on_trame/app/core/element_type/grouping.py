"""Grouping element types — pure organisational folders (no VTK source of
their own; C++ ``MapperType::Folder`` / ``isGroupingType``)."""

from .base import ElementType
from .enums import TreeRole, VisibilityPolicy, ColorPolicy


class Grouping(ElementType):
    """Tri-state folder; checking selects all selectable descendants."""

    # GridContainer wraps an IjkGrid/UnstructuredGrid: it holds the grid's
    # "Full Geometry" rep + its SubReps + BlockedWellbores as children, and
    # renders nothing itself (C++ MapperType::Folder).
    KINDS = ("Collection", "Wellbore", "Feature", "Interpretation", "GridContainer")

    def tree_role(self) -> TreeRole:
        return TreeRole.FOLDER

    def is_grouping(self) -> bool:
        return True

    def eye_descriptor(self):
        return None

    def tracking_bucket(self):
        return None

    def visibility_policy(self) -> VisibilityPolicy:
        return VisibilityPolicy.NONE

    def color_policy(self) -> ColorPolicy:
        return ColorPolicy.NONE


class PartialType(Grouping):
    """A partial stub (a partial rep OR a partial property leaf): only Title
    + UUID, no data — shown as ``!!!PARTIAL!!!`` and NOT checkable."""

    KINDS = ("Partial", "partial")

    def is_selectable(self) -> bool:
        return False

    def propagates_selection(self) -> bool:
        return False
