"""The OSDU guide as the corpus reads it: one section per glossary entry,
navigation and long JSON records left out, links reduced to their label."""
from fespp_ia.corpus import source_of
from fespp_ia.osdu_docs import clean_markdown, glossary_markdown, page_name

GLOSSARY = """<a name="TOC"></a> Previous Chapter: [Appendix A References](90-References.md)

# Appendix B Glossary of Terms

Quick Navigation:  [4](#4) [A](#a) - [Top of Page](#TOC)

## A

<a name="Activity"></a>
* **Activity**<br>
  (OSDU entity type **Activity** in group-type work-product-component) Description: _Instance of a given activity_<br>
    &rarr; _OSDU types/schemas:_ [work-product-component--Activity](../../E-R/work-product-component/Activity.1.1.0.md)
<a name="Wellbore"></a>
* **Wellbore**<br>
  A path drilled from a well origin to a bottom hole<br>
"""


def test_the_glossary_becomes_one_section_per_entry_with_the_types_by_name():
    md, n = glossary_markdown(GLOSSARY, "# OSDU — glossaire\n\nSource : test")
    assert n == 2
    assert "### Activity\n\n(OSDU entity type Activity in group-type work-product-component)" in md
    assert "Types OSDU : work-product-component--Activity" in md
    assert "### Wellbore\n\nA path drilled from a well origin to a bottom hole" in md
    assert "E-R/" not in md and "Quick Navigation" not in md and "<a name" not in md


def test_a_guide_page_loses_its_navigation_its_json_records_and_its_links_section():
    lines = "\n".join(f'  "k{i}": {i},' for i in range(20))
    page = f"""<a name="TOC"></a> Previous Chapter: [9 Seismic](09-Seismic.md)

[[_TOC_]]

# 13 Earth Modelling

The *RESQML* standard maps to [IjkGridRepresentation](../../E-R/IjkGrid.1.0.0.md) ![fig](Illustrations/x.png).

| **RESQML**       | **OSDU**          |
|------------------|-------------------|
| obj_TimeSeries   | [TimeSeries](../../E-R/TimeSeries.md) |

```json
{{
{lines}
}}
```

```json
{{"short": 1}}
```

---

## Links

1. Return to the [Beginning of the Chapter](#TOC)
"""
    md = clean_markdown(page)
    assert md.startswith("# 13 Earth Modelling")
    assert "maps to IjkGridRepresentation ." in md
    assert "| obj_TimeSeries | TimeSeries |" in md
    assert "(exemple JSON omis / JSON example left out)" in md
    assert '{"short": 1}' in md
    assert "Previous Chapter" not in md and "_TOC_" not in md and "Links" not in md and "Return to" not in md


def test_worked_examples_are_named_by_their_folder():
    assert page_name("Examples/WorkedExamples/WellLog/README.md") == "WellLog.md"
    assert page_name("Examples/WorkedExamples/Reservoir Data/README.md") == "Reservoir_Data.md"
    assert page_name("Guides/Chapters/13-EarthModelling.md") == "13-EarthModelling.md"


def test_the_osdu_folder_has_its_own_label():
    assert source_of("/repo/ia/corpus/osdu/glossaire-osdu.md") == "osdu"
