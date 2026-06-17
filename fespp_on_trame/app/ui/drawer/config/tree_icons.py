"""Material Design icon map for tree node kinds."""

TREE_ICONS = {
    # Reservoir
    "IjkGrid": "mdi-axis-arrow-info",
    "UnstructuredGrid": "mdi-data-matrix",
    "Property": "mdi-chart-box-outline",
    "ContinuousProperty": "mdi-chart-line",
    "DiscreteProperty": "mdi-chart-bar",
    "CategoricalProperty": "mdi-chart-bar",
    "TimeSeries": "mdi-timeline-clock",
    "MultiRealization": "mdi-layers-triple",
    "MultiRealizationTimeSeries": "mdi-animation",

    # Surface
    "Grid2d": "mdi-grid-large",
    "PointSet": "mdi-circle-medium",
    "TriangulatedSet": "mdi-triangle-outline",
    "PolylineSet": "mdi-vector-polyline",

    # Well
    "Wellbore": "mdi-transmission-tower",
    "Trajectory": "mdi-pipe",
    "Frame": "mdi-vector-line",
    "MarkerFrame": "mdi-flag-outline",
    "Marker": "mdi-map-marker",

    # Grouping nodes inserted by the alternate tree-hierarchy modes
    # (ByInterpretation / ByFeatureAndInterpretation).
    "Feature": "mdi-shape-outline",
    "Interpretation": "mdi-script-text-outline",
}


def get_icon_for_type(node_type: str) -> str:
    """Return the icon name for a node kind. Falls back to a substring
    match so e.g. "ContinuousProperty" inherits the "Property" icon
    when no exact entry exists, and finally to mdi-folder when nothing
    matches."""
    if node_type in TREE_ICONS:
        return TREE_ICONS[node_type]

    for key, icon in TREE_ICONS.items():
        if key in node_type or node_type in key:
            return icon

    return "mdi-folder"


# Synthetic kinds whose primary icon should reflect the underlying
# property type (Continuous / Discrete / Categorical) instead of the
# synthetic wrapper itself. The TS / MR aspect is conveyed via
# secondary badges in the treeview.
_SYNTHETIC_PROPERTY_TYPES = {
    "TimeSeries",
    "MultiRealization",
    "MultiRealizationTimeSeries",
}


def get_primary_icon(node_type: str, prop_kind: str = None) -> str:
    """Primary icon for a tree node. For synthetic types that collapse
    a sub-tree into a single leaf, use the underlying property kind
    (FESPP's `propKind` attribute) so the icon matches what's
    displayed; fall back to the synthetic type's own icon when
    `propKind` is missing (older data)."""
    if node_type in _SYNTHETIC_PROPERTY_TYPES and prop_kind:
        return get_icon_for_type(prop_kind)
    return get_icon_for_type(node_type)


def get_icon_expression(type_field: str = "item.type") -> str:
    """Build a Vue-template ternary that selects the icon name from
    `item.type` at render time (kept for templates that resolve icons
    inline rather than via the precomputed `item.icon`)."""
    conditions = []
    for node_type, config in TREE_ICONS.items():
        if node_type != "default":
            conditions.append(f"{type_field} === '{node_type}' ? '{config['icon']}'")

    expression = " : ".join(conditions) + f" : '{TREE_ICONS['default']['icon']}'"
    return expression
