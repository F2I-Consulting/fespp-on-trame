"""View-update / camera-reset sentinel handlers — extracted from
`boot.initialize_fespp_engine`.

The UI writes `state.view_reset_camera = True` or
`state.view_update = True` to request a render-pass refresh. The
handlers below re-arm the sentinel back to `False` after firing so
the same request can be re-triggered later (Trame would otherwise
collapse identical writes into no-ops).

Camera reset additionally refreshes per-block visibility on every
loaded IjkGrid — block visibility is a slicer-side concept and the
ParaView camera reset alone wouldn't account for newly enabled /
disabled blocks."""


def on_view_reset_camera(state, controller, source_registry, value):
    """Re-arm the sentinel and trigger the camera reset + view update."""
    if value != True:
        return
    for ijk in source_registry.ijk_grids():
        ijk.update_block_visibility()
    controller.view_reset_camera()
    controller.view_update()
    state.view_reset_camera = False
    state.flush()


def on_view_update(state, controller, value):
    """Re-arm the sentinel and trigger the view update."""
    if value != True:
        return
    controller.view_update()
    state.view_update = False
    state.flush()


def broadcast_view_update(server):
    """`@controller.add('on_data_change')` callback — broadcast a
    refresh to every panel rather than the active view only. Palette
    changes / global TC writes / property changes all want non-active
    panels refreshed too. Falls back to view_update when the multi-
    view isn't yet wired (early bootstrap)."""
    update_all = getattr(server.controller, "view_update_all", None)
    if update_all is not None:
        update_all()
    else:
        server.controller.view_update()
