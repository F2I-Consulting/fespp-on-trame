"""stratigraphy

(Moved out of app/boot, overhaul slice 10.)"""
from fespp_on_trame.engine import repo_query
from fespp_on_trame.engine.vtk_log import capture_vtk_messages


def register(core, *, _defer, _etp_on):
    """Wire the section's controllers and watchers; hands back what
    the rest of the app still calls (nothing)."""
    # the shared services (app/core/context.Core)
    state = core.state
    controller = core.controller
    active_data_source = core.active_data_source
    _mv = core.mv
    # --- stratigraphy ---------------------------------------------------
    _strati_cache = {"key": None}

    def _strati_wanted():
        """Is a view that draws the stratigraphic column open: the
        Stratigraphy view, or the well-log panel with wells in it?"""
        mv = _mv()
        if mv is None:
            return False
        try:
            if mv.panel_ids_of_kind("stratigraphy"):
                return True
            return bool(mv.panel_ids_of_kind("welllog")) and bool(
                getattr(state, "ui_welllog_wells", None))
        except Exception as exc:
            print("[fespp] stratigraphy: view lookup failed:", exc, flush=True)
            return False

    @controller.set("stratigraphy_on_demand")
    def _stratigraphy_on_demand():
        """After a load the column is stale. Under ETP the lean load leaves
        the stratigraphic objects on the store and the first read of the
        column brings them over (785 objects, 2.6 to 3.8 s on a hosted
        store): that read happens now only when a view draws the column,
        and otherwise when such a view opens (`ensure_stratigraphy`)."""
        _strati_cache["key"] = None
        if _strati_wanted():
            _refresh_stratigraphy()
        else:
            state.ui_strati_columns = []
            state.ui_strati_note = ""

    @controller.set("ensure_stratigraphy")
    def _ensure_stratigraphy():
        """A view that draws the column just opened or got a well: build it
        when it is stale, nothing otherwise."""
        if _strati_cache.get("key") is None:
            _refresh_stratigraphy()
    @controller.set("refresh_stratigraphy")
    def _refresh_stratigraphy():
        mv = core.mv()
        views = ([*mv.panel_ids_of_kind("stratigraphy"), *mv.panel_ids_of_kind("welllog")]
                 if mv is not None else [])
        if views and _strati_cache.get("key") is None:
            state.ui_strati_note = "Reading the stratigraphic column…"
        _defer("stratigraphy", _refresh_stratigraphy_now, views=views)

    def _refresh_stratigraphy_now():
        with capture_vtk_messages(state):
            _read_stratigraphy()

    def _read_stratigraphy():
        """The stratigraphic column of the loaded data, through the reader's
        query channel (engine/repo_query): fesapi is the source, so EPC and
        ETP behave alike. The XML is parsed in Python — the one field
        the column needs most, the chronostratigraphic bracket, is not in
        fesapi's typed API, and serializeIntoString hands it over for free.

        There is no zip fallback: the app reads RESQML through FESPP only, so
        an older plugin means no column and says so.
        """
        from fespp_on_trame.engine import stratigraphy
        src = active_data_source.get_source()
        note = ""
        columns = []
        key = None
        try:
            t = repo_query.tag(src)
            ranks = tuple(repo_query.object_uuids(
                src, repo_query.TYPE_STRATI_RANK, cache_tag=t))
            # update_data_information fires on far more than a new load;
            # the tag and the rank set are the whole question, and counting
            # ranks — never testing a string — is what keeps boot's
            # empty.epc (a valid, empty answer) from reading as data
            key = ("channel", _etp_on(), t, ranks)
            if key == _strati_cache.get("key"):
                return
            partial = ()
            if ranks:
                columns, partial = stratigraphy.build_columns_from_source(
                    src, ranks, cache_tag=t)
            if not columns:
                if partial:
                    # fesapi demotes a WHOLE rank to a stub over one
                    # reference it cannot wrap — say so, or this reads as
                    # "the file has no column" when it plainly has one
                    note = (f"{len(partial)} stratigraphic column rank(s) are "
                            "reference stubs here: their objects are not "
                            "loaded, or fesapi could not read a reference "
                            "in them (see the log).")
                elif ranks:
                    note = "The stratigraphic column ranks carry no unit."
                else:
                    note = "No stratigraphic column in the loaded data."
        except repo_query.ChannelMissing:
            key = ("no-channel",)
            columns = []
            note = ("This FESPP build has no object query channel — rebuild "
                    "the plugin to read the stratigraphic column.")
        except Exception as exc:
            # say WHAT happened: a channel failure and a genuine absence look
            # identical to the user otherwise
            print("[fespp] stratigraphy error:", exc, flush=True)
            key = None
            columns = []
            note = "The stratigraphic column could not be read (see the log)."
        _strati_cache["key"] = key
        state.ui_strati_columns = columns
        state.ui_strati_note = note
        # a panel whose rank is gone from the file shows the first one again
        uuids = {c["uuid"] for c in columns}
        chosen = dict(getattr(state, "ui_strati_selected_by_view", None) or {})
        kept = {pid: u for pid, u in chosen.items() if u in uuids}
        if kept != chosen:
            state.ui_strati_selected_by_view = kept

    @controller.set("strati_select")
    def strati_select(uuid, view_id):
        """A rank was chosen in THIS panel's column: the other panels keep
        theirs (two ranks of one file read side by side)."""
        chosen = dict(getattr(state, "ui_strati_selected_by_view", None) or {})
        chosen[str(view_id or "")] = str(uuid or "")
        state.ui_strati_selected_by_view = chosen

    @controller.set("strati_pick")
    def strati_pick(unit_title, view_id):
        """A band was clicked: mark it in THIS view's column."""
        marks = dict(getattr(state, "ui_strati_titles", None) or {})
        vid = str(view_id or "")
        marks[vid] = "" if marks.get(vid) == unit_title else (unit_title or "")
        state.ui_strati_titles = marks
