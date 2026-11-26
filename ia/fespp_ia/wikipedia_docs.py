"""Wikipedia articles, French and English (CC BY-SA 4.0), on reservoir
geology, sedimentology, stratigraphy, structural geology, wells and logs,
and reservoir modelling -- a CURATED list, not a crawl -- fetched once AT
INSTALL TIME into ia/corpus/geologie/wikipedia (git-ignored), for the RAG
to read. The service never downloads anything.

    python -m fespp_ia.wikipedia_docs --out /ia/corpus/geologie/wikipedia --cache /ia/corpus_cache/wikipedia
    python -m fespp_ia.wikipedia_docs --check --cache ...   -> only verify the titles against the API

Why: the glossary and the AAPG Wiki explain in English, from the petroleum
side; a question asked in French (on diagenesis, say) is far, by vector,
from both. The French Wikipedia gives the French wording of each notion
and the English twin of every page (its "en" langlink) gives the English
one, so the same notion is in the corpus in both languages.

For each French title of ARTICLES: the French page and its English twin,
or the English title given in the list when the French Wikipedia has no
page for the notion. The titles are checked against the API first (a
missing page or a disambiguation page is reported, never written) and
redirects are followed. One article = one Markdown file
<out>/<lang>/<name>.md, in the format of wiki_docs (the AAPG fetcher):
"# Wikipédia › <title>", the source URL and the licence, then the article
cut on its own headings. Left out: infoboxes, hatnotes and message boxes,
figures, navboxes, portal bars, the table of contents, footnote marks, and
the closing sections of notes, references and links, in either language
(WikipediaText.stop_sections). A formula is kept as its TeX source.
Polite: wiki_docs.WORKERS workers, wiki_docs.DELAY seconds between two
requests of a worker, the raw pages cached (a re-run fetches nothing).
"""
import argparse
import json
import os
import re
import time
import unicodedata
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

from fespp_ia.wiki_docs import DELAY, WORKERS, ArticleText, api_get, article_markdown, safe_name

API = {"fr": "https://fr.wikipedia.org/w/api.php", "en": "https://en.wikipedia.org/w/api.php"}
LABEL = {"fr": "Wikipédia", "en": "Wikipedia"}
LICENSE = "CC BY-SA 4.0"
# the category of the disambiguation pages: a second signal beside the
# "disambiguation" page property
DISAMBIGUATION_CATEGORY = {"fr": "Catégorie:Homonymie", "en": "Category:Disambiguation pages"}
QUERY_BATCH = 50      # titles per action=query call, the API's limit

# (French title, English title): the English page is the French page's
# "en" langlink, unless a title is given here -- for a notion the French
# Wikipedia has no page for, or whose twin is off the mark. A French title
# the French Wikipedia lacks may stay when its English twin is given: the
# English page is still fetched, the French one reported missing (--check
# lists them).
ARTICLES = [
    # reservoir
    ("Roche réservoir", "Petroleum reservoir"),
    ("Roche-mère (géologie)", "Source rock"),
    ("Roche couverture", "Cap rock"),
    ("Piège (géologie)", "Petroleum trap"),
    ("Contact huile-eau", "Water contact"),
    ("Aquifère", None),
    ("Pression capillaire", "Capillary pressure"),
    ("Mouillabilité", None),
    ("Saturation en eau", "Water saturation"),
    ("Porosité", None),
    ("Perméabilité (fluide)", None),
    ("Loi de Darcy", None),
    ("Karst", None),
    ("Fracture (géologie)", "Fracture (geology)"),
    ("Diaclase", None),
    ("Système pétrolier", None),
    ("Géologie du pétrole", "Petroleum geology"),
    ("Pétrophysique", "Petrophysics"),
    ("Réserves pétrolières", "Oil reserves"),
    ("Volumes en place", "Oil in place"),
    ("Récupération assistée du pétrole", None),
    # rocks and sedimentology
    ("Grès (géologie)", None),
    ("Argile", None),
    ("Argilite", None),
    ("Calcaire", None),
    ("Dolomie", None),
    ("Roche carbonatée", None),
    ("Marne (géologie)", None),
    ("Évaporite", None),
    ("Conglomérat (géologie)", None),
    ("Sable", None),
    ("Limon (roche)", "Silt"),
    ("Craie", None),
    ("Roche sédimentaire", None),
    ("Roche détritique", None),
    ("Faciès (géologie)", None),
    ("Lithologie", None),
    ("Diagenèse", None),
    ("Cimentation (géologie)", None),
    ("Compaction (géologie)", "Compaction (geology)"),
    ("Sédimentologie", None),
    ("Sédimentation", None),
    ("Granulométrie", None),
    ("Chenal", "Channel (geography)"),
    ("Delta (hydrologie)", None),
    ("Turbidite", None),
    ("Courant de turbidité", None),
    ("Séquence de Bouma", None),
    ("Méandre", None),
    ("Plaine inondable", None),
    ("Milieu de sédimentation", "Depositional environment"),
    ("Cône alluvial", None),
    ("Dune", None),
    ("Récif", None),
    ("Récif corallien", None),
    ("Plate-forme carbonatée", None),
    ("Érosion éolienne", "Aeolian processes"),
    ("Alluvion", None),
    ("Sédiment", None),
    ("Estuaire", None),
    ("Lagune", None),
    ("Bassin sédimentaire", None),
    ("Subsidence (géologie)", "Subsidence"),
    ("Plateau continental", None),
    ("Talus continental", None),
    ("Plaine abyssale", None),
    ("Cône sous-marin", "Submarine fan"),
    ("Stratification croisée", "Cross-bedding"),
    ("Tempestite", None),
    # stratigraphy
    ("Stratigraphie", None),
    ("Stratigraphie séquentielle", "Sequence stratigraphy"),
    ("Lithostratigraphie", None),
    ("Chronostratigraphie", None),
    ("Biostratigraphie", None),
    ("Discordance (géologie)", None),
    ("Étage stratigraphique", "Stage (stratigraphy)"),
    ("Formation (géologie)", "Formation (geology)"),
    ("Horizon (géologie)", "Horizon (geology)"),
    ("Séquence sédimentaire", "Sequence (geology)"),
    ("Échelle des temps géologiques", None),
    ("Fossile stratigraphique", None),
    ("Principe de superposition", None),
    ("Strate (géologie)", "Stratum"),
    ("Transgression marine", None),
    ("Régression marine", None),
    ("Eustatisme", None),
    ("Cyclostratigraphie", None),
    ("Paléozoïque", None),
    ("Mésozoïque", None),
    ("Cénozoïque", None),
    ("Dévonien", None),
    ("Carbonifère", None),
    ("Permien", None),
    ("Trias", None),
    ("Jurassique", None),
    ("Crétacé", None),
    ("Paléogène", None),
    ("Néogène", None),
    ("Quaternaire", None),
    ("Bajocien", None),
    ("Bathonien", None),
    ("Callovien", None),
    ("Oxfordien", None),
    ("Kimméridgien", None),
    ("Aptien", None),
    ("Cénomanien", None),
    ("Maastrichtien", None),
    ("Danien", None),
    # structure
    ("Faille", None),
    ("Faille normale", None),
    ("Faille inverse", None),
    ("Décrochement", None),
    ("Pli (géologie)", None),
    ("Anticlinal", None),
    ("Synclinal", None),
    ("Dôme de sel", None),
    ("Diapir", None),
    ("Tectonique salifère", "Salt tectonics"),
    ("Chevauchement", None),
    ("Graben", None),
    ("Horst", "Horst (geology)"),
    ("Rift", None),
    ("Tectonique", None),
    ("Pendage", None),
    ("Rejet de faille", None),
    # wells and logs
    ("Forage", None),
    ("Puits de pétrole", None),
    ("Diagraphie", None),
    ("Diagraphie gamma", "Gamma ray logging"),
    ("Diagraphie de résistivité", "Resistivity logging"),
    ("Diagraphie sonique", "Sonic logging"),
    ("Diagraphie de densité", "Density logging"),
    ("Diagraphie neutron", "Formation evaluation neutron porosity"),
    ("Carotte (géologie)", None),
    ("Carottage", None),
    ("Complétion (forage)", "Completion (oil and gas wells)"),
    ("Forage dirigé", None),
    ("Pression interstitielle", "Pore water pressure"),
    ("Tubage", "Casing (borehole)"),
    ("Boue de forage", None),
    ("Tête de puits", "Wellhead"),
    ("Mesure pendant le forage", "Measurement while drilling"),
    # modelling
    ("Modélisation géologique", "Geologic modelling"),
    ("Géostatistique", None),
    ("Krigeage", None),
    ("Variogramme", None),
    ("Simulation de réservoir", "Reservoir simulation"),
    ("Sismique réflexion", "Reflection seismology"),
    ("Ingénierie des réservoirs", "Reservoir engineering"),
    ("Modélisation de bassin", "Basin modelling"),
    ("Injection d'eau (production de pétrole)", None),
    ("Analyse des courbes de déclin", "Decline curve analysis"),
    ("Géophysique", None),
]

_TEX = re.compile(r"^\{\\displaystyle\s*(.*)\}$", re.S)


class WikipediaText(ArticleText):
    """ArticleText with Wikipedia's chrome left out -- infoboxes, hatnotes
    (the homonym and "Main article:" notes), message boxes,
    figures and their captions, navboxes and portal bars -- the French and
    English closing sections stopping the article, and a formula kept as
    its TeX source: the alt text of its fallback image, since the MathML
    beside it says nothing once its tags are stripped."""
    skip_tags = ArticleText.skip_tags | {"figure"}
    skip_classes = ArticleText.skip_classes | {
        "infobox", "infobox_v2", "infobox_v3", "hatnote", "navigation-not-searchable", "bandeau-container",
        "bandeau-article", "bandeau-section", "bandeau-portail", "homonymie", "metadata", "ambox", "sistersitebox",
        "side-box", "shortdescription", "portalbox", "vertical-navbox", "NavFrame", "boilerplate", "toccolours",
        "thumberror"}
    stop_sections = re.compile(
        r"^(notes?( et références)?|références?|voir aussi|annexes?|bibliographie|sources?|liens? externes?|"
        r"articles? connexes?|notes and references|references?|see also|external links?|further reading|"
        r"footnotes|citations|bibliography|related articles?)$", re.I)

    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag, attrs)
        if tag == "img" and not self._skipping():
            a = dict(attrs)
            if "mwe-math-fallback-image" in (a.get("class") or ""):
                self._cur.append(_TEX.sub(r"\1", (a.get("alt") or "").strip()))


def page_name(title):
    """The file name of a page: its title with the accents folded, then
    safe_name ("Stratigraphie séquentielle" -> "Stratigraphie_sequentielle")."""
    folded = "".join(c for c in unicodedata.normalize("NFD", title) if unicodedata.category(c) != "Mn")
    return safe_name(folded)


def page_url(lang, title):
    return f"https://{lang}.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"), safe="/():,")


def is_disambiguation(page):
    """A page of the API (formatversion 2) that lists homonyms: the
    "disambiguation" page property, or its category."""
    return "disambiguation" in (page.get("pageprops") or {}) or any(
        re.search(r"Homonymie|Disambiguation", c.get("title", "")) for c in page.get("categories") or [])


def resolve(query, requested):
    """{requested title: {"title": the page's title after the API's
    normalisation (the first letter upper-cased) and its redirects, or
    None when the page does not exist; "disambiguation": bool; "en": its
    English twin (the "en" langlink) or None}} from one action=query
    answer."""
    step = {}
    for key in ("normalized", "redirects"):
        for m in query.get(key) or []:
            step[m["from"]] = m["to"]
    pages = {p["title"]: p for p in query.get("pages") or []}
    out = {}
    for t in requested:
        final, seen = t, set()
        while final in step and final not in seen:
            seen.add(final)
            final = step[final]
        p = pages.get(final)
        if p is None or p.get("missing") or p.get("invalid"):
            out[t] = {"title": None, "disambiguation": False, "en": None}
            continue
        en = next((ll["title"] for ll in p.get("langlinks") or [] if ll.get("lang") == "en"), None)
        out[t] = {"title": p["title"], "disambiguation": is_disambiguation(p), "en": en}
    return out


def check_titles(lang, titles):
    """resolve() of every title, QUERY_BATCH titles a call."""
    out = {}
    for k in range(0, len(titles), QUERY_BATCH):
        batch = titles[k:k + QUERY_BATCH]
        # the langlink and category limits count for the whole batch (10 by
        # default): without "max", most pages of a batch would come back
        # without their twin
        d = api_get(API[lang], {"action": "query", "titles": "|".join(batch), "redirects": 1,
                                "prop": "pageprops|langlinks|categories", "ppprop": "disambiguation",
                                "lllang": "en", "lllimit": "max", "clcategories": DISAMBIGUATION_CATEGORY[lang],
                                "cllimit": "max", "formatversion": 2})
        out.update(resolve(d.get("query") or {}, batch))
        time.sleep(DELAY)
    return out


def checked(lang, titles, cache):
    """check_titles, remembered in <cache>/<lang>/_check.json: a re-run
    asks the API only about the titles it has not seen (delete the file to
    ask again)."""
    path = os.path.join(cache, lang, "_check.json")
    known = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            known = json.load(f)
    new = [t for t in titles if t not in known]
    if new:
        known.update(check_titles(lang, new))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(known, f, ensure_ascii=False, indent=1)
    return {t: known[t] for t in titles}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Fetch the curated Wikipedia articles (FR + EN) for the RAG.")
    ap.add_argument("--out", help="ia/corpus/geologie/wikipedia (not needed with --check)")
    ap.add_argument("--cache", required=True, help="where the raw pages are kept (re-runs read them)")
    ap.add_argument("--limit", type=int, default=0, help="only the first N titles of the list (a quick look)")
    ap.add_argument("--check", action="store_true", help="verify the titles against the API, write no article")
    a = ap.parse_args(argv)
    if not a.check and not a.out:
        ap.error("--out is required (unless --check)")
    articles = ARTICLES[:a.limit] if a.limit else ARTICLES

    # 1. the titles, checked: the French pages, then their English twins
    notes = {"missing": [], "disambiguation": [], "redirected": [], "no English twin": []}
    pages = {"fr": [], "en": []}
    fr = checked("fr", [t for t, _ in articles], a.cache)
    en_wanted = []
    for t, en_title in articles:
        r = fr[t]
        if r["title"] is None:
            notes["missing"].append(f"fr:{t}")
        elif r["disambiguation"]:
            notes["disambiguation"].append(f"fr:{t}")
        else:
            if r["title"] != t:
                notes["redirected"].append(f"fr:{t} -> {r['title']}")
            pages["fr"].append(r["title"])
        twin = en_title or r["en"]
        if twin:
            en_wanted.append(twin)
        else:
            notes["no English twin"].append(f"fr:{t}")
    en = checked("en", list(dict.fromkeys(en_wanted)), a.cache)
    for t in en_wanted:
        r = en[t]
        if r["title"] is None:
            notes["missing"].append(f"en:{t}")
        elif r["disambiguation"]:
            notes["disambiguation"].append(f"en:{t}")
        else:
            if r["title"] != t:
                notes["redirected"].append(f"en:{t} -> {r['title']}")
            pages["en"].append(r["title"])
    for lang in pages:
        pages[lang] = list(dict.fromkeys(pages[lang]))
    for key, items in notes.items():
        if items:
            print(f"[wikipedia] {key} ({len(items)}): " + "; ".join(items), flush=True)
    print(f"[wikipedia] {len(pages['fr'])} French and {len(pages['en'])} English pages", flush=True)
    if a.check:
        return

    # 2. the pages, WORKERS at a time, each worker pausing DELAY between two
    # of its requests; the raw answer is cached (a re-run fetches nothing)
    def cpath(lang, title):
        return os.path.join(a.cache, lang, page_name(title) + ".json")

    def get(job):
        lang, title = job
        if os.path.exists(cpath(lang, title)):
            return
        d = api_get(API[lang], {"action": "parse", "page": title, "prop": "text", "redirects": 1, "disabletoc": 1,
                                "disableeditsection": 1, "formatversion": 2})
        tmp = cpath(lang, title) + ".part"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(tmp, cpath(lang, title))
        time.sleep(DELAY)

    jobs = [(lang, t) for lang in ("fr", "en") for t in pages[lang]]
    for lang in pages:
        os.makedirs(os.path.join(a.cache, lang), exist_ok=True)
        os.makedirs(os.path.join(a.out, lang), exist_ok=True)
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for n, _ in enumerate(pool.map(get, jobs), 1):
            if n % 50 == 0:
                print(f"[wikipedia] {n}/{len(jobs)} pages fetched", flush=True)

    # 3. one Markdown file per page
    written, chars, short = {"fr": 0, "en": 0}, 0, []
    for lang, title in jobs:
        with open(cpath(lang, title), encoding="utf-8") as f:
            d = json.load(f)
        md = article_markdown(title, (d.get("parse") or {}).get("text", ""), LABEL[lang], page_url(lang, title),
                              LICENSE, parser=WikipediaText)
        if not md:
            short.append(f"{lang}:{title}")
            continue
        with open(os.path.join(a.out, lang, page_name(title) + ".md"), "w", encoding="utf-8") as f:
            f.write(md)
        written[lang] += 1
        chars += len(md)
    print(f"[wikipedia] fr {written['fr']} + en {written['en']} articles written, {chars} characters"
          + (f", too short: {short}" if short else "") + f" -> {a.out}", flush=True)


if __name__ == "__main__":
    main()
