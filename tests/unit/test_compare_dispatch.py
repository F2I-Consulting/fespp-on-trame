"""engine/compare_dispatch: one free selection of properties, one tab per kind.

The selection becomes a statistics matrix, overlaid distributions and
cross-plot seeds. Pure functions over a fake assembly, no ParaView (the
conftest stubs); the value reads are monkeypatched with numpy arrays.
"""
import pytest

from tests.unit.fake_assembly import FakeDataAssembly
from fespp_on_trame.engine.tree import Tree
from fespp_on_trame.engine import compare_dispatch as cd
from fespp_on_trame.engine import compare_tree as ct
from fespp_on_trame.engine import compare_matrix
from fespp_on_trame.engine import derived_props


def _tree():
    """Two grids with properties of four kinds.

    Grid A: PORO, NTG, FACIES (discrete) and the multi-realization PORO_MR;
    grid B: SW and PORO_B. Kinds: porosity (PORO, PORO_B, PORO_MR), net to
    gross (NTG), facies (FACIES), saturation (SW)."""
    asm = FakeDataAssembly()
    grid_a = asm.add_node_with_attrs("_gridA", 0, label="IjkGrid_A", title="A",
                                     type="IjkGrid", typeCode="2")
    grid_b = asm.add_node_with_attrs("_gridB", 0, label="IjkGrid_B", title="B",
                                     type="IjkGrid", typeCode="2")
    nodes = {
        "poro": asm.add_node_with_attrs(
            "_poro", grid_a, label="Properties_PORO", title="PORO",
            type="ContinuousProperty", typeCode="4", propertyKind="porosity",
            uom="m3/m3"),
        "ntg": asm.add_node_with_attrs(
            "_ntg", grid_a, label="Properties_NTG", title="NTG",
            type="ContinuousProperty", typeCode="4",
            propertyKind="net to gross"),
        "facies": asm.add_node_with_attrs(
            "_facies", grid_a, label="Properties_FACIES", title="FACIES",
            type="DiscreteProperty", typeCode="4", propertyKind="facies"),
        "poro_mr": asm.add_node_with_attrs(
            "_poro_mr", grid_a, label="MR_PORO_MR", title="PORO_MR",
            type="MultiRealization", typeCode="4", propertyKind="porosity",
            realization_indices="0,1,2"),
        "sw": asm.add_node_with_attrs(
            "_sw", grid_b, label="Properties_SW", title="SW",
            type="ContinuousProperty", typeCode="4",
            propertyKind="saturation"),
        "poro_b": asm.add_node_with_attrs(
            "_poro_b", grid_b, label="Properties_PORO_B", title="PORO_B",
            type="ContinuousProperty", typeCode="4", propertyKind="porosity"),
    }
    tree = Tree(asm)
    paths = {k: asm.GetNodePath(n) for k, n in nodes.items()}
    paths["grid_a"] = asm.GetNodePath(grid_a)
    paths["derived"] = derived_props.path_for(paths["grid_a"], "PHIE")
    return tree, paths


class _FakeStore:
    """The derived store's read side: one recipe PHIE on grid A."""

    def __init__(self, path):
        self._path = path

    def active_paths(self):
        return [self._path]

    def title(self, path):
        return "ƒ PHIE" if path == self._path else ""

    def get(self, path):
        return ({"prop_kind": "ContinuousProperty", "uom": ""}
                if path == self._path else None)

    def axis_caps(self, tree, path):
        return {"is_mr": False, "is_ts": False, "reals": []}


@pytest.fixture
def store():
    tree, p = _tree()
    derived_props.set_store(_FakeStore(p["derived"]))
    yield tree, p
    derived_props.set_store(None)


@pytest.fixture
def values(monkeypatch):
    np = pytest.importorskip("numpy")
    n = 40
    data = {
        "poro": np.linspace(0.05, 0.35, n),
        "ntg": np.where(np.arange(n) % 4 == 0, np.nan, 0.8),
        "facies": (np.arange(n) % 3).astype(float),
        "poro_mr": np.linspace(0.1, 0.2, n),
        "sw": np.linspace(0.2, 0.9, n),
        "poro_b": np.linspace(0.0, 0.1, n),
        "derived": np.linspace(0.02, 0.3, n),
    }

    def fake_values(state, tree, source_registry, path, rep, real_idx=None,
                    ts_idx=None):
        if derived_props.is_derived(path):
            return data["derived"]
        vals = data[path.rsplit("/_", 1)[-1]]
        # A realization shifts the values, so two realizations never tie.
        return vals + (0.01 * real_idx if real_idx else 0.0)
    monkeypatch.setattr(cd, "_values_for", fake_values)
    return data


def _items(*specs):
    return [{"path": p, "real": r, "ts": t} for p, r, t in specs]


def _boom(*_a, **_k):
    raise AssertionError("the values were read again")


class TestKeys:
    def test_round_trip(self):
        assert cd.item_key("/data/x", None, None) == "/data/x||"
        assert cd.item_key("/data/x", 3, 0) == "/data/x|3|0"
        assert cd.item_key("/data/x", None, 7) == "/data/x||7"
        assert cd.item_key("derived:///data/_g#a|b", 2, None) == "derived:///data/_g#a|b|2|"


class TestKindTree:
    def test_two_kinds_two_reps(self, store):
        import xml.etree.ElementTree as ET
        tree, p = store
        xml, path_map = ct.kind_tree_xml(
            tree, [p["poro"], p["sw"], p["poro_b"], p["ntg"]])
        root = ET.fromstring(xml)
        assert root.tag == "compare"
        kinds = {k.get("title"): k for k in root}
        assert set(kinds) == {"porosity", "saturation", "net to gross"}
        assert all(k.get("type") == "KindFolder" for k in root)
        # Porosity spans both grids: one rep folder each.
        poro = kinds["porosity"]
        reps = {r.get("title"): r for r in poro}
        assert set(reps) == {"A", "B"}
        assert all(r.get("type") == "RepFolder" for r in poro)
        leaf = reps["A"][0]
        assert leaf.get("type") == "CompareItem"
        assert leaf.get("title") == "PORO"
        assert leaf.get("propType") == "ContinuousProperty"
        assert leaf.get("units") == "m3/m3"
        assert reps["B"][0].get("units") is None

    def test_path_map_follows_the_widget_rule(self, store):
        """The path map uses the widget's naming rule.

        The widget names a node "/<root>/<tag>/…" from the element tags,
        starting at the root's children."""
        import xml.etree.ElementTree as ET
        tree, p = store
        xml, path_map = ct.kind_tree_xml(tree, [p["poro"], p["sw"]])
        root = ET.fromstring(xml)
        expected = {}
        for k in root:
            for r in k:
                for leaf in r:
                    expected[f"/{root.tag}/{k.tag}/{r.tag}/{leaf.tag}"] = \
                        leaf.get("title")
        assert {k: cd._title(tree, v) for k, v in path_map.items()} == expected
        assert set(path_map.values()) == {p["poro"], p["sw"]}
        # Tags are ids, unique per level.
        assert len({k.tag for k in root}) == len(list(root))
        assert list(path_map) == ["/compare/k0/r0/p0", "/compare/k1/r1/p1"]

    def test_derived_path_lands_under_no_kind(self, store):
        import xml.etree.ElementTree as ET
        tree, p = store
        xml, path_map = ct.kind_tree_xml(tree, [p["poro"], p["derived"]])
        root = ET.fromstring(xml)
        kinds = {k.get("title"): k for k in root}
        assert set(kinds) == {"porosity", "no kind"}
        rep = kinds["no kind"][0]
        assert rep.get("title") == "A"
        leaf = rep[0]
        assert leaf.get("propType") == "DerivedProperty"
        assert leaf.get("title") == "ƒ PHIE"
        assert path_map["/compare/k1/r1/p1"] == p["derived"]

    def test_every_leaf_declares_the_visibility_eye(self, store):
        """Every leaf declares the visibility eye; the host decides which show it.

        The eye means "shown in a 3D view" in this tree as in the data tree.
        Which leaves may carry one is the host's call (`eye_paths`, the
        properties the session holds), so every leaf declares it."""
        import xml.etree.ElementTree as ET
        tree, p = store
        xml, _ = ct.kind_tree_xml(tree, [p["poro"], p["sw"]])
        leaves = [leaf for k in ET.fromstring(xml) for r in k for leaf in r]
        assert leaves and all(leaf.get("eye") == "array" for leaf in leaves)

    def test_a_rep_is_named_by_its_wellbore_when_its_own_name_repeats(self):
        """A rep folder whose title repeats is prefixed with its wellbore.

        Several wells may each hold a frame titled "Well Log Frame": the
        folder carries the wellbore name, or the reader picks a curve blind."""
        import xml.etree.ElementTree as ET
        asm = FakeDataAssembly()
        titles = []
        for name in ("WELL-A", "WELL-B"):
            well = asm.add_node_with_attrs(
                f"_{name}", 0, label=name, title=name, type="Wellbore",
                typeCode="2")
            frame = asm.add_node_with_attrs(
                "_frame", well, label="Frame", title="Well Log Frame",
                type="Frame", typeCode="2")
            leaf = asm.add_node_with_attrs(
                "_gr", frame, label="Properties_GR", title="GR",
                type="ContinuousProperty", typeCode="4",
                propertyKind="gamma ray")
            titles.append(asm.GetNodePath(leaf))
        xml, _ = ct.kind_tree_xml(Tree(asm), titles)
        reps = [r.get("title") for k in ET.fromstring(xml) for r in k]
        assert sorted(reps) == ["WELL-A · Well Log Frame",
                                "WELL-B · Well Log Frame"]

    def test_unknown_and_empty_paths_are_skipped(self, store):
        tree, p = store
        xml, path_map = ct.kind_tree_xml(tree, ["/data/_nope", "", p["ntg"]])
        assert list(path_map.values()) == [p["ntg"]]
        assert ct.kind_tree_xml(tree, []) == ("<compare></compare>", {})

    def test_mr_leaf_keeps_its_node_type(self, store):
        import xml.etree.ElementTree as ET
        tree, p = store
        xml, _ = ct.kind_tree_xml(tree, [p["poro_mr"]])
        leaf = ET.fromstring(xml)[0][0][0]
        assert leaf.get("propType") == "MultiRealization"

    def test_an_untitled_node_still_gets_a_leaf(self, store):
        """A node the tree cannot title is still tickable.

        Without a leaf the property could not be compared at all."""
        import xml.etree.ElementTree as ET
        tree, p = store
        asm = tree._data_assembly
        nid = asm.add_node_with_attrs("_bare", asm.GetFirstNodeByPath(
            p["grid_a"]), label="Properties_BARE",
            type="ContinuousProperty", typeCode="4")
        path = asm.GetNodePath(nid)
        xml, path_map = ct.kind_tree_xml(tree, [path])
        leaf = ET.fromstring(xml)[0][0][0]
        assert leaf.get("title") == "_bare"
        assert list(path_map.values()) == [path]


def _mixed_tree():
    """One porosity per representation family, and a saturation on the grid.

    One porosity on a grid, one on a log frame under a wellbore, one on a
    surface, one on a single polyline (the plugin's own spelling of one
    PolylineRepresentation, a Surface like a set of them), one on a rep of
    a type no family lists; a saturation on the grid only. Kinds: porosity
    (5 reps), saturation (1)."""
    asm = FakeDataAssembly()
    grid = asm.add_node_with_attrs("_grid", 0, label="Grid", title="Grid",
                                   type="GridContainer", typeCode="2")
    props = asm.add_node_with_attrs("_props", grid, label="properties",
                                    title="properties",
                                    type="PropertiesFolder", typeCode="2")
    asm.add_node_with_attrs("_geom", props, label="Geo", title="SolidColor",
                            type="IjkGrid", typeCode="2")
    well = asm.add_node_with_attrs("_well", 0, label="W1", title="W1",
                                   type="Wellbore", typeCode="2")
    frame = asm.add_node_with_attrs("_frame", well, label="Frame",
                                    title="Well Log Frame", type="Frame",
                                    typeCode="2")
    surf = asm.add_node_with_attrs("_surf", 0, label="Top", title="Top",
                                   type="TriangulatedSet", typeCode="2")
    line = asm.add_node_with_attrs("_line", 0, label="Line", title="Line",
                                   type="Polyline", typeCode="2")
    odd = asm.add_node_with_attrs("_odd", 0, label="Odd", title="Odd",
                                  type="Sub", typeCode="2")
    nodes = {}
    for key, parent, kind in (("grid_poro", props, "porosity"),
                              ("log_poro", frame, "porosity"),
                              ("surf_poro", surf, "porosity"),
                              ("line_poro", line, "porosity"),
                              ("odd_poro", odd, "porosity"),
                              ("grid_sw", props, "saturation")):
        nodes[key] = asm.add_node_with_attrs(
            f"_{key}", parent, label=f"Properties_{key}", title=key.upper(),
            type="ContinuousProperty", typeCode="4", propertyKind=kind)
    tree = Tree(asm)
    paths = {k: asm.GetNodePath(n) for k, n in nodes.items()}
    paths["grid"] = asm.GetNodePath(grid)
    return tree, paths


class TestFamilies:
    """Rep folders carry the data tree's family (Reservoir / Surface / Well).

    The family is the one the data tree's tabs file the representation
    under, so the docked tree gets the same three tabs with the same rule:
    the family of the first node on the path that a family lists, and its
    whole subtree with it."""

    def test_a_rep_is_of_the_family_of_its_first_listed_ancestor(self):
        tree, p = _mixed_tree()
        fam = {k: cd.rep_family(tree, cd._rep_path(tree, p[k]))
               for k in ("grid_poro", "log_poro", "surf_poro", "line_poro",
                         "odd_poro")}
        # A grid property resolves to the geometry under the GridContainer,
        # a log to its Frame under the Wellbore: the family is the folder's.
        assert fam == {"grid_poro": "Reservoir", "log_poro": "Well",
                       "surf_poro": "Surface", "line_poro": "Surface",
                       "odd_poro": "Other"}
        # A property with no rep still has a tab to be found in.
        assert cd.rep_family(tree, "") == "Other"
        assert cd.rep_family(None, "/data/_grid") == "Other"

    def test_every_rep_folder_carries_its_family(self):
        import xml.etree.ElementTree as ET
        tree, p = _mixed_tree()
        xml, path_map = ct.kind_tree_xml(tree, list(p[k] for k in (
            "grid_poro", "log_poro", "surf_poro", "line_poro", "odd_poro",
            "grid_sw")))
        root = ET.fromstring(xml)
        by_leaf = {}
        for k in root:
            assert k.get("family") is None   # a kind spans families
            for r in k:
                assert r.get("type") == "RepFolder"
                for leaf in r:
                    assert leaf.get("family") is None   # inherits its rep's
                    by_leaf[leaf.get("title")] = r.get("family")
        assert by_leaf == {"GRID_PORO": "Reservoir", "LOG_PORO": "Well",
                           "SURF_PORO": "Surface", "LINE_PORO": "Surface",
                           "ODD_PORO": "Other", "GRID_SW": "Reservoir"}
        # The synthetic path rule is untouched by the attribute.
        assert list(path_map) == [f"/compare/k0/r{i}/p{i}" for i in range(5)] \
            + ["/compare/k1/r5/p5"]

    def test_a_derived_property_takes_the_family_of_its_grid(self, store):
        import xml.etree.ElementTree as ET
        tree, p = store
        xml, _ = ct.kind_tree_xml(tree, [p["derived"]])
        assert ET.fromstring(xml)[0][0].get("family") == "Reservoir"

    @staticmethod
    def _tab_counts(xml, tabs):
        """Replay the widget's tab label counts.

        A kind folder is a root of a tab when at least one of its reps is
        of that family (a match keeps its ancestors)."""
        import xml.etree.ElementTree as ET
        root = ET.fromstring(xml)
        return {t["name"]: sum(
            1 for k in root if any(r.get("family") == t["name"] for r in k))
            for t in tabs}

    def test_the_tabs_are_the_families_plus_other_while_needed(self):
        tree, p = _mixed_tree()
        assert [t["name"] for t in ct.tree_tabs("")] == \
            ["Reservoir", "Surface", "Well", "Seismic"]
        assert ct.tree_tabs("<compare></compare>") == ct.tree_tabs("")
        assert ct.tree_tabs("<not xml") == ct.tree_tabs("")
        xml, _ = ct.kind_tree_xml(tree, [p["grid_poro"], p["log_poro"]])
        tabs = ct.tree_tabs(xml)
        assert [t["name"] for t in tabs] == ["Reservoir", "Surface", "Well", "Seismic"]
        assert all(t["types"] == [] for t in tabs)
        # A family the file has nothing of is an empty tab, not a missing one.
        assert self._tab_counts(xml, tabs) == {"Reservoir": 1, "Surface": 0,
                                               "Well": 1, "Seismic": 0}
        xml, _ = ct.kind_tree_xml(tree, [p["odd_poro"]])
        assert [t["name"] for t in ct.tree_tabs(xml)] == \
            ["Reservoir", "Surface", "Well", "Seismic", "Other"]

    def test_tab_counts_count_kind_folders_of_the_family(self):
        """A tab counts the kind folders that have a rep of its family.

        "Reservoir (2)": two kinds have a rep on the grid; porosity is
        counted once per tab it shows in, since it spans five reps."""
        tree, p = _mixed_tree()
        xml, _ = ct.kind_tree_xml(tree, list(p[k] for k in (
            "grid_poro", "log_poro", "surf_poro", "line_poro", "odd_poro",
            "grid_sw")))
        tabs = ct.tree_tabs(xml)
        assert self._tab_counts(xml, tabs) == {"Reservoir": 2, "Surface": 1,
                                               "Well": 1, "Seismic": 0, "Other": 1}


class TestWhatTheFileHolds:
    """The tree lists what the file holds, not what happens to be loaded.

    The kind, the rep and the title are attributes of the assembly, so the
    walk costs no read at all."""

    def test_every_property_of_the_assembly_is_listed(self, store):
        tree, p = store
        found = ct.assembly_property_paths(tree)
        assert sorted(found) == sorted(p[k] for k in
                                       ("poro", "ntg", "facies", "poro_mr",
                                        "sw", "poro_b"))
        # The grids themselves are not properties.
        assert p["grid_a"] not in found

    def test_a_partial_stub_is_left_out(self, store):
        """A partial reference is not listed.

        A reference whose target is not in the file has no values behind
        it: offering it to tick would offer a load that cannot happen."""
        tree, p = store
        asm = tree._data_assembly
        asm.add_node_with_attrs(
            "_ghost", asm.GetFirstNodeByPath(p["grid_a"]),
            label="Properties_GHOST", title="!!!PARTIAL!!! GHOST",
            type="ContinuousProperty", typeCode="4")
        assert not [x for x in ct.assembly_property_paths(tree)
                    if x.endswith("_ghost")]

    def test_a_multi_realization_property_is_listed_once(self, store):
        """A multi-realization node is listed once, without its children.

        The widget draws an MR node as one leaf and never recurses into its
        per-realization children, which carry the same title. Listing them
        would offer the same property as many times as it has realizations,
        under paths no selection is ever made of."""
        tree, p = store
        asm = tree._data_assembly
        mr = asm.GetFirstNodeByPath(p["poro_mr"])
        for i in range(3):
            asm.add_node_with_attrs(
                f"_poro_mr_r{i}", mr, label=f"PORO_MR_{i}", title="PORO_MR",
                type="ContinuousProperty", typeCode="4",
                propertyKind="porosity")
        found = ct.assembly_property_paths(tree)
        assert p["poro_mr"] in found
        assert not [x for x in found if "_poro_mr_r" in x]

    def test_a_kind_the_session_cannot_track_is_not_offered(self, store):
        """A property kind the session does not track as an array is not listed.

        `ui_loaded_array_paths`, which says whether a property has been
        read, only ever holds the kinds tracked as an array. The generic
        "Property" is not one: a leaf for it would load and then be
        declared "not loaded" forever."""
        tree, p = store
        asm = tree._data_assembly
        asm.add_node_with_attrs(
            "_plain", asm.GetFirstNodeByPath(p["grid_a"]),
            label="Properties_PLAIN", title="PLAIN", type="Property",
            typeCode="4")
        assert not [x for x in ct.assembly_property_paths(tree)
                    if x.endswith("_plain")]

    def test_a_loaded_leaf_carries_no_sentence(self, store):
        """A loaded leaf carries no tooltip sentence.

        The tooltip says what is missing and what to do about it. On a tree
        listing a whole file, repeating "loaded" on every leaf would be tens
        of kilobytes of XML stating the normal case."""
        import xml.etree.ElementTree as ET
        tree, p = store
        xml, _ = ct.kind_tree_xml(tree, [p["poro"], p["sw"]],
                                  loaded={p["poro"]})
        leaves = {leaf.get("title"): leaf for k in ET.fromstring(xml)
                  for r in k for leaf in r}
        assert leaves["PORO"].get("info") is None
        assert leaves["SW"].get("info")

    def test_a_property_not_loaded_is_offered_and_says_so(self, store):
        """A property not loaded is listed and its leaf says so.

        It groups under its kind like any other, its synthetic path maps to
        it, and the leaf carries the state the widget renders."""
        import xml.etree.ElementTree as ET
        tree, p = store
        listed = [p["poro"], p["sw"]]
        xml, path_map = ct.kind_tree_xml(tree, listed, loaded={p["poro"]})
        root = ET.fromstring(xml)
        leaves = {leaf.get("title"): leaf for k in root for r in k
                  for leaf in r}
        assert set(leaves) == {"PORO", "SW"}
        assert leaves["PORO"].get("loadState") is None
        assert leaves["SW"].get("loadState") == cd.UNLOADED
        # The leaf says what a tick does and does not do: it reads into the
        # statistics, never into a 3D view, where the eye is the way in.
        info = leaves["SW"].get("info")
        assert "Ticking it here reads it into the statistics" in info
        assert "not into a 3D view" in info and "eye" in info
        # The kind still groups it, and the widget path rule is untouched.
        kinds = {k.get("title"): [leaf.get("title") for r in k for leaf in r]
                 for k in root}
        assert kinds == {"porosity": ["PORO"], "saturation": ["SW"]}
        assert path_map == {"/compare/k0/r0/p0": p["poro"],
                            "/compare/k1/r1/p1": p["sw"]}

    def test_a_property_being_read_says_that_instead(self, store):
        import xml.etree.ElementTree as ET
        tree, p = store
        xml, _ = ct.kind_tree_xml(tree, [p["sw"]], loaded=set(),
                                  pending={p["sw"]: cd.LOADING})
        leaf = ET.fromstring(xml)[0][0][0]
        assert leaf.get("loadState") == cd.LOADING
        xml, _ = ct.kind_tree_xml(tree, [p["sw"]], loaded=set(),
                                  pending={p["sw"]: cd.FAILED})
        leaf = ET.fromstring(xml)[0][0][0]
        assert leaf.get("loadState") == cd.FAILED
        assert "Data health" in leaf.get("info")

    def test_no_loaded_set_means_every_listed_path_is_loaded(self, store):
        import xml.etree.ElementTree as ET
        tree, p = store
        xml, _ = ct.kind_tree_xml(tree, [p["poro"], p["sw"]])
        assert all(leaf.get("loadState") is None
                   for k in ET.fromstring(xml) for r in k for leaf in r)


class TestTickPlan:
    """A tick in the docked tree: what joins the view, what is read.

    The plan says which items join the view and which properties the
    session is asked to read."""

    def test_ticking_a_property_not_loaded_loads_it(self, store):
        tree, p = store
        plan = ct.tick_plan([p["sw"]], [], loaded={p["poro"]})
        assert plan["to_load"] == [p["sw"]]
        assert plan["pending"] == {p["sw"]: cd.LOADING}
        assert plan["items"] == [{"path": p["sw"], "real": None, "ts": None}]

    def test_ticking_a_loaded_property_reads_nothing_again(self, store):
        tree, p = store
        plan = ct.tick_plan([p["poro"]], [], loaded={p["poro"]})
        assert plan["to_load"] == [] and plan["pending"] == {}

    def test_a_derived_recipe_is_never_loaded_through_the_tree(self, store):
        tree, p = store
        plan = ct.tick_plan([p["derived"]], [], loaded=set())
        assert plan["to_load"] == []
        assert plan["items"][0]["path"] == p["derived"]

    def test_unticking_drops_the_item_and_unloads_nothing(self, store):
        """Unticking removes the item from the view and unloads nothing.

        A 3D view may be showing that property: leaving the view is
        no reason to pull it out of the scene."""
        tree, p = store
        items = _items((p["poro"], None, None), (p["sw"], None, None))
        plan = ct.tick_plan([p["poro"]], items,
                            loaded={p["poro"], p["sw"]})
        assert [it["path"] for it in plan["items"]] == [p["poro"]]
        assert plan["to_load"] == [] and plan["pending"] == {}

    def test_a_property_already_waiting_is_not_asked_for_twice(self, store):
        tree, p = store
        plan = ct.tick_plan([p["sw"], p["ntg"]],
                            _items((p["sw"], None, None)), loaded=set(),
                            pending={p["sw"]: cd.LOADING})
        assert plan["to_load"] == [p["ntg"]]
        assert plan["pending"] == {p["sw"]: cd.LOADING,
                                   p["ntg"]: cd.LOADING}

    def test_the_existing_items_keep_their_order_and_coordinates(self, store):
        tree, p = store
        items = _items((p["poro"], 2, None), (p["sw"], None, None))
        plan = ct.tick_plan([p["sw"], p["poro"], p["ntg"]], items,
                            loaded={p["poro"], p["sw"], p["ntg"]})
        assert plan["items"] == items + [{"path": p["ntg"], "real": None,
                                          "ts": None}]

    def test_a_tick_over_the_cap_asks_before_reading_anything(self, store):
        """A tick over the load cap asks first and reads nothing.

        A ticked folder stands for its whole subtree. Above the cap the tick
        reads nothing and joins nothing yet: it comes back as a question the
        caller puts on screen, because a click on a collapsed folder must
        never start a read whose size the user cannot see."""
        tree, p = store
        ticked = [p["sw"], p["ntg"], p["facies"]]
        plan = ct.tick_plan(ticked, [], loaded=set(), max_load=2)
        assert plan["to_load"] == [] and plan["pending"] == {}
        assert plan["confirm"] == ticked
        assert plan["items"] == []

    def test_the_same_tick_uncapped_reads_the_whole_cascade(self, store):
        """Confirming replays the same tick with no cap.

        What the question announced is exactly what the confirmation does."""
        tree, p = store
        ticked = [p["sw"], p["ntg"], p["facies"]]
        asked = ct.tick_plan(ticked, [], loaded=set(), max_load=2)
        plan = ct.tick_plan(ticked, [], loaded=set())
        assert plan["confirm"] == []
        assert plan["to_load"] == asked["confirm"]
        assert [it["path"] for it in plan["items"]] == ticked

    def test_the_cap_counts_what_must_be_READ_only(self, store):
        """The cap counts only the properties that must be read.

        Ticking a whole folder of properties already loaded reads nothing,
        so it never has to ask."""
        tree, p = store
        plan = ct.tick_plan([p["sw"], p["ntg"], p["facies"]], [],
                            loaded={p["ntg"], p["facies"]}, max_load=1)
        assert plan["to_load"] == [p["sw"]] and plan["confirm"] == []
        assert [it["path"] for it in plan["items"]] == [p["sw"], p["ntg"],
                                                        p["facies"]]

    def test_a_tick_waiting_for_an_answer_leaves_the_selection_as_it_was(
            self, store):
        """A tick awaiting confirmation leaves the selection unchanged.

        Nothing joins, nothing is dropped and nothing waits while the
        question stands: stepping back has to be a no-op."""
        tree, p = store
        items = _items((p["poro"], None, None))
        plan = ct.tick_plan([p["poro"], p["sw"], p["ntg"]], items,
                            loaded={p["poro"]},
                            pending={p["facies"]: cd.LOADING}, max_load=1)
        assert plan["items"] == items
        assert plan["pending"] == {p["facies"]: cd.LOADING}
        assert plan["confirm"] == [p["sw"], p["ntg"]]

    def test_what_arrives_stops_waiting_what_never_came_says_so(self, store):
        tree, p = store
        pending = {p["sw"]: cd.LOADING, p["ntg"]: cd.LOADING}
        left, failed = ct.settle_pending(pending, {p["sw"]})
        assert left == {p["ntg"]: cd.LOADING} and failed == []
        left, failed = ct.settle_pending(left, {p["sw"]}, finished=True)
        assert left == {p["ntg"]: cd.FAILED} and failed == [p["ntg"]]
        # A failure is reported once, not on every later load.
        left, failed = ct.settle_pending(left, {p["sw"]}, finished=True)
        assert left == {p["ntg"]: cd.FAILED} and failed == []


class TestWaitingItems:
    """An item whose values are not there yet is not read.

    Such an item never looks like one that has figures."""

    def test_the_row_says_it_is_loading_and_reads_nothing(self, store,
                                                          monkeypatch):
        tree, p = store
        monkeypatch.setattr(cd, "_values_for", _boom)
        rows = cd.rows_for(None, tree, None,
                           _items((p["sw"], None, None)),
                           pending={p["sw"]: cd.LOADING})
        row = next(iter(rows.values()))
        assert row["load"] == cd.LOADING and row["metrics"] == {}
        assert row["label"].endswith("· loading")
        assert "figures appear" in row["note"]

    def test_a_property_that_never_came_says_what_to_do(self, store,
                                                        monkeypatch):
        tree, p = store
        monkeypatch.setattr(cd, "_values_for", _boom)
        rows = cd.rows_for(None, tree, None,
                           _items((p["sw"], None, None)),
                           pending={p["sw"]: cd.FAILED})
        row = next(iter(rows.values()))
        assert row["label"].endswith("· read failed")
        assert "Data health" in row["note"]

    def test_the_chip_carries_the_state(self, store):
        tree, p = store
        chips = cd.resolve_items(None, tree,
                                 _items((p["poro"], None, None),
                                        (p["sw"], None, None)), "",
                                 pending={p["sw"]: cd.LOADING})
        assert chips[0]["load"] == "" and "·" not in chips[0]["title"]
        assert chips[1]["load"] == cd.LOADING
        assert chips[1]["title"].endswith("· loading")

    def test_the_other_two_tabs_leave_it_out_with_its_reason(self, store,
                                                             values):
        tree, p = store
        items = _items((p["poro"], None, None), (p["sw"], None, None))
        fig, meta = cd.dist_figure(None, tree, None, items, {},
                                   pending={p["sw"]: cd.LOADING})
        assert meta["traces"] == 1 and "loading" in meta["note"]
        seeds = cd.xplot_seeds(None, tree, items, "",
                               pending={p["sw"]: cd.LOADING})
        assert seeds["ys"] == [] and "loading" in seeds["skipped"][0]


class TestResolveItems:
    def test_a_chip_says_what_its_row_reads(self, store):
        tree, p = store
        items = _items((p["poro"], None, None), (p["sw"], None, None),
                       (p["ntg"], 2, None))
        chips = cd.resolve_items(None, tree, items, "")
        assert [c["title"] for c in chips] == ["PORO", "SW", "NTG"]
        assert [c["baseline"] for c in chips] == [False, False, False], "no baseline by default"
        assert chips[0]["rep"] == "A" and chips[1]["rep"] == "B"
        assert chips[0]["kind"] == "porosity" and chips[0]["uom"] == "m3/m3"
        assert chips[2]["real"] == 2 and chips[2]["ts"] is None
        assert chips[2]["key"] == cd.item_key(p["ntg"], 2, None)

    def test_the_baseline_is_the_item_named(self, store):
        tree, p = store
        items = _items((p["poro"], None, None), (p["sw"], None, None))
        chips = cd.resolve_items(None, tree, items, cd.item_key(p["sw"], None, None))
        assert [c["baseline"] for c in chips] == [False, True]
        # An unknown key names none.
        chips = cd.resolve_items(None, tree, items, "/data/gone||")
        assert [c["baseline"] for c in chips] == [False, False]

    def test_realization_choices_and_derived_chip(self, store):
        tree, p = store
        items = _items((p["poro_mr"], 1, None), (p["derived"], None, None))
        chips = cd.resolve_items(None, tree, items, "")
        assert [r["value"] for r in chips[0]["reals"]] == [0, 1, 2]
        assert chips[0]["ts_opts"] == []
        assert chips[1]["title"] == "ƒ PHIE" and chips[1]["kind"] == "no kind"
        assert chips[1]["rep"] == "A"

    def test_empty_selection(self, store):
        tree, _ = store
        assert cd.resolve_items(None, tree, [], "") == []


class TestMatrix:
    def test_one_block_per_kind_baseline_first(self, store, values):
        tree, p = store
        items = _items((p["sw"], None, None), (p["poro"], None, None),
                       (p["poro_b"], None, None), (p["ntg"], None, None))
        base = cd.item_key(p["poro_b"], None, None)
        blocks, rows, ann = cd.matrix(None, tree, None, items, base, "", True)
        assert [b["kind"] for b in blocks] == ["saturation", "porosity",
                                               "net to gross"]
        # The baseline leads its block, the rest keep the selection order.
        assert blocks[1]["keys"] == [base, cd.item_key(p["poro"], None, None)]
        assert all(rows[k]["metrics"]["Cardinality"] > 0 for k in rows)
        assert rows[cd.item_key(p["ntg"], None, None)]["metrics"]["NaN_count"] == 10
        assert rows[base]["label"] == "PORO_B" and rows[base]["rep"] == "B"
        assert set(rows[base]["metrics"]) <= set(compare_matrix._METRIC_KEYS)
        assert rows[base]["profile"] in ("symmetric", "skewed_right",
                                         "skewed_left", "heavy_tail", "")

    def test_annotation_mode_per_block(self, store, values):
        tree, p = store
        items = _items((p["poro"], None, None), (p["poro_b"], None, None),
                       (p["sw"], None, None), (p["ntg"], None, None))
        base = cd.item_key(p["poro"], None, None)
        blocks, rows, ann = cd.matrix(None, tree, None, items, base, "", True)
        # Baseline block: deltas against the baseline, the baseline "eq".
        assert ann[base]["Mean"] == "eq"
        assert ann[cd.item_key(p["poro_b"], None, None)]["Mean"] == "neg"
        # A block without the baseline: extrema, and a lone row has none.
        sw = cd.item_key(p["sw"], None, None)
        assert "Mean" not in ann.get(sw, {})
        # No baseline at all: the two ends of each metric.
        _blocks, _rows, ann = cd.matrix(None, tree, None, items, "", "", True)
        assert {ann[base]["Mean"], ann[cd.item_key(p["poro_b"], None, None)]["Mean"]} == {"min", "max"}
        # Every tag is a word the widget turns into a class.
        assert all(isinstance(t, str) for by in ann.values() for t in by.values())

    def test_deltas_to_the_baseline_are_written_for_its_kind(self, store, values):
        """Deltas to the baseline are written for the rows of its kind only.

        Under a cell the matrix writes the difference to the baseline, in
        the metric's unit and in percent of it: for the rows of the
        baseline's kind, never for the baseline itself nor for another
        kind, and with no percent against a baseline of 0."""
        tree, p = store
        items = _items((p["poro"], None, None), (p["poro_b"], None, None),
                       (p["sw"], None, None))
        base = cd.item_key(p["poro"], None, None)
        other = cd.item_key(p["poro_b"], None, None)
        _blocks, rows, _ = cd.matrix(None, tree, None, items, base, "", True)
        d = cd.deltas_from_rows(items, rows, base)
        assert base not in d, "the baseline is what the others are read against"
        assert cd.item_key(p["sw"], None, None) not in d, "another kind has no delta"
        mean = d[other]["Mean"]
        want = rows[other]["metrics"]["Mean"] - rows[base]["metrics"]["Mean"]
        assert mean["abs"] == pytest.approx(want)
        assert mean["rel"] == pytest.approx(want / rows[base]["metrics"]["Mean"] * 100.0)
        # The baseline's NaN count is 0: an absolute delta, no percent.
        assert d[other]["NaN_count"]["abs"] == rows[other]["metrics"]["NaN_count"]
        assert d[other]["NaN_count"]["rel"] is None
        # No baseline, no delta.
        assert cd.deltas_from_rows([], rows, base) == {}

    def test_sort_inside_a_block(self, store, values):
        tree, p = store
        items = _items((p["poro"], None, None), (p["poro_mr"], 0, None),
                       (p["poro_b"], None, None))
        base = cd.item_key(p["poro_mr"], 0, None)
        blocks, rows, _ = cd.matrix(None, tree, None, items, base,
                                    "Mean", True)
        keys = blocks[0]["keys"]
        assert keys[0] == base
        means = [rows[k]["metrics"]["Mean"] for k in keys[1:]]
        assert means == sorted(means)
        blocks, rows, _ = cd.matrix(None, tree, None, items, base,
                                    "Mean", False)
        means = [rows[k]["metrics"]["Mean"] for k in blocks[0]["keys"][1:]]
        assert means == sorted(means, reverse=True)

    def test_sort_by_the_total_count_and_by_the_representation(self):
        """The total count and the representation sort like the metrics.

        The total is the defined and the undefined counts added up, as the
        matrix writes it; the representation is what its column writes —
        where a following row is read, else its item's — in alphabetical
        order whatever its case. A row with nothing to sort on sinks, in
        either direction."""
        items = [{"path": f"/p{i}", "real": None, "ts": None, "uid": u}
                 for i, u in enumerate("abc")]
        rows = {
            "a": {"kind": "k", "rep": "geogrid",
                  "metrics": {"Cardinality": 5.0, "NaN_count": 5.0}},
            "b": {"kind": "k", "rep": "Alpha",
                  "metrics": {"Cardinality": 8.0, "NaN_count": 0.0}},
            "c": {"kind": "k", "rep": "Geogrid", "support_label": "Blocked wellbore · W1",
                  "metrics": {}},
        }

        def keys(sort_key, asc):
            return cd.blocks_from_rows(items, rows, "", sort_key, asc)[0][0]["keys"]
        assert keys("Total", True) == ["b", "a", "c"]
        assert keys("Total", False) == ["a", "b", "c"]
        assert keys("Representation", True) == ["b", "c", "a"]
        assert keys("Representation", False) == ["a", "c", "b"]
        assert {"Total", "Representation"} <= set(compare_matrix.SORT_KEYS)

    def test_real_and_time_in_the_label_and_the_key(self, store, values):
        tree, p = store
        items = _items((p["poro_mr"], 0, None), (p["poro_mr"], 2, 1))
        blocks, rows, _ = cd.matrix(None, tree, None, items, "", "", True)
        k0, k2 = cd.item_key(p["poro_mr"], 0, None), cd.item_key(p["poro_mr"], 2, 1)
        assert blocks[0]["keys"] == [k0, k2]
        assert rows[k0]["label"] == "PORO_MR · real 0"
        assert rows[k2]["label"] == "PORO_MR · real 2 · t1"
        assert rows[k2]["metrics"]["Mean"] > rows[k0]["metrics"]["Mean"]

    def test_unreadable_item_keeps_a_row_with_a_note(self, store, values,
                                                     monkeypatch):
        tree, p = store
        monkeypatch.setattr(cd, "_values_for", lambda *a, **k: None)
        items = _items((p["poro"], None, None), ("/data/_nope", None, None))
        blocks, rows, ann = cd.matrix(None, tree, None, items, "", "", True)
        for row in rows.values():
            assert row["metrics"] == {} and row["note"]
        assert ann == {}
        assert [b["kind"] for b in blocks] == ["porosity", "no kind"]

    def test_duplicate_item_is_one_row(self, store, values):
        tree, p = store
        items = _items((p["poro"], None, None), (p["poro"], None, None))
        blocks, rows, _ = cd.matrix(None, tree, None, items, "", "", True)
        assert len(blocks) == 1 and blocks[0]["kind"] == "porosity"
        assert blocks[0]["keys"] == [cd.item_key(p["poro"], None, None)]
        assert blocks[0]["uom"] == "m3/m3" and blocks[0]["uom_mixed"] is False
        assert blocks[0]["units"] == ["m3/m3"]
        assert len(rows) == 1

    def test_empty_selection(self, store, values):
        tree, _ = store
        assert cd.matrix(None, tree, None, [], "", "", True) == ([], {}, {})

    def test_one_row_per_entry_when_the_session_names_them(self, store,
                                                           values):
        """Entries named by a session uid are one row each.

        The session gives every entry a uid: a pinned copy still at its
        source's realization and time is a row of its own (the Statistics
        card's pinned row), read once with its source. Each row says what
        it reads and what its pickers offer."""
        tree, p = store
        reads = []
        real_values = cd._values_for

        def counting(*a, **k):
            reads.append(a[3])
            return real_values(*a, **k)
        cd._values_for = counting
        try:
            items = [{"path": p["poro_mr"], "real": 1, "ts": None, "uid": "i1"},
                     {"path": p["poro_mr"], "real": 1, "ts": None, "uid": "i2",
                      "pinned": True},
                     {"path": p["poro_mr"], "real": 2, "ts": None, "uid": "i3"}]
            blocks, rows, _ = cd.matrix(None, tree, None, items, "i2", "", True)
        finally:
            cd._values_for = real_values
        assert sorted(rows) == ["i1", "i2", "i3"]
        assert blocks[0]["keys"][0] == "i2", "the baseline is an entry, by uid"
        assert set(blocks[0]["keys"]) == {"i1", "i2", "i3"}
        assert len(reads) == 2, "two distinct keys, two reads"
        assert rows["i1"]["metrics"] == rows["i2"]["metrics"]
        assert rows["i2"]["pinned"] and not rows["i1"]["pinned"]
        assert rows["i1"]["key"] == cd.item_key(p["poro_mr"], 1, None)
        assert rows["i1"]["title"] == "PORO_MR" and rows["i1"]["real"] == 1
        assert [o["value"] for o in rows["i1"]["reals"]] == [0, 1, 2]
        assert rows["i1"]["ts_opts"] == []

    def test_three_time_steps_of_one_property_are_three_rows(self, store,
                                                             values):
        """Three entries of one property at three time steps are three rows.

        Each entry is a row keyed by its uid, never merged by path; the
        deltas and the CSV name the entries the same way."""
        tree, p = store
        items = [{"path": p["poro_mr"], "real": 0, "ts": t, "uid": f"u{t}"}
                 for t in (0, 1, 2)]
        blocks, rows, ann = cd.matrix(None, tree, None, items, "u1", "", True)
        assert blocks[0]["keys"] == ["u1", "u0", "u2"]
        assert [rows[k]["ts"] for k in blocks[0]["keys"]] == [1, 0, 2]
        deltas = cd.deltas_from_rows(items, rows, "u1")
        assert set(deltas) == {"u0", "u2"}
        header = cd.csv_payload(items, rows, "u1", kind="porosity")["header"]
        assert sum(1 for line in header if line.startswith("# item:")) == 3

    def test_sorting_reuses_the_rows(self, store, values, monkeypatch):
        """Sorting re-reads no array.

        Ordering is pure: the panel calls blocks_from_rows over the rows it
        already holds."""
        tree, p = store
        items = _items((p["poro"], None, None), (p["poro_b"], None, None))
        rows = cd.rows_for(None, tree, None, items)
        monkeypatch.setattr(cd, "_values_for", _boom)
        base = cd.item_key(p["poro_b"], None, None)
        blocks, ann = cd.blocks_from_rows(items, rows, base, "Mean", True)
        assert blocks[0]["keys"][0] == base
        assert ann[base]["Mean"] == "eq"
        blocks, _ = cd.blocks_from_rows(items, rows, "", "Mean", False)
        means = [rows[k]["metrics"]["Mean"] for k in blocks[0]["keys"][1:]]
        assert means == sorted(means, reverse=True)

    def test_the_row_cache_reads_a_row_once(self, store, values, monkeypatch):
        """The session row cache reads a row once while its values hold.

        Without it, every pinned time step would be re-read at every tick.
        A row read once is served again while its values cannot have
        changed, and read again when the component or the weights behind it
        change, or when the property leaves the session."""
        tree, p = store
        items = _items((p["poro"], None, None), (p["poro_mr"], 1, None))
        cache = {}
        loaded = {p["poro"], p["poro_mr"]}
        rows = cd.rows_for(None, tree, None, items, cache=cache, loaded=loaded)
        assert cache["_reads"] == 2 and cache["_hits"] == 0
        # A derived recipe is never cached: it is read at every call.
        derived = _items((p["derived"], None, None))
        for _ in range(2):
            cd.rows_for(None, tree, None, derived, cache=cache, loaded={p["derived"]})
            assert cache["_reads"] == 1 and cache["_hits"] == 0
        assert cd.item_key(p["derived"], None, None) not in cache
        monkeypatch.setattr(cd, "_values_for", _boom)
        again = cd.rows_for(None, tree, None, items, cache=cache, loaded=loaded)
        assert cache["_hits"] == 2 and cache["_reads"] == 0
        for k in rows:
            assert again[k]["metrics"] == rows[k]["metrics"]
        # The property left the session: its row is read again (and says
        # it could not be).
        out = cd.rows_for(None, tree, None, items[:1], cache=cache, loaded=set())
        assert cache["_hits"] == 0 and cache["_reads"] == 1
        assert not out[cd.item_id(cd._norm_item(items[0]))]["metrics"]
        # Another component of the property: another key, read again.
        class _S:
            ui_vector_component = {p["poro"]: 1}
        out = cd.rows_for(_S(), tree, None, items[:1], cache=cache, loaded=loaded)
        assert cache["_reads"] == 1 and cache["_hits"] == 0
        assert "the values were read again" in out[cd.item_id(cd._norm_item(items[0]))]["note"]
        cd.clear_reads()
        assert not cd.READS

    def test_the_reads_at_other_time_steps_share_one_batch(self, store, values,
                                                            monkeypatch):
        """Reads at other time steps share one time batch.

        The rows are grouped by time step inside that batch: the session's
        time first, then the others."""
        from fespp_on_trame.engine import property_values as pv
        tree, p = store
        seen = []
        real_batch = pv.time_batch

        class _Probe:
            def __enter__(self):
                seen.append("enter")
            def __exit__(self, *a):
                seen.append("exit")
        monkeypatch.setattr(pv, "time_batch", lambda: _Probe())
        order = []
        real_values = cd._values_for

        def spy(state, tree_, sr, path, rep, real_idx=None, ts_idx=None):
            order.append(ts_idx)
            return real_values(state, tree_, sr, path, rep, real_idx=real_idx, ts_idx=ts_idx)
        monkeypatch.setattr(cd, "_values_for", spy)
        items = _items((p["poro"], None, 2), (p["poro_b"], None, None),
                       (p["ntg"], None, 1), (p["sw"], None, 2))
        cd.rows_for(None, tree, None, items)
        assert seen == ["enter", "exit"]
        assert order == [None, 1, 2, 2]
        assert real_batch is not None

    def test_a_row_the_state_no_longer_holds_is_skipped(self, store, values):
        tree, p = store
        items = _items((p["poro"], None, None), (p["sw"], None, None))
        rows = cd.rows_for(None, tree, None, items)
        rows.pop(cd.item_key(p["sw"], None, None))
        blocks, _ = cd.blocks_from_rows(items, rows, "", "", True)
        assert [b["kind"] for b in blocks] == ["porosity"]


class TestXplotSeeds:
    def test_baseline_is_x_and_other_reps_are_skipped(self, store):
        tree, p = store
        items = _items((p["sw"], None, None), (p["poro"], 3, None),
                       (p["ntg"], None, None), (p["poro_b"], None, None))
        seeds = cd.xplot_seeds(None, tree, items, cd.item_key(p["poro"], 3, None))
        assert (seeds["x"], seeds["xreal"], seeds["xts"]) == (p["poro"], 3, None)
        assert seeds["ys"] == [{"path": p["ntg"], "real": None, "ts": None}]
        assert seeds["skipped"] == ["SW: not on A", "PORO_B: not on A"]

    def test_first_item_when_no_baseline_and_the_diagonal(self, store):
        tree, p = store
        items = _items((p["poro_mr"], 1, None), (p["poro_mr"], 1, None),
                       (p["poro_mr"], 2, None), (p["derived"], None, None))
        seeds = cd.xplot_seeds(None, tree, items, "")
        assert seeds["x"] == p["poro_mr"] and seeds["xreal"] == 1
        assert seeds["ys"] == [{"path": p["poro_mr"], "real": 2, "ts": None},
                               {"path": p["derived"], "real": None, "ts": None}]
        assert seeds["skipped"] == ["PORO_MR · real 1: same as X (the diagonal)"]

    def test_empty_selection(self, store):
        tree, _ = store
        assert cd.xplot_seeds(None, tree, [], "") == {
            "x": None, "xreal": None, "xts": None, "ys": [], "skipped": []}

    def test_an_item_not_flagged_is_not_a_chart(self, store, values):
        """An item not flagged `xplot` is not charted.

        Nor is it a skipped item (there is nothing to explain); an entry that
        does not say is in. X is the item the key names whatever its own flag:
        it is the abscissa, not a chart."""
        tree, p = store
        items = _items((p["poro"], None, None), (p["ntg"], None, None),
                       (p["sw"], None, None))
        items[1]["xplot"] = False
        seeds = cd.xplot_seeds(None, tree, items, "")
        assert seeds["x"] == p["poro"] and seeds["ys"] == []
        assert seeds["skipped"] == ["SW: not on A"]
        # The flag on X itself has no say: X stays the item the key names.
        items[0]["xplot"], items[1]["xplot"] = False, True
        seeds = cd.xplot_seeds(None, tree, items, cd.item_key(p["poro"], None, None))
        assert seeds["x"] == p["poro"]
        assert seeds["ys"] == [{"path": p["ntg"], "real": None, "ts": None}]
        # the flag is the seeds', a published row carries none
        assert "xplot" not in cd.rows_for(None, tree, None, items)[cd.item_id(items[0])]

    def test_the_baseline_at_a_date_crosses_its_own_other_dates(self, store, values):
        """A baseline at one date is crossed with the other rows, not itself.

        With a property at a date as the baseline, the rows at other coordinates
        are charted against it (what moved), while a row at the very same
        coordinates is the diagonal, never a chart of the property against
        itself."""
        tree, p = store
        items = [{"path": p["poro_mr"], "real": 0, "ts": 0, "uid": "g0"},
                 {"path": p["poro_mr"], "real": 0, "ts": 1, "uid": "g1"},
                 {"path": p["poro"], "real": None, "ts": 2, "uid": "f2"},
                 {"path": p["poro"], "real": None, "ts": 2, "uid": "f2b"}]
        seeds = cd.xplot_seeds(None, tree, items, "f2")
        assert (seeds["x"], seeds["xts"]) == (p["poro"], 2)
        assert [y["ts"] for y in seeds["ys"]] == [0, 1]
        assert seeds["skipped"] == ["PORO · t2: same as X (the diagonal)"]


class TestDistFigure:
    def test_one_trace_per_item_of_the_kind(self, store, values):
        pytest.importorskip("plotly")
        tree, p = store
        items = _items((p["poro"], None, None), (p["poro_b"], None, None),
                       (p["poro_mr"], 2, None))
        fig, meta = cd.dist_figure(None, tree, None, items,
                                   {"mode": "bars", "nbins": 10})
        js = fig.to_plotly_json()
        assert len(js["data"]) == 3 and meta["traces"] == 3
        assert [t["name"] for t in js["data"]] == ["PORO", "PORO_B",
                                                   "PORO_MR · real 2"]
        assert all(t["type"] == "bar" and t["opacity"] == 0.55
                   for t in js["data"])
        assert js["layout"]["barmode"] == "overlay"
        assert js["layout"]["xaxis"]["title"]["text"] == "porosity (m3/m3)"
        assert js["layout"]["yaxis"]["title"]["text"] == "Count"
        assert meta == {"kept": 120, "total": 120, "note": "", "traces": 3}

    def test_options_reach_the_layout_and_the_discrete_path(self, store, values):
        pytest.importorskip("plotly")
        tree, p = store
        fig, meta = cd.dist_figure(
            None, tree, None, _items((p["facies"], None, None)),
            {"mode": "line", "log_y": True, "cumulative": True,
             "norm": "probability"})
        js = fig.to_plotly_json()
        trace = js["data"][0]
        # Per-category bins: three facies, cumulative probability ends at 1.
        assert trace["type"] == "scatter" and trace["x"] == [0.0, 1.0, 2.0]
        assert trace["y"][-1] == pytest.approx(1.0)
        assert js["layout"]["yaxis"]["type"] == "log"
        assert js["layout"]["yaxis"]["title"]["text"] == "Cumulative probability"
        assert js["layout"]["xaxis"]["title"]["text"] == "facies"
        # no names in the file: the codes stand, no forced ticks
        assert "tickvals" not in js["layout"]["xaxis"]

    def test_named_categories_name_the_axis(self, store, values, monkeypatch):
        pytest.importorskip("plotly")
        from fespp_on_trame.engine.utils import categories
        tree, p = store
        monkeypatch.setattr(categories, "labels_for",
                            lambda tree, path, vtk=None, reader=None:
                            {0: "sand", 2: "coal"} if path == p["facies"] else {})
        fig, _ = cd.dist_figure(None, tree, None, _items((p["facies"], None, None)),
                                {"mode": "bars"})
        x = fig.to_plotly_json()["layout"]["xaxis"]
        assert x["tickmode"] == "array" and x["tickvals"] == [0.0, 1.0, 2.0]
        # a code the file leaves unnamed keeps its code
        assert x["ticktext"] == ["sand", "1", "coal"]
        # a continuous item beside it: the axis is numeric again
        fig, _ = cd.dist_figure(None, tree, None,
                                _items((p["facies"], None, None), (p["poro"], None, None)),
                                {"mode": "bars", "nbins": 10})
        assert "tickvals" not in fig.to_plotly_json()["layout"]["xaxis"]

    def test_uirevision_holds_across_a_binning_change(self, store, values):
        pytest.importorskip("plotly")
        tree, p = store
        items = _items((p["poro"], None, None))
        a = cd.dist_figure(None, tree, None, items, {"nbins": 10})[0]
        b = cd.dist_figure(None, tree, None, items, {"nbins": 40})[0]
        c = cd.dist_figure(None, tree, None, items,
                           {"nbins": 40, "cumulative": True})[0]
        rev = lambda f: f.to_plotly_json()["layout"]["uirevision"]  # noqa: E731
        assert rev(a) and rev(a) == rev(b)     # same axes: the zoom stays
        assert rev(c) != rev(a)                # the heights mean something else
        # Another component of one item: its bars are other numbers.
        st = type("S", (), {"ui_vector_component": {p["poro"]: 1}})()
        d = cd.dist_figure(st, tree, None, items, {"nbins": 40})[0]
        assert rev(d) != rev(b)

    def test_meta_is_never_null(self, store, values, monkeypatch):
        tree, p = store
        fig, meta = cd.dist_figure(None, tree, None, [], {})
        assert fig is None and meta["traces"] == 0 and meta["note"]
        monkeypatch.setattr(cd, "_values_for", lambda *a, **k: None)
        fig, meta = cd.dist_figure(None, tree, None,
                                   _items((p["poro"], None, None)), None)
        assert fig is None
        assert meta["traces"] == 0 and meta["note"].startswith("not drawn: PORO")

    def test_unreadable_item_is_noted_beside_the_drawn_ones(self, store, values):
        pytest.importorskip("plotly")
        tree, p = store
        items = _items((p["poro"], None, None), ("/data/_nope", None, None))
        fig, meta = cd.dist_figure(None, tree, None, items, {"nbins": "12"})
        assert meta["traces"] == 1 and "not loaded" in meta["note"]
        assert len(fig.to_plotly_json()["data"][0]["x"]) == 12


class TestUnitsAndExport:
    def test_block_unit_and_row_provenance(self, store, values):
        tree, p = store
        items = _items((p["poro"], None, None), (p["poro_b"], None, None),
                       (p["poro_mr"], 2, 1))
        blocks, rows, _ = cd.matrix(None, tree, None, items, "", "", True)
        # PORO declares m3/m3, the two others nothing: the block does not
        # pretend they agree, and the rows without a unit are named.
        assert blocks[0]["uom"] == "" and blocks[0]["uom_mixed"] is True
        assert blocks[0]["units"] == ["m3/m3", "none declared"]
        # None declared anywhere: nothing to mix.
        items = _items((p["poro_b"], None, None), (p["poro_mr"], 2, 1))
        blocks, _r, _ = cd.matrix(None, tree, None, items, "", "", True)
        assert blocks[0]["uom"] == "" and blocks[0]["uom_mixed"] is False
        assert blocks[0]["units"] == []
        blocks, rows, _ = cd.matrix(None, tree, None, _items(
            (p["poro"], None, None), (p["poro_b"], None, None), (p["poro_mr"], 2, 1)),
            "", "", True)
        k = cd.item_key(p["poro_mr"], 2, 1)
        assert rows[k]["real"] == 2 and rows[k]["ts"] == 1
        assert rows[cd.item_key(p["poro"], None, None)]["real"] is None

    def test_mixed_units_in_a_block_are_said(self, store, values, monkeypatch):
        tree, p = store
        units = {p["poro"]: "m3/m3", p["poro_b"]: "%"}
        monkeypatch.setattr(cd._sd(), "_unit_for_array_path",
                            lambda tree, path: units.get(path, ""))
        items = _items((p["poro"], None, None), (p["poro_b"], None, None))
        blocks, _rows, _ = cd.matrix(None, tree, None, items, "", "", True)
        assert blocks[0]["uom"] == "" and blocks[0]["uom_mixed"] is True
        assert blocks[0]["units"] == ["%", "m3/m3"]

    def test_csv_payload_names_the_baseline_and_every_item(self, store, values):
        import re
        tree, p = store
        items = _items((p["poro"], None, None), (p["poro_mr"], 2, 1))
        base = cd.item_key(p["poro_mr"], 2, 1)
        _blocks, rows, _ = cd.matrix(None, tree, None, items, base, "", True)
        pl = cd.csv_payload(items, rows, base, kind="porosity")
        assert re.fullmatch(r"statistics_\d{4}-\d{2}-\d{2}\.csv", pl["name"])
        h = pl["header"]
        # The export is one kind's matrix: the header names the kind first.
        assert h.index("# kind: porosity") < h.index("# baseline: PORO_MR · real 2 · t1")
        assert "# items: 2" in h
        assert not any(line.startswith("# blocks") for line in h)
        assert "# kind:" not in "\n".join(cd.csv_payload(items, rows, base)["header"])
        # Each item line names where it was read, then any note. Here the
        # fake grid has no readable cells, so the row says why it carries no
        # volume-weighted mean rather than leaving the column silently empty.
        assert any(line.startswith("# item: PORO (A)") for line in h)
        assert any(line.startswith("# item: PORO_MR · real 2 · t1"
                                   " (A, real 2, time step 1)") for line in h)
        assert any("for a weighted mean" in line for line in h)
        assert cd.csv_payload([], {}, "") == {"name": "", "header": []}

    def test_dist_figure_of_differences_is_diverging(self, store, values, monkeypatch):
        np = pytest.importorskip("numpy")
        pytest.importorskip("plotly")
        from fespp_on_trame.engine.utils.color_palette import DIVERGING_NEG, DIVERGING_POS
        tree, p = store
        values["derived"][:] = np.linspace(-0.2, 0.3, len(values["derived"]))
        monkeypatch.setattr(derived_props, "is_difference",
                            lambda path: derived_props.is_derived(path))
        items = _items((p["derived"], None, None))
        fig, _ = cd.dist_figure(None, tree, None, items, {"mode": "bars", "nbins": 10})
        js = fig.to_plotly_json()
        assert js["layout"]["xaxis"]["range"] == [-0.3, 0.3]
        assert any(s["x0"] == 0 for s in js["layout"]["shapes"])
        colors = js["data"][0]["marker"]["color"]
        assert colors[0] == DIVERGING_NEG and colors[-1] == DIVERGING_POS
        # With a native property beside it: neither the range nor the line.
        items = _items((p["derived"], None, None), (p["poro"], None, None))
        fig, _ = cd.dist_figure(None, tree, None, items, {"mode": "bars", "nbins": 10})
        js = fig.to_plotly_json()
        assert "range" not in js["layout"]["xaxis"] and not js["layout"].get("shapes")
