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
# Kept for the disabled (WIP) Slice / Clip tabs — re-enable in render().
from fespp_on_trame.app.ui.drawer.panel.slice_plane_panel import SlicePlanePanel  # noqa: F401
from fespp_on_trame.app.ui.drawer.panel.clip_plane_panel import ClipPlanePanel  # noqa: F401


class SlicersPanel:
    """Single VExpansionPanel "Slicers" containing the three tabs."""

    def __init__(self, *, with_ijk: bool = True):
        # `with_ijk=False` for surface / well main tabs where the IJK
        # slicer has nothing to do.
        self._with_ijk = with_ijk

    def render(self):
        # WIP: the Slice / Clip PLANE tools have known bugs and are NOT stable
        # for this release — disabled in the UI (like the multi-view add-view
        # buttons). Backend kept; re-enable the tabs/bodies below when fixed.
        # The surface / well Slicers panel held ONLY Slice+Clip, so it is not
        # rendered there at all.
        if not self._with_ijk:
            return
        with vuetify3.VExpansionPanel():
            with vuetify3.VExpansionPanelTitle(classes="pa-2"):
                html.Span(
                    "Slicers",
                    classes="text-body-2 font-weight-medium",
                )
                vuetify3.VSpacer()
                # Slice / Clip status chips removed — those plane tools are
                # WIP/disabled for this release (see render() note).
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
                    # Slice / Clip tabs disabled — WIP, not stable this release.

                # Tab bodies. v_show (not v_if) so each tab keeps its local UI
                # state across tab switches.
                with html.Div(v_show="ui_slicers_tab === 'ijk'"):
                    SlicerControls().render_body()
                # Slice / Clip bodies disabled (WIP). Re-enable with the tabs:
                #   with html.Div(v_show="ui_slicers_tab === 'slice'"):
                #       SlicePlanePanel().render_body()
                #   with html.Div(v_show="ui_slicers_tab === 'clip'"):
                #       ClipPlanePanel().render_body()
