"""The `.fespp.json` session file — pure: no trame, no ParaView.

A session file holds the STATE of the application, never the data: the data
(EPC + h5 files, or an OSDU/ETP connection) is loaded again, and the state is
applied over it. Every piece of the state names objects by their ASSEMBLY
PATH, which FESPP builds on the RESQML uuids — the same objects reloaded give
the same paths, whatever the file is called or the order it is read in.

A stable path does not mean unchanged data: an object kept under its uuid
may have been edited, or an export may have re-created it under a new uuid.
So the file also keeps, for every object the state names, its uuid, type,
title and the fingerprint of its RESQML Citation (Creation, LastUpdate,
VersionString, Format — LastUpdate is optional and often absent), and
`compare_objects` says what changed.

Layout of the document (schema 1)::

    {"schema": 1,
     "meta":    {"app", "paraview", "saved", "note"},
     "sources": {"files": [{"name", "size_mb"}], "etp": null | {...}},
     "session": {"selected_paths": [...]},   (a `z_scale` here: every 3D view's)
     "objects": {path: {"uuid", "type", "title", "creation",
                        "last_update", "version", "format"}},
     "layout":  <dockview toJSON()> | null,
     "views":   [{"id", "kind", "title", ...one paragraph per view...}]}

A document written by hand (the API's) places a view with `"place":
"right" | "below"` on its paragraph: the view opens split from the one
before it in the document (a file's views are placed by its `layout`).
"""
import json
import re

SCHEMA = 1
SUFFIX = ".fespp.json"


class SessionFileError(ValueError):
    """A file that cannot be restored; the message is the reader's."""


# ------------------------------------------------------------ read / write
def dumps(doc):
    """The text of a session file: indented JSON, non-ASCII kept as is."""
    return json.dumps(doc, indent=2, ensure_ascii=False)


def loads(text):
    """The document of a session file, validated and migrated to `SCHEMA`.
    Raises `SessionFileError` with what is wrong, in the reader's words."""
    try:
        doc = json.loads(text or "")
    except (TypeError, ValueError) as exc:
        raise SessionFileError(f"This is not a session file (not JSON: {exc}).") from None
    return document(doc, partial=False)


# the groups a document may hold, and what each one is
GROUPS = (("sources", dict), ("session", dict), ("objects", dict),
          ("layout", dict), ("views", list))


def document(obj, partial=True):
    """A session document as the application applies it.

    `partial=True` is the API's document (the PO, 21/10): every group of
    GROUPS may be absent — an absent group leaves the session as it is, a
    present and empty one erases what it covers — `reset` (false) asks
    for a session emptied first, and `schema` defaults to SCHEMA. The
    document says `partial` so that the host knows which rule to apply.
    `partial=False` is a file: `schema` and `views` are required and the
    absent groups take their defaults, as `loads` always read them.
    Raises `SessionFileError` with what is wrong."""
    if not isinstance(obj, dict):
        raise SessionFileError("A session document is a JSON object.")
    if not partial and ("schema" not in obj or "views" not in obj):
        raise SessionFileError("This JSON file is not a fespp-on-trame session"
                               " (no schema or views).")
    try:
        schema = int(obj.get("schema", SCHEMA))
    except (TypeError, ValueError):
        raise SessionFileError(f"Unknown session format {obj.get('schema')!r}.") from None
    if schema > SCHEMA:
        raise SessionFileError(
            f"This session was saved by a newer version of the application"
            f" (format {schema}, this one reads up to {SCHEMA}).")
    for group, kind in GROUPS:
        value = obj.get(group)
        if group in obj and value is not None and not isinstance(value, kind):
            what = "a list" if kind is list else "an object"
            raise SessionFileError(f"The document's {group} is not {what}.")
    doc = _migrate(obj, schema) if not partial else dict(obj, schema=SCHEMA)
    if not partial and not isinstance(doc.get("views"), list):
        raise SessionFileError("The session's views are not a list.")
    for v in doc.get("views") or ():
        if isinstance(v, dict) and v.get("place") not in (None, "right", "below"):
            raise SessionFileError(f"A view's place is right or below, not {v['place']!r}.")
    doc["partial"] = bool(partial)
    doc["reset"] = bool(obj.get("reset", False))
    # an ETP dataspace is loaded by its URI; a document written by a person
    # or a host names it (demo/Volve): one form inside, the one the store
    # answers and the loaded list records
    etp = (doc.get("sources") or {}).get("etp")
    if isinstance(etp, dict) and etp.get("dataspaces"):
        doc["sources"] = dict(doc["sources"], etp=dict(
            etp, dataspaces=[etp_dataspace_uri(d) for d in etp["dataspaces"]]))
    return doc


def etp_dataspace_uri(name):
    """`eml:///dataspace('demo/Volve')` for `demo/Volve`; a URI is kept."""
    name = str(name or "").strip()
    return name if not name or name.lower().startswith("eml:///") else f"eml:///dataspace('{name}')"


UUID_PREFIX = "uuid:"


def resolve_uuids(doc, lookup):
    """The document with every `uuid:<uuid>` string — a path's place, in a
    list, a value or a key — replaced by the path `lookup(uuid)` gives for
    it in the loaded data (an application hôte names objects by uuid, not
    by the assembly paths it cannot know). Returns (document, the uuids
    `lookup` did not find, left as they were)."""
    missing = []

    def one(value):
        if isinstance(value, str) and value.lstrip().lower().startswith(UUID_PREFIX):
            # typed by a person as often as by a program: spaces and braces
            # around the uuid are not part of it
            uuid = value.lstrip()[len(UUID_PREFIX):].strip().strip("{}").strip()
            path = lookup(uuid)
            if path:
                return path
            if uuid not in missing:
                missing.append(uuid)
            return value
        if isinstance(value, list):
            return [one(v) for v in value]
        if isinstance(value, dict):
            return {one(k): one(v) for k, v in value.items()}
        return value

    return one(doc), missing


def _migrate(doc, schema):
    """Older formats brought up to `SCHEMA`, one step at a time. Schema 1 is
    the first format, so this only fills the optional sections with their
    defaults."""
    doc = dict(doc)
    doc["schema"] = SCHEMA
    doc.setdefault("meta", {})
    doc.setdefault("sources", {})
    doc.setdefault("session", {})
    doc.setdefault("objects", {})
    doc.setdefault("layout", None)
    return doc


# ------------------------------------------------------------ the data
def file_states(expected, loaded):
    """The expected files against what the session has read: one row each,
    `state` "loaded" / "different" / "missing". Recognised by NAME (a file
    renamed is not the same file for the reader either); a size that moved
    by more than the rounding says it is not the same content."""
    have = {f.get("name"): f for f in (loaded or ()) if f.get("name")}
    rows = []
    for f in expected or ():
        name = f.get("name") or ""
        row = {"name": name, "size_mb": f.get("size_mb"), "state": "missing", "why": ""}
        got = have.get(name)
        if got is not None:
            row["state"] = "loaded"
            a, b = f.get("size_mb"), got.get("size_mb")
            if a is not None and b is not None and abs(float(a) - float(b)) > 0.05:
                row["state"] = "different"
                row["why"] = (f"not the same size: {float(a):.1f} MB when saved,"
                              f" {float(b):.1f} MB now")
            elif got.get("failed"):
                row["state"] = "different"
                row["why"] = "the reader could not read it"
        rows.append(row)
    return rows


_CITATION = {"creation": "Creation", "last_update": "LastUpdate",
             "version": "VersionString", "format": "Format",
             "title": "Title", "originator": "Originator"}


def citation_of(xml):
    """The Citation fields of one object's XML — `{creation, last_update,
    version, format, title, originator}`, "" for an absent one. Namespace
    prefixes vary (eml:, eml20:, eml23:), the local names do not."""
    out = {}
    for key, tag in _CITATION.items():
        m = re.search(r"<(?:\w+:)?" + tag + r"\b[^>]*>([^<]*)</(?:\w+:)?" + tag + ">",
                      xml or "")
        out[key] = m.group(1).strip() if m else ""
    return out


_FINGERPRINT = ("creation", "last_update", "version", "format")


def compare_objects(saved, current, candidates=None):
    """What changed since the save, object by object.

    `saved`: the file's ``objects`` — ``{path: {uuid, type, title, creation,
    last_update, version, format}}``. `current`: the same shape for the
    objects found now (a path absent from it is absent from the data).
    `candidates(type, title)`: the paths of objects of that type and title
    found now — a re-export changes the uuid, so the path, but rarely both.

    Returns ``[{"path", "level", "text", "replacement"}]`` — "ok" rows are
    left out: nothing to say about an object that did not change."""
    findings = []
    for path, was in (saved or {}).items():
        title = was.get("title") or path.rsplit("/", 1)[-1]
        now = (current or {}).get(path)
        if now is None:
            alt = [p for p in (candidates(was.get("type"), was.get("title"))
                               if candidates else ()) if p != path]
            if alt:
                findings.append({
                    "path": path, "level": "warn", "replacement": alt[0],
                    "text": f"{title}: not in the data any more; an object of the"
                            f" same type and title is (another uuid — re-exported?)."})
            else:
                findings.append({"path": path, "level": "error", "replacement": "",
                                 "text": f"{title}: not in the data any more — skipped."})
            continue
        moved = [k for k in _FINGERPRINT if (was.get(k) or "") != (now.get(k) or "")]
        if not moved:
            continue
        when = now.get("last_update") or now.get("creation") or "?"
        older = (was.get("creation") and now.get("creation")
                 and now["creation"] < was["creation"])
        findings.append({
            "path": path, "level": "warn", "replacement": "",
            "text": (f"{title}: OLDER than when the session was saved"
                     f" (created {now.get('creation')}) — probably not the same data."
                     if older else
                     f"{title}: changed since the session was saved"
                     f" ({', '.join(moved)}; now {when})."),
        })
    return findings


def keep_known(paths, known):
    """`(kept, dropped)` — the saved paths the data still has, and the rest.
    A derived property (``derived://``) is the calculator's, not the data's:
    kept as is."""
    kept, dropped = [], []
    for p in paths or ():
        (kept if (p in known or str(p).startswith("derived://")) else dropped).append(p)
    return kept, dropped


def etp_state(saved, connected, loaded):
    """The OSDU / ETP part of a session being reopened: `saved` is the
    file's ``sources.etp`` (url, partition, dataspaces — never a token),
    `connected` / `loaded` what the server holds now. Returns
    ``(status, ready, missing)``: what the door shows, whether the ETP part
    is ready, the dataspaces still to load."""
    if not saved:
        return None, True, []
    loaded = list(loaded or ())
    wanted = list(saved.get("dataspaces") or ())
    missing = [d for d in wanted if d not in loaded]
    status = {"url": saved.get("url") or "", "partition": saved.get("partition") or "",
              "dataspaces": wanted, "connected": bool(connected),
              "loaded": [d for d in wanted if d in loaded]}
    return status, bool(connected) and not missing, missing


# ------------------------------------------------------------ the views
def remap_ids(value, mapping):
    """A copy of `value` (the dockview layout, a view paragraph) with every
    panel id of the save renamed to the id the new session gave it — keys
    and string values alike, all at once (an old "view_2" becoming "view_1"
    while an old "view_1" becomes "view_3" never collides)."""
    if isinstance(value, dict):
        return {mapping.get(k, k) if isinstance(k, str) else k: remap_ids(v, mapping)
                for k, v in value.items()}
    if isinstance(value, list):
        return [remap_ids(v, mapping) for v in value]
    if isinstance(value, str):
        return mapping.get(value, value)
    return value


def panel_mapping(mapping):
    """`mapping` (saved panel id -> new id) extended to the TEMPLATE names
    dockview keeps for each panel (`<id>_template`, in the layout's
    params): renamed ids with their old templates would show another
    panel's content, or nothing."""
    out = dict(mapping or {})
    for old, new in (mapping or {}).items():
        out[f"{old}_template"] = f"{new}_template"
    return out


def layout_ids(layout):
    """The panel ids a dockview layout names (`toJSON().panels`)."""
    try:
        return list(((layout or {}).get("panels") or {}).keys())
    except AttributeError:
        return []
