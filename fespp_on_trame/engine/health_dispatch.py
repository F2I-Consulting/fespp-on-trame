"""Data health — what is wrong with what was loaded, gathered in one table.

The signals already exist, scattered: partial objects (a reference whose
target is not in the file — FESPP marks the stub in the assembly), datasets
fesapi could not read (the captured VTK log, and the nodes the engine had
to deselect), frames whose depths fall outside their trajectory, properties
without a kind or a unit, kinds outside PWLS, a CRS the projection cannot
use or coordinates that cannot be what the code says, duplicated titles,
and values outside what their kind allows (a porosity above 1, a negative
permeability) wherever the reader wrote the property's bounds on its node.
Read here into findings ``{severity, category, object, path, message,
count}`` — the question one asks of an unknown EPC, answered in one place,
read-only.
"""
import re

from fespp_on_trame.engine import element_type as _et
from fespp_on_trame.engine import geo, node_kinds, pwls_kinds
from fespp_on_trame.engine import node_facts
from fespp_on_trame.engine.utils import numfmt

_UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_PARTIAL = node_kinds.PARTIAL_PREFIX
_GRIDS = ("IjkGrid", "UnstructuredGrid")
_SEVERITY_RANK = {"error": 0, "warning": 1, "info": 2}


def _finding(severity, category, message, obj="", path="", count=None):
    return {"severity": severity, "category": category, "object": obj or "",
            "path": path or "", "message": message, "count": count}


def _is_property(node_type):
    return node_facts.is_property_kind(node_type)


# ---- the captured VTK / fesapi messages ------------------------------------

def classify_message(text, level=""):
    """``(severity, category, message)`` of one captured line, or None for
    noise. fesapi's own wording is kept: it names the dataset, the uuid,
    the depth — far more actionable than a paraphrase."""
    t = " ".join(str(text or "").split())
    if not t:
        return None
    low = t.lower()
    if "error when rendering uuid" in low or "hdf5" in low or "could not be opened" in low:
        return "error", "data", t
    if "out of the trajectory" in low:
        return "warning", "well", t
    if "cannot be associated" in low or "assumed to be a partial" in low:
        return "info", "kind", t
    if "fesapi error" in low:
        return "error", "data", t
    lv = (level or "").upper()
    if lv.startswith("ERR"):
        return "warning", "log", t
    if lv.startswith("WARN"):
        return "info", "log", t
    return None


_ADDR_RE = re.compile(r"0x[0-9a-fA-F]+")
_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _template(msg):
    """The message with its uuids, addresses and numbers blanked — the same
    complaint about forty properties is one finding, counted."""
    t = _UUID_RE.sub("<uuid>", msg)
    t = _ADDR_RE.sub("<addr>", t)
    return _NUM_RE.sub("<n>", t)


def log_findings(messages, tree, limit=60):
    """The findings the captured log gives — one per distinct complaint
    (uuids, addresses and numbers blanked), counted, each tied to the object
    the first occurrence's uuid names when the tree knows it."""
    by_key, order = {}, []
    for m in messages or []:
        got = classify_message((m or {}).get("text"), (m or {}).get("level"))
        if got is None:
            continue
        severity, category, msg = got
        key = _template(msg)[:240]
        if key in by_key:
            by_key[key]["count"] += 1
            continue
        title, path = "", ""
        for u in _UUID_RE.findall(msg):
            nid = tree.find_node_id_by_uuid(u) if tree is not None else None
            if nid:
                title = tree.find_title(nid) or ""
                path = tree.find_path(nid) or ""
                break
        by_key[key] = _finding(severity, category, msg[:300], title, path, 1)
        order.append(key)
    out = []
    for key in order[:limit]:
        f = by_key[key]
        if f["count"] > 1:
            f["message"] = f"{f['message']} (×{f['count']})"
        out.append(f)
    if len(order) > limit:
        out.append(_finding("info", "log", f"{len(order) - limit} more distinct messages not listed"))
    return out


# ---- the CRS ----------------------------------------------------------------

def utm_sanity(epsg, bounds):
    """A sentence when the data's coordinates cannot be the eastings and
    northings of the UTM code they claim — the code is then not the one
    the data was written in — else None."""
    try:
        fam = geo._utm_family(int(epsg))
    except (TypeError, ValueError):
        return None
    if fam is None or not bounds or len(bounds) < 4:
        return None
    x0, x1, y0, y1 = bounds[0], bounds[1], bounds[2], bounds[3]
    # VTK's "no geometry" bounds are ±1e299: nothing loaded says nothing
    if (not all(abs(v) < 1e12 for v in (x0, x1, y0, y1))
            or x0 > x1 or y0 > y1):
        return None
    zone, south, datum = fam
    problems = []
    if x1 < 100_000 or x0 > 900_000:
        problems.append(f"eastings {numfmt.fmt_fixed(x0, 0)}..{numfmt.fmt_fixed(x1, 0)} m"
                        " where a UTM easting"
                        " lies between 100 000 and 900 000 m")
    if y1 < 0 or y0 > 10_000_000:
        problems.append(f"northings {numfmt.fmt_fixed(y0, 0)}..{numfmt.fmt_fixed(y1, 0)} m"
                        " where a UTM northing"
                        " lies between 0 and 10 000 000 m")
    if not problems:
        return None
    return (f"the coordinates cannot be EPSG:{epsg} (UTM zone "
            f"{zone}{'S' if south else 'N'}, {datum}): " + "; ".join(problems))


def crs_findings(crs_probe, bounds):
    """The CRS findings, from ``crs_probe()`` — boot's ``_any_usable_crs``:
    ``(usable, info, n_crs, reason)`` — and the data bounds."""
    try:
        usable, info, n_crs, reason = crs_probe()
    except Exception as exc:
        return [_finding("info", "crs", f"the CRS could not be read: {exc}")]
    if n_crs == 0:
        return [_finding("warning", "crs", "no CRS object in the loaded data:"
                         " the Globe cannot place it on the Earth")]
    out = []
    if not usable:
        if info and info.get("epsg") is not None:
            why = geo.epsg_problem(info.get("epsg")) or ""
            if info.get("time"):
                why = (why + "; " if why else "") + "a TIME CRS: its vertical axis is time, not depth"
            out.append(_finding("warning", "crs",
                                f"EPSG:{info['epsg']} cannot place the data on the Earth"
                                + (f" — {why}" if why else ""), info.get("title") or ""))
        else:
            out.append(_finding("warning", "crs",
                                "no projected EPSG code in the loaded data"
                                + (f" (the CRS says: {reason})" if reason else "")))
        return out
    epsg = info.get("epsg")
    out.append(_finding("info", "crs",
                        f"EPSG:{epsg} ({info.get('how') or 'declared'}) over {n_crs} CRS object(s)",
                        info.get("title") or ""))
    doubt = utm_sanity(epsg, bounds)
    if doubt:
        out.append(_finding("warning", "crs", doubt, info.get("title") or ""))
    return out


# ---- the values against their kind ------------------------------------------
# What a kind's values can be, read off the PWLS ancestry: a fraction lies in
# [0, 1] (or [0, 100] declared in %), a positive-by-nature quantity never
# goes below 0. Small and explicit; a kind under none of these is not
# checked. The aliases are RESQML 2.0.1 names outside PWLS 4.0.

_FRACTION_ANCESTORS = frozenset({
    "porosity", "saturation", "net gross thickness ratio",
    "net pay gross thickness ratio", "net reservoir gross thickness ratio",
    "relative permeability"})
_POSITIVE_ANCESTORS = frozenset({"permeability", "thickness", "volume"})
# PWLS files these under thickness, but a depth difference between two
# seismic events is signed
_SIGNED_KINDS = frozenset({
    "peak peak delta depth", "peak trough delta depth",
    "trough peak delta depth", "trough trough delta depth"})
_ALIASES = {"net to gross ratio": "fraction",
            "rock permeability": "positive", "permeability rock": "positive",
            "rock volume": "positive"}


def expected_domain(kind):
    """``"fraction"``, ``"positive"`` or None for a property kind."""
    k = (kind or "").strip().lower()
    if not k or k in _SIGNED_KINDS:
        return None
    alias = _ALIASES.get(k)
    if alias:
        return alias
    for anc in pwls_kinds.ancestors(k):
        if anc in _FRACTION_ANCESTORS:
            return "fraction"
        if anc in _POSITIVE_ANCESTORS:
            return "positive"
    return None


def range_findings(kind, uom, lo, hi, title, path):
    """The findings the declared bounds of one property give against its
    kind's domain; ``[]`` when nothing is wrong or nothing is known
    (`lo` / `hi` None — the caller counts that as unchecked)."""
    dom = expected_domain(kind)
    if dom is None or (lo is None and hi is None):
        return []
    out = []
    uom = (uom or "").strip()
    # every spelling the files use for a percentage (p.u., PU, %vol...), as
    # the volumetrics and the well-log cutoffs read them
    pct = uom.lower() in node_kinds.PERCENT_UNITS
    if dom == "fraction" and hi is not None:
        if not uom and hi > 1.0:
            # the reader writes no unit on the nodes that carry bounds (a
            # time series, a realization set): the unit is unknown here
            out.append(_finding(
                "warning", "range",
                f"values up to {numfmt.fmt(hi)}, no unit on this node: a"
                f" {kind} in % or a mis-scaled fraction — check the unit"
                " (a fraction expects 0 to 1, a percentage 0 to 100)",
                title, path))
        elif not pct and hi > 1.0:
            out.append(_finding(
                "warning", "range",
                f"values up to {numfmt.fmt(hi)}: a percentage declared as a"
                f" fraction? ('{kind}' in {uom} expects 0 to 1 — check the"
                " unit, or read it as % in Volumetrics)", title, path))
        elif pct and hi > 100.0:
            out.append(_finding(
                "warning", "range",
                f"values up to {numfmt.fmt(hi)} %: above 100 % ('{kind}' in %"
                " expects 0 to 100 — check the unit)", title, path))
    if lo is not None and lo < 0.0:
        out.append(_finding(
            "error", "range",
            f"values down to {numfmt.fmt(lo)}: a {kind} cannot be negative —"
            " check the null value or the unit", title, path))
    return out


def _bound(text):
    """A declared bound as a float; None when empty, unparsable or NaN."""
    try:
        v = float(text)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


# ---- the tree ------------------------------------------------------------------

def _attr(asm, nid, name):
    try:
        return asm.GetAttributeOrDefault(nid, name, "") or ""
    except Exception:
        return ""


def _selectable(node_type):
    try:
        return bool(_et.for_kind(node_type).is_selectable())
    except Exception:
        return True


#: the node types of a wellbore marker, as the reader writes them
_MARKER_TYPES = ("Marker", "WellboreMarker")


def tree_findings(tree, far=None, skip=()):
    """``(findings, counts_by_type)`` from one walk of the assembly.

    `far(paths)`: those of the rows `paths` a store holds (an ETP
    dataspace). Its reader writes no measured depth on the markers, so a
    marker without one says nothing of a well read from there.
    `skip`: the rows that are not data, and what is under them — the
    session's own velocity model."""
    asm = getattr(tree, "_data_assembly", None)
    if asm is None:
        return [], {}
    findings, counts = [], {}
    no_kind, no_uom, kinds_out = {}, {}, set()
    markers_no_md, partials, unchecked = {}, {}, {}
    # properties a lazy ETP load left on the store ("lazy" = "1" on the node):
    # their kind, unit and range are not known YET, which is not "none"
    not_read = {}
    for nid, children in tree.iter_nodes():
        if skip and nid and node_facts.is_under(tree.find_path(nid) or "", skip):
            continue
        # repeated titles among the REAL objects (uuid-named) of the same
        # type under a titled parent: a marker frame picking the same horizon
        # twice — not the untitled containers that gather every property or
        # every marker of the file, where repeats are the normal case
        titles = {}
        parent_title = (tree.find_title(nid) or "").strip() if nid else ""
        if parent_title:
            for c in children:
                t = (tree.find_title(c) or "").strip()
                try:
                    name = asm.GetNodeName(c) or ""
                except Exception:
                    name = ""
                if t and name.startswith("_") and _UUID_RE.match(name[1:] or ""):
                    titles.setdefault((tree.find_type(c) or "", t), []).append(c)
        dups = {t: len(ids) for (_ty, t), ids in titles.items() if len(ids) > 1}
        if dups:
            # one finding per parent, not one per repeated title: a marker
            # frame that picks several horizons twice yields a single row
            shown = sorted(dups.items(), key=lambda kv: -kv[1])
            findings.append(_finding(
                "info", "duplicate",
                f"{len(dups)} title{'s' if len(dups) > 1 else ''} repeated among its children: "
                + ", ".join(f"'{t}' ×{n}" for t, n in shown[:6])
                + (" …" if len(shown) > 6 else ""),
                (tree.find_title(nid) or "").replace(_PARTIAL, "").strip() if nid else "",
                tree.find_path(nid) or "" if nid else "", len(dups)))
        if nid == 0:
            continue
        ntype = tree.find_type(nid) or ""
        raw_title = _attr(asm, nid, "title")
        title = raw_title.replace(_PARTIAL, "").strip()
        path = tree.find_path(nid) or ""
        counts[ntype or "?"] = counts.get(ntype or "?", 0) + 1
        if raw_title.startswith(_PARTIAL) or ntype == "partial" or not _selectable(ntype):
            # the same missing object is referenced from many places (a log
            # every well's frame points at): one row per title, with the count
            parent = asm.GetParent(nid)
            ptitle = (tree.find_title(parent) or "").replace(_PARTIAL, "").strip() if parent else ""
            entry = partials.setdefault(title, {"type": ntype, "path": path, "n": 0, "under": {}})
            entry["n"] += 1
            if ptitle:
                entry["under"][ptitle] = entry["under"].get(ptitle, 0) + 1
            continue
        if _is_property(ntype):
            rid = tree.find_representation_node(nid)
            rep_key = tree.find_path(rid) if rid is not None else path
            rep_title = tree.find_rep_title(rid) if rid is not None else ""
            if _attr(asm, nid, "lazy") == "1":
                entry = not_read.setdefault(rep_key, [rep_title, 0])
                entry[1] += 1
                continue
            kind = _attr(asm, nid, "propertyKind")
            if not kind:
                entry = no_kind.setdefault(rep_key, [rep_title, 0])
                entry[1] += 1
            elif not pwls_kinds.known(kind):
                kinds_out.add(kind)
            ptype = tree.find_prop_type(nid) or ""
            if ptype == "ContinuousProperty" and not _attr(asm, nid, "uom"):
                entry = no_uom.setdefault(rep_key, [rep_title, 0])
                entry[1] += 1
            lo, hi = _attr(asm, nid, "minvalue"), _attr(asm, nid, "maxvalue")
            try:
                if lo != "" and hi != "" and float(lo) == float(hi):
                    findings.append(_finding(
                        "info", "grid",
                        f"declared minimum and maximum are both {lo}: a"
                        " constant property, or bounds written wrong",
                        title, path))
            except ValueError:
                pass
            # the values against the kind's domain, from the bounds the
            # reader wrote on the node — no data is read here
            if expected_domain(kind):
                flo, fhi = _bound(lo), _bound(hi)
                if flo is None and fhi is None:
                    entry = unchecked.setdefault(rep_key, [rep_title, 0, set()])
                    entry[1] += 1
                    entry[2].add(kind.strip().lower())
                else:
                    uom = _attr(asm, nid, "uom")
                    findings += range_findings(kind, uom, flo, fhi, title, path)
            continue
        if ntype == "Wellbore":
            kinds = {tree.find_type(d) or "" for d in tree.find_all_descendant_ids(nid)}
            if "Trajectory" not in kinds:
                findings.append(_finding("warning", "well",
                                         "no trajectory: its logs and markers cannot be"
                                         " placed in 3D", title, path))
            continue
        if ntype in ("Frame", "MarkerFrame", "SeismicWellboreFrame"):
            tuuid = _attr(asm, nid, "trajectoryUuid")
            if tuuid and tree.find_node_id_by_uuid(tuuid) is None:
                findings.append(_finding("warning", "well",
                                         f"its trajectory ({tuuid}) is not in the file",
                                         title, path))
            if ntype == "Frame" and not any(
                    _is_property(tree.find_type(c) or "") for c in children):
                findings.append(_finding("info", "well", "a frame without any channel",
                                         title, path))
            continue
        if ntype in _MARKER_TYPES:
            if not _attr(asm, nid, "md"):
                wid = tree.find_parent_node_id_with_type(nid, "Wellbore")
                key = tree.find_path(wid) if wid is not None else "?"
                entry = markers_no_md.setdefault(key, [(tree.find_title(wid) or "") if wid is not None else "", 0])
                entry[1] += 1
            continue
        if ntype in _GRIDS:
            parent = asm.GetParent(nid)
            holder = parent if parent and (tree.find_role(parent) or "") not in ("", "Root") else nid
            if not tree.has_property_descendant(holder) and not tree.has_property_descendant(nid):
                findings.append(_finding("info", "grid", "a grid without any property",
                                         title, path))
    for title, e in partials.items():
        under = sorted(e["under"].items(), key=lambda kv: -kv[1])
        where = ", ".join(f"'{p}'" + (f" ×{n}" if n > 1 else "") for p, n in under[:3])
        findings.append(_finding(
            "error", "partial",
            f"referenced but not in the file ({e['type'] or 'object'})"
            + (f" {e['n']} times" if e["n"] > 1 else "")
            + (f", under {where}" if where else "") + ": nothing can be loaded",
            title, e["path"], e["n"]))
    for rep_key, (rep_title, n) in no_kind.items():
        findings.append(_finding("info", "kind",
                                 f"{n} propert{'y' if n == 1 else 'ies'} declare no property kind"
                                 " (standard 2.0.1 kinds on an older plugin, or local kinds"
                                 " without a title): they pair by name only",
                                 rep_title, rep_key, n))
    if not_read:
        n = sum(e[1] for e in not_read.values())
        findings.append(_finding(
            "info", "kind",
            f"{n} propert{'y' if n == 1 else 'ies'} still on the store (a lazy ETP load,"
            f" under {len(not_read)} object{'s' if len(not_read) > 1 else ''}): kind, unit"
            " and range are checked once they are opened or read",
            "", "", n))
    for rep_key, (rep_title, n) in no_uom.items():
        findings.append(_finding("warning", "unit",
                                 f"{n} continuous propert{'y' if n == 1 else 'ies'} without a unit",
                                 rep_title, rep_key, n))
    if kinds_out:
        shown = sorted(kinds_out)
        findings.append(_finding("info", "kind",
                                 f"{len(shown)} kind{'s' if len(shown) > 1 else ''} not in PWLS 4.0"
                                 f" (RESQML 2.0.1 names or local kinds): "
                                 + ", ".join(shown[:12]) + (" …" if len(shown) > 12 else ""),
                                 "", "", len(shown)))
    silent = far(list(markers_no_md)) if far is not None and markers_no_md else ()
    for key, (wtitle, n) in markers_no_md.items():
        if key in silent:
            continue
        findings.append(_finding("info", "well",
                                 f"{n} marker{'s' if n > 1 else ''} without a measured depth:"
                                 " placed by geometry (TVD)", wtitle, key if key != "?" else "", n))
    for rep_key, (rep_title, n, kinds) in unchecked.items():
        shown = sorted(kinds)
        findings.append(_finding(
            "info", "range",
            f"{n} propert{'y' if n == 1 else 'ies'} with a bounded kind"
            f" ({', '.join(shown[:4])}{' …' if len(shown) > 4 else ''}) declare no"
            " minimum/maximum: their values were not range-checked (the check"
            " reads the bounds the file declares on the property, none here)",
            rep_title, rep_key, n))
    return findings, counts


# ---- the whole table --------------------------------------------------------

EMPTY_GEOMETRY_MESSAGE = (
    "Every point at one place: the store served empty coordinates for this"
    " object, so nothing is drawn."
    " Report it to the store's administrators.")


def empty_geometry_findings(empty):
    """One error per object whose points all sit at one place: ``empty`` is
    the session's ``ui_empty_geometry``, path -> title."""
    return [_finding("error", "data", EMPTY_GEOMETRY_MESSAGE, title or path.rsplit("/", 1)[-1], path, 1)
            for path, title in sorted((empty or {}).items())]


def compute(state, tree, crs_probe=None, bounds=None, far=None):
    """``{"summary", "findings", "note"}`` — the whole health table: the
    tree, the captured log, the deselected datasets and the CRS, without
    duplicates, sorted by severity then category. `far(paths)`: those of
    the rows a store holds (`tree_findings`)."""
    # the session's own velocity model is no data: nothing is said of it
    own = list(getattr(state, "ui_model_tree_rows", None) or [])
    findings, counts = tree_findings(tree, far=far, skip=own)
    findings += [f for f in log_findings(getattr(state, "vtk_log_messages", None), tree)
                 if not (f["path"] and node_facts.is_under(f["path"], own))]
    findings += empty_geometry_findings(getattr(state, "ui_empty_geometry", None))
    for nid_key, err in (getattr(state, "ui_invalid_node_errors", None) or {}).items():
        try:
            nid = int(nid_key)
        except (TypeError, ValueError):
            continue
        findings.append(_finding("error", "data",
                                 f"unreadable dataset, deselected: {err}",
                                 tree.find_title(nid) or "", tree.find_path(nid) or ""))
    if crs_probe is not None and counts:
        findings += crs_findings(crs_probe, bounds)
    # the same object mirrored in two places of the tree says its thing once
    unique, seen = [], set()
    for f in findings:
        key = (f["severity"], f["category"], f["object"], f["message"])
        if key not in seen:
            seen.add(key)
            unique.append(f)
    findings = unique
    findings.sort(key=lambda f: (_SEVERITY_RANK.get(f["severity"], 3), f["category"],
                                 f["object"], f["message"]))
    by_sev = {"error": 0, "warning": 0, "info": 0}
    for f in findings:
        by_sev[f["severity"]] = by_sev.get(f["severity"], 0) + 1
    types = sorted(counts.items(), key=lambda kv: -kv[1])
    summary = {
        "errors": by_sev["error"], "warnings": by_sev["warning"], "infos": by_sev["info"],
        "objects": sum(counts.values()),
        "partial": counts.get("Partial", 0) + counts.get("partial", 0),
        "types": [[t, n] for t, n in types[:14]],
        # the files the session handed to the reader, with what each added
        # to the tree (the import endpoint keeps the list; a failed read is
        # listed too, as such)
        "files": [dict(f) for f in (getattr(state, "ui_loaded_files", None) or [])],
    }
    if not counts:
        note = "Nothing loaded yet — import an EPC or connect a dataspace."
    elif not findings:
        note = ("Nothing to report: no partial object, no unreadable dataset,"
                " kinds and units declared, a usable CRS.")
    else:
        note = ""
    return {"summary": summary, "findings": findings, "note": note}


def csv_payload(result):
    """`{"name", "header"}` the panel's Copy CSV writes its rows under."""
    from fespp_on_trame.engine.utils import csv_export as ce
    r = result or {}
    if not r.get("findings"):
        return dict(ce.EMPTY_PAYLOAD)
    sm = r.get("summary") or {}
    fields = [
        ("files", "; ".join(
            f"{f.get('name')} ({'failed to read' if f.get('failed') else str(f.get('objects', 0)) + ' objects'})"
            for f in (sm.get("files") or [])) or "none imported (a dataspace, or nothing yet)"),
        ("objects", f"{sm.get('objects', 0)} in the tree, {sm.get('partial', 0)} partial"),
        ("findings", f"{sm.get('errors', 0)} errors, {sm.get('warnings', 0)} warnings,"
                     f" {sm.get('infos', 0)} infos"),
        ("count", "how many times the same finding occurred, when more than"
                  " once; empty for a single occurrence"),
    ]
    return ce.payload("health", fields)
