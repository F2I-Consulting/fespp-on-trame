"""One way to write a number on screen — the same rule the widgets apply
in `widgets/_shared/numfmt.js`, so a value reads the same in every panel.

A measured quantity is shown to four significant digits, in scientific
notation outside [1e-3, 1e6], its thousands grouped by a thin space; a
missing value is an en dash. A count keeps every digit. The CSV exports
never go through here: they carry the raw values (`csv_export`).

Outside the rule, on purpose: the tick labels of the Plotly charts (drawn
by Plotly) and the 3D colour bar, drawn by ParaView from a printf format —
`SCALAR_BAR_RANGE_FORMAT` gives it the four significant digits, without the
thousands grouping and with printf's own switch to an exponent.
"""
import math
from decimal import Decimal, ROUND_HALF_UP

SCALAR_BAR_RANGE_FORMAT = "%.4g"

DASH = "–"
THIN = " "
NBSP = " "

_SUPERSCRIPT = {2: "²", 3: "³", 4: "⁴"}


def _group(digits):
    """'1234567' -> '1 234 567' (thin spaces), untouched up to 3 digits."""
    if len(digits) <= 3:
        return digits
    head = len(digits) % 3
    parts = ([digits[:head]] if head else []) + [
        digits[i:i + 3] for i in range(head, len(digits), 3)]
    return THIN.join(parts)


def _strip_zeros(s):
    return s.rstrip("0").rstrip(".") if "." in s else s


def _to_float(v):
    """(float, ok) — a string is parsed; one that is not a number is a
    label and is handed back unchanged by the caller."""
    if isinstance(v, bool):
        return float(v), True
    if isinstance(v, str):
        try:
            return float(v.strip()), True
        except ValueError:
            return None, False
    try:
        return float(v), True
    except (TypeError, ValueError):
        return None, False


def _round_sig(a, digits=4):
    """`a` (> 0) rounded to `digits` significant digits, half away from
    zero on the exact binary value; an exact Decimal."""
    d = Decimal(a)
    e = d.adjusted()
    q = d.scaleb(-e).quantize(Decimal(1).scaleb(-(digits - 1)),
                              rounding=ROUND_HALF_UP)
    if q >= 10:
        q = Decimal("1." + "0" * (digits - 1))
        e += 1
    return q.scaleb(e)


def fmt(v):
    """A measured quantity: 4 significant digits, scientific outside
    [1e-3, 1e6], thin-space thousands, `–` when missing."""
    if v is None:
        return DASH
    if isinstance(v, str) and not v.strip():
        return DASH
    f, ok = _to_float(v)
    if not ok:
        return v
    if math.isnan(f):
        return DASH
    if math.isinf(f):
        return "∞" if f > 0 else "-∞"
    if f == 0:
        return "0"
    sign = "-" if f < 0 else ""
    r = _round_sig(abs(f))
    e = r.adjusted()
    if r < Decimal("0.001") or r > Decimal(1000000):
        mant = _strip_zeros(format(r.scaleb(-e), "f"))
        return f"{sign}{mant}e{'-' if e < 0 else '+'}{abs(e)}"
    decimals = max(0, 3 - e)
    s = _strip_zeros(format(r.quantize(Decimal(1).scaleb(-decimals)), "f"))
    if "." in s:
        whole, frac = s.split(".", 1)
        return f"{sign}{_group(whole)}.{frac}"
    return f"{sign}{_group(s)}"


def fmt_int(v):
    """A count: every digit, thin-space grouped, `–` when missing."""
    if v is None:
        return DASH
    f, ok = _to_float(v)
    if not ok:
        return v
    if math.isnan(f) or math.isinf(f):
        return DASH
    n = int(math.floor(abs(f) + 0.5))
    return ("-" if f < 0 and n else "") + _group(str(n))


def fmt_pct(fraction):
    """A fraction as a percentage: `12.35 %`."""
    if fraction is None:
        return DASH
    f, ok = _to_float(fraction)
    if not ok or math.isnan(f):
        return DASH
    return f"{fmt(f * 100.0)}{NBSP}%"


def fmt_fixed(v, decimals):
    """Coordinates, depths, contacts: a fixed number of decimals, half
    away from zero on the exact value, thin-space grouped, never
    scientific."""
    if v is None:
        return DASH
    f, ok = _to_float(v)
    if not ok:
        return v
    if math.isnan(f) or math.isinf(f):
        return DASH
    decimals = max(0, int(decimals))
    d = Decimal(f).quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)
    s = format(abs(d), "f")
    sign = "-" if d < 0 else ""
    if "." in s:
        whole, frac = s.split(".", 1)
        return f"{sign}{_group(whole)}.{frac}"
    return f"{sign}{_group(s)}"


def unit_power(uom, power, ascii=False):
    """The unit a statistic is expressed in: `m3/m3`, `(m3/m3)²` — the
    ASCII form `(m3/m3)^2` for a CSV column header; "" without a unit or
    for a dimensionless statistic."""
    uom = (uom or "").strip()
    try:
        power = int(power)
    except (TypeError, ValueError):
        power = 0
    if not uom or power == 0:
        return ""
    if power == 1:
        return uom
    if ascii:
        return f"({uom})^{power}"
    return f"({uom}){_SUPERSCRIPT.get(power, '^' + str(power))}"


def plural(count, one, many=None):
    """`1 wellbore`, `3 wellbores` — the count grouped like any other, and
    the noun written out. A sentence reading "1 wellbore(s)" tells the
    reader the application did not know how many it had."""
    n = 0
    f, ok = _to_float(count)
    if ok and not (math.isnan(f) or math.isinf(f)):
        n = int(math.floor(abs(f) + 0.5)) * (-1 if f < 0 else 1)
    word = one if n == 1 else (many if many is not None else f"{one}s")
    return f"{fmt_int(n)} {word}"
