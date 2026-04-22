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
        print(f"[DEBUG apply_nan] skip: nan_color too short ({nan_color!r})")
        return
    try:
        rgb = ColorOpacityEditorConvertor.convert_hex_to_rgb(hex_val)
        lut.NanColor = [rgb[0] / 255, rgb[1] / 255, rgb[2] / 255]
        if len(hex_val) >= 8:
            nan_op = int(hex_val[6:8], 16) / 255
            lut.NanOpacity = nan_op
            print(f"[DEBUG apply_nan] NanColor={lut.NanColor}, NanOpacity={nan_op}, EnableOpacityMapping={lut.EnableOpacityMapping}")
        else:
            print(f"[DEBUG apply_nan] NanColor set but no alpha, EnableOpacityMapping={lut.EnableOpacityMapping}")
    except (ValueError, IndexError) as e:
        print(f"[DEBUG apply_nan] exception: {e}")


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
        print(f"[DEBUG on_nan_color] nan_color={nan_color!r}")
        if not nan_color or len(nan_color) < 7:
            return
        [_, array_name] = self.get_representation_color_array_name()
        if not array_name:
            print(f"[DEBUG on_nan_color] no array_name, skip")
            return
        lut = pvsimple.GetColorTransferFunction(array_name)
        if not lut:
            print(f"[DEBUG on_nan_color] no lut for {array_name!r}, skip")
            return

        print(f"[DEBUG on_nan_color] BEFORE: EnableOpacityMapping={lut.EnableOpacityMapping}, NanOpacity={lut.NanOpacity}")
        _apply_nan_color_to_lut(lut)
        # Forcer la synchro proxy→VTK puis la reconstruction de la LUT texture
        try:
            lut.UpdateVTKObjects()
            lut.SMProxy.MarkAllPropertiesAsModified()
        except Exception as e:
            print(f"[DEBUG on_nan_color] lut update exception: {e}")
        # Forcer toutes les représentations visibles à se re-mapper
        try:
            active_view = pvsimple.GetActiveView()
            for src in pvsimple.GetSources().values():
                rep = pvsimple.GetRepresentation(src, active_view)
                if rep and rep.Visibility:
                    rep.UpdateVTKObjects()
                    rep.SMProxy.MarkAllPropertiesAsModified()
        except Exception as e:
            print(f"[DEBUG on_nan_color] rep refresh exception: {e}")
        print(f"[DEBUG on_nan_color] AFTER force-refresh: NanOpacity={lut.NanOpacity}, calling Render()")
        pvsimple.Render()
        self.ctrl.view_update()


class ColorEditor(html.Div):
    """Color & Opacity editor panel for Property nodes."""

    def __init__(self):
        super().__init__(v_if="active_color_array_name && active_color_array_name.length > 0")

        state.setdefault("active_color_array_name", "")

        with self:
            with vuetify3.VExpansionPanels(v_model=("coe_panels", [0]), multiple=True, elevation=0):
                with vuetify3.VExpansionPanel(title="Colors & Opacity", elevation=0, value=0):
                    with vuetify3.VExpansionPanelText(classes="pa-0"):
                        coe = _FesppColorOpacityEditor()

        # --- Override array-name lookup to use state instead of active source ---
        _original_get_array_name = coe.get_representation_color_array_name

        def _get_array_name_from_state():
            name = state.active_color_array_name
            if name:
                return ["CELLS", name]
            return _original_get_array_name()

        coe.get_representation_color_array_name = _get_array_name_from_state

        # --- Public controller hook ---
        def _update_color_editor(array_name):
            print(f"[DEBUG _update_color_editor] ENTER array_name={array_name!r}")
            state.active_color_array_name = array_name
            try:
                coe.update_scalar_range()
            except Exception:
                pass
            lut = pvsimple.GetColorTransferFunction(array_name)
            if lut:
                print(f"[DEBUG _update_color_editor] BEFORE apply_nan: EnableOpacityMapping={lut.EnableOpacityMapping}, NanOpacity={lut.NanOpacity}")
                _apply_nan_color_to_lut(lut)
                print(f"[DEBUG _update_color_editor] AFTER apply_nan: EnableOpacityMapping={lut.EnableOpacityMapping}, NanOpacity={lut.NanOpacity}")
                if len(lut.RGBPoints) >= 4:
                    smin = lut.RGBPoints[0]
                    smax = lut.RGBPoints[-4]
                    all_opaque = [smin, 1.0, 0.5, 0.0, smax, 1.0, 0.5, 0.0]
                    coe.update_colors(lut.RGBPoints)
                    print(f"[DEBUG _update_color_editor] calling update_opacities(all_opaque={all_opaque})")
                    coe.update_opacities(all_opaque)
                    print(f"[DEBUG _update_color_editor] AFTER update_opacities: EnableOpacityMapping={lut.EnableOpacityMapping}, NanOpacity={lut.NanOpacity}")

        controller.update_color_editor = _update_color_editor
