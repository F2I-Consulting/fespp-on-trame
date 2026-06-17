"""Full-content dim overlay shown while trame processes a state
flush. Blocks input during the busy phase so the user can't queue
events on top of a pending update.

Bound to `state.trame__busy`, which trame toggles automatically.
`BusyProgressBar` is the lighter, bottom-strip alternative."""
from trame.widgets import vuetify3


class BusyOverlay:
    """Full-content dim overlay that blocks input during a flush."""

    def render(self):
        vuetify3.VOverlay(
            v_if=("trame__busy",),
            v_model=("trame__busy",),
            persistent=True,
            scrim="rgba(0, 0, 0, 0.7)",
            class_="d-flex align-center justify-center",
        )
