from trame_client.widgets.core import AbstractElement

from trame_fespp_assistant import module


class HtmlElement(AbstractElement):
    """Base element that registers the widget's Vue module with the server."""

    def __init__(self, _elem_name, children=None, **kwargs):
        super().__init__(_elem_name, children, **kwargs)
        if self.server:
            self.server.enable_module(module)


__all__ = ["AssistantPanel"]


class AssistantPanel(HtmlElement):
    """The Assistant panel: a conversation in which a French or English
    sentence becomes one command of the host application.

    The panel draws the messages, the buttons of the last one and the
    field; the conversation itself (parsing, asking back, running,
    undoing) belongs to the controller (`trame_fespp_assistant.controller`).
    It knows nothing of the application: props in, events out.

    Props:
        data    the controller's state var, see the README::

                {messages: [{id, role: user|assistant, text,
                             level: info|ok|ask|error, rows: [[label, value]],
                             choices: [{id, label}], undoable}],
                 busy, can_undo, lang: fr|en, examples: [str]}

                Only the LAST message's choices are drawn; the Undo button
                sits on the message whose action can be undone.
    Events:
        ask(text)        a sentence typed (Enter or Send) or an example clicked
        choose(id)       a button of the last message ("intent:…", "target:…",
                         "category:…", "none", "undo", "cancel")
        undo(id)         undo the action of reply `id` (only while it is the last one)
        clear()          empty the conversation
    """

    def __init__(self, children=None, **kwargs):
        super().__init__("assistant-panel", children, **kwargs)
        self._attr_names += ["data"]
        self._event_names += ["ask", "choose", "undo", "clear"]
