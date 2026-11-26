"""The log view's MD-TVD table (the MD column beside a TVD axis): every
stretch of the hole keeps pairs, a log read every half metre deep down never
crowds out a log read every fifteen metres higher up (Volve 15/9-19 A, 20/11:
the table crossed 1650 m of hole in a straight line, 148 m off)."""
from fespp_on_trame.engine import welllog_dispatch as wd


def _tvd(md):
    # a hole plumb to 1000 m, then leaning: 0.6 m down per metre along it
    return md if md <= 1000 else 1000 + 0.6 * (md - 1000)


def _table():
    sparse = [[1.0, md, _tvd(md)] for md in range(0, 2000, 15)]
    dense = [[1.0, 2000 + k * 0.5, _tvd(2000 + k * 0.5)] for k in range(4000)]
    return wd.md_tvd({"checkshot": sparse, "gamma": dense})


def _at(table, md):
    for (a, ta), (b, tb) in zip(table, table[1:]):
        if a <= md <= b:
            return ta if b == a else ta + (md - a) * (tb - ta) / (b - a)
    return None


def test_the_table_stays_small():
    assert len(_table()) <= wd.MD_TVD_POINTS + 1


def test_every_stretch_of_the_hole_keeps_its_pairs():
    table = _table()
    # away from the bend at 1000 m, which no sample stands on
    for md in (100, 700, 1300, 1900, 2500, 3900):
        assert abs(_at(table, md) - _tvd(md)) < 1.0, md


def test_a_short_table_is_kept_whole():
    full = {"a": [[1.0, md, _tvd(md)] for md in range(0, 100, 10)]}
    assert wd.md_tvd(full) == [[md, _tvd(md)] for md in range(0, 100, 10)]
