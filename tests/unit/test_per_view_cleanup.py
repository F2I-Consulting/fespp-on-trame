"""A closed panel leaves nothing of its own in the state.

`per_view_state.SUFFIXED_VARS` is the one inventory of the keys a view or a
panel creates under its own id: closing it (`teardown`) nulls each of them
and forgets the change handlers bound to them. A key built with a panel's
id but missing from the inventory outlives the panel, handlers included,
for the rest of the session. The docked trees of the analysis panels
(Statistics, the well log, Log <-> Grid) each build the same
family of keys, so the family is checked on the source of the whole
package: a tree key added anywhere has to be inventoried.
"""
import re
from pathlib import Path

import fespp_on_trame
from fespp_on_trame.app.views import per_view_state

_PREFIXES = {prefix for prefix, _factory in per_view_state.SUFFIXED_VARS}
_PACKAGE = Path(fespp_on_trame.__file__).resolve().parent
# a docked tree's key: `<panel>_tree_<what>__<view id>`, built as an f-string
_TREE_KEY = re.compile(r"""f["']([a-z]+_tree_[a-z_]+__)\{""")
# any key built with a view's or a panel's id, as an f-string
_VIEW_KEY = re.compile(
    r"""f["']([a-zA-Z0-9_]+__)\{(?:vid|view_id|self\.view_id|rvid|pid|panel_id|self\.panel_id)\}["']""")
# built the same way, yet no key of the state: a pipeline proxy's name
_NOT_STATE = {"selection_highlight__"}


class FakeState:
    """A trame state as `teardown` reads it: the vars as attributes, and the
    private `_change_callbacks` table (key -> [(func, translator)])."""

    def __init__(self):
        self._change_callbacks = {}

    def __setitem__(self, name, value):
        setattr(self, name, value)

    def change(self, *keys):
        def register(func):
            for k in keys:
                self._change_callbacks.setdefault(k, []).append((func, None))
            return func
        return register


def _handler(**_):
    return None


def test_the_compare_tree_keys_are_inventoried():
    for what in ("selected", "eye", "shown", "toggle", "ctx", "active",
                 "active_by_tab", "colour", "open"):
        assert f"compare_tree_{what}__" in _PREFIXES, what


def test_every_docked_tree_key_is_inventoried():
    built = {}
    for path in sorted(_PACKAGE.rglob("*.py")):
        for m in _TREE_KEY.finditer(path.read_text(encoding="utf-8")):
            built.setdefault(m.group(1), path.relative_to(_PACKAGE).as_posix())
    assert "compare_tree_selected__" in built, "the scan reads the trees' keys"
    missing = {key: where for key, where in built.items() if key not in _PREFIXES}
    assert not missing, (
        "per-view keys a closed panel would leave behind — add them to"
        " per_view_state.SUFFIXED_VARS: " + ", ".join(
            f"{key} ({where})" for key, where in sorted(missing.items())))


def test_every_key_built_with_a_view_id_is_inventoried():
    built = {}
    for path in sorted(_PACKAGE.rglob("*.py")):
        for m in _VIEW_KEY.finditer(path.read_text(encoding="utf-8")):
            built.setdefault(m.group(1), path.relative_to(_PACKAGE).as_posix())
    assert "ui_object_look__" in built, "the scan reads the views' keys"
    missing = {key: where for key, where in built.items()
               if key not in _PREFIXES and key not in _NOT_STATE}
    assert not missing, (
        "per-view keys a closed view would leave behind — add them to"
        " per_view_state.SUFFIXED_VARS: " + ", ".join(
            f"{key} ({where})" for key, where in sorted(missing.items())))


def test_closing_a_compare_panel_leaves_nothing_of_its_tree():
    state = FakeState()
    vid = "view_9"
    # what the Statistics panel and its docked tree build under their id
    state[f"compare_tree_open__{vid}"] = True
    for what in ("selected", "eye", "shown"):
        state[f"compare_tree_{what}__{vid}"] = ["/Porosity/Grid/PHIT"]
    for what in ("selected", "toggle", "ctx"):
        state.change(f"compare_tree_{what}__{vid}")(_handler)
    state.change("ui_compare_items")(_handler)

    per_view_state.teardown(state, vid)

    left = {k: v for k, v in vars(state).items()
            if k.endswith("__" + vid) and v is not None}
    assert left == {}, "the closed panel's keys are nulled"
    assert not any(k.endswith("__" + vid) for k in state._change_callbacks), \
        "and their handlers are gone"
    assert "ui_compare_items" in state._change_callbacks, \
        "the session's own handlers stay"


def test_a_render_view_is_not_given_the_compare_panel_s_keys(monkeypatch):
    # `seed` runs for render views: the keys only a panel creates stay
    # out of them, so a key named `compare_tree_*__<id>` always names the
    # Statistics panel's id
    monkeypatch.setattr(per_view_state, "_LIVE", set())
    state = FakeState()
    per_view_state.seed(state, "view_1")
    seeded = {k for k in vars(state) if k.endswith("__view_1")}
    assert "visible_paths__view_1" in seeded, "a render view's own keys are seeded"
    assert not {k for k in seeded if k.startswith("compare_tree_")}
