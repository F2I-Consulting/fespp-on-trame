"""DerivedStore — the derived-property RECIPES of the session.

A derived property is a formula over the loaded properties of ONE grid,
not data: nothing enters the VTK pipeline (zero proxies), so a FESPP
re-execution has nothing to wipe. Consumers read values through
`property_values.values_for`, which routes a `derived://` path here.

Identity — `derived://<rep_path>#<name>`: rep paths cannot contain `#`
(the C++ MakeValidNodeName strips it), so `rsplit("#", 1)` is safe. The
path deliberately is NOT a tree node: the Data Explorer renders the C++
collector's live assembly, which is rebuilt outside our control.

Cache — one byte-capped LRU holds BOTH evaluation results and input
reads, keyed by (kind, path, real, ts, generation, definition
generation, vector component) where generation is
`server.context.load_generation`: any Selectors commit orphans every
entry and the next consumer read recomputes. Caching the INPUTS keeps the
edit-and-retype loop of a formula instant even on a large grid: only the
formula itself is evaluated again, its inputs are already in memory.
"""
import difflib
import re
from collections import OrderedDict

import numpy as np

from fespp_on_trame.engine import derived_expr
from fespp_on_trame.engine import element_type
from fespp_on_trame.engine import realization_dispatch
from fespp_on_trame.engine.utils.naming import make_valid_vtk_name

PREFIX = "derived://"
MAX_DEPTH = 5
CACHE_BYTES = 256 * 1024 * 1024

_STORE = {"instance": None}


def _session_time():
    """The session's current time (the TimeKeeper's): what a read that
    names no time step gets (engine/view_axes)."""
    from fespp_on_trame.engine import view_axes
    return view_axes.session_time()


def get_store():
    return _STORE["instance"]


def set_store(store):
    _STORE["instance"] = store


_PIN_RE = re.compile(r"^(?P<base>.+?)(?:__r(?P<real>\d+))?(?:__t(?P<ts>\d+))?$")


def split_pin(ident):
    """``(base, pin)`` of an expression identifier: ``PORO__r3`` reads
    PORO at realization 3 whatever the view's slider says, ``SOIL__t5`` at
    time step 5, ``X__r3__t5`` both — an A − B between two realizations or
    two time steps of one property is then an ordinary formula. `pin` is
    ``{"real": int | None, "ts": int | None}``, or None when nothing is
    pinned."""
    m = _PIN_RE.match(ident or "")
    if not m or (m.group("real") is None and m.group("ts") is None):
        return ident, None
    return m.group("base"), {
        "real": int(m.group("real")) if m.group("real") is not None else None,
        "ts": int(m.group("ts")) if m.group("ts") is not None else None,
    }


def is_derived(path):
    return isinstance(path, str) and path.startswith(PREFIX)


def is_difference(path):
    """True for a derived property created as an A − B: its figures read
    on a diverging scale around zero."""
    if not is_derived(path):
        return False
    store = get_store()
    d = store.get(path) if store is not None else None
    return bool(d) and (d.get("role") or "") == "difference"


def is_multireal_path(tree, path):
    try:
        return realization_dispatch.is_multirealization_property(tree, path)
    except Exception:
        return False


def path_for(rep_path, name):
    return f"{PREFIX}{rep_path}#{name}"


def parse_path(path):
    """(rep_path, name) of a derived path, or (None, None)."""
    if not is_derived(path) or "#" not in path:
        return None, None
    body = path[len(PREFIX):]
    rep_path, _, name = body.rpartition("#")
    return (rep_path or None), (name or None)


class DerivedError(Exception):
    """A recipe cannot be evaluated NOW (missing input, unloaded grid...).
    The message is consumer-facing."""


class DerivedStore:
    def __init__(self, server):
        self._server = server
        self._defs = OrderedDict()   # (rep_path, name) -> def dict
        self._cache = OrderedDict()  # key -> np.ndarray (LRU)
        self._cache_bytes = 0
        # bumped on every def create/update/delete and folded into every
        # cache key: a dependent recipe's cached output must never survive
        # its input's edit (rename included). Keystrokes never bump, so the
        # preview's input cache stays warm through the typing loop.
        self._def_gen = 0

    def _bump_defs(self):
        self._def_gen += 1

    def _is_ts_path(self, tree, path):
        if is_derived(path):
            return bool(self.axis_caps(tree, path)["is_ts"])
        try:
            nid = tree.find_node_id(path)
            kind = tree.find_type(nid) or ""
        except Exception:
            return False
        return element_type.for_kind(kind).is_time_series()

    def _ts_keypart(self, tree, path, ts_idx):
        """Cache-key time component. An explicit ts_idx keys itself; a TS
        path read in follow-the-slider mode (ts_idx=None) keys the session's
        CURRENT time (the TimeKeeper's, what such a read gets) — a time move
        is then a cache miss, never a frozen first read; an unknown time is
        never served from the cache. Non-TS paths key None (time-invariant)."""
        if ts_idx is not None:
            return ts_idx
        if not self._is_ts_path(tree, path):
            return None
        t = _session_time()
        return ("now", t) if t is not None else ("now", object())

    def _comp_keypart(self, state, path, _depth=1):
        """Cache-key vector component. A property with several values per
        element is read as ONE value — the component the session chose, or
        the magnitude — so that choice is an INPUT of the values: keyed
        without it, an entry would keep serving the previous component. A
        recipe keys the choices of its own inputs, so changing one component
        misses only the entries that read it."""
        from fespp_on_trame.engine import property_values
        if not is_derived(path):
            return property_values.component_choice(state, path)
        d = self.get(path) if _depth <= MAX_DEPTH else None
        if d is None:
            return None
        inputs = ([d["source"]] if d.get("type") == "percentile"
                  else list(d.get("inputs") or ()))
        return tuple(self._comp_keypart(state, p, _depth + 1) for p in inputs)

    # ---- generation (cache validity) --------------------------------
    def _generation(self):
        try:
            return int(getattr(self._server.context, "load_generation", 0))
        except Exception:
            return 0

    # ---- def table --------------------------------------------------
    def get(self, path):
        rep_path, name = parse_path(path)
        return self._defs.get((rep_path, name))

    def defs_for_rep(self, rep_path):
        return [d for (rp, _n), d in self._defs.items() if rp == rep_path]

    def all_defs(self):
        return list(self._defs.values())

    def active_paths(self):
        """Choice-list paths — stale defs excluded."""
        return [path_for(d["rep_path"], d["name"])
                for d in self._defs.values() if not d.get("stale")]

    def title(self, path):
        _rp, name = parse_path(path)
        return f"ƒ {name}" if name else ""

    # ---- creation / validation --------------------------------------
    def loaded_props_of_rep(self, state, tree, rep_path):
        """{array_path: (title, kind)} of the grid's LOADED properties."""
        from fespp_on_trame.engine import stats_dispatch
        out = {}
        for p in list(getattr(state, "ui_loaded_array_paths", None) or []):
            try:
                if stats_dispatch._rep_path_for_array_path(tree, p) != rep_path:
                    continue
                title, kind = stats_dispatch._title_and_kind(tree, p)
                if title:
                    out[p] = (title, kind)
            except Exception:
                continue
        return out

    def bind_identifiers(self, state, tree, rep_path, identifiers,
                         exclude_name=None):
        """Map each expression identifier to a property array_path (native
        or derived) of `rep_path`. Case-insensitive against titles AND
        their sanitized VTK names. Returns (bindings {ident -> path},
        error message or "")."""
        props = self.loaded_props_of_rep(state, tree, rep_path)
        by_key = {}
        for p, (title, _k) in props.items():
            for key in (title, make_valid_vtk_name(title)):
                by_key.setdefault(key.lower(), []).append((key, p))
        for d in self.defs_for_rep(rep_path):
            if exclude_name and d["name"] == exclude_name:
                continue
            dp = path_for(rep_path, d["name"])
            for key in (d["name"], d["vtk_name"]):
                by_key.setdefault(key.lower(), []).append((key, dp))

        bindings = {}
        for ident in identifiers:
            # a pinned identifier (PORO__r3) binds by its base name; the pin
            # is read again at evaluation
            base, _pin = split_pin(ident)
            hits = by_key.get(base.lower(), [])
            paths = sorted({p for _k, p in hits})
            if not paths:
                close = difflib.get_close_matches(
                    base.lower(), list(by_key.keys()), n=3, cutoff=0.6)
                names = sorted({k for c in close for k, _p in by_key[c]})
                hint = (" — did you mean " + " / ".join(
                    f"'{n}'" for n in names) + "?") if names else ""
                return {}, f"Unknown property '{ident}'{hint}"
            if len(paths) > 1:
                titles = sorted({k for k, _p in hits})
                return {}, (f"'{ident}' is ambiguous between "
                            + " and ".join(f"'{t}'" for t in titles))
            bindings[ident] = paths[0]
        return bindings, ""

    def validate(self, state, tree, rep_path, name, expression,
                 editing_name=None):
        """Full pre-create validation. Returns (parsed, bindings, error)."""
        parsed = derived_expr.parse(expression)
        if parsed.error:
            col = f" (column {parsed.col})" if parsed.col else ""
            return None, {}, parsed.error + col
        if not parsed.identifiers:
            return None, {}, ("The expression is a constant — reference at "
                              "least one property.")
        bindings, err = self.bind_identifiers(
            state, tree, rep_path, parsed.identifiers,
            exclude_name=editing_name)
        if err:
            return None, {}, err
        # cycle / depth guard over derived-on-derived
        err = self._check_depth(rep_path, name or editing_name, bindings)
        if err:
            return None, {}, err
        return parsed, bindings, ""

    def _check_depth(self, rep_path, name, bindings, _depth=1, _seen=None):
        if _depth > MAX_DEPTH:
            return f"Formula chain deeper than {MAX_DEPTH} levels."
        seen = set(_seen or ())
        if name:
            seen.add((rep_path, name))
        for p in bindings.values():
            if not is_derived(p):
                continue
            rp, nm = parse_path(p)
            if (rp, nm) in seen:
                return f"Cycle: '{nm}' would reference itself."
            d = self._defs.get((rp, nm))
            if d is None:
                continue
            sub = {i: pp for i, pp in zip(d["inputs_idents"], d["inputs"])}
            err = self._check_depth(rp, nm, sub, _depth + 1, seen)
            if err:
                return err
        return None

    def check_name(self, state, tree, rep_path, name, editing_name=None):
        """'' when `name` is usable on `rep_path`, else the refusal."""
        name = (name or "").strip()
        if not name:
            return "Give the property a name."
        if "#" in name:
            return "The name cannot contain '#'."
        if name.lower().startswith("fespp_"):
            return "The 'fespp_' prefix is reserved."
        vn = make_valid_vtk_name(name).lower()
        props = self.loaded_props_of_rep(state, tree, rep_path)
        for _p, (title, _k) in props.items():
            if make_valid_vtk_name(title).lower() == vn:
                return f"'{name}' collides with the loaded property '{title}'."
        for d in self.defs_for_rep(rep_path):
            if d["name"] == editing_name:
                continue
            if d["vtk_name"].lower() == vn:
                return f"'{name}' collides with the derived '{d['name']}'."
        return ""

    def create(self, state, tree, rep_path, name, expression, uom="",
               prop_kind="ContinuousProperty", editing_name=None, role=""):
        """Create (or update, when `editing_name`) a def. Returns ('', def)
        or (error, None). `role` marks what the property stands for —
        `"difference"` for an A − B. An edit that does not restate it keeps
        it only while the expression is unchanged (a rename, a unit): a new
        formula need not be a difference."""
        err = self.check_name(state, tree, rep_path, name,
                              editing_name=editing_name)
        if err:
            return err, None
        parsed, bindings, err = self.validate(
            state, tree, rep_path, name, expression, editing_name=editing_name)
        if err:
            return err, None
        previous = self._defs.get((rep_path, editing_name)) if editing_name else None
        if editing_name and editing_name != name:
            self._defs.pop((rep_path, editing_name), None)
        kept_role = ""
        same_formula = (previous is not None and " ".join(expression.split())
                        == " ".join(previous.get("expression", "").split()))
        if same_formula:
            kept_role = previous.get("role") or ""
        d = {
            "type": "expr",
            "name": name.strip(),
            "rep_path": rep_path,
            "expression": expression.strip(),
            "inputs": [bindings[i] for i in parsed.identifiers],
            "inputs_idents": list(parsed.identifiers),
            "inputs_pins": [split_pin(i)[1] for i in parsed.identifiers],
            "uom": (uom or "").strip(),
            "prop_kind": prop_kind or "ContinuousProperty",
            "vtk_name": make_valid_vtk_name(name.strip()),
            "role": role or kept_role,
            "stale": False,
            "error": "",
        }
        self._defs[(rep_path, d["name"])] = d
        self._bump_defs()
        return "", d

    def create_percentile(self, state, tree, rep_path, source_path, quantile,
                          name=None, uom=""):
        """A PERCENTILE recipe: for each cell, the q-th percentile ACROSS the
        realizations of an MR property — the standard P10/P50/P90 uncertainty
        deliverable. It collapses the realization axis, so the result is a
        plain per-cell array that every consumer reads through the seam.

        `source_path` must be a loaded MR property of `rep_path`."""
        from fespp_on_trame.engine import stats_dispatch
        if not is_multireal_path(tree, source_path):
            return ("Realization percentiles need a multi-realization "
                    "property."), None
        if stats_dispatch._rep_path_for_array_path(tree, source_path) != rep_path:
            return "The property is on another grid.", None
        src_title = stats_dispatch._title_and_kind(tree, source_path)[0] or "prop"
        q = float(quantile)
        name = (name or f"P{int(round(q))}_{make_valid_vtk_name(src_title)}")
        err = self.check_name(state, tree, rep_path, name)
        if err:
            return err, None
        d = {
            "type": "percentile",
            "name": name.strip(),
            "rep_path": rep_path,
            # the NAME carries the domain label (exceedance P10/P50/P90);
            # the description states the plain numpy percentile, unambiguous
            "expression": (f"percentile {int(round(q))} across realizations"
                           f" of {src_title}"),
            "source": source_path,
            "quantile": q,
            "inputs": [source_path],       # native input — no cycle possible
            "inputs_idents": [make_valid_vtk_name(src_title)],
            "uom": (uom or stats_dispatch._unit_for_array_path(
                tree, source_path) or "").strip(),
            "prop_kind": "ContinuousProperty",
            "vtk_name": make_valid_vtk_name(name.strip()),
            "stale": False,
            "error": "",
        }
        self._defs[(rep_path, d["name"])] = d
        self._bump_defs()
        return "", d

    def delete(self, path):
        """Drop the def; returns the list of DEPENDENT derived paths that
        referenced it (each flagged in error by the deletion), so boot can
        scrub their consumers."""
        rep_path, name = parse_path(path)
        self._defs.pop((rep_path, name), None)
        self._bump_defs()
        dependents = []
        for d in self._defs.values():
            if path in d["inputs"]:
                d["error"] = f"References the deleted '{name}'."
                dependents.append(path_for(d["rep_path"], d["name"]))
        return dependents

    # ---- lifecycle --------------------------------------------------
    def mark_stale_for_loaded(self, loaded_rep_paths):
        """A def whose grid left the loaded set is KEPT and flagged; its
        cache rows are evicted. Re-checking the grid revives it."""
        loaded = set(loaded_rep_paths or [])
        for d in self._defs.values():
            was = d.get("stale", False)
            d["stale"] = d["rep_path"] not in loaded
            if d["stale"] and not was:
                self._evict_path(path_for(d["rep_path"], d["name"]))

    def publish(self, state):
        from trame.app import get_server
        server = get_server()
        tree = getattr(server.context, "tree", None)
        rows = []
        for d in self._defs.values():
            rep_title = ""
            try:
                nid = tree.find_node_id(d["rep_path"]) if tree else None
                rep_title = (tree.find_rep_title(nid) or "") if nid else ""
            except Exception:
                pass
            rows.append({
                "path": path_for(d["rep_path"], d["name"]),
                "rep_path": d["rep_path"],
                "rep_title": rep_title or d["rep_path"].rsplit("/", 1)[-1],
                "name": d["name"],
                "expression": d["expression"],
                "uom": d["uom"],
                "prop_kind": d["prop_kind"],
                "type": d.get("type", "expr"),
                "quantile": d.get("quantile"),
                "role": d.get("role") or "",
                "stale": bool(d.get("stale")),
                "error": d.get("error") or "",
            })
        state.ui_derived_props = rows

    # ---- axis capabilities (MR / TS) --------------------------------
    def axis_caps(self, tree, path):
        """{is_mr, is_ts, reals} of a derived path: MR/TS if ANY input is;
        offered realizations = the INTERSECTION of the MR inputs' available
        indices, so every offered pick is valid by construction."""
        d = self.get(path)
        caps = {"is_mr": False, "is_ts": False, "reals": []}
        if d is None:
            return caps
        if d.get("type") == "percentile":
            # the realization axis is REDUCED away; time survives
            return {"is_mr": False,
                    "is_ts": self._is_ts_path(tree, d["source"]),
                    "reals": []}
        reals = None
        pins = d.get("inputs_pins") or [None] * len(d["inputs"])
        for p, pin in zip(d["inputs"], pins):
            # a pinned axis is fixed by the formula: it offers no pick
            pin_real = pin is not None and pin.get("real") is not None
            pin_ts = pin is not None and pin.get("ts") is not None
            if is_derived(p):
                sub = self.axis_caps(tree, p)
                caps["is_mr"] |= sub["is_mr"] and not pin_real
                caps["is_ts"] |= sub["is_ts"] and not pin_ts
                if sub["is_mr"] and not pin_real:
                    r = set(sub["reals"])
                    reals = r if reals is None else (reals & r)
                continue
            try:
                nid = tree.find_node_id(p)
                kind = tree.find_type(nid) or ""
            except Exception:
                kind = ""
            et = element_type.for_kind(kind)
            if et.is_multi_realization() and not pin_real:
                caps["is_mr"] = True
                r = set(realization_dispatch.available_realization_indices(
                    tree, p))
                reals = r if reals is None else (reals & r)
            if et.is_time_series() and not pin_ts:
                caps["is_ts"] = True
        caps["reals"] = sorted(reals) if reals else []
        return caps

    # ---- evaluation -------------------------------------------------
    def evaluate(self, state, tree, source_registry, path,
                 real_idx=None, ts_idx=None, _depth=1):
        """np.ndarray of the recipe at (real_idx, ts_idx), or raises
        DerivedError naming what is missing."""
        if _depth > MAX_DEPTH:
            raise DerivedError(f"Formula chain deeper than {MAX_DEPTH}.")
        d = self.get(path)
        if d is None:
            raise DerivedError("Unknown derived property.")
        if d.get("stale"):
            raise DerivedError(
                f"The grid of '{d['name']}' is not loaded — check it again.")
        gen = self._generation()
        # a percentile collapses the realization axis — real_idx is
        # meaningless for it, normalise the key so picks don't fragment it
        eff_real = None if d.get("type") == "percentile" else real_idx
        key = ("out", path, eff_real, self._ts_keypart(tree, path, ts_idx),
               gen, self._def_gen, self._comp_keypart(state, path))
        hit = self._cache_get(key)
        if hit is not None:
            return hit

        from fespp_on_trame.engine import property_values
        if d.get("type") == "percentile":
            src = d["source"]
            reals = realization_dispatch.available_realization_indices(
                tree, src)
            if not reals:
                raise DerivedError(
                    f"'{d['name']}': no realizations to reduce.")
            stack = []
            for r in reals:
                ikey = ("in", src, int(r),
                        self._ts_keypart(tree, src, ts_idx),
                        gen, self._def_gen,
                        self._comp_keypart(state, src))
                v = self._cache_get(ikey)
                if v is None:
                    v = property_values.values_for(
                        state, tree, source_registry, src, d["rep_path"],
                        real_idx=int(r), ts_idx=ts_idx)
                    if v is None:
                        raise DerivedError(
                            f"'{d['name']}': could not read realization {r}"
                            " (is the property still checked?).")
                    self._cache_put(ikey, v)
                stack.append(v)
            if len({len(v) for v in stack}) > 1:
                raise DerivedError(
                    f"'{d['name']}': realizations have different sizes.")
            import warnings
            with np.errstate(all="ignore"), warnings.catch_warnings():
                warnings.simplefilter("ignore")   # all-NaN slices -> NaN
                out = np.nanpercentile(np.array(stack), d["quantile"], axis=0)
            out = np.asarray(out, dtype=np.float64).ravel()
            out[~np.isfinite(out)] = np.nan
            self._cache_put(key, out)
            return out

        parsed = derived_expr.parse(d["expression"])
        if parsed.error:
            raise DerivedError(parsed.error)
        bindings = {}
        length = None
        pins = d.get("inputs_pins") or [None] * len(d["inputs"])
        for ident, p, pin in zip(d["inputs_idents"], d["inputs"], pins):
            # a pinned input reads at ITS realization / time step, whatever
            # the caller's (the view's slider) — that is what makes
            # PORO__r3 - PORO__r7 a difference between two realizations
            in_real = pin["real"] if (pin and pin.get("real") is not None) else real_idx
            in_ts = pin["ts"] if (pin and pin.get("ts") is not None) else ts_idx
            ikey = ("in", p, in_real, self._ts_keypart(tree, p, in_ts),
                    gen, self._def_gen, self._comp_keypart(state, p))
            vals = self._cache_get(ikey)
            if vals is None:
                if is_derived(p):
                    vals = self.evaluate(state, tree, source_registry, p,
                                         real_idx=in_real, ts_idx=in_ts,
                                         _depth=_depth + 1)
                else:
                    # a non-MR input ignores real_idx by construction
                    # (_resolve_vtk_name only suffixes MR kinds); a non-TS
                    # input is time-invariant under the TimeKeeper move
                    vals = property_values.values_for(
                        state, tree, source_registry, p, d["rep_path"],
                        real_idx=in_real, ts_idx=in_ts)
                if vals is None:
                    raise DerivedError(
                        f"Could not read '{ident}' (is it still checked?).")
                self._cache_put(ikey, vals)
            if length is None:
                length = len(vals)
            elif len(vals) != length:
                raise DerivedError(
                    f"'{ident}' has {len(vals)} values where "
                    f"{length} were expected — different supports.")
            bindings[ident] = vals
        try:
            out = derived_expr.evaluate(parsed, bindings)
        except (ValueError, TypeError, ArithmeticError) as exc:
            # OverflowError (float pow towers), numpy TypeError/ValueError:
            # every arithmetic failure becomes a DerivedError, the one error
            # `property_values.values_for` catches
            raise DerivedError(str(exc) or type(exc).__name__)
        if length is not None and len(out) != length:
            raise DerivedError("The result is not cell-aligned.")
        self._cache_put(key, out)
        return out

    def preview(self, state, tree, source_registry, rep_path, expression,
                real_idx=None, ts_idx=None, editing_name=None):
        """Stats of an UNSAVED formula (the panel's live preview), evaluated
        at full resolution. `editing_name` applies the SAME self-exclusion
        as create, so preview and Create can never disagree on a name.
        Returns ({n, nan, nan_pct, min, mean, max, p10, p90}, error) —
        p10 / p90 are percentiles over the CELLS of this one result, not
        the across-realization percentiles `create_percentile` builds."""
        parsed, bindings_paths, err = self.validate(
            state, tree, rep_path, None, expression,
            editing_name=editing_name)
        if err:
            return None, err
        from fespp_on_trame.engine import property_values
        bindings = {}
        length = None
        gen = self._generation()
        for ident in parsed.identifiers:
            p = bindings_paths[ident]
            pin = split_pin(ident)[1]
            in_real = pin["real"] if (pin and pin.get("real") is not None) else real_idx
            in_ts = pin["ts"] if (pin and pin.get("ts") is not None) else ts_idx
            ikey = ("in", p, in_real, self._ts_keypart(tree, p, in_ts),
                    gen, self._def_gen, self._comp_keypart(state, p))
            vals = self._cache_get(ikey)
            if vals is None:
                if is_derived(p):
                    try:
                        vals = self.evaluate(state, tree, source_registry, p,
                                             real_idx=in_real, ts_idx=in_ts)
                    except DerivedError as exc:
                        return None, str(exc)
                else:
                    vals = property_values.values_for(
                        state, tree, source_registry, p, rep_path,
                        real_idx=in_real, ts_idx=in_ts)
                if vals is None:
                    return None, f"Could not read '{ident}' (is it checked?)."
                self._cache_put(ikey, vals)
            if length is None:
                length = len(vals)
            elif len(vals) != length:
                return None, (f"'{ident}' has {len(vals)} values where "
                              f"{length} were expected — different supports.")
            bindings[ident] = vals
        try:
            out = derived_expr.evaluate(parsed, bindings)
        except (ValueError, TypeError, ArithmeticError) as exc:
            return None, (str(exc) or type(exc).__name__)
        fin = out[np.isfinite(out)]
        n = int(len(out))
        if not len(fin):
            return {"n": n, "nan": n, "nan_pct": 100.0}, ""
        return {
            "n": n,
            "nan": int(n - len(fin)),
            "nan_pct": 100.0 * (n - len(fin)) / max(1, n),
            "min": float(np.min(fin)),
            "mean": float(np.mean(fin)),
            "max": float(np.max(fin)),
            "p10": float(np.percentile(fin, 10)),
            "p90": float(np.percentile(fin, 90)),
            "values": out,
        }, ""

    # ---- LRU --------------------------------------------------------
    def _cache_get(self, key):
        arr = self._cache.get(key)
        if arr is not None:
            self._cache.move_to_end(key)
        return arr

    def _cache_put(self, key, arr):
        try:
            nbytes = int(arr.nbytes)
        except Exception:
            return
        if nbytes > CACHE_BYTES:
            return
        old = self._cache.pop(key, None)
        if old is not None:
            self._cache_bytes -= int(old.nbytes)
        self._cache[key] = arr
        self._cache_bytes += nbytes
        while self._cache_bytes > CACHE_BYTES and self._cache:
            _k, v = self._cache.popitem(last=False)
            self._cache_bytes -= int(v.nbytes)

    def _evict_path(self, path):
        for k in [k for k in self._cache if k[1] == path]:
            v = self._cache.pop(k)
            self._cache_bytes -= int(v.nbytes)
