"""app/core/lifecycle: one list of subscribers per application event
(slice 2b of the overhaul)."""
import pytest

from fespp_on_trame.app.core.lifecycle import Lifecycle


def test_every_subscriber_runs_in_order_with_the_event_s_arguments():
    lc = Lifecycle(log=lambda _t: None)
    seen = []
    lc.on("view_closed", lambda vid: seen.append(("a", vid)), name="a")

    @lc.on("view_closed")
    def b(vid):
        seen.append(("b", vid))
    lc.emit("view_closed", vid="view_2")
    assert seen == [("a", "view_2"), ("b", "view_2")]
    assert lc.subscribers("view_closed") == ["a", "b"]


def test_a_failing_subscriber_is_said_and_the_others_still_run():
    logs, seen = [], []
    lc = Lifecycle(log=logs.append)

    def broken(vid):
        raise KeyError("gone")
    lc.on("view_cuts", broken)
    lc.on("view_cuts", lambda vid: seen.append(vid))
    lc.emit("view_cuts", vid="view_1")
    assert seen == ["view_1"]
    assert logs and "broken" in logs[0] and "view_cuts" in logs[0]


def test_an_unknown_event_is_refused_at_subscription():
    with pytest.raises(ValueError):
        Lifecycle().on("view_reopened", lambda: None)
