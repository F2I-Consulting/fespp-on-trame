"""The active node of the 3D views (overhaul slice 5, Q4).

A view's active node is two state variables, written together here:
`active_path__<vid>`, the node the cards follow (Values, Colormap, the
Attributes card's arrays), and `active_by_tab__<vid>`, the active node of
each tab of its tree ("reservoir", ...). The tree's click writes them from
the browser; every server-side writer goes through `activate`, `restore`
or `clear`.

`target_of(vid, tool)` says which representation a card acts on — the
Slicers (an IJK grid), the Thresholds (an isolatable representation: a
grid, a surface, a polyline or point set...), the Volumetrics (cells with a
volume): the view's active node when it qualifies, else the Reservoir
tab's, else the first loaded representation that does. The active node
comes first since the Thresholds reach surfaces (27/10): a surface clicked
in the Surface tab is what the card acts on, not the grid of another tab.
One rule for the three cards, the titles they show and the controllers
they call (04-verification D14). Since 28/10 a slicer card names its object
in a list of its own (`pin`, `targets`): a pinned object comes before the
active node.

A tick on a leaf makes it active in the tree. A tick on a folder leaves the
active node where it is: the Values card reads what the folder holds instead
(`ticked`, `values_update`, `values_path`), and so it does on a folder that
is the active node."""
import re

from fespp_on_trame.engine import node_facts, node_kinds

SLICERS = "slicers"
THRESHOLDS = "thresholds"
VOLUMETRICS = "volumetrics"


def _natural(title):
    """Sort key of a title, its numbers as numbers: the tree's own order."""
    return [int(s) if s.isdigit() else s.casefold() for s in re.split(r"(\d+)", title or "")]


def folder_reading(read, eyes, kind_of, title_of):
    """The node the Values card reads for a folder, `read` being the paths
    read under it and `eyes` the view's open eyes: the one property whose eye
    is open; else — several of them, or none — the first geometry or
    trajectory by title; "" when it holds neither."""
    props = [p for p in read if p in eyes and node_facts.is_property_kind(kind_of(p))]
    if len(props) == 1:
        return props[0]
    drawn = [p for p in read if kind_of(p) in node_kinds.GEOMETRY_KINDS]
    return min(drawn, key=lambda p: _natural(title_of(p))) if drawn else ""


def well_node_to_open(state):
    """The node a log view's tree opens on when the gesture that opened it
    named none: the active node of the Well card of the 3D view used last
    (else of another 3D view open), its eye open or not; "" when none."""
    live = [p.get("id") for p in (getattr(state, "fespp_render_panels", None) or [])
            if p.get("id") and not p.get("globe")]
    last = getattr(state, "fespp_last_render_panel_id", None) or ""
    for vid in ([last] if last in live else []) + [v for v in live if v != last]:
        path = (getattr(state, f"active_by_tab__{vid}", None) or {}).get("well")
        if path:
            return path
    return ""


class Activation:
    """The active nodes of the session's 3D views, one writer for all."""

    def __init__(self, state, rep_path_of, qualifies, loaded, views=None,
                 kind_of=None, title_of=None):
        """`rep_path_of(path)`: a node's representation ("" or None when it
        has none); `qualifies(tool, rep_path)`: whether that card can act
        on it; `loaded()`: the loaded representations, in their order;
        `views()`: the live 3D views; `kind_of(path)`, `title_of(path)`: a
        node's type and the name it is shown by."""
        self._state = state
        self._rep_path_of = rep_path_of
        self._qualifies = qualifies
        self._loaded = loaded
        self._views = views or (lambda: [])
        self._kind_of = kind_of or (lambda _path: "")
        self._title_of = title_of or (lambda _path: "")

    def ticked(self, vid, roots):
        """A tick in the tree of `vid` asks to read `roots`: the Values card
        reads them from now on (`values_update`), until a row is clicked or
        the active node moves."""
        self._state[f"values_folder__{vid}"] = list(roots)

    def values_path(self, vid):
        """The node the Values card of `vid` reads: what `values_update`
        settled, else the active node."""
        return getattr(self._state, f"ui_values_node__{vid}", None) or self.path(vid)

    def _is_folder(self, path):
        """`path` stands for what lies under it: neither a property nor a
        row that draws itself."""
        return (bool(path) and not node_facts.is_property_kind(self._kind_of(path))
                and self._rep_path_of(path) != path)

    def values_update(self, vid):
        """Settle the node the Values card of `vid` reads, a tick, an eye or
        the active node having moved: `folder_reading` over the rows ticked
        last, else over the active node when it is a folder; none (the active
        node itself) when they are single leaves or nothing read is under
        them."""
        var = f"ui_values_node__{vid}"
        # the node made active last in a panel's tree (the log view's...), read as a 3D view's would be
        focus = self.focus()
        roots = ([focus] if focus
                 else list(getattr(self._state, f"values_folder__{vid}", None) or ()) or [self.path(vid)])
        tops = roots if len(roots) > 1 else [r for r in roots if self._is_folder(r)]
        read = [p for p in getattr(self._state, "selected_paths", None) or ()
                if node_facts.is_under(p, tops)]
        eyes = set() if focus else set(getattr(self._state, f"visible_paths__{vid}", None) or ())
        node = (folder_reading(read, eyes, self._kind_of, self._title_of) if read else "") or focus
        if (getattr(self._state, var, None) or "") != node:
            self._state[var] = node

    def views(self):
        """The live 3D views."""
        return list(self._views() or ())

    def focus(self):
        """The node made active last in a PANEL's tree (``ui_values_focus``),
        when that tree is the one used last: the Values view reads it rather
        than a 3D view's active node; "" when a 3D view's tree was used last,
        or the node is none of the model's (a grouping row)."""
        path = (getattr(self._state, "ui_values_focus", None) or {}).get("path") or ""
        return path if path and self._kind_of(path) else ""

    def focused(self, tree, path):
        """A panel's tree (`tree`: its kind) made `path` its active node: the
        Values view of every 3D view reads it, until a 3D view's tree is used."""
        self._state["ui_values_focus"] = {"tree": tree, "path": path or ""} if path else None
        for vid in self._views():
            self.values_update(vid)

    def unfocused(self):
        """A 3D view's tree used: the Values view reads the 3D views' active
        nodes again."""
        if getattr(self._state, "ui_values_focus", None):
            self._state["ui_values_focus"] = None
            for vid in self._views():
                self.values_update(vid)

    def path(self, vid):
        return getattr(self._state, f"active_path__{vid}", None) or ""

    def by_tab(self, vid):
        return dict(getattr(self._state, f"active_by_tab__{vid}", None) or {})

    def activate(self, vid, path, tab=None, tab_path=None):
        """Make `path` the view's active node; with `tab`, that tab's active
        node too (`tab_path`, or `path`)."""
        self._state[f"active_path__{vid}"] = path or ""
        if tab:
            by = self.by_tab(vid)
            by[tab] = tab_path or path or ""
            self._state[f"active_by_tab__{vid}"] = by

    def restore(self, vid, path, by_tab):
        """Both as they were (an undo, a session)."""
        self._state[f"active_by_tab__{vid}"] = dict(by_tab or {})
        self._state[f"active_path__{vid}"] = path or ""

    def clear(self, paths, vids=None):
        """Every active node among `paths` cleared, in `vids` (every live 3D
        view by default): an object no longer read must not stay active
        under the cards (03 §6.2, SA). Returns the views touched."""
        drop = set(paths or ())
        touched = []
        for vid in (self._views() if vids is None else vids):
            changed = False
            if self.path(vid) in drop:
                self._state[f"active_path__{vid}"] = ""
                changed = True
            by = self.by_tab(vid)
            kept = {k: p for k, p in by.items() if p not in drop}
            if kept != by:
                self._state[f"active_by_tab__{vid}"] = kept
                changed = True
            if changed:
                touched.append(vid)
        return touched

    def unloaded(self, paths):
        """`paths` unticked: an active node among them stays the active row
        (the PO, 23/11: the box clicked lights its row like any click), the
        Values view reading it still — not read, it offers to read it again;
        the cards act on what is read (`target_of`)."""
        for vid in self.views():
            self.values_update(vid)

    def pin(self, vid, tool, rep_path):
        """The object the card `tool` of `vid` acts on, picked in the card's
        list or by a right-click "Geometry slicer" (the PO, 28/10): it
        wins over the active node while it is loaded and qualifies; ""
        lets the active node choose again."""
        var = f"tool_pin__{vid}"
        cur = dict(getattr(self._state, var, None) or {})
        if cur.get(tool, "") == (rep_path or ""):
            return
        cur[tool] = rep_path or ""
        self._state[var] = cur

    def unpinned(self, vid):
        """A node made active: it takes over from an object picked in a
        card's list, the whole scene of a Geometry slicer included (the PO,
        23/11: whatever is highlighted, the card goes to it)."""
        var = f"tool_pin__{vid}"
        if any((getattr(self._state, var, None) or {}).values()):
            self._state[var] = {}

    def pinned(self, vid, tool):
        """The object picked in the card `tool` of `vid`, "" when none."""
        return (getattr(self._state, f"tool_pin__{vid}", None) or {}).get(tool) or ""

    def targets(self, vid, tool):
        """Every loaded representation the card `tool` can act on, in load
        order — the card's list of objects."""
        return [p for p in self._loaded() or () if self._qualifies(tool, p)]

    def target_of(self, vid, tool, fallback=True, remembered=True):
        """The representation `tool` acts on in `vid`, or "". `remembered`:
        the Reservoir tree's last active node when the view's own does not
        qualify; `fallback`: the first loaded one that qualifies when neither
        a pin nor an active node names one (the Geometry slicer takes neither:
        the whole scene instead, 29/10 and 23/11)."""
        loaded = self._loaded() or ()
        pinned = self.pinned(vid, tool)
        if pinned and pinned in loaded and self._qualifies(tool, pinned):
            return pinned
        # an active node no longer read names nothing: its object left the
        # views with its tick, and a card on it would act on nothing
        nodes = (self.path(vid),) + ((self.by_tab(vid).get("reservoir") or "",) if remembered else ())
        for node in nodes:
            rep = self._rep_path_of(node) or "" if node else ""
            if rep and rep in loaded and self._qualifies(tool, rep):
                return rep
        if not fallback:
            return ""
        for path in self._loaded() or ():
            if self._qualifies(tool, path):
                return path
        return ""
