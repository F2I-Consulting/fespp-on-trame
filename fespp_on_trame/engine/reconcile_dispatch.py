"""Well ↔ model reconciliation by property KIND.

For every well in the log view, a measured log is set against the grid
property of the same kind, sampled along the well's trajectory
(`engine/trajectory_sampling`), zone by zone — the zones being what
`engine/welllog_dispatch` already gives the log view: the stratigraphic
column laid onto the well, else the marker pairs.

The pairing is semantic: FESPP's `propertyKind` on both sides (the RESQML
kind, not a curve mnemonic — PHIE, PHIT and NPHI all say "porosity"). A file
that declares no kind falls back to the names. Units are read, not guessed:
a log in % against a grid in v/v is scaled, anything else different is
flagged and left alone. Read-only: nothing is written to the EPC.

Every row is one (well, zone, log, grid property): the two statistics, the
gap, and the gap in log standard deviations — the "z" the table is sorted by,
so the first rows are where the model contradicts the logs most. A zone
with fewer than `MIN_SAMPLES` log samples has a z that means little: its
row is flagged and ranked after the others, never dropped.

Zones are bounded on TRUE VERTICAL DEPTH, as in the log view, so the two
tables report the same samples for the same zone. Beside the plain grid mean
the row carries the mean weighted by the LENGTH of hole traversed inside the
zone: the synthetic curve is read at a fixed step, so a sample near a bound
stands for a stretch that is only partly inside. Both are shown, and the
column headers say which is which. Each row also discloses the PWLS quantity
class of its two sides: two known and different classes (a length against a
volume) demote the row to the bottom of the table with the reason, and a
class PWLS does not know is said to be unchecked rather than assumed right.
"""
import math
import re

from fespp_on_trame.engine import (
    node_kinds, pwls_kinds, stats_dispatch, trajectory_sampling, welllog_dispatch,
)

# units that all mean "a fraction", and the ones that mean "a percentage"
# (p.u. included): one vocabulary for the whole application (node_kinds)
_FRACTION_UNITS = node_kinds.FRACTION_UNITS
_PERCENT_UNITS = node_kinds.PERCENT_UNITS

# how a log and a grid property go together, best first
_BASIS_RANK = {"kind": 0, "name": 1, "kind~": 2, "name~": 3}

# the log samples a zone needs for its z to rank the row: below, the flag
# `n<MIN_SAMPLES` is set and the row sorts after every other
MIN_SAMPLES = 5

# the short curve mnemonics a log or a grid property is commonly titled
# by, each with the words that name the same quantity: a WHOLE word equal
# to one of them pairs the two sides (SW ↔ WatSat), any other word under
# four letters (a unit, an article, a rank) does not
_MNEMONICS = {
    "sw": {"sw", "swat", "watsat"},
    "so": {"so", "soil", "oilsat"},
    "sg": {"sg", "sgas", "gassat"},
    "phi": {"phi", "phie", "phit", "poro", "porosity"},
    "ntg": {"ntg", "nettogross"},
    "gr": {"gr", "gammaray"},
    "vsh": {"vsh", "vshale"},
    "rho": {"rho", "rhob", "density"},
}
_MNEMONIC_OF = {alias: m for m, aliases in _MNEMONICS.items() for alias in aliases}


def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _tokens(s):
    """The words that carry meaning in a kind or a title: those of four
    letters or more, and a short curve mnemonic written as a whole word —
    the other short words pair everything with everything. A word that
    names a mnemonic's quantity also yields the mnemonic, so ``SW`` and
    ``WatSat`` share a token."""
    out = set()
    for t in _norm(s).split():
        if len(t) >= 4:
            out.add(t)
        mnemonic = _MNEMONIC_OF.get(t)
        if mnemonic:
            out.add(mnemonic)
    return out


def match_basis(log_kind, log_name, prop_kind, prop_name):
    """How a log and a grid property go together: ``"kind"`` (the same kind
    title), ``"kind~"`` (one kind a specialisation of the other in the PWLS
    hierarchy — a neutron porosity IS a porosity — or, for kinds the
    hierarchy does not know, kinds sharing a word: an approximate pairing
    the row flags), ``"name"`` / ``"name~"`` (the same, on the titles, when
    a side declares no kind), or None. Two declared kinds that disagree are
    NOT a pair, whatever the names say — and two PWLS kinds that are merely
    siblings (water / gas saturation) never are: the semantics win."""
    lk, pk = _norm(log_kind), _norm(prop_kind)
    if lk and pk:
        if lk == pk:
            return "kind"
        rel = pwls_kinds.relation(log_kind, prop_kind)
        if rel is not None:
            return "kind" if rel[0] == 0 else "kind~"
        if pwls_kinds.known(log_kind) and pwls_kinds.known(prop_kind):
            return None
        if _tokens(lk) & _tokens(pk):
            return "kind~"
        return None
    ln, pn = _norm(log_name), _norm(prop_name)
    if ln and ln == pn:
        return "name"
    if _tokens(ln) & _tokens(pn):
        return "name~"
    return None


def basis_reason(log_kind, prop_kind, basis):
    """The words the row's flag shows for an approximate pairing."""
    if basis == "kind~":
        rel = pwls_kinds.relation(log_kind, prop_kind)
        if rel is not None:
            a, b = (log_kind, prop_kind) if rel[1] == "a under b" else (prop_kind, log_kind)
            return f"{a} ⊂ {b}"
        return f"kinds share a word: {log_kind} / {prop_kind}"
    if basis == "name~":
        return "titles share a word"
    if basis == "name":
        return "paired by name"
    return None


# ---- the quantity class: is this even the same kind of quantity? ----------
# `match_basis` already refuses two KNOWN, unrelated PWLS kinds, so a class
# guard can only ever fire where it cannot: on the shared-word branches,
# reached only when a side declares no kind or a kind the table ignores. The
# class is therefore resolved from the kind OR, failing that, from the title.

# a class that carries no information: the PWLS root "property" is
# "unitless", and about a third of the kinds inherit it
_NEUTRAL_CLASSES = {"", "unitless"}

# every way PWLS spells "a ratio of two like quantities": these are the SAME
# quantity class for pairing purposes — a porosity is "volume per volume" and
# a water saturation "dimensionless", and they must pair
_FRACTION_CLASSES = {
    "dimensionless", "volume per volume", "length per length",
    "mass per mass", "force per force", "power per power", "time per time",
    "amount of substance per amount of substance", "PWLS:pressure per pressure",
}


def quantity_class_of(kind, title):
    """The PWLS quantity class of a side: its KIND's, or — when the side
    declares no kind, or the kind is not in the table — its TITLE's, since a
    property is often titled with a kind name. "" when neither is known."""
    return pwls_kinds.quantity_class(kind) or pwls_kinds.quantity_class(title)


def _norm_class(c):
    """The class as the guard compares it: the uninformative ones read as
    unknown, and every spelling of a ratio of like quantities reads the same.
    Once normalised, no kind of the shipped PWLS table conflicts with an
    ancestor's class: the guard never breaks a pairing the hierarchy
    allows."""
    c = (c or "").strip()
    if c in _NEUTRAL_CLASSES:
        return ""
    return "fraction" if c in _FRACTION_CLASSES else c


def class_mismatch(class_log, class_prop):
    """True when both classes are known and they are not the same quantity —
    a length against a volume. Either side unknown: not checked, never a
    refusal."""
    a, b = _norm_class(class_log), _norm_class(class_prop)
    return bool(a) and bool(b) and a != b


def class_note(class_log, class_prop):
    """What the row says about the two quantity classes — that they differ,
    or that one of them is not in the table, so nothing was checked."""
    if class_mismatch(class_log, class_prop):
        return f"different quantity classes: {class_log} vs {class_prop}"
    a, b = _norm_class(class_log), _norm_class(class_prop)
    if a and b:
        return None
    side = ("on both sides" if not a and not b else
            "on the log" if not a else "on the grid property")
    return (f"quantity class unknown {side}: the pairing is not checked"
            " against one")


def pair_reason(log_kind, prop_kind, basis, log_title=None, prop_title=None):
    """The whole reason a pair is what it is: the basis words, and what the
    quantity classes of the two sides said."""
    parts = [p for p in (basis_reason(log_kind, prop_kind, basis),
                         class_note(quantity_class_of(log_kind, log_title),
                                    quantity_class_of(prop_kind, prop_title)))
             if p]
    return "; ".join(parts) or None


def with_classes(pair, logs, props_by_path):
    """`pair` plus its two PWLS quantity classes, whether they clash, and
    the whole reason the pairing is what it is (`pair_reason`).

    Recomputed for a HAND-EDITED pair too: the panel sends an edited list
    back as ``{log, prop, basis}`` alone, and a pairing nobody should read
    must be flagged in the pairs strip whether the app proposed it or the
    user did — the more so as a pair whose zones hold no sample produces no
    table row to carry the flag."""
    log_meta = (logs or {}).get(pair.get("log")) or {}
    prop = (props_by_path or {}).get(pair.get("prop")) or {}
    cl = quantity_class_of(log_meta.get("kind"), pair.get("log"))
    cp = quantity_class_of(prop.get("kind"), prop.get("title"))
    return {**pair, "class_log": cl, "class_prop": cp,
            "class_mismatch": class_mismatch(cl, cp),
            "why": pair_reason(log_meta.get("kind"), prop.get("kind"),
                               pair.get("basis"), pair.get("log"),
                               prop.get("title"))}


def auto_pairs(logs, props):
    """``[{log, prop, basis, why, class_log, class_prop, class_mismatch}]`` —
    every log against the grid properties it goes with, keeping for each log
    only its best basis (an exact kind beats a shared word). `logs` is
    ``{title: {kind, unit}}``, `props` a list of ``{path, title, kind, unit}``.

    A pair whose two sides are known to be different quantities is DEMOTED,
    not dropped: any pair without a class mismatch beats it, and it survives
    alone only when nothing else goes with that log — flagged, and ranked
    last."""
    out = []
    for title, meta in (logs or {}).items():
        found = []
        for p in props or []:
            basis = match_basis(meta.get("kind"), title, p.get("kind"), p.get("title"))
            if not basis:
                continue
            bad = class_mismatch(quantity_class_of(meta.get("kind"), title),
                                 quantity_class_of(p.get("kind"), p.get("title")))
            found.append((_BASIS_RANK[basis] + (10 if bad else 0), basis, p["path"]))
        if not found:
            continue
        best = min(r for r, _b, _p in found)
        for r, basis, path in found:
            if r == best:
                prop = next(p for p in props if p["path"] == path)
                out.append(with_classes({"log": title, "prop": path,
                                         "basis": basis}, logs, {path: prop}))
    return out


def unit_factor(log_unit, prop_unit):
    """``(factor for the LOG values, flag | None)``: a % log against a
    fraction grid is scaled down (and the other way up); two fractions or
    two equal units need nothing; anything else is flagged and left as is —
    a conversion nobody asked for would hide the very mismatch this is for."""
    lu, pu = (log_unit or "").strip().lower(), (prop_unit or "").strip().lower()
    if lu == pu:
        return 1.0, None
    if lu in _PERCENT_UNITS and pu in _FRACTION_UNITS:
        return 0.01, f"log {log_unit.strip()} → v/v"
    if pu in _PERCENT_UNITS and lu in _FRACTION_UNITS:
        return 100.0, f"log v/v → {prop_unit.strip()}"
    if lu in _FRACTION_UNITS and pu in _FRACTION_UNITS:
        return 1.0, None
    if lu in _PERCENT_UNITS and pu in _PERCENT_UNITS:
        return 1.0, None
    return 1.0, f"units differ: {lu or '?'} vs {pu or '?'}"


def _stats(vals):
    n = len(vals)
    mean = sum(vals) / n
    var = sum((v - mean) ** 2 for v in vals) / n
    return {"n": n, "mean": mean, "std": math.sqrt(var),
            "p50": welllog_dispatch._percentile(sorted(vals), 50)}


def traversed_lengths(depths, top, bottom):
    """``[ℓ]`` — the length of hole each sample stands for INSIDE
    ``[top, bottom)``, sample by sample, on the sorted `depths`.

    The synthetic curve is read at a fixed step along the hole, so a sample
    near a zone boundary stands for a stretch that is partly outside the
    zone. A sample owns the half-step to each neighbour (the first and the
    last mirror their single one); that stretch is clipped to the zone and
    floored at 0, so a sample just outside contributes nothing and one
    astride the bound contributes its share. A lone sample bounds no
    stretch: its length is 0, and the weighted mean is then not reported
    rather than guessed."""
    n = len(depths)
    if n < 2:
        return [0.0] * n
    out = []
    for i, d in enumerate(depths):
        lo = (d + depths[i - 1]) / 2.0 if i else d - (depths[1] - d) / 2.0
        hi = ((d + depths[i + 1]) / 2.0 if i < n - 1
              else d + (d - depths[n - 2]) / 2.0)
        out.append(max(0.0, min(bottom, hi) - max(top, lo)))
    return out


def _on_axis(triples, vertical):
    """``[(depth, value)]`` sorted on the axis the zone is bounded on: the
    true vertical depth, or the drawn one for a zone that has no usable
    vertical bounds (a horizontal section)."""
    out = [((t if vertical else d), v) for v, d, t in triples
           if not vertical or t is not None]
    return sorted(out, key=lambda p: p[0])


def rows_for_well(well, pairs, logs, props_by_path):
    """The reconciliation rows of ONE well of a log-view payload that carries
    the sampled grid curves (``<title> (grid)``) among its ``_full`` samples.
    Pure: no ParaView, no state — the unit tests drive it on a dict.

    Zones are bounded, and samples selected, on the TRUE VERTICAL depth —
    the same axis `welllog_dispatch` sums its thicknesses on, so a zone holds
    the same samples in both tables."""
    full = well.get("_full") or {}
    zones, source = welllog_dispatch.zone_intervals(well)
    if not zones:
        d = well.get("depth") or {}
        # the whole well: every sample, whatever the axis its depth is on
        zones = [{"name": "(whole well)", "top": d.get("min", -math.inf),
                  "bottom": d.get("max", math.inf),
                  "top_tvd": -math.inf, "bottom_tvd": math.inf}]
        source = "well"
    rows = []
    for pair in pairs or []:
        prop = props_by_path.get(pair.get("prop"))
        if prop is None:
            continue
        log_title = pair.get("log")
        ls = full.get(log_title)
        gs = full.get(f"{prop['title']} (grid)")
        if not ls or not gs:
            continue
        log_meta = (logs or {}).get(log_title) or {}
        factor, unit_flag = unit_factor(log_meta.get("unit"), prop.get("unit"))
        class_log = quantity_class_of(log_meta.get("kind"), log_title)
        class_grid = quantity_class_of(prop.get("kind"), prop.get("title"))
        checked = bool(_norm_class(class_log)) and bool(_norm_class(class_grid))
        mismatch = class_mismatch(class_log, class_grid)
        l_tri, g_tri = welllog_dispatch._triples(ls), welllog_dispatch._triples(gs)
        for z in zones:
            top, bottom = float(z["top"]), float(z["bottom"])
            t0, t1 = z.get("top_tvd"), z.get("bottom_tvd")
            no_tvd = t0 is None or t1 is None or float(t1) <= float(t0)
            lo, hi = (top, bottom) if no_tvd else (float(t0), float(t1))
            lseq, gseq = _on_axis(l_tri, not no_tvd), _on_axis(g_tri, not no_tvd)
            lv = [float(v) * factor for d, v in lseq
                  if v is not None and lo <= d < hi]
            # the grid mean over the LENGTH of hole traversed in the zone,
            # beside the plain one: a sample astride a zone bound counts only
            # for the part of its stretch that is inside
            lengths = traversed_lengths([d for d, _v in gseq], lo, hi)
            gv, num, den = [], 0.0, 0.0
            for (d, v), w in zip(gseq, lengths):
                if v is None:
                    continue
                if lo <= d < hi:
                    # the unweighted mean is one sample one vote, so it takes
                    # the samples whose station is in the zone
                    gv.append(float(v))
                if w > 0.0:
                    # the weighted one takes every sample that OWNS hole
                    # inside the zone — a station just outside still stands
                    # for the half-step that reaches in, and dropping it
                    # would leave `len_grid` short of the zone it names
                    num += float(v) * w
                    den += w
            if not lv or not gv:
                continue
            a, b = _stats(lv), _stats(gv)
            gap = a["mean"] - b["mean"]
            mean_len = num / den if den > 0 else None
            total = den
            flags = []
            if a["n"] < MIN_SAMPLES:
                flags.append(f"n<{MIN_SAMPLES}")
            if unit_flag:
                flags.append(unit_flag)
            if pair.get("basis") in ("kind~", "name~", "name"):
                flags.append(basis_reason(log_meta.get("kind"), prop.get("kind"),
                                          pair.get("basis")) or (
                    "approximate kind" if pair["basis"] == "kind~" else "paired by name"))
            if mismatch:
                flags.append(f"different quantity classes: {class_log} vs {class_grid}")
            elif not checked:
                flags.append("quantity class not checked")
            if no_tvd:
                flags.append("selected on the drawn axis: the zone bounds have"
                             " no usable true vertical depth")
            log_unit = log_meta.get("unit") or ""
            prop_unit = prop.get("unit") or ""
            rows.append({
                "well": well.get("name"), "zone": z["name"],
                "top": top, "bottom": bottom, "zone_source": source,
                "kind": log_meta.get("kind") or prop.get("kind") or "",
                "log": log_title, "log_unit": log_unit,
                "prop": prop["title"], "prop_unit": prop_unit,
                # the unit the compared values are in: the log's, or the grid
                # property's once the log has been scaled to it
                "unit": prop_unit if factor != 1.0 else log_unit,
                "prop_path": prop["path"], "basis": pair.get("basis"),
                "class_log": class_log, "class_grid": class_grid,
                "class_checked": checked, "class_mismatch": mismatch,
                "n_log": a["n"], "n_grid": b["n"],
                "mean_log": a["mean"], "mean_grid": b["mean"],
                "mean_grid_len": mean_len, "len_grid": total,
                "p50_log": a["p50"], "p50_grid": b["p50"],
                "gap": gap,
                "rel": (gap / abs(a["mean"])) if a["mean"] else None,
                "z": (gap / a["std"]) if a["std"] > 0 else None,
                "flags": flags,
            })
    return rows


def sort_rows(rows):
    """Where the model contradicts the logs most, first: by |z|, a row with
    no z (a constant log) after every other, then by |gap|. A row with
    fewer than `MIN_SAMPLES` log samples ranks after all of those, whatever
    its z — it stays in the table, flagged. A row whose two sides are known
    to be different quantities ranks after even those: it is not a
    contradiction, it is a pairing nobody should read."""
    return sorted(rows, key=lambda r: (
        bool(r.get("class_mismatch")),
        r.get("n_log", MIN_SAMPLES) < MIN_SAMPLES,
        -(abs(r["z"]) if r.get("z") is not None else -1.0),
        -abs(r.get("gap") or 0.0)))


# ---- what the session offers --------------------------------------------

def channel_paths(tree, well_path):
    """Every log channel under a wellbore — its frames' channels, the very
    walk the log view draws from (role WellboreChannel, class names as the
    fallback)."""
    wid = tree.find_node_id(well_path) if well_path else None
    if wid is None:
        return []
    out = []
    for fid in welllog_dispatch._descendants_of_kinds(
            tree, wid, welllog_dispatch._FRAME_ROLES, welllog_dispatch._FRAME_KINDS):
        for cid in welllog_dispatch._children_of_kinds(
                tree, fid, welllog_dispatch._CHANNEL_ROLES,
                welllog_dispatch._CHANNEL_KINDS):
            cpath = tree.find_path(cid)
            if cpath:
                out.append(cpath)
    return out


def session_inputs(welllog_wells, own_logs, dropped, selected,
                   wellbore_of, channels_of):
    """What the panel reads, from its TWO doors — pure, so it is tested
    without a session.

    * the log view's wells (``ui_welllog_wells``): every READ channel under
      them;
    * the panel's own tree (``ui_reconcile_logs``): the channels ticked
      there, and only those — a well the panel took in for one log does not
      bring in every curve the data tree happens to have read under it;
    * less what the panel's tree unticked (``ui_reconcile_dropped``): out of
      this table, still loaded.

    Returns ``(wells, selected)``: the wells in order (the log view's first,
    no repeat) and the selection the dispatch filters by — the session's,
    with every channel of those wells the panel does not hold taken out, and
    everything dropped taken out. Trajectories and markers stay: the zones
    are read from them."""
    dropped = set(dropped or ())
    read = set(selected or ())
    wells = []
    for w in list(welllog_wells or []) + [wellbore_of(p) for p in own_logs or ()]:
        if w and w not in wells:
            wells.append(w)
    from_view = set(welllog_wells or ())
    held, every = set(), set()
    for w in wells:
        chans = channels_of(w)
        every.update(chans)
        if w in from_view:
            held.update(c for c in chans if c in read)
    held.update(c for c in (own_logs or ()) if c in read)
    held -= dropped
    eff = [p for p in (selected or ())
           if p not in dropped and (p not in every or p in held)]
    return wells, eff


def log_channels(tree, well_paths, selected_paths):
    """``{title: {kind, unit}}`` over the CHECKED channels of the wells —
    what the log view draws, so what can be reconciled."""
    checked = set(selected_paths or [])
    out = {}
    for well_path in well_paths or []:
        wid = tree.find_node_id(well_path)
        if wid is None:
            continue
        for fid in welllog_dispatch._descendants_of_kinds(
                tree, wid, welllog_dispatch._FRAME_ROLES, welllog_dispatch._FRAME_KINDS):
            for cid in welllog_dispatch._children_of_kinds(
                    tree, fid, welllog_dispatch._CHANNEL_ROLES,
                    welllog_dispatch._CHANNEL_KINDS):
                cpath = tree.find_path(cid)
                if not cpath or cpath not in checked:
                    continue
                title = tree.find_title(cid) or "channel"
                out.setdefault(title, {
                    "kind": welllog_dispatch._attr(tree, cid, "propertyKind"),
                    "unit": welllog_dispatch._attr(tree, cid, "uom"),
                })
    return out


def grid_properties(tree, loaded_paths):
    """``[{path, title, kind, unit}]`` — the loaded properties that live on a
    grid (a channel cannot be sampled along a trajectory, it IS one)."""
    props = []
    for p in loaded_paths or []:
        rep_path = stats_dispatch._rep_path_for_array_path(tree, p)
        rid = tree.find_node_id(rep_path) if rep_path else None
        if rid is None or (tree.find_type(rid) or "") not in (
                "IjkGrid", "UnstructuredGrid"):
            continue
        nid = tree.find_node_id(p)
        props.append({
            "path": p,
            "title": stats_dispatch._title_and_kind(tree, p)[0] or p,
            "kind": welllog_dispatch._attr(tree, nid, "propertyKind"),
            "unit": welllog_dispatch._attr(tree, nid, "uom"),
        })
    return props


def compute(state, tree, source_registry, pairs=None, step=1.0,
            wells=None, selected=None, dropped=None):
    """The panel's whole payload: ``{rows, pairs, logs, props, wells, note,
    step, auto}`` — `pairs` None means "pair automatically" (and `auto`
    says so, for the panel's badge).

    `wells` / `selected` / `dropped` are what the panel reads, merged from
    its two doors by `session_inputs`; left None, `wells` and `selected`
    default to the log view's wells and the session's selection."""
    if wells is None:
        wells = list(getattr(state, "ui_welllog_wells", None) or [])
    if selected is None:
        selected = list(getattr(state, "selected_paths", None) or [])
    out = set(dropped or ())
    logs = log_channels(tree, wells, selected) if wells else {}
    props = [p for p in grid_properties(
                 tree, getattr(state, "ui_loaded_array_paths", None) or [])
             if p["path"] not in out]
    props_by_path = {p["path"]: p for p in props}
    auto = pairs is None
    if auto:
        pairs = auto_pairs(logs, props)
    pairs = [with_classes(p, logs, props_by_path) for p in pairs or []
             if p.get("log") in logs and p.get("prop") in props_by_path]
    base = {"rows": [], "pairs": pairs, "auto": auto, "step": step,
            "logs": [{"title": t, **m} for t, m in logs.items()],
            "props": props, "wells": len(wells), "note": "",
            "min_samples": MIN_SAMPLES}
    if not wells:
        base["note"] = ("No log yet: tick a wellbore or its logs in this"
                        " panel's tree (the tree button), or right-click a"
                        " wellbore → Add to Well Log view.")
        return base
    if not logs:
        base["note"] = ("No log is read: tick the logs in this panel's tree,"
                        " or in the log view's.")
        return base
    if not props:
        base["note"] = ("No grid property: tick one in this panel's tree"
                        " (Reservoir tab) or in the data tree.")
        return base
    if not pairs:
        base["note"] = ("No log goes with a loaded grid property, by kind or by"
                        " name — pair them by hand below.")
        return base
    requests = [{"well": w, "prop": p, "step": step}
                for w in wells for p in sorted({pr["prop"] for pr in pairs})]
    synth = trajectory_sampling.curves_for(state, tree, source_registry, requests)
    payload = welllog_dispatch.build_payload(
        tree, source_registry, wells, selected,
        strati_columns=getattr(state, "ui_strati_columns", None),
        synthetics=synth)
    rows = []
    for well in payload.get("wells") or []:
        rows.extend(rows_for_well(well, pairs, logs, props_by_path))
    base["rows"] = sort_rows(rows)
    if not rows:
        base["note"] = ("The pairs gave no row: the trajectories may not enter"
                        " the grid, or no zone holds both a log sample and a"
                        " grid cell.")
    return base


def csv_payload(result):
    """`{"name", "header"}` the panel's Copy CSV writes its rows under: the
    sampling step, the pair count, the basis legend, and what the value
    columns are expressed in. Empty without a row."""
    from fespp_on_trame.engine.utils import csv_export as ce
    r = result or {}
    if not r.get("rows"):
        return dict(ce.EMPTY_PAYLOAD)
    fields = [
        ("sampling step", f"{r.get('step')} (the grid read along the trajectory"
                          " every that many depth units)"),
        ("pairs", f"{len(r.get('pairs') or [])}"
                  + (" (automatic)" if r.get("auto") else " (set by hand)")),
        ("basis", "kind = the same property kind; kind~ = one kind a"
                  " specialisation of the other, or kinds sharing a word;"
                  " name / name~ = paired on the titles; manual = set by hand"),
        ("values", "mean, P50 and delta in the unit column of each row (the"
                   " log's unit, or the grid property's when the flags say the"
                   " log was scaled to it); delta_rel is a fraction of the log"
                   " mean; z = delta over the log's standard deviation"
                   "; mean_grid_len is the grid mean weighted by the length of"
                   " hole traversed in the zone (traversed_length), on true"
                   " vertical depth"),
        ("flags", f"n<{r.get('min_samples', MIN_SAMPLES)} = too few log samples"
                  " to trust the row; a unit or pairing doubt is spelled out"
                  "; a quantity-class mismatch means the two sides are not the"
                  " same kind of quantity and the row ranks last;"
                  " \"quantity class not checked\" means PWLS knows neither"
                  " side's class"),
    ]
    return ce.payload("log_grid", fields)
