"""Velocity model — v(x, y, t), what converts an object of the other
vertical domain for display (the PO, 30/10: "the real cube, lines are not
great"), in TIME: its layers are two-way times, its grid is drawn in a
time view.

nx × ny cells over an extent (x0..x1, y0..y1), layers in two-way time
shared by every cell column — K even ones over the time range set, or the
times of the points entered (the laws are exact there) —, one interval
velocity per cell (m/s) and a depth at the top of each cell column. Built
from the model's laws (engine/time_depth): one law fills every cell (1 × 1
with no extent); placed columns are control points, each cell of a layer
reading them by the inverse square of its distance to them — a first cube
from pseudo-wells. The depths integrate down the cell's vertical: z(t) =
z0 + Σ v dt / 2, and the inverse for depth → time; above the first and
below the last layer the end velocities carry on.

The columns are drawn in the 3D views as the arrow of their track
(`pins`), in the view's domain: at their depth in a depth view, at their
two-way time in a time view.

numpy throughout: the stage converts whole leaves.
"""
import numpy as np

DEPTH, TIME = "depth", "time"


def _polydata(points, verts=(), lines=(), polys=(), arrays=None):
    """A vtkPolyData of `points` with its vertices, lines and polygons
    (cells in THAT order, as VTK keeps them) and the cell arrays
    `arrays` {name: values, one per cell in the same order}."""
    from vtkmodules.util.numpy_support import numpy_to_vtk
    from vtkmodules.vtkCommonCore import vtkPoints
    from vtkmodules.vtkCommonDataModel import vtkCellArray, vtkPolyData
    out = vtkPolyData()
    pts = vtkPoints()
    pts.SetData(numpy_to_vtk(np.asarray(points, float).reshape(-1, 3), deep=1))
    out.SetPoints(pts)
    for kind, cells in (("verts", verts), ("lines", lines), ("polys", polys)):
        if not cells:
            continue
        arr = vtkCellArray()
        for c in cells:
            arr.InsertNextCell(len(c), list(c))
        getattr(out, {"verts": "SetVerts", "lines": "SetLines", "polys": "SetPolys"}[kind])(arr)
    for name, values in (arrays or {}).items():
        a = numpy_to_vtk(np.asarray(values, float), deep=1)
        a.SetName(name)
        out.GetCellData().AddArray(a)
    if arrays:
        out.GetCellData().SetActiveScalars(next(iter(arrays)))
    return out


def _quads(corners, values, name="velocity"):
    """A vtkPolyData of quads — `corners` (n, 4, 3), each quad its own four
    points — with their cell array `name`."""
    from vtkmodules.util.numpy_support import numpy_to_vtk, numpy_to_vtkIdTypeArray
    from vtkmodules.vtkCommonCore import vtkPoints
    from vtkmodules.vtkCommonDataModel import vtkCellArray, vtkPolyData
    n = len(corners)
    out = vtkPolyData()
    pts = vtkPoints()
    pts.SetData(numpy_to_vtk(np.ascontiguousarray(corners, float).reshape(-1, 3), deep=1))
    out.SetPoints(pts)
    cells = vtkCellArray()
    cells.SetData(numpy_to_vtkIdTypeArray(np.arange(0, 4 * n + 1, 4, dtype=np.int64), deep=1),
                  numpy_to_vtkIdTypeArray(np.arange(4 * n, dtype=np.int64), deep=1))
    out.SetPolys(cells)
    a = numpy_to_vtk(np.ascontiguousarray(values, float), deep=1)
    a.SetName(name)
    out.GetCellData().AddArray(a)
    out.GetCellData().SetActiveScalars(name)
    return out


def fill_missing(v):
    """The velocities of `v` (nl, ny, nx) that are none — not a number, not
    above zero — replaced in place by the nearest one of their cell column:
    the one above, else the one below; a column that holds none takes the
    mean of the others. How many were replaced; ValueError when the grid
    holds no velocity at all."""
    with np.errstate(invalid="ignore"):
        bad = v > 0                 # False for what is not a number too
    np.logical_not(bad, out=bad)
    bad |= np.isinf(v)
    count = int(np.count_nonzero(bad))
    if count == v.size:
        raise ValueError("no velocity above zero on the grid")
    if not count:
        return 0
    for k in range(1, len(v)):
        take = bad[k] & ~bad[k - 1]
        v[k][take] = v[k - 1][take]
        bad[k][take] = False
    for k in range(len(v) - 2, -1, -1):
        take = bad[k] & ~bad[k + 1]
        v[k][take] = v[k + 1][take]
        bad[k][take] = False
    if bad.any():
        v[bad] = v[~bad].mean(dtype=float)
    return count


def read_velocities(v, times, reading, at):
    """The velocities `v` (nl, ny, nx) of a grid read as it is — "interval",
    "average" or "rms" velocities standing at `at` of their cells between
    `times` (ms) — made what a Cube takes, in place: a cell with none takes
    the nearest one of its column (`fill_missing`), RMS velocities become
    interval ones (`interval_from_rms`), and a grid that starts away from
    time 0 is given the depth of its top: its first velocity carried on up
    to time 0, where the depth is 0 (an average velocity says that depth
    itself). (the depth of the top or None, where the values stand from then
    on, how many cells were replaced)."""
    replaced = fill_missing(v)
    t0 = float(np.asarray(times, float)[0])
    ztop = v[0] * v.dtype.type(t0 / 2000.0) if reading != "average" and t0 != 0.0 else None
    if reading == "rms":
        at = interval_from_rms(v, times, at)
    return ztop, at, replaced


def depth_model_in_time(depths, v):
    """A velocity model in depth read as one in two-way time: `depths` the
    boundaries of its layers (nk + 1, m, increasing), `v` their velocities
    (nk, nj, ni), m/s. Each column's times are integrated down its cells, then
    its interval velocities read again on nk even layers from time 0 at the
    surface to the latest time, so that a column keeps its depth at each of
    them. The first velocity carries on up to the surface (the zero, or the
    top of a model above it), the last one below the bottom; a cell with no
    velocity takes the nearest one of its column (`fill_missing`). (times,
    velocities, surface depth)."""
    z = np.asarray(depths, float)
    v = np.array(v, float)
    fill_missing(v)
    nk, nj, ni = v.shape
    surface = min(float(z[0]), 0.0)
    first = 2000.0 * (z[0] - surface) / v[0]
    down = np.cumsum(2000.0 * np.diff(z)[:, None, None] / v, axis=0)
    t = np.concatenate([first[None], first[None] + down])
    times = np.linspace(0.0, float(t[-1].max()), nk + 1)
    out = np.empty_like(v)
    for j, i in np.ndindex(nj, ni):
        column = t[:, j, i]
        at = np.interp(times, column, z)
        above, below = times < column[0], times > column[-1]
        at[above] = surface + times[above] * v[0, j, i] / 2000.0
        at[below] = z[-1] + (times[below] - column[-1]) * v[-1, j, i] / 2000.0
        out[:, j, i] = 2000.0 * np.diff(at) / np.diff(times)
    return times, out, surface


def interval_from_rms(v, times, at):
    """RMS velocities `v` (nl, ny, nx) of the layers bounded by `times` (ms),
    each standing at `at` of its cell, made interval velocities in place by
    Dix's formula between a sample and the next: v² = (v2²·t2 − v1²·t1) /
    (t2 − t1), not smoothed. Where the RMS velocity falls too fast for an
    interval velocity to exist, the RMS velocity itself stands; so does it
    above the first sample. Hands back where the values stand from then on
    (the Cube's `at`)."""
    t = np.asarray(times, float)
    ts = t[:-1] + at * np.diff(t)
    n = len(ts)

    def between(a, b):
        q = v[b].astype(float) ** 2 * ts[b] - v[a].astype(float) ** 2 * ts[a]
        q /= ts[b] - ts[a]
        real = q > 0
        out = np.sqrt(np.where(real, q, 0.0))
        out[~real] = v[b][~real]
        return out

    if at >= 1.0 - 1e-9:            # a sample at its cell's bottom: the interval above it is the cell
        for k in range(n - 1, 0, -1):
            v[k] = between(k - 1, k)
        return 0.5
    for k in range(n - 1):
        v[k] = between(k, k + 1)
    if n > 1:
        v[n - 1] = v[n - 2]
    return min(1.0, at + 0.5)


class Cube:
    """`times`: increasing two-way times (nl + 1, ms), the layer
    boundaries; `v`: (nl, ny, nx) m/s; `ztop`: (ny, nx) the depth at the
    top boundary, 0 by default. `z`: (nl + 1, ny, nx) the depth of every
    boundary of every cell column, integrated down.

    `frame`: (ox, oy, ax, ay, bx, by) for the columns of a grid read as it
    is — its first node and the step of one column along each of its two
    horizontal axes, which need not follow X and Y (a seismic survey's
    inline and crossline); None: the columns divide the extent along X and
    Y. Velocities given in float32 stay float32 (a 90 M cell grid).

    `average`: `v` holds AVERAGE velocities from the datum (depth =
    v·t/2), interpolated in time between their samples; the interval
    velocities between the depths they give are what the cube holds from
    then on.

    `at`: where in its cell a value stands, a fraction of the cell's height
    — 0 its top (the time of a seismic sample), 0.5 its middle, 1 its bottom
    (the PO, 12/11: what the producer did, which RESQML does not say). An
    average velocity is a sample at that time; an interval velocity holds
    over a cell's height centred there, 0.5 being the cell itself. The depth
    is 0 at time 0 whatever `at`."""

    def __init__(self, x0, x1, y0, y1, nx, ny, times, v, ztop=None, frame=None, average=False, at=0.5):
        self.x0, self.x1, self.y0, self.y1 = float(x0), float(x1), float(y0), float(y1)
        self.nx, self.ny = int(nx), int(ny)
        self.frame = tuple(float(f) for f in frame) if frame is not None else None
        self.t = np.asarray(times, float)
        v = np.asarray(v)
        self.v = (v if v.dtype == np.float32 else v.astype(float)).reshape(len(self.t) - 1, self.ny, self.nx)
        self.top = (np.zeros((1, self.ny, self.nx), self.v.dtype) if ztop is None
                    else np.asarray(ztop, self.v.dtype).reshape(1, self.ny, self.nx))
        at = min(1.0, max(0.0, float(at)))
        if average:
            self._from_average(at)
        else:
            self._centre_on(at)
            self._depths()

    def _centre_on(self, at):
        """Interval velocities standing at `at` of their cells: each layer
        takes the velocities whose cell's height covers it, in place (a
        value at the top covers the upper half of its layer and the lower
        half of the one above)."""
        shift = at - 0.5
        if abs(shift) < 1e-9 or self.layers < 2:
            return
        f = abs(shift)
        if shift < 0:       # standing higher: a layer is partly its own, partly the next one's
            for k in range(self.layers - 1):
                self.v[k] *= 1.0 - f
                self.v[k] += f * self.v[k + 1]
        else:               # standing lower: partly the one above's
            for k in range(self.layers - 1, 0, -1):
                self.v[k] *= 1.0 - f
                self.v[k] += f * self.v[k - 1]

    def _from_average(self, at):
        """The depths of the boundaries from average velocities sampled at
        `at` of their cells (v·t/2 at each boundary, v read between the
        samples around it, the first and the last carried out), then `v`
        made the interval velocities between them, in place."""
        tt = (self.t / 2000.0).astype(self.v.dtype)
        self.z = np.empty((len(self.t),) + self.v.shape[1:], self.v.dtype)
        # the average velocity at boundary k lies between the samples of
        # cells k - 1 and k: `at` of the way from the one below
        self.z[0] = self.v[0]
        self.z[-1] = self.v[-1]
        if self.layers > 1:
            np.multiply(self.v[:-1], at, out=self.z[1:-1])
            self.z[1:-1] += (1.0 - at) * self.v[1:]
        self.z *= tt[:, None, None]
        np.subtract(self.z[1:], self.z[:-1], out=self.v)
        self.v /= np.diff(tt)[:, None, None]
        self.top = self.z[:1].copy()
        self.zmax = float(self.z[-1].max())

    def _depths(self):
        """The depth at every layer boundary of every cell column,
        integrated down from the top through the velocities, in place."""
        dt = (np.diff(self.t) / 2000.0).astype(self.v.dtype)
        self.z = np.empty((len(self.t),) + self.v.shape[1:], self.v.dtype)
        self.z[0] = self.top[0]
        np.multiply(self.v, dt[:, None, None], out=self.z[1:])      # m, per layer
        np.cumsum(self.z[1:], axis=0, out=self.z[1:])
        self.z[1:] += self.top
        self.zmax = float(self.z[-1].max())

    def apply(self, cells):
        """`cells` {(k, j, i): m/s} set on the velocity model, the depths below them
        following: what the Values table edits by hand."""
        for (k, j, i), value in cells.items():
            self.v[k, j, i] = float(value)
        self._depths()

    def signature(self):
        """A digest of the velocity model — extent, cells, layers, velocities, top
        depths: two cubes alike share it, so a model changed into the same
        cube keeps its key and its version in the tree."""
        import hashlib
        h = hashlib.blake2b(digest_size=16)
        h.update(np.array([self.x0, self.x1, self.y0, self.y1, self.nx, self.ny, *(self.frame or ())],
                          float).tobytes())
        for a in (self.t, self.v, self.top):
            h.update(np.ascontiguousarray(a).tobytes())
        return h.hexdigest()

    def layer_values(self, k):
        """The velocities of layer `k`, row by row (ny rows of nx)."""
        return np.round(self.v[int(k)], 3).tolist()

    # ---------------------------------------------------------------- build
    @classmethod
    def build(cls, laws, extent=None, nx=20, ny=20, nz=None, trange=None):
        """From `laws` [(x, y, law)], every law valid: the placed ones as
        control points over `extent` (x0, x1, y0, y1), nx × ny; with none
        placed, the first law alone, the same in every cell (1 × 1 with no
        extent). The layers: `nz` even in time over `trange` (t0, t1) — the
        laws' first to last time when None —, or the times of the laws'
        points; a cell reads each law's depths at its layer boundaries
        (exact there), above a law's start and below its last point the end
        intervals carried on. None when there is no law."""
        laws = [(x, y, law) for x, y, law in laws if law.valid()]
        if not laws:
            return None
        placed = [(x, y, law) for x, y, law in laws if x is not None and y is not None]
        if extent is None:
            placed, extent, nx, ny = [], (0.0, 1.0, 0.0, 1.0), 1, 1
        x0, x1, y0, y1 = (float(e) for e in extent)
        used = placed or [laws[0]]
        times = {float(t) for _x, _y, law in used for _z, t in law.rows()}
        if nz:
            t0, t1 = (float(trange[0]), float(trange[1])) if trange else (min(times), max(times))
            layers = np.linspace(t0, t1, int(nz) + 1).tolist()
        else:
            layers = sorted(times)
        t = np.array(layers)
        xs = x0 + (np.arange(nx) + 0.5) * (x1 - x0) / nx
        ys = y0 + (np.arange(ny) + 0.5) * (y1 - y0) / ny
        X, Y = np.meshgrid(xs, ys)                          # (ny, nx)

        def per_layer(law):
            z = np.array([law.to_depth(tt) for tt in layers])
            return 2000.0 * np.diff(z) / np.diff(t), z[0]

        v = np.zeros((len(t) - 1, ny, nx))
        z0 = np.zeros((ny, nx))
        if not placed:
            lv, lz = per_layer(used[0][2])
            v[:] = lv[:, None, None]
            z0[:] = lz
        else:
            weight = np.zeros((ny, nx))
            for x, y, law in placed:
                w = 1.0 / ((X - x) ** 2 + (Y - y) ** 2 + 1.0)
                lv, lz = per_layer(law)
                v += w[None, :, :] * lv[:, None, None]
                z0 += w * lz
                weight += w
            v /= weight[None, :, :]
            z0 /= weight
        # the weights leave 1999.999…: a velocity is read to the micrometre per second
        v = np.round(v, 6)
        return cls(x0, x1, y0, y1, nx, ny, layers, v, np.round(z0, 6))

    # ---------------------------------------------------------------- read
    @property
    def layers(self):
        return len(self.t) - 1

    def summary(self):
        return {"nx": self.nx, "ny": self.ny, "layers": self.layers, "cells": int(self.v.size),
                "vmin": float(self.v.min()), "vmax": float(self.v.max()),
                "ttop": float(self.t[0]), "tmax": float(self.t[-1]),
                "ztop": float(self.z[0].min()), "zmax": self.zmax,
                "extent": [self.x0, self.x1, self.y0, self.y1]}

    def _grid_coords(self, x, y):
        """(b, a): where each (x, y) falls in column units, b along the rows
        (ny), a along a row (nx)."""
        x, y = np.asarray(x, float), np.asarray(y, float)
        if self.frame is None:
            dx = (self.x1 - self.x0) / self.nx or 1.0
            dy = (self.y1 - self.y0) / self.ny or 1.0
            return (y - self.y0) / dy, (x - self.x0) / dx
        ox, oy, ax, ay, bx, by = self.frame
        det = (ax * by - ay * bx) or 1.0
        dx, dy = x - ox, y - oy
        return (ax * dy - ay * dx) / det, (dx * by - dy * bx) / det

    def cells_of(self, x, y):
        """(j, i) of the cell under each (x, y), the edge cells carrying on
        outside the extent."""
        b, a = self._grid_coords(x, y)
        i = np.clip(np.floor(a).astype(int), 0, self.nx - 1)
        j = np.clip(np.floor(b).astype(int), 0, self.ny - 1)
        return j, i

    def probe(self, x, y, vertical, domain=DEPTH):
        """The cell at (x, y) and `vertical` (positive down: a depth in m,
        or a two-way time in ms in a time view): {i, j, k, v, depth, twt};
        None outside the extent or the velocity model's time range."""
        b, a = (float(c[0]) for c in self._grid_coords([x], [y]))
        if not (-1e-6 <= a <= self.nx + 1e-6 and -1e-6 <= b <= self.ny + 1e-6):
            return None
        if domain == TIME:
            twt = float(vertical)
            depth = float(self.to_depth([x], [y], [twt])[0])
        else:
            depth = float(vertical)
            twt = float(self.to_time([x], [y], [depth])[0])
        ttol = 1e-6 * max(1.0, abs(float(self.t[-1])))
        if twt < self.t[0] - ttol or twt > self.t[-1] + ttol:
            return None
        j, i = (int(a[0]) for a in self.cells_of([x], [y]))
        k = int(np.clip(np.searchsorted(self.t, twt, side="right") - 1, 0, self.layers - 1))
        return {"i": i, "j": j, "k": k, "v": float(self.v[k, j, i]), "depth": depth, "twt": twt}

    def _layer_at_depth(self, j, i, depth):
        """The layer holding each depth in its cell column (j, i), the end
        layers carrying on above and below: a bisection on the column's
        boundaries, every point at once — never the (nl + 1) × points
        boundaries gathered, gigabytes for a large grid."""
        nb = len(self.t)
        lo = np.zeros(depth.shape, int)
        hi = np.full(depth.shape, nb)
        for _ in range(int(np.ceil(np.log2(nb + 1)))):
            mid = (lo + hi) // 2
            above = self.z[np.minimum(mid, nb - 1), j, i] > depth
            go = lo < hi
            hi = np.where(go & above, mid, hi)
            lo = np.where(go & ~above, mid + 1, lo)
        return np.clip(lo - 1, 0, self.layers - 1)

    def to_time(self, x, y, depth):
        """Two-way time (ms) at `depth` (m, positive down) under (x, y)."""
        return self._time_at(*self.cells_of(x, y), np.asarray(depth, float))

    def to_depth(self, x, y, twt):
        """Depth (m) at two-way time `twt` (ms) under (x, y)."""
        return self._depth_at(*self.cells_of(x, y), np.asarray(twt, float))

    def _time_at(self, j, i, depth):
        k = self._layer_at_depth(j, i, depth)
        z0, z1 = self.z[k, j, i], self.z[k + 1, j, i]
        t0, t1 = self.t[k], self.t[k + 1]
        return t0 + (depth - z0) * (t1 - t0) / (z1 - z0)

    def _depth_at(self, j, i, twt):
        k = np.clip(np.searchsorted(self.t, twt, side="right") - 1, 0, self.layers - 1)
        t0, t1 = self.t[k], self.t[k + 1]
        z0, z1 = self.z[k, j, i], self.z[k + 1, j, i]
        return z0 + (twt - t0) * (z1 - z0) / (t1 - t0)

    def convert(self, xyz, to):
        """The z of `xyz` (n × 3) converted `to` DEPTH or TIME, the sign
        of z kept (in these files both are negative downward)."""
        xyz = np.asarray(xyz, float)
        z = xyz[:, 2]
        f = self.to_depth if to == DEPTH else self.to_time
        return np.sign(z) * f(xyz[:, 0], xyz[:, 1], np.abs(z))

    # ------------------------------------------------------------- display
    def bottom(self, domain=DEPTH):
        """The deepest vertical the velocity model reaches, negative downward."""
        return -(float(self.t[-1]) if domain == TIME else self.zmax)

    def shell(self, domain):
        """The outside of the velocity model as a reader would draw its
        grid: the top and bottom faces of every cell column and the side
        faces of the columns on its rim, each with its cell's interval
        `velocity` — what shows a model not generated yet, whose grid no
        reader holds. In the view's domain: the layer boundaries at their two-way
        times in a time view, each column at its own depths in a depth one.
        None for a grid read as it is: its reader draws it."""
        if self.frame is not None or self.layers < 1:
            return None
        nl, ny, nx = self.v.shape
        xs = np.linspace(self.x0, self.x1, nx + 1)
        ys = np.linspace(self.y0, self.y1, ny + 1)
        # the vertical of every boundary of every column, negative downward
        w = (np.broadcast_to(-self.t[:, None, None], (nl + 1, ny, nx)) if domain == TIME
             else -np.asarray(self.z, float))
        j, i = np.indices((ny, nx))
        corners, values = [], []

        def face(k):
            """The face of every column at boundary `k`."""
            z = w[k]
            return np.stack([np.stack([xs[i], ys[j], z], -1), np.stack([xs[i + 1], ys[j], z], -1),
                             np.stack([xs[i + 1], ys[j + 1], z], -1), np.stack([xs[i], ys[j + 1], z], -1)],
                            -2).reshape(-1, 4, 3)

        def side(xa, ya, xb, yb, jj, ii):
            """The faces from (xa, ya) to (xb, yb) of the columns (jj, ii),
            one per layer."""
            top, base = w[:-1][:, jj, ii], w[1:][:, jj, ii]
            xa, ya, xb, yb = (np.broadcast_to(c, top.shape) for c in (xa, ya, xb, yb))
            corners.append(np.stack([np.stack([xa, ya, top], -1), np.stack([xb, yb, top], -1),
                                     np.stack([xb, yb, base], -1), np.stack([xa, ya, base], -1)],
                                    -2).reshape(-1, 4, 3))
            values.append(self.v[:, jj, ii].ravel())

        corners += [face(0), face(nl)]
        values += [self.v[0].ravel(), self.v[-1].ravel()]
        rows, cols = np.arange(ny), np.arange(nx)
        side(xs[0], ys[rows], xs[0], ys[rows + 1], rows, np.zeros(ny, int))
        side(xs[-1], ys[rows], xs[-1], ys[rows + 1], rows, np.full(ny, nx - 1))
        side(xs[cols], ys[0], xs[cols + 1], ys[0], np.zeros(nx, int), cols)
        side(xs[cols], ys[-1], xs[cols + 1], ys[-1], np.full(nx, ny - 1), cols)
        return _quads(np.concatenate(corners), np.concatenate(values))

    def pins(self, domain, columns, active=None):
        """The columns as the arrow in 3D (the PO: "the arrow will surely
        be 3D"): `columns` = [(name, x, y, law)], placed and valid.
        `lines`: one segment per interval, its `velocity`, and below the
        last point a cone — the last interval carried on; `points`: a
        vertex at the start and at every point entered (`kind` 0 / 1);
        `halo`: the segments of column `active`; `labels`: [(name, x, y,
        z)] for a billboard each, a cone's height above the zero (at it,
        the top face of the velocity model shown with them hides it)."""
        span = max(self.x1 - self.x0, self.y1 - self.y0, 1.0)
        r = 0.012 * span                                  # the cone's radius
        length = 0.06 * abs(self.bottom(domain)) or 1.0   # the cone's height
        lp, ll, lv, pp, pk, hp, hl, labels = [], [], [], [], [], [], [], []
        polys, pv = [], []
        for ci, (name, x, y, law) in enumerate(columns):
            rows = law.rows()
            vel = law.velocities()
            zs = [-(t if domain == TIME else z) for z, t in rows]
            base = len(lp)
            lp += [(x, y, zc) for zc in zs]
            for k in range(len(zs) - 1):
                ll.append((base + k, base + k + 1))
                lv.append(vel[k])
            # the arrow head: the last interval carried on below the last point
            apex = len(lp)
            lp.append((x, y, zs[-1] - length))
            ring = len(lp)
            for q in range(12):
                a = 2.0 * np.pi * q / 12.0
                lp.append((x + r * np.cos(a), y + r * np.sin(a), zs[-1]))
            for q in range(12):
                polys.append((apex, ring + q, ring + (q + 1) % 12))
                pv.append(vel[-1])
            pp += [(x, y, zc) for zc in zs]
            pk += [0] + [1] * (len(zs) - 1)
            if active is not None and ci == active:
                hbase = len(hp)
                hp += [(x, y, zc) for zc in zs]
                hl += [(hbase + k, hbase + k + 1) for k in range(len(zs) - 1)]
            labels.append((name, float(x), float(y), float(length)))
        return {
            "lines": _polydata(lp, lines=ll, polys=polys, arrays={"velocity": lv + pv}) if lp else None,
            "points": _polydata(pp, verts=[(q,) for q in range(len(pp))], arrays={"kind": pk}) if pp else None,
            "halo": _polydata(hp, lines=hl) if hl else None,
            "labels": labels,
        }
