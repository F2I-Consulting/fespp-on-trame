"""A property whose values cannot be read is unchecked, badged and announced.

FESPP reports it in two wordings — "Error when initialize uuid" when the
values cannot be opened (the .h5 is missing, or its element count does
not match the grid), "Error when rendering uuid" when a mapper cannot
materialise — each followed by fesapi's own explanation. Both must reach
the user: nothing is silent.
"""
from types import SimpleNamespace

import pytest

from trame.app import get_server
from fespp_on_trame.engine import vtk_log
from fespp_on_trame.engine.tree import Tree
from tests.unit.fake_assembly import FakeDataAssembly

UUID = "c2be50b6-08d2-461b-81a4-73dbb04ba605"
OTHER = "45221b2d-1e04-498f-a72a-180f9a23b84a"


@pytest.fixture
def world(monkeypatch):
    asm = FakeDataAssembly()
    grid = asm.add_node_with_attrs("_grid", 0, label="IjkGrid_G", title="Geogrid",
                                   type="IjkGrid")
    bad = asm.add_node_with_attrs("_" + UUID, grid, label="phi", title="PORO",
                                  type="ContinuousProperty")
    good = asm.add_node_with_attrs("_" + OTHER, grid, label="ntg", title="NTG",
                                   type="ContinuousProperty")
    tree = Tree(asm)
    monkeypatch.setattr(get_server().context, "tree", tree, raising=False)
    monkeypatch.setattr(vtk_log, "_session_temp_dir", lambda: "/tmp/tmpw4j0w3lu")
    bad_path, good_path = asm.GetNodePath(bad), asm.GetNodePath(good)
    state = SimpleNamespace(
        vtk_log_messages=[], ui_invalid_node_ids=[], ui_invalid_node_errors={},
        selected_paths=[bad_path, good_path], active_path=bad_path, load_error="",
    )
    return SimpleNamespace(tree=tree, state=state, bad=bad, bad_path=bad_path,
                           good_path=good_path)


def test_an_unreadable_property_is_unchecked_badged_and_announced(world):
    vtk_log._flag_invalid_nodes(world.state, [{
        "text": ("Error when initialize uuid: " + UUID + "\n"
                 "The HDF5 file /tmp/tmpw4j0w3lu/vector_props.h5 does not exist"),
    }])
    s = world.state
    assert s.selected_paths == [world.good_path], "the unreadable one is unchecked, the other stays"
    assert s.active_path == "", "the active node was the unreadable one: nothing is active"
    assert s.ui_invalid_node_ids == [world.bad]
    assert s.ui_invalid_node_errors == {
        str(world.bad): "The HDF5 file vector_props.h5 does not exist"}
    assert s.load_error == "The HDF5 file vector_props.h5 does not exist", (
        "fesapi's wording, without the server's temporary path")


def test_the_rendering_wording_is_read_too(world):
    vtk_log._flag_invalid_nodes(world.state, [{
        "text": ("Error when rendering uuid: " + UUID + "\n"
                 "The HDF5 dataset /RESQML/" + UUID + "/values could not be opened."),
    }])
    assert world.state.ui_invalid_node_ids == [world.bad]
    assert world.state.load_error == (
        "The HDF5 dataset /RESQML/" + UUID + "/values could not be opened.")


def test_a_message_about_an_unknown_uuid_changes_nothing(world):
    vtk_log._flag_invalid_nodes(world.state, [{
        "text": "Error when initialize uuid: 00000000-0000-0000-0000-000000000000\nwhatever",
    }])
    s = world.state
    assert s.selected_paths == [world.bad_path, world.good_path]
    assert s.ui_invalid_node_ids == [] and s.load_error == ""


def test_a_property_kind_warning_is_not_an_unreadable_node(world):
    vtk_log._flag_invalid_nodes(world.state, [{
        "text": ("property " + UUID + " cannot be associated to a resqml property"
                 " kind \"length\" which does not derive from ..."),
    }])
    assert world.state.ui_invalid_node_ids == []
    assert world.state.selected_paths == [world.bad_path, world.good_path]
