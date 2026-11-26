"""What a 3D view owns besides its scene (overhaul slice 7).

Two things outlive a view's scene — the Globe flip rebuilds the scene and
keeps them — and are not the scene's business:

* its colour tables and opacity functions (`engine/luts.ViewLuts`), one per
  property, so a colour edit in one view does not bleed into another;
* its CLONE: a per-view `EPCCollectorClone` proxy, a shallow-copy
  passthrough of what the displays chain on (`derived_arrays.
  display_source_of`), hidden everywhere — the anchor the view's grid
  isolates (slicers, thresholds, Hide NaN) chain their extractor on.

Each also holds the view's ParaView render view (`pv_view`), so a caller
holding a panel id finds it (`pv_view_of`).

They used to live in the legacy per-representation `ViewScene`, which was
built for every view only to carry them. `ViewResourcesRegistry` makes them
when a render view is created and releases them when it closes; the legacy
`ViewScene` uses the same ones when the BlockScope flag is off.
"""
from fespp_on_trame.engine.luts import ViewLuts


class ViewResources:
    """One render view's colour tables and clone."""

    def __init__(self, view_id, source, pv_view=None):
        """`source`: the ActiveSource facade (EPC or ETP) the clone passes
        through; `pv_view`: the view's ParaView render view."""
        self.view_id = str(view_id)
        self._source = source
        self.pv_view = pv_view
        self.luts = ViewLuts(self.view_id)
        self._clone = self._create_clone() if source is not None else None

    # ------------------------------------------------------------------
    # The clone

    def _create_clone(self):
        """The per-view `EPCCollectorClone`, hidden in every view (PV's lazy
        display would paint a phantom outline). Built through
        `_create_plugin_filter_proxy` so it resolves even when the pvsimple
        namespace was not refreshed by `LoadPlugin`. The source itself when
        the clone cannot be built: an opaque handle either way."""
        try:
            from paraview import simple as pvsimple
            from fespp_on_trame.engine.sources.representation import (
                _create_plugin_filter_proxy,
            )
            from fespp_on_trame.engine.derived_arrays import display_source_of
            # the isolates chain on the clone: it passes through what the
            # displays chain on (the derived-arrays filter), so a computed
            # property is an array of the isolated grid too
            clone = _create_plugin_filter_proxy(
                proxy_class="EPCCollectorClone",
                registration_name=f"EPCCollector_View{self.view_id}",
                inputs={"Input": display_source_of(self._source)},
            )
            if clone is None:
                return self._source.get_source()
            try:
                for view in pvsimple.GetViews():
                    disp = pvsimple.GetDisplayProperties(clone, view=view)
                    if disp is not None:
                        disp.Visibility = 0
            except Exception as exc:
                print(f"[fespp] view clone ({self.view_id}): not hidden ({exc})", flush=True)
            return clone
        except Exception as exc:
            print(f"[fespp] view clone ({self.view_id}): the source stands in ({exc})", flush=True)
            return self._source.get_source()

    def rebind_clone_input(self, new_src):
        """Point the clone at the CURRENT display source: a view created
        before an ETP connection is chained on the (then empty) EPC
        collector, and every isolate built on it would extract nothing.
        Called whenever the active source flips."""
        if new_src is None or self._clone is None or self._clone is new_src:
            return
        try:
            if hasattr(self._clone, "Input"):
                self._clone.Input = new_src
                self._clone.UpdatePipelineInformation()
                return
        except Exception as exc:
            print(f"[fespp] view clone ({self.view_id}): not rebound ({exc})", flush=True)
        # the fallback handle (the source itself): the new READER — never
        # the derived filter, `release` tells it from a clone by that
        self._clone = (self._source.get_source()
                       if self._source is not None else new_src)

    @property
    def clone(self):
        return self._clone

    # ------------------------------------------------------------------
    # The colour tables (engine/luts)

    def get_or_create_lut(self, base_array_name):
        return self.luts.lut(base_array_name)

    def get_or_create_pwf(self, base_array_name):
        return self.luts.pwf(base_array_name)

    # ------------------------------------------------------------------

    def release(self):
        """The view closes: its tables and its clone go (never the source
        itself, the clone's stand-in). Idempotent."""
        self.luts.release()
        if (self._clone is not None and self._source is not None
                and self._clone is not self._source.get_source()):
            try:
                from paraview import simple as pvsimple
                pvsimple.Delete(self._clone)
            except Exception as exc:
                print(f"[fespp] view clone ({self.view_id}): not deleted ({exc})", flush=True)
        self._clone = None
        self.pv_view = None

    def __repr__(self):
        return f"<ViewResources view_id={self.view_id!r}>"


class ViewResourcesRegistry:
    """The `ViewResources` of every open render view."""

    def __init__(self, source):
        self._source = source
        self._views = {}

    def add_view(self, view_id, pv_view=None):
        """Make the view's resources, or return the existing ones (told
        its render view when they did not know it)."""
        view_id = str(view_id)
        res = self._views.get(view_id)
        if res is None:
            res = self._views[view_id] = ViewResources(view_id, self._source, pv_view)
        elif pv_view is not None:
            res.pv_view = pv_view
        return res

    def remove_view(self, view_id):
        res = self._views.pop(str(view_id), None)
        if res is not None:
            res.release()

    def get(self, view_id):
        return self._views.get(str(view_id)) if view_id is not None else None

    def view_ids(self):
        return list(self._views)

    def rebind_clone_inputs(self):
        """Re-point every view's clone at the CURRENT display source (the
        active source may have flipped since the views were made)."""
        try:
            from fespp_on_trame.engine.derived_arrays import display_source_of
            src = display_source_of(self._source)
        except Exception as exc:
            print(f"[fespp] view clones: no display source ({exc})", flush=True)
            return
        for res in self._views.values():
            res.rebind_clone_input(src)


def current():
    """The running server's registry, or None before boot made it."""
    from trame.app import get_server
    return getattr(get_server().context, "view_resources", None)


def pv_view_of(view_id):
    """The render view of the panel `view_id`, or None when unknown."""
    reg = current()
    res = reg.get(view_id) if reg is not None else None
    return res.pv_view if res is not None else None
