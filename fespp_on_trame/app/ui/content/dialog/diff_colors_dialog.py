from trame.app import get_server
from trame.widgets import vuetify3 as vuetify3, html
from paraview import simple as pvsimple

from fespp_on_trame.app.ui.drawer.panel.color_editor import (
    _FesppColorOpacityEditor,
    _apply_nan_color_to_lut,
)


_DIFF_ARRAY_NAME = "fespp_diff_value"
_DIFF_CALC_NAME = "fespp_diff"


class _DiffColorOpacityEditor(_FesppColorOpacityEditor):
    """ColorOpacityEditor whose target array is fixed to
    fespp_diff_value, and whose state-change handlers only fire while
    the diff colors dialog is the active editor. Mirrors the gating in
    _FesppColorOpacityEditor so the two editors never both write to a
    shared LUT during the same state mutation.
    """

    def get_representation_color_array_name(self):
        return ["CELLS", _DIFF_ARRAY_NAME]

    def _should_apply_state_change(self) -> bool:
        # Inverse of the drawer's gating: only react while the diff
        # dialog is the live editor.
        return bool(self.state.diff_colors_dialog_visible)

    def update_scalar_range(self) -> None:
        """Defensive variant: at construction time (or any time before
        compute_diff has run) fespp_diff_value does not exist on the
        active source, so the parent's implementation crashes deref'ing
        a None array_info. Fall back to [0, 0] in that case."""
        src = self.source_proxy
        if src is None:
            self.state.scalar_range = [0, 0]
            return
        try:
            info = src.GetDataInformation().DataInformation
            cd_info = info.GetCellDataInformation() if info is not None else None
            arr_info = (
                cd_info.GetArrayInformation(_DIFF_ARRAY_NAME)
                if cd_info is not None
                else None
            )
            if arr_info is None:
                self.state.scalar_range = [0, 0]
                return
        except Exception:
            self.state.scalar_range = [0, 0]
            return
        # Array exists — defer to the parent's full logic (which also
        # touches the LUT VectorComponent).
        super().update_scalar_range()


class DiffColorsDialog:
    """Full ColorOpacityEditor wired to fespp_diff_value (PythonCalculator
    output) inside a dialog. The editor reads from the active source/view
    via GetActiveSource/GetActiveView; refresh_diff_color_editor()
    repoints those to the diff calc + diff view and reloads the LUT/OTF
    state so the existing editor handlers operate on the diff array."""

    def __init__(self):
        self.server = get_server()
        self.state = self.server.state
        self.controller = self.server.controller
        self._coe = None
        self._prev_active_view = None
        self._prev_active_source = None

    def render(self):
        with vuetify3.VDialog(
            v_model=("diff_colors_dialog_visible", False),
            max_width="720",
            scrollable=True,
        ):
            with vuetify3.VCard():
                vuetify3.VCardTitle("Diff color & opacity")
                with vuetify3.VCardText(classes="pa-2"):
                    html.Div(
                        "Edits the LUT/PWF of the fespp_diff_value array"
                        " shown in the Diff view.",
                        classes="text-caption text-medium-emphasis mb-2",
                    )
                    self._coe = _DiffColorOpacityEditor()

                with vuetify3.VCardActions():
                    vuetify3.VSpacer()
                    vuetify3.VBtn(
                        "Close",
                        variant="text",
                        click="diff_colors_dialog_visible = false",
                    )

        @self.controller.set("refresh_diff_color_editor")
        def _refresh():
            """Pull fespp_diff_value's current LUT/OTF into the editor's
            state vars. Called right after compute_diff and whenever the
            dialog opens, so the editor reflects the current diff state
            rather than the previously-active tree array."""
            coe = self._coe
            if coe is None:
                return
            try:
                coe.update_scalar_range()
            except Exception:
                pass
            lut = pvsimple.GetColorTransferFunction(_DIFF_ARRAY_NAME)
            otf = pvsimple.GetOpacityTransferFunction(_DIFF_ARRAY_NAME)
            if lut is not None:
                _apply_nan_color_to_lut(lut)
                if len(lut.RGBPoints) >= 4:
                    coe.update_colors(lut.RGBPoints)
            if otf is not None and otf.Points:
                coe.update_opacities(otf.Points)

        @self.state.change("diff_colors_dialog_visible")
        def _on_visible(diff_colors_dialog_visible, **_):
            """Active source/view must be calc+diff while the dialog is
            open so the embedded ColorOpacityEditor reads its scalar
            range / RGBPoints / preset off the right proxies. On close
            we restore the user's previous active state — otherwise
            subsequent tree clicks would silently keep acting on the
            diff view."""
            if diff_colors_dialog_visible:
                self._prev_active_view = pvsimple.GetActiveView()
                self._prev_active_source = pvsimple.GetActiveSource()
                calc = pvsimple.FindSource(_DIFF_CALC_NAME)
                mv = self.server.context.multi_view
                diff_view = None
                if mv is not None and mv._diff_panel_id is not None:
                    diff_view = mv._pv_internal.get(mv._diff_panel_id)
                if calc is not None:
                    pvsimple.SetActiveSource(calc)
                if diff_view is not None:
                    pvsimple.SetActiveView(diff_view)
                self.controller.refresh_diff_color_editor()
            else:
                if self._prev_active_view is not None:
                    pvsimple.SetActiveView(self._prev_active_view)
                if self._prev_active_source is not None:
                    pvsimple.SetActiveSource(self._prev_active_source)
                self._prev_active_view = None
                self._prev_active_source = None
