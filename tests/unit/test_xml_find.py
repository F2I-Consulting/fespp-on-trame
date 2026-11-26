"""The XML explorer's search (engine/repo_query): the repository index the
plugin answers to the type name "*", and the search over it."""
from fespp_on_trame.engine import repo_query as rq


def _index():
    return [
        {"uuid": "aaaa1111-0000-0000-0000-000000000001", "type": "IjkGridRepresentation", "title": "Sector", "partial": False},
        {"uuid": "bbbb2222-0000-0000-0000-000000000002", "type": "ContinuousProperty", "title": "Porosity", "partial": False},
        {"uuid": "cccc3333-0000-0000-0000-000000000003", "type": "ContinuousProperty", "title": "Total Porosity", "partial": False},
        {"uuid": "dddd4444-0000-0000-0000-000000000004", "type": "WellboreFeature", "title": "OP1", "partial": True},
    ]


def test_every_word_must_match_somewhere():
    hits, total = rq.search_index(_index(), "porosity continuous")
    assert total == 2 and [h["title"] for h in hits] == ["Porosity", "Total Porosity"]
    hits, total = rq.search_index(_index(), "porosity grid")
    assert total == 0 and hits == []


def test_a_title_that_starts_with_the_word_ranks_first():
    hits, _ = rq.search_index(_index(), "poro")
    assert [h["title"] for h in hits] == ["Porosity", "Total Porosity"]


def test_a_uuid_fragment_and_a_type_find_the_object():
    assert rq.search_index(_index(), "dddd4444")[0][0]["title"] == "OP1"
    assert rq.search_index(_index(), "ijkgrid")[0][0]["title"] == "Sector"


def test_the_limit_keeps_the_total_honest():
    index = [{"uuid": f"{i:08d}-0000-0000-0000-000000000000", "type": "T", "title": f"obj {i}", "partial": False}
             for i in range(100)]
    hits, total = rq.search_index(index, "obj", limit=10)
    assert len(hits) == 10 and total == 100


def test_an_empty_text_finds_nothing():
    assert rq.search_index(_index(), "   ") == ([], 0)


def test_the_channel_lines_are_split_with_the_title_last(monkeypatch):
    """The title may carry a "|": it is the fourth field and keeps the rest."""
    lines = ["u1|IjkGridRepresentation|0|Sector", "u2|ContinuousProperty|1|Net | Gross", "bad", ""]
    monkeypatch.setattr(rq, "_ask", lambda *a, **k: lines)
    monkeypatch.setattr(rq, "tag", lambda s: "t1")
    rq._INDEX_CACHE.clear()
    reader = object()
    out = rq.object_index(reader)
    assert out == [{"uuid": "u1", "type": "IjkGridRepresentation", "partial": False, "title": "Sector"},
                   {"uuid": "u2", "type": "ContinuousProperty", "partial": True, "title": "Net | Gross"}]
    # cached on the reader and its tag: the channel is not asked twice
    monkeypatch.setattr(rq, "_ask", lambda *a, **k: (_ for _ in ()).throw(AssertionError("asked twice")))
    assert rq.object_index(reader) == out
    rq._INDEX_CACHE.clear()


def test_series_indices_read_the_step_and_the_realization_of_a_property():
    v201 = ('<resqml2:ContinuousProperty xmlns:resqml2="x"><resqml2:TimeIndex>'
            '<resqml2:Index>3</resqml2:Index><resqml2:TimeSeries/></resqml2:TimeIndex>'
            '<resqml2:RealizationIndex>7</resqml2:RealizationIndex></resqml2:ContinuousProperty>')
    assert rq.series_indices(v201) == (3, 7)
    v22 = ('<resqml:ContinuousProperty><resqml:TimeIndices><resqml:TimeIndexCount>1'
           '</resqml:TimeIndexCount><resqml:TimeIndexStart>5</resqml:TimeIndexStart>'
           '</resqml:TimeIndices><resqml:RealizationIndices><eml:Value>2</eml:Value>'
           '</resqml:RealizationIndices></resqml:ContinuousProperty>')
    assert rq.series_indices(v22) == (5, 2)
    # fesapi's own writing (Volve's GasSat): attributes on the Index, and an
    # IndexableElement before it that must not be read as the Index
    fesapi = ('<resqml20:ContinuousProperty><resqml20:IndexableElement xsi:type="x">cells'
              '</resqml20:IndexableElement><resqml20:TimeIndex xsi:type="resqml20:TimeIndex">'
              '<resqml20:Index xmlns:xsd="y" xsi:type="xsd:nonNegativeInteger">4</resqml20:Index>'
              '<resqml20:TimeSeries/></resqml20:TimeIndex></resqml20:ContinuousProperty>')
    assert rq.series_indices(fesapi) == (4, None)
    assert rq.series_indices('<p><RealizationIndex xsi:type="xsd:int">6</RealizationIndex></p>') == (None, 6)
    # a property of neither kind, a stub, nothing
    assert rq.series_indices("<ContinuousProperty><Count>1</Count></ContinuousProperty>") == (None, None)
    assert rq.series_indices("<PartialObject/>") == (None, None)
    assert rq.series_indices("") == (None, None)
