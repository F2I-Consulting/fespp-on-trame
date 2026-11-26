"""fespp_pool — sessions ready before anyone asks (S3, first slice; a trial).

Two processes, one file, the launcher's config.json as their one source:

  pvpython fespp_pool.py template CFG   the TEMPLATE: imports ParaView, the
        FESPP plugin, trame and the application once, then keeps
        FESPP_POOL_SIZE forked children READY — the application started on
        its own port, waiting for a client. It reads their output, marks a
        child ready on trame's "App running at", reaps the ones that exit
        and forks again. No thread, no event loop: a fork must find nothing
        to inherit but the imports.

  python fespp_pool.py launcher CFG     the HTTP front wslink's launcher used
        to be (same routes, same answer): POST /paraview hands a ready
        session over at once — no spawn, no one-second polling — and writes
        the Apache mapping; GET and DELETE as before.

They meet on the filesystem (POOL_DIR): ready/<port>.json, moved to
taken/<id>.json by the launcher; the mapping file is rewritten from taken/.
Measured on 21/10 (S0): a child is ready 2.8 s after its fork, costs 205 MB
of its own while waiting (the ParaView, plugin and Python pages are shared)
and the browser reaches the 3D view 2.7 s after the page, instead of 5.7
to 8 s through a spawn.
"""
import importlib
import json
import os
import re
import secrets
import select
import sys
import time
import uuid
import warnings

POOL_DIR = os.environ.get("FESPP_POOL_DIR", "/tmp/fespp_pool")
READY_DIR = os.path.join(POOL_DIR, "ready")
TAKEN_DIR = os.path.join(POOL_DIR, "taken")
READY_LINE = b"App running at"


def say(msg):
    os.write(1, f"[pool {os.getpid()}] {msg}\n".encode())


def load_config(path):
    """The launcher's config.json (wslink's layout; `//` comments allowed)."""
    text = open(path, encoding="utf-8").read()
    text = re.sub(r"(?m)^\s*//.*$", "", text)
    return json.loads(text)


def cmd_option(cmd, flag):
    return cmd[cmd.index(flag) + 1] if flag in cmd else None


def ensure_dirs():
    for d in (READY_DIR, TAKEN_DIR):
        os.makedirs(d, exist_ok=True)


def write_record(path, rec):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rec, f)
    os.replace(tmp, path)


def read_records(d):
    out = []
    for name in sorted(os.listdir(d)):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(d, name), encoding="utf-8") as f:
                out.append((name, json.load(f)))
        except (OSError, ValueError):
            continue
    return out


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def write_mapping(proxy_file, host, sessions):
    """The Apache RewriteMap: one `<id> <host>:<port>` line per live child,
    ready or taken — written by the template alone, in place, as wslink
    does (the file keeps its owner, group and mode; Apache re-reads it on
    its mtime). A session's id is given at its fork and written here
    before it is ready: the application reads its own id off this file at
    start (engine/io/upload_endpoint), to build its /api/<id>/upload URL."""
    with open(proxy_file, "w", encoding="utf-8") as f:
        f.writelines(f"{sid} {host}:{port}\n" for sid, port in sessions)


def prune_taken():
    """Drop the taken records whose session has exited."""
    gone = [n for n, rec in read_records(TAKEN_DIR) if not alive(rec.get("pid", -1))]
    for n in gone:
        try:
            os.remove(os.path.join(TAKEN_DIR, n))
        except OSError:
            pass
    return gone


def take_ready():
    """The oldest ready session, moved to taken/ under the id the template
    gave it — the rename is the lock: two requests cannot take the same
    one. None when none is ready."""
    recs = sorted(read_records(READY_DIR), key=lambda nr: nr[1].get("since", 0))
    for name, rec in recs:
        if not alive(rec.get("pid", -1)):
            try:
                os.remove(os.path.join(READY_DIR, name))
            except OSError:
                pass
            continue
        sid = rec["id"]
        try:
            os.rename(os.path.join(READY_DIR, name), os.path.join(TAKEN_DIR, f"{sid}.json"))
        except OSError:
            continue
        rec = dict(rec, taken=time.time())
        write_record(os.path.join(TAKEN_DIR, f"{sid}.json"), rec)
        return rec
    return None


def single():
    """One session for the whole machine (FESPP_POOL_SINGLE=1, the public
    demo): a tab closed then opened again finds its session and its data
    (until the session's idle timeout), and a visitor cannot open fifty."""
    return os.environ.get("FESPP_POOL_SINGLE", "") not in ("", "0")


def live_taken():
    """The newest taken session still running, or None."""
    prune_taken()
    recs = sorted(read_records(TAKEN_DIR), key=lambda nr: nr[1].get("taken", 0))
    return recs[-1][1] if recs else None


def session_to_hand():
    """(session, again) for a browser asking: in single mode the session
    already taken when one lives (again=True), else the oldest ready one,
    taken (None when none is ready)."""
    if single():
        held = live_taken()
        if held is not None:
            return held, True
    return take_ready(), False


def counts():
    """{ready, taken}: the pool as the records say it."""
    return {"ready": len([n for n in os.listdir(READY_DIR) if n.endswith(".json")]),
            "taken": len([n for n in os.listdir(TAKEN_DIR) if n.endswith(".json")])}


# ----------------------------------------------------------------- template

def run_template(cfg_path):
    cfg = load_config(cfg_path)
    conf = cfg["configuration"]
    app = cfg["apps"]["trame"]
    plugin = cmd_option(app["cmd"], "--fespp-plugin-path")
    epc = cmd_option(app["cmd"], "--local-epc-file-path")
    host = cfg["resources"][0]["host"]
    lo, hi = cfg["resources"][0]["port_range"]
    log_dir = conf["log_dir"]
    proxy_file = conf["proxy_file"]
    size = int(os.environ.get("FESPP_POOL_SIZE", "2"))
    # a ready session older than this is replaced: a fresh fork keeps the
    # GL context and the memory of a waiting session as they were measured
    max_age = float(os.environ.get("FESPP_POOL_MAX_AGE", "3600"))
    # the template holds VTK's two threads at the fork; Python warns of a
    # deadlock risk in the child — none seen (S0, the trial), and the line
    # would fill the log at every fork
    warnings.filterwarnings("ignore", message=".*multi-threaded.*", category=DeprecationWarning)
    ensure_dirs()
    os.makedirs(log_dir, exist_ok=True)
    for d in (READY_DIR, TAKEN_DIR):
        for n in os.listdir(d):
            os.remove(os.path.join(d, n))
    children = {}      # pid -> {id, port, secret, fd, buf, ready, log, born}

    def mapping():
        write_mapping(proxy_file, host, [(c["id"], c["port"]) for c in children.values()])

    mapping()

    t = time.perf_counter()
    from paraview import simple
    simple.LoadPlugin(plugin)
    for module in ("paraview.web.venv", "trame.app", "fespp_on_trame.app.boot", "fespp_on_trame.__main__"):
        importlib.import_module(module)
    say(f"template ready in {time.perf_counter() - t:.2f}s; keeping {size} session(s) ready"
        f" on {host}:{lo}-{hi}")

    def ports_in_use():
        used = {c["port"] for c in children.values()}
        used |= {rec["port"] for _n, rec in read_records(TAKEN_DIR)}
        return used

    def fork_child():
        used = ports_in_use()
        port = next((p for p in range(lo, hi + 1) if p not in used), None)
        if port is None:
            say("no free port: the pool waits")
            return
        secret = secrets.token_hex(24)
        # random, not time-based as wslink's: not guessable from the clock
        sid = str(uuid.uuid4())
        r, w = os.pipe()
        pid = os.fork()
        if pid == 0:
            # the child: its output to the parent's pipe, then the application
            os.close(r)
            os.dup2(w, 1)
            os.dup2(w, 2)
            os.close(w)
            sys.argv = ["fespp_on_trame", "--server", "--host", host, "--port", str(port),
                        "--authKey", secret, "--fespp-plugin-path", plugin]
            if epc:
                sys.argv += ["--local-epc-file-path", epc]
            # how long a session lives with no browser on it (wslink's
            # --timeout, 300 s): a session created by REST and loading a
            # store for minutes before a browser attaches needs more
            if os.environ.get("FESPP_SESSION_IDLE"):
                sys.argv += ["--timeout", os.environ["FESPP_SESSION_IDLE"]]
            try:
                import fespp_on_trame.__main__ as main_module
                main_module.main()
                os._exit(0)
            except BaseException as exc:  # noqa: BLE001 — the child dies with its reason
                os.write(2, f"[pool child] exit on {exc!r}\n".encode())
                os._exit(1)
        os.close(w)
        log = open(os.path.join(log_dir, f"pool-{port}-{pid}.txt"), "ab", buffering=0)
        children[pid] = {"id": sid, "port": port, "secret": secret, "fd": r, "buf": b"",
                         "ready": False, "log": log, "born": time.time()}
        # on the map before it is ready: the child reads its id there at start
        mapping()
        say(f"forked session {pid} on port {port} as {sid}")

    def drop(pid, status):
        c = children.pop(pid, None)
        if c is None:
            return
        try:
            os.close(c["fd"])
        except OSError:
            pass
        c["log"].close()
        try:
            os.remove(os.path.join(READY_DIR, f"{c['port']}.json"))
        except OSError:
            pass
        for n, rec in read_records(TAKEN_DIR):
            if rec.get("pid") == pid:
                try:
                    os.remove(os.path.join(TAKEN_DIR, n))
                except OSError:
                    pass
        mapping()
        say(f"session {pid} on port {c['port']} exited (status {status})")

    while True:
        # the children that exited
        while True:
            try:
                pid, status = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                break
            if pid == 0:
                break
            drop(pid, status)
        # their output: relayed to their log, watched for the ready line
        fds = {c["fd"]: pid for pid, c in children.items()}
        if fds:
            readable, _w, _x = select.select(list(fds), [], [], 0.25)
        else:
            readable = []
            time.sleep(0.25)
        for fd in readable:
            c = children.get(fds[fd])
            if c is None:
                continue
            try:
                data = os.read(fd, 65536)
            except OSError:
                data = b""
            if not data:
                continue
            c["log"].write(data)
            if not c["ready"]:
                c["buf"] = (c["buf"] + data)[-4096:]
                if READY_LINE in c["buf"]:
                    c["ready"] = True
                    write_record(os.path.join(READY_DIR, f"{c['port']}.json"),
                                 {"id": c["id"], "port": c["port"], "secret": c["secret"],
                                  "pid": fds[fd], "since": time.time()})
                    say(f"session {fds[fd]} ready on port {c['port']}"
                        f" ({time.time() - c['born']:.1f}s after its fork)")
        # the taken ones whose client left: pruned here too, the launcher
        # may be idle
        prune_taken()
        # a ready session too old goes (its record first, so that no client
        # gets it meanwhile); the reap below drops it, the refill replaces it
        now = time.time()
        for pid, c in list(children.items()):
            if c["ready"] and now - c["born"] > max_age:
                try:
                    os.remove(os.path.join(READY_DIR, f"{c['port']}.json"))
                except OSError:
                    continue      # taken since: it is a client's now
                try:
                    os.kill(pid, 15)
                except OSError:
                    pass
                say(f"session {pid} on port {c['port']} waited {max_age:.0f}s: replaced")
        # keep the pool full: ready plus still starting
        starting = sum(1 for c in children.values() if not c["ready"])
        ready = counts()["ready"]
        while ready + starting < size:
            fork_child()
            starting += 1


# ----------------------------------------------------------------- the REST front's spec

# ------------------------------------------------------------ the API's words
# the document's schema as Swagger UI shows it in the POST blocks: the keys
# a document written by hand uses, each one said. A saved session carries
# more (GET …/state writes them), applied as they are.
_PATH = {"type": "string",
         "description": "an object: its path in the loaded data, or uuid:<uuid> (looked up)"}
_PATHS = {"type": "array", "items": _PATH}

# `stats` is an older document's word for `compare`, the Statistics view
VIEW_KINDS = ["render", "globe", "compare", "stats", "welllog", "reconcile", "health", "xml",
              "values", "timedepth", "stratigraphy", "calculator", "assistant"]

VIEW_SCHEMA = {
    "type": "object",
    "required": ["kind"],
    "additionalProperties": True,
    "description": "one view: a 3D view (kind render), the Globe (kind globe, one per session, "
                   "the keys of a 3D view and globe_state) or an analysis panel. The keys below are "
                   "the ones a document written by hand uses; a saved session carries more "
                   "(GET …/state shows them), applied as they are.",
    "properties": {
        "kind": {"type": "string", "enum": VIEW_KINDS,
                 "description": "compare is the Statistics view; stats, an older document's word for it, "
                                "is still read; distribution and crossplot, kinds that are gone, are "
                                "skipped and said"},
        "id": {"type": "string", "description": "a saved panel's id; optional in a document"},
        "title": {"type": "string"},
        "place": {"type": "string", "enum": ["right", "below"],
                  "description": "split from the view before it in the document; absent: a tab. "
                                 "A panel already open stays where it is."},
        "eyes": {**_PATHS, "description": "render: what the view shows; absent, the view keeps its own"},
        "active_path": {**_PATH, "description": "render: the active node (its cards, its colour)"},
        "rep_style": {"type": "string",
                      "description": "render: Surface, Surface With Edges, Wireframe, Points, Feature Edges"},
        "flat_colors": {"type": "boolean", "description": "render: the exact colours, no shading"},
        "interaction_mode": {"type": "string", "enum": ["3D", "2D"], "description": "render: 3D or 2D (map)"},
        "tree_layout": {"type": "string", "enum": ["flat", "by_interpretation", "by_feature_and_interpretation", "kind"],
                        "description": "render: how its data tree lays out the forest (`tree_kind` true in an "
                                       "older document reads as kind); compare: its docked tree's layout, kind "
                                       "(the default) or the session's tree layout; welllog: flat (the default) "
                                       "or kind"},
        "own_domain": {**_PATHS, "description": "the objects kept in their own vertical domain in this "
                                                "view, not drawn converted in the other"},
        "domain": {"type": "string", "enum": ["depth", "time"],
                   "description": "render: the vertical domain drawn; an object of the other one is drawn "
                                  "converted by the time-depth model"},
        "z_scale": {"type": "number", "minimum": 0.01, "maximum": 100, "example": 3.0,
                    "description": "render: the view's vertical exaggeration; absent, it keeps its own"},
        "hidden": {"type": "boolean",
                   "description": "render: hidden from the top bar's 3D views door — out of the screen, its "
                                  "objects, camera and cards kept; absent, shown"},
        "opacities": {"type": "object", "additionalProperties": {"type": "number", "minimum": 0, "maximum": 1},
                      "description": "render: {representation path: opacity} of the objects made see-through "
                                     "while a property paints them"},
        "solid_opacities": {"type": "object", "additionalProperties": {"type": "number", "minimum": 0, "maximum": 1},
                            "description": "render: the same while they are drawn in their solid color; absent, "
                                           "\"opacities\" holds for both"},
        "time": {"type": "object", "description": "render: the view's time step",
                 "properties": {"index": {"type": "integer"}, "speed": {"type": "number"}}},
        "camera": {"type": "object", "description": "render, stratigraphy (its model's 3D): ParaView's "
                                                    "camera (position, focal point, view up, angle, "
                                                    "pivot) as GET …/state writes it"},
        "grids": {"type": "array", "items": {"type": "object"},
                  "description": "render: per grid, the slicers (IJK ranges and positions), "
                                 "the threshold chain, the NaN mask (`hide_nan`; `nan_shown`: its NaN cells "
                                 "shown by hand, a grid painted by a property holding NaN hiding them by default)"},
        "tables": {"type": "array", "items": {"type": "object"}, "description": "render: the colour tables"},
        "cards": {"type": "object", "description": "render: the open cards and their place"
                  " (`open`, `geometry`; `layout`, where they stand in the view's dock); the tree's"
                  " cards are `tree` (Reservoir), `tree_surface`, `tree_well` and `tree_seismic`"
                  " (the lattice IJK grids)"},
        "globe": {"type": "boolean", "description": "render, an older document: true reads the view as "
                                                     "the Globe"},
        "globe_state": {"type": "object", "description": "globe: its typed EPSG code, its framing, the "
                                                         "Earth's opacity"},
        "extracts": {"type": "array", "items": {"type": "object"},
                     "description": "render: the selection extracts {path, rep_path, row, mode, cells, invert, "
                                    "field, title, visible}, made again; path is the name it was saved under, "
                                    "it comes back under another"},
        "items": {"type": "array", "description": "compare: the properties it holds, one row each; a row "
                                                  "follows the session's default realization and current "
                                                  "time unless it names them",
                  "items": {"type": "object", "required": ["path"], "properties": {
                      "path": _PATH,
                      "uid": {"type": "string",
                              "description": "its name in kinds (baseline, xplot_x, xplot_y); a new one is given "
                                             "on reading"},
                      "real": {"type": "integer", "nullable": True, "description": "the realization it reads"},
                      "ts": {"type": "integer", "nullable": True, "description": "the time step it reads"},
                      "pinned": {"type": "boolean", "description": "a row pinned beside the property's own"}}}},
        "parts": {**_PATHS, "description": "compare: the parts of a grid (sub-representations, blocked "
                                           "wellbores) whose rows follow the items of their grid; what the "
                                           "session does not read yet is read; an extract comes back with "
                                           "its 3D view"},
        "tab": {"type": "string", "description": "compare: the kind shown, one tab per property kind"},
        "kinds": {"type": "object", "additionalProperties": {"type": "object"},
                  "description": "compare: per kind, {baseline, sort_key, sort_asc, visible_metrics, "
                                 "xplot_x, xplot_y, dist_opts} as GET …/state writes it; what is absent "
                                 "is the default"},
        "tree_open": {"oneOf": [{"type": "boolean"},
                                {"type": "array", "items": {"type": "string",
                                                            "enum": ["Reservoir", "Surface", "Well", "Seismic", "Other"]}}],
                      "description": "welllog: its docked tree is open; compare, reconcile: the family "
                                     "cards of its tree that are open (true in an older document: the first "
                                     "family the file holds)"},
        "pinned": {**_PATHS, "description": "stats (an older document): the properties pinned"},
        "wells": {**_PATHS, "description": "welllog: the wells shown"},
        "align": {"type": "string", "enum": ["TVD", "MD"],
                  "description": "welllog: the depth every well is laid out on, regular true vertical depth "
                                 "(the default) or regular measured depth"},
        "markers_off": {"type": "array", "items": {"type": "string"},
                        "description": "welllog: the markers drawn dimmed, by name"},
        "column": {"type": "string", "description": "stratigraphy: the rank shown (its uuid); absent, the first"},
        "unit": {"type": "string", "nullable": True, "description": "stratigraphy: the unit marked"},
    },
}

_POINTS = {"type": "array", "description": "the points below the start, in depth order",
           "items": {"type": "object", "properties": {
               "depth": {"type": "number", "description": "m"},
               "twt": {"type": "number", "description": "two-way time, ms"}}}}

TIME_DEPTH_SCHEMA = {
    "type": "object",
    "description": "the time-depth model: columns, each a law at a position; it draws an object "
                   "in time in a view in depth. No column that converts: no velocity model, nothing "
                   "is converted; one: its law everywhere; several: the velocity model "
                   "the placed ones make. A document before 02/11 in \"1d\" mode (its `points`) "
                   "comes back as a first column. Present, it replaces every model of the session: "
                   "this one is the active one — or, with `generated` false, the inputs of one "
                   "not generated, the model of `others` marked `converting` still the one the "
                   "conversions read —, `others` the rest; a model absent from the document is gone",
    "properties": {
        "name": {"type": "string", "description": "the model's name, its row in the Seismic tree; "
                                                  "\"Velocity model N\", N from 1, when absent"},
        "generated": {"type": "boolean", "description": "false: the inputs of a model not generated "
                                                        "(its TDLaws, its zone, its layers), kept for the "
                                                        "view; no grid is made of them and they convert "
                                                        "nothing. Absent on a model"},
        "converting": {"type": "boolean", "description": "on one of `others`, beside inputs not generated: "
                                                         "the model left for them, which the conversions "
                                                         "read until another is generated or chosen; the "
                                                         "last of `others` when none is marked"},
        "from": {"type": "string", "description": "the velocity it was taken from: "
                                                  "\"<its grid's node>:<its property>\""},
        "data": {"type": "string", "description": "a velocity model of the data, a lattice grid in time read "
                                                  "as it is: its grid (a path, or uuid:<its uuid>). It holds no "
                                                  "column; the grid's velocity is read again when the document "
                                                  "applies, and the card says so when the grid is not in the data"},
        "velocity": {"type": "string", "description": "with `data`: the property read as its velocity (a path, or "
                                                      "uuid:<its uuid>); the one its eye is on, else its first, "
                                                      "when absent"},
        "uuids": {"type": "object", "description": "the uuids of its grid in the tree (crs, grid, prop, hdf), "
                                                   "taken again when free: what the document ticks and shows "
                                                   "of the model finds it"},
        "others": {"type": "array", "items": {"type": "object"},
                   "description": "the session's other velocity models, each of this same form"},
        "columns": {"type": "array", "description": "the columns, each a law at a position",
                    "items": {"type": "object", "properties": {
                        "x": {"type": "number", "nullable": True, "description": "easting, the data's units"},
                        "y": {"type": "number", "nullable": True, "description": "northing"},
                        "name": {"type": "string"},
                        "source": {"type": "string", "description": "where its points came from: a well's "
                                                                   "time log or sonic, its markers on the "
                                                                   "time horizons, surface pairs"},
                        "start": {"type": "object", "description": "where the law starts, the zero "
                                                                   "(0 m, 0 ms) when absent: a datum",
                                  "properties": {"depth": {"type": "number", "description": "m"},
                                                 "twt": {"type": "number", "description": "two-way time, ms"}}},
                        "points": _POINTS}}},
        "extent": {"type": "array", "items": {"type": "number", "nullable": True}, "minItems": 4, "maxItems": 6,
                   "nullable": True,
                   "description": "velocity model: [x0, x1, y0, y1, t0, t1], its zone and the two-way "
                                  "times its layers cut, ms ([0, 5000] without them). It grows past "
                                  "the zone to the columns placed outside. The zone null: the loaded "
                                  "data's, else a square around the columns"},
        "extent_from": {"type": "string", "enum": ["data", "typed", "columns", "files"], "nullable": True,
                        "description": "where the zone came from: the objects ticked (it follows "
                                       "them), entered, or none (a square around the columns); "
                                       "\"files\", from a document before 03/11, is read as entered"},
        "prefilled": {"type": "string", "enum": ["wells", "sonic", "markers"],
                      "description": "the Pre-fill the columns were read by (its entry ticked in the "
                                     "menu): the vertical wells' time logs, their sonic logs, the "
                                     "markers on the time horizon of their interpretation; absent "
                                     "when the columns were entered"},
        "nx": {"type": "integer", "minimum": 1, "maximum": 200, "description": "velocity model: cells along x (100 when absent)"},
        "ny": {"type": "integer", "minimum": 1, "maximum": 200, "description": "velocity model: cells along y (100 when absent)"},
        "nz": {"type": "integer", "minimum": 1, "maximum": 200,
               "description": "velocity model: layers in K, even in two-way time over the extent's t0 to t1 (100 when absent)"},
        "cells": {"type": "array", "items": {"type": "array", "items": {"type": "number"}, "minItems": 4,
                                             "maxItems": 4},
                  "description": "the cells set by hand (the Values card's Map on the velocity model's "
                                 "grid), [k, j, i, m/s] each"},
        "cells_shape": {"type": "array", "items": {"type": "integer"}, "minItems": 3, "maxItems": 3,
                        "description": "[layers, ny, nx] of the velocity model the cells were set on: they apply "
                                       "while the velocity model keeps that shape"},
        "active": {"type": "integer", "description": "the column edited"},
    },
}

DOCUMENT_SCHEMA = {
    "type": "object",
    "description": "A session document (the .fespp.json format). Every group is optional: absent "
                   "leaves that part of the session as it is, present is the whole truth of its "
                   "part (views: [] closes every eye). Objects are named uuid:<uuid>. The ETP "
                   "store's token travels in the Authorization: Bearer header, never here.",
    "properties": {
        "schema": {"type": "integer", "description": "the document format, 1", "example": 1},
        "reset": {"type": "boolean",
                  "description": "empty the session first (nothing read, eyes closed; the panels stay open)"},
        "sources": {"type": "object", "description": "what is loaded", "properties": {
            "files": {"type": "array", "description": "EPC files", "items": {"type": "object", "properties": {
                "name": {"type": "string", "example": "drogon.epc"},
                "path": {"type": "string", "example": "private/drogon.epc",
                         "description": "the file on the server, under its open directory (/deploy/data)"},
                "size_mb": {"type": "number", "description": "written by GET …/state"}}}},
            "etp": {"type": "object", "nullable": True,
                    "description": "an OSDU / ETP store (its token in the Authorization header)",
                    "properties": {
                        "url": {"type": "string",
                                "example": "wss://admeinterop.energy.azure.com/api/reservoir-ddms-etp/v2/"},
                        "partition": {"type": "string", "example": "opendes"},
                        "dataspaces": {"type": "array", "items": {"type": "string"}, "example": ["demo/Volve"],
                                       "description": "plain names (demo/Volve) or URIs "
                                                      "(eml:///dataspace('demo/Volve'))"}}}}},
        "session": {"type": "object", "description": "what is read, and the session-wide settings",
                    "properties": {
                        "selected_paths": {**_PATHS, "description": "what is read, born hidden (each view's eyes "
                                                                    "say what it shows); present = the whole "
                                                                    "truth of the reads"},
                        "z_scale": {"type": "number", "example": 1.0,
                                    "description": "the vertical exaggeration of every 3D view; a view's own "
                                                   "`z_scale` wins. GET …/state writes it per view"},
                        "vector_components": {"type": "object", "additionalProperties": {"type": "string"},
                                              "description": "{property: component} for the vector properties"},
                        "property_kinds": {"type": "object", "additionalProperties": {"type": "string"},
                                           "description": "{property uuid: PWLS 4.0 kind} the kinds the reader "
                                                          "set (right-click Type…); the file's kind for the others"},
                        "property_positions": {"type": "object",
                                               "additionalProperties": {"enum": ["top", "centre", "bottom"]},
                                               "description": "{property uuid: where in its cell a velocity's "
                                                              "value stands}; top for the others"},
                        "object_colors": {"type": "object", "additionalProperties": {"type": "string"},
                                          "description": "{representation path: \"#rrggbb\"} the solid colours "
                                                         "the reader set (drawn where no property paints the "
                                                         "object, its chip in the tree)"},
                        "derived": {"type": "array", "items": {"type": "object"},
                                    "description": "the calculator's recipes {type, name, rep_path, expression, "
                                                   "uom, prop_kind, role, source, quantile, inputs}, made again"},
                        "wells": {"type": "object",
                                  "description": "how the wells are drawn in the 3D views; absent, left as they are",
                                  "properties": {
                                      "log_modes": {"type": "object",
                                                    "additionalProperties": {"enum": ["graph", "curve", "tube"]},
                                                    "description": "{log path: how it is drawn} — a filled graph "
                                                                   "on its hole when absent"},
                                      "log_width": {"type": "number",
                                                    "description": "the graphs' width as drawn (scene units); "
                                                                   "absent, taken from the first holes drawn"},
                                      "marker_scale": {"type": "number",
                                                       "description": "how many times as large as the reader makes "
                                                                      "them the markers are drawn (first 2.5)"},
                                      "marker_labels": {**_PATHS,
                                                        "description": "the markers whose name is written beside "
                                                                       "them"}}},
                        "time_depth_law": TIME_DEPTH_SCHEMA}},
        "objects": {"type": "object", "additionalProperties": {"type": "object"},
                    "description": "written by GET …/state: {path: {uuid, type, title, creation, last_update, "
                                   "version, format}}; on apply, an object that changed since is said"},
        "layout": {"type": "object", "nullable": True,
                   "description": "the panels' dockview layout, as a saved session writes it; a document "
                                  "written by hand places its views with `place` instead"},
        "views": {"type": "array", "items": VIEW_SCHEMA,
                  "description": "one paragraph per view; [] closes every eye"},
    },
}

_ADME = "wss://admeinterop.energy.azure.com/api/reservoir-ddms-etp/v2/"
DOCUMENT_EXAMPLES = {
    "adme_demo_volve": {
        "summary": "ADME demo/Volve: an object in the 3D view, another in Statistics on the right",
        "value": {"sources": {"etp": {"url": _ADME, "partition": "opendes", "dataspaces": ["demo/Volve"]}},
                  "session": {"selected_paths": ["uuid:9690445e-348a-4121-b8e4-952dfc96b285",
                                                 "uuid:5af3641f-5a55-43a9-bb31-d7f81ab0ba70"]},
                  "views": [{"kind": "render", "eyes": ["uuid:9690445e-348a-4121-b8e4-952dfc96b285"]},
                            {"kind": "compare", "place": "right",
                             "items": [{"path": "uuid:5af3641f-5a55-43a9-bb31-d7f81ab0ba70"}]}]}},
    "an_epc_file": {
        "summary": "An EPC under the server's open directory (drogon), a property shown on its grid",
        "value": {"sources": {"files": [{"name": "drogon.epc", "path": "private/drogon.epc"}]},
                  "session": {"selected_paths": ["uuid:0eb751ef-219b-4e1f-8e4e-06187f16e61a"]},
                  "views": [{"kind": "render", "eyes": ["uuid:0eb751ef-219b-4e1f-8e4e-06187f16e61a"]}]}},
    "close_every_eye": {"summary": "Close every eye, keep what is read", "value": {"views": []}},
    "z_scale": {"summary": "A Z exaggeration of 3, nothing else touched", "value": {"session": {"z_scale": 3}}},
    "velocity_model": {
        "summary": "A velocity model of two columns over a zone, put in the Seismic tree as a grid",
        "value": {"session": {"time_depth_law": {
            "name": "Velocity model 1",
            "extent": [0, 1000, 0, 500, 0, 3000], "nx": 20, "ny": 10, "nz": 12,
            "columns": [
                {"name": "W1", "x": 100, "y": 100,
                 "points": [{"depth": 1000, "twt": 1000}, {"depth": 2000, "twt": 1800}]},
                {"name": "W2", "x": 900, "y": 400,
                 "points": [{"depth": 1000, "twt": 950}, {"depth": 2000, "twt": 1700}]}]}}}},
    "reset": {"summary": "Empty the session", "value": {"reset": True}},
}

STATUS_SCHEMA = {
    "type": "object",
    "description": "the Session door's status: the report of an apply, or why a document was refused",
    "properties": {
        "phase": {"type": "string", "enum": ["waiting", "ready", "restoring", "done", "error"],
                  "description": "waiting: a source is not there yet (an ETP token to type); done: applied"},
        "report": {"type": "array", "items": {"type": "object", "properties": {
            "level": {"type": "string", "enum": ["ok", "warn", "error"]}, "text": {"type": "string"}}}},
        "error": {"type": "string", "description": "why the document was refused (400)"},
        "views": {"type": "integer"},
        "silent": {"type": "boolean", "description": "applied by the API: the door does not pop up"},
    },
}

# the native resources (engine/io/session_endpoint): what they take and answer
NATIVE_SCHEMAS = {
    "Uuids": {"type": "object", "required": ["uuids"], "properties": {
        "uuids": {"type": "array", "items": {"type": "string"},
                  "description": "the objects, by uuid (uuid:<uuid> and braces accepted)"},
        "show": {"type": "boolean", "default": True,
                 "description": "false: read only, the 3D view's eyes left as they are"}}},
    "ObjectRow": {"type": "object", "properties": {
        "uuid": {"type": "string", "nullable": True,
                 "description": "null for a calculator's derived property"},
        "type": {"type": "string", "description": "the object's type, as the data tree says it"},
        "title": {"type": "string"},
        "shown": {"type": "boolean", "description": "an eye open on it in the 3D view"},
        "loaded": {"type": "boolean", "description": "its data in the session (false while it is being read)"}}},
    "Objects": {"type": "object", "properties": {
        "view": {"type": "string", "description": "the 3D view spoken of"},
        "loading": {"type": "boolean", "description": "a read still running (POST/PUT ?wait= waits for its end)"},
        "objects": {"type": "array", "items": {"$ref": "#/components/schemas/ObjectRow"},
                    "description": "every object the session reads, in reading order"},
        "missing": {"type": "array", "items": {"type": "string"},
                    "description": "the uuids asked for that are not in the loaded data (or not read, for a DELETE)"}}},
    "ServerFile": {"type": "object", "required": ["path"], "properties": {
        "path": {"type": "string", "description": "an EPC under the server's open directory (/deploy/data)"}}},
    "EtpSource": {"type": "object", "required": ["url"], "properties": {
        "url": {"type": "string", "description": "the store's websocket URL"},
        "partition": {"type": "string", "description": "the data partition (OSDU)"},
        "dataspaces": {"type": "array", "items": {"type": "string"},
                       "description": "names (demo/Volve) or URIs (eml:///dataspace('demo/Volve')) to load"}}},
    "Sources": {"type": "object", "properties": {
        "files": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "size_mb": {"type": "number"},
            "failed": {"type": "boolean", "description": "handed to the reader, which could not read it"}}}},
        "etp": {"type": "object", "nullable": True, "properties": {
            "url": {"type": "string"}, "partition": {"type": "string"}, "connected": {"type": "boolean"},
            "dataspaces": {"type": "array", "items": {"type": "string"}, "description": "the dataspaces loaded"},
            "available": {"type": "array", "items": {"type": "string"},
                          "description": "the dataspaces the store lists, loaded or not"}}}}},
    "CatalogueRow": {"type": "object", "properties": {
        "uuid": {"type": "string"}, "type": {"type": "string"}, "title": {"type": "string"},
        "read": {"type": "boolean", "description": "the session reads it"},
        "shown": {"type": "boolean", "description": "an eye open on it in the 3D view"}}},
    "Catalogue": {"type": "object", "properties": {
        "view": {"type": "string"},
        "objects": {"type": "array", "items": {"$ref": "#/components/schemas/CatalogueRow"}},
        "total": {"type": "integer", "description": "the objects kept by the filters"},
        "truncated": {"type": "boolean", "description": "more than `limit`: the first ones only"}}},
    "Error": {"type": "object", "properties": {"error": {"type": "string"}}},
}

OBJECTS_EXAMPLES = {
    "a_property": {"summary": "A property of drogon, shown on its grid",
                   "value": {"uuids": ["0eb751ef-219b-4e1f-8e4e-06187f16e61a"]}},
    "read_only": {"summary": "Read, not shown",
                  "value": {"uuids": ["0eb751ef-219b-4e1f-8e4e-06187f16e61a"], "show": False}},
}

# the page's own door: its query, as `engine/session_query.py` reads it
PAGE_PARAMETERS = [
    {"name": "epc", "in": "query", "schema": {"type": "array", "items": {"type": "string"}}, "explode": True,
     "example": "private/drogon.epc",
     "description": "an EPC under the server's open directory (/deploy/data); repeat for several"},
    {"name": "etp", "in": "query", "schema": {"type": "string"}, "example": _ADME,
     "description": "an OSDU / ETP store's websocket URL; the Session door opens prefilled, the token to type"},
    {"name": "dataspace", "in": "query", "schema": {"type": "array", "items": {"type": "string"}},
     "explode": True, "example": "demo/Volve", "description": "the store's dataspaces to load; repeat for several"},
    {"name": "partition", "in": "query", "schema": {"type": "string"}, "example": "opendes",
     "description": "the store's data partition"},
    {"name": "uuid", "in": "query", "schema": {"type": "array", "items": {"type": "string"}}, "explode": True,
     "example": "64f0be3e-6177-4be6-a29c-95dbbefbf22a",
     "description": "the objects to read, shown in the first 3D view; repeat for several"},
    {"name": "state", "in": "query", "schema": {"type": "string", "format": "uri"},
     "description": "a whole document the server fetches at that http(s) address (2 MB at most); alone"},
]

API_DESCRIPTION = """Sessions ready before anyone asks, driven by two resources, **Sources** and **Objects**, or by **session documents** (the `.fespp.json` format).

**Sources and Objects.** What a host application needs, said by uuid: read an EPC (by its path under the server's open directory, or sent) or an ETP store's dataspaces, then show objects in the 3D view (`POST` adds, `PUT` is the whole of it, `DELETE` takes one or all away). Each answer is short and final: the objects read, each shown or not, and the uuids not in the loaded data. The store's credentials travel in the `Authorization` header, Bearer or Basic, never in a body.

**A document.** Every group is optional: an absent group leaves that part of the session as it is, a present one is the whole truth of its part (`views: []` closes every eye); `reset: true` empties the session first. Objects are named `uuid:<uuid>`. A view's `place` (`right` | `below`) splits the view before it in the document. The ETP store's token travels in the `Authorization: Bearer` header (the Authorize button), never in a document or a URL. The schema and examples are in each POST block; `GET /sessions/{id}/state` gives a full document to start from.

**Two doors.** The REST one (*Sessions*): `POST /sessions` with a document gives a session already loading and the `page` a browser opens to attach to it. The page's own query (*Page*): a link to paste, `?etp=…&dataspace=…&partition=…&uuid=…`, or `?state=<url of a document>`."""


# Swagger UI, pinned, from a CDN: nothing to install in the image, the
# page needs the internet
SWAGGER_UI = "https://cdnjs.cloudflare.com/ajax/libs/swagger-ui/5.17.14"


def docs_html(base, icon):
    """The REST front's documentation page: Swagger UI reading the OpenAPI
    document under `base` (`<prefix>/paraview`): the schema and the examples
    in each block, Try it out a click away. Its
    Authorize button takes the store's bearer token, never a URL."""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>FesTrame sessions API</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="{icon}">
<link rel="stylesheet" href="{SWAGGER_UI}/swagger-ui.min.css"></head>
<body><div id="ui"></div>
<script src="{SWAGGER_UI}/swagger-ui-bundle.min.js"></script>
<script>SwaggerUIBundle({{url: "{base}/openapi.json", dom_id: "#ui", defaultModelExpandDepth: 4}});</script>
</body></html>
"""


def openapi(base, page=None):
    """The REST front's OpenAPI 3.0 document, rooted at `base` (`<prefix>/paraview`);
    `page` is the application's page (`<prefix>/`), whose query is the other door."""
    page = (page or base.rsplit("/", 1)[0] + "/").rstrip("/") or "/"
    doc_body = {"required": False, "content": {"application/json": {
        "schema": {"$ref": "#/components/schemas/Document"}, "examples": DOCUMENT_EXAMPLES}}}
    status_resp = {"description": "the door's status", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Status"}}}}
    session_resp = {"description": "the session", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Session"}}}}
    sid = {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
    s = ["Sessions"]
    view = {"name": "view", "in": "query", "required": False, "schema": {"type": "string"},
            "description": "the 3D view (its id, as GET …/objects says it); the first one when absent"}
    wait = {"name": "wait", "in": "query", "required": False, "schema": {"type": "integer", "minimum": 0, "maximum": 110},
            "description": "seconds to wait for the reads to end before answering (0: at once)"}
    catalogue_params = [
        {"name": "type", "in": "query", "required": False, "schema": {"type": "string"},
         "description": "one type of object, as the data tree names it (IjkGrid, Grid2d, ContinuousProperty, Wellbore…), any case"},
        {"name": "q", "in": "query", "required": False, "schema": {"type": "string"},
         "description": "a text the title holds, any case"},
        {"name": "limit", "in": "query", "required": False,
         "schema": {"type": "integer", "minimum": 0, "maximum": 5000, "default": 500}}]

    def answer(ref, text):
        return {"description": text, "content": {"application/json": {"schema": {"$ref": f"#/components/schemas/{ref}"}}}}

    refused = answer("Error", "refused: the error says why")
    unknown = answer("Error", "no such session")
    gone = answer("Error", "the session did not answer (it stopped)")
    objects = answer("Objects", "the objects read, each shown or not in the 3D view")
    sources = answer("Sources", "the files read and the ETP store")
    uuids_body = {"required": True, "content": {"application/json": {
        "schema": {"$ref": "#/components/schemas/Uuids"}, "examples": OBJECTS_EXAMPLES}}}
    o, src = ["Objects"], ["Sources"]
    return {
        "openapi": "3.0.3",
        "info": {"title": "FesTrame sessions", "version": "1", "description": API_DESCRIPTION},
        "servers": [{"url": base}],
        "tags": [{"name": "Sessions", "description": "the REST door: a session created on a document, "
                                                     "applied to, read, closed"},
                 {"name": "Sources", "description": "what a session reads: EPC files, an ETP store's dataspaces"},
                 {"name": "Objects", "description": "the objects a session reads and its 3D view shows, by uuid"},
                 {"name": "Page", "description": "the page's own door: a link that opens FesTrame on data "
                                                 "(the ETP token is the reader's to type, never in a URL)"}],
        "paths": {
            "/sessions": {
                "get": {"tags": s, "summary": "The sessions in use",
                        "responses": {"200": {"description": "a list of sessions", "content": {"application/json": {
                            "schema": {"type": "array", "items": {"$ref": "#/components/schemas/Session"}}}}}}},
                "post": {"tags": s, "summary": "A session, the document applied on it",
                         "requestBody": doc_body,
                         "responses": {"201": session_resp, "400": status_resp, "503": {"description": "no session is ready"}}},
            },
            "/sessions/{id}": {
                "get": {"tags": s, "summary": "One session", "parameters": [sid], "responses": {"200": session_resp, "404": {"description": "unknown"}}},
                "delete": {"tags": s, "summary": "Close it", "parameters": [sid], "responses": {"200": {"description": "closed"}, "404": {"description": "unknown"}}},
            },
            "/sessions/{id}/apply": {
                "post": {"tags": s, "summary": "Apply a document on it", "parameters": [sid], "requestBody": doc_body,
                         "responses": {"200": status_resp, "400": status_resp, "404": {"description": "unknown"}}},
            },
            "/sessions/{id}/state": {
                "get": {"tags": s, "summary": "The session as one document", "parameters": [sid],
                        "responses": {"200": {"description": "the document", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Document"}}}}}},
            },
            "/sessions/{id}/sources": {
                "get": {"tags": src, "summary": "The files read and the ETP store", "parameters": [sid],
                        "responses": {"200": sources, "404": unknown, "502": gone}},
            },
            "/sessions/{id}/sources/files": {
                "post": {"tags": src, "summary": "Read an EPC: by its path on the server, or sent with its HDF5",
                         "parameters": [sid],
                         "requestBody": {"required": True, "content": {
                             "application/json": {"schema": {"$ref": "#/components/schemas/ServerFile"},
                                                  "example": {"path": "private/drogon.epc"}},
                             "multipart/form-data": {"schema": {"type": "object", "properties": {"files": {
                                 "type": "array", "items": {"type": "string", "format": "binary"},
                                 "description": "an .epc and its .h5 files"}}}}}},
                         "responses": {"200": answer("Sources", "the sources, the files sent read (read, skipped: "
                                                                "a name the session had already read)"),
                                       "400": refused, "404": unknown, "502": gone}},
            },
            "/sessions/{id}/sources/etp": {
                "post": {"tags": src, "summary": "Connect an ETP store and load dataspaces", "parameters": [sid],
                         "security": [{"bearer": []}, {"basic": []}],
                         "requestBody": {"required": True, "content": {"application/json": {
                             "schema": {"$ref": "#/components/schemas/EtpSource"},
                             "example": {"url": _ADME, "partition": "opendes", "dataspaces": ["demo/Volve"]}}}},
                         "responses": {"200": sources, "400": refused,
                                       "401": answer("Error", "no credentials in the Authorization header"),
                                       "404": unknown,
                                       "502": answer("Error", "the store refused the connection, or a dataspace")}},
            },
            "/sessions/{id}/objects": {
                "get": {"tags": o, "summary": "The objects read, each shown or not", "parameters": [sid, view],
                        "responses": {"200": objects, "400": refused, "404": unknown, "502": gone}},
                "post": {"tags": o, "summary": "Read objects and show them, added to what is there",
                         "parameters": [sid, view, wait], "requestBody": uuids_body,
                         "responses": {"200": objects, "400": refused, "404": unknown, "502": gone}},
                "put": {"tags": o, "summary": "Only these objects read and shown",
                        "parameters": [sid, view, wait], "requestBody": uuids_body,
                        "responses": {"200": objects, "400": refused, "404": unknown, "502": gone}},
                "delete": {"tags": o, "summary": "Every object taken away", "parameters": [sid, view],
                           "responses": {"200": objects, "400": refused, "404": unknown, "502": gone}},
            },
            "/sessions/{id}/catalogue": {
                "get": {"tags": o, "summary": "Every object of the data, read or not, to choose from",
                        "parameters": [sid, view] + catalogue_params,
                        "responses": {"200": answer("Catalogue", "the objects of the data"), "400": refused,
                                      "404": unknown, "502": gone}},
            },
            "/sessions/{id}/objects/{uuid}": {
                "delete": {"tags": o, "summary": "One object taken away (no longer read nor shown)",
                           "parameters": [sid, {"name": "uuid", "in": "path", "required": True,
                                                "schema": {"type": "string"}}, view],
                           "responses": {"200": objects, "400": refused, "404": unknown, "502": gone}},
            },
            "/pool": {"get": {"tags": s, "summary": "What waits and what is taken",
                              "responses": {"200": {"description": "the pool", "content": {"application/json": {"schema": {
                                  "type": "object", "properties": {"ready": {"type": "integer"}, "taken": {"type": "integer"},
                                                                   "size": {"type": "integer"}}}}}}}}},
            "/": {"servers": [{"url": page}],
                  "get": {"tags": ["Page"], "summary": "The application's page, opened on data by its query",
                          "parameters": PAGE_PARAMETERS,
                          "responses": {"200": {"description": "the page; the Session door applies the document "
                                                               "the query makes, and says what it did"}}}},
        },
        "components": {"schemas": {
            "Document": DOCUMENT_SCHEMA,
            "View": VIEW_SCHEMA,
            "Status": STATUS_SCHEMA,
            "Session": {"type": "object", "properties": {
                "id": {"type": "string"}, "sessionURL": {"type": "string"}, "secret": {"type": "string"},
                "page": {"type": "string", "description": "the page a browser opens to attach to it"},
                "port": {"type": "integer"}, "status": {"$ref": "#/components/schemas/Status"}}},
            **NATIVE_SCHEMAS,
        }, "securitySchemes": {"bearer": {"type": "http", "scheme": "bearer",
                                          "description": "the ETP store's token, for the document's sources.etp"
                                                         " or POST …/sources/etp"},
                               "basic": {"type": "http", "scheme": "basic",
                                         "description": "the ETP store's user and password, for POST …/sources/etp"}}},
    }


# ----------------------------------------------------------------- launcher

def run_launcher(cfg_path):
    from aiohttp import web
    cfg = load_config(cfg_path)
    conf = cfg["configuration"]
    host = cfg["resources"][0]["host"]
    proxy_file = conf["proxy_file"]
    endpoint = "/" + conf.get("endpoint", "paraview").strip("/")
    url_template = conf["sessionURL"]
    timeout = float(conf.get("timeout", 25))
    ensure_dirs()

    def answer(rec):
        url = url_template.replace("${id}", rec["id"]).replace("${host}", host) \
                          .replace("${port}", str(rec["port"]))
        return {"id": rec["id"], "sessionURL": url, "secret": rec["secret"]}

    async def handle_post(request):
        import asyncio
        try:
            await request.json()
        except Exception:  # noqa: BLE001 — wslink refused a body with no "application"; a ready session costs nothing to hand over
            pass
        prune_taken()
        deadline = time.time() + timeout
        while True:
            rec, again = session_to_hand()
            if rec is not None:
                say(f"session {rec['id']} handed over{' again (single mode)' if again else ''}:"
                    f" port {rec['port']}, pid {rec['pid']}")
                return web.json_response(answer(rec))
            if time.time() > deadline:
                return web.json_response({"error": "No session was ready before the timeout."},
                                         status=503)
            await asyncio.sleep(0.1)

    def find_taken(sid):
        for n, rec in read_records(TAKEN_DIR):
            if rec.get("id") == sid:
                return n, rec
        return None, None

    def unknown():
        return web.json_response({"error": "Unknown session"}, status=404)

    def close(n, rec):
        """The session killed; the template reaps it and rewrites the map."""
        try:
            os.kill(rec["pid"], 15)
        except OSError:
            pass
        try:
            os.remove(os.path.join(TAKEN_DIR, n))
        except OSError:
            pass

    async def handle_get(request):
        n, rec = find_taken(request.match_info["id"])
        return web.json_response(answer(rec)) if rec else unknown()

    async def handle_delete(request):
        n, rec = find_taken(request.match_info["id"])
        if rec is None:
            return unknown()
        close(n, rec)
        return web.json_response(answer(rec))

    async def handle_pool(request):
        """GET <endpoint>/pool: what waits and what is taken — for a watch,
        and for run.ps1 to say when the first session is ready."""
        prune_taken()
        return web.json_response(dict(counts(), size=int(os.environ.get("FESPP_POOL_SIZE", "2"))))

    # ---- the REST front (S3): sessions created with a document, driven
    # through their own /apply and /state (engine/io/session_endpoint)
    import asyncio
    import aiohttp
    prefix = os.environ.get("TRAME_URL_PREFIX", "") or ""

    async def session_call(rec, method, path, body=None, headers=None, params=None):
        """A route of the session's own HTTP server, on its port."""
        url = f"http://127.0.0.1:{rec['port']}{path}"
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as http:
            async with http.request(method, url, json=body, headers=headers or {}, params=params) as r:
                try:
                    data = await r.json()
                except Exception:  # noqa: BLE001 — not JSON: the text says what the session said
                    data = {"error": (await r.text())[:500]}
                return r.status, data

    def page_url(rec):
        """The page attached to that session: the client connects straight
        to the `sessionURL` the address carries, with its secret."""
        from urllib.parse import urlencode
        return f"{prefix}/?" + urlencode({"sessionURL": answer(rec)["sessionURL"],
                                          "secret": rec["secret"]})

    def auth_of(request):
        auth = request.headers.get("Authorization")
        return {"Authorization": auth} if auth else None

    async def body_of(request):
        if not request.can_read_body:
            return None
        return await request.json()

    async def handle_sessions_post(request):
        try:
            doc = await body_of(request)
        except Exception:  # noqa: BLE001 — the body is the client's: said back
            return web.json_response({"error": "A JSON document is expected."}, status=400)
        prune_taken()
        if single() and live_taken() is not None:
            return web.json_response({"error": "This machine holds one session, already taken:"
                                               " GET …/sessions gives it."}, status=409)
        rec = take_ready()
        if rec is None:
            return web.json_response({"error": "No session is ready."}, status=503)
        out = dict(answer(rec), page=page_url(rec), port=rec["port"])
        say(f"session {rec['id']} created by REST: port {rec['port']}" + (" with a document" if doc else ""))
        if doc:
            code, status = await session_call(rec, "POST", "/apply", doc, auth_of(request))
            out["status"] = status
            return web.json_response(out, status=code if code >= 400 else 201)
        return web.json_response(out, status=201)

    async def handle_sessions_get(request):
        prune_taken()
        return web.json_response([{"id": r["id"], "port": r["port"], "since": r.get("taken"),
                                   "page": page_url(r)} for _n, r in read_records(TAKEN_DIR)])

    async def handle_session_get(request):
        n, rec = find_taken(request.match_info["id"])
        return web.json_response(dict(answer(rec), page=page_url(rec), port=rec["port"])) if rec else unknown()

    async def handle_session_state(request):
        n, rec = find_taken(request.match_info["id"])
        if rec is None:
            return unknown()
        code, data = await session_call(rec, "GET", "/state")
        return web.json_response(data, status=code)

    async def handle_session_apply(request):
        n, rec = find_taken(request.match_info["id"])
        if rec is None:
            return unknown()
        try:
            doc = await body_of(request)
        except Exception:  # noqa: BLE001 — the body is the client's: said back
            return web.json_response({"error": "A JSON document is expected."}, status=400)
        code, data = await session_call(rec, "POST", "/apply", doc or {}, auth_of(request))
        return web.json_response(data, status=code)

    async def handle_session_delete(request):
        n, rec = find_taken(request.match_info["id"])
        if rec is None:
            return unknown()
        close(n, rec)
        return web.json_response({"id": rec["id"], "closed": True})

    # ---- the native routes: objects and sources said by uuid, relayed to
    # the session's own (engine/io/session_endpoint)
    def failed(exc):
        return web.json_response({"error": f"The session did not answer: {exc or type(exc).__name__}"},
                                 status=502)

    async def relay(request, method, path, body=None, params=None):
        n, rec = find_taken(request.match_info["id"])
        if rec is None:
            return unknown()
        try:
            code, data = await session_call(rec, method, path, body, auth_of(request), params)
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            return failed(exc)
        return web.json_response(data, status=code)

    async def json_of(request):
        """The request's JSON body, or the 400 that refuses it."""
        try:
            return await body_of(request), None
        except Exception:  # noqa: BLE001 — the body is the client's: said back
            return None, web.json_response({"error": "A JSON object is expected."}, status=400)

    async def handle_objects(request):
        body = None
        if request.method in ("POST", "PUT"):
            body, refused = await json_of(request)
            if refused is not None:
                return refused
        return await relay(request, request.method, "/objects", body, list(request.query.items()))

    async def handle_object_delete(request):
        params = [("uuid", request.match_info["uuid"])] + [(k, v) for k, v in request.query.items() if k == "view"]
        return await relay(request, "DELETE", "/objects", None, params)

    async def handle_sources(request):
        return await relay(request, "GET", "/sources")

    async def handle_catalogue(request):
        return await relay(request, "GET", "/catalogue", None, list(request.query.items()))

    async def handle_sources_files(request):
        """An EPC by its path under the open directory (JSON), or EPC and
        HDF5 files sent (multipart, streamed to the session's /upload)."""
        if request.content_type != "multipart/form-data":
            body, refused = await json_of(request)
            if refused is not None:
                return refused
            return await relay(request, "POST", "/sources/files", body)
        n, rec = find_taken(request.match_info["id"])
        if rec is None:
            return unknown()
        url = f"http://127.0.0.1:{rec['port']}/upload"
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None, sock_read=600)) as http:
                async with http.post(url, data=request.content,
                                     headers={"Content-Type": request.headers["Content-Type"]}) as r:
                    try:
                        sent = await r.json()
                    except Exception:  # noqa: BLE001 — not JSON: the text says what the session said
                        sent = {"message": (await r.text())[:500]}
                    if r.status >= 400:
                        return web.json_response({"error": sent.get("message") or f"Upload refused ({r.status})."},
                                                 status=r.status)
            code, data = await session_call(rec, "GET", "/sources")
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            return failed(exc)
        if code < 400:
            data = dict(data, read=sent.get("epc_paths") or [], skipped=sent.get("skipped") or [])
        return web.json_response(data, status=code)

    async def handle_sources_etp(request):
        body, refused = await json_of(request)
        if refused is not None:
            return refused
        return await relay(request, "POST", "/sources/etp", body)

    async def handle_openapi(request):
        return web.json_response(openapi(prefix + endpoint, prefix + "/"))

    async def handle_docs(request):
        return web.Response(text=docs_html(prefix + endpoint, prefix + "/logo.png"),
                            content_type="text/html")

    app = web.Application()
    app.router.add_post(endpoint, handle_post)
    app.router.add_post(endpoint + "/", handle_post)
    app.router.add_get(endpoint + "/pool", handle_pool)
    app.router.add_get(endpoint + "/openapi.json", handle_openapi)
    app.router.add_get(endpoint + "/docs", handle_docs)
    app.router.add_get(endpoint + "/sessions", handle_sessions_get)
    app.router.add_post(endpoint + "/sessions", handle_sessions_post)
    app.router.add_get(endpoint + "/sessions/{id}", handle_session_get)
    app.router.add_get(endpoint + "/sessions/{id}/state", handle_session_state)
    app.router.add_post(endpoint + "/sessions/{id}/apply", handle_session_apply)
    app.router.add_delete(endpoint + "/sessions/{id}", handle_session_delete)
    for method in ("GET", "POST", "PUT", "DELETE"):
        app.router.add_route(method, endpoint + "/sessions/{id}/objects", handle_objects)
    app.router.add_delete(endpoint + "/sessions/{id}/objects/{uuid}", handle_object_delete)
    app.router.add_get(endpoint + "/sessions/{id}/catalogue", handle_catalogue)
    app.router.add_get(endpoint + "/sessions/{id}/sources", handle_sources)
    app.router.add_post(endpoint + "/sessions/{id}/sources/files", handle_sources_files)
    app.router.add_post(endpoint + "/sessions/{id}/sources/etp", handle_sources_etp)
    app.router.add_get(endpoint + "/{id}", handle_get)
    app.router.add_delete(endpoint + "/{id}", handle_delete)
    say(f"launcher on {conf['host']}:{conf['port']}{endpoint}, mapping {proxy_file}")
    web.run_app(app, host=conf["host"], port=int(conf["port"]), print=None)


if __name__ == "__main__":
    mode, cfg = sys.argv[1], sys.argv[2]
    {"template": run_template, "launcher": run_launcher}[mode](cfg)
