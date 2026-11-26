"""A scene's rows go with what is no longer read, not with what is under a
row still read: a log shown is the row of its channel, under its frame's —
pruned to the representations read, it went, and the log's eye stayed open
over nothing (a node read from the Values view, 20/11)."""
from fespp_on_trame.engine.blockscope.pdc_scene import PdcScene

FRAME, LOG, GRID, OTHER = "/data/w/_frame", "/data/w/_frame/_log", "/data/g/_grid", "/data/w2/_frame/_log"


def _scene():
    scene = PdcScene("view_1", None, None)
    for sel in (FRAME, LOG, GRID, OTHER):
        scene.ensure_entry(sel)
    scene.isolated = {LOG, GRID, OTHER}
    return scene


def test_a_row_under_a_representation_read_stays():
    scene = _scene()
    scene.prune([FRAME, GRID])
    assert set(scene.block_state) == {FRAME, LOG, GRID}
    assert scene.isolated == {LOG, GRID}


def test_what_is_no_longer_read_goes_with_what_is_under_it():
    scene = _scene()
    scene.prune([GRID])
    assert set(scene.block_state) == {GRID}
    assert scene.isolated == {GRID}
