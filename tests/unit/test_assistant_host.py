"""app/assistant_host: the Assistant's adapter to the application.

Covers the objects the command engine may name (one walk of the assembly),
and each command carried out on the application's controllers with the
right arguments in the right order (some controllers take the view id
first), then undone.

Runs over a fake assembly and a fake application (state, controllers,
views), with no ParaView (the conftest stubs). The fake runs the load chain
on a flush, as trame's watchers do, so a command that forgets to flush
reads nothing."""
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "widgets" / "session"))

from tests.unit.fake_assembly import FakeDataAssembly  # noqa: E402
from fespp_on_trame.engine.tree import Tree  # noqa: E402
from fespp_on_trame.ia.nlu import catalogue  # noqa: E402
from fespp_on_trame.engine.utils.naming import make_valid_vtk_name  # noqa: E402
from fespp_on_trame.engine.utils import numfmt  # noqa: E402
from fespp_on_trame.app.assistant_host import FesppAssistantHost, LABELS  # noqa: E402

VID = "view_1"
PORO_VTK = make_valid_vtk_name("Total Porosity")      # the VTK array name: "TotalPorosity"
U = {k: f"{n:08x}-0000-4000-8000-{n:012x}" for n, k in enumerate(
    ("grid", "poro", "ntg", "kh", "kv", "wb", "traj", "frame", "gr", "surf", "part", "phi_log", "fluids"),
    start=1)}


def _tree():
    """A grid, a well, a surface and a partial stub.

    Geogrid (an IjkGrid in the grid-folder layout) with four continuous
    properties, two of them permeabilities, and a categorical one; the well
    55/33-1 with a trajectory and two logs; a Grid2d surface; a partial
    stub."""
    asm = FakeDataAssembly()
    add = asm.add_node_with_attrs
    gc = add(f"_gridfolder_{U['grid']}", 0, title="Geogrid", type="GridContainer")
    pf = add(f"_propsfolder_{U['grid']}", gc, title="Properties", type="PropertiesFolder")
    n = {"grid": add(f"_{U['grid']}", pf, title="SolidColor", type="IjkGrid")}
    for key, title, kind in (("poro", "Total Porosity", "porosity"),
                             ("ntg", "Net-to-Gross Ratio (PEM)", "net to gross ratio"),
                             ("kh", "Horizontal Permeability", "rock permeability"),
                             ("kv", "Vertical Permeability", "rock permeability")):
        n[key] = add(f"_{U[key]}", pf, title=title, type="ContinuousProperty", propertyKind=kind,
                     uom="m3/m3" if key == "poro" else "", minvalue="0", maxvalue="0.4")
    n["wb"] = add(f"_{U['wb']}", 0, title="55/33-1", type="Wellbore")
    n["traj"] = add(f"_{U['traj']}", n["wb"], title="55/33-1", type="Trajectory")
    lf = add(f"_logsfolder_{U['wb']}", n["wb"], title="Logs", type="WellboreLogsFolder")
    n["frame"] = add(f"_{U['frame']}", lf, title="LOGS", type="Frame")
    n["gr"] = add(f"_{U['gr']}", n["frame"], title="GR", type="ContinuousProperty",
                  propertyKind="gamma ray api unit")
    # The well logs a porosity too, so "porosity" names a log as well as a
    # grid property.
    n["phi_log"] = add(f"_{U['phi_log']}", n["frame"], title="Total Porosity (Original Log)",
                       type="ContinuousProperty", propertyKind="porosity")
    # A fluids column: a categorical property whose string lookup names its
    # codes.
    n["fluids"] = add(f"_{U['fluids']}", pf, title="Fluids", type="CategoricalProperty",
                      propertyKind="index")
    n["surf"] = add(f"_{U['surf']}", 0, title="Top Volantis", type="Grid2d")
    n["part"] = add(f"_{U['part']}", 0, title="!!!PARTIAL!!!Somewhere", type="Partial")
    paths = {k: asm.GetNodePath(v) for k, v in n.items()}
    return Tree(asm), paths


class FakeState(dict):
    """trame's state as the adapter uses it.

    Attribute and item access, watchers, and a flush that runs what the
    application runs on one."""

    def __init__(self):
        super().__init__()
        object.__setattr__(self, "watchers", {})
        object.__setattr__(self, "hooks", [])
        object.__setattr__(self, "flushes", 0)

    def __getattr__(self, k):
        if k.startswith("__"):
            raise AttributeError(k)
        return self.get(k)

    def change(self, *names):
        def deco(fn):
            for name in names:
                self.watchers.setdefault(name, []).append(fn)
            return fn
        return deco

    def dirty(self, *names):
        pass

    def flush(self):
        object.__setattr__(self, "flushes", self.flushes + 1)
        for hook in list(self.hooks):
            hook()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.flush()
        return False


class FakeIso:
    """A grid's isolate: its threshold chain and its slicer lists.

    The slicer lists start as IjkGrid starts them: whole extent, one mid
    plane per axis, full mode."""

    def __init__(self, ext=((0, 10), (0, 20), (0, 30))):
        self.chain = []
        self._range_mode = "full"
        for a, (lo, hi) in zip("ijk", ext):
            setattr(self, f"_range_{a}", [lo, hi])
            setattr(self, f"_slices_{a}_list", [(lo + hi) // 2])
            setattr(self, f"_slices_{a}_visible_list", [True])
        self._volumes = [[list(r) for r in ext]]
        self._volumes_visible = [True]

    def get_chain(self):
        return [dict(e) for e in self.chain]


class FakeMV:
    def __init__(self, render=(VID,)):
        self._kinds = {v: "render" for v in render}
        self._titles = {v: "3D view" for v in render}
        self.pv = {v: SimpleNamespace(CameraPosition=[0, 0, 10], CameraFocalPoint=[0, 0, 0],
                                      CameraViewUp=[0, 1, 0], CameraViewAngle=30.0,
                                      CameraParallelScale=1.0, CameraParallelProjection=0,
                                      CenterOfRotation=[1, 2, 3])
                   for v in render}
        self.n = 10
        self.removed = []

    def view_ids(self):
        return [p for p, k in self._kinds.items() if k == "render"]

    def panel_ids_of_kind(self, kind):
        return [p for p, k in self._kinds.items() if k == kind]

    def kind_of(self, pid):
        return self._kinds.get(pid, "render")

    def get_pv_view(self, vid):
        return self.pv.get(vid)

    def add(self, kind, singleton=False):
        if singleton and self.panel_ids_of_kind(kind):
            return self.panel_ids_of_kind(kind)[0]
        self.n += 1
        pid = f"view_{self.n}"
        self._kinds[pid] = kind
        self._titles[pid] = kind
        return pid

    def remove_panel(self, pid):
        self.removed.append(pid)


class FakeApp:
    """The application as the adapter drives it.

    The controllers are recorded; the effects the adapter reads back (a
    load, the threshold chain, the Colormap card) are simulated."""

    def __init__(self, tree=None, paths=None, render=(VID,)):
        if tree is None:
            tree, paths = _tree()
        self.tree, self.p = tree, paths
        s = self.state = FakeState()
        s.update({"fespp_render_panels": [{"id": v} for v in render],
                  "fespp_active_panel_id": render[0] if render else "",
                  "fespp_last_render_panel_id": render[0] if render else "",
                  "selected_paths": [], "ui_loaded_rep_paths": [], "ui_loaded_array_paths": [],
                  f"visible_paths__{VID}": [], f"active_path__{VID}": "",
                  f"active_by_tab__{VID}": {}, f"ui_scale_z__{VID}": 1.0})
        self.calls = []
        self.mv = FakeMV(render)
        self.isos = {}
        self.refuse = set()
        self.hidden = []
        self.highlight = {"count": 3, "total": 10, "valid": 8, "array": PORO_VTK,
                          "assoc": "CELLS"}
        self.well_cells = None          # what well_cells_where returns; None: 3 crossed, 1 in the zone
        self.well_cells_payload = None
        self.nan_ok = True
        self.pin_values = {}            # {"ts" | "real": the values a row can be pinned at}
        self.add_fails = False          # the isolate cannot resolve the array
        self.ctx = SimpleNamespace(tree=tree, multi_view=self.mv, grid_isolates=self.isos,
                                   source_registry="REG",
                                   active_data_source=SimpleNamespace(get_source=lambda: "SRC"),
                                   render_scheduler=SimpleNamespace(mark_dirty=self._noop,
                                                                    flush=self._noop))
        fns = {name[1:]: getattr(self, name) for name in dir(self)
               if name.startswith("_") and not name.startswith("__")
               and name[1:] in self.CONTROLLERS}
        self.ctrl = SimpleNamespace(**{k: self._rec(k, f) for k, f in fns.items()})
        s.hooks.append(self._on_flush)
        self.server = SimpleNamespace(state=s, context=self.ctx, controller=self.ctrl)

    CONTROLLERS = (
        "select_paths", "session_select", "on_eye_changed", "threshold_add", "threshold_range",
        "threshold_remove", "threshold_visible", "highlight_where", "node_highlight", "well_cells_where",
        "session_view_tables", "session_restore_view_tables", "cmap_preset", "cmap_range",
        "cmap_rescale", "cmap_hide_nan", "set_flat_colors", "nav_reset", "nav_zoom_active",
        "set_zscale", "open_render_view", "add_to_stats",
        "open_welllog", "welllog_tree_wells", "open_reconcile", "reconcile_tree_paths",
        "open_compare", "compare_set", "compare_tree_paths",
        "xml_open_active", "xml_open", "open_stratigraphy",
        "open_calculator", "open_health", "health_focus", "slicer_range", "slicer_positions",
        "slicer_mode", "slicer_visibility", "slicer_volumes", "slicer_volumes_visible",
        "session_save", "camera_link_sync", "session_row_eye")

    def _noop(self, *a):
        pass

    def _rec(self, name, fn):
        def call(*args):
            self.calls.append((name, args))
            return fn(*args)
        return call

    def called(self, name):
        return [a for n, a in self.calls if n == name]

    # ---- what a flush runs in the application
    def _rep_of(self, path):
        nid = self.tree.find_node_id(path) if path else None
        rid = self.tree.find_representation_node(nid) if nid is not None else None
        return self.tree.find_path(rid) if rid is not None else None

    def _is_prop(self, path):
        nid = self.tree.find_node_id(path) if path else None
        return nid is not None and "Property" in (self.tree.find_type(nid) or "")

    def _on_flush(self):
        s = self.state
        reps, arrays = list(s["ui_loaded_rep_paths"]), list(s["ui_loaded_array_paths"])
        eyes = list(s[f"visible_paths__{VID}"])
        for p in list(s["selected_paths"]) + self.hidden:
            if p in reps or p in arrays or p in self.refuse:
                if p in self.refuse:
                    s["empty_color_snackbar_text"] = "That read was refused."
                continue
            if self._is_prop(p):
                arrays.append(p)
                rep = self._rep_of(p)
                if rep and rep not in reps:
                    reps.append(rep)
                    if p not in self.hidden:
                        eyes.append(rep)
                if p not in self.hidden:
                    eyes.append(p)              # born visible
            else:
                reps.append(p)
                if p not in self.hidden:
                    eyes.append(p)
        self.hidden = []
        s["ui_loaded_rep_paths"], s["ui_loaded_array_paths"] = reps, arrays
        s[f"visible_paths__{VID}"] = eyes
        # The Colormap card follows the active property, the Slicers card
        # the Reservoir tab's grid.
        act = s[f"active_path__{VID}"] or ""
        if self._is_prop(act):
            title = self.tree.find_title(self.tree.find_node_id(act))
            card = dict(s.get(f"ui_colormap__{VID}") or {})
            card.update(array=make_valid_vtk_name(title), label=title, min=0.0, max=0.4)
            s[f"ui_colormap__{VID}"] = card
        s[f"ui_slicers__{VID}"] = {"has_grid": True, "range_i": [0, 10], "range_j": [0, 20],
                                   "range_k": [0, 30]}

    # ---- controllers
    def _select_paths(self, paths):
        self.state["selected_paths"] = list(paths)

    def _session_select(self, paths):
        self.hidden += list(paths)

    def _on_eye_changed(self, vid, paths):
        pass

    def _session_row_eye(self, payload, vid):
        rows = [dict(r) for r in (self.state[f"ui_session_rows__{vid}"] or [])]
        for r in rows:
            if r.get("path") == payload.get("path"):
                r["visible"] = not r.get("visible")
        self.state[f"ui_session_rows__{vid}"] = rows

    def _iso(self, vid):
        by_tab = self.state[f"active_by_tab__{vid}"] or {}
        rep = self._rep_of(by_tab.get("reservoir"))
        return self.isos.setdefault((vid, rep), FakeIso())

    def _push(self, vid, iso):
        self.state[f"ui_thresholds__{vid}"] = iso.get_chain()

    def _threshold_add(self, payload, vid):
        iso = self._iso(vid)
        name = f"threshold_{len(self.calls)}"
        parent = payload[1] if any(e["name"] == payload[1] for e in iso.chain) else None
        if not self.add_fails:
            iso.chain.append({"name": name, "parent_name": parent, "array": payload[0], "visible": True,
                              "low": 0.0, "high": 0.4, "data_range": [0.0, 0.4]})
        # As boot does: the target's chain is pushed, whatever the add gave.
        self._push(vid, iso)

    def _threshold_range(self, payload, vid):
        iso = self._iso(vid)
        for e in iso.chain:
            if e["name"] == payload[0]:
                e["low"], e["high"] = payload[1]
        self._push(vid, iso)

    def _threshold_remove(self, name, vid):
        iso = self._iso(vid)
        gone = next((e for e in iso.chain if e["name"] == name), None)
        iso.chain = [e for e in iso.chain if e["name"] != name]
        # As IjkGrid.delete_threshold does: the children adopt its parent.
        for e in iso.chain:
            if gone is not None and e["parent_name"] == name:
                e["parent_name"] = gone["parent_name"]
        self._push(vid, iso)

    def _threshold_visible(self, payload, vid):
        iso = self._iso(vid)
        for e in iso.chain:
            if e["name"] == payload[0]:
                e["visible"] = bool(payload[1])
        self._push(vid, iso)

    def _highlight_where(self, payload, vid):
        self.highlight_active = self.state[f"active_path__{vid}"]
        return dict(self.highlight)

    def _node_highlight(self, indices, vid):
        pass

    def _well_cells_where(self, payload, vid):
        self.well_cells_payload = payload
        if self.well_cells is not None:
            return dict(self.well_cells)
        zone = payload.get("array") is not None
        per = {t: {"crossed": 3, "in": 1 if zone else 3} for t in payload["trajectories"]}
        return {"per": per, "lit": sum(d["in"] for d in per.values()), "total": 10}

    def _session_view_tables(self, vid):
        return [{"array": PORO_VTK, "lut": {"RGBPoints": [0, 0, 0, 1]}}]

    def _session_restore_view_tables(self, vid, tables):
        pass

    def _cmap_preset(self, preset, vid):
        # What boot's cmap_preset writes for the Colormap card's preset field.
        self.state["ui_active_colormap_by_view"] = dict(self.state.get("ui_active_colormap_by_view") or {},
                                                        **{vid: preset})

    def _cmap_range(self, rng, vid):
        pass

    def _cmap_rescale(self, mode, vid):
        pass

    def _cmap_hide_nan(self, on, vid):
        card = dict(self.state[f"ui_colormap__{vid}"] or {})
        if self.nan_ok:
            card["hide_nan"] = bool(on)
        else:
            card["hide_nan_why"] = "No visible grid is painted by this property"
        self.state[f"ui_colormap__{vid}"] = card

    def _set_flat_colors(self, vid, on):
        self.state[f"ui_flat_colors__{vid}"] = bool(on)

    def _nav_reset(self, vid):
        self.mv.pv[vid].CameraPosition = [5, 5, 5]
        self.mv.pv[vid].CenterOfRotation = [0, 0, 0]      # reset_camera_centered moves the pivot

    def _nav_zoom_active(self, vid):
        self.mv.pv[vid].CameraPosition = [7, 7, 7]

    def _camera_link_sync(self, vid):
        pass

    def _set_zscale(self, value, vid=None):
        # The real one writes it in its debounced commit.
        self.state[f"ui_scale_z__{vid}"] = float(value)

    def _open_render_view(self, source_id=None):
        self.mv.add("render")

    def _add_to_stats(self, path):
        """The property in the Statistics view, once at the coordinates it
        names, and the view open."""
        items = self.state.get("ui_compare_items") or []
        if not any(it["path"] == path and not it["pinned"] for it in items):
            uid = f"i{len(items) + 1}"
            items = items + [{"path": path, "real": None, "ts": None, "uid": uid, "pinned": False}]
        self.state["ui_compare_items"] = items
        self.mv.add("compare", singleton=True)

    def _compare_set(self, key, value):
        """`pin_all` as the view runs it: one pinned row per value this
        property has (`self.pin_values`, by axis)."""
        assert key == "pin_all"
        uid, axis = value
        items = self.state["ui_compare_items"]
        src = next(it for it in items if it["uid"] == uid)
        fresh = [{"path": src["path"], "uid": f"p{axis}{v}", "pinned": True,
                  "real": v if axis == "real" else src["real"],
                  "ts": v if axis == "ts" else src["ts"]}
                 for v in self.pin_values.get(axis, ())]
        self.state["ui_compare_items"] = items + fresh

    def _open_welllog(self):
        self.mv.add("welllog", singleton=True)

    def _welllog_tree_wells(self, vid, paths):
        pass

    def _open_reconcile(self):
        self.mv.add("reconcile", singleton=True)

    def _reconcile_tree_paths(self, vid, paths):
        pass

    def _open_compare(self):
        self.mv.add("compare", singleton=True)

    def _compare_tree_paths(self, vid, paths):
        pass

    def _xml_open_active(self, vid):
        self.xml_active = self.state[f"active_path__{vid}"]
        self.mv.add("xml")

    def _xml_open(self, uuid, title, note=""):
        self.mv.add("xml")

    def _open_stratigraphy(self):
        self.mv.add("stratigraphy", singleton=True)

    def _open_calculator(self, path=None):
        self.mv.add("calculator", singleton=True)

    def _open_health(self):
        self.mv.add("health", singleton=True)

    def _health_focus(self, path):
        self.mv.add("health", singleton=True)

    # The slicers as boot runs them on the isolate of the Reservoir tab's grid.
    def _slicer_range(self, payload, vid):
        iso = self._iso(vid)
        axis, rng = payload
        setattr(iso, f"_range_{axis}", [int(rng[0]), int(rng[1])])
        iso._volumes = [[list(iso._range_i), list(iso._range_j), list(iso._range_k)]]
        iso._range_mode = "range"

    def _slicer_positions(self, payload, vid):
        iso = self._iso(vid)
        axis, positions = payload
        setattr(iso, f"_slices_{axis}_list", [int(p) for p in positions or []])
        iso._range_mode = "slice"

    def _slicer_mode(self, mode, vid):
        self._iso(vid)._range_mode = mode

    def _slicer_visibility(self, payload, vid):
        axis, vis = payload
        setattr(self._iso(vid), f"_slices_{axis}_visible_list", list(vis or []))

    def _slicer_volumes(self, payload, vid):
        iso = self._iso(vid)
        iso._volumes = [list(map(list, v)) for v in payload or []]
        iso._volumes_visible = (list(iso._volumes_visible) + [True] * len(iso._volumes))[:len(iso._volumes)]

    def _slicer_volumes_visible(self, payload, vid):
        self._iso(vid)._volumes_visible = list(payload or [])

    def _session_save(self, note):
        pass


@pytest.fixture
def app():
    return FakeApp()


@pytest.fixture
def host(app):
    return FesppAssistantHost(app.server)


def _load(app, *keys):
    """Mark objects as read, the way a tick would, with their eyes closed."""
    s = app.state
    for k in keys:
        p = app.p[k]
        (s["ui_loaded_array_paths"] if app._is_prop(p) else s["ui_loaded_rep_paths"]).append(p)
        s["selected_paths"].append(p)


def _run(host, text, lang="fr"):
    cmd = host.parse(text)
    assert cmd["intent"] is not None, text
    r = host.answer(cmd, lang) if host.readonly(cmd["intent"]) else host.execute(cmd, lang)
    return cmd, r


# ------------------------------------------------------------------ the catalogue
def test_the_catalogue_names_each_object_once_with_its_parent_and_kind(host, app):
    objs = host.objects()
    by = {o["path"]: o for o in objs}
    assert len(by) == len(objs)
    p = app.p
    grid = by[p["grid"]]
    assert (grid["title"], grid["type"], grid["parent"], grid["rep_path"]) == (
        "Geogrid", "IjkGrid", None, p["grid"])
    poro = by[p["poro"]]
    assert (poro["title"], poro["kind"], poro["parent"], poro["rep_path"], poro["tab"]) == (
        "Total Porosity", "porosity", p["grid"], p["grid"], "reservoir")
    assert poro["uom"] == "m3/m3"
    gr = by[p["gr"]]
    assert (gr["parent"], gr["rep_path"], gr["tab"]) == (p["wb"], p["frame"], "well")
    wb = by[p["wb"]]
    assert (wb["type"], wb["trajectory"], wb["parent"]) == ("Wellbore", p["traj"], None)
    assert by[p["surf"]]["type"] == "Grid2d" and by[p["surf"]]["tab"] == "surface"
    # The parts of a well, the folders and the partial stub are not objects.
    for key in ("traj", "frame", "part"):
        assert p[key] not in by
    assert all(o["type"] not in ("GridContainer", "PropertiesFolder", "WellboreLogsFolder")
               for o in objs)
    assert not any(o["loaded"] for o in objs)


def test_the_live_flags_follow_the_reads(host, app):
    _load(app, "poro", "traj")
    by = {o["path"]: o for o in host.objects()}
    assert by[app.p["poro"]]["loaded"] and by[app.p["wb"]]["loaded"]
    assert not by[app.p["ntg"]]["loaded"]


def test_the_catalogue_is_walked_again_only_when_the_assembly_changes(host, app):
    walks = []
    real = host._walk
    host._walk = lambda tree: walks.append(1) or real(tree)
    host.objects()
    host.objects()
    assert len(walks) == 1
    for fn in app.state.watchers["assembly_rev"]:
        fn(assembly_rev=2)
    host.objects()
    assert len(walks) == 2


def test_derived_properties_are_named_by_their_title(host, app):
    path = f"derived://{app.p['grid']}#PHIE"
    app.ctx.derived_store = SimpleNamespace(active_paths=lambda: [path], title=lambda p: "ƒ PHIE")
    d = {o["path"]: o for o in host.objects()}[path]
    assert (d["type"], d["parent"], d["title"], d["loaded"]) == ("DerivedProperty", app.p["grid"],
                                                                "ƒ PHIE", True)


def test_no_tree_no_objects():
    app = FakeApp()
    app.ctx.tree = None
    assert FesppAssistantHost(app.server).objects() == []


# ------------------------------------------------------------------ parse / missing / ask
def test_parse_resolves_the_targets_on_the_catalogue(host, app):
    cmd = host.parse("montre la porosité de Geogrid")
    assert cmd["intent"] == "show" and cmd["sure"] and cmd["missing"] == []
    assert [t["path"] for t in cmd["targets"]] == [app.p["poro"]]
    assert host.parse("show the porosity of Geogrid")["intent"] == "show"


def test_nonsense_is_not_a_command(host):
    for text in ("blablabla xyz", "xqzt"):
        assert host.parse(text)["intent"] is None


def test_two_properties_for_one_command_ask_which_one(host, app):
    cmd = host.parse("montre la perméabilité de Geogrid")
    assert cmd["missing"] == ["object|kind"] and not cmd["sure"]
    assert {t["path"] for t in host.targets(cmd)} == {app.p["kh"], app.p["kv"]}
    ask = host.ask_missing(cmd, "fr")
    ids = [c["id"] for c in ask["choices"]]
    assert ids[-1] == "cancel"
    assert set(ids[:-1]) == {f"target:{app.p['kh']}", f"target:{app.p['kv']}"}
    assert any(c["label"] == "Horizontal Permeability de Geogrid" for c in ask["choices"])
    assert "Which one" in host.ask_missing(cmd, "en")["text"]
    # The panel's "target:<path>" button, as AssistantController.choose applies it.
    cmd["targets"] = [t for t in host.targets(cmd) if t["path"] == app.p["kv"]]
    cmd["missing"] = []
    r = host.execute(cmd, "fr")
    assert r["ok"] and r["text"] == "Affiché : Vertical Permeability de Geogrid."
    assert app.called("select_paths") == [([app.p["kv"]],)]


def test_a_grid_named_without_a_kind_takes_its_active_property(host, app):
    _load(app, "poro")
    cmd = host.parse("filtre Geogrid au-dessus de 0,2")
    assert cmd["missing"] == ["object|kind"]          # four properties: which one?
    app.state[f"active_path__{VID}"] = app.p["poro"]
    cmd = host.parse("filtre Geogrid au-dessus de 0,2")
    assert cmd["missing"] == [] and cmd["sure"]
    assert [t["path"] for t in host.targets(cmd)] == [app.p["poro"]]


def test_a_kind_with_two_properties_on_one_grid_is_asked_even_with_one_active(host, app):
    _load(app, "kh")
    app.state[f"active_path__{VID}"] = app.p["kh"]
    cmd = host.parse("filtre la perméabilité au-dessus de 100")
    assert cmd["missing"] == ["object|kind"]
    assert {t["path"] for t in host.targets(cmd)} == {app.p["kh"], app.p["kv"]}


def test_no_property_named_nor_active_offers_them_all(host, app):
    cmd = host.parse("surligne les mailles au-dessus de 0,2")
    assert cmd["intent"] == "highlight" and cmd["missing"] == ["object|kind"]
    ask = host.ask_missing(cmd, "fr")
    assert f"target:{app.p['poro']}" in [c["id"] for c in ask["choices"]]
    assert len(ask["choices"]) <= 9
    # With a property active, it answers instead.
    app.state[f"active_path__{VID}"] = app.p["poro"]
    assert host.parse("surligne les mailles au-dessus de 0,2")["sure"]


def test_a_kind_said_alone_is_the_grids_property_not_the_wells_logs(host, app):
    """A kind said alone means the grid's property, not the wells' logs.

    "la porosité" (the porosity) names both Total Porosity of Geogrid and a
    log of the wells; a filter, a highlight or a statistic on it means the
    grid's."""
    p = app.p
    for text in ("filtre la porosité au-dessus de 0,2",
                 "surligne les mailles où la porosité dépasse 0,2",
                 "quelle est la porosité moyenne ?", "montre la porosité",
                 "passe la porosité en viridis"):
        cmd = host.parse(text)
        assert cmd["sure"] and cmd["missing"] == [], text
        assert [t["path"] for t in host.targets(cmd)] == [p["poro"]], text
    # With the well named: its log.
    cmd = host.parse("montre la porosité du puits 55/33-1")
    assert [t["path"] for t in host.targets(cmd)] == [p["phi_log"]]
    # A highlight offers grid properties only.
    cmd = host.parse("surligne les mailles au-dessus de 0,2")
    ids = {c["id"] for c in host.ask_missing(cmd, "fr")["choices"]}
    assert f"target:{p['poro']}" in ids and f"target:{p['phi_log']}" not in ids
    assert f"target:{p['gr']}" not in ids


def test_a_missing_bound_is_asked_in_words(host):
    cmd = {"intent": "threshold", "slots": {"kind": "porosity"}, "targets": [], "missing": ["min|max"]}
    ask = host.ask_missing(cmd, "fr")
    assert "valeurs" in ask["text"] and [c["id"] for c in ask["choices"]] == ["cancel"]


def test_labels_and_handlers_exist_for_every_intent_in_both_languages(host):
    assert set(LABELS) == set(catalogue.INTENTS)
    for intent, spec in catalogue.INTENTS.items():
        fr, en = host.label(intent, "fr"), host.label(intent, "en")
        assert fr and en, intent
        assert host.readonly(intent) == spec["readonly"]
        prefix = "_ans_" if spec["readonly"] else "_do_"
        assert callable(getattr(host, prefix + intent, None)), intent


@pytest.mark.parametrize("lang", ["fr", "en"])
def test_the_examples_are_commands_on_the_loaded_data(host, lang):
    ex = host.examples(lang)
    assert len(ex) == 6 and "Geogrid" in ex[0]
    assert [host.parse(e)["intent"] for e in ex] == [
        "show", "threshold", "highlight", "value", "describe", "open_panel"]


def test_the_highlight_example_asks_for_the_top_of_the_range(host):
    """The highlight example uses a bound near the top of the data range.

    A highlight lights cells one by one (capped): its example must not
    light half the grid, as the middle of the range would."""
    ex = host.examples("fr")
    assert ex[1] == "filtre la porosité au-dessus de 0,2"
    assert ex[2] == "surligne les mailles où la porosité dépasse 0,36"


def test_without_data_the_examples_are_generic():
    app = FakeApp()
    app.ctx.tree = None
    host = FesppAssistantHost(app.server)
    assert host.examples("fr")[0] == "liste ce qui est chargé"
    assert host.parse(host.examples("en")[0])["intent"] == "list"


# ------------------------------------------------------------------ show / hide / isolate
def test_show_reads_opens_the_eye_activates_and_undo_puts_the_eyes_back(host, app):
    cmd, r = _run(host, "montre la porosité de Geogrid")
    assert r["ok"] and r["text"] == "Affiché : Total Porosity de Geogrid."
    s, p = app.state, app.p
    assert app.called("select_paths") == [([p["poro"]],)]
    eyes = s[f"visible_paths__{VID}"]
    assert eyes.count(p["poro"]) == 1                       # born visible: only added
    assert app.called("on_eye_changed")[-1] == (VID, eyes)   # the view id first
    assert s[f"active_path__{VID}"] == p["poro"]
    assert s[f"active_by_tab__{VID}"] == {"reservoir": p["poro"]}
    u = host.undo(r["undo"], "fr")
    assert u["ok"] and u["text"].startswith("Annulé")
    assert s[f"visible_paths__{VID}"] == [] and s[f"active_path__{VID}"] == ""
    assert app.called("on_eye_changed")[-1] == (VID, [])
    assert s["ui_loaded_array_paths"] == [p["poro"]]          # what was read stays read


def test_show_a_well_reads_its_trajectory(host, app):
    _, r = _run(host, "montre le puits 55/33-1")
    assert r["ok"]
    assert app.called("select_paths") == [([app.p["traj"]],)]
    assert app.p["traj"] in app.state[f"visible_paths__{VID}"]


def test_a_refused_read_is_said(host, app):
    app.refuse.add(app.p["poro"])
    _, r = _run(host, "montre la porosité de Geogrid")
    assert not r["ok"] and r["undo"] is None
    assert "Total Porosity" in r["text"] and "refused" in r["text"]


def test_hide_closes_the_object_and_its_properties_eyes(host, app):
    p = app.p
    _load(app, "poro", "traj")
    app.state[f"visible_paths__{VID}"] = [p["grid"], p["poro"], p["traj"]]
    _, r = _run(host, "cache Geogrid")
    assert r["ok"] and app.state[f"visible_paths__{VID}"] == [p["traj"]]
    assert app.called("on_eye_changed")[-1] == (VID, [p["traj"]])
    host.undo(r["undo"], "fr")
    assert app.state[f"visible_paths__{VID}"] == [p["grid"], p["poro"], p["traj"]]


def test_hide_what_is_not_shown_changes_nothing(host, app):
    _, r = _run(host, "cache Geogrid")
    assert r["ok"] and r["undo"] is None and not app.called("on_eye_changed")


def test_isolate_keeps_only_the_target(host, app):
    p = app.p
    _load(app, "poro", "traj", "surf")
    app.state[f"visible_paths__{VID}"] = [p["grid"], p["poro"], p["traj"], p["surf"]]
    _, r = _run(host, "isole Top Volantis")
    assert r["ok"] and app.state[f"visible_paths__{VID}"] == [p["surf"]]
    host.undo(r["undo"], "fr")
    assert app.state[f"visible_paths__{VID}"] == [p["grid"], p["poro"], p["traj"], p["surf"]]


def _obj(host, path):
    return {o["path"]: o for o in host.objects()}[path]


def test_isolate_a_property_keeps_its_grid_eye(host, app):
    """Isolating a property keeps its grid's eye open.

    In BlockScope a property eye only colours: [porosity] alone would hide
    everything while the reply says "only shown"."""
    p = app.p
    _load(app, "grid", "poro", "surf")
    app.state[f"visible_paths__{VID}"] = [p["grid"], p["poro"], p["surf"]]
    poro = _obj(host, p["poro"])
    cmd = {"intent": "isolate", "slots": {"objects": [[poro]]}, "targets": [poro], "text": "isole la porosité"}
    r = host.execute(cmd, "fr")
    assert r["ok"] and app.state[f"visible_paths__{VID}"] == [p["grid"], p["poro"]]


def test_isolate_a_grid_keeps_the_property_colouring_it(host, app):
    p = app.p
    _load(app, "grid", "poro", "surf")
    app.state[f"visible_paths__{VID}"] = [p["grid"], p["poro"], p["surf"]]
    _, r = _run(host, "isole Geogrid")
    assert r["ok"] and app.state[f"visible_paths__{VID}"] == [p["grid"], p["poro"]]


def test_show_a_property_whose_grid_eye_was_closed_opens_it(host, app):
    p = app.p
    _load(app, "grid", "poro")
    app.state[f"visible_paths__{VID}"] = [p["poro"]]          # the grid's eye closed by the user
    _, r = _run(host, "montre la porosité de Geogrid")
    assert r["ok"] and app.state[f"visible_paths__{VID}"] == [p["poro"], p["grid"]]
    assert app.called("on_eye_changed")[-1] == (VID, [p["poro"], p["grid"]])


def test_a_filter_on_a_grid_whose_eye_is_closed_opens_it(host, app):
    """A filter on a hidden grid shows the grid again.

    With the grid hidden and another property's eye open, the grid shows
    again and the colour stays that property's."""
    p = app.p
    _load(app, "grid", "poro", "kh")
    app.state[f"visible_paths__{VID}"] = [p["kh"]]
    _, r = _run(host, "filtre la porosité au-dessus de 0,2")
    assert r["ok"] and app.state[f"visible_paths__{VID}"] == [p["kh"], p["grid"]]


def test_a_half_failed_read_leaves_the_view_as_it_was(host, app):
    """A read that half fails leaves the view's eyes as they were.

    Top Volantis loads (born visible) and the porosity is refused: the
    reply is an error, so there is no undo, and the view must not keep Top
    Volantis."""
    p = app.p
    app.refuse.add(p["poro"])
    surf, poro = _obj(host, p["surf"]), _obj(host, p["poro"])
    for intent in ("show", "isolate"):
        cmd = {"intent": intent, "slots": {"objects": [[surf], [poro]]}, "targets": [surf, poro],
               "text": "montre Top Volantis et la porosité"}
        r = host.execute(cmd, "fr")
        assert not r["ok"] and r["undo"] is None and "Total Porosity" in r["text"]
        assert app.state[f"visible_paths__{VID}"] == [] and app.state[f"active_path__{VID}"] == ""
    assert p["surf"] in app.state["ui_loaded_rep_paths"]     # what was read stays read


def test_without_a_3d_view_a_gesture_says_so():
    app = FakeApp(render=())
    host = FesppAssistantHost(app.server)
    _, r = _run(host, "montre la porosité de Geogrid")
    assert not r["ok"] and "vue 3D" in r["text"] and not app.called("select_paths")


# ------------------------------------------------------------------ threshold / highlight
def test_threshold_adds_a_root_entry_then_its_range_and_undo_removes_it(host, app):
    p, s = app.p, app.state
    _, r = _run(host, "filtre la porosité au-dessus de 0,2")
    assert r["ok"], r["text"]
    assert r["text"] == "Total Porosity de Geogrid : mailles gardées de 0,2 à 0,4."
    # Read, then the grid in the Reservoir tab, the property active.
    assert app.called("select_paths") == [([p["poro"]],)]
    assert s[f"active_by_tab__{VID}"]["reservoir"] == p["grid"]
    assert s[f"active_path__{VID}"] == p["poro"]
    (add,) = app.called("threshold_add")
    assert add == ([PORO_VTK, None], VID)
    name = s[f"ui_thresholds__{VID}"][-1]["name"]
    # "Above 0.2": up to the top of the data range.
    assert app.called("threshold_range") == [([name, [0.2, 0.4]], VID)]
    host.undo(r["undo"], "fr")
    assert app.called("threshold_remove") == [(name, VID)]
    assert s[f"ui_thresholds__{VID}"] == [] and s[f"active_path__{VID}"] == ""


def test_a_second_filter_on_the_same_property_changes_its_range(host, app):
    """A second filter on the same property changes the existing entry's range.

    Never a second root on the same array: roots render in parallel (a
    union), so [0.2, max] ∪ [0.3, max] would still show 0.2 while the reply
    says 0.3. The entry's range changes; the undo puts it back."""
    s = app.state
    _run(host, "filtre la porosité au-dessus de 0,2")
    (e,) = app.isos[(VID, app.p["grid"])].chain
    _, r = _run(host, "filtre la porosité au-dessus de 0,3")
    assert r["ok"] and r["text"] == "Total Porosity de Geogrid : mailles gardées de 0,3 à 0,4."
    assert len(app.called("threshold_add")) == 1
    (e2,) = app.isos[(VID, app.p["grid"])].chain
    assert (e2["name"], e2["low"], e2["high"]) == (e["name"], 0.3, 0.4)
    host.undo(r["undo"], "fr")
    (e3,) = app.isos[(VID, app.p["grid"])].chain
    assert (e3["low"], e3["high"]) == (0.2, 0.4)
    assert not app.called("threshold_remove")
    assert s[f"active_path__{VID}"] == app.p["poro"]      # the view as after the first filter


def test_a_hidden_entry_on_the_same_property_is_shown_again_and_hidden_on_undo(host, app):
    _run(host, "filtre la porosité au-dessus de 0,2")
    iso = app.isos[(VID, app.p["grid"])]
    iso.chain[0]["visible"] = False
    _, r = _run(host, "filtre la porosité au-dessus de 0,3")
    assert r["ok"] and iso.chain[0]["visible"] is True
    host.undo(r["undo"], "fr")
    assert iso.chain[0]["visible"] is False and (iso.chain[0]["low"], iso.chain[0]["high"]) == (0.2, 0.4)


def test_a_filter_on_another_property_chains_under_the_last_one(host, app):
    """A filter on another property chains as an intersection.

    The reply says the other filter still applies."""
    _run(host, "filtre la porosité au-dessus de 0,2")
    iso = app.isos[(VID, app.p["grid"])]
    first = iso.chain[0]["name"]
    _, r = _run(host, "filtre Horizontal Permeability au-dessus de 0,1")
    assert r["ok"], r["text"]
    kh_vtk = make_valid_vtk_name("Horizontal Permeability")
    assert app.called("threshold_add")[-1] == ([kh_vtk, first], VID)
    assert r["text"] == ("Horizontal Permeability de Geogrid : mailles gardées de 0,1 à 0,4."
                         " Les autres filtres de la grille s'appliquent aussi (Total Porosity).")
    host.undo(r["undo"], "fr")
    assert [e["name"] for e in iso.chain] == [first]


def test_a_filter_on_a_union_says_so(host, app):
    """A filter added over a union of roots says so.

    With two roots built in the Thresholds card, the reply must not claim
    that only this range is kept."""
    iso = app.isos[(VID, app.p["grid"])] = FakeIso()
    iso.chain = [{"name": "a", "parent_name": None, "array": "X", "visible": True, "low": 0, "high": 1,
                  "data_range": [0, 1]},
                 {"name": "b", "parent_name": None, "array": "Y", "visible": True, "low": 0, "high": 1,
                  "data_range": [0, 1]}]
    _, r = _run(host, "filter porosity above 0.2", "en")
    assert r["ok"] and "a union" in r["text"]


def test_a_failed_add_never_takes_another_entry_for_the_new_one(host, app):
    """A failed add never mistakes an existing entry for the new one.

    ui_thresholds__<vid> holds another grid's chain (the last one a card
    gesture pushed); the add fails on Geogrid, whose own entry is pushed.
    Diffing the view's variable would take the user's entry for the new
    one, overwrite its range and remove it on undo."""
    p = app.p
    iso = app.isos[(VID, p["grid"])] = FakeIso()
    iso.chain = [{"name": "users", "parent_name": None, "array": "NTG", "visible": True,
                  "low": 0.5, "high": 0.6, "data_range": [0, 1]}]
    app.state[f"ui_thresholds__{VID}"] = [{"name": "other_grid_entry", "array": "Z"}]
    app.add_fails = True
    _, r = _run(host, "filtre la porosité au-dessus de 0,2")
    assert not r["ok"] and r["undo"] is None
    assert not app.called("threshold_range") and not app.called("threshold_remove")
    assert iso.chain[0]["low"] == 0.5


def test_a_threshold_below_keeps_from_the_bottom_of_the_data(host, app):
    _, r = _run(host, "filter porosity below 0.1", "en")
    assert r["ok"] and r["text"] == "Geogrid Total Porosity: cells kept from 0 to 0.1."
    assert app.called("threshold_range")[0][0][1] == [0.0, 0.1]


def test_clear_threshold_removes_the_chain_and_undo_replays_it(host, app):
    _run(host, "filtre la porosité au-dessus de 0,2")
    _, r = _run(host, "enlève le filtre")
    assert r["ok"] and "Geogrid" in r["text"]
    assert len(app.called("threshold_remove")) == 1
    assert app.isos[(VID, app.p["grid"])].chain == []
    host.undo(r["undo"], "fr")
    assert len(app.called("threshold_add")) == 2
    (e,) = app.isos[(VID, app.p["grid"])].chain
    assert (e["array"], e["low"], e["high"]) == (PORO_VTK, 0.2, 0.4)


def test_no_filter_to_clear(host, app):
    _, r = _run(host, "enlève le filtre")
    assert r["ok"] and r["undo"] is None and not app.called("threshold_remove")


def test_highlight_activates_the_property_then_lights_the_cells(host, app):
    _, r = _run(host, "surligne les mailles où la porosité dépasse 0,2")
    assert r["ok"], r["text"]
    assert app.called("highlight_where") == [([0.2, None], VID)]
    assert app.highlight_active == app.p["poro"]            # active before the call
    assert app.p["poro"] in app.state[f"visible_paths__{VID}"]
    assert r["text"] == "3 mailles sur 8 surlignées : Total Porosity ≥ 0,2."
    host.undo(r["undo"], "fr")
    assert app.called("node_highlight") == [([], VID)]


def test_highlight_in_english_and_between_two_bounds(host, app):
    _, r = _run(host, "highlight the cells where porosity is between 0.1 and 0.3", "en")
    assert app.called("highlight_where") == [([0.1, 0.3], VID)]
    assert r["text"] == "3 of 8 cells highlighted: 0.1 ≤ Total Porosity ≤ 0.3."


def test_a_failed_highlight_is_said_and_leaves_the_view_as_it_was(host, app):
    app.highlight = {"error": "Block not loaded."}
    _, r = _run(host, "surligne les mailles où la porosité dépasse 0,2")
    assert not r["ok"] and "Block not loaded." in r["text"] and r["undo"] is None
    assert app.state[f"active_path__{VID}"] == ""


def test_clear_highlight_has_nothing_to_undo(host, app):
    _, r = _run(host, "enlève la surbrillance")
    assert r["ok"] and r["undo"] is None
    assert app.called("node_highlight") == [([], VID)]


def test_too_many_matches_to_highlight_are_said_not_lit(host, app):
    app.highlight = {"count": 450000, "total": 911493, "valid": 900000, "too_many": 100000,
                     "array": PORO_VTK, "assoc": "CELLS"}
    _, r = _run(host, "surligne les mailles où la porosité dépasse 0,2")
    assert not r["ok"] and r["undo"] is None
    n = numfmt.fmt_int      # the thin space every panel groups digits with
    assert r["text"].startswith(f"{n(450000)} mailles sur {n(900000)} vérifient Total Porosity ≥ 0,2 : trop")
    assert n(100000) in r["text"] and "filtre Total Porosity" in r["text"]
    assert app.state[f"active_path__{VID}"] == ""          # the view as it was


# ------------------------------------------------------------------ a Globe view
@pytest.mark.parametrize("text", ["filtre la porosité au-dessus de 0,2", "coupe selon K entre 10 et 20",
                                  "surligne les mailles où la porosité dépasse 0,2", "enlève le filtre"])
def test_a_globe_view_refuses_filters_slices_and_highlights(host, app, text):
    """A Globe view refuses filters, slices and highlights before any read.

    An isolate built on a Globe would draw local-CRS metres thousands of km
    off the Earth, so nothing is read or built."""
    _load(app, "grid")
    app.state[f"ui_globe_mode__{VID}"] = True
    _, r = _run(host, text)
    assert not r["ok"] and "Globe" in r["text"]
    for name in ("select_paths", "threshold_add", "threshold_remove", "slicer_range", "highlight_where"):
        assert not app.called(name), name


def test_undoing_a_filter_on_a_view_flipped_to_globe_builds_nothing(host, app):
    _, r = _run(host, "filtre la porosité au-dessus de 0,2")
    app.state[f"ui_globe_mode__{VID}"] = True
    u = host.undo(r["undo"], "fr")
    assert u["ok"] and "Globe" in u["text"] and not app.called("threshold_remove")
    assert app.state[f"visible_paths__{VID}"] == []         # the eyes are put back all the same


def test_undoing_a_slice_on_a_view_flipped_to_globe_builds_nothing(host, app):
    _load(app, "grid")
    _, r = _run(host, "coupe selon K entre 10 et 20")
    app.state[f"ui_globe_mode__{VID}"] = True
    n = len(app.calls)
    u = host.undo(r["undo"], "fr")
    assert u["ok"] and "Globe" in u["text"]
    assert not [c for c, _ in app.calls[n:] if c.startswith("slicer_")]


def test_filters_removed_are_not_put_back_on_a_globe_until_it_is_3d_again(host, app):
    _run(host, "filtre la porosité au-dessus de 0,2")
    _, r = _run(host, "enlève le filtre")
    app.state[f"ui_globe_mode__{VID}"] = True
    u = host.undo(r["undo"], "fr")
    assert not u["ok"] and "Globe" in u["text"] and len(app.called("threshold_add")) == 1
    app.state[f"ui_globe_mode__{VID}"] = False
    _, u = _run(host, "annule")                               # the token stayed live
    assert u["ok"] and len(app.called("threshold_add")) == 2


# ------------------------------------------------------------------ derived properties
def _derived(app):
    path = f"derived://{app.p['grid']}#PHIE"
    app.ctx.derived_store = SimpleNamespace(active_paths=lambda: [path], title=lambda p: "ƒ PHIE")
    return path


@pytest.mark.parametrize("intent,slots", [("show", {}), ("isolate", {}), ("threshold", {"min": 0.2}),
                                          ("highlight", {"min": 0.2}), ("colormap", {"preset": "Turbo"}),
                                          ("hide_nan", {"on": True})])
def test_a_derived_property_is_not_drawn_and_says_why(host, app, intent, slots):
    path = _derived(app)
    d = {o["path"]: o for o in host.objects()}[path]
    cmd = {"intent": intent, "slots": dict(slots, objects=[[d]]), "targets": [d], "text": "ƒ PHIE"}
    r = host.execute(cmd, "fr")
    assert not r["ok"] and "dérivée" in r["text"] and "ƒ PHIE" in r["text"]
    assert not app.called("on_eye_changed") and not app.called("cmap_preset")
    assert not app.called("threshold_add") and not app.called("highlight_where")


def test_a_derived_property_gives_way_to_a_drawn_one(host, app):
    path = _derived(app)
    idx = {o["path"]: o for o in host.objects()}
    cmd = {"intent": "threshold", "slots": {"min": 0.2}, "targets": [idx[path], idx[app.p["poro"]]],
           "text": "filtre au-dessus de 0,2"}
    assert [t["path"] for t in host.targets(cmd)] == [app.p["poro"]]
    # Nothing named: a highlight never offers it.
    cmd = {"intent": "highlight", "slots": {"min": 0.2}, "targets": [], "text": "surligne au-dessus de 0,2"}
    assert path not in {t["path"] for t in host.targets(cmd)}
    # A statistic still reads it.
    cmd = {"intent": "value", "slots": {}, "targets": [idx[path]], "text": "moyenne de ƒ PHIE"}
    assert [t["path"] for t in host.targets(cmd)] == [path]


# ------------------------------------------------------------------ slice / colours / view
def test_slice_keeps_a_range_of_layers_and_undo_turns_it_off(host, app):
    _load(app, "grid")
    _, r = _run(host, "coupe selon K entre 10 et 20")
    assert r["ok"] and app.called("slicer_range") == [(["k", [10, 20]], VID)]
    assert app.state[f"active_by_tab__{VID}"]["reservoir"] == app.p["grid"]
    host.undo(r["undo"], "fr")
    assert app.called("slicer_mode") == [("full", VID)]
    # The command built the grid's slicer state: its whole extent is back,
    # so switching the card's Slice on next does not show K 10-20.
    iso = app.isos[(VID, app.p["grid"])]
    assert (iso._range_i, iso._range_j, iso._range_k) == ([0, 10], [0, 20], [0, 30])
    assert iso._volumes == [[[0, 10], [0, 20], [0, 30]]] and iso._range_mode == "full"


def test_slice_undo_replays_every_axis_even_an_empty_one(host, app):
    """The slice undo replays every axis, including an empty one.

    With an I plane at 20 and no K plane, "coupe selon K" (slice along K)
    adds K = 15; the undo must send K = [] again, since slicer_positions
    replaces only the axis it names."""
    p = app.p
    _load(app, "grid")
    iso = app.isos[(VID, p["grid"])] = FakeIso()
    iso._range_mode = "slice"
    iso._slices_i_list, iso._slices_k_list = [20], []
    iso._slices_i_visible_list, iso._slices_k_visible_list = [True], []
    _, r = _run(host, "coupe selon K")
    assert r["ok"] and iso._slices_k_list == [15]
    n = len(app.calls)
    host.undo(r["undo"], "fr")
    replay = [(name, args[0]) for name, args in app.calls[n:] if name.startswith("slicer_")]
    assert replay == [
        ("slicer_range", ["i", [0, 10]]), ("slicer_range", ["j", [0, 20]]), ("slicer_range", ["k", [0, 30]]),
        ("slicer_positions", ["i", [20]]), ("slicer_visibility", ["i", [True]]),
        ("slicer_positions", ["j", [10]]), ("slicer_visibility", ["j", [True]]),
        ("slicer_positions", ["k", []]), ("slicer_visibility", ["k", []]),
        ("slicer_volumes", [[[0, 10], [0, 20], [0, 30]]]), ("slicer_volumes_visible", [True]),
        ("slicer_mode", "slice")]
    assert (iso._slices_i_list, iso._slices_k_list, iso._range_mode) == ([20], [], "slice")


def test_slice_undo_replays_a_range_and_several_boxes(host, app):
    p = app.p
    _load(app, "grid")
    iso = app.isos[(VID, p["grid"])] = FakeIso()
    iso._range_mode, iso._range_k = "range", [10, 20]
    iso._volumes = [[[0, 10], [0, 20], [10, 20]], [[0, 5], [0, 5], [0, 5]]]
    iso._volumes_visible = [True, False]
    _, r = _run(host, "coupe selon K entre 5 et 8")
    assert r["ok"] and iso._range_k == [5, 8]
    host.undo(r["undo"], "fr")
    assert iso._range_k == [10, 20] and iso._range_mode == "range"
    assert iso._volumes == [[[0, 10], [0, 20], [10, 20]], [[0, 5], [0, 5], [0, 5]]]
    assert iso._volumes_visible == [True, False]


def test_slice_layers_outside_the_grid_are_refused(host, app):
    _load(app, "grid")
    _, r = _run(host, "coupe selon K entre 100 et 120")
    assert not r["ok"] and r["undo"] is None
    assert r["text"] == "Geogrid : K va de 0 à 30 ; ces couches n'y sont pas."
    assert not app.called("slicer_range")
    assert app.state[f"active_path__{VID}"] == ""          # the activation went back


def test_colormap_saves_the_tables_first_and_undo_writes_them_back(host, app):
    _load(app, "poro")
    _, r = _run(host, "passe la porosité en viridis")
    assert r["ok"] and "Viridis" in r["text"]
    names = [n for n, _ in app.calls]
    assert names.index("session_view_tables") < names.index("cmap_preset")
    assert app.called("cmap_preset") == [("Viridis (matplotlib)", VID)]
    host.undo(r["undo"], "fr")
    ((vid, tables),) = app.called("session_restore_view_tables")
    assert vid == VID and tables[0]["array"] == PORO_VTK


@pytest.mark.parametrize("before", ["Turbo", None])
def test_colormap_undo_puts_back_the_preset_the_card_names(host, app, before):
    _load(app, "poro")
    app.state["ui_active_colormap_by_view"] = {VID: before} if before else {}
    _, r = _run(host, "passe la porosité en viridis")
    assert app.state["ui_active_colormap_by_view"][VID] == "Viridis (matplotlib)"
    host.undo(r["undo"], "fr")
    assert app.state["ui_active_colormap_by_view"].get(VID) == before


def test_colours_without_a_property_say_so(host, app):
    _, r = _run(host, "recale la palette")
    assert not r["ok"] and not app.called("cmap_rescale")


def test_color_range_and_rescale_act_on_the_active_property(host, app):
    _load(app, "poro")
    app.state[f"active_path__{VID}"] = app.p["poro"]
    app.state.flush()
    _, r = _run(host, "palette de 0,1 à 0,3")
    assert r["ok"] and app.called("cmap_range") == [([0.1, 0.3], VID)]
    _, r = _run(host, "recale la palette")
    assert r["ok"] and app.called("cmap_rescale") == [("data", VID)]


def test_hide_nan_and_its_undo(host, app):
    _load(app, "poro")
    app.state[f"active_path__{VID}"] = app.p["poro"]
    app.state.flush()
    _, r = _run(host, "masque les valeurs absentes")
    assert r["ok"] and app.called("cmap_hide_nan") == [(True, VID)]
    host.undo(r["undo"], "fr")
    assert app.called("cmap_hide_nan")[-1] == (False, VID)


def test_hide_nan_undo_puts_back_the_previous_mask_not_the_default(host, app):
    """The hide-NaN undo restores the previous mask, not a default.

    Starting with the mask on, "show the missing values" then Undo puts it
    back on (a hard-coded False would pass the test above)."""
    _load(app, "poro")
    app.state[f"ui_colormap__{VID}"] = {"hide_nan": True}
    app.state[f"active_path__{VID}"] = app.p["poro"]
    app.state.flush()
    cmd = {"intent": "hide_nan", "slots": {"on": False}, "targets": [], "text": "montre les valeurs absentes"}
    r = host.execute(cmd, "fr")
    assert r["ok"] and app.called("cmap_hide_nan") == [(False, VID)]
    host.undo(r["undo"], "fr")
    assert app.called("cmap_hide_nan")[-1] == (True, VID)


def test_a_refused_hide_nan_leaves_the_active_node_as_it_was(host, app):
    """A refused hide-NaN leaves the active node as it was.

    The porosity is read with its eye closed, so the mask finds no grid
    painted by it. The activation done for it is reverted, since the
    failure drops the undo."""
    _load(app, "poro")
    app.nan_ok = False
    _, r = _run(host, "masque les valeurs absentes de la porosité")
    assert not r["ok"] and r["undo"] is None
    assert app.state[f"active_path__{VID}"] == "" and app.state[f"active_by_tab__{VID}"] == {}


def test_hide_nan_refused_gives_the_reason(host, app):
    _load(app, "poro")
    app.state[f"active_path__{VID}"] = app.p["poro"]
    app.state.flush()
    app.nan_ok = False
    _, r = _run(host, "masque les valeurs absentes")
    assert not r["ok"] and "No visible grid" in r["text"]


def test_flat_colors_takes_the_view_id_first(host, app):
    _, r = _run(host, "couleurs exactes")
    assert r["ok"] and app.called("set_flat_colors") == [(VID, True)]
    host.undo(r["undo"], "fr")
    assert app.called("set_flat_colors")[-1] == (VID, False)


def test_flat_colors_undo_puts_back_the_previous_shading(host, app):
    app.state[f"ui_flat_colors__{VID}"] = True
    cmd = {"intent": "flat_colors", "slots": {"on": False}, "targets": [], "text": "remets l'ombrage"}
    r = host.execute(cmd, "fr")
    assert r["ok"] and r["text"] == "Ombrage rétabli." and app.called("set_flat_colors") == [(VID, False)]
    host.undo(r["undo"], "fr")
    assert app.called("set_flat_colors")[-1] == (VID, True)


def test_reset_camera_and_undo_puts_the_camera_back(host, app):
    _, r = _run(host, "recadre la vue")
    assert r["ok"] and app.called("nav_reset") == [(VID,)]
    pv = app.mv.pv[VID]
    assert pv.CameraPosition == [5, 5, 5] and pv.CenterOfRotation == [0, 0, 0]
    host.undo(r["undo"], "fr")
    # The pivot too (vtk.js orbits around it), and the linked views follow.
    assert pv.CameraPosition == [0, 0, 10] and pv.CenterOfRotation == [1, 2, 3]
    assert app.called("camera_link_sync") == [(VID,)]


def test_reset_camera_on_an_object_and_its_undo(host, app):
    _load(app, "grid")
    _, r = _run(host, "recadre sur Geogrid")
    assert r["ok"] and r["text"] == "Vue cadrée sur Geogrid."
    assert app.called("nav_zoom_active") == [(VID,)]
    assert app.state[f"active_path__{VID}"] == app.p["grid"]
    host.undo(r["undo"], "fr")
    assert app.mv.pv[VID].CameraPosition == [0, 0, 10]
    assert app.state[f"active_path__{VID}"] == "" and app.state[f"active_by_tab__{VID}"] == {}


def test_z_scale_and_undo(host, app):
    _, r = _run(host, "exagération verticale x 3")
    assert r["ok"] and app.called("set_zscale") == [(3.0, VID)]
    assert r["text"] == "Exagération verticale × 3."
    host.undo(r["undo"], "fr")
    assert app.called("set_zscale")[-1] == (1.0, VID)


def test_z_scale_undo_puts_back_the_previous_factor_step_by_step(host, app):
    """Each Z-scale undo restores the factor before it, not the default.

    From ×2 (set with the view's slider): ×3, ×5, Undo, Undo gives ×3 then
    ×2, not the default ×1."""
    app.state[f"ui_scale_z__{VID}"] = 2.0
    _, r3 = _run(host, "exagération verticale x 3")
    _, r5 = _run(host, "exagération verticale x 5")
    host.undo(r5["undo"], "fr")
    host.undo(r3["undo"], "fr")
    assert app.called("set_zscale") == [(3.0, VID), (5.0, VID), (3.0, VID), (2.0, VID)]


def test_new_view_and_undo_closes_it(host, app):
    _, r = _run(host, "ouvre une nouvelle vue")
    assert r["ok"] and app.called("open_render_view") == [(None,)]
    new = [v for v in app.mv.view_ids() if v != VID]
    host.undo(r["undo"], "fr")
    assert app.mv.removed == new


# ------------------------------------------------------------------ panels
def test_open_statistics_and_undo_closes_the_new_panel(host, app):
    _, r = _run(host, "ouvre les statistiques")
    assert r["ok"] and app.called("open_compare") == [()]
    assert "Statistiques" in r["text"]
    (pid,) = app.mv.panel_ids_of_kind("compare")
    host.undo(r["undo"], "fr")
    assert app.mv.removed == [pid]


def test_statistics_of_a_property_add_it_read_or_not(host, app):
    """"Add to stats" reads what is not read, born hidden, and opens the view."""
    _, r = _run(host, "ouvre les statistiques de la porosité")
    assert r["ok"] and app.called("add_to_stats") == [(app.p["poro"],)]
    assert app.called("open_compare") == []
    (pid,) = app.mv.panel_ids_of_kind("compare")
    _load(app, "poro")
    _run(host, "ouvre les statistiques de la porosité")
    assert app.called("add_to_stats") == [(app.p["poro"],)] * 2
    assert app.mv.panel_ids_of_kind("compare") == [pid]


@pytest.mark.parametrize("words", ["ouvre les statistiques", "ouvre la comparaison"])
def test_both_words_open_the_one_view_under_one_name(host, app, words):
    _, r = _run(host, words)
    assert r["ok"] and "Statistiques" in r["text"]
    assert len(app.mv.panel_ids_of_kind("compare")) == 1
    assert app.mv.panel_ids_of_kind("stats") == []


@pytest.mark.parametrize("words, axis, kept", [
    ("ouvre les statistiques de la porosité pour tous les pas de temps", "ts",
     [(None, 0), (None, 1), (None, 2)]),
    ("ouvre les statistiques de la porosité pour toutes les réalisations", "real",
     [(0, None), (1, None), (2, None)])])
def test_every_step_or_realization_pins_one_row_each_on_the_property_s_row(host, app, words, axis, kept):
    app.pin_values = {axis: [0, 1, 2]}
    _, r = _run(host, words)
    assert r["ok"]
    assert app.called("compare_set") == [("pin_all", ["i1", axis])], "on the item's uid"
    items = app.state["ui_compare_items"]
    assert [(it["real"], it["ts"]) for it in items if it["pinned"]] == kept
    assert "3 ligne(s) épinglée(s)" in r["text"]


def test_a_property_with_a_single_value_says_there_is_nothing_more_to_pin(host, app):
    _, r = _run(host, "ouvre les statistiques de la porosité pour tous les pas de temps")
    assert r["ok"] and "rien à épingler" in r["text"]


def test_closing_the_statistics_and_undo_opens_the_view_on_what_it_held(host, app):
    _run(host, "ouvre les statistiques")
    (pid,) = app.mv.panel_ids_of_kind("compare")
    app.state[f"compare_tree_selected__{pid}"] = ["/compare/porosity/Geogrid/PORO"]
    app.state["fespp_active_panel_id"] = pid
    _, r = _run(host, "ferme les statistiques")
    assert r["ok"] and app.mv.removed == [pid] and "Statistiques" in r["text"]
    app.mv._kinds.pop(pid)
    host.undo(r["undo"], "fr")
    (back,) = app.mv.panel_ids_of_kind("compare")
    assert app.called("compare_tree_paths") == [(back, ["/compare/porosity/Geogrid/PORO"])]


def test_the_question_names_the_statistics_once(host, app):
    asked = host.ask_missing({"intent": "open_panel", "slots": {}, "missing": ["panel"]}, "fr")
    assert asked["text"].count("Statistiques") == 1
    assert "Comparaison" not in asked["text"]


def test_the_log_view_of_a_well(host, app):
    _, r = _run(host, "ouvre la vue des logs du puits 55/33-1")
    assert r["ok"]
    (pid,) = app.mv.panel_ids_of_kind("welllog")
    assert app.called("welllog_tree_wells") == [(pid, [app.p["wb"]])]


@pytest.mark.parametrize("text", ["ouvre un crossplot de la porosité", "ouvre la distribution de la porosité"])
def test_a_crossplot_or_a_distribution_opens_the_statistics_on_the_property(host, app, text):
    """Both are charts of the Statistics view: the property joins it, read or
    not, and the reply names that view."""
    _, r = _run(host, text)
    assert r["ok"] and app.called("add_to_stats") == [(app.p["poro"],)]
    assert "Statistiques" in r["text"]
    (pid,) = app.mv.panel_ids_of_kind("compare")
    host.undo(r["undo"], "fr")
    assert app.mv.removed == [pid]


def test_a_distribution_needs_a_property(host):
    assert host.parse("ouvre une distribution")["missing"] == ["object|kind"]


def test_closing_the_crossplot_closes_the_statistics_and_says_so(host, app):
    _run(host, "ouvre un crossplot de la porosité")
    (pid,) = app.mv.panel_ids_of_kind("compare")
    _, r = _run(host, "ferme le crossplot")
    assert r["ok"] and "Statistiques" in r["text"]
    assert app.mv.removed == [pid]


def test_the_xml_explorer_on_an_object(host, app):
    _, r = _run(host, "ouvre l'explorateur XML de Geogrid")
    assert r["ok"] and app.xml_active == app.p["grid"]
    assert app.called("xml_open_active") == [(VID,)]
    host.undo(r["undo"], "fr")
    assert app.state[f"active_path__{VID}"] == ""


def test_data_health(host, app):
    _, r = _run(host, "ouvre Data health")
    assert r["ok"] and app.called("open_health") == [()]


# ------------------------------------------------------------------ questions
def test_value_reads_hidden_then_gives_the_statistics_card_figures(host, app, monkeypatch):
    from fespp_on_trame.engine import property_values
    seen = {}

    def values_for(state, tree, reg, path, rep, *a, **k):
        seen.update(path=path, rep=rep, reg=reg)
        return np.array([0.1, 0.2, 0.3, np.nan])

    monkeypatch.setattr(property_values, "values_for", values_for)
    cmd, r = _run(host, "quelle est la porosité moyenne ?")
    assert host.readonly("value") and r["ok"], r["text"]
    assert app.called("session_select") == [([app.p["poro"]],)]    # read born hidden
    assert app.p["poro"] not in app.state[f"visible_paths__{VID}"]
    assert seen == {"path": app.p["poro"], "rep": app.p["grid"], "reg": "REG"}
    rows = dict(r["rows"])
    assert (rows["Minimum"], rows["Maximum"], rows["Moyenne"], rows["Médiane"]) == ("0,1", "0,3", "0,2", "0,2")
    assert rows["Valeurs absentes"] == "1" and rows["Unité"] == "m3/m3"
    assert r["text"] == "Total Porosity de Geogrid : moyenne 0,2 m3/m3, de 0,1 à 0,3 (3 valeurs)."
    _, r = _run(host, "what is the maximum porosity?", "en")
    assert dict(r["rows"])["Mean"] == "0.2"
    assert r["text"].startswith("Geogrid Total Porosity: maximum 0.3 m3/m3")


def test_value_answers_for_the_realization_the_view_shows(host, app, monkeypatch):
    """A value question answers for the realization the view shows.

    With realization 3 picked in the Time & Realizations card, the figures
    are realization 3's (like the colours, a filter or a highlight), and
    the reply says so."""
    from fespp_on_trame.engine import property_values, realization_dispatch
    seen = {}

    def values_for(state, tree, reg, path, rep, real_idx=None, **k):
        seen["real"] = real_idx
        return np.array([0.1, 0.2, 0.3])

    monkeypatch.setattr(property_values, "values_for", values_for)
    monkeypatch.setattr(realization_dispatch, "is_multirealization_property", lambda tree, p: True)
    app.state["ui_active_realization_by_array_by_view"] = {VID: {app.p["poro"]: 3}}
    _, r = _run(host, "quelle est la porosité moyenne ?")
    assert r["ok"] and seen["real"] == 3
    assert r["text"].startswith("Total Porosity de Geogrid (réalisation 3) : moyenne 0,2")
    assert dict(r["rows"])["Réalisation"] == "3"


def test_value_answers_for_the_time_step_the_view_shows(host, app, monkeypatch):
    """A property that varies in time is read at the step of the view's
    Time card, not at whatever step the reader last ran, and the reply
    names the step."""
    from fespp_on_trame.engine import property_values
    seen = {}

    def values_for(state, tree, reg, path, rep, real_idx=None, ts_idx=None, **k):
        seen["ts"] = ts_idx
        return np.array([0.1, 0.2, 0.3])

    monkeypatch.setattr(property_values, "values_for", values_for)
    index = host._index

    def timed():
        d = index()
        d[app.p["poro"]] = dict(d[app.p["poro"]], type="TimeSeries")
        return d

    monkeypatch.setattr(host, "_index", timed)
    app.state[f"ui_timereal__{VID}"] = {"time": {"index": 2, "nb": 5, "label": "2015-06-01"}}
    _, r = _run(host, "quelle est la porosité moyenne ?")
    assert r["ok"] and seen["ts"] == 2
    assert "(pas de temps 3 / 5 (2015-06-01))" in r["text"]
    assert dict(r["rows"])["Pas de temps"] == "3 / 5 (2015-06-01)"


def test_describe_reads_the_citation(host, app, monkeypatch):
    from fespp_on_trame.engine import repo_query
    asked = []

    def object_xml(src, uuid, *a, **k):
        asked.append((src, uuid))
        return ("<resqml2:IjkGridRepresentation><eml:Citation><eml:Title>Geogrid</eml:Title>"
                "<eml:Originator>cedric</eml:Originator><eml:Creation>2026-01-02T03:04:05Z</eml:Creation>"
                "<eml:Format>F2I</eml:Format></eml:Citation></resqml2:IjkGridRepresentation>")

    monkeypatch.setattr(repo_query, "object_xml", object_xml)
    _, r = _run(host, "décris Geogrid")
    assert r["ok"] and asked == [("SRC", U["grid"])]
    rows = dict(r["rows"])
    assert rows["Titre"] == "Geogrid" and rows["Type"] == "grille IJK"
    assert rows["Auteur"] == "cedric" and rows["Créé le"] == "2026-01-02T03:04:05Z"
    assert rows["UUID"] == U["grid"]
    assert r["text"] == "Geogrid : grille IJK, créé par cedric."


def test_list_counts_and_marks_what_is_read(host, app):
    _load(app, "poro")
    _, r = _run(host, "liste ce qui est chargé")
    assert r["ok"]
    assert r["text"] == "1 grille, 5 propriétés, 1 puits, 2 courbes, 1 surface — ✓ = lu."
    rows = dict(r["rows"])
    assert "Total Porosity ✓" in rows["Geogrid"] and rows["Puits"] == "55/33-1"


def test_help_lists_every_command(host):
    _, r = _run(host, "aide")
    assert r["ok"] and len(r["rows"]) == len(catalogue.INTENTS)
    _, r = _run(host, "help", "en")
    assert r["text"].startswith("Here is what I can do")


def test_save_session_downloads_the_file(host, app):
    _, r = _run(host, "enregistre la session")
    assert r["ok"] and app.called("session_save") == [("assistant",)]


# ------------------------------------------------------------------ undo
def test_undo_said_undoes_the_last_gesture_once(host, app):
    _, r = _run(host, "exagération verticale x 3")
    token = r["undo"]
    _, u = _run(host, "annule")
    assert u["ok"] and u["undo"] is None and app.called("set_zscale")[-1] == (1.0, VID)
    # The panel's own Undo button on the same gesture: nothing more happens.
    again = host.undo(token, "fr")
    assert again["ok"] and "déjà" in again["text"]
    assert len(app.called("set_zscale")) == 2
    _, u = _run(host, "undo", "en")
    assert u["text"] == "Nothing to undo."


def test_a_missing_controller_is_said_not_raised(host, app):
    del app.ctrl.highlight_where
    _, r = _run(host, "surligne les mailles où la porosité dépasse 0,2")
    assert not r["ok"] and "highlight_where" in r["text"]


def test_a_filter_never_chains_under_a_hidden_entry(host, app):
    """A new filter never chains under a hidden entry.

    A hidden ancestor drops its branch (IjkGrid._visible_leaf_tips):
    chained under it, the new filter would never be drawn while the reply
    claims cells are kept. It becomes a root of its own, and the hidden
    filter is not named."""
    iso = app.isos[(VID, app.p["grid"])] = FakeIso()
    iso.chain = [{"name": "a", "parent_name": None, "array": "NTG", "visible": False, "low": 0, "high": 1,
                  "data_range": [0, 1]}]
    _, r = _run(host, "filtre la porosité au-dessus de 0,2")
    assert r["ok"], r["text"]
    assert app.called("threshold_add")[-1] == ([PORO_VTK, None], VID)
    assert "autres filtres" not in r["text"] and "union" not in r["text"]


def test_an_entry_under_a_hidden_ancestor_is_not_reused(host, app):
    """An entry under a hidden ancestor is not re-ranged.

    Same array, but under a hidden parent: re-ranging it would draw
    nothing, so a drawn entry is added instead."""
    iso = app.isos[(VID, app.p["grid"])] = FakeIso()
    iso.chain = [{"name": "a", "parent_name": None, "array": "NTG", "visible": False, "low": 0, "high": 1,
                  "data_range": [0, 1]},
                 {"name": "b", "parent_name": "a", "array": PORO_VTK, "visible": True, "low": 0.1,
                  "high": 0.4, "data_range": [0, 0.4]}]
    _, r = _run(host, "filtre la porosité au-dessus de 0,2")
    assert r["ok"], r["text"]
    assert app.called("threshold_add")[-1] == ([PORO_VTK, None], VID)


# ------------------------------------------------------------------ category values (a fluids lookup)
@pytest.fixture
def fluids(host, app, monkeypatch):
    """Give Fluids the value names water / oil / gas.

    The names follow a "Reservoir Fluid" string lookup; the application
    reads them from the file, the fixture supplies them."""
    real = FesppAssistantHost._category_names

    def names(self, tree, path):
        return {0: "water", 1: "oil", 2: "gas"} if path == app.p["fluids"] else real(self, tree, path)
    monkeypatch.setattr(FesppAssistantHost, "_category_names", names)
    host._cache = None
    return app.p["fluids"]


def test_a_categorical_property_carries_its_value_names(host, fluids):
    by = {o["path"]: o for o in host.objects()}
    assert by[fluids]["categories"] == {0: "water", 1: "oil", 2: "gas"}


def test_the_oil_zones_with_a_neutral_verb_ask_filter_first_then_highlight(host, fluids):
    """A neutral verb on a category asks: filter first, then highlight.

    "affiche les zones d'huile" (display the oil zones) may mean keeping
    only those cells or lighting them on the whole grid, so the Assistant
    asks, offering the filter first."""
    cmd = host.parse("peux-tu m'afficher les zones d'huile de la grille")
    assert cmd["intent"] == "threshold" and not cmd["sure"]
    assert cmd["choose_between"] == ["threshold", "highlight"]
    assert [t["path"] for t in cmd["targets"]] == [fluids]
    assert host.choice_label(cmd, "threshold", "fr") == "Ne garder que les mailles « oil » (Fluids)"
    assert host.choice_label(cmd, "highlight", "fr") == "Surligner les mailles « oil » sur toute la grille"


def test_keeping_only_the_oil_cells_filters_on_the_oil_code(host, app, fluids):
    cmd, r = _run(host, "garde que les zones d'huile")
    assert cmd["intent"] == "threshold" and cmd["sure"]
    assert r["ok"] and r["text"].startswith("Fluids de Geogrid : seules les mailles « oil » sont gardées.")
    name = app.isos[(VID, app.p["grid"])].chain[-1]["name"]
    assert app.called("threshold_range")[-1] == ([name, [1.0, 1.0]], VID)


def test_a_value_the_property_does_not_list_is_said(host, app, fluids):
    cmd = host.parse("garde que les zones d'huile")
    cmd["slots"]["category"] = "coal"
    r = host.execute(cmd, "fr")
    assert not r["ok"] and "pas de valeur « coal »" in r["text"]


def test_a_category_value_never_asks_for_bounds(host, fluids):
    cmd = host.parse("affiche moi l'eau de la grille")
    cmd["intent"] = "highlight"                          # the reader's choice
    assert "min|max" not in host.missing(cmd)


def test_the_session_remembers_the_last_command_for_a_sentence_that_refers_back(host, app, fluids):
    """A sentence that refers back reuses the last command's target and value.

    "surligne les zones d'huile" (highlight the oil zones), then "cache le
    reste" (hide the rest), means keeping only the oil cells."""
    cmd, r = _run(host, "surligne les zones d'huile")
    assert r["ok"], r["text"]
    cmd = host.parse("cache le reste")
    assert cmd["intent"] == "threshold" and cmd["sure"]
    assert cmd["slots"]["category"] == "oil" and [t["path"] for t in cmd["targets"]] == [fluids]


def test_hiding_the_oil_keeps_water_and_gas_and_the_undo_puts_back_the_filters(host, app, fluids):
    cmd, r = _run(host, "masque la zone huile de la grille")
    assert cmd["intent"] == "threshold" and cmd["slots"].get("exclude")
    assert r["ok"] and r["text"] == "Fluids de Geogrid : les mailles « oil » sont masquées ; restent : water, gas."
    iso = app.isos[(VID, app.p["grid"])]
    assert [(e["low"], e["high"]) for e in iso.chain] == [(0.0, 0.0), (2.0, 2.0)]
    assert all(e.get("parent_name") is None for e in iso.chain)          # side by side: a union
    host.undo(r["undo"], "fr")
    assert iso.chain == []


def test_a_sentence_with_two_requests_parses_into_a_command_and_the_words_of_its_follow_up(host, app):
    """The follow-up of a sentence is kept as its words, read when its turn comes.

    Read up front, it would not know what the first request showed or kept;
    the panel parses it once the first one has run."""
    cmd = host.parse("montre la porosité de Geogrid et passe en viridis")
    assert cmd["intent"] == "show" and [t["path"] for t in cmd["targets"]] == [app.p["poro"]]
    (nxt,) = cmd["then"]
    assert nxt == "passe en viridis"
    nxt = host.parse(nxt)
    assert nxt["intent"] == "colormap" and nxt["slots"]["preset"] == "Viridis (matplotlib)" and nxt["sure"]


# ------------------------------------------------------------------ the cells the wells go through
def test_the_cells_the_wells_go_through_are_found_from_the_geometry_and_said_per_well(host, app):
    """The cells crossed by the wells come from the geometry, reported per well.

    "surligne les mailles traversées par les puits" (highlight the cells
    the wells go through) works without any blocked wellbore in the data:
    with the wells and the grid in sight, boot's well_cells_where walks
    each trajectory through the grid."""
    _, r = _run(host, "surligne les mailles traversées par les puits")
    assert r["ok"], r["text"]
    p = app.well_cells_payload
    assert p["grid"] == app.p["grid"] and p["trajectories"] == [app.p["traj"]]
    assert p["array"] is None and p["lo"] is None and p["hi"] is None
    eyes = app.state[f"visible_paths__{VID}"]
    assert app.p["traj"] in eyes and app.p["grid"] in eyes
    assert r["text"] == "Mailles traversées par les puits : 55/33-1 (3). 3 mailles surlignées."
    host.undo(r["undo"], "fr")
    assert app.called("node_highlight") == [([], VID)]
    assert app.state[f"visible_paths__{VID}"] == []


def test_the_wells_through_a_zone_read_the_value_s_code_and_count_the_cells_in_it(host, app, fluids):
    _, r = _run(host, "quels puits traversent la zone d'huile ?")
    assert r["ok"], r["text"]
    p = app.well_cells_payload
    assert p["array"] == fluids and p["lo"] == p["hi"] == 1.0 and p["grid"] == app.p["grid"]
    assert fluids in app.state[f"visible_paths__{VID}"]
    assert r["text"] == "1 puits traverse Fluids « oil » : 55/33-1 (1 sur 3 traversées). 1 maille surlignée."


def test_no_well_through_the_zone_is_said_with_what_they_cross(host, app, fluids):
    app.well_cells = {"per": {app.p["traj"]: {"crossed": 3, "in": 0}}, "lit": 0, "total": 10}
    _, r = _run(host, "which wells cross the oil zone", "en")
    assert r["ok"], r["text"]
    assert r["text"] == "No well crosses Fluids “oil”. 55/33-1 stays out of it. 0 cells highlighted."


def test_a_named_well_is_followed_alone_and_a_property_condition_is_the_zone(host, app):
    _, r = _run(host, "highlight the cells where porosity is above 0.2 crossed by the well 55/33-1", "en")
    assert r["ok"], r["text"]
    p = app.well_cells_payload
    assert p["trajectories"] == [app.p["traj"]] and p["array"] == app.p["poro"] and p["lo"] == 0.2
    assert r["text"] == "1 well crosses Total Porosity ≥ 0.2: 55/33-1 (1 of 3 crossed). 1 cell highlighted."


def test_a_failed_well_walk_is_said_and_leaves_the_view_as_it_was(host, app):
    app.well_cells = {"error": "The grid is not loaded."}
    _, r = _run(host, "surligne les mailles traversées par les puits")
    assert not r["ok"] and "The grid is not loaded." in r["text"] and r["undo"] is None
    assert app.state[f"visible_paths__{VID}"] == []


# ------------------------------------------------------------------ "between which values?" names the property
def test_between_which_values_names_the_property_and_its_range(host):
    """Asking for the missing bounds names the property and its data range.

    A bare "between which values?" leaves the reader unsure which
    property the values belong to."""
    cmd = host.parse("surligne la porosité")
    assert "min|max" in host.missing(cmd)
    r = host.ask_missing(cmd, "fr")
    assert r["text"].startswith("Entre quelles valeurs de Total Porosity (de 0 à 0,4) ?"), r["text"]
    assert [c["id"] for c in r["choices"]] == ["cancel"]


def test_between_which_values_of_a_categorical_property_offers_its_values(host, app, fluids):
    cmd = host.parse("surligne Fluids")
    r = host.ask_missing(cmd, "fr")
    assert r["text"] == "Quelles mailles de Fluids ?"
    assert [c["id"] for c in r["choices"]] == ["category:water", "category:oil", "category:gas", "cancel"]
    chosen = host.with_category(cmd, "oil")
    assert host.missing(chosen) == []
    r = host.execute(chosen, "fr")
    assert r["ok"], r["text"]
    assert app.called("highlight_where") == [([1.0, 1.0], VID)]


def test_which_cells_with_nothing_named_offers_the_grids_category_values(host, app, fluids):
    cmd = host.parse("surligne les mailles")
    r = host.ask_missing(cmd, "fr")
    assert r["text"].startswith("Quelles mailles ?")
    assert [c["id"] for c in r["choices"]][:3] == ["category:water", "category:oil", "category:gas"]
    assert r["choices"][1]["label"] == "oil (Fluids)"
    chosen = host.with_category(cmd, "oil")
    assert [t["path"] for t in chosen["targets"]] == [fluids]
    assert host.missing(chosen) == []


def test_the_wells_out_of_the_zone_are_hidden_and_the_undo_shows_them_again(host, app, fluids):
    app.well_cells = {"per": {app.p["traj"]: {"crossed": 3, "in": 0}}, "lit": 0, "total": 10}
    _, r = _run(host, "enlève les puits qui ne passent pas par la zone d'huile")
    assert r["ok"], r["text"]
    assert r["text"].endswith(" 1 puits masqué : 55/33-1.")
    assert app.p["traj"] not in app.state[f"visible_paths__{VID}"]
    host.undo(r["undo"], "fr")
    assert app.state[f"visible_paths__{VID}"] == []
    # A well that crosses stays, and the reply says there is nothing to hide.
    app.well_cells = None
    _, r = _run(host, "enlève les puits qui ne passent pas par la zone d'huile")
    assert r["text"].endswith(" Aucun puits à masquer.") and app.p["traj"] in app.state[f"visible_paths__{VID}"]


def test_a_gesture_that_fills_an_empty_view_resets_the_camera(host, app):
    """A gesture that brings something into an empty view resets the camera.

    In an empty view (for instance a session restored with nothing shown)
    the camera may point away from the data, so a gesture that works would
    still show nothing."""
    _, r = _run(host, "montre la porosité")
    assert r["ok"] and app.called("nav_reset") == [(VID,)]
    # Something already in sight: the camera is left alone.
    _, r = _run(host, "montre la perméabilité horizontale")
    assert r["ok"] and app.called("nav_reset") == [(VID,)]


# ------------------------------------------------------------------ the local AI service (fespp_ia)
class FakeIA:
    """The local AI service as the adapter calls it (ia/llm.LocalIA).

    `command` is the model's command, or None for a call that failed with
    `error`; `status` is what /v1/health says (None: no answer)."""

    def __init__(self, command=None, answer=None, error="", status="ok"):
        self.command_reply, self.answer_reply, self.calls = command, answer, []
        self.error, self.status, self.last_error = error, status, "down"
        self.sent = []          # the keyword arguments of each command call

    def command(self, text, catalogue, objects, lang="fr", **kw):
        self.calls.append(("command", text, [c["name"] for c in catalogue], [o["title"] for o in objects], lang))
        self.sent.append(dict(kw, objects=objects))
        if self.command_reply is None:
            self.last_error = self.error
        return None if self.command_reply is None else dict(self.command_reply)

    def ask(self, question, lang="fr", k=6):
        self.calls.append(("ask", question, lang))
        return self.answer_reply

    def health(self, timeout=5.0):
        self.calls.append(("health", timeout))
        if self.status is None:
            self.last_error = "connection refused"
            return None
        return {"status": self.status}


def test_a_question_goes_to_the_local_ai_and_its_sources_are_rows(app):
    ia = FakeIA(answer={"text": "Un pilier est une ligne selon K. [pillars]",
                        "sources": [{"title": "pillars", "source": "fesapi", "path": "a.h", "score": 0.8}]})
    host = FesppAssistantHost(app.server, ia=ia)
    r = host.answer({"intent": "ask", "slots": {"question": "c'est quoi un pilier ?"}}, "fr")
    assert r["ok"] and r["text"].startswith("Un pilier") and r["rows"] == [["pillars", "fesapi"]]
    assert ia.calls == [("ask", "c'est quoi un pilier ?", "fr")]
    assert host.slow("ask") and not host.slow("show") and host.llm_available()


def test_without_the_service_a_question_is_answered_from_the_glossary(app):
    host = FesppAssistantHost(app.server, ia=None)
    assert not host.llm_available() and host.llm_command("x") is None
    r = host.answer({"intent": "ask", "slots": {"question": "c'est quoi un pilier ?"}}, "fr")
    assert r["ok"] and r["text"].startswith("Pilier (pillar) : ") and "Source : glossaire du réservoir" in r["text"]
    r = host.answer({"intent": "ask", "slots": {"question": "c'est quoi un zorglub ?"}}, "fr")
    assert not r["ok"] and "IA locale" in r["text"] and "FESPP_IA_URL" not in r["text"]
    # the shipped copy never drifts from the corpus's glossary
    root = Path(__file__).resolve().parents[2]
    assert ((root / "ia" / "corpus" / "glossaire-reservoir.md").read_text(encoding="utf-8")
            == (root / "fespp_on_trame" / "assets" / "glossaire-reservoir.md").read_text(encoding="utf-8"))


def test_the_local_ai_s_reading_becomes_a_command_in_the_engine_s_shape(app, fluids):
    ia = FakeIA(command={"intent": "well_cells", "category": "oil", "kind": None, "min": None, "max": None,
                         "objects": ["55/33-1"], "well_filter": "keep_crossing", "question": None, "_seconds": 12.3})
    host = FesppAssistantHost(app.server, ia=ia)
    cmd = host.llm_command("enlève les puits qui ne passent pas par les chenaux à huile", "fr")
    assert cmd["intent"] == "well_cells" and cmd["by"] == "llm" and cmd["sure"] and cmd["seconds"] == 12.3
    assert cmd["slots"]["category"] == "oil" and cmd["slots"]["well_filter"] == "keep_crossing"
    assert [t["title"] for t in cmd["targets"]] == ["Fluids"] and cmd["missing"] == []
    # The well the model listed is not named by the sentence: every well is meant.
    assert [o["title"] for c in cmd["slots"]["objects"] for o in c] == []
    call = ia.calls[0]
    assert call[0] == "command" and "well_cells" in call[2] and "ask" not in call[2] and "Fluids" in call[3]
    r = host.execute(cmd, "fr")
    assert r["ok"], r["text"]
    assert app.well_cells_payload["trajectories"] == [app.p["traj"]]


def test_the_model_is_told_what_it_confuses_but_the_help_keeps_the_short_words(host):
    by = {c["name"]: c for c in host.catalogue_for_llm()}
    assert by["threshold"]["fr"].startswith(catalogue.INTENTS["threshold"]["fr"] + " — ")
    assert "zone de fluide" in by["threshold"]["fr"] and "fluid or facies zone" in by["threshold"]["en"]
    assert "threshold" in by["show"]["fr"] and "threshold" in by["hide"]["en"]
    assert "quelle grille" in by["complain"]["fr"] and "palette" in by["color_range"]["fr"]
    # A French sentence about the blocked wellbores gets the French prompt.
    assert "blocked wellbores" in by["well_cells"]["fr"] and "blocks des puits" in by["well_cells"]["fr"]
    assert by["complain"]["en"].startswith("say the reply was not what you wanted")
    assert "rien ne disparaît" in by["highlight"]["fr"] and "keep_crossing" in by["isolate"]["en"]
    assert by["save_session"]["fr"] == catalogue.INTENTS["save_session"]["fr"]   # no hint: unchanged
    assert by["colormap"]["fr"] == catalogue.INTENTS["colormap"]["fr"]           # said by color_range already
    from fespp_on_trame.ia.llm import LLM_HINTS
    assert set(LLM_HINTS) <= set(catalogue.INTENTS) and "ask" not in by
    _, r = _run(host, "aide")
    texts = [row[1] for row in r["rows"]]
    assert catalogue.INTENTS["threshold"]["fr"] in texts and not any(" — " in t for t in texts)


def test_the_local_ai_s_question_and_nothing_are_read_as_such(app):
    host = FesppAssistantHost(app.server, ia=FakeIA(command={"intent": "ask", "question": "un pilier ?"}))
    assert host.llm_command("un pilier ?")["slots"] == {"question": "un pilier ?"}
    host = FesppAssistantHost(app.server, ia=FakeIA(command={"intent": "unknown"}))
    assert host.llm_command("blabla") is None


# ------------------------------------------------------------------ what the engine reads is a command
@pytest.mark.parametrize("text,intent", [
    ("Annule", "undo"), ("Annule !", "undo"), ("anule", "undo"), ("Aide !", "help"), ("Help!", "help"),
    ("Recadre", "reset_camera"), ("Liste", "list"), ("Sauvegarde", "save_session"),
    ("enlève l'ombrage", "flat_colors")])
def test_a_command_the_engine_reads_is_never_taken_for_gibberish(host, text, intent):
    """A capital, an accent, a punctuation mark or a slip does not make a
    sentence gibberish.

    The engine reads the normalised words, a slip in a verb mended
    ("anule"): what it reads is a command, and what it does not ("xqzt") it
    rejects itself."""
    cmd = host.parse(text)
    assert cmd["intent"] == intent and cmd["sure"], text


# ------------------------------------------------------------------ the statistic asked for leads the reply
@pytest.mark.parametrize("text,lead", [
    ("quelle est la médiane de la porosité ?", "médiane"),
    ("écart-type de la porosité ?", "écart type"),
    ("quel est le Minimum de la porosité ?", "minimum 0,1"),
    ("porosité minimale ?", "minimum 0,1"),
    ("quelle est la porosité moyenne ?", "moyenne 0,2")])
def test_a_statistic_is_found_whatever_its_accents_or_capitals(host, app, monkeypatch, text, lead):
    """The statistic a sentence asks for is the reply's first figure.

    "médiane", "écart-type" or "Minimum" are read in the normalised text,
    as the engine reads them; a statistic not said gives the mean."""
    from fespp_on_trame.engine import property_values
    monkeypatch.setattr(property_values, "values_for", lambda *a, **k: np.array([0.1, 0.2, 0.3, np.nan]))
    _, r = _run(host, text)
    assert r["ok"] and r["text"].startswith(f"Total Porosity de Geogrid : {lead}"), r["text"]


# ------------------------------------------------------------------ the requests of a sentence, read in turn
def _panel(app, host):
    """The real conversation controller (widgets/assistant) on the adapter."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "widgets" / "assistant"))
    from trame_fespp_assistant.controller import AssistantController
    return AssistantController(app.server, host)


def _replies(app):
    return [m for m in app.state["ui_assistant"]["messages"] if m["role"] == "assistant"]


def test_the_second_request_is_read_once_the_first_has_run(host, app):
    """A later request of a sentence is read once the one before has run.

    "filter above 0.2" names no property: read up front, it would ask which
    one; read after "show the porosity", the porosity is the view's active
    property, and the filter runs on it."""
    ctl = _panel(app, host)
    ctl.ask("montre la porosité de Geogrid et filtre au-dessus de 0,2")
    assert [m["level"] for m in _replies(app)] == ["ok", "ok"], [m["text"] for m in _replies(app)]
    name = app.isos[(VID, app.p["grid"])].chain[-1]["name"]
    assert app.called("threshold_range")[-1] == ([name, [0.2, 0.4]], VID)
    assert len(ctl._undo) == 2


def test_the_rest_of_a_sentence_takes_up_the_zone_its_first_request_lit(host, app, fluids):
    """ "…then hide the rest" keeps only the value the first request lit."""
    ctl = _panel(app, host)
    ctl.ask("surligne les zones d'huile puis cache le reste")
    texts = [m["text"] for m in _replies(app)]
    assert texts[-1].startswith("Fluids de Geogrid : seules les mailles « oil » sont gardées."), texts


# ------------------------------------------------------------------ the local AI's reading, checked by the sentence
def _ai_host(app, **command):
    """The adapter with a local AI whose model answers `command`."""
    reply = {"intent": None, "category": None, "kind": None, "min": None, "max": None, "objects": [],
             "well_filter": None, "question": None}
    reply.update(command)
    ia = FakeIA(command=reply)
    return FesppAssistantHost(app.server, ia=ia), ia


@pytest.mark.parametrize("text", ["cache l'huile", "don't show the oil"])
def test_a_zone_the_local_ai_reads_hidden_is_hidden_not_kept(app, fluids, text):
    """A zone the model reads as hidden hides it, the other values kept.

    The model's command has no polarity of its own: without the sentence's
    hiding word, the filter would keep ONLY the zone the reader wanted gone."""
    host, _ = _ai_host(app, intent="threshold", category="oil")
    cmd = host.llm_command(text)
    assert cmd["slots"]["exclude"] is True and cmd["sure"]
    r = host.execute(cmd, "fr")
    assert r["text"] == "Fluids de Geogrid : les mailles « oil » sont masquées ; restent : water, gas."


def test_the_service_s_own_polarity_is_kept_when_the_words_say_none(app, fluids):
    host, _ = _ai_host(app, intent="threshold", category="water", exclude=True)
    assert host.llm_command("sans l'eau")["slots"]["exclude"] is True
    host, _ = _ai_host(app, intent="threshold", category="water", exclude=False)
    assert host.llm_command("sans l'eau")["slots"]["exclude"] is False


def test_a_zone_read_with_no_polarity_from_the_service_asks_hide_or_keep(app, fluids):
    """The service sent no `exclude`: a zone read with a verb the engine's
    rules lack ("planque", "zappe") or with a negation ("sans") is never
    kept alone by default — the reader is asked whether to hide it or keep
    only it, one button each. Words that keep, or a sentence of known words
    none of which hides, still keep."""
    host, _ = _ai_host(app, intent="threshold", category="gas")
    cmd = host.llm_command("planque-moi tout ce qui est gazeux")
    assert cmd["slots"]["exclude"] is None and cmd["missing"] == ["exclude"] and not cmd["sure"]
    q = host.ask_missing(cmd, "fr")
    assert q["text"] == "Masquer les mailles « gas », ou ne garder qu'elles ?"
    assert [(c["id"], c["label"]) for c in q["choices"]] == [
        ("exclude:true", "Masquer les mailles « gas » (Fluids)"),
        ("exclude:false", "Ne garder que les mailles « gas » (Fluids)"), ("cancel", "Annuler")]
    hidden = dict(cmd, slots=dict(cmd["slots"], exclude=True))
    assert host.missing(hidden) == []
    r = host.execute(hidden, "fr")
    assert r["text"] == "Fluids de Geogrid : les mailles « gas » sont masquées ; restent : water, oil."
    for text, polarity in (("ne garde que le gazeux", False), ("the gas cells", False), ("give me the gas zone", False),
                           ("sans le gaz", None), ("zappe-moi le gaz", None)):
        host, _ = _ai_host(app, intent="threshold", category="gas")
        cmd = host.llm_command(text)
        assert cmd["slots"]["exclude"] is polarity, text
        assert cmd["sure"] is (polarity is not None), text


@pytest.mark.parametrize("said,canonical", [
    ("water_saturation", "water saturation"), ("Lithology1", "facies"), ("avg porosity", "porosity"),
    ("Fluids", "fluids"), ("wellbore", None), ("mean", None), ("well_feature_NO_15_9-F-1_ABC", None)])
def test_the_local_ai_s_kind_is_made_canonical(said, canonical):
    assert FesppAssistantHost._canonical_kind(said) == canonical


def test_a_kind_the_local_ai_made_up_finds_nothing_rather_than_failing(app):
    """A title or a made-up word as the model's kind is dropped: the named
    objects then stand alone ("hide the well" never answers "not found")."""
    host, _ = _ai_host(app, intent="hide", kind="wellbore", objects=["55/33-1"])
    cmd = host.llm_command("cache le puits 55/33-1")
    assert cmd["slots"]["kind"] is None and [t["title"] for t in cmd["targets"]] == ["55/33-1"]


def test_a_category_the_sentence_does_not_name_as_a_zone_is_dropped(app, fluids):
    """The model's category is kept only when the sentence names that zone.

    A value it guessed ("oil" for "show the porosity") would replace the
    property asked for; "water sat" is the water saturation, not the water
    zone, whatever the engine took "water" for."""
    host, _ = _ai_host(app, intent="show", category="oil", kind="porosity")
    cmd = host.llm_command("montre la porosité")
    assert cmd["slots"]["category"] is None and [t["path"] for t in host.targets(cmd)] == [app.p["poro"]]
    host, _ = _ai_host(app, intent="threshold", category="water", kind="water_saturation", min=0.3)
    cmd = host.llm_command("water sat above 0.3")
    assert cmd["slots"]["category"] is None and cmd["slots"]["kind"] == "water saturation"
    assert (cmd["slots"]["min"], cmd["slots"]["max"]) == (0.3, None)


def test_the_local_ai_s_objects_are_the_ones_the_sentence_names(host, app):
    """Only the objects the sentence names are kept, matched closely.

    "33-1" is "55/33-1" (the model may shorten a title), an object the model
    copied from the session's list is not named and goes, and two objects
    sharing a title are both kept for the question to ask which."""
    objs = host.objects()
    named = host._named_by(["33-1", "Geogrid"], ["decris", "le", "puits", "33-1"], objs)
    assert [[o["title"] for o in c] for c in named] == [["55/33-1"]]
    twins = [{"path": "/a", "title": "PHIT"}, {"path": "/b", "title": "PHIT"}, {"path": "/c", "title": "NTG"}]
    assert [[o["path"] for o in c] for c in host._named_by(["PHIT"], ["montre", "phit"], twins)] == [["/a", "/b"]]


def test_a_question_on_the_wells_hides_none_of_them(app, fluids):
    """A well filter needs a word that removes or keeps wells: "which wells
    cross the oil?" asks, it never hides the wells asked about."""
    host, _ = _ai_host(app, intent="well_cells", category="oil", well_filter="keep_crossing")
    assert host.llm_command("quels puits traversent la zone d'huile ?")["slots"]["well_filter"] is None
    assert host.llm_command("garde que les puits qui traversent l'huile")["slots"]["well_filter"] == "keep_crossing"


@pytest.mark.parametrize("text,intent,model,bounds", [
    ("les mailles entre 10 et 30 % de porosité", "threshold", {"min": 10, "max": 30}, (0.1, 0.3)),
    ("porosité en dessous de 0,1", "threshold", {"min": 0.1}, (None, 0.1)),
    ("fais ressortir les fortes porosités", "highlight", {"min": 0.2, "max": 1}, (None, None))])
def test_the_bounds_are_read_from_the_sentence_s_numbers(app, text, intent, model, bounds):
    """The bounds come from the sentence's numbers, read by the engine's
    rules: "below" is a maximum, a percent of a fraction is one, and a bound
    the model made up with no number said is never used (it is asked)."""
    host, _ = _ai_host(app, intent=intent, kind="porosity", **model)
    cmd = host.llm_command(text)
    assert (cmd["slots"]["min"], cmd["slots"]["max"]) == bounds
    assert ("min|max" in cmd["missing"]) == (bounds == (None, None))


@pytest.mark.parametrize("model,key,value", [
    ({"intent": "open_panel", "panel": "stats"}, "panel", "stats"),
    ({"intent": "open_panel", "panel": "statistiques"}, "panel", "stats"),
    ({"intent": "colormap", "preset": "inferno"}, "preset", "Inferno (matplotlib)"),
    ({"intent": "colormap", "preset": "Plasma (matplotlib)"}, "preset", "Plasma (matplotlib)"),
    ({"intent": "colormap", "preset": "sunset"}, "preset", None),
    ({"intent": "slice", "axis": "J"}, "axis", "j"),
    ({"intent": "z_scale", "factor": 3}, "factor", 3.0)])
def test_the_service_s_panel_preset_axis_and_factor_fill_what_the_engine_did_not_read(app, model, key, value):
    host, _ = _ai_host(app, **model)
    cmd = host.llm_command("fais le avec le truc")
    assert cmd["slots"][key] == value
    assert (key in cmd["missing"]) == (value is None)


def test_the_engine_s_words_win_over_the_service_s_values(app):
    host, _ = _ai_host(app, intent="colormap", preset="Jet")
    assert host.llm_command("passe en viridis")["slots"]["preset"] == "Viridis (matplotlib)"


def test_showing_the_missing_values_through_the_local_ai_shows_them(app):
    host, _ = _ai_host(app, intent="hide_nan")
    assert host.llm_command("montre les valeurs absentes")["slots"]["on"] is False


def test_what_the_local_ai_is_told(app):
    """The vocabulary of the slots and a reading time go with the sentence;
    the session's objects carry their parent and come ranked."""
    from fespp_on_trame.ia import llm
    from fespp_on_trame.ia.nlu import lexicon
    _load(app, "kh")
    host, ia = _ai_host(app, intent="show", objects=["Geogrid"])
    host.llm_command("montre Geogrid")
    sent = ia.sent[0]
    assert sent["timeout"] == llm.COMMAND_TIMEOUT_S == 90.0
    assert sent["vocab"] == {"kinds": list(lexicon.KINDS), "panels": list(lexicon.PANELS),
                             "presets": list(lexicon.PRESETS)}
    rows = sent["objects"]
    # what is read first, then the grids and the wells, the grid's
    # properties, the surfaces, the wells' logs
    assert [r["title"] for r in rows][:3] == ["Horizontal Permeability", "Geogrid", "55/33-1"]
    assert rows[-1]["title"] in ("GR", "Total Porosity (Original Log)")
    by = {r["title"]: r for r in rows}
    assert by["Total Porosity"]["parent"] == "Geogrid" and by["GR"]["parent"] == "55/33-1"
    assert "parent" not in by["Geogrid"]


def test_what_the_local_ai_is_told_is_read_before_its_call(app):
    """The application is read on the event loop; the call alone, which the
    panel runs in a thread, reads nothing of it."""
    host, ia = _ai_host(app, intent="show", objects=["Geogrid"])
    call = host.llm_prepare("montre Geogrid", "fr")

    def no_read():
        raise AssertionError("the application read from the call")
    host.objects = no_read
    got = call()
    del host.objects
    cmd = host.llm_finish("montre Geogrid", got, "fr")
    assert cmd["intent"] == "show" and [t["path"] for t in cmd["targets"]] == [app.p["grid"]]


def test_a_failed_call_says_why_and_the_service_is_left_alone_for_a_while(app, monkeypatch):
    """A call that failed comes back as an error with its reason, not as "no
    command"; the service is then taken as down until its health is asked
    again, a minute later."""
    import fespp_on_trame.app.assistant_host as mod
    now = [1000.0]
    monkeypatch.setattr(mod.time, "monotonic", lambda: now[0])
    ia = FakeIA(command=None, error="timed out")
    host = FesppAssistantHost(app.server, ia=ia)
    assert host.llm_available() and host.llm_problem() == ""
    got = host.llm_command("fais un truc")
    assert got["intent"] is None and got["error"] == "timed out"
    assert not host.llm_available() and host.llm_problem() == "timed out"
    probes = [c for c in ia.calls if c[0] == "health"]
    now[0] += 61
    assert host.llm_available()
    assert len([c for c in ia.calls if c[0] == "health"]) == len(probes) + 1


@pytest.mark.parametrize("status,why", [("loading", "loading"), (None, "connection refused")])
def test_a_service_down_is_seen_by_its_health_at_most_once_a_minute(app, monkeypatch, status, why):
    import fespp_on_trame.app.assistant_host as mod
    now = [1000.0]
    monkeypatch.setattr(mod.time, "monotonic", lambda: now[0])
    ia = FakeIA(status=status)
    host = FesppAssistantHost(app.server, ia=ia)
    assert not host.llm_available() and host.llm_problem() == why
    now[0] += 30
    assert not host.llm_available()
    assert [c[0] for c in ia.calls] == ["health"]


# ------------------------------------------------------------------ "which values?" names the property
def test_the_wells_through_a_property_with_no_value_ask_which_cells_first(host, app):
    """A zone said without its value is asked before anything runs, with
    the property and its range — never a bare "a value, please"."""
    cmd = host.parse("surligne les mailles de porosité traversées par les puits")
    assert cmd["intent"] == "well_cells" and cmd["missing"] == ["min|max"] and not cmd["sure"]
    q = host.ask_missing(cmd, "fr")
    assert q["text"].startswith("Entre quelles valeurs de Total Porosity (de 0 à 0,4) ?"), q["text"]


def test_a_gesture_without_a_bound_says_which_values_of_what(host, app, fluids):
    by = {o["path"]: o for o in host.objects()}
    poro, fl = by[app.p["poro"]], by[app.p["fluids"]]
    r = host._no_bounds({"intent": "highlight", "slots": {"kind": "porosity"}, "targets": [poro]}, "fr")
    assert not r["ok"] and r["text"].startswith("Entre quelles valeurs de Total Porosity (de 0 à 0,4) ?")
    r = host._no_bounds({"intent": "highlight", "slots": {}, "targets": [fl]}, "en")
    assert r["text"] == "Which cells of Fluids? Values: water, oil, gas."
    # executed without its value, the wells' walk says it the same way
    cmd = {"intent": "well_cells", "slots": {"kind": "porosity"}, "targets": [poro], "text": "x"}
    r = host.execute(cmd, "fr")
    assert not r["ok"] and r["text"].startswith("Entre quelles valeurs de Total Porosity")


# ------------------------------------------------------------------ a hidden zone's polarity, kept by the session
def test_and_the_gas_after_hiding_the_oil_hides_the_gas(host, app, fluids):
    """ "And the gas?" after "hide the oil zone" hides the gas too: the
    session keeps the polarity of its last command, and what is hidden stays
    hidden until it is shown — the oil does not come back. The values
    already hidden are read from the view when the gesture runs. A sentence
    that says its own gesture overrides it."""
    _, r = _run(host, "masque la zone huile de la grille")
    assert r["ok"]
    cmd = host.parse("et pour le gaz ?")
    assert cmd["intent"] == "threshold" and cmd["slots"]["exclude"]
    assert cmd["slots"]["categories"] == ["gas"] and cmd["slots"]["values_mode"] == "add"
    r = host.execute(cmd, "fr")
    assert r["text"] == "Fluids de Geogrid : les mailles « oil » et « gas » sont masquées ; restent : water."
    assert [(e["low"], e["high"]) for e in app.isos[(VID, app.p["grid"])].chain] == [(0.0, 0.0)]
    cmd = host.parse("garde que le gaz")
    assert not cmd["slots"].get("exclude") and cmd["slots"]["categories"] == ["gas"]
    assert "values_mode" not in cmd["slots"]


# ------------------------------------------------------------------ several values of a category
def _values_cmd(host, app, intent, values, exclude=False):
    fl = {o["path"]: o for o in host.objects()}[app.p["fluids"]]
    return {"intent": intent, "text": "x", "targets": [fl],
            "slots": {"category": values[0], "categories": list(values), "exclude": exclude, "objects": [[fl]]}}


def test_keeping_two_values_apart_in_the_table_filters_on_both(host, app, fluids):
    r = host.execute(_values_cmd(host, app, "threshold", ["water", "gas"]), "fr")
    assert r["ok"] and r["text"] == "Fluids de Geogrid : seules les mailles « water » et « gas » sont gardées."
    iso = app.isos[(VID, app.p["grid"])]
    assert [(e["low"], e["high"]) for e in iso.chain] == [(0.0, 0.0), (2.0, 2.0)]
    host.undo(r["undo"], "fr")
    assert iso.chain == []


def test_keeping_two_values_next_to_each_other_is_one_filter(host, app, fluids):
    r = host.execute(_values_cmd(host, app, "threshold", ["oil", "gas"]), "en")
    assert r["ok"] and r["text"] == "Geogrid Fluids: only the “oil” and “gas” cells are kept."
    name = app.isos[(VID, app.p["grid"])].chain[-1]["name"]
    assert app.called("threshold_range")[-1] == ([name, [1.0, 2.0]], VID)


def test_hiding_two_values_keeps_the_rest(host, app, fluids):
    r = host.execute(_values_cmd(host, app, "threshold", ["water", "gas"], exclude=True), "fr")
    assert r["ok"] and r["text"] == ("Fluids de Geogrid : les mailles « water » et « gas » sont masquées ;"
                                     " restent : oil.")
    assert [(e["low"], e["high"]) for e in app.isos[(VID, app.p["grid"])].chain] == [(1.0, 1.0)]


def test_highlighting_values_lights_one_run_of_codes(host, app, fluids):
    r = host.execute(_values_cmd(host, app, "highlight", ["oil", "gas"]), "fr")
    assert r["ok"] and app.called("highlight_where") == [([1.0, 2.0], VID)]
    assert r["text"].endswith(": Fluids « oil » et « gas ».")
    r = host.execute(_values_cmd(host, app, "highlight", ["water", "gas"]), "fr")
    assert not r["ok"] and "une suite de valeurs à la fois" in r["text"]
    assert len(app.called("highlight_where")) == 1


def test_the_buttons_and_the_values_said_name_every_value(host, app, fluids):
    cmd = _values_cmd(host, app, "threshold", ["water", "gas"])
    assert host.choice_label(cmd, "threshold", "fr") == "Ne garder que les mailles « water » et « gas » (Fluids)"
    cmd["slots"]["exclude"] = True
    assert host.choice_label(cmd, "threshold", "en") == "Hide the “water” and “gas” cells (Fluids)"
    # a value chosen by a button, or kept by a correction, replaces the list
    cmd["slots"]["category"] = "oil"
    assert host._values(cmd) == ["oil"]


def test_values_filtered_side_by_side_still_pass_the_grid_s_other_filters(host, app, fluids):
    """The entries of a filter on values chain under the grid's last filter.

    As new roots they would join the porosity filter's cells (a union) and
    keep more than the reply says; under it, both conditions hold."""
    _run(host, "filtre la porosité au-dessus de 0,2")
    iso = app.isos[(VID, app.p["grid"])]
    poro = iso.chain[0]["name"]
    _, r = _run(host, "masque la zone huile de la grille")
    note = " Les autres filtres de la grille s'appliquent aussi (Total Porosity)."
    assert r["ok"] and r["text"].endswith(note), r["text"]
    made = [e for e in iso.chain if e["name"] != poro]
    assert [(e["low"], e["high"], e["parent_name"]) for e in made] == [(0.0, 0.0, poro), (2.0, 2.0, poro)]
    host.undo(r["undo"], "fr")
    assert [e["name"] for e in iso.chain] == [poro]


def test_the_client_sends_the_vocabulary_and_waits_a_command_s_time(monkeypatch):
    """ia/llm.LocalIA on the wire: /v1/command carries the slots' vocabulary
    (an old service ignores it) and the timeout the call is given; its own
    is a question's."""
    import io
    import json
    from fespp_on_trame.ia import llm
    seen = []

    class Reply(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(req, timeout=None):
        seen.append((json.loads(req.data.decode("utf-8")), timeout))
        return Reply(json.dumps({"command": {"intent": "show"}, "seconds": 1.0}).encode("utf-8"))
    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    ia = llm.LocalIA("http://x")
    assert ia.command("montre la poro", [{"name": "show"}], [], "fr", timeout=llm.COMMAND_TIMEOUT_S)["intent"] == "show"
    ia.command("montre la poro", [{"name": "show"}], [], "fr", vocab={"kinds": ["porosity"]})
    (body, timeout), (body2, timeout2) = seen
    assert body["vocab"] == llm.vocabulary() and "porosity" in body["vocab"]["kinds"]
    assert "Viridis (matplotlib)" in body["vocab"]["presets"] and "stats" in body["vocab"]["panels"]
    assert timeout == 90.0 and timeout2 == llm.TIMEOUT_S
    assert body2["vocab"] == {"kinds": ["porosity"]}


def test_a_correction_naming_the_values_again_keeps_hiding_them(host, app, fluids):
    """ "I said water and gas" after hiding the oil hides them: the
    correction redoes the last command with its polarity — it never keeps
    only the values the reader wanted gone."""
    _run(host, "masque la zone huile de la grille")
    cmd = host.parse("J'avais dit eau et gaz")
    assert cmd["intent"] == "threshold" and cmd["slots"]["exclude"]
    r = host.execute(cmd, "fr")
    assert r["ok"] and "« water »" in r["text"] and "sont masquées" in r["text"], r["text"]


def test_a_zone_said_in_a_derived_form_is_the_local_ai_s_to_name(app, fluids):
    """The local AI is reached for the words the lexicon lacks: "ces trucs
    huileux" names the oil, and getting rid of them hides the oil zone."""
    host, _ = _ai_host(app, intent="threshold", category="oil")
    cmd = host.llm_command("vire moi ces trucs huileux")
    assert cmd["slots"]["category"] == "oil" and cmd["slots"]["exclude"] is True and cmd["sure"]


# ------------------------------------------------------------------ a value asked to be seen is seen
def _hid_the_oil(host):
    """The session's memory right after "hide the oil zone"."""
    host._context = {"intent": "threshold", "category": "oil", "categories": ["oil"], "exclude": True,
                     "kind": None, "targets": []}


@pytest.mark.parametrize("text", ["non, je voulais voir l'huile", "je veux voir le gaz", "remets l'huile",
                                  "no, I wanted to see the oil", "put the gas back", "show the gas",
                                  "ramène l'huile", "rétablis l'huile", "restaure l'huile", "restore the oil",
                                  "je veux retrouver l'huile", "je veux ravoir l'huile"])
def test_a_sentence_that_says_its_showing_gesture_never_takes_up_the_hiding(host, text):
    """After "hide the oil zone", a sentence that asks to see, show or put
    back a value is read as it says it: the last command's hiding is never
    added to it by the adapter, nor kept when the engine took it from that
    command alone."""
    _hid_the_oil(host)
    for taken_by_the_engine in (False, True):
        sl = {"category": "oil", "categories": ["oil"], "repeat": True}
        if taken_by_the_engine:
            sl["exclude"] = True
        cmd = {"intent": "threshold", "text": text, "slots": sl}
        host._take_up_polarity(cmd)
        assert not cmd["slots"].get("exclude"), (text, taken_by_the_engine)


def test_a_verbless_repeat_takes_up_the_hiding_and_a_hiding_said_keeps_it(host):
    _hid_the_oil(host)
    for text in ("et pour le gaz ?", "le gaz aussi", "the water now"):
        cmd = {"intent": "threshold", "text": text, "slots": {"category": "gas", "categories": ["gas"], "repeat": True}}
        host._take_up_polarity(cmd)
        assert cmd["slots"]["exclude"] is True, text
    cmd = {"intent": "threshold", "text": "je ne veux plus voir le gaz",
           "slots": {"category": "gas", "categories": ["gas"], "exclude": True}}
    host._take_up_polarity(cmd)
    assert cmd["slots"]["exclude"] is True


@pytest.mark.parametrize("text,lang,kept", [("non, je voulais voir l'huile", "fr", (1.0, 1.0)),
                                            ("no, I wanted to see the oil", "en", (1.0, 1.0)),
                                            ("je veux voir le gaz", "fr", (2.0, 2.0))])
def test_the_value_asked_to_be_seen_after_a_hiding_is_what_the_filter_shows(host, app, fluids, text, lang, kept):
    """End to end after "hide the oil zone": the value asked for is shown —
    never hidden again, and never in a union with the values the hiding
    kept."""
    _run(host, "masque la zone huile de la grille")
    cmd, r = _run(host, text, lang)
    assert cmd["intent"] == "threshold" and not cmd["slots"].get("exclude"), cmd["slots"]
    assert r["ok"], r["text"]
    assert [(e["low"], e["high"]) for e in app.isos[(VID, app.p["grid"])].chain] == [kept]


# ------------------------------------------------------------------ more values in a later request add up
@pytest.mark.parametrize("text,lang,first,kept,said", [
    ("masque la zone huile de la grille puis le gaz", "fr", [(0.0, 0.0), (2.0, 2.0)], [(0.0, 0.0)],
     "Fluids de Geogrid : les mailles « oil » et « gas » sont masquées ; restent : water."),
    ("cache l'huile puis l'eau", "fr", [(0.0, 0.0), (2.0, 2.0)], [(2.0, 2.0)],
     "Fluids de Geogrid : les mailles « oil » et « water » sont masquées ; restent : gas."),
    ("garde l'huile puis le gaz", "fr", [(1.0, 1.0)], [(1.0, 2.0)],
     "Fluids de Geogrid : seules les mailles « oil » et « gas » sont gardées."),
    ("hide the oil zone then the gas", "en", [(0.0, 0.0), (2.0, 2.0)], [(0.0, 0.0)],
     "Geogrid Fluids: the “oil” and “gas” cells are hidden; left: water.")])
def test_a_later_request_naming_another_value_adds_it_to_the_first(host, app, fluids, text, lang, first, kept, said):
    """ "Hide the oil zone then the gas" asks for both: the later request
    adds its value to the one just filtered — the oil never comes back —
    and its undo puts back what the first request did."""
    ctl = _panel(app, host)
    ctl.ask(text)
    replies = _replies(app)
    assert [m["level"] for m in replies] == ["ok", "ok"], [m["text"] for m in replies]
    assert replies[-1]["text"] == said
    iso = app.isos[(VID, app.p["grid"])]
    assert [(e["low"], e["high"]) for e in iso.chain] == kept
    ctl.undo()
    assert [(e["low"], e["high"]) for e in iso.chain] == first


def test_a_later_highlight_naming_another_value_lights_both(host, app, fluids):
    ctl = _panel(app, host)
    ctl.ask("surligne l'eau puis l'huile")
    assert [a[0] for a in app.called("highlight_where")] == [[0.0, 0.0], [0.0, 1.0]]
    assert _replies(app)[-1]["text"].endswith(": Fluids « water » et « oil ».")


def test_after_a_keep_a_sentence_of_its_own_is_about_its_own_value(host, app, fluids):
    """Across sentences only a hiding adds up: after a keep, "and the gas?"
    keeps the gas."""
    _run(host, "garde que les zones d'huile")
    cmd, r = _run(host, "et le gaz ?")
    assert cmd["slots"]["categories"] == ["gas"] and not cmd["slots"].get("exclude") and r["ok"]
    assert [(e["low"], e["high"]) for e in app.isos[(VID, app.p["grid"])].chain] == [(2.0, 2.0)]


def test_a_later_request_that_says_only_replaces_the_values(host, app, fluids):
    ctl = _panel(app, host)
    ctl.ask("garde l'huile puis garde que le gaz")
    assert [(e["low"], e["high"]) for e in app.isos[(VID, app.p["grid"])].chain] == [(2.0, 2.0)]


# ------------------------------------------------------------------ an undo puts the chain back as it was
def _shape(app):
    """The grid's chain as (array, its parent's array, low, high): the
    names are regenerated by an undo."""
    chain = app.isos[(VID, app.p["grid"])].chain
    by = {e["name"]: e["array"] for e in chain}
    return sorted((e["array"], by.get(e["parent_name"]) if e["parent_name"] else None, e["low"], e["high"])
                  for e in chain)


def test_undoing_a_filter_on_values_chained_under_another_puts_the_chain_back_as_it_was(host, app, fluids):
    """The entries a filter on values replaced come back under their
    parent: as roots they would join the porosity filter's cells (a union)
    and show more than before the gesture."""
    _run(host, "filtre la porosité au-dessus de 0,2")
    _run(host, "masque la zone huile de la grille")
    before = _shape(app)
    assert before == [("Fluids", PORO_VTK, 0.0, 0.0), ("Fluids", PORO_VTK, 2.0, 2.0), (PORO_VTK, None, 0.2, 0.4)]
    _, r = _run(host, "masque la zone eau de la grille")
    assert r["ok"] and _shape(app) != before
    host.undo(r["undo"], "fr")
    assert _shape(app) == before


def test_an_undo_takes_back_its_gesture_only_and_a_filter_taken_off_since_stays_off(host, app, fluids):
    """The undo of a filter gesture takes back what the gesture changed and
    only that: a filter taken off in the Thresholds card since stays off,
    the values the gesture replaced come back under their own parent —
    never an entry put back under another, nor a new root whose cells
    would join the others' (a union)."""
    _run(host, "filtre la porosité au-dessus de 0,2")
    _run(host, "masque la zone huile de la grille")
    _run(host, "filtre le net sur brut au-dessus de 0,1")
    ntg = make_valid_vtk_name("Net-to-Gross Ratio (PEM)")
    assert _shape(app) == [("Fluids", ntg, 0.0, 0.0), ("Fluids", ntg, 2.0, 2.0), (ntg, PORO_VTK, 0.1, 0.4),
                           (PORO_VTK, None, 0.2, 0.4)]
    _, r = _run(host, "masque la zone eau de la grille")
    iso = app.isos[(VID, app.p["grid"])]
    app._threshold_remove(next(e["name"] for e in iso.chain if e["array"] == PORO_VTK), VID)
    said = host.undo(r["undo"], "fr")
    assert said["ok"] and said["text"] == "Annulé : « filtrer par valeur » Fluids de Geogrid.", said["text"]
    assert _shape(app) == [("Fluids", ntg, 0.0, 0.0), ("Fluids", ntg, 2.0, 2.0), (ntg, None, 0.1, 0.4)]


# ------------------------------------------------------------------ a percent, a bound past the data
def test_a_percent_on_the_fraction_just_shown_is_made_a_fraction(host, app):
    """ "…and filter above 20 %" on the porosity just shown is 0.2: the
    engine makes a percent a fraction when the sentence names the kind,
    the adapter when the property comes from the view — for a filter, a
    highlight and the colour range."""
    ctl = _panel(app, host)
    ctl.ask("montre la porosité et filtre au-dessus de 20 %")
    name = app.isos[(VID, app.p["grid"])].chain[-1]["name"]
    assert app.called("threshold_range")[-1] == ([name, [0.2, 0.4]], VID), [m["text"] for m in _replies(app)]
    _, r = _run(host, "surligne au-dessus de 30 %")
    assert r["ok"] and app.called("highlight_where")[-1] == ([0.3, None], VID)
    _, r = _run(host, "couleurs de 10 à 30 %")
    assert r["ok"] and app.called("cmap_range")[-1] == ([0.1, 0.3], VID)


def test_a_bound_past_the_data_s_range_is_said_never_swapped_into_another_range(host, app):
    """A bound past the other end of the data ("above 20" on a porosity of
    0 to 0.4) would keep nothing: the reply gives the range, nothing is set,
    and the bounds are never swapped into a filter from 0.4 to 20."""
    _run(host, "montre la porosité")
    _, r = _run(host, "filtre au-dessus de 20")
    assert not r["ok"] and r["undo"] is None
    assert r["text"] == "Total Porosity de Geogrid va de 0 à 0,4 : au-dessus de 20, aucune maille ne resterait."
    assert app.isos[(VID, app.p["grid"])].chain == []
    _, r = _run(host, "surligne au-dessus de 150")
    assert not r["ok"] and r["text"].startswith("Total Porosity de Geogrid va de 0 à 0,4 : au-dessus de 150,")
    assert app.called("highlight_where") == []
    _, r = _run(host, "fixe la plage de couleurs au-dessus de 5")
    assert not r["ok"] and r["text"].startswith("Les valeurs de Total Porosity vont de 0 à 0,4 : au-dessus de 5,")
    assert app.called("cmap_range") == []


# ------------------------------------------------------------------ several entries on one property
def test_keeping_one_value_where_the_property_holds_several_entries_puts_one_filter(host, app, fluids):
    """After "hide the oil zone" (two entries side by side: water, gas),
    "keep only the gas" is one filter in their place — re-ranging one of
    them would leave the water shown while the reply says only the gas is
    kept; its undo puts both back."""
    _run(host, "masque la zone huile de la grille")
    _, r = _run(host, "garde que les zones de gaz")
    assert r["text"] == "Fluids de Geogrid : seules les mailles « gas » sont gardées."
    iso = app.isos[(VID, app.p["grid"])]
    assert [(e["low"], e["high"]) for e in iso.chain] == [(2.0, 2.0)]
    host.undo(r["undo"], "fr")
    assert [(e["low"], e["high"]) for e in iso.chain] == [(0.0, 0.0), (2.0, 2.0)]


def test_a_range_on_a_property_with_entries_side_by_side_is_one_filter(host, app):
    _run(host, "filtre la porosité au-dessus de 0,2")
    iso = app.isos[(VID, app.p["grid"])]
    app._threshold_add([PORO_VTK, None], VID)            # a second one side by side (the Thresholds card)
    _, r = _run(host, "filtre la porosité au-dessus de 0,3")
    assert r["ok"] and r["text"] == "Total Porosity de Geogrid : mailles gardées de 0,3 à 0,4.", r["text"]
    assert [(e["array"], e["low"], e["high"]) for e in iso.chain] == [(PORO_VTK, 0.3, 0.4)]
    host.undo(r["undo"], "fr")
    assert sorted((e["low"], e["high"]) for e in iso.chain) == [(0.0, 0.4), (0.2, 0.4)]


# ------------------------------------------------------------------ the local AI's failures, in words
def test_the_local_ai_s_failures_are_said_in_the_reader_s_words(app):
    """Why a call failed or the service is out is said in words — a
    timeout, a refused connection, a full queue, a model loading — never as
    the client's raw English; a reason it does not know comes as it is."""
    from fespp_on_trame.ia import llm
    host = FesppAssistantHost(app.server, ia=FakeIA(command=None, error="<urlopen error timed out>"))
    assert host.llm_wait_s == llm.COMMAND_TIMEOUT_S
    refused = ("connexion refusée, le service n'est pas lancé", "connection refused, the service is not running")
    for raw, fr, en in (
            ("<urlopen error timed out>", "délai d'attente dépassé", "it took too long"),
            ("<urlopen error [WinError 10061] No connection could be made because the target machine actively"
             " refused it>",) + refused,
            ("<urlopen error [Errno 111] Connection refused>",) + refused,
            ("503 busy: every slot is taken, try again", "le service est occupé, sa file d'attente est pleine",
             "the service is busy, its queue is full"),
            ("503 Service Unavailable", "le service est indisponible pour l'instant",
             "the service is unavailable for now"),
            ("loading", "le modèle est encore en chargement", "the model is still loading")):
        assert (host.llm_reason(raw, "fr"), host.llm_reason(raw, "en")) == (fr, en), raw
    assert host.llm_reason("a reason never seen", "fr") == "a reason never seen"
    ctl = _panel(app, host)
    ctl.ask("xqzt wblorp")
    assert _replies(app)[-1]["text"].startswith(
        "L'IA locale n'a pas répondu (délai d'attente dépassé) : je n'ai pas compris la phrase.")
    host = FesppAssistantHost(app.server, ia=FakeIA(status="loading"))
    ctl = _panel(app, host)
    ctl.ask("xqzt wblorp")
    assert "(L'IA locale ne répond pas : le modèle est encore en chargement.)" in _replies(app)[-1]["text"]
    ia = FakeIA(answer=None)
    ia.last_error = "<urlopen error timed out>"
    r = FesppAssistantHost(app.server, ia=ia).answer({"intent": "ask", "slots": {"question": "un pilier ?"}}, "fr")
    assert r["ok"] and r["text"].startswith("Pilier (pillar) : ")
    assert r["text"].endswith("(L'IA locale n'a pas répondu : délai d'attente dépassé.)")


def test_the_client_keeps_the_service_s_reason_for_an_http_error(monkeypatch):
    """A full queue and a model that does not answer are both a 503: the
    client keeps the service's own detail, which says which."""
    import io
    import json
    import urllib.error
    from fespp_on_trame.ia import llm

    def urlopen(req, timeout=None):
        body = io.BytesIO(json.dumps({"detail": "busy: every slot is taken, try again"}).encode("utf-8"))
        raise urllib.error.HTTPError(req.full_url, 503, "Service Unavailable", {}, body)
    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    ia = llm.LocalIA("http://x")
    assert ia.command("montre la poro", [{"name": "show"}], [], "fr") is None
    assert ia.last_error == "503 busy: every slot is taken, try again"
    assert llm.reason_words(ia.last_error, "fr") == "le service est occupé, sa file d'attente est pleine"


# ------------------------------------------------------------------ the true fallback: what only the model reads
def test_the_local_ai_s_bounds_are_kept_when_the_engine_read_nothing_of_the_sentence(app):
    """A number in words ("au-delà de vingt pour cent") is the model's alone
    to read: its bound is kept when the engine read nothing of the sentence
    — a fraction kind's percent made one, as the engine does."""
    host, _ = _ai_host(app, intent="threshold", kind="porosity", min=20)
    cmd = host.llm_command("garde les cellules poreuses au-delà de vingt pour cent")
    assert (cmd["slots"]["min"], cmd["slots"]["max"]) == (0.2, None) and cmd["sure"], cmd["slots"]
    r = host.execute(cmd, "fr")
    assert r["ok"] and r["text"].startswith("Total Porosity de Geogrid : mailles gardées de 0,2 à 0,4."), r["text"]
    # the kind not said: the percent is made a fraction on the property in view
    host, _ = _ai_host(app, intent="threshold", min=30)
    cmd = host.llm_command("garde au-delà de trente pour cent")
    assert cmd["slots"]["min"] == 30 and cmd["slots"]["percent"]
    r = host.execute(cmd, "fr")
    assert r["ok"] and r["text"].startswith("Total Porosity de Geogrid : mailles gardées de 0,3 à 0,4."), r["text"]


def test_a_value_the_local_ai_read_in_words_the_lexicon_lacks_is_offered_first(app, fluids):
    """The engine read nothing, the model read the gas — a value of the
    session the sentence does not say with the lexicon's words. It is
    never taken unasked: it comes first among the values offered, the
    hiding the model read kept for the click."""
    host, _ = _ai_host(app, intent="threshold", category="gas", exclude=True)
    cmd = host.llm_command("planque le méthane")
    assert cmd["slots"]["category"] is None and cmd["missing"] == ["min|max"]
    assert [t["path"] for t in cmd["targets"]] == [fluids]
    q = host.ask_missing(cmd, "fr")
    assert q["text"] == "Quelles mailles de Fluids masquer ?"
    assert [c["id"] for c in q["choices"]] == ["category:gas", "category:water", "category:oil", "cancel"]
    chosen = host.with_category(cmd, "gas")
    assert host.missing(chosen) == []
    r = host.execute(chosen, "fr")
    assert r["text"] == "Fluids de Geogrid : les mailles « gas » sont masquées ; restent : water, oil."


def test_a_hiding_verb_said_not_leaves_the_polarity_to_the_service(app, fluids):
    """ "Don't hide the oil": the hiding verb is said not, so the hiding a
    word list reads in it is no reading — the service's polarity is, and
    without one the reader is asked."""
    for text in ("ne cache pas les trucs huileux", "don't hide the oily stuff", "sans cacher les trucs huileux"):
        host, _ = _ai_host(app, intent="threshold", category="oil", exclude=False)
        assert host.llm_command(text)["slots"]["exclude"] is False, text
        host, _ = _ai_host(app, intent="threshold", category="oil")
        assert host.llm_command(text)["slots"]["exclude"] is None, text


def test_a_zone_in_words_the_lexicon_lacks_with_no_polarity_is_asked_then_hidden(app, fluids):
    """Through the panel: the value offered first, then hide or keep (the
    service said no polarity), and the reader's two clicks hide the water."""
    host, _ = _ai_host(app, intent="threshold", category="water")
    ctl = _panel(app, host)
    ctl.ask("zappe la flotte")
    last = _replies(app)[-1]
    assert last["text"] == "Quelles mailles de Fluids ?" and last["choices"][0]["id"] == "category:water"
    ctl.choose("category:water")
    last = _replies(app)[-1]
    assert last["text"] == "Masquer les mailles « water », ou ne garder qu'elles ?"
    ctl.choose("exclude:true")
    assert _replies(app)[-1]["text"] == "Fluids de Geogrid : les mailles « water » sont masquées ; restent : oil, gas."


# ------------------------------------------------------------------ what a filter hides is read from the view
def _kept_ranges(app):
    """The ranges of the grid's filter entries, in the chain's order."""
    iso = app.isos.get((VID, app.p["grid"]))
    return [] if iso is None else [(e["low"], e["high"]) for e in iso.chain]


@pytest.mark.parametrize("between", ["UNDO", "annule", "enlève les filtres"])
@pytest.mark.parametrize("later", ["masque le gaz", "et le gaz ?"])
def test_a_hiding_after_an_undo_or_the_filters_taken_off_hides_its_own_value_only(host, app, fluids, between, later):
    """What a filter already hides is read from the view when the gesture
    runs: after "hide the oil zone" taken back (the Undo button, "annule")
    or the filters taken off, hiding the gas hides the gas alone — the oil
    the reader just put back is never hidden again."""
    ctl = _panel(app, host)
    ctl.ask("masque la zone huile de la grille")
    if between == "UNDO":
        ctl.undo()
    else:
        ctl.ask(between)
    ctl.ask(later)
    assert _replies(app)[-1]["text"] == "Fluids de Geogrid : les mailles « gas » sont masquées ; restent : water, oil."
    assert _kept_ranges(app) == [(0.0, 1.0)]


@pytest.mark.parametrize("text", ["cache l'huile puis annule puis cache le gaz",
                                  "hide the oil then undo then hide the gas",
                                  "masque l'huile puis enlève les filtres puis masque le gaz"])
def test_in_one_sentence_a_value_undone_or_unfiltered_is_not_hidden_again(host, app, fluids, text):
    ctl = _panel(app, host)
    ctl.ask(text)
    assert _kept_ranges(app) == [(0.0, 1.0)], [m["text"] for m in _replies(app)]


@pytest.mark.parametrize("first,text,lang", [
    ("masque la zone huile de la grille", "en fait le gaz", "fr"),
    ("masque la zone huile de la grille", "finalement le gaz", "fr"),
    ("masque la zone huile de la grille", "oups, le gaz", "fr"),
    ("masque la zone huile de la grille", "pardon, le gaz", "fr"),
    ("masque la zone huile de la grille", "je me suis trompé, le gaz", "fr"),
    ("masque la zone huile de la grille", "erreur, c'est le gaz", "fr"),
    ("hide the oil zone of the grid", "actually the gas", "en"),
    ("hide the oil zone of the grid", "sorry, the gas", "en"),
    ("hide the oil zone of the grid", "my bad, the gas", "en"),
    ("hide the oil zone of the grid", "oops, the gas", "en")])
def test_a_correction_replaces_the_value_it_corrects(host, app, fluids, first, text, lang):
    """A correction said with its own words ("en fait", "oups", "sorry",
    "my bad"…) puts its value in place of the one it corrects: the oil
    comes back, the gas is hidden — it never adds to it."""
    _run(host, first, lang)
    cmd, r = _run(host, text, lang)
    assert cmd["slots"].get("values_mode") == "correct", cmd["slots"]
    assert r["ok"] and _kept_ranges(app) == [(0.0, 1.0)], r["text"]


def test_a_correction_takes_back_only_the_value_the_last_sentence_named(host, app, fluids):
    """ "Hide the water", "hide the oil", "actually the gas": the gas takes
    the oil's place and the water stays hidden — the correction is of the
    last sentence, not of everything hidden before it."""
    _run(host, "masque la zone eau de la grille")
    _run(host, "masque la zone huile de la grille")
    _, r = _run(host, "en fait le gaz")
    assert r["ok"], r["text"]
    assert r["text"] == "Fluids de Geogrid : les mailles « water » et « gas » sont masquées ; restent : oil."
    assert _kept_ranges(app) == [(1.0, 1.0)]


@pytest.mark.parametrize("text,lang", [("je ne veux pas voir le gaz", "fr"),
                                       ("je ne veux pas voir le gaz non plus", "fr"),
                                       ("ne montre pas le gaz", "fr"), ("do not show the gas", "en"),
                                       ("I do not want to see the gas either", "en"),
                                       ("don't show the gas", "en")])
def test_a_hiding_said_with_a_showing_verb_said_not_adds_up(host, app, fluids, text, lang):
    """A showing verb said not is a hiding, whatever the words: after "hide
    the oil zone", "je ne veux pas voir le gaz" or "do not show the gas"
    hides the gas too — never a correction that brings the oil back."""
    _run(host, "masque la zone huile de la grille", lang)
    _, r = _run(host, text, lang)
    assert r["ok"] and _kept_ranges(app) == [(0.0, 0.0)], r["text"]


@pytest.mark.parametrize("text", ["cache l'huile puis ne montre pas le gaz",
                                  "cache l'huile puis je ne veux pas voir le gaz",
                                  "hide the oil then do not show the gas",
                                  "hide the oil then I do not want to see the gas either"])
def test_a_later_request_hiding_with_a_showing_verb_said_not_adds_up(host, app, fluids, text):
    ctl = _panel(app, host)
    ctl.ask(text)
    assert _kept_ranges(app) == [(0.0, 0.0)], [m["text"] for m in _replies(app)]


@pytest.mark.parametrize("text,kept", [("masque l'huile puis surligne le gaz puis cache l'eau", [(2.0, 2.0)]),
                                       ("masque l'huile puis montre la porosité puis masque le gaz", [(0.0, 0.0)]),
                                       ("hide the oil, then highlight the gas, then hide the water", [(2.0, 2.0)])])
def test_a_gesture_in_between_never_brings_a_hidden_value_back(host, app, fluids, text, kept):
    """In one sentence, a highlight or a show between two hidings: the
    second hiding adds to what the filter hides — the oil stays hidden."""
    ctl = _panel(app, host)
    ctl.ask(text)
    assert _kept_ranges(app) == kept, [m["text"] for m in _replies(app)]


def test_after_a_keep_a_hiding_hides_one_more_value_never_shows_another(host, app, fluids):
    """ "Keep the water and gas zones", then "hide the gas zone": the water
    alone stays — what the keep hid (the oil) is never shown by a hiding."""
    _run(host, "garde les zones eau et gaz de la grille")
    assert _kept_ranges(app) == [(0.0, 0.0), (2.0, 2.0)]
    _, r = _run(host, "masque la zone gaz de la grille")
    assert r["ok"] and _kept_ranges(app) == [(0.0, 0.0)], r["text"]


def test_hiding_a_value_hidden_already_changes_nothing_and_says_so(host, app, fluids):
    _run(host, "masque la zone huile de la grille")
    n = len(app.calls)
    _, r = _run(host, "masque l'huile")
    assert r["ok"] and r["undo"] is None
    assert r["text"] == "Fluids de Geogrid : les mailles « oil » sont déjà masquées ; restent : water, gas."
    assert not [c for c, _ in app.calls[n:] if c.startswith("threshold_")]


def test_a_highlight_after_its_undo_lights_its_own_value_only(host, app, fluids):
    """ "Highlight the water then undo then highlight the oil": the water's
    highlight was taken back, the oil is lit alone."""
    ctl = _panel(app, host)
    ctl.ask("surligne l'eau puis annule puis surligne l'huile")
    assert app.called("highlight_where")[-1] == ([1.0, 1.0], VID), [m["text"] for m in _replies(app)]


def test_the_local_ai_s_hiding_adds_up_as_the_engine_s_does(app, fluids):
    """The values the local AI reads meet the filter's as the engine's
    reading would: its hiding of the gas, after the oil was hidden, hides
    both."""
    host, _ = _ai_host(app, intent="threshold", category="gas", exclude=True)
    _run(host, "masque la zone huile de la grille")
    cmd = host.llm_command("planque aussi le gaz")
    assert cmd["slots"]["values_mode"] == "add" and cmd["sure"], cmd["slots"]
    r = host.execute(cmd, "fr")
    assert r["ok"] and _kept_ranges(app) == [(0.0, 0.0)], r["text"]


# ------------------------------------------------------------------ a value asked to be seen again
def test_the_showing_words_are_the_engine_s_list_and_the_seeing_again_it_lacks():
    """One list of showing words with the engine: its own first, then the
    words of seeing again it does not have — each once."""
    from fespp_on_trame.app import assistant_host as ah
    from fespp_on_trame.ia.nlu import engine
    words = tuple(getattr(engine, "SHOW_WORDS", None) or getattr(engine, "_SHOW_WORDS", ()))
    assert words and ah._SHOW_SAID[:len(words)] == words
    assert all(w in ah._SHOW_SAID for w in ah._AGAIN) and len(set(ah._SHOW_SAID)) == len(ah._SHOW_SAID)
    for w in ("revoir", "de nouveau", "a nouveau", "again", "ramene", "retablis", "restaure", "restore", "retrouver",
              "ravoir", "remets", "put back", "bring back", "unhide"):
        assert w in ah._AGAIN, w


def _t3(lang, fr, en):
    return en if lang == "en" else fr


@pytest.mark.parametrize("text,lang", [("je veux revoir l'huile", "fr"), ("ramène l'huile", "fr"),
                                       ("rétablis l'huile", "fr"),
                                       ("restaure l'huile", "fr"), ("je veux retrouver l'huile", "fr"),
                                       ("je veux ravoir l'huile", "fr"), ("l'huile de nouveau", "fr"),
                                       ("à nouveau l'huile", "fr"), ("restore the oil", "en"),
                                       ("the oil again please", "en"), ("I want to see the oil again", "en")])
def test_a_value_asked_to_be_seen_again_comes_back(host, app, fluids, text, lang):
    """After "hide the oil zone", a sentence that asks to see the oil again
    shows it: the filter that hid it goes (nothing else of Fluids was
    hidden) — never the last command's hiding taken up, nor the oil added
    to the values hidden. Its undo hides the oil again."""
    _run(host, "masque la zone huile de la grille")
    cmd, r = _run(host, text, lang)
    assert cmd["slots"].get("values_mode") == "again" and not cmd["slots"].get("exclude"), cmd["slots"]
    assert r["ok"] and _kept_ranges(app) == [], r["text"]
    assert r["text"] == _t3(lang, "Fluids de Geogrid : les mailles « oil » sont de nouveau affichées, plus aucune"
                                  " valeur n'est masquée.",
                            "Geogrid Fluids: the “oil” cells are shown again, no value is hidden any more.")
    host.undo(r["undo"], lang)
    assert _kept_ranges(app) == [(0.0, 0.0), (2.0, 2.0)]


@pytest.mark.parametrize("text,lang", [("je veux revoir le gaz", "fr"), ("ramène le gaz", "fr"),
                                       ("restore the gas", "en")])
def test_a_value_seen_again_leaves_the_other_hidden_values_hidden(host, app, fluids, text, lang):
    _run(host, "masque les zones huile et gaz de la grille")
    _, r = _run(host, text, lang)
    assert r["ok"] and _kept_ranges(app) == [(0.0, 0.0), (2.0, 2.0)], r["text"]
    assert r["text"] == _t3(lang, "Fluids de Geogrid : les mailles « gas » sont de nouveau affichées ; restent"
                                  " masquées : oil.",
                            "Geogrid Fluids: the “gas” cells are shown again; still hidden: oil.")


def test_a_value_asked_again_that_is_not_hidden_is_said_in_sight_and_nothing_is_done(host, app, fluids):
    """The gas is in sight after "hide the oil zone": "je veux revoir le
    gaz" says so and does nothing — never a hiding, nor the other values
    hidden to keep the gas alone."""
    _run(host, "masque la zone huile de la grille")
    n = len(app.calls)
    _, r = _run(host, "je veux revoir le gaz")
    assert r["ok"] and r["undo"] is None
    assert r["text"] == "Fluids de Geogrid : les mailles « gas » sont déjà affichées. Restent masquées : oil."
    assert _kept_ranges(app) == [(0.0, 0.0), (2.0, 2.0)]
    assert not [c for c, _ in app.calls[n:] if c.startswith("threshold_")]


def test_seeing_again_said_not_keeps_the_hiding(host):
    """ "Je ne veux plus revoir le gaz" is a hiding: the polarity the engine
    took from the last command stays, and the gas joins the values hidden."""
    _hid_the_oil(host)
    cmd = {"intent": "threshold", "text": "je ne veux plus revoir le gaz",
           "slots": {"category": "gas", "categories": ["gas"], "exclude": True, "repeat": True}}
    host._take_up_polarity(cmd)
    host._mark_values(cmd, False)
    assert cmd["slots"]["exclude"] is True and cmd["slots"]["values_mode"] == "add"


# ------------------------------------------------------------------ an undo puts back the whole chain
class _IjkNamesApp(FakeApp):
    """The fake with entry names made as IjkGrid.add_threshold makes them —
    a root "thr_<rep>_<array>", a child "<parent>_<array>", "_2", "_3"… on
    a collision — so the names an undo regenerates come back the same."""

    def _threshold_add(self, payload, vid):
        iso = self._iso(vid)
        parent = payload[1] if any(e["name"] == payload[1] for e in iso.chain) else None
        base = f"thr_grid_{payload[0]}" if parent is None else f"{parent}_{payload[0]}"
        names = {e["name"] for e in iso.chain}
        name, k = base, 2
        while name in names:
            name, k = f"{base}_{k}", k + 1
        if not self.add_fails:
            iso.chain.append({"name": name, "parent_name": parent, "array": payload[0], "visible": True,
                              "low": 0.0, "high": 0.4, "data_range": [0.0, 0.4]})
        self._push(vid, iso)


def _shape_of(app):
    """The grid's chain as (array, its parent's array, low, high, visible),
    sorted: the names are regenerated by an undo."""
    iso = app.isos.get((VID, app.p["grid"]))
    chain = [] if iso is None else iso.chain
    by = {e["name"]: e["array"] for e in chain}
    return sorted((e["array"], by.get(e["parent_name"]) if e["parent_name"] else None, e["low"], e["high"],
                   e.get("visible", True)) for e in chain)


_UNDO_SCENARIOS = {
    "d": ["filtre la porosité au-dessus de 0,2", "masque l'huile", "filtre le net sur brut au-dessus de 0,1",
          "masque l'eau", "garde que le gaz"],
    "e": ["masque l'huile", "filtre la porosité au-dessus de 0,2", "masque l'eau"],
    "f": ["masque l'huile", "filtre la porosité au-dessus de 0,2", "garde que le gaz"],
    "g": ["garde l'eau et le gaz", "filtre la porosité au-dessus de 0,2", "masque l'eau"],
    "k": ["masque l'huile", "filtre la porosité entre 0,1 et 0,3", "masque le gaz", "garde que l'eau"],
}


@pytest.mark.parametrize("ijk_names", [False, True], ids=["fake names", "IjkGrid names"])
@pytest.mark.parametrize("steps", list(_UNDO_SCENARIOS.values()), ids=list(_UNDO_SCENARIOS))
def test_each_undo_puts_the_grid_s_whole_chain_back_as_it_was_before_its_gesture(monkeypatch, steps, ijk_names):
    """A filter chained under an entry a later gesture replaces (the
    porosity under one of the Fluids entries a hiding put side by side) is
    handed to its grandparent when that entry goes (IjkGrid). Undone one
    by one from the top, each gesture puts the grid's whole chain back as
    it was before it — every entry under its own parent, with its range and
    its eye — whatever the depth, and whatever names the entries come back
    with."""
    app = _IjkNamesApp() if ijk_names else FakeApp()
    real = FesppAssistantHost._category_names

    def names(self, tree, path):
        return {0: "water", 1: "oil", 2: "gas"} if path == app.p["fluids"] else real(self, tree, path)
    monkeypatch.setattr(FesppAssistantHost, "_category_names", names)
    host = FesppAssistantHost(app.server)
    ctl = _panel(app, host)
    before, execute = [], host.execute

    def recording(cmd, lang):
        shape = _shape_of(app)
        r = execute(cmd, lang)
        if r.get("ok") and r.get("undo") is not None:
            before.append(shape)
        return r
    host.execute = recording
    for s in steps:
        ctl.ask(s)
    assert len(before) == len(ctl._undo) >= 3, [m["text"] for m in _replies(app)]
    while ctl._undo:
        ctl.undo()
        assert _shape_of(app) == before.pop(), (steps, _replies(app)[-1]["text"])


# ------------------------------------------------------------------ colours, percents, the wells, the AI's failures
class _CardApp(FakeApp):
    """The Colormap card as boot fills it: min / max the colour table's
    range (cmap_range sets it), data_min / data_max the data's."""

    def __init__(self):
        self.lut = (0.0, 0.4)
        super().__init__()

    def _cmap_range(self, rng, vid):
        self.lut = tuple(rng)

    def _on_flush(self):
        super()._on_flush()
        card = dict(self.state.get(f"ui_colormap__{VID}") or {})
        if card:
            card.update(min=self.lut[0], max=self.lut[1], data_min=0.0, data_max=0.4)
            self.state[f"ui_colormap__{VID}"] = card


def test_one_colour_bound_is_checked_against_the_data_not_the_colours_narrowed_since():
    """After "colours from 0.1 to 0.2" on a porosity of 0 to 0.4, "colour
    range above 0.25" is inside the data: from 0.25 to the data's top —
    never refused for the colours' narrowed range, nor swapped into
    0.2 – 0.25. A bound past the data is refused with the data's range."""
    app = _CardApp()
    host = FesppAssistantHost(app.server)
    _run(host, "montre la porosité")
    _run(host, "couleurs de 0,1 à 0,2")
    _, r = _run(host, "fixe la plage de couleurs au-dessus de 0,25")
    assert r["ok"] and app.called("cmap_range")[-1] == ([0.25, 0.4], VID), r["text"]
    _, r = _run(host, "fixe la plage de couleurs au-dessus de 0,5")
    assert not r["ok"] and r["text"].startswith("Les valeurs de Total Porosity vont de 0 à 0,4 : au-dessus de 0,5,")


def _percent_tree(uom):
    """Geogrid with a porosity stored in percent (0 to 40)."""
    asm = FakeDataAssembly()
    add = asm.add_node_with_attrs
    gc = add(f"_gridfolder_{U['grid']}", 0, title="Geogrid", type="GridContainer")
    pf = add(f"_propsfolder_{U['grid']}", gc, title="Properties", type="PropertiesFolder")
    n = {"grid": add(f"_{U['grid']}", pf, title="SolidColor", type="IjkGrid")}
    n["poro"] = add(f"_{U['poro']}", pf, title="Total Porosity", type="ContinuousProperty", propertyKind="porosity",
                    uom=uom, minvalue="0", maxvalue="40")
    return Tree(asm), {k: asm.GetNodePath(v) for k, v in n.items()}


class _PercentApp(FakeApp):
    """A porosity stored in percent: its filter entries span 0 to 40."""

    def __init__(self, uom):
        super().__init__(*_percent_tree(uom))

    def _threshold_add(self, payload, vid):
        super()._threshold_add(payload, vid)
        e = self._iso(vid).chain[-1]
        e["low"], e["high"], e["data_range"] = 0.0, 40.0, [0.0, 40.0]


@pytest.mark.parametrize("uom", ["%", "p.u."])
def test_a_property_stored_in_percent_takes_the_numbers_as_said(uom):
    """The engine makes "porosity above 20" a fraction by the kind alone
    (0.2) and leaves the number as said in the slots (`raw`): a porosity
    stored in percent takes 20 — for a filter, a highlight and the colours."""
    app = _PercentApp(uom)
    host = FesppAssistantHost(app.server)
    poro = {o["path"]: o for o in host.objects()}[app.p["poro"]]

    def cmd(intent, **slots):
        return {"intent": intent, "text": "x", "targets": [poro],
                "slots": dict({"kind": "porosity", "objects": [[poro]]}, **slots)}
    r = host.execute(cmd("threshold", min=0.2, raw={"min": 20.0}, percent=True), "fr")
    assert r["ok"] and app.called("threshold_range")[-1][0][1] == [20.0, 40.0], r["text"]
    r = host.execute(cmd("highlight", min=0.3, raw={"min": 30.0}), "fr")
    assert r["ok"] and app.called("highlight_where")[-1] == ([30.0, None], VID), r["text"]
    r = host.execute(cmd("color_range", min=0.1, max=0.3, raw={"min": 10.0, "max": 30.0}, percent=True), "fr")
    assert r["ok"] and app.called("cmap_range")[-1] == ([10.0, 30.0], VID), r["text"]


def test_a_fraction_keeps_the_engine_s_fraction_and_the_local_ai_leaves_the_number_as_said(app):
    """A porosity stored as a fraction keeps 0.2 whatever the slots' `raw`;
    the local AI's reading of a percent leaves the number as said too, so a
    property stored in percent takes it."""
    host = FesppAssistantHost(app.server)
    poro = {o["path"]: o for o in host.objects()}[app.p["poro"]]
    r = host.execute({"intent": "threshold", "text": "x", "targets": [poro],
                      "slots": {"kind": "porosity", "min": 0.2, "raw": {"min": 20.0}, "objects": [[poro]]}}, "fr")
    assert r["ok"] and app.called("threshold_range")[-1][0][1] == [0.2, 0.4], r["text"]
    papp = _PercentApp("%")
    host, _ = _ai_host(papp, intent="threshold", kind="porosity")
    cmd = host.llm_command("filtre la porosité au-dessus de 20 %")
    assert cmd["slots"]["min"] == 0.2 and cmd["slots"]["raw"] == {"min": 20.0}, cmd["slots"]
    r = host.execute(cmd, "fr")
    assert r["ok"] and papp.called("threshold_range")[-1][0][1] == [20.0, 40.0], r["text"]


def test_the_wells_zone_bound_is_a_fraction_on_the_fraction_in_view(host, app):
    """ "…the wells through the cells above 20 %" on the porosity in view
    (no kind said): 0.2, as for a filter."""
    poro = {o["path"]: o for o in host.objects()}[app.p["poro"]]
    cmd = {"intent": "well_cells", "text": "x", "targets": [poro],
           "slots": {"min": 20.0, "percent": True, "objects": [[poro]]}}
    r = host.execute(cmd, "fr")
    assert r["ok"] and (app.well_cells_payload["lo"], app.well_cells_payload["hi"]) == (0.2, None), r["text"]


@pytest.mark.parametrize("raw", ["Remote end closed connection without response",
                                 "<urlopen error [WinError 10054] An existing connection was forcibly closed by the"
                                 " remote host>",
                                 "[Errno 104] Connection reset by peer",
                                 "<urlopen error [WinError 10053] An established connection was aborted by the"
                                 " software in your host machine>"])
def test_a_connection_lost_during_a_call_is_said_in_words(raw):
    """The service restarted or stopped during the call: "connection lost",
    never the client's raw English in a French reply."""
    from fespp_on_trame.ia import llm
    assert (llm.reason_words(raw, "fr"), llm.reason_words(raw, "en")) == ("connexion interrompue", "connection lost")


# ------------------------------------------------------------------ the final re-check's sentences, pinned
NTG_VTK = make_valid_vtk_name("Net-to-Gross Ratio (PEM)")


def _said(app, host, *sentences):
    """Each sentence through the panel, in turn: the panel and its replies."""
    ctl = _panel(app, host)
    for s in sentences:
        ctl.ask(s)
    return ctl, _replies(app)


@pytest.mark.parametrize("first,text,kept", [
    ("masque l'eau", "pardon, cache aussi l'huile", [(2.0, 2.0)]),
    ("masque l'eau", "en fait, masque aussi le gaz", [(1.0, 1.0)]),
    ("masque l'eau", "finalement, cache aussi le gaz", [(1.0, 1.0)]),
    ("masque l'eau", "oups, cache l'huile en plus", [(2.0, 2.0)]),
    ("masque l'eau", "et l'huile aussi, pardon", [(2.0, 2.0)]),
    ("masque l'eau", "c'est bien, cache le gaz aussi", [(1.0, 1.0)]),
    ("masque l'eau", "masque aussi le gaz, c'est plus lisible", [(1.0, 1.0)]),
    ("masque l'eau", "et le gaz, c'est pareil", [(1.0, 1.0)]),
    ("masque l'eau", "le gaz aussi, c'est possible ?", [(1.0, 1.0)]),
    ("masque l'eau", "c'est le gaz qu'il faut aussi masquer", [(1.0, 1.0)]),
    ("masque l'eau", "pardon, et le gaz ?", [(1.0, 1.0)]),
    ("hide the water", "actually, hide the gas too", [(1.0, 1.0)]),
    ("hide the water", "sorry, the gas too", [(1.0, 1.0)]),
    ("hide the water", "my bad, hide the oil as well", [(2.0, 2.0)]),
    ("garde l'eau et l'huile", "c'est parfait, masque l'huile", [(0.0, 0.0)])])
def test_a_value_added_in_so_many_words_adds_up_whatever_correction_word_comes_with_it(host, app, fluids, first,
                                                                                        text, kept):
    """ "Aussi", "en plus", "too", "as well" add the value to the ones the
    filter hides, whatever correction word the sentence holds ("pardon",
    "en fait", "sorry", "my bad"); "pardon" said after the request is
    politeness, and "c'est" said in passing corrects nothing — the value
    hidden before never comes back unasked."""
    _said(app, host, first, text)
    assert _kept_ranges(app) == kept, [m["text"] for m in _replies(app)]


@pytest.mark.parametrize("first,text,lang,kept", [
    ("masque l'eau", "c'est l'huile que je voulais masquer", "fr", [(0.0, 0.0), (2.0, 2.0)]),
    ("masque l'eau", "pardon, l'huile", "fr", [(0.0, 0.0), (2.0, 2.0)]),
    ("hide the water", "no, the gas", "en", [(0.0, 1.0)]),
    ("masque l'eau", "plutôt le gaz aussi", "fr", [(0.0, 1.0)])])
def test_a_correction_without_an_addition_still_replaces_the_value(host, app, fluids, first, text, lang, kept):
    """ "C'est X que…", a leading "pardon", "no," and "plutôt" (which says
    what it replaces, even with "aussi") still take the last value back."""
    _run(host, first, lang)
    cmd, r = _run(host, text, lang)
    assert cmd["slots"].get("values_mode") == "correct", cmd["slots"]
    assert r["ok"] and _kept_ranges(app) == kept, r["text"]


def _hand_filter(app, array, parent, lo, hi):
    """A filter added in the Thresholds card, on the grid of its Reservoir
    tab: the new entry's name."""
    app.state[f"active_by_tab__{VID}"] = dict(app.state[f"active_by_tab__{VID}"] or {}, reservoir=app.p["grid"])
    iso = app.isos[(VID, app.p["grid"])]
    before = {e["name"] for e in iso.chain}
    app.ctrl.threshold_add([array, parent], VID)
    name = next(e["name"] for e in iso.chain if e["name"] not in before)
    app.ctrl.threshold_range([name, [lo, hi]], VID)
    return name


def _entry_on(app, array):
    return next(e for e in app.isos[(VID, app.p["grid"])].chain if e["array"] == array)


@pytest.mark.parametrize("under", [False, True], ids=["beside", "under the hiding"])
def test_an_undo_leaves_a_filter_added_by_hand_since(host, app, fluids, under):
    """ "Masque l'eau", a porosity filter added in the Thresholds card, then
    Undo: the water comes back and the porosity filter stays — beside the
    hiding's entry, or chained under it (it then moves up, as IjkGrid does
    when a parent goes, and the reply says it stays)."""
    ctl, _ = _said(app, host, "masque l'eau")
    _hand_filter(app, PORO_VTK, _entry_on(app, "Fluids")["name"] if under else None, 0.2, 0.4)
    ctl.undo()
    assert _shape_of(app) == [(PORO_VTK, None, 0.2, 0.4, True)]
    tail = " Le filtre sur Total Porosity, ajouté depuis, reste." if under else ""
    assert _replies(app)[-1]["text"] == "Annulé : « filtrer par valeur » Fluids de Geogrid." + tail


def test_an_undo_of_the_filters_taken_off_puts_them_back_under_a_filter_added_since(host, app, fluids):
    """ "Masque l'eau", "enlève les filtres", a porosity filter added by
    hand, then Undo: the water is hidden again AND the porosity filter
    applies — the entry put back chains under it, never beside it in a
    union that shows every cell of either."""
    ctl, _ = _said(app, host, "masque l'eau", "enlève les filtres")
    _hand_filter(app, PORO_VTK, None, 0.2, 0.4)
    ctl.undo()
    assert _shape_of(app) == [("Fluids", PORO_VTK, 1.0, 2.0, True), (PORO_VTK, None, 0.2, 0.4, True)]


def test_an_undo_puts_a_filter_back_above_its_old_child_and_below_a_filter_added_since(host, app, fluids):
    """The porosity filter taken off held the hiding under it (moved up to
    the root by the removal); since, a net-to-gross filter at the root and a
    porosity filter under the hiding were added by hand. The undo puts the
    porosity filter back with the hiding under it again, below the filter
    added at its level — one chain, every hand-made filter kept, never an
    entry hung under its own descendant."""
    ctl, _ = _said(app, host, "filtre la porosité au-dessus de 0,2", "sans le gaz", "retire le filtre de la porosité")
    _hand_filter(app, NTG_VTK, None, 0.15, 0.4)
    _hand_filter(app, PORO_VTK, _entry_on(app, "Fluids")["name"], 0.1, 0.4)
    ctl.undo()
    chain = app.isos[(VID, app.p["grid"])].chain
    names = {e["name"] for e in chain}
    assert all(e["parent_name"] is None or e["parent_name"] in names for e in chain)
    assert _shape_of(app) == [("Fluids", PORO_VTK, 0.0, 1.0, True), (NTG_VTK, None, 0.15, 0.4, True),
                              (PORO_VTK, "Fluids", 0.1, 0.4, True), (PORO_VTK, NTG_VTK, 0.2, 0.4, True)]


@pytest.mark.parametrize("change,shape", [
    ("range", [(PORO_VTK, None, 0.3, 0.4, True)]),
    ("eye", [(PORO_VTK, None, 0.2, 0.4, False)])])
def test_an_undo_leaves_a_range_moved_or_an_eye_closed_by_hand_since(host, app, fluids, change, shape):
    """ "Filtre la porosité au-dessus de 0,2", "masque l'eau", then the
    porosity range moved to 0.3 – 0.4 (or its eye closed) in the Thresholds
    card, then Undo: the hiding goes, the reader's change stays."""
    ctl, _ = _said(app, host, "filtre la porosité au-dessus de 0,2", "masque l'eau")
    app.state[f"active_by_tab__{VID}"] = dict(app.state[f"active_by_tab__{VID}"], reservoir=app.p["grid"])
    poro = _entry_on(app, PORO_VTK)["name"]
    if change == "range":
        app.ctrl.threshold_range([poro, [0.3, 0.4]], VID)
    else:
        app.ctrl.threshold_visible([poro, False], VID)
    ctl.undo()
    assert _shape_of(app) == shape
    assert _replies(app)[-1]["text"] == "Annulé : « filtrer par valeur » Fluids de Geogrid."


def test_an_undo_leaves_an_entry_of_its_gesture_changed_since_and_says_so(host, app, fluids):
    """A later change on an entry the gesture added is said and kept: the
    hiding's own entry retouched by hand is the reader's now, left as it
    is."""
    ctl, _ = _said(app, host, "masque l'eau")
    app.state[f"active_by_tab__{VID}"] = dict(app.state[f"active_by_tab__{VID}"], reservoir=app.p["grid"])
    app.ctrl.threshold_range([_entry_on(app, "Fluids")["name"], [2.0, 2.0]], VID)
    ctl.undo()
    assert _kept_ranges(app) == [(2.0, 2.0)]
    assert _replies(app)[-1]["text"] == ("Annulé : « filtrer par valeur » Fluids de Geogrid. Le filtre sur Fluids,"
                                         " changé depuis, est laissé tel quel.")


def test_an_undo_leaves_a_range_its_gesture_set_and_the_reader_moved_since(host, app):
    """ "Above 0.2" then "above 0.3", the range moved to 0.25 by hand, then
    the second filter undone: the reader's range stays, and the reply says
    so."""
    _run(host, "filtre la porosité au-dessus de 0,2")
    _, r = _run(host, "filtre la porosité au-dessus de 0,3")
    app.state[f"active_by_tab__{VID}"] = dict(app.state[f"active_by_tab__{VID}"], reservoir=app.p["grid"])
    app.ctrl.threshold_range([_entry_on(app, PORO_VTK)["name"], [0.25, 0.4]], VID)
    said = host.undo(r["undo"], "fr")
    assert _kept_ranges(app) == [(0.25, 0.4)]
    assert said["text"] == ("Annulé : « filtrer par valeur » Total Porosity de Geogrid. Le filtre sur Total"
                            " Porosity, changé depuis, est laissé tel quel.")


def test_an_undo_closes_the_eyes_its_gesture_opened_and_leaves_one_opened_since(host, app):
    """The filter read the porosity and opened its grid's eye; the well's
    eye opened by hand since stays open after the undo."""
    _, r = _run(host, "filtre la porosité au-dessus de 0,2")
    eyes = list(app.state[f"visible_paths__{VID}"])
    assert app.p["grid"] in eyes
    app.state[f"visible_paths__{VID}"] = eyes + [app.p["traj"]]
    host.undo(r["undo"], "fr")
    assert app.state[f"visible_paths__{VID}"] == [app.p["traj"]]


@pytest.mark.parametrize("first,text,kept", [
    ("garde que l'eau", "sans le gaz", [(0.0, 0.0)]),
    ("garde que l'eau", "sans aucun gaz", [(0.0, 0.0)]),
    ("garde l'eau et l'huile", "plus de gaz", [(0.0, 1.0)]),
    ("garde l'eau et l'huile", "le gaz en moins", [(0.0, 1.0)]),
    ("keep only the oil", "without the gas", [(1.0, 1.0)]),
    ("keep only the oil", "no gas at all", [(1.0, 1.0)])])
def test_after_a_keep_a_zone_said_not_is_hidden_never_kept_alone(host, app, fluids, first, text, kept):
    """After a keep, "sans le gaz", "plus de gaz", "le gaz en moins", "no
    gas", "without the gas" hide the gas — here hidden already, which is
    said — and never keep ONLY the gas."""
    _, replies = _said(app, host, first, text)
    assert _kept_ranges(app) == kept, [m["text"] for m in replies]
    assert "déjà masquées" in replies[-1]["text"] or "already hidden" in replies[-1]["text"], replies[-1]


def test_a_zone_said_not_with_nothing_before_offers_to_hide_it(host, fluids):
    cmd = host.parse("sans le gaz")
    assert cmd["slots"]["exclude"] is True
    assert host.choice_label(cmd, "threshold", "fr") == "Masquer les mailles « gas » (Fluids)"


@pytest.mark.parametrize("first,text,said", [
    ("masque l'eau", "ne cache pas l'huile",
     "Fluids de Geogrid : les mailles « oil » ne sont pas masquées, rien à faire."),
    ("masque l'eau", "surtout ne masque pas l'huile",
     "Fluids de Geogrid : les mailles « oil » ne sont pas masquées, rien à faire."),
    ("masque l'huile", "ne cache pas l'huile",
     "Fluids de Geogrid : rien n'est masqué de plus ; les mailles « oil » le sont déjà — demandez à les revoir"
     " pour les afficher.")])
def test_a_hiding_verb_said_not_hides_nothing_and_says_so(host, app, fluids, first, text, said):
    _run(host, first)
    before = _kept_ranges(app)
    n = len(app.calls)
    _, r = _run(host, text)
    assert r["ok"] and r["undo"] is None and r["text"] == said
    assert _kept_ranges(app) == before and not [c for c, _ in app.calls[n:] if c.startswith("threshold_")]


@pytest.mark.parametrize("text", ["cache le gaz, ne cache pas l'huile",
                                  # the keep after the conjunction spares the value it names
                                  "cache le gaz mais laisse l'huile",
                                  # … and a keep that starts a request of its own keeps it
                                  "hide the gas but keep the oil"])
def test_a_value_spared_next_to_one_hidden_is_left_as_it_is(host, app, fluids, text):
    _said(app, host, "masque l'eau", text)
    assert _kept_ranges(app) == [(1.0, 1.0)], [m["text"] for m in _replies(app)]


@pytest.mark.parametrize("first,text", [("masque l'eau", "cache le gaz, pas l'huile"),
                                        ("hide the water", "hide the gas but not the oil"),
                                        ("hide the water", "no more gas")])
def test_a_value_said_not_that_the_last_request_did_not_name_corrects_nothing(host, app, fluids, first, text):
    """ "Cache le gaz, pas l'huile" after "masque l'eau": the oil is left as
    it is, the gas joins the water — the water never comes back; "no more
    gas" is a hiding, not a "no" that takes the water back."""
    _said(app, host, first, text)
    assert _kept_ranges(app) == [(1.0, 1.0)], [m["text"] for m in _replies(app)]


def test_a_value_said_not_that_the_last_request_named_is_corrected(host, app, fluids):
    _said(app, host, "masque l'eau", "masque le gaz", "non, pas le gaz, l'huile")
    assert _kept_ranges(app) == [(2.0, 2.0)], [m["text"] for m in _replies(app)]


@pytest.mark.parametrize("first,text,kept", [
    ("masque l'eau", "au lieu de l'eau, cache l'huile", [(0.0, 0.0), (2.0, 2.0)]),
    ("hide the water", "hide the gas instead of the water", [(0.0, 1.0)]),
    ("hide the water", "instead of the water, hide the oil", [(0.0, 0.0), (2.0, 2.0)])])
def test_the_value_said_after_instead_of_comes_back(host, app, fluids, first, text, kept):
    """ "Au lieu de l'eau", "instead of the water" name the value replaced:
    it comes back, never hidden with the new one."""
    _said(app, host, first, text)
    assert _kept_ranges(app) == kept, [m["text"] for m in _replies(app)]


@pytest.mark.parametrize("steps,shape", [
    (["masque l'huile", "filtre la porosité au-dessus de 0,2"],
     [("Fluids", PORO_VTK, 0.0, 0.0, True), ("Fluids", PORO_VTK, 2.0, 2.0, True), (PORO_VTK, None, 0.2, 0.4, True)]),
    (["garde l'eau et le gaz", "filtre la porosité au-dessus de 0,2"],
     [("Fluids", PORO_VTK, 0.0, 0.0, True), ("Fluids", PORO_VTK, 2.0, 2.0, True), (PORO_VTK, None, 0.2, 0.4, True)]),
    (["filtre la porosité au-dessus de 0,2", "masque l'huile", "filtre le net sur brut au-dessus de 0,1"],
     [("Fluids", NTG_VTK, 0.0, 0.0, True), ("Fluids", NTG_VTK, 2.0, 2.0, True), (NTG_VTK, PORO_VTK, 0.1, 0.4, True),
      (PORO_VTK, None, 0.2, 0.4, True)])])
def test_a_range_filter_after_values_side_by_side_applies_to_every_one_of_them(host, app, fluids, steps, shape):
    """A filter on values hides one value with two entries side by side
    (water, gas): a range filter put next goes above them, so every cell
    shown passes it — never under the last one alone, which would leave the
    water's low-porosity cells shown. The reply says the other filters
    apply (an intersection), and the undo puts the chain back."""
    ctl, _ = _said(app, host, *steps[:-1])
    before = _shape_of(app)
    ctl.ask(steps[-1])
    assert _shape_of(app) == shape
    assert "s'appliquent aussi" in _replies(app)[-1]["text"] and "union" not in _replies(app)[-1]["text"]
    ctl.undo()
    assert _shape_of(app) == before


def test_re_ranging_the_filter_above_values_says_an_intersection(host, app, fluids):
    _, replies = _said(app, host, "filtre la porosité au-dessus de 0,2", "masque l'huile",
                       "filtre la porosité au-dessus de 0,3")
    assert replies[-1]["text"] == ("Total Porosity de Geogrid : mailles gardées de 0,3 à 0,4. Les autres filtres"
                                   " de la grille s'appliquent aussi (Fluids).")


def test_an_addition_in_a_sentence_of_its_own_adds_to_a_keep_and_to_a_highlight(host, app, fluids):
    _said(app, host, "keep only the oil", "and the gas as well")
    assert _kept_ranges(app) == [(1.0, 2.0)]
    _said(app, host, "surligne l'eau", "surligne aussi l'huile")
    assert app.called("highlight_where")[-1] == ([0.0, 1.0], VID)


@pytest.mark.parametrize("steps,said", [
    (["masque l'huile", "je voudrais revoir l'eau"],
     "Fluids de Geogrid : les mailles « water » sont déjà affichées. Restent masquées : oil."),
    (["hide the oil", "I want to see the water again"],
     "Geogrid Fluids: the “water” cells are shown already. Still hidden: oil."),
    (["masque la zone huile de la grille", "je veux revoir le gaz"],
     "Fluids de Geogrid : les mailles « gas » sont déjà affichées. Restent masquées : oil.")])
def test_a_value_in_sight_asked_again_changes_nothing(host, app, fluids, steps, said):
    ctl, _ = _said(app, host, *steps[:-1])
    before, depth = _kept_ranges(app), len(ctl._undo)
    ctl.ask(steps[-1])
    assert _replies(app)[-1]["text"] == said
    assert _kept_ranges(app) == before and len(ctl._undo) == depth


def test_a_value_asked_again_when_its_filter_s_eye_is_closed_changes_nothing(host, app, fluids):
    """ "Garde que l'huile", the filter's eye closed by hand (every cell in
    sight), then "je veux revoir le gaz": in sight already, nothing hidden."""
    ctl, _ = _said(app, host, "garde que l'huile")
    app.state[f"active_by_tab__{VID}"] = dict(app.state[f"active_by_tab__{VID}"], reservoir=app.p["grid"])
    app.ctrl.threshold_visible([_entry_on(app, "Fluids")["name"], False], VID)
    ctl.ask("je veux revoir le gaz")
    assert _replies(app)[-1]["text"] == "Fluids de Geogrid : les mailles « gas » sont déjà affichées."
    assert _shape_of(app) == [("Fluids", None, 1.0, 1.0, False)]


def test_a_correction_of_a_value_seen_again_hides_it_again_and_shows_the_one_meant(host, app, fluids):
    _, replies = _said(app, host, "masque l'eau et le gaz", "remontre l'eau", "non, pas l'eau, le gaz")
    assert _kept_ranges(app) == [(1.0, 2.0)]
    assert replies[-1]["text"] == ("Fluids de Geogrid : les mailles « gas » sont de nouveau affichées ; restent"
                                   " masquées : water.")


def test_a_hiding_finished_by_buttons_keeps_its_polarity(host, app, fluids):
    """ "Masque des mailles de Fluids" is asked about: "filter by value",
    then the gas — the gas is hidden with the oil hidden before, never kept
    alone; the question says "masquer"."""
    ctl, replies = _said(app, host, "masque l'huile", "masque des mailles de Fluids")
    assert "intent:threshold" in [c["id"] for c in replies[-1].get("choices") or ()], replies[-1]
    ctl.choose("intent:threshold")
    assert _replies(app)[-1]["text"] == "Quelles mailles de Fluids masquer ?"
    ctl.choose("category:gas")
    assert _kept_ranges(app) == [(0.0, 0.0)], _replies(app)[-1]["text"]


def test_the_filter_of_one_property_is_taken_off_alone(host, app, fluids):
    """ "Retire le filtre de la porosité" takes off that property's entries
    only: the water stays hidden; the undo puts the porosity filter back."""
    ctl, replies = _said(app, host, "masque l'eau", "filtre la porosité au-dessus de 0,2",
                         "retire le filtre de la porosité")
    assert replies[-1]["text"] == "Filtre par valeur enlevé : Total Porosity de Geogrid."
    assert _shape_of(app) == [("Fluids", None, 1.0, 2.0, True)]
    ctl.undo()
    assert _shape_of(app) == [("Fluids", None, 1.0, 2.0, True), (PORO_VTK, "Fluids", 0.2, 0.4, True)]
    _, r = _run(host, "retire le filtre du net sur brut")
    assert r["ok"] and r["undo"] is None and r["text"].startswith("Aucun filtre par valeur sur Net-to-Gross")


def test_the_filter_taken_off_under_another_comes_back_above_it_on_undo(host, app, fluids):
    """The porosity filter holds the hiding under it: taken off, the hiding
    moves up to its place; the undo puts the porosity back and the hiding
    under it again — the parent the gesture changed, put back."""
    ctl, _ = _said(app, host, "filtre la porosité au-dessus de 0,2", "masque l'eau",
                   "retire le filtre de la porosité")
    assert _shape_of(app) == [("Fluids", None, 1.0, 2.0, True)]
    ctl.undo()
    assert _shape_of(app) == [("Fluids", PORO_VTK, 1.0, 2.0, True), (PORO_VTK, None, 0.2, 0.4, True)]


@pytest.mark.parametrize("raw,fr,en", [
    ("404 Not Found", "le service ne connaît pas cette adresse (404) : vérifiez FESPP_IA_URL",
     "the service does not know this address (404): check FESPP_IA_URL"),
    ("500 Internal Server Error", "le service a rencontré une erreur interne (500)",
     "the service failed on an internal error (500)"),
    ("Expecting value: line 1 column 1 (char 0)", "sa réponse est illisible (ce n'est pas du JSON)",
     "its reply cannot be read (it is not JSON)")])
def test_an_http_or_json_failure_of_the_local_ai_is_said_in_words(raw, fr, en):
    from fespp_on_trame.ia import llm
    assert (llm.reason_words(raw, "fr"), llm.reason_words(raw, "en")) == (fr, en)


def test_hide_all_hides_the_selection_extracts_too(host, app):
    """D33: "hide all" leaves no selection extract on screen, does not call
    a view holding one "already empty", and its undo puts it back."""
    s = app.state
    s[f"visible_paths__{VID}"] = []
    s[f"ui_session_rows__{VID}"] = [{"path": f"session://{VID}/x1", "kind": "extract",
                                     "visible": True}]
    cmd, r = _run(host, "masque tout")
    assert r["ok"] and r["undo"] is not None, r
    assert s[f"ui_session_rows__{VID}"][0]["visible"] is False
    u = host.undo(r["undo"], "fr")
    assert u["ok"]
    assert s[f"ui_session_rows__{VID}"][0]["visible"] is True
    _, r2 = _run(host, "masque tout")
    _, r3 = _run(host, "masque tout")
    assert r3["text"] in ("La vue est déjà vide.", "The view is already empty.")
