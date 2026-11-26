"""The velocity models of a session: one active at most, the others parked.

A session starts with NO model: the law's memory (app/features/time_depth_law
`held`) then holds the inputs of one to generate — its TDLaws, its zone, its
layers — and nothing converts. `generate` makes a model of them, named
"Velocity model N" from 1; from then on the conversions, the view and the
pins act on it, its fields being that memory itself, so nothing there has to
know about the others. A parked model keeps its fields in its entry until it
is active again. The inputs of a model not generated are kept by nobody:
left for a model chosen in the view, they are gone, and "New velocity model"
always starts blank — the way to drop inputs entered by mistake.

A lattice IJK grid of the tree becomes a model on "Use as velocity model" or
when it is chosen in the card: its extent, layers and velocities as cells set
by hand on one column at its centre. A grid in depth is read in two-way time
on the way in (engine/velocity_model.depth_model_in_time).

A grid the editable model cannot hold — over MAX_CELLS along an axis, its
columns not along X and Y, its vertical axis I or J (a seismic velocity
cube) — and any lattice grid in time is read AS IT IS: full resolution,
float32, not editable, never written to the tree (it is in it). Its velocity
is the property chosen in the card's list, and that list alone chooses it —
an eye opened on another property of the grid changes nothing (the PO,
13/11: looking at an amplitude made it the velocity); an interval velocity unless
its kind says otherwise, an RMS one made interval velocities by Dix's
formula. No grid is ever taken unasked.

An entry: {id, name, from (the velocity it was taken from, "<grid's last path
segment>:<property>", "" for a model made in the card), uuids (those a session
saved for its grid in the tree), then the OWN fields while parked}.

State:   ``ui_cube_grid_rows``: the rows of the lattice grids of the tree, a
         version of the active model aside.
Gesture: ``controller.time_depth_from_grid(path)``.
"""
import types

from fespp_on_trame.engine import node_facts, property_types, view_routing
from fespp_on_trame.engine import time_depth_prefill as prefill
from fespp_on_trame.engine.blockscope import domain_convert
from fespp_on_trame.engine.time_depth import MAX_CELLS, Column, Law, Model

# a generated model's name, numbered from 1
NAME = "Velocity model"
# the view's choice of no model: the inputs of one to generate
NEW = "new"
DEFAULT_V_FALLBACK = 2000.0     # a grid whose velocities are all zero: the column's law at this

OWN = ("model", "active", "cube", "key", "sig", "draft", "extent_auto", "note", "prefilled", "touched", "data",
       "velocity", "seeded")

# where a model's velocity comes from, besides the Pre-fills of
# app/features/time_depth_prefills: one property of a grid of the data, or
# TDLaws entered by hand (the session's own model, which holds no property:
# its TDLaws make its velocity)
PROPERTY, BY_HAND = "property", "hand"


def blank():
    """The OWN fields of a model nobody touched yet. `seeded`: it had a
    TDLaw once — the one it starts with is not given twice."""
    return {"model": Model(), "active": 0, "cube": None, "key": "", "sig": "",
            "draft": [None, None, None, None], "extent_auto": False, "note": "", "prefilled": "",
            "touched": False, "data": None, "velocity": None, "seeded": False}


class NotRead(ValueError):
    """The grid or its velocity is not in the session yet: reading it may help."""


class Models:
    def __init__(self, held):
        self.held = held
        self.reset()

    def reset(self):
        """No model at all."""
        self.entries = []
        self.current = None
        # the model left for the inputs of a new one: the conversions read it
        # until another is generated or chosen
        self.serving = None
        self.next_id = 1

    def entry(self, mid):
        return next((e for e in self.entries if e["id"] == mid), None)

    def active(self):
        return self.entry(self.current)

    def converting(self):
        """The id of the model the conversions read: the active one; while
        the inputs of a new one are entered, the model left for them."""
        return self.current if self.current is not None else self.serving

    def parked(self):
        return [e for e in self.entries if e["id"] != self.current]

    def of_source(self, source):
        """The model taken from the velocity `source`, None when there is none."""
        return next((e["id"] for e in self.entries if source and e["from"] == source), None)

    def _park(self):
        """The active model's fields go to its entry; with none active, the
        inputs entered so far are dropped."""
        entry = self.active()
        if entry is not None:
            entry.update({k: self.held[k] for k in OWN})

    def _entry(self, name, source="", uuids=None):
        mid = self.next_id
        self.next_id += 1
        self.entries.append({"id": mid, "name": name, "from": source, "uuids": uuids})
        self.current, self.serving = mid, None
        return mid

    def add(self, name=None, source="", uuids=None):
        """A new model, blank and active (`name`, else "Velocity model N");
        the active one is parked."""
        self._park()
        mid = self._entry(self.unique(name) if name else self.numbered(), source, uuids)
        self.held.update(blank())
        return mid

    def generate(self):
        """The inputs entered so far become a model, active, named
        "Velocity model N"; None when a model is active already."""
        if self.current is not None:
            return None
        return self._entry(self.numbered())

    def to_draft(self):
        """The inputs of a new model from now on, blank, the active model
        left for them: it goes on converting. False when none was active."""
        if self.current is None:
            return False
        self._park()
        self.serving, self.current = self.current, None
        self.held.update(blank())
        return True

    def switch(self, mid):
        """Model `mid` active, the active one parked. False when it is unknown."""
        entry = self.entry(mid)
        if entry is None or mid == self.current:
            return False
        self._park()
        self.current, self.serving = mid, None
        self.held.update({k: entry.pop(k) for k in OWN})
        return True

    def numbered(self):
        """"Velocity model N", N the first number from 1 no model wears."""
        names = {e["name"] for e in self.entries}
        n = 1
        while f"{NAME} {n}" in names:
            n += 1
        return f"{NAME} {n}"

    def retitle(self, name, source=""):
        """The active model, untouched so far, is now about `source`."""
        entry = self.active()
        entry["name"], entry["from"] = self.unique(name, entry), source

    def unique(self, name, leaving_out=None):
        names = {e["name"] for e in self.entries if e is not leaving_out}
        if name not in names:
            return name
        n = 2
        while f"{name} {n}" in names:
            n += 1
        return f"{name} {n}"

    def listing(self):
        """[(id, name, cube, key)] of every model the session writes to the
        tree, the active one first: a grid of the data read as it is is in
        it already."""
        active = self.active()
        rows = ([(active["id"], active["name"], self.held["cube"], self.held["key"])]
                if active and not self.held.get("data") else [])
        return rows + [(e["id"], e["name"], e.get("cube"), e.get("key", ""))
                       for e in self.parked() if not e.get("data")]


def register(core, held, models, *, changed, publish, zone_follows, query, xml_of):
    """The grids of the tree as models. `changed()`: the model changed, `publish()`:
    its state written, `zone_follows()`: its zone moved to the files' when
    nobody typed it (True when it moved), `query()` and `xml_of(query, uuids)`:
    the reader's query channel. Hands back what the law calls: `options()`,
    `pick(value)`, `lattice_rows_publish()`."""
    controller, ctx, state = core.controller, core.ctx, core.state
    waiting = {"grid": None}    # a grid chosen in the card, its velocity being read

    def _tree():
        return getattr(core, "tree", None)

    def _velocity_leaf(tree, rid):
        """The node of the velocity of the grid `rid`, None when it has none."""
        cid = tree.find_parent_node_id_with_type(rid, "GridContainer")
        for node, _children in tree.iter_nodes(cid if cid is not None else rid):
            if (node_facts.is_property_kind(tree.find_type(node) or "")
                    and prefill.is_velocity_title(tree.find_title(node))):
                return node
        return None

    def _grid_cube(path):
        """A loaded IJK grid of the tree read as a velocity model: its extent,
        the two-way times of its layers (nk + 1, ms: the mean time of each K
        interface; a grid in depth is read in time), the velocities (nk, nj,
        ni) of the property `path` names — or the grid's velocity one, else its
        only array. ValueError says what is wrong, NotRead what is missing."""
        import numpy as np
        from fespp_on_trame.engine.velocity_model import depth_model_in_time
        from vtkmodules.util.numpy_support import vtk_to_numpy
        tree = _tree()
        index = getattr(ctx, "assembly_index", None)
        nid = tree.find_node_id(path) if tree is not None and path else None
        if nid is None or index is None:
            raise ValueError("no such row")
        rid = tree.find_representation_node(nid)
        if rid is None:
            raise ValueError("no grid under this row")
        rep_path = tree.find_path(rid)
        dom = getattr(ctx, "domain_of_path", None)
        domain = dom(rep_path) if dom is not None else "time"
        if domain not in ("time", "depth"):
            raise ValueError("its CRS says neither depth nor time")
        datasets = [ds for ds, _flat in (index.datasets(rep_path) or ())
                    if ds is not None and hasattr(ds, "GetExtent")]
        if not datasets:
            raise NotRead("the grid is not loaded as an IJK grid: tick it first")
        ds = datasets[0]
        ext = ds.GetExtent()
        ni, nj, nk = ext[1] - ext[0], ext[3] - ext[2], ext[5] - ext[4]
        if min(ni, nj, nk) < 1:
            raise ValueError("the grid has no cell")
        if max(ni, nj, nk) > MAX_CELLS:
            raise ValueError(f"the velocity model holds {MAX_CELLS} cells per axis at most"
                             f" ({ni} × {nj} × {nk} here)")
        cd = ds.GetCellData()
        names = [cd.GetArrayName(a) for a in range(cd.GetNumberOfArrays())]
        names = [n for n in names if n and n not in ("ConnectivityFlags", "vtkGhostType")]
        own = node_facts.is_property_kind(tree.find_type(nid) or "")
        leaf = nid if own else _velocity_leaf(tree, rid)
        wanted = tree.find_title(leaf) if leaf is not None else ""
        if wanted and wanted not in names:
            raise NotRead(f"{wanted} is not loaded on the grid: tick it first")
        if not wanted and len(names) != 1:
            if not names:
                raise NotRead("no property loaded on the grid: tick its velocity first")
            raise ValueError("no velocity among its properties: right-click the one to use")
        name = wanted or names[0]
        arr = cd.GetArray(name)
        if arr is None or arr.GetNumberOfComponents() != 1 or arr.GetNumberOfTuples() != ni * nj * nk:
            raise ValueError(f"{name} is not one value per cell")
        v = np.asarray(vtk_to_numpy(arr), float).reshape(nk, nj, ni)
        pts = np.asarray(vtk_to_numpy(ds.GetPoints().GetData()), float)
        per_face = (ni + 1) * (nj + 1)
        if len(pts) != per_face * (nk + 1):
            raise ValueError("the grid's nodes are not those of a plain IJK lattice")
        # the view's z counts up, the depth or the two-way time its opposite
        z = [0.0 - float(pts[k * per_face:(k + 1) * per_face, 2].mean()) for k in range(nk + 1)]
        z = [0.0 if abs(d) < 1e-9 else d for d in z]        # a top at the zero reads 0, not -0
        if any(b <= a for a, b in zip(z, z[1:])):
            raise ValueError("the grid's layers do not go down")
        surface = 0.0
        if domain == "depth":
            z, v, surface = depth_model_in_time(z, v)
            z = [float(t) for t in z]
        extent = (float(pts[:, 0].min()), float(pts[:, 0].max()), float(pts[:, 1].min()), float(pts[:, 1].max()))
        return types.SimpleNamespace(
            extent=extent, times=z, v=v, surface=surface, name=name, in_depth=domain == "depth",
            title=(tree.find_rep_title(rid) or tree.find_title(rid) or "grid"),
            source=f"{rep_path.rsplit('/', 1)[-1]}:{name}")

    def _view_in_use():
        return view_routing.model_view(state)

    def _busy(text):
        """The load pill while a grid of the data becomes the model: its
        velocity read from the store, then the model built ("" ends it)."""
        if (getattr(state, "ui_work_note", "") or "") == text:
            return
        state.ui_work_note = text
        flush = getattr(state, "flush", None)
        if callable(flush):
            flush()

    def _properties(tree, rid):
        """The nodes of the properties of grid `rid`, in the tree's order."""
        cid = tree.find_parent_node_id_with_type(rid, "GridContainer")
        return [node for node, _children in tree.iter_nodes(cid if cid is not None else rid)
                if node_facts.is_property_kind(tree.find_type(node) or "")]

    def _in_time(rep_path):
        dom = getattr(ctx, "domain_of_path", None)
        return (dom(rep_path) if dom is not None else "time") == "time"

    def _velocity_of(tree, rid):
        """The property of grid `rid` a model takes as its velocity until the
        card's list says another: one named as a velocity, else its first."""
        found = _velocity_leaf(tree, rid)
        if found is not None:
            return found
        return next(iter(_properties(tree, rid)), None)

    def _structured_of(path):
        """(tree, rid, rep_path, dataset) of the loaded grid under `path`."""
        tree = _tree()
        index = getattr(ctx, "assembly_index", None)
        nid = tree.find_node_id(path) if tree is not None and path else None
        if nid is None or index is None:
            raise ValueError("no such row")
        rid = tree.find_representation_node(nid)
        if rid is None:
            raise ValueError("no grid under this row")
        rep_path = tree.find_path(rid)
        datasets = [ds for ds, _flat in (index.datasets(rep_path) or ())
                    if ds is not None and hasattr(ds, "GetExtent")]
        if not datasets:
            raise NotRead("the grid is not loaded as an IJK grid: tick it first")
        return tree, rid, rep_path, datasets[0]

    def _axes_of(ds):
        """(vertical, a, b, steps, origin, n): which of the grid's axes I, J,
        K (0, 1, 2) runs down, the two others, the step of one cell along
        each axis and the first node (from the nodes, no copy of them), the
        cells per axis."""
        import numpy as np
        from vtkmodules.util.numpy_support import vtk_to_numpy
        e = ds.GetExtent()
        n = (e[1] - e[0], e[3] - e[2], e[5] - e[4])
        pts = vtk_to_numpy(ds.GetPoints().GetData())
        nodes = (n[0] + 1, n[1] + 1, n[2] + 1)

        def node(i, j, k):
            return np.asarray(pts[i + nodes[0] * (j + nodes[1] * k)], float)

        origin = node(0, 0, 0)
        steps = [node(1, 0, 0) - origin, node(0, 1, 0) - origin, node(0, 0, 1) - origin]
        down = [abs(s[2]) / (np.hypot(s[0], s[1]) + 1e-12) for s in steps]
        vertical = int(np.argmax(down))
        a, b = [x for x in range(3) if x != vertical]
        return vertical, a, b, steps, origin, n, node

    def _as_is_needed(ds):
        """Whether the editable model cannot hold the grid: too many cells
        along an axis, its columns not along X and Y, or not K that runs down."""
        vertical, a, b, steps, _o, n, _node = _axes_of(ds)
        along = abs(steps[a][1]) < 1e-6 * abs(steps[a][0]) and abs(steps[b][0]) < 1e-6 * abs(steps[b][1])
        return vertical != 2 or not along or max(n) > MAX_CELLS

    def _grid_as_is(path):
        """A lattice grid of the tree read as it is (see the module):
        SimpleNamespace(cube, title, source, name, kind, note)."""
        import numpy as np
        from fespp_on_trame.engine.velocity_model import Cube, read_velocities
        from vtkmodules.util.numpy_support import vtk_to_numpy
        tree, rid, rep_path, ds = _structured_of(path)
        if not _in_time(rep_path):
            raise ValueError("a grid read as it is must be in time")
        nid = tree.find_node_id(path)
        leaf = nid if node_facts.is_property_kind(tree.find_type(nid) or "") else _velocity_of(tree, rid)
        if leaf is None:
            raise ValueError("the grid holds no property to read as its velocity")
        name = tree.find_title(leaf)
        arr = ds.GetCellData().GetArray(name)
        if arr is None:
            raise NotRead(f"{name} is not loaded on the grid: tick it first")
        vertical, a, b, steps, origin, n, node = _axes_of(ds)
        if arr.GetNumberOfComponents() != 1 or arr.GetNumberOfTuples() != n[0] * n[1] * n[2]:
            raise ValueError(f"{name} is not one value per cell")
        # the layers: the two-way times down the vertical axis, the same in
        # every column (a lattice): checked at the far corner
        corner = [0, 0, 0]
        corner[a], corner[b] = n[a], n[b]

        def times_at(col):
            out = []
            for v in range(n[vertical] + 1):
                ijk = list(col)
                ijk[vertical] = v
                out.append(-float(node(*ijk)[2]))
            return np.asarray(out)

        t = times_at([0, 0, 0])
        if np.abs(times_at(corner) - t).max() > 1e-3 * max(1.0, abs(t).max()):
            raise ValueError("its layers are not flat in time")
        values = vtk_to_numpy(arr).reshape(n[2], n[1], n[0])         # K, J, I
        axis = {0: 2, 1: 1, 2: 0}                                     # VTK axis -> numpy axis
        v = values.transpose(axis[vertical], axis[b], axis[a])
        if t[-1] < t[0]:
            t, v = t[::-1], v[::-1]
        if np.any(np.diff(t) <= 0):
            raise ValueError("its layers do not go down")
        v = np.array(v, dtype=np.float32, order="C")      # its own: the model works in place
        sa, sb = steps[a], steps[b]
        corners = np.array([origin[:2], origin[:2] + n[a] * sa[:2], origin[:2] + n[b] * sb[:2],
                            origin[:2] + n[a] * sa[:2] + n[b] * sb[:2]])
        # what the velocity is, by its kind — set in the session, else the
        # file's; the name never decides (app/features/property_types)
        kind_of = getattr(ctx, "property_kind_of", None)
        kind = (kind_of(leaf) if kind_of is not None else tree.find_attribute_value(leaf, "propertyKind")) or ""
        reading = property_types.velocity_reading(kind)
        pos_of = getattr(ctx, "property_position_of", None)
        at = pos_of(leaf) if pos_of is not None else property_types.DEFAULT_POSITION
        how = f"an {reading} velocity"
        if reading == "rms":
            how = "an RMS velocity, made interval velocities by Dix's formula, not smoothed"
        ztop, stands, replaced = read_velocities(v, t, reading, property_types.POSITIONS[at])
        cube = Cube(corners[:, 0].min(), corners[:, 0].max(), corners[:, 1].min(), corners[:, 1].max(),
                    n[a], n[b], t, v, ztop=ztop, frame=(origin[0], origin[1], sa[0], sa[1], sb[0], sb[1]),
                    average=reading == "average", at=stands)
        kind = kind or "no kind"
        title = tree.find_rep_title(rid) or tree.find_title(rid) or "grid"
        letters = "IJK"
        note = (f"{title} read as it is: {n[a]} × {n[b]} columns ({letters[a]}, {letters[b]}),"
                f" {n[vertical]} layers along {letters[vertical]}, {t[0]:g} to {t[-1]:g} ms;"
                f" velocity: {name} (kind: {kind}, its values at the {at} of their cells),"
                f" read as {how}"
                + (f"; above {t[0]:g} ms its first velocity carries on up to time 0" if ztop is not None else "")
                + (f"; {replaced} cell(s) held no velocity and took the nearest one of their column"
                   if replaced else ""))
        properties = [{"value": tree.find_path(p), "label": tree.find_title(p)} for p in _properties(tree, rid)]
        return types.SimpleNamespace(cube=cube, title=title, source=f"{rep_path.rsplit('/', 1)[-1]}:{name}",
                                     rep_path=rep_path, name=name, kind=kind, note=note, path=tree.find_path(leaf),
                                     at=at, reading=reading, properties=properties)

    def _from_grid_as_is(path):
        """The grid read as it is as a model of its own, active; the model
        made in the card stays in the list (the PO, 12/11)."""
        _busy("Building the velocity model…")
        try:
            _set_as_is(path)
        finally:
            _busy("")

    def _set_as_is(path):
        grid = _grid_as_is(path)
        known = models.of_source(grid.source)
        if known is not None and known != models.current:
            _activate(known)
            return
        if held.get("data") and held["data"] == grid.rep_path:
            models.retitle(grid.title, grid.source)
        elif known is None:
            left = models.current
            models.add(grid.title, grid.source)
            _tell_tree(left)
        m = held["model"]
        c = grid.cube
        m.extent = (c.x0, c.x1, c.y0, c.y1)
        m.nx, m.ny, m.nz = c.nx, c.ny, c.layers
        m.trange = (float(c.t[0]), float(c.t[-1]))
        # what makes this model is named, not hashed: 380 MB of a 90 M cell grid
        held.update(data=grid.rep_path, cube=c, sig=f"data:{grid.source}:{grid.kind}:{grid.at}", note=grid.note,
                    touched=True,
                    extent_auto=False, prefilled="", active=0,
                    velocity={"path": grid.path, "name": grid.name, "kind": grid.kind, "at": grid.at,
                              "reading": grid.reading, "properties": grid.properties})
        held["rev"] += 1
        held["key"] = f"tdl:{held['rev']}"
        domain_convert.register_cube(held["key"], c)
        print(f"[fespp] journal time-depth law: {grid.title} read as it is, {grid.name} as the velocity", flush=True)
        changed()
        # the velocity chosen is the one shown: its eye opens on the grid in
        # the view in use (an eye moved afterwards changes nothing here)
        vid = _view_in_use()
        if vid and getattr(core, "eyes", None):
            others = {p["value"] for p in grid.properties} - {grid.path}
            now = list(core.eyes.get(vid))
            want = [p for p in now if p not in others]
            if grid.path not in want:
                want.append(grid.path)
            if want != now:
                core.eyes.set(vid, want)

    def _kind_changed(path):
        """A property typed anew: the grid read as it is reads its velocity
        again when that property is the one it reads."""
        rep = held.get("data")
        tree = _tree()
        nid = tree.find_node_id(path) if rep and tree is not None else None
        if nid is None or tree.find_path(tree.find_representation_node(nid)) != rep:
            return
        if (models.active() or {}).get("from") != f"{rep.rsplit('/', 1)[-1]}:{tree.find_title(nid)}":
            return
        try:
            _from_grid_as_is(path)
        except (NotRead, ValueError, TypeError, AttributeError) as exc:
            _note_refused(exc)

    ctx.property_kind_listeners = list(getattr(ctx, "property_kind_listeners", None) or []) + [_kind_changed]

    def _from_grid(path):
        """A model made from a loaded grid: the active one while nobody
        touched it, a new one otherwise; the model taken from this velocity
        already is made active instead. A grid the editable model cannot
        hold is read as it is."""
        import numpy as np
        _tree_, _rid, rep, ds = _structured_of(path)
        if _as_is_needed(ds) or _in_time(rep):
            _from_grid_as_is(path)
            return
        grid = _grid_cube(path)
        t, v = grid.times, grid.v
        nk, nj, ni = v.shape
        known = models.of_source(grid.source)
        if known is not None:
            _activate(known)
            return
        left = None
        if models.current is None or held["touched"]:
            left = models.current
            models.add(grid.title, grid.source)
        else:
            models.retitle(grid.title, grid.source)
        m = held["model"]
        vmean = float(np.mean(v)) or DEFAULT_V_FALLBACK
        law = Law([(grid.surface + vmean * (t[-1] - t[0]) / 2000.0, t[-1])], start=(grid.surface, t[0]))
        m.columns = [Column(law, (grid.extent[0] + grid.extent[1]) / 2, (grid.extent[2] + grid.extent[3]) / 2)]
        m.extent = grid.extent
        m.nx, m.ny, m.nz = ni, nj, nk
        m.trange = (float(t[0]), float(t[-1]))
        m.cells = {(k, j, i): float(v[k, j, i]) for k in range(nk) for j in range(nj) for i in range(ni)}
        m.cells_shape = (nk, nj, ni)
        held.update(active=0, prefilled="", extent_auto=False, draft=[None, None, None, None], touched=True)
        dt = np.diff(t)
        uneven = (" — its layers are not even: the velocity model's are, the velocities taken layer by layer"
                  if not np.allclose(dt, dt[0], rtol=0, atol=1e-6 * max(1.0, abs(t[-1]))) else "")
        read = " — in depth in the file, read in two-way time" if grid.in_depth else ""
        held["note"] = (f"the velocity model of {grid.title}: {ni} × {nj} × {nk} cells, {grid.name} as the velocity,"
                        f" {t[0]:g} to {t[-1]:g} ms{uneven}{read}")
        print(f"[fespp] journal time-depth law: the velocity model taken from {grid.title} ({grid.name})", flush=True)
        changed()
        _tell_tree(left)

    def _tell_tree(left):
        hook = getattr(ctx, "time_depth_tree_left", None)
        if left is not None and hook is not None:
            hook(left)

    def _activate(mid):
        """Model `mid` is the one the conversions use from now on."""
        left = models.current
        if not models.switch(mid):
            return
        domain_convert.register_cube(held["key"], held["cube"])
        print(f"[fespp] journal time-depth law: the active velocity model is {models.active()['name']}", flush=True)
        if not zone_follows():
            changed()
        _tell_tree(left)

    def _new():
        """The view shows the inputs of a model to generate; the model left
        for them goes on converting."""
        left = models.current
        if not models.to_draft():
            return
        print(f"[fespp] journal time-depth law: the inputs of a new velocity model, {models.entry(left)['name']}"
              " still converts", flush=True)
        if not zone_follows():
            changed()
        # blank inputs stand on the files' zone, as those the view opens on
        ensure_zone = getattr(ctx, "time_depth_ensure_zone", None)
        if ensure_zone is not None:
            ensure_zone()
        _tell_tree(left)

    def _note_refused(error):
        held["note"] = held["refusal"] = f"not taken as the velocity model: {error}"
        held["refused"] += 1
        print(f"[fespp] time-depth law: a grid not taken as the velocity model ({error})", flush=True)
        publish()

    def _adopt(row):
        """A lattice grid of the files chosen in the card: taken at once when
        its velocity is read; otherwise that velocity alone is read first, and
        unticked again once taken: the model's own row stands for it."""
        try:
            _from_grid(row)
            return
        except NotRead as exc:
            print(f"[fespp] time-depth law: {row} read first ({exc})", flush=True)
        except (ValueError, TypeError, AttributeError) as exc:
            _note_refused(exc)
            return
        tree = _tree()
        nid = tree.find_node_id(row)
        leaf = (nid if node_facts.is_property_kind(tree.find_type(nid) or "")
                else _velocity_of(tree, tree.find_representation_node(nid)))
        selected = list(getattr(state, "selected_paths", None) or [])
        path = tree.find_path(leaf) if leaf is not None else row
        if path in selected:
            _note_refused("its velocity is ticked, yet the reader never brought the values in")
            return
        waiting["grid"] = {"row": row, "path": path, "before": selected}
        _busy(f"Reading {tree.find_title(leaf) if leaf is not None else 'the velocity'} for the velocity model…")
        controller.select_paths(selected + [path])

    def _adopt_when_read(changed_key):
        """The read of a grid chosen in the card ended: taken, or the card says
        why not."""
        grid = waiting["grid"]
        if grid is None or getattr(state, "ui_loading", False):
            return
        _busy("")
        if grid["path"] not in (getattr(state, "selected_paths", None) or ()):
            waiting["grid"] = None
            _note_refused("its velocity was not read")
            return
        try:
            _from_grid(grid["row"])
        except NotRead as exc:
            if changed_key == "ui_loading":
                waiting["grid"] = None
                _note_refused(exc)
            return
        except (ValueError, TypeError, AttributeError) as exc:
            waiting["grid"] = None
            _note_refused(exc)
            return
        waiting["grid"] = None
        if held.get("data"):
            return      # a grid read as it is is the model
        now = list(getattr(state, "selected_paths", None) or [])
        kept = [p for p in now if p in grid["before"] or not node_facts.is_under(p, [grid["row"]])]
        if kept != now:
            controller.select_paths(kept)

    def _candidate(row):
        """A lattice grid of the files that can be chosen in the card:
        {value, label}, None when it is a model of the session already, or
        was taken."""
        tree = _tree()
        owner = getattr(ctx, "time_depth_tree_owner", None)
        nid = tree.find_node_id(row) if tree is not None else None
        rid = tree.find_representation_node(nid) if nid is not None else None
        if rid is None or (owner is not None and owner(row) is not None):
            return None
        taken = tree.find_path(rid).rsplit("/", 1)[-1] + ":"
        if any(str(e.get("from") or "").startswith(taken) for e in models.entries):
            return None
        return {"value": row, "label": tree.find_rep_title(rid) or tree.find_title(rid) or row}

    def options():
        """What the view's list offers: the inputs of a new model, the
        session's models, then the lattice grids of the files."""
        out = [{"value": NEW, "label": "New velocity model"}]
        out += [{"value": f"m{e['id']}", "label": e["name"]} for e in models.entries]
        return out + [c for c in map(_candidate, getattr(state, "ui_cube_grid_rows", None) or ()) if c]

    def pick_property(path):
        """The card's property of a grid read as it is: its velocity from now on."""
        if held.get("data") and path:
            _adopt(str(path))

    def again(saved):
        """A session's model of the data put back: `saved` {data, velocity,
        from} — its grid's row, the property it read as its velocity (the
        one titled as `from` says when the document is older) — read as it is
        again: at once when the values are in, once the session's reads end
        otherwise, the velocity ticked here when the session does not read it."""
        tree = _tree()
        rid = tree.find_node_id(str(saved.get("data") or "")) if tree is not None else None
        row = str(saved.get("velocity") or "")
        if rid is not None and (not row or tree.find_node_id(row) is None):
            title = str(saved.get("from") or "").partition(":")[2]
            row = next((tree.find_path(p) for p in _properties(tree, rid) if tree.find_title(p) == title),
                       tree.find_path(rid))
        if not row or tree is None or tree.find_node_id(row) is None:
            _note_refused("the grid of the session's velocity model is not in the loaded data")
            return
        selected = list(getattr(state, "selected_paths", None) or [])
        if row not in selected:
            _adopt(row)
            return
        waiting["grid"] = {"row": row, "path": row, "before": selected}
        _adopt_when_read("the read")

    def pick(value):
        """The view's 3D grid: the inputs of a new model ("new"), a model of
        the session ("m<id>") or a grid's row."""
        value = str(value or "")
        mine = value == NEW or (value[:1] == "m" and value[1:].isdigit())
        if mine and waiting["grid"] is not None:
            # a grid still being read to become the model is no longer the choice
            waiting["grid"] = None
            _busy("")
        if value == NEW:
            _new()
        elif mine:
            _activate(int(value[1:]))
        elif value:
            _adopt(value)

    lattice = {"uuids": None}

    def _lattice_rows():
        """The rows of the tree's IJK grids whose geometry is a lattice, their
        container's path each, what is no use to offer aside
        (`ctx.time_depth_tree_unoffered`): read on the query channel from the
        grid's XML (a `Point3dLatticeArray` under its Geometry), one request
        for the lot."""
        tree = _tree()
        if tree is None or getattr(tree, "_data_assembly", None) is None:
            return []
        try:
            q = query()
            grids = [e["uuid"] for e in (q.index() or ()) if e.get("type") == "IjkGridRepresentation"]
            xml = xml_of(q, grids)
        except Exception as exc:
            print(f"[fespp] time-depth law: the grids' geometry not read ({exc!r})", flush=True)
            return []
        own = getattr(ctx, "time_depth_tree_unoffered", None)
        mine = set(own() if own is not None else ())
        rows, uuids = [], []
        for uuid, text in xml.items():
            if "Point3dLatticeArray" not in (text or ""):
                continue
            nid = tree.find_node_id_by_uuid(uuid)
            cid = tree.find_parent_node_id_with_type(nid, "GridContainer") if nid is not None else None
            path = tree.find_path(cid if cid is not None else nid) if nid is not None else None
            if path and path not in mine:
                rows.append(path)
                uuids.append(uuid)
        lattice["uuids"] = uuids
        return sorted(rows)

    def _lattice_uuids():
        """The uuids of those grids, as last listed."""
        if lattice["uuids"] is None:
            _lattice_rows()
        return list(lattice["uuids"] or ())

    def lattice_rows_publish(**_):
        rows = _lattice_rows()
        tree = _tree()
        if tree is not None:
            # what files a row under Seismic, for whatever sorts by family
            tree.lattice_rows = frozenset(rows)
        if rows != list(getattr(state, "ui_cube_grid_rows", None) or []):
            state.ui_cube_grid_rows = rows
            publish()

    @controller.set("time_depth_from_grid")
    def time_depth_from_grid(path):
        """The tree's "Use as velocity model" on a grid or one of its
        properties (app/views/widgets/data_tree, app/features/panels). On the
        row of a model of the session, that model becomes active."""
        owner = getattr(ctx, "time_depth_tree_owner", None)
        mid = owner(str(path or "")) if owner is not None else None
        if mid is not None:
            _activate(mid)
            return
        try:
            _from_grid(str(path or ""))
        except (ValueError, TypeError, AttributeError) as exc:
            _note_refused(exc)

    on_change = getattr(state, "change", None)
    if callable(on_change):      # trame's state; a test's plain dict has none
        # the lattice grids of the tree, as the server's tree changes (an
        # ETP read lists objects first and reads them when ticked)
        on_change("assembly_rev", "lazy_rev")(lattice_rows_publish)
        on_change("ui_loaded_array_paths", "selected_paths")(lambda **_: _adopt_when_read("the read"))
        on_change("ui_loading")(lambda **_: _adopt_when_read("ui_loading"))

    ctx.time_depth_model_id = lambda: models.current
    ctx.time_depth_converting_id = models.converting
    ctx.time_depth_models = models.listing
    ctx.time_depth_model_uuids = lambda mid: (models.entry(mid) or {}).get("uuids")
    ctx.time_depth_cube_grid_rows = _lattice_rows
    ctx.time_depth_lattice_uuids = _lattice_uuids
    ctx.time_depth_publish_grid_rows = lattice_rows_publish
    return types.SimpleNamespace(options=options, pick=pick, pick_property=pick_property, again=again)
