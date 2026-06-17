"""Scope-aware camera orientation editor.

Renders the "Orientation" section of the GlobalSettingsDialog. The
target view always shows exactly one of the two orientation aids:

  - **Camera Orientation Widget** (the interactive 3D gizmo)
  - **Orientation Axes** (the small XYZ marker)

Toggling one off implies turning the other on, hence a 2-option
VBtnToggle in the UI. Per-scope: scope=="global" applies to every
render view, scope=="<panel_id>" applies only to that view.

View properties driven here:
  - `view.Visible = 1 | 0` toggles the Camera Orientation Widget
  - `view.Location = 'Bottom Left'` positions the Camera Orientation
    Widget (kept consistent across all render views)
  - `view.OrientationAxesVisibility = 1 | 0` toggles the XYZ marker

The orientation-widget property names differ across ParaView
versions, so writes go through `_safe_set` (a misnamed property
degrades to a no-op instead of crashing the dialog).
"""
from paraview import simple as pvsimple
from trame.app import get_server
from trame.widgets import html, vuetify3


def _safe_set(view, name, value):
    """setattr that swallows errors, so an unknown / renamed property
    degrades to a no-op. The camera-orientation-widget property names
    differ across ParaView versions."""
    try:
        setattr(view, name, value)
    except Exception:
        pass


class OrientationEditor:
    SCOPE_GLOBAL = "global"
    MODE_CAMERA_WIDGET = "camera_widget"
    MODE_AXES = "axes"

    _WIDGET_DEFAULT_LOCATION = "Bottom Left"

    def __init__(self, scope_var: str = "settings_scope", mode_var: str = "orientation_mode"):
        self.scope_var = scope_var
        # Per-instance mode state var: the global and per-view dialogs
        # MUST use different names, else both react to the same
        # state.change and the global one broadcasts to every view
        # whenever the per-view toggle is touched.
        self.mode_var = mode_var
        self._server = get_server()
        self._state = self._server.state
        self._controller = self._server.controller
        # Re-entrancy guard for the read-back-on-scope-change path.
        self._syncing = False

        # Default matches the engine-seeded initial RenderView.
        self._state.setdefault(mode_var, self.MODE_CAMERA_WIDGET)

        self._state.change(scope_var)(self._on_scope_change)
        self._state.change(mode_var)(self._on_mode_change)

    # ----- helpers -----

    def _current_scope(self):
        return getattr(self._state, self.scope_var, self.SCOPE_GLOBAL) or self.SCOPE_GLOBAL

    def _multi_view(self):
        return getattr(self._server.context, "multi_view", None)

    def _target_views(self):
        """Yield the render views the orientation mode should be
        applied to. Diff panels are excluded — they don't get
        orientation widget toggling from this editor."""
        scope = self._current_scope()
        mv = self._multi_view()
        if mv is None:
            v = pvsimple.GetActiveView()
            if v is not None:
                yield None, v
            return
        kinds = getattr(mv, "_panel_kinds", {}) or {}
        if scope == self.SCOPE_GLOBAL:
            for pid, view in mv.panel_pv_views().items():
                if kinds.get(pid, "render") != "render":
                    continue
                yield pid, view
        else:
            view = mv.get_pv_view(scope) if hasattr(mv, "get_pv_view") else None
            if view is not None:
                yield scope, view

    def _read_mode(self, view):
        """Best-effort read of the current orientation mode on a view.
        Camera widget visible takes precedence; fall back to axes."""
        try:
            if int(getattr(view, "Visible", 0)):
                return self.MODE_CAMERA_WIDGET
        except Exception:
            pass
        try:
            if int(getattr(view, "OrientationAxesVisibility", 0)):
                return self.MODE_AXES
        except Exception:
            pass
        return self.MODE_CAMERA_WIDGET

    def _apply_mode(self, view, mode):
        """Apply the orientation mode to a single view: one
        visibility on, the other off (mutually exclusive)."""
        if mode == self.MODE_CAMERA_WIDGET:
            _safe_set(view, "Visible", 1)
            _safe_set(view, "Location", self._WIDGET_DEFAULT_LOCATION)
            _safe_set(view, "OrientationAxesVisibility", 0)
        else:  # MODE_AXES
            _safe_set(view, "Visible", 0)
            _safe_set(view, "OrientationAxesVisibility", 1)
        try:
            view.SMProxy.UpdateVTKObjects()
        except Exception:
            pass

    def _render_and_push(self, panel_id=None):
        """Render every targeted view and push the fresh frame to
        the matching client(s). When scope is global, broadcast to
        all panels; when scope is a single panel, push only to that
        panel's html view."""
        mv = self._multi_view()
        scope = self._current_scope()
        if mv is None:
            try:
                pvsimple.Render()
            except Exception:
                pass
            try:
                self._controller.view_update()
            except Exception:
                pass
            return
        if scope == self.SCOPE_GLOBAL:
            for pid, view in self._target_views():
                try:
                    pvsimple.Render(view=view)
                except Exception:
                    pass
            update_all = getattr(self._controller, "view_update_all", None)
            if update_all is not None:
                try:
                    update_all()
                except Exception:
                    pass
            else:
                try:
                    self._controller.view_update()
                except Exception:
                    pass
        else:
            view = mv.get_pv_view(scope) if hasattr(mv, "get_pv_view") else None
            if view is not None:
                try:
                    pvsimple.Render(view=view)
                except Exception:
                    pass
            html_v = mv.get_html_view(scope) if hasattr(mv, "get_html_view") else None
            if html_v is not None:
                try:
                    html_v.update()
                except Exception:
                    pass

    # ----- handlers -----

    def _on_scope_change(self, **_):
        """Pre-fill orientation_mode from the new scope's view (or
        the first render view in global scope, which represents the
        rest since a previous global write kept them in sync)."""
        view = None
        for _pid, v in self._target_views():
            view = v
            break
        if view is None:
            return
        self._syncing = True
        try:
            setattr(self._state, self.mode_var, self._read_mode(view))
        finally:
            self._syncing = False

    def _on_mode_change(self, **_):
        if self._syncing:
            return
        mode = getattr(self._state, self.mode_var, self.MODE_CAMERA_WIDGET)
        for _pid, view in self._target_views():
            self._apply_mode(view, mode)
        self._render_and_push()

    # ----- render -----

    def render(self):
        """Emit the Orientation section. Must be called inside an
        open Trame layout context (typically a VCardText). The two
        aids are mutually exclusive, hence a single two-option
        toggle."""
        html.Div(
            "Orientation",
            classes="text-caption text-uppercase font-weight-bold mb-2",
        )
        with vuetify3.VBtnToggle(
            v_model=(self.mode_var, self.MODE_CAMERA_WIDGET),
            mandatory=True,
            density="comfortable",
            color="blue",
            divided=True,
            classes="mb-2 w-100",
        ):
            vuetify3.VBtn(
                "Camera Orientation Widget",
                value=self.MODE_CAMERA_WIDGET,
                size="small",
                prepend_icon="mdi-axis-arrow",
            )
            vuetify3.VBtn(
                "Orientation Axes",
                value=self.MODE_AXES,
                size="small",
                prepend_icon="mdi-axis",
            )
