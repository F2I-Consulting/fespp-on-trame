"""Pick, under a ray from the pointer, the things that have no width.

The show-position readout casts a ray from the pixel under the pointer and
meets the drawn blocks with their cell locators (see boot.cursor_hit). A
surface or a cell has an area the ray can cross; a TRAJECTORY is drawn as
lines and a set of points as vertices, and a ray practically never meets
those within the locator's tolerance (0.1 mm). Here they are met within
:data:`PICK_PX` pixels of the pointer, measured at their own depth, since a
pixel is wider far away, and as they are DRAWN: under a Z exaggeration the
data's own distances are not the screen's (at Z x 25, five pixels sideways
are 125 up and down in the data's space).

All segments are tested at once with numpy: a trajectory is a few hundred
segments, a dataset of them a few thousand. The closest points between the
ray and a segment follow Ericson, Real-Time Collision Detection, 5.1.9."""
import numpy as np

#: How close, in pixels, the pointer must come to a line or a point for the
#: readout to name it.
PICK_PX = 5


def near_lines(ds, p1, u, px, pick_px=PICK_PX, scale=None):
    """Find the line or vertex of polydata `ds` the ray passes nearest.

    The ray is ``p1 + s·u`` with s in [0, 1]; `px` is ``(dn, dd)``: a pixel
    at s is ``|dn + s·dd|`` wide, the gap to the ray through the next pixel.
    All in the space of `ds`; `scale` is the (x, y, z) scale `ds` is drawn
    with: the distances are measured as drawn, and s is the same in both.
    Returns ``(s, point, cell id)`` of the hit within `pick_px` pixels, or
    None when nothing is that close or `ds` holds neither lines nor
    vertices. With several within reach, the nearest to the eye (smallest
    s) wins. The point is in the space of `ds`; the cell id is the
    polydata's own: its vertices first, then its lines."""
    if ds is None or not ds.IsA("vtkPolyData"):
        return None
    n_verts = ds.GetNumberOfVerts()
    n_lines = ds.GetNumberOfLines()
    if not (n_verts or n_lines) or ds.GetPoints() is None:
        return None
    from vtkmodules.util.numpy_support import vtk_to_numpy
    S = np.asarray(scale if scale is not None else (1.0, 1.0, 1.0), float)
    pts = vtk_to_numpy(ds.GetPoints().GetData()).astype(float) * S
    P1, U = np.asarray(p1, float) * S, np.asarray(u, float) * S
    DN, DD = np.asarray(px[0], float) * S, np.asarray(px[1], float) * S
    a = float(U @ U)
    if a <= 0.0:
        return None

    def reach(s):
        return pick_px * np.linalg.norm(DN[None, :] + np.asarray(s)[:, None] * DD[None, :], axis=1)

    def cells(arr):
        return (vtk_to_numpy(arr.GetConnectivityArray()).astype(np.int64),
                vtk_to_numpy(arr.GetOffsetsArray()).astype(np.int64))

    found = []          # (s, point, cell) of each kind's best
    if n_lines:
        conn, offs = cells(ds.GetLines())
        # segment k joins conn[k] and conn[k + 1] when both are in one line
        seg = np.arange(max(0, len(conn) - 1))
        cell_of = np.searchsorted(offs, seg, side="right") - 1
        keep = (seg + 1) < offs[cell_of + 1]
        seg, cell_of = seg[keep], cell_of[keep]
        if len(seg):
            A, B = pts[conn[seg]], pts[conn[seg + 1]]
            D2 = B - A
            R = P1 - A
            e = np.einsum("ij,ij->i", D2, D2)
            f = np.einsum("ij,ij->i", D2, R)
            b = D2 @ U
            c = R @ U
            denom = a * e - b * b
            with np.errstate(divide="ignore", invalid="ignore"):
                s = np.clip(np.where(denom > 1e-30, (b * f - c * e) / denom, 0.0), 0.0, 1.0)
                t = np.where(e > 1e-30, (b * s + f) / e, 0.0)
                s = np.where(t < 0.0, np.clip(-c / a, 0.0, 1.0), s)
                s = np.where(t > 1.0, np.clip((b - c) / a, 0.0, 1.0), s)
                t = np.clip(t, 0.0, 1.0)
            C2 = A + t[:, None] * D2
            dist = np.linalg.norm(P1 + s[:, None] * U - C2, axis=1)
            ok = np.nonzero(dist <= reach(s))[0]
            if len(ok):
                k = ok[np.argmin(s[ok])]
                found.append((float(s[k]), [float(v) for v in C2[k] / S], int(n_verts + cell_of[k])))
    if n_verts:
        conn, offs = cells(ds.GetVerts())
        Q = pts[conn]
        s = np.clip(((Q - P1) @ U) / a, 0.0, 1.0)
        dist = np.linalg.norm(P1 + s[:, None] * U - Q, axis=1)
        ok = np.nonzero(dist <= reach(s))[0]
        if len(ok):
            k = ok[np.argmin(s[ok])]
            cell = int(np.searchsorted(offs, k, side="right") - 1)
            found.append((float(s[k]), [float(v) for v in Q[k] / S], cell))
    return min(found, key=lambda h: h[0]) if found else None
