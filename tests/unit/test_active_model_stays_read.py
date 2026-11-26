"""The velocity model the conversions read stays ticked
(app/features/time_depth_tree, one of `ctx.untick_vetoes`): a tree's untick of
its grid or of its velocity is put back and says why; what else its row holds
is unticked freely. Here a grid of the data read as it is, the model the
session generated being in the browser suite (40-second-model-shown)."""
import types

from tests.unit.fake_assembly import FakeDataAssembly
from fespp_on_trame.app.features import time_depth_tree
from fespp_on_trame.engine.tree import Tree


class _Controller:
    def set(self, _name):
        return lambda fn: fn


class _State(dict):
    def __getattr__(self, key):
        return self.get(key)


def _session():
    asm = FakeDataAssembly()
    box = asm.add_node_with_attrs("_gridfolder_1", 0, title="Seismic velocities", label="Seismic velocities",
                                  type="GridContainer", typeCode="0")
    grid = asm.add_node_with_attrs("_grid1", box, title="geometry", label="IjkGrid_geometry",
                                   type="IjkGrid", typeCode="2")
    props = {t: asm.add_node_with_attrs(f"_prop_{t}", grid, title=t, label=f"Properties_{t}",
                                        type="ContinuousProperty", typeCode="4")
             for t in ("Velocity", "Amplitude")}
    other = asm.add_node_with_attrs("_horizon1", 0, title="Top", label="Grid2d_Top", type="Grid2d", typeCode="2")
    tree = Tree(None)
    tree.set_tree(asm)
    paths = {name: tree.find_path(nid) for name, nid in
             (("box", box), ("grid", grid), ("other", other), *props.items())}
    core = types.SimpleNamespace(controller=_Controller(), ctx=types.SimpleNamespace(), state=_State(),
                                 tree=tree, mv=lambda: None)
    time_depth_tree.register(core)
    core.ctx.time_depth_cube_key = lambda: "tdl:1"
    core.ctx.time_depth_converting_id = lambda: 1
    core.ctx.time_depth_data_grid = lambda: paths["grid"]
    core.ctx.time_depth_data_velocity = lambda: paths["Velocity"]
    return core, paths


def test_the_grid_and_the_velocity_of_the_active_model_are_put_back_and_said():
    core, p = _session()
    veto = core.ctx.untick_vetoes[-1]
    before = [p["box"], p["grid"], p["Velocity"], p["Amplitude"], p["other"]]
    # another property of the grid is unticked freely
    assert veto(before, [p["box"], p["grid"], p["Velocity"], p["other"]]) == ([], "")
    # its velocity is not
    back, why = veto(before, [p["box"], p["grid"], p["Amplitude"], p["other"]])
    assert back == [p["Velocity"]]
    assert why.startswith("Seismic velocities stays checked: it is the active T→D model")
    # nor its whole row: what was ticked of it is ticked again, the rest goes
    back, _why = veto(before, [p["other"]])
    assert back == [p["box"], p["grid"], p["Velocity"], p["Amplitude"]]


def test_with_no_model_converting_nothing_is_kept():
    core, p = _session()
    core.ctx.time_depth_cube_key = lambda: ""
    assert core.ctx.untick_vetoes[-1]([p["box"], p["grid"], p["Velocity"]], []) == ([], "")
