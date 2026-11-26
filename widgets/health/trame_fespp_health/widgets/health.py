from trame_client.widgets.core import AbstractElement

from trame_fespp_health import module


class HtmlElement(AbstractElement):
    def __init__(self, _elem_name, children=None, **kwargs):
        super().__init__(_elem_name, children, **kwargs)
        if self.server:
            self.server.enable_module(module)


__all__ = ["HealthPanel"]


class HealthPanel(HtmlElement):
    """Data health: what is wrong with the loaded data, in one table.

    Props in are the payload engine/health_dispatch builds; events out are
    the reader's requests. The host computes, the panel only filters.

    Props::

        data  {summary: {errors, warnings, infos, objects, partial, types, files},
               findings: [{severity, category, object, path, message, count}],
               note, csv: {name, header}}
        focus_on {text, n}  — put this object's name in the text filter. The
               table is the session's only findings table, so "show me that
               object" is a filter, not a table of its own; `n` changes on
               every request, so the same object asked for twice is applied
               twice.

    Events::

        refresh()
        activate(path)   — a row's object, to make it the active tree node
    """

    def __init__(self, **kwargs):
        super().__init__("health-panel", **kwargs)
        self._attr_names += ["data", ("focus_on", "focus")]
        self._event_names += ["refresh", "activate"]
