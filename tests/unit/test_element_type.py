"""Tests unitaires pour fespp_on_trame.app.core.element_type.

Garde-fou du contrat ElementType : la résolution kind→classe et les
valeurs déclaratives (tree_role, eye, bucket, policies) doivent rester en
phase avec TYPES_PARTICULARITES — c'est ce contrat auquel les couches
tracking / œil / visibilité / coloration délèguent (Steps 1-3, 5)."""
import pytest

from fespp_on_trame.app.core import element_type as et
from fespp_on_trame.app.core.element_type import (
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
        assert e.primary_hidden() is False
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
        assert e.primary_hidden() is True

    def test_marker_frame(self):
        e = et.for_kind("MarkerFrame")
        assert isinstance(e, FrameRep)
        assert e.tree_role() == TR.FOLDER
        assert e.visibility_policy() == VP.MULTI
        assert e.primary_hidden() is True

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


class TestChildBehaviour:
    """Step 4.1 — the per-type child behaviour lives on the frame classes
    (strategy pattern); RepInScene passes itself as `ris`."""

    def test_frame_store_attrs(self):
        ch = et.for_kind("Frame")
        assert ch._child_store_attr == "_channel_extractors"
        assert ch._reg_prefix == "chn"
        mk = et.for_kind("MarkerFrame")
        assert mk._child_store_attr == "_marker_extractors"
        assert mk._reg_prefix == "mrk"

    def test_base_child_methods_are_noops(self):
        g = et.for_kind("IjkGrid")  # a non-frame rep
        assert g.set_child_visible(None, "x", True) is None
        assert g.child_source(None, "x") is None
        assert g.visible_child_source(None) is None
        assert g.visible_child_displays(None) == []
        assert g.set_child_color(None, "x", "#fff") is None

    def test_frame_child_source_reads_ris_store(self):
        # child_source(create=False) just reads ris.<store>; an empty store
        # returns None without touching paraview. Each frame type dispatches
        # to its OWN store (channels vs markers).
        class _Ris:
            _channel_extractors = {}
            _marker_extractors = {}
        ris = _Ris()
        assert et.for_kind("Frame").child_source(ris, "c", create=False) is None
        ris._channel_extractors["c"] = "CHAN"
        assert et.for_kind("Frame").child_source(ris, "c", create=False) == "CHAN"
        ris._marker_extractors["m"] = "MARK"
        assert et.for_kind("MarkerFrame").child_source(ris, "m", create=False) == "MARK"
        # cross-store isolation: a channel frame doesn't see marker store.
        assert et.for_kind("Frame").child_source(ris, "m", create=False) is None


class TestFallback:
    def test_unknown_kind_is_standard_rep(self):
        e = et.for_kind("TotallyUnknownKind")
        assert isinstance(e, Representation)
        assert e.visibility_policy() == VP.STANDARD

    def test_none_kind_falls_back(self):
        assert isinstance(et.for_kind(None), Representation)
        assert isinstance(et.for_kind(""), Representation)


class TestSyncWithCode:
    # NOTE: the old `_DATA_ARRAY_KINDS == PropertyLeaf.KINDS` sync test was
    # removed in Step 1 — data_load now DELEGATES the bucket decision to
    # element_type.for_kind(...).tracking_bucket(), so there is no separate
    # constant to drift. The invariant is covered by
    # TestContract.test_property_leaves (every PropertyLeaf kind → array bucket).

    def test_no_kind_claimed_twice(self):
        # Import-time guard already raises on collision; assert the
        # registry size matches the sum of distinct KINDS.
        total = sum(len(set(c.KINDS)) for c in et._CONCRETE)
        assert len(et.registered_kinds()) == total
