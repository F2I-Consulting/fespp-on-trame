import asyncio
import ptc
from trame.app import get_server
from trame.widgets import vuetify3 as vuetify3

server = get_server()
state = server.state

class CustomTimeControl(ptc.TimeControl):
    """
    TimeControl surchargé avec un délai configurable entre chaque step.
    
    Usage:
        CustomTimeControl(
            play_delay=0.5,  # Délai en secondes (par défaut 0.1)
        )
    """
    
    def __init__(self, play_delay=0.1, **kwargs):
        """
        Initialise le TimeControl avec un délai personnalisé.
        
        Args:
            play_delay (float): Délai en secondes entre chaque step (défaut: 0.1)
            **kwargs: Autres arguments passés au TimeControl de base
        """
        self._play_delay = play_delay
        super().__init__(**kwargs)
    
    @property
    def play_delay(self):
        """Récupère le délai actuel."""
        return self._play_delay
    
    @play_delay.setter
    def play_delay(self, value):
        """
        Modifie le délai entre les steps.
        
        Args:
            value (float): Nouveau délai en secondes
        """
        self._play_delay = value
    
    async def play_animation(self):
        """
        Surcharge de la méthode play_animation avec délai configurable.
        """
        with self.state:
            while self.state.time_play:
                with self.state:
                    self.next()
                await asyncio.sleep(self._play_delay)


# Exemple avec number-input pour contrôler le délai
def custom_time_control_ui(tc: CustomTimeControl):
    """
    Exemple avec un number-inout UI pour contrôler le délai.
    """
    # Time Step Label (Text)
    ptc.VLabel(
        "{{ ui_time_label }}",
        v_if=("ptc_show_vcr"),
        classes="mr-2 text-subtitle-1 font-weight-bold flex-shrink-0",
        # Fixed width prevents layout shift when content changes
        style="overflow: visible; white-space: nowrap; width: 100px;",
        )

    time_ctrl = tc
    
    @server.state.change("animation_delay")
    def update_delay(animation_delay, **kwargs):
        """Callback quand le slider change."""
        time_ctrl.play_delay = float(animation_delay)
    
    # UI pour contrôler le délai
    with vuetify3.VContainer():
        vuetify3.VTextField(
            label="delay",
            v_model="animation_delay",
            v_if=("ptc_show_vcr"),
            # Le type 'number' force la gestion numérique par le navigateur
            type="number", 
            min=0.01,
            max=4.0,
            step=0.01,
            # Ajoutez les boutons incrémentation/décrémentation
            append_icon="mdi-plus",
            prepend_icon="mdi-minus",
            # Gérez l'incrémentation/décrémentation avec des événements
            # C'est la partie clé pour remplacer le VNumberInput
            click_prepend=f"animation_delay = Number(animation_delay) - 0.01",
            click_append=f"animation_delay = Number(animation_delay) + 0.01",
            # Optionnel: Pour limiter le nombre de décimales affichées
            # key_up="animation_delay = Number(animation_delay).toFixed(2)", 
            density="compact"
        )
    
    return time_ctrl