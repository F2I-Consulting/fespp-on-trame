"""Unit tests for fespp_on_trame.engine.element_type.

Guard of the ElementType contract: the kind → class resolution and the
declarative values (tree_role, eye, bucket, policies) must stay in step with
the per-type spec (doc/EN/TYPES_PARTICULARITES.md). The tracking, eye,
visibility and colouring layers all delegate to this contract."""
import pytest

from fespp_on_trame.engine import element_type as et
from fespp_on_trame.engine.element_type import (
    TreeRole, VisibilityPolicy, ColorPolicy, EyeKind,
    ElementType, Representation,
    Grouping, PartialType, GridRep, IjkGridRep, SurfaceRep,
    WellboreGeometryRep, SeismicFrameRep,
    FrameRep, ChannelFrameRep, MarkerFrameRep,
    Leaf, PropertyLeaf, MarkerLeaf,
)

TR, VP, CP, EK = TreeRole, VisibilityPolicy, ColorPolicy, EyeKind


# kind → expected concrete class
_RESOLUTION = [
    ("IjkGrid", IjkGridRep),
    ("UnstructuredGrid", GridRep),
    ("Sub", GridRep),
    ("Grid2d", SurfaceRep),
    ("PointSet", SurfaceRep),
    ("Polyline", SurfaceRep),
    ("PolylineSet", SurfaceRep),
    ("TriangulatedSet", SurfaceRep),
    ("Trajectory", WellboreGeometryRep),
    ("Completion", WellboreGeometryRep),
    ("Perfo", WellboreGeometryRep),
    ("Perforation", WellboreGeometryRep),
    ("SeismicWellboreFrame", SeismicFrameRep),
    ("Frame", ChannelFrameRep),
    ("MarkerFrame", MarkerFrameRep),
    ("Collection", Grouping),
    ("Wellbore", Grouping),
    ("Feature", Grouping),
    ("Interpretation", Grouping),
    ("Partial", PartialType),
    ("partial", PartialType),
    ("ContinuousProperty", PropertyLeaf),
    ("DiscreteProperty", PropertyLeaf),
    ("CategoricalProperty", PropertyLeaf),
    ("TimeSeries", PropertyLeaf),
    ("MultiRealization", PropertyLeaf),
    ("MultiRealizationTimeSeries", PropertyLeaf),
    ("Marker", MarkerLeaf),
]


class TestResolution:
    @pytest.mark.parametrize("kind,klass", _RESOLUTION)
    def test_kind_resolves_to_class(self, kind, klass):
        assert isinstance(et.for_kind(kind), klass)

    def test_singletons(self):
        # Same kind always returns the SAME instance (stateless singleton).
        assert et.for_kind("IjkGrid") is et.for_kind("IjkGrid")

    def test_all_known_kinds_registered(self):
        expected = {k for k, _ in _RESOLUTION}
        assert expected <= et.registered_kinds()


class TestContract:
    def test_ijkgrid_is_modal(self):
        e = et.for_kind("IjkGrid")
        assert e.tree_role() == TR.REPRESENTATION
        assert e.visibility_policy() == VP.IJK_MODAL
        assert e.color_policy() == CP.COLORABLE
        assert e.tracking_bucket() == et.BUCKET_REP
        assert e.eye_descriptor().kind == EK.REP

    @pytest.mark.parametrize("kind", ["UnstructuredGrid", "Sub", "Grid2d",
                                      "Trajectory", "SeismicWellboreFrame"])
    def test_standard_reps(self, kind):
        e = et.for_kind(kind)
        assert e.tree_role() == TR.REPRESENTATION
        assert e.visibility_policy() == VP.STANDARD
        assert e.tracking_bucket() == et.BUCKET_REP
        assert e.is_grouping() is False
        assert e.eye_descriptor().kind == EK.REP

    @pytest.mark.parametrize("kind", ["Collection", "Wellbore", "Feature",
                                      "Interpretation"])
    def test_groupings(self, kind):
        e = et.for_kind(kind)
        assert e.tree_role() == TR.FOLDER
        assert e.is_grouping() is True
        assert e.propagates_selection() is True
        assert e.is_selectable() is True
        assert e.eye_descriptor() is None
        assert e.tracking_bucket() is None
        assert e.visibility_policy() == VP.NONE
        assert e.color_policy() == CP.NONE

    @pytest.mark.parametrize("kind", ["Partial", "partial"])
    def test_partial_not_selectable(self, kind):
        e = et.for_kind(kind)
        assert isinstance(e, Grouping)        # folder-like
        assert e.is_selectable() is False
        assert e.propagates_selection() is False

    def test_channel_frame(self):
        e = et.for_kind("Frame")
        # folder-for-the-tree, representation-for-the-source
        assert isinstance(e, Representation)
        assert e.tree_role() == TR.FOLDER
        assert e.is_grouping() is True
        assert e.eye_descriptor() is None
        assert e.tracking_bucket() is None
        assert e.visibility_policy() == VP.ONE_AT_A_TIME

    def test_marker_frame(self):
        e = et.for_kind("MarkerFrame")
        assert isinstance(e, FrameRep)
        assert e.tree_role() == TR.FOLDER
        assert e.visibility_policy() == VP.MULTI

    @pytest.mark.parametrize("kind", ["ContinuousProperty", "DiscreteProperty",
                                      "CategoricalProperty", "TimeSeries",
                                      "MultiRealization", "MultiRealizationTimeSeries"])
    def test_property_leaves(self, kind):
        e = et.for_kind(kind)
        assert e.tree_role() == TR.LEAF
        assert e.tracking_bucket() == et.BUCKET_ARRAY
        assert e.color_policy() == CP.COLORABLE
        ed = e.eye_descriptor()
        assert ed.kind == EK.ARRAY
        assert ed.color == "purple"
        assert ed.multi is False

    @pytest.mark.parametrize("kind,ts,mr", [
        ("ContinuousProperty", False, False),
        ("DiscreteProperty", False, False),
        ("CategoricalProperty", False, False),
        ("TimeSeries", True, False),
        ("MultiRealization", False, True),
        ("MultiRealizationTimeSeries", True, True),
    ])
    def test_property_variant_predicates(self, kind, ts, mr):
        # Every property leaf is_property(); the TS / MR wrappers add the
        # time-series / multi-realization predicates (same eye / bucket).
        e = et.for_kind(kind)
        assert e.is_property() is True
        assert e.is_time_series() is ts
        assert e.is_multi_realization() is mr

    @pytest.mark.parametrize("kind", ["IjkGrid", "Frame", "Marker", "Collection",
                                      "Grid2d", "Trajectory"])
    def test_non_properties_have_no_property_predicates(self, kind):
        e = et.for_kind(kind)
        assert e.is_property() is False
        assert e.is_time_series() is False
        assert e.is_multi_realization() is False

    def test_marker_leaf(self):
        e = et.for_kind("Marker")
        assert e.tree_role() == TR.LEAF
        assert e.tracking_bucket() == et.BUCKET_MARKER
        assert e.color_policy() == CP.VISIBILITY_ONLY
        ed = e.eye_descriptor()
        assert ed.kind == EK.MARKER
        assert ed.color == "deep-orange"
        assert ed.multi is True


class TestEyeSingletons:
    """eye_descriptor() returns SHARED singletons — building a large tree
    must allocate nothing per node."""

    def test_descriptors_are_shared_singletons(self):
        assert et.for_kind("ContinuousProperty").eye_descriptor() is et.EYE_ARRAY
        assert et.for_kind("DiscreteProperty").eye_descriptor() is et.EYE_ARRAY
        assert et.for_kind("Marker").eye_descriptor() is et.EYE_MARKER
        assert et.for_kind("IjkGrid").eye_descriptor() is et.EYE_REP
        assert et.for_kind("Trajectory").eye_descriptor() is et.EYE_REP

    def test_same_instance_across_calls(self):
        e = et.for_kind("ContinuousProperty")
        assert e.eye_descriptor() is e.eye_descriptor()


class TestFallback:
    def test_unknown_kind_is_standard_rep(self):
        e = et.for_kind("TotallyUnknownKind")
        assert isinstance(e, Representation)
        assert e.visibility_policy() == VP.STANDARD

    def test_none_kind_falls_back(self):
        assert isinstance(et.for_kind(None), Representation)
        assert isinstance(et.for_kind(""), Representation)


class TestSyncWithCode:
    # data_load delegates the bucket decision to
    # element_type.for_kind(...).tracking_bucket(), so there is no separate
    # kind list to drift; TestContract.test_property_leaves covers that
    # invariant (every PropertyLeaf kind → array bucket).

    def test_no_kind_claimed_twice(self):
        # The registry raises on a collision at import time; the size check
        # also pins it: one entry per distinct kind of every concrete class.
        total = sum(len(set(c.KINDS)) for c in et._CONCRETE)
        assert len(et.registered_kinds()) == total
