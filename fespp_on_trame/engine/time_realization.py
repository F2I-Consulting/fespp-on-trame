"""Time dispatch: global TimeKeeper labelling for the UI.

`change_time_label` keeps `state.ui_time_label` aligned with the
tree-attached `timeX.YYYYYY` label (or the formatted raw float when
no custom label was attached). `register_per_view_time_label` does the
same wiring for each panel's own slider so per-view readouts match the
global format.

Per-view realization selection is owned by
`fespp_on_trame.engine.realization_dispatch` (state map
`ui_active_realization_by_array_by_view`), not this module.
"""
import re

from paraview import simple as pvsimple


# `2019-12-31T23:00:00Z` / `2019-12-31 23:00:00` → keep `2019-12-31`.
# Reservoir timeseries labels are dated to the day in practice, so the
# time-of-day is noise that crowds the TC chip + every stats table
# column. Anything that doesn't match the ISO date prefix (e.g. the
# fallback `timeX.YYYYYY`, custom non-date labels) passes through
# unchanged.
_ISO_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})[T ]\d{2}:\d{2}")


def _shorten_time_label(label):
    """`label` cut to its ISO date when it starts with one, else as is."""
    if not isinstance(label, str):
        return label
    m = _ISO_DATE_RE.match(label)
    if m:
        return m.group(1)
    return label


def label_for_time_value(tree, time_value):
    """Return the tree-attached label (`timeX.YYYYYY` attribute on
    root) for a given time, or the formatted time itself when no
    custom label is registered. ISO datetime labels are trimmed to
    their date part (`YYYY-MM-DD`)."""
    try:
        label = tree.find_attribute_value(0, f"time{time_value:.6f}")
        if label is not None:
            return _shorten_time_label(label)
    except Exception:
        pass
    return f"time{time_value:.6f}"


def change_time_label(state, tree):
    """Update `state.ui_time_label` from the current time step's
    label attribute on the assembly root, falling back to the
    formatted time value."""
    try:
        index = state.time_index
        if index is not None:
            time_value = pvsimple.GetTimeKeeper().TimestepValues[index]
            state.ui_time_label = label_for_time_value(tree, time_value)
    except Exception:
        state.ui_time_label = ""


def register_per_view_time_label(state, tree, time_value_var, label_var):
    """Wire a `state.change` handler that recomputes `label_var`
    from `time_value_var` using the same tree-driven lookup as the
    global TC label. Called by `FesppMultiView` when it creates a
    per-view TimeControl, so each panel's slider readout matches
    the global label format instead of showing the raw float.

    Also bumps `ui_per_view_time_pulse`, a shared monotonic
    counter the Statistics view watches (app/features/compare_parts)
    so that a 3D view's rows follow that view's time.
    `time_value_<panel_id>` is dynamic per view, so no static
    watcher can name it; the pulse gives every per-view TC a single,
    fixed state var it can poke."""
    def _on_change(**_):
        try:
            tv = float(getattr(state, time_value_var, 0) or 0)
            setattr(state, label_var, label_for_time_value(tree, tv))
        except Exception:
            setattr(state, label_var, "")
        try:
            current = int(getattr(state, "ui_per_view_time_pulse", 0) or 0)
            state.ui_per_view_time_pulse = current + 1
        except Exception:
            pass
    state.change(time_value_var)(_on_change)
    # Seed once so the label is already populated when the panel
    # first renders.
    _on_change()


# ---------------------------------------------------------------- real steps
# FESPP publishes ONE list of time steps for the whole session (ParaView has
# one per source): the union of the time indices of every time series read.
# A series asked for a step it has no property at keeps its previous data, so
# a view coloured by a series of 3 steps out of 21 shows 18 steps that change
# nothing. A view's time steps are those at which what it colours by changes.

def series_of(tree, path, realization=None):
    """``(TimeSeries uuid, property title, realization)`` of the time series
    `path` names, None when it is none: a ``TimeSeries`` node (its title), a
    realization of a ``MultiRealizationTimeSeries`` (its parent's
    ``propTitle``, its ``realization_index``) or the multi-realization node
    itself (its ``propTitle``, `realization` the one the view shows)."""
    from fespp_on_trame.engine import row_object
    nid = tree.find_node_id(path) if path else None
    if nid is None:
        return None
    kind = tree.find_type(nid) or ""
    uuid = row_object.uuid_of(path.rsplit("/", 1)[-1])
    if not uuid:
        return None
    if kind == "MultiRealizationTimeSeries":
        title = tree.find_attribute_value(nid, "propTitle")
    elif kind == "TimeSeries":
        real = tree.find_attribute_value(nid, "realization_index")
        if real is None:
            title = tree.find_attribute_value(nid, "title")
        else:
            title = tree.find_parent_attribute_value(nid, "propTitle")
            real = str(real).strip()
            realization = int(real) if real.isdigit() else None
    else:
        return None
    if not title:
        return None
    return uuid, str(title), realization


def series_members(related, title):
    """The properties among `related` (the objects designating a TimeSeries,
    ``[{uuid, type, title}]``) named `title`: the steps of one property's
    series, which FESPP folds by that title."""
    return [r for r in related or ()
            if "Property" in (r.get("type") or "") and (r.get("title") or "") == title]


def series_steps(xmls, realization=None):
    """The time indices the XML of a series' properties declare, sorted, one
    realization's alone when `realization` is given."""
    from fespp_on_trame.engine import repo_query
    out = set()
    for xml in xmls or ():
        ts, real = repo_query.series_indices(xml)
        if ts is None:
            continue
        if realization is not None and real is not None and real != realization:
            continue
        out.add(ts)
    return sorted(out)


def step_positions(values, series):
    """The positions in `values` (the session's time steps: the time indices
    FESPP publishes) a view steps through: those of the steps of the series
    it colours by (`series`, one list a series, None for a series whose steps
    are unknown: every position). [] when it colours by no time series."""
    series = list(series or ())
    if not series:
        return []
    if any(s is None for s in series):
        return list(range(len(values or ())))
    wanted = {float(t) for steps in series for t in steps}
    return [i for i, v in enumerate(values or ())
            if any(abs(float(v) - t) < 1e-6 for t in wanted)]


def next_position(positions, current):
    """The position after `current` among `positions`, the first after the
    last (a play loops); `current` when there is none."""
    after = [p for p in positions or () if p > current]
    if after:
        return after[0]
    return positions[0] if positions else current


def position_kept(positions, current):
    """The position a view shows once its steps are `positions`: `current`
    when it is one of them, else the first (another series coloured that
    has no data at `current`); `current` when there are none."""
    if not positions or current in positions:
        return current
    return positions[0]
