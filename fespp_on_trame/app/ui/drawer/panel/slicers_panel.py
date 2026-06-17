"""Unified "Slicers" parent panel.

Currently exposes only the IJK slicer. The plane Slice and plane
Clip features are implemented in the backend (slice_plane.py,
clip_plane.py, slice_dispatch.py, clip_dispatch.py, plane_widget.py)
and their UI panels exist (SlicePlanePanel, ClipPlanePanel) but they
are commented out in this file — see the `# SLICE/CLIP UI HIDDEN`
markers below. Re-enable by uncommenting; nothing else in the app
needs to change.

The original consolidated design had three internal tabs (IJK /
Slice / Clip) so all "cut the rep geometry" controls lived under
one VExpansionPanel. With Slice + Clip hidden the panel collapses
to a single body — no tab bar, just the IJK content."""
from trame.widgets import html, vuetify3

from fespp_on_trame.app.ui.drawer.panel.slicers import (
    SlicerControls, IJK_TAB_VISIBLE,
)
# SLICE/CLIP UI HIDDEN — imports kept for future re-enable.
# from fespp_on_trame.app.ui.drawer.panel.slice_plane_panel import SlicePlanePanel
# from fespp_on_trame.app.ui.drawer.panel.clip_plane_panel import ClipPlanePanel


class SlicersPanel:
    """Single VExpansionPanel "Slicers" containing the IJK slicer
    only. Slice and Clip tab additions are commented out — see
    module docstring."""

    def __init__(self, *, with_ijk: bool = True):
        # `with_ijk=False` for surface / well main tabs where the IJK
        # slicer has nothing to do. With Slice/Clip currently hidden,
        # `with_ijk=False` produces an empty body — callers should
        # avoid instantiating the panel in that case.
        self._with_ijk = with_ijk

    def render(self):
        with vuetify3.VExpansionPanel():
            with vuetify3.VExpansionPanelTitle(classes="pa-2"):
                html.Span(
                    "Slicers",
                    classes="text-body-2 font-weight-medium",
                )
                vuetify3.VSpacer()
                # SLICE/CLIP UI HIDDEN — at-a-glance status chips.
                # vuetify3.VChip(
                #     "Slice",
                #     v_if="ui_slice_enabled",
                #     size="x-small",
                #     variant="tonal",
                #     color="red",
                #     classes="mr-1",
                # )
                # vuetify3.VChip(
                #     "Clip",
                #     v_if="ui_clip_enabled",
                #     size="x-small",
                #     variant="tonal",
                #     color="orange",
                #     classes="mr-1",
                # )
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
                # SLICE/CLIP UI HIDDEN — the tab bar is collapsed
                # because only IJK is exposed. Restore the VTabs block
                # and the Slice/Clip tab bodies below when re-enabling.
                # with vuetify3.VTabs(
                #     v_model=("ui_slicers_tab", "ijk" if self._with_ijk else "slice"),
                #     density="compact",
                #     color="primary",
                #     grow=True,
                #     mandatory=True,
                #     classes="mb-2",
                # ):
                #     if self._with_ijk:
                #         vuetify3.VTab(
                #             "IJK",
                #             value="ijk",
                #             v_if=IJK_TAB_VISIBLE,
                #             size="small",
                #         )
                #     vuetify3.VTab("Slice", value="slice", size="small")
                #     vuetify3.VTab("Clip", value="clip", size="small")

                if self._with_ijk:
                    SlicerControls().render_body()
                # SLICE/CLIP UI HIDDEN — tab bodies.
                # with html.Div(v_show="ui_slicers_tab === 'slice'"):
                #     SlicePlanePanel().render_body()
                # with html.Div(v_show="ui_slicers_tab === 'clip'"):
                #     ClipPlanePanel().render_body()
