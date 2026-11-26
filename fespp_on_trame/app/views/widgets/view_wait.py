"""THE wait of a view, whatever its kind: the view greyed, and held still, under
the kit's bar along its top edge. A camera turned or a click made during the
wait would not answer, and nothing would say why.

Past 400 ms (`fp-late`) only: a quick answer never flashes it, and the mouse
goes through until then. Its state, ``ui_view_busy__<id>``, is written by
`ctx.view_busy` (app/features/heavy). The host is positioned.
"""
from trame.widgets import html


def view_wait(server, view_id):
    busy = f"ui_view_busy__{view_id}"
    server.state.setdefault(busy, False)
    with html.Div(
        v_show=(busy,),
        classes="fp-wait-scrim fp-late",
        # over the view's cards too, however raised: they read what it waits for
        style="position:absolute; inset:0; z-index:900;",
        raw_attrs=["data-fp-view-wait"],
    ):
        html.Div(
            classes="fp-busy",
            style="position:absolute; top:0; left:0; right:0;",
            raw_attrs=["data-fp-view-busy"],
        )
