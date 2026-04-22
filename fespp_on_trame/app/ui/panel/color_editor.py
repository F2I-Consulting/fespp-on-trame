import ptc
from trame.app import get_server
from trame.widgets import color_opacity_editor as trame_coe
from trame.widgets import vuetify3, html
from trame.decorators import change
from paraview import simple as pvsimple
from ptc.color_opacity_editor import ColorOpacityEditorConvertor

server = get_server()
state = server.state
controller = server.controller


def _apply_nan_color_to_lut(lut):
    """Apply current state.nan_color (#RRGGBB or #RRGGBBAA) to a LUT."""
    nan_color = state.nan_color or ""
    hex_val = nan_color.lstrip("#")
    if len(hex_val) < 6:
        return
    try:
        rgb = ColorOpacityEditorConvertor.convert_hex_to_rgb(hex_val)
        lut.NanColor = [rgb[0] / 255, rgb[1] / 255, rgb[2] / 255]
        if len(hex_val) >= 8:
            lut.NanOpacity = int(hex_val[6:8], 16) / 255
    except (ValueError, IndexError):
        pass


class _FesppColorOpacityEditor(ptc.ColorOpacityEditor):
    """Surcharge de ptc.ColorOpacityEditor avec NaN color en mode hexa (#RRGGBBAA)
    pour gérer couleur ET opacité du NaN en un seul picker."""

    def __init__(self):
        # Force le format hexa avant que le parent ne pose son défaut #RRGGBB
        state.setdefault("nan_color", "#FF000033")
        super().__init__()

    def build_content(self) -> None:
        """Même contenu que le parent, mais VColorPicker hexa à la place de ColorPicker."""
        with self:
            vuetify3.VSelect(
                label="Select preset",
                v_model=("preset_name",),
                items=("presets_names",),
            )

            trame_coe.ColorOpacityEditor(
                style="width: 100%; height: 15rem; padding: 0.5rem;",
                v_model_colorNodes=("colors", []),
                v_model_opacityNodes=(
                    "opacities",
                    self.make_linear_nodes([0, 1], [0, 1]),
                ),
                scalar_range=("scalar_range", [0, 0]),
                background_shape=("background_shape", "opacity"),
                background_opacity=("background_opacity", True),
                handle_radius=7,
                line_width=2,
                viewport_padding=("viewport_padding", [8, 8]),
                handle_color=("handle_color", [0.125, 0.125, 0.125, 1]),
                handle_border_color=("handle_border_color", [0.75, 0.75, 0.75, 1]),
                histograms=("histograms", []),
                histograms_range=("histograms_range", []),
                show_histograms=("show_histograms", False),
                histograms_color=("histograms_color", [0, 0, 0, 0.25]),
            )

            # Nan color picker en hexa (#RRGGBBAA)
            with vuetify3.VMenu(close_on_content_click=False):
                with vuetify3.Template(v_slot_activator="{ props }"):
                    with vuetify3.VBtn(
                        "Nan Color",
                        v_bind="props",
                        elevation=0,
                        classes="justify-start",
                        block=True,
                    ):
                        with vuetify3.Template(v_slot_prepend=True):
                            vuetify3.VIcon(
                                "mdi-circle",
                                color=("nan_color ? nan_color.slice(0,7) : '#FF0000'",),
                            )
                vuetify3.VColorPicker(
                    v_model=("nan_color",),
                    modes=("['hexa']",),
                    classes="w-100",
                    divided=True,
                    landscape=True,
                    max_width=300,
                )

            with vuetify3.VExpansionPanels(
                v_model=("opened_panels", [0, 1]),
                multiple=True,
                elevation=0,
            ):
                with vuetify3.VExpansionPanel():
                    vuetify3.VExpansionPanelTitle("Color transfer function")
                    vuetify3.VDivider()
                    with vuetify3.VExpansionPanelText():
                        self.build_color_editor_table()
                with vuetify3.VExpansionPanel():
                    vuetify3.VExpansionPanelTitle("Opacity transfer function")
                    vuetify3.VDivider()
                    with vuetify3.VExpansionPanelText():
                        self.build_opacity_editor_table()

    @change("preset_name")
    def on_preset_name_changed(self, *args, **kwargs) -> None:
        """Surcharge : appel parent + préserve l'alpha de nan_color."""
        # Sauvegarder l'alpha actuel avant que le parent n'écrase nan_color en #RRGGBB
        hex_val = (self.state.nan_color or "").lstrip("#")
        saved_alpha = hex_val[6:8] if len(hex_val) >= 8 else "33"
        # Appel du parent (met à jour le LUT, les couleurs, et écrit nan_color en #RRGGBB)
        super().on_preset_name_changed(*args, **kwargs)
        # Ré-ajouter l'alpha
        current = (self.state.nan_color or "#FF0000").lstrip("#")[:6]
        self.state.nan_color = f"#{current}{saved_alpha}"

    @change("opacities")
    def on_opacities_changed(self, *args, **kwargs) -> None:
        """EnableOpacityMapping conditionnel.

        Limitation VTK : quand EnableOpacityMapping=1, le rendu ignore
        lut.NanOpacity (l'alpha des cellules NaN est forcé à 1.0 par le
        shader de l'OTF). On active donc l'OTF uniquement si au moins un
        nœud d'opacité est < 1.0 — sinon on laisse EOM=0 pour préserver
        NaN opacity dans le cas par défaut "tout opaque".
        """
        [_, array_name] = self.get_representation_color_array_name()
        if array_name:
            lut = pvsimple.GetColorTransferFunction(array_name)
            if lut:
                opacities = self.state.opacities or []
                has_transparency = any(op[1] < 0.999 for op in opacities)
                lut.EnableOpacityMapping = 1 if has_transparency else 0
        super().on_opacities_changed(*args, **kwargs)

    @change("nan_color")
    def on_nan_color_changed(self, *args, **kwargs) -> None:
        """Surcharge : applique NanColor + NanOpacity sur le LUT actif."""
        nan_color = self.state.nan_color
        if not nan_color or len(nan_color) < 7:
            return
        [_, array_name] = self.get_representation_color_array_name()
        if not array_name:
            return
        lut = pvsimple.GetColorTransferFunction(array_name)
        if not lut:
            return
        _apply_nan_color_to_lut(lut)
        pvsimple.Render()
        self.ctrl.view_update()


# NOTE: the standalone ColorEditor panel class has been merged into
# SolidColorPanel (see solid_color_panel.py). _FesppColorOpacityEditor and
# _apply_nan_color_to_lut remain here as shared utilities, imported by the
# merged panel.

state.setdefault("active_color_array_name", "")
