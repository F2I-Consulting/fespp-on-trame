"""Reading a property's values at a time step (overhaul slice 7).

`TimeScope(source, ts_idx)`: the session's time moved to time step
`ts_idx` for the reads in between `enter()` and `exit()` (or a `with`
block), then put back, the source read again at it — a later colour-by or
colour bar must not pull data binned at the step. No move for None or an
index out of range. The statistics and the distribution used to carry
their own copy of these lines; `property_values.values_for` keeps its
batched variant (several reads, one move back)."""


def _time_keeper():
    from paraview import simple as pvsimple
    return pvsimple.GetTimeKeeper()


class TimeScope:
    def __init__(self, source, ts_idx, keeper=None):
        self._source = source
        self._ts = ts_idx
        self._keeper = keeper or _time_keeper
        self._saved = None

    def enter(self):
        if self._ts is None or self._source is None:
            return self
        try:
            tk = self._keeper()
            values = list(tk.TimestepValues or [])
            if 0 <= int(self._ts) < len(values):
                saved = float(tk.Time)
                want = float(values[int(self._ts)])
                tk.Time = want
                self._saved = saved
                self._source.UpdatePipeline(want)
        except Exception as exc:
            print(f"[fespp] time step {self._ts}: the read stays at the session's time"
                  f" ({exc!r})", flush=True)
        return self

    def exit(self):
        saved, self._saved = self._saved, None
        if saved is None:
            return
        try:
            tk = self._keeper()
            tk.Time = saved
            self._source.UpdatePipeline(saved)
        except Exception as exc:
            print(f"[fespp] the session's time could not be put back ({exc!r})", flush=True)

    def __enter__(self):
        return self.enter()

    def __exit__(self, *exc):
        self.exit()
        return False
