"""Multi-view-aware TimeControl widget.

Subclasses ptc.TimeControl so that callers think of "the time control",
but rebuilds its UI in __init__ so that every state binding can be
namespaced — multiple instances coexist without sharing time_index,
time_play, speed_scale or time_nb.

Two scopes:
  - scope="global" → writes pvsimple.GetTimeKeeper().Time. Every view
    that is linked to the keeper (i.e. every view by default) follows
    along. Used by the top tools band.
  - scope="view"   → writes target_view.ViewTime + Render(view=target_view)
    on one specific PV view, without touching the TimeKeeper. The
    target view diverges from the global time until either the global
    TC writes again or the user clicks the resync button on the
    global TC. Used inside each multi-view panel.

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
    """Build the state-var suffix from a namespace label.

    namespace="" → no suffix, state vars are time_index / time_play /
    time_nb / time_value / speed_scale (ptc defaults — back-compat with
    any code that reads them directly).

    namespace="panel_2" → suffix "_panel_2", state vars are time_index_panel_2
    etc. Used by the per-view TCs so they don't collide with each other
    nor with the global one.
    """
    return f"_{namespace}" if namespace else ""


class FesppTimeControl(ptc.TimeControl):
    # Registry of every live FesppTimeControl instance. Used by the
    # global TC to push its new index into every per-view sibling so the
    # per-view sliders reflect the post-sync state (their underlying
    # view.ViewTime was already updated by TimeKeeper's property link —
    # this just keeps the slider state coherent with what's on screen).
    # Entries are not actively cleaned up on panel close; iterating
    # over a stale instance only writes to a no-longer-rendered state
    # var, which is harmless.
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

        # Per-instance state-var names. ptc's defaults (no suffix) are
        # preserved only for the namespace="" global instance, so any
        # legacy reader (e.g. changeTimeLabel in fespp_engine) keeps
        # working.
        self._sv_index = f"time_index{sfx}"
        self._sv_nb = f"time_nb{sfx}"
        self._sv_value = f"time_value{sfx}"
        self._sv_play = f"time_play{sfx}"
        self._sv_speed = f"speed_scale{sfx}"
        # Adapt the default time_expression to the namespaced vars so a
        # caller that doesn't pass time_expression still gets a coherent
        # readout per instance. The parens around (idx + 1) are
        # important: without them JS evaluates left-to-right and the
        # leading 'time_value.toFixed(4) + " - "' coerces the rest to
        # string, so 'idx + 1' becomes string concat (e.g. "5" + 1 →
        # "51" instead of 6). ptc.TimeControl's default has this same
        # bug — we fix it locally without touching ptc.
        if time_expression == "time_value.toFixed(4)  + ' - ' + time_index + 1 + ' / ' + time_nb":
            time_expression = (
                f"{self._sv_value}.toFixed(4) + ' - ' + ({self._sv_index} + 1) + ' / ' + {self._sv_nb}"
            )

        # Skip ptc.TimeControl.__init__ entirely — it builds the UI with
        # hardcoded state names. Call the grandparent (VCard) directly.
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

        # A newly-created per-view TC inherits the global current time
        # — the target view's ViewTime is already at tk.Time via the
        # property link, so we just align the slider state so the
        # widget doesn't lie about its position. setdefault above won't
        # overwrite a pre-existing value (e.g. after panel close/reopen
        # of the same id), so this initial alignment is best-effort.
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
            # TimeKeeper.Time (set by per-view writes, cleared by
            # global writes or by clicking resync here).
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

        # Bind change handlers to the namespaced state — TrameApp's
        # decorator-based wiring on ptc.TimeControl is tied to the
        # default state names, so we register our own here.
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
        """Override ptc.TimeControl.update — its @change('time_index')
        and @controller.add('on_data_loaded') decorators would otherwise
        re-fire on every FesppTimeControl instance (including per-view
        ones whose namespaced state is unrelated to 'time_index'),
        writing TimeKeeper.Time from the wrong scope. We register our
        own per-instance handlers against the namespaced state in
        __init__ instead."""
        pass

    def _on_index_change(self, **_):
        """Apply the new index: write the appropriate time target and
        update the readout. The actual destination (TimeKeeper vs single
        view.ViewTime) is what makes the two scopes differ."""
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
            # on_data_change keeps the rest of the app (color bars,
            # labels, etc.) in sync with the active time.
            self.server.controller.on_data_change()

    def _write_time(self, t: float):
        """Push `t` to the right target depending on scope.

        global: TimeKeeper.Time → every linked view's ViewTime updates
                via property link, then broadcast a fresh client-side
                frame to ALL panels (not just the active one — without
                this the non-active views keep showing the previous
                timestep until the user clicks on them). After the
                broadcast, also mirror the new index into every per-view
                TC's state so its slider reflects the resynced position.
        view:   target view only. Skip if the view is already at this
                time (case where a global write just propagated through
                TimeKeeper → here we'd just be re-rendering the same
                frame). Otherwise set ViewTime, render server-side, then
                push the fresh image to THAT view's vtk.js client (not
                the active one — view_update would target the wrong
                view here)."""
        if self._scope == "global":
            tk = pvsimple.GetTimeKeeper()
            tk.Time = t
            # Broadcast image push to every panel. Falls back to
            # view_update (active-only) if the multi-view doesn't expose
            # the all-views variant — should not happen post-wiring but
            # keeps the TC usable in isolation.
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
            # A global write resyncs everything by definition — clear
            # the mixed flag. _sync_peer_indices above pushed the new
            # index into per-view sliders too, and their short-circuit
            # in _write_time keeps them from re-flipping the flag.
            self.server.state.ptc_global_mixed = False
            return
        view = self._target_pv_view
        if view is None:
            return
        # Skip the write if the view is already at this time — happens
        # right after a global write where TimeKeeper.Time propagated to
        # this view, and the per-view slider sync below this code path
        # triggered _on_index_change with the same value the view
        # already has.
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
            print(f"[FesppTimeControl] failed to set ViewTime on {view}: {e}")
            return
        # Push the freshly-rendered frame to this view's vtk.js client.
        # Without it, the divergent time stays server-side and the
        # browser keeps showing the previous frame.
        if self._target_html_view is not None:
            try:
                self._target_html_view.update()
            except Exception:
                pass
        # This view just diverged from TimeKeeper.Time — surface that
        # so the global TC shows its mixed badge / resync button.
        # Recompute by inspecting peers instead of trusting a sticky
        # flag: lets us turn the flag back off when a per-view scrub
        # happens to land back on the global time.
        self.server.state.ptc_global_mixed = self._compute_mixed()

    def _compute_mixed(self) -> bool:
        """True iff at least one per-view TC's target view sits at a
        different ViewTime than the global TimeKeeper. Used to drive
        the mixed badge — recomputed after every per-view write so it
        can flip back to false when the user happens to scrub back to
        the global time."""
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
        """Re-broadcast the global TC's current index to every view.
        Bound to the mixed-badge button — gives the user a one-click
        way to undo per-view divergence and bring every panel back to
        the global timestep."""
        if self._scope != "global":
            return
        self.refresh_from_keeper(apply=True)

    def _sync_peer_indices(self, index: int):
        """Push `index` into every per-view TC's slider state so each
        per-view slider reflects the global resync. The peer's
        _on_index_change will fire as a side effect — but its
        _write_time short-circuits when the target view's ViewTime is
        already at the new time (which is the case here, since the
        TimeKeeper.Time write above already propagated)."""
        for inst in FesppTimeControl._instances:
            if inst is self or inst._scope != "view":
                continue
            try:
                setattr(inst.state, inst._sv_index, index)
            except Exception:
                pass

    # Navigation helpers — same semantics as ptc.TimeControl but talk
    # to our namespaced state.
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
