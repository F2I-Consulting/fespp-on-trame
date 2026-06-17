"""Plane clip for a representation — analog of `SlicePlane`.

A Clip filter cuts the volume in half along a plane and keeps one
side (the side is flipped by `InsideOut`). Output is volumetric, not
2D, so it inherits the rep's coloring (ColorBy, LookupTable, Diffuse
/ Ambient, Opacity) — the user sees the rep "with one half removed",
same coloring as before.

Data model mirrors `SlicePlane` (origin + normal + derived axis) so
the panel and widget UX is identical. Extra state: `_inside_out`.

Pipeline: `pvsimple.Clip(ClipType='Plane', Crinkleclip=0)`. Input is
the rep's canonical source.

Widget visibility is gated by `state.ui_plane_edit_mode == 'clip'`
— Slice and Clip share a single edit channel so only one widget is
on-screen at a time, even when both filters are applied.
"""
import math

from paraview import simple as pvsimple

from fespp_on_trame.app.core.sources.representation import _sanitize
from fespp_on_trame.app.core.sources.plane_widget import PlaneWidget


_AXIS_NORMAL = {
    "X": [1.0, 0.0, 0.0],
    "Y": [0.0, 1.0, 0.0],
    "Z": [0.0, 0.0, 1.0],
}
_AXIS_INDEX = {"X": 0, "Y": 1, "Z": 2}
_AXIS_SNAP_COS = math.cos(math.radians(5.0))


def _normal_to_axis(normal):
    if not normal:
        return None
    nx, ny, nz = float(normal[0]), float(normal[1]), float(normal[2])
    length = math.sqrt(nx * nx + ny * ny + nz * nz)
    if length < 1e-9:
        return None
    nx, ny, nz = nx / length, ny / length, nz / length
    best_axis, best_dot = None, 0.0
    for axis, comp in (("X", abs(nx)), ("Y", abs(ny)), ("Z", abs(nz))):
        if comp > best_dot:
            best_axis, best_dot = axis, comp
    return best_axis if best_dot >= _AXIS_SNAP_COS else None


class ClipPlane:
    """Single plane clip over a representation source."""

    __slots__ = (
        "_rep_path", "_upstream", "_state",
        "_view_id", "_view_pv",
        "_enabled", "_axis", "_origin", "_normal", "_inside_out",
        "_proxy", "_bounds", "_widget",
    )

    def __init__(self, rep_path: str, upstream, state,
                 view_id: str | None = None, view_pv=None):
        """`view_id` / `view_pv` make this clip per-(rep, view):
          - `view_pv` is the PV view to Show/Hide on; falls back to
            `GetActiveView()` when None (backward compat).
          - `view_id` is mixed into the proxy registration name so two
            clips on the same rep but different views don't collide
            on the PV proxy registry."""
        self._rep_path = rep_path
        self._upstream = upstream
        self._state = state
        self._view_id = view_id
        self._view_pv = view_pv
        self._enabled = False
        self._axis = "X"
        self._origin: list = [0.0, 0.0, 0.0]
        self._normal: list = list(_AXIS_NORMAL["X"])
        self._inside_out = False
        self._proxy = None
        self._bounds: tuple | None = None
        widget_suffix = (
            f"clip_{view_id}_{rep_path}" if view_id else f"clip_{rep_path}"
        )
        self._widget = PlaneWidget(
            id_suffix=widget_suffix,
            bounds_provider=self._ensure_bounds,
            on_end_interact=self._on_widget_interact,
        )

    def _resolve_view(self):
        """The PV view this clip targets. Captured view wins; falls
        back to active view for backward-compat callers."""
        if self._view_pv is not None:
            return self._view_pv
        return pvsimple.GetActiveView()

    # ------------------------------------------------------------------
    # Public API

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def offset(self) -> float:
        return float(self._origin[_AXIS_INDEX[self._axis]])

    @property
    def output(self):
        """The Clip filter proxy — used by the rep's visibility
        resolver to Show this in place of the rep source."""
        return self._proxy

    def to_dict(self) -> dict:
        bx0, bx1, by0, by1, bz0, bz1 = self._ensure_bounds()
        return {
            "enabled": self._enabled,
            "axis": self._axis,
            "offset": self.offset,
            "inside_out": self._inside_out,
            "bounds": [bx0, bx1, by0, by1, bz0, bz1],
        }

    def set(self, enabled=None, axis=None, offset=None,
            origin=None, normal=None, inside_out=None):
        self._ensure_bounds()

        if axis is not None and axis in _AXIS_NORMAL:
            self._axis = axis
            self._normal = list(_AXIS_NORMAL[axis])
            if offset is None and origin is None:
                self._origin = self._bbox_centre_with_offset(
                    axis, self._axis_midpoint(axis),
                )
        if offset is not None:
            self._origin = self._bbox_centre_with_offset(
                self._axis, float(offset),
            )
        if origin is not None:
            self._origin = [float(v) for v in origin]
        if normal is not None:
            self._normal = [float(v) for v in normal]
            snapped = _normal_to_axis(self._normal)
            if snapped is not None:
                self._axis = snapped
        if inside_out is not None:
            self._inside_out = bool(inside_out)
        if enabled is not None:
            self._enabled = bool(enabled)
        self._apply()

    def delete(self):
        self._widget.destroy()
        if self._proxy is None:
            return
        view = self._resolve_view()
        try:
            if view is not None:
                pvsimple.Hide(proxy=self._proxy, view=view)
        except Exception:
            pass
        try:
            pvsimple.Delete(self._proxy)
        except Exception:
            pass
        self._proxy = None

    # ------------------------------------------------------------------
    # Geometry helpers (identical to SlicePlane — could be shared
    # via a mixin, but keeping each filter class self-contained makes
    # them easier to read in isolation).

    def _ensure_bounds(self):
        if self._bounds is not None:
            return self._bounds
        try:
            info = self._upstream.GetDataInformation()
            b = info.GetBounds()
            self._bounds = (
                float(b[0]), float(b[1]),
                float(b[2]), float(b[3]),
                float(b[4]), float(b[5]),
            )
        except Exception:
            self._bounds = (0.0, 1.0, 0.0, 1.0, 0.0, 1.0)
        bx0, bx1, by0, by1, bz0, bz1 = self._bounds
        self._origin = [
            (bx0 + bx1) * 0.5,
            (by0 + by1) * 0.5,
            (bz0 + bz1) * 0.5,
        ]
        return self._bounds

    def _axis_midpoint(self, axis: str) -> float:
        b = self._ensure_bounds()
        i = _AXIS_INDEX[axis]
        return (b[2 * i] + b[2 * i + 1]) * 0.5

    def _bbox_centre_with_offset(self, axis: str, offset: float):
        bx0, bx1, by0, by1, bz0, bz1 = self._ensure_bounds()
        cx = (bx0 + bx1) * 0.5
        cy = (by0 + by1) * 0.5
        cz = (bz0 + bz1) * 0.5
        if axis == "X":
            return [float(offset), cy, cz]
        if axis == "Y":
            return [cx, float(offset), cz]
        return [cx, cy, float(offset)]

    # ------------------------------------------------------------------
    # PV Clip proxy

    def _ensure_proxy(self):
        if self._proxy is not None:
            return
        if self._view_id:
            name = f"clip_{self._view_id}_{_sanitize(self._rep_path)}"
        else:
            name = f"clip_{_sanitize(self._rep_path)}"
        try:
            self._proxy = pvsimple.Clip(
                Input=self._upstream,
                ClipType="Plane",
                registrationName=name,
            )
            # Crinkleclip=0 gives smooth-cut output; 1 keeps original
            # cells that intersect the plane (ragged edge). Smooth is
            # the natural default for "look inside".
            try:
                self._proxy.Crinkleclip = 0
            except Exception:
                pass
        except Exception as exc:
            return
        # Inherit display props from the upstream source so the
        # clipped half looks like the rep (same coloring, same
        # representation type). Copied once on creation — if the user
        # changes the rep's coloring later, they can toggle clip
        # off/on to refresh.
        view = self._resolve_view()
        if view is not None:
            try:
                src_disp = pvsimple.GetDisplayProperties(self._upstream, view=view)
                clip_disp = pvsimple.GetRepresentation(proxy=self._proxy, view=view)
                if src_disp is not None and clip_disp is not None:
                    for attr in (
                        "Representation", "Scale", "ColorArrayName",
                        "LookupTable", "DiffuseColor", "AmbientColor",
                        "Opacity",
                    ):
                        try:
                            val = getattr(src_disp, attr)
                            if attr in ("Scale", "ColorArrayName",
                                        "DiffuseColor", "AmbientColor"):
                                val = list(val)
                            setattr(clip_disp, attr, val)
                        except Exception:
                            pass
            except Exception:
                pass

    def _apply(self):
        if not self._enabled:
            self._widget.destroy()
            if self._proxy is None:
                return
            view = self._resolve_view()
            try:
                if view is not None:
                    pvsimple.Hide(proxy=self._proxy, view=view)
            except Exception:
                pass
            return
        self._ensure_proxy()
        if self._proxy is None:
            return
        try:
            self._proxy.ClipType.Origin = list(self._origin)
            self._proxy.ClipType.Normal = list(self._normal)
            # PV6 renamed the old `InsideOut` int property to `Invert`
            # (bool). Try the new name first, fall back to the legacy
            # name for older PV builds.
            try:
                self._proxy.Invert = 1 if self._inside_out else 0
            except Exception:
                try:
                    self._proxy.InsideOut = 1 if self._inside_out else 0
                except Exception:
                    pass
            self._proxy.UpdatePipeline()
        except Exception as exc:
            return
        view = self._resolve_view()
        if view is None:
            return
        try:
            pvsimple.Show(proxy=self._proxy, view=view)
            disp = pvsimple.GetDisplayProperties(self._proxy, view=view)
            if disp is not None:
                disp.Visibility = 1
                sm = getattr(disp, "SMProxy", None)
                if sm is not None:
                    sm.UpdateVTKObjects()
        except Exception:
            pass
        edit_mode = getattr(self._state, "ui_plane_edit_mode", None)
        if edit_mode == "clip":
            self._widget.ensure(view)
            self._widget.sync(self._origin, self._normal)
        else:
            self._widget.destroy()

    def _on_widget_interact(self, origin, normal):
        self._origin = list(origin)
        self._normal = list(normal)
        snapped = _normal_to_axis(self._normal)
        if snapped is not None:
            self._axis = snapped
        try:
            self._proxy.ClipType.Origin = list(self._origin)
            self._proxy.ClipType.Normal = list(self._normal)
            self._proxy.UpdatePipeline()
        except Exception:
            pass
        self._publish_state_vars()
        view = self._widget.view or pvsimple.GetActiveView()
        if view is not None:
            try:
                pvsimple.Render(view=view)
            except Exception:
                pass

    def _publish_state_vars(self):
        st = self._state
        bx0, bx1, by0, by1, bz0, bz1 = self._ensure_bounds()
        i = _AXIS_INDEX[self._axis]
        lo = (bx0, by0, bz0)[i]
        hi = (bx1, by1, bz1)[i]
        try:
            st.ui_clip_axis = self._axis
            st.ui_clip_offset = float(self._origin[i])
            st.ui_clip_bounds = [bx0, bx1, by0, by1, bz0, bz1]
            st.ui_clip_offset_min = float(lo)
            st.ui_clip_offset_max = float(hi)
            st.ui_clip_offset_step = (
                (hi - lo) / 1000.0 if hi > lo else 0.001
            )
            st.ui_clip_inside_out = bool(self._inside_out)
        except Exception:
            pass
