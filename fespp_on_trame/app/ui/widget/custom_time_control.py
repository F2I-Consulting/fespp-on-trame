import asyncio
import ptc
from trame.app import get_server
from trame.widgets import vuetify3 as vuetify
from trame.widgets import html

server = get_server()
state = server.state

class CustomTimeControl(ptc.TimeControl):
    def __init__(self, play_delay=1.0, **kwargs):  # Changé à 1.0 par défaut
        self._play_delay = play_delay
        super().__init__(**kwargs)
        print(f"CustomTimeControl initialized with delay: {play_delay}s")
    
    @property
    def play_delay(self):
        return self._play_delay
    
    @play_delay.setter
    def play_delay(self, value):
        old_value = self._play_delay
        self._play_delay = value
        print(f"CustomTimeControl: play_delay changed from {old_value}s to {value}s")
    
    async def play_animation(self):
        print(f"Starting animation with delay: {self._play_delay}s")
        with self.state:
            while self.state.time_play:
                with self.state:
                    self.next()
                await asyncio.sleep(self._play_delay)
        print("Animation stopped")

def custom_time_control_ui(tc: CustomTimeControl):
    """
    Version avec gestion robuste des états None
    """
    
    SPEEDS = [4.0, 2.0, 1.0, 0.5, 0.25]
    DEFAULT_INDEX = 2
    
    # Fonction utilitaire pour obtenir un index valide
    def get_safe_speed_index():
        """Retourne toujours un index valide, même si state.speed_index est None"""
        index = state.speed_index
        if index is None:
            state.speed_index = DEFAULT_INDEX
            state.animation_delay = SPEEDS[DEFAULT_INDEX]
            tc.play_delay = SPEEDS[DEFAULT_INDEX]
            return DEFAULT_INDEX
        return index  # S'assurer que c'est un entier
    
    # Initialize state de manière robuste
    if not hasattr(state, 'speed_index') or state.speed_index is None:
        state.speed_index = DEFAULT_INDEX
        state.animation_delay = SPEEDS[DEFAULT_INDEX]
        tc.play_delay = SPEEDS[DEFAULT_INDEX]
    
    def speed_down():
        current_index = get_safe_speed_index()
        
        if current_index > 0:
            new_index = current_index - 1
            state.speed_index = new_index
            state.animation_delay = SPEEDS[new_index]
            tc.play_delay = SPEEDS[new_index]
    
    def speed_up():
        current_index = get_safe_speed_index()
        
        if current_index < len(SPEEDS) - 1:
            new_index = current_index + 1
            state.speed_index = new_index
            state.animation_delay = SPEEDS[new_index]
            tc.play_delay = SPEEDS[new_index]
    
    with html.Div(style="display: flex; align-items: center; gap: 12px; flex-wrap: wrap; color-background: white; "):
        
        # Contrôle principal
        with html.Div(style="display: flex; align-items: center; gap: 12px;"):
            ptc.VLabel(
                "{{ ui_time_label }}",
                v_if=("ptc_show_vcr",),
                classes="text-subtitle-1 font-weight-bold",
                style="overflow: visible; white-space: nowrap;",
            )
            
            tc
            
            with vuetify.VBtnGroup(
                v_if=("ptc_show_vcr",),
                density="compact",
                variant="text",
            ):
                # Slow down button
                vuetify.VBtn(
                    icon="mdi-minus",
                    size="small",
                    click=speed_down,
                    disabled=("speed_index <= 0",),
                    tooltip="slow",
                )
                
                # Speed indicator
                with vuetify.VBtn(
                    size="x-large",
                    disabled=True,
                    style="min-width: 20px;max-width: 30px;",
                    variant="tonal"
                ):
                    vuetify.VIcon(
                        size="x-large",
                        icon=(f"['mdi-gauge-empty', 'mdi-gauge-low', 'mdi-gauge', 'mdi-gauge-full', 'mdi-gauge-full'][speed_index ?? {DEFAULT_INDEX}]",),
                        color=(f"['#1976D2', '#42A5F5', '#66BB6A', '#FFA726', '#F44336'][speed_index ?? {DEFAULT_INDEX}]",),
                    )
                
                # Speed up button
                vuetify.VBtn(
                    icon="mdi-plus",
                    size="small",
                    click=speed_up,
                    disabled=(f"speed_index >= {len(SPEEDS) - 1}",),
                    tooltip="speed up",
                )
        
    @state.change("animation_delay")
    def on_animation_delay_change(animation_delay, **kwargs):
        safe_delay = animation_delay if animation_delay is not None else "None"
        
        # Mettre à jour tc.play_delay si animation_delay change depuis l'extérieur
        if animation_delay is not None:
            try:
                tc.play_delay = float(animation_delay)
            except (TypeError, ValueError):
                pass
    
    get_safe_speed_index()
    
    return tc