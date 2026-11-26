"""Integer sets as runs: [[first, last], ...], each run inclusive.

A selection extract keeps cell ids by the thousand, mostly in long
consecutive stretches (a block of a grid, a layer); a session file stores
them as runs rather than one number each."""


def to_runs(ids):
    """Sorted, de-duplicated runs of the integers in `ids`."""
    out = []
    for v in sorted(set(int(i) for i in ids or ())):
        if out and v == out[-1][1] + 1:
            out[-1][1] = v
        else:
            out.append([v, v])
    return out


def from_runs(runs):
    """The integers of `runs`, in order."""
    out = []
    for run in runs or ():
        first, last = int(run[0]), int(run[1])
        out.extend(range(first, last + 1))
    return out
