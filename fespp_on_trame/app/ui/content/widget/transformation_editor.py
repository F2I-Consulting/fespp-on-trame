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

    @staticmethod
    def _proxy_reg_name(proxy):
        """Registration name of a proxy (per-(marker,view) extractors are
        registered as ``mrk_…``). Searches both groups the plugin uses."""
        try:
            from paraview import servermanager as _sm
            pm = _sm.ProxyManager()
            smp = getattr(proxy, "SMProxy", proxy)
            for group in ("filters", "sources"):
                n = pm.GetProxyName(group, smp)
                if n:
                    return n
        except Exception:
            pass
        return None

    @classmethod
    def _rep_is_marker(cls, rep, marker_ids):
        """True when this raw PV representation is a marker glyph — so it
        must TRANSLATE, not scale. Robust detection: either the input proxy's
        GlobalID is in the scene-registry marker set, OR its registration
        name carries the ``mrk_`` prefix (works even when the scene registry
        hasn't tracked it)."""
        try:
            inp = rep.Input
        except Exception:
            return False
        try:
            if marker_ids and inp.SMProxy.GetGlobalID() in marker_ids:
                return True
        except Exception:
            pass
        name = cls._proxy_reg_name(inp)
        return bool(name and name.startswith("mrk_"))

    def _apply_z_scale(self):
        """Apply the editor's Scale to every visible rep on every
        target view. Save / restore ColorArrayName + LookupTable
        around the Scale write so a side-effect on rep state doesn't
        clobber the active coloring.

        Two extra responsibilities beyond the raw rep loop:
          - PERSIST the Z exaggeration to ``state.ui_scale_z`` so a source
            created LATER (a freshly-loaded clone / IjkGrid / extractor)
            picks it up at build time (its creation hook reads ui_scale_z)
            and the on-load re-apply scales it too. The Z-scale is GLOBAL,
            so a single state var is the source of truth.
          - MARKERS are symbolic: scaling their rep turns the sphere/disk
            into an "olive". They are TRANSLATED in Z instead (handled by
            marker_dispatch.apply_marker_z), never scaled."""
        try:
            scale_data = self._te.typed_state.data.scale
            scale = [scale_data.x.value, scale_data.y.value, scale_data.z.value]
        except Exception:
            return
        zs = scale[2]
        # Persist the GLOBAL exaggeration (the missing link: nothing wrote
        # ui_scale_z before, so the creation hooks + on-load re-apply always
        # read 1.0 and a later-loaded object stayed flat). The Z-scale is
        # conceptually global, so a single state var is the source of truth
        # that creation hooks + on-load re-apply read.
        try:
            self._state.ui_scale_z = zs
        except Exception:
            pass
        # Recognise marker glyphs so they translate (round) rather than
        # scale (olive).
        from fespp_on_trame.app.core.engine import marker_dispatch
        scene_registry = getattr(self._server.context, "scene_registry", None)
        marker_ids = marker_dispatch.marker_proxy_ids(scene_registry)
        for view in self._target_views():
            reps = getattr(view, "Representations", None) or []
            for rep in reps:
                if not getattr(rep, "Visibility", 0):
                    continue
                if self._rep_is_marker(rep, marker_ids):
                    try:
                        marker_dispatch.apply_marker_z(rep, rep.Input, zs)
                    except Exception:
                        pass
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
