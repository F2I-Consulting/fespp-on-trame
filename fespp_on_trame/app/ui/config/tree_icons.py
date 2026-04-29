"""
Configuration des icônes pour les différents types de nœuds dans les TreeViews
"""

# Mapping entre les types de nœuds et leurs icônes Material Design
TREE_ICONS = {
    # Reservoir types
    "IjkGrid": "mdi-axis-arrow-info",
    "UnstructuredGrid": "mdi-data-matrix",
    "Property": "mdi-chart-box-outline",
    "ContinuousProperty": "mdi-chart-line",
    "DiscreteProperty": "mdi-chart-bar",
    "CategoricalProperty": "mdi-chart-bar",
    "TimeSeries": "mdi-timeline-clock",
    "MultiRealization": "mdi-layers-triple",
    "MultiRealizationTimeSeries": "mdi-animation",

    # Surface types
    "Grid2d": "mdi-grid-large",
    "PointSet": "mdi-circle-medium",
    "TriangulatedSet": "mdi-triangle-outline",
    "PolylineSet": "mdi-vector-polyline",
    
    # Well types
    "Wellbore": "mdi-transmission-tower",
    "Trajectory": "mdi-pipe",
    "Frame": "mdi-vector-line",
    "MarkerFrame":"mdi-flag-outline",
    "Marker": "mdi-map-marker",
}

def get_icon_for_type(node_type: str) -> dict:
    """
    Retourne l'icône et la couleur correspondant au type de nœud.

    Args:
        node_type: Le type du nœud (ex: "IjkGrid", "Property", etc.)

    Returns:
        Dict contenant 'icon' et 'color'
    """
    # Recherche exacte
    if node_type in TREE_ICONS:
        return TREE_ICONS[node_type]

    # Recherche partielle (ex: "ContinuousProperty" contient "Property")
    for key, icon in TREE_ICONS.items():
        if key in node_type or node_type in key:
            return icon

    # Fallback par défaut
    return "mdi-folder"


# Synthetic types where the primary icon should reflect the underlying
# property type (Continuous/Discrete/Categorical) — not the synthetic
# wrapper. The MR/TS aspect is conveyed via secondary badges in the
# treeview.
_SYNTHETIC_PROPERTY_TYPES = {
    "TimeSeries",
    "MultiRealization",
    "MultiRealizationTimeSeries",
}


def get_primary_icon(node_type: str, prop_kind: str = None) -> str:
    """Return the primary icon for a tree node.

    For synthetic types (TimeSeries / MultiRealization /
    MultiRealizationTimeSeries) that collapse a sub-tree into a single
    leaf, the icon should reflect the underlying property type — exposed
    by FESPP as the `propKind` assembly attribute. Falls back to the
    synthetic type's own icon when `propKind` is missing (older data).
    """
    if node_type in _SYNTHETIC_PROPERTY_TYPES and prop_kind:
        return get_icon_for_type(prop_kind)
    return get_icon_for_type(node_type)

def get_icon_expression(type_field: str = "item.type") -> str:
    """
    Génère une expression JavaScript pour déterminer l'icône dynamiquement.
    Utile pour les templates Vue.
    
    Args:
        type_field: Le champ contenant le type dans l'objet item
        
    Returns:
        Expression JavaScript sous forme de string
    """
    conditions = []
    for node_type, config in TREE_ICONS.items():
        if node_type != "default":
            conditions.append(f"{type_field} === '{node_type}' ? '{config['icon']}'")
    
    # Ajouter le fallback
    expression = " : ".join(conditions) + f" : '{TREE_ICONS['default']['icon']}'"
    return expression
