import ptc
from trame.app import get_server
from trame.widgets import color_opacity_editor as trame_coe
from trame.widgets import vuetify3, html
from trame.decorators import change
from paraview import simple as pvsimple
from ptc.color_opacity_editor import ColorOpacityEditorConvertor

from fespp_on_trame.app.core.engine import source_resolver

server = get_server()
state = server.state
controller = server.controller


def _apply_nan_color_to_lut(lut):
    """Apply state.nan_color (#RRGGBB or #RRGGBBAA) to the given LUT."""
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
    """ptc.ColorOpacityEditor with a hexa (#RRGGBBAA) NaN color picker
    so the user can pick both the colour and the alpha of NaN cells in
    a single control."""

    def __init__(self):
        # Force hexa format BEFORE the parent applies its #RRGGBB default.
        # App convention: valid values get flat-1 opacity via the PWF;
        # NaN cells default to alpha 00 (transparent) unless the user
        # dials in an alpha here. The red hue means raising the alpha
        # yields a visible "no data" marker.
        state.setdefault("nan_color", "#FF000000")
        super().__init__()

    def build_content(self) -> None:
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
                scalar_range=("scalar_range", [0, 1]),
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

    def _should_apply_state_change(self) -> bool:
        """While the diff-colors dialog is open it owns state.colors /
        state.opacities, so the drawer editor must stand down to avoid
        clobbering the active tree array's LUT. Subclasses can override
        (the diff dialog's editor inverts this check)."""
        return not bool(self.state.diff_colors_dialog_visible)

    def update_scalar_range(self) -> None:
        """Override ptc's `update_scalar_range`.

        Resolve the BASE array name (title → suffixed for MR) for the
        data-info lookup, and the SCOPED name only for the LUT proxy.
        Query the target scene's `RepInScene.source()` (per-view
        EnergisticsExtractor) so MR `_real_<idx>` arrays are found —
        ptc's `self.source_proxy` (= `GetActiveSource`) returns the
        shared `ExtractBlock`, which doesn't carry them."""
        raw_name = self.state.active_color_array_name or ""
        if not raw_name:
            self.state.scalar_range = [0, 1]
            return
        # Resolve the base VTK array name (MR title → `_real_<idx>`).
        base_name, scene_lut = source_resolver.resolve_target_scoped_lut(raw_name)
        if not base_name:
            self.state.scalar_range = [0, 1]
            return
        # Prefer the per-view scene's RepInScene source for the array
        # info lookup — MR `_real_<idx>` arrays live on the per-view
        # EnergisticsExtractor, not on the ExtractBlock that
        # `GetActiveSource()` returns.
        source = None
        try:
            from trame.app import get_server
            srv = get_server()
            st = srv.state
            ctx = srv.context
            # Wellbore channel: read its OWN per-channel extractor
            # (materialised even when hidden) — the frame's primary
            # source() carries no channel array. None for non-channels.
            source = source_resolver.channel_source_for(
                getattr(st, "active_color_array_path", "") or ""
            )
            target_panel = (
                getattr(st, "drawer_target_view_id", "") or ""
                or getattr(st, "fespp_active_panel_id", "") or ""
            )
            rep_path = st.active_representation_path or ""
            scene_registry = getattr(ctx, "scene_registry", None)
            if source is None and scene_registry is not None and target_panel and rep_path:
                scene = scene_registry.get_scene(target_panel)
                if scene is not None:
                    rep_in_scene = scene.get_rep(rep_path)
                    if rep_in_scene is not None:
                        try:
                            source = rep_in_scene.source()
                        except Exception:
                            source = None
        except Exception:
            source = None
        if source is None:
            source = self.source_proxy
        if source is None:
            self.state.scalar_range = [0, 1]
            return
        try:
            # Force a FULL pipeline pass (RequestData), not just the info
            # pass — the per-view IjkGrid's rep_data extractor (returned
            # by `RepInScene.source()`) is built with only
            # `UpdatePipelineInformation()` at creation time. Without a
            # data pass here `GetDataInformation()` reports
            # `NumberOfCells=0` and `GetArrayInformation(base_name)`
            # returns None even though the property array is present on
            # the downstream slicers.
            source.UpdatePipeline()
            source_info = source.GetDataInformation()
        except Exception:
            self.state.scalar_range = [0, 1]
            return
        if source_info is None:
            self.state.scalar_range = [0, 1]
            return
        # Default to cells (FESPP arrays are CELLS today) — fall back
        # to points when not found.
        array_info = None
        for getter in (
            source_info.GetCellDataInformation,
            source_info.GetPointDataInformation,
        ):
            try:
                di = getter()
                if di is not None:
                    ai = di.GetArrayInformation(base_name)
                    if ai is not None:
                        array_info = ai
                        break
            except Exception:
                continue
        if array_info is None:
            self.state.scalar_range = [0, 1]
            return
        lut = scene_lut if scene_lut is not None else pvsimple.GetColorTransferFunction(base_name)
        vector_component = 0
        try:
            vector_component = int(lut.VectorComponent) if lut is not None else 0
        except Exception:
            vector_component = 0
        try:
            r = array_info.GetComponentRange(vector_component)
            # Widen a degenerate range (constant / all-NaN→0 log) so the
            # COE gradient doesn't divide by zero (addColorStop non-finite).
            lo, hi = source_resolver.nondegenerate_range(r[0], r[1])
            self.state.scalar_range = [lo, hi]
        except Exception:
            self.state.scalar_range = [0, 1]

    @change("colors")
    def on_colors_changed(self, *args, **kwargs) -> None:
        if not self._should_apply_state_change():
            return
        super().on_colors_changed(*args, **kwargs)
        # ptc's `update_color_transfer_function` writes RGBPoints but
        # never Renders, and in pinned mode the default `view_update`
        # refreshes the focused panel rather than the drawer target
        # where the edit applies. Render + push to the target explicitly.
        source_resolver.render_and_push_target(self.server.controller)

    @change("preset_name")
    def on_preset_name_changed(self, *args, **kwargs) -> None:
        """Wrap the parent's preset handler so the NaN alpha survives.
        The parent rewrites nan_color in #RRGGBB and would silently
        drop the alpha component."""
        if not self._should_apply_state_change():
            return
        hex_val = (self.state.nan_color or "").lstrip("#")
        saved_alpha = hex_val[6:8] if len(hex_val) >= 8 else "33"
        super().on_preset_name_changed(*args, **kwargs)
        current = (self.state.nan_color or "#FF0000").lstrip("#")[:6]
        self.state.nan_color = f"#{current}{saved_alpha}"
        # Parent mutates RGBPoints but never Renders. Push to target.
        source_resolver.render_and_push_target(self.server.controller)

    @change("opacities")
    def on_opacities_changed(self, *args, **kwargs) -> None:
        """Toggle EnableOpacityMapping based on whether any opacity
        node is below 1.0. VTK limitation: when EnableOpacityMapping=1
        the renderer ignores lut.NanOpacity (the OTF shader forces
        NaN cells to alpha=1.0). We keep EOM=0 for the default
        all-opaque case so NaN opacity stays effective."""
        if not self._should_apply_state_change():
            return
        [_, array_name] = self.get_representation_color_array_name()
        if array_name:
            lut = pvsimple.GetColorTransferFunction(array_name)
            if lut:
                opacities = self.state.opacities or []
                has_transparency = any(op[1] < 0.999 for op in opacities)
                lut.EnableOpacityMapping = 1 if has_transparency else 0
        super().on_opacities_changed(*args, **kwargs)
        # Parent's `update_opacity_transfer_function` Renders the FOCUSED
        # panel (active view in pvsimple). Re-Render + push on the drawer
        # target so pinned mode refreshes the right panel.
        source_resolver.render_and_push_target(self.server.controller)

    @change("nan_color")
    def on_nan_color_changed(self, *args, **kwargs) -> None:
        """Apply NanColor + NanOpacity on the active LUT."""
        if not self._should_apply_state_change():
            return
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
        source_resolver.render_and_push_target(self.server.controller)


state.setdefault("active_color_array_name", "")
