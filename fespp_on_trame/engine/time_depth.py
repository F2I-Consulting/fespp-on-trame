"""Time-depth law — what draws an object of one vertical domain in a view of
the other (the PO, 30/10: a property in time, asked for in a depth view, is
either seen in the time view or converted for display); the laws of the
session's velocity models are edited in the card of a 3D view.

The law is a table of points (depth in metres below the vertical zero,
two-way time in milliseconds), laterally constant, piecewise linear
between two points: each interval is one velocity, v = 2 Δz / Δt. Below
the last point the last interval carries on; above the first, the first.
A law starts at its start point — the zero (0 m, 0 ms) unless another is
given: a datum, 120 m at 0 ms, or 0 m at 30 ms (the PO's manager, 02/11)
— and holds one more point at least: a line (the PO: "a line from 0 to an
entered depth, points added, the interval velocity between two points").

Pure Python, no VTK: `table()` hands the two columns to whoever converts
arrays (the scene's convert stage interpolates with numpy); `to_time` /
`to_depth` convert one value, for the tests and the card.
"""
from bisect import bisect_right

DEPTH, TIME = "depth", "time"
ZERO = (0.0, 0.0)
# the line a TDLaw entered by hand starts from, to edit: 0 to 5 000 m at
# 2 000 m/s (also the velocity of a point added to an empty law)
DEFAULT_V = 2000.0
START_DEPTH = 5000.0


def _pairs(points):
    out = []
    for p in points or ():
        if isinstance(p, dict):
            z, t = p.get("depth"), p.get("twt")
        else:
            z, t = p
        try:
            out.append((float(z), float(t)))
        except (TypeError, ValueError):
            print(f"[fespp] time-depth law: a point not read: {p!r}", flush=True)
            continue
    return out


class Law:
    """`points`: (depth m, two-way time ms) pairs after the `start` point,
    the zero unless given. The points are kept as given (the card edits
    them in place); `problems()` says what keeps the law from converting."""

    def __init__(self, points=(), start=ZERO):
        self.start = (float(start[0]), float(start[1]))
        self.points = [p for p in _pairs(points) if p != self.start]

    # ---------------------------------------------------------------- edit
    @classmethod
    def from_dict(cls, data):
        data = data or {}
        start = _pairs([data["start"]]) if data.get("start") else []
        return cls(data.get("points") or (), start[0] if start else ZERO)

    def to_dict(self):
        out = {"points": [{"depth": z, "twt": t} for z, t in self.points]}
        if self.start != ZERO:
            out["start"] = {"depth": self.start[0], "twt": self.start[1]}
        return out

    def copy(self):
        return Law(list(self.points), self.start)

    def set_start(self, depth=None, twt=None):
        z, t = self.start
        self.start = (float(z if depth is None else depth), float(t if twt is None else twt))

    def set_point(self, index, depth=None, twt=None):
        z, t = self.points[index]
        self.points[index] = (float(z if depth is None else depth), float(t if twt is None else twt))

    def add_point(self, depth=None, twt=None):
        """A point after the last: at the same velocity, 500 m further,
        unless given. A point above the start becomes the start, the old
        start one of the points."""
        rows = self.rows()
        z0, t0 = rows[-1][:2] if rows else ZERO
        v = self.velocities()[-1] if self.velocities() else DEFAULT_V
        z = float(z0 + 500.0 if depth is None else depth)
        t = float(t0 + 2000.0 * (z - z0) / v if twt is None else twt)
        if z < self.start[0]:
            self.points.append(self.start)
            self.start = (z, t)
            return -1
        self.points.append((z, t))
        return len(self.points) - 1

    def del_point(self, index):
        del self.points[index]

    def set_velocity(self, index, velocity):
        """The interval above row `index` (1: the first point) set to
        `velocity` m/s: the row's time follows, its depth kept, and the
        rows below shift with it, each keeping its own velocity — the
        depths are the picks, the times what the velocities make of them."""
        v = float(velocity)
        if v <= 0:
            raise ValueError("a velocity is positive")
        self.points.sort()
        rows = self.rows()
        if not 1 <= index < len(rows):
            raise IndexError("no such interval")
        z_prev, t_prev = rows[index - 1]
        z_cur, t_old = rows[index]
        if z_cur <= z_prev:
            raise ValueError("the point is not below the one above")
        delta = t_prev + 2000.0 * (z_cur - z_prev) / v - t_old
        for k in range(index - 1, len(self.points)):
            z, t = self.points[k]
            self.points[k] = (z, t + delta)

    # ---------------------------------------------------------------- read
    def rows(self):
        """The start, then the points in depth order: [(z, t)]."""
        return [self.start] + sorted(self.points)

    def velocities(self):
        """The interval velocity (m/s) of each interval of `rows()`, None
        for an interval that is not a step down in both columns."""
        rows = self.rows()
        out = []
        for (z0, t0), (z1, t1) in zip(rows, rows[1:]):
            dz, dt = z1 - z0, t1 - t0
            out.append(2000.0 * dz / dt if dz > 0 and dt > 0 else None)
        return out

    def problems(self):
        """Why the law cannot convert yet, [] when it can: no point beyond
        the start, or a point not deeper AND later than the one before."""
        if not self.points:
            return ["no point beyond the start: enter a depth and its two-way time"]
        out = []
        rows = self.rows()
        for i, ((z0, t0), (z1, t1)) in enumerate(zip(rows, rows[1:])):
            if z1 <= z0 or t1 <= t0:
                out.append(f"point {i + 1} ({z1:g} m, {t1:g} ms) is not below and later than"
                           f" the one before ({z0:g} m, {t0:g} ms)")
        return out

    def valid(self):
        return not self.problems()

    def table(self):
        """The two columns the convert stage interpolates on: (depths,
        times), the start first, both increasing; ([], []) when invalid."""
        if not self.valid():
            return [], []
        rows = self.rows()
        return [z for z, _t in rows], [t for _z, t in rows]

    # ------------------------------------------------------------- convert
    @staticmethod
    def _interp(x, xs, ys):
        """Piecewise linear on (xs, ys), the end intervals carried beyond
        the ends."""
        n = len(xs)
        i = bisect_right(xs, x)
        if i <= 0:
            i = 1
        elif i >= n:
            i = n - 1
        x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
        return y0 + (x - x0) * (y1 - y0) / (x1 - x0)

    def to_time(self, depth):
        zs, ts = self.table()
        if not zs:
            raise ValueError("; ".join(self.problems()))
        return self._interp(float(depth), zs, ts)

    def to_depth(self, twt):
        zs, ts = self.table()
        if not zs:
            raise ValueError("; ".join(self.problems()))
        return self._interp(float(twt), ts, zs)

    def convert(self, values, to):
        """`values` of the other domain converted `to` DEPTH or TIME, one
        by one (the card's check; arrays go through `table()`)."""
        f = self.to_depth if to == DEPTH else self.to_time
        return [f(v) for v in values]


def starting_law():
    """The law a TDLaw entered by hand starts from, a line to edit: 0 to
    START_DEPTH at DEFAULT_V. No model is made of it unasked."""
    return Law([(START_DEPTH, 2000.0 * START_DEPTH / DEFAULT_V)])


class Column:
    """A law at a position (x, y): one column of the velocity model (the PO,
    30/10: "the arrow becomes 3D") — unplaced until both are entered."""

    def __init__(self, law=None, x=None, y=None, name=None, source=None):
        self.law = law if law is not None else Law()
        self.x = None if x is None else float(x)
        self.y = None if y is None else float(y)
        self.name = str(name) if name else None      # "C<n>" in the view when None
        self.source = str(source) if source else None   # what pre-filled it ("TWTIME, 167 samples")

    @classmethod
    def from_dict(cls, data):
        data = data or {}
        return cls(Law.from_dict(data), data.get("x"), data.get("y"), data.get("name"), data.get("source"))

    def to_dict(self):
        out = {"x": self.x, "y": self.y, **self.law.to_dict()}
        if self.name:
            out["name"] = self.name
        if self.source:
            out["source"] = self.source
        return out

    def placed(self):
        return self.x is not None and self.y is not None

    def usable(self):
        """Drawn in the 3D views as a pin: placed, its law valid."""
        return self.placed() and self.law.valid()

    def why_left_out(self):
        """What in its law keeps this column from converting, in a few
        words: "no point", "a point out of order"; "" when its law is
        valid (the model adds "not placed" where a place is needed)."""
        if not self.law.points:
            return "no point"
        return "" if self.law.valid() else "a point out of order"


LONE_HALF = 500.0     # m: half the side of the square around a lone column (no extent set)
GROW_PAD = 0.02      # of the grown cube's larger side: the margin kept beyond a column
                     # placed outside the extent set
MAX_CELLS = 200      # along x, y and z
DEFAULT_CELLS = 64   # the velocity model's cells along x and y until the reader enters another number:
                     # coarse, so the model opens at once; the reader refines it
DEFAULT_LAYERS = 64  # the velocity model's layers in K, likewise
DEFAULT_TRANGE = (0.0, 5000.0)   # ms: the velocity model's two-way time range until the reader enters another


class Model:
    """What converts (no 1D / cube switch, the columns side by side): no
    column to start with, and nothing converts until one is entered whose law
    is valid. One column: its law everywhere, wherever it stands; several, the
    velocity model — the placed ones as control points, a point converted by
    the columns around it, weighted by the inverse square of their distance
    (engine/velocity_model). `nz`: the velocity model's layers, even in two-way time over `trange` (t0,
    t1) ms, the number the reader enters (the PO, 03/11: never "auto";
    None, the layers at the times entered, is kept for the engine alone).
    `cells`: the velocity model's cells
    edited by hand, {(k, j, i): m/s} on a velocity model of `cells_shape` (layers,
    ny, nx) — set aside when the velocity model's cells change."""

    def __init__(self):
        self.columns = []
        self.extent = None        # (x0, x1, y0, y1) the velocity model covers
        self.nx, self.ny = DEFAULT_CELLS, DEFAULT_CELLS
        self.nz = DEFAULT_LAYERS
        self.trange = DEFAULT_TRANGE
        self.cells = {}
        self.cells_shape = None

    # ---------------------------------------------------------------- edit
    @classmethod
    def from_dict(cls, data):
        """The model of a session; a document before 02/11 in "1d" mode (or
        older, a bare law) brings its law back as a column, first."""
        data = data or {}
        model = cls()
        model.columns = [Column.from_dict(c) for c in (data.get("columns") or [])]
        legacy = Law.from_dict(data)
        if data.get("mode", "1d") != "cube" and legacy.points:
            model.columns.insert(0, Column(legacy, name="1D" if model.columns else None))
        try:
            ext = list(data.get("extent") or [])
            zone, times = ext[:4], ext[4:6]
            model.extent = tuple(float(v) for v in zone) if len(zone) == 4 and None not in zone else None
            model.nx = max(1, min(MAX_CELLS, int(data.get("nx") or DEFAULT_CELLS)))
            model.ny = max(1, min(MAX_CELLS, int(data.get("ny") or DEFAULT_CELLS)))
            model.nz = max(1, min(MAX_CELLS, int(data["nz"]))) if data.get("nz") else DEFAULT_LAYERS
            # a document before 04/11 holds its times apart, in `trange`
            tr = times if len(times) == 2 else data.get("trange")
            model.trange = (float(tr[0]), float(tr[1])) if tr and len(tr) == 2 else DEFAULT_TRANGE
        except (TypeError, ValueError):
            print(f"[fespp] time-depth model: a velocity model setting not read: {data!r}"[:200], flush=True)
        try:
            shape = data.get("cells_shape")
            model.cells_shape = tuple(int(v) for v in shape) if shape and len(shape) == 3 else None
            for k, j, i, v in (data.get("cells") or []):
                model.cells[(int(k), int(j), int(i))] = float(v)
        except (TypeError, ValueError):
            print(f"[fespp] time-depth model: the edited cells not read: {data!r}"[:200], flush=True)
            model.cells, model.cells_shape = {}, None
        return model

    def to_dict(self):
        """The model of a session; `extent` is [x0, x1, y0, y1, t0, t1]: the
        zone, null while none is set, and the two-way times the layers cut."""
        out = {"columns": [c.to_dict() for c in self.columns],
               "extent": list(self.extent or (None,) * 4) + list(self.trange),
               "nx": self.nx, "ny": self.ny, "nz": self.nz}
        if self.cells and self.cells_shape:
            out["cells"] = [[k, j, i, v] for (k, j, i), v in sorted(self.cells.items())]
            out["cells_shape"] = list(self.cells_shape)
        return out

    def set_cell(self, k, j, i, velocity, shape):
        """Cell (k, j, i) of the velocity model of `shape` (layers, ny, nx) set to
        `velocity` by hand; the cells of another shape are let go."""
        v = float(velocity)
        if v <= 0:
            raise ValueError("a velocity is positive")
        shape = tuple(int(n) for n in shape)
        k, j, i = int(k), int(j), int(i)
        if not (0 <= k < shape[0] and 0 <= j < shape[1] and 0 <= i < shape[2]):
            raise IndexError("no such cell")
        if self.cells_shape != shape:
            self.cells.clear()
            self.cells_shape = shape
        self.cells[(k, j, i)] = v

    def add_column(self, x=None, y=None):
        """A column after the last, its law to start from the first column
        that converts, else from the starting line."""
        used = self.usable_columns()
        law = used[0].law.copy() if used else starting_law()
        self.columns.append(Column(law, x, y))
        return len(self.columns) - 1

    def usable_columns(self):
        """The columns that convert: the one whose law is valid, wherever it
        stands; of several, the placed ones (the first, when none is)."""
        valid = [c for c in self.columns if c.law.valid()]
        if len(valid) <= 1:
            return valid
        placed = [c for c in valid if c.placed()]
        return placed or valid[:1]

    def has_law(self):
        """A column converts: the model can make a velocity model."""
        return bool(self.usable_columns())

    def why_left_out(self, column):
        """Why `column` does not convert, in a few words ("not placed",
        "no point", "a point out of order", joined), "" when it does."""
        if any(c is column for c in self.usable_columns()):
            return ""
        # a place matters once another column converts: the velocity model needs it
        others = any(c is not column and c.law.valid() for c in self.columns)
        out = ["not placed"] if others and not column.placed() else []
        law = column.why_left_out()
        return ", ".join(out + ([law] if law else []))

    def extent_in_use(self):
        """The extent the velocity model covers: the one set (typed, the files' or
        the loaded data's), grown to take in every column placed outside
        it (two fields side by side: the neighbour's peripheral wells
        count); else a square around the placed columns that convert, a
        little wider, 1 km at least: a velocity model needs no data loaded to stand.
        None while none is set and no converting column is placed."""
        if self.extent is not None:
            return self._grown(self.extent)
        cols = [c for c in self.usable_columns() if c.placed()]
        if not cols:
            return None
        xs, ys = [c.x for c in cols], [c.y for c in cols]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        half = max(0.6 * max(max(xs) - min(xs), max(ys) - min(ys)), LONE_HALF)
        return (cx - half, cx + half, cy - half, cy + half)

    def outside_extent(self):
        """The indices of the columns placed outside the extent set: the
        ones that grew the velocity model. Empty while no extent is set."""
        if self.extent is None:
            return []
        x0, x1, y0, y1 = self.extent
        return [i for i, c in enumerate(self.columns)
                if c.placed() and not (x0 <= c.x <= x1 and y0 <= c.y <= y1)]

    def _grown(self, ext):
        """`ext` grown, side by side, to the columns placed beyond it,
        each grown side keeping a margin (GROW_PAD) past its column."""
        out = [self.columns[i] for i in self.outside_extent()]
        if not out:
            return ext
        x0, x1, y0, y1 = ext
        nx0, nx1 = min([x0] + [c.x for c in out]), max([x1] + [c.x for c in out])
        ny0, ny1 = min([y0] + [c.y for c in out]), max([y1] + [c.y for c in out])
        pad = GROW_PAD * max(nx1 - nx0, ny1 - ny0)
        return (nx0 - pad if nx0 < x0 else x0, nx1 + pad if nx1 > x1 else x1,
                ny0 - pad if ny0 < y0 else y0, ny1 + pad if ny1 > y1 else y1)

    def free_spot(self):
        """Where a column "at the centre" goes: the extent's centre, or,
        once a column stands there, the first free cell centre of a finer
        grid over the extent (2 x 2, then 3 x 3...), the nearest to the
        centre first: always inside the extent, never on another column.
        None while there is no extent in use (or an empty one)."""
        ext = self.extent_in_use()
        if ext is None:
            return None
        x0, x1, y0, y1 = ext
        w, h = x1 - x0, y1 - y0
        if w <= 0 or h <= 0:
            return None
        cx, cy = x0 + w / 2, y0 + h / 2
        taken = [(c.x, c.y) for c in self.columns if c.placed()]
        tx, ty = 0.02 * w, 0.02 * h
        for g in range(1, 9):
            spots = [(x0 + (i + 0.5) * w / g, y0 + (j + 0.5) * h / g)
                     for j in range(g) for i in range(g)]
            spots.sort(key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2)
            for x, y in spots:
                if all(abs(x - px) > tx or abs(y - py) > ty for px, py in taken):
                    return x, y
        return cx, cy

    # ---------------------------------------------------------------- read
    def laws(self):
        """The laws that convert, [(x, y, law)]: none while no column does."""
        return [(c.x, c.y, c.law) for c in self.usable_columns()]

    def columns_of(self):
        """What the convert stage interpolates on: [{x, y, depths, times}]."""
        out = []
        for x, y, law in self.laws():
            depths, times = law.table()
            if depths:
                out.append({"x": x, "y": y, "depths": depths, "times": times})
        return out

    def problems(self):
        """What is wrong with the model's zone or times, [] when nothing is:
        an empty extent typed, an empty time range. A column left out is no
        problem of the model: each one says why itself (`why_left_out`), and
        `has_law` says whether one converts at all."""
        if self.extent is not None:
            x0, x1, y0, y1 = self.extent
            if x1 <= x0 or y1 <= y0:
                return ["the extent is empty: x1 above x0 and y1 above y0"]
        if self.trange[1] <= self.trange[0]:
            return ["the time range is empty: its end later than its start"]
        return []

    def valid(self):
        return not self.problems()

    def deepest(self):
        """(depth, twt) of the deepest point of the columns, (0, 0) with
        none: how far down the empty outline reaches."""
        points = [p for c in self.columns for p in c.law.points]
        if not points:
            return (0.0, 0.0)
        return (max(z for z, _t in points), max(t for _z, t in points))

    def cube(self):
        """The velocity model (engine/velocity_model), the cells edited by
        hand set on it when it still has their shape; None while
        `problems()` says why not, or no column converts."""
        if self.problems():
            return None
        from fespp_on_trame.engine.velocity_model import Cube
        cube = Cube.build(self.laws(), self.extent_in_use(), self.nx, self.ny, self.nz, self.trange)
        if cube is not None and self.cells and self.cells_shape == cube.v.shape:
            cube.apply(self.cells)
        return cube

    def cells_stale(self, cube):
        """The edited cells belong to another shape than `cube`'s: they no
        longer apply."""
        return bool(self.cells) and (cube is None or self.cells_shape != cube.v.shape)
