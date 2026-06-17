"""ParaView ImplicitPlaneWidgetRepresentation wrapper.

Shared by `SlicePlane` and `ClipPlane` — both filters edit a Plane
proxy (Slice's `SliceType` / Clip's `ClipType`) with the same UX
(drag the sphere to move origin, drag the arrow to rotate normal).

Lifecycle
---------
- `ensure(view)` creates the widget proxy on first call, registers
  it in the view's `HiddenRepresentations`, places it on the
  current bounds, enables interaction, and installs an end-of-drag
  observer.
- `sync(origin, normal)` pushes external state onto the widget
  (panel-driven moves; the widget handles follow).
- `destroy()` tears the widget down — called when the owning filter
  is disabled or when the rep releases.

Only one widget per rep is needed in practice (Slice + Clip can't be
edited simultaneously), but each filter creates its own instance and
the edit-mode logic upstream decides which one calls `ensure(...)`.
"""
from paraview import simple as pvsimple  # noqa: F401 — kept for symmetry with callers

from fespp_on_trame.app.core.sources.representation import _sanitize


def _set_prop_scalar(proxy, name, value):
    """Set a 1-element SM property (PlaceFactor, Enabled, Visibility,
    …). The raw vtkSMProxy returned by `pxm.NewProxy` doesn't expose
    Python attribute access for properties, so we go through
    `GetProperty(name).SetElement(0, value)`."""
    try:
        prop = proxy.GetProperty(name)
        if prop is None:
            return
        prop.SetElement(0, value)
    except Exception:
        pass


def _set_prop_vec(proxy, name, values):
    try:
        prop = proxy.GetProperty(name)
        if prop is None:
            return
        for i, v in enumerate(values):
            prop.SetElement(i, float(v))
    except Exception:
        pass


def _get_prop_vec(proxy, name, n):
    try:
        prop = proxy.GetProperty(name)
        if prop is None:
            return None
        return [float(prop.GetElement(i)) for i in range(n)]
    except Exception:
        return None


class PlaneWidget:
    """One ImplicitPlaneWidgetRepresentation bound to a single
    end-user callback. The owner (SlicePlane / ClipPlane) supplies
    the bounds for placement and a callback to invoke when the user
    finishes a drag."""

    __slots__ = (
        "_id_suffix", "_bounds_provider", "_on_end_interact",
        "_proxy", "_view", "_reg_name", "_obs_tag",
    )

    def __init__(self, id_suffix: str, bounds_provider, on_end_interact):
        # id_suffix: stable string for PV registration ("slice"/"clip"
        # combined with the rep path) so we can re-find / unregister.
        # bounds_provider: callable () -> 6-tuple, used for PlaceWidget.
        # on_end_interact: callable (origin: list[3], normal: list[3]).
        self._id_suffix = id_suffix
        self._bounds_provider = bounds_provider
        self._on_end_interact = on_end_interact
        self._proxy = None
        self._view = None
        self._reg_name = None
        self._obs_tag = None

    # ------------------------------------------------------------------
    # Public

    @property
    def proxy(self):
        return self._proxy

    @property
    def view(self):
        return self._view

    def ensure(self, view):
        """Make sure a widget exists in `view`. If a widget was attached
        to a different view, it's torn down first so we never end up
        with stale instances accumulating across active-view switches."""
        if view is None:
            return
        if self._proxy is not None and self._view is view:
            return
        if self._proxy is not None:
            self.destroy()

        try:
            from paraview.servermanager import ProxyManager
            pxm = ProxyManager()
            widget = pxm.NewProxy(
                "representations", "ImplicitPlaneWidgetRepresentation",
            )
        except Exception as exc:
            return
        if widget is None:
            return

        reg_name = f"plane_widget_{_sanitize(self._id_suffix)}"
        try:
            pxm.RegisterProxy("widgets", reg_name, widget)
        except Exception:
            pass
        self._reg_name = reg_name
        self._proxy = widget

        _set_prop_scalar(widget, "PlaceFactor", 1.05)

        # PlaceWidget on vtk3DWidgetRepresentation takes a single 6-tuple.
        b = self._bounds_provider()
        try:
            cs = widget.GetClientSideObject()
            if cs is not None and hasattr(cs, "PlaceWidget"):
                cs.PlaceWidget([b[0], b[1], b[2], b[3], b[4], b[5]])
        except Exception as exc:
            pass

        # Attach to the view's hidden reps so the interactor sees it.
        try:
            hidden = view.SMProxy.GetProperty("HiddenRepresentations")
            if hidden is not None:
                hidden.AddProxy(widget)
                view.SMProxy.UpdateVTKObjects()
        except Exception as exc:
            pass

        _set_prop_scalar(widget, "Enabled", 1)
        _set_prop_scalar(widget, "Visibility", 1)
        try:
            widget.UpdateVTKObjects()
        except Exception:
            pass

        # End-of-drag observer.
        def _on_end(obj, evt):
            o = _get_prop_vec(widget, "Origin", 3)
            n = _get_prop_vec(widget, "Normal", 3)
            if o is None or n is None:
                return
            self._on_end_interact(o, n)

        try:
            self._obs_tag = widget.AddObserver("EndInteractionEvent", _on_end)
        except Exception as exc:
            pass
        self._view = view

    def sync(self, origin, normal):
        """Push external state (panel-driven edits) onto the widget so
        its handles follow."""
        widget = self._proxy
        if widget is None:
            return
        _set_prop_vec(widget, "Origin", origin)
        _set_prop_vec(widget, "Normal", normal)
        try:
            widget.UpdateVTKObjects()
        except Exception:
            pass

    def destroy(self):
        widget = self._proxy
        view = self._view
        reg_name = self._reg_name
        obs_tag = self._obs_tag
        self._proxy = None
        self._view = None
        self._reg_name = None
        self._obs_tag = None
        if widget is None:
            return
        if obs_tag is not None:
            try:
                widget.RemoveObserver(obs_tag)
            except Exception:
                pass
        _set_prop_scalar(widget, "Visibility", 0)
        _set_prop_scalar(widget, "Enabled", 0)
        try:
            widget.UpdateVTKObjects()
        except Exception:
            pass
        try:
            if view is not None:
                hidden = view.SMProxy.GetProperty("HiddenRepresentations")
                if hidden is not None:
                    hidden.RemoveProxy(widget)
                    view.SMProxy.UpdateVTKObjects()
        except Exception:
            pass
        try:
            from paraview.servermanager import ProxyManager
            ProxyManager().UnRegisterProxy("widgets", reg_name or "", widget)
        except Exception:
            pass
