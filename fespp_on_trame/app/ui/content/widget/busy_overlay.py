"""Full-content dim overlay shown while trame is processing a state
flush. Blocks input during the busy phase so the user doesn't queue
events on top of a pending update.

Bound to `state.trame__busy`, which trame toggles automatically. The
companion `BusyProgressBar` (a thinner bottom strip rendered inside
the multi-view area) is in `busy_progress_bar.py` — it provides a
less intrusive "loading…" cue when blocking the whole layout would
be overkill."""
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
