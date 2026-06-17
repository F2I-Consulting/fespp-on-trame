"""Shared single-upstream threshold-chain graph logic.

`RepInScene` (per-view) and `ExtractBlockRepresentation` each keep a flat list
of ``ChainEntry`` that forms a tree via ``entry.parent_name``. The graph-walking
primitives below — find an entry by name, detect a visible descendant, and
resolve the effective upstream a (re)wired child reads from — are shared by
both; only the chain's ROOT input proxy (rep source vs per-view extractor) and
the target view differ, and those are passed in by the caller.

These do NOT cover `IjkGrid`'s chain, which is multi-upstream (one ``Threshold``
per active slicer / volume crop) and keeps its own rewiring.

Pure list logic — no ParaView import, import-safe."""


def entry_by_name(chain, name):
    """The ``ChainEntry`` named `name` in `chain`, or None."""
    for e in chain:
        if e.name == name:
            return e
    return None


def has_visible_descendant(chain, name):
    """True iff at least one entry transitively rooted at `name` (excluding
    `name` itself) is visible."""
    for child in (e for e in chain if e.parent_name == name):
        if child.visible:
            return True
        if has_visible_descendant(chain, child.name):
            return True
    return False


def effective_input_for_parent(chain, parent_name, root_input):
    """The upstream proxy a new / refreshed child under `parent_name` should
    read from: `root_input` when `parent_name` is None or no visible ancestor
    remains; otherwise the nearest VISIBLE ancestor's proxy (hidden ancestors
    are skipped so the rendered chain stays connected)."""
    if parent_name is None:
        return root_input
    cursor = entry_by_name(chain, parent_name)
    while cursor is not None and not cursor.visible:
        cursor = entry_by_name(chain, cursor.parent_name)
    if cursor is None:
        return root_input
    return cursor.proxy


def refresh_chain_visibility(chain, view, source, root_input, rep_hidden,
                             force_hide_source=False):
    """Recompute Input wiring + display Visibility for every entry of a
    single-upstream `chain`, then re-assert the rep `source`'s own visibility.

    Rules:
      - each entry's Input is rewired to its effective upstream (nearest
        visible ancestor, else `root_input`);
      - an entry is SHOWN iff it is visible AND has no visible descendant
        (a rendered tip) AND the rep is not hidden;
      - `source` is hidden when the rep is hidden, OR a chain tip is shown,
        OR `force_hide_source` (a channel-less wellbore frame never shows
        its primary).

    The per-class POLICY is supplied by the caller: `view` (target view),
    `source` (the rep's primary proxy to hide/show), `root_input` (the chain
    head — usually == `source`), `rep_hidden` (rep eye / slice / clip), and
    `force_hide_source`. When `view` is None the Inputs are still rewired but
    nothing is shown/hidden (the legacy caller relies on this; the per-view
    caller guards on `view` before calling)."""
    from paraview import simple as pvsimple
    any_shown = False
    for entry in chain:
        upstream = effective_input_for_parent(chain, entry.parent_name, root_input)
        try:
            if entry.proxy.Input is not upstream:
                entry.proxy.Input = upstream
                entry.proxy.UpdatePipeline()
        except Exception as exc:
            pass
        if view is None:
            continue
        try:
            tip = entry.visible and not has_visible_descendant(chain, entry.name)
            if tip and not rep_hidden:
                pvsimple.Show(proxy=entry.proxy, view=view)
                any_shown = True
            else:
                pvsimple.Hide(proxy=entry.proxy, view=view)
        except Exception:
            pass
    if view is not None and source is not None:
        try:
            if rep_hidden or any_shown or force_hide_source:
                pvsimple.Hide(proxy=source, view=view)
            else:
                pvsimple.Show(proxy=source, view=view)
        except Exception:
            pass
