"""A view's own dock of cards: the view's content is its fixed centre, each card
a panel of it (the 3D view's tool cards, the log view's zone statistics). One
dock for every view that carries cards, so their tab rows, their buttons
(`HEADER_BUTTONS`) and their close are the same everywhere.

The centre's content is built in an ``FpDockSlot(slot_key=center_slot(vid))``
and each card's in a ``FloatingCard(in_panel=True, panel_slot=card_slot(vid,
key))``, both kept in a hidden reservoir: each moves into its panel while
that panel exists.
"""
from trame.widgets import html
from trame_fespp_dock.widgets import FpDock

from fespp_on_trame.app.views.widgets.view_chrome import HEADER_BUTTONS
from fespp_on_trame.engine import tree_families

# the cards that act on the active node of a tree: they open docked under
# that tree's card, split below its panel
UNDER_TREE = ("timereal", "slicers", "thresholds")
# the cards that open as tabs of one another: the Geometry slicer and the
# Property slicer, together at the bottom left
TABBED = (("slicers", "thresholds"),)


def center_slot(vid):
    """The slot the view's content moves into: the dock's centre."""
    return f"{vid}:__center__"


def card_slot(vid, key):
    """The slot the content of the card `key` moves into."""
    return f"{vid}:{key}"


def card_spec(vid, key, title, width=260, height=0, side=None):
    """What the dock makes the card `key`'s panel with (FpDock panel_specs):
    its tab title, its first size (0: the dock's) and the side of the centre
    it first opens on (None: left)."""
    spec = {"title": title, "initialWidth": width, "initialHeight": height,
            "minimumWidth": 180, "minimumHeight": 120, "slot": card_slot(vid, key)}
    if side:
        spec["side"] = side
    return spec


def tree_anchor(key, open_keys, active_tree=""):
    """The tree card the card `key` opens under: `active_tree` (the card of
    the view's active node) when it is open, else the first tree card open;
    "" for a card not of `UNDER_TREE` or with no tree card open, which the
    dock places as it places any card."""
    if key not in UNDER_TREE:
        return ""
    trees = [k for k in open_keys or () if k in tree_families.KEYS]
    if active_tree in trees:
        return active_tree
    return trees[0] if trees else ""


def tab_mate(key, open_keys):
    """The open card the card `key` opens beside as a tab (`TABBED`): the
    other slicer when it is open; "" for none."""
    for group in TABBED:
        if key in group:
            for other in group:
                if other != key and other in (open_keys or ()):
                    return other
    return ""


def anchored_specs(specs, key, anchor, mate=""):
    """`specs` (card id -> card_spec) with the card `key` opening as a tab
    beside the panel `mate` (FpDock's `with`) when it is docked, else below
    the panel `anchor` (FpDock's `below`), or where the dock places it when
    both are ""."""
    out = dict(specs or {})
    spec = out.get(key)
    if not isinstance(spec, dict):
        return out
    spec = {k: v for k, v in spec.items() if k not in ("below", "with")}
    if mate:
        spec["with"] = mate
    if anchor:
        spec["below"] = anchor
    out[key] = spec
    return out


def card_dock(vid, panels, specs, close, layout, visibility=None, reveal=None, active=None):
    """The dock, in a box taking the room left to it in a flex row.

    `panels`: a JS expression, the ids of the open cards; `specs`: a JS
    expression, {id: card_spec(...)}; `close`: the panel_close_request
    handler (the card asks to close, the host takes it out of `panels`);
    `layout`: the state var the dock's layout is kept in, read back when the
    dock is ready (a reload, a session reopened); `visibility`: the handler
    told when a card comes on screen or goes behind a tab; `reveal`: the state
    var ({id, n}) naming the card to bring in front; `active`: the handler told
    the card in use (its id)."""
    with html.Div(style="flex:1 1 0; height:100%; min-width:0; position:relative;"
                        " isolation:isolate;"):
        FpDock(
            ref=f"fp_cards_{vid}",
            classes="fp-cards",
            theme="Light",
            center=center_slot(vid),
            panels=(panels,),
            panel_specs=(specs,),
            panel_close_request=close,
            floating_group_drag_handle="tabbar",
            floating_group_bounds="boundedWithinViewport",
            header_buttons=(repr(HEADER_BUTTONS),),
            layout=(layout,),
            layout_changed=f"{layout} = $event",
            **({"panel_visibility": visibility} if visibility else {}),
            **({"reveal": (reveal,)} if reveal else {}),
            **({"active_panel": active} if active else {}),
        )
