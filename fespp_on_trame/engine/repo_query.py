"""The query channel into the FESPP readers — the one Python-reachable RPC.

FESPP's classes are ClientServer-wrapped and never Python-wrapped:
``paraview_add_plugin()`` calls ``vtk_module_wrap_client_server`` and nothing
else, so ``GetClientSideObject()`` hands back the reader degraded to its
nearest wrapped base and every FESPP method is invisible (``hasattr`` is
False for all of them, ``GetLiveAssembly`` included). A settable
ServerManager property (the question) paired with an information-only one
carrying a StringArrayHelper (the answer) is the single channel that crosses
the gap; the plugin also uses it for ``FilesInfo`` and ``DataspacesInfo``.

The object queries live on a proxy of their own, ``EnergisticsQuery`` in the
``energistics`` group (``vtkEnergisticsQuery``), bound to a reader through
its ``Source`` property: the EPC collector and the ETP source are asked the
same way, and asking never marks the reader modified. This module creates
one query proxy per reader and keeps it. The ETP-only questions — the
inventory of a dataspace, the lazy fetch — are store operations and stay on
the ETP source.

Two idioms the channel depends on:

- push with the FORCED ``SMProxy.UpdateProperty(name, 1)``: an unforced push
  is a silent no-op on an unchanged value (the ETP ``Dataspaces`` trap), and
  the same question may legitimately be asked twice;
- pull with the single-property ``UpdatePropertyInformation(prop)``: the bare
  form re-pulls EVERY information property, and on the collector
  ``GetAllFiles()`` is the EPC loader itself.

A session reads files and a store together, each reader with its own
repository (engine/sources/merged_source): the source the application holds
then STANDS FOR both readers (`stands_for`), and a question asked of it goes
to the reader that holds the object — every function below takes either.

What comes back is fesapi's view of an object — ``serializeIntoString()`` —
not the file's bytes: the root loses its ``obj_`` prefix, every element gains
an ``xsi:type``, namespaces are declared per subtree and anything fesapi did
not deserialize is absent. It is identical over EPC and ETP, which is the
point.
"""
import re

TYPE_STRATI_RANK = "StratigraphicColumnRankInterpretation"

QUERY_GROUP = "energistics"
QUERY_PROXY = "EnergisticsQuery"

# the questions the ETP source answers itself (store operations)
_READER_KEYS = ("InventoryKey", "LazyFetchKey")


class ChannelMissing(RuntimeError):
    """The loaded plugin predates the query channel.

    The presence of the proxy definition (or of a property) is the only
    version probe available: the wrapping gap makes ``hasattr`` on the
    client-side object answer False for every method, old plugin or new."""


def _proxy(source):
    """The vtkSMProxy behind a pvsimple wrapper, or the proxy itself."""
    return getattr(source, "SMProxy", source)


# the global id of a source standing for several readers -> those readers
_READERS = {}


def _gid(source):
    """What tells one source from another: its proxy's global id."""
    proxy = _proxy(source)
    get = getattr(proxy, "GetGlobalIDAsString", None)
    return get() if get is not None else f"py{id(proxy)}"


def stands_for(source, readers):
    """`source` (the readers' collections joined) stands for `readers` from
    now on: what is asked of it is asked of them."""
    _READERS[_gid(source)] = list(readers)


def _readers(source):
    """The readers `source` stands for; None when it is a reader itself."""
    return _READERS.get(_gid(source))


def _owners(readers):
    """{uuid: the reader that holds the object}: the first reader listing it
    whole, else the first listing it at all."""
    out, stubs = {}, {}
    for reader in readers:
        for entry in object_index(reader):
            (stubs if entry["partial"] else out).setdefault(entry["uuid"], reader)
    for uuid, reader in stubs.items():
        out.setdefault(uuid, reader)
    return out


def store_uuids(source):
    """The uuids `source` reads from a store (a reader that fetches on
    demand): asking about one is a request to a server. Empty over files."""
    far = _store(source, "LazyFetchKey")
    if far is None:
        return set()
    readers = _readers(source) or [source]
    if len(readers) == 1:
        return {e["uuid"] for e in object_index(far)}
    return {uuid for uuid, reader in _owners(readers).items() if reader is far}


def _owner(readers, uuid):
    """The reader asked about `uuid` (its suffix after "|" aside): the one
    that holds it, the first when none lists it."""
    return _owners(readers).get(str(uuid).split("|", 1)[0], readers[0])


# reader global id -> (reader SMProxy, query SMProxy): the query proxies are
# never registered, this dict is what keeps them alive
_QUERY_PROXIES = {}


def _query_proxy(source):
    """The EnergisticsQuery proxy bound to this reader, created on first
    use; None when the loaded plugin has no such proxy."""
    reader = _proxy(source)
    key = reader.GetGlobalIDAsString()
    hit = _QUERY_PROXIES.get(key)
    if hit is not None and hit[0] is reader:
        return hit[1]
    pxm = reader.GetSessionProxyManager()
    if pxm is None or not pxm.GetProxyDefinitionManager().HasDefinition(QUERY_GROUP, QUERY_PROXY):
        return None
    query = pxm.NewProxy(QUERY_GROUP, QUERY_PROXY)
    if query is None:
        return None
    query.UnRegister(None)      # the creation's reference: Python holds the proxy from here
    prop = query.GetProperty("Source")
    prop.RemoveAllProxies()
    prop.AddProxy(reader)
    query.UpdateVTKObjects()
    _QUERY_PROXIES[key] = (reader, query)
    return query


def has_channel(source):
    readers = _readers(source)
    if readers is not None:
        return any(has_channel(r) for r in readers)
    return _query_proxy(source) is not None


def has_relations(source):
    """This plugin build answers the relationship query. Probed separately
    from `has_channel`: a build can carry the query channel without the
    relationship query, and there the two lists come back empty, which reads
    exactly like "this object is related to nothing" — and the reader
    deserves to be told which of the two it is looking at."""
    readers = _readers(source)
    if readers is not None:
        return any(has_relations(r) for r in readers)
    query = _query_proxy(source)
    return query is not None and query.GetProperty("ObjectRelationsKey") is not None


def tag(source):
    """The reader's AssemblyTag — bumped on every load, so it is the cache
    key a caller carries in front of every question. 0 when unavailable.
    Of a source standing for several readers: one number that changes when
    any of theirs does."""
    readers = _readers(source)
    if readers is not None:
        return hash(tuple((_gid(r), tag(r)) for r in readers)) & 0x7FFFFFFF
    proxy = _proxy(source)
    prop = proxy.GetProperty("AssemblyTag")
    if prop is None:
        return 0
    try:
        proxy.UpdatePropertyInformation(prop)
        return int(prop.GetElement(0))
    except Exception:
        return 0


def _ask(source, key_name, reply_name, key):
    """Push `key` on the property `key_name` and read the lines of
    `reply_name` back — on the query proxy of the reader, or on the reader
    itself for its own questions (`_READER_KEYS`)."""
    on_reader = key_name in _READER_KEYS
    proxy = _proxy(source) if on_reader else _query_proxy(source)
    key_prop = proxy.GetProperty(key_name) if proxy is not None else None
    reply_prop = proxy.GetProperty(reply_name) if proxy is not None else None
    if key_prop is None or reply_prop is None:
        raise ChannelMissing(
            f"the loaded FESPP plugin has no {key_name} property — rebuild "
            "it with the query channel (vtkEnergisticsQuery)")
    key_prop.SetElement(0, key)
    proxy.UpdateProperty(key_name, 1)            # forced: see the module doc
    proxy.UpdatePropertyInformation(reply_prop)  # this property only
    reply = [str(reply_prop.GetElement(i))
             for i in range(reply_prop.GetNumberOfElements())]
    if on_reader:
        # Re-settle the reader after the round-trip. The forced UpdateProperty
        # calls MarkModified on the reader (ParaView has no way to push a
        # property without it). Left as is, that flag makes a LATER read of
        # another time step leave the reader's CLIENT data information
        # empty — the C++ output stays correct, but the assembly the client
        # holds loses its nodes, and the next render's per-block scalar bar
        # dereferences a null GetSubsetDataInformation: a segmentation
        # fault. A direct UpdatePipeline at the current time re-executes and
        # re-gathers. The object queries go through their own proxy and
        # never mark the reader, so only the reader's own questions pay it.
        try:
            from paraview import simple as _pvsimple
            proxy.UpdatePipeline(float(_pvsimple.GetTimeKeeper().Time))
        except Exception as exc:
            print(f"[fespp] repo_query: reader re-settle after a {key_name} query "
                  f"failed ({exc!r}); a render after a time-step read may be unsafe",
                  flush=True)
    return reply


def object_xml(source, uuids, cache_tag=None):
    """Serialized XML of each uuid — one string per uuid, in order: the part
    as fesapi holds it, a ``<PartialObject>`` marker for a reference stub, or
    "" for an unknown uuid. Pass one uuid for one string, a list for a list.

    A list is ONE round trip: one request per object would take hundreds of
    requests for a single stratigraphic rank. Uuids go over as given — the
    C++ side case-folds, and lower-casing here would only hide a writer that
    emitted upper-case hex."""
    single = isinstance(uuids, str)
    wanted = [uuids] if single else [u for u in (uuids or ()) if u]
    if not wanted:
        return "" if single else []
    readers = _readers(source)
    if readers is not None:
        # one round trip per reader, each asked for the objects it holds
        owners = _owners(readers)
        found = {}
        for reader in readers:
            mine = [u for u in wanted if owners.get(u, readers[0]) is reader]
            if mine:
                found.update(zip(mine, object_xml(reader, mine)))
        reply = [found.get(u, "") for u in wanted]
        return reply[0] if single else reply
    t = cache_tag if cache_tag is not None else tag(source)
    reply = _ask(source, "ObjectXmlKey", "ObjectXml",
                 f"{t}|" + ",".join(wanted))
    if single:
        return reply[0] if reply else ""
    # the C++ answers one value per uuid; never let a short reply misalign
    # the caller's zip() all the same
    reply += [""] * (len(wanted) - len(reply))
    return reply[:len(wanted)]


def object_uuids(source, type_name, cache_tag=None):
    """Uuids of every object of one RESQML type name, partial stubs INCLUDED:
    fesapi demotes a whole rank to partial over one reference it cannot wrap,
    and that rank must still be listed so absence and demotion stay
    distinguishable to the caller (its XML is then the partial marker)."""
    readers = _readers(source)
    if readers is not None:
        return list(dict.fromkeys(u for r in readers for u in object_uuids(r, type_name)))
    t = cache_tag if cache_tag is not None else tag(source)
    return [u for u in _ask(source, "ObjectUuidsKey", "ObjectUuids",
                            f"{t}|{type_name}") if u]


_INDEX_CACHE = {}


def object_index(source, cache_tag=None):
    """Every object of the repository — ``[{uuid, type, title, partial}]``
    — the door the XML explorer opens any object from. One channel call
    per load (cached on the assembly tag): the C++ answers the type name
    "*" with one "uuid|xmlTag|partial|title" line per object, the title
    last because it may carry a "|". A plugin too old for "*" answers an
    empty list, and the caller says so."""
    readers = _readers(source)
    if readers is not None:
        # an object two readers hold is listed once, whole when one has it so
        out, at = [], {}
        for reader in readers:
            for entry in object_index(reader):
                known = at.get(entry["uuid"])
                if known is None:
                    at[entry["uuid"]] = len(out)
                    out.append(entry)
                elif out[known]["partial"] and not entry["partial"]:
                    out[known] = entry
        return out
    t = cache_tag if cache_tag is not None else tag(source)
    gid = _gid(source)
    hit = _INDEX_CACHE.get(gid)
    if hit is not None and hit[0] == t:
        return hit[1]
    out = []
    for line in _ask(source, "ObjectUuidsKey", "ObjectUuids", f"{t}|*"):
        parts = line.split("|", 3)
        if len(parts) < 4 or not parts[0]:
            continue
        out.append({"uuid": parts[0], "type": parts[1],
                    "partial": parts[2] == "1", "title": parts[3]})
    _INDEX_CACHE[gid] = (t, out)
    return out


def search_index(index, text, limit=60):
    """The entries of `index` matching `text`: every whitespace-separated
    word must appear in the title, the type or the uuid, case-folded;
    titles that START with the first word rank first, then titles that
    contain it, then the rest, each group alphabetical. Returns
    ``(hits, total)`` with at most `limit` hits."""
    words = [w for w in (text or "").lower().split() if w]
    if not words:
        return [], 0

    def _hay(e):
        return (e.get("title") or "").lower(), (e.get("type") or "").lower(), (e.get("uuid") or "").lower()
    found = []
    for e in index:
        title, typ, uuid = _hay(e)
        if all(w in title or w in typ or w in uuid for w in words):
            rank = 0 if title.startswith(words[0]) else 1 if words[0] in title else 2
            found.append((rank, title, e))
    found.sort(key=lambda x: (x[0], x[1]))
    return [e for _, _, e in found[:limit]], len(found)


def object_relations(source, uuid, cache_tag=None):
    """The relationships of one object, BOTH WAYS:
    ``{"target": [{uuid, type, title, partial}], "source": [...]}``.

    A **target** is an object this one designates — those could be read from
    its XML, where every ``DataObjectReference`` is written. A **source** is
    an object that designates THIS one, and that is readable nowhere but
    here: the reference lives in the XML of the object that POINTS, never in
    the one it points at, so no amount of reading these bytes would find it.
    fesapi keeps both directions and the channel hands them over.

    Both lists are empty on a plugin too old for the query, which is the same
    answer as "this object is related to nothing" — the caller says which it
    cannot tell apart."""
    out = {"target": [], "source": []}
    if not uuid:
        return out
    readers = _readers(source)
    if readers is not None:
        return object_relations(_owner(readers, uuid), uuid)
    t = cache_tag if cache_tag is not None else tag(source)
    for line in _ask(source, "ObjectRelationsKey", "ObjectRelations",
                     f"{t}|{uuid}"):
        # direction|uuid|xmlTag|partial|title — the title last, it may carry
        # a "|" of its own
        parts = line.split("|", 4)
        if len(parts) < 5 or parts[0] not in out:
            continue
        out[parts[0]].append({"uuid": parts[1], "type": parts[2],
                              "partial": parts[3] == "1", "title": parts[4]})
    return out


def object_fields(source, uuid, cache_tag=None):
    """Typed fields of one object as a dict — what fesapi's own accessors
    report, one ``key=value`` line per value, split on the FIRST ``=`` (a
    WKT carries its own). Empty for an unknown uuid, a reference stub, or a
    type the C++ has no entry for (it has one for the local 3D CRS, in both
    RESQML generations). Every key is optional: a getter that fails on its
    own drops its line, not the object."""
    if not uuid:
        return {}
    readers = _readers(source)
    if readers is not None:
        return object_fields(_owner(readers, uuid), uuid)
    t = cache_tag if cache_tag is not None else tag(source)
    fields = {}
    for line in _ask(source, "ObjectFieldsKey", "ObjectFields", f"{t}|{uuid}"):
        key, sep, value = line.partition("=")
        if sep and key:
            fields[key] = value
    return fields


_TYPE_ENUM_CACHE = {}


def type_enum(source):
    """FESPP's TreeViewNodeType table, ``{code: {"label", "grouping",
    "mapper"}}`` — 0 -> Unknown, 1 -> Collection, and so on.

    Beyond the label it carries the two predicates the PLUGIN owns, so the
    app does not re-implement them from lists of type names:

      grouping  isGroupingType — checking the node cascades to its children
      mapper    getMapperType  — "Folder" (draws nothing), "Data" (rides on a
                parent rep), "Mapper" / "MapperSet" (has geometry of its own)

    Cached per process, not per load: the table is a property of the BUILD,
    not of the data. Empty on a plugin that predates the property — callers
    then fall back to their own name lists."""
    readers = _readers(source)
    if readers is not None:
        return type_enum(readers[0])
    proxy = _query_proxy(source)
    key = id(proxy)
    if key in _TYPE_ENUM_CACHE:
        return _TYPE_ENUM_CACHE[key]
    out = {}
    prop = proxy.GetProperty("TypeEnumXml") if proxy is not None else None
    if prop is not None:
        try:
            proxy.UpdatePropertyInformation(prop)      # this property only
            xml = str(prop.GetElement(0)) if prop.GetNumberOfElements() else ""
            import xml.etree.ElementTree as ET
            for el in ET.fromstring(xml) if xml else ():
                code, label = el.get("code"), el.get("label")
                if code is not None and label:
                    out[str(code)] = {
                        "label": label,
                        "grouping": el.get("grouping") == "1",
                        "mapper": el.get("mapper") or "Folder",
                    }
        except Exception:
            out = {}
    _TYPE_ENUM_CACHE[key] = out
    return out


def is_partial_marker(xml_text):
    """True for the ``<PartialObject>`` marker the C++ emits for a stub."""
    head = (xml_text or "").lstrip()
    return head.startswith("<PartialObject")


# an element may carry attributes (fesapi writes xsi:type and xmlns on the
# Index of a TimeIndex: Volve's GasSat); "\b" keeps IndexableElement out
_TIME_INDEX = re.compile(
    r"<(?:\w+:)?TimeIndex\b[^>]*>.*?<(?:\w+:)?Index\b[^>]*>\s*(\d+)\s*<", re.S)
_TIME_INDEX_START = re.compile(r"<(?:\w+:)?TimeIndexStart\b[^>]*>\s*(\d+)\s*<")
_REALIZATION_INDEX = re.compile(r"<(?:\w+:)?RealizationIndex\b[^>]*>\s*(\d+)\s*<")
_REALIZATION_INDICES = re.compile(
    r"<(?:\w+:)?RealizationIndices\b[^>]*>(.*?)</(?:\w+:)?RealizationIndices>", re.S)


def series_indices(xml_text):
    """``(time index, realization index)`` a property's XML declares, each
    None when it declares none: the step of a time series (RESQML 2.0.1
    ``TimeIndex/Index``, 2.2 ``TimeIndices/TimeIndexStart``) and the
    realization (2.0.1 ``RealizationIndex``, 2.2 the first value of
    ``RealizationIndices``). What makes ten objects of one title ten steps
    or ten realizations of ONE property."""
    xml = xml_text or ""
    ts = real = None
    m = _TIME_INDEX.search(xml) or _TIME_INDEX_START.search(xml)
    if m:
        ts = int(m.group(1))
    m = _REALIZATION_INDEX.search(xml)
    if m:
        real = int(m.group(1))
    else:
        m = _REALIZATION_INDICES.search(xml)
        if m:
            first = re.search(r">\s*(\d+)\s*<", m.group(1))
            real = int(first.group(1)) if first else None
    return ts, real


def _store(source, prop):
    """The reader that answers the store's own question `prop`: `source`
    when it carries the property, the one of the readers it stands for that
    does; None when none does."""
    for reader in (_readers(source) or [source]):
        if _proxy(reader).GetProperty(prop) is not None:
            return reader
    return None


def has_inventory(source):
    """This plugin build inventories a dataspace without loading it — the
    ETP source alone carries the property (an EPC has no dataspace)."""
    return _store(source, "InventoryKey") is not None


def inventory_lines(source, dataspace_uri, types="*", cache_tag=""):
    """The inventory of one ETP dataspace, read by the plugin over the open
    session into a scratch repository of its own — nothing lands in the
    tree. The raw lines, as `osdu_explorer.parse_inventory` reads them:
    "#info|key=value|..." first (or "#error|words" alone), then one
    "uri|type|uuid|kind|title" per object, the title last.

    `types`: a comma list of qualified types ("resqml20.obj_ContinuousProperty",
    `osdu_explorer.KIND_TYPES` for the property kinds), "*" for every
    object — what a later load of the dataspace reuses instead of its own
    fetch — or "names" for the resources alone (no XML: the counts and
    names of any ETP server, REST facade or not). `cache_tag` is the
    caller's key: the plugin answers an unchanged key from its cache, and
    validates a changed one against the store's last-write stamp before
    fetching again. Synchronous: seconds on a hosted store, on the server
    loop, and never while a dataspace loads (the plugin says so)."""
    if not dataspace_uri:
        return ["#error|no dataspace named"]
    if not has_inventory(source):
        raise ChannelMissing("the loaded FESPP plugin has no InventoryKey property — rebuild it "
                             "with the dataspace inventory (vtkETPSource::SetInventoryKey)")
    return _ask(_store(source, "InventoryKey"), "InventoryKey", "Inventory",
                f"{cache_tag}|{dataspace_uri}|{types}")


def has_lazy_fetch(source):
    """This plugin build leaves the properties and frames of a dataspace on
    the store at load (the lazy leaves) and fetches them on request — the
    ETP source alone carries the property."""
    return _store(source, "LazyFetchKey") is not None


def parse_lazy_reply(lines):
    """`(remaining, fetched, seconds)` from the plugin's "remaining|fetched|seconds",
    None when the reply is empty or unreadable."""
    if not lines:
        return None
    parts = str(lines[0]).split("|")
    if len(parts) < 3 or not parts[0].isdigit() or not parts[1].isdigit():
        return None
    seconds = parts[2].strip()
    if not seconds.replace(".", "", 1).isdigit():
        return None
    return int(parts[0]), int(parts[1]), float(seconds)


def lazy_fetch(source, max_objects=200, nonce=0, uuids=None):
    """Fetch objects the plugin left on the store at the last dataspace
    loads, and complete their tree nodes (property kind, unit, range,
    metadata). `(remaining, fetched, seconds)`, or None.

    Without `uuids`: the next `max_objects` of the background read. With
    `uuids` (the nodes a tree expand or a panel opens): those objects and,
    for a grid, a trajectory, a frame or a property, every deferred
    property, frame and channel of that holder, in ONE request, at most
    `max_objects` of them. An empty list asks nothing.

    Synchronous, on the server loop: on a hosted store 0.13 s a request plus
    about 2 ms an object (doc/dev/ETP_TREE_FROM_DISCOVERY.md)."""
    if not has_lazy_fetch(source):
        return None
    key = f"{nonce}|{max(1, int(max_objects))}"
    if uuids is not None:
        wanted = [u for u in uuids if u]
        if not wanted:
            return None
        key += "|" + ",".join(wanted)
    return parse_lazy_reply(_ask(_store(source, "LazyFetchKey"), "LazyFetchKey", "LazyFetch", key))


__all__ = ["ChannelMissing", "TYPE_STRATI_RANK", "has_channel", "tag",
           "object_xml", "object_uuids", "object_fields", "type_enum",
           "is_partial_marker", "has_inventory", "inventory_lines",
           "has_lazy_fetch", "parse_lazy_reply", "lazy_fetch"]
