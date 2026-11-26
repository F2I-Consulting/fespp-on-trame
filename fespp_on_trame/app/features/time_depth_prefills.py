"""The Pre-fill of the time-depth model: TDLaws read from the files on the query
channel, nothing loaded in the views: the question first (the shared box), the
reads on a yes (engine/time_depth_prefill). What it reads replaces the columns
of the active model, whose memory is the law's (app/features/time_depth_law
`held`).
"""
import types

from fespp_on_trame.engine import time_depth_prefill as prefill
from fespp_on_trame.engine.utils import numfmt


def register(held, *, _changed, publish, _ask, _query, _channels, _markers, _grids,
             _trajectories=None, _defer=None, _card_views=None):
    """`_ask(question, on_yes, on_no)`: the shared question box. `_query()`: the
    reader's query channel, `_channels()`: the log channels of the tree,
    `_markers()`: its marker frames, `_grids()`: its 2D grids by domain,
    `_trajectories()`: its wells' trajectories [(well, uuid)], `_defer(name, fn,
    views)`: one turn later behind the bar of `views`, `_card_views()`: the 3D
    views with the model's card open. Hands back what the law calls:
    `prefill(what)`, `counts()`, `check()`, `xml_of(query, uuids)`."""
    # a well -> it stands on one vertical. Read once each.
    is_vertical = {}

    def model():
        return held["model"]

    def _kept(wells):
        """(how many of `wells` are vertical, how many are not): a well not read
        yet counts as vertical."""
        out = sum(1 for well in wells if is_vertical.get(well) is False)
        return len(wells) - out, out

    def _counts():
        """What each Pre-fill entry gives, for the menu (0 greys the entry):
        the vertical wells with a time log, a sonic log, markers, the deviated
        ones left out, and the 2D grids in time and in depth — the tree walked
        at every publish, milliseconds, nothing read (`check` reads what it does
        not know yet)."""
        out = {"wells": 0, "wells_out": 0, "sonic": 0, "sonic_out": 0, "markers": 0, "markers_out": 0,
               "time_grids": 0, "depth_grids": 0}
        try:
            channels = _channels()
            grids = _grids()
            wells, wells_out = _kept([log[0] for log in prefill.pick_time_logs(channels)])
            sonic, sonic_out = _kept([log[0] for log in prefill.pick_sonic_logs(channels)])
            markers, markers_out = _kept(sorted({well for well, *_rest in _markers()}))
            out.update(wells=wells, wells_out=wells_out, sonic=sonic, sonic_out=sonic_out,
                       markers=markers, markers_out=markers_out,
                       time_grids=int(grids.get("time", 0)), depth_grids=int(grids.get("depth", 0)))
        except Exception as exc:
            print(f"[fespp] time-depth pre-fill: the tree could not be counted ({exc!r})", flush=True)
        return out

    def _on_a_vertical(items):
        """The `items` (a well first) of the wells not known to be deviated."""
        return [item for item in items if is_vertical.get(item[0]) is not False]

    def _not_vertical(every, kept, what):
        """What a question says first of the wells with `what` that are not
        vertical: they make no TDLaw."""
        gone = sorted({item[0] for item in every} - {item[0] for item in kept})
        if not gone:
            return ""
        names = ", ".join(gone[:6]) + (f" and {len(gone) - 6} more" if len(gone) > 6 else "")
        return (f"{numfmt.plural(len(gone), 'well', 'wells')} with {what} {'is' if len(gone) == 1 else 'are'}"
                f" not vertical and {'is' if len(gone) == 1 else 'are'} NOT taken into account: {names}. ")

    def _unread():
        """The wells not read yet whose trajectory is at hand, a file's: a
        store's is a request, and there a pick says what it found."""
        far = getattr(_query(), "store", lambda: ())()
        return [(well, uuid) for well, uuid in (_trajectories() if _trajectories is not None else ())
                if well not in is_vertical and uuid not in far]

    def _read_wells():
        """Each well not read yet: its trajectory's extent, on the query channel."""
        try:
            q = _query()
            for well, uuid in _unread():
                is_vertical[well] = prefill.extent_vertical(q.fields(uuid))
        except Exception as exc:
            print(f"[fespp] time-depth pre-fill: the wells could not be read ({exc!r})", flush=True)
        publish()

    def _check():
        """While the card is open, what the menu announces is what a pick
        gives, for the wells at hand (`_unread`)."""
        views = _card_views() if _card_views is not None else []
        if not views or _defer is None:
            return
        try:
            if not _unread():
                return
        except Exception as exc:
            print(f"[fespp] time-depth pre-fill: the wells could not be listed ({exc!r})", flush=True)
            return
        _defer("time-depth wells", _read_wells, views=views)

    def _say(note):
        """What a pre-fill could not do: a band in the card, until the next edit."""
        held["note"] = note
        held["refusal"] = note
        publish()

    def _prefill(what):
        """A pre-fill from the files, on the query channel, nothing loaded
        in the views: the question first (the shared box), the reads on a
        yes (engine/time_depth_prefill)."""
        if _ask is None:
            raise ValueError("no question box to ask through")
        go = {"wells": _prefill_wells, "sonic": _prefill_sonic, "markers": _prefill_markers}.get(what)
        if go is None:
            raise ValueError("unknown pre-fill")
        go()

    def _set_columns(columns, note, kind):
        """The model's columns replaced by `columns` [(name, (x, y),
        points, source)], read by the Pre-fill `kind`."""
        m = model()
        m.columns = []
        for name, (x, y), points, source in columns:
            c = m.columns[m.add_column(x, y)]
            c.name = prefill.column_name(name)
            c.source = source
            c.law.points[:] = [(float(z), float(t)) for z, t in points]
        held["active"] = 0
        held["note"] = note
        held["prefilled"] = kind
        held["touched"] = True
        _changed()

    def _replaced():
        """What a pre-fill of columns says of the current ones."""
        n = len(model().columns)
        return f" The {n} current TDLaw{'s are' if n > 1 else ' is'} replaced." if n else ""

    def _left(read, columns, why):
        """" · 2 without <why>", or "" when every read made a column."""
        left = len(read) - len(columns)
        return f" · {left} without {why}" if left > 0 else ""

    def _vertical(read):
        """The reads of vertical wells, and what says the deviated ones
        left out: a TDLaw stands for ONE place, a well not wholly vertical makes
        none, even where its log is."""
        kept, gone = prefill.vertical_only([r for r in read if is_vertical.get(r[0]) is not False])
        gone += [r[0] for r in read if is_vertical.get(r[0]) is False]
        is_vertical.update((well, False) for well in gone)
        return kept, (f" · {numfmt.plural(len(gone), 'deviated well', 'deviated wells')} left out"
                      if gone else "")

    def _prefill_wells():
        every = prefill.pick_time_logs(_channels())
        logs = _on_a_vertical(every)
        if not logs:
            _say("the wells with a time log are all deviated" if every
                 else "no well carries a time log (a channel in s or ms)")
            return
        q = _query()
        n = numfmt.plural(len(logs), "well", "wells")
        names = _names(logs)

        def go():
            read, deviated = _vertical([(w, t, prefill.log_samples(q.fields(uuid))) for w, uuid, t, _uom in logs])
            columns, step = prefill.wells_columns(read)
            if not columns:
                _say(f"the time logs of {n}: none of a vertical well holds two usable samples" + deviated)
                return
            _set_columns(columns, f"{len(columns)} TDLaws from the wells' time logs, every {step:g} m"
                         + _left(read, columns, "two usable samples") + deviated, "wells")

        _ask({"title": f"Read the time logs of {n}?",
              "body": (_not_vertical(every, logs, "a time log")
                       + f"{names}: their samples are read on the query channel, nothing is loaded in the views."
                       " One TDLaw per vertical well (a deviated one is left out), named after it, placed"
                       f" where the log is, its points on a depth step shared by all (about"
                       f" {prefill.LAYERS_WANTED} layers)." + _replaced()),
              "ok": "Read"}, go, None)

    def _names(logs):
        """"W1 (DT), W2 (DT_EDIT), …" — the logs a question names, each well
        by its column's name."""
        return (", ".join(f"{prefill.column_name(w) or w} ({t})" for w, _uuid, t, _uom in logs[:8])
                + (", …" if len(logs) > 8 else ""))

    def _top_twt(x, y, depth):
        """The two-way time at a sonic log's top: the current model's there
        when it converts, else from the zero at REPLACEMENT_V."""
        cube = held["cube"]
        if cube is not None:
            try:
                return float(cube.to_time([x], [y], [depth])[0])
            except (IndexError, ValueError, ZeroDivisionError) as exc:
                print(f"[fespp] time-depth pre-fill: the model gave no time at a log's top ({exc!r})", flush=True)
        return 2000.0 * depth / prefill.REPLACEMENT_V

    def _prefill_sonic():
        every = prefill.pick_sonic_logs(_channels())
        logs = _on_a_vertical(every)
        if not logs:
            _say("the wells with a sonic log are all deviated" if every
                 else "no well carries a sonic log (DT in us/ft or us/m, Vp in m/s or ft/s)")
            return
        q = _query()
        n = numfmt.plural(len(logs), "well", "wells")
        above = ("the current model's time there" if held["cube"] is not None
                 else f"{prefill.REPLACEMENT_V:g} m/s from the zero")
        lo, hi = prefill.VP_RANGE

        def go():
            read, deviated = _vertical([(w, t, prefill.sonic_samples(q.fields(uuid), _top_twt))
                                        for w, uuid, t, _uom in logs])
            columns, step = prefill.wells_columns(
                read, describe=lambda title, s: f"{title} integrated from {s[0][2]:.0f} m")
            if not columns:
                _say(f"the sonic logs of {n}: none of a vertical well holds two usable values" + deviated)
                return
            _set_columns(columns, f"{len(columns)} TDLaws from the wells' sonic logs, every {step:g} m"
                         + _left(read, columns, "two usable values") + deviated, "sonic")

        _ask({"title": f"Integrate the sonic logs of {n}?",
              "body": (_not_vertical(every, logs, "a sonic log")
                       + f"{_names(logs)}: their values are read on the query channel, nothing is loaded in"
                       f" the views. Each log is integrated down from its top (two-way time = 2 Σ dz / v,"
                       f" a velocity outside {lo:g}–{hi:g} m/s dropped as a spike); above its top, {above}."
                       " One TDLaw per vertical well (a deviated one is left out), named after it, placed"
                       " where the log is, its points on a depth step shared by all." + _replaced()),
              "ok": "Read"}, go, None)

    def _xml_of(q, uuids):
        """{uuid: its XML} of the distinct, non-empty `uuids`, in one
        round trip."""
        wanted = sorted({u for u in uuids if u})
        reader = getattr(q, "xml", None)
        if not wanted or reader is None:
            return {}
        return dict(zip(wanted, reader(wanted)))

    def _surfaces(q):
        """The 2D grids of the files and what pairs them, read on the query
        channel (their XML, their interpretation's, their feature's, their
        CRS): [{uuid, title, interp, feature, time, factor}] — `title` the
        feature's name, `interp` the interpretation's uuid, `time` a time
        CRS, `factor` its unit to the ms."""
        entries = [(e["uuid"], e.get("title") or "") for e in q.index() or ()
                   if e.get("type") == "Grid2dRepresentation"]
        reps = _xml_of(q, [u for u, _t in entries])
        refs = {u: prefill.xml_refs(reps.get(u), "RepresentedInterpretation", "LocalCrs") for u, _t in entries}
        interps = _xml_of(q, [r[0] for r in refs.values()])
        feats = {i: prefill.xml_refs(x, "InterpretedFeature") for i, x in interps.items()}
        names = _xml_of(q, [f[0] for f in feats.values()])
        out = []
        for uuid, title in entries:
            interp, crs, _own = refs[uuid]
            feature, interp_title = feats.get(interp, ("", ""))
            feature_title = prefill.xml_refs(names.get(feature))[-1]
            name = next((t for t in (feature_title, interp_title, title) if t and t != "|UNNAMED|"), title)
            crs_fields = q.fields(crs) if crs else {}
            time = str(crs_fields.get("time_crs", "")).lower() == "true"
            factor = (prefill.time_factor(crs_fields.get("time_unit")) or 1.0) if time else 1.0
            out.append({"uuid": uuid, "title": name, "interp": (interp or "").lower(), "feature": feature,
                        "time": time, "factor": factor})
        return out

    def _reader(q, s):
        """(at, extent) of surface `s` counted downward — a time in ms, a
        depth in m — None when its elevations cannot be read."""
        reader = getattr(q, "surface", None)
        fields = reader(s["uuid"]) if reader is not None else {}
        got = prefill.surface_reader(fields)
        if got is None:
            return None
        return prefill.oriented(got[0], fields, s["factor"]), got[1]

    _NO_SURFACE_READ = ("the surfaces' elevations could not be read on the query channel"
                        " (a server whose plugin predates them reads none)")

    def _prefill_markers():
        every = _markers()
        frames = _on_a_vertical(every)
        if not frames:
            _say("the wells with markers are all deviated" if every else "no well carries markers")
            return
        q = _query()
        times = [s for s in _surfaces(q) if s["time"]]
        if not times:
            _say("no surface in time to read the markers on")
            return
        # a marker reads the grid in time of ITS interpretation, by uuid,
        # never by name, and only when the interpretation has one: with
        # several, which one would it be?
        by_interp = {}
        for s in times:
            if s["interp"]:
                by_interp.setdefault(s["interp"], []).append(s)
        one = {i: ss[0] for i, ss in by_interp.items() if len(ss) == 1}
        many = len(by_interp) - len(one)
        wells = sorted({w for w, *_rest in frames})
        n = numfmt.plural(len(wells), "well", "wells")

        def go():
            xml = _xml_of(q, [uuid for _w, uuid, _t, _titles in frames])
            by_well = {}
            for well, uuid, _title, _titles in frames:
                interps = prefill.marker_interpretations(xml.get(uuid))
                by_well.setdefault(well, []).extend(prefill.marker_points(q.fields(uuid), interps))
            surface_at = {}     # interpretation uuid -> (at, extent) | None
            for interp in sorted({m[0] for ms in by_well.values() for m in ms} & set(one)):
                surface_at[interp] = _reader(q, one[interp])
            if not any(r is not None for r in surface_at.values()):
                _say(_NO_SURFACE_READ if surface_at
                     else "no marker's interpretation has one surface in time")
                return

            def time_of(interp, _title, x, y):
                got = surface_at.get(interp)
                return got[0](x, y) if got is not None else None

            read, deviated = _vertical([(w, "markers", prefill.marker_samples(ms, time_of))
                                        for w, ms in by_well.items()])
            columns, step = prefill.wells_columns(
                read, least=1, describe=lambda _t, s: f"{len(s)} markers on the time horizons")
            if not columns:
                _say(f"the markers of {n}: none of a vertical well stands on the surface in time"
                     " of its interpretation" + deviated)
                return
            used = sum(1 for r in surface_at.values() if r is not None)
            _set_columns(columns, f"{len(columns)} TDLaws from the markers on {used}"
                                  f" time horizons, every {step:g} m" + _left(read, columns, "a marker on one")
                         + deviated, "markers")

        _ask({"title": f"Read the markers of {n} on the time horizons?",
              "body": (_not_vertical(every, frames, "markers")
                       + f"{numfmt.plural(len(one), 'interpretation has', 'interpretations have')} one surface"
                       " in time" + (f", {many} more than one: their markers point at no single time horizon"
                                     " and are NOT taken into account" if many else "")
                       + ". Each marker is read on the surface in time of its own interpretation (by its uuid):"
                       " its depth against the surface's two-way time. On the query channel, nothing is loaded"
                       " in the views. One TDLaw per vertical well (a deviated one is left out), its points"
                       " on a depth step shared by all." + _replaced()),
              "ok": "Read"}, go, None)

    return types.SimpleNamespace(prefill=_prefill, counts=_counts, check=_check, xml_of=_xml_of)
