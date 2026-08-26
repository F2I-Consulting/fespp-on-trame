"""Global CSS injected once into the app layout.

`trame_client.Style` adds a real <style> element to the document head
(unlike `html.Style`, which is bound inside the trame app body and
sometimes loses its specificity in transient mounts)."""
from trame.widgets import client as trame_client


def inject_global_styles() -> None:
    """Inject the three CSS blocks the app relies on."""

    # Vertical centering fix for ptc components.
    trame_client.Style(".te-align-center .v-row { align-items: center; }")

    # The AppBar title ("FESPP on TRAME") is a flex item Vuetify lets
    # shrink with an ellipsis — at exactly 100% browser zoom the flex
    # rounding truncated it while 90% / 110% showed it whole. Pin it
    # to its natural width.
    trame_client.Style(
        ".v-app-bar .v-toolbar-title {"
        "  flex: 0 0 auto;"
        "  min-width: max-content;"
        "}"
    )

    # Hide the default trame footer. The --v-layout-bottom reset stops
    # Vuetify reserving space for the now-hidden footer.
    trame_client.Style(
        "footer, .v-footer {"
        "  display: none !important;"
        "  height: 0 !important;"
        "  min-height: 0 !important;"
        "  overflow: hidden !important;"
        "}"
        ".v-layout { --v-layout-bottom: 0 !important; }"
    )

    # Let per-panel action chrome (negative top offset) overflow
    # upward into the dockview tab row instead of being clipped. Scoped
    # to the immediate content wrappers, not the group, to avoid
    # breaking dockview's own internals.
    trame_client.Style(
        ".dv-content-container,"
        " .dv-active-panel-wrapper,"
        " [class*='dv-content-container'],"
        " [class*='dv-active-panel'] {"
        "   overflow: visible !important;"
        " }"
    )

    # Floating Stats minimize: collapse the shell to one tabstrip row
    # and ~240px wide. The mirror `.dv-render-overlay-float` element
    # needs the same pin because dockview's resize observer copies the
    # shell's bounding rect onto it. Resize handles are disabled so a
    # drag can't leak a new size into the inline style and break
    # restore.
    trame_client.Style(
        "body.fespp-stats-minimized"
        " .dv-resize-container:has(.fespp-stats-panel),"
        " body.fespp-stats-minimized"
        " .dv-render-overlay-float:has(.fespp-stats-panel) {"
        "   height: calc(var(--dv-tabs-and-actions-container-height, 35px) + 3px) !important;"
        "   min-height: calc(var(--dv-tabs-and-actions-container-height, 35px) + 3px) !important;"
        "   width: 240px !important;"
        "   min-width: 240px !important;"
        " }"
        " body.fespp-stats-minimized"
        " .dv-resize-container:has(.fespp-stats-panel)"
        " [class*='dv-resize-handle'] {"
        "   pointer-events: none !important;"
        " }"
    )

    # Floating Stats maximize: pin top/left/width/height so the shell
    # covers the full dockview container. `.dv-resize-container` is
    # position:absolute inside the dockview gridview, so 100% reaches
    # the gridview's bounds. Same resize-handle disable as minimize.
    trame_client.Style(
        "body.fespp-stats-maximized"
        " .dv-resize-container:has(.fespp-stats-panel),"
        " body.fespp-stats-maximized"
        " .dv-render-overlay-float:has(.fespp-stats-panel) {"
        "   top: 0 !important;"
        "   left: 0 !important;"
        "   right: auto !important;"
        "   bottom: auto !important;"
        "   width: 100% !important;"
        "   height: 100% !important;"
        "   min-width: 0 !important;"
        "   min-height: 0 !important;"
        " }"
        " body.fespp-stats-maximized"
        " .dv-resize-container:has(.fespp-stats-panel)"
        " [class*='dv-resize-handle'] {"
        "   pointer-events: none !important;"
        " }"
    )

    # Match the dockview tab row to the drawer card title style.
    # Container and every tab variant land on blue-grey-darken-2
    # (#455A64) with white text; hidden tabs nudge to #546E7A as an
    # active/inactive cue. Themes declare these vars on `.dv-theme-*`,
    # so the selector also lists `.dv-dockview` to win regardless of
    # which theme prop ptc passes.
    trame_client.Style(
        ".dv-dockview,"
        " .dv-theme-dracula,"
        " .dv-theme-dark,"
        " .dv-theme-light,"
        " .dv-theme-abyss,"
        " .dv-theme-abyss-spaced,"
        " .dv-theme-replit,"
        " .dv-theme-visual-studio,"
        " .dv-theme-light-spaced {"
        "   --dv-tabs-and-actions-container-background-color: #455A64;"
        "   --dv-activegroup-visiblepanel-tab-background-color: #455A64;"
        "   --dv-inactivegroup-visiblepanel-tab-background-color: #455A64;"
        "   --dv-activegroup-hiddenpanel-tab-background-color: #546E7A;"
        "   --dv-inactivegroup-hiddenpanel-tab-background-color: #546E7A;"
        "   --dv-activegroup-visiblepanel-tab-color: #ffffff;"
        "   --dv-inactivegroup-visiblepanel-tab-color: rgba(255,255,255,0.9);"
        "   --dv-activegroup-hiddenpanel-tab-color: rgba(255,255,255,0.65);"
        "   --dv-inactivegroup-hiddenpanel-tab-color: rgba(255,255,255,0.55);"
        "   --dv-tabs-container-scrollbar-color: rgba(255,255,255,0.3);"
        " }"
    )
