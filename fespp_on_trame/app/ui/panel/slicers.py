from trame.app import get_server
from trame.widgets import vuetify3 as vuetify3, html
from typing import Literal

server = get_server()
state = server.state

vuetify3.enable_lab()

class SlicerControls(html.Div):
    def __init__(self):
        super().__init__(style="display: flex; align-items: center; width: auto;")
        
        state.setdefault("ui_range_i", [0, 0])  
        state.setdefault("ui_range_j", [0, 0])
        state.setdefault("ui_range_k", [0, 0])
        state.setdefault("ui_slices_i_active", False)
        state.setdefault("ui_slices_i", 0)
        state.setdefault("ui_slices_j_active", False)
        state.setdefault("ui_slices_j", 0)
        state.setdefault("ui_slices_k_active", False)
        state.setdefault("ui_slices_k", 0)
        state.setdefault("ui_slices_range_active", False)
        state.setdefault("ui_slices_range_i", [0, 0])
        state.setdefault("ui_slices_range_j", [0, 0])
        state.setdefault("ui_slices_range_k", [0, 0])
        state.setdefault("ui_slices_range_mode", "range")
        
        self._mode_var = f"ui_slices_range_mode"
        self._slices_range_active_var = f"ui_slices_range_active"
        
        with self:
            with vuetify3.VExpansionPanel(
                title="Slicer"
            ):
                with vuetify3.VExpansionPanelText():
                    vuetify3.VSwitch(
                        v_model=(self._mode_var, "range",),
                        style="margin-left: 1.5rem;",
                        label=(self._mode_var,),
                        false_value="range",
                        true_value="slice",
                    )

                    self.RangeSlider("i")
                    self.RangeSlider("j")
                    self.RangeSlider("k")

                    self.Slider("i")
                    self.Slider("j")
                    self.Slider("k")

    def RangeSlider(self, index: Literal["i", "j", "k"]):
        range_var = f"ui_range_{index}"
        slices_range_var = f"ui_slices_range_{index}"

        vuetify3.VRangeSlider(
            v_if=(f"{self._mode_var} === 'range'"),
            label=index.upper(),
            strict=True,
            min=(f"{range_var}[0]",),
            max=(f"{range_var}[1]",),
            step=1,
            v_model=(slices_range_var,),
            thumb_label="always",
            update_modelValue="console.log($event)",
        )

    def Slider(self, index: Literal["i", "j", "k"]):
        range_var = f"ui_range_{index}"
        slices_var = f"ui_slices_{index}"
            
        vuetify3.VSlider(
            v_if=(f"{self._mode_var} === 'slice'"),
            label=index.upper(),
            min=(f"{range_var}[0]",),
            max=(f"{range_var}[1]",),
            step=1,
            thumb_label="always",
            model_value=(f"{slices_var}",),
            update_modelValue=f"{slices_var} = $event",
        )

