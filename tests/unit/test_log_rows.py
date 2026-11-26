"""A well's log in the Values view and the 3D views (engine/node_facts,
engine/values_table): a log is a block of its own under its frame — never a
cell of it —; one not read is offered to be read, its frame read with other
logs holds none of its values; the page keeps "Hide NaN" when the server asks
for it again; the log view's cursor turns to the nearest row kept."""
import numpy as np

from tests.unit.fake_assembly import FakeDataAssembly
from fespp_on_trame.engine import node_facts as nf
from fespp_on_trame.engine import values_table
from fespp_on_trame.engine.tree import Tree


def _world():
    asm = FakeDataAssembly()
    well = asm.add_node_with_attrs("_well", 0, label="Wellbore_W", title="55/33-2", type="Wellbore")
    logs = asm.add_node_with_attrs("_logs", well, label="logs", title="logs", type="Folder")
    frame = asm.add_node_with_attrs("_frame", logs, label="Frame_F", title="Well Log Frame",
                                    type="Frame", typeCode="5")
    ai = asm.add_node_with_attrs("_ai", frame, label="Log_AI", title="Acoustic Impedance",
                                 type="ContinuousProperty", typeCode="4")
    edited = asm.add_node_with_attrs("_aie", frame, label="Log_AIE", title="Acoustic Impedance (Edited)",
                                     type="ContinuousProperty", typeCode="4")
    seis = asm.add_node_with_attrs("_sframe", logs, label="SFrame", title="Seismic frame",
                                   type="SeismicWellboreFrame", typeCode="5")
    twt = asm.add_node_with_attrs("_twt", seis, label="Log_TWT", title="TWT",
                                  type="ContinuousProperty", typeCode="4")
    traj = asm.add_node_with_attrs("_traj", well, label="Traj", title="Drilled trajectory",
                                   type="WellboreTrajectory", typeCode="3")
    tree = Tree(asm)
    p = {k: asm.GetNodePath(v) for k, v in (("well", well), ("frame", frame), ("ai", ai), ("edited", edited),
                                            ("seis", seis), ("twt", twt), ("traj", traj))}
    return tree, p


class TestALogIsABlockOfItsOwn:
    def test_a_frame_s_property_is_a_log(self):
        tree, p = _world()
        assert nf.rep_path_for(tree, p["ai"]) == p["frame"], "the frame is the log's representation"
        assert nf.is_log(tree, p["ai"]) and nf.is_log(tree, p["twt"])

    def test_the_frame_the_well_and_its_trajectory_are_no_log(self):
        tree, p = _world()
        for k in ("frame", "seis", "well", "traj"):
            assert not nf.is_log(tree, p[k]), k
        assert not nf.is_log(tree, "") and not nf.is_log(tree, "/data/nowhere")

    def test_a_log_not_read_is_offered_to_be_read(self):
        # one log of the frame read: its sibling is not, whatever the frame's block holds
        tree, p = _world()
        assert not nf.is_unread_log(tree, p["ai"], [p["ai"]])
        assert nf.is_unread_log(tree, p["edited"], [p["ai"]])
        assert nf.is_unread_log(tree, p["edited"], None)

    def test_a_grid_property_is_never_an_unread_log(self):
        tree, p = _world()
        assert not nf.is_unread_log(tree, p["frame"], [])
        assert not nf.is_unread_log(tree, p["traj"], [])


class TestTheValuesRequest:
    def test_hide_nan_is_on_unless_said(self):
        # the card's box starts ticked: a page the server asks for on its own (a read, a tick) hides them too
        assert values_table.query({"offset": 0})["hide_nan"] is True
        assert values_table.query({"offset": 0, "hide_nan": None})["hide_nan"] is True
        assert values_table.query(0)["hide_nan"] is True
        assert values_table.query({"hide_nan": False})["hide_nan"] is False
        assert values_table.query({"hide_nan": True})["hide_nan"] is True

    def test_a_bad_request_reads_from_the_first_page(self):
        q = values_table.query({"offset": "x", "hide_nan": False})
        assert q["offset"] == 0

    def test_the_cursor_and_the_filters_are_read(self):
        q = values_table.query({"offset": 400, "cursor_md": "1520.5", "only": 1,
                                "filters": [{"column": "MD", "min": "1000", "max": "", "op": "or"}]})
        assert q["offset"] == 400 and q["cursor_md"] == 1520.5 and q["only"] is True
        assert q["filters"] == [{"column": "MD", "min": 1000.0, "max": None, "op": "or"}]
        assert q["filter"] == "MD"


class TestTheCursorRow:
    MD = np.array([0.0, 15.0, 30.0, np.nan, 60.0, 75.0])

    def test_the_nearest_row_kept_and_its_page(self):
        kept = np.arange(6)
        assert values_table.nearest_row(self.MD, kept, 58.0, 200) == (4, 0)
        assert values_table.nearest_row(self.MD, kept, 58.0, 2) == (4, 4)

    def test_a_row_the_filter_leaves_out_is_never_the_cursor_s(self):
        kept = np.array([0, 1, 5])
        assert values_table.nearest_row(self.MD, kept, 58.0, 200) == (5, 0)

    def test_a_row_without_a_depth_is_never_the_cursor_s(self):
        assert values_table.nearest_row(self.MD, np.array([2, 3]), 46.0, 200) == (2, 0)

    def test_no_depth_no_cursor(self):
        assert values_table.nearest_row(self.MD, np.array([3]), 46.0, 200) == (None, None)
        assert values_table.nearest_row(self.MD, np.array([], dtype=np.int64), 46.0, 200) == (None, None)
