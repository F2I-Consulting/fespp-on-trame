"""Who draws a grid in a view — decided in one place.

A grid of a 3D view is drawn by exactly one of three: a visible selection
extract or the copy a formula colours it by, drawn in its place; its isolate
(the slicer's crops, a threshold chain, the NaN mask), only while the
isolate is needed and the grid's eye is open; else the view's composite.
The decision was taken in several places that each knew part of the rule
(`_extract_layout` knew the extracts, `_settle_isolate` the isolate, and a
dozen controllers called the isolate's ``show()`` directly), so a vertical
exaggeration, a "Slice off" or a threshold removed could bring back a grid
the eye had hidden or one an extract replaced, or paint it twice
(04-verification D7, N8). Slice 3 of the overhaul.

``settle(vid, rep_path)`` is the only writer of ``scene.isolated`` and the
only caller of an isolate's ``show()`` / ``hide_all()``; an isolate asks it
to redraw (its ``shown_by``) instead of showing itself.
"""

def replaced_rows(extracts):
    """The tree rows of the geometries a visible extract stands in for (its
    representation's row): the eye says what is drawn, so theirs is shown
    closed while the extract is; sorted, once each."""
    return sorted({e.get("rep_path") for e in extracts or () if e.get("visible") and e.get("rep_path")})


REPLACED = "replaced"     # an extract or a formula's copy draws it
ISOLATE = "isolate"       # its isolate draws it
HIDDEN = "hidden"         # its isolate is needed, its eye is closed
COMPOSITE = "composite"   # the view's composite draws it


class Occupancy:
    def __init__(self, scene_of, isolate_of, replaced, on_settled=None):
        """`scene_of(vid)` -> the view's composite scene or None;
        `isolate_of(vid, rep_path)` -> its isolate or None;
        `replaced(vid, selector)` -> True while an extract is drawn in the
        grid's place; `on_settled(vid, rep_path)` is told after each
        decision is made so (the selection's overlay follows it, D10)."""
        self._scene_of = scene_of
        self._isolate_of = isolate_of
        self._replaced = replaced
        self._on_settled = on_settled

    def decide(self, vid, rep_path, selector=None):
        """Who should draw `rep_path` in `vid` — read only; "" when the
        view has no scene."""
        scene = self._scene_of(vid)
        sel = selector or rep_path
        if scene is None or not sel:
            return ""
        if self._replaced(vid, sel):
            return REPLACED
        iso = self._isolate_of(vid, rep_path) if rep_path else None
        if iso is not None and iso.needs_isolation():
            # drawn when its eye is open and the view shows its domain
            return ISOLATE if sel in scene.shown_selectors() else HIDDEN
        return COMPOSITE

    def settle(self, vid, rep_path, selector=None):
        """Decide who draws `rep_path` in `vid`, and make it so; returns
        the decision ("" when the view has no scene)."""
        decision = self.decide(vid, rep_path, selector)
        if not decision:
            return decision
        scene = self._scene_of(vid)
        sel = selector or rep_path
        iso = self._isolate_of(vid, rep_path) if rep_path else None
        scene.set_isolated(sel, decision != COMPOSITE)
        if iso is not None:
            if decision == ISOLATE:
                iso.show()
            else:
                iso.hide_all()
        if self._on_settled is not None:
            self._on_settled(vid, rep_path)
        return decision
