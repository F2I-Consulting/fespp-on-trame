"""Scope-aware Transformation section (Z scale) used by both the
global and per-view settings dialogs.

Reads its scope dynamically from `state[scope_var]`:
  - "global" → apply to every render view in the multi-view;
  - any other value (a panel id) → apply only to that panel.

Wraps ptc.TransformEditor with the FESPP custom Apply that
preserves rep ColorArrayName / LookupTable around the Scale write
(observed previously to clobber the active coloring otherwise)."""
from paraview import simple as pvsimple
from trame.app import get_server
from trame.widgets import html

import ptc


SCOPE_GLOBAL = "global"


class TransformationEditor:
    """Z-scale editor scoped by `state[scope_var]`."""

    def __init__(self, scope_var: str = "settings_scope"):
        self._scope_var = scope_var
        self._server = get_server()
        self._state = self._server.state
        self._controller = self._server.controller
        self._te = None  # set in render()

    def render(self):
        html.Div(
            "Transformation",
            classes="text-caption text-uppercase font-weight-bold mb-n1",
        )
        self._te = ptc.TransformEditor(
            show_translation=False,
            show_scale=True,
            show_origin=False,
            show_orientation=False,
            show_apply_button=True,
            classes="text-blue te-align-center",
        )
        # Hide X / Y scale knobs — only Z matters for vertical
        # exaggeration in the standard FESPP workflow.
        self._te.set_components_visibilities({
            self._te.scale_name.x: False,
            self._te.scale_name.y: False,
        })
        self._te.bind_on_apply_button_clicked(self._apply_z_scale)

    def _current_scope(self) -> str:
        return getattr(self._state, self._scope_var, SCOPE_GLOBAL) or SCOPE_GLOBAL

    def _target_views(self):
        """Yield the PV views to apply the transformation to,
        following the current scope. Reaches the multi-view via
        get_server().context.multi_view — the trame controller has
        no back-reference to the server."""
        scope = self._current_scope()
        mv = getattr(self._server.context, "multi_view", None)
        if mv is None:
            v = pvsimple.GetActiveView()
            if v is not None:
                yield v
            return
        if scope == SCOPE_GLOBAL:
            kinds = getattr(mv, "_panel_kinds", {}) or {}
            for pid, view in (mv._pv_internal or {}).items():
                if kinds.get(pid, "render") != "render":
                    continue
                yield view
        else:
            view = mv.get_pv_view(scope) if hasattr(mv, "get_pv_view") else None
            if view is not None:
                yield view

    def _apply_z_scale(self):
        """Apply the editor's Scale to every visible rep on every
        target view. Save / restore ColorArrayName + LookupTable
        around the Scale write so a side-effect on rep state doesn't
        clobber the active coloring."""
        try:
            scale_data = self._te.typed_state.data.scale
            scale = [scale_data.x.value, scale_data.y.value, scale_data.z.value]
        except Exception:
            return
        for view in self._target_views():
            reps = getattr(view, "Representations", None) or []
            for rep in reps:
                if not getattr(rep, "Visibility", 0):
                    continue
                saved_color = None
                saved_lut = None
                try:
                    saved_color = rep.ColorArrayName
                except AttributeError:
                    pass
                try:
                    saved_lut = rep.LookupTable
                except AttributeError:
                    pass
                try:
                    rep.Scale = scale
                except AttributeError:
                    pass
                try:
                    rep.DataAxesGrid.Scale = scale
                except AttributeError:
                    pass
                try:
                    rep.PolarAxes.Scale = scale
                except AttributeError:
                    pass
                if saved_color is not None:
                    try:
                        if rep.ColorArrayName != saved_color:
                            rep.ColorArrayName = saved_color
                    except Exception:
                        pass
                if saved_lut is not None:
                    try:
                        if rep.LookupTable != saved_lut:
                            rep.LookupTable = saved_lut
                    except Exception:
                        pass
            try:
                pvsimple.Render(view=view)
            except Exception:
                pass
        # Push to clients. In single-scope we could target the panel's
        # html_view only, but view_update_all is a no-op for already-
        # up-to-date panels and keeps the code branch-free.
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
