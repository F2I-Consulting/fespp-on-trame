"""CSV exports — raw values under a header that says where they come from.

A file leaving the app must be reproducible: every cell is the shortest
decimal that round-trips the value (`repr`), never the rounded, converted
figure shown on screen; the unit is named once, in the column header; a
comment block (`# key: value`) states the property, representation,
realization, time step, date and app version the numbers were read at.
A value that could not be evaluated is `n/a`; one that does not apply is an
empty cell. The widgets that write their own file apply the same layout
(`widgets/_shared/csvexport.js`) over the header lines built here.
"""
import math
import re
from datetime import datetime

NA = "n/a"
_EXP_ZERO = re.compile(r"e([+-])0(\d)")
_SLUG = re.compile(r"[^A-Za-z0-9._-]+")


def _version():
    try:
        from fespp_on_trame import __version__
        return str(__version__ or "").strip() or "dev"
    except Exception:
        return "dev"


def escape(s):
    """A text cell: quoted when it holds a comma, a quote or a newline."""
    s = "" if s is None else str(s)
    if any(c in s for c in ',"\n\r'):
        return '"' + s.replace('"', '""') + '"'
    return s


def cell(v):
    """One cell, raw: `n/a` for None or NaN, `repr` for a float (exponent
    written without a leading zero), full digits for an int, `true` /
    `false` for a bool, escaped text otherwise."""
    if v is None:
        return NA
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if math.isnan(v):
            return NA
        if math.isinf(v):
            return "inf" if v > 0 else "-inf"
        return _EXP_ZERO.sub(r"e\1\2", repr(float(v)))
    try:
        import numpy as np
        if isinstance(v, np.integer):
            return str(int(v))
        if isinstance(v, np.floating):
            return cell(float(v))
    except Exception:
        pass
    return escape(v)


def column(name, uom="", power=1):
    """A column header naming its unit: `min (m3/m3)`,
    `variance ((m3/m3)^2)`, `cells` when there is none."""
    from fespp_on_trame.engine.utils import numfmt
    u = numfmt.unit_power(uom, power, ascii=True)
    return f"{name} ({u})" if u else str(name)


def header_lines(kind, fields):
    """The comment block: the app and the table kind, the date, one line
    per (key, value) — `fields` is a list of pairs or a dict; a None value
    is skipped — and the `n/a` legend last."""
    out = [f"# fespp-on-trame {_version()} - {kind}",
           f"# date: {datetime.now().strftime('%Y-%m-%d %H:%M')}"]
    items = fields.items() if isinstance(fields, dict) else (fields or [])
    for key, value in items:
        if value is None:
            continue
        text = " ".join(str(value).split())
        out.append(f"# {key}: {text}")
    out.append(f"# {NA} = not available")
    return out


def render(header, columns, rows):
    """The file text: the header lines as given, the column line, one line
    per row (each a list, or a dict read by column name) through `cell`;
    newline-terminated."""
    lines = list(header or [])
    lines.append(",".join(escape(c) for c in columns))
    for row in rows or []:
        if isinstance(row, dict):
            row = [row.get(c) for c in columns]
        lines.append(",".join(cell(v) for v in row))
    return "\n".join(lines) + "\n"


def slug(s):
    """A file-name-safe fragment: anything but letters, digits, `.`, `_`
    and `-` becomes `_`; at most 60 characters."""
    return _SLUG.sub("_", str(s or "")).strip("_")[:60]


def file_name(kind, *parts):
    """`<kind>_<part>_..._<YYYY-MM-DD>.csv` — empty parts are skipped."""
    tail = "".join("_" + slug(p) for p in parts if p and slug(p))
    return f"{kind}{tail}_{datetime.now().strftime('%Y-%m-%d')}.csv"


def payload(kind, fields, *parts):
    """`{"name", "header"}` for a widget that writes its own rows."""
    return {"name": file_name(kind, *parts), "header": header_lines(kind, fields)}


EMPTY_PAYLOAD = {"name": "", "header": []}
