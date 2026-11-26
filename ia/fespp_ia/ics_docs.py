"""The ICS International Chronostratigraphic Chart as a document for the RAG,
written once AT INSTALL TIME into ia/corpus/geologie/ics (git-ignored), from
the table the application already carries (fespp_on_trame/engine/ics_chart.py,
whose CHART_VERSION the document names). The service never reads the
application.

    python -m fespp_ia.ics_docs /ia/corpus/geologie/ics                       # in the app image
    python -m fespp_ia.ics_docs /ia/corpus/geologie/ics --chart /repo/fespp_on_trame/engine/ics_chart.py

One Markdown file, cut by the corpus builder on its headings: what the
chart is and is not (a well top "Hugin Fm" is lithostratigraphy, it is not
in it), how to read it, then one "### <French name> (<English name>)" per
unit with its rank, its parents, its base, its top and its duration in Ma,
in French then in English -- a question in either language lands on the
same chunk, titled by both names.

Why from the table: the chart ships as a poster, not as a data file; the
application transcribed it by hand and versions it, so the assistant reads
the very numbers the application uses to place a "Callovian Top" marker,
and follows them when the table is updated. The French names are those of
the ICS's French edition of the chart: a table for the irregular ones, the
rule -ian -> -ien for the other stages.

Licence: the chart is CC BY 4.0 (International Commission on Stratigraphy;
Cohen, K.M., Finney, S.C., Gibbard, P.L. & Fan, J.-X., The ICS International
Chronostratigraphic Chart, Episodes 36); the file names the ICS as its source.
"""
import argparse
import importlib.util
import os

CHART_URL = "https://stratigraphy.org/chart"
LICENSE = "CC BY 4.0"
FILE_NAME = "charte-chronostratigraphique.md"
TITLE = "Charte chronostratigraphique ICS (International Chronostratigraphic Chart)"

RANKS = {"eon": "éon", "era": "ère", "period": "période", "epoch": "époque", "stage": "étage"}
_FEMININE = {"ère", "période", "époque"}

# The names the rule -ian -> -ien does not give: the eons, eras, periods and
# epochs, and the stages whose French form takes an accent or another root.
FRENCH = {
    "Cenozoic": "Cénozoïque", "Mesozoic": "Mésozoïque", "Paleozoic": "Paléozoïque",
    "Precambrian": "Précambrien", "Proterozoic": "Protérozoïque", "Archean": "Archéen", "Hadean": "Hadéen",
    "Quaternary": "Quaternaire", "Neogene": "Néogène", "Paleogene": "Paléogène",
    "Cretaceous": "Crétacé", "Jurassic": "Jurassique", "Triassic": "Trias",
    "Carboniferous": "Carbonifère", "Devonian": "Dévonien",
    "Holocene": "Holocène", "Pleistocene": "Pléistocène", "Pliocene": "Pliocène", "Miocene": "Miocène",
    "Oligocene": "Oligocène", "Eocene": "Éocène", "Paleocene": "Paléocène",
    "Piacenzian": "Plaisancien", "Zanclean": "Zancléen", "Rupelian": "Rupélien",
    "Lutetian": "Lutétien", "Ypresian": "Yprésien", "Thanetian": "Thanétien", "Selandian": "Sélandien",
    "Cenomanian": "Cénomanien", "Barremian": "Barrémien", "Kimmeridgian": "Kimméridgien",
    "Aalenian": "Aalénien", "Sinemurian": "Sinémurien", "Rhaetian": "Rhétien",
    "Olenekian": "Olénekien", "Induan": "Indouen",
}
# A series qualifier goes after the noun in French: "Middle Jurassic" ->
# "Jurassique moyen". Lower/Upper name rock, Early/Late name time.
QUALIFIERS = {"lower": "inférieur", "early": "inférieur", "middle": "moyen",
              "upper": "supérieur", "late": "supérieur"}


def french_name(name):
    """The French name of a chart term: "Callovian" -> "Callovien",
    "Cretaceous" -> "Crétacé", "Middle Jurassic" -> "Jurassique moyen"."""
    first, _, rest = name.partition(" ")
    if rest and first.lower() in QUALIFIERS:
        return f"{french_name(rest)} {QUALIFIERS[first.lower()]}"
    if name in FRENCH:
        return FRENCH[name]
    if name.endswith("ian"):
        return name[:-3] + "ien"
    return name


def ma(value, french=False):
    """An age in Ma without trailing zeros (165.3, 251.902, 0.0117), with a
    decimal comma in French."""
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text.replace(".", ",") if french else text


def _vowel(fr):
    """Whether a French name takes the elided article (l', de l')."""
    return fr[0].lower() in "aeiouyhéè"


def _le(fr):
    return ("L'" if _vowel(fr) else "Le ") + fr


def _du(fr):
    return ("de l'" if _vowel(fr) else "du ") + fr


def _un(rank_fr):
    return ("une " if rank_fr in _FEMININE else "un ") + rank_fr


def unit_section(chart, name):
    """(heading, body) of one unit: its French and English names, its rank,
    its parents up to the era, its base, top and duration, the units it
    holds -- one paragraph in French, the same in English."""
    by_name = {u[0]: u for u in chart._UNITS}
    _, rank, _, parent = by_name[name]
    hit = chart.lookup(name)
    base, top = hit["base_ma"], hit["top_ma"]
    fr, rank_fr = french_name(name), RANKS[rank]
    chain = []
    while parent:
        chain.append(parent)
        parent = by_name[parent][3]
    # the table is youngest first; a unit's members read better oldest first
    members = [u[0] for u in chart._UNITS if u[3] == name][::-1]

    if chain:
        fr_where = ", ".join(f"{_du(french_name(p))} ({RANKS[by_name[p][1]]})" for p in chain)
        en_where = ", ".join(f"of the {p} ({by_name[p][1]})" for p in chain)
    else:
        fr_where, en_where = "de la charte ICS", "of the ICS chart"
    if top:
        fr_span = (f"Sa base est à {ma(base, True)} Ma, son sommet à {ma(top, True)} Ma"
                   f" (Ma : millions d'années avant le présent) ; il dure {ma(base - top, True)} Ma.")
        en_span = (f"Its base is at {ma(base)} Ma, its top at {ma(top)} Ma"
                   f" (Ma: million years before present); it lasts {ma(base - top)} Ma.")
    else:
        fr_span = (f"Sa base est à {ma(base, True)} Ma (millions d'années avant le présent),"
                   f" son sommet est le présent (0 Ma) ; il dure {ma(base, True)} Ma.")
        en_span = (f"Its base is at {ma(base)} Ma (million years before present),"
                   f" its top is the present (0 Ma); it lasts {ma(base)} Ma.")
    fr_text = f"{_le(fr)} ({name}) est {_un(rank_fr)} {fr_where}. {fr_span}"
    en_text = f"The {name} ({fr} in French) is {'an' if rank in ('eon', 'era', 'epoch') else 'a'} {rank} {en_where}. {en_span}"
    if members:
        member_rank = by_name[members[0]][1]
        member_fr = RANKS[member_rank]
        order = "de la plus ancienne à la plus récente" if member_fr in _FEMININE else "du plus ancien au plus récent"
        fr_text += f" Ses {member_fr}s, {order} : {', '.join(french_name(m) for m in members)}."
        en_text += f" Its {member_rank}s, oldest first: {', '.join(members)}."
    fr_text += f" Charte ICS {chart.CHART_VERSION}."
    en_text += f" ICS chart {chart.CHART_VERSION}."
    return f"### {fr} ({name})", f"{fr_text}\n\n{en_text}"


def document(chart):
    """The whole Markdown file: title, source line, what the chart is and
    is not, how to read it, then one section per unit in the chart's order
    (youngest first)."""
    n = len(chart._UNITS)
    tertiary = chart.lookup("Tertiary")["base_ma"]     # the alias resolves to the Paleogene base
    parts = [
        f"# {TITLE}",
        f"Source : {chart.CHART_SOURCE}, {CHART_URL}, version {chart.CHART_VERSION}"
        f" — licence {LICENSE} (International Commission on Stratigraphy)",
        "La charte chronostratigraphique internationale de la Commission internationale de stratigraphie"
        " (ICS) découpe le temps géologique en unités emboîtées — éons, ères, périodes, époques (séries),"
        " étages — bornées par des âges en millions d'années (Ma). Ce document donne les"
        f" {n} unités que l'application connaît (fespp_on_trame/engine/ics_chart.py, charte"
        f" {chart.CHART_VERSION}) : nom français et anglais, rang, unités parentes, base, sommet et durée.",
        "The ICS International Chronostratigraphic Chart, published by the International Commission on"
        " Stratigraphy, divides geological time into nested units — eons, eras, periods, epochs (series),"
        f" stages — bounded by ages in million years (Ma). This document lists the {n} units the"
        f" application knows (fespp_on_trame/engine/ics_chart.py, chart {chart.CHART_VERSION}): French"
        " and English name, rank, parents, base, top and duration.",

        "## Du temps, pas de la roche (time, not rock)",
        "La charte est de la chronostratigraphie : elle date. Les marqueurs d'un puits (well tops, well"
        " markers) sont de la lithostratigraphie : ils nomment des roches, des formations — « Hugin Fm » —"
        " qui ne figurent pas dans la charte, et c'est normal, ce n'est pas un manque. Seules les"
        " références chronostratigraphiques qu'un fichier RESQML porte — « Callovian Top », « Danian"
        " Base », une unité stratigraphique (StratigraphicUnitInterpretation) nommée par un étage — se"
        " rattachent à la charte, qui donne alors la base et le sommet de l'unité en Ma. Une formation se"
        " date en la rangeant dans un ou plusieurs étages, jamais en la cherchant dans la charte.",
        "The chart is chronostratigraphy: it dates. Well tops (well markers) are lithostratigraphy: they"
        " name rocks, formations — \"Hugin Fm\" — which are not in the chart, and that is correct, not a"
        " gap. Only the chronostratigraphic references a RESQML file carries — \"Callovian Top\", \"Danian"
        " Base\", a stratigraphic unit (StratigraphicUnitInterpretation) named after a stage — join to the"
        " chart, which then gives the unit's base and top in Ma. A formation is dated by assigning it to"
        " one or more stages, never by looking it up in the chart.",

        "## Lire la charte (reading the chart)",
        "Un âge se compte en Ma, millions d'années avant le présent. La charte n'imprime que la base de"
        " chaque unité : son sommet est la base de l'unité qui la suit, et le sommet de la plus récente"
        " est le présent (0 Ma). Les qualificatifs inférieur, moyen, supérieur (Lower, Middle, Upper pour"
        " les roches ; Early, Middle, Late pour le temps) désignent les séries d'une période et se placent"
        f" après le nom en français : « Middle Jurassic » se dit « {french_name('Middle Jurassic')} »,"
        f" « Upper Cretaceous » « {french_name('Upper Cretaceous')} ». Le « Tertiaire » (Tertiary),"
        " abandonné par l'ICS mais courant dans les données de l'industrie (Volve), couvre le Paléogène"
        f" et le Néogène ; sa base est celle du Paléogène, {ma(tertiary, True)} Ma."
        " Cette table couvre le Cénozoïque et le Mésozoïque au niveau des étages, le Paléozoïque au niveau"
        f" des périodes et le Précambrien en un seul bloc ; les âges sont ceux de la version {chart.CHART_VERSION}"
        " de la charte, tels que l'application les a transcrits.",
        "An age is counted in Ma, million years before present. The chart prints only the base of each"
        " unit: its top is the base of the unit that follows, and the top of the youngest one is the"
        " present (0 Ma). The qualifiers Lower, Middle, Upper (for rock; Early, Middle, Late for time)"
        " name the series of a period and go after the noun in French: \"Middle Jurassic\" is"
        f" \"{french_name('Middle Jurassic')}\", \"Upper Cretaceous\" is \"{french_name('Upper Cretaceous')}\"."
        " \"Tertiary\", abandoned by the ICS but common in industry data (Volve), spans the Paleogene and"
        f" the Neogene; its base is the Paleogene base, {ma(tertiary)} Ma. This table covers the Cenozoic and"
        " the Mesozoic at stage level, the Paleozoic at period level and the Precambrian as one block;"
        f" the ages are those of chart version {chart.CHART_VERSION}, as the application transcribed them.",
    ]
    for name, *_ in chart._UNITS:
        parts += unit_section(chart, name)
    return "\n\n".join(parts) + "\n"


def default_chart_path():
    """fespp_on_trame/engine/ics_chart.py of the repository this module sits in."""
    ia = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(os.path.dirname(ia), "fespp_on_trame", "engine", "ics_chart.py")


def load_chart(path=None):
    """The application's table: the package when it is importable (the app
    image), else the module file alone -- it imports nothing, so it loads
    in the fespp_ia image too, where the application's dependencies are
    absent."""
    if path is None:
        try:
            from fespp_on_trame.engine import ics_chart
            return ics_chart
        except ImportError:
            path = default_chart_path()
    spec = importlib.util.spec_from_file_location("ics_chart", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(argv=None):
    ap = argparse.ArgumentParser(description="Write the ICS chart, from the application's table, as a document for the RAG.")
    ap.add_argument("out", help="ia/corpus/geologie/ics")
    ap.add_argument("--chart", help="the ics_chart.py to read when fespp_on_trame is not importable"
                                    " (default: the one of this repository)")
    a = ap.parse_args(argv)
    chart = load_chart(a.chart)
    text = document(chart)
    os.makedirs(a.out, exist_ok=True)
    path = os.path.join(a.out, FILE_NAME)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"[ics] {len(chart._UNITS)} units, {len(text)} characters, chart {chart.CHART_VERSION}"
          f" from {chart.__file__} -> {path}", flush=True)


if __name__ == "__main__":
    main()
