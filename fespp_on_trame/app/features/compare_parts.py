"""What the rows of the Statistics view follow beside its selection.

* The parts of a grid (`ui_compare_parts`, engine/stats_supports): a
  sub-representation, a blocked wellbore, a selection extract whose eye is open
  in the view's tree. An extract is no leaf of that tree but a row of the
  session (`ui_compare_session_rows`), under the view that made it; it leaves
  the parts when it is deleted there.
* What moves elsewhere: a part's rows follow the reads (`_on_stats_inputs`); a
  3D view's rows follow what the 3D view draws, which no state says
  (`view_cuts`), once a burst of gestures is over.
* "Stats", the door of the data trees: the property joins the selection.
"""
from fespp_on_trame.engine import compare_tree
from fespp_on_trame.engine import stats_supports

# seconds of quiet after a gesture on a 3D view before its rows are read again:
# a slider dragged or a player running moves what the view draws at each step,
# and those rows read every cell it draws
_CUTS_QUIET = 0.4


def register(core, *, _compare, _compare_add, _compare_parts,
             _property_or_note, _rebuild_compare_tree, _refresh_compare,
             _refresh_compare_rows, _set_compare_parts,
             _sync_compare_tree_selection):
    """Wire the section's controllers and watchers; the rest of the app calls
    nothing of it directly."""
    # the shared services (app/core/context.Core)
    state = core.state
    controller = core.controller
    tree = core.tree
    batcher = core.batcher
    _mv = core.mv

    def _publish_session_rows():
        """Every 3D view's extracts in the docked tree, named with their view:
        an extract's eye adds its rows under the items of its grid, deleting it
        is its 3D view's business and takes those rows with it."""
        mv = _mv()
        parts = _compare_parts()
        rows, seen = [], set()
        for panel in (getattr(state, "fespp_render_panels", None) or []):
            vid = panel.get("id") if isinstance(panel, dict) else None
            if not vid:
                continue
            vtitle = (mv.title_of(vid) if mv is not None else "") or vid
            for r in (getattr(state, f"ui_session_rows__{vid}", None) or []):
                path = r.get("path")
                if r.get("kind") != "extract" or not path or path in seen:
                    continue
                seen.add(path)
                rows.append(dict(r, parent=compare_tree.extract_folder(tree, path),
                                 title=f"{r.get('title') or path} — {vtitle}",
                                 visible=path in parts, removable=False,
                                 eye_titles=["Add this extract's rows under the properties of its grid",
                                             "Take this extract's rows out"]))
        kept = [p for p in parts if not stats_supports.is_extract(p) or p in seen]
        if kept != parts:
            _set_compare_parts(kept)
        if rows != list(getattr(state, "ui_compare_session_rows", None) or []):
            state.ui_compare_session_rows = rows

    def _part_rows_stale():
        """Whether a row of an extract says another name than the extract's own
        (it was renamed since the rows were read)."""
        for row in (getattr(state, "ui_compare_rows", None) or {}).values():
            part = row.get("support") or ""
            if (stats_supports.is_extract(part)
                    and row.get("support_label") != stats_supports.part_label(tree, part)):
                return True
        return False

    @core.lifecycle.on("session_rows")
    def _session_rows_follow(vid):
        """Published at the end of every eye pass, too: an eye of the view."""
        folders = {compare_tree.extract_folder(tree, p) for p in stats_supports.session_extracts()}
        if folders != _compare["extract_folders"]:
            _rebuild_compare_tree()
        _publish_session_rows()
        # an extract of the rows renamed (its pencil): the rows take the new name
        if _part_rows_stale():
            _refresh_compare()
        _cuts_moved()

    @state.change("ui_compare_parts", "fespp_render_panels", "ui_compare_tree_xml")
    def _on_parts_rows(**_):
        _publish_session_rows()
        _sync_compare_tree_selection()

    @controller.set("compare_session_eye")
    def compare_session_eye(ev, view_id):
        """The eye of an extract in the docked tree."""
        path = str((ev if isinstance(ev, dict) else {}).get("path") or "")
        if stats_supports.is_extract(path):
            parts = _compare_parts()
            _set_compare_parts([p for p in parts if p != path] if path in parts else parts + [path])

    @controller.set("add_to_stats")
    def add_to_stats(path):
        """"Stats", from a data tree (`_compare_add`)."""
        if path and _property_or_note(path, "a statistics row"):
            _compare_add([{"path": path}])

    @state.change("ui_compare_parts", "fespp_render_panels", "ui_active_realization_by_array_by_view",
                  "ui_loaded_array_paths", "ui_loaded_rep_paths")
    def _on_stats_inputs(**_):
        _refresh_compare()

    def _cuts_moved():
        if _compare["views"]:
            batcher.schedule("compare:cuts", _refresh_compare_rows, delay=_CUTS_QUIET)

    @core.lifecycle.on("view_cuts")
    def _on_view_cuts(vid):
        _cuts_moved()

    @state.change("ui_per_view_time_pulse")
    def _on_view_time(**_):
        _cuts_moved()
