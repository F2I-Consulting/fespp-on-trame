"""Multi-view-aware TimeControl widget.

Subclasses ptc.TimeControl but rebuilds its UI in __init__ so every
state binding can be namespaced — multiple instances coexist without
sharing time_index, time_play, speed_scale or time_nb.

Two scopes:
  - scope="global" → writes pvsimple.GetTimeKeeper().Time. Every view
    linked to the keeper (i.e. every view by default) follows along.
    Used by the top tools band.
  - scope="view"   → writes target_view.ViewTime + Render(view=target_view)
    on one specific PV view, without touching the TimeKeeper. That
    view diverges from the global time until the global TC writes
    again or the user clicks its resync button. Used inside each
    multi-view panel.

Available timesteps come from GetTimeKeeper().TimestepValues in both
modes — fespp registers every TS source on the global keeper, so its
TimestepValues is the union of every view's time set.
"""
import asyncio

from paraview import simple as pvsimple
from trame.app import asynchronous
from trame.widgets import html, vuetify3

import ptc


def _suffix(namespace: str) -> str:
    """State-var suffix for a namespace label.

    namespace="" → no suffix; state vars are the ptc defaults
    (time_index / time_play / time_nb / time_value / speed_scale), so
    code reading them directly still works.

    namespace="panel_2" → "_panel_2"; state vars become
    time_index_panel_2 etc. Used by per-view TCs so they don't collide
    with each other or the global one.
    """
    return f"_{namespace}" if namespace else ""


class FesppTimeControl(ptc.TimeControl):
    # Registry of every live FesppTimeControl instance. The global TC
    # pushes its new index into every per-view sibling so their
    # sliders reflect the post-sync state (the underlying view.ViewTime
    # is already updated via TimeKeeper's property link). Stale entries
    # after a panel close are harmless — a write just lands on a
    # no-longer-rendered state var.
    _instances: "list[FesppTimeControl]" = []

    def __init__(
        self,
        namespace: str = "",
        scope: str = "global",
        target_pv_view=None,
        target_html_view=None,
        time_expression: str = "time_value.toFixed(4)  + ' - ' + time_index + 1 + ' / ' + time_nb",
        show_var: str = "ptc_show_vcr",
        **kwargs,
    ):
        if scope not in ("global", "view"):
            raise ValueError(f"scope must be 'global' or 'view', got {scope!r}")
        if scope == "view" and target_pv_view is None:
            raise ValueError("scope='view' requires target_pv_view to be set")

        self._scope = scope
        self._target_pv_view = target_pv_view
        self._target_html_view = target_html_view
        self._namespace = namespace
        sfx = _suffix(namespace)

        # Per-instance state-var names. The ptc defaults (no suffix)
        # are kept for the namespace="" global instance so code that
        # reads them directly (e.g. changeTimeLabel) keeps working.
        self._sv_index = f"time_index{sfx}"
        self._sv_nb = f"time_nb{sfx}"
        self._sv_value = f"time_value{sfx}"
        self._sv_play = f"time_play{sfx}"
        self._sv_speed = f"speed_scale{sfx}"
        # Adapt the default time_expression to the namespaced vars so a
        # caller that omits time_expression still gets a coherent
        # per-instance readout. The parens around (idx + 1) are
        # required: without them JS evaluates left-to-right and the
        # leading 'time_value.toFixed(4) + " - "' coerces the rest to
        # string, so 'idx + 1' becomes string concat (e.g. "5" + 1 →
        # "51" instead of 6).
        if time_expression == "time_value.toFixed(4)  + ' - ' + time_index + 1 + ' / ' + time_nb":
            time_expression = (
                f"{self._sv_value}.toFixed(4) + ' - ' + ({self._sv_index} + 1) + ' / ' + {self._sv_nb}"
            )

        # Skip ptc.TimeControl.__init__ (it builds the UI with
        # hardcoded state names) and call the grandparent (VCard).
        vuetify3.VCard.__init__(
            self,
            v_show=f"({show_var}) && {self._sv_nb} > 0",
            **{
                **kwargs,
                "classes": kwargs.get("classes", "pa-1 px-2 elevation-5 rounded-lg"),
                "style": "width: 100%; overflow: hidden; background: rgba(255, 255, 255, 0.5);"
                + kwargs.get("style", ""),
            },
        )

        self.state.setdefault(self._sv_index, 0)
        self.state.setdefault(self._sv_nb, 0)
        self.state.setdefault(self._sv_value, 0)
        self.state.setdefault(self._sv_speed, 1)
        self.state.setdefault(self._sv_play, False)
        # Cross-instance flag — set by per-view writes, cleared by
        # global writes / explicit resync. Drives the "mixed" badge on
        # the global TC.
        self.state.setdefault("ptc_global_mixed", False)

        # A new per-view TC inherits the global current time: the
        # target view's ViewTime is already at tk.Time via the property
        # link, so we just align the slider so the widget doesn't
        # misreport its position. Best-effort — setdefault above won't
        # overwrite a value left from a same-id close/reopen.
        if scope == "view":
            global_idx = int(getattr(self.server.state, "time_index", 0) or 0)
            if global_idx != getattr(self.state, self._sv_index, 0):
                setattr(self.state, self._sv_index, global_idx)

        with (
            self,
            html.Div(
                classes="d-flex align-center",
                style="pointer-events: auto; user-select: none;",
            ),
        ):
            vuetify3.VBtn(
                icon="mdi-skip-previous",
                density="compact",
                flat=True,
                click=self.first,
                classes="mr-1",
            )
            vuetify3.VBtn(
                icon="mdi-chevron-left",
                density="compact",
                flat=True,
                click=self.previous,
                classes="mr-1",
            )
            vuetify3.VBtn(
                icon="mdi-play",
                density="compact",
                flat=True,
                classes="mr-1",
                click=self.play,
                v_show=f"!{self._sv_play}",
            )
            vuetify3.VBtn(
                icon="mdi-stop",
                density="compact",
                flat=True,
                classes="mr-1",
                click=self.stop,
                v_show=(self._sv_play, False),
            )
            vuetify3.VBtn(
                icon="mdi-chevron-right",
                density="compact",
                flat=True,
                click=self.next,
                classes="mr-1",
            )
            vuetify3.VBtn(
                icon="mdi-skip-next",
                density="compact",
                flat=True,
                click=self.last,
                classes="mr-1",
            )

            with vuetify3.VMenu(location="bottom"):
                with vuetify3.Template(v_slot_activator="{ props }"):
                    vuetify3.VBtn(
                        icon="mdi-speedometer-medium",
                        v_bind="props",
                        flat=True,
                        density="compact",
                        classes="mx-2",
                    )
                with vuetify3.VBtnToggle(
                    v_model=(self._sv_speed,), mandatory=True, direction="vertical"
                ):
                    vuetify3.VBtn(
                        "{{value}}",
                        value=("value",),
                        v_for="value in [0.25, 0.5, 1.0, 2.0, 5.0]",
                    )

            html.Div(
                f"{{{{ {time_expression} }}}}",
                classes="text-caption text-center",
                style="width: 10rem;",
            )

            vuetify3.VSlider(
                v_model=(self._sv_index, 0),
                min=0,
                max=(f"{self._sv_nb} - 1",),
                step=1,
                density="compact",
                hide_details=True,
            )

            # Mixed indicator + resync button — only on the global TC.
            # Visible when at least one view's ViewTime diverges from
            # TimeKeeper.Time.
            if scope == "global":
                with vuetify3.VTooltip(location="bottom"):
                    with vuetify3.Template(v_slot_activator="{ props }"):
                        vuetify3.VBtn(
                            icon="mdi-sync-alert",
                            v_bind="props",
                            v_show=("ptc_global_mixed", False),
                            density="compact",
                            flat=True,
                            color="orange-darken-2",
                            classes="ml-2",
                            click=self.resync_all,
                        )
                    html.Span(
                        "Views diverge — click to resync every view to the global time"
                    )

        # Bind change handlers to the namespaced state ourselves —
        # ptc.TimeControl's decorator wiring is tied to the default
        # state names.
        self.server.state.change(self._sv_index)(self._on_index_change)
        # Refresh on data load so newly-loaded TS sources expand the
        # slider range.
        self.server.controller.on_data_loaded.add(self.refresh_from_keeper)

        FesppTimeControl._instances.append(self)

        self.refresh_from_keeper()

    @property
    def time_values(self):
        return list(pvsimple.GetTimeKeeper().TimestepValues)

    def update(self, **_):
        """No-op override of ptc.TimeControl.update. Its decorators
        bind to the default 'time_index' / 'on_data_loaded', which
        would re-fire on every instance (including per-view ones) and
        write TimeKeeper.Time from the wrong scope. Per-instance
        handlers are registered against the namespaced state in
        __init__ instead."""
        pass

    def _on_index_change(self, **_):
        """Apply the new index: write the scope's time target
        (TimeKeeper vs single view.ViewTime) and update the readout."""
        self.refresh_from_keeper(apply=True)

    def refresh_from_keeper(self, apply: bool = False, **_):
        """Pull TimestepValues from the global TimeKeeper, refresh
        time_nb/time_value, clamp time_index, and (if apply=True) push
        the new time into the scope's target."""
        time_values = self.time_values
        st = self.state
        setattr(st, self._sv_nb, len(time_values))
        idx = int(getattr(st, self._sv_index, 0) or 0)
        if idx >= len(time_values):
            idx = 0
        if idx < 0:
            idx = len(time_values) + idx
        setattr(st, self._sv_index, idx)

        if not time_values:
            setattr(st, self._sv_value, 0)
            return
        t = time_values[idx]
        setattr(st, self._sv_value, t)

        if apply:
            self._write_time(t)
            # Keep the rest of the app (colour bars, labels, …) in
            # sync with the active time.
            self.server.controller.on_data_change()

    def _write_time(self, t: float):
        """Push `t` to the right target depending on scope.

        global: TimeKeeper.Time → every linked view's ViewTime updates
                via property link. Broadcast a fresh frame to ALL
                panels (not just the active one, else non-active views
                keep showing the previous timestep), then mirror the
                new index into every per-view TC's slider state.
        view:   target view only. Skip if the view is already at this
                time (a global write may have just propagated here).
                Otherwise set ViewTime, render, and push the fresh
                image to THAT view's vtk.js client (view_update would
                target the wrong view)."""
        if self._scope == "global":
            tk = pvsimple.GetTimeKeeper()
            tk.Time = t
            # Broadcast the image push to every panel; fall back to
            # view_update (active-only) when the multi-view doesn't
            # expose the all-views variant, so the TC still works in
            # isolation.
            ctrl = self.server.controller
            update_all = getattr(ctrl, "view_update_all", None)
            if update_all is not None:
                try:
                    update_all()
                except Exception:
                    pass
            else:
                try:
                    ctrl.view_update()
                except Exception:
                    pass
            self._sync_peer_indices(int(getattr(self.state, self._sv_index, 0) or 0))
            # A global write resyncs everything, so clear the mixed
            # flag. The per-view sliders just synced; their short-
            # circuit below keeps them from re-flipping it.
            self.server.state.ptc_global_mixed = False
            return
        view = self._target_pv_view
        if view is None:
            return
        # Skip if the view is already at this time — happens right
        # after a global write whose TimeKeeper.Time propagated here
        # and triggered _on_index_change with the value the view
        # already holds.
        try:
            current = float(view.ViewTime)
            if abs(current - t) < 1e-12:
                return
        except Exception:
            pass
        try:
            view.ViewTime = t
            view.SMProxy.UpdateVTKObjects()
            pvsimple.Render(view=view)
        except Exception as e:
            return
        # Push the freshly-rendered frame to this view's vtk.js client,
        # else the divergent time stays server-side and the browser
        # keeps showing the previous frame.
        if self._target_html_view is not None:
            try:
                self._target_html_view.update()
            except Exception:
                pass
        # This view may now diverge from TimeKeeper.Time — recompute
        # the mixed flag from peers (rather than setting it sticky-true)
        # so it can flip back off when a scrub lands on the global time.
        self.server.state.ptc_global_mixed = self._compute_mixed()

    def _compute_mixed(self) -> bool:
        """True iff at least one per-view TC's target view sits at a
        different ViewTime than the global TimeKeeper. Drives the
        mixed badge."""
        try:
            tk_t = float(pvsimple.GetTimeKeeper().Time)
        except Exception:
            return False
        for inst in FesppTimeControl._instances:
            if inst._scope != "view":
                continue
            view = inst._target_pv_view
            if view is None:
                continue
            try:
                if abs(float(view.ViewTime) - tk_t) > 1e-9:
                    return True
            except Exception:
                pass
        return False

    def resync_all(self):
        """Re-broadcast the global TC's current index to every view,
        undoing per-view divergence. Bound to the mixed-badge
        button."""
        if self._scope != "global":
            return
        self.refresh_from_keeper(apply=True)

    def _sync_peer_indices(self, index: int):
        """Push `index` into every per-view TC's slider state so each
        reflects the global resync. The peer's _on_index_change fires
        as a side effect, but its _write_time short-circuits since the
        target view's ViewTime already matches (the TimeKeeper.Time
        write above propagated)."""
        for inst in FesppTimeControl._instances:
            if inst is self or inst._scope != "view":
                continue
            try:
                setattr(inst.state, inst._sv_index, index)
            except Exception:
                pass

    # Navigation helpers — ptc.TimeControl semantics against the
    # namespaced state.
    def first(self):
        setattr(self.state, self._sv_index, 0)

    def last(self):
        setattr(self.state, self._sv_index, max(0, len(self.time_values) - 1))

    def previous(self):
        setattr(self.state, self._sv_index, int(getattr(self.state, self._sv_index, 0) or 0) - 1)

    def next(self):
        setattr(self.state, self._sv_index, int(getattr(self.state, self._sv_index, 0) or 0) + 1)

    def play(self):
        if not getattr(self.state, self._sv_play, False):
            setattr(self.state, self._sv_play, True)
            asynchronous.create_task(self._play_animation())

    def stop(self):
        setattr(self.state, self._sv_play, False)

    async def _play_animation(self):
        with self.state:
            while getattr(self.state, self._sv_play, False):
                with self.state:
                    self.next()
                await asyncio.sleep(0.1 / float(getattr(self.state, self._sv_speed, 1.0) or 1.0))
