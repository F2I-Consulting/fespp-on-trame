"""Per-tab whitelist of selectable node kinds for the VTreeview's
item_props / `selectable` flag."""

SELECTABLE_TYPES = {
    "reservoir": ["Property", "ContinuousProperty", "DiscreteProperty", "CategoricalProperty"],
    "surface": ["TriangulatedSet", "PolylineSet"],
    "well": ["WellboreTrajectory", "WellboreFrame", "WellboreMarker"]
}


def get_item_props_js(tree_category: str = "reservoir") -> str:
    """Build a Vue `item_props` callback that toggles `selectable`
    based on the whitelist for the given tab."""
    allowed_types = SELECTABLE_TYPES.get(tree_category, [])
    conditions = " || ".join([f"item.type?.includes('{t}')" for t in allowed_types])

    return f"item => ({{ selectable: {conditions} }})"
