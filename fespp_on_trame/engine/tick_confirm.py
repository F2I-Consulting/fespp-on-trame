"""The one question the application asks before a tick reads a lot at once.

A checkbox in a tree means "read this object and keep it in the session"
(common to every view) and, in a panel's own tree, "put it in this panel"
as well. The box also asks before an untick unloads what another view is
using (`unload_question`). A FOLDER stands
for its whole subtree, so ONE click can stand for dozens of reads, each of
which, in the data tree, also pulls its representation into the 3D view.
Above :data:`MAX_TICK_LOAD` unread properties — the well logs weighed
instead by their values, above :data:`MAX_LOG_VALUES` (the nodes of their
frames: a frame's logs cost by their length, not their number) — the tick
states its size and waits for an answer instead of starting a read the reader could neither see
coming nor stop: nothing is read before the yes, and a no puts the boxes
back where they were.

The threshold and the words live HERE and nowhere else. The data tree, the
Statistics tree and the well-log tree ask the same
question with the same number, or the box would be a surprise in one tree
and a habit in another. The one thing that differs is where the read
lands, and the box says it: the 3D view for the data tree, the panel alone
for a panel's tree.

The box itself is drawn once, in the application layout
(``fespp_on_trame.__main__``), from ``state.ui_tick_confirm``, with the
shared ``fp-scrim`` / ``fp-dialog`` of ``widgets/_shared/panel.css``.
"""
import re

from fespp_on_trame.engine.utils import numfmt

#: Above how many UNREAD properties one tick asks first. Twenty: a kind
#: folder of a real file holds dozens of properties, so an unbounded read is
#: always announced, while an ordinary folder stays immediate.
MAX_TICK_LOAD = 20

#: Above how many values of well logs one tick asks first, whatever the
#: number of logs: a log holds as many values as its frame has nodes, and the
#: read goes by the values (drogon, 23/11: one log of a 15 556-node frame
#: 0.7 s, its 21 logs read 3.5 s, some 7.5 µs a value). Some two seconds
#: and a half.
MAX_LOG_VALUES = 250_000

# fesapi writes the element with attributes (`xmlns:xsd=…`)
_NODE_COUNT = re.compile(r"<(?:[\w.-]+:)?NodeCount\b[^>]*>\s*(\d+)\s*<")


def node_count(xml):
    """The nodes of a log frame its XML says (the values of each of its
    logs); 0 when it says none."""
    found = _NODE_COUNT.search(xml or "")
    return int(found.group(1)) if found else 0


_NIJK = re.compile(r"<(?:[\w.-]+:)?N([ijk])\b[^>]*>\s*(\d+)\s*<", re.I)


def ijk_cells(xml):
    """The cells of an IJK grid its XML says (Ni × Nj × Nk); 0 when it does
    not say them all."""
    n = {k.lower(): int(v) for k, v in _NIJK.findall(xml or "")}
    return n.get("i", 0) * n.get("j", 0) * n.get("k", 0)


def asks(properties, log_values):
    """Whether a tick asks first: more unread `properties` than
    MAX_TICK_LOAD, the logs aside, or more `log_values` than
    MAX_LOG_VALUES, the values of the unread logs."""
    return properties > MAX_TICK_LOAD or log_values > MAX_LOG_VALUES


def question(count, shown=True, remote=False, objects=False, values=0):
    """The ``{title, body, ok}`` the shared dialog renders for `count`
    properties about to be read: one wording, whichever tree asked, but
    for the consequence. `shown` is the data tree, whose read also lands in
    the 3D view; a panel's tree reads into the panel and shows nothing.
    `objects`: the count holds more than properties (the parts of a grid).
    `values`: the values of the well logs among them, said first.

    `remote` is a read from an ETP / OSDU server: there EVERY object is a
    download (a surface, a well, a grid as well as a property), so the
    count is of objects, and the box says how the read goes (one after the
    other, visible as they arrive, stoppable)."""
    if remote:
        what = numfmt.plural(count, "object", "objects")
        return {
            "title": f"Download {what} from the server?",
            "body": ("They arrive one after the other and show as they come;"
                     " Stop, at the bottom of the view, ends the download and"
                     " keeps what has arrived. Nothing has been read yet."),
            "ok": f"Download {what}",
        }
    what = (numfmt.plural(count, "object", "objects") if objects
            else numfmt.plural(count, "property", "properties"))
    if shown:
        body = ("Reading them also puts them, and the representations they"
                " belong to, in the 3D views. Nothing has been read yet.")
    else:
        body = ("Reading them puts them in this panel, not in the 3D views:"
                " open an eye in a 3D view's data tree to show one there."
                " Nothing has been read yet.")
    if values:
        body = f"Their well logs hold {numfmt.fmt_int(values)} values. " + body
    return {
        "title": f"Read {what}?",
        "body": body,
        "ok": f"Read {what}",
    }


def _names(items, cap=3):
    """'A', 'A and B', 'A, B and C', 'A, B and 2 others'."""
    items = [str(i) for i in items if i]
    if len(items) > cap:
        rest = len(items) - (cap - 1)
        items = items[:cap - 1] + [f"{rest} others"]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def unload_question(names, views):
    """The ``{title, body, ok}`` asked before an untick unloads objects that
    another view is using (the PO, 18/10: a checkbox is the session's load,
    common to every view, so unticking it takes the data out of every view
    showing it — said first, with where).

    `names` are the objects unticked (their titles), `views` the titles of
    the views using them, the view the untick came from left out."""
    what = _names(names) or "This data"
    where = _names(views)
    many = len([n for n in names if n]) > 1
    return {
        "title": f"Unload {what}?",
        "body": (f"{'They are' if many else 'It is'} used in {where}. If you"
                 f" confirm, {'they are' if many else 'it is'} unloaded from"
                 f" the session and removed from {where}."),
        "ok": "Unload",
    }
