"""The tool cards open in each 3D view (overhaul slice 5).

`ui_open_tools_by_view` — {view id: [card keys, in the order they opened]}
— has ONE writer, here. The gestures keep their own rules (a selection
mode excludes the other one and the cursor mode, the Slicers card asks for
a cut); what they decide is written
through `open`, `close` or `set`, and a selection tool's mode variable
always follows its key (`sync_modes`: a restored session lit the button
and left the mode off, 04-verification D29)."""

VAR = "ui_open_tools_by_view"


class Cards:
    """The open cards of the session's 3D views, one writer for all."""

    def __init__(self, state, mode_tools=()):
        """`mode_tools`: the selection tools, [{"key", "var"}] — a key open
        means its mode variable `<var><vid>` is on."""
        self._state = state
        self._modes = list(mode_tools)
        # {view id: the cards on screen in its dock, not behind another tab}
        self._seen = {}

    def _all(self):
        return dict(getattr(self._state, VAR, None) or {})

    def keys(self, vid):
        return list(self._all().get(vid) or [])

    def is_open(self, vid, key):
        return key in self.keys(vid)

    def has_view(self, vid):
        return vid in self._all()

    def set(self, vid, keys):
        """The view's open cards are `keys`, in that order; True when that
        changed anything."""
        keys = list(dict.fromkeys(k for k in (keys or ()) if k))
        allv = self._all()
        if allv.get(vid) == keys and vid in allv:
            return False
        allv[vid] = keys
        self._state[VAR] = allv
        return True

    def set_many(self, mapping):
        """Several views at once, one write."""
        allv = self._all()
        changed = False
        for vid, keys in (mapping or {}).items():
            keys = list(dict.fromkeys(k for k in (keys or ()) if k))
            if allv.get(vid) != keys or vid not in allv:
                allv[vid] = keys
                changed = True
        if changed:
            self._state[VAR] = allv
        return changed

    def seen(self, vid, key, visible):
        """The view's dock says whether the card `key` is on screen."""
        shown = self._seen.setdefault(str(vid), set())
        (shown.add if visible else shown.discard)(key)

    def hidden(self, vid, key):
        """`key` is open in the view, behind another card's tab."""
        shown = self._seen.get(str(vid))
        return shown is not None and self.is_open(vid, key) and key not in shown

    def reveal(self, vid, key):
        """The card `key` brought in front of the other tabs of its group."""
        var = f"ui_card_reveal__{vid}"
        n = int((getattr(self._state, var, None) or {}).get("n", 0)) + 1
        self._state[var] = {"id": key, "n": n}

    def open(self, vid, key, last=False):
        """Open `key` (moved to the end with `last`); open already behind
        another card's tab, it comes in front."""
        cur = self.keys(vid)
        if key in cur and not last:
            if self.hidden(vid, key):
                self.reveal(vid, key)
            return False
        return self.set(vid, [k for k in cur if k != key] + [key])

    def close(self, vid, key):
        cur = self.keys(vid)
        if key not in cur:
            return False
        return self.set(vid, [k for k in cur if k != key])

    def sync_modes(self, vid):
        """Each selection tool's mode variable follows its key."""
        cur = set(self.keys(vid))
        for spec in self._modes:
            self._state[f"{spec['var']}{vid}"] = spec["key"] in cur
