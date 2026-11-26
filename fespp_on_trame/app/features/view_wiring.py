"""The per-view wiring: `wire_view` (the view manager calls it for each
view it creates), the scene made for a view (the Globe's, one turn after
its view), the cards a view offers, opened and placed (`toggle_tool`,
`card_geometry`).

trame @state.change handlers can never be unregistered — guard against a
second wire_view call for the same LIVE vid (panel rebuild / id reuse)
stacking N copies of the per-view closures.

(Moved out of app/boot, overhaul slice 10.)"""
import sys
from fespp_on_trame.app.views import per_view_state
from fespp_on_trame.app.views.widgets import card_dock
from fespp_on_trame.engine.state_defaults import z_scale_of
from fespp_on_trame.engine import node_facts
from fespp_on_trame.engine import tree_families


def register(core, *, _apply_cmap_nodes, _axes_grid_titles, _cursor_mode_off,
             _cursor_pos, _defer, _detect_crs,
             _push_active_array_label,
             _push_card_arrays, _push_colormap_state, _push_globe_state,
             _push_slicer_state, _push_threshold_note, _push_threshold_state,
             _push_volumetrics, _rep_path_of, _selection_off, _set_tool_target,
             _slicer_armed, _slicer_grid, _threshold_isolate,
             _threshold_target):
    """Wire the section's controllers and watchers; hands back what
    the rest of the app still calls (_volumetrics_rep, _wired_vids)."""
    # the shared services (app/core/context.Core)
    state = core.state
    controller = core.controller
    ctx = core.ctx
    tree = core.tree
    active_data_source = core.active_data_source
    source_registry = core.source_registry
    selector = core.selector
    scheduler = core.scheduler
    activation = core.activation
    cards = core.cards
    displays = core.displays
    _mv = core.mv
    selection = core.selection
    # trame @state.change handlers can never be unregistered — guard against a
    # second wire_view call for the same LIVE vid (panel rebuild / id reuse)
    # stacking N copies of the per-view closures.
    _wired_vids = set()

    # the panels whose tree the Values view follows while they are the active view: their kind -> the name of
    # their tree's active node
    _PANEL_TREES = {"welllog": "welllog_tree_active__", "compare": "compare_tree_active__",
                    "reconcile": "reconcile_tree_active__"}

    @controller.set("values_focus")
    def values_focus(tree_kind, path):
        """A panel's tree (the log view's, the Statistics', the Log ↔ Grid
        one) made `path` its active node: the Values view reads it, until a
        3D view or its tree is used again (app/scene/activation)."""
        if path:
            activation.focused(str(tree_kind or ""), str(path))

    @controller.set("welllog_focus")
    def welllog_focus(view_id, path):
        """The log view's tree made `path` its active node: the view brings
        its graph to its middle (engine/node_facts.log_view_focus); `n`
        counts the asks, so a node made active again is brought back."""
        var = f"welllog_focus__{view_id}"
        focus = node_facts.log_view_focus(tree, str(path or ""))
        n = int((getattr(state, var, None) or {}).get("n") or 0) + 1
        state[var] = dict(focus, n=n) if focus else None

    @state.change("fespp_active_panel_id")
    def _values_follow_the_active_view(fespp_active_panel_id=None, **_):
        """The Values view reads the active node of the active view's tree: a
        3D view's, or a panel's that has one; another panel made active (the
        Values view itself) changes nothing."""
        mv = _mv()
        pid = str(fespp_active_panel_id or "")
        kind = mv.kind_of(pid) if mv is not None and pid else ""
        if kind == "render":
            activation.unfocused()
        elif kind in _PANEL_TREES:
            path = getattr(state, _PANEL_TREES[kind] + pid, None) or ""
            if path:
                activation.focused(kind, path)

    def _attach_domain(vid, scene):
        """Depth or time: what the view draws (app/features/view_domain)."""
        attach = getattr(ctx, "attach_view_domain", None)
        if attach is not None:
            attach(vid, scene)

    def _make_scene(vid, pv_view, *, globe):
        """This view's scene.

        ``globe`` = the same data projected onto the Earth (the Globe
        view). It is KEYWORD-ONLY on purpose: a caller passing the view KIND
        positionally (the truthy string "render") would silently turn every
        view into a Globe; a positional call raises instead.

        The ActiveSource facade is passed, NOT the raw collector: the scene
        must follow the source that actually holds the data (ETP store after
        a connect) — ensure_main_rep self-heals on source flips."""
        if globe:
            from fespp_on_trame.engine.blockscope.globe_scene import GlobeScene
            from fespp_on_trame.engine import geo as _g
            _granted, _note = _g.earth_texture_affordable(state.ui_globe_texture)
            state.ui_globe_texture = _granted
            state.ui_globe_texture_note = _note
            scene = GlobeScene(
                vid, pv_view, active_data_source, scheduler,
                texture=_g.earth_texture_path(_granted))
            ctx.blockscope_scenes[vid] = scene
            # the vertical domain the view draws, before its first projection
            _attach_domain(vid, scene)
            try:
                scene.set_zscale(z_scale_of(state, vid))   # radial
                crs = _detect_crs()
                scene.set_epsg(crs["epsg"] if crs else 0)
                scene.ensure_earth()
                scene.reconcile()
                scene.frame("earth")
                _push_globe_state(vid)
            except Exception as exc:
                print(f"[fespp] globe init error ({vid}): {exc!r}", file=sys.stderr, flush=True)
        else:
            from fespp_on_trame.engine.blockscope.pdc_scene import PdcScene
            scene = PdcScene(vid, pv_view, active_data_source, scheduler)
            ctx.blockscope_scenes[vid] = scene
            # the vertical domain the view draws, before its first projection
            _attach_domain(vid, scene)
            scene.show_selection(selection.owner_vid in ("", vid))
            scene._zscale = z_scale_of(state, vid)
            try:
                # materialize main_rep NOW projected from the (empty) table —
                # a fresh composite rep would otherwise show ALL blocks.
                scene.reconcile()
            except Exception as exc:
                print(f"[fespp] pdc_scene init error ({vid}):", exc, flush=True)
        # the wellheads drawn in this view (never on the Earth, where they
        # would sit at projected coordinates), deleted with the view
        displays.add(
            vid, "wellheads", "wellhead", None,
            follows_z=False,   # selector.apply_z_scale re-anchors every head
            close=lambda v=vid: selector.drop_view(v))
        return scene

    def _view_kind(vid):
        """"globe" for the Globe view, "render" for a 3D view."""
        return "globe" if getattr(state, f"ui_globe_mode__{vid}", False) else "render"

    @controller.set("globe_build")
    def globe_build(view_id):
        """The Globe view's scene, now: the data projected onto the Earth,
        then the view's eyes replayed onto it; nothing once it is built.
        Its door runs it one turn after the view (`_globe_later`); a session
        restored runs it at once, before the Globe's code, framing and
        camera are put back."""
        vid = str(view_id)
        if not per_view_state.is_live(vid) or vid in ctx.blockscope_scenes:
            return
        mv = _mv()
        pv_view = mv.get_pv_view(vid) if mv is not None else None
        if pv_view is None:
            return
        _make_scene(vid, pv_view, globe=True)
        _refresh_view_tools(vid)
        _apply_axes_labels(vid)
        try:
            controller.on_eye_changed(
                vid, list(getattr(state, f"visible_paths__{vid}", None) or []))
        except Exception as exc:
            print(f"[fespp] globe eyes ({vid}):", exc, flush=True)
        scheduler.mark_dirty(vid)
        scheduler.flush()

    def _globe_later(vid):
        """The Globe view on screen at once under its wait bar, its scene one
        turn later: the projection runs over every block and the eyes are
        replayed, seconds on a real grid (`heavy_pending` waits on it)."""
        state[f"ui_globe_busy__{vid}"] = True

        def build():
            try:
                globe_build(vid)
            finally:
                if per_view_state.is_live(vid):
                    state[f"ui_globe_busy__{vid}"] = False
        _defer(f"globe:{vid}", build, [vid])


    def _has_grid(vid):
        """Offer the slicers exactly when they can act: same resolver the
        panel and the isolate use, so the button never promises an empty
        panel. Since 29/10 the card cuts the whole scene when no object is
        picked or active: offered as soon as the view draws something."""
        pick = getattr(ctx, "geometry_target", None)
        if pick is not None:
            return bool(pick(vid))
        path, _sel, _scene = _slicer_grid(vid)
        return bool(path)

    def _volumetrics_rep(vid):
        """The representation the Volumetrics card of this view cubes: the
        Reservoir tab's active node when it has cells with a volume (a grid,
        a cell sub-representation, a blocked wellbore), else the first loaded
        one — the slicer's rule, over a wider family."""
        return activation.target_of(vid, "volumetrics")

    def _has_thresholdable(vid):
        """The Thresholds card can act as soon as a property is read on a
        representation a threshold can isolate — a grid, a
        sub-representation, a surface, a polyline or point set (the PO,
        27/10: "dès qu'il y a 1 propriété de cochée, ijkgrid ou autre, même
        surface"). WIDER THAN THE SLICERS, on purpose: a crop needs a
        structured grid, a threshold only values."""
        from fespp_on_trame.engine.node_kinds import ISOLATABLE_KINDS
        for array_path in state.ui_loaded_array_paths or ():
            rep = _rep_path_of(array_path)
            nid = tree.find_node_id(rep) if rep else None
            if nid is not None and (tree.find_type(nid) or "") in ISOLATABLE_KINDS:
                return True
        return False

    def _has_series(vid):
        """A time series or a multi-realization property is read: the
        TS/MR card has something to step through."""
        from fespp_on_trame.engine import node_facts
        for path in state.ui_loaded_array_paths or ():
            nid = core.tree.find_node_id(path)
            if nid is not None and (core.tree.find_type(nid) or "") in node_facts.SERIES_KINDS:
                return True
        return False

    def _has_other_view(vid):
        """Another plain 3D view to link this one's camera to (a Globe
        view's camera lives on the Earth: it links to nothing)."""
        others = [p for p in (state.fespp_render_panels or [])
                  if p.get("id") != vid and not p.get("globe")]
        return bool(others)

    # tag -> "can this tool act in this view?" (a tool that cannot is
    # greyed with its reason, tools_config.NEEDS_WHY)
    _TOOL_NEEDS = {
        # a tree card: the data holds an object of its family
        **{key: (lambda vid, key=key: key in tree_families.present(
            state.assembly_xml or "", getattr(state, "ui_cube_grid_rows", None) or ()))
           for key in tree_families.KEYS},
        "grid": _has_grid,
        "thresholdable": _has_thresholdable,
        "volume": lambda vid: bool(_volumetrics_rep(vid)),
        "loaded": lambda vid: bool(state.ui_loaded_rep_paths),
        "property": lambda vid: bool(state.ui_loaded_array_paths),
        "series": _has_series,
        "views": _has_other_view,
    }

    # the cards closed by the toolbar when their tool can no longer act, and
    # whether each could act at the last look: (vid, key) -> bool
    _CLOSED_WHEN_IDLE = ("slicers", "thresholds")
    _able = {}

    def _refresh_view_tools(vid):
        """The toolbar of THIS view: every tool its KIND serves (a 3D view, the
        Globe), those whose ``needs`` precondition is not met greyed with the
        reason as their title (tools_config.toolbar). Recomputed server-side
        on every change that can flip an answer — a view is built long
        before any data exists, so a list frozen at build time is always
        wrong."""
        from fespp_on_trame.app.views.tools_config import (
            TOOLS, MODE_TOOLS, NEEDS_WHY, NO_DATA_WHY, toolbar)
        kind = _view_kind(vid)
        entries = [t for t in TOOLS if kind in t.get("kinds", ("render", "globe"))]
        if kind == "render":
            entries += MODE_TOOLS
        has_data = bool(state.ui_has_data)
        # a slicer card left with nothing to act on — its object unticked,
        # nothing drawn any more — closes, and its button greys (the PO,
        # 03/11: "si plus rien dans la 3D view le slicer est inutile"). On
        # the change only: a card opened before its object is drawn (a
        # session put back) is not closed under the reader
        for t in entries:
            if t["key"] not in _CLOSED_WHEN_IDLE:
                continue
            try:
                able = has_data and bool(_TOOL_NEEDS[t["needs"]](vid))
            except Exception as exc:
                print(f"[fespp] toolbar gate {t['needs']!r} ({vid}):", exc, flush=True)
                able = True
            was = _able.get((vid, t["key"]))
            _able[(vid, t["key"])] = able
            if was and not able and cards.is_open(vid, t["key"]):
                cards.close(vid, t["key"])
        # a card open stays closable: its button is not greyed under it
        open_keys = set(cards.keys(vid) or ())

        def gate(t):
            # nothing imported (no EPC, no ETP dataspace): every one of
            # these tools acts on data
            if not has_data:
                return NO_DATA_WHY
            need = t.get("needs")
            if not need or t["key"] in open_keys:
                return ""
            try:
                if _TOOL_NEEDS[need](vid):
                    return ""
            except Exception as exc:
                # never grey a tool because a probe threw
                print(f"[fespp] toolbar gate {need!r} ({vid}):", exc, flush=True)
                return ""
            return NEEDS_WHY.get(need, "nothing to act on yet")

        state[f"view_tools_{vid}"] = toolbar(entries, gate)

    def _apply_axes_labels(vid):
        """The orientation axes of a view (bottom left) lettered after the
        data's CRS — E N Z for "Easting Northing" (`geo.axes_labels`), the
        whole names being in the pick readout; X Y Z on the Globe, whose axes
        are the Earth's, and before any CRS is known."""
        mv = _mv()
        pvv = mv.get_pv_view(vid) if mv is not None else None
        if pvv is None:
            return
        from fespp_on_trame.engine import geo
        globe = bool(getattr(state, f"ui_globe_mode__{vid}", False))
        # the CRS of the view's vertical domain: T in a view switched to time
        labels = ("X", "Y", "Z") if globe else geo.axes_labels(ctx.view_crs(vid))
        # the axes grid's titles follow the same CRS, shown or not
        _axes_grid_titles(vid, pvv)
        changed = False
        for axis, text in zip("XYZ", labels):
            prop = f"OrientationAxes{axis}LabelText"
            try:
                if getattr(pvv, prop) != text:
                    setattr(pvv, prop, text)
                    changed = True
            except Exception as exc:
                print(f"[fespp] axes label ({vid}):", exc, flush=True)
        if changed:
            scheduler.mark_dirty(vid)

    # a view switched to depth or time letters its axes again (view_domain)
    ctx.apply_axes_labels = _apply_axes_labels

    @state.change("ui_loaded_rep_paths", "ui_loaded_array_paths", "selected_paths",
                  "fespp_render_panels", "ui_open_tools_by_view", "assembly_rev", "ui_cube_grid_rows")
    def _on_loaded_reps_tools(**_):
        # checking (or unchecking) a grid makes the slicers worth offering,
        # and changes what an open Thresholds card can say
        for vid in list(getattr(ctx, "blockscope_scenes", None) or {}):
            if per_view_state.is_live(vid):
                _refresh_view_tools(vid)
                _push_threshold_note(vid)
                _apply_axes_labels(vid)

    @state.change("ui_has_data")
    def _on_has_data(**_):
        # the first import populates every view's toolbar; a reset empties it
        from fespp_on_trame.app.views.tools_config import TOOLS, default_open_keys
        defaults = {}
        for vid in list(getattr(ctx, "blockscope_scenes", None) or {}):
            if not per_view_state.is_live(vid):
                continue
            _refresh_view_tools(vid)
            # A view built before any import opened nothing; give it its
            # default cards now — but never override what the user arranged.
            if state.ui_has_data and not cards.keys(vid):
                defaults[vid] = default_open_keys(TOOLS, _view_kind(vid), state.assembly_xml or "",
                                                  getattr(state, "ui_cube_grid_rows", None) or ())
        cards.set_many(defaults)

    @state.change("ui_cube_grid_rows")
    def _tree_card_follows(**_):
        # the lattice grids are listed after the assembly: a view left with a
        # Reservoir card that holds nothing shows the Seismic one, where they went
        held = tree_families.present(state.assembly_xml or "", getattr(state, "ui_cube_grid_rows", None) or ())
        first, seismic = tree_families.KEYS[0], tree_families.SEISMIC
        if first in held or seismic not in held:
            return
        moved = {}
        for vid in list(getattr(ctx, "blockscope_scenes", None) or {}):
            keys = cards.keys(vid) if per_view_state.is_live(vid) else []
            if first in keys and seismic not in keys:
                moved[vid] = [seismic if k == first else k for k in keys]
        cards.set_many(moved)

    def _wire_cursor(vid):
        """The reading mouse of `vid`: each sample of the pointer
        (`pos_ev__`, throttled client-side, written only while the mouse
        mode is on) read into the readout's line."""
        pos_var = f"pos_ev__{vid}"

        @state.change(pos_var)
        def _on_pos_ev(**kw):
            if not per_view_state.is_live(vid):
                return
            if not getattr(state, f"ui_cursor_mode__{vid}", False):
                return
            state[f"ui_cursor_pos__{vid}"] = _cursor_pos(vid, kw.get(pos_var))

    @controller.set("wire_bare_view")
    def wire_bare_view(vid, pv_view, kind="bare"):
        """A view that draws one thing on its own — the Stratigraphy panel's
        velocity model (view_manager, `render_view: "bare"`): its state
        seeded, its axes lettered, its reading mouse wired, the velocity model drawn.
        No scene, no eyes, no tools, no colour handlers: nothing of the
        data is drawn there."""
        per_view_state.seed(state, vid)
        if vid in _wired_vids:
            return
        _wired_vids.add(vid)
        _apply_axes_labels(vid)
        _wire_cursor(vid)

    @controller.set("wire_view")
    def wire_view(vid, pv_view, kind="render"):
        per_view_state.seed(state, vid)
        if kind == "globe":
            # what reads the flag (camera, navigation, picking, the title
            # bar) knows the Globe from its birth, before its scene exists
            state[f"ui_globe_mode__{vid}"] = True
        # an exaggeration asked for before there was a view
        waiting_z = getattr(ctx, "zscale_no_view", None)
        if waiting_z:
            state[f"ui_scale_z__{vid}"] = waiting_z
            ctx.zscale_no_view = None
        if vid not in ctx.blockscope_scenes:
            if kind == "globe":
                _globe_later(vid)
            else:
                _make_scene(vid, pv_view, globe=False)
        if vid in _wired_vids:
            return
        _wired_vids.add(vid)
        # This view's toolbar, now that its state exists: the panel was built
        # before wiring, so its seeded list has not seen the `needs` gates yet.
        _refresh_view_tools(vid)
        _apply_axes_labels(vid)

        col_var = f"colour_request__{vid}"
        act_var = f"active_path__{vid}"
        folder_var = f"values_folder__{vid}"
        values_var = f"ui_values_node__{vid}"
        colors_var = f"ui_cmap_colors__{vid}"
        opac_var = f"ui_cmap_opacities__{vid}"

        _wire_cursor(vid)

        @state.change(colors_var)
        def _on_cmap_colors(**kw):
            _apply_cmap_nodes(vid, "colors", kw.get(colors_var))

        @state.change(opac_var)
        def _on_cmap_opacities(**kw):
            _apply_cmap_nodes(vid, "opacities", kw.get(opac_var))

        values_read = {"path": ""}

        def _values_node_moved():
            # the Values view is titled by the node it reads ("Values ·
            # Facies"), a geometry by its object's name; the Geometry slicer
            # follows the active node too
            path = activation.values_path(vid)
            nodes = dict(state.ui_active_node_by_view or {})
            n_id = tree.find_node_id(path) if path else None
            nodes[vid] = (tree.find_rep_title(n_id) or "") if n_id is not None else ""
            state.ui_active_node_by_view = nodes
            state.ui_values_key_by_view = {**(state.ui_values_key_by_view or {}), vid: path or ""}
            _refresh_view_tools(vid)
            # another node invalidates the page shown; the same node, reached
            # another way (a folder's reading, then its row), keeps it
            if path != values_read["path"]:
                values_read["path"] = path
                if (state.ui_node_values_by_view or {}).get(vid):
                    controller.values_node_moved(vid)

        @state.change(folder_var)
        def _on_values_folder(**_):
            if per_view_state.is_live(vid):
                activation.values_update(vid)

        @state.change(values_var)
        def _on_values_node(**_):
            if per_view_state.is_live(vid):
                _values_node_moved()

        @state.change(act_var)
        def _on_active(**kw):
            # Feed THIS view's Attributes/COE card from the active tree node:
            # available arrays of its rep + the array it currently colours by.
            if not per_view_state.is_live(vid):
                return
            path = kw.get(act_var) or ""
            rep_path = _rep_path_of(path) if path else ""
            # the cards follow it again, an object picked in their list let go
            if path:
                activation.unpinned(vid)
            _push_card_arrays(vid, path)
            # the volumetrics card of this view follows its active grid
            _push_volumetrics(vid)
            # the Values card comes back to it from a folder ticked, and from
            # a panel's tree used last (activation.focus)
            if getattr(state, folder_var, None):
                state[folder_var] = []
            activation.unfocused()
            activation.values_update(vid)
            _values_node_moved()
            # (no XML here any more: the XML explorer is its own view, opened
            # by the XML button, the tree's and the render's right-click —
            # the manager, 15/10, found a third copy in this card confusing)
            _push_active_array_label(vid)
            try:
                _push_colormap_state(vid)
            except Exception as exc:
                print(f"[fespp] colormap projection error ({vid}):", exc,
                      flush=True)
            # the view's one colour bar follows the table the card now
            # edits (engine/legends): drawn now, a click renders nothing else
            scheduler.flush()
            # Seed this view's slicer panel with the active grid's extents
            # (idle full-extent state, or the live isolate's if one exists).
            try:
                # keyed by the grid the slicers act on (the Reservoir tab's),
                # not by the displayed tab's node: a click on a wellbore must
                # not show a still-cut grid as idle
                grid_path = _slicer_grid(vid)[0]
                iso = ((getattr(ctx, "grid_isolates", None) or {}).get((vid, grid_path))
                       if grid_path else None)
                _push_slicer_state(vid, iso)
            except Exception:
                pass
            _push_threshold_note(vid, path, rep_path)
            # the Thresholds card lists its (new) target's chain, not the
            # last grid's (04-verification D15)
            _push_threshold_state(vid, _threshold_isolate(vid)[0])

        @state.change(col_var)
        def _on_col(**kw):
            # colormap icon on an array node -> colour that array's rep in THIS
            # view ('solid' swatch -> COE). The PV view is resolved via
            # multi_view at CALL time — capturing pv_view here would pin a
            # deleted proxy for the life of this never-unregistered handler.
            import sys
            if not per_view_state.is_live(vid):
                return
            req = kw.get(col_var) or {}
            # the tree's colour swatch sends 'solid' ("Edit colour"), the
            # array's colormap icon 'colormap': both open the editor on it
            if req.get("kind") not in ("colormap", "solid") or not req.get("path"):
                return
            rep_path = _rep_path_of(req["path"])
            if not rep_path:
                return
            try:
                # the colorBy is owned by the eyes: the colormap icon
                # ACTIVATES the array node and OPENS this view's Colormap
                # editor on it (icon = open the COE)
                activation.activate(vid, req["path"])
                cards.open(vid, "colormap")
            except Exception as exc:
                print(f"[fespp] colour_request error ({vid}):", exc,
                      file=sys.stderr, flush=True)

    @controller.set("card_geometry")
    def card_geometry(tool_key, view_id, geometry):
        """Where a tool card of `view_id` was left — moved, resized or
        docked — kept per view so a page reload puts it back there. The
        card reports {x, y, w, h, dock}; nothing else is trusted."""
        if not tool_key or not view_id or not isinstance(geometry, dict):
            return
        var = f"ui_card_geometry__{view_id}"
        cur = dict(getattr(state, var, None) or {})
        keep = {}
        for k in ("x", "y", "w", "h"):
            v = geometry.get(k)
            if isinstance(v, (int, float)) and v == v:
                keep[k] = float(v)
        dock = geometry.get("dock")
        keep["dock"] = dock if dock in ("float", "left", "right", "bottom") else "float"
        if cur.get(tool_key) == keep:
            return
        cur[tool_key] = keep
        state[var] = cur

    @controller.set("card_visibility")
    def card_visibility(event, view_id):
        """A card of the view's dock came on screen or went behind a tab. The
        last family tree on screen in any view is the one a Statistics view
        opens on (`ctx.last_tree_family`)."""
        ev = event if isinstance(event, dict) else {}
        if ev.get("id"):
            cards.seen(str(view_id), ev["id"], bool(ev.get("visible")))
            if ev.get("visible") and ev["id"] in tree_families.KEYS:
                ctx.last_tree_family = tree_families.NAMES[tree_families.KEYS.index(ev["id"])]

    @controller.set("card_in_use")
    def card_in_use(card_id, view_id):
        """A card of the view's dock became the one in use. A family's tree
        brings back its own active node — the one it had last, else its
        first object read, else its first row —: the cards (slicers,
        thresholds, Values) follow a node of the tree in use, never another
        family's (the PO, 23/11)."""
        vid = str(view_id or "")
        title = tree_families.title_of_key(str(card_id or ""))
        if not title or not per_view_state.is_live(vid):
            return
        node = tree_families.node_brought_back(
            tree, title, activation.path(vid), activation.by_tab(vid).get(title.lower()),
            getattr(state, "selected_paths", None),
            getattr(state, f"ui_tree_layout__{vid}", None) or "flat")
        if node:
            activation.activate(vid, node, tab=title.lower())

    @controller.set("close_tool")
    def close_tool(tool_key, view_id):
        """A card closed from its panel in the view's dock: closed as by its
        toolbar button, once (a second close asked meanwhile does nothing)."""
        if cards.is_open(str(view_id), tool_key):
            toggle_tool(tool_key, view_id)

    def _place_under_tree(vid, key, open_keys):
        """The card `key`, about to open in `vid`, docked under the tree card
        of the view's active node (card_dock.tree_anchor): its spec says so,
        written before the open list so the dock reads both together."""
        act = activation.path(vid)
        active_tree = (tree_families.key_of(state.assembly_xml or "", act,
                                            getattr(state, "ui_cube_grid_rows", None) or ())
                       if act else "")
        var = f"ui_card_specs__{vid}"
        specs = getattr(state, var, None) or {}
        placed = card_dock.anchored_specs(specs, key, card_dock.tree_anchor(key, open_keys, active_tree),
                                          card_dock.tab_mate(key, open_keys))
        if placed != specs:
            state[var] = placed

    @controller.set("toggle_tool")
    def toggle_tool(tool_key, view_id):
        # Open/close a tool's floating card in THIS view (per-view open-set).
        from fespp_on_trame.app.views.tools_config import MODE_TOOLS
        cur = cards.keys(view_id)
        modes = {m["key"]: m for m in MODE_TOOLS}
        spec = modes.get(tool_key)
        if spec is not None:
            # a MODE button: it flips a per-view state var, not a card. The
            # open-set still carries the key — that is what the toolbar
            # highlights.
            on = tool_key not in cur
            state[f"{spec['var']}{view_id}"] = on
            cur = [k for k in cur if k != tool_key] + ([tool_key] if on else [])
            other = spec.get("excludes")
            if on and other:
                cur = [k for k in cur if k != other]
                state[f"{modes[other]['var']}{view_id}"] = False
            if on:
                # a selection takes the left button: the title bar's mouse
                # mode (show position, scene fixed) gives way to it
                _cursor_mode_off(view_id)
            else:
                # the last selection tool off: its cells are deselected
                _selection_off(view_id)
        else:
            if cards.hidden(view_id, tool_key):
                # open behind another card's tab: its button brings it in
                # front, as a view's button does
                cards.reveal(view_id, tool_key)
                return
            opening = tool_key not in cur
            cur = ([k for k in cur if k != tool_key] if tool_key in cur
                   else cur + [tool_key])
            if opening and tool_key in card_dock.UNDER_TREE:
                _place_under_tree(str(view_id), tool_key, cur)
        cards.set(view_id, cur)
        # The Geometry slicer cuts with its rows only (the PO's manager,
        # 28/10: no "Enable" any more): opening the card shows them, it no
        # longer switches a Volume mode on; a row added is what cuts.
        if tool_key == "slicers" and tool_key in cur:
            try:
                rep_path, _sel, _scene = _slicer_grid(view_id)
                _push_slicer_state(view_id, ctx.grid_isolates.get((view_id, rep_path)) if rep_path else None)
            except Exception as exc:
                print(f"[fespp] geometry slicer at open ({view_id}):", exc, flush=True)
        # The Property slicer opens on the active property (the PO, 30/10):
        # a card with no box takes a box with it.
        if tool_key == "thresholds" and tool_key in cur:
            hook = getattr(ctx, "property_card_open", None)
            if hook is not None:
                try:
                    hook(view_id)
                except Exception as exc:
                    print(f"[fespp] property slicer at open ({view_id}):", exc, flush=True)
    return (_volumetrics_rep, _wired_vids)
