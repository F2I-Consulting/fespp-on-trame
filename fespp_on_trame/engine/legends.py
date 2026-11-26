"""One colour bar per 3D view, and the legend of every other table.

A view can be coloured by many tables (a whole wellbore colours one table
per log channel, often dozens), and one bar per table would pile up in the
corners, unreadable. So the view shows ONE bar, the bar of the table the
Colormap card edits; every coloured table is listed in the view's Legends
card, and picking one there makes it the table the card edits, hence the
one bar.

The card edits the tree's active node. That node does not always name a
painting table (nothing active yet, a wellbore or a log's frame, another
tree tab, an eye opened without a click, a property whose eye is closed),
and a view with coloured objects and no bar at all reads as broken. So the
bar stays on the table it was on while that table still paints, and moves
to a table that has just started painting otherwise (`choose_focus`).

No ParaView import here: the choice and the legend rows are plain data,
unit-tested; `PdcScene` applies them to the view's bar, `boot` publishes
the rows.
"""

# how many colours a continuous table's swatch is sampled into
SWATCH_STOPS = 16

# the sections of the list, in this order: a grid's property and a log are
# told apart at a glance (the tree's families, engine/tree_families)
FAMILY_ORDER = ("grid", "well", "surface", "seismic", "other")
_FAMILY_OF_TAB = {"Reservoir": "grid", "Well": "well", "Surface": "surface", "Seismic": "seismic"}


def family_of_tab(tab):
    """The list's section for a tree family ("Reservoir", "Well",
    "Surface", "Seismic"); "other" for anything else."""
    return _FAMILY_OF_TAB.get(tab or "", "other")


def choose_focus(keys, target, previous, previous_keys):
    """The table whose bar the view shows, among `keys` (the tables painting
    the view, in the view's order): the table the Colormap card edits when
    it paints; else the table the bar was already on, while it paints; else
    the first table that has just started painting; else the first one.
    None when nothing paints."""
    keys = list(keys or ())
    if not keys:
        return None
    if target in keys:
        return target
    if previous in keys:
        return previous
    seen = set(previous_keys or ())
    fresh = [k for k in keys if k not in seen]
    return fresh[0] if fresh else keys[0]


def sample_positions(lo, hi, n=SWATCH_STOPS, log=False):
    """`n` values from `lo` to `hi`, evenly spaced: in log space when the
    table maps on a log scale (and the range is positive), so the swatch
    shows what the bar shows."""
    lo, hi = float(lo), float(hi)
    if n < 2:
        return [lo]
    if log and lo > 0 and hi > 0:
        import math
        a, b = math.log10(lo), math.log10(hi)
        return [10 ** (a + (b - a) * i / (n - 1)) for i in range(n)]
    return [lo + (hi - lo) * i / (n - 1) for i in range(n)]


def legend_rows(tables, focus, hidden, describe):
    """The legend rows, by section (`FAMILY_ORDER`: grids, wells,
    surfaces) then by title, so a row never moves when the bar does.

    `tables`: ``[{"key", "title", ...}]``, the tables painting the view.
    `focus`: the key of the table holding the bar. `hidden`: the keys whose
    bar the reader switched off. `describe(table)` returns the drawn part of
    a row, ``{"lo", "hi", "stops", "codes", "log", "family", "owners"}``,
    read from its colour table and the tree by the caller; `owners` names
    what the table paints (two wells' GR share one scale: both are named)."""
    rows = []
    for t in tables or ():
        key = t.get("key")
        row = {"key": key, "title": t.get("title") or "",
               "lo": "", "hi": "", "stops": [], "codes": [], "log": False,
               "family": "other", "owners": []}
        row.update(describe(t) or {})
        off = key in (hidden or ())
        row["bar"] = key == focus and not off
        row["bar_off"] = key == focus and off
        rows.append(row)
    rank = {f: i for i, f in enumerate(FAMILY_ORDER)}
    rows.sort(key=lambda r: (rank.get(r["family"], len(rank)),
                             r["title"].casefold(), r["key"] or ""))
    return rows
