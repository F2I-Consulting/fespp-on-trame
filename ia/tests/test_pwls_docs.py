"""The PWLS 4.0 dictionary to Markdown: a synthetic EPC of four property
kinds (the root, an abstract node without a definition, two kinds with
aliases) gives the files, headings and lines the corpus builder expects;
a bigger one shows the builder makes one chunk per kind."""
import zipfile

import pytest

from fespp_ia.corpus import dropped_files
from fespp_ia.pwls_docs import alias_line, group_of, kind_markdown, main, read_kinds

ROOT = "a48c9c25-1e3a-43c8-be6a-044224cc69cb"
FRACTION = "608644e2-3cd4-461e-92d3-5d7768472bbd"
POROSITY = "69698278-5ad1-4512-bddc-8afed34bc3d8"
SATURATION = "2cea6718-2266-49b0-9a10-57fe3127eebc"


def part(uuid, title, description, parent, parent_title, quantity, abstract, aliases=()):
    alias_xml = "".join(
        f'<eml23:Aliases authority="{authority}" xsi:type="eml23:ObjectAlias">'
        f'<eml23:Identifier xsi:type="eml23:String64">{identifier}</eml23:Identifier></eml23:Aliases>\n'
        for authority, identifier in aliases)
    desc_xml = f'<eml23:Description xsi:type="eml23:String2000">{description}</eml23:Description>' if description else ""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<eml23:PropertyKind xmlns:eml23="http://www.energistics.org/energyml/data/commonv2" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" schemaVersion="2.3" uuid="{uuid}" xsi:type="eml23:PropertyKind">
{alias_xml}<eml23:Citation xsi:type="eml23:Citation">
<eml23:Title xsi:type="eml23:String256">{title}</eml23:Title>
<eml23:Originator xsi:type="eml23:String64">Energistics</eml23:Originator>
{desc_xml}
</eml23:Citation>
<eml23:IsAbstract xmlns:xsd="http://www.w3.org/2001/XMLSchema" xsi:type="xsd:boolean">{abstract}</eml23:IsAbstract>
<eml23:QuantityClass xsi:type="eml23:QuantityClassKindExt">{quantity}</eml23:QuantityClass>
<eml23:Parent xsi:type="eml23:DataObjectReference">
<eml23:Uuid xsi:type="eml23:UuidString">{parent}</eml23:Uuid>
<eml23:QualifiedType xsi:type="eml23:QualifiedType">eml23.PropertyKind</eml23:QualifiedType>
<eml23:Title xsi:type="eml23:String2000">{parent_title}</eml23:Title>
</eml23:Parent>
</eml23:PropertyKind>
"""


@pytest.fixture
def epc(tmp_path):
    path = tmp_path / "pwls.epc"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        # the root names itself as its parent; an abstract node without a
        # definition; porosity with three aliases (one identifier twice)
        # and a "&" the XML escapes; a kind filed under another letter
        z.writestr(f"namespace_eml23/PropertyKind_{ROOT}.xml",
                   part(ROOT, "property", "Any SDM Property defined in this catalogue", ROOT, "property",
                        "unitless", "true", [("Energistics:RESQML 2.0.1", "quantity")]))
        z.writestr(f"namespace_eml23/PropertyKind_{FRACTION}.xml",
                   part(FRACTION, "volume fraction", "", ROOT, "property", "volume per volume", "true"))
        z.writestr(f"namespace_eml23/PropertyKind_{POROSITY}.xml",
                   part(POROSITY, "porosity", "Pore volume per unit gross volume &amp; nothing else.",
                        FRACTION, "volume fraction", "volume per volume", "false",
                        [("Energistics:PWLS v1", "Porosity"), ("Energistics:PWLS v2", "Porosity"),
                         ("Energistics:RESQML 2.0.1", "porosity")]))
        z.writestr(f"namespace_eml23/PropertyKind_{SATURATION}.xml",
                   part(SATURATION, "water saturation", "The extent to which the pore space contains water.",
                        ROOT, "property", "dimensionless", "false", [("Energistics:PWLS v2", "Water_Saturation")]))
        z.writestr(f"namespace_eml23/_rels/PropertyKind_{POROSITY}.xml.rels", "<Relationships/>")
    return path


def test_the_parts_are_read_with_their_aliases_parent_and_class(epc):
    kinds = {k["title"]: k for k in read_kinds(str(epc))}
    assert set(kinds) == {"property", "volume fraction", "porosity", "water saturation"}
    porosity = kinds["porosity"]
    assert porosity["description"] == "Pore volume per unit gross volume & nothing else."
    assert porosity["aliases"] == [("Energistics:PWLS v1", "Porosity"), ("Energistics:PWLS v2", "Porosity"),
                                   ("Energistics:RESQML 2.0.1", "porosity")]
    assert porosity["parent"] == "volume fraction"
    assert porosity["quantity_class"] == "volume per volume"
    assert porosity["abstract"] is False
    assert kinds["property"]["parent"] is None        # the root, its own parent in the file
    assert kinds["volume fraction"]["abstract"] is True


def test_a_kind_is_a_heading_and_up_to_three_lines():
    md = kind_markdown({"title": "porosity", "description": "Pore volume per unit gross volume.",
                        "aliases": [("Energistics:PWLS v1", "Porosity"), ("Energistics:PWLS v2", "Porosity"),
                                    ("Energistics:RESQML 2.0.1", "porosity")],
                        "parent": "volume fraction", "quantity_class": "volume per volume", "abstract": False})
    assert md == ("### porosity\n"
                  "Pore volume per unit gross volume.\n"
                  "Alias : Porosity (PWLS v1, PWLS v2), porosity (RESQML 2.0.1)\n"
                  "Parent : volume fraction ; classe de grandeur : volume per volume\n")


def test_an_abstract_kind_without_a_definition_is_left_out_a_root_keeps_its_class():
    """An abstract kind with no definition has nothing to teach and gives no
    section; a kind without a parent still states its quantity class."""
    assert kind_markdown({"title": "volume fraction", "description": "", "aliases": [], "parent": "property",
                          "quantity_class": "volume per volume", "abstract": True}) == ""
    assert kind_markdown({"title": "property", "description": "Any property.", "aliases": [], "parent": None,
                          "quantity_class": "unitless", "abstract": True}) == \
        "### property\nAny property.\nclasse de grandeur : unitless\n"


def test_the_alias_line_and_the_groups():
    assert alias_line([]) == ""
    assert alias_line([("Energistics:PWLS v2", "Water_Saturation"), ("", "Sw")]) == \
        "Alias : Water_Saturation (PWLS v2), Sw"
    assert group_of("porosity") == "P-Q"
    assert group_of("quality factor") == "P-Q"
    assert group_of("1st derivative") == "A"
    assert group_of("x coordinate") == "X-Z"
    assert group_of("water saturation") == "W"


def test_main_writes_one_file_per_group_with_the_header_and_rewrites_the_folder(epc, tmp_path, capsys):
    out = tmp_path / "pwls"
    out.mkdir()
    (out / "pwls-z.md").write_text("# stale\n", encoding="utf-8")
    assert main([str(epc), str(out)]) == 0
    assert sorted(p.name for p in out.iterdir()) == ["pwls-p-q.md", "pwls-w.md"]   # the stale file is gone
    text = (out / "pwls-p-q.md").read_text(encoding="utf-8")
    assert text.startswith("# PWLS 4.0 -- P-Q\n\nSource : Energistics, PWLS 4.0")
    assert "https://www.energistics.org/" in text.split("\n")[2]
    assert "\n### porosity\nPore volume per unit gross volume & nothing else.\n" \
           "Alias : Porosity (PWLS v1, PWLS v2), porosity (RESQML 2.0.1)\n" \
           "Parent : volume fraction ; classe de grandeur : volume per volume\n" in text
    assert "### property\nAny SDM Property defined in this catalogue\nAlias : quantity (RESQML 2.0.1)\n" \
           "classe de grandeur : unitless\n" in text
    assert "### volume fraction" not in text        # abstract, no definition
    assert "### water saturation\n" in (out / "pwls-w.md").read_text(encoding="utf-8")
    assert "3 kinds of 4 in 2 files" in capsys.readouterr().out


def test_the_corpus_builder_makes_one_chunk_per_kind(tmp_path):
    # sixty kinds: a file of realistic size (the builder reads a small
    # Markdown file as one chunk, whatever its headings)
    path = tmp_path / "pwls.epc"
    with zipfile.ZipFile(path, "w") as z:
        for n in range(60):
            uuid = f"{n:08d}-0000-4000-8000-000000000000"
            z.writestr(f"namespace_eml23/PropertyKind_{uuid}.xml",
                       part(uuid, f"porosity kind {n:02d}", f"Definition number {n} of a porosity, from cores or logs.",
                            ROOT, "porosity", "volume per volume", "false", [("Energistics:PWLS v2", f"Porosity_{n}")]))
    out = tmp_path / "pwls"
    main([str(path), str(out)])
    rows = {r["title"]: r for r in dropped_files(str(out))}
    assert len(rows) == 61 and all(r["path"] == "pwls-p-q.md" for r in rows.values())
    assert rows["PWLS 4.0 -- P-Q"]["text"].startswith("PWLS 4.0 -- P-Q\n\nSource : Energistics")   # the header line
    assert rows["PWLS 4.0 -- P-Q › porosity kind 07"]["text"] == (
        "PWLS 4.0 -- P-Q › porosity kind 07\n\n"
        "Definition number 7 of a porosity, from cores or logs.\n"
        "Alias : Porosity_7 (PWLS v2)\n"
        "Parent : porosity ; classe de grandeur : volume per volume")
