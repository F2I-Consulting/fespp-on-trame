from trame_client.widgets.core import AbstractElement, Template

from trame_fespp_reconcile import module

# The `tools` slot (the host's tree button, at the end of the header bar)
# must be declared to trame's `Template` before a caller can write
# `v_slot_tools=True`: an unregistered name is rendered into the DEFAULT slot,
# and the button lands, invisible, in the panel body.
Template.slot_names.add("tools")


class HtmlElement(AbstractElement):
    def __init__(self, _elem_name, children=None, **kwargs):
        super().__init__(_elem_name, children, **kwargs)
        if self.server:
            self.server.enable_module(module)


__all__ = ["ReconcilePanel"]


class ReconcilePanel(HtmlElement):
    """Well ↔ model reconciliation by property kind.

    Props in are the payload engine/reconcile_dispatch builds; events out are
    the reader's requests. The host computes, the panel shows and sorts.

    Props::

        data  {rows, pairs, auto, logs, props, wells, note, step,
               min_samples, csv}

    Events::

        compute([step])
        auto_pairs()
        set_pairs([{log, prop, basis}, ...])

    Slots::

        tools   the end of the header bar: the host's tree button
    """

    def __init__(self, **kwargs):
        super().__init__("reconcile-panel", **kwargs)
        self._attr_names += ["data"]
        self._event_names += ["compute", "auto_pairs", "set_pairs"]
