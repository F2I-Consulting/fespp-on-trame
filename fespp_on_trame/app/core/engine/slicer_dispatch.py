"""Slicer / range / volume / representation dispatch — extracted from
`boot.initialize_fespp_engine`.

Every function in this module receives its dependencies explicitly so
boot.py can keep the trame decorator registrations (`@state.change`,
`@controller.set`) as thin closure wrappers. The actual logic lives
here.

Handlers covered:
  - `set_slider_value` — write the first slice position for an axis
    into the corresponding `ui_slices_{i,j,k}_list`.
  - `update_slice_positions` — slicer position lists per axis.
  - `update_slice_range` — slicer range bounds per axis.
  - `update_slice_mode` — slice vs range mode toggle.
  - `update_volume_visible` — show/hide the volume crop.
  - `update_slice_visibility` — per-axis per-slicer visibility.
  - `apply_z_scale` — fan out the global Z exaggeration to every
    rep + IjkGrid slicer / volume.
  - `propagate_representation` — push the active representation
    type (Surface / Wireframe / Points / …) onto every proxy in
    the scene."""
from paraview import simple as pvsimple


def _active_ijk_grid(state, source_registry):
    """Resolve the active IjkGrid from the state's active rep path."""
    return source_registry.get_ijk_grid(state.active_representation_path)


def set_slider_value(state, index, value):
    """Set the first slice position for the given axis ('i', 'j', or
    'k'). Value-only entry point used by the slice slider widgets —
    avoids them having to know about the per-axis list shape."""
    try:
        value = int(value)
    except (ValueError, TypeError):
        return
    list_var = f"ui_slices_{index}_list"
    current = list(getattr(state, list_var, [0]))
    if current:
        current[0] = value
    else:
        current = [value]
    setattr(state, list_var, current)


def update_slice_positions(state, controller, source_registry, view,
                           i_list, j_list, k_list):
    """Sync per-slicer visibility lists with the slice lists, then
    push positions to the active IjkGrid. New slicers default to
    visible."""
    for axis, lst in (('i', i_list), ('j', j_list), ('k', k_list)):
        vis_var = f"ui_slices_{axis}_visible_list"
        lst = lst or []
        vis_list = list(getattr(state, vis_var, []) or [])
        while len(vis_list) < len(lst):
            vis_list.append(True)
        while len(vis_list) > len(lst):
            vis_list.pop()
        setattr(state, vis_var, vis_list)

    active = _active_ijk_grid(state, source_registry)
    if active is not None:
        active.apply_slice_positions(
            i_list or [],
            j_list or [],
            k_list or [],
        )
        active.show()
    pvsimple.Render(view=view)
    controller.view_update()


def update_slice_range(state, controller, source_registry, view,
                      range_i, range_j, range_k):
    active = _active_ijk_grid(state, source_registry)
    if active is not None:
        active.apply_range(range_i, range_j, range_k)
        active.show()
    pvsimple.Render(view=view)
    controller.view_update()


def update_slice_mode(state, controller, source_registry, view, mode):
    """Mode flip (`slice` ↔ `range`) changes the set of "active
    sources" — IjkGrid re-attaches its threshold chain accordingly
    (rep_data + volume in range, rep_data + per-axis slicers in
    slice)."""
    active = _active_ijk_grid(state, source_registry)
    if active is not None:
        active.apply_mode(mode or 'slice')
        active.show()
    pvsimple.Render(view=view)
    controller.view_update()


def update_volume_visible(state, controller, source_registry, view, visible):
    active = _active_ijk_grid(state, source_registry)
    if active is not None:
        active.apply_volume_visible(visible)
        active.show()
    pvsimple.Render(view=view)
    controller.view_update()


def update_slice_visibility(state, controller, source_registry, view,
                            vis_i, vis_j, vis_k):
    active = _active_ijk_grid(state, source_registry)
    if active is not None:
        active.apply_slice_visibility(
            vis_i or [],
            vis_j or [],
            vis_k or [],
        )
        active.show()
    pvsimple.Render(view=view)
    controller.view_update()


def apply_z_scale(controller, source_registry, view, zscale):
    """Broadcast the global vertical exaggeration to every extracted
    rep source and to every IjkGrid slicer / volume proxy."""
    try:
        zs = float(zscale or 1.0)
    except (TypeError, ValueError):
        zs = 1.0
    source_registry.apply_z_scale(zs)
    ijk_srcs = []
    for ijk in source_registry.ijk_grids():
        ijk_srcs.extend(ijk._all_slice_sources())
        if ijk._src_slicer_volume is not None:
            ijk_srcs.append(ijk._src_slicer_volume)
    for src in ijk_srcs:
        rep = pvsimple.GetRepresentation(proxy=src, view=view)
        if rep is not None:
            rep.Scale = [1.0, 1.0, zs]
    pvsimple.Render(view=view)
    controller.view_update()


def propagate_representation(source_registry, representation_active):
    """ptc.RepresentBy applies the new representation to ParaView's
    active source only. Mirror it to every other proxy that could
    end up rendered for the same rep — sources (rep_data /
    rep_source / slicers / slicervolume) and Threshold filters — so
    the view stays consistent regardless of which proxy is currently
    visible (e.g. switching threshold on/off, falling back to
    rep_data when all slicers are hidden)."""
    if not representation_active:
        return
    view = pvsimple.GetActiveView()
    if view is None:
        return
    proxies = []
    try:
        proxies.extend(source_registry.all_sources())
    except Exception:
        pass
    try:
        proxies.extend(thr for _, thr in source_registry.all_thresholds())
    except Exception:
        pass
    # IjkGrid: rep_data + slicers + slicervolume + their thresholds,
    # across every active grid.
    try:
        for ijk in source_registry.ijk_grids():
            if ijk._src_extract_init is not None:
                proxies.append(ijk._src_extract_init)
            if ijk._src_slicer_volume is not None:
                proxies.append(ijk._src_slicer_volume)
            proxies.extend(ijk._all_slice_sources())
            proxies.extend(ijk.all_threshold_sources())
    except Exception:
        pass
    for p in proxies:
        try:
            disp = pvsimple.GetRepresentation(proxy=p, view=view)
            if disp is not None:
                disp.Representation = representation_active
        except Exception:
            pass
    pvsimple.Render(view=view)
