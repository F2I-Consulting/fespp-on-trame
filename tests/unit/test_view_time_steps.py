"""A view's time steps (engine/time_realization): FESPP publishes one list
of steps for the whole session, the union of every time series read; a view
steps through those at which what it colours by changes — a series of one
step among 21 makes no player of 21 steps that change nothing."""
from fespp_on_trame.engine import time_realization as tr

TS = "11111111-2222-3333-4444-555555555555"


class _Tree:
    """Nodes by path: {path: (type, {attribute: value}, parent path)}."""

    def __init__(self, nodes):
        self._paths = list(nodes)
        self._nodes = nodes

    def find_node_id(self, path):
        return self._paths.index(path) + 1 if path in self._nodes else None

    def _at(self, nid):
        return self._nodes[self._paths[nid - 1]]

    def find_type(self, nid):
        return self._at(nid)[0]

    def find_attribute_value(self, nid, name):
        return self._at(nid)[1].get(name)

    def find_parent_attribute_value(self, nid, name):
        while nid is not None:
            kind, attrs, parent = self._at(nid)
            if name in attrs:
                return attrs[name]
            nid = self.find_node_id(parent) if parent else None
        return None


def _tree():
    mrts = f"/data/_g/_{TS}multirealts_PORO"
    return _Tree({
        f"/data/_g/_{TS}TimeSeries_Pressure": ("TimeSeries", {"title": "Pressure"}, "/data/_g"),
        mrts: ("MultiRealizationTimeSeries", {"title": "PORO", "propTitle": "Porosity"}, "/data/_g"),
        f"{mrts}/_{TS}real_3_PORO": ("TimeSeries", {"realization_index": "3"}, mrts),
        "/data/_g/_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee": ("ContinuousProperty", {"title": "NTG"}, "/data/_g"),
        "/data/_g/_00000000-0000-0000-0000-000000000000TimeSeries_X": ("TimeSeries", {"title": "X"}, "/data/_g"),
    })


def test_a_time_series_is_its_timeseries_and_its_property_title():
    assert tr.series_of(_tree(), f"/data/_g/_{TS}TimeSeries_Pressure") == (TS, "Pressure", None)


def test_a_realization_of_a_multi_realization_series_names_its_parent_and_its_index():
    path = f"/data/_g/_{TS}multirealts_PORO/_{TS}real_3_PORO"
    assert tr.series_of(_tree(), path) == (TS, "Porosity", 3)
    # the multi-realization node itself: the realization the view shows
    assert tr.series_of(_tree(), f"/data/_g/_{TS}multirealts_PORO", 5) == (TS, "Porosity", 5)


def test_a_plain_property_or_a_series_without_timeseries_is_no_series():
    assert tr.series_of(_tree(), "/data/_g/_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee") is None
    assert tr.series_of(_tree(), "/data/_g/_00000000-0000-0000-0000-000000000000TimeSeries_X") is None
    assert tr.series_of(_tree(), "/data/_g/unknown") is None
    assert tr.series_of(_tree(), "") is None


def test_the_members_of_a_series_are_the_properties_of_its_title():
    related = [{"uuid": "a", "type": "resqml20.obj_ContinuousProperty", "title": "Pressure"},
               {"uuid": "b", "type": "resqml20.obj_ContinuousProperty", "title": "Transmissibility K (TRANZ)"},
               {"uuid": "c", "type": "resqml20.obj_IjkGridRepresentation", "title": "Pressure"},
               {"uuid": "d", "type": "resqml20.obj_DiscreteProperty", "title": "Pressure"}]
    assert [m["uuid"] for m in tr.series_members(related, "Pressure")] == ["a", "d"]
    assert tr.series_members(None, "Pressure") == []


def _v201(index, real=None):
    real_xml = f"<resqml20:RealizationIndex>{real}</resqml20:RealizationIndex>" if real is not None else ""
    # fesapi writes attributes on the typed elements it serializes
    return ('<resqml20:ContinuousProperty xmlns:resqml20="x">' + real_xml
            + '<resqml20:TimeIndex xsi:type="resqml20:TimeIndex">'
            + f'<resqml20:Index xmlns:xsd="http://www.w3.org/2001/XMLSchema">{index}</resqml20:Index>'
            + '<resqml20:TimeSeries/></resqml20:TimeIndex></resqml20:ContinuousProperty>')


def test_the_steps_of_a_series_are_the_time_indices_its_xml_declares():
    v22 = ('<resqml:ContinuousProperty><resqml:TimeIndices><resqml:TimeIndexCount>1'
           '</resqml:TimeIndexCount><resqml:TimeIndexStart>5</resqml:TimeIndexStart>'
           '</resqml:TimeIndices></resqml:ContinuousProperty>')
    assert tr.series_steps([_v201(7), v22, _v201(2), _v201(7), ""]) == [2, 5, 7]
    assert tr.series_steps([]) == []


def test_one_realization_keeps_its_own_steps():
    xmls = [_v201(1, real=3), _v201(4, real=3), _v201(9, real=5)]
    assert tr.series_steps(xmls, realization=3) == [1, 4]
    assert tr.series_steps(xmls) == [1, 4, 9]


def test_a_view_steps_through_the_steps_of_what_it_colours_by():
    values = [float(i) for i in range(21)]
    # a series of one step: one position, nothing to play
    assert tr.step_positions(values, [[12]]) == [12]
    # two series coloured: their steps joined
    assert tr.step_positions(values, [[0, 5, 10], [5, 7]]) == [0, 5, 7, 10]
    # a series whose steps are unknown: every step
    assert tr.step_positions(values, [[3], None]) == list(range(21))
    # no series coloured: no time step to go through
    assert tr.step_positions(values, []) == []
    # the session's steps need not start at 0 nor be whole positions
    assert tr.step_positions([2.0, 4.0, 9.0], [[4, 9]]) == [1, 2]


def test_another_series_coloured_keeps_the_step_or_goes_to_its_first():
    # the step shown exists for the new series: it stays
    assert tr.position_kept([0, 5, 7, 10], 7) == 7
    # it does not: back to the first step, not the nearest
    assert tr.position_kept([3, 5, 7, 10], 9) == 3
    assert tr.position_kept([12], 4) == 12
    # no step at all: nothing moves
    assert tr.position_kept([], 4) == 4


def test_a_play_goes_to_the_next_step_and_loops():
    assert tr.next_position([0, 5, 7, 10], 5) == 7
    assert tr.next_position([0, 5, 7, 10], 6) == 7
    assert tr.next_position([0, 5, 7, 10], 10) == 0
    assert tr.next_position([], 4) == 4
