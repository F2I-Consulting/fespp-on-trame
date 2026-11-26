"""engine/pwls_kinds — ancestry over a tiny hierarchy, and the shipped table."""
import pytest

from fespp_on_trame.engine import pwls_kinds as pk


@pytest.fixture
def tiny():
    pk.use_table({
        "property": [None, ""],
        "porosity": ["property", "volume per volume"],
        "Neutron Porosity": ["porosity", "volume per volume"],
        "effective porosity": ["porosity", "volume per volume"],
        "saturation": ["property", "volume per volume"],
        "water saturation": ["saturation", "volume per volume"],
        "gas saturation": ["saturation", "volume per volume"],
    })
    yield
    pk.use_table(None)


def test_ancestors_are_lower_cased_self_first(tiny):
    assert pk.ancestors("NEUTRON porosity") == ["neutron porosity", "porosity", "property"]
    assert pk.ancestors("no such kind") == []
    assert pk.known("Porosity") and not pk.known("PHIE")
    assert pk.quantity_class("porosity") == "volume per volume"


def test_relation_same_and_specialisation(tiny):
    assert pk.relation("porosity", "Porosity") == (0, "same")
    assert pk.relation("neutron porosity", "porosity") == (1, "a under b")
    assert pk.relation("saturation", "water saturation") == (1, "b under a")
    assert pk.relation("neutron porosity", "property") == (2, "a under b")


def test_relation_never_pairs_siblings_or_unknowns(tiny):
    assert pk.relation("water saturation", "gas saturation") is None
    assert pk.relation("neutron porosity", "water saturation") is None
    assert pk.relation("porosity", "PHIE") is None


def test_shipped_table_knows_the_classics():
    pk.use_table(None)
    if not pk.known("porosity"):
        pytest.skip("assets/pwls40_kinds.json not generated")
    assert pk.relation("water saturation", "saturation")[1] == "a under b"
    assert pk.relation("water saturation", "gas saturation") is None
