import ptc
from trame.app import get_server
from trame.widgets import color_opacity_editor as trame_coe
from trame.widgets import vuetify3, html
from trame.decorators import change
from paraview import simple as pvsimple
from ptc.color_opacity_editor import ColorOpacityEditorConvertor

from fespp_on_trame.app.core.engine import source_resolver
from fespp_on_trame.app.core.sources import leaf_rep

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
        # Scalar-range + log-scale controls (continuous properties only —
        # this editor is mounted solely for the non-categorical /
        # non-SolidColor case). Register the button handlers BEFORE
        # super().__init__() runs build_content, which references them.
        state.setdefault("color_range_min", 0.0)
        state.setdefault("color_range_max", 1.0)
        state.setdefault("color_use_log", False)
        controller.fespp_apply_color_range = self.apply_color_range
        controller.fespp_reset_color_range = self.reset_color_range_to_data
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

            # --- Scalar range (min/max) + log scale ---
            # Continuous properties only: this editor is mounted solely for
            # the non-categorical / non-SolidColor case (see
            # solid_color_panel), so these knobs never reach a discrete,
            # categorical or SolidColor representation.
            with vuetify3.VRow(no_gutters=True, classes="px-2 pt-2"):
                with vuetify3.VCol(cols=6, classes="pr-1"):
                    vuetify3.VTextField(
                        label="Min",
                        v_model_number=("color_range_min", 0.0),
                        type="number",
                        density="compact",
                        variant="outlined",
                        hide_details=True,
                        keydown_enter=self.apply_color_range,
                    )
                with vuetify3.VCol(cols=6, classes="pl-1"):
                    vuetify3.VTextField(
                        label="Max",
                        v_model_number=("color_range_max", 1.0),
                        type="number",
                        density="compact",
                        variant="outlined",
                        hide_details=True,
                        keydown_enter=self.apply_color_range,
                    )
            with vuetify3.VRow(no_gutters=True, classes="px-2 pt-1", align="center"):
                vuetify3.VBtn(
                    "Apply",
                    size="small",
                    variant="tonal",
                    click=(controller.fespp_apply_color_range,),
                )
                vuetify3.VBtn(
                    "Reset to data range",
                    size="small",
                    variant="text",
                    classes="ml-1",
                    click=(controller.fespp_reset_color_range,),
                )
                vuetify3.VSpacer()
                vuetify3.VSwitch(
                    label="Log scale",
                    v_model=("color_use_log", False),
                    density="compact",
                    hide_details=True,
                    inset=True,
                    classes="flex-grow-0 mt-0",
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

    # ---- Scalar range (min/max) + log scale — continuous props only ----

    @staticmethod
    def _positive_floor(hi):
        """A log axis needs a strictly-positive lower bound: pick a floor
        four decades below the max (tiny epsilon when the max itself is
        non-positive)."""
        try:
            hi = float(hi)
        except (TypeError, ValueError):
            return 1e-6
        return hi * 1e-4 if hi > 0 else 1e-6

    def _resolve_active_lut(self):
        """`(base_name, lut)` for the active array on the drawer's target
        view — the per-view scoped LUT, falling back to the global
        singleton (same resolution as `update_scalar_range`)."""
        raw_name = self.state.active_color_array_name or ""
        if not raw_name:
            return None, None
        base_name, scene_lut = source_resolver.resolve_target_scoped_lut(raw_name)
        if not base_name:
            return None, None
        lut = scene_lut if scene_lut is not None else pvsimple.GetColorTransferFunction(base_name)
        return base_name, lut

    def _sync_range_fields(self, lo, hi):
        """Reflect a range into the Min/Max inputs. They never auto-apply
        (apply is explicit via button / Enter), so writing them here can't
        loop back into a rescale."""
        try:
            self.state.color_range_min = float(lo)
            self.state.color_range_max = float(hi)
        except (TypeError, ValueError):
            pass

    def _resolve_target_pwf(self, base_name):
        """The target scene's scoped opacity function for `base_name`,
        or None outside the per-view scene model."""
        try:
            srv = get_server()
            target = (
                getattr(srv.state, "drawer_target_view_id", "") or ""
                or getattr(srv.state, "fespp_active_panel_id", "") or ""
            )
            reg = getattr(srv.context, "scene_registry", None)
            scene = reg.get_scene(target) if (reg and target) else None
            return scene.get_or_create_pwf(base_name) if scene is not None else None
        except Exception:
            return None

    def _apply_scalar_range(self, lo, hi, pin=True):
        """Rescale the active view's LUT (+ its scoped PWF, in lockstep)
        to [lo, hi] and push the frame. Clamps the lower bound positive
        when the LUT is in log mode.

        `pin=True` marks the range as user-chosen by setting
        `AutomaticRescaleRangeMode='Never'` ON THE LUT PROXY — the flag
        every auto-rescale site checks through `leaf_rep.range_is_pinned`
        (`apply_color_array`'s client-side force-rescale,
        `rescale_to_range`). Without the pin those sites snapped the
        range back to the data on the very next eye click / activation /
        time step, which made this feature look dead on its first
        iteration. `pin=False` (Reset) restores PV's default mode."""
        base, lut = self._resolve_active_lut()
        if lut is None:
            return
        lo, hi = source_resolver.nondegenerate_range(lo, hi)
        if int(getattr(lut, "UseLogScale", 0)) and lo <= 0:
            lo = self._positive_floor(hi)
        try:
            lut.RescaleTransferFunction(float(lo), float(hi))
        except Exception:
            return
        try:
            lut.AutomaticRescaleRangeMode = (
                "Never" if pin else "Grow and update on 'Apply'"
            )
        except Exception:
            pass
        # PWF in lockstep (proportional control-point remap) so the
        # opacity features follow the colour range instead of staying
        # anchored at stale scalar positions.
        try:
            pwf = self._resolve_target_pwf(base)
            if pwf is not None:
                pwf.RescaleTransferFunction(float(lo), float(hi))
        except Exception:
            pass
        self.state.scalar_range = [float(lo), float(hi)]
        self._sync_range_fields(lo, hi)
        source_resolver.render_and_push_target(self.server.controller)

    def apply_color_range(self, *args, **kwargs):
        """Apply the user-entered Min/Max (ignores an inverted / empty
        range where Max <= Min). Wired to the Apply button + Enter."""
        if not self._should_apply_state_change():
            return
        try:
            lo = float(self.state.color_range_min)
            hi = float(self.state.color_range_max)
        except (TypeError, ValueError):
            return
        if hi <= lo:
            return
        self._apply_scalar_range(lo, hi)

    def reset_color_range_to_data(self, *args, **kwargs):
        """Unpin the range, recompute the data range and rescale the LUT
        back to it."""
        if not self._should_apply_state_change():
            return
        _base, lut = self._resolve_active_lut()
        if lut is not None:
            # Unpin FIRST so the recompute + future auto-rescales resume.
            try:
                lut.AutomaticRescaleRangeMode = "Grow and update on 'Apply'"
            except Exception:
                pass
        self.update_scalar_range()
        rng = self.state.scalar_range or [0.0, 1.0]
        try:
            self._apply_scalar_range(float(rng[0]), float(rng[1]), pin=False)
        except (TypeError, ValueError, IndexError):
            pass

    @change("scalar_range")
    def on_scalar_range_changed(self, *args, **kwargs) -> None:
        """Mirror the recomputed data range into the Min/Max inputs and
        reflect the LUT's current log state in the switch. Fires whenever
        `update_scalar_range` recomputes the range (property activation /
        target-view or realization switch). On a PINNED LUT the inputs
        mirror the pinned range read off the LUT's actual control points
        — not the recomputed data range, which the LUT deliberately no
        longer follows."""
        rng = self.state.scalar_range or [0.0, 1.0]
        lo = rng[0] if rng else 0.0
        hi = rng[1] if len(rng) > 1 else 1.0
        _base, lut = self._resolve_active_lut()
        if lut is not None and leaf_rep.range_is_pinned(lut):
            try:
                pts = list(lut.RGBPoints or [])
                if len(pts) >= 4:
                    lo, hi = float(pts[0]), float(pts[-4])
            except Exception:
                pass
        self._sync_range_fields(lo, hi)
        if lut is not None:
            self.state.color_use_log = bool(int(getattr(lut, "UseLogScale", 0)))

    @change("color_use_log")
    def on_color_use_log_changed(self, *args, **kwargs) -> None:
        """Toggle logarithmic colour mapping on the active LUT. No-ops when
        the LUT already matches the request, so the programmatic reflect
        from `on_scalar_range_changed` doesn't re-remap the control points.
        Enabling log clamps the lower bound strictly positive."""
        if not self._should_apply_state_change():
            return
        _base, lut = self._resolve_active_lut()
        if lut is None:
            return
        desired = 1 if self.state.color_use_log else 0
        if int(getattr(lut, "UseLogScale", 0)) == desired:
            return
        if desired:
            try:
                lo = float(self.state.color_range_min)
                hi = float(self.state.color_range_max)
            except (TypeError, ValueError):
                rng = self.state.scalar_range or [0.0, 1.0]
                lo, hi = float(rng[0]), float(rng[1])
            if lo <= 0:
                lo = self._positive_floor(hi)
                try:
                    lut.RescaleTransferFunction(lo, hi)
                except Exception:
                    pass
                self.state.scalar_range = [lo, hi]
                self._sync_range_fields(lo, hi)
            lut.UseLogScale = 1
            try:
                lut.MapControlPointsToLogSpace()
            except Exception:
                pass
        else:
            try:
                lut.MapControlPointsToLinearSpace()
            except Exception:
                pass
            lut.UseLogScale = 0
        source_resolver.render_and_push_target(self.server.controller)

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
