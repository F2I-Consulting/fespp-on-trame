"""Visual-regression comparator — run with pvpython inside the app image.

Usage: pvpython compare.py <baseline_dir> <candidate_dir> [pixel_thr] [frac_thr]

For every PNG in <baseline_dir>, loads the same-named PNG from
<candidate_dir> and counts the pixels whose max channel difference
exceeds ``pixel_thr`` (default 12/255 — absorbs anti-aliasing noise).
FAIL when the differing fraction exceeds ``frac_thr`` (default 0.5%),
when sizes differ, or when the candidate is missing. A ``<name>_diff.png``
mask (white = differing pixels) is written next to failing candidates.
Exit code: 0 = all pass, 1 = at least one failure."""
import json
import os
import sys

import numpy as np
from vtkmodules.util.numpy_support import numpy_to_vtk, vtk_to_numpy
from vtkmodules.vtkCommonDataModel import vtkImageData
from vtkmodules.vtkIOImage import vtkPNGReader, vtkPNGWriter


def load_png(path):
    r = vtkPNGReader()
    r.SetFileName(path)
    r.Update()
    img = r.GetOutput()
    w, h, _ = img.GetDimensions()
    arr = vtk_to_numpy(img.GetPointData().GetScalars())
    return arr.reshape(h, w, -1)


def write_mask(path, mask):
    h, w = mask.shape
    img = vtkImageData()
    img.SetDimensions(w, h, 1)
    data = numpy_to_vtk((mask.astype(np.uint8) * 255).reshape(-1, 1))
    img.GetPointData().SetScalars(data)
    wr = vtkPNGWriter()
    wr.SetFileName(path)
    wr.SetInputData(img)
    wr.Write()


def main():
    baseline_dir, cand_dir = sys.argv[1], sys.argv[2]
    pixel_thr = int(sys.argv[3]) if len(sys.argv) > 3 else 12
    frac_thr = float(sys.argv[4]) if len(sys.argv) > 4 else 0.005

    results, ok = [], True
    names = sorted(
        n for n in os.listdir(baseline_dir)
        if n.endswith(".png") and not n.endswith("_diff.png")
    )
    if not names:
        print(json.dumps({"pass": False, "error": "no baselines"}))
        sys.exit(1)
    for name in names:
        cand = os.path.join(cand_dir, name)
        entry = {"name": name}
        if not os.path.exists(cand):
            entry.update({"pass": False, "error": "missing candidate"})
            ok = False
        else:
            b = load_png(os.path.join(baseline_dir, name))
            c = load_png(cand)
            if b.shape != c.shape:
                entry.update({"pass": False,
                              "error": f"size {b.shape} vs {c.shape}"})
                ok = False
            else:
                nch = min(b.shape[2], 3)
                diff = np.abs(b[:, :, :nch].astype(np.int16)
                              - c[:, :, :nch].astype(np.int16))
                mask = diff.max(axis=2) > pixel_thr
                frac = float(mask.mean())
                entry.update({"pass": frac <= frac_thr,
                              "diff_fraction": round(frac, 6)})
                if not entry["pass"]:
                    ok = False
                    write_mask(
                        os.path.join(cand_dir,
                                     name[:-4] + "_diff.png"),
                        mask,
                    )
        results.append(entry)
    print(json.dumps({"pass": ok, "results": results}, indent=1))
    sys.exit(0 if ok else 1)


main()
