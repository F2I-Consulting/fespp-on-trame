"""Every display a 3D view draws OUTSIDE its composite, in one registry.

A view draws its file's blocks through ONE composite representation
(engine/blockscope/pdc_scene). Everything else on screen is a display of its
own: an isolate's crops and threshold tips, a selection extract, the
selection overlay of an isolated grid, the contact planes of the Volumetrics
card, the wellheads. (A formula has no display of its own: it colours its
grid's block, engine/derived_arrays.) The gestures that touch them all
— the vertical exaggeration, closing the view and Represent By —
used to walk them family by family, and each walk forgot someone
(04-verification E1, E2: the contact planes outlived a closed view, the
threshold tips kept the old exaggeration, Represent By skipped the isolates
and the extracts).

Here a display is registered once, when it is made, saying what it follows;
the gestures walk the registry. A family keeps its own state (the
extract chains, the recipes, the volumetrics parameters); what crosses
families lives here. Slice 2 of the overhaul.

An entry's hooks, all optional:

- ``zscale(z)`` — follow a new vertical exaggeration; by default the
  display's ``Scale`` becomes ``[1, 1, z]``;
- ``style(name)`` — follow the view's Represent By; by default the
  display's ``Representation``; only for an entry made with
  ``follows_style=True``;
- ``close()`` — put the display away: the family's own drop, which also
  removes the entry (removing an absent entry is harmless).

No hook raises out of the registry: a failure is printed with what it was
about, and the walk goes on.
"""


class Entry:
    """One display of one view (see the module note for the hooks)."""

    __slots__ = ("vid", "key", "kind", "display", "follows_z", "follows_style",
                 "zscale", "style", "close")

    def __init__(self, vid, key, kind, display=None, follows_z=True,
                 follows_style=False, zscale=None, style=None, close=None):
        self.vid = str(vid or "")
        self.key = str(key or "")
        self.kind = str(kind or "")
        self.display = display
        self.follows_z = bool(follows_z)
        self.follows_style = bool(follows_style)
        self.zscale = zscale
        self.style = style
        self.close = close


class Displays:
    """The registry: per view, its off-composite displays by key."""

    def __init__(self, log=None):
        self._by_view = {}
        self._log = log or (lambda text: print(text, flush=True))

    # ------------------------------------------------------------ entries
    def add(self, vid, key, kind, display=None, **hooks):
        """Register a display under (view, key) — replacing what was there
        under that key — and return its entry."""
        entry = Entry(vid, key, kind, display, **hooks)
        self._by_view.setdefault(entry.vid, {})[entry.key] = entry
        return entry

    def remove(self, vid, key):
        """Forget the entry (the family has put the display away)."""
        entries = self._by_view.get(str(vid or ""))
        if not entries:
            return
        entries.pop(str(key or ""), None)
        if not entries:
            self._by_view.pop(str(vid or ""), None)

    def get(self, vid, key):
        return (self._by_view.get(str(vid or "")) or {}).get(str(key or ""))

    def entries(self, vid=None, kind=None):
        """The entries of one view (every view when None), of one kind (any
        when None) — a copy: a hook may add or remove while it is walked."""
        views = [str(vid)] if vid is not None else list(self._by_view)
        return [e for v in views for e in list((self._by_view.get(v) or {}).values())
                if kind is None or e.kind == kind]

    # ------------------------------------------------------------ gestures
    def set_zscale(self, z, vid=None):
        """Every display of view `vid` (of every view when None) that follows
        the vertical exaggeration, at `z`."""
        for e in self.entries(vid):
            if not e.follows_z:
                continue
            try:
                if e.zscale is not None:
                    e.zscale(z)
                elif e.display is not None:
                    e.display.Scale = [1.0, 1.0, float(z)]
            except Exception as exc:
                self._log(f"[fespp] displays: z of {e.kind} {e.key} ({e.vid}): {exc}")

    def set_style(self, vid, style):
        """The displays of view `vid` that follow Represent By, drawn as
        `style` ("Surface", "Wireframe", …)."""
        for e in self.entries(vid):
            if not e.follows_style:
                continue
            try:
                if e.style is not None:
                    e.style(style)
                elif e.display is not None:
                    e.display.Representation = style
            except Exception as exc:
                self._log(f"[fespp] displays: style of {e.kind} {e.key} ({e.vid}): {exc}")

    def close_view(self, vid):
        """The view closes: each of its displays is put away."""
        for e in self.entries(vid):
            self._close(e)
        self._by_view.pop(str(vid or ""), None)

    def _close(self, e):
        try:
            if e.close is not None:
                e.close()
        except Exception as exc:
            self._log(f"[fespp] displays: closing {e.kind} {e.key} ({e.vid}): {exc}")
        self.remove(e.vid, e.key)
