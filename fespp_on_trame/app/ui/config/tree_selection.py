# fespp_on_trame/app/ui/config/tree_selection.py
"""
Configuration de la sélectabilité des noeuds dans les TreeViews
"""

SELECTABLE_TYPES = {
    "reservoir": ["Property", "ContinuousProperty", "DiscreteProperty", "CategoricalProperty"],
    "surface": ["TriangulatedSet", "PolylineSet"],
    "well": ["WellboreTrajectory", "WellboreFrame", "WellboreMarker"]
}

def get_item_props_js(tree_category: str = "reservoir") -> str:
    """
    Génère le code JavaScript pour item_props
    """
    allowed_types = SELECTABLE_TYPES.get(tree_category, [])
    conditions = " || ".join([f"item.type?.includes('{t}')" for t in allowed_types])
    
    return f"item => ({{ selectable: {conditions} }})"