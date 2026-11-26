"""The Wikipedia fetcher, on fixtures (no network): the title check (the
English twin, redirects, disambiguation pages, missing pages), the file
names, the header line, what the parser keeps and drops, and a whole run
with the API faked."""
import json

from fespp_ia import wikipedia_docs
from fespp_ia.wiki_docs import article_markdown
from fespp_ia.wikipedia_docs import ARTICLES, WikipediaText, is_disambiguation, page_name, page_url, resolve

QUERY_FR = {"batchcomplete": True, "query": {
    "normalized": [{"fromencoded": False, "from": "roche réservoir", "to": "Roche réservoir"}],
    "redirects": [{"from": "Roche réservoir", "to": "Roche-réservoir"}],
    "pages": [
        {"pageid": 1, "ns": 0, "title": "Roche-réservoir",
         "langlinks": [{"lang": "en", "title": "Petroleum reservoir"}]},
        {"pageid": 2, "ns": 0, "title": "Diagenèse", "langlinks": [{"lang": "en", "title": "Diagenesis"}]},
        {"pageid": 3, "ns": 0, "title": "Faciès", "pageprops": {"disambiguation": ""}},
        {"pageid": 4, "ns": 0, "title": "Horizon", "categories": [{"ns": 14, "title": "Catégorie:Homonymie"}]},
        {"ns": 0, "title": "Net to gross", "missing": True},
        {"pageid": 5, "ns": 0, "title": "Karst"}]}}
QUERY_EN = {"batchcomplete": True, "query": {"pages": [
    {"pageid": 10, "ns": 0, "title": "Diagenesis"},
    {"pageid": 11, "ns": 0, "title": "Petroleum reservoir"},
    {"ns": 0, "title": "Net pay", "missing": True}]}}

FR_HTML = r"""<div class="mw-parser-output"><style data-mw-deduplicate="TemplateStyles:r1">.x{}</style>
<div class="bandeau-container homonymie"><div class="bandeau-cell">Pour les articles homonymes, voir <a href="/wiki/Diagen%C3%A8se_(homonymie)">Diagenèse (homonymie)</a>.</div></div>
<div class="infobox_v3"><div class="entete">Diagenèse</div><table><tr><th>Type</th><td>Processus</td></tr></table></div>
<p>La <b>diagenèse</b> est l'ensemble des processus physico-chimiques et biochimiques par lesquels un sédiment est transformé en roche sédimentaire<sup class="reference" id="cite_ref-1"><a href="#cite_note-1">1</a></sup>.</p>
<figure class="mw-default-size" typeof="mw:File/Thumb"><a href="/wiki/Fichier:x.jpg"><img alt="" src="x.jpg"></a><figcaption>Grès cimenté vu au microscope.</figcaption></figure>
<div class="mw-heading mw-heading2"><h2 id="Processus">Processus</h2><span class="mw-editsection">[modifier]</span></div>
<div class="bandeau-container bandeau-section metadata bandeau-niveau-detail">Article détaillé : Compaction.</div>
<p>La compaction réduit la porosité avec la profondeur selon <span class="mwe-math-element"><span class="mwe-math-mathml-inline mwe-math-mathml-a11y" style="display: none;"><math><semantics><mrow><mi>φ</mi></mrow><annotation encoding="application/x-tex">{\displaystyle \phi =\phi _{0}e^{-cz}}</annotation></semantics></math></span><img src="m.svg" class="mwe-math-fallback-image-inline mw-invert" alt="{\displaystyle \phi =\phi _{0}e^{-cz}}"></span> (loi d'Athy).</p>
<ul><li>cimentation</li><li>dissolution</li></ul>
<table class="wikitable"><tbody><tr><th>Stade</th><th>Profondeur</th></tr><tr><td>Éogenèse</td><td>0 à 1 km</td></tr></tbody></table>
<div class="mw-heading mw-heading2"><h2 id="Notes">Notes et références</h2></div>
<div class="mw-references-wrap"><ol class="references"><li id="cite_note-1">Référence 1 : un livre.</li></ol></div>
<div class="mw-heading mw-heading2"><h2 id="Voir_aussi">Voir aussi</h2></div>
<ul><li><a href="/wiki/Compaction">Compaction (géologie)</a></li></ul>
<div class="navbox"><table><tr><td>Palette Géologie</td></tr></table></div>
<div class="bandeau-portail noprint">Portail de la géologie</div>
</div>"""

EN_HTML = """<div class="mw-parser-output"><div class="shortdescription nomobile noexcerpt noprint">Change of sediments</div>
<div role="note" class="hatnote navigation-not-searchable">"Diagenetic" redirects here. For the album, see Diagenetic (album).</div>
<table class="infobox"><tbody><tr><th>Part of</th><td>Sedimentology</td></tr></tbody></table>
<table class="box-More_citations_needed plainlinks metadata ambox"><tbody><tr><td>This article needs additional citations.</td></tr></tbody></table>
<p><b>Diagenesis</b> is the process of physical and chemical changes in deposited sediment during its conversion to sedimentary rock, at temperatures and pressures less than those required for metamorphism.</p>
<div class="mw-heading mw-heading2"><h2 id="Role">Role in petroleum geology</h2></div>
<p>Diagenetic cementation and dissolution control the porosity of a reservoir rock and, with it, its permeability.</p>
<div class="mw-heading mw-heading2"><h2 id="See_also">See also</h2></div>
<ul><li>Catagenesis (geology)</li></ul>
<div class="mw-heading mw-heading2"><h2 id="References">References</h2></div>
<ol class="references"><li>A reference.</li></ol>
</div>"""


def test_resolve_follows_normalisation_and_redirects_and_reads_the_twin():
    r = resolve(QUERY_FR["query"], ["roche réservoir", "Diagenèse", "Karst"])
    assert r["roche réservoir"] == {"title": "Roche-réservoir", "disambiguation": False, "en": "Petroleum reservoir"}
    assert r["Diagenèse"] == {"title": "Diagenèse", "disambiguation": False, "en": "Diagenesis"}
    assert r["Karst"] == {"title": "Karst", "disambiguation": False, "en": None}


def test_resolve_flags_a_missing_page_and_both_kinds_of_disambiguation():
    r = resolve(QUERY_FR["query"], ["Net to gross", "Faciès", "Horizon"])
    assert r["Net to gross"]["title"] is None
    assert r["Faciès"]["disambiguation"]          # flagged by the page property
    assert r["Horizon"]["disambiguation"]         # flagged by the category
    assert not is_disambiguation({"title": "Karst"})


def test_file_names_fold_the_accents_and_urls_keep_the_title_readable():
    assert page_name("Diagenèse") == "Diagenese"
    assert page_name("Stratigraphie séquentielle") == "Stratigraphie_sequentielle"
    assert page_name("Faille (géologie)") == "Faille_geologie"
    assert page_name("Oil–water contact") == "Oil_water_contact"
    assert page_url("fr", "Faille (géologie)") == "https://fr.wikipedia.org/wiki/Faille_(g%C3%A9ologie)"
    assert page_url("en", "Petroleum reservoir") == "https://en.wikipedia.org/wiki/Petroleum_reservoir"


def test_a_french_article_has_the_header_line_and_keeps_only_its_text():
    md = article_markdown("Diagenèse", FR_HTML, "Wikipédia", page_url("fr", "Diagenèse"), "CC BY-SA 4.0",
                          parser=WikipediaText)
    assert md.startswith("# Wikipédia › Diagenèse\n\nSource : Wikipédia, https://fr.wikipedia.org/wiki/Diagen%C3%A8se"
                         " — licence CC BY-SA 4.0 (auteurs : historique de la page)\n\n")
    assert "La diagenèse est l'ensemble des processus" in md
    assert "roche sédimentaire." in md and "sédimentaire1" not in md    # the footnote mark is dropped
    assert "## Processus" in md
    assert r"\phi =\phi _{0}e^{-cz} (loi d'Athy)" in md and "displaystyle" not in md
    assert "- cimentation" in md
    assert "Éogenèse | 0 à 1 km" in md
    for noise in ("Pour les articles homonymes", "Type | Processus", "Grès cimenté", "[modifier]", "Article détaillé",
                  "Référence 1", "Compaction (géologie)", "Palette Géologie", "Portail de la géologie", ".x{}"):
        assert noise not in md


def test_an_english_article_stops_at_see_also_and_drops_its_boxes():
    md = article_markdown("Diagenesis", EN_HTML, "Wikipedia", page_url("en", "Diagenesis"), "CC BY-SA 4.0",
                          parser=WikipediaText)
    assert md.startswith("# Wikipedia › Diagenesis\n\nSource : Wikipedia, https://en.wikipedia.org/wiki/Diagenesis"
                         " — licence CC BY-SA 4.0 (auteurs : historique de la page)\n\n")
    assert "Diagenesis is the process of physical and chemical changes" in md
    assert "## Role in petroleum geology" in md
    for noise in ("Change of sediments", "redirects here", "Part of | Sedimentology", "additional citations",
                  "Catagenesis", "A reference."):
        assert noise not in md


def test_the_curated_list_holds_one_to_two_hundred_distinct_french_titles():
    """The list is curated, not crawled: a bounded set of distinct French
    titles, each with an optional English title to use instead of the
    page's own interlanguage link."""
    fr = [t for t, _ in ARTICLES]
    assert 90 <= len(fr) <= 200
    assert len(set(fr)) == len(fr)
    assert all(isinstance(en, str) or en is None for _, en in ARTICLES)


def test_a_whole_run_writes_both_languages_reports_and_then_reads_its_cache(tmp_path, monkeypatch, capsys):
    calls = []

    def fake_api(api, params, retries=3):
        calls.append(params["action"])
        if params["action"] == "query":
            return QUERY_FR if api == wikipedia_docs.API["fr"] else QUERY_EN
        return {"parse": {"title": params["page"], "text": FR_HTML if api == wikipedia_docs.API["fr"] else EN_HTML}}

    monkeypatch.setattr(wikipedia_docs, "api_get", fake_api)
    monkeypatch.setattr(wikipedia_docs, "DELAY", 0)
    monkeypatch.setattr(wikipedia_docs, "ARTICLES", [("Diagenèse", None), ("roche réservoir", None), ("Faciès", None),
                                                     ("Net to gross", "Net pay"), ("Horizon", None), ("Karst", None)])
    out, cache = tmp_path / "out", tmp_path / "cache"
    wikipedia_docs.main(["--out", str(out), "--cache", str(cache)])
    assert sorted(p.name for p in (out / "fr").iterdir()) == ["Diagenese.md", "Karst.md", "Roche-reservoir.md"]
    assert sorted(p.name for p in (out / "en").iterdir()) == ["Diagenesis.md", "Petroleum_reservoir.md"]
    assert (out / "fr" / "Roche-reservoir.md").read_text(encoding="utf-8").startswith(
        "# Wikipédia › Roche-réservoir\n\nSource : Wikipédia, https://fr.wikipedia.org/wiki/Roche-r%C3%A9servoir — licence")
    said = capsys.readouterr().out
    assert "missing (2): fr:Net to gross; en:Net pay" in said
    assert "disambiguation (2): fr:Faciès; fr:Horizon" in said
    assert "redirected (1): fr:roche réservoir -> Roche-réservoir" in said
    assert "no English twin (3): fr:Faciès; fr:Horizon; fr:Karst" in said
    assert "fr 3 + en 2 articles written" in said
    assert calls.count("query") == 2 and calls.count("parse") == 5
    checked = json.load(open(cache / "fr" / "_check.json", encoding="utf-8"))
    assert checked["roche réservoir"]["title"] == "Roche-réservoir"

    calls.clear()
    wikipedia_docs.main(["--out", str(out), "--cache", str(cache)])
    assert calls == []          # the check and the pages come from the cache


def test_check_only_verifies_and_writes_no_article(tmp_path, monkeypatch):
    monkeypatch.setattr(wikipedia_docs, "api_get", lambda api, params, retries=3: QUERY_FR)
    monkeypatch.setattr(wikipedia_docs, "DELAY", 0)
    monkeypatch.setattr(wikipedia_docs, "ARTICLES", [("Karst", None)])
    wikipedia_docs.main(["--check", "--cache", str(tmp_path / "cache")])
    assert not (tmp_path / "out").exists()
    assert (tmp_path / "cache" / "fr" / "_check.json").exists()
