"""Per-view camera control toolbar.

Renders reset / +X / +Y / +Z / 2D↔3D-toggle buttons scoped to a
single render panel plus the panels it's linked to via
`state.view_links`.

Each panel owns its own instance. Pair it with `ViewLinkMenu` (the
magnet button) which mutates `state.view_links` to define the
broadcast group."""
from typing import Literal

from paraview import simple as pvsimple
from trame.app import get_server
from trame.widgets import html, vuetify3


class PerViewCameraToolbar:
    """Reset / orient / 2D-3D buttons scoped to a panel + its links."""

    def __init__(self, panel_id: str):
        self._panel_id = panel_id
        self._server = get_server()
        self._state = self._server.state
        self._state.setdefault("interaction_mode", "3D")

    # ------------------------------------------------------------------
    # Target resolution

    def _target_panel_ids(self):
        """Self + every linked panel, deduped, only the ones that
        actually exist in the multi-view (filters orphaned link
        entries left over by closed panels)."""
        mv = getattr(self._server.context, "multi_view", None)
        if mv is None:
            return [self._panel_id]
        pv_internal = mv.panel_pv_views()
        linked = (self._state.view_links or {}).get(self._panel_id, [])
        out = [self._panel_id]
        for pid in linked:
            if pid in pv_internal and pid not in out:
                out.append(pid)
        return [pid for pid in out if pid in pv_internal]

    def _iter_target_views(self):
        """Yield (panel_id, pv_view, html_view) for each panel in the
        current broadcast group."""
        mv = getattr(self._server.context, "multi_view", None)
        if mv is None:
            v = pvsimple.GetActiveView()
            if v is not None:
                yield self._panel_id, v, None
            return
        pv_views = mv.panel_pv_views()
        html_views = mv.panel_html_views()
        for pid in self._target_panel_ids():
            pv_v = pv_views.get(pid)
            if pv_v is not None:
                yield pid, pv_v, html_views.get(pid)

    # ------------------------------------------------------------------
    # Action callbacks

    def _reset_camera(self):
        for _pid, pv_v, html_v in self._iter_target_views():
            try:
                pvsimple.Render(view=pv_v)
            except Exception:
                pass
            if html_v is not None:
                try:
                    html_v.reset_camera()
                except Exception:
                    pass

    def _orient(self, orient_call):
        """Apply an orientation reset (e.g. ResetActiveCameraToPositiveX)
        on every target view, then ask the vtk.js client to refit
        bounds while keeping the new direction."""
        for _pid, pv_v, html_v in self._iter_target_views():
            try:
                orient_call(pv_v)
            except Exception:
                pass
            try:
                pvsimple.Render(view=pv_v)
            except Exception:
                pass
            if html_v is not None:
                try:
                    html_v.reset_camera()
                except Exception:
                    pass

    def _orient_x(self):
        self._orient(lambda v: v.ResetActiveCameraToPositiveX())

    def _orient_y(self):
        self._orient(lambda v: v.ResetActiveCameraToPositiveY())

    def _orient_z(self):
        self._orient(lambda v: v.ResetActiveCameraToPositiveZ())

    def _set_interaction_mode(self, mode: "Literal['2D', '3D']"):
        """`interaction_mode` is a single global state var — we keep
        it that way because the 2D / 3D button toggles the icon based
        on it, and tracking it per-view would complicate the UI for
        marginal value. The mode write fans out to every target view
        regardless."""
        for _pid, pv_v, html_v in self._iter_target_views():
            try:
                pv_v.InteractionMode = mode
            except Exception:
                pass
            if html_v is not None:
                try:
                    html_v.update()
                except Exception:
                    pass
        self._state.interaction_mode = mode

    # ------------------------------------------------------------------
    # Render

    def render(self):
        """Vertical column of icon buttons. Sits next to ViewLinkMenu
        (the magnet button) which renders right above this toolbar."""
        with html.Div(
            classes="d-flex flex-column align-center",
            style="gap: 2px;",
        ):
            self._btn(
                icon="mdi-crop-free",
                tooltip="Reset camera",
                click=self._reset_camera,
            )
            self._btn(
                icon="mdi-axis-x-arrow",
                tooltip="Set view direction to +X",
                click=self._orient_x,
            )
            self._btn(
                icon="mdi-axis-y-arrow",
                tooltip="Set view direction to +Y",
                click=self._orient_y,
            )
            self._btn(
                icon="mdi-axis-z-arrow",
                tooltip="Set view direction to +Z",
                click=self._orient_z,
            )
            # 2D / 3D toggle — the icon flips with state.interaction_mode.
            self._btn(
                icon="mdi-video-3d",
                tooltip="Switch to 2D interaction",
                click=(self._set_interaction_mode, "['2D']"),
                v_show="interaction_mode === '3D'",
            )
            self._btn(
                icon="mdi-video-2d",
                tooltip="Switch to 3D interaction",
                click=(self._set_interaction_mode, "['3D']"),
                v_show="interaction_mode === '2D'",
            )

    def _btn(self, icon: str, tooltip: str, click, v_show: str = None):
        """One tooltipped icon button. Tooltip placed on the right so
        it doesn't overlap the panel content above."""
        with vuetify3.VTooltip(location="right"):
            with vuetify3.Template(v_slot_activator="{ props }"):
                kwargs = dict(
                    icon=icon,
                    v_bind="props",
                    variant="text",
                    size="small",
                    color="grey-darken-1",
                    click=click,
                )
                if v_show is not None:
                    kwargs["v_show"] = v_show
                vuetify3.VBtn(**kwargs)
            html.Span(tooltip)
