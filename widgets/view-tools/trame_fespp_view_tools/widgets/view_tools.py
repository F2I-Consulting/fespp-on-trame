from trame_client.widgets.core import AbstractElement

from trame_fespp_view_tools import module


class HtmlElement(AbstractElement):
    def __init__(self, _elem_name, children=None, **kwargs):
        super().__init__(_elem_name, children, **kwargs)
        if self.server:
            self.server.enable_module(module)


__all__ = ["ViewToolbar"]


class ViewToolbar(HtmlElement):
    """Per-view toolbar — a strip of toggle buttons, one per tool.

    Props:
        tools  : [{key, icon, title}] — the buttons to show
        open   : [tool keys] — which tools are currently open
        badges : [tool keys] — marked with a green "running" play badge
                 (e.g. the view's time animation plays while its card is
                 closed)
    Event:
        toggle(tool_key)

    The host owns the open-set in PER-VIEW state and shows/hides the matching
    FloatingCards.
    """

    def __init__(self, **kwargs):
        super().__init__("view-toolbar", **kwargs)
        self._attr_names += ["tools", "open", "actions", "badges"]
        self._event_names += ["toggle", "action"]
