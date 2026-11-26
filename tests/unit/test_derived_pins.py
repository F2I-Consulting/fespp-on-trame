"""engine/derived_props — pinned identifiers (A − B between two
realizations or two time steps of one property)."""
from fespp_on_trame.engine import derived_expr
from fespp_on_trame.engine.derived_props import split_pin


def test_split_pin_reads_realization_and_time_step():
    assert split_pin("PORO") == ("PORO", None)
    assert split_pin("PORO__r3") == ("PORO", {"real": 3, "ts": None})
    assert split_pin("SOIL__t12") == ("SOIL", {"real": None, "ts": 12})
    assert split_pin("X__r0__t5") == ("X", {"real": 0, "ts": 5})
    # an underscore in a name is not a pin
    assert split_pin("net_to_gross") == ("net_to_gross", None)
    assert split_pin("A__rx") == ("A__rx", None)


def test_parser_accepts_pinned_identifiers_as_names():
    parsed = derived_expr.parse("PORO__r3 - PORO__r7")
    assert not parsed.error
    assert list(parsed.identifiers) == ["PORO__r3", "PORO__r7"]
    parsed = derived_expr.parse("SOIL__t50 - SOIL__t0")
    assert not parsed.error and set(parsed.identifiers) == {"SOIL__t50", "SOIL__t0"}
