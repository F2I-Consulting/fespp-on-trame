"""Tests for engine.legends: one colour bar per 3D view, and a legend for
every other colour table.

The cases are the ones met in use: a whole wellbore colouring 33 tables at
once, a tab switch or a click on a log in 3D that leaves the card with no
node to follow, a table that stops painting, the bar switched off."""
import math

from fespp_on_trame.engine import legends


def test_the_card_s_table_holds_the_bar_when_it_paints():
    assert legends.choose_focus(["a", "b", "c"], "c", "a", ["a", "b", "c"]) == "c"


def test_the_bar_stays_where_it_was_when_the_card_names_nothing():
    # a tab switch, a frame activated by a pick: the bar must not jump
    assert legends.choose_focus(["a", "b"], None, "b", ["a", "b"]) == "b"


def test_a_card_table_that_paints_nothing_leaves_the_bar_where_it_was():
    # the active property's eye is closed: the card edits it, the view keeps
    # a bar for what it shows
    assert legends.choose_focus(["a", "b"], "z", "a", ["a", "b"]) == "a"


def test_the_bar_goes_to_a_table_that_has_just_started_painting():
    # the table the bar was on is gone; of the survivors, the new one
    assert legends.choose_focus(["a", "b", "c"], None, "x", ["a", "x"]) == "b"


def test_a_whole_wellbore_on_an_empty_view_gives_the_bar_to_its_first_table():
    keys = [f"log{i:02d}" for i in range(33)]
    assert legends.choose_focus(keys, None, None, []) == "log00"


def test_a_wellbore_added_under_a_coloured_grid_keeps_the_grid_s_bar():
    keys = ["grid"] + [f"log{i:02d}" for i in range(33)]
    assert legends.choose_focus(keys, None, "grid", ["grid"]) == "grid"


def test_nothing_painting_means_no_bar():
    assert legends.choose_focus([], "a", "a", ["a"]) is None


def test_the_first_table_when_nothing_is_new_and_the_old_one_left():
    assert legends.choose_focus(["b", "c"], None, "a", ["a", "b", "c"]) == "b"


def test_linear_samples_span_the_range():
    xs = legends.sample_positions(0.0, 30.0, 4)
    assert xs == [0.0, 10.0, 20.0, 30.0]


def test_log_samples_are_even_in_log_space():
    xs = legends.sample_positions(1.0, 1000.0, 4, log=True)
    assert [round(math.log10(x), 9) for x in xs] == [0.0, 1.0, 2.0, 3.0]


def test_a_log_scale_on_a_range_touching_zero_samples_linearly():
    assert legends.sample_positions(0.0, 1.0, 3, log=True) == [0.0, 0.5, 1.0]


def _describe(t):
    return {"lo": "0", "hi": "1", "stops": ["#000000", "#ffffff"]}


def test_rows_are_sorted_by_title_and_the_bar_is_marked():
    tables = [{"key": "k2", "title": "RHOB (g/cm3)"},
              {"key": "k1", "title": "GR (gAPI)"},
              {"key": "k3", "title": "active_cell — constant 1"}]
    rows = legends.legend_rows(tables, "k2", set(), _describe)
    assert [r["title"] for r in rows] == [
        "active_cell — constant 1", "GR (gAPI)", "RHOB (g/cm3)"]
    assert [r["bar"] for r in rows] == [False, False, True]
    assert not any(r["bar_off"] for r in rows)
    assert rows[1]["stops"] == ["#000000", "#ffffff"]


def test_a_switched_off_bar_is_said_so_on_its_row():
    rows = legends.legend_rows([{"key": "k", "title": "SW"}], "k", {"k"}, _describe)
    assert rows[0]["bar"] is False and rows[0]["bar_off"] is True


def test_a_coded_table_carries_its_codes_not_a_ramp():
    codes = [{"code": 1, "label": "Sand", "color": "#ffcc00"}]
    rows = legends.legend_rows([{"key": "k", "title": "Facies"}], None, set(),
                               lambda t: {"codes": codes})
    assert rows[0]["codes"] == codes and rows[0]["stops"] == []
    assert rows[0]["bar"] is False


def test_grids_come_before_wells_and_a_shared_log_names_both_wells():
    where = {"k1": {"family": "well", "owners": ["15/9-19 A", "15/9-F-1 A"]},
             "k2": {"family": "grid", "owners": ["Geogrid"]},
             "k3": {"family": "surface", "owners": ["Top Hugin"]}}
    tables = [{"key": "k1", "title": "GR (gAPI)"}, {"key": "k3", "title": "Depth"},
              {"key": "k2", "title": "Porosity"}]
    rows = legends.legend_rows(tables, None, set(),
                               lambda t: {**_describe(t), **where[t["key"]]})
    assert [r["family"] for r in rows] == ["grid", "well", "surface"]
    assert rows[1]["owners"] == ["15/9-19 A", "15/9-F-1 A"]


def test_the_tree_s_tabs_name_the_sections():
    assert legends.family_of_tab("Reservoir") == "grid"
    assert legends.family_of_tab("Well") == "well"
    assert legends.family_of_tab("Surface") == "surface"
    assert legends.family_of_tab("Seismic") == "seismic"
    assert legends.family_of_tab("") == "other"
