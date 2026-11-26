"""RESQML assembly node-kind constants shared across the tree UI and the
activator, kept in a dependency-free leaf module so both `engine/legacy/activator.py`
and `app/ui/selection_deps.py` can import it without a circular import."""

#: What the reader prefixes the title of a partial object with — a reference
#: whose target is not in the file: no geometry, no values, nothing to load.
PARTIAL_PREFIX = "!!!PARTIAL!!!"


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
    # here (and auto-checks separately when a property loads), so the
    # cascade never reaches the geometry.
    "PropertiesFolder",
    # The wellbore's folders: its log frames under "logs", its marker
    # frames under "markers", its completions under "completions"; the
    # trajectory stays a direct child. Checking a folder checks everything
    # in it, as the C++ isGroupingType says.
    "WellboreLogsFolder",
    "WellboreMarkersFolder",
    "WellboreCompletionsFolder",
)


#: The three families the data tree's tabs sort the file into — Reservoir /
#: Surface / Well — by the type of the node that HEADS each: the very lists
#: the tree widget's DEFAULT_TABS holds (`widgets/tree` DataExplorerTree.vue;
#: keep the two in step). A tab keeps a matching node with its whole subtree,
#: so what sits under a Wellbore is a Well whatever its own type says: the
#: family of any node is that of the first node on its path listed here.
#: A container (GridContainer) is filed by the geometry it wraps
#: (`Tree.family_type`: since 27/10 a surface has one too); the name stays
#: under Reservoir for a container whose geometry cannot be found.
FAMILIES = (
    ("Reservoir", ("GridContainer", "IjkGrid", "UnstructuredGrid",
                   "ExplicitStructuredGrid")),
    ("Surface", ("TriangulatedSet", "Grid2d", "Grid2dRepresentation",
                 "Polyline", "PolylineSet", "PointSet")),
    ("Well", ("Wellbore", "Trajectory", "WellboreTrajectory", "MarkerFrame")),
)
#: The family of the IJK grids whose geometry is a lattice — a velocity model,
#: a seismic cube. It lists no type: such a grid has a reservoir grid's, so
#: its row files it (engine/tree_families).
SEISMIC_FAMILY = "Seismic"
#: Where a node none of the three lists goes, so that a tree sorted by family
#: never hides one: a tab of that name is drawn only while the file has some.
OTHER_FAMILY = "Other"


#: The geometry a container (GridContainer) wraps in its "properties" folder,
#: beside the properties: a grid, and since 27/10 a surface, a polyline or a
#: point set (the plugin lays them all out alike). A property of a container
#: resolves to this leaf (`Tree.find_representation_node`).
CONTAINED_KINDS = ("IjkGrid", "UnstructuredGrid",
                   "Grid2d", "Grid2dRepresentation", "TriangulatedSet",
                   "PolylineSet", "Polyline", "PointSet")

#: The rows that draw an object itself: the geometry of a grid or a surface,
#: the trajectory of a well (a tick on a folder falls back on one of them,
#: app/scene/activation).
GEOMETRY_KINDS = CONTAINED_KINDS + ("ExplicitStructuredGrid", "Trajectory", "WellboreTrajectory")

#: The frames of a well's logs: each log under one is a block of its own.
LOG_FRAMES = ("Frame", "SeismicWellboreFrame")

#: The representation kinds a threshold can isolate: any that carries
#: values on its elements. The IJK grid also gets crops and slicers; the
#: others get the extractor and the threshold chain, which never needed a
#: structured grid (the PO, 27/10: "dès qu'il y a 1 propriété de cochée,
#: ijkgrid ou autre, même surface").
ISOLATABLE_KINDS = ("IjkGrid", "UnstructuredGrid", "Sub",
                    "TriangulatedSet", "Grid2d", "Grid2dRepresentation",
                    "PolylineSet", "PointSet")


def is_ijk_grid(ds):
    """A dataset of an IJK grid: a vtkExplicitStructuredGrid (corner-point
    geometry), a vtkStructuredGrid with at least one layer of cells (a
    lattice; a 2D grid of a surface has none)."""
    if ds is None:
        return False
    if ds.IsA("vtkExplicitStructuredGrid"):
        return True
    if ds.IsA("vtkStructuredGrid"):
        ext = ds.GetExtent()
        return ext[5] > ext[4]
    return False


def family_of_type(node_type):
    """The family that lists `node_type`, "" when none does."""
    for name, types in FAMILIES:
        if node_type in types:
            return name
    return ""


#: Node kinds that carry VALUES: a property leaf, whatever shape its values
#: take (one per element, one per realization, one per timestep, both).
#: A statistics row, a cross-plot axis and a formula input all read
#: values, so these are the nodes those actions apply to — a folder, a grid,
#: a well or a feature has none. "Property" is the generic kind a collector
#: emits when it cannot refine it further.
PROPERTY_KINDS = (
    "ContinuousProperty",
    "DiscreteProperty",
    "CategoricalProperty",
    "TimeSeries",
    "MultiRealization",
    "MultiRealizationTimeSeries",
    "Property",
)


#: The units that say "a fraction" and the ones that say "a percentage",
#: as files spell them: a porosity in ``p.u.`` (porosity units) is a
#: percentage, one in ``v/v`` or ``m3/m3`` a fraction, and the two are the
#: same quantity a hundred apart. One vocabulary for the well-log cutoffs,
#: the volumetrics and the Log ↔ Grid table, so a log in p.u. against a
#: grid in v/v is scaled and not read as the model contradicting the data.
FRACTION_UNITS = frozenset({"", "v/v", "m3/m3", "m³/m³", "fraction", "frac",
                            "1", "unitless", "euc", "dec", "ratio"})
PERCENT_UNITS = frozenset({"%", "p.u.", "pu", "percent", "pct", "%vol"})


def percent_factor(unit):
    """0.01 for a unit that says "a percentage", 1.0 otherwise: what a value
    declared in that unit is multiplied by to be read as a fraction."""
    return 0.01 if (unit or "").strip().lower() in PERCENT_UNITS else 1.0
