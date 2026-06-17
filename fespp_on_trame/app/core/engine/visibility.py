"""Visibility dispatch — tree eye-icon click on a representation.

Extracted from `boot.initialize_fespp_engine`. The rep eye chip is a
3-state affordance:

  1. Hidden (closed eye, grey) — the rep is in the per-panel hidden
     bucket.
  2. Visible + SolidColor (open eye, blue) — visible without any
     scalar coloring.
  3. Visible + array (lighter open eye) — visible, scalar-coloured
     by an active array.

The click cycles:
  (3) → (2) — clear the active array, keep the rep visible. Same
              effect as clicking the data-array eye to deactivate.
  (2) → (1) — hide the rep in this panel.
  (1) → (2) — re-show the rep (in SolidColor; activate ColorBy via
              the data-array eye separately).

`panel_id` is the render panel the click came from; absent → legacy
active-view behaviour.

`state.ui_hidden_rep_paths` (global) is kept in sync as a mirror of
the active panel's hidden set so legacy consumers
(`extract_block.py:_refresh_chain_visibility`, …) keep reading a
coherent value."""
from paraview import simple as pvsimple

from fespp_on_trame.app.core.engine import panel_resolver, source_resolver
from fespp_on_trame.app.core.sources.representation import _apply_default_tint


def _clear_active_array(state, controller, server, source_registry, tree,
                        rep_path, panel_id, view, html_view):
    """Drop the active array binding for `rep_path` in `panel_id` and
    push SolidColor onto every display of that rep in `view`. Mirrors
    the legacy global map iff this is the active panel."""
    bucket_key = panel_id or panel_resolver.active_panel_id(server) or "_active"

    by_view = dict(state.ui_active_array_by_rep_by_view or {})
    panel_map = dict(by_view.get(bucket_key, {}) or {})
    panel_map.pop(rep_path, None)
    by_view[bucket_key] = panel_map
    state.ui_active_array_by_rep_by_view = by_view

    active = panel_resolver.active_panel_id(server)
    if active and active == bucket_key:
        mirror = dict(state.ui_active_array_by_rep or {})
        mirror.pop(rep_path, None)
        state.ui_active_array_by_rep = mirror

    source_resolver.apply_color_array(
        source_registry, tree, rep_path, None, view=view,
    )
    # The scalar bar for the cleared array is now orphaned in `view`
    # (no visible display references its LUT here). Sweep stale bars.
    source_resolver.hide_unused_scalar_bars(view=view)
    if view is not None:
        try:
            pvsimple.Render(view=view)
        except Exception:
            pass
    if html_view is not None:
        try:
            html_view.update()
        except Exception:
            pass
    else:
        try:
            controller.view_update()
        except Exception:
            pass


def toggle_marker_visibility(state, controller, server, source_registry, tree,
                             marker_path, panel_id=None):
    """Tree eye on a WellboreMarker leaf.

    Markers display MULTIPLE at a time (unlike single-select log
    channels): each toggled marker renders via its OWN per-(rep, view)
    EnergisticsExtractor pointed at the marker's assembly node. This
    flips the marker in this panel's `ui_visible_marker_paths_by_view`
    bucket and shows / hides its per-marker extractor in the target
    view's RepInScene. Visibility-only — markers carry no colour array.
    """
    if not marker_path:
        return
    node_id = tree.find_node_id(marker_path)
    if node_id is None:
        return
    r_id = tree.find_representation_node(node_id)
    r_path = tree.find_path(r_id) if r_id is not None else None
    if not r_path:
        return
    view, html_view = panel_resolver.resolve_view_and_html_view(server, panel_id)
    bucket_key = panel_id or panel_resolver.active_panel_id(server) or "_active"

    by_view = dict(state.ui_visible_marker_paths_by_view or {})
    bucket = list(by_view.get(bucket_key, []) or [])
    if marker_path in bucket:
        bucket.remove(marker_path)
        new_visible = False
    else:
        bucket.append(marker_path)
        new_visible = True
    by_view[bucket_key] = bucket
    state.ui_visible_marker_paths_by_view = by_view

    rep_in_scene = source_resolver._scene_rep_for_view(r_path, view)
    if rep_in_scene is not None:
        try:
            rep_in_scene.set_marker_visible(marker_path, new_visible)
        except Exception as exc:
            print(f"[WARNING] set_marker_visible({marker_path}, {panel_id}): {exc}")
    else:
        print(f"[WARNING] toggle_marker_visibility({marker_path}, {panel_id}):"
              f" no RepInScene for {r_path}")

    if view is not None:
        try:
            pvsimple.Render(view=view)
        except Exception:
            pass
    if html_view is not None:
        try:
            html_view.update()
        except Exception:
            pass
    else:
        try:
            controller.view_update()
        except Exception:
            pass
    print(
        f"[VIS-MARKER] {marker_path} → {'show' if new_visible else 'hide'} "
        f"(panel={panel_id or 'active'})"
    )


def toggle_rep_visibility(state, controller, server, source_registry, rep_path,
                          panel_id=None, tree=None):
    if not rep_path:
        return
    view, html_view = panel_resolver.resolve_view_and_html_view(server, panel_id)
    bucket_key = panel_id or panel_resolver.active_panel_id(server) or "_active"

    # A wellbore frame has no own geometry — its only renderable content
    # is the single selected channel tube. The 3-state "clear coloring,
    # keep geometry" intermediate makes no sense there (it would leave
    # the log painted in SolidColor instead of hiding it). Treat the
    # frame's eye as a plain show/hide: skip the clear-coloring branch so
    # the click goes straight to flipping the per-view extractor's
    # visibility.
    is_frame = False
    if tree is not None:
        try:
            _nid = tree.find_node_id(rep_path)
            is_frame = (tree.find_type(_nid) == 'Frame') if _nid is not None else False
        except Exception:
            is_frame = False

    # State (3) — array active on this rep in this panel → click means
    # "give up the coloring", not "hide the rep". Drop the array and
    # leave the geometry visible in SolidColor.
    active_array_path = (state.ui_active_array_by_rep_by_view or {}) \
        .get(bucket_key, {}).get(rep_path)
    is_hidden_now = rep_path in (
        (state.ui_hidden_rep_paths_by_view or {}).get(bucket_key, []) or []
    )
    if active_array_path and not is_hidden_now and not is_frame:
        _clear_active_array(
            state, controller, server, source_registry, tree,
            rep_path, panel_id, view, html_view,
        )
        return

    # State (1)↔(2) — flip visibility for this rep in this panel.
    by_view = dict(state.ui_hidden_rep_paths_by_view or {})
    bucket = list(by_view.get(bucket_key, []) or [])
    if rep_path in bucket:
        bucket.remove(rep_path)
        show = True
    else:
        bucket.append(rep_path)
        show = False
    by_view[bucket_key] = bucket
    state.ui_hidden_rep_paths_by_view = by_view

    # Mirror the active panel's hidden set into the legacy global
    # var so extract_block.py:_refresh_chain_visibility etc. keep
    # reading a coherent value.
    active = panel_resolver.active_panel_id(server)
    if active and active == bucket_key:
        state.ui_hidden_rep_paths = list(bucket)

    srcs, view = source_resolver.sources_for_rep_path(source_registry, rep_path, view=view)
    if not srcs:
        print(f"[WARNING] toggle_rep_visibility({rep_path}, {panel_id}): no source found")

    if show:
        # For IjkGrid the per-mode Show/Hide pattern is intricate
        # (slice vs range, volume eye, deepest threshold leaf) — let
        # IjkGrid.show() decide which sources to actually render in
        # the target view. For non-IjkGrid reps, plain Show on the
        # source proxy is the right behaviour.
        ijk = source_registry.get_ijk_grid(rep_path)
        if ijk is not None:
            try:
                ijk.show(view=view)
            except Exception as _e:
                print(f"[WARNING] IjkGrid.show(view) raised: {_e}")
        else:
            # ExtractBlock side — the rep's `add_source` set
            # Representation + tint on the active view's display only.
            # For panels other than the original, the display we're
            # about to flip Vis=1 on has PV's defaults; re-assert
            # Representation and tint so SolidColor matches the
            # user's pick.
            rep_type = state.representation_active or "Surface"
            grid_color = (state.solid_color_by_rep or {}).get(rep_path)
            for src in srcs:
                try:
                    pvsimple.Show(src, view=view)
                except Exception as _e:
                    print(f"[WARNING] Show raised: {_e}")
                try:
                    d = pvsimple.GetDisplayProperties(src, view=view)
                    if d is not None:
                        d.Visibility = 1
                        try:
                            d.Representation = rep_type
                        except Exception:
                            pass
                        _apply_default_tint(d, grid_color)
                        sm = getattr(d, "SMProxy", None)
                        if sm is not None:
                            sm.UpdateVTKObjects()
                except Exception as _e:
                    print(f"[WARNING] Visibility flag flip raised: {_e}")
    else:
        # Hide: flip Visibility on every source of the rep (slicers,
        # volume crop, rep_data extractor) so the panel goes dark
        # regardless of which one was rendering.
        for src in srcs:
            try:
                pvsimple.Hide(src, view=view)
            except Exception as _e:
                print(f"[WARNING] Hide raised: {_e}")
            try:
                d = pvsimple.GetDisplayProperties(src, view=view)
                if d is not None:
                    d.Visibility = 0
                    sm = getattr(d, "SMProxy", None)
                    if sm is not None:
                        sm.UpdateVTKObjects()
            except Exception as _e:
                print(f"[WARNING] Visibility flag flip raised: {_e}")
    if view is not None:
        try:
            view.SMProxy.UpdateVTKObjects()
        except Exception:
            pass
        pvsimple.Render(view=view)
    if html_view is not None:
        try:
            html_view.update()
        except Exception:
            pass
    else:
        controller.view_update()
    print(
        f"[VIS] {rep_path} → {'show' if show else 'hide'} "
        f"({len(srcs)} sources, panel={panel_id or 'active'})"
    )
