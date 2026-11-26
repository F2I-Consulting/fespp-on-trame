"""The one question a tick asks before reading a lot at once.

One threshold, one wording, whichever tree raised it: a box that appears in
the Statistics view at eight properties and never in the data tree is a
surprise, not a habit.
"""
from fespp_on_trame.engine import compare_dispatch, tick_confirm


class TestTheThreshold:
    def test_the_number_the_product_owner_set(self):
        assert tick_confirm.MAX_TICK_LOAD == 20

    def test_it_is_written_once(self):
        # every tree reads THIS module; no other module keeps its own copy
        assert not hasattr(compare_dispatch, "MAX_TICK_LOAD")


class TestTheWords:
    def test_the_question_says_how_many_and_what_it_costs(self):
        q = tick_confirm.question(23)
        assert q["title"] == "Read 23 properties?"
        assert q["ok"] == "Read 23 properties"
        assert "3D views" in q["body"]
        assert "Nothing has been read yet." in q["body"]

    def test_a_panel_tree_says_the_read_stays_in_the_panel(self):
        # same number, same buttons; the one thing that differs is where
        # the read lands, and the box must not promise the 3D view
        q = tick_confirm.question(23, shown=False)
        assert q["title"] == "Read 23 properties?"
        assert q["ok"] == "Read 23 properties"
        assert "in this panel, not in the 3D views" in q["body"]
        assert "open an eye in a 3D view's data tree" in q["body"]
        assert "Nothing has been read yet." in q["body"]

    def test_one_property_reads_in_the_singular(self):
        q = tick_confirm.question(1)
        assert q["title"] == "Read 1 property?"
        assert q["ok"] == "Read 1 property"

    def test_a_big_count_is_grouped_like_every_other_number(self):
        # the one number rule: a thin space between the thousands
        assert tick_confirm.question(1234)["title"] == "Read 1\u2009234 properties?"

    def test_a_server_read_counts_objects_and_says_it_can_be_stopped(self):
        # over ETP every object is a download (surfaces and wells as well
        # as properties, as in a "select all" of surfaces): the count is of
        # objects, and the box says how the read can be stopped
        q = tick_confirm.question(240, remote=True)
        assert q["title"] == "Download 240 objects from the server?"
        assert q["ok"] == "Download 240 objects"
        assert "Stop" in q["body"]
        assert "Nothing has been read yet." in q["body"]


def test_a_frame_says_its_nodes():
    xml = ('<resqml2:WellboreFrameRepresentation><eml:Title>Well Log Frame</eml:Title>'
           '<resqml2:NodeCount>15556</resqml2:NodeCount></resqml2:WellboreFrameRepresentation>')
    assert tick_confirm.node_count(xml) == 15556
    assert tick_confirm.node_count("<NodeCount> 12 </NodeCount>") == 12
    # as fesapi serializes it (the frame of 55/33-A-4 in drogon)
    assert tick_confirm.node_count('<resqml20:NodeCount xmlns:xsd="http://www.w3.org/2001/XMLSchema"'
                                   ' xsi:type="xsd:positiveInteger">15556</resqml20:NodeCount>') == 15556
    assert tick_confirm.node_count("<resqml20:NodeCountry>3</resqml20:NodeCountry>") == 0
    assert tick_confirm.node_count("") == 0 and tick_confirm.node_count(None) == 0


def test_logs_ask_by_their_values_not_their_number():
    big, small = 15556, 4865
    # the PO, 23/11: one log of the frame read, its 20 others asked nothing — the same wait
    assert tick_confirm.asks(0, 20 * big)
    assert tick_confirm.asks(0, 21 * big)
    assert not tick_confirm.asks(0, big)                # one log of it: under a second
    assert not tick_confirm.asks(0, 25 * small)         # every log of a short frame
    # the properties that are no log keep their count
    assert tick_confirm.asks(tick_confirm.MAX_TICK_LOAD + 1, 0)
    assert not tick_confirm.asks(tick_confirm.MAX_TICK_LOAD, 0)


def test_the_question_says_the_values_of_the_logs():
    q = tick_confirm.question(20, shown=False, values=311120)
    assert q["title"] == "Read 20 properties?"
    assert "311" in q["body"] and "values" in q["body"]
    assert "values" not in tick_confirm.question(20, shown=False)["body"]


def test_a_grid_says_its_cells_as_fesapi_writes_them():
    xml = ('<resqml20:Ni xmlns:xsd="http://www.w3.org/2001/XMLSchema" xsi:type="xsd:positiveInteger">100</resqml20:Ni>'
           '<resqml20:Nj>200</resqml20:Nj><resqml20:Nk xsi:type="xsd:positiveInteger"> 300 </resqml20:Nk>')
    assert tick_confirm.ijk_cells(xml) == 6_000_000
    assert tick_confirm.ijk_cells("<Ni>4</Ni><Nj>5</Nj>") == 0       # no Nk: not said
    assert tick_confirm.ijk_cells("") == 0
