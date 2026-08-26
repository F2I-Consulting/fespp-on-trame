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
    # Per-grid sub-folders: checking one bulk-selects just its blocked
    # wellbores / subreps (mirrors the C++ isGroupingType in enum.h —
    # purely an app-side notion though: the cascade expands to children
    # paths BEFORE the selectors reach C++, where a folder path lands in
    # MapperType::Folder and is skipped).
    "BlockedWellboreFolder",
    "SubRepresentationFolder",
    # Grid "properties" folder: tri-state + bulk like any other envelope.
    # Checking it selects the PROPERTIES only — the geometry rep is
    # excluded by find_all_selectable_descendant_ids when the walk starts
    # here (and auto-checks separately when a property loads), so the old
    # fear "cascades to the geometry" no longer applies.
    "PropertiesFolder",
)
