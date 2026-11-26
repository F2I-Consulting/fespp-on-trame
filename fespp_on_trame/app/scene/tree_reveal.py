"""A node shown in its tree card from outside the tree: the 3D view's
right-click "Show in tree", a row of the Data health table.

The same as a click on its row: the node becomes the view's active one and
its family's tree card opens, or comes in front of the tabs of its group;
the card's tree then unfolds its ancestors and scrolls to the row (the tree
widget's `active`)."""
from fespp_on_trame.engine import tree_families


def targets(prop, path, others=()):
    """The nodes a right-click on the 3D view offers to show in the tree,
    one menu entry each, by name: the property colouring the object under
    the pointer, the object, then any other object under the same pixel;
    once each, in that order."""
    out = []
    for p in [prop, path, *(others or ())]:
        if p and p not in out:
            out.append(p)
    return out


def show_in_tree(activation, cards, state, vid, path):
    """`path` made the active node of `vid`, its family's tree card open and
    in front. Returns that card's key, "" when there is nothing to show."""
    if not vid or not path:
        return ""
    key = tree_families.key_of(getattr(state, "assembly_xml", None) or "", path,
                               getattr(state, "ui_cube_grid_rows", None) or ())
    # as a click on the row, the active one included: the Values card reads
    # the node, no longer a folder ticked before
    state[f"values_folder__{vid}"] = []
    activation.activate(vid, path)
    cards.open(vid, key)
    return key
