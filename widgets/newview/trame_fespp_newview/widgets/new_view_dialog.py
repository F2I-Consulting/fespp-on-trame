from trame_client.widgets.core import AbstractElement

from trame_fespp_newview import module


class HtmlElement(AbstractElement):
    def __init__(self, _elem_name, children=None, **kwargs):
        super().__init__(_elem_name, children, **kwargs)
        if self.server:
            self.server.enable_module(module)


__all__ = ["NewViewDialog", "ViewsDoor"]


class NewViewDialog(HtmlElement):
    """What a second 3D view starts from: nothing, or another view.

    Copying the current view is right when you want the same thing twice
    side by side, and wrong when you want a clean view to build something
    else in, so the dialog lets the reader choose.

    Props:
        open        the dialog is up
        views       [{id, title, globe}] the render views on offer; a Globe
                    view is not one (its camera lives in ECEF)
        default_from  the view to propose copying, normally the active one
    Events:
        create(source_id)  "" for an empty view, else the view to copy
        close()
    """

    def __init__(self, **kwargs):
        super().__init__("new-view-dialog", **kwargs)
        self._attr_names += ["open", "views", ("default_from", "defaultFrom")]
        self._event_names += ["create", "close"]


class ViewsDoor(HtmlElement):
    """The top bar's door to the 3D views: a pop-over with one tile per 3D
    view — a click makes it the active view (shown again first when hidden),
    its eye hides it (out of the screen, everything kept) or shows it again
    where it was — and a "+" tile for a new one. The Globe has its own door
    and is not listed.

    Props:
        views   [{id, title, globe, hidden}] the render views
        active  the active view's id
        title   the button's tooltip
    Events:
        activate(id)  make that view the active one
        toggle(id)    hide or show that view
        add()         open a new 3D view
    """

    def __init__(self, **kwargs):
        super().__init__("views-door", **kwargs)
        self._attr_names += ["views", "active", "title"]
        self._event_names += ["activate", "toggle", "add"]
