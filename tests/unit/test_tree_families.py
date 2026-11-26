"""engine/tree_families — the families a tree is cut into, the Seismic one
filed by the rows of the lattice grids."""
from fespp_on_trame.engine import tree_families as tf

XML = ('<root type="Root">'
       '<Geogrid type="GridContainer"><props type="PropertiesFolder">'
       '<geo type="IjkGrid"/><poro type="ContinuousProperty"/></props></Geogrid>'
       '<Velocity type="GridContainer"><props type="PropertiesFolder">'
       '<lat type="IjkGrid"/><vint type="ContinuousProperty"/></props></Velocity>'
       '<Top type="GridContainer"><props type="PropertiesFolder"><t type="Grid2d"/></props></Top>'
       '</root>')
LATTICE = ["/root/Velocity"]
ONLY_LATTICE = ('<root type="Root"><Velocity type="GridContainer"><props type="PropertiesFolder">'
                '<lat type="IjkGrid"/></props></Velocity></root>')


def test_the_seismic_card_comes_last_and_lists_no_type():
    assert tf.KEYS == ("tree", "tree_surface", "tree_well", "tree_seismic")
    assert tf.NAMES[-1] == "Seismic"
    assert tf.FAMILIES[-1] == ("tree_seismic", "Seismic", ())


def test_the_seismic_tab_takes_the_lattice_rows_the_reservoir_one_leaves_them():
    assert tf.tab_of("tree_seismic") == [{"name": "Seismic", "types": [], "lattice": "take"}]
    reservoir = tf.tab_of("tree")[0]
    assert reservoir["lattice"] == "leave" and "IjkGrid" in reservoir["types"]
    # the list reaches the browser as its repr: nothing JavaScript cannot read
    assert "True" not in repr(tf.tab_of("tree_seismic")) and "False" not in repr(tf.tab_of("tree"))
    assert "lattice" not in tf.tab_of("tree_surface")[0]
    assert "lattice" not in tf.tab_of("tree_well")[0]
    assert tf.tab_named("Seismic") == tf.tab_of("tree_seismic")


def test_without_lattice_rows_no_seismic_family():
    assert tf.present(XML) == {"tree", "tree_surface"}
    assert tf.present_names(XML) == ["Reservoir", "Surface"]


def test_the_lattice_rows_make_the_seismic_family():
    assert tf.present(XML, LATTICE) == {"tree", "tree_surface", "tree_seismic"}
    assert tf.present_names(XML, LATTICE) == ["Reservoir", "Surface", "Seismic"]


def test_a_lattice_grid_counts_for_no_other_family():
    assert tf.present(ONLY_LATTICE, LATTICE) == {"tree_seismic"}
    assert tf.first_present(ONLY_LATTICE, LATTICE) == "tree_seismic"
    assert tf.first_present(ONLY_LATTICE) == "tree"


def test_the_same_assembly_is_read_again_when_its_lattice_rows_change():
    assert tf.present(ONLY_LATTICE) == {"tree"}
    assert tf.present(ONLY_LATTICE, LATTICE) == {"tree_seismic"}
    assert tf.present(ONLY_LATTICE) == {"tree"}


def test_the_card_of_a_path():
    assert tf.key_of(XML, "/root/Geogrid/props/poro", LATTICE) == "tree"
    assert tf.key_of(XML, "/root/Velocity/props/vint", LATTICE) == "tree_seismic"
    assert tf.key_of(XML, "/root/Velocity", LATTICE) == "tree_seismic"
    assert tf.key_of(XML, "/root/Velocity/props/vint") == "tree"
    assert tf.key_of(XML, "/root/Top", LATTICE) == "tree_surface"


def test_a_panel_opens_only_the_families_it_knows():
    assert tf.open_cards(["Reservoir", "Seismic"], [], tf.LOG_GRID) == ["Reservoir"]
    assert tf.open_cards(True, ["Seismic"], tf.NAMES) == ["Seismic"]


class _Tree:
    """The few calls the family rule makes of the data tree."""

    def __init__(self, nodes, lattice=()):
        self.nodes = nodes                      # {nid: (type, path)}
        self.lattice_rows = frozenset(lattice)

    def find_node_id(self, path):
        return next((nid for nid, (_t, p) in self.nodes.items() if p == path), None)

    def find_path(self, nid):
        return self.nodes[nid][1]

    def family_type(self, nid):
        return self.nodes[nid][0]


_NODES = {1: ("IjkGrid", "/root/Geogrid"), 2: ("ContinuousProperty", "/root/Geogrid/props/poro"),
          3: ("IjkGrid", "/root/Velocity"), 4: ("ContinuousProperty", "/root/Velocity/props/vint"),
          5: ("Wellbore", "/root/W1"), 6: ("Frame", "/root/W1/logs/frame"),
          7: ("TextNote", "/root/note")}


def test_one_rule_names_the_family_of_a_node_a_lattice_row_is_seismic():
    tree = _Tree(_NODES, LATTICE)
    assert tf.name_of(tree, 1) == "Reservoir" and tf.name_of(tree, 3) == "Seismic"
    assert tf.name_of(tree, 5) == "Well" and tf.name_of(tree, 2) == ""
    # no lattice row known: the type alone files it
    assert tf.name_of(_Tree(_NODES), 3) == "Reservoir"


def test_the_family_of_a_path_is_that_of_the_first_node_filed_on_it():
    tree = _Tree(_NODES, LATTICE)
    assert tf.of_path(tree, "/root/Geogrid/props/poro") == ("Reservoir", 1)
    assert tf.of_path(tree, "/root/Velocity/props/vint") == ("Seismic", 3)
    assert tf.of_path(tree, "/root/W1/logs/frame") == ("Well", 5)
    assert tf.of_path(tree, "/root/note") == ("", None) and tf.of_path(tree, "") == ("", None)
