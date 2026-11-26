"""Camera synchronization card of ONE render view (the "Synchronize camera" tool).

Checklist of every OTHER render view; ticking one links / unlinks the two
views SYMMETRICALLY. The link itself is ParaView's own camera link, one per
linked pair (`MultiView._apply_camera_links`): the linked view follows every
frame of a gesture. `MultiView._sync_camera_from` copies the camera once more
on the mouse release (each view's vtk.js EndAnimation) and pushes the linked
views' last image.

State shape:
    state.view_links: dict[view_id, list[view_id]]  — symmetric: if A is in
        view_links[B] then B is in view_links[A]. Entries of a closed view
        are purged by `MultiView._on_view_closed`.
    state.fespp_render_panels: [{id, title}] — published by MultiView on
        every view add / close.
"""


def toggle_link(state, panel_a: str, panel_b: str):
    """Toggle the camera link between two views, on both sides at once.

    If the A↔B link exists it is dropped from both views, otherwise it is
    added to both. Module-level so every caller (the engine, the tests)
    goes through the same primitive.
    """
    if panel_a == panel_b or not panel_a or not panel_b:
        return
    links = {k: list(v) for k, v in (state.view_links or {}).items()}
    a_set = set(links.get(panel_a, []))
    if panel_b in a_set:
        a_set.discard(panel_b)
        links[panel_a] = sorted(a_set)
        b_set = set(links.get(panel_b, []))
        b_set.discard(panel_a)
        links[panel_b] = sorted(b_set)
    else:
        a_set.add(panel_b)
        links[panel_a] = sorted(a_set)
        b_set = set(links.get(panel_b, []))
        b_set.add(panel_a)
        links[panel_b] = sorted(b_set)
    for k in list(links.keys()):
        if not links[k]:
            links.pop(k)
    state.view_links = links
