"""What a session document written with views that are gone says, in today's
words. Pure: no trame, no ParaView.

Statistics (kind `stats`) and Compare (kind `compare`) were two panels. They are
one view now, of kind `compare`, so a document's `stats` paragraph is read as
that view's, and a document holding both comes back as one panel:

* `{pinned, panel_state, tree_open}` becomes `{kind: "compare", items, tree_open}`:
  per pinned property, the rows of its card (the default row unpinned, the others
  pinned, each at its realization and time step), a bare item without any;
* the first of the two paragraphs keeps its place in the document and in its
  layout, the other one joins it and leaves the layout.

The histogram and the cross-plot were views of their own (kinds `distribution`
and `crossplot`). They are charts of the Statistics view now: such a paragraph
leaves the document and its layout, and the door says so.

The paragraph says no `parts`: the session reads that as older than the parts of
a grid, and shows the columns such a document could not have chosen.

The Globe was a mode of a 3D view (`"globe": true` on a `render` paragraph). It
is a view of its own now, of kind `globe` and one per session: the first such
paragraph is read as the Globe's, under its name; a later one as a plain 3D view.
"""

#: the title a saved `compare` panel holds, and that of the view now
_OLD_TITLE = "Compare"
_TITLE = "Statistics"
_GLOBE_TITLE = "Globe"
#: the kinds of view that are gone, and what the reader called them
_REMOVED_KINDS = {"distribution": "Distribution", "crossplot": "Cross-plot"}


def _item(path, real=None, ts=None, pinned=False):
    return {"path": path, "real": real, "ts": ts, "pinned": pinned}


def stats_items(view):
    """The items of a `stats` paragraph: the rows of each card it pins."""
    states = view.get("panel_state") or {}
    items = []
    for path in view.get("pinned") or ():
        if not path or not isinstance(path, str):
            continue
        rows = (states.get(path) or {}).get("originals") or ()
        items.extend(_item(path, row.get("real_idx"), row.get("ts_idx"), row.get("id") != "default")
                     for row in rows)
        if not rows:
            items.append(_item(path))
    return items


def stats_as_compare(view):
    """A `stats` paragraph as a `compare` one, its place and title kept."""
    kept = {k: v for k, v in view.items() if k not in ("pinned", "panel_state")}
    return dict(kept, kind="compare", items=stats_items(view))


def _joined(first, other):
    """The one view two paragraphs stand for: the place of the first, whatever
    else either says, and every item of both once — the ones of a saved
    selection first, its baselines name them by their uid."""
    both = list(first.get("items") or ()) + list(other.get("items") or ())
    items, seen = [], set()
    for it in sorted(both, key=lambda it: not it.get("uid")):
        coord = (it.get("path"), it.get("real"), it.get("ts"))
        if coord not in seen:
            seen.add(coord)
            items.append(it)
    return {**other, **first, "items": items}


def _grid_without(node, panel):
    """A node of a dockview grid without the panel; None when nothing is left
    of it."""
    data = node.get("data")
    if node.get("type") == "leaf":
        views = [v for v in (data or {}).get("views") or () if v != panel]
        if not views:
            return None
        active = data.get("activeView")
        return dict(node, data=dict(data, views=views,
                                    activeView=active if active in views else views[0]))
    kept = [n for n in (_grid_without(child, panel) for child in data or ()) if n is not None]
    return dict(node, data=kept) if kept else None


def layout_without(layout, panel):
    """A dockview layout (`toJSON()`) that no longer places `panel`; None when
    it places nothing else."""
    if not isinstance(layout, dict) or panel not in (layout.get("panels") or {}):
        return layout
    grid = layout.get("grid") or {}
    root = _grid_without(grid.get("root") or {}, panel)
    if root is None:
        return None
    return dict(layout, grid=dict(grid, root=root),
                panels={k: v for k, v in layout["panels"].items() if k != panel})


def _layout_titled(layout, panel, title=_TITLE, old=_OLD_TITLE):
    """A dockview layout, the tab of `panel` titled `title` when it holds `old`
    (any title when `old` is None): the tab reads its title from there."""
    tab = ((layout or {}).get("panels") or {}).get(panel)
    if not isinstance(tab, dict) or (old is not None and tab.get("title") != old):
        return layout
    return dict(layout, panels=dict(layout["panels"], **{panel: dict(tab, title=title)}))


def current_views(views, layout=None):
    """`(views, layout)` of a document, as today's application reads them."""
    views = list(views or ())
    out, at, gone = [], None, []
    globe = any(v.get("kind") == "globe" for v in views)
    for v in views:
        kind = v.get("kind")
        if kind == "stats":
            v = stats_as_compare(v)
        elif kind == "compare" and v.get("title") == _OLD_TITLE:
            v = dict(v, title=_TITLE)
        elif kind == "render" and "globe" in v:
            on = bool(v["globe"]) and not globe
            v = {k: x for k, x in v.items() if k != "globe"}
            if on:
                globe = True
                v.update(kind="globe", title=_GLOBE_TITLE)
                layout = _layout_titled(layout, v.get("id"), _GLOBE_TITLE, None)
            else:
                v.pop("globe_state", None)
        if v.get("kind") != "compare":
            out.append(v)
        elif at is None:
            at = len(out)
            out.append(v)
        else:
            out[at] = _joined(out[at], v)
            gone.append(v.get("id"))
    for panel in gone:
        layout = layout_without(layout, panel)
    if at is not None:
        layout = _layout_titled(layout, out[at].get("id"))
    return out, layout


def without_removed_kinds(views, layout=None):
    """`(views, layout, gone)`: the document without the views of a kind that
    is gone, the panels its layout places with them; `gone` are those views,
    each with a title to say it by."""
    kept, gone = [], []
    for v in views:
        name = _REMOVED_KINDS.get(v.get("kind"))
        if name is None:
            kept.append(v)
            continue
        gone.append(dict(v, title=v.get("title") or name))
        layout = layout_without(layout, v.get("id"))
    return kept, layout, gone
