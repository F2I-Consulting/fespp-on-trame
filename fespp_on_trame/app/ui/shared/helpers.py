from trame.widgets import vuetify3 as vuetify3, html


def create_card(title, icon, height=None):
    """Build a flat, vertically-resizable VCard with a styled toolbar
    title and a scrollable content area. Returns the VCardText so the
    caller can populate it inside a `with` block."""
    card_props = {
        "classes": "pa-0 mb-4 border d-flex flex-column",
        "elevation": 0,
        "flat": True,
        "tile": False,
        "style": "resize: vertical; overflow: hidden; min-height: 250px;",
    }

    if height:
        card_props["style"] = card_props["style"].replace("250px", height)
        card_props["height"] = height

    with vuetify3.VCard(**card_props):
        with vuetify3.VToolbar(
            density="compact",
            classes="bg-blue-grey-lighten-5 flex-grow-0",
            color="blue-grey-darken-2",
        ):
            vuetify3.VIcon(icon, classes="mr-3")
            vuetify3.VToolbarTitle(title, classes="text-subtitle-1 font-weight-medium")

        return vuetify3.VCardText(
            classes="pa-3 flex-grow-1 overflow-y-auto",
        )
