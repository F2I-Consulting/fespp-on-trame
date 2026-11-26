"""The page's query as a session document (S1, 21/10): the door an
application hôte opens FesTrame by — pure, no trame.

    ?epc=<name>[&epc=…]        an EPC under the server's open directory
    ?etp=<url>&dataspace=<ds>  an OSDU / ETP store, its dataspaces (repeat
                               `dataspace` for several) and `&partition=`
                               its data partition; the token is the
                               reader's to type, never in a URL
    &uuid=<uuid>[&uuid=…]      what to read, shown in the first 3D view
    ?state=<url>               a whole document fetched from there

An EPC name stays under the open directory: a path with `..`, an absolute
one or a drive letter is refused, said in the report."""
import os
import posixpath
from urllib.parse import parse_qs

OPEN_DIR_VAR = "FESPP_OPEN_DIR"
DEFAULT_OPEN_DIR = "/deploy/data"


class QueryError(ValueError):
    """A query that opens nothing; the message is the reader's."""


def open_dir():
    return os.environ.get(OPEN_DIR_VAR) or DEFAULT_OPEN_DIR


def epc_path(name, root=None):
    """The server path of an EPC the query names, under `root` (the open
    directory) — or a QueryError when the name leaves it."""
    root = root or open_dir()
    clean = (name or "").replace("\\", "/").strip()
    if not clean or clean.startswith("/") or ":" in clean or ".." in clean.split("/"):
        raise QueryError(f"An EPC is named by its path under the open directory, not {name!r}.")
    norm = posixpath.normpath(clean)
    if norm.startswith("..") or norm == ".":
        raise QueryError(f"An EPC is named by its path under the open directory, not {name!r}.")
    return posixpath.join(root, norm)


def server_path(name, root=None):
    """The server path of an EPC a document names: a relative name under
    the open directory (`epc_path`), or an absolute path already under it
    (what the page's query makes). Any other path is refused: a document
    comes from the network, the directory is the server's choice."""
    root = (root or open_dir()).replace("\\", "/").rstrip("/")
    clean = (name or "").replace("\\", "/").strip()
    if clean.startswith("/"):
        full = posixpath.normpath(clean)
        if full != root and not full.startswith(root + "/"):
            raise QueryError(f"An EPC is named by its path under the open directory, not {name!r}.")
        return full
    return epc_path(clean, root)


def parse(search):
    """The query's parameters: {name: [values]} of `?a=1&b=2&b=3`."""
    search = (search or "").lstrip("?")
    return {k: [v for v in vs if v] for k, vs in parse_qs(search, keep_blank_values=False).items()}


def document_from_query(search, root=None):
    """The partial document the query asks for, or None when it asks for
    nothing (a plain page). `state=` is left to the caller (a fetch): the
    document says it under "state_url"."""
    q = parse(search)
    doc = {}
    if q.get("state"):
        return {"state_url": q["state"][0]}
    epcs = q.get("epc") or []
    etp = (q.get("etp") or [None])[0]
    dataspaces = q.get("dataspace") or []
    uuids = q.get("uuid") or []
    if not epcs and not etp and not uuids:
        return None
    sources = {}
    if epcs:
        sources["files"] = [{"name": posixpath.basename(e), "path": epc_path(e, root)} for e in epcs]
    if etp:
        if not dataspaces:
            raise QueryError("An ETP store is opened with at least one dataspace (&dataspace=…).")
        sources["etp"] = {"url": etp, "partition": (q.get("partition") or [""])[0],
                          "dataspaces": dataspaces}
    if sources:
        doc["sources"] = sources
    if uuids:
        paths = ["uuid:" + u for u in uuids]
        doc["session"] = {"selected_paths": paths}
        doc["views"] = [{"kind": "render", "eyes": paths}]
    return doc
