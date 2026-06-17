"""Bottom progress strip rendered inside the multi-view area.

Two indeterminate progress lines + an info alert showing
`view_loading_message`. Lighter complement of `BusyOverlay`: both
react to `state.trame__busy`, but this one only takes a few pixels at
the bottom so the user can keep watching the 3D view during a flush."""
import ptc
from trame.widgets import html


class BusyProgressBar:
    """Bottom progress strip rendered inside the multi-view area."""

    def render(self):
        with html.Div(
            v_if=("trame__busy",),
            style="position: absolute; bottom: 0; width: 100%; left: 0; z-index: 2;",
        ):
            ptc.VProgressLinear(indeterminate=True, color="green-darken-1")
            ptc.VProgressLinear(reverse=True, indeterminate=True, color="blue-darken-4")
            ptc.VAlert(
                children=["{{ view_loading_message }}"],
                type="info",
                prominent=True,
                color="blue-grey-lighten-4",
                classes="w-100 pa-0 ma-0",
            )
