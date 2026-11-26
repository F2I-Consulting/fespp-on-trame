"""app/scene/eyes: one writer for the eye sets of the 3D views, and the
state watcher no longer runs the pass a second time (04-verification W1)."""
from fespp_on_trame.app.scene.eyes import Eyes


class _State(dict):
    def __getattr__(self, k):
        return self.get(k)


def _eyes(rewrite=None, live=True, skip=True):
    state = _State()
    runs = []

    def run(vid, paths):
        runs.append((vid, list(paths)))
        if rewrite is not None:
            state[f"visible_paths__{vid}"] = rewrite(paths)

    return Eyes(state, run, is_live=lambda _v: live, skip_echoes=skip), state, runs


def test_a_write_then_apply_is_not_run_again_by_the_watcher():
    eyes, state, runs = _eyes()
    state["visible_paths__v1"] = ["/a"]
    eyes.apply("v1", ["/a"])
    eyes.on_watch("v1", ["/a"])          # the flush hands the same set back
    assert runs == [("v1", ["/a"])]
    assert eyes.passes["v1"] == 1 and eyes.echoes["v1"] == 1


def test_echoes_still_run_while_the_skip_is_off():
    # the default until the pass settles in one run (see the module)
    eyes, state, runs = _eyes(skip=False)
    state["visible_paths__v1"] = ["/a"]
    eyes.apply("v1", ["/a"])
    eyes.on_watch("v1", ["/a"])
    assert len(runs) == 2 and eyes.echoes["v1"] == 1


def test_a_click_in_the_browser_runs_the_pass():
    eyes, state, runs = _eyes()
    eyes.set("v1", ["/a"])
    state["visible_paths__v1"] = ["/a", "/b"]
    eyes.on_watch("v1", ["/a", "/b"])
    assert runs[-1] == ("v1", ["/a", "/b"])


def test_what_the_pass_leaves_is_what_the_watcher_skips():
    # the pass drops a sibling eye (one colouring eye per grid) and echoes
    # the cleaned set: that echo must not run the pass again
    eyes, state, runs = _eyes(rewrite=lambda paths: [p for p in paths if p != "/old"])
    eyes.set("v1", ["/old", "/new"])
    eyes.on_watch("v1", ["/new"])
    assert len(runs) == 1 and state["visible_paths__v1"] == ["/new"]


def test_apply_always_runs_a_replay():
    # the Globe's scene built or a realization replays the same set on purpose
    eyes, _state, runs = _eyes()
    eyes.set("v1", ["/a"])
    eyes.apply("v1")
    assert len(runs) == 2


def test_toggle_inherit_and_show_everywhere():
    eyes, state, runs = _eyes()
    eyes.toggle("v1", "/a")
    eyes.toggle("v1", "/b")
    eyes.toggle("v1", "/a")
    assert state["visible_paths__v1"] == ["/b"]
    assert eyes.inherit("v2", "v1") and state["visible_paths__v2"] == ["/b"]
    assert not eyes.inherit("v3", "nowhere")
    assert eyes.show_everywhere(["v1", "v2"], ["/c"], True) == ["v1", "v2"]
    assert eyes.show_everywhere(["v1", "v2"], ["/c"], True) == []
    assert state["visible_paths__v2"] == ["/b", "/c"]


def test_a_closing_view_is_left_alone():
    eyes, _state, runs = _eyes(live=False)
    eyes.apply("v1", ["/a"])
    assert runs == [] and "v1" not in eyes.passes


def test_a_read_keeps_the_watcher_pass():
    # the load handlers invalidate after their passes: the watcher's pass
    # at the end of the flush sees the read complete
    eyes, state, runs = _eyes()
    state["visible_paths__v1"] = ["/a"]
    eyes.apply("v1", ["/a"])
    eyes.invalidate()
    eyes.on_watch("v1", ["/a"])
    assert len(runs) == 2


def test_a_stale_watcher_value_is_not_applied():
    # a load writes 11 then 12 paths; the pass applies 12; the watcher is
    # then handed the queued 11, then 12: the state's 12 holds, no pass runs
    eyes, state, runs = _eyes()
    state["visible_paths__v1"] = ["/a", "/b"]
    eyes.apply("v1", ["/a", "/b"])
    eyes.on_watch("v1", ["/a"])
    eyes.on_watch("v1", ["/a", "/b"])
    assert runs == [("v1", ["/a", "/b"])]
