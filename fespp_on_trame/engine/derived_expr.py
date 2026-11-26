"""Safe expression engine of the derived-property calculator.

`parse` turns the user's formula into a compiled, WHITELISTED python
expression: an AST walk refuses everything but arithmetic, comparisons,
conditionals and a fixed numpy function set — no attribute access, no
subscripts, no strings, no keywords — then `evaluate` runs it with empty
builtins over numpy arrays. Raw user text is never exec'd.

The function table is NaN-transparent (numpy semantics) so gaps flow
through a formula the way they flow through every consumer: a NaN input
cell yields a NaN output cell.
"""
import ast
import math

import numpy as np

MAX_LEN = 2000
MAX_NODES = 500

# 1-arg NaN-aware scalar reductions are what make the normalize template
# `(X - min(X)) / (max(X) - min(X))` expressible.
FUNCS = {
    "log10": np.log10, "log2": np.log2, "log": np.log, "ln": np.log,
    "exp": np.exp, "sqrt": np.sqrt, "abs": np.abs,
    "clip": np.clip, "where": np.where,
    "floor": np.floor, "ceil": np.ceil, "round": np.round,
    "power": np.power,
    "isnan": np.isnan, "isfinite": np.isfinite,
    "sin": np.sin, "cos": np.cos, "tan": np.tan, "arctan": np.arctan,
    "minimum": np.minimum, "maximum": np.maximum,
    "min": np.nanmin, "max": np.nanmax,
    "mean": np.nanmean, "sum": np.nansum,
}
CONSTANTS = {"pi": math.pi, "e": math.e, "nan": math.nan}

# (min, max) positional arguments per function. Enforced in parse() so a
# ufunc's SECOND positional (its `out=` slot — np.sqrt(a, b) writes into b)
# can NEVER be reached: that would silently corrupt the input array in place,
# and the inputs are the very LRU-cached buffers every other consumer reads.
# A wrong arity is also caught here rather than escaping as a raw TypeError.
ARITY = {
    "log10": (1, 1), "log2": (1, 1), "log": (1, 1), "ln": (1, 1),
    "exp": (1, 1), "sqrt": (1, 1), "abs": (1, 1),
    "clip": (3, 3), "where": (3, 3),
    "floor": (1, 1), "ceil": (1, 1), "round": (1, 1),
    "power": (2, 2), "minimum": (2, 2), "maximum": (2, 2),
    "isnan": (1, 1), "isfinite": (1, 1),
    "sin": (1, 1), "cos": (1, 1), "tan": (1, 1), "arctan": (1, 1),
    "min": (1, 1), "max": (1, 1), "mean": (1, 1), "sum": (1, 1),
}
assert set(ARITY) == set(FUNCS), "ARITY and FUNCS must cover the same names"

_ALLOWED_OPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv,
                ast.Mod, ast.Pow, ast.BitAnd, ast.BitOr)
_ALLOWED_UNARY = (ast.USub, ast.UAdd)
_ALLOWED_CMP = (ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE)


class _IntToFloat(ast.NodeTransformer):
    """Rewrite every integer literal as a float. `a ** b` on Python ints can
    build a multi-million-digit bignum (9**9**9) that pegs a core BEFORE
    numpy is ever reached; as floats the same tower overflows to inf (or a
    caught OverflowError) in O(1). Numeric results are unchanged for real
    formulas (2 vs 2.0 over float arrays)."""

    def visit_Constant(self, node):
        if isinstance(node.value, int) and not isinstance(node.value, bool):
            return ast.copy_location(ast.Constant(float(node.value)), node)
        return node


class Parsed:
    """Result of `parse`: the compiled code and its free identifiers, or
    an error message with the column it points at."""
    __slots__ = ("code", "identifiers", "error", "col")

    def __init__(self, code=None, identifiers=(), error=None, col=None):
        self.code = code
        self.identifiers = tuple(identifiers)
        self.error = error
        self.col = col


def _err(message, col=None):
    return Parsed(error=message, col=col)


def parse(expr):
    """Compile `expr` or explain why not. Returns a Parsed whose
    `identifiers` are the free names to bind to property arrays."""
    text = (expr or "").strip()
    if not text:
        return _err("Empty expression.")
    if len(text) > MAX_LEN:
        return _err(f"Expression longer than {MAX_LEN} characters.")
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        return _err(f"Syntax error: {exc.msg}.", exc.offset)

    names = []
    count = 0
    for node in ast.walk(tree):
        count += 1
        if count > MAX_NODES:
            return _err(f"Expression larger than {MAX_NODES} nodes.")
        col = getattr(node, "col_offset", None)
        if isinstance(node, (ast.Expression, ast.Load)):
            continue
        if isinstance(node, ast.BinOp):
            if not isinstance(node.op, _ALLOWED_OPS):
                return _err("Operator not allowed.", col)
            continue
        if isinstance(node, _ALLOWED_OPS + _ALLOWED_UNARY + _ALLOWED_CMP):
            continue
        if isinstance(node, ast.UnaryOp):
            if not isinstance(node.op, _ALLOWED_UNARY):
                return _err("Unary operator not allowed.", col)
            continue
        if isinstance(node, ast.Compare):
            if not all(isinstance(o, _ALLOWED_CMP) for o in node.ops):
                return _err("Comparison operator not allowed.", col)
            continue
        if isinstance(node, ast.BoolOp):
            # numpy raises "truth value of an array is ambiguous" on
            # `and`/`or` — refuse at parse with the working alternative
            return _err("Use '&' / '|' between conditions instead of "
                        "'and' / 'or' (numpy arrays).", col)
        if isinstance(node, ast.IfExp):
            continue
        if isinstance(node, ast.Call):
            if (not isinstance(node.func, ast.Name)
                    or node.func.id not in FUNCS):
                fn = getattr(node.func, "id", None) or "expression"
                return _err(f"Unknown function '{fn}'.", col)
            if node.keywords:
                return _err("Keyword arguments are not allowed.", col)
            lo, hi = ARITY[node.func.id]
            if not (lo <= len(node.args) <= hi):
                want = str(lo) if lo == hi else f"{lo} to {hi}"
                return _err(f"'{node.func.id}' takes {want} argument(s), "
                            f"got {len(node.args)}.", col)
            continue
        if isinstance(node, ast.Name):
            nid = node.id
            if nid.startswith("__"):
                return _err(f"Name '{nid}' is not allowed.", col)
            if nid not in FUNCS and nid not in CONSTANTS and nid not in names:
                names.append(nid)
            continue
        if isinstance(node, ast.Constant):
            if not isinstance(node.value, (int, float)):
                return _err("Only numeric constants are allowed.", col)
            continue
        return _err(f"'{type(node).__name__}' is not allowed here.", col)

    try:
        tree = ast.fix_missing_locations(_IntToFloat().visit(tree))
        code = compile(tree, "<derived>", "eval")
    except (ValueError, TypeError) as exc:
        return _err(f"Cannot compile: {exc}.")
    return Parsed(code=code, identifiers=names)


def evaluate(parsed, bindings):
    """Run a successful `parse` result over `bindings` {identifier ->
    np.ndarray}. Returns a float64 array with +-inf folded into NaN (the
    uniform "missing" every consumer already masks). Raises ValueError
    on a scalar-only result."""
    env = dict(FUNCS)
    env.update(CONSTANTS)
    # Read-only VIEWS: the bindings are the LRU-cached buffers shared with
    # every consumer — a second guard behind the arity check, so any
    # in-place write raises instead of silently poisoning the cache.
    for k, v in bindings.items():
        try:
            ro = v.view()
            ro.flags.writeable = False
            env[k] = ro
        except Exception:
            env[k] = v
    with np.errstate(all="ignore"):
        result = eval(parsed.code, {"__builtins__": {}}, env)  # noqa: S307
    arr = np.asarray(result, dtype=np.float64)
    if arr.ndim == 0:
        raise ValueError(
            "The expression is a constant — reference at least one property.")
    arr = np.array(arr, dtype=np.float64, copy=True).ravel()
    arr[~np.isfinite(arr)] = np.nan
    return arr


def to_pv_expression(text, parsed, name_map, assoc="CELLS"):
    """Regenerate the formula as a PythonCalculator expression, every
    identifier emitted as inputs[0].CellData['<real vtk name>'] (the
    quoted form resolves whatever characters the VTK name holds). Serves
    only the fallback 3D colouring path — a PythonCalculator over an
    isolated block — never the numpy evaluation of `evaluate`."""
    field = "CellData" if assoc == "CELLS" else "PointData"
    out = text
    # longest first so PORO_NTG is not clobbered by a PORO replacement
    for ident in sorted(parsed.identifiers, key=len, reverse=True):
        real = name_map.get(ident, ident).replace("'", "\\'")
        out = _replace_ident(out, ident, f"inputs[0].{field}['{real}']")
    return out


def _replace_ident(text, ident, repl):
    """Replace whole-word occurrences of `ident` only."""
    import re
    return re.sub(rf"\b{re.escape(ident)}\b", repl, text)
