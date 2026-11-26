"""Tests for engine/utils/numfmt, the single on-screen number rule.

widgets/_shared/numfmt.js mirrors it, and the same worked examples are
pinned on both sides so the two cannot drift apart."""
import math

import pytest

from fespp_on_trame.engine.utils import numfmt as nf
from fespp_on_trame.engine.utils.numfmt import DASH, NBSP, THIN

T = THIN


@pytest.mark.parametrize("value, expected", [
    (0, "0"),
    (0.00123, "0.00123"),
    (1.2e-14, "1.2e-14"),
    (1234.5678, f"1{T}235"),
    (3.4e12, "3.4e+12"),
    (-0.5, "-0.5"),
    (1e6, f"1{T}000{T}000"),
    (float("nan"), DASH),
    # the fixed/scientific range test runs on the rounded value
    (1000001, f"1{T}000{T}000"),
    (1000500, "1.001e+6"),
    (0.00099995, "0.001"),
    # a tie rounds away from zero
    (1234500000, "1.235e+9"),
    (-1234500000, "-1.235e+9"),
    (0.5, "0.5"),
    (12.3456, "12.35"),
    (999.96, f"1{T}000"),
    (-0.0, "0"),
    (True, "1"),
])
def test_fmt_worked_examples(value, expected):
    assert nf.fmt(value) == expected


def test_fmt_missing_and_infinite():
    assert nf.fmt(None) == DASH
    assert nf.fmt("") == DASH
    assert nf.fmt("   ") == DASH
    assert nf.fmt(float("inf")) == "∞"
    assert nf.fmt(float("-inf")) == "-∞"


def test_fmt_strings_parse_or_pass_through():
    assert nf.fmt("1234.5678") == f"1{T}235"
    assert nf.fmt("Upper") == "Upper"          # a label, not a number


def test_fmt_never_writes_a_decimal_comma_or_a_regular_space():
    for v in (1234.5, 1e6, 0.001234, -98765.4321):
        s = nf.fmt(v)
        assert "," not in s and " " not in s


def test_fmt_int():
    assert nf.fmt_int(926808) == f"926{T}808"
    assert nf.fmt_int(926808.0) == f"926{T}808"
    assert nf.fmt_int(12.5) == "13"
    assert nf.fmt_int(-12.5) == "-13"
    assert nf.fmt_int(0) == "0"
    assert nf.fmt_int(None) == DASH
    assert nf.fmt_int(float("nan")) == DASH
    assert nf.fmt_int(12345678901) == f"12{T}345{T}678{T}901"   # never scientific


def test_fmt_pct():
    assert nf.fmt_pct(0.123456) == f"12.35{NBSP}%"
    assert nf.fmt_pct(1) == f"100{NBSP}%"
    assert nf.fmt_pct(None) == DASH
    assert nf.fmt_pct(float("nan")) == DASH


def test_fmt_fixed():
    assert nf.fmt_fixed(0.125, 2) == "0.13"
    assert nf.fmt_fixed(1234567.891, 2) == f"1{T}234{T}567.89"
    assert nf.fmt_fixed(-3.14159, 3) == "-3.142"
    assert nf.fmt_fixed(6400000, 0) == f"6{T}400{T}000"
    assert nf.fmt_fixed(1e9, 0) == f"1{T}000{T}000{T}000"       # never scientific
    assert nf.fmt_fixed(None, 2) == DASH
    assert nf.fmt_fixed(float("nan"), 2) == DASH


def test_unit_power():
    assert nf.unit_power("m3/m3", 1) == "m3/m3"
    assert nf.unit_power("m3/m3", 2) == "(m3/m3)²"
    assert nf.unit_power("m3/m3", 3) == "(m3/m3)³"
    assert nf.unit_power("m3/m3", 4) == "(m3/m3)⁴"
    assert nf.unit_power("m3/m3", 2, ascii=True) == "(m3/m3)^2"
    assert nf.unit_power("m3/m3", 0) == ""
    assert nf.unit_power("", 2) == ""
    assert nf.unit_power(None, 1) == ""


def test_the_widgets_unit_table_covers_every_metric():
    """The power of the property's unit each statistic carries, what the headers
    and the CSV columns of the Statistics view read: a variance is in unit², a
    third moment in unit³, a count has none."""
    import re
    from pathlib import Path
    from fespp_on_trame.engine import compare_matrix
    js = (Path(__file__).resolve().parents[2] / "widgets" / "_shared" / "numfmt.js").read_text(encoding="utf-8")
    body = re.search(r"STAT_UNIT_POWER = \{(.*?)\}", js, re.S).group(1)
    table = {quoted or bare: int(power)
             for quoted, bare, power in re.findall(r'(?:"([^"]+)"|(\w+)):\s*(\d)', body)}
    assert set(table) == set(compare_matrix._METRIC_KEYS)
    assert table["Variance"] == 2 and table["M3"] == 3 and table["M4"] == 4
    assert table["Mean"] == table["Mean (L)"] == table["Sum"] == 1
    assert table["Cardinality"] == table["NaN_count"] == table["Skewness"] == 0


def test_round_trip_on_random_magnitudes():
    # every output is either a grouped fixed number or a short scientific one
    import re
    fixed = re.compile(rf"^-?\d{{1,3}}({T}\d{{3}})*(\.\d+)?$")
    sci = re.compile(r"^-?\d(\.\d+)?e[+-]\d+$")
    for k in range(-20, 20):
        for m in (1.0, 1.23456, 9.99995, 5.5):
            s = nf.fmt(m * 10.0 ** k)
            assert fixed.match(s) or sci.match(s), s
            assert not math.isnan(float(s.replace(T, "")))


def test_plural_writes_the_noun_out():
    """The noun takes its right number, never "(s)".

    "1 wellbore(s)" reads as if the application did not know the count;
    the count itself is grouped like every other number."""
    assert nf.plural(1, "wellbore") == "1 wellbore"
    assert nf.plural(0, "wellbore") == "0 wellbores"
    assert nf.plural(3, "wellbore") == "3 wellbores"
    assert nf.plural(19, "property", "properties") == "19 properties"
    assert nf.plural(1, "property", "properties") == "1 property"
    assert nf.plural(2500, "cell") == f"2{T}500 cells"
    assert nf.plural(None, "cell") == "0 cells"
