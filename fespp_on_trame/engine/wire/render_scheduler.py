"""RenderScheduler — one render and one frame push per dirty view per handler.

Contract
--------
Input:     ``get_multi_view`` — zero-arg callable returning the live
           ``MultiView`` (or None before it exists). Resolved at flush time,
           never captured, so the scheduler survives views being opened and
           closed.
Behaviour: handlers call ``mark_dirty(view_id)`` any number of times while they
           mutate the scene, then ONE ``flush()`` at their tail. ``flush()``
           renders and pushes a frame to each dirty view exactly once and
           clears the set. Marking an unknown or already-closed view is
           harmless (it is skipped at flush).
Reads:     the multi-view registry (``get_pv_view`` / ``get_html_view`` /
           ``view_ids``).
Writes:    nothing in trame state — only ParaView renders and VtkRemoteView
           frame pushes. The listeners (``add_flush_listener``) are called
           with the dirty view ids BEFORE the renders: what a view shows
           beside its image (the Legends card) is published once per
           handler, from the scene the frame is drawn from.
"""
from paraview import simple as pvsimple


class RenderScheduler:
    def __init__(self, get_multi_view):
        self._get_mv = get_multi_view
        self._dirty = set()
        self._listeners = []

    def add_flush_listener(self, fn):
        """Call ``fn(view_ids)`` before every flush that renders something.

        A listener may change the scene or mark more views dirty: those
        changes are drawn by the same flush.
        """
        self._listeners.append(fn)

    def mark_dirty(self, view_id):
        """Queue ``view_id`` for the next flush; an empty id is ignored."""
        if view_id:
            self._dirty.add(str(view_id))

    def mark_all_dirty(self):
        mv = self._get_mv()
        for vid in (mv.view_ids() if mv is not None else []):
            self._dirty.add(str(vid))

    def flush(self):
        """Render and push a frame to each dirty view once, then clear."""
        dirty, self._dirty = self._dirty, set()
        if not dirty:
            return
        for fn in self._listeners:
            try:
                fn(sorted(dirty))
            except Exception as exc:
                print("[fespp] flush listener error:", exc, flush=True)
        # What a listener changed (the Colormap card re-projected, the view's
        # bar moved) is drawn in THIS flush, not left for the next one.
        dirty |= self._dirty
        self._dirty = set()
        mv = self._get_mv()
        if mv is None:
            return
        for vid in dirty:
            # ONE render per view, not two: `html_view.update()` pushes an
            # image through StillRenderToString, which renders the scene
            # itself, so a pvsimple.Render before it would double the render
            # cost of every action. A bare Render is only the fallback for a
            # view with no client.
            html_view = mv.get_html_view(vid)
            if html_view is not None:
                try:
                    html_view.update()
                    continue
                except Exception:
                    pass
            pv_view = mv.get_pv_view(vid)
            if pv_view is not None:
                try:
                    pvsimple.Render(view=pv_view)
                except Exception as exc:
                    print(f"[fespp] render error ({vid}):", exc, flush=True)
