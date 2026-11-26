"""The velocity model as RESQML 2.0.1, written by fesapi (the PO, 02/11:
"FESPP on trame est un visualizer RESQML, je ne veux pas sortir de ce
format"): a DataObjectRepository of its own holding a LocalTime3dCrs
(the velocity model's layers in two-way time, ms) — or a LocalDepth3dCrs for a velocity model
in depth —, an IjkGridRepresentation whose geometry is a lattice (origin,
three offsets with their spacing: createIjkGridLatticeRepresentation +
setGeometryAsCoordinateLineNodes) and a ContinuousProperty "velocity" on
its cells, in m/s, serialised as <stem>.epc + <stem>.h5 — read back by
the plugin like any package, the velocity model then a grid of the tree with its
property, in the domain of its CRS.

Run as a SUBPROCESS of the app (`write_cube`): the fesapi Python module
(the PyPI wheel, installed in the deployed image by deploy/caddy/run.ps1)
carries its own HDF5, and the view's process already holds the plugin's;
two HDF5 libraries in one process are a known way to crash. The child
reads the velocity model as JSON on stdin and answers JSON on stdout.

A lattice has ONE spacing per direction: layers that follow the values
entered are not even, so the velocity model is resampled on even layers of the
thinnest one (200 at most), each taking the velocity of the layer holding
its middle, and the answer says so.
"""
import json
import os
import subprocess
import sys

MAX_LAYERS = 200
ORIGINATOR = "FesTrame"


def even_layers(z, v, unit="m"):
    """`z` (nl + 1 boundaries, depths or times) and `v` (nl, ny, nx) on
    even layers: as they are when already even, else resampled on the
    thinnest layer's step; (z, v, note) with `note` "" or what was done."""
    import numpy as np
    z = np.asarray(z, float)
    v = np.asarray(v, float)
    dz = np.diff(z)
    if len(dz) == 0:
        raise ValueError("a velocity model needs one layer at least")
    tol = 1e-6 * max(1.0, abs(float(z[-1])))
    if np.all(np.abs(dz - dz[0]) <= tol):
        return z, v, ""
    step = float(dz.min())
    n = int(np.ceil((z[-1] - z[0]) / step - 1e-9))
    if n > MAX_LAYERS:
        n = MAX_LAYERS
        step = float(z[-1] - z[0]) / n
    zz = z[0] + step * np.arange(n + 1)
    mids = (zz[:-1] + zz[1:]) / 2.0
    k = np.clip(np.searchsorted(z, mids, side="right") - 1, 0, len(dz) - 1)
    return zz, v[k], f"resampled on {n} even layers of {step:g} {unit} (the layers entered are not even)"


# the property of a velocity model written here: the same velocity in every
# cell is an average velocity as much as an interval one, and says so (its
# name, a facet statistics = average); any other holds interval velocities
VELOCITY, AVERAGE_VELOCITY = "velocity", "Average velocity"
TITLES = (VELOCITY, AVERAGE_VELOCITY)


def write(spec):
    """`spec` {dir, stem, title, x0, x1, y0, y1, nx, ny, z: [nl + 1
    boundaries], v: [[[...]]] (nl, ny, nx) m/s, domain: "time" (the
    boundaries two-way times in ms) | "depth" (in m, the default)}: the
    package written in `dir` as <stem>.epc and <stem>.h5 by fesapi; {epc,
    h5, grid, property, cells, note}."""
    import fesapi
    import numpy as np
    in_time = spec.get("domain") == "time"
    z, v, note = even_layers(spec["z"], spec["v"], "ms" if in_time else "m")
    nl, ny, nx = v.shape
    x0, x1, y0, y1 = (float(spec[k]) for k in ("x0", "x1", "y0", "y1"))
    if nx != int(spec["nx"]) or ny != int(spec["ny"]):
        raise ValueError("the velocity model's cells and its values disagree")
    out_dir = os.path.abspath(spec["dir"])
    os.makedirs(out_dir, exist_ok=True)
    stem = spec["stem"]
    title = spec.get("title") or "Velocity model"
    # the uuids: given, the package is a new version of the same objects
    uuids = spec.get("uuids") or {}

    repo = fesapi.DataObjectRepository()
    # the CRS: no offset, no rotation, metres, the vertical positive
    # downward (as Volve's and Drogon's) — two-way times in ms for a velocity model in
    # time; its EPSG unknown — the velocity model stands in the coordinates the data
    # is shown in
    if in_time:
        crs = repo.createLocalTime3dCrs(uuids.get("crs", ""), "Velocity model CRS", 0.0, 0.0, 0.0, 0.0,
                                        fesapi.eml20__LengthUom_m, "unknown", fesapi.eml20__TimeUom_ms,
                                        fesapi.eml20__LengthUom_m, "unknown", False)
    else:
        crs = repo.createLocalDepth3dCrs(uuids.get("crs", ""), "Velocity model CRS", 0.0, 0.0, 0.0, 0.0,
                                         fesapi.eml20__LengthUom_m, "unknown",
                                         fesapi.eml20__LengthUom_m, "unknown", False)
    repo.setDefaultCrs(crs)
    hdf = repo.createHdfProxy(uuids.get("hdf", ""), "Velocity model HDF5", out_dir, stem + ".h5",
                              fesapi.DataObjectRepository.openingMode_OVERWRITE)
    repo.setDefaultHdfProxy(hdf)
    grid = repo.createIjkGridLatticeRepresentation(uuids.get("grid", ""), title, nx, ny, nl)
    # the lattice: I east, J north, K down from the top layer boundary (in
    # the CRS's vertical unit: m, or ms in time)
    grid.setGeometryAsCoordinateLineNodes(
        fesapi.resqml20__PillarShape_vertical, fesapi.resqml20__KDirection_down, False,
        x0, y0, float(z[0]),
        1.0, 0.0, 0.0, (x1 - x0) / nx,
        0.0, 1.0, 0.0, (y1 - y0) / ny,
        0.0, 0.0, 1.0, float(z[1] - z[0]))
    flat = np.ascontiguousarray(v, dtype=np.float64).ravel()      # K slowest, I fastest
    constant = bool(flat.size) and float(flat.min()) == float(flat.max())
    prop = repo.createContinuousProperty(grid, uuids.get("prop", ""), AVERAGE_VELOCITY if constant else VELOCITY, 1,
                                         fesapi.eml23__IndexableElement_cells,
                                         fesapi.resqml20__ResqmlUom_m_x002fs,
                                         fesapi.resqml20__ResqmlPropertyKind_velocity)
    if constant:
        prop.pushBackFacet(fesapi.eml23__FacetKind_statistics, "average")
    values = fesapi.DoubleArray(int(flat.size))      # SWIG's carray: filled one by one
    for i, value in enumerate(flat.tolist()):
        values.setitem(i, value)
    prop.pushBackDoubleHdf5Array3dOfValues(values.cast(), nx, ny, nl,
                                           float(flat.min()), float(flat.max()), hdf)
    epc_path = os.path.join(out_dir, stem + ".epc")
    epc = fesapi.EpcDocument(epc_path)
    epc.serializeFrom(repo)
    # the HDF5 file is complete once its proxy is closed
    close = getattr(hdf, "close", None)
    if close is not None:
        close()
    return {"epc": epc_path, "h5": os.path.join(out_dir, stem + ".h5"), "grid": grid.getUuid(),
            "property": prop.getUuid(), "cells": [nx, ny, nl], "note": note}


def _python():
    """The interpreter the child runs on: the deployed venv's (fesapi is
    installed there), else this one."""
    venv = "/deploy/server/venv/bin/python"
    return venv if os.path.exists(venv) else sys.executable


def write_cube(spec, timeout=120):
    """`write(spec)` in a child process: its answer, or {error}."""
    try:
        got = subprocess.run([_python(), os.path.abspath(__file__)], input=json.dumps(spec),
                             capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"[fespp] RESQML writer: not run ({exc!r})", flush=True)
        return {"error": f"the RESQML writer could not run ({exc})"}
    out = (got.stdout or "").strip().splitlines()
    try:
        answer = json.loads(out[-1]) if out else {}
    except ValueError:
        print(f"[fespp] RESQML writer: no answer read ({out[-1][:200]!r})", flush=True)
        answer = {}
    if got.returncode != 0 or not isinstance(answer, dict) or "epc" not in answer:
        why = answer.get("error") if isinstance(answer, dict) else ""
        tail = (got.stderr or "").strip().splitlines()[-1:] if got.stderr else []
        return {"error": why or (tail[0] if tail else f"the RESQML writer failed (exit {got.returncode})")}
    return answer


def main():
    try:
        spec = json.load(sys.stdin)
        answer = write(spec)
    except ImportError as exc:
        answer = {"error": f"fesapi is not installed in this image ({exc})"}
        print(f"[fespp] RESQML writer: {exc!r}", file=sys.stderr, flush=True)
    except Exception as exc:      # noqa: BLE001 — said back to the app, which says it to the reader
        answer = {"error": f"{type(exc).__name__}: {exc}"}
        print(f"[fespp] RESQML writer: {exc!r}", file=sys.stderr, flush=True)
    print(json.dumps(answer), flush=True)
    sys.exit(0 if "epc" in answer else 1)


if __name__ == "__main__":
    main()
