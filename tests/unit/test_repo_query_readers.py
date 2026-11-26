"""engine/repo_query — a source standing for several readers: each question
goes to the reader that holds the object."""
import pytest

from fespp_on_trame.engine import repo_query as rq


class _Reader:
    def __init__(self, gid, index, has_store=False):
        self.gid, self.index, self.has_store = gid, index, has_store
        self.asked = []

    def GetGlobalIDAsString(self):
        return self.gid

    def GetProperty(self, name):
        return object() if self.has_store and name in ("LazyFetchKey", "InventoryKey") else None


@pytest.fixture
def two(monkeypatch):
    files = _Reader("1", ["a|IjkGridRepresentation|0|Model", "c|LocalDepth3dCrs|1|crs"])
    store = _Reader("2", ["b|Grid2dRepresentation|0|Top", "c|LocalDepth3dCrs|0|crs"], has_store=True)
    joined = _Reader("9", [])

    def ask(source, key_name, reply_name, key):
        source.asked.append((key_name, key))
        wanted = key.split("|", 1)[1]
        if key_name == "ObjectUuidsKey":
            return list(source.index) if wanted == "*" else [
                line.split("|")[0] for line in source.index if line.split("|")[1] == wanted]
        if key_name == "ObjectXmlKey":
            held = {line.split("|")[0] for line in source.index}
            return [f"<{u} of={source.gid}/>" if u in held else "" for u in wanted.split(",")]
        if key_name == "ObjectFieldsKey":
            return [f"reader={source.gid}"]
        return []

    monkeypatch.setattr(rq, "_ask", ask)
    monkeypatch.setattr(rq, "_READERS", {})
    monkeypatch.setattr(rq, "_INDEX_CACHE", {})
    tags = {"1": 3, "2": 5}
    plain = rq.tag
    monkeypatch.setattr(rq, "tag", lambda s: tags[s.gid] if s.gid in tags else plain(s))
    rq.stands_for(joined, [files, store])
    return joined, files, store, tags


def test_the_index_lists_both_readers_an_object_of_both_once_and_whole(two):
    joined, _files, _store, _tags = two
    index = rq.object_index(joined)
    assert [(e["uuid"], e["partial"]) for e in index] == [("a", False), ("c", False), ("b", False)]


def test_each_object_is_asked_of_the_reader_that_holds_it_in_one_round_trip_each(two):
    joined, files, store, _tags = two
    assert rq.object_xml(joined, ["b", "a", "zz", "c"]) == ["<b of=2/>", "<a of=1/>", "", "<c of=2/>"]
    assert rq.object_xml(joined, "a") == "<a of=1/>"
    assert [k for k, _key in files.asked].count("ObjectXmlKey") == 2
    assert [k for k, _key in store.asked].count("ObjectXmlKey") == 1
    assert rq.object_fields(joined, "b|surface") == {"reader": "2"}
    assert rq.object_fields(joined, "a") == {"reader": "1"}
    assert rq.object_uuids(joined, "LocalDepth3dCrs") == ["c"]


def test_the_tag_changes_when_a_reader_s_does_and_the_store_answers_its_own_questions(two):
    joined, files, store, tags = two
    before = rq.tag(joined)
    tags["2"] = 6
    assert rq.tag(joined) != before
    assert rq.has_lazy_fetch(joined) and rq.has_inventory(joined)
    assert rq._store(joined, "LazyFetchKey") is store
    assert not rq.has_lazy_fetch(files)
