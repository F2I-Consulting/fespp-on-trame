"""tree_grammar: what a tick and an eye mean, in every tree.

One grammar, the same in the data tree of every 3D view and in the three
panel trees (Statistics, the well-log, Log <-> Grid):

* a **checkbox** is the session's load, common to every view: ticked in any
  tree = read into the session; unticked = unloaded from it. An untick that
  would take out what ANOTHER view is using (a 3D view showing it, a panel
  holding it) asks first and names those views. A tick in a panel's tree
  also puts what it read in that panel, as a data-tree tick shows what it
  read in its view; it shows nothing in the 3D views.
* an **eye** is "shown in THIS view": in a 3D view, drawn there; in a panel,
  held by it — a property in Statistics, a well (or one of its curves) in the
  log, a row of the Log <-> Grid table. It is offered on what the session
  holds and never reads anything.

What lives here is the pure half — which paths a ticked set stands for, and
what each panel keeps of them. The routing is in ``app/features/
tick_question`` (`tree_tick`) and ``app/scene/panel_trees``.
"""


def expand(ticked, is_leaf, descendants):
    """The leaves a ticked set stands for.

    A leaf stands for itself, a folder for every leaf under it: the widget
    sends the folder's own path and the cascade is the server's, in every
    tree (the data tree expands it with the load dependencies, the panels
    with this).
    """
    out = []
    for path in ticked or ():
        if not path:
            continue
        for leaf in ([path] if is_leaf(path) else descendants(path)):
            if leaf and leaf not in out:
                out.append(leaf)
    return out


def panel_wells(ticked, wellbores_of):
    """The well-log: the wellbores the log holds after a tick.

    Whatever node was ticked, the set is reduced to wellbores — the log
    correlates wellbores, and ticking a trajectory, a frame or a marker
    means "this well", not "this array". ``wellbores_of(path)`` answers with
    the well a node belongs to, or with every well under it when the tick is
    a folder above them (a folder stands for its subtree in every tree).
    """
    wells = []
    for path in ticked or ():
        for well in wellbores_of(path) or ():
            if well and well not in wells:
                wells.append(well)
    return wells


def curves_alone(named, fresh, wellbore_of, is_curve, curves_of):
    """The curves a gesture leaves out of the log for the wells it brings in
    by naming some of their curves alone — an eye on a property kind's
    folder, one log ticked —: such a well brings the curves named, not every
    one it has. A well named as a whole (the wellbore, its trajectory, a
    frame, a marker frame) brings everything. `named` the paths of the
    gesture, `fresh` the wells it brings in, `curves_of(well)` every curve of
    a well."""
    out = []
    for well in fresh or ():
        mine = [p for p in named or () if wellbore_of(p) == well]
        if not mine or not all(is_curve(p) for p in mine):
            continue
        keep = set(mine)
        out += [c for c in curves_of(well) or () if c not in keep and c not in out]
    return out
