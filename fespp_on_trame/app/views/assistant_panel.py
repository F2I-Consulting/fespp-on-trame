"""AssistantPanel — the ``assistant`` view kind: the application asked in
plain French or English ("show the porosity of Geogrid", "open
statistics"), one command per sentence, and the reply says what was done.

Mount point only: the conversation is the decoupled
``trame_fespp_assistant`` widget (``widgets/assistant``). Its controller
(``AssistantController``, built in ``__main__``) owns ``ui_assistant`` and
reaches the application only through ``app/assistant_host`` — the one place
that knows the tree and the controllers. Its four gestures are the
controllers ``assistant_ask`` / ``assistant_choose`` / ``assistant_undo`` /
``assistant_clear``.

Singleton: one conversation for the session. It outlives a close (the state
var is session-wide) and is not saved in a session file.
"""
from trame.widgets import html
from trame_fespp_assistant.widgets import AssistantPanel as _AssistantWidget


class AssistantPanel:
    """The assistant widget mounted in one panel, wired to the four
    assistant controllers."""

    def __init__(self, server, view_id):
        self.server = server
        self.view_id = str(view_id)
        ctrl = server.controller
        with html.Div(style="height:100%; width:100%; background:#fff;"
                            " display:flex; flex-direction:column;"):
            _AssistantWidget(
                data=("ui_assistant", {}),
                # the sentence typed (or an example clicked), a button of
                # the last reply, the reply's Undo, the panel's Clear
                ask=(ctrl.assistant_ask, "[$event]"),
                choose=(ctrl.assistant_choose, "[$event]"),
                undo=(ctrl.assistant_undo, "[$event]"),
                clear=(ctrl.assistant_clear, "[]"),
            )
        self.html_view = None  # non-render kind
