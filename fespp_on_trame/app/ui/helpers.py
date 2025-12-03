from trame.widgets import vuetify3 as vuetify3, html


def create_card(title, icon, height=None):
    """
    Creates a Vuetify VCard that is vertically resizable (CSS resize: vertical).
    The content (VCardText) adapts to the new height and is scrollable.
    """

    # 1. Base Card Properties (Flat, Bordered + Resizable)
    card_props = {
        "classes": "pa-0 mb-4 border d-flex flex-column",
        "elevation": 0,
        "flat": True,
        "tile": False,
        "style": "resize: vertical; overflow: hidden; min-height: 250px;",
    }

    # Handling initial height
    if height:
        card_props["style"] = card_props["style"].replace("250px", height)
        card_props["height"] = height

    with vuetify3.VCard(**card_props):
        # 2. Styled Title Section (VToolbar)
        with vuetify3.VToolbar(
            density="compact",
            classes="bg-blue-grey-lighten-5 flex-grow-0",
            color="blue-grey-darken-2",
        ):
            vuetify3.VIcon(icon, classes="mr-3")
            vuetify3.VToolbarTitle(title, classes="text-subtitle-1 font-weight-medium")

        # 3. Adaptive and Scrollable Content Area
        return vuetify3.VCardText(
            classes="pa-3 flex-grow-1 overflow-y-auto",
        )
