"""The colour bar of a 3D view (overhaul slice 7).

ONE colour bar per view (engine/legends). The arrays painting the view's
shown blocks are folded into TABLES, keyed by colour table — the
realizations of one property share a table under several names — and the
bar goes to the table the Colormap card edits when it paints the view, else
stays on the table it was on, else goes to one that has just started
painting. The reader can switch a table's bar off (the Colormap card's
box); the choice stays with the table.

`ViewBars` used to be the bar half of `PdcScene`, which composes it and
keeps its methods (`set_bar_target`, `begin_bar_gesture`, `legend_tables`,
…) as delegations: the scene draws, the bars decide which table speaks."""
from paraview import simple as pvsimple

from fespp_on_trame.engine import legends
from fespp_on_trame.engine.utils import numfmt
from fespp_on_trame.engine.utils.naming import strip_realization_suffix

BAR_CORNER = "Lower Right Corner"


class ViewBars:
    """The tables painting one view and the one bar among them."""

    def __init__(self, scene):
        # the scene: its view proxy, its id, its scoped colour tables, its
        # render scheduling
        self._scene = scene
        # one per TABLE: {key, lut, title, arrays, selectors}, in the view's order
        self.tables = []
        # the array the Colormap card edits in this view (`set_target`) — the
        # view's one bar goes to its table when it paints; and the key of the
        # table the bar is on
        self.target = ""
        self.focus = None
        # (table keys, bar table) before the eye pass being applied
        # (`begin_gesture`), None outside one
        self._gesture = None
        # the tables whose bar the reader turned OFF in this view, by array
        # name without its realization suffix — a realization switch keeps
        # the choice
        self.hidden = set()

    # ------------------------------------------------------------------
    # The reader's choices

    def set_visible(self, array, on) -> None:
        """The Colormap card's box: the bar of ONE table (the array the card
        edits) on or off."""
        if not array:
            return
        key = strip_realization_suffix(array)
        if on:
            self.hidden.discard(key)
        else:
            self.hidden.add(key)
        self.show_focus()
        self._scene._mark_dirty()

    def visible(self, array) -> bool:
        return bool(array) and strip_realization_suffix(array) not in self.hidden

    def set_target(self, array) -> bool:
        """The array the Colormap card edits in this view, "" for none. True
        when the view's bar moved to another table (the caller renders)."""
        self.target = array or ""
        if self._gesture is not None:
            return False      # chosen once, at end_gesture
        if not self._choose([t["key"] for t in self.tables], self.focus):
            return False
        self.show_focus()
        self._scene._mark_dirty()
        return True

    def begin_gesture(self) -> None:
        """An eye pass is about to run several reconciles — one per coloured
        path, the clears, then the visibility flip. The bar is chosen ONCE,
        at `end_gesture`, against the tables as they were before: a
        half-applied state (a log's table gone before the one replacing it
        shows) would move the bar to a table the reader did not touch."""
        self._gesture = ([t["key"] for t in self.tables], self.focus)

    def end_gesture(self) -> None:
        gesture, self._gesture = self._gesture, None
        if gesture is None:
            return
        self._choose(*gesture)
        self.show_focus()
        self._scene._mark_dirty()

    # ------------------------------------------------------------------
    # What the Legends card lists

    def table(self):
        """The table holding the view's bar, or None when nothing colours
        the view. Its bar may be switched off (`table_hidden`)."""
        return next((t for t in self.tables if t["key"] == self.focus), None)

    def legend(self):
        """Every table colouring the view, in the view's order, the key of
        the one holding the bar, and the keys whose bar is switched off."""
        hidden = {t["key"] for t in self.tables if self.table_hidden(t)}
        return list(self.tables), self.focus, hidden

    def table_hidden(self, table) -> bool:
        return any(not self.visible(a) for a in table["arrays"])

    # ------------------------------------------------------------------
    # From the scene's reconcile

    def sync(self, bars):
        """`bars` = [(lut, title, array, selectors)], one per array painting
        a shown block, folded into tables; the bar then chosen and shown."""
        tables, by_key = [], {}
        for lut, title, array, sels in bars:
            key = lut.GetGlobalIDAsString()
            table = by_key.get(key)
            if table is None:
                table = by_key[key] = {"key": key, "lut": lut, "title": title,
                                       "arrays": [], "selectors": []}
                tables.append(table)
            table["arrays"].append(array)
            table["selectors"].extend(s for s in sels if s not in table["selectors"])
        previous = [t["key"] for t in self.tables]
        self.tables = tables
        if self._gesture is not None:
            return      # an eye pass in progress: chosen at its end
        self._choose(previous, self.focus)
        self.show_focus()

    def _target_key(self):
        """The table of the array the Colormap card edits: the same scoped
        table the card resolves, so the realizations of one property, one
        table under several names, match."""
        if not self.target:
            return None
        try:
            return self._scene.scoped_lut(self.target).GetGlobalIDAsString()
        except Exception as exc:
            print(f"[fespp] bar target ({self._scene.view_id}):", exc, flush=True)
            return None

    def _choose(self, base_keys, base_focus) -> bool:
        """The bar's table, chosen against the state before the change;
        True when it moved. Nothing painting keeps the choice: a scene being
        refilled (the Globe's, its eyes replayed once it is built) finds
        its table again when it paints."""
        keys = [t["key"] for t in self.tables]
        if not keys:
            return False
        focus = legends.choose_focus(keys, self._target_key(), base_focus, base_keys)
        moved = focus != self.focus
        self.focus = focus
        return moved

    def shown_length(self):
        """How much of the view's height the bar takes (`ScalarBarLength`), 0
        with none shown."""
        view = self._scene.pv_view
        table = self.table()
        if view is None or table is None or self.table_hidden(table):
            return 0
        try:
            return float(pvsimple.GetScalarBar(table["lut"], view).ScalarBarLength)
        except Exception as exc:
            print(f"[fespp] scalar bar length ({self._scene.view_id}):", exc, flush=True)
            return 0

    def show_focus(self):
        """The bar of the focus table, unless the reader switched it off;
        every other bar of the view hidden, strays included. A bar is
        created for that table only: GetScalarBar makes a visible one. A
        title already names the component when one is read: ParaView's own
        component suffix would say it twice."""
        view = self._scene.pv_view
        if view is None:
            return
        try:
            keep = None
            table = self.table()
            if table is not None and not self.table_hidden(table):
                sb = pvsimple.GetScalarBar(table["lut"], view)
                dress(sb, table["title"])
                _size_for_codes(sb, table["lut"])
                sb.Visibility = 1
                keep = table["key"]
            for r in view.Representations:
                if r.GetXMLName() != "ScalarBarWidgetRepresentation":
                    continue
                lut = getattr(r, "LookupTable", None)
                if (lut is None or lut.GetGlobalIDAsString() != keep) \
                        and int(getattr(r, "Visibility", 0)):
                    r.Visibility = 0
        except Exception as exc:
            print(f"[fespp] scalar bar sync error ({self._scene.view_id}):", exc, flush=True)


def dress(sb, title):
    """A scalar bar as every view shows one: its title alone (a title
    already names the component), the same four digits as the Colormap
    card, in BAR_CORNER."""
    sb.Title = title
    sb.ComponentTitle = ""
    sb.RangeLabelFormat = numfmt.SCALAR_BAR_RANGE_FORMAT
    sb.WindowLocation = BAR_CORNER


def _size_for_codes(sb, lut):
    """A bar painted by code lists every code with a leader line: past a
    dozen the labels overflow the view at the default length and font. The
    bar grows with the codes and its labels shrink; a ramp keeps ParaView's
    defaults."""
    from fespp_on_trame.engine import categorical_palette
    try:
        n_ann = len(categorical_palette.annotations_of(lut))
        n = n_ann if categorical_palette.is_indexed(lut) else 0
        # past what a legend can name (a file's own colours on thousands of
        # codes, categorical_palette.tame): the swatches, no labels — laying
        # out thousands of them held the render for minutes (27/10). Counted
        # whatever the mode: a ramp's bar draws its annotations too.
        sb.DrawAnnotations = 0 if n_ann > categorical_palette.MAX_CATEGORIES else 1
        if n > categorical_palette.MAX_CATEGORIES:
            sb.ScalarBarLength = 0.33
            sb.LabelFontSize = 16
        elif n > 12:
            sb.ScalarBarLength = min(0.85, 0.03 * n + 0.2)
            sb.LabelFontSize = 10 if n > 24 else 12
        else:
            sb.ScalarBarLength = 0.33
            sb.LabelFontSize = 16
    except Exception as exc:
        print("[fespp] scalar bar size:", exc, flush=True)
