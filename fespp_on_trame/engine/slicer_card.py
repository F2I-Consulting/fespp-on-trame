"""A slicer card — pure (the PO's manager, 28/10: "the same UI for the two,
so a user who understands one understands the other").

The Geometry slicer and the Property slicer are one card over different
SUBJECTS: the I, J and K of a grid, or the properties added to the card.

A card is a list of BOXES joined by ∪ or ∩ (`op` of a box after the first;
∩ binds tighter, as between ranges — the manager, 29/10). Each box has its
own mode (the manager: "Range/Slice inside the boxes, to mix even more"):

- a Range box: each subject keeps one or more ranges joined by ∪ or ∩ — ∩
  binds tighter, as in algebra: `I 0-10 ∪ I 20-30 ∩ I 25-40` keeps
  `0-10 ∪ 25-30`; the subjects intersect;
- a Slice box: per subject, cuts at a value, shown together — each keeping
  that value only (`only`), everything below it (`below`: from the lowest
  value up to it) or above it (`above`: from it up to the highest; the PO,
  28/10). It starts with no cut, the object whole (the manager, 29/10: "by
  default everything visible"); its "+" adds one through the middle.

A hidden box or cut cuts nothing (as if it were not there); with nothing
shown the card does not cut at all (`cutting`). A subject of one value (a
constant property, the Z of a flat surface — its extent a single value) is
never cut on (the PO, 29/10: its slicer disabled).

The card compiles into PRODUCTS (`products`): a sum of products, each
{subject: [low, high]} — the cells inside every interval of one product
show, and the products show together. The Geometry slicer draws each as a
crop box, the Property slicer as one branch of the threshold chain.

card = {subjects: [subject, ...], boxes: [{id, op, mode, visible,
ranges: {subject: [{id, op, low, high}]}, cuts: {subject: [{id, at, cmp,
visible}]}}]} — a box holds the subjects it cuts on (a property taken out
of one box stays in the others).
"""
from itertools import product as _cartesian

AND, OR = "and", "or"
RANGE, SLICE = "range", "slice"
# what a cut keeps of its subject
ONLY, BELOW, ABOVE = "only", "below", "above"
# beyond this many products the card is refused rather than drawn: every
# product is a crop or a chain branch of its own
MAX_PRODUCTS = 64


def empty(subjects=()):
    return {"subjects": list(subjects), "boxes": []}


def _ids(card):
    out = set()
    for box in card.get("boxes") or ():
        out.add(box.get("id"))
        for ranges in (box.get("ranges") or {}).values():
            out.update(r.get("id") for r in ranges)
        for cuts in (box.get("cuts") or {}).values():
            out.update(c.get("id") for c in cuts)
    return out


def new_id(card, prefix):
    taken = _ids(card)
    n = len(taken) + 1
    while f"{prefix}{n}" in taken:
        n += 1
    return f"{prefix}{n}"


def middle(extent, values=None, whole=False):
    """The middle of `extent` (a whole number when `whole`), or the value of
    `values` nearest it."""
    mid = (float(extent[0]) + float(extent[1])) / 2.0
    vals = [float(v) for v in values or ()]
    if vals:
        return min(vals, key=lambda v: abs(v - mid))
    return float(int(mid)) if whole else mid


def new_range(card, extent, op=OR):
    return {"id": new_id(card, "r"), "op": AND if op == AND else OR,
            "low": float(extent[0]), "high": float(extent[1])}


def new_cut(card, box, subject, extent, values=None, whole=False):
    """A cut through the middle of `subject`, in `box`."""
    cut = {"id": new_id(card, "c"), "at": middle(extent, values, whole), "cmp": ONLY,
           "visible": True}
    box.setdefault("cuts", {}).setdefault(subject, []).append(cut)
    return cut


def new_box(card, extents, mode=RANGE, values=None, whole=(), subjects=None):
    """A box keeping each of `subjects` (the card's when None; none: an
    empty box, its properties added one by one) whole: in range mode one
    whole range per subject, in slice mode no cut yet (its "+" adds one)."""
    box = {"id": new_id(card, "b"), "op": OR, "mode": SLICE if mode == SLICE else RANGE,
           "visible": True, "ranges": {}, "cuts": {}}
    card.setdefault("boxes", []).append(box)
    for s in (card.get("subjects") or ()) if subjects is None else subjects:
        box["ranges"][s] = [new_range(card, extents[s])]
        box["cuts"][s] = []
    return box


def set_mode(card, box, mode, extents=None, values=None, whole=()):
    """`box` in `mode`, its ranges and cuts kept for a switch back."""
    box["mode"] = SLICE if mode == SLICE else RANGE


def holds(box, subject):
    """Whether `box` cuts on `subject`."""
    return subject in (box.get("ranges") or {}) or subject in (box.get("cuts") or {})


def add_subject(card, subject, extents, values=None, whole=False, box=None):
    """`subject` cut by the card too: a whole range in `box` when given,
    else in every box that does not cut on it yet."""
    if subject not in card["subjects"]:
        card["subjects"].append(subject)
    for box in [box] if box is not None else card.get("boxes") or ():
        if not holds(box, subject):
            box.setdefault("ranges", {})[subject] = [new_range(card, extents[subject])]
            box.setdefault("cuts", {})[subject] = []


def remove_subject(card, subject, box=None):
    """`subject` no longer cut on: in `box` only when given — the card
    forgets it once no box holds it."""
    if subject not in card["subjects"]:
        return
    for b in ([box] if box is not None else card.get("boxes") or ()):
        (b.get("ranges") or {}).pop(subject, None)
        (b.get("cuts") or {}).pop(subject, None)
    if box is None or not any(holds(b, subject) for b in card.get("boxes") or ()):
        card["subjects"].remove(subject)


def prune(card):
    """The card forgets the subjects no box holds (a box removed took its
    properties with it: a property left in no box stayed a subject of the
    card, hidden, and came back in every new box — the PO, 30/10)."""
    card["subjects"] = [s for s in card.get("subjects") or ()
                        if any(holds(b, s) for b in card.get("boxes") or ())]


def missing(card):
    """The card's subjects some box does not cut on (the "+ Property" can
    give them back to it)."""
    return [s for s in card.get("subjects") or ()
            if any(not holds(b, s) for b in card.get("boxes") or ())]


def follow_extents(card, old, new):
    """The subjects' extents went from `old` to `new` (the whole scene grows
    as its objects are read): a range that reached an end of the old extent
    reaches the same end of the new one — a card keeping everything keeps
    everything; a range inside stays where it is."""
    for box in card.get("boxes") or ():
        for s, ranges in (box.get("ranges") or {}).items():
            if not old.get(s) or not new.get(s):
                continue
            o0, o1 = float(old[s][0]), float(old[s][1])
            n0, n1 = float(new[s][0]), float(new[s][1])
            for r in ranges:
                if float(r["low"]) <= o0:
                    r["low"] = n0
                if float(r["high"]) >= o1:
                    r["high"] = n1


def constant(extent):
    """Whether a subject's extent is one value: nothing to cut on it."""
    if not extent or len(extent) < 2 or extent[0] is None or extent[1] is None:
        return False
    return float(extent[0]) == float(extent[1])


def defaults(card, extents):
    """A card starts with one Range box keeping everything (the PO, 28/10)."""
    if not card.get("boxes"):
        new_box(card, extents)


def find(card, item_id):
    """("box", box, None) | ("range", range, (box, subject)) |
    ("cut", cut, (box, subject)) | (None, None, None)."""
    for box in card.get("boxes") or ():
        if box.get("id") == item_id:
            return "box", box, None
        for s, ranges in (box.get("ranges") or {}).items():
            for r in ranges:
                if r.get("id") == item_id:
                    return "range", r, (box, s)
        for s, cuts in (box.get("cuts") or {}).items():
            for c in cuts:
                if c.get("id") == item_id:
                    return "cut", c, (box, s)
    return None, None, None


def intervals(ranges):
    """The intervals a subject's ranges keep in one box: ∩ binds tighter —
    a ∩ range narrows the interval before it, a ∪ range starts another;
    an empty one keeps nothing."""
    groups = []
    for r in ranges or ():
        lo, hi = float(r["low"]), float(r["high"])
        if not groups or r.get("op") != AND:
            groups.append([lo, hi])
        else:
            g = groups[-1]
            g[0], g[1] = max(g[0], lo), min(g[1], hi)
    return [g for g in groups if g[0] <= g[1]]


def _shown_cuts(card, box, extents=None):
    """The shown cuts of a Slice box, [(subject, cut)] — none on a subject
    of one value (`extents` given)."""
    return [(s, c) for s in card.get("subjects") or ()
            if extents is None or not constant(extents.get(s))
            for c in (box.get("cuts") or {}).get(s) or () if c.get("visible", True)]


def cutting(card):
    """Whether the card cuts: a shown Range box, or a shown cut of a shown
    Slice box."""
    for box in card.get("boxes") or ():
        if not box.get("visible", True):
            continue
        if box.get("mode") != SLICE or _shown_cuts(card, box):
            return True
    return False


def _meet(a, b):
    """The intersection of two products, None when it keeps nothing."""
    out = dict(a)
    for s, (lo, hi) in b.items():
        if s in out:
            lo, hi = max(out[s][0], lo), min(out[s][1], hi)
            if lo > hi:
                return None
        out[s] = [lo, hi]
    return out


def _box_products(card, box, extents):
    """What one shown box keeps, as products ([] when it keeps nothing);
    None for a Slice box with no shown cut, or a box holding no subject yet
    (as if it were not there: an empty box of a card on properties waits for
    its first property, it does not keep everything — the PO, 30/10)."""
    if not any(holds(box, s) for s in card.get("subjects") or ()):
        return None
    if box.get("mode") == SLICE:
        cuts = _shown_cuts(card, box, extents)
        if not cuts:
            return None
        return [{s: cut_interval(c, extents[s])} for s, c in cuts]
    alternatives = []
    for s in card.get("subjects") or ():
        ranges = (box.get("ranges") or {}).get(s) or []
        if not ranges or constant(extents.get(s)):
            continue
        kept = intervals(ranges)
        if not kept:
            return []    # this box keeps nothing
        alternatives.append([(s, iv) for iv in kept])
    return [dict((s, list(iv)) for s, iv in combo) for combo in _cartesian(*alternatives)]


def cut_interval(cut, extent):
    """What a cut keeps of its subject: the value only, or everything
    below / above it within `extent`."""
    at = float(cut["at"])
    if cut.get("cmp") == BELOW:
        return [float(extent[0]), at]
    if cut.get("cmp") == ABOVE:
        return [at, float(extent[1])]
    return [at, at]


def products(card, extents):
    """The sum of products the card keeps: [{subject: [low, high]}], a
    subject absent from a product not cut by it (`extents`: each subject's
    [min, max], what a cut below or above reaches). The shown boxes join
    by their `op`, ∩ binding tighter: a ∩ box narrows the group before it
    (each product met with each of its own), a ∪ box starts another group.
    Raises ValueError beyond MAX_PRODUCTS."""
    groups = []
    for box in card.get("boxes") or ():
        if not box.get("visible", True):
            continue
        prods = _box_products(card, box, extents)
        if prods is None:
            continue
        if groups and box.get("op") == AND:
            met = [_meet(a, b) for a in groups[-1] for b in prods]
            groups[-1] = [p for p in met if p is not None]
        else:
            groups.append(prods)
        if sum(len(g) for g in groups) > MAX_PRODUCTS:
            raise ValueError(f"more than {MAX_PRODUCTS} pieces to draw: fewer ∪ ranges or cuts")
    return [p for g in groups for p in g]


def boxes(card, extents, axes=("i", "j", "k"), whole=True):
    """The crop boxes of a geometry card: each product, the axes it leaves
    free at their whole extent, clipped to the object — whole indices on
    an I/J/K grid (`whole` True, or the axes it names: a surface's I and J
    beside its X, Y and Z), the scene's coordinates on X/Y/Z (a cut at one
    value: a box flat on that axis, the cells the plane crosses)."""
    out = []
    for prod in products(card, extents):
        box = []
        for a in axes:
            lo, hi = prod.get(a, extents[a])
            if whole is True or (whole and a in whole):
                lo = max(int(extents[a][0]), int(round(float(lo))))
                hi = min(int(extents[a][1]), int(round(float(hi))))
            else:
                lo = max(float(extents[a][0]), float(lo))
                hi = min(float(extents[a][1]), float(hi))
            box.append([lo, hi])
        if all(r[0] <= r[1] for r in box):
            out.append(box)
    return out


def from_boxes(boxes_, visible, extents, subjects=("i", "j", "k")):
    """A card drawing the crop boxes `boxes_` (one Range box each) — a
    slicing made elsewhere (a session read back, the assistant)."""
    card = empty(subjects)
    vis = list(visible or [])
    for n, b in enumerate(boxes_ or ()):
        box = new_box(card, extents)
        box["visible"] = bool(vis[n]) if n < len(vis) else True
        for a, r in zip(subjects, b):
            box["ranges"][a][0]["low"], box["ranges"][a][0]["high"] = float(r[0]), float(r[1])
    return card


def from_cuts(positions, visible, extents, subjects=("i", "j", "k")):
    """A card drawing cuts made elsewhere: one Slice box holding them."""
    card = empty(subjects)
    box = {"id": new_id(card, "b"), "mode": SLICE, "visible": True,
           "ranges": {s: [] for s in subjects}, "cuts": {s: [] for s in subjects}}
    card["boxes"].append(box)
    for s in subjects:
        box["ranges"][s] = [new_range(card, extents[s])]
        flags = list((visible or {}).get(s) or [])
        for n, p in enumerate((positions or {}).get(s) or []):
            cut = new_cut(card, box, s, extents[s])
            cut["at"], cut["visible"] = float(p), bool(flags[n]) if n < len(flags) else True
    return card


def from_paths(paths, subjects):
    """A card drawing threshold-chain branches: `paths` the visible
    root-to-tip branches, each [(subject, low, high)] — a chain built
    elsewhere, one Range box per branch."""
    card = empty(subjects)
    for path in paths or ():
        box = {"id": new_id(card, "b"), "mode": RANGE, "visible": True, "ranges": {}, "cuts": {}}
        card["boxes"].append(box)
        for s, lo, hi in path:
            if s not in card["subjects"]:
                card["subjects"].append(s)
            box["ranges"].setdefault(s, []).append(
                {"id": new_id(card, "r"), "op": OR if not box["ranges"].get(s) else AND,
                 "low": float(lo), "high": float(hi)})
    for box in card["boxes"]:
        for s in card["subjects"]:
            box["cuts"].setdefault(s, [])
    return card
