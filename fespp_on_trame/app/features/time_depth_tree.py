"""A velocity model the session generated as a grid the reader holds: written
as RESQML by fesapi (engine/resqml_epc: an IjkGridRepresentation with a
lattice geometry and its velocity property) and read by the reader, so the 3D
view draws it, and slices it, as any grid. A lattice grid, its row is in the
Seismic tree with the data's (engine/tree_families); the 3D view in use shows
it while the model's view is open — that view closed, its eyes close and its
row stays, read —, and its files are saved from its row's menu ("Save as
EPC", app/views/widgets/data_tree).

The reader can neither forget a file nor read again an object it holds
(the same uuids read twice crash the plugin): every change of a model
writes a NEW version, new uuids, read like an import — one second after
the last change. The versions before it are
taken out of the views (unticked) and out of the tree (`ui_hidden_tree_rows`),
so one row stands for each model of the session
(app/features/time_depth_models): what was ticked and shown of the last
version is ticked and shown of the new one. The 3D view in use, the model's view open,
follows the model made active; what the others show is theirs.

The model the conversions read is the one the session keeps read: its row is
ticked as soon as it is in the tree, and the model it took over from is
unticked then, not before — left for the inputs of a new one ("New velocity
model"), a model goes on converting, ticked, its eyes closed in the view in
use, until the new one is generated or another is chosen. A tree's untick of
its grid or of its velocity is refused and says why (`ctx.untick_vetoes`,
app/features/tick_question): unticked, it would convert all the same, the
tree saying it is not read.

A model is written as soon as it is generated, in a session that reads a
store as in one that reads files: the file reader takes the model's file
beside the store (engine/sources/merged_source).

State:  ``ui_hidden_tree_rows`` (the containers of the versions a later one
        replaced: no tree lists them), ``ui_model_tree_rows`` (those of
        every version of every model: what Data health and the Statistics
        view leave out),
        ``ui_cube_tree`` = {row (the container of the active model's version
        in the tree), grid, prop (its paths), download ([the .epc's URL, the
        .h5's]), cells [nx, ny, nk], parked [{row, download}] the others};
        ``ui_active_model_row``, the tree row of the velocity model the
        conversions read (the session's, or a grid of the data read as it
        is), "" while none converts: its title says so in the data trees.
Hooks:  ``ctx.time_depth_tree_rows()`` the containers of every version of
        every model; ``ctx.time_depth_tree_unoffered()`` those no tree lists
        (the versions gone);
        ``ctx.time_depth_tree_active_rows()`` those of the active model;
        ``ctx.time_depth_tree_owner(path)`` the model whose row holds `path`;
        ``ctx.time_depth_tree_grids()`` the uuids of their grids;
        ``ctx.time_depth_tree_current()`` the active model's version | None;
        ``ctx.time_depth_tree_uuids(mid)`` those of model `mid`'s version;
        ``ctx.time_depth_tree_left(mid)`` model `mid` is no longer the active one;
        ``ctx.time_depth_tree_forget()`` a document replaces the models.
"""
import os
import uuid as _uuid
from urllib.parse import quote

from fespp_on_trame.engine import node_facts, tree_families, view_routing

DELAY = 1.0             # s after the last change of a model already in the tree
VIEW = "timedepth"      # the model's view (app/views/views_config)


def register(core):
    controller, ctx, state, tree = core.controller, core.ctx, core.state, core.tree
    held = {"on": False, "by": {}, "gone": [], "replaced": None, "timer": None, "said": "",
            "card_in": set(), "show_in": set(), "grids": set(), "last_version": 0,
            # the model the view edits as last seen, and the one the session
            # keeps read as the converting one
            "edited": None, "read_for": None}

    def _of(mid):
        """The versions of model `mid`, numbered after those a document replaced:
        their files are read already, and the reader skips a name it has."""
        return held["by"].setdefault(mid, {"version": held["last_version"], "current": None, "old": []})

    def _mine():
        """The versions of the active model; with none active, none."""
        mid = ctx.time_depth_model_id()
        return _of(mid) if mid is not None else {"version": 0, "current": None, "old": []}

    def _say(text):
        """What went wrong putting the velocity model in the tree, in the model's
        note (said once per cause)."""
        if text == held["said"]:
            return
        held["said"] = text
        print(f"[fespp] velocity model in the tree: {text}", flush=True)
        ctx.time_depth_law_note(f"velocity model not put in the tree: {text}")

    def _loop():
        """The server's event loop, None outside it (a unit test): nothing
        waits there."""
        import asyncio
        try:
            return asyncio.get_running_loop()
        except RuntimeError:
            print("[fespp] velocity model in the tree: no event loop, nothing scheduled", flush=True)
            return None

    def _in_tree():
        """The version in the tree is the velocity model as it stands."""
        key = ctx.time_depth_cube_key() if getattr(ctx, "time_depth_cube_key", None) else ""
        cur = _mine()["current"]
        return bool(key) and cur is not None and cur.get("key") == key

    def _working(on):
        """The pill at the bottom of the page (fespp_on_trame.__main__) while a
        version is on its way: seconds with nothing else to see."""
        verb = "Updating" if _mine()["current"] is not None else "Creating"
        state.ui_work_note = f"{verb} the velocity model…" if on else ""
        state.flush()

    def due():
        """The model changed: a new version in DELAY s, the earlier wait
        dropped; its first version at once, there is nothing to gather. Outside
        the server's loop (a unit test) nothing waits."""
        if not held["on"] or (ctx.time_depth_cube() if getattr(ctx, "time_depth_cube", None) else None) is None:
            return
        loop = _loop()
        if loop is None:
            return
        if held["timer"] is not None:
            held["timer"].cancel()
        held["timer"] = loop.call_later(DELAY if _mine()["current"] is not None else 0.05, _fire)
        if not _in_tree():
            _working(True)

    def _fire():
        held["timer"] = None
        with state:
            try:
                write()
            finally:
                _working(False)

    def _path_of_uuid(uuid, container=False):
        nid = tree.find_node_id_by_uuid(uuid)
        if nid is None:
            return ""
        if container:
            cid = tree.find_parent_node_id_with_type(nid, "GridContainer")
            nid = cid if cid is not None else nid
        return tree.find_path(nid) or ""

    def _url(name):
        sid = getattr(state, "upload_session_id", None) or ""
        return (f"api/{sid}/export" if sid else "export") + "?file=" + quote(name)

    def write():
        """Each velocity model the tree does not hold as it stands written as a
        new version and read, the active one first."""
        waiting = [m for m in ctx.time_depth_models() if m[2] is not None
                   and (_of(m[0])["current"] or {}).get("key") != m[3]]
        if not waiting:
            return
        for model in waiting:
            if not _write_one(*model):
                break
        _versions_gone_follow()
        publish()
        _show_model()
        _active_stays_read()

    def _versions_gone_follow():
        """A version gone ticked again (a session saved with it, restored on
        top of the ones since): its row is hidden, the version in the tree
        takes what it holds."""
        selected = getattr(state, "selected_paths", None) or ()
        for versions in held["by"].values():
            for gone in versions["old"]:
                if versions["current"] is not None and any(
                        node_facts.is_under(p, [gone["container"]]) for p in selected):
                    _swap(gone, versions["current"])

    def _write_one(mid, title, cube, key):
        """Model `mid` as a new version; its last one swapped for it in the
        selection and the views. False when it could not be."""
        from fespp_on_trame.engine import resqml_epc
        from fespp_on_trame.engine.io.temp_dir import temp_dir
        mine = _of(mid)
        # the uuids a session saved, while nothing here holds them: what it
        # ticked and showed of the model then finds it where it was
        ids = ctx.time_depth_model_uuids(mid) or {}
        kept = held["replaced"]
        if (kept is not None and kept["ids"].get("grid") == ids.get("grid")
                and kept.get("sig") == cube.signature()):
            # restored over the session that saved it: that version is the model
            held["replaced"], mine["current"] = None, {**kept, "key": key}
            return True
        n = mine["version"] + 1
        if not ids.get("grid") or tree.find_node_id_by_uuid(ids["grid"]) is not None:
            ids = {k: str(_uuid.uuid4()) for k in ("crs", "grid", "prop", "hdf")}
        held["grids"].add(ids["grid"])
        stem = f"velocity-model-{mid}-v{n}"
        spec = {"dir": os.path.join(temp_dir, "exports"), "stem": stem, "title": title,
                "x0": cube.x0, "x1": cube.x1, "y0": cube.y0, "y1": cube.y1, "nx": cube.nx, "ny": cube.ny,
                "z": cube.t.tolist(), "v": cube.v.tolist(), "domain": "time", "uuids": ids}
        got = resqml_epc.write_cube(spec)
        if "error" in got:
            _say(got["error"])
            return False
        load = getattr(controller, "load_epc_file", None)
        report = (load(got["epc"]) or {}) if load is not None else {"failure": "no reader"}
        if report.get("failure"):
            _say(report["failure"])
            return False
        new = {"ids": ids, "container": _path_of_uuid(ids["grid"], container=True),
               "grid": _path_of_uuid(ids["grid"]), "prop": _path_of_uuid(ids["prop"]),
               "epc": os.path.basename(got["epc"]), "h5": os.path.basename(got["h5"]),
               "cells": list(got.get("cells") or []), "key": key, "sig": cube.signature()}
        if not new["container"]:
            _say("the reader read the package but the tree does not hold it")
            return False
        mine["version"], held["said"] = n, ""
        old, mine["current"] = mine["current"], new
        if old is None and mid == ctx.time_depth_model_id():
            old, held["replaced"] = held["replaced"], None
        if old is not None:
            mine["old"].append(old)
            _swap(old, new)
        print(f"[fespp] journal velocity model: version {n} in the tree ({new['container']})", flush=True)
        return True

    def left(mid):
        """Model `mid` gave way to the active one: the 3D view in use, showing
        it, shows this one instead, as soon as it is in the tree."""
        old = _of(mid)["current"]
        if old is not None:
            for vid in held["card_in"]:
                eyes = core.eyes.get(vid)
                kept = [p for p in eyes if not node_facts.is_under(p, [old["container"]])]
                if len(kept) != len(eyes):
                    core.eyes.set(vid, kept)
                    held["show_in"].add(vid)
        publish()
        _show_model()
        _active_stays_read()

    def _active_stays_read():
        """The model the conversions read is the one the session keeps read:
        once its version is in the tree its row is ticked, and the model it
        took over from is unticked — then, not before. A grid of the data
        read as it is is ticked by its own choice."""
        mid = ctx.time_depth_converting_id() if getattr(ctx, "time_depth_converting_id", None) else None
        if mid is None or mid == held["read_for"]:
            return
        data = ctx.time_depth_data_grid() if getattr(ctx, "time_depth_data_grid", None) else ""
        cur = None if data else _of(mid)["current"]
        if not data and (cur is None or cur.get("key") != ctx.time_depth_cube_key()):
            return
        selected = list(getattr(state, "selected_paths", None) or [])
        old = _of(held["read_for"])["current"] if held["read_for"] is not None else None
        kept = [p for p in selected if old is None or not node_facts.is_under(p, [old["container"]])]
        if cur is not None and not any(node_facts.is_under(p, [cur["container"]]) for p in kept):
            kept.append(cur["container"])
        held["read_for"] = mid
        if kept != selected:
            controller.select_paths(kept)

    def _stays_read(before, after):
        """A tree's untick taking `before` to `after` (paths) would unload
        the model the conversions read: ([its rows to tick again], why);
        ([], "") when its grid and its velocity stay ticked."""
        row = _active_row()
        if not row:
            return [], ""
        data = ctx.time_depth_data_grid() if getattr(ctx, "time_depth_data_grid", None) else ""
        if data:
            needed = [data, ctx.time_depth_data_velocity()]
        else:
            cur = _of(ctx.time_depth_converting_id())["current"]
            needed = [cur["grid"], cur["prop"]]
        now = set(after)
        if not any(p and p in before and p not in now for p in needed):
            return [], ""
        nid = tree.find_node_id(row)
        name = (tree.find_title(nid) if nid is not None else "") or "The velocity model"
        return ([p for p in before if p not in now and node_facts.is_under(p, [row])],
                f"{name} stays checked: it is the active T→D model, the conversions read it."
                " Generate or choose another velocity model first, or close its eye to hide it.")

    def _edited_moved():
        """The model the view edits changed — generated, chosen: the 3D view
        in use, the model's view open, shows it as soon as it is in the tree,
        whatever it showed of the one before."""
        edited = ctx.time_depth_model_id()
        if edited != held["edited"]:
            held["edited"] = edited
            if edited is not None:
                held["show_in"] |= held["card_in"]
        _show_model()
        _active_stays_read()

    def forget():
        """A document replaces the session's models: their rows go, and what
        was shown of the active one goes to the next version written."""
        held["edited"], held["read_for"] = None, None
        active = _mine()["current"]
        for versions in held["by"].values():
            held["gone"] += versions["old"]
            parked = versions["current"]
            if parked is not None and parked is not active:
                held["gone"].append(parked)
                _unticked(parked)
        held["replaced"] = active
        held["last_version"] = max([held["last_version"], *(b["version"] for b in held["by"].values())])
        held["by"] = {}

    def renamed():
        """{uuid a document saved: the one its model has now}. Restored over a
        session that has moved on since, a version still holds the saved uuids, and
        the same uuids read twice crash the plugin: the model is written under others."""
        out = {}
        for mid, *_rest in ctx.time_depth_models():
            saved = ctx.time_depth_model_uuids(mid) or {}
            now = (_of(mid)["current"] or {}).get("ids") or {}
            out.update({saved[k]: now[k] for k in ("grid", "prop")
                        if saved.get(k) and now.get(k) and saved[k] != now[k]})
        return out

    def _show_model():
        """The views asking for it (`show`) draw the model once it is in the
        tree: its grid ticked, the eyes of its geometry and velocity open, the
        Values card on it. It waits for the version of the model as it stands
        (a zone just given, a TDLaw edited), and for a zone: a model around
        nothing would take the view's framing."""
        cur = _mine()["current"]
        law = getattr(ctx, "time_depth_law", None)
        if cur is None or not held["show_in"] or law is None or law().extent_in_use() is None:
            return
        if cur.get("key") != ctx.time_depth_cube_key():
            return
        vids, held["show_in"] = held["show_in"], set()
        row = cur["container"]
        selected = list(getattr(state, "selected_paths", None) or [])
        ticked = any(node_facts.is_under(p, [row]) for p in selected)
        for vid in vids:
            core.activation.ticked(vid, [row])
            _seismic_card(vid)
            if ticked:
                eyes = core.eyes.get(vid)
                core.eyes.set(vid, eyes + [p for p in (cur["grid"], cur["prop"]) if p not in eyes])
        if not ticked:
            controller.select_paths(selected + [row])

    def _seismic_card(vid):
        """The Seismic tree card of `vid` open: where the lattice grids, the
        models among them, are listed."""
        cards = getattr(core, "cards", None)
        if cards is not None:
            cards.open(vid, tree_families.SEISMIC)

    def show(vid):
        """The model's view opened, `vid` the 3D view in use: the active model
        comes with it, and the Seismic tree when the data holds a lattice grid."""
        held["show_in"].add(str(vid))
        ctx.time_depth_ensure_zone()
        start()
        if getattr(state, "ui_cube_grid_rows", None):
            _seismic_card(str(vid))
        _show_model()

    def _eyes_closed():
        """The models leave the views: their eyes close, they stay read."""
        rows = list(_current_rows())
        mv = core.mv()
        for vid in (mv.view_ids() if mv is not None and rows else []):
            eyes = core.eyes.get(vid)
            kept = [p for p in eyes if not node_facts.is_under(p, rows)]
            if len(kept) != len(eyes):
                core.eyes.set(vid, kept)

    def _unticked(version):
        """`version` leaves the selection (unloaded), and with it the views."""
        selected = list(getattr(state, "selected_paths", None) or [])
        kept = [p for p in selected if not node_facts.is_under(p, [version["container"]])]
        if kept != selected:
            controller.select_paths(kept)

    def _swap(old, new):
        """What was ticked and shown of `old`, what a panel holds of it, is
        ticked, shown and held of `new`; `old` leaves the selection (unloaded)."""
        def moved(p):
            return p.replace(old["ids"]["grid"], new["ids"]["grid"]).replace(old["ids"]["prop"], new["ids"]["prop"])

        def of_old(p):
            return node_facts.is_under(p, [old["container"]])

        core.panel_trees.move(moved)
        sel = list(getattr(state, "selected_paths", None) or [])
        if any(of_old(p) for p in sel):
            controller.select_paths([p for p in sel if not of_old(p)] + [moved(p) for p in sel if of_old(p)])
        mv = core.mv()
        for vid in (mv.view_ids() if mv is not None else []):
            var = f"visible_paths__{vid}"
            vis = list(getattr(state, var, None) or [])
            if any(of_old(p) for p in vis):
                state[var] = [p for p in vis if not of_old(p)] + [moved(p) for p in vis if of_old(p)]
            # the node the cards follow follows the grid
            act = getattr(state, f"active_path__{vid}", None) or ""
            if of_old(act):
                state[f"active_path__{vid}"] = moved(act)
            folder = list(getattr(state, f"values_folder__{vid}", None) or [])
            if any(of_old(p) for p in folder):
                state[f"values_folder__{vid}"] = [moved(p) if of_old(p) else p for p in folder]
            by = dict(getattr(state, f"active_by_tab__{vid}", None) or {})
            if any(of_old(p) for p in by.values()):
                state[f"active_by_tab__{vid}"] = {t: (moved(p) if of_old(p) else p) for t, p in by.items()}
        _reload_maps()

    def _reload_maps():
        """The Values card's maps read again once the new grid is drawn
        (app/features/values_map): an edited cell shows its new value."""
        maps = {v: m for v, m in (getattr(state, "ui_node_map_by_view", None) or {}).items()
                if isinstance(m, dict) and "k" in m}
        reader = getattr(controller, "node_values_map", None)
        if not maps or reader is None:
            return
        loop = _loop()
        if loop is None:
            return

        def again():
            with state:
                for vid, m in maps.items():
                    reader({"k": m["k"]}, vid)

        loop.call_later(DELAY, again)

    def _gone_rows():
        return [o["container"] for o in held["gone"]] + [o["container"] for b in held["by"].values() for o in b["old"]]

    def _current_rows():
        """{the row of a model in the tree: its id}."""
        return {b["current"]["container"]: mid for mid, b in held["by"].items() if b["current"] is not None}

    def owner(path):
        for row, mid in _current_rows().items():
            if node_facts.is_under(path, [row]):
                return mid
        return None

    def _files_of(version):
        return {"row": version["container"], "download": [_url(version["epc"]), _url(version["h5"])]}

    def _view_open():
        return VIEW in (getattr(state, "ui_open_view_kinds", None) or ())

    def _active_row():
        """The tree row of the velocity model the conversions read."""
        if not (ctx.time_depth_cube_key() if getattr(ctx, "time_depth_cube_key", None) else ""):
            return ""
        data = ctx.time_depth_data_grid() if getattr(ctx, "time_depth_data_grid", None) else ""
        if data:
            nid = tree.find_node_id(data)
            cid = tree.find_parent_node_id_with_type(nid, "GridContainer") if nid is not None else None
            return (tree.find_path(cid) if cid is not None else "") or data
        mid = ctx.time_depth_converting_id() if getattr(ctx, "time_depth_converting_id", None) else None
        cur = _of(mid)["current"] if mid is not None else None
        return cur["container"] if cur is not None else ""

    def _publish_active():
        row = _active_row()
        if row != (getattr(state, "ui_active_model_row", None) or ""):
            state.ui_active_model_row = row

    def publish():
        cur = _mine()["current"]
        _publish_active()
        state.ui_hidden_tree_rows = _gone_rows()
        state.ui_model_tree_rows = _gone_rows() + list(_current_rows())
        parked = [_files_of(b["current"]) for b in held["by"].values()
                  if b["current"] is not None and b["current"] is not cur]
        state.ui_cube_tree = {"parked": parked, **(
            {**_files_of(cur), "grid": cur["grid"], "prop": cur["prop"], "cells": cur["cells"]}
            if cur is not None else {})}
        lattice = getattr(ctx, "time_depth_publish_grid_rows", None)
        if lattice is not None:
            lattice()

    def start():
        """The model goes into the tree from now on."""
        if held["on"]:
            return
        held["on"] = True
        due()

    def _forgotten(**_):
        """A file read anew, everything cleared: a version the tree no longer
        holds is forgotten, and the model put back."""
        lost = [b for b in held["by"].values()
                if b["current"] is not None and tree.find_node_id(b["current"]["container"]) is None]
        if not lost:
            return
        for b in lost:
            b["current"], b["old"] = None, []
        held["gone"], held["replaced"] = [], None
        publish()
        due()

    def _view_opened(**_):
        """The model's view open: the 3D view in use follows the model made
        active. Closed: the models' eyes close in the views; their rows stay
        in the tree, read."""
        is_open = _view_open()
        in_use = view_routing.model_view(state)
        opened = {in_use} if is_open and in_use else set()
        held["show_in"] &= opened
        if is_open:
            start()
        was, held["card_in"] = held["card_in"], opened
        if was != opened:
            # a model not generated yet is shown in the view in use alone
            pins = getattr(ctx, "time_depth_pins_refresh", None)
            if pins is not None:
                pins()
        if is_open != held.get("was_open", False):
            held["was_open"] = is_open
            if not is_open:
                _eyes_closed()
            if held["on"]:
                publish()

    on_change = getattr(state, "change", None)
    if callable(on_change):
        on_change("ui_open_view_kinds", "fespp_last_render_panel_id")(_view_opened)
        on_change("assembly_rev")(_forgotten)

    ctx.time_depth_law_listeners = list(getattr(ctx, "time_depth_law_listeners", None) or []) + [
        due, _publish_active, _edited_moved]
    ctx.untick_vetoes = list(getattr(ctx, "untick_vetoes", None) or []) + [_stays_read]
    ctx.time_depth_tree_rows = lambda: _gone_rows() + list(_current_rows())
    ctx.time_depth_tree_unoffered = _gone_rows
    ctx.time_depth_tree_active_rows = lambda: [o["container"] for o in _mine()["old"]] + (
        [_mine()["current"]["container"]] if _mine()["current"] is not None else [])
    ctx.time_depth_tree_uuids = lambda mid: (_of(mid)["current"] or {}).get("ids")
    ctx.time_depth_tree_owner = owner
    ctx.time_depth_tree_left = left
    ctx.time_depth_tree_forget = forget
    ctx.time_depth_tree_renamed = renamed
    ctx.time_depth_tree_current = lambda: _mine()["current"]
    ctx.time_depth_tree_grids = lambda: held["grids"]
    ctx.time_depth_tree_start = start
    # the 3D view in use while the model's view is open: where a model not
    # generated yet is shown, no row of the tree for it (app/features/time_depth_pins)
    ctx.time_depth_card_views = lambda: set(held["card_in"])
    ctx.time_depth_show = show
    ctx.time_depth_tree_write = write
    state.ui_hidden_tree_rows = []
    state.ui_model_tree_rows = []
    state.ui_cube_tree = {}
    state.ui_active_model_row = ""
    start()
    return start
