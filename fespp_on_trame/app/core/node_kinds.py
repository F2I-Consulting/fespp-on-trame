"""RESQML assembly node-kind constants shared across the tree UI and the
activator, kept in a dependency-free leaf module so both `core/activator.py`
and `ui/drawer/tree_views.py` can import it without a circular import."""

#: Node kinds that are GROUPING folders in the tree (tri-state checkbox,
#: expand/collapse, bulk-select). Governs ONLY tree selection / tri-state —
#: independent of source creation.
GROUPING_KINDS = (
    "Collection",
    "Wellbore",
    "Partial",
    "Feature",
    "Interpretation",
    "Frame",
    "MarkerFrame",
    # The grid container folder (wraps a grid's Full Geometry + SubReps +
    # BlockedWellbores); checking it bulk-selects those children.
    "GridContainer",
)
