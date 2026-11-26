"""engine/values: a read at a time step moves the session's time and puts
it back, the source read again at it."""
from fespp_on_trame.engine.values import TimeScope


class _Keeper:
    TimestepValues = [0.0, 10.0, 20.0]
    Time = 0.0


class _Source:
    def __init__(self):
        self.updates = []

    def UpdatePipeline(self, t):
        self.updates.append(t)


def test_a_step_is_read_and_the_session_s_time_comes_back():
    tk, src = _Keeper(), _Source()
    tk.Time = 10.0
    with TimeScope(src, 2, keeper=lambda: tk):
        assert tk.Time == 20.0
    assert tk.Time == 10.0
    assert src.updates == [20.0, 10.0]


def test_no_step_or_one_out_of_range_moves_nothing():
    tk, src = _Keeper(), _Source()
    with TimeScope(src, None, keeper=lambda: tk):
        pass
    with TimeScope(src, 7, keeper=lambda: tk):
        pass
    assert src.updates == [] and tk.Time == 0.0
