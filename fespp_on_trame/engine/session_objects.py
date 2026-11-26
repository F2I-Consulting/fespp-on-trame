"""session_objects — the rules of the native Objects and Sources routes
(engine/io/session_endpoint, the pool's REST front): what a session reads
and what a 3D view shows, said by uuid, without a session document.

Pure: the paths, the views' eyes and the tree's answers come in as
arguments, so the rules are tested without ParaView. The gestures that
apply them are app/features/session_api's controllers."""

UUID_PREFIX = "uuid:"


class ObjectsError(ValueError):
    """A request the routes refuse (400), in words for its sender."""


def uuids_of(body):
    """The uuids a request names: `{"uuids": [...]}`, each one as typed by a
    person or a program (`uuid:` before it, braces or spaces around it),
    once each, in their order."""
    if not isinstance(body, dict) or not isinstance(body.get("uuids"), list):
        raise ObjectsError('A JSON object {"uuids": ["<uuid>", …]} is expected.')
    out = []
    for value in body["uuids"]:
        if not isinstance(value, str):
            raise ObjectsError(f"A uuid is a string, not {value!r}.")
        uuid = value.strip()
        if uuid.lower().startswith(UUID_PREFIX):
            uuid = uuid[len(UUID_PREFIX):]
        uuid = uuid.strip().strip("{}").strip().lower()
        if not uuid:
            raise ObjectsError("An empty uuid.")
        if uuid not in out:
            out.append(uuid)
    return out


def flag_of(body, name, default=True):
    """A boolean of the request (`show`), its default when absent."""
    value = (body or {}).get(name, default) if isinstance(body, dict) else default
    if not isinstance(value, bool):
        raise ObjectsError(f'"{name}" is true or false, not {value!r}.')
    return value


def added(want, selected, eyes, show=True):
    """(what is read, what the view shows) once `want` is added: what was
    read stays read, what the view showed stays shown."""
    read = list(selected) + [p for p in want if p not in selected]
    shown = list(eyes) + ([p for p in want if p not in eyes] if show else [])
    return read, shown


def replaced(want, show=True):
    """(what is read, what the view shows) when `want` is the whole of it."""
    return list(want), (list(want) if show else [])


def removed(gone, selected, eyes_by_view):
    """(what is read, {view: its eyes}) once `gone` is no longer read: no
    view keeps an eye on what is not read."""
    gone = set(gone)
    read = [p for p in selected if p not in gone]
    keep = set(read)
    return read, {vid: [p for p in eyes if p in keep] for vid, eyes in eyes_by_view.items()}


def first_render_view(view_ids, kind_of, asked=None):
    """The 3D view a request speaks of: the one it names (`?view=`), else
    the first 3D view of the session, else None (a session no browser has
    attached to yet has no view: a show opens one)."""
    renders = [v for v in view_ids if kind_of(v) == "render"]
    if asked:
        if asked not in renders:
            raise ObjectsError(f"No 3D view {asked!r}: the 3D views are {', '.join(renders) or 'none'}.")
        return asked
    return renders[0] if renders else None


def object_root(path, uuid_of):
    """The row that names the object a leaf stands for. FESPP's tree draws a
    representation as a leaf (SolidColor) inside folders that carry its uuid
    (`_gridfolder_<uuid>/_propsfolder_<uuid>/_<uuid>`): the topmost of them
    bears the object's title. `uuid_of(segment)` reads a segment's uuid."""
    parts = str(path).split("/")
    uuid = uuid_of(parts[-1])
    top = len(parts)
    while uuid and top > 1 and uuid_of(parts[top - 2]) == uuid:
        top -= 1
    return "/".join(parts[:top])


def rows(selected, eyes, describe, loaded=None):
    """One row per object read: {uuid, type, title, shown}, and `loaded`
    (its data in the session, not only asked for) when the paths loaded are
    given. `describe(path)` gives (uuid, type, title) from the tree; a
    calculator's derived property has no uuid (null)."""
    shown = set(eyes)
    out = []
    for path in selected:
        uuid, type_, title = describe(path)
        row = {"uuid": uuid or None, "type": type_ or "", "title": title or "", "shown": path in shown}
        if loaded is not None:
            row["loaded"] = loaded(path)
        out.append(row)
    return out


def settled(answer):
    """An objects answer whose reads are over: no read running, every object
    asked for loaded."""
    return not answer.get("loading") and all(r.get("loaded", True) for r in answer.get("objects") or ())


def catalogue(objects, read, shown, kind="", text="", limit=500):
    """The objects of the data, read or not: (rows, total). `objects`
    [(path, uuid, type, title)], one per object; a row {uuid, type, title,
    read, shown}; `kind` keeps one type (any case), `text` the titles
    holding it (any case); `limit` rows at most, `total` all those kept."""
    kind, text = (kind or "").strip().lower(), (text or "").strip().lower()
    read, shown = set(read), set(shown)
    kept = [{"uuid": uuid, "type": type_ or "", "title": title or "", "read": path in read, "shown": path in shown}
            for path, uuid, type_, title in objects
            if uuid and (not kind or (type_ or "").lower() == kind) and (not text or text in (title or "").lower())]
    return kept[:max(0, int(limit))], len(kept)


def count_of(value, name, default, most):
    """A whole number of the query (`limit`, `wait`) between 0 and `most`,
    its default when absent."""
    if value in (None, ""):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ObjectsError(f'"{name}" is a whole number, not {value!r}.') from None
    if not 0 <= number <= most:
        raise ObjectsError(f'"{name}" is between 0 and {most}, not {number}.')
    return number
