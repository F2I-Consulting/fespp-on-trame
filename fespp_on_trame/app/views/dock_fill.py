"""A detached view filling the dock, the other views as its tabs.

A floating window covers what lies under it: to stay within reach, the other
views join it, at the same size, and the layout they left comes back when it
lets go. Joining mounts nothing again; coming back is a layout restored, as on a
reload. The window's size is a class the gesture puts on it (`.fp-filled`,
view_chrome): the layout restored makes a new window, without it.
"""
import copy


def layout_without(layout, gone):
    """A copy of `layout`, as dockview serialises it, without the panels in
    `gone` and the groups they leave empty."""
    out = copy.deepcopy(layout)
    gone = set(gone)

    def keep(group):
        group["views"] = [v for v in group.get("views") or () if v not in gone]
        if group.get("activeView") in gone:
            group["activeView"] = group["views"][0] if group["views"] else None
        return bool(group["views"])

    def prune(node):
        if node.get("type") == "leaf":
            return keep(node.get("data") or {})
        node["data"] = [child for child in node.get("data") or () if prune(child)]
        return bool(node["data"])

    for pid in gone:
        (out.get("panels") or {}).pop(pid, None)
    root = (out.get("grid") or {}).get("root")
    if root:
        prune(root)
    out["floatingGroups"] = [g for g in out.get("floatingGroups") or () if keep(g.get("data") or {})]
    return out


class DockFill:
    """The one window filling the dock, while there is one."""

    def __init__(self, dock):
        self._dock = dock
        self.owner = None
        self._before = None

    def toggle(self, title):
        """The window whose active tab wears `title` fills the dock, or the one
        that does lets go."""
        if self.owner:
            self.leave()
            return
        dock = self._dock
        owner = next((p for p in dock.panel_ids() if dock.title_of(p) == title), None)
        if owner:
            self._take(owner)

    def _take(self, owner):
        dock = self._dock
        self.owner = owner
        self._before = copy.deepcopy(dock._layout)
        moves = [("movePanelTo", pid, {"referencePanel": owner, "direction": "within"})
                 for pid in dock.panel_ids() if pid != owner]
        dock.in_order(*moves, ("activePanel", owner))

    def layout(self):
        """The layout to keep: while a window fills the dock, the one it covers."""
        dock = self._dock
        if not self.owner:
            return dock._layout
        return layout_without(self._before, set(self._before.get("panels") or ()) - set(dock.panel_ids()))

    def leave(self, anchor=None):
        """Every view back where it was, those opened meanwhile where their kind
        opens, and `anchor` from its window to the dock."""
        if not self.owner:
            return
        layout = self.layout()
        if anchor:
            layout = layout_without(layout, {anchor})
        self._end()
        self._dock.come_back(layout, anchor)

    def panel_closed(self, panel_id):
        """The window stays while it holds a view, whichever asked for it."""
        if panel_id != self.owner:
            return
        left = self._dock.panel_ids()
        if left:
            self.owner = left[0]
        else:
            self._end()

    def _end(self):
        self.owner = None
        self._before = None
