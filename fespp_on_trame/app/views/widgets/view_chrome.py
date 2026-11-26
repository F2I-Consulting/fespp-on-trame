"""What a view draws over the dock's tab row: its chrome, centred between its
tab and the dock's buttons at the row's right end (dock left, right, top,
bottom, detach, close: `HEADER_BUTTONS`). The chrome's place is the one rule for
all of them (the 3D view's strip, the time-depth model's zoom).
"""

ROW = "var(--dv-tabs-and-actions-container-height, 35px)"
# the buttons the dock draws at the right end of every tab row, views and cards
HEADER_BUTTONS = ["left", "right", "top", "bottom", "float", "close"]
# their width, left free by the chrome
_BUTTONS = 24 * len(HEADER_BUTTONS) + 8


def chrome_place(left):
    """The style of a view's chrome in the tab row, from `left` px on. Only its
    controls take the pointer: the empty part of the row is what a detached view
    is moved by."""
    return (f"position:absolute; top:calc(-1 * {ROW}); height:{ROW};"
            f" left:{left}px; right:{_BUTTONS}px; z-index:6; pointer-events:none;")


def chrome_tools(left):
    """The style of a view's tools in its tab row, from `left` px on, centred
    (a panel's zoom: the time-depth model's, the log view's)."""
    return (chrome_place(left) + " display:flex; align-items:center;"
            " justify-content:center; gap:4px; container-type:inline-size;")


def fill_on_double_click(server):
    """The dock's double click: a floating window's tab row is its title bar. The
    window fills the dock at once; the rest is the server's (app/views/dock_fill)."""
    trigger = server.controller.trigger_name(server.controller.view_fill)
    return ("const row = $event.target.closest('.dv-tabs-and-actions-container');"
            # a tab row of this dock, not of a dock inside one of its panels
            " const own = row && row.closest('.fp-views, .fp-cards') === $event.currentTarget;"
            " const win = own && row.closest('.dv-resize-container');"
            " const tab = win && row.querySelector('.dv-tab.dv-active-tab');"
            " if (tab) { win.classList.add('fp-filled');"
            f" trigger('{trigger}', [tab.innerText.trim()]); }}")

