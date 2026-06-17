"""Plane slice for a representation, with an optional interactive
ParaView-style implicit-plane widget.

Data model
----------
Canonical state per slice:
  - `_origin: [3]` — any point on the plane
  - `_normal: [3]` — plane normal (not necessarily unit-length but
    always non-zero once the slice is enabled)
  - `_axis: 'X'|'Y'|'Z'` — UI affordance for the panel; tracks the
    cardinal axis closest to the current normal. Set via the panel's
    axis-toggle buttons (snaps normal to that axis).

The widget visibility is gated by `state.ui_plane_edit_mode == 'slice'`
— Slice and Clip share a single edit channel so only one widget is
on-screen at a time, even when both filters are applied.

Pipeline: `pvsimple.Slice` with `SliceType=Plane`, Input = rep's
canonical source.
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
# Tolerance for snapping a widget-edited normal back to a cardinal
# axis: dot-product with the cardinal direction ≥ this value (cos 5°).
_AXIS_SNAP_COS = math.cos(math.radians(5.0))


def _normal_to_axis(normal):
    """Return 'X'/'Y'/'Z' if `normal` lies within 5° of a cardinal
    axis (either direction), else None."""
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


class SlicePlane:
    """One axis-snapped (but freely orientable) plane slice over a
    representation source.

    View-aware via the optional `view_pv` / `view_id` constructor
    args:
      - `view_pv` (the PV view this slice should render into) drives
        every `Show` / `Hide` / display lookup. When None, falls back
        to `pvsimple.GetActiveView()` — backward compat for callers
        that don't yet thread the view through.
      - `view_id` (the trame panel id) makes the slice proxy's
        registration name unique per (rep, view). Without this, two
        SlicePlane instances for the same rep in different views
        would collide on the PV registry name and reuse the same
        proxy."""

    __slots__ = (
        "_rep_path", "_upstream", "_state",
        "_view_id", "_view_pv",
        "_enabled", "_axis", "_origin", "_normal",
        "_proxy", "_bounds", "_widget",
    )

    def __init__(self, rep_path: str, upstream, state,
                 view_id: str | None = None, view_pv=None):
        self._rep_path = rep_path
        self._upstream = upstream
        self._state = state
        self._view_id = view_id
        self._view_pv = view_pv
        self._enabled = False
        self._axis = "X"
        self._origin: list = [0.0, 0.0, 0.0]
        self._normal: list = list(_AXIS_NORMAL["X"])
        self._proxy = None
        self._bounds: tuple | None = None
        widget_suffix = (
            f"slice_{view_id}_{rep_path}" if view_id else f"slice_{rep_path}"
        )
        self._widget = PlaneWidget(
            id_suffix=widget_suffix,
            bounds_provider=self._ensure_bounds,
            on_end_interact=self._on_widget_interact,
        )

    def _resolve_view(self):
        """Return the view to Show/Hide on. Captured view wins; falls
        back to active view when the caller didn't provide one."""
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
        """The Slice filter proxy — exposed for callers that need to
        treat the slice's output as a visible source (e.g. the stats
        dispatcher, which has to include slice / clip outputs in the
        per-view rendered sources list because they replace the
        upstream rep on Visibility)."""
        return self._proxy

    def to_dict(self) -> dict:
        bx0, bx1, by0, by1, bz0, bz1 = self._ensure_bounds()
        return {
            "enabled": self._enabled,
            "axis": self._axis,
            "offset": self.offset,
            "bounds": [bx0, bx1, by0, by1, bz0, bz1],
        }

    def set(self, enabled=None, axis=None, offset=None,
            origin=None, normal=None):
        """Patch any subset of state and refresh PV pipeline + widget."""
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
    # Geometry helpers

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
    # PV Slice proxy

    def _ensure_proxy(self):
        if self._proxy is not None:
            return
        # Include view_id in the registration name so per-(rep, view)
        # SlicePlanes don't collide on PV's proxy registry. Falls back
        # to the legacy name when no view is bound.
        if self._view_id:
            name = f"slice_{self._view_id}_{_sanitize(self._rep_path)}"
        else:
            name = f"slice_{_sanitize(self._rep_path)}"
        try:
            self._proxy = pvsimple.Slice(
                Input=self._upstream,
                SliceType="Plane",
                registrationName=name,
            )
        except Exception as exc:
            print(f"[WARNING] SlicePlane create {self._rep_path}: {exc}")
            return
        # Bright red tint so the cross-section stands out against the
        # rep beneath (without an explicit tint the slice picks up the
        # rep's grey + z-fights — visually invisible).
        view = self._resolve_view()
        if view is not None:
            try:
                disp = pvsimple.GetRepresentation(proxy=self._proxy, view=view)
                if disp is not None:
                    disp.Representation = "Surface"
                    disp.DiffuseColor = [1.0, 0.15, 0.15]
                    disp.AmbientColor = [1.0, 0.15, 0.15]
                    disp.LineWidth = 2.0
                    try:
                        disp.EdgeColor = [1.0, 0.6, 0.6]
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
            self._proxy.SliceType.Origin = list(self._origin)
            self._proxy.SliceType.Normal = list(self._normal)
            self._proxy.UpdatePipeline()
        except Exception as exc:
            print(f"[WARNING] SlicePlane apply {self._rep_path}: {exc}")
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
        # Widget gated on edit mode: only this slice's widget is shown
        # when the user picked "edit slice"; otherwise the clip's
        # widget (or neither) is visible.
        edit_mode = getattr(self._state, "ui_plane_edit_mode", None)
        if edit_mode == "slice":
            self._widget.ensure(view)
            self._widget.sync(self._origin, self._normal)
        else:
            self._widget.destroy()

    def _on_widget_interact(self, origin, normal):
        """End-of-drag callback from PlaneWidget."""
        self._origin = list(origin)
        self._normal = list(normal)
        snapped = _normal_to_axis(self._normal)
        if snapped is not None:
            self._axis = snapped
        try:
            self._proxy.SliceType.Origin = list(self._origin)
            self._proxy.SliceType.Normal = list(self._normal)
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
        """Mirror current state onto the `ui_slice_*` trame vars."""
        st = self._state
        bx0, bx1, by0, by1, bz0, bz1 = self._ensure_bounds()
        i = _AXIS_INDEX[self._axis]
        lo = (bx0, by0, bz0)[i]
        hi = (bx1, by1, bz1)[i]
        try:
            st.ui_slice_axis = self._axis
            st.ui_slice_offset = float(self._origin[i])
            st.ui_slice_bounds = [bx0, bx1, by0, by1, bz0, bz1]
            st.ui_slice_offset_min = float(lo)
            st.ui_slice_offset_max = float(hi)
            st.ui_slice_offset_step = (
                (hi - lo) / 1000.0 if hi > lo else 0.001
            )
        except Exception:
            pass
