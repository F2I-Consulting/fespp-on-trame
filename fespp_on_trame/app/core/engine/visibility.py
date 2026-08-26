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
            pass
    else:
        pass

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


def _per_view_ijk_for(rep_path, view):
    """The per-view IjkGrid instance rendering `rep_path` in `view`,
    or None (non-grid rep / scene not built / per-view IjkGrid not
    materialised yet)."""
    try:
        from fespp_on_trame.app.core.engine.source_resolver import (
            _scene_rep_for_view,
        )
        ris = _scene_rep_for_view(rep_path, view)
        return getattr(ris, "_per_view_ijk", None)
    except Exception:
        return None


def toggle_rep_visibility(state, controller, server, source_registry, rep_path,
                          panel_id=None, tree=None):
    if not rep_path:
        return
    view, html_view = panel_resolver.resolve_view_and_html_view(server, panel_id)
    bucket_key = panel_id or panel_resolver.active_panel_id(server) or "_active"

    # Visibility and colouring are ORTHOGONAL: this eye means show/hide the
    # rep, nothing else. It used to first "give up the colouring" (SolidColor)
    # and only hide on a second click — which made hiding a rep necessarily
    # DESTROY its active array, so "hide the grid, keep the wells coloured by
    # PORO" was unexpressible, and any consumer of the grid's active property
    # lost it the moment the grid went away. Dropping a colour array is the
    # PROPERTY eye's job (`active_array.toggle_dataarray_color`), which already
    # allows one active array per rep and falls back to SolidColor when the
    # last one closes. That also retires the wellbore-frame special case: the
    # frame's eye was only ever exempted to escape this same intermediate.
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
        pass

    if show:
        # For IjkGrid the per-mode Show/Hide pattern is intricate
        # (slice vs range, volume eyes, deepest threshold leaf) — let
        # IjkGrid.show() decide which sources to actually render in
        # the target view. Re-show ONLY the pipeline that renders in
        # this view: the per-view IjkGrid when the scene has one, else
        # the legacy shared instance. Re-showing BOTH painted the
        # legacy full-grid rep_data — whose mode and coloring never
        # track the per-view state — on top of the per-view crops /
        # slices (legacy extractor visible over
        # the per-view crop after a geometry-eye re-show). The HIDE
        # side still sweeps both instances — belt and braces.
        ijk = source_registry.get_ijk_grid(rep_path)
        per_view_ijk = _per_view_ijk_for(rep_path, view)
        for ijk_inst in ([per_view_ijk] if per_view_ijk is not None else [ijk]):
            if ijk_inst is None:
                continue
            try:
                ijk_inst.show(view=view)
            except Exception as _e:
                pass
        # Non-IjkGrid reps take the generic Show path below.
        if ijk is not None:
            pass
        else:
            # ExtractBlock side — the rep's `add_source` set
            # Representation + tint on the active view's display only.
            # For other panels the display we're about to flip Vis=1 on
            # has PV's defaults, so re-assert Representation and tint to
            # match the user's pick.
            from fespp_on_trame.app.core.sources.representation import rep_type_for
            rep_type = rep_type_for(state, rep_path)
            grid_color = (state.solid_color_by_rep or {}).get(rep_path)
            for src in srcs:
                try:
                    pvsimple.Show(src, view=view)
                except Exception as _e:
                    pass
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
                    pass
    else:
        # Hide: flip Visibility on every source of the rep (slicers,
        # volume crop, rep_data extractor) so the panel goes dark
        # regardless of which one was rendering. Cover BOTH IjkGrid
        # pipelines explicitly: the show path re-shows the LEGACY
        # shared instance while `sources_for_rep_path` prefers the
        # per-view set once a RepInScene exists — hiding only the
        # latter left the legacy slicers rendering on the second eye
        # close (per-axis slicer proxies survive a bare rep_data hide).
        all_srcs = list(srcs)
        try:
            _ijk_legacy = source_registry.get_ijk_grid(rep_path)
        except Exception:
            _ijk_legacy = None
        for _ijk_inst in (_ijk_legacy, _per_view_ijk_for(rep_path, view)):
            if _ijk_inst is None:
                continue
            _p = getattr(_ijk_inst, "_src_extract_init", None)
            if _p is not None:
                all_srcs.append(_p)
            all_srcs.extend(getattr(_ijk_inst, "_src_volumes", []) or [])
            try:
                all_srcs.extend(_ijk_inst._all_slice_sources())
            except Exception:
                pass
            try:
                all_srcs.extend(_ijk_inst.all_threshold_sources())
            except Exception:
                pass
        srcs = all_srcs
        for src in srcs:
            try:
                pvsimple.Hide(src, view=view)
            except Exception as _e:
                pass
            try:
                d = pvsimple.GetDisplayProperties(src, view=view)
                if d is not None:
                    d.Visibility = 0
                    sm = getattr(d, "SMProxy", None)
                    if sm is not None:
                        sm.UpdateVTKObjects()
            except Exception as _e:
                pass
    # Colour-bar invariant on eye flips: re-showing a rep must bring its
    # active array's bar back (a hide-side sweep dropped it, and nothing
    # outside a load batch re-shows bars), and hiding must sweep the
    # now-orphan bar instead of leaving a stale legend.
    try:
        if show:
            source_resolver.reassert_active_scalar_bars(
                state, source_registry, view=view)
        else:
            source_resolver.hide_unused_scalar_bars(view=view)
            source_resolver.layout_visible_scalar_bars(view)
    except Exception:
        pass
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
