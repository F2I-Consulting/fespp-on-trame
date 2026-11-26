from trame_client.widgets.core import AbstractElement

from trame_fespp_view_tools import module


class HtmlElement(AbstractElement):
    """Base element that registers this package's Vue module with the server."""

    def __init__(self, _elem_name, children=None, **kwargs):
        super().__init__(_elem_name, children, **kwargs)
        if self.server:
            self.server.enable_module(module)


__all__ = ["ViewToolbar"]


class ViewToolbar(HtmlElement):
    """Per-view toolbar: a strip of toggle buttons, one per tool.

    Props:
        tools   : [{key, icon, title, disabled}] - the toggle buttons; a
                  disabled tool is drawn but inert, its title saying why
        open    : [tool keys] - which tools are currently open
        actions : [{key, icon, title}] - one-shot buttons below the tools
                  (e.g. reset camera)
        badges  : [tool keys] - marked with a green "running" play badge
                  (e.g. the view's time animation plays while its card is
                  closed)
    Events:
        toggle(tool_key), action(action_key)

    The host owns the open-set in per-view state and shows/hides the matching
    FloatingCards.
    """

    def __init__(self, **kwargs):
        super().__init__("view-toolbar", **kwargs)
        self._attr_names += ["tools", "open", "actions", "badges"]
        self._event_names += ["toggle", "action"]
