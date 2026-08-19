"""Headless visual-test scenario runner.

Activated ONLY when the ``FESPP_SCENARIO`` environment variable points to a
scenario JSON file (see ``tests/visual/``): after ``on_server_ready`` the
runner executes the scripted steps through the SAME state vars and
controller methods the browser UI drives, and captures server-side
screenshots along the way. ``test-visual.ps1`` then diffs the captures
against per-scenario baselines. Inert in normal runs — no client, no UI
interaction, no state cost when the env var is absent.

Scenario file format — a JSON object::

    {"steps": [
      {"op": "load",   "path": "/tmp/testdata/drogon.epc"},
      {"op": "check",  "title": "Facies"},
      {"op": "shot",   "name": "grid_facies"},
      {"op": "eye",    "title": "Geogrid"},
      {"op": "set",    "var": "ui_slices_range_mode", "value": "range"},
      {"op": "volumes_fraction", "i": [0.4, 1.0], "j": [0, 1], "k": [0, 1]},
      {"op": "activate", "title": "Facies"},
      {"op": "reset_camera"},
      {"op": "wait",   "s": 2}
    ]}

Every step accepts an optional ``settle`` (seconds to sleep after the
step; default 1.5) so trame flush chains and renders complete before the
next step or shot."""
import asyncio
import json
import os

from paraview import simple as pvsimple

# Tree kinds → the tree-tab selection state var their checkbox writes.
_WELL_KINDS = {
    "Wellbore", "Trajectory", "Frame", "MarkerFrame", "Marker",
    "SeismicWellboreFrame", "Completion", "Channel", "WellboreMarkerFrame",
}
_SURFACE_KINDS = {
    "Grid2d", "TriangulatedSet", "PointSet", "PolylineSet", "Polyline",
}

_DEFAULT_SETTLE = 1.5
_SHOT_RESOLUTION = [1280, 800]


def schedule(server, state, controller, tree, view, scenario_path):
    """Fire the runner as a background task on the server loop."""
    asyncio.ensure_future(
        _run(server, state, controller, tree, view, scenario_path)
    )


def _out_dir():
    d = os.environ.get("FESPP_SCENARIO_OUT", "/tmp/visual_out")
    os.makedirs(d, exist_ok=True)
    return d


def _log(out, msg):
    print(f"[SCENARIO] {msg}", flush=True)
    with open(os.path.join(out, "scenario.log"), "a") as f:
        f.write(msg + "\n")


def _find_node_by_title(tree, title):
    """First assembly node whose title (fallback: label) equals `title`."""
    asm = tree._data_assembly
    if asm is None:
        return None
    hits = []

    def walk(nid):
        t = (asm.GetAttributeOrDefault(nid, "title", None)
             or asm.GetAttributeOrDefault(nid, "label", None))
        if t == title:
            hits.append(nid)
            return
        for i in range(asm.GetNumberOfChildren(nid)):
            walk(asm.GetChild(nid, i))

    walk(asm.GetRootNode())
    return hits[0] if hits else None


def _select_var_for(tree, node_id):
    kind = tree.find_type(node_id) or ""
    if kind in _WELL_KINDS:
        return "ui_select_node_well"
    if kind in _SURFACE_KINDS:
        return "ui_select_node_surface"
    return "ui_select_node_reservoir"


def _resolve_view(server, state, fallback):
    try:
        mv = getattr(server.context, "multi_view", None)
        pid = getattr(state, "fespp_active_panel_id", "") or ""
        v = mv.get_pv_view(pid) if (mv is not None and pid) else None
        if v is not None:
            return v
    except Exception:
        pass
    return fallback or pvsimple.GetActiveView()


async def _run(server, state, controller, tree, view, scenario_path):
    out = _out_dir()
    shot_idx = 0
    try:
        with open(scenario_path) as f:
            steps = json.load(f).get("steps", [])
        _log(out, f"start: {scenario_path} ({len(steps)} steps)")
        # Let boot (plugin load, layout, initial data_load) settle.
        await asyncio.sleep(4.0)

        for i, step in enumerate(steps):
            op = step.get("op", "")
            _log(out, f"step {i}: {json.dumps(step)}")
            v = _resolve_view(server, state, view)

            if op == "load":
                with state:
                    controller.load_epc_file(step["path"])

            elif op in ("check", "uncheck"):
                nid = _find_node_by_title(tree, step["title"])
                if nid is None:
                    raise RuntimeError(f"node not found: {step['title']!r}")
                var = step.get("var") or _select_var_for(tree, nid)
                with state:
                    lst = list(getattr(state, var) or [])
                    if op == "check" and nid not in lst:
                        lst.append(nid)
                    if op == "uncheck" and nid in lst:
                        lst.remove(nid)
                    setattr(state, var, lst)
                    state.dirty(var)

            elif op == "activate":
                nid = _find_node_by_title(tree, step["title"])
                if nid is None:
                    raise RuntimeError(f"node not found: {step['title']!r}")
                var = step.get("var", "ui_active_node_reservoir")
                with state:
                    setattr(state, var, [nid])
                    state.dirty(var)

            elif op == "eye":
                nid = _find_node_by_title(tree, step["title"])
                if nid is None:
                    raise RuntimeError(f"node not found: {step['title']!r}")
                r_id = tree.find_representation_node(nid)
                rep_path = tree.find_path(r_id) if r_id is not None else None
                if not rep_path:
                    raise RuntimeError(f"no rep path for: {step['title']!r}")
                with state:
                    controller.toggle_rep_visibility(rep_path)

            elif op == "set":
                with state:
                    setattr(state, step["var"], step["value"])
                    state.dirty(step["var"])

            elif op == "volumes_fraction":
                # Crop volume 1 to fractions of the grid's I/J/K extents.
                def _bounds(axis, frac):
                    rng = list(getattr(state, f"ui_range_{axis}") or [0, 1])
                    lo, hi = rng[0], rng[1]
                    return [int(round(lo + frac[0] * (hi - lo))),
                            int(round(lo + frac[1] * (hi - lo)))]
                vol = [_bounds("i", step.get("i", [0, 1])),
                       _bounds("j", step.get("j", [0, 1])),
                       _bounds("k", step.get("k", [0, 1]))]
                with state:
                    state.ui_volumes_list = [vol]
                    state.ui_volumes_visible_list = list(
                        step.get("visible", [True]))
                    state.dirty("ui_volumes_list")
                    state.dirty("ui_volumes_visible_list")

            elif op == "narrow_color_range":
                # Narrow the active continuous colormap to fractions of
                # the range the color editor seeded — drives the same
                # auto-apply path as typing Min/Max in the drawer.
                lo = float(getattr(state, "color_range_min", 0.0) or 0.0)
                hi = float(getattr(state, "color_range_max", 1.0) or 1.0)
                frac = step.get("fraction", [0.25, 0.75])
                with state:
                    state.color_range_min = lo + frac[0] * (hi - lo)
                    state.color_range_max = lo + frac[1] * (hi - lo)
                    state.dirty("color_range_min")
                    state.dirty("color_range_max")

            elif op == "reset_camera":
                pvsimple.ResetCamera(v)
                v.CenterOfRotation = list(v.CameraFocalPoint)
                pvsimple.Render(view=v)

            elif op == "wait":
                await asyncio.sleep(float(step.get("s", 1.0)))

            elif op == "shot":
                pvsimple.Render(view=v)
                name = step.get("name", f"step{i}")
                fname = f"{shot_idx:02d}_{name}.png"
                pvsimple.SaveScreenshot(
                    os.path.join(out, fname), v,
                    ImageResolution=list(_SHOT_RESOLUTION),
                )
                shot_idx += 1
                _log(out, f"shot: {fname}")

            else:
                raise RuntimeError(f"unknown op: {op!r}")

            await asyncio.sleep(float(step.get("settle", _DEFAULT_SETTLE)))

        _log(out, "done")
    except Exception as exc:
        _log(out, f"ERROR: {exc!r}")
        with open(os.path.join(out, "ERROR.txt"), "w") as f:
            f.write(repr(exc))
    finally:
        with open(os.path.join(out, "DONE"), "w") as f:
            f.write("done")
