"""The host of a slicer card — the gestures of the Geometry and the Property
slicers alike (the PO's manager, 28/10: one UI for the two, "a user who
understands one understands the other"). The cards differ only by their
subjects (the I, J, K of a grid; the properties added to the card) and by
how a card is drawn (crop boxes; threshold-chain branches): each tool gives
those two, this host does the rest on the card's model
(`engine/slicer_card`):

- the gestures: boxes, each Range or Slice, ranges joined by ∪ / ∩ inside
  a Range box, cuts in a Slice box, eyes, the card's eye, ⟲, the object of
  the card's list, the properties added;
- the hand on a slider, LIVE and as fluid as the player: a drag's values
  coalesce, the last wins (slicer_player.Coalescer), drawn on the light path
  (`draw(..., live=True)`: the filters on screen, nothing settled);
- the player bar of every range and cut (slicer_player.Player): a range
  slides whole, a cut steps from value to value.

State, per view: `<card_key><vid>` = {card, subjects, addable, fixed, shape, target,
targets, all_visible, note} — the card as a COPY: trame sends a value that
differs from the last one sent, and a card changed in place compares equal
to itself; the player publishes `<player_key><vid>`.
"""
import copy

from fespp_on_trame.app.features.slicer_player import Coalescer, Player
from fespp_on_trame.engine import slicer_card as sc
from fespp_on_trame.engine import value_sweep

_INTEGER = ("Index", "Discrete", "Categorical")


class CardHost:
    """One slicer tool's cards, one per (view, object)."""

    def __init__(self, core, *, tool, card_key, player_key, context, card_of, draw,
                 fixed_subjects=False, extra_targets=None, shape=None):
        """`context(vid, extra)`: (rep_path, infos {subject: {label, kind,
        extent, values, labels}}, note, addable [{value, label}]) — the
        object the card cuts in `vid` and what its subjects are (`extra`:
        subjects about to be added, whose infos are wanted too); `card_of(vid, rep,
        infos)`: the card of that object (made, or read back from what is
        drawn); `draw(vid, rep, card, infos, live)`: the card drawn;
        `fixed_subjects`: the subjects are given (I, J, K), not added;
        `extra_targets(vid)`: entries [{value, label}] put before the objects
        of the card's list (the Geometry slicer's whole scene); `shape`: what
        the card shows of the model, {boxes, modes, cmp, many} each True
        unless said (the Time & Realizations card: rows of one value)."""
        self._extra_targets = extra_targets
        self._shape = dict(shape or {})
        self._state = core.state
        self._activation = core.activation
        self._ctx = core.ctx
        self._lifecycle = core.lifecycle
        self.tool = tool
        self._card_key = card_key
        self._context = context
        self._card_of = card_of
        self._draw = draw
        self._fixed = fixed_subjects
        self._live = Coalescer(core.state)
        self.off = set()      # (vid, rep): the card kept, the whole object shown
        self.player = Player(core, player_key, self._steps_of, self._play_step)

    # ------------------------------------------------------------ state
    def publish(self, vid):
        rep, infos, note, addable = self._context(vid, ())
        card = self._card_of(vid, rep, infos) if rep else None
        targets = (getattr(self._state, f"ui_tool_targets__{vid}", None) or {}).get(self.tool) or []
        if self._extra_targets is not None:
            targets = list(self._extra_targets(vid) or []) + list(targets)
        self._state[f"{self._card_key}{vid}"] = {
            "target": rep or "", "targets": list(targets),
            "card": copy.deepcopy(card) if card else sc.empty(()),
            "subjects": [dict(info, value=s, categories=_categories(info))
                         for s, info in infos.items()] if rep else [],
            # a property the card cuts on but a box was rid of can go back
            "addable": [] if self._fixed else (
                list(addable or []) + [{"value": s, "label": (infos.get(s) or {}).get("label") or s}
                                       for s in (sc.missing(card) if card else [])
                                       if not any(a.get("value") == s for a in addable or ())]),
            "fixed": self._fixed,
            "shape": dict(self._shape),
            "all_visible": (vid, rep) not in self.off,
            "note": note or "",
        }

    def _redraw(self, vid, rep, card, infos, live=False):
        self._draw(vid, rep, card, infos, live)
        self.publish(vid)
        # a step of a drag or of the player settles nothing: said here
        self._lifecycle.emit("view_cuts", vid=vid)

    # ------------------------------------------------------------ player
    def _item(self, vid, item_id):
        rep, infos, _note, _add = self._context(vid, ())
        card = self._card_of(vid, rep, infos) if rep else None
        if card is None:
            return rep, infos, None, None, None, None
        kind, item, where = sc.find(card, item_id)
        return rep, infos, card, kind, item, where

    def _steps_of(self, vid, item_id, width):
        rep, infos, card, kind, item, where = self._item(vid, item_id)
        if item is None or kind not in ("range", "cut"):
            return None
        subject = where[1]
        info = infos.get(subject) or {}
        if kind == "range":
            low, high, mode = item["low"], item["high"], "range"
        else:
            low = high = item["at"]
            mode = "value"
        steps = value_sweep.window_steps(info.get("kind") or "Continuous", extent=info.get("extent"),
                                         values=info.get("values"), labels=info.get("labels"),
                                         low=low, high=high, mode=mode, width=width)
        name = info.get("label") or subject
        return [(a, b, f"{name} {t}") for a, b, t in steps], info.get("kind") or "Continuous", low

    def _play_step(self, vid, item_id, low, high):
        rep, infos, card, kind, item, _where = self._item(vid, item_id)
        if item is None:
            return False
        if kind == "range":
            item["low"], item["high"] = float(low), float(high)
        elif kind == "cut":
            # a continuous step is a window: its centre is the value cut
            item["at"] = float(low) if low == high else (float(low) + float(high)) / 2.0
        else:
            return False
        self._redraw(vid, rep, card, infos, live=True)
        return True

    # ------------------------------------------------------------ gestures
    def gesture(self, edit, vid):
        """One gesture of the card (FpSlicer): target {path}, all_visible
        {on}, reset, add_subject {subject, box?}, del_subject {subject, box?};
        add_box {mode}, box_mode {id, mode}, join_box {id, join},
        toggle_box / del_box {id}; add_range {box, subject, join},
        set_range {id, low, high, live}, join_range {id, join}, del_range
        {id}; add_cut {box, subject}, set_cut {id, at, live}, cut_cmp {id,
        cmp: only | below | above}, toggle_cut / del_cut {id}; player {id,
        action: play | speed | loop | step, value}."""
        vid = str(vid)
        edit = dict(edit or {})
        op = edit.get("op") or ""
        if not edit.get("live"):
            # the journal a scenario is written from (the PO, 30/10: "more
            # debug, so you see exactly what I do")
            print(f"[fespp] journal card {self.tool} ({vid}): {edit}", flush=True)
        if op == "target":
            self.player.stop(vid)
            self._activation.pin(vid, self.tool, edit.get("path") or "")
            self.publish(vid)
            return
        if op == "player" and edit.get("action") == "play" and not edit.get("value"):
            # a pause always pauses, whatever the card holds by now (its row
            # made again, nothing to step through while a read goes on): the
            # button shows the player's state, said again
            self.player.play(vid, False)
            return
        rep, infos, _note, _add = self._context(
            vid, (edit.get("subject"),) if op == "add_subject" else ())
        if not rep:
            return
        card = self._card_of(vid, rep, infos)
        if card is None:
            return
        exts = {s: info["extent"] for s, info in infos.items()}
        values = {s: info.get("values") for s, info in infos.items()}
        whole = tuple(s for s, info in infos.items() if info.get("kind") in _INTEGER)
        kind, item, where = sc.find(card, edit.get("id"))
        live = bool(edit.get("live"))
        if op == "player":
            if item is None:
                return
            action, value = edit.get("action"), edit.get("value")
            if action == "play":
                self.player.play_row(vid, item["id"], bool(value))
            elif action == "speed":
                self.player.speed(vid, value)
            elif action == "loop":
                self.player.loop(vid, bool(value))
            elif action == "step":
                if self.player.row(vid) != item["id"]:
                    self.player.start(vid, item["id"])
                self.player.step(vid, int(value))
            return
        if op == "set_range" and kind == "range":
            lo, hi = float(edit.get("low")), float(edit.get("high"))
            if where[1] in whole:
                lo, hi = float(round(lo)), float(round(hi))
            item["low"], item["high"] = min(lo, hi), max(lo, hi)
        elif op == "set_cut" and kind == "cut":
            at = float(edit.get("at"))
            item["at"] = float(round(at)) if where[1] in whole else at
        else:
            live = False
            if not self._structure(op, edit, card, exts, values, whole, kind, item, where, vid, rep):
                print(f"[fespp] {self.tool} card ({vid}): gesture refused: {edit!r}", flush=True)
                return
        if self.player.row(vid) == edit.get("id") and op in ("set_range", "set_cut"):
            self.player.refresh(vid)
        if live:
            self._live.request((vid, "draw"), lambda: self._redraw(vid, rep, card, infos, live=True))
        else:
            self._redraw(vid, rep, card, infos)

    def _structure(self, op, edit, card, exts, values, whole, kind, item, where, vid, rep):
        """The gestures that change what the card holds; False when refused."""
        if op == "all_visible":
            (self.off.discard if edit.get("on") else self.off.add)((vid, rep))
        elif op == "reset":
            self.player.stop(vid)
            card["boxes"] = []
            if self._fixed:
                sc.defaults(card, exts)
            else:
                # a card on properties starts again empty: its first
                # property makes its first box
                card["subjects"] = []
        elif op == "add_subject" and not self._fixed and edit.get("subject") in exts:
            # a property in ONE box: the box named, else the first box made
            # for it (the PO, 30/10: a box held every property of the card,
            # one he had never put there among them); with boxes and none
            # named (the right-click door), in every box
            s_ = edit["subject"]
            box = None
            if edit.get("box"):
                _k, box, _w = sc.find(card, edit.get("box"))
                if box is None:
                    return False
            elif not card.get("boxes"):
                box = sc.new_box(card, exts, values=values, whole=whole, subjects=())
            sc.add_subject(card, s_, exts, values.get(s_), s_ in whole, box=box)
        elif op == "del_subject" and not self._fixed and edit.get("subject") in card["subjects"]:
            # the × on a property's line: out of THAT box (the manager,
            # 29/10); with no box named, out of the card
            box = None
            if edit.get("box"):
                _k, box, _w = sc.find(card, edit.get("box"))
                if box is None:
                    return False
            self.player.stop(vid)
            sc.remove_subject(card, edit["subject"], box)
        elif op == "add_box":
            # a card on properties: an empty box, its properties added by
            # its own "+ Property" (the PO, 30/10)
            sc.new_box(card, exts, mode=edit.get("mode") or sc.RANGE, values=values, whole=whole,
                       subjects=None if self._fixed else ())
        elif op == "add_range" and edit.get("subject") in exts:
            _k, box, _w = sc.find(card, edit.get("box"))
            if box is None:
                return False
            box.setdefault("ranges", {}).setdefault(edit["subject"], []).append(
                sc.new_range(card, exts[edit["subject"]], op=sc.AND if edit.get("join") == "and" else sc.OR))
        elif op == "add_cut" and edit.get("subject") in exts:
            _k, box, _w = sc.find(card, edit.get("box"))
            if box is None:
                return False
            sc.new_cut(card, box, edit["subject"], exts[edit["subject"]], values.get(edit["subject"]),
                       edit["subject"] in whole)
        elif item is None:
            return False
        elif op == "box_mode" and kind == "box":
            self.player.stop(vid)
            sc.set_mode(card, item, edit.get("mode"), exts, values, whole)
        elif op in ("toggle_box", "toggle_cut") and kind in ("box", "cut"):
            item["visible"] = not item.get("visible", True)
        elif op == "del_box" and kind == "box":
            card["boxes"].remove(item)
            if not self._fixed:
                sc.prune(card)
        elif op == "join_box" and kind == "box":
            # the box joins the ones above by ∪ or ∩ (the manager, 29/10)
            item["op"] = sc.AND if edit.get("join") == "and" else sc.OR
        elif op == "join_range" and kind == "range":
            item["op"] = sc.AND if edit.get("join") == "and" else sc.OR
        elif op == "del_range" and kind == "range":
            where[0]["ranges"][where[1]].remove(item)
        elif op == "del_cut" and kind == "cut":
            where[0]["cuts"][where[1]].remove(item)
        elif op == "cut_cmp" and kind == "cut" and edit.get("cmp") in (sc.ONLY, sc.BELOW, sc.ABOVE):
            # what the cut keeps: its value only, or below / above it (28/10)
            item["cmp"] = edit["cmp"]
        else:
            return False
        if item is not None and op.startswith("del_") and self.player.row(vid) == item.get("id"):
            self.player.stop(vid)
        return True


def _categories(info):
    """A categorical subject's values with their names, for the slider's
    ticks and the bounds' menus."""
    if info.get("kind") != "Categorical":
        return []
    labels = {str(k): v for k, v in (info.get("labels") or {}).items()}
    out = []
    for v in sorted({float(x) for x in info.get("values") or ()}):
        key = str(int(v)) if v.is_integer() else str(v)
        # a value its table leaves unnamed is named by its number
        out.append({"value": v, "label": str(labels.get(key) or key)})
    return out
