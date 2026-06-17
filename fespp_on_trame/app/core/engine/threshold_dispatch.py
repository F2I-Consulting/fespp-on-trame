"""Threshold-chain dispatch — extracted from `boot.initialize_fespp_engine`.

Phase 3a/3b: this dispatcher routes IjkGrid AND non-IjkGrid threshold
ops through `SceneRegistry` so each (view, rep) has its own chain.
Legacy fallback only when the per-view IjkGrid hasn't been built yet
(no property picked) or the scene_registry isn't ready (early boot).

The engine's job is unchanged at the contract level:

  1. Publish the active view's active rep's chain into
     `state.ui_threshold_chain` so the UI can render it
     (depth-decorated + DFS-reordered for indentation).
  2. Forward UI events (add / delete / set_range / set_visible) into
     the right provider — `RepInScene` for both rep types (per-view),
     legacy as a fallback only.

The provider's call convention is uniform:
`provider.<op>(parent / name / ...)` — no rep_path parameter. Both
`RepInScene` and `IjkGrid` expose the same signatures so the
dispatcher branching collapsed to "did we get a per-view provider,
or did we hit the legacy fallback that takes rep_path first".

Multi-realization quirk: `state.active_color_array_name` carries the
property TITLE (e.g. "VOIL"), not the VTK array name. For MR
properties the actual array stored in CellData/PointData is
`<title>_real_<idx>` — one per loaded realization. `_resolve_vtk_array_name`
below substitutes the suffixed name when the active property is MR
in the active view, otherwise threshold creation would silently fail
on `_resolve_assoc` (no array named "VOIL" exists).

All functions in this module are free functions taking explicit
dependencies. boot.py registers thin closure wrappers that capture
the relevant deps from the engine init scope and forward."""
import re

from paraview import simple as pvsimple

from fespp_on_trame.app.core.engine import realization_dispatch


def _render_and_push(state, controller, fallback_view):
    """Render the target panel's pv_view + push the frame to its
    vtk.js client. Mirrors `slicer_dispatch._render_and_push` — kept
    here as a thin local helper so this module doesn't import from
    its sibling.

    `fallback_view` is the engine's legacy `_view` used when the
    target panel can't be resolved (early boot, no multi_view)."""
    target = (
        getattr(state, "drawer_target_view_id", "") or ""
        or getattr(state, "fespp_active_panel_id", "") or ""
    )
    pv_view = fallback_view
    if target:
        try:
            from trame.app import get_server
            ctx = get_server().context
            scenes = getattr(ctx, "scene_registry", None)
            if scenes is not None:
                scene = scenes.get_scene(target)
                if scene is not None and getattr(scene, "pv_view", None) is not None:
                    pv_view = scene.pv_view
        except Exception:
            pass
    if pv_view is not None:
        try:
            pvsimple.Render(view=pv_view)
        except Exception:
            pass
    try:
        controller.view_update_for(target)
    except Exception:
        pass
    try:
        controller.view_update()
    except Exception:
        pass


_NAME_INVALID_RE = re.compile(r"[^\-.0-9A-Z_a-z]")


def _active_view_id(state):
    """Best-effort target panel id for threshold-chain operations.

    Prefers the Attributes drawer's `drawer_target_view_id` (picker
    in the Attributes toolbar — follows the active panel by default,
    can be pinned to any view), falls back to `fespp_active_panel_id`
    for the boot window before the drawer picker has fired."""
    target = getattr(state, "drawer_target_view_id", "") or ""
    if target:
        return target
    return getattr(state, "fespp_active_panel_id", "") or ""


def _find_property_path_by_title(tree, rep_path, array_title):
    """Walk the rep's subtree for a property node whose title (or
    `propTitle` for MR nodes) matches `array_title` after sanitisation.
    Returns the tree path or None.

    Used by `_resolve_vtk_array_name` to map the title-only state var
    `active_color_array_name` to the property's array_path — needed
    to detect MR vs non-MR via `is_multirealization_property(path)`.
    Previously we read the path from
    `ui_active_array_by_rep_by_view[view][rep]`, but that bucket only
    follows EYE clicks; if the user tree-activates a NEW property
    without clicking its eye, the bucket still holds the previous
    property's path → the resolver would mistakenly apply MR
    suffixing of the new title with the OLD property's realization
    idx, building a non-existent VTK array name."""
    if not array_title or tree is None or not rep_path:
        return None
    rep_id = tree.find_node_id(rep_path)
    if rep_id is None:
        return None
    sanitized = _NAME_INVALID_RE.sub("", array_title)
    if not sanitized:
        return None
    for child_id in tree.find_all_descendant_ids(rep_id):
        kind = tree.find_type(child_id) or ""
        is_prop = (
            "Property" in kind
            or kind in ("TimeSeries", "MultiRealization", "MultiRealizationTimeSeries")
        )
        if not is_prop:
            continue
        child_title = tree.find_title(child_id) or ""
        if kind in ("MultiRealization", "MultiRealizationTimeSeries"):
            pt = tree.find_attribute_value(child_id, "propTitle")
            if pt:
                child_title = pt
        if _NAME_INVALID_RE.sub("", child_title) == sanitized:
            return tree.find_path(child_id)
    return None


def _resolve_vtk_array_name(state, tree, view_id, rep_path, array_title):
    """Map the property-title fallback (`state.active_color_array_name`)
    to the actual VTK array stored on the source.

    For non-MR properties the title IS the VTK array name (modulo
    PV's sanitisation). For MR properties the VTK array is
    `<sanitized_title>_real_<idx>` where `<idx>` is the realization
    picked by this view via the per-view RealizationPicker. Without
    this resolution step, `RepInScene._add_threshold_local` would
    fail at `_resolve_assoc(title)` (the title alone isn't an array
    name) and the user would see no threshold appear after clicking
    Add — the silent-fail bug observed during 2026-05-27 smoke
    test.

    Resolution path:
      1. Find the property's tree node by walking the rep subtree
         for one matching the title. This binds the title to a
         specific array_path so we know exactly which property is
         being thresholded — important when the title and the
         eye-binding refer to different properties.
      2. If is_mr, look up (or auto-pick) the realization for this
         view + array_path and return the suffixed VTK name.
      3. Otherwise return the title unchanged."""
    if not array_title or tree is None:
        return array_title
    array_path = _find_property_path_by_title(tree, rep_path, array_title)
    if not array_path:
        # Fallback: use the eye-binding's array_path if the title
        # walk missed (defensive — every reachable property should be
        # discoverable from the rep's subtree).
        by_view = state.ui_active_array_by_rep_by_view or {}
        array_path = (by_view.get(view_id, {}) or {}).get(rep_path)
    if not array_path:
        return array_title
    if not realization_dispatch.is_multirealization_property(tree, array_path):
        return array_title
    realization_idx = realization_dispatch.get_active_realization_for_view(
        state, view_id, array_path,
    )
    if realization_idx is None:
        # MR property activated via tree selection but no realization
        # explicitly picked in this view yet (no eye click on the
        # array). Auto-pick the first available index AND persist it
        # to the view's realization bucket so subsequent ColorBy /
        # threshold ops see a consistent choice. Without persistence
        # the threshold lands on `_real_<default>` while ColorBy stays
        # in SolidColor — confusing for the user.
        realization_idx = realization_dispatch.default_realization_for(
            state, tree, array_path,
        )
        if realization_idx is None:
            return array_title
        realization_dispatch.set_active_realization_for_view(
            state, view_id, array_path, realization_idx,
        )
    # Sanitize the title the same way the FESPP plugin does when
    # naming VTK arrays (strip chars outside [-.0-9A-Z_a-z]).
    sanitized = _NAME_INVALID_RE.sub("", array_title)
    return realization_dispatch.suffixed_array_name(sanitized, int(realization_idx))


def threshold_provider(state, scene_registry, source_registry, view_id=None):
    """Return `(provider, rep_path)` for the active rep, or
    `(None, None)` when no chain-capable rep is active.

    Phase 3a/3b routing:
      - IjkGrid AND UnstructuredGrid → per-view `RepInScene` from
        `scene_registry`. For IjkGrid the chain is owned by the
        scene's per-view `IjkGrid` instance (`_per_view_ijk`);
        `RepInScene._ijk_provider()` delegates there. For non-IjkGrid
        the chain lives on `RepInScene._chain`.
      - Fallback to legacy `SourceRegistry` ONLY when the scene
        registry has no view at all (truly early boot before
        `multi_view.add_view` ran). When the scene EXISTS but the rep
        hasn't been synced yet (the activator runs threshold-UI
        publish before `sync_loaded_reps` adds the rep) we return
        `(None, None)` to publish an empty chain silently — falling
        back to SourceRegistry there would trigger a spurious
        `[DEPRECATED]` print and shows no chain anyway (the rep just
        loaded, no thresholds exist yet)."""
    rep_type = state.ui_active_node_reservoir_type_rep
    grid_path = state.active_representation_path
    if not grid_path:
        return None, None
    if rep_type in ("IjkGrid", "UnstructuredGrid"):
        vid = view_id or _active_view_id(state)
        if scene_registry is not None and vid:
            rep = scene_registry.get_rep(vid, grid_path)
            if rep is not None:
                return rep, grid_path
            # Scene exists but rep not synced yet → empty chain,
            # no legacy fallback. Skip the warning print.
            if scene_registry.has_view(vid):
                return None, None
        if rep_type == "IjkGrid":
            ijk = source_registry.get_ijk_grid(grid_path)
            return (ijk, grid_path) if ijk is not None else (None, None)
        # Fallback: legacy ExtractBlockRepresentation behaviour.
        # `source_registry` itself is the provider; its compat methods
        # take `rep_path` as their first argument — that asymmetry is
        # confined to the four wrappers below.
        return source_registry, grid_path
    return None, None


def hide_unused_scalar_bars():
    """Compat shim — delegates to `source_resolver.hide_unused_scalar_bars`."""
    from fespp_on_trame.app.core.engine import source_resolver
    source_resolver.hide_unused_scalar_bars()


def _is_per_view_provider(provider):
    """True when the provider follows the no-rep-path call convention
    (`IjkGrid` and `RepInScene`); False when it's the legacy
    `SourceRegistry` (whose compat methods take rep_path first)."""
    # Avoid importing concrete classes here to keep the module light;
    # the `SourceRegistry` is the only "legacy" provider, recognised
    # by its `get_ijk_grid` attribute. Everything else (IjkGrid,
    # RepInScene) goes through the per-view branch.
    return not hasattr(provider, "get_ijk_grid")


def publish_threshold_chain(state, scene_registry, source_registry, view_id=None):
    """Push the active rep's chain into `state.ui_threshold_chain` so
    the UI re-renders. Idempotent — call after any chain mutation or
    after the active view / rep changes.

    Per-view: the published chain is the one belonging to the active
    view (or `view_id` if explicitly passed). The UI panel keeps
    reading the flat `ui_threshold_chain` state var — same wire
    contract as before."""
    provider, rep_path = threshold_provider(state, scene_registry, source_registry, view_id=view_id)
    if provider is None:
        state.ui_threshold_chain = []
        return
    chain = provider.get_chain() if _is_per_view_provider(provider) else provider.get_chain(rep_path)
    depth_by_name = {}
    for entry in chain:
        parent = entry.get("parent_name")
        depth_by_name[entry["name"]] = (
            0 if parent is None else depth_by_name.get(parent, 0) + 1
        )
        entry["_depth"] = depth_by_name[entry["name"]]
    # DFS reorder: emit each entry right after its parent's subtree.
    children_by_parent: dict = {}
    for entry in chain:
        children_by_parent.setdefault(entry.get("parent_name"), []).append(entry)
    ordered: list = []

    def _emit(parent_name):
        for child in children_by_parent.get(parent_name, []):
            ordered.append(child)
            _emit(child["name"])

    _emit(None)
    state.ui_threshold_chain = ordered


def refresh_threshold_ui_for_active_grid(state, scene_registry, source_registry, view_id=None):
    """Republish the chain + available arrays on grid switch /
    property load / active-view change."""
    provider, rep_path = threshold_provider(state, scene_registry, source_registry, view_id=view_id)
    if provider is None:
        state.update({
            "ui_threshold_chain": [],
            "ui_threshold_arrays_available": [],
        })
        return
    arrays = provider.available_arrays() if _is_per_view_provider(provider) else provider.available_arrays(rep_path)
    state.ui_threshold_arrays_available = [n for _, n in arrays]
    publish_threshold_chain(state, scene_registry, source_registry, view_id=view_id)


def threshold_add(state, controller, scene_registry, source_registry, activator, view,
                  parent_name=None, array=None, view_id=None, tree=None):
    """Add a threshold under `parent_name` (or the rep root if None).
    The array defaults to the currently visible active property — per
    spec, no blind threshold-on-anything VSelect.

    `tree` (optional) is used to detect MR properties and substitute
    the suffixed VTK array name (`<title>_real_<idx>`) when the
    fallback array is a property title. Without `tree` the resolver
    is bypassed (MR properties will silently miss — caller should
    pass tree)."""
    provider, rep_path = threshold_provider(state, scene_registry, source_registry, view_id=view_id)
    if provider is None:
        return
    if not array:
        array = state.active_color_array_name or None
    if not array:
        print("[WARNING] threshold_add: no active array to bind onto")
        return
    vid = view_id or _active_view_id(state)
    if tree is not None and rep_path and vid:
        resolved = _resolve_vtk_array_name(state, tree, vid, rep_path, array)
        if resolved and resolved != array:
            print(f"[threshold_add] MR resolution: {array!r} → {resolved!r}"
                  f" (view={vid}, rep={rep_path})")
            array = resolved
    if _is_per_view_provider(provider):
        new_name = provider.add_threshold(parent_name, array)
    else:
        new_name = provider.add_threshold(rep_path, parent_name, array)
    if new_name is None:
        print(f"[threshold_add] provider returned None for array={array!r}"
              f" — array may not exist on the source (MR without picked realization?)")
        return
    publish_threshold_chain(state, scene_registry, source_registry, view_id=view_id)
    if activator is not None:
        try:
            activator.refresh_active()
        except Exception:
            pass
    hide_unused_scalar_bars()
    _render_and_push(state, controller, view)


def threshold_delete(state, controller, scene_registry, source_registry, view, name, view_id=None):
    provider, rep_path = threshold_provider(state, scene_registry, source_registry, view_id=view_id)
    if provider is None or not name:
        return
    if _is_per_view_provider(provider):
        provider.delete_threshold(name)
    else:
        provider.delete_threshold(rep_path, name)
    publish_threshold_chain(state, scene_registry, source_registry, view_id=view_id)
    hide_unused_scalar_bars()
    _render_and_push(state, controller, view)


def threshold_set_range(state, controller, scene_registry, source_registry, view,
                       name, low, high, view_id=None):
    provider, rep_path = threshold_provider(state, scene_registry, source_registry, view_id=view_id)
    if provider is None or not name:
        return
    try:
        low = float(low)
        high = float(high)
    except (TypeError, ValueError):
        return
    if _is_per_view_provider(provider):
        provider.set_range(name, low, high)
    else:
        provider.set_range(rep_path, name, low, high)
    publish_threshold_chain(state, scene_registry, source_registry, view_id=view_id)
    _render_and_push(state, controller, view)


def threshold_set_visible(state, controller, scene_registry, source_registry, activator, view,
                          name, visible, view_id=None):
    provider, rep_path = threshold_provider(state, scene_registry, source_registry, view_id=view_id)
    if provider is None or not name:
        return
    if _is_per_view_provider(provider):
        provider.set_visible(name, bool(visible))
    else:
        provider.set_visible(rep_path, name, bool(visible))
    publish_threshold_chain(state, scene_registry, source_registry, view_id=view_id)
    if activator is not None:
        try:
            activator.refresh_active()
        except Exception:
            pass
    hide_unused_scalar_bars()
    _render_and_push(state, controller, view)


def on_threshold_pending_action(state, action,
                                threshold_add, threshold_delete,
                                threshold_set_range, threshold_set_visible):
    """Single-entry-point dispatcher for UI threshold events.

    The UI writes a `{action, ...}` dict into the
    `ui_threshold_pending_action` sentinel; this handler routes it
    to the matching controller method, then clears the sentinel so
    subsequent identical actions still fire (Trame collapses no-op
    writes).

    The four `threshold_*` callables are the controller-registered
    closures from boot.py — passed in rather than re-imported so this
    module stays oblivious to the engine wiring."""
    if not action:
        return
    try:
        kind = action.get("action")
        if kind == "add":
            threshold_add(parent_name=action.get("parent"))
        elif kind == "delete":
            threshold_delete(action.get("name"))
        elif kind == "set_range":
            threshold_set_range(
                action.get("name"),
                action.get("low"),
                action.get("high"),
            )
        elif kind == "set_visible":
            threshold_set_visible(action.get("name"), action.get("visible"))
        else:
            print(f"[WARNING] unknown threshold action: {kind!r}")
    finally:
        state.ui_threshold_pending_action = None
