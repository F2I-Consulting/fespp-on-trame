"""The one rule for the docked tree of a panel that chooses its own content.

The panels that carry one — the well log, Log ↔ Grid; not Statistics, whose
tree opens with it — share one rule: the panel says whether its tree opens on
its first open — the well log always, Log ↔ Grid **only while it is empty**. A panel whose
only door is its tree would otherwise open with nothing in it and no visible
way in; and a tree that re-opened itself every time the panel emptied would
take 320 px back from a reader who had just closed it. So it opens ONCE, on
the first open of a panel that has nothing in it, and never by itself again.

`seed_open` is that rule and the only place it is written.

The memory of "this view has already had its answer" lives here rather than
in the state: `per_view_state.teardown` nulls a closed panel's per-view vars,
and the answer has to outlive that — it is dropped by `forget`, which that
same teardown calls, so a later view never inherits a dead one's.
"""

#: view ids whose docked tree has already been given its opening state
_ANSWERED = set()


def seed_open(state, var, view_id, empty):
    """Seed `var` (``<kind>_tree_open__<vid>``) for the panel being built.

    The first time this view asks, OPEN when the panel is `empty` and closed
    otherwise; afterwards whatever the reader left stands.
    """
    vid = str(view_id)
    if vid not in _ANSWERED:
        _ANSWERED.add(vid)
        state[var] = bool(empty)
        return
    if getattr(state, var, None) is None:
        state[var] = False


def forget(view_id):
    """Drop the answer of a closed view, so a later view never inherits it."""
    _ANSWERED.discard(str(view_id))

