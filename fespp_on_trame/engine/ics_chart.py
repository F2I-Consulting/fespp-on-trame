"""The ICS International Chronostratigraphic Chart, as a lookup table.

SOURCE: the International Commission on Stratigraphy's own machine-readable
chart (github.com/i-c-stratigraphy/chart, chart.ttl, CC-BY 4.0), turned into
`ics_chart_data` by doc/private/probes/make_ics_data.py. It used to be a
table transcribed by hand from the poster, which missed the Quaternary
stages and the epochs of the Mesozoic: the reference column it fed showed
holes where the chart has none (the PO, 2026-10-15). Every unit of every
rank now comes with the chart's own beginning, end and colour.

WHAT IT IS FOR: a REFERENCE scale drawn beside a rank the FILE dates
(engine/stratigraphy). It never gives an age to a unit of the file, nor
classifies one by its name: that would be the chart's word, not the file's.

WHAT IT IS NOT: this is chronostratigraphy (time). A well's tops are
lithostratigraphy (rock): "Hugin Fm" never appears here, and that is
correct, not a gap.
"""
from fespp_on_trame.engine.ics_chart_data import CHART_SOURCE, CHART_VERSION, UNITS

# (name, rank, top_ma, base_ma, parent, colour), youngest first
_BY_NAME = {u[0].lower(): u for u in UNITS}


def _normalise(title):
    """A title as the chart is looked up: lower case, underscores and
    punctuation around the words dropped, and a TRAILING boundary role taken
    off ("Callovian Top" is the top of the Callovian). Nothing else: a
    qualifier stays ("Jurassic Middle" is not the Jurassic), and a leading
    role too ("Base Cretaceous" is a surface, not the period)."""
    words = [w.strip(".,;:()").lower() for w in (title or "").replace("_", " ").split()]
    words = [w for w in words if w]
    if len(words) > 1 and words[-1] in ("top", "base"):
        words = words[:-1]
    return " ".join(words)


def _as_dict(unit):
    name, rank, top, base, parent, colour = unit
    return {"name": name, "rank": rank, "top_ma": top, "base_ma": base,
            "parent": parent, "color": colour, "chart": CHART_VERSION}


def lookup(title):
    """The chart unit a title names EXACTLY, or None (no approximation:
    PO, 2026-10-05). Kept for callers that ask the chart about a name; the
    stratigraphic column no longer does."""
    key = _normalise(title)
    unit = _BY_NAME.get(key) if key else None
    return _as_dict(unit) if unit is not None else None


def units_between(younger_ma, older_ma, ranks=("period", "epoch", "stage")):
    """[{name, rank, top_ma, base_ma, parent, color, chart}] — the chart's
    units of `ranks` that overlap [younger_ma, older_ma], youngest first:
    the reference scale drawn beside a rank the FILE dates, never a source
    of ages for its units."""
    out = []
    for unit in UNITS:
        name, rank, top, base, _parent, _colour = unit
        if rank not in ranks or base <= younger_ma or top >= older_ma:
            continue
        out.append(_as_dict(unit))
    out.sort(key=lambda u: (u["top_ma"], u["base_ma"]))
    return out


__all__ = ["CHART_SOURCE", "CHART_VERSION", "lookup", "units_between"]
