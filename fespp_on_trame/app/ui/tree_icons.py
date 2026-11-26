"""The icon of a tree node kind, as a NAME.

Python cannot carry a shape, so it sends a name and the widget draws it:
``fespp-*`` is a drawing of the application's own set
(``widgets/_shared/icons/fespp-icons.js``, rendered by ``FpIcon``), ``mdi-*``
is a Material glyph rendered by the host's ``<v-icon>``. A renderer that
receives one must know both — the data explorer does.

Only two kinds keep an mdi glyph: a bare ``Property``, which has no drawing
of its own, and the grouping rows of the Interpretation / Feature layouts,
which are not objects of the model.
"""

TREE_ICONS = {
    # Reservoir
    "GridContainer": "fespp-grid-container",
    "IjkGrid": "fespp-grid-ijk",
    "ExplicitStructuredGrid": "fespp-grid-ijk",
    "UnstructuredGrid": "fespp-grid-unstructured",
    # the plugin shortens an xml tag by dropping a trailing "Representation",
    # so a SubRepresentation reaches the tree typed "Sub"
    "Sub": "fespp-sub-representation",
    "SubRepresentation": "fespp-sub-representation",
    "BlockedWellbore": "fespp-blocked-wellbore",
    "PropertiesFolder": "fespp-folder-properties",
    "SubRepresentationFolder": "fespp-folder-sub-representation",
    "BlockedWellboreFolder": "fespp-folder-blocked-wellbore",

    # Properties
    "Property": "mdi-chart-box-outline",
    "ContinuousProperty": "fespp-property-continuous",
    "DiscreteProperty": "fespp-property-discrete",
    "CategoricalProperty": "fespp-property-categorical",
    "TimeSeries": "fespp-time-series",
    "MultiRealization": "fespp-multi-realization",
    "MultiRealizationTimeSeries": "fespp-multi-realization-time-series",
    "Collection": "fespp-property-set",

    # Surface
    "Grid2d": "fespp-surface-grid2d",
    "Grid2dRepresentation": "fespp-surface-grid2d",
    "PointSet": "fespp-point-set",
    "TriangulatedSet": "fespp-surface-tin",
    "Polyline": "fespp-polyline",
    "PolylineSet": "fespp-polyline-set",

    # Well
    "Wellbore": "fespp-wellbore",
    "Trajectory": "fespp-trajectory",
    "WellboreTrajectory": "fespp-trajectory",
    "Frame": "fespp-log-frame",
    "WellboreFrame": "fespp-log-frame",
    "WellboreChannel": "fespp-log-channel",
    "MarkerFrame": "fespp-marker-frame",
    "WellboreMarkerFrame": "fespp-marker-frame",
    "Marker": "fespp-marker",
    "WellboreMarker": "fespp-marker",
    "WellboreCompletion": "fespp-completion",
    "Perforation": "fespp-perforation",
    "WellboreLogsFolder": "fespp-folder-logs",
    "WellboreMarkersFolder": "fespp-folder-markers",
    "WellboreCompletionsFolder": "fespp-folder-completions",

    # Grouping nodes inserted by the alternate tree-hierarchy modes
    # (ByInterpretation / ByFeatureAndInterpretation).
    "Feature": "mdi-shape-outline",
    "Interpretation": "mdi-script-text-outline",
}

# The button of a family's tree card in a view's toolbar: the data tree,
# its root drawn as the family (engine/tree_families names them); Other, a
# rep of none of them, the data tree as it is.
FAMILY_TREE_ICONS = {
    "Reservoir": "fespp-data-tree-reservoir",
    "Surface": "fespp-data-tree-surface",
    "Well": "fespp-data-tree-well",
    "Seismic": "fespp-data-tree-seismic",
    "Other": "fespp-data-tree",
}

# What a kind with no entry draws: the "unknown object" mark of the set — a
# dotted circle that says the type was not recognised, where a folder glyph
# would quietly claim it is a folder.
FALLBACK_ICON = "fespp-unknown"


def get_icon_for_type(node_type: str) -> str:
    """Return the icon name for a node kind.

    Without an exact entry, falls back to a substring match (an unlisted
    "...Property" kind inherits the "Property" icon), and finally to the
    unknown mark.
    """
    # A node with no "type" attribute reaches here as None, and the substring
    # fallback below would raise TypeError rather than degrade — an icon
    # lookup must never be able to break the tree.
    if not node_type:
        return FALLBACK_ICON
    if node_type in TREE_ICONS:
        return TREE_ICONS[node_type]

    for key, icon in TREE_ICONS.items():
        if key in node_type or node_type in key:
            return icon

    return FALLBACK_ICON


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
    """Return the primary icon name for a tree node.

    A synthetic type that collapses a sub-tree into a single leaf uses the
    underlying property kind (FESPP's `propType` attribute), so the icon
    matches what is displayed; it falls back to its own icon when the node
    carries no property type.
    """
    if node_type in _SYNTHETIC_PROPERTY_TYPES and prop_kind:
        return get_icon_for_type(prop_kind)
    return get_icon_for_type(node_type)
