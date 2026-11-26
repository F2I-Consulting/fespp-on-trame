"""PdcScene — Layer V: ONE composite representation of the shared PDC per view.

Contract
--------
Input:     ``view_id``, its ``pv_view`` proxy, the session ``collector``, and
           (optionally) the ``RenderScheduler``.
Behaviour: owns ``main_rep`` — the single COMPOSITE representation of the
           collector in this view — plus ``block_state``, the pure-Python
           desired-state table ``{selector: BlockEntry}``. Every mutator is
           desired-state-FIRST: it edits the table, then ``reconcile()``
           regenerates ALL Block* property lists from the table (the rep is a
           projection of the dict — idempotent repair after any structure
           change), then marks the view dirty on the scheduler (caller
           flushes).
Reads:     the collector source; its own table.
Writes:    ``main_rep`` properties only (BlockSelectors / BlockColorArrayNames
           / Scale / ...) — never trame state.

Why the COMPOSITE rep (and not the leaf_rep monkeypatch's leaf): the per-block
API — ``BlockSelectors``, ``BlockColorArrayNames``, ``BlockLookupTables``,
``BlockOpacities`` … — lives ONLY on the composite
``vtkSMPVRepresentationProxy`` (it is the MultiBlock Inspector's mechanism).
A composite representation is heavy in memory; keeping exactly one per view
makes that cost CONSTANT in the number of objects shown — which is the whole
point of BlockScope. ``Show`` therefore goes through
``leaf_rep.show_composite`` (the ``pvsimple.Show`` captured before the global
leaf monkeypatch), with the pipeline controller as the fallback.
"""
from dataclasses import dataclass

from paraview import simple as pvsimple
from paraview import servermanager as _sm

from fespp_on_trame.engine import legends
# as _ranges: reconcile keeps a dict of the bars' ranges named `ranges`
from fespp_on_trame.engine import ranges as _ranges
from fespp_on_trame.engine.derived_arrays import display_source_of as _display_source
from fespp_on_trame.engine.utils import numfmt
from fespp_on_trame.engine.utils.naming import strip_realization_suffix

# BlockSelectors for an empty visible set: a path no block matches. The
# meaning of an empty list is undocumented upstream and may differ between
# ParaView versions; a never-matching selector renders nothing on all of them.
SENTINEL_NO_BLOCKS = "/__fespp_no_block__"
# Where the view's one colour bar goes (engine/legends: one bar per view).
from fespp_on_trame.engine.blockscope.bars import BAR_CORNER  # noqa: F401, E402


@dataclass
class BlockEntry:
    """Desired per-block display state (one row of the reconcile table)."""
    visible: bool = False
    color_array: str = ""        # empty -> solid / inherited colour
    assoc: str = "POINTS"        # POINTS | CELLS
    # what the colour bar calls the array — the property's one display name
    # (title, component, unit); empty -> the VTK array name
    label: str = ""
    lut_key: str = ""            # LutManager key ("array__viewId")
    opacity: float = 1.0         # while a property paints it
    solid_opacity: float = 1.0   # while it is drawn in its solid colour
    solid_rgb: tuple = None      # None -> no solid colour override
    # a discrete or categorical property: its codes and their names,
    # [{"code", "label"}, …] — the LUT paints one colour per code
    # (categorical_palette); None -> a continuous ramp
    categories: list = None
    # why a discrete property is NOT painted by code (too many codes);
    # "" when it is, or when the property is continuous
    categories_note: str = ""


    def drawn_opacity(self):
        """The opacity it is drawn at: the property's while one paints it,
        else its solid colour's."""
        return self.opacity if self.color_array else self.solid_opacity

class PdcScene:
    """The one composite representation of the shared PDC in one view,
    projected from a desired-state table (see the module docstring)."""

    def __init__(self, view_id, pv_view, collector, scheduler=None):
        self.view_id = str(view_id)
        self.pv_view = pv_view
        # `collector` is the ActiveSource facade (EPC collector, or the ETP
        # store once connected) — resolved on every `ensure_main_rep`, never
        # frozen.
        self._collector = collector
        self._scheduler = scheduler
        self.block_state = {}      # selector -> BlockEntry
        # Selectors currently ISOLATED out of the composite projection (a
        # per-view isolate — slicer crops, threshold chain — renders them
        # through its own leaf displays instead). The eye state is untouched:
        # releasing the isolate restores the block seamlessly.
        self.isolated = set()
        # the vertical domain this view draws ("depth" or "time", the PO,
        # 28/10) and how a block's domain is read (app/features/view_domain):
        # a block of the other domain keeps its eye but is not drawn; one
        # whose domain is unknown is drawn in both
        self.vdomain = None
        self.domain_of = None
        self.main_rep = None
        # whether this view draws the shared source's selection: its ONE
        # selection belongs to the view that made it (show_selection)
        self.selection_shown = True
        self._bound_src = None     # source proxy main_rep was Shown on
        # (lut, title, array, selectors) of every table the last reconcile
        # found painting the view — one per array name, several names can
        # share a table (the realizations of one property)
        self._last_bars = []
        # the view's one colour bar among the tables painting it
        # (engine/blockscope/bars)
        from fespp_on_trame.engine.blockscope.bars import ViewBars
        self.bars = ViewBars(self)
        self._zscale = 1.0
        # the X / Y / Z cut of the whole scene (the Geometry slicer on the
        # scene, 29/10; engine/blockscope/scene_crop): main_rep draws its
        # first piece, one more composite rep each further piece, the same
        # block properties copied on them ([{"src", "rep"}])
        self.crop = None
        self._extras = []
        # an object of the other vertical domain drawn here with the
        # time-depth law (the PO, 30/10; engine/blockscope/domain_convert):
        # the selectors allowed, the law's table, the stage on the source
        self.converted = set()
        self.convert_cube = ""      # the velocity model's key in domain_convert.CUBES
        # () -> [(lut, title, array, selectors)]: the tables painting the
        # view that are no block of it (the velocity model,
        # app/features/time_depth_view), listed with the blocks' for the bar
        self.extra_bars = None
        self.flats_of = None       # selector -> flat indices (view_domain.attach)
        self._convert = None

    # ------------------------------------------------------------------
    # main_rep lifecycle

    def ensure_main_rep(self):
        """Get-or-create the one composite rep of the ACTIVE source in this
        view. Self-healing: when the active source flipped since the rep was
        created (ETP connect after panel creation, disconnect back to EPC),
        the stale rep is released and re-shown on the new source: the source
        is looked up on every call, never frozen at creation."""
        self._drop_stale_stages()
        try:
            base = _display_source(self._collector)
        except Exception:
            base = None
        if base is None or self.pv_view is None:
            return self.main_rep
        base = self._converted_base(base)
        # a cut scene draws its pieces, the first by main_rep
        tips = (self.crop.tips(base, self._cut_blocks()) if self.crop is not None else []) or [base]
        src = tips[0]
        self._sync_extras(tips[1:])
        if self.main_rep is not None:
            if self._bound_src is src:
                return self.main_rep
            from fespp_on_trame.engine.etp_debug import etp_debug
            etp_debug(f"pdc[{self.view_id}]: source flip -> rebinding main_rep")
            self._release_main()
        rep = self._show_composite(src)
        if rep is not None:
            self.main_rep = rep
            self._bound_src = src
            # SET the draw style instead of inheriting the guess of
            # ParaView's Show(): for an ETP source that guess can be Outline
            # (a bounding box and nothing else).
            self.apply_rep_style()
            self._apply_selection_shown()
            try:
                from fespp_on_trame.engine.etp_debug import etp_debug
                etp_debug(f"pdc[{self.view_id}]: main_rep created "
                          f"id={rep.SMProxy.GetGlobalIDAsString()} "
                          f"src={src.SMProxy.GetGlobalIDAsString()}")
            except Exception:
                pass
        return self.main_rep

    def show_selection(self, on):
        """Draw the shared source's selection in this view, or not. ParaView
        keeps ONE selection per source and every representation of it draws
        that selection; a view that did not make it hides it with
        SelectionVisibility (the PO, 16/10: a selection made in one view
        must not show in the others)."""
        self.selection_shown = bool(on)
        self._apply_selection_shown()

    def _apply_selection_shown(self):
        if self.main_rep is None:
            return
        try:
            self.main_rep.SelectionVisibility = 1 if self.selection_shown else 0
        except Exception as exc:
            print(f"[fespp] selection visibility ({self.view_id}, {self.main_rep.GetXMLName()}"
                  f" of {self._bound_src.GetXMLName() if self._bound_src is not None else None}):", exc, flush=True)

    def _show_composite(self, src):
        # The pvsimple.Show captured before the leaf monkeypatch: a rep
        # created this way re-renders on a plain BlockSelectors edit. A rep
        # created by the pipeline controller can keep rendering the OLD block
        # selection after an edit, so the controller is only the fallback.
        try:
            from fespp_on_trame.engine.sources import leaf_rep
            rep = leaf_rep.show_composite(src, self.pv_view)
            if rep is not None:
                return rep
        except Exception:
            pass
        # Fallback: the ParaView pipeline controller (registers the rep for
        # cascading unregister on view delete).
        try:
            from paraview.modules.vtkRemotingViews import (
                vtkSMParaViewPipelineControllerWithRendering,
            )
            controller = vtkSMParaViewPipelineControllerWithRendering()
            rep_sm = controller.Show(src.SMProxy, 0, self.pv_view.SMProxy)
            if rep_sm is not None:
                return _sm._getPyProxy(rep_sm)
        except Exception as exc:
            print(f"[fespp] pdc_scene show error ({self.view_id}):", exc,
                  flush=True)
        return None

    def apply_rep_style(self, style=None):
        """Set this view's "Represent By" on the composite rep. BlockScope
        draws every block through ONE rep, so the style is per VIEW."""
        rep = self.main_rep
        if rep is None:
            return
        if style is None:
            try:
                from trame.app import get_server
                style = getattr(get_server().state,
                                f"ui_rep_style__{self.view_id}", None)
            except Exception:
                style = None
        try:
            rep.Representation = style or "Surface"
        except Exception as exc:
            # an unsupported style for this data type must not kill the view
            print(f"[fespp] rep style ({self.view_id}) {style!r}:", exc,
                  flush=True)
        self._copy_to_extras(rep)

    def release(self):
        """Drop the composite reps and the scene's cut (view close).
        block_state is kept — a rebind re-projects it onto a new rep via
        reconcile."""
        self._release_main()
        self._sync_extras([])
        crop, self.crop = self.crop, None
        if crop is not None:
            crop.release()

    # ------------------------------------------------------------------
    # the scene's cut (the Geometry slicer on the scene)

    def set_crop(self, boxes, bounds=None, live=False):
        """The scene of this view cut to `boxes` ([[x0, x1], [y0, y1], [z0,
        z1]] each, the scene's coordinates, shown together) in a scene of
        `bounds`; None or [] draws it whole. `live`: a step of a drag or of
        the player (the mark moves, engine/blockscope/scene_crop)."""
        if not boxes:
            if self.crop is None:
                return
            print(f"[fespp] journal composite ({self.view_id}): scene whole again", flush=True)
            crop, self.crop = self.crop, None
            self.reconcile()          # main_rep back on the source, no extra rep
            crop.release()
            self._mark_dirty()
            return
        if not live or self.crop is None:
            print(f"[fespp] journal composite ({self.view_id}): scene cut, {len(boxes)} box(es),"
                  f" {len(self.isolated)} isolated, live={live}", flush=True)
        from fespp_on_trame.engine.blockscope.scene_crop import SceneCrop
        if self.crop is None:
            self.crop = SceneCrop(self.view_id)
        try:
            base = _display_source(self._collector)
        except Exception as exc:
            print(f"[fespp] scene cut ({self.view_id}): no source to cut ({exc})", flush=True)
            base = None
        if base is None:
            return
        if self.crop.set_boxes(base, boxes, bounds, self._cut_blocks()):
            # what the view draws changed (cut, whole again, new stages):
            # the reps move to it; a step otherwise only moves the mark
            self.reconcile()
            self.crop.drop_stale()
        self._mark_dirty()

    def _drop_stale_stages(self):
        """The stages the representations left at the previous call (they
        were rebound then; a stage still drawn is never deleted)."""
        if self._convert is not None:
            self._convert.drop_stale()
        if self.crop is not None:
            self.crop.drop_stale()

    def _convert_flats(self):
        """The flat indices of the blocks drawn converted: those of the
        other domain among `converted`, when the law can convert."""
        if not self.converted or self.flats_of is None or not self.convert_cube:
            return set()
        out = set()
        for sel in self.converted & (self.shown_selectors() - self.isolated):
            if self.domain_of is not None and self.domain_of(sel) not in (None, self.vdomain):
                out.update(self.flats_of(sel) or ())
        return out

    def _converted_base(self, base):
        """`base` with the converted blocks' z moved, or `base` itself."""
        flats = self._convert_flats()
        if not flats:
            if self._convert is not None:
                self._convert.park()
            return base
        if self._convert is None:
            from fespp_on_trame.engine.blockscope.domain_convert import DomainConvert
            self._convert = DomainConvert(self.view_id)
        return self._convert.tip(base, flats, self.convert_cube, self.vdomain)

    def _cut_blocks(self):
        """The blocks a cut scene extracts: those main_rep draws (the
        visible ones of the view's domain, not given up to an isolate)."""
        return sorted(self.shown_selectors() - self.isolated) or [SENTINEL_NO_BLOCKS]

    def crop_tip_ids(self):
        """The global ids of what the cut scene draws (picking maps a cell
        picked there back to the source's)."""
        return self.crop.tip_ids() if self.crop is not None else set()

    def _sync_extras(self, tips):
        """One composite rep per piece after the first, on `tips`."""
        keep = []
        for tip in tips:
            have = next((e for e in self._extras if e["src"] is tip), None)
            if have is None:
                rep = self._show_composite(tip)
                if rep is None:
                    continue
                have = {"src": tip, "rep": rep}
            keep.append(have)
        for e in self._extras:
            if all(e is not k for k in keep):
                try:
                    e["rep"].Visibility = 0
                    pvsimple.Delete(e["rep"])
                except Exception as exc:
                    print(f"[fespp] scene cut: a rep not deleted ({self.view_id}): {exc}", flush=True)
        self._extras = keep

    def _copy_to_extras(self, rep):
        """The extra pieces' reps take every property of main_rep but its
        input: the same blocks, colours, tables, style and scale."""
        for e in self._extras:
            try:
                e["rep"].SMProxy.Copy(rep.SMProxy, "vtkSMInputProperty", 0)
                e["rep"].SMProxy.UpdateVTKObjects()
            except Exception as exc:
                print(f"[fespp] scene cut: a piece's rep not dressed ({self.view_id}): {exc}",
                      flush=True)

    def _release_main(self):
        """Drop main_rep only (a source flip rebinds it)."""
        rep, self.main_rep = self.main_rep, None
        self._bound_src = None
        if rep is None:
            return
        try:
            rep.Visibility = 0
            pvsimple.Delete(rep)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Desired-state mutators (state first -> reconcile -> mark dirty)

    def ensure_entry(self, selector) -> "BlockEntry":
        entry = self.block_state.get(selector)
        if entry is None:
            entry = BlockEntry()
            self.block_state[selector] = entry
        return entry

    def prune(self, keep_selectors) -> None:
        """Drop table rows whose selector is no longer loaded (Selectors
        removal): a row under a loaded one stays — a log shown is the row of
        its channel, under its frame's. Caller reconciles."""
        keep = set(keep_selectors or ())

        def kept(selector):
            path = selector
            while path:
                if path in keep:
                    return True
                path = path.rsplit("/", 1)[0]
            return False

        for selector in [s for s in self.block_state if not kept(s)]:
            self.block_state.pop(selector, None)
        # an isolated block that is gone must not stay subtracted from the
        # visible set: when it comes back, it comes back visible
        self.isolated = {s for s in self.isolated if kept(s)}

    def set_visible(self, selector, visible) -> None:
        self.ensure_entry(selector).visible = bool(visible)
        self.reconcile()
        self._mark_dirty()

    def set_visible_many(self, show, hide=()) -> None:
        """Flip a whole eye set with ONE reconcile. ``reconcile`` rebuilds
        every Block* list and re-sweeps the view's representations, so calling
        ``set_visible`` per selector would make a single click cost one or
        more reconciles per object."""
        for selector in hide:
            self.ensure_entry(selector).visible = False
        for selector in show:
            self.ensure_entry(selector).visible = True
        self.reconcile()
        self._mark_dirty()

    def set_color(self, selector, array, assoc="POINTS", lut_key="",
                  label="", categories=None, categories_note="") -> None:
        entry = self.ensure_entry(selector)
        entry.color_array = array or ""
        entry.assoc = assoc or "POINTS"
        entry.lut_key = lut_key or ""
        entry.label = label or ""
        entry.categories = list(categories) if categories else None
        entry.categories_note = categories_note or ""
        self.reconcile()
        self._mark_dirty()

    def relabel(self, array, label) -> None:
        """A new display name for every block coloured by `array` (the
        component read changed): the bar's title follows."""
        touched = False
        for entry in self.block_state.values():
            if entry.color_array == array and entry.label != (label or ""):
                entry.label = label or ""
                touched = True
        if touched:
            self.reconcile()
            self._mark_dirty()

    def set_zscale(self, z) -> None:
        try:
            self._zscale = float(z)
        except (TypeError, ValueError):
            return
        self.reconcile()
        self._mark_dirty()

    def set_isolated(self, selector, on) -> None:
        if on:
            self.isolated.add(selector)
        else:
            self.isolated.discard(selector)
        print(f"[fespp] journal composite ({self.view_id}): block {selector[-40:]!r}"
              f" {'isolated' if on else 'back'}, {len(self.isolated)} isolated, cut={self.crop is not None}", flush=True)
        self.reconcile()
        self._mark_dirty()

    def visible_selectors(self) -> set:
        return {s for s, e in self.block_state.items() if e.visible}

    def shown_selectors(self) -> set:
        """The blocks this view draws: the visible ones of its domain."""
        visible = self.visible_selectors()
        if not self.vdomain or self.domain_of is None:
            return visible
        return {s for s in visible
                if self.domain_of(s) in (None, self.vdomain) or s in self.converted}

    # ------------------------------------------------------------------
    # Projection

    def reconcile(self) -> None:
        """Regenerate ALL Block* lists on main_rep from block_state. Idempotent
        — safe to re-run after any structure change / view split / reconnect."""
        rep = self.ensure_main_rep()
        if rep is None:
            return
        visible = sorted(self.shown_selectors() - self.isolated)
        try:
            # CRITICAL: BlockSelectors are matched against the assembly the
            # rep's `Assembly` property selects — the default 'Hierarchy'
            # exposes /Root/... paths, so our /data/... selectors would match
            # NOTHING and the rep would keep rendering every block.
            # 'Assembly' = FESPP's custom vtkDataAssembly, whose node paths
            # ARE the Selectors contract.
            if rep.GetProperty("Assembly") is not None:
                rep.Assembly = 'Assembly'
            rep.BlockSelectors = visible or [SENTINEL_NO_BLOCKS]
            # Force-push: a later EDIT of the list (one block hidden) reaches
            # the SM property, but without this push the composite mapper
            # keeps rendering the old selection.
            rep.SMProxy.UpdateProperty("BlockSelectors", 1)
        except Exception as exc:
            print(f"[fespp] reconcile BlockSelectors error ({self.view_id}):",
                  exc, flush=True)
        # Colour projection — PER BLOCK: a triplet (selector, association,
        # array) and a lookup table per coloured block, paired index-wise,
        # so a grid keeps its property while a log keeps its channel. A
        # GLOBAL anchor naming a real array must stay on or ParaView
        # ignores every triplet; for a continuous table WHICH array it
        # names does not matter (the anchor choice is below). The anchor
        # alone colours nothing else: every coloured block needs its own
        # triplet, or it renders white.
        # The blocks an isolate shows through its crops (slicers,
        # thresholds) are off the composite but keep their entry: their
        # table and bar stay, the crops paint with the same table.
        shown = sorted(self.shown_selectors())
        coloured = [(s, self.block_state[s]) for s in shown
                    if self.block_state[s].color_array]
        try:
            # one table per array of the view, its range the union over the
            # blocks it paints (two wells' channels of one name share it)
            ranges = {}
            # the same unions, NOT opened up: a field of no width is a field
            # every cell shares, and the bar has to say so (below)
            flat = {}
            for sel, entry in coloured:
                if entry.categories:
                    continue
                raw = self._block_raw_range(entry, sel)
                rng = (_ranges.widen_for_bar(*raw) if raw is not None
                       else self._array_range(entry))
                if rng is None:
                    continue
                cur = ranges.get(entry.color_array)
                ranges[entry.color_array] = (rng if cur is None else
                                             (min(cur[0], rng[0]), max(cur[1], rng[1])))
                if raw is not None:
                    cr = flat.get(entry.color_array)
                    flat[entry.color_array] = (raw if cr is None else
                                               (min(cr[0], raw[0]), max(cr[1], raw[1])))
            luts_by_array, bars = {}, []
            # which blocks each array paints — the Legends card activates
            # one of them when its table is picked
            sels_by_array = {}
            for sel, entry in coloured:
                sels_by_array.setdefault(entry.color_array, []).append(sel)
            for sel, entry in coloured:
                lut = luts_by_array.get(entry.color_array)
                if lut is None:
                    lut = self._scoped_lut(entry.color_array)
                    if entry.categories:
                        # a property whose values are codes: one colour
                        # per code, the codes named on the bar; a range
                        # means nothing to an indexed lookup
                        from fespp_on_trame.engine import categorical_palette
                        categorical_palette.apply(lut, entry.categories)
                    else:
                        # more codes than a legend can name, indexed by the
                        # plugin: a ramp (or the file's own colours, its bar
                        # without labels) — categorical_palette.tame
                        from fespp_on_trame.engine import categorical_palette
                        categorical_palette.tame(lut)
                        rng = ranges.get(entry.color_array)
                        if rng is not None and not self._range_pinned(lut):
                            lut.RescaleTransferFunction(rng[0], rng[1])
                            # its opacity curve too: left on ParaView's 0..1,
                            # its top node falls outside a narrower table
                            # (0..0.9, say) and the Colormap graph gets ONE
                            # node — painted all in the table's first colour
                            self._rescale_pwf(entry.color_array, rng)
                    luts_by_array[entry.color_array] = lut
                    # A CONSTANT FIELD SAYS SO ON ITS BAR. Colouring by an
                    # array every cell shares (an activity flag set on every
                    # cell, say) paints the whole object one flat colour —
                    # the middle of the map — which reads exactly like "the
                    # grid has lost its colours". The value is on the bar,
                    # so the reader sees the data and not a failure.
                    title = entry.label or entry.color_array
                    raw = flat.get(entry.color_array)
                    if raw is not None and raw[1] - raw[0] <= 1e-12 * max(
                            1.0, abs(raw[0]), abs(raw[1])):
                        title = f"{title} — constant {numfmt.fmt(raw[0])}"
                    bars.append((lut, title, entry.color_array,
                                 sels_by_array[entry.color_array]))
            # The anchor is the block whose table is INDEXED (a property
            # coloured by code) when there is one. ParaView's per-block
            # road cannot apply an indexed table: a categorical grid that
            # is not the anchor leaves the frame (background, alpha 0)
            # even with every block attribute correct on the mapper,
            # whereas a continuous property renders either way. Only the
            # representation-level road maps an indexed table, so the first
            # array of codes takes it; another array of codes in the view
            # takes the per-block road with its colours as a table of
            # steps (`_stepped_table`), which that road can apply.
            anchor = (next((e for _s, e in coloured if e.categories), coloured[0][1])
                      if coloured else None)
            triplets, luts = [], []
            for sel, entry in coloured:
                if sel in self.isolated:
                    continue      # painted by its crops, not the composite
                triplets += [sel, "1" if entry.assoc == "CELLS" else "0",
                             entry.color_array]
                lut = luts_by_array[entry.color_array]
                if entry.categories and (entry.assoc, entry.color_array) != (anchor.assoc, anchor.color_array):
                    lut = self._stepped_table(entry.color_array, lut)
                luts.append(lut)
            if rep.GetProperty("BlockColorArrayNames") is not None:
                rep.BlockColorArrayNames = triplets
                rep.SMProxy.UpdateProperty("BlockColorArrayNames", 1)
            lut_prop = rep.SMProxy.GetProperty("BlockLookupTables")
            if lut_prop is not None:
                lut_prop.RemoveAllProxies()
                for lut in luts:
                    lut_prop.AddProxy(lut.SMProxy)
                rep.SMProxy.UpdateProperty("BlockLookupTables", 1)
            if coloured:
                rep.ColorArrayName = [anchor.assoc, anchor.color_array]
                rep.LookupTable = luts_by_array[anchor.color_array]
            else:
                rep.ColorArrayName = ['POINTS', '']
            self._last_bars = bars
            self._sync_scalar_bars(self._with_extra_bars(bars))
            # Solid family colours as native per-block BlockColors
            # (selector, r, g, b): applied per visible entry that carries a
            # solid_rgb and no colour array; a block coloured by an array
            # keeps its array mapping (BlockColors would override it).
            if rep.GetProperty("BlockColors") is not None:
                quads = []
                for selector in visible:
                    entry = self.block_state[selector]
                    if entry.solid_rgb and not entry.color_array:
                        r, g, b = entry.solid_rgb
                        # StringVectorProperty: 4 string elements per command.
                        quads.extend([selector, str(r), str(g), str(b)])
                rep.BlockColors = quads
            # the opacity of what paints an object (app/features/object_look),
            # as native per-block BlockOpacities (selector, value)
            if rep.GetProperty("BlockOpacities") is not None:
                pairs = []
                for selector in visible:
                    op = self.block_state[selector].drawn_opacity()
                    if op is not None and op < 0.999:
                        pairs.extend([selector, str(float(op))])
                rep.BlockOpacities = pairs
        except Exception as exc:
            print(f"[fespp] reconcile color error ({self.view_id}):",
                  exc, flush=True)
        try:
            # data_load's parent-hide of the per-rep pipeline (or any stray
            # leaf-path write) may have zeroed it; the projection owns it —
            # reassert.
            rep.Visibility = 1
        except Exception:
            pass
        try:
            rep.Scale = [1.0, 1.0, self._zscale]
        except Exception:
            pass
        try:
            rep.SMProxy.UpdateVTKObjects()
        except Exception:
            pass
        # the further pieces of a cut scene: dressed as main_rep
        self._copy_to_extras(rep)

    # ------------------------------------------------------------------
    # Read-only views, for what reads the scene from outside (the colour bar,
    # the categorical palette, the headless harness): no private read
    # crosses the class (overhaul slice 8)

    def scoped_lut(self, array_name):
        """The view's own colour table of `array_name`."""
        return self._scoped_lut(array_name)

    def stepped_table(self, array_name, lut):
        """The indexed table of `array_name` as the table of steps a
        composite's per-block road can apply."""
        return self._stepped_table(array_name, lut)

    def range_pinned(self, lut):
        """The reader fixed this table's range: nothing rescales it."""
        return self._range_pinned(lut)

    def block_range(self, entry, selector):
        """The range a block's colouring shows (hidden cells skipped)."""
        return self._block_range(entry, selector)

    def block_raw_range(self, entry, selector):
        """The block's full data range, every cell counted."""
        return self._block_raw_range(entry, selector)

    def _stepped_table(self, array, lut):
        """The indexed table of `array` as a table of steps, for the
        composite's per-block road (categorical_palette.steps_from); the
        indexed table itself when the steps cannot be written."""
        from fespp_on_trame.engine import categorical_palette
        try:
            twin = self._scoped_lut(array + categorical_palette.STEPS)
            if twin is not None and categorical_palette.steps_from(twin, lut):
                return twin
        except Exception as exc:
            print(f"[fespp] stepped table of {array} ({self.view_id}): {exc!r}", flush=True)
        return lut

    def _scoped_lut(self, array_name):
        """Per-VIEW LUT (registered ``array__viewId``) via this view's
        ViewScene when available — the Colormap editor (COE) resolves the
        same scoped name, and per-view colormap edits must not bleed across
        views. Falls back to the global LUT when the view has no ViewScene
        (single-view / early boot)."""
        try:
            from trame.app import get_server
            reg = getattr(get_server().context, "view_resources", None)
            vres = reg.get(self.view_id) if reg is not None else None
            if vres is not None:
                lut = vres.get_or_create_lut(array_name)
                if lut is not None:
                    return lut
        except Exception:
            pass
        return pvsimple.GetColorTransferFunction(array_name)

    def _rescale_pwf(self, array_name, rng):
        """The view's opacity function of `array_name` onto the range its
        colour table was just rescaled to (the same scoped name as
        `_scoped_lut`; proportional, so a curve the reader drew keeps its
        shape)."""
        try:
            from trame.app import get_server
            reg = getattr(get_server().context, "view_resources", None)
            vres = reg.get(self.view_id) if reg is not None else None
            pwf = (vres.get_or_create_pwf(array_name) if vres is not None
                   else pvsimple.GetOpacityTransferFunction(array_name))
            if pwf is not None:
                pwf.RescaleTransferFunction(rng[0], rng[1])
        except Exception as exc:
            print(f"[fespp] opacity rescale ({self.view_id}) {array_name!r}:",
                  exc, flush=True)

    @staticmethod
    def _range_pinned(lut):
        """A user-chosen range (Colormap card: custom / all-time-steps /
        all-realizations) sets AutomaticRescaleRangeMode='Never' — the
        reconcile must not snap it back to the data on every eye toggle."""
        try:
            return "Never" in str(lut.AutomaticRescaleRangeMode)
        except Exception:
            return False

    # ------------------------------------------------------------------
    # The colour bar (engine/blockscope/bars.ViewBars)

    @property
    def hidden_bars(self):
        return self.bars.hidden

    @property
    def bar_target(self):
        return self.bars.target

    @bar_target.setter
    def bar_target(self, array):
        self.bars.target = array or ""

    @property
    def _bar_focus(self):
        return self.bars.focus

    def resync_bars(self):
        """Show the view's bar again — after ParaView's own Hide swept it
        away (an isolate hiding a crop: the sweep keeps only the tables a
        VISIBLE display names globally, and the composite's per-block
        tables are named by none)."""
        self.bars.sync(self._with_extra_bars(self._last_bars))

    def _with_extra_bars(self, bars):
        """`bars` and the tables of what paints the view without being one
        of its blocks (`extra_bars`)."""
        if self.extra_bars is None:
            return bars
        try:
            return list(bars) + list(self.extra_bars() or [])
        except Exception as exc:
            print(f"[fespp] extra colour tables ({self.view_id}): {exc!r}", flush=True)
            return bars

    def set_bar_visible(self, array, on) -> None:
        self.bars.set_visible(array, on)

    def bar_visible(self, array) -> bool:
        return self.bars.visible(array)

    def set_bar_target(self, array) -> bool:
        return self.bars.set_target(array)

    def begin_bar_gesture(self) -> None:
        self.bars.begin_gesture()

    def end_bar_gesture(self) -> None:
        self.bars.end_gesture()

    def bar_table(self):
        return self.bars.table()

    def legend_tables(self):
        return self.bars.legend()

    def bar_length(self):
        """How much of the view's height its colour bar takes, 0 with none."""
        return self.bars.shown_length()

    def table_bar_hidden(self, table) -> bool:
        return self.bars.table_hidden(table)

    def _sync_scalar_bars(self, bars):
        self.bars.sync(bars)

    def _block_range(self, entry, selector):
        """`_block_raw_range`, opened up when it has no width (engine/ranges)."""
        raw = self._block_raw_range(entry, selector)
        return None if raw is None else _ranges.widen_for_bar(*raw)

    def _data_sources(self):
        """Where an array's data is read: the reader (its own arrays, kept
        current by the reads), then what displays chain on (a computed
        array, engine/derived_arrays). One source on the Globe."""
        out = []
        for get in (lambda: self._collector.get_source(),
                    lambda: _display_source(self._collector)):
            try:
                src = get()
            except Exception as exc:
                print(f"[fespp] data source ({self.view_id}):", exc, flush=True)
                continue
            if src is not None and all(src is not o for o in out):
                out.append(src)
        return out

    def _block_raw_range(self, entry, selector):
        """Data range of the entry's array on the block `selector` paints,
        AS IT IS (not widened).

        Read on the block's own datasets (the app runs in the server
        process: the PDC is at hand), because the composite's data
        information spans EVERY block carrying an array of that name, and
        a log channel's name is shared by the placeholder blocks of the
        other frames (which would give a real curve a range of 0 to 1e-38).
        None when the block or the array cannot be read."""
        for src in self._data_sources():
            raw = self._block_raw_range_on(src, entry, selector)
            if raw is not None:
                return raw
        return None

    def _block_raw_range_on(self, src, entry, selector):
        try:
            pdc = src.GetClientSideObject().GetOutputDataObject(0)
            asm = pdc.GetDataAssembly() if pdc is not None else None
            if asm is None or not selector:
                return None
            node = asm.GetFirstNodeByPath(selector)
            if node is None or node < 0:
                return None
            lo, hi = None, None
            for i in asm.GetDataSetIndices(node, True):
                pds = pdc.GetPartitionedDataSet(i)
                for j in range(pds.GetNumberOfPartitions() if pds is not None else 0):
                    ds = pds.GetPartition(j)
                    if ds is None:
                        continue
                    data = (ds.GetPointData() if entry.assoc == "POINTS"
                            else ds.GetCellData())
                    arr = data.GetArray(entry.color_array) if data is not None else None
                    if arr is None or arr.GetNumberOfTuples() == 0:
                        continue
                    rng = _ranges.finite_range(arr, data.GetArray("vtkGhostType"))
                    if rng is None:
                        continue
                    r0, r1 = rng
                    lo = r0 if lo is None else min(lo, r0)
                    hi = r1 if hi is None else max(hi, r1)
            if lo is not None and hi is not None and lo <= hi:
                return (lo, hi)
        except Exception as exc:
            # the composite's range takes over; say which block refused
            print(f"[fespp] block range ({self.view_id}) {selector!r}"
                  f" {entry.color_array!r}:", exc, flush=True)
        return None

    def _array_range(self, entry):
        """Data range of the entry's array, from the source's cheap
        vtkPVDataInformation (component -1 = magnitude). Never ColorBy."""
        try:
            for src in self._data_sources():
                di = src.GetDataInformation()
                adi = (di.GetPointDataInformation() if entry.assoc == "POINTS"
                       else di.GetCellDataInformation())
                ai = adi.GetArrayInformation(entry.color_array)
                if ai is None:
                    continue
                rng = ai.GetComponentRange(-1)
                if rng is not None and rng[0] <= rng[1]:
                    return _ranges.widen_for_bar(rng[0], rng[1])
                return None
        except Exception:
            pass
        return None

    def _mark_dirty(self):
        if self._scheduler is not None:
            self._scheduler.mark_dirty(self.view_id)
