import ptc
from trame.app import get_server
from trame.widgets import vuetify3, html
from paraview import simple as pvsimple

server = get_server()
state = server.state
controller = server.controller


class ColorEditor(html.Div):
    """Color & Opacity editor panel for Property nodes.

    Wraps ptc.ColorOpacityEditor with:
    - per-source active-array tracking via state.active_color_array_name
    - EnableOpacityMapping propagation to all visible sources
    - controller.update_color_editor wired up for external callers
    """

    def __init__(self):
        super().__init__(v_if="active_color_array_name && active_color_array_name.length > 0")

        state.setdefault("active_color_array_name", "")

        with self:
            with vuetify3.VExpansionPanels(v_model=("coe_panels", [0]), multiple=True, elevation=0):
                with vuetify3.VExpansionPanel(title="Colors & Opacity", elevation=0, value=0):
                    with vuetify3.VExpansionPanelText(classes="pa-0"):
                        coe = ptc.ColorOpacityEditor()

        # --- Override array-name lookup to use state instead of active source ---
        _original_get_array_name = coe.get_representation_color_array_name

        def _get_array_name_from_state():
            name = state.active_color_array_name
            if name:
                return ["CELLS", name]
            return _original_get_array_name()

        coe.get_representation_color_array_name = _get_array_name_from_state

        # --- Opacity helpers ---

        def _enable_opacity_on_all_sources():
            """Active l'opacité séparée sur le LUT actif (appelé une seule fois à l'activation)."""
            array_name = state.active_color_array_name
            if array_name:
                lut = pvsimple.GetColorTransferFunction(array_name)
                if lut:
                    try:
                        lut.EnableOpacityMapping = 1
                    except AttributeError:
                        pass
            active_view = pvsimple.GetActiveView()
            if not active_view:
                return
            for _, source in pvsimple.GetSources().items():
                disp = pvsimple.GetDisplayProperties(source, view=active_view)
                if disp and disp.Visibility:
                    try:
                        disp.EnableOpacityMapping = 1
                    except AttributeError:
                        pass

        # --- Public controller hook ---
        def _update_color_editor(array_name):
            state.active_color_array_name = array_name
            state.coe_panels = [0]
            try:
                coe.update_scalar_range()
            except Exception:
                pass
            lut = pvsimple.GetColorTransferFunction(array_name)
            if lut and len(lut.RGBPoints) >= 4:
                smin = lut.RGBPoints[0]
                smax = lut.RGBPoints[-4]
                all_opaque = [smin, 1.0, 0.5, 0.0, smax, 1.0, 0.5, 0.0]
                coe.update_colors(lut.RGBPoints)
                coe.update_opacities(all_opaque)
                _enable_opacity_on_all_sources()

        controller.update_color_editor = _update_color_editor
