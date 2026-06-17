"""Scope-aware background editor.

A self-contained class that renders the "Background" section of the
GlobalSettingsDialog. The block it emits switches based on the value
of the state var passed via `scope_var`:

  - scope == "global" → `ptc.PalettePicker`. Clicking a palette runs
    `simple.LoadPalette()` (ParaView's global palette settings), and
    `on_data_change` re-broadcasts a fresh frame to every panel.

  - scope == "<panel_id>" → per-view controls modelled on the
    ParaView Properties panel:
      * `Use Color Palette For Background` checkbox →
        `view.UseColorPaletteForBackground = 0/1`
      * `Background Color Mode` select →
        `view.BackgroundColorMode = "Single Color" | "Gradient"`
      * Color pickers → `view.Background` / `view.Background2`.

State vars (back-compat with one another between scopes):
  - `bg_use_palette` (bool)
  - `bg_mode` ("Single Color" | "Gradient")
  - `bg_color1`, `bg_color2` (hex strings — what VColorPicker emits)

When the scope changes, the class reads the target view's current
state and pushes it into those state vars so the controls reflect
reality. A `_syncing` flag prevents the read-back from re-triggering
the write handlers in a loop.
"""
from paraview import simple as pvsimple
from trame.app import get_server
from trame.widgets import html, vuetify3

import ptc


def _rgb_to_hex(rgb):
    try:
        r, g, b = rgb[:3]
        return "#{:02x}{:02x}{:02x}".format(
            int(round(max(0.0, min(1.0, float(r))) * 255)),
            int(round(max(0.0, min(1.0, float(g))) * 255)),
            int(round(max(0.0, min(1.0, float(b))) * 255)),
        )
    except Exception:
        return "#000000"


def _hex_to_rgb(hex_str):
    s = (hex_str or "").lstrip("#")
    if len(s) < 6:
        return [0.0, 0.0, 0.0]
    try:
        return [
            int(s[0:2], 16) / 255.0,
            int(s[2:4], 16) / 255.0,
            int(s[4:6], 16) / 255.0,
        ]
    except ValueError:
        return [0.0, 0.0, 0.0]


class BackgroundEditor:
    SCOPE_GLOBAL = "global"

    def __init__(self, scope_var: str = "settings_scope"):
        self.scope_var = scope_var
        self._server = get_server()
        self._state = self._server.state
        self._controller = self._server.controller
        # Set when we are pushing values into state from a view read,
        # so the per-var @change handlers don't push those same values
        # back into the view.
        self._syncing = False

        st = self._state
        st.setdefault("bg_use_palette", True)
        st.setdefault("bg_mode", "Single Color")
        st.setdefault("bg_color1", "#5c6c7a")
        st.setdefault("bg_color2", "#1133aa")

        # Scope changes drive the read-back from the target view.
        st.change(scope_var)(self._on_scope_change)
        # Per-control changes drive the write-back to the target view.
        st.change("bg_use_palette")(self._on_use_palette_change)
        st.change("bg_mode")(self._on_mode_change)
        st.change("bg_color1")(self._on_color1_change)
        st.change("bg_color2")(self._on_color2_change)

    # ----- helpers -----

    def _current_scope(self):
        return getattr(self._state, self.scope_var, self.SCOPE_GLOBAL) or self.SCOPE_GLOBAL

    def _multi_view(self):
        return getattr(self._server.context, "multi_view", None)

    def _pv_view(self):
        scope = self._current_scope()
        if scope == self.SCOPE_GLOBAL:
            return None
        mv = self._multi_view()
        if mv is None or not hasattr(mv, "get_pv_view"):
            return None
        return mv.get_pv_view(scope)

    def _html_view(self):
        scope = self._current_scope()
        if scope == self.SCOPE_GLOBAL:
            return None
        mv = self._multi_view()
        if mv is None or not hasattr(mv, "get_html_view"):
            return None
        return mv.get_html_view(scope)

    def _render_and_push(self):
        view = self._pv_view()
        if view is not None:
            try:
                pvsimple.Render(view=view)
            except Exception:
                pass
        html_v = self._html_view()
        if html_v is not None:
            try:
                html_v.update()
            except Exception:
                pass

    # ----- handlers -----

    def _on_scope_change(self, **_):
        """Read the target view's current background state and push
        it onto bg_* state vars so the controls reflect reality."""
        view = self._pv_view()
        if view is None:
            # Global scope: leave bg_* vars at their last per-view
            # values (the per-view section won't be rendered anyway).
            return
        self._syncing = True
        try:
            try:
                self._state.bg_use_palette = bool(int(view.UseColorPaletteForBackground))
            except Exception:
                self._state.bg_use_palette = True
            try:
                mode = str(view.BackgroundColorMode)
                if mode not in ("Single Color", "Gradient"):
                    mode = "Single Color"
                self._state.bg_mode = mode
            except Exception:
                self._state.bg_mode = "Single Color"
            try:
                self._state.bg_color1 = _rgb_to_hex(list(view.Background))
            except Exception:
                pass
            try:
                self._state.bg_color2 = _rgb_to_hex(list(view.Background2))
            except Exception:
                pass
        finally:
            self._syncing = False

    def _on_use_palette_change(self, **_):
        if self._syncing:
            return
        view = self._pv_view()
        if view is None:
            return
        try:
            view.UseColorPaletteForBackground = 1 if self._state.bg_use_palette else 0
            view.SMProxy.UpdateVTKObjects()
        except Exception:
            pass
        self._render_and_push()

    def _on_mode_change(self, **_):
        if self._syncing:
            return
        view = self._pv_view()
        if view is None:
            return
        try:
            view.BackgroundColorMode = self._state.bg_mode
            view.SMProxy.UpdateVTKObjects()
        except Exception:
            pass
        self._render_and_push()

    def _on_color1_change(self, **_):
        if self._syncing:
            return
        view = self._pv_view()
        if view is None:
            return
        try:
            view.Background = _hex_to_rgb(self._state.bg_color1)
            view.SMProxy.UpdateVTKObjects()
        except Exception:
            pass
        self._render_and_push()

    def _on_color2_change(self, **_):
        if self._syncing:
            return
        view = self._pv_view()
        if view is None:
            return
        try:
            view.Background2 = _hex_to_rgb(self._state.bg_color2)
            view.SMProxy.UpdateVTKObjects()
        except Exception:
            pass
        self._render_and_push()

    # ----- render -----

    def render(self):
        """Emit the Background section. Must be called inside an open
        Trame layout context (e.g. a VCardText). Builds two
        alternative subtrees and toggles between them via v-if on the
        scope state var."""
        scope = self.scope_var

        html.Div(
            "Background",
            classes="text-caption text-uppercase font-weight-bold mb-2",
        )

        # Global scope: ptc.PalettePicker. Behaviour unchanged from
        # the legacy single-view setup — palette change is applied
        # via simple.LoadPalette which is global ParaView, and the
        # broadcast on_data_change handler pushes a fresh frame to
        # every panel.
        with html.Div(
            v_if=f"{scope} === 'global'",
            classes="d-flex align-center",
        ):
            html.Span(
                "Palette:",
                classes="text-caption font-weight-medium mr-3",
            )
            ptc.PalettePicker(
                color="blue",
                base_color="blue",
                item_color="blue",
                flat=True,
            )

        # Per-view scope: ParaView Properties-panel-style controls.
        with html.Div(v_if=f"{scope} !== 'global'"):
            vuetify3.VCheckbox(
                v_model=("bg_use_palette", True),
                label="Use Color Palette For Background",
                density="compact",
                hide_details=True,
                classes="mb-2",
            )
            # Mode + color pickers only meaningful when not deferring
            # to the global palette.
            with html.Div(v_if="!bg_use_palette", classes="ml-4"):
                vuetify3.VSelect(
                    v_model=("bg_mode", "Single Color"),
                    items=("['Single Color', 'Gradient']",),
                    label="Background Color Mode",
                    density="compact",
                    hide_details=True,
                    variant="outlined",
                    style="max-width: 280px;",
                    classes="mb-3",
                )
                # Color 1 (Background) — always shown when not using
                # palette. The swatch is the VBtn activator; clicking
                # opens a VMenu with a VColorPicker.
                self._color_row("Color 1", "bg_color1")
                # Color 2 (Background2) — shown only in Gradient mode.
                with html.Div(v_if="bg_mode === 'Gradient'", classes="mt-2"):
                    self._color_row("Color 2", "bg_color2")

    def _color_row(self, label: str, color_state: str):
        """Single labelled colour-picker row: a swatch button that
        toggles a VColorPicker popover. close_on_content_click=False
        keeps the picker open while the user drags the hue/value
        sliders so each intermediate value is committed live to the
        view (no debouncing — looks responsive enough in practice)."""
        with html.Div(classes="d-flex align-center"):
            html.Span(
                f"{label}:",
                classes="text-caption mr-2",
                style="min-width: 70px;",
            )
            with vuetify3.VMenu(close_on_content_click=False):
                with vuetify3.Template(v_slot_activator="{ props }"):
                    vuetify3.VBtn(
                        v_bind="props",
                        size="small",
                        variant="elevated",
                        color=(color_state,),
                        style=(
                            f"{{ minWidth: '48px', height: '32px',"
                            f" backgroundColor: {color_state},"
                            " border: '1px solid rgba(0,0,0,0.2)' }",
                        ),
                    )
                # Background colour has no transparency semantics —
                # `hexa`/`rgba`/`hsla` modes would show an opacity
                # slider for nothing. The bg_color1/bg_color2 state
                # vars are already 6-char "#rrggbb" strings (see
                # `_rgb_to_hex` / `_hex_to_rgb`).
                vuetify3.VColorPicker(
                    v_model=(color_state,),
                    mode="hex",
                    modes=("['hex', 'rgb', 'hsl']",),
                    show_swatches=True,
                )
