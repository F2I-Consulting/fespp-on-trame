"""The ICS chart document for the RAG: the French names, one unit's span and
duration, and the file the generator writes, with one "### " heading per
unit (one chunk per unit). The tests on the chart itself need
fespp_on_trame/engine/ics_chart.py beside the package (in the repository,
or mounted there) and are skipped otherwise."""
import os

import pytest

from fespp_ia import ics_docs


def test_french_names_come_from_the_table_then_the_rule_ian_ien():
    assert ics_docs.french_name("Callovian") == "Callovien"
    assert ics_docs.french_name("Danian") == "Danien"
    assert ics_docs.french_name("Bathonian") == "Bathonien"
    assert ics_docs.french_name("Rupelian") == "Rupélien"        # the table beats the rule
    assert ics_docs.french_name("Cretaceous") == "Crétacé"
    assert ics_docs.french_name("Triassic") == "Trias"
    assert ics_docs.french_name("Eocene") == "Éocène"
    assert ics_docs.french_name("Cenozoic") == "Cénozoïque"
    assert ics_docs.french_name("Precambrian") == "Précambrien"


def test_a_series_qualifier_goes_after_the_noun():
    assert ics_docs.french_name("Middle Jurassic") == "Jurassique moyen"
    assert ics_docs.french_name("Upper Cretaceous") == "Crétacé supérieur"
    assert ics_docs.french_name("Early Jurassic") == "Jurassique inférieur"
    assert ics_docs.french_name("Late Triassic") == "Trias supérieur"
    assert ics_docs.french_name("Lower Callovian") == "Callovien inférieur"


def test_ages_lose_their_trailing_zeros_and_take_a_comma_in_french():
    assert ics_docs.ma(66.0) == "66"
    assert ics_docs.ma(251.902) == "251.902"
    assert ics_docs.ma(0.0117, french=True) == "0,0117"
    assert ics_docs.ma(165.3 - 161.5, french=True) == "3,8"


@pytest.fixture(scope="module")
def chart():
    path = ics_docs.default_chart_path()
    if not os.path.exists(path):
        pytest.skip(f"the application's table is not there: {path}")
    return ics_docs.load_chart(path)


def test_a_stage_gives_its_parents_base_top_and_duration_in_both_languages(chart):
    heading, body = ics_docs.unit_section(chart, "Callovian")
    assert heading == "### Callovien (Callovian)"
    fr, en = body.split("\n\n")
    assert fr.startswith("Le Callovien (Callovian) est un étage du Jurassique (période), du Mésozoïque (ère).")
    assert "Sa base est à 165,3 Ma, son sommet à 161,5 Ma" in fr and "il dure 3,8 Ma" in fr
    assert en.startswith("The Callovian (Callovien in French) is a stage of the Jurassic (period), of the Mesozoic (era).")
    assert "Its base is at 165.3 Ma, its top at 161.5 Ma" in en and "it lasts 3.8 Ma" in en
    assert f"ICS chart {chart.CHART_VERSION}." in en


def test_a_period_lists_its_stages_oldest_first_and_the_youngest_unit_ends_today(chart):
    _, body = ics_docs.unit_section(chart, "Jurassic")
    assert "Le Jurassique (Jurassic) est une période du Mésozoïque (ère)." in body
    assert "Ses étages, du plus ancien au plus récent : Hettangien, Sinémurien, Pliensbachien," in body
    assert "Its stages, oldest first: Hettangian, Sinemurian," in body
    _, body = ics_docs.unit_section(chart, "Quaternary")
    assert "son sommet est le présent (0 Ma) ; il dure 2,58 Ma" in body
    assert "Ses époques, de la plus ancienne à la plus récente : Pléistocène, Holocène." in body


def test_the_document_has_one_heading_per_unit_of_the_chart(chart, tmp_path):
    ics_docs.main([str(tmp_path), "--chart", ics_docs.default_chart_path()])
    text = (tmp_path / ics_docs.FILE_NAME).read_text(encoding="utf-8")
    assert text.startswith(f"# {ics_docs.TITLE}\n\nSource : {chart.CHART_SOURCE}, https://stratigraphy.org/chart,"
                           f" version {chart.CHART_VERSION} — licence CC BY 4.0")
    headings = [ln for ln in text.splitlines() if ln.startswith("### ")]
    assert len(headings) == len(chart._UNITS) == 70
    assert headings[0] == "### Cénozoïque (Cenozoic)" and headings[-1] == "### Précambrien (Precambrian)"
    assert "« Hugin Fm »" in text and "« Jurassique moyen »" in text and "Paléogène, 66 Ma" in text
