"""Depth or time, per 3D view: its title bar says which, and switches it.

Depth and time are two vertical references: an object's vertical axis is a
depth or a seismic two-way time, as its local CRS says (the plugin's
`vdomain` on its node, engine/crs_reference.domain_of). A 3D view draws
one domain: a block of the other keeps its tick and its eye and is simply
not drawn (PdcScene.shown_selectors, app/scene/occupancy), so a switch
recomputes nothing in ParaView — the blocks only go back into the
composite's list. One view whose domain switches, rather than a second
view stacked under it: every panel of the app is ONE ParaView view (the
layout, the cards, the camera links, the sessions are keyed by it), and a
hidden twin would double each of them. One camera for both domains: a
switch keeps it, the view is framed once, on the first object it draws
(the PO, 29/10).

A view has no domain of its own to defend: empty, it takes the domain of
the first objects ticked in it, nothing asked (it opens saying depth, and an
object in time ticked first turns it to time — with an active velocity model
too). The questions are for the ticks that follow, of the domain the view is
not in. Empty: it shows nothing in its domain (nothing of it, nothing
converted, nothing that has no domain), and the
Time-depth model's view is not working in it.

An object in time ticked in a view in depth that draws something already
is drawn converted with the active velocity model, nothing asked: its row
in the tree says so (T→D, on the object and on its
geometry); a click on that tag keeps it in its own domain in this view, the
tag saying T again, and a click brings it back. A view in TIME shows time
alone: nothing in depth is ever converted to time, an object in depth
keeping its D tag, undrawn, until the view goes back to depth — ticked
there, one box offers to switch the view to depth, or to stay in time.

With no active velocity model nothing is converted: the object stays undrawn,
its tag saying T, and at its tick one box says why, offering to open the
Time-depth model view (to choose a model, or generate one) or to switch the
view to time. A model made active, or edited, redraws what it converts.

The title bar's switch asks nothing, whatever the view holds: the boxes are
a tick's.

But nothing the Seismic tree files — a lattice IJK grid: a velocity model of
the data or of the session, a seismic cube (`tree.lattice_rows`,
engine/tree_families) — is ever converted: a velocity model converted to
depth would be converted by itself, and seismic is not converted on the fly.
In a view in depth that draws something it is kept in its
own domain, its tag saying T — no button, a click converts nothing —
until the view switches, and at its tick one box offers to switch the view to
time, or to stay in depth: the Time-depth model view would change nothing to it.

A row that carries no domain of its own — a wellbore, its folders — is drawn
where what it holds is (`crs_reference.domain_held`): a view in time draws
nothing of a well in depth, its name at its head included.

State: `ui_vdomain__<vid>` ("depth" | "time"); `ui_vdomains`, the domains
the loaded data holds (the title bar offers the switch when there are two);
`converted_paths__<vid>`, the rows drawn converted; `undrawn_paths__<vid>`, the
rows of the other domain kept in their own; `fixed_paths__<vid>`, those of
them this view never converts (a row of the Seismic tree, anything in a
view in time).
"""
from fespp_on_trame.engine import crs_reference, node_facts

DEPTH, TIME = crs_reference.DOMAINS


def no_model_question(count):
    """The box of an object in time shown in a view in depth with no active
    velocity model: {title, body, ok, third, cancel} (app/features/tick_question)."""
    what = "this object in time" if count == 1 else f"these {count} objects in time"
    return {"title": "No active velocity model",
            "body": (f"A view in depth draws {what} converted with the active velocity model, and none is"
                     " active. Open the Time-depth model view to choose a lattice grid or generate a model,"
                     " or switch this view to time."),
            "ok": "Open the T→D model view", "third": "Switch the view to time", "cancel": "Cancel"}


def in_time_question(count):
    """The box of an object in depth ticked in a view in time: {title, body,
    ok, cancel} (app/features/tick_question)."""
    what = "this object in depth stays" if count == 1 else f"these {count} objects in depth stay"
    return {"title": "View in time",
            "body": (f"A view in time draws nothing in depth: {what} undrawn until the view is in depth."
                     " Switch this view to depth?"),
            "ok": "Switch the view to depth", "cancel": "Cancel"}


def in_depth_question(count):
    """The box of a row of the Seismic tree ticked in a view in depth: {title,
    body, ok, cancel} (app/features/tick_question)."""
    what = "this object stays" if count == 1 else f"these {count} objects stay"
    return {"title": "View in depth",
            "body": (f"Nothing of the Seismic tree is converted to depth: {what} undrawn until the view is in time."
                     " Switch this view to time?"),
            "ok": "Switch the view to time", "cancel": "Cancel"}


def register(core, *, _detect_crs, _publish_lazy_read, occupancy, _ask=None):
    """Wire the `view_domain` controller and the scenes' domain filter.
    `_ask(question, on_yes, on_no, on_third)`: the shared question box
    (app/features/tick_question)."""
    state = core.state
    controller = core.controller
    ctx = core.ctx
    tree = core.tree
    scheduler = core.scheduler
    lifecycle = core.lifecycle
    _chosen = {}     # vid -> the domain the view was switched to (its own choice)

    _converted = {}     # vid -> the selectors drawn converted with the law
    _own = {}           # vid -> the selectors the reader keeps in their own domain

    @lifecycle.on("view_closed")
    def _forget_view(vid):
        _chosen.pop(vid, None)
        _converted.pop(vid, None)
        _own.pop(vid, None)

    def domain_of_path(path):
        """"depth", "time" or None (no CRS, not in the tree)."""
        nid = tree.find_node_id(path) if path else None
        return crs_reference.domain_of(tree, nid) if nid is not None else None

    def _held_domain(path):
        """The domain of what the row `path` draws: its own, or that of what
        it holds (a wellbore, a folder); None with no CRS, not in the tree."""
        nid = tree.find_node_id(path) if path else None
        return crs_reference.domain_held(tree, nid) if nid is not None else None

    def _block_domain(sel):
        try:
            return _held_domain(sel)
        except Exception as exc:
            print(f"[fespp] view domain: block {sel!r} not read ({exc})", flush=True)
            return None

    def domain(vid):
        """The domain `vid` draws: the one it was switched to, else the
        view's state, depth by default."""
        if vid in _chosen:
            return _chosen[vid]
        d = getattr(state, f"ui_vdomain__{vid}", None)
        return d if d in (DEPTH, TIME) else DEPTH

    def _held():
        """The domains the loaded data holds, read on the server's tree —
        not on the XML sent to the browser, which an ETP read leaves behind
        (app/boot._publish_lazy_read sends it again only for what the tree
        draws). An object listed but not read yet may carry none."""
        out = set()
        for nid, _children in tree.iter_nodes():
            d = tree.find_attribute_value(nid, "vdomain")
            if d in (DEPTH, TIME):
                out.add(d)
                if len(out) == 2:
                    break
        return sorted(out)

    def _tree_lacks_domain(paths):
        """Whether an object of `paths` (its row, what is under it, what
        it hangs under) carries a domain on the server the tree on screen
        does not show: an ETP object read by its tick, its CRS with it."""
        import re
        xml = state.assembly_xml or ""
        asm = getattr(tree, "_data_assembly", None)
        if asm is None or not paths:
            return False
        try:
            for path in paths:
                nid = tree.find_node_id(path)
                if nid is None:
                    continue
                nodes = [nid] + list(asm.GetChildNodes(nid, True))
                up = asm.GetParent(nid)
                while up is not None and up > 0:
                    nodes.append(up)
                    up = asm.GetParent(up)
                for n in nodes:
                    if not (asm.GetAttributeOrDefault(n, "vdomain", "") or ""):
                        continue
                    if not re.search(r"<" + re.escape(asm.GetNodeName(n)) + r"\b[^>]*\bvdomain=", xml):
                        return True
        except Exception as exc:
            print("[fespp] view domain: the tree's domains not compared:", exc, flush=True)
        return False

    def _law_cube():
        """The key of the velocity model the convert stage reads
        (app/features/time_depth_law registers it), "" when the model
        cannot convert."""
        key = getattr(ctx, "time_depth_cube_key", None)
        return key() if key is not None else ""

    def _flats_of(sel):
        index = getattr(ctx, "assembly_index", None)
        return index.flat_indices(sel) if index is not None else ()

    def attach(vid, scene):
        """The scene of `vid` draws the view's domain (view_wiring calls this
        on every scene it makes, the Globe's included), the objects it draws
        converted (in a view in depth alone) and the law they are converted
        with."""
        scene.domain_of = _block_domain
        scene.vdomain = domain(vid)
        scene.converted = set(_converted.get(vid, ())) if scene.vdomain == DEPTH else set()
        scene.convert_cube = _law_cube()
        scene.flats_of = _flats_of

    def publish_undrawn(vid):
        """The ticked objects of the other domain `vid` does not draw (kept in
        their own): their rows in the tree carry no eye until the view switches
        to their domain or they are converted. Those this view never converts
        — a row of the Seismic tree, anything in a view in time — are said
        apart: their tag is no button."""
        vid = str(vid)
        mine = domain(vid)
        conv = _converted.get(vid, set())
        paths = set(getattr(state, "selected_paths", None) or ()) | set(
            getattr(state, f"visible_paths__{vid}", None) or ())
        kept = {p: _selector_of(p) for p in paths if _held_domain(p) not in (None, mine)}
        kept = {p: sel for p, sel in kept.items() if sel not in conv}
        never = set(kept.values()) if mine == TIME else _seismic(set(kept.values()))
        for name, rows in ((f"undrawn_paths__{vid}", kept),
                           (f"fixed_paths__{vid}", {p: sel for p, sel in kept.items() if sel in never})):
            out = sorted({row for p, sel in rows.items() for row in (p, *_rows_of(sel))})
            if out != list(getattr(state, name, None) or []):
                state[name] = out

    def _seismic(sels):
        """The selectors of `sels` the Seismic tree files, never converted:
        the lattice IJK grids and what they hold (`tree.lattice_rows`, the
        one rule of that family, engine/tree_families)."""
        rows = list(getattr(tree, "lattice_rows", None) or ())
        return {s for s in sels if rows and node_facts.is_under(s, rows)}

    def _of_the_other_domain(vid):
        """The blocks `vid` holds of the domain it does not draw: they are
        drawn converted, but for those the reader keeps in their own and the
        rows of the Seismic tree; none in a view in time, none with no active
        model."""
        mine = domain(vid)
        if mine == TIME or not _law_cube():
            return set()
        paths = set(getattr(state, "selected_paths", None) or ()) | set(
            getattr(state, f"visible_paths__{vid}", None) or ())
        sels = {_selector_of(p) for p in paths
                if domain_of_path(p) not in (None, mine)} - _own.get(vid, set())
        return sels - _seismic(sels)

    def _redraw(vid):
        """The scene of `vid` projected again on its domain; the grids drawn
        by their isolate (a slicer, a threshold) follow."""
        publish_undrawn(vid)
        _publish_converted(vid)
        scene = (getattr(ctx, "blockscope_scenes", None) or {}).get(vid)
        if scene is not None:
            attach(vid, scene)
            scene.reconcile()
        for (v, rep) in list((getattr(ctx, "grid_isolates", None) or {}).keys()):
            if v == vid:
                occupancy.settle(vid, rep)
        # its axes lettered after the CRS of its domain: T, its time unit
        relabel = getattr(ctx, "apply_axes_labels", None)
        if relabel is not None:
            relabel(vid)
        # the model's columns follow the domain (app/features/time_depth_pins),
        # and the wells' heads (app/features/eye_pass)
        for hook in ("time_depth_pins_refresh", "wellheads_follow"):
            follow = getattr(ctx, hook, None)
            if follow is not None:
                follow(vid)
        scheduler.mark_dirty(vid)

    def _law_changed():
        """The active model edited, chosen or gone: the views redraw what it
        converts — what waited for a model is converted, what was converted
        with the one gone goes back to its own domain."""
        mv = core.mv()
        active = bool(_law_cube())
        for vid in (mv.view_ids() if mv is not None else list(_converted)):
            sels = _converted.setdefault(vid, set())
            fresh = _of_the_other_domain(vid) - sels
            if not active and sels:
                sels.clear()
                _redraw(vid)
            elif active and (sels or fresh):
                sels.update(fresh)
                _redraw(vid)
        scheduler.flush()

    def _waiting(vid):
        """How many objects in time `vid`, in depth, holds undrawn for want
        of an active velocity model."""
        if domain(vid) != DEPTH or _law_cube():
            return 0
        paths = set(getattr(state, "selected_paths", None) or ()) | set(
            getattr(state, f"visible_paths__{vid}", None) or ())
        sels = {_selector_of(p) for p in paths if domain_of_path(p) == TIME} - _own.get(vid, set())
        return len(sels - _seismic(sels))

    def _say_no_model(vid, count=None):
        """The box of a view in depth asked for objects in time (`count`,
        those it holds undrawn when None) with no active model: the model's
        view, the view in time, or nothing."""
        count = _waiting(vid) if count is None else count
        if not count or _ask is None:
            return
        print(f"[fespp] journal domain ({vid}): {count} object(s) in time and no active velocity model, asked",
              flush=True)

        def _open():
            door = getattr(controller, "open_time_depth", None)
            if door is not None:
                door()

        _ask(no_model_question(count), _open, None, lambda: set_domain(vid, TIME))

    def _say_in_time(vid, count):
        """The box of a view in time asked for `count` objects in depth: the
        view in depth, or nothing — they stay ticked, undrawn."""
        if count and _ask is not None:
            print(f"[fespp] journal domain ({vid}): {count} object(s) in depth ticked in a view in time, asked",
                  flush=True)
            _ask(in_time_question(count), lambda: set_domain(vid, DEPTH), None)

    def _say_in_depth(vid, count):
        """The box of a view in depth asked for `count` rows of the Seismic
        tree: the view in time, or nothing — they stay ticked, undrawn."""
        if count and _ask is not None:
            print(f"[fespp] journal domain ({vid}): {count} object(s) of the Seismic tree ticked in a view in depth,"
                  " asked", flush=True)
            _ask(in_depth_question(count), lambda: set_domain(vid, TIME), None)

    ctx.time_depth_law_listeners = list(getattr(ctx, "time_depth_law_listeners", None) or []) + [_law_changed]

    def set_domain(vid, dom):
        """`vid` draws the objects of `dom`, its camera kept: ONE camera for
        both domains, never recentred by a switch (the PO, 29/10: the view
        is framed once, on the first object it draws)."""
        vid = str(vid)
        if dom not in (DEPTH, TIME):
            return
        old = domain(vid)
        if dom != old:
            print(f"[fespp] journal domain ({vid}): the view goes from {old} to {dom}", flush=True)
        _chosen[vid] = dom
        scene = (getattr(ctx, "blockscope_scenes", None) or {}).get(vid)
        if dom == old and (scene is None or scene.vdomain == dom):
            state[f"ui_vdomain__{vid}"] = dom
            return
        state[f"ui_vdomain__{vid}"] = dom
        _converted.setdefault(vid, set()).update(_of_the_other_domain(vid))
        _redraw(vid)
        from fespp_on_trame.app.views import per_view_state
        if vid not in per_view_state.FRAMED and scene is not None and scene.shown_selectors():
            # the first objects this view draws: framed on them, as a load
            # frames a view's first data (app/features/eye_pass)
            controller.nav_reset(vid)
            per_view_state.FRAMED.add(vid)
        scheduler.flush()

    def _selector_of(path):
        """The block the composite draws for `path`: its representation."""
        nid = tree.find_node_id(path) if path else None
        rid = tree.find_representation_node(nid) if nid is not None else None
        return tree.find_path(rid) if rid is not None else path

    def _rows_of(sel):
        """The tree rows that say a block is drawn converted: its own, and
        the grid's row when the block is a grid's geometry (the PO, 02/11:
        T→D on the geometry and on the representation)."""
        out = [sel]
        rid = tree.find_node_id(sel)
        cid = tree.find_parent_node_id_with_type(rid, "GridContainer") if rid is not None else None
        if cid is not None and cid != rid:
            path = tree.find_path(cid)
            if path:
                out.append(path)
        return out

    def _publish_converted(vid):
        """The rows drawn converted NOW: an object of the view's own domain
        wears its plain tag, whatever it was converted for before."""
        mine = domain(vid)
        rows = sorted({row for sel in (_converted.get(vid, ()) if mine == DEPTH else ())
                       if _block_domain(sel) not in (None, mine) for row in _rows_of(sel)})
        if rows != list(getattr(state, f"converted_paths__{vid}", None) or []):
            state[f"converted_paths__{vid}"] = rows

    def convert(vid, paths):
        """`paths` (objects of the other domain) drawn in `vid` converted
        with the time-depth law — the tree says so (`converted_paths__`)."""
        vid = str(vid)
        sels = {_selector_of(p) for p in paths if p} - _own.get(vid, set())
        sels -= _seismic(sels)
        if not sels:
            return
        _converted.setdefault(vid, set()).update(sels)
        _publish_converted(vid)
        print(f"[fespp] journal domain ({vid}): {len(sels)} object(s) converted with the law", flush=True)
        _redraw(vid)
        scheduler.flush()

    @controller.set("view_domain_object")
    def view_domain_object(path, view_id):
        """A click on the tag of an object of the other domain: drawn converted
        in this view, or kept in its own."""
        vid = str(view_id or "")
        if domain(vid) == TIME:
            return      # nothing is converted to time
        sel = _selector_of(path)
        if _seismic({sel}):
            return      # nor a row of the Seismic tree to depth
        conv, own = _converted.setdefault(vid, set()), _own.setdefault(vid, set())
        if sel in conv:
            conv.discard(sel)
            own.add(sel)
        elif not _law_cube():
            _say_no_model(vid, 1)
            return
        else:
            own.discard(sel)
            conv.add(sel)
        _redraw(vid)
        scheduler.flush()

    def keep_own(vid, sels):
        """A document's: the blocks kept in their own domain in `vid`."""
        vid = str(vid)
        _own[vid] = set(sels or ())
        _converted.setdefault(vid, set()).difference_update(_own[vid])
        _redraw(vid)

    @state.change("selected_paths")
    def _ticks_moved(selected_paths=None, **_):
        """An object unticked is no longer drawn converted: its row goes back
        to its own domain. One ticked, in any view, is converted in the others
        too, for the day their eye opens on it."""
        loaded = {_selector_of(p) for p in (selected_paths or ()) if p}
        mv = core.mv()
        for vid in (mv.view_ids() if mv is not None else ()):
            sels = _converted.setdefault(vid, set())
            gone, fresh = sels - loaded, _of_the_other_domain(vid) - sels
            sels.difference_update(gone)
            _own.get(vid, set()).intersection_update(loaded)
            sels.update(fresh)
            if gone:
                _redraw(vid)
            elif fresh:
                _publish_converted(vid)
                publish_undrawn(vid)
                scene = (getattr(ctx, "blockscope_scenes", None) or {}).get(vid)
                if scene is not None:
                    attach(vid, scene)
        scheduler.flush()

    @controller.set("view_domain")
    def view_domain(view_id, dom):
        """The title bar's Depth | Time switch (Title3dView `set-domain`): the
        view switches, nothing asked. In depth with no active model its
        objects in time stay undrawn, their tag saying T."""
        try:
            set_domain(view_id, dom)
        except Exception as exc:
            print(f"[fespp] view domain error ({view_id}):", exc, flush=True)

    def _first_objects(vid, added, mine):
        """Whether `added`, none of them of the domain `mine` the view is in,
        are the first objects `vid` draws: empty, it shows nothing in its
        domain — nothing of it, nothing converted, nothing that has no
        domain — and the Time-depth model's view is not working in it (its
        columns, its preview are drawn there)."""
        if any(_held_domain(p) == mine for p in added):
            return False
        cards = getattr(ctx, "time_depth_card_views", None)
        if cards is not None and vid in cards():
            return False
        new = [_selector_of(p) for p in added] + list(added)
        scene = (getattr(ctx, "blockscope_scenes", None) or {}).get(vid)
        if scene is not None:
            # what the scene draws in the view's domain, the objects just ticked aside
            return all(node_facts.is_under(sel, new) for sel in scene.shown_selectors())
        converted = _converted.get(vid, set())
        for p in getattr(state, f"visible_paths__{vid}", None) or ():
            sel = _selector_of(p)
            if node_facts.is_under(sel, new):
                continue
            if _held_domain(p) in (None, mine) or sel in converted:
                return False
        return True

    def on_tick(vid, added):
        """Objects ticked in the data tree of `vid`. The first objects of an
        empty view give it their domain, nothing asked. In a view in depth
        that draws something, those in time are drawn converted with the
        law; without a law they stay undrawn and a box says why. In a view
        in time, those in depth stay undrawn and a box offers the view in
        depth. A row of the Seismic tree is never converted: in a view in
        depth it stays undrawn and a box offers the view in time — unless
        the box of the objects no model converts, which offers it too,
        stands."""
        vid = str(vid)
        if _tree_lacks_domain(added):
            # read by the tick, with its CRS: the tree on screen says its domain
            _publish_lazy_read()
        mine = domain(vid)
        publish_undrawn(vid)
        # a wellbore, a folder: of the domain of what it holds
        theirs = [p for p in added if _held_domain(p) not in (None, mine)]
        if not theirs:
            return
        if _first_objects(vid, added, mine):
            print(f"[fespp] journal domain ({vid}): empty, the view takes the domain of the first objects ticked",
                  flush=True)
            set_domain(vid, TIME if mine == DEPTH else DEPTH)
            return
        if mine == TIME:
            # counted by object: its properties are its representation's, and
            # a wellbore is one, whatever it holds
            sels = {_selector_of(p) for p in theirs}
            _say_in_time(vid, len({s for s in sels if not any(o != s and s.startswith(o + "/") for o in sels)}))
            return
        seismic = _seismic({_selector_of(p) for p in theirs})
        others = [p for p in theirs if _selector_of(p) not in seismic]
        if others and not _law_cube():
            _say_no_model(vid)
            return
        if others:
            convert(vid, others)
        _say_in_depth(vid, len(seismic))

    # the server's watchers follow the assembly's revisions, not its XML
    # (app/boot: the XML is the tree widget's payload) — `lazy_rev` too: an
    # ETP / OSDU object is listed first and read when ticked, and only then
    # does its node carry its CRS (the PO, 28/10: no domain over OSDU)
    @state.change("assembly_rev", "lazy_rev")
    def _domains_held(**_):
        """The domains the loaded data holds: one the view is not in, and
        its title bar offers the switch."""
        held = _held()
        if held != list(state.ui_vdomains or []):
            state.ui_vdomains = held

    state.ui_vdomains = []
    ctx.attach_view_domain = attach
    # the CRS a view names its axes and its readout after: its domain's
    ctx.view_crs = lambda vid: _detect_crs(domain(str(vid)), codeless=True)
    # the CRS of the objects of a domain, whatever a view shows them in
    ctx.domain_crs = lambda which: _detect_crs(which, codeless=True)
    ctx.view_domain_tick = on_tick
    ctx.view_domain_own = lambda vid: sorted(_own.get(str(vid), ()))
    ctx.view_domain_keep_own = keep_own
    ctx.view_domain_of = domain
    ctx.view_domain_set = set_domain
    ctx.domain_of_path = domain_of_path
