"""The application's side of the session door (widgets/session): what the
state of fespp-on-trame is made of, and how it is put back.

The door itself (phases, validation, expected files, download, report) is
the widget's `SessionController`; this adapter only knows the application:
what is read, the calculator's recipes, the time-depth model, the 3D views
(eyes, active node, look, domain, colour tables, time, slicers, thresholds,
cards, Globe, camera), the analysis panels (the Stratigraphy panel with its
tab and its model's 3D) and the layout. What a file holds and cannot be put back is
SAID in the report, never dropped silently.
"""
import json
import os

from fespp_on_trame.app.views.camera import CAMERA_PROPERTIES
from fespp_on_trame.engine import node_facts, repo_query, row_object, session_older

from fespp_on_trame.engine.state_defaults import z_scale_of


def _reconcile_cards(s, value):
    """The Log ↔ Grid tree cards `value` opens (a saved boolean: the first
    family the data holds)."""
    from fespp_on_trame.engine import tree_families
    return tree_families.open_cards(value, tree_families.present_names(s.assembly_xml or ""),
                                    tree_families.LOG_GRID)


class FesppSessionHost:
    """The host the session widget's controller calls: it collects the
    application's state into a session document and restores one."""

    def __init__(self, server):
        self.server = server
        self.state = server.state
        self.ctx = server.context
        self.ctrl = server.controller
        # during a restore, what the document names and came back under
        # another name: an extract's path, an item's uid

    # ------------------------------------------------------------ helpers
    def _mv(self):
        return getattr(self.ctx, "multi_view", None)

    def _tree(self):
        return getattr(self.ctx, "tree", None)

    def _known(self, path):
        tree = self._tree()
        return bool(path) and tree is not None and tree.find_node_id(path) is not None

    def _made(self, path):
        """A derived recipe the session has made again: its eye comes back
        with the view's other eyes (04-verification D2)."""
        if not str(path).startswith("derived://"):
            return False
        store = getattr(self.ctx, "derived_store", None)
        try:
            return store is not None and store.get(path) is not None
        except Exception as exc:
            print(f"[fespp] session: recipe {path!r} not readable:", exc, flush=True)
            return False

    # ------------------------------------------------------------ the host API
    def app_name(self):
        try:
            from fespp_on_trame import __version__ as v
        except ImportError as exc:
            print("[fespp] session: no application version:", exc, flush=True)
            v = ""
        return f"fespp-on-trame {v}".strip()

    # ------------------------------------------------------------ OSDU / ETP
    # the state vars whose change makes the door re-check the ETP sources
    etp_watch = ("etp_connected", "ui_etp_loaded_dataspaces")

    def _collect_etp(self):
        end = dict(getattr(self.state, "ui_etp_endpoint", None) or {})
        loaded = list(getattr(self.state, "ui_etp_loaded_dataspaces", None) or [])
        if not end.get("url") or not loaded:
            return None
        return {"url": end["url"], "partition": end.get("partition") or "",
                "dataspaces": loaded}

    def etp_state(self):
        return {"connected": bool(getattr(self.state, "etp_connected", False)),
                "loaded": list(getattr(self.state, "ui_etp_loaded_dataspaces", None) or [])}

    def etp_resume(self, dataspaces):
        """The saved dataspaces loaded one after the other, as the form's
        Load would (`etp_select` is a coroutine)."""
        import asyncio
        from trame.app import asynchronous

        async def _load():
            for ds in dataspaces:
                res = self.ctrl.etp_select({"dataspace": ds})
                if asyncio.iscoroutine(res):
                    await res
                # what the load wrote reaches the browser (and the door's
                # watchers) now, not at the next gesture
                self.state.flush()

        asynchronous.create_task(_load())

    def has_data(self):
        return bool(getattr(self.state, "ui_has_data", False))

    def loaded_files(self):
        return list(getattr(self.state, "ui_loaded_files", None) or [])

    def collect(self, citations=True):
        """The session document's parts.

        `citations=False` (the autosave) leaves the objects without their
        Citation, so that no query reaches the data reader: a reader query
        (any repo_query) followed by the read of a time step never read
        before makes the next render crash in the plugin. The autosave fires
        after every render, so it must never query; an explicit save may."""
        selected = list(getattr(self.state, "selected_paths", None) or [])
        mv = self._mv()
        views = []
        panels = self._collect_panels()
        for pid, title in (getattr(mv, "_titles", None) or {}).items():
            kind = mv.kind_of(pid)
            view = {"id": pid, "kind": kind, "title": title}
            if kind in ("render", "globe"):
                view.update(self._collect_render(pid, globe=kind == "globe"))
            else:
                view.update(panels.get(pid) or {})
            views.append(view)
        return {
            "sources": {
                "files": [{"name": f.get("name"), "size_mb": f.get("size_mb")}
                          for f in self.loaded_files() if not f.get("failed")],
                # the OSDU / ETP server and the dataspaces read, NEVER the
                # token: on reopening the form is prefilled and the reader
                # types the token
                "etp": self._collect_etp(),
            },
            "session": {"selected_paths": selected,
                        # the component each vector property is read by
                        "vector_components": dict(
                            getattr(self.state, "ui_vector_component", None) or {}),
                        # the calculator's recipes (a derived property is
                        # made again, not read)
                        "derived": self._collect_derived(),
                        # the kinds the reader set on properties
                        # (app/features/property_types), by uuid
                        "property_kinds": dict(getattr(self.state, "property_kinds", None) or {}),
                        "property_positions": dict(getattr(self.state, "property_positions", None) or {}),
                        # the time-depth law (app/features/time_depth_law)
                        "time_depth_law": self._law_doc(),
                        # the objects whose colour the reader changed
                        # (app/features/object_look), loaded ones only
                        "object_colors": {p: c for p, c in (getattr(self.state, "ui_object_colors", None)
                                                            or {}).items() if p in set(selected)},
                        # how the wells are drawn in the 3D views (app/features/log_tracks)
                        "wells": self._collect_wells(selected)},
            "objects": self.current_objects(self._file_objects(selected), citations=citations),
            "layout": mv.fill.layout() if hasattr(mv, "fill") else getattr(mv, "_layout", None),
            "views": views,
        }

    def _collect_wells(self, selected):
        """The wells' settings of the session: each log's way (graph, curve,
        tube; a filled graph when absent), the graphs' width as drawn, the
        markers' scale, the markers named — of the objects read only."""
        read = set(selected)
        out = {}
        modes = {p: m for p, m in (getattr(self.state, "ui_log_modes", None) or {}).items() if p in read}
        if modes:
            out["log_modes"] = modes
        labels = [p for p in (getattr(self.state, "ui_marker_labels", None) or ()) if p in read]
        if labels:
            out["marker_labels"] = labels
        for key, name in (("ui_log_width", "log_width"), ("ui_marker_scale", "marker_scale")):
            value = getattr(self.state, key, None)
            if isinstance(value, (int, float)) and value > 0:
                out[name] = float(value)
        return out

    def _restore_wells(self, wells):
        """The wells' settings back, before what is read is drawn."""
        if not isinstance(wells, dict):
            return
        modes = {str(p): str(m) for p, m in (wells.get("log_modes") or {}).items()
                 if m in ("graph", "curve", "tube") and self._known(p)}
        self.state.ui_log_modes = modes
        self.state.ui_marker_labels = [str(p) for p in (wells.get("marker_labels") or ()) if self._known(p)]
        for key, name in (("ui_log_width", "log_width"), ("ui_marker_scale", "marker_scale")):
            value = wells.get(name)
            if isinstance(value, (int, float)) and value > 0:
                self.state[key] = float(value)

    def _file_objects(self, paths):
        """`paths` without the velocity models' rows: the document brings them
        back itself (`time_depth_law`), they are no data to compare with the
        save."""
        rows = getattr(self.ctx, "time_depth_tree_rows", None)
        rows = list(rows()) if rows is not None else []
        return [p for p in paths if not node_facts.is_under(p, rows)]

    def _collect_render(self, vid, globe=False):
        s = self.state
        ctx = self.ctx
        out = {
            "eyes": list(getattr(s, f"visible_paths__{vid}", None) or []),
            "active_path": getattr(s, f"active_path__{vid}", None) or "",
            "active_by_tab": dict(getattr(s, f"active_by_tab__{vid}", None) or {}),
            "rep_style": getattr(s, f"ui_rep_style__{vid}", None) or "Surface",
            "flat_colors": bool(getattr(s, f"ui_flat_colors__{vid}", False)),
            "interaction_mode": getattr(s, f"ui_interaction_mode__{vid}", None) or "3D",
            "domain": getattr(s, f"ui_vdomain__{vid}", None) or "depth",
            "tree_layout": getattr(s, f"ui_tree_layout__{vid}", None) or "flat",
            "own_domain": list(ctx.view_domain_own(vid)) if hasattr(ctx, "view_domain_own") else [],
            "z_scale": z_scale_of(s, vid),
        }
        # hidden from the top bar's 3D views door: out of the screen, kept
        hidden = getattr(getattr(ctx, "multi_view", None), "hidden", None)
        if not globe and callable(hidden) and vid in hidden():
            out["hidden"] = True
        # the objects made see-through in this view (app/features/object_look)
        opac = getattr(ctx, "object_opacities", None)
        if opac is not None and (opac(vid) or opac(vid, True)):
            out["opacities"] = opac(vid)
            out["solid_opacities"] = opac(vid, True)
        scene = (getattr(ctx, "blockscope_scenes", None) or {}).get(vid)
        # the Globe: its code when the reader typed one, its framing, the
        # Earth's opacity
        if globe:
            g = dict(getattr(s, f"ui_globe__{vid}", None) or {})
            out["globe_state"] = {
                "epsg": g.get("epsg"), "from_data": bool(g.get("from_data", True)),
                "mode": getattr(scene, "mode", None) or g.get("mode"),
                "framed": getattr(scene, "_framed", None),
                "opacity": g.get("opacity"),
            }
        # time and realizations: the view's own step, one realization per
        # multi-realization property
        tr = dict(getattr(s, f"ui_timereal__{vid}", None) or {})
        out["time"] = {k: (tr.get("time") or {}).get(k) for k in ("index", "speed")}
        out["realizations"] = dict((getattr(s, "ui_active_realization_by_array_by_view", None)
                                    or {}).get(vid) or {})
        # per grid of the view: the slicers, the threshold chain, the NaN mask
        grids = []
        for (ivid, rep), iso in list((getattr(ctx, "grid_isolates", None) or {}).items()):
            if ivid != vid:
                continue
            g = {"rep_path": rep, "ijk": bool(getattr(iso, "_is_ijk", False)),
                 "mode": getattr(iso, "_range_mode", "full"),
                 "chain": [dict(e) for e in (iso.get_chain() or [])]}
            if g["ijk"]:
                g.update({
                    "ranges": {a: list(getattr(iso, f"_range_{a}", None) or []) for a in "ijk"},
                    "positions": {a: list(getattr(iso, f"_slices_{a}_list", None) or [])
                                  for a in "ijk"},
                    "visible": {a: list(getattr(iso, f"_slices_{a}_visible_list", None) or [])
                                for a in "ijk"},
                    "volumes": [[list(r) for r in vol]
                                for vol in (getattr(iso, "_volumes", None) or [])],
                    "volumes_visible": list(getattr(iso, "_volumes_visible", None) or []),
                })
            grids.append(g)
        for (ivid, rep), flag in list((getattr(ctx, "grid_hide_nan", None) or {}).items()):
            if ivid != vid or not (flag or {}).get("on"):
                continue
            g = next((x for x in grids if x["rep_path"] == rep), None)
            if g is None:
                g = {"rep_path": rep, "mode": "full", "chain": []}
                grids.append(g)
            g["hide_nan"] = {"auto": bool(flag.get("auto"))}
        # NaN cells shown by hand, against the default that hides them
        for ivid, rep in sorted(getattr(ctx, "grid_nan_shown", None) or ()):
            if ivid != vid:
                continue
            g = next((x for x in grids if x["rep_path"] == rep), None)
            if g is None:
                g = {"rep_path": rep, "mode": "full", "chain": []}
                grids.append(g)
            g["nan_shown"] = True
        out["grids"] = grids
        # the colour tables, raw (boot's accessor: the memos live there),
        # and the bars the reader switched off
        try:
            out["tables"] = self.ctrl.session_view_tables(vid) or []
            # the selection extracts (04-verification D2)
            out["extracts"] = self.ctrl.session_view_extracts(vid) or []
        except Exception as exc:
            print(f"[fespp] session color tables ({vid}):", exc, flush=True)
            out["tables"] = []
        out["hidden_bars"] = sorted(getattr(scene, "hidden_bars", None) or [])
        # the cards: which are open, where they were left
        out["cards"] = {
            "open": list((getattr(s, "ui_open_tools_by_view", None) or {}).get(vid) or []),
            "geometry": dict(getattr(s, f"ui_card_geometry__{vid}", None) or {}),
        }
        # and, cards as panels of the view's dock, where they stand in it
        layout = getattr(s, f"ui_card_layout__{vid}", None)
        if layout:
            out["cards"]["layout"] = layout
        cam = self._camera(vid)
        if cam is not None:
            out["camera"] = cam
        return out

    def _camera(self, vid):
        """The camera of the ParaView view of `vid`, None without one."""
        pvv = self._mv().get_pv_view(vid)
        if pvv is None:
            return None
        cam = {}
        for prop in CAMERA_PROPERTIES:
            try:
                v = getattr(pvv, prop)
                cam[prop] = list(v) if hasattr(v, "__len__") and not isinstance(v, str) else v
            except Exception as exc:
                print(f"[fespp] session camera {prop} ({vid}):", exc, flush=True)
        return cam

    def _set_camera(self, vid, cam):
        """The saved camera `cam` on the ParaView view of `vid`; a camera
        without a pivot leaves the view's own in place."""
        pvv = self._mv().get_pv_view(vid)
        if pvv is None or not cam:
            return
        for prop in CAMERA_PROPERTIES:
            if prop in cam:
                try:
                    setattr(pvv, prop, cam[prop])
                except Exception as exc:
                    print(f"[fespp] session camera {prop} ({vid}):", exc, flush=True)
        if "CameraParallelProjection" in cam:
            # the Navigation card says the projection the view came back in
            self.state[f"ui_nav_parallel__{vid}"] = bool(cam["CameraParallelProjection"])

    def _set_domain(self, vid, dom):
        """`vid` drawn in `dom` ("depth" | "time"), as its title bar's switch
        does it."""
        if dom and dom != getattr(self.state, f"ui_vdomain__{vid}", None):
            try:
                self.ctrl.view_domain(vid, dom)
            except Exception as exc:
                print(f"[fespp] session domain ({vid}):", exc, flush=True)

    def current_objects(self, paths, citations=True):
        """{path: {uuid, type, title, creation, last_update, version,
        format}} of the objects the data has now — the Citation read from
        each object's XML, ONE round trip for all of them; none with
        `citations=False` (the fields stay empty, the tree's title stands)."""
        from trame_fespp_session.format import citation_of
        tree = self._tree()
        rows = {}
        for p in paths or ():
            nid = tree.find_node_id(p) if tree is not None and p else None
            if nid is None:
                continue
            uuid = row_object.uuid_of(p.rsplit("/", 1)[-1])
            rows[p] = {"uuid": uuid, "type": tree.find_type(nid) or "",
                       "title": tree.find_title(nid) or ""}
        uuids = sorted({r["uuid"] for r in rows.values() if r["uuid"]})
        xml = {}
        src_of = getattr(self.ctx, "active_data_source", None)
        if uuids and src_of is not None and citations:
            try:
                xml = dict(zip(uuids, repo_query.object_xml(src_of.get_source(), uuids)))
            except Exception as exc:
                print("[fespp] session citations:", exc, flush=True)
        for r in rows.values():
            c = citation_of(xml.get(r["uuid"], ""))
            r.update({k: c[k] for k in ("creation", "last_update", "version", "format")})
            r["title"] = r["title"] or c["title"]
        return rows

    def candidates(self, type_, title):
        """Paths of the objects of that type and title in the data now."""
        tree = self._tree()
        asm = getattr(tree, "_data_assembly", None) if tree is not None else None
        if asm is None or not title:
            return []
        hits = []

        def walk(nid):
            t = (asm.GetAttributeOrDefault(nid, "title", None)
                 or asm.GetAttributeOrDefault(nid, "label", None))
            if t == title and (not type_ or (tree.find_type(nid) or "") == type_):
                hits.append(tree.find_path(nid))
            for i in range(asm.GetNumberOfChildren(nid)):
                walk(asm.GetChild(nid, i))

        walk(asm.GetRootNode())
        return [p for p in hits if p]

    # ------------------------------------------------------------ the API's doors
    def path_by_uuid(self, uuid):
        """The assembly path of the object of that uuid in the data now,
        or None (a document names objects by uuid: format.resolve_uuids)."""
        tree = self._tree()
        nid = tree.find_node_id_by_uuid(uuid) if tree is not None else None
        return tree.find_path(nid) if nid is not None else None

    def load_file(self, path):
        """An EPC named by a server path (the page's query, a document):
        read now and recorded as the import door records a dropped file,
        so that the session's expected files see it."""
        from fespp_on_trame.engine import session_query as sq
        from fespp_on_trame.engine.io.upload_endpoint import record_file
        name = os.path.basename(path)
        # under the server's open directory only, as the page's query
        try:
            path = sq.server_path(path)
        except sq.QueryError as exc:
            self.state.load_error = str(exc)
            return False
        if not os.path.isfile(path):
            self.state.load_error = f"{name}: no such file on the server."
            return False
        before = len((getattr(self.state, "assembly_xml", None) or ""))
        report = self.ctrl.load_epc_file(path) or {}
        size_mb = os.path.getsize(path) / (1024.0 * 1024.0)
        added = len((getattr(self.state, "assembly_xml", None) or "")) - before
        record_file(self.state, name, size_mb, max(0, added), report.get("failure"))
        return not report.get("failure")

    def _reset(self, say):
        """A session emptied before a document applies (`reset`): nothing
        read any more, every 3D view's eyes closed. Its panels stay open —
        they are the browser's to close — and say so."""
        mv = self._mv()
        self.ctrl.session_select([], replace=True)
        for vid in mv.view_ids():
            self.state[f"visible_paths__{vid}"] = []
            self.ctrl.on_eye_changed(vid, [])
        panels = [p for p in (mv.html_views() or []) if mv.kind_of(p) != "render"]
        say("ok", "Session emptied: nothing read, every view's eyes closed"
                  + (f"; {len(panels)} panel(s) left open." if panels else "."))

    # ------------------------------------------------------------ restore
    def _under_models_uuids(self, doc):
        """`doc` speaking of its velocity models under the uuids they have now."""
        renamed = getattr(self.server.context, "time_depth_tree_renamed", None)
        renamed = renamed() if renamed is not None else {}
        if not renamed:
            return doc
        text = json.dumps(doc)
        for old, new in renamed.items():
            text = text.replace(old, new)
        return json.loads(text)

    def restore(self, doc, say):
        """Put a session document back, step by step; `say(level, text)`
        writes each outcome to the door's report.

        A PARTIAL document (`format.document`: the API's) applies only the
        groups it holds — an absent group leaves that part of the session
        alone, a present one is the whole truth of its part (`selected_paths`
        given = the session's reads, nothing else); `reset` empties the
        session first. A file (not partial) adds to what is loaded, as the
        door always did."""
        from trame_fespp_session import format as sf
        mv = self._mv()
        if hasattr(mv, "fill"):
            mv.fill.leave()
        partial = bool(doc.get("partial"))
        print(f"[fespp] journal session: a document put back ({'partial' if partial else 'a file'}:"
              f" {', '.join(sorted(k for k in doc if k != 'partial'))})", flush=True)
        # the objects a document names by uuid: their paths in the data now
        doc, unknown = sf.resolve_uuids(doc, self.path_by_uuid)
        if unknown:
            say("error", f"{len(unknown)} uuid(s) are not in the loaded data: "
                         + ", ".join(unknown[:5]) + (" …" if len(unknown) > 5 else ""))
        if doc.get("reset"):
            self._reset(say)
        session = doc.get("session") or {}

        # 0. the Assistant's Undo spoke of the views this restore overwrites
        #    — under the SAME ids (`live[i]` below): it would put the old
        #    eyes, filters and colour tables back over the restored ones
        self._drop_assistant_undo()

        # 1. the Z scale, then what is read — born hidden: each view's eyes
        #    say where it shows. Derived properties come after their recipes.
        if session.get("z_scale"):
            # every view: an older document holds one value for all.
            # Applied now, cameras and every display included, not merely
            # written (D25: a reused view kept the old one on its grid)
            now = getattr(self.ctrl, "set_zscale_now", None)
            if callable(now):
                now(session["z_scale"])
        # the kinds set on properties, before anything reads one (a velocity
        # of the data is read by its kind)
        if isinstance(session.get("property_kinds"), dict):
            self.state.property_kinds = {str(k): str(v) for k, v in session["property_kinds"].items()}
        if isinstance(session.get("property_positions"), dict):
            self.state.property_positions = {str(k): str(v) for k, v in session["property_positions"].items()}
        # the velocity models before what is read: a session ticked and showed
        # them, and they are in the tree under the uuids it saved once written
        # (app/features/time_depth_tree); session-wide, before the views: they
        # rescale the unpinned tables
        if session.get("time_depth_law"):
            ctx = self.server.context
            restore_law = getattr(ctx, "time_depth_law_restore", None)
            if restore_law is not None:
                restore_law(session["time_depth_law"])
            in_tree = getattr(ctx, "time_depth_tree_start", None)
            write = getattr(ctx, "time_depth_tree_write", None)
            if in_tree is not None and write is not None:
                in_tree()
                write()
                doc = self._under_models_uuids(doc)
                session = doc.get("session") or {}
        # the wells' settings before what is read is drawn
        if "wells" in session:
            self._restore_wells(session.get("wells"))
        selected = list(session.get("selected_paths") or ())
        paths = [p for p in selected if not str(p).startswith("derived://")]
        known = {p for p in paths if self._known(p)}
        kept, dropped = sf.keep_known(paths, known)
        if dropped:
            say("error", f"{len(dropped)} object(s) of the session are not in the"
                         " loaded data and were skipped.")
        if partial and "selected_paths" in session:
            self.ctrl.session_select(kept, replace=True)
            say("ok", f"{len(kept)} object(s) read.")
        elif not partial:
            self.ctrl.session_select(kept)
            say("ok", f"{len(kept)} object(s) read.")
        # a velocity model of the data: read again now that its velocity is
        # (app/features/time_depth_law)
        again = getattr(self.server.context, "time_depth_law_restore_data", None)
        if again is not None:
            again()
        set_color = getattr(self.server.context, "object_set_color", None)
        for path, color in (session.get("object_colors") or {}).items():
            if set_color is not None and self._known(path):
                set_color(path, color)
        for path, comp in (session.get("vector_components") or {}).items():
            if self._known(path):
                try:
                    self.ctrl.set_vector_component(path, comp)
                except Exception as exc:
                    say("warn", f"The component of a vector property not restored ({exc}).")
        # 2. the calculator's recipes, inputs first, then the derived
        #    properties the session read
        made = self._restore_derived(session.get("derived") or [], say)
        derived_read = [p for p in selected if str(p).startswith("derived://") and p in made]
        if derived_read:
            self.ctrl.session_select(derived_read)

        # 3. the 3D views: the new session's first 3D view takes the first
        #    saved one, the others are created. A partial document without
        #    views leaves them, with `views: []` closes every eye
        if partial and "views" not in doc:
            return
        # a document's view may carry no id (a file's always does): one by
        # its place, for the mapping and the layout below
        views = [dict(v, id=v.get("id") or f"doc_view_{i}")
                 for i, v in enumerate(doc.get("views") or ())]
        # a document older than the one Statistics view
        views, layout = session_older.current_views(views, doc.get("layout"))
        if partial and not views:
            for vid in mv.view_ids():
                self.state[f"visible_paths__{vid}"] = []
                self.ctrl.on_eye_changed(vid, [])
            say("ok", "Every view's eyes closed.")
            return
        # the views a document names of a kind that is gone: the rest opens
        views, layout, gone = session_older.without_removed_kinds(views, layout)
        for v in gone:
            say("warn", f"{v['title']}: not restored, the Statistics view now draws"
                        " the histograms and the cross-plots.")
        saved = [v for v in views if v.get("kind") in ("render", "globe")]
        live = [p for p in mv.view_ids() if mv.kind_of(p) == "render"]
        # a view's `place` ("right" | "below") splits the view that precedes
        # it in the document, once that one is back (else the active panel)
        before = {v["id"]: p["id"] for p, v in zip(views, views[1:])}
        mapping = {}
        for v in saved:
            kind = v["kind"]
            if kind == "render" and live:
                vid = live.pop(0)
            else:
                vid = mv.add_view(kind=kind, direction=v.get("place"),
                                  reference_panel_id=mapping.get(before.get(v["id"])))
            mapping[v["id"]] = vid
        for v in saved:
            self._set_view_zscale(mapping[v["id"]], v, session)
            self._restore_render(mapping[v["id"]], v, say)
        say("ok", f"{len(saved)} 3D view(s) restored.")

        # 4. the analysis panels, in the order their inputs impose
        panels = [v for v in views if v.get("kind") not in ("render", "globe")]
        mapping.update(self._restore_panels(panels, mapping, say, before))

        # 5. every panel's title, then the layout when every panel it places
        #    is back (the template names follow the ids)
        for v in views:
            new = mapping.get(v.get("id"))
            if new and v.get("title"):
                mv.retitle(new, v["title"])
        if layout and set(sf.layout_ids(layout)) <= set(mapping):
            try:
                new = sf.remap_ids(layout, sf.panel_mapping(mapping))
                mv.restore_layout(new)
                mv._layout = new
            except Exception as exc:
                say("warn", f"The layout could not be put back ({exc}); the panels are tabs.")
        elif layout:
            missing = [i for i in sf.layout_ids(layout) if i not in mapping]
            say("warn", f"The layout places {len(missing)} panel(s) that could not be"
                        " restored: the panels come back as tabs.")

    def _drop_assistant_undo(self):
        """Empty the Assistant's undo stack (widgets/assistant, built by
        `__main__._wire_assistant`).

        Its Undo button, and an undo asked in the chat, must only act on what
        was done in THIS session. The conversation stays when the controller
        can keep it (`clear_undo`), else it goes with the stack (`clear`).
        No assistant (switched off, or not built): nothing to drop."""
        assistant = getattr(self.ctx, "assistant", None)
        if assistant is None:
            return
        drop = getattr(assistant, "clear_undo", None) or getattr(assistant, "clear", None)
        if drop is None:
            print("[fespp] session: the assistant has neither clear_undo nor clear;"
                  " its Undo still acts on the views before the restore", flush=True)
            return
        try:
            drop()
        except Exception as exc:
            print("[fespp] session: the assistant's undo stack could not be dropped:",
                  exc, flush=True)

    # ------------------------------------------------------------ panels
    def _collect_panels(self):
        """{panel id: what the panel keeps} for every analysis panel, by
        kind."""
        s, mv = self.state, self._mv()
        out = {}
        for pid in list((getattr(mv, "_titles", None) or {})):
            kind = mv.kind_of(pid)
            if kind == "render":
                continue
            p = {}
            if kind == "welllog":
                p = {"wells": list(s.ui_welllog_wells or []),
                     "synth": list(s.ui_welllog_synth or []),
                     **{k: s[f"welllog_{k}__{pid}"] for k in (
                         "dropped", "zoom", "flatten", "cutoffs",
                         "zones_open", "synth_open", "tree_open", "tree_layout",
                         "align", "markers_off", "card_layout")}}
            elif kind == "reconcile":
                r = dict(s.ui_reconcile or {})
                p = {"logs": list(s.ui_reconcile_logs or []),
                     "dropped": list(s.ui_reconcile_dropped or []),
                     "pairs": list(r.get("pairs") or []), "auto": bool(r.get("auto", True)),
                     "step": r.get("step"), "tree_open": _reconcile_cards(s, s[f"reconcile_tree_open__{pid}"])}
            elif kind == "compare":
                try:
                    p = dict(self.ctrl.session_compare_state() or {})
                except Exception as exc:
                    print("[fespp] session compare:", exc, flush=True)
                from fespp_on_trame.engine import compare_tree, tree_families
                p["tree_open"] = tree_families.open_cards(
                    s[f"compare_tree_open__{pid}"], compare_tree.families_present(s.ui_compare_tree_xml or ""),
                    compare_tree.card_names())
                p["tree_layout"] = s.ui_compare_tree_layout or "kind"
            elif kind == "xml":
                p = {"tabs": list(s[f"xml_tabs__{pid}"] or []),
                     "tab": int(s[f"xml_tab__{pid}"] or 0)}
            elif kind == "stratigraphy":
                # the rank THIS panel chose ("" = none: it shows the first)
                p = {"column": (s.ui_strati_selected_by_view or {}).get(pid) or "",
                     "unit": (s.ui_strati_titles or {}).get(pid)}
            elif kind == "assistant":
                # the panel and its place only: the conversation spoke of
                # the objects of THIS session, the restored one starts anew
                p = {}
            out[pid] = p
        return out

    def _law_doc(self):
        doc = getattr(self.server.context, "time_depth_law_doc", None)
        return doc() if doc is not None else {}

    def _collect_derived(self):
        """The calculator's recipes: a derived property is made again on
        restore, never saved as values."""
        store = getattr(self.ctx, "derived_store", None)
        keep = ("type", "name", "rep_path", "expression", "uom", "prop_kind",
                "role", "source", "quantile", "inputs")
        return [{k: d.get(k) for k in keep if d.get(k) is not None}
                for d in (store.all_defs() if store is not None else [])]

    def _restore_derived(self, recipes, say):
        """The calculator's recipes, a recipe after the recipes it reads
        (a rename moves a recipe to the end: the saved order is not enough).
        Returns the paths of the ones made."""
        from fespp_on_trame.engine import derived_props
        store = getattr(self.ctx, "derived_store", None)
        tree = self._tree()
        made = set()
        if store is None or not recipes:
            return made
        # a recipe binds its identifiers to the properties READ on its grid:
        # its inputs are read first (born hidden), whether or not the session
        # itself showed them
        inputs = sorted({i for r in recipes for i in (r.get("inputs") or ())
                         if not str(i).startswith("derived://") and self._known(i)}
                        | {r.get("source") for r in recipes
                           if r.get("source") and self._known(r.get("source"))})
        if inputs:
            self.ctrl.session_select(inputs)
        # the list of what is read (`ui_loaded_array_paths`, which a recipe
        # binds against) is written by the load's watchers: run them now
        self.state.flush()
        pending = list(recipes)
        for _round in range(len(pending) + 1):
            if not pending:
                break
            later = []
            for r in pending:
                path = derived_props.path_for(r.get("rep_path"), r.get("name"))
                needs = [i for i in r.get("inputs") or () if str(i).startswith("derived://")]
                if any(i not in made for i in needs):
                    later.append(r)
                    continue
                if store.get(path) is not None:
                    made.add(path)          # already there (restored in the same session)
                    continue
                if not self._known(r.get("rep_path")):
                    say("warn", f"Derived property {r.get('name')}: its grid is not in the data — skipped.")
                    continue
                try:
                    if r.get("type") == "percentile":
                        err, _d = store.create_percentile(
                            self.state, tree, r["rep_path"], r.get("source"), r.get("quantile"),
                            name=r.get("name"), uom=r.get("uom") or "")
                    else:
                        err, _d = store.create(
                            self.state, tree, r["rep_path"], r["name"], r.get("expression") or "",
                            uom=r.get("uom") or "", prop_kind=r.get("prop_kind") or "ContinuousProperty",
                            role=r.get("role") or "")
                except Exception as exc:
                    print(f"[fespp] session derived {r.get('name')!r}:", exc, flush=True)
                    err = str(exc)
                if err:
                    say("warn", f"Derived property {r.get('name')} not restored: {err}")
                else:
                    made.add(path)
            if len(later) == len(pending):
                for r in later:
                    say("warn", f"Derived property {r.get('name')}: a property it reads is missing — skipped.")
                break
            pending = later
        store.publish(self.state)
        if made:
            say("ok", f"{len(made)} derived propert{'y' if len(made) == 1 else 'ies'} of the calculator.")
        return made

    def _restore_panels(self, panels, mapping, say, before=None):
        """Each analysis panel reopened through the gesture the UI uses (the
        openers register what a bare panel would lack) and given back what
        it held. A panel with a `place` is split from the view before it in
        the document (`before`: {saved id: the id before it}), once that one
        is back. Returns {saved id: new id}."""
        from fespp_on_trame.app.views.views_config import VIEW_KINDS
        mv = self._mv()
        out = {}
        known = self._known
        before = before or {}

        def ok_path(p):
            return known(p) or str(p).startswith("derived://")

        def opened(kind, opener, *args):
            before = set(mv.panel_ids_of_kind(kind) or [])
            res = opener(*args)
            now = list(mv.panel_ids_of_kind(kind) or [])
            new = [p for p in now if p not in before]
            return res if isinstance(res, str) and res else (new[0] if new else (now[0] if now else None))

        order = ("welllog", "reconcile", "compare", "xml", "stratigraphy",
                 "calculator", "health", "values", "timedepth", "assistant")
        rank = {k: i for i, k in enumerate(order)}
        panels = sorted(panels, key=lambda v: rank.get(v.get("kind"), len(order)))
        from fespp_on_trame.app.core import previews
        for v in panels:
            kind = v.get("kind")
            # a view not offered on this server is not reopened (the
            # assistant says so through its own door, below)
            if kind != "assistant" and not previews.offered(kind):
                continue
            title = v.get("title") or (VIEW_KINDS.get(kind) or {}).get("label") or kind
            prev = before.get(v.get("id"))
            try:
                with mv.placed(v.get("place"), out.get(prev) or mapping.get(prev)):
                    pid = self._restore_panel(kind, v, opened, ok_path, say)
            except Exception as exc:
                say("warn", f"{title}: not restored ({exc}).")
                continue
            if pid:
                out[v["id"]] = pid
            else:
                say("warn", f"{title}: not restored.")
        if out:
            say("ok", f"{len(out)} panel(s) restored.")
        return out

    def _restore_panel(self, kind, v, opened, ok_path, say):
        """Reopen one panel of that kind and give it back its saved state;
        returns its new id, or None when it cannot come back."""
        s, c, mv = self.state, self.ctrl, self._mv()
        if kind == "welllog":
            s.ui_welllog_wells = [p for p in v.get("wells") or () if ok_path(p)]
            s.ui_welllog_synth = list(v.get("synth") or [])
            pid = opened("welllog", c.open_welllog)
            # the wells' watchers run NOW: a well that has just arrived brings
            # every curve back, which would undo the curves set aside below
            s.flush()
            for k in ("dropped", "zoom", "flatten", "cutoffs", "zones_open", "synth_open", "tree_open",
                      "tree_layout", "align", "markers_off", "card_layout"):
                if k in v:
                    s[f"welllog_{k}__{pid}"] = v[k]
            c.refresh_welllog()
            return pid
        if kind == "reconcile":
            s.ui_reconcile_logs = [p for p in v.get("logs") or () if ok_path(p)]
            s.ui_reconcile_dropped = list(v.get("dropped") or [])
            pid = opened("reconcile", c.open_reconcile)
            s[f"reconcile_tree_open__{pid}"] = _reconcile_cards(s, v.get("tree_open"))
            if not v.get("auto", True) and v.get("pairs"):
                c.reconcile_set_pairs([p for p in v["pairs"] if ok_path(p.get("prop"))])
            if v.get("step"):
                c.reconcile_compute(v["step"])
            return pid
        if kind == "compare":
            saved = dict(v)
            saved["items"] = [i for i in v.get("items") or () if ok_path(i.get("path"))]
            gone = len(v.get("items") or ()) - len(saved["items"])
            if gone:
                say("warn", f"{gone} row(s) of the Statistics view name what is not in the data — skipped.")
            if "parts" in v:
                saved["parts"] = [p for p in v["parts"] or () if ok_path(p)]
            c.session_compare_restore(saved)
            pid = (mv.panel_ids_of_kind("compare") or [None])[0]
            if pid and "tree_open" in v:
                from fespp_on_trame.engine import compare_tree, tree_families
                s[f"compare_tree_open__{pid}"] = tree_families.open_cards(
                    v["tree_open"], compare_tree.families_present(s.ui_compare_tree_xml or ""),
                    compare_tree.card_names())
            if pid and v.get("tree_layout"):
                c.compare_tree_layout(v["tree_layout"])
            return pid
        if kind == "xml":
            pid = mv.add_view(kind="xml")
            s[f"xml_tabs__{pid}"] = list(v.get("tabs") or [])
            c.xml_select_tab(int(v.get("tab") or 0), pid)
            return pid
        if kind == "values":
            return mv.add_view(kind="values")
        if kind == "timedepth":
            return opened("timedepth", c.open_time_depth)
        if kind == "stratigraphy":
            pid = opened("stratigraphy", c.open_stratigraphy)
            if v.get("column"):
                chosen = dict(s.ui_strati_selected_by_view or {})
                chosen[pid] = v["column"]
                s.ui_strati_selected_by_view = chosen
            if v.get("unit"):
                titles = dict(s.ui_strati_titles or {})
                titles[pid] = v["unit"]
                s.ui_strati_titles = titles
            return pid
        if kind == "calculator":
            return opened("calculator", c.open_calculator)
        if kind == "health":
            return opened("health", c.open_health)
        if kind == "assistant":
            # back empty (the conversation is not saved), through the door's
            # own opener: an assistant switched off (FESPP_ASSISTANT=0)
            # opens nothing, and the report says the panel was not restored
            return opened("assistant", c.open_assistant)
        return None

    def _set_view_zscale(self, vid, v, session):
        """The exaggeration of a 3D view, before what it draws comes back;
        said nowhere, it keeps its own."""
        z = v.get("z_scale") or (session or {}).get("z_scale")
        now = getattr(self.ctrl, "set_zscale_now", None)
        if z and callable(now):
            now(z, vid)

    def _restore_render(self, vid, v, say):
        """Give the 3D view `vid` back what the saved view `v` held, in the
        order the steps depend on each other."""
        s, c = self.state, self.ctrl
        name = v.get("title") or vid

        def attempt(what, fn, *args):
            try:
                return fn(*args)
            except Exception as exc:
                say("warn", f"{name}: {what} not restored ({exc}).")
                return None

        # 1. the eyes (the reads were done before, born hidden) — a view
        #    paragraph without them keeps the view's own
        eyes = [p for p in v.get("eyes") or () if self._known(p) or self._made(p)]
        if "eyes" in v:
            s[f"visible_paths__{vid}"] = eyes
            c.on_eye_changed(vid, eyes)
        else:
            eyes = list(getattr(s, f"visible_paths__{vid}", None) or [])
        # 2. the Globe: its scene now (its door builds it a turn later), the
        #    eyes replayed onto it, before its code, framing and camera
        if v.get("kind") == "globe":
            g = v.get("globe_state") or {}
            attempt("the Globe", c.globe_build, vid)
            if g.get("epsg") and not g.get("from_data", True):
                attempt("the Globe's EPSG code", c.globe_epsg, g["epsg"], vid)
            if g.get("mode"):
                attempt("the Globe's framing", c.globe_frame, g["mode"], vid, g.get("framed"))
            if g.get("opacity") is not None:
                attempt("the Earth's opacity", c.globe_opacity, g["opacity"], vid)
        # 3. realizations (one eye pass for all), then the view's time step
        reals = {p: i for p, i in (v.get("realizations") or {}).items() if self._known(p)}
        if reals:
            by_view = dict(getattr(s, "ui_active_realization_by_array_by_view", None) or {})
            by_view[vid] = {**(by_view.get(vid) or {}), **reals}
            s.ui_active_realization_by_array_by_view = by_view
            c.on_eye_changed(vid, eyes)
        t = v.get("time") or {}
        if t.get("index") is not None:
            attempt("the time step", c.time_index, int(t["index"]), vid)
        if t.get("speed"):
            attempt("the play speed", c.time_speed, t["speed"], vid)
        # 4. each grid: slicers, thresholds, NaN mask — the cards act on the
        #    grid of the Reservoir tab, so the tab points at each in turn
        by_tab = dict(v.get("active_by_tab") or {})
        for g in v.get("grids") or ():
            if g.get("nan_shown") and g.get("rep_path") and hasattr(self.ctx, "grid_nan_shown"):
                # its NaN cells shown by hand: the default leaves them
                self.ctx.grid_nan_shown.add((vid, g["rep_path"]))
            if g.get("nan_shown") and not (g.get("hide_nan") or g.get("chain")
                                           or g.get("mode", "full") != "full"):
                continue
            self._restore_grid(vid, g, name, say)
        # the objects made see-through in this view
        set_opacity = getattr(self.ctx, "object_set_opacity", None)
        painted = v.get("opacities") or {}
        # an older document holds one opacity per object, whatever paints it
        for solid, opacities in ((False, painted), (True, v.get("solid_opacities", painted))):
            for path, op in opacities.items():
                if set_opacity is not None and self._known(path):
                    set_opacity(vid, path, op, solid)
        # 5. the colour tables, after everything that rescales them
        if v.get("tables"):
            attempt("the color tables", c.session_restore_view_tables, vid, v["tables"])
        # the selection extracts, made again on their grids (an older
        # session without the key leaves the view's own alone)
        if "extracts" in v:
            attempt("the selection extracts", c.session_restore_extracts, vid, v["extracts"])
        scene = (getattr(self.ctx, "blockscope_scenes", None) or {}).get(vid)
        for array in v.get("hidden_bars") or ():
            if scene is not None:
                scene.set_bar_visible(array, False)
        # 6. the active nodes as saved (the grids moved the Reservoir tab)
        s[f"active_by_tab__{vid}"] = {k: p for k, p in by_tab.items() if self._known(p)}
        if self._known(v.get("active_path")):
            s[f"active_path__{vid}"] = v["active_path"]
        c.set_rep_style(vid, v.get("rep_style") or "Surface")
        c.set_flat_colors(vid, bool(v.get("flat_colors")))
        if (v.get("interaction_mode") or "3D") != "3D":
            c.view_interaction_mode(vid, v["interaction_mode"])
        # 7. the cards: open as they were, where they were left (the place a
        #    card takes is read when it mounts: a view that already existed
        #    takes it at the next page load)
        cards = v.get("cards") or {}
        if cards.get("open") is not None:
            # through the cards' one writer (app/scene/cards); a selection
            # tool is a MODE as much as a lit button: its mode variable
            # follows the open list, as toggle_tool sets it (D29)
            from fespp_on_trame.app.scene.cards import Cards
            from fespp_on_trame.app.views.tools_config import MODE_TOOLS
            from fespp_on_trame.app.core import previews
            writer = getattr(self.ctx, "cards", None) or Cards(s, MODE_TOOLS)
            # a card not offered on this server (a preview switched off)
            # stays closed; the Values and time-depth cards of an older
            # document are views now
            writer.set(vid, [k for k in cards["open"] if previews.offered(k) and k not in ("attributes", "timedepth")])
            writer.sync_modes(vid)
            if "attributes" in cards["open"]:
                self.ctrl.open_values()
            if "timedepth" in cards["open"]:
                self.ctrl.open_time_depth()
        if cards.get("geometry"):
            s[f"ui_card_geometry__{vid}"] = dict(cards["geometry"])
        if cards.get("layout"):
            s[f"ui_card_layout__{vid}"] = cards["layout"]
        # 8. the domain, then the camera, last: everything above may frame
        #    the view
        self._set_domain(vid, v.get("domain"))
        if v.get("own_domain") and hasattr(self.ctx, "view_domain_keep_own"):
            self.ctx.view_domain_keep_own(vid, v["own_domain"])
        self.state[f"ui_tree_layout__{vid}"] = v.get("tree_layout") or ("kind" if v.get("tree_kind") else "flat")
        self._set_camera(vid, v.get("camera") or {})
        sch = getattr(self.ctx, "render_scheduler", None)
        if sch is not None:
            sch.mark_dirty(vid)
            sch.flush()
        hide = getattr(getattr(self.ctx, "multi_view", None), "hide_panel", None)
        if v.get("hidden") and callable(hide):
            hide(vid)

    def _restore_grid(self, vid, g, name, say):
        """Replay one grid's slicers, threshold chain and NaN mask in view
        `vid`."""
        s, c = self.state, self.ctrl
        rep = g.get("rep_path")
        if not self._known(rep):
            say("warn", f"{name}: a grid it cut or thresholded is not in the data — skipped.")
            return
        s[f"active_by_tab__{vid}"] = {**(s[f"active_by_tab__{vid}"] or {}), "reservoir": rep}
        try:
            if g.get("ijk") and g.get("mode", "full") != "full":
                for a in "ijk":
                    if (g.get("ranges") or {}).get(a):
                        c.slicer_range([a, g["ranges"][a]], vid)
                for a in "ijk":
                    if (g.get("positions") or {}).get(a):
                        c.slicer_positions([a, g["positions"][a]], vid)
                    if (g.get("visible") or {}).get(a):
                        c.slicer_visibility([a, g["visible"][a]], vid)
                if g.get("volumes"):
                    c.slicer_volumes(g["volumes"], vid)
                    if g.get("volumes_visible"):
                        c.slicer_volumes_visible(g["volumes_visible"], vid)
                c.slicer_mode(g["mode"], vid)
        except Exception as exc:
            say("warn", f"{name}: the slicers of a grid not restored ({exc}).")
        # the threshold chain, replayed parent first: names are regenerated,
        # so the saved ones are mapped to the new ones
        renamed = {}
        for e in g.get("chain") or ():
            try:
                parent = renamed.get(e.get("parent_name")) if e.get("parent_name") else None
                c.threshold_add([e["array"], parent], vid)
                iso = (getattr(self.ctx, "grid_isolates", None) or {}).get((vid, rep))
                new = (iso.get_chain() or [])[-1]["name"]
                renamed[e["name"]] = new
                c.threshold_range([new, [e["low"], e["high"]]], vid)
                if not e.get("visible", True):
                    c.threshold_visible([new, False], vid)
            except Exception as exc:
                say("warn", f"{name}: threshold on {e.get('array')} not restored ({exc}).")
        if g.get("hide_nan"):
            try:
                c.session_hide_nan(vid, rep, bool(g["hide_nan"].get("auto")))
            except Exception as exc:
                say("warn", f"{name}: Hide NaN cells not restored ({exc}).")
