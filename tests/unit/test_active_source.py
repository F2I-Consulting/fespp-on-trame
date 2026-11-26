"""engine/sources/source_registry.ActiveSource — the readers of a session: a
reader counts while it HOLDS data, and a row is said of the reader that
holds it."""
from types import SimpleNamespace

import pytest

from fespp_on_trame.engine import repo_query as rq


class _Assembly:
    def __init__(self, paths):
        self.paths = list(paths)

    def GetNumberOfChildren(self, _node):
        return len(self.paths)

    def GetFirstNodeByPath(self, path):
        return 1 if path in self.paths else -1


class _Reader:
    def __init__(self, paths):
        self.assembly = _Assembly(paths)

    def GetClientSideObject(self):
        output = SimpleNamespace(GetDataAssembly=lambda: self.assembly)
        return SimpleNamespace(GetOutputDataObject=lambda _port: output)


def _session(files=(), store=()):
    source_registry = pytest.importorskip("fespp_on_trame.engine.sources.source_registry")
    readers = SimpleNamespace(files=_Reader(files), store=_Reader(store))
    connector = SimpleNamespace(is_connected=False, get_source=lambda: readers.store)
    active = source_registry.ActiveSource(SimpleNamespace(get_source=lambda: readers.files), connector)
    return active, readers, connector


def test_nothing_read_is_the_file_reader_alone_even_with_a_store_connected():
    active, readers, connector = _session()
    connector.is_connected = True
    assert active.readers() == [readers.files]
    assert active.store_paths(["/data/a"]) == set()


def test_a_store_counts_from_its_first_dataspace_on_and_past_its_disconnection():
    active, readers, connector = _session(store=["/data/top"])
    assert active.readers() == [readers.store], "disconnected: what was read of it stays"
    assert active.store_paths(["/data/top", "/data/else", "derived://x"]) == {"/data/top", "/data/else"}
    readers.files.assembly.paths.append("/data/model")
    assert active.readers() == [readers.files, readers.store], "the file reader first"


def test_with_both_a_row_is_the_store_s_when_its_assembly_holds_it():
    active, readers, _connector = _session(files=["/data/model"], store=["/data/top"])
    assert active.store_paths(["/data/model", "/data/top", "", "/data/gone"]) == {"/data/top"}
    assert active.reader_of("/data/top") is readers.store
    assert active.reader_of("/data/model") is readers.files


class _Asked:
    def __init__(self, gid, index, has_store=False):
        self.gid, self.index, self.has_store = gid, index, has_store

    def GetGlobalIDAsString(self):
        return self.gid

    def GetProperty(self, name):
        return object() if self.has_store and name == "LazyFetchKey" else None


def test_the_uuids_of_the_store_are_those_it_holds_whole_or_alone(monkeypatch):
    files = _Asked("1", ["a|IjkGridRepresentation|0|Model", "c|LocalDepth3dCrs|1|crs"])
    store = _Asked("2", ["b|Grid2dRepresentation|0|Top", "c|LocalDepth3dCrs|0|crs"], has_store=True)
    joined = _Asked("9", [])
    monkeypatch.setattr(rq, "_ask", lambda source, key_name, reply_name, key: list(source.index))
    monkeypatch.setattr(rq, "_READERS", {})
    monkeypatch.setattr(rq, "_INDEX_CACHE", {})
    monkeypatch.setattr(rq, "tag", lambda s: 1)
    rq.stands_for(joined, [files, store])
    assert rq.store_uuids(joined) == {"b", "c"}
    assert rq.store_uuids(store) == {"b", "c"}
    assert rq.store_uuids(files) == set()
