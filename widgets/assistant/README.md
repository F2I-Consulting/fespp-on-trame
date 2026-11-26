# trame-fespp-assistant

The **Assistant**: a chat panel in which a sentence, in French or in English,
becomes one command of the host application — "montre la porosité de
Geogrid", "filter porosity above 0.2", "annule". The panel draws the
conversation and the field; the controller (`trame_fespp_assistant/controller.py`)
holds the conversation — what to ask back, what runs, what can be undone —
and a HOST adapter, the only place that knows the application, parses the
sentence and carries the command out. Nothing leaves the server: the host's
parser is local.

## Contract

```
props   data   {messages, busy, can_undo, lang, examples}
               messages  [{id, role: user|assistant, text,
                           level: info|ok|ask|error        (assistant only)
                           rows: [[label, value], ...]     (optional, a small table)
                           choices: [{id, label}]         (optional buttons)
                           undoable: bool}]               (its action can be undone)
               busy      a command is running: the 2 px bar, Send / Undo /
                         examples / choices / Clear held
               can_undo  something can be undone
               lang      fr | en, the language of the last sentence
               examples  [str]  sentences shown, and sent on a click, while
                                the conversation is empty
events  ask(text)     a sentence typed (Enter or Send) or an example clicked
        choose(id)    a button of the LAST message: "intent:<name>",
                      "instead:<name>", "target:<path>", "category:<value>",
                      "exclude:true" / "exclude:false", "none", "undo",
                      "cancel"
        undo(id)      the Undo of the reply `id`: undo its action
        clear()       empty the conversation (what was done in the views stays)
```

Only the last message's choices are drawn: an older question was answered, or
a new sentence replaced it. The Undo button sits on the message whose action
is on top of the undo stack, and sends that message's id.

The field: Enter sends, Shift+Enter starts a new line, it empties once its
request is sent, and it holds 500 characters (the controller's `MAX_TEXT`).
The list follows the newest message. A gesture sent holds the buttons that
would send another (examples, choices, Undo, Send) until the controller's
state answers — its busy bar or its reply — so a double click sends once;
the hold lifts by itself after 2 s if the controller ignored the gesture.

## The controller

```python
from trame_fespp_assistant.controller import AssistantController, detect_language

ctl = AssistantController(server, host)          # state var "ui_assistant"
AssistantPanel(data=(ctl.data_var,), ask=(ctl.ask, "[$event]"),
               choose=(ctl.choose, "[$event]"), undo=(ctl.undo, "[$event]"),
               clear=ctl.clear)
```

`undo` must be wired with `"[$event]"`: the controller undoes only when the id
is the reply of the action on top of the stack, and ignores a stale click (a
double click, a click that crossed the first one's reply) instead of undoing
an older action. Called without an id (`ctl.undo()`, a panel wired `"[]"`),
it undoes the last action, whichever it is.

A sentence goes: parsed by the host → not understood (an error, with three
examples) / unclear ("Did you mean…?", one button per likely command and
Cancel) / lacking something (the host's own question, whose buttons may name
objects) / run. A question (`host.readonly`) is answered, a gesture is
executed and, when the host hands back an undo token, can be undone (the
last 20 whose reply is still in the conversation: a reply trimmed out of the
200 messages kept takes its undo with it). A typed "annule" / "undo" undoes
too: the stack lives in the controller. Every reply is in the sentence's
language, French or English (`detect_language`); a sentence that says
neither keeps the conversation's. A sentence over 500 characters is not
parsed: it is refused with a short reply, and only its beginning is kept.

A sentence that holds several requests ("show X and switch to viridis")
runs them in order, each with its own reply and undo. The host gives the
words of the later ones (`then`), which the controller has it parse when
their turn comes — after the request before has run, so "…then the wells
that cross them" knows the zone just kept. A host with the optional
`parse_next` reads them there, knowing they are later requests of one
sentence ("hide the oil zone then the gas" adds the gas to the values just
hidden). A failure stops the sentence and says the rest was not done; so
does a request not read when there is no local AI, and so does a host call
that raises, the local AI's included.

When a command names values whose polarity nothing said, the host may ask
with the buttons "exclude:true" (hide them) and "exclude:false" (keep only
them): the controller puts the choice in the command's `slots["exclude"]`.

A sentence that leaves a choice between gestures (`choose_between`) is
asked about — unless the host marks the command `run_first`: the first
gesture then runs at once (the application filters by default rather than
asking "filter or highlight?"), and its reply offers each other gesture as
an "instead:<name>" button, worded by the host's optional `instead_label`
("Highlight instead"), then Cancel ("undo"). "instead:<name>" undoes the
gesture that ran and runs that one with the same words. The offer is made
only when nothing of the sentence follows, and only when the first gesture
lacks nothing — otherwise the choice is asked as usual.

With a local AI (`host.llm_available()`), a request the host's parser did
not read goes to it — that request alone, the rest of the sentence waiting
for its command, which is then run or asked about like the parser's. The
host prepares the call on the event loop (`llm_prepare`: what the AI is
told is read from the application there), only the HTTP call runs in a
thread, and its answer becomes a command back on the loop (`llm_finish`).
A call that failed says so, with its reason; when the AI is configured but
out, "not understood" says why (`llm_problem`). A host with `llm_reason`
puts those reasons in the reader's words (a timeout, a refused connection,
a full queue, a model loading), and the waiting message gives the longest
the host waits (`llm_wait_s`, in seconds) when it says it.

A "target:<path>" button is resolved when it is clicked, against the host's
candidates then — they come from live state (the view's active property
narrows a grid's properties to itself). When the host has the optional
`objects()` (every object of the data now), an object no longer among the
candidates but still in the data is used as clicked; one gone from the data
is refused ("… is no longer available: nothing done") and the question is
asked again with the candidates of now. A choice is never run with no
target.

### Busy, and calling it from code

A command runs with `busy` up. Inside a trame event the state reaches the
browser only once the handler returns, so when an event loop is running the
gesture publishes the bar, flushes it, and the host's work runs as an
asyncio task one loop turn later (20 ms, as `_defer` in app/boot.py): the bar
is on screen during the work, and `ask` / `choose` / `undo` return before
the reply exists. A caller inside the loop that reads the reply (a headless
scenario) awaits `await ctl.idle()`, or polls `state.ui_assistant` for the
reply (the reply and `busy: false` land in the same state push). Without a
running loop (a script, a unit test) the same calls run through and the
reply is in the state on return.

While a command runs, `ask`, `choose`, `undo` and `clear` are ignored (and
said so in the log): the panel holds its buttons, and what still arrives is
a click that crossed the busy state on the wire.

The host protocol is written out in the controller's docstring. The optional
`host.examples_watch` names state vars after whose change the examples are
asked again (they are built from the loaded data); `ctl.refresh_examples()`
does the same by hand.

The conversation lives on the server for the session and is not saved.

## Test hooks

`[data-fp-assistant]` the panel · `[data-fp-assistant-input]` the field ·
`[data-fp-assistant-send]` Send · `[data-fp-assistant-msg]` each message, with
`data-role` and (assistant) `data-level` · `[data-fp-assistant-choice]` with
`data-choice-id` · `[data-fp-assistant-undo]` · `[data-fp-assistant-clear]` ·
`[data-fp-assistant-example]`.

## Build

```
cd vue-components && npm install && npm run build
# -> trame_fespp_assistant/module/serve/{*.umd.js, style.css}
```
