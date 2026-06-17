"""Unified "Slicers" parent panel — IJK + Slice + Clip tabs.

The three tabs are all "cut the rep geometry" variants; grouping
them under one VExpansionPanel + internal VTabs keeps the drawer
compact while showing only the relevant controls at a time.

The backend is per-(rep, view) — each render view has its own
SlicePlane / ClipPlane filter. The UI binds to the GLOBAL
`ui_slice_*` / `ui_clip_*` state vars, which reflect the ACTIVE
panel's filter state via the publish hooks in `slice_dispatch` /
`clip_dispatch`. Switching panel shows the slider values from the
last edit (no auto-refresh from the newly-active panel).

Tab body sources:
  - IJK   → `SlicerControls().render_body()` (IJK + threshold).
            Only rendered in the reservoir tab (with_ijk=True) —
            surface / well don't have IJK grids.
  - Slice → `SlicePlanePanel().render_body()`
  - Clip  → `ClipPlanePanel().render_body()`

Active inner tab is persisted in `state.ui_slicers_tab` (single state
var across all main tabs — VTabs `mandatory` mode falls back to the
first available tab when the value doesn't match)."""
from trame.widgets import html, vuetify3

from fespp_on_trame.app.ui.drawer.panel.slicers import (
    SlicerControls, IJK_TAB_VISIBLE,
)
from fespp_on_trame.app.ui.drawer.panel.slice_plane_panel import SlicePlanePanel
from fespp_on_trame.app.ui.drawer.panel.clip_plane_panel import ClipPlanePanel


class SlicersPanel:
    """Single VExpansionPanel "Slicers" containing the three tabs."""

    def __init__(self, *, with_ijk: bool = True):
        # `with_ijk=False` for surface / well main tabs where the IJK
        # slicer has nothing to do.
        self._with_ijk = with_ijk

    def render(self):
        with vuetify3.VExpansionPanel():
            with vuetify3.VExpansionPanelTitle(classes="pa-2"):
                html.Span(
                    "Slicers",
                    classes="text-body-2 font-weight-medium",
                )
                vuetify3.VSpacer()
                # At-a-glance status chips: surface the currently-active
                # cut modes without expanding the panel.
                vuetify3.VChip(
                    "Slice",
                    v_if="ui_slice_enabled",
                    size="x-small",
                    variant="tonal",
                    color="red",
                    classes="mr-1",
                )
                vuetify3.VChip(
                    "Clip",
                    v_if="ui_clip_enabled",
                    size="x-small",
                    variant="tonal",
                    color="orange",
                    classes="mr-1",
                )
                if self._with_ijk:
                    vuetify3.VChip(
                        "{{ ui_slices_range_mode === 'slice' ? 'IJK slice' : 'IJK range' }}",
                        v_if=(
                            "ui_active_node_reservoir_type_rep === 'IjkGrid'"
                        ),
                        size="x-small",
                        variant="tonal",
                        color="blue",
                        classes="mr-1",
                    )

            with vuetify3.VExpansionPanelText(classes="pa-2"):
                with vuetify3.VTabs(
                    v_model=("ui_slicers_tab", "ijk" if self._with_ijk else "slice"),
                    density="compact",
                    color="primary",
                    grow=True,
                    mandatory=True,
                    classes="mb-2",
                ):
                    if self._with_ijk:
                        # Hide the IJK tab when the active node would
                        # render nothing — the tab bar stays honest.
                        vuetify3.VTab(
                            "IJK",
                            value="ijk",
                            v_if=IJK_TAB_VISIBLE,
                            size="small",
                        )
                    vuetify3.VTab("Slice", value="slice", size="small")
                    vuetify3.VTab("Clip", value="clip", size="small")

                # Tab bodies. v_show (not v_if) so each tab keeps its
                # local UI state (sliders, scroll position) across
                # tab switches.
                if self._with_ijk:
                    with html.Div(v_show="ui_slicers_tab === 'ijk'"):
                        SlicerControls().render_body()
                with html.Div(v_show="ui_slicers_tab === 'slice'"):
                    SlicePlanePanel().render_body()
                with html.Div(v_show="ui_slicers_tab === 'clip'"):
                    ClipPlanePanel().render_body()
