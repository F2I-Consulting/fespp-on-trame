"""The stratigraphic column, read from the objects' XML.

WHERE THE XML COMES FROM: fesapi, through the reader's query channel
(engine/repo_query — ``serializeIntoString()`` of every object the column
touches). That is the same source over a local EPC and over ETP, which is
why the column exists in an ETP session too. The app reads RESQML through
FESPP only: there is no zip reader.

WHY THE XML AND NOT FESAPI'S TYPED API: the one field that makes a
chronostratigraphic binding possible — ``ChronostratigraphicTop`` /
``Bottom`` on a StratigraphicUnitFeature — is not in fesapi's typed API (the
name appears only in the generated gsoap proxies), and fesapi also drops the
RESQML 2.0.1 per-unit ``<Index>`` on read. The serialized XML carries both,
so parsing it here is the smaller and the more faithful path. (RESQML 2.2
has no bracket in the schema at all — that is not a gap of this code.)

Stratigraphy is nowhere in FESPP's tree: the plugin maps REPRESENTATIONS
(geometry), and in RESQML the stratigraphy lives in the INTERPRETATION
layer, which has no dataset of its own. Hence a query by uuid rather than a
tree node.

The resolution chain:

    StratigraphicColumnRankInterpretation
      -> StratigraphicUnits[Index].Unit        (ordered, by Index)
        -> StratigraphicUnitInterpretation
          -> InterpretedFeature
            -> StratigraphicUnitFeature        title, colour, chrono bracket

Two facts that shape the code. The unit INTERPRETATION is often titled
"|UNNAMED|" — the readable name lives on the FEATURE, so the chain must be
walked to the end. And a data set often ships as SEVERAL EPCs that
reference each other, so the uuid index spans every loaded file, not one.

No h5py, no zipfile and no fesapi binding here: everything comes from the
reader proxy through engine/repo_query.

WHAT THE FILE STATES, NOTHING MORE (the PO and his manager, 2026-10-15). A
unit of the file shows an age only when the file writes it: in RESQML 2.2 a
unit interpretation may carry its own interval, HasOccurredDuring as a
GeologicTimeBasedTimeInterval (Start and End, each a GeologicTime: a
DateTime and an AgeOffsetAttribute in years). RESQML 2.0.1 gives a unit no
number (its HasOccuredDuring and the feature's Chronostratigraphic
Top/Bottom only NAME other objects); the one 2.0.1 age, a genetic
boundary's AbsoluteAge, belongs to a horizon, and none of the 45 ADME
dataspaces nor the local test files carries one. The ICS chart
(engine/ics_chart) no longer dates or classifies a unit by its NAME; it is
joined to a rank the file dates, as a reference scale over the same ages
(`ics`). A hole between two dated units is listed (`age_gaps`) so the
panel hatches it instead of leaving it blank.
"""
import re
import xml.etree.ElementTree as ET

# uuid as it appears in a part name: obj_<Type>_<uuid>.xml
_PART_UUID = re.compile(
    r"_([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
    r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\.xml$")

# a RESQML colour rides in ExtraMetadata as RGBA floats, e.g.
# "0.827451 0.827451 0.827451 1" (the writer's convention, not the standard's)
_COLOR_KEYS = ("pdgm/dx/resqml/color", "color")


def _local(tag):
    """Local name of a namespaced tag — every RESQML writer picks its own
    prefixes, so matching on the local name is the only stable way in."""
    return tag.rsplit("}", 1)[-1]


def _child(elem, name):
    for c in elem:
        if _local(c.tag) == name:
            return c
    return None


def _children(elem, name):
    return [c for c in elem if _local(c.tag) == name]


def _text(elem, name):
    c = _child(elem, name)
    return (c.text or "").strip() if c is not None else ""


def _title(elem):
    """Citation/Title of an object, or the Title carried by a reference."""
    cit = _child(elem, "Citation")
    if cit is not None:
        return _text(cit, "Title")
    return _text(elem, "Title")


def _dor_uuid(ref):
    """The uuid of a DataObjectReference. RESQML 2.0.1 spells the element
    ``UUID``, 2.2 / EML 2.3 spells it ``Uuid`` — accept either rather than
    silently resolving nothing."""
    if ref is None:
        return ""
    return _text(ref, "UUID") or _text(ref, "Uuid")


def _ref_uuid(elem, name):
    """UUID inside a DataObjectReference child called `name`."""
    return _dor_uuid(_child(elem, name))


def _ref_title(elem, name):
    ref = _child(elem, name)
    return _text(ref, "Title") if ref is not None else ""


def _rgba_to_hex(value):
    """"0.83 0.83 0.83 1" -> "#d3d3d3". Returns "" on anything unexpected —
    a missing colour is normal and the caller falls back to its own ramp."""
    parts = (value or "").replace(",", " ").split()
    if len(parts) < 3:
        return ""
    try:
        rgb = [float(p) for p in parts[:3]]
    except ValueError:
        return ""
    # nan / inf PARSE fine and then raise in round() — and the exception
    # would travel all the way out of _build_columns, dropping every column
    # of every loaded file over one bad value in one unit.
    import math
    if not all(math.isfinite(c) for c in rgb):
        return ""
    if max(rgb) > 1.0:          # already 0-255
        rgb = [c / 255.0 for c in rgb]
    return "#" + "".join(f"{max(0, min(255, round(c * 255))):02x}" for c in rgb)


def _extra_metadata(elem):
    """{name: value} of the ExtraMetadata NameValuePairs."""
    out = {}
    for em in _children(elem, "ExtraMetadata"):
        name = _text(em, "Name")
        if name:
            out[name] = _text(em, "Value")
    return out


def _fallback_color(position, total):
    """A readable band colour for a unit the file did not colour.

    Some files, synthetic ones especially, carry no colour at all; without
    this their column would come up blank. Deterministic (same unit, same
    colour, every session), and kept muted so a generated colour never
    passes for the official one — `color_source` says which.
    """
    if total <= 0:
        return "#b0b0b0"
    # walk the hue circle, skipping the red end so nothing reads as an alarm
    hue = (0.08 + 0.78 * (position / float(max(total - 1, 1)))) % 1.0
    import colorsys
    r, g, b = colorsys.hls_to_rgb(hue, 0.72, 0.42)
    return "#" + "".join(f"{round(c * 255):02x}" for c in (r, g, b))


_AGE_FIELDS = ("AgeOffsetAttribute", "YearOffset")


def _years(elem):
    """The age a GeologicTime (2.2) or Timestamp (2.0.1) element states, in
    years from its DateTime, or None. Writers differ on the sign; the two
    bounds of an interval are ordered by magnitude afterwards."""
    if elem is None:
        return None
    for name in _AGE_FIELDS:
        text = _text(elem, name)
        if text:
            try:
                return abs(float(text))
            except ValueError:
                return None
    return None


def _file_ages(interp):
    """(younger_ma, older_ma) the interpretation's own time interval
    states, or (None, None). Only an interval with BOTH bounds written as
    numbers counts: a boundary-based interval names two objects and gives no
    number, and half an interval is not an age."""
    for name in ("HasOccurredDuring", "HasOccuredDuring"):
        interval = _child(interp, name)
        if interval is None:
            continue
        start, end = _years(_child(interval, "Start")), _years(_child(interval, "End"))
        if start is None or end is None:
            return None, None
        return min(start, end) / 1e6, max(start, end) / 1e6
    return None, None


def _unit_from_interpretation(index, interp_uuid):
    """Walk interpretation -> feature and collect what the column shows."""
    interp = index.get(interp_uuid)
    if interp is None:
        return None
    feat_uuid = _ref_uuid(interp, "InterpretedFeature")
    feat = index.get(feat_uuid) if feat_uuid else None
    # the INTERPRETATION is frequently "|UNNAMED|"; the readable name is on
    # the feature. Fall back to the interpretation only when the feature is
    # absent (a partial object, or a reference into a file we do not have).
    name = _title(feat) if feat is not None else ""
    if not name:
        name = _title(interp)
    colour = ""
    chrono_top = chrono_bottom = ""
    if feat is not None:
        meta = _extra_metadata(feat)
        for key in _COLOR_KEYS:
            if meta.get(key):
                colour = _rgba_to_hex(meta[key])
                if colour:
                    break
        # the chronostratigraphic bracket: a PAIR of boundaries, never one
        # point. This is the only thing in the file that can be joined to a
        # chart — and fesapi does not expose it.
        chrono_top = _ref_title(feat, "ChronostratigraphicTop")
        chrono_bottom = _ref_title(feat, "ChronostratigraphicBottom")
    younger_ma, older_ma = _file_ages(interp)
    return {
        "uuid": interp_uuid,
        "feature_uuid": feat_uuid,
        "title": name or "(unnamed)",
        "color": colour,
        "chrono_top": chrono_top,
        "chrono_bottom": chrono_bottom,
        # the file's own ages, in Ma; None when it writes none
        "younger_ma": younger_ma,
        "older_ma": older_ma,
    }


# A unit title is a BOUNDARY: "<entity>_ Top" / "<entity> Base". Writers use
# both separators, and some entries carry no role at all ("Seabed", "TPaMFS115").
_ROLE = re.compile(r"^(?P<entity>.*?)[ _]+(?P<role>Top|Base)$", re.IGNORECASE)


def _entity_kind(name):
    """What KIND of thing this entry is, as far as its name STATES it.

    A rock unit says so in its name ("NORDLAND GP", "HUGIN FM", "… MB": the
    author's own label). A name that happens to be a term of the ICS chart
    is no longer called a time unit: that was the chart's word, not the
    file's (2026-10-15). Everything else is "other" — unclassified, and
    shown as such:
    the operator's zonation and the correlation surfaces used to be guessed
    from patterns in the name (digits, "MFS", "BCU"…), which is an
    approximation the column, made for professionals, must not make (PO,
    2026-10-05).
    """
    n = name.strip().rstrip("_").strip()
    upper = n.upper()
    if upper.endswith(" GP") or upper.endswith(" GROUP"):
        return "group"
    if upper.endswith(" FM") or upper.endswith(" FORMATION"):
        return "formation"
    if upper.endswith(" MB") or upper.endswith(" MEMBER"):
        return "member"
    return "other"


def _entities_of(units):
    """Collapse the boundary list into ENTITIES, one band per thing.

    Hundreds of boundaries are an unreadable wall; the same column holds
    about half as many entities, each spanning from its Top to its Base —
    the boundaries the file lists under the same name, at their own index.
    """
    by_entity = {}
    order = []
    for u in units:
        m = _ROLE.match(u["title"] or "")
        if m:
            name = m.group("entity").strip()
            role = m.group("role").lower()
        else:
            name, role = (u["title"] or "").strip(), "single"
        e = by_entity.get(name)
        if e is None:
            e = {"name": name, "kind": _entity_kind(name),
                 "top": None, "base": None, "color": u["color"],
                 "color_source": u.get("color_source", ""),
                 "chrono_top": u.get("chrono_top", ""),
                 "chrono_bottom": u.get("chrono_bottom", ""),
                 "younger_ma": None, "older_ma": None}
            by_entity[name] = e
            order.append(e)
        # the entity spans the ages its units state, when they state any
        if u.get("younger_ma") is not None and u.get("older_ma") is not None:
            e["younger_ma"] = (u["younger_ma"] if e["younger_ma"] is None
                               else min(e["younger_ma"], u["younger_ma"]))
            e["older_ma"] = (u["older_ma"] if e["older_ma"] is None
                             else max(e["older_ma"], u["older_ma"]))
        if role == "base":
            e["base"] = u["index"]
        else:
            if e["top"] is None:
                e["top"] = u["index"]
            if role == "single":
                e["base"] = u["index"]
    out = []
    for e in order:
        if e["top"] is None:
            e["top"] = e["base"]
        if e["base"] is None:
            e["base"] = e["top"]          # a Top with no Base: a single surface
        e["span"] = max(0, e["base"] - e["top"])
        out.append(e)
    out.sort(key=lambda e: (e["top"], -e["span"]))
    # No parent group (PO, 2026-10-05: no approximation, the column is for
    # professionals): it was guessed from which group's index span covered
    # an entity, which the file never states.
    return out


def age_gaps(entities):
    """[{younger_ma, older_ma}] — every stretch of time between the youngest
    and the oldest dated entity that NO entity of the list covers: what the
    panel hatches as "not defined". Exact on the file's numbers (a gap of
    one year is a gap); nothing is invented before the first entity or
    after the last."""
    spans = sorted((e["younger_ma"], e["older_ma"]) for e in entities or ()
                   if e.get("younger_ma") is not None and e.get("older_ma") is not None)
    gaps = []
    if not spans:
        return gaps
    reach = spans[0][1]
    for younger, older in spans[1:]:
        if younger > reach + 1e-9:
            gaps.append({"younger_ma": reach, "older_ma": younger})
        reach = max(reach, older)
    return gaps


def _ics_reference(entities):
    """The ICS chart over the ages the file dates this rank with, as a
    REFERENCE scale to draw beside it, or None for a rank the file does not
    date (the PO, 2026-10-15: ICS only where the data has ages)."""
    dated = [e for e in entities if e.get("younger_ma") is not None and e.get("older_ma") is not None]
    if not dated:
        return None
    try:
        from fespp_on_trame.engine import ics_chart
        younger = min(e["younger_ma"] for e in dated)
        older = max(e["older_ma"] for e in dated)
        return {"chart": ics_chart.CHART_VERSION, "source": ics_chart.CHART_SOURCE,
                "units": ics_chart.units_between(younger, older)}
    except Exception as exc:
        print("[fespp] ICS reference not joined:", exc, flush=True)
        return None


def entity_index(columns):
    """{boundary title -> entity} across every column.

    A well's MARKER titles are the column's boundary titles verbatim
    ("NORDLAND GP_ Top" is both a marker in the well and the top of the
    NORDLAND GP entity), which is what lets a well be placed on the column
    without reading a single array from the HDF5.
    """
    out = {}
    for col in columns or ():
        ents = {e["name"]: e for e in col.get("entities") or ()}
        for u in col.get("units") or ():
            title = (u.get("title") or "").strip()
            if not title:
                continue
            m = _ROLE.match(title)
            name = m.group("entity").strip() if m else title
            role = m.group("role").lower() if m else "single"
            ent = ents.get(name)
            if ent is not None:
                out.setdefault(title, (ent, role))
    return out


_ROCK_KINDS = ("formation", "member", "other")

# The three lanes the stratigraphy chart draws, and what each takes from the
# set of units open at a given depth. They are read innermost-first, so a lane
# shows the most specific unit it has rather than the broadest.
_LANES = (
    ("time", lambda e: e["kind"] == "chrono"),
    ("group", lambda e: e["kind"] == "group"),
    ("rock", lambda e: e["kind"] in _ROCK_KINDS),
)


def _innermost(stack, pred):
    for entity in reversed(stack):
        if pred(entity):
            return entity
    return None


def intervals_for_tops(columns, tops):
    """{"time": [...], "group": [...], "rock": [...]} — the column laid onto
    ONE well's depth axis, split into the same lanes the chart uses.

    Each lane is a list of {name, kind, parent, color, top, bottom}.

    `tops` is the well's [{name, depth}] as the well-log builds it. Each pair
    of consecutive picks bounds an interval; a `Base` pick closes what it
    names without opening anything, which is what leaves the gaps a well
    legitimately has.

    Splitting by lane rather than returning one band matters: time and rock
    are parallel axes, so at a given depth a well is inside a stage AND
    inside a group AND inside a formation at once. One band can only show
    the innermost of the three and silently drops the other two.
    """
    index = entity_index(columns)
    picks = sorted(
        [t for t in (tops or []) if t.get("depth") is not None],
        key=lambda t: t["depth"])
    # A STACK of currently-open entities, not one interval per Top: below the
    # base of a formation you are still inside its group, and a pick the
    # column does not know must not blank the rock around it. This is what
    # makes each lane continuous instead of gap-riddled.
    stack = []
    lanes = {name: [] for name, _ in _LANES}
    for i, pick in enumerate(picks[:-1]):
        found = index.get((pick.get("name") or "").strip())
        if found is not None:
            entity, role = found
            stack = [e for e in stack if e["name"] != entity["name"]]
            if role != "base":
                stack.append(entity)
        top, bottom = pick["depth"], picks[i + 1]["depth"]
        if bottom <= top or not stack:
            continue
        for name, pred in _LANES:
            current = _innermost(stack, pred)
            if current is None:
                continue
            out = lanes[name]
            if (out and out[-1]["name"] == current["name"]
                    and out[-1]["bottom"] == top):
                out[-1]["bottom"] = bottom      # same unit across several picks
                continue
            out.append({
                "name": current["name"], "kind": current["kind"],
                "parent": current.get("parent", ""), "color": current["color"],
                "top": top, "bottom": bottom,
            })
    return lanes


class RepoIndex:
    """uuid -> parsed root, served by the reader's query channel.

    It offers the two calls `_build_columns` makes on its index:
    `parts_of_type` and `get`.

    Fetching is BATCHED by stage. Asked one object at a time, a rank costs
    one round trip per unit and per feature, hundreds for a real column;
    asked as the rank, then every unit interpretation it lists, then every
    feature those name, it costs three. `get()` on a rank root triggers
    those two prefetches, so the per-unit calls `_build_columns` makes
    afterwards all hit the cache.

    A `<PartialObject>` marker (a reference stub — the common case over ETP
    for anything outside the fetched dataspace) parses like any root: its
    `Citation/Title` is what `_title` reads, so the unit keeps its name and
    is never dropped — `_fallback_color` is position-dependent, and a
    dropped unit would silently recolour the whole column. Such a unit has
    no colour and no chrono bracket; `partial` records who was a stub.
    """

    def __init__(self, source, rank_uuids, cache_tag=None):
        from fespp_on_trame.engine import repo_query
        self._query = repo_query
        self._source = source
        self._tag = cache_tag
        self._ranks = [u for u in (rank_uuids or ()) if u]
        self._parsed = {}
        self._rank_keys = {u.lower() for u in self._ranks}
        self._rank_prefetched = set()
        self.partial = set()
        self.prefetch(self._ranks)

    def prefetch(self, uuids):
        """Fetch and parse, in one batch, every uuid not cached yet."""
        wanted = []
        seen = set()
        for u in uuids or ():
            k = (u or "").lower()
            if k and k not in self._parsed and k not in seen:
                seen.add(k)
                wanted.append(u)
        if not wanted:
            return
        replies = self._query.object_xml(self._source, wanted,
                                         cache_tag=self._tag)
        for uuid, text in zip(wanted, replies):
            root = None
            if text:
                try:
                    root = ET.fromstring(text)
                except Exception:
                    root = None
            if root is not None and _local(root.tag) == "PartialObject":
                self.partial.add(uuid.lower())
            self._parsed[uuid.lower()] = root

    def _prefetch_rank(self, root):
        """Fetch a rank's unit interpretations, then their features."""
        interps = []
        for su in _children(root, "StratigraphicUnits"):
            ref = _child(su, "Unit") or su
            u = _dor_uuid(ref)
            if u:
                interps.append(u)
        self.prefetch(interps)
        feats = []
        for u in interps:
            r = self._parsed.get(u.lower())
            if r is not None and _local(r.tag) != "PartialObject":
                f = _ref_uuid(r, "InterpretedFeature")
                if f:
                    feats.append(f)
        self.prefetch(feats)

    def get(self, uuid):
        """Parsed root element of the object, or None."""
        key = (uuid or "").lower()
        if key not in self._parsed:
            self.prefetch([uuid])
        root = self._parsed.get(key)
        # a rank root, seen for the first time: pull its units and their
        # features in two batches, so the builder's per-unit calls hit cache
        if (root is not None and key in self._rank_keys
                and key not in self._rank_prefetched
                and _local(root.tag) != "PartialObject"):
            self._rank_prefetched.add(key)
            self._prefetch_rank(root)
        return root

    def parts_of_type(self, type_name):
        """[(uuid, "")] — the ranks the channel listed; no part names here."""
        if type_name == "StratigraphicColumnRankInterpretation":
            return [(u, "") for u in self._ranks]
        return []


def build_columns_from_source(source, rank_uuids, cache_tag=None):
    """(columns, partial_rank_uuids) — the stratigraphic columns, read
    through the reader's query channel: identical over EPC and ETP.

    `partial_rank_uuids` are the ranks the reader only holds as reference
    stubs — either their dataspace was not fetched, or fesapi demoted the
    rank over one reference it could not wrap. They yield no column, and
    the caller must say so rather than report "no column in the data".
    """
    index = RepoIndex(source, rank_uuids, cache_tag)
    columns = _build_columns(index)
    ranks_lower = {u.lower() for u in index._ranks}
    partial_ranks = sorted(u for u in index.partial if u in ranks_lower)
    return columns, partial_ranks


def _build_columns(index):
    """One column dict per rank of `index`, sorted by rank index then title."""
    columns = []
    for uuid, _part in index.parts_of_type("StratigraphicColumnRankInterpretation"):
        root = index.get(uuid)
        if root is None:
            continue
        entries = []
        for su in _children(root, "StratigraphicUnits"):
            # 2.0.1 wraps the reference in a <Unit> child and carries an
            # explicit <Index>; 2.2 makes StratigraphicUnits BE the
            # reference and drops the index, so document order is the order.
            ref = _child(su, "Unit") or su
            uuid_ref = _dor_uuid(ref)
            if not uuid_ref:
                continue
            try:
                order = int(_text(su, "Index"))
            except (TypeError, ValueError):
                order = len(entries)
            entries.append((order, uuid_ref))
        entries.sort(key=lambda e: e[0])
        units = []
        for order, interp_uuid in entries:
            unit = _unit_from_interpretation(index, interp_uuid)
            if unit is not None:
                unit["index"] = order
                units.append(unit)
        if not units:
            continue
        for position, unit in enumerate(units):
            if unit["color"]:
                unit["color_source"] = "file"
            else:
                unit["color"] = _fallback_color(position, len(units))
                unit["color_source"] = "generated"
        # 2.0.1: <Index> + <OrderingCriteria>. 2.2 renames both.
        try:
            rank_index = int(_text(root, "Index")
                             or _text(root, "RankInStratigraphicColumn"))
        except (TypeError, ValueError):
            rank_index = 0
        ordering = _text(root, "OrderingCriteria")
        if not ordering:
            ascending = _text(root, "AscendingOrderingCriteria")
            if ascending:
                ordering = ascending
        entities = _entities_of(units)
        title = _title(root)
        if not title or title == "|UNNAMED|":
            # SKUA writes "|UNNAMED|"; name the rank by the column it
            # interprets rather than showing the placeholder
            title = _ref_title(root, "InterpretedFeature") or "Stratigraphic column"
        columns.append({
            "uuid": uuid,
            "title": title,
            # "age" here means "sorted by age" — NOT that the units are
            # chronostratigraphic: a rank ordered by age commonly lists
            # lithostratigraphic units (NORDLAND GP, Utsira Fm). Treat it as
            # a sort hint and never as a chrono/litho classification.
            "ordering": ordering,
            "index": rank_index,
            "units": units,
            # what the UI actually draws: one band per thing, nested
            "entities": entities,
            # the file dates this rank: the panel lays it on its ages,
            # hatches the holes between them and draws the ICS chart beside
            # it as a reference; none of the three for an undated rank
            "dated": any(e.get("younger_ma") is not None for e in entities),
            "age_gaps": age_gaps(entities),
            "ics": _ics_reference(entities),
        })
    columns.sort(key=lambda c: (c["index"], c["title"]))
    return columns
