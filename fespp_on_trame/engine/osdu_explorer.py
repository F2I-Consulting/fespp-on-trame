"""The dataspace explorer: what an OSDU server holds, before anything is
loaded — the list of its dataspaces with dates and sizes, the facts of
each one (grids, wells, properties, surfaces, EPSG), and a text search
over the OSDU catalogue.

Everything here is HTTP on the Reservoir DDMS **REST facade** and the OSDU
**Search** service, with the token of the ETP connection (the same
Bearer, or the same Basic pair): the facade sits beside the ETP endpoint
on an OSDU platform (`wss://host/api/reservoir-ddms-etp/v2/` ->
`https://host/api/reservoir-ddms/v2`), and nothing here touches ParaView,
so it all runs in threads. A server without the facade (a bare
open-etp-server) gives the names only: the explorer then shows what ETP
listed, without facts.

The list of dataspaces takes one call, the type counts of a dataspace
one, its CRS two, the catalogue one. The facts still cost about a second
per dataspace on a hosted platform, hence the background scan that the
state mirrors as it goes. The token never leaves the process: it is read
from the connection kept in memory and put in a header, nothing else."""
import json
import re
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT = 60
SCAN_PARALLEL = 8       # dataspaces whose facts are read side by side
PAGE = 10000            # $top of the facade's paginated lists
CRS_TYPES = ("resqml20.obj_LocalDepth3dCrs", "resqml20.obj_LocalTime3dCrs", "eml23.LocalEngineeringCompoundCrs")
# the facts, from the type names the facade lists (RESQML 2.0.1 "obj_" and
# 2.2 without it)
FACTS = {
    "grids": ("IjkGridRepresentation", "UnstructuredGridRepresentation", "TruncatedIjkGridRepresentation"),
    "wells": ("WellboreTrajectoryRepresentation", "DeviationSurveyRepresentation", "BlockedWellboreRepresentation"),
    "properties": ("ContinuousProperty", "DiscreteProperty", "CategoricalProperty", "PointsProperty"),
    "surfaces": ("Grid2dRepresentation", "TriangulatedSetRepresentation"),
    "horizons": ("HorizonInterpretation",),
    "faults": ("FaultInterpretation",),
}
_ETP_PATH = re.compile(r"/reservoir-ddms-etp(/|$)")


class OsduError(Exception):
    """An answer the explorer cannot use: the status and the server's words."""


def empty_state():
    """The explorer's state before a connection (and after a disconnect):
    the shape the widget renders."""
    return {"status": "idle", "message": "", "rest": False, "dataspaces": [], "scanned": 0, "total": 0,
            "search": {"text": "", "status": "idle", "total": 0, "dataspaces": [], "components": [], "message": ""},
            "find": {"text": "", "status": "idle", "total": 0, "results": []}}


def rest_base(etp_url):
    """The REST facade beside an ETP endpoint, or None when the URL does
    not follow the OSDU layout: `wss://host/api/reservoir-ddms-etp/v2/`
    -> `https://host/api/reservoir-ddms/v2`."""
    u = urllib.parse.urlsplit((etp_url or "").strip())
    if u.scheme not in ("wss", "ws", "https", "http") or not u.netloc or not _ETP_PATH.search(u.path):
        return None
    scheme = "https" if u.scheme in ("wss", "https") else "http"
    path = _ETP_PATH.sub(r"/reservoir-ddms\1", u.path).rstrip("/")
    return f"{scheme}://{u.netloc}{path}"


def search_url(etp_url):
    """The OSDU Search service of the same platform, or None."""
    u = urllib.parse.urlsplit((etp_url or "").strip())
    if not u.netloc or not _ETP_PATH.search(u.path):
        return None
    scheme = "https" if u.scheme in ("wss", "https") else "http"
    return f"{scheme}://{u.netloc}/api/search/v2/query"


class Rest:
    """The two services, with the connection's credentials in a header."""

    def __init__(self, base, search, partition, token, token_type="Bearer", opener=None):
        self.base, self.search, self.partition = base, search, partition or ""
        self.headers = {"Authorization": f"{token_type} {token}", "data-partition-id": self.partition,
                        "Accept": "application/json", "Content-Type": "application/json"}
        self._open = opener or urllib.request.urlopen

    def call(self, method, url, body=None):
        """One HTTP call: the decoded JSON answer (None when empty), or
        OsduError with the status and the start of the server's words."""
        req = urllib.request.Request(url, method=method, headers=self.headers,
                                     data=json.dumps(body).encode("utf-8") if body is not None else None)
        try:
            with self._open(req, timeout=TIMEOUT) as r:
                text = r.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            words = exc.read().decode("utf-8", "replace")[:200] if exc.fp else ""
            raise OsduError(f"{exc.code} on {url.split('?')[0]}: {words or exc.reason}") from None
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise OsduError(f"{url.split('?')[0]}: {exc}") from None
        return json.loads(text) if text else None

    def get(self, path, **query):
        q = urllib.parse.urlencode({k: v for k, v in query.items() if v is not None})
        return self.call("GET", f"{self.base}{path}" + (f"?{q}" if q else ""))

    def query(self, body):
        return self.call("POST", self.search, body)


def dataspace_path(uri):
    """`eml:///dataspace('demo/Volve')` -> `demo/Volve` (an ETP URI as
    FESPP lists them, or a path already)."""
    m = re.match(r"^eml:///dataspace\('(.*)'\)$", (uri or "").strip())
    return m.group(1).replace("''", "'") if m else (uri or "").strip()


def dataspace_uri(path):
    """`demo/Volve` -> `eml:///dataspace('demo/Volve')`, quotes doubled."""
    return f"eml:///dataspace('{path.replace(chr(39), chr(39) * 2)}')"


def _custom(d, key):
    """A customData value of the facade: {"values": [x]}, [x] or a scalar,
    down to x."""
    v = (d.get("customData") or {}).get(key)
    if isinstance(v, dict):
        v = v.get("values", v)
    if isinstance(v, list):
        v = v[0] if v else None
    return v


def _flag(v):
    return str(v).strip().lower() in ("true", "1", "yes") if v is not None else False


_UNITS = {"b": 1, "kb": 1000, "mb": 1000 ** 2, "gb": 1000 ** 3, "tb": 1000 ** 4}
_SIZE = re.compile(r"^\s*([0-9]+(?:[.,][0-9]+)?)\s*([kmgt]?b)?\s*$", re.I)


def size_bytes(v):
    """The facade's size as bytes: a number, or the words it uses
    ("514 MB", "232 kB"); None when neither."""
    if v is None or v == "":
        return None
    m = _SIZE.match(str(v))
    if not m:
        return None
    number = float(m.group(1).replace(",", "."))
    return int(number * _UNITS[(m.group(2) or "b").lower()])


def entry(path, uri=None, facade=None):
    """One row of the explorer from the facade's record when there is one."""
    project, _, name = path.partition("/")
    row = {"uri": uri or dataspace_uri(path), "path": path, "project": project if name else "",
           "name": name or path, "last_write": None, "size": None, "locked": False, "read_only": False, "facts": None}
    if facade:
        row["last_write"] = facade.get("storeLastWrite") or facade.get("lastWrite")
        size = _custom(facade, "size")
        row["size"] = size_bytes(size)
        if size not in (None, "") and row["size"] is None:
            row["note"] = f"size not read: {size!r}"
        row["locked"] = _flag(_custom(facade, "locked"))
        row["read_only"] = _flag(_custom(facade, "read-only"))
    return row


def list_dataspaces(rest, etp_uris=()):
    """The explorer's rows: the facade's list (dates, sizes) merged with
    what ETP listed (uris), the ETP order first for what both hold."""
    facade = {}
    skip = 0
    while True:
        page = rest.get("/dataspaces", **{"$top": PAGE, "$skip": skip}) or []
        for d in page:
            if d.get("path"):
                facade[d["path"]] = d
        if len(page) < PAGE:
            break
        skip += PAGE
    rows, seen = [], set()
    for uri in etp_uris:
        path = dataspace_path(uri)
        if path in seen or not path or path == "eml:///":
            continue
        seen.add(path)
        rows.append(entry(path, uri, facade.get(path)))
    for path, d in facade.items():
        if path not in seen:
            rows.append(entry(path, d.get("uri"), d))
    return rows


def names_only(etp_uris):
    """The rows a server without the facade allows."""
    rows, seen = [], set()
    for uri in etp_uris:
        path = dataspace_path(uri)
        if path and path not in seen and path != "eml:///":
            seen.add(path)
            rows.append(entry(path, uri))
    return rows


def _short(type_name):
    return type_name.split(".")[-1].removeprefix("obj_")


def summarise(types):
    """The facts of a dataspace from the facade's type counts
    [{"name": "resqml20.obj_IjkGridRepresentation", "count": 2}, ...]."""
    counts = {_short(t.get("name", "")): int(t.get("count") or 0) for t in types or []}
    facts = {"objects": sum(counts.values())}
    for key, names in FACTS.items():
        facts[key] = sum(counts.get(n, 0) for n in names)
    return facts


def epsg_codes(obj):
    """Every EPSG code an object's JSON names (a CRS: its projected and
    vertical codes), in order, without repeats."""
    out = []

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k == "EpsgCode" and isinstance(v, (int, str)) and str(v).strip().isdigit():
                    code = int(v)
                    if code not in out:
                        out.append(code)
                else:
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(obj)
    return out


def dataspace_facts(rest, path):
    """The facts of one dataspace: the type counts (one call), then the
    EPSG codes of its CRS objects -- only the CRS types the counts name,
    two objects at most: a hosted facade can take seconds per call, so
    every call spared counts."""
    ds = urllib.parse.quote(path, safe="")
    types = rest.get(f"/dataspaces/{ds}/resources") or []
    facts = summarise(types)
    present = {t.get("name") for t in types if t.get("count")}
    codes, notes, looked = [], [], 0
    for crs_type in CRS_TYPES:
        if crs_type not in present or looked >= 2:
            continue
        try:
            crs_list = rest.get(f"/dataspaces/{ds}/resources/{crs_type}", **{"$top": 2}) or []
        except OsduError as exc:
            notes.append(f"{crs_type}: {exc}")
            continue
        for crs in crs_list:
            guid = (crs.get("uri") or "").rsplit("(", 1)[-1].rstrip(")")
            if not guid or looked >= 2:
                continue
            looked += 1
            try:
                obj = rest.get(f"/dataspaces/{ds}/resources/{crs_type}/{guid}", **{"$format": "json"})
            except OsduError as exc:
                notes.append(f"{guid}: {exc}")
                continue
            for code in epsg_codes(obj):
                if code not in codes:
                    codes.append(code)
    facts["epsg"] = codes
    facts["error"] = "; ".join(notes) or None
    return facts


_LUCENE_SPECIAL = re.compile(r'([+\-!(){}\[\]^"~*?:\\/]|&&|\|\|)')


_CRS_FIELD = "data.SpatialPoint.AsIngestedCoordinates.CoordinateReferenceSystemID"


def lucene_text(text, partition="opendes"):
    """A reader's words as a Search query: each word a prefix of the
    name, special characters escaped; a word of digits is also an EPSG
    code, matched exactly on the component's CRS id (the field is a
    keyword, matched whole: no wildcard inside it, the whole id quoted)."""
    words = [w for w in re.split(r"\s+", (text or "").strip()) if w]
    parts = []
    for w in words:
        name = f"data.Name:{_LUCENE_SPECIAL.sub(r'\\\1', w)}*"
        if w.isdigit() and 4 <= len(w) <= 5:
            crs = " OR ".join(f'{_CRS_FIELD}:"{partition}:reference-data--CoordinateReferenceSystem:{kind}:EPSG::{w}:"'
                              for kind in ("Projected", "Vertical", "Geographic2D", "Bound"))
            parts.append(f"({name} OR {crs})")
        else:
            parts.append(name)
    return " AND ".join(parts)


_DDMS_URI = re.compile(r"dataspace\('((?:[^']|'')*)'\)")


def component_dataspace(data):
    """The dataspace a catalogue component lives in: the RDDMS manifest
    writes the object's ETP uri in data.DDMSDatasets
    ("eml://reservoir-ddms1/dataspace('demo/volve_horizons')/resqml20.obj_HorizonInterpretation(...)"),
    older records name the dataspace's dataset in data.Datasets
    ("opendes:dataset--ETPDataspace:demo-teapot:", the path's first "/"
    written "-")."""
    for d in data.get("DDMSDatasets") or []:
        m = _DDMS_URI.search(str(d))
        if m:
            return m.group(1).replace("''", "'")
    for d in data.get("Datasets") or []:
        m = re.search(r"dataset--ETPDataspace:([^:]+)", str(d))
        if m:
            return m.group(1).replace("-", "/", 1)
    return None


def catalogue_search(rest, text, limit=20):
    """The catalogue's dataspaces and components whose name holds the
    words: what a locked, published dataspace is known by."""
    q = lucene_text(text, rest.partition or "opendes")
    if not q:
        return {"total": 0, "dataspaces": [], "components": []}
    ds = rest.query({"kind": "*:*:dataset--ETPDataspace:*", "query": q, "limit": limit,
                     "returnedFields": ["id", "data.Name", "data.DatasetProperties.URI"]}) or {}
    wpc = rest.query({"kind": "*:*:work-product-component--*:*", "query": q, "limit": max(limit, 100),
                      "returnedFields": ["id", "kind", "data.Name", "data.DDMSDatasets", "data.Datasets"]}) or {}
    dataspaces = []
    for r in ds.get("results", []):
        data = r.get("data") or {}
        uri = data.get("DatasetProperties.URI") or (data.get("DatasetProperties") or {}).get("URI")
        name = data.get("Name") or dataspace_path(uri or "")
        if uri:
            dataspaces.append({"name": name, "uri": uri})
    components = []
    for r in wpc.get("results", []):
        data = r.get("data") or {}
        kind = (r.get("kind") or "").split("--")[-1].split(":")[0]
        components.append({"name": data.get("Name") or r.get("id"), "kind": kind, "dataspace": component_dataspace(data)})
    # the same component published several times (versions, reruns) is
    # one entry with its count, which keeps the list short
    merged = {}
    for c in components:
        key = (c["name"], c["kind"], c["dataspace"])
        if key in merged:
            merged[key]["count"] += 1
        else:
            merged[key] = dict(c, count=1)
    components = list(merged.values())
    # the dataspaces the components live in, most components first, each
    # with what it holds: the answer to "which dataspaces have a Hugin
    # horizon / are in 23031" is a short list of dataspaces, not the
    # components one by one
    known = {d["uri"]: d for d in dataspaces}
    by_dataspace = {}
    for c in components:
        if c["dataspace"]:
            by_dataspace.setdefault(c["dataspace"], []).append(c)
    for path, held in sorted(by_dataspace.items(), key=lambda x: -sum(c["count"] for c in x[1])):
        uri = dataspace_uri(path)
        kinds = {}
        for c in held:
            kinds[c["kind"]] = kinds.get(c["kind"], 0) + c["count"]
        summary = {"components": sum(c["count"] for c in held),
                   "kinds": [{"kind": k, "count": n} for k, n in sorted(kinds.items(), key=lambda x: -x[1])],
                   "names": sorted({c["name"] for c in held})[:8]}
        if uri in known:
            known[uri].update(summary)
        else:
            dataspaces.append({"name": path, "uri": uri, **summary})
    return {"total": int(ds.get("totalCount") or 0) + int(wpc.get("totalCount") or 0),
            "dataspaces": dataspaces, "components": components[:limit]}


# ------------------------------------------------------------ the inventory and the search
INVENTORY_MAX = 20000   # objects listed per dataspace: beyond, the names stop (the facts stay)
_OBJECT_TYPE = re.compile(r"/(?:witsml|resqml|prodml|eml)\d+\.(?:obj_)?(\w+)\(")
_ACCENTS = {"é": "e", "è": "e", "ê": "e", "à": "a", "ç": "c", "î": "i", "ô": "o", "û": "u", "ù": "u"}


def _fold(s):
    """Lower case with the common accents folded: a search ignores both."""
    s = (s or "").lower()
    return "".join(_ACCENTS.get(c, c) for c in s)


def dataspace_inventory(rest, path):
    """Every object of a dataspace as (type, name), read off the facade's
    flat resource list (one call per PAGE objects, at most INVENTORY_MAX
    in all): the names a search finds a well, a property or a horizon by."""
    ds = urllib.parse.quote(path, safe="")
    out, skip = [], 0
    while len(out) < INVENTORY_MAX:
        page = rest.get(f"/dataspaces/{ds}/resources/all", **{"$top": PAGE, "$skip": skip}) or []
        for r in page:
            m = _OBJECT_TYPE.search(r.get("uri") or "")
            out.append((m.group(1) if m else "", r.get("name") or ""))
        if len(page) < PAGE:
            break
        skip += PAGE
    return out


# the words of a question that ask for a kind of content, and the fact they read
_FACET_WORDS = {
    "wells": ("wells", "well", "puits", "wellbore", "wellbores", "trajectoire", "trajectoires"),
    "grids": ("grids", "grid", "grille", "grilles", "maillage"),
    "properties": ("properties", "property", "props", "propriete", "proprietes"),
    "surfaces": ("surfaces", "surface"),
    "horizons": ("horizons", "horizon"),
    "faults": ("faults", "fault", "faille", "failles"),
}
_FACET_OF = {w: facet for facet, words in _FACET_WORDS.items() for w in words}
# the words that ask for a lock state, and the row field they read
_LOCK_WORDS = {"locked": "locked", "lock": "locked", "verrouille": "locked", "verrou": "locked",
               "readonly": "read_only", "read-only": "read_only", "lecture-seule": "read_only"}
# the dataspaces written since this process last listed the server, or new
# since then (`changed` on the row, set by boot from its memory of the server)
_CHANGED_WORDS = frozenset(("modified", "changed", "updated", "new", "recent", "modifie", "modifies", "modifiee",
                            "modifiees", "change", "changes", "nouveau", "nouveaux", "nouvelle", "nouvelles",
                            "recent", "recents", "recente", "recentes"))
_TERM = re.compile(r"^(epsg|type|since|project|name|kind):(.+)$")


def parse_query(text):
    """The terms of a search box: plain words, and the typed filters
    epsg:23031, type:ijkgrid, since:YYYY-MM, project:demo, name:volve."""
    terms = []
    for raw in (text or "").split():
        m = _TERM.match(raw.lower())
        if m:
            terms.append((m.group(1), _fold(m.group(2))))
        else:
            terms.append(("word", _fold(raw)))
    return terms


# objects that carry a name but say nothing of the data: the HDF file
# reference, the provenance, the dictionaries
# the objects a search never names: the file's plumbing. A PropertyKind is
# NOT plumbing: its title is a kind the dataspace defines ("porosity"), the
# one fact about its properties the resource list carries
_PLUMBING = {"EpcExternalPartReference", "Activity", "ActivityTemplate", "PropertySet",
             "PropertyKindDictionary", "TimeSeries", "MdDatum"}
# the property types, short and qualified (RESQML 2.0.1 "obj_" and 2.2 without)
PROPERTY_TYPES = ("ContinuousProperty", "DiscreteProperty", "CategoricalProperty", "PointsProperty",
                  "CommentProperty")
# what the ETP inventory of a dataspace fetches to read the KINDS of its
# properties: the properties, and the PropertyKind objects a local kind
# points at (a few hundred kilobytes of XML, never the grids)
KIND_TYPES = tuple(f"resqml20.obj_{t}" for t in PROPERTY_TYPES) + ("resqml20.obj_PropertyKind",) \
    + tuple(f"resqml22.{t}" for t in PROPERTY_TYPES) + ("eml23.PropertyKind",)


def short_type(qualified):
    """"ContinuousProperty" for "resqml20.obj_ContinuousProperty" or
    "resqml22.ContinuousProperty"; a short name stays as it is."""
    t = (qualified or "").rsplit(".", 1)[-1]
    return t[4:] if t.startswith("obj_") else t


def parse_inventory(lines):
    """The ETP inventory of a dataspace as the plugin answers it
    (`repo_query.inventory_lines`): {"info": {key: value}, "error": None |
    words, "objects": [{uri, type (qualified), uuid, kind, title}]}. The
    first line is "#info|key=value|..." or "#error|words"; each other line
    "uri|type|uuid|kind|title", the title last (it may carry a "|"). An
    empty answer is an error too: the plugin always says something."""
    out = {"info": {}, "error": None, "objects": []}
    if not lines:
        out["error"] = "no answer from the plugin"
        return out
    for line in lines:
        line = str(line or "")
        if line.startswith("#error|"):
            out["error"] = line[len("#error|"):] or "unknown failure"
            continue
        if line.startswith("#info|"):
            for part in line[len("#info|"):].split("|"):
                key, sep, value = part.partition("=")
                if sep and key:
                    out["info"][key] = value
            continue
        if line.startswith("#"):
            continue
        fields = line.split("|", 4)
        if len(fields) < 5:
            continue
        uri, qualified, uuid, kind, title = fields
        out["objects"].append({"uri": uri, "type": qualified, "uuid": uuid, "kind": kind, "title": title})
    return out


def kinds_summary(objects):
    """What the inventory says of a dataspace's properties: {"total": the
    properties, "kinds": [{"kind", "count"}] (the most frequent first, then
    by name), "unknown": the properties whose kind could not be read}."""
    counts, total, unknown = {}, 0, 0
    for o in objects or ():
        if short_type(o.get("type")) not in PROPERTY_TYPES:
            continue
        total += 1
        kind = (o.get("kind") or "").strip()
        if not kind:
            unknown += 1
            continue
        counts[kind] = counts.get(kind, 0) + 1
    kinds = sorted(({"kind": k, "count": c} for k, c in counts.items()), key=lambda e: (-e["count"], _fold(e["kind"])))
    return {"total": total, "kinds": kinds, "unknown": unknown}


def kind_rows(objects):
    """The inventory's properties as the search box reads them: (short
    type, title, kind) per property with a kind."""
    return [(short_type(o.get("type")), o.get("title") or "", o.get("kind") or "")
            for o in objects or () if short_type(o.get("type")) in PROPERTY_TYPES and o.get("kind")]


def merge_inventories(rest_rows, kinds):
    """One inventory of a dataspace for the search: the REST facade's
    (type, name) rows, the properties among them replaced by the ETP
    inventory's (type, name, kind) rows once those are known — the same
    property must not be counted twice."""
    if not kinds:
        return list(rest_rows or ())
    return [r for r in (rest_rows or ()) if r[0] not in PROPERTY_TYPES] + list(kinds)


def _rows3(inventory):
    """Every inventory row as (type, name, kind): the facade's rows carry
    no kind."""
    return [(r[0], r[1], r[2] if len(r) > 2 else "") for r in (inventory or ()) if len(r) >= 2]


def _match_term(kind, value, row, inventory):
    """(score, why, objects) of one term against one dataspace, or None
    when the term does not hold there."""
    facts = row.get("facts") or {}
    rows3 = [(t, n, k) for t, n, k in _rows3(inventory) if t not in _PLUMBING]
    inventory = [(t, n) for t, n, _k in rows3]
    path, project, name = _fold(row.get("path")), _fold(row.get("project")), _fold(row.get("name"))
    epsg = [str(c) for c in (facts.get("epsg") or [])]
    if kind == "epsg":
        return (8.0, f"EPSG {value}", []) if value in epsg else None
    if kind == "kind":
        # the kind of a property, as the ETP inventory read it
        hits = [(t, n) for t, n, k in rows3 if k and value in _fold(k)]
        if not hits:
            return None
        first = next(k for t, n, k in rows3 if k and value in _fold(k))
        return (6.0 + min(len(hits), 20) * 0.1, f"{len(hits)} {_plural(len(hits), 'property', 'properties')} of kind {first}",
                hits[:5])
    if kind == "since":
        return (1.0, f"modified since {value}", []) if (row.get("last_write") or "") >= value else None
    if kind == "project":
        return (6.0, f"project {row.get('project')}", []) if value in project else None
    if kind == "word" and value in _LOCK_WORDS:
        # the lock the list already knows: "locked" finds the locked ones,
        # "readonly" / "lecture seule" the read-only ones
        if _LOCK_WORDS[value] == "locked" and row.get("locked"):
            return (4.0, "locked", [])
        if _LOCK_WORDS[value] == "read_only" and row.get("read_only"):
            return (4.0, "read-only", [])
        return None
    if kind == "word" and value in _CHANGED_WORDS:
        # "modified", "new", "changé": the dataspaces the store wrote since
        # this process last listed the server (boot keeps the facts of the
        # others across connections), or new since then
        return (4.0, "changed since the last visit", []) if row.get("changed") else None
    if kind == "name":
        return (10.0, f"named {row.get('name')}", []) if value in name else None
    if kind == "type":
        hits = [(t, n) for t, n in inventory if value in _fold(t)]
        if not hits:
            return None
        return (4.0 + min(len(hits), 20) * 0.1, f"{len(hits)} {hits[0][0]}", hits[:5])
    # a plain word: the dataspace's name first, then a code, a facet, a
    # type, the names of its objects
    score, why, objects = 0.0, [], []
    if value in name:
        score, why = 10.0, [f"named {row.get('name')}"]
    elif value in path:
        score, why = 6.0, [f"in {row.get('path')}"]
    if value.isdigit() and value in epsg:
        score += 8.0
        why.append(f"EPSG {value}")
    facet = _FACET_OF.get(value)
    if facet and facts.get(facet):
        score += 3.0
        why.append(f"{facts[facet]} {facet}")
    if len(value) >= 3:
        type_hits = [(t, n) for t, n in inventory if value in _fold(t)]
        if type_hits:
            score += 4.0 + min(len(type_hits), 20) * 0.1
            why.append(f"{len(type_hits)} {type_hits[0][0]}")
            objects += type_hits[:3]
    if len(value) >= 2:
        name_hits = [(t, n) for t, n in inventory if value in _fold(n)]
        if name_hits:
            exact = [h for h in name_hits if _fold(h[1]) == value]
            score += (7.0 if exact else 5.0) + min(len(name_hits), 10) * 0.5
            first = (exact or name_hits)[0]
            why.append(f"{_kind_word(first[0])} {first[1]}" + (f" (+{len(name_hits) - 1})" if len(name_hits) > 1 else ""))
            objects += (exact + [h for h in name_hits if h not in exact])[:5]
    if len(value) >= 3:
        # the kinds the ETP inventory read: "porosity" finds the properties
        # OF that kind whatever they are called (PORO, PHIE, Phi_eff)
        kind_hits = [(t, n) for t, n, k in rows3 if k and value in _fold(k) and (t, n) not in objects]
        if kind_hits:
            score += 6.0 + min(len(kind_hits), 20) * 0.1
            first = next(k for t, n, k in rows3 if k and value in _fold(k))
            why.append(f"{len(kind_hits)} {_plural(len(kind_hits), 'property', 'properties')} of kind {first}")
            objects += kind_hits[:3]
    return (score, " · ".join(why), objects) if score else None


def _plural(n, one, many):
    return one if n == 1 else many


def _kind_word(type_name):
    """A short word for an object type: 'property' for ContinuousProperty..."""
    t = type_name or "object"
    if t == "PropertyKind":
        return "kind"
    for word, hint in (("property", "Property"), ("well", "Wellbore"), ("horizon", "Horizon"), ("fault", "Fault"),
                       ("grid", "Grid"), ("surface", "TriangulatedSet"), ("CRS", "Crs")):
        if hint.lower() in t.lower():
            return word
    return t


def find(text, rows, inventories, limit=100):
    """The dataspaces a search box text designates, ranked: every term
    must hold (AND); the score adds what each term found, and says why."""
    terms = parse_query(text)
    if not terms:
        return {"text": text or "", "status": "done", "total": 0, "results": []}
    results = []
    for row in rows:
        inventory = inventories.get(row.get("path")) or []
        score, whys, objects = 0.0, [], []
        for kind, value in terms:
            hit = _match_term(kind, value, row, inventory)
            if hit is None:
                break
            score += hit[0]
            whys.append(hit[1])
            objects += [o for o in hit[2] if o not in objects]
        else:
            results.append({"uri": row.get("uri"), "path": row.get("path"), "score": round(score, 1),
                            "why": whys[:4], "objects": [{"type": t, "name": n} for t, n in objects[:5]],
                            "_lw": row.get("last_write") or ""})
    # the best score first; at equal score the most recently written
    results.sort(key=lambda r: r["_lw"], reverse=True)
    results.sort(key=lambda r: -r["score"])
    for r in results:
        r.pop("_lw", None)
    return {"text": text or "", "status": "done", "total": len(results), "results": results[:limit]}


def merge_catalogue(found, catalogue, rows):
    """The search box's results completed by the OSDU catalogue: a
    dataspace the catalogue also knows for these words says it is
    published (and how many of its components match); a dataspace only
    the catalogue knows comes last. The catalogue never removes a result:
    it sees only the published dataspaces, and needs every word on one
    component."""
    out = dict(found)
    results = [dict(r) for r in found.get("results") or []]
    by_path = {r["path"]: r for r in results}
    listed = {r.get("path") for r in rows}
    for d in (catalogue or {}).get("dataspaces") or []:
        path = dataspace_path(d.get("uri") or d.get("name") or "")
        n = d.get("components")
        reason = f"published: {n} components" if n else "published"
        if path in by_path:
            hit = by_path[path]
            hit["why"] = list(hit.get("why") or []) + [reason]
            hit["published"] = True
        else:
            hit = {"uri": d.get("uri") or dataspace_uri(path), "path": path, "score": 1.0, "published": True,
                   "why": [reason if path in listed else reason + " (not listed by the server)"], "objects": []}
            results.append(hit)
            by_path[path] = hit
    out["results"] = results
    out["total"] = len(results)
    return out
