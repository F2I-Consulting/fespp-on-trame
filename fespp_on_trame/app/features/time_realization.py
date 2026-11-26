"""Per-view TIME + REALIZATION application: the view's time (view.ViewTime
— this view alone, no TimeKeeper write) and the realization of each
multi-realization property (per (view, MR property), rendered through the
'<name>_real_<idx>' array via _real_idx_for). The card asking for them is
the shared slicer card (app/features/timereal_slicer; the PO, 29/10); the
controllers here serve the assistant and a session read back, and the
state `ui_timereal__<vid>` the assistant.

(Moved out of app/boot, overhaul slice 10.)"""
from paraview import simple as pvsimple
from fespp_on_trame.app.views import per_view_state


def register(core, *, _eye_driven_colors, _push_colormap_state,
             on_eye_changed):
    """Wire the section's controllers and watchers; hands back what the
    rest of the app calls: push (the old state), apply_time, time_index,
    time_values, steps (the positions a view steps through), specs,
    set_realization, after_push (the card's hook)."""
    # the shared services (app/core/context.Core)
    state = core.state
    controller = core.controller
    tree = core.tree
    scheduler = core.scheduler
    lifecycle = core.lifecycle
    _mv = core.mv
    # Per-view TIME + REALIZATION controls (widgets/timereal): a per-panel
    # TimeControl (view.ViewTime — this view alone, no TimeKeeper
    # write) and RealizationPicker (per-(view, MR property) realization,
    # rendered through the '<name>_real_<idx>' array via _real_idx_for).
    _view_time_idx = {}   # vid -> index into the time keeper's values
    _view_speed = {}      # vid -> play speed factor
    _play_tasks = {}      # vid -> asyncio play task
    _after_push = []      # called with vid after the state is pushed (the card)

    @lifecycle.on("view_closed")
    def _forget_time_of(vid):
        """A closed view's time step goes, and its playback stops."""
        _view_time_idx.pop(vid, None)
        task = _play_tasks.pop(vid, None)
        if task is not None and not task.done():
            task.cancel()

    def _time_values():
        try:
            return [float(t) for t in
                    (pvsimple.GetTimeKeeper().TimestepValues or [])]
        except Exception:
            return []

    _series_steps = {}   # (TimeSeries uuid, title, realization) -> its time indices, None unknown

    @lifecycle.on("new_data")
    def _forget_series_steps():
        _series_steps.clear()

    def _steps_of_series(key):
        """The time indices of one series, read once from the XML of the
        properties designating its TimeSeries; None when they cannot be."""
        if key in _series_steps:
            return _series_steps[key]
        from fespp_on_trame.engine import repo_query
        from fespp_on_trame.engine import time_realization as _tr
        uuid, title, realization = key
        steps = None
        try:
            source = core.active_data_source.get_source()
            related = repo_query.object_relations(source, uuid).get("source")
            members = _tr.series_members(related, title)
            xmls = repo_query.object_xml(source, [m["uuid"] for m in members])
            steps = _tr.series_steps(xmls, realization) or None
        except Exception as exc:
            print(f"[fespp] time steps of {title!r} not read ({exc!r}): every step kept", flush=True)
        _series_steps[key] = steps
        print(f"[fespp] time steps of {title!r}: {steps}", flush=True)
        return steps

    def _steps(vid):
        """The positions in the session's time steps at which what `vid`
        colours by changes: the steps of the time series it colours by."""
        from fespp_on_trame.engine import element_type
        from fespp_on_trame.engine import realization_dispatch as _rd
        from fespp_on_trame.engine import time_realization as _tr
        series = []
        for p in dict.fromkeys((_eye_driven_colors.get(vid) or {}).values()):
            if not p:
                continue
            if p.startswith("derived://"):
                from fespp_on_trame.engine import derived_props
                if derived_props.get_store().axis_caps(tree, p).get("is_ts"):
                    series.append(None)
                continue
            nid = tree.find_node_id(p)
            if nid is None or not element_type.for_kind(tree.find_type(nid) or "").is_time_series():
                continue
            key = _tr.series_of(tree, p, _rd.get_active_realization_for_view(state, vid, p))
            series.append(_steps_of_series(key) if key else None)
        return _tr.step_positions(_time_values(), series)

    def _mr_specs(vid):
        """[{array_path, title, available_indices, current_idx}] of the
        multi-realization properties the view colours by."""
        from fespp_on_trame.engine import realization_dispatch as _rd
        specs, seen = [], set()
        for _sel, p in (_eye_driven_colors.get(vid) or {}).items():
            if (not p or p in seen
                    or not _rd.is_multirealization_property(tree, p)):
                continue
            seen.add(p)
            avail = _rd.available_realization_indices(tree, p)
            if not avail:
                continue
            cur = _rd.get_active_realization_for_view(state, vid, p)
            if cur is None or cur not in avail:
                cur = avail[0]
            nid = tree.find_node_id(p)
            title = ""
            if nid is not None:
                title = (tree.find_attribute_value(nid, "propTitle")
                         or tree.find_title(nid) or "")
            specs.append({"array_path": p,
                          "title": title or p.rsplit("/", 1)[-1],
                          "available_indices": list(avail),
                          "current_idx": int(cur)})
        specs.sort(key=lambda s: s["title"])
        return specs

    def _push_timereal_state(vid):
        from fespp_on_trame.engine import time_realization as _tr
        values = _time_values()
        idx = int(_view_time_idx.get(vid, 0) or 0)
        if values:
            idx = max(0, min(idx, len(values) - 1))
        tval = values[idx] if values else 0.0
        label = _tr.label_for_time_value(tree, tval) if values else ""
        time_d = {"nb": len(values), "index": idx, "value": tval,
                  "label": label, "playing": vid in _play_tasks,
                  "speed": _view_speed.get(vid, 1.0)}
        state[f"ui_timereal__{vid}"] = {"time": time_d, "specs": _mr_specs(vid)}
        for fn in _after_push:
            fn(vid)

    def _apply_view_time(vid, idx):
        values = _time_values()
        if not values:
            return
        idx = max(0, min(int(idx), len(values) - 1))
        _view_time_idx[vid] = idx
        mv = _mv()
        pvv = mv.get_pv_view(vid) if mv is not None else None
        if pvv is not None:
            try:
                pvv.ViewTime = values[idx]
            except Exception as exc:
                print(f"[fespp] view time error ({vid}):", exc, flush=True)
        # Contract: one fixed var every per-view scrub pokes (the Statistics view).
        try:
            state.ui_per_view_time_pulse = int(
                state.ui_per_view_time_pulse or 0) + 1
        except Exception:
            pass
        _push_timereal_state(vid)
        try:
            _push_colormap_state(vid)   # the data range follows the step
        except Exception:
            pass
        scheduler.mark_dirty(vid)
        scheduler.flush()

    @controller.set("time_index")
    def time_index(idx, view_id):
        try:
            idx = int(idx)
        except (TypeError, ValueError):
            print(f"[fespp] time index refused ({view_id}): {idx!r} is not"
                  " a whole number", flush=True)
            return
        _apply_view_time(view_id, idx)

    @controller.set("time_speed")
    def time_speed(speed, view_id):
        try:
            _view_speed[view_id] = max(0.05, float(speed))
        except (TypeError, ValueError):
            print(f"[fespp] time speed refused ({view_id}): {speed!r} is not"
                  " a number", flush=True)
            return
        _push_timereal_state(view_id)

    @controller.set("time_play")
    def time_play(on, view_id):
        import asyncio
        task = _play_tasks.pop(view_id, None)
        if task is not None:
            task.cancel()
        if not on:
            _push_timereal_state(view_id)
            return

        async def _loop():
            try:
                while True:
                    await asyncio.sleep(0.5 / _view_speed.get(view_id, 1.0))
                    steps = _steps(view_id)
                    if len(steps) < 2 or not per_view_state.is_live(view_id):
                        break
                    from fespp_on_trame.engine import time_realization as _tr
                    nxt = _tr.next_position(steps, int(_view_time_idx.get(view_id, 0)))
                    with state:
                        _apply_view_time(view_id, nxt)
            except asyncio.CancelledError:
                pass
            finally:
                # forget THIS task only: a play pressed twice has already put
                # the next one in the table, and popping it would leave a
                # playback nothing can stop (the cross-plot's loop does so too)
                if _play_tasks.get(view_id) is asyncio.current_task():
                    _play_tasks.pop(view_id, None)

        from trame.app import asynchronous
        _play_tasks[view_id] = asynchronous.create_task(_loop())
        _push_timereal_state(view_id)

    @controller.set("set_realization")
    def set_realization(payload, view_id):
        from fespp_on_trame.engine import realization_dispatch as _rd
        try:
            path, idx = payload[0], int(payload[1])
        except (TypeError, ValueError, IndexError):
            return
        _rd.set_active_realization_for_view(state, view_id, path, idx)
        # Re-run the eye reconcile: it resolves '<name>_real_<idx>' through
        # _real_idx_for and recolours the rep (+ derived BW) in this view.
        on_eye_changed(view_id, list(
            getattr(state, f"visible_paths__{view_id}", None) or []))

    # ------------------------------------------------------------------
    return {"push": _push_timereal_state, "apply_time": _apply_view_time,
            "time_index": lambda vid: int(_view_time_idx.get(vid, 0) or 0),
            "time_values": _time_values, "steps": _steps, "specs": _mr_specs,
            "set_realization": set_realization, "after_push": _after_push}
