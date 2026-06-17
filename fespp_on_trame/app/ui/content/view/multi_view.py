from typing import Literal

from paraview import simple as pvsimple
from trame.ui.html import DivLayout
from trame.widgets import paraview, vuetify3 as vuetify3, html

import ptc

from ..widget.time_control import FesppTimeControl
from ..widget.realization_picker import PerViewRealizationPicker
from ..widget.view_link_menu import ViewLinkMenu
from ..widget.per_view_camera_toolbar import PerViewCameraToolbar


ViewKind = Literal["render", "diff", "stats", "distribution", "stats_compare"]


class FesppMultiView(ptc.MultiView):
    """MultiView wired for FESPP:

    - The first add_view() adopts the pre-existing active RenderView
      (created at engine import) instead of spawning a new one,
      so the engine's captured `_view` stays the panel-1 view.
    - Tracks the trame VtkRemoteView widget per panel and the active
      panel id, so controller.view_update / view_reset_camera /
      view_replace can target the currently active panel.
    - Camera sync between views fires on the EndAnimation interactor
      event (mouse release), copying camera params manually instead of
      relying on AddCameraLink (which forces a per-frame re-render of
      every linked view and is unusable interactively).
    - Knows about a dedicated "diff" panel kind: starts empty, shows an
      inline A/B setup form on top of its viewport, and exposes its own
      palette / edit-inputs chrome.
    """

    def __init__(self, namespace_prefix: str = "time_view", **kwargs):
        self._html_views: dict = {}
        self._panel_titles: dict = {}
        self._panel_kinds: dict = {}
        self._active_panel_id = None
        self._namespace_prefix = namespace_prefix
        self._first_view_adopted = False
        self._diff_panel_id = None
        # Singleton dockview tab for the descriptive-statistics panel.
        # Tracked so callers can detect whether the view already exists
        # before creating another one.
        self._stats_panel_id = None
        super().__init__(**kwargs)
        # Public state — tree views iterate this to render one eye per
        # render panel on each rep / data-array node. Diff panels are
        # excluded because their content is driven by the diff dialog,
        # not by per-source eye toggles.
        self.server.state.setdefault("fespp_render_panels", [])
        # Active panel exposed to Vue so the contextual band (active
        # panel toolbar above the dockview) can react. id is used to
        # target per-panel actions, title is shown to the user as a
        # "Settings for: <title>" indicator.
        self.server.state.setdefault("fespp_active_panel_id", "")
        self.server.state.setdefault("fespp_active_panel_title", "")
        # Per-view camera-broadcast group. Read by PerViewCameraToolbar
        # to know which other panels to fan out reset/orient/2D-3D
        # actions to. Mutated symmetrically by ViewLinkMenu.
        self.server.state.setdefault("view_links", {})

    def _publish_panels_state(self):
        """Refresh fespp_render_panels (render-only, drives the tree's
        eye chip row) and fespp_settings_scopes (Global + every panel
        including diff, drives the Scope select in
        GlobalSettingsDialog). Called on add/close so both stay in
        sync with what's actually on screen.

        Empty render panels are still listed here on purpose: their
        chips appear closed (the rep is in the panel's hidden bucket),
        and the user can click them to incrementally populate the
        empty scene from the tree."""
        render = []
        scopes = [{"value": "global", "title": "Global (all views)"}]
        for pid, title in self._panel_titles.items():
            kind = self._panel_kinds.get(pid)
            if kind == "render":
                render.append({"id": pid, "title": title})
                scopes.append({"value": pid, "title": title})
            elif kind == "diff":
                scopes.append({"value": pid, "title": title})
        self.server.state.fespp_render_panels = render
        self.server.state.fespp_settings_scopes = scopes
        # Keep the active panel title in sync after a rename — the
        # title comes from _panel_titles which the rename hook in
        # ViewSettingsDialog mutates before calling this method.
        if self._active_panel_id:
            self.server.state.fespp_active_panel_title = self._panel_titles.get(
                self._active_panel_id, ""
            )

    def _seed_per_view_hidden_state(self, panel_id, ref_panel_id, kind="render", replicate=True):
        """Initialise the per-view buckets for a new panel.

        Hidden bucket:
          - First view (no ref): seed from the legacy
            ui_hidden_rep_paths (user's prior hidden set carries over).
          - Empty render panel (replicate=False): seed with **every
            currently-loaded rep** so the tree shows a closed-eye
            chip per rep on this panel. The user can then click each
            closed chip to incrementally populate the empty scene
            (toggle_rep_visibility removes the rep from this bucket
            and calls Show() on this panel's view).
          - Subsequent view with a ref AND replicate=True: copy the
            ref panel's bucket so replicate's visual Show/Hide matches
            the state.
          - Diff: empty.

        Active-array bucket:
          - First view: copy from legacy ui_active_array_by_rep so the
            user keeps their current coloring on the panel they're
            already used to.
          - Subsequent view replicated from a ref: copy the ref's
            bucket so the new scene shows the *same* coloring on each
            rep (matching what the user sees in the source view).
            The user can then diverge per-panel from there.
          - Empty render panel (replicate=False): empty — nothing
            visible, nothing coloured.
          - Diff: empty.

        Active-realization bucket (per (panel, array_path) → idx):
          - Same shape as the active-array bucket. Must mirror it on
            replicate: every MR array is suffixed `_real_<idx>`, so a
            carried-over MR property without its idx would resolve to a
            non-existent unsuffixed name and fall back to SolidColor.
            Empty for the non-replicate cases."""
        st = self.server.state
        hidden_by_view = dict(st.ui_hidden_rep_paths_by_view or {})
        active_by_view = dict(st.ui_active_array_by_rep_by_view or {})
        real_by_view = dict(st.ui_active_realization_by_array_by_view or {})
        # Per-view VISIBLE markers (multi-select). Same copy semantics as
        # the active-array bucket: a replicated view inherits the ref's
        # shown markers; empty/diff/first views start with none.
        marker_by_view = dict(st.ui_visible_marker_paths_by_view or {})
        if kind == "diff":
            hidden_by_view[panel_id] = []
            active_by_view[panel_id] = {}
            real_by_view[panel_id] = {}
            marker_by_view[panel_id] = []
        elif kind == "render" and not replicate:
            # Empty panel — every loaded rep starts in the hidden
            # bucket so all chips appear closed in the tree.
            hidden_by_view[panel_id] = list(st.ui_loaded_rep_paths or [])
            active_by_view[panel_id] = {}
            real_by_view[panel_id] = {}
            marker_by_view[panel_id] = []
        elif ref_panel_id and ref_panel_id in hidden_by_view:
            hidden_by_view[panel_id] = list(hidden_by_view.get(ref_panel_id, []) or [])
            active_by_view[panel_id] = dict(active_by_view.get(ref_panel_id, {}) or {})
            real_by_view[panel_id] = dict(real_by_view.get(ref_panel_id, {}) or {})
            marker_by_view[panel_id] = list(marker_by_view.get(ref_panel_id, []) or [])
        else:
            hidden_by_view[panel_id] = list(st.ui_hidden_rep_paths or [])
            active_by_view[panel_id] = dict(st.ui_active_array_by_rep or {})
            # First view has no ref-bucket to copy from; mirror the
            # existing active_realization map if present, else empty.
            real_by_view[panel_id] = dict(real_by_view.get(panel_id, {}) or {})
            marker_by_view[panel_id] = list(marker_by_view.get(panel_id, []) or [])
        st.ui_hidden_rep_paths_by_view = hidden_by_view
        st.ui_active_array_by_rep_by_view = active_by_view
        st.ui_active_realization_by_array_by_view = real_by_view
        st.ui_visible_marker_paths_by_view = marker_by_view

    def add_view(
        self,
        kind: ViewKind = "render",
        replicate: bool | None = None,
        title: str | None = None,
        direction: str = "within",
        reference_panel_id: str | None = None,
    ):
        """direction: where to place the new panel relative to its
        reference panel in the dockview layout. "within" (default) →
        new tab in the reference panel's group. "right"/"below"/
        "left"/"above" → new group on that side. reference_panel_id
        defaults to the current active panel."""
        self._view_count += 1
        panel_id = f"ptc_view_{self._view_count}"
        template_name = f"ptc_view_{self._view_count}_template"
        if title is None:
            if kind == "diff":
                panel_title = "Diff"
            elif kind == "stats":
                panel_title = "Stats"
            elif kind == "distribution":
                panel_title = "Distribution"
            elif kind == "stats_compare":
                panel_title = "Compare stats"
            else:
                panel_title = f"View {self._view_count}"
        else:
            panel_title = title

        # Stats: HTML-only view (no PV view, no scene, no replicate).
        # Renders the multi-property descriptive stats panel with the
        # full width of the dockview tile. Singleton — only one stats
        # tab at a time. Branches early to avoid the render / diff
        # setup below.
        if kind == "stats":
            return self._add_stats_panel(panel_id, template_name, panel_title)
        if kind == "distribution":
            return self._add_distribution_panel(panel_id, template_name, panel_title)
        if kind == "stats_compare":
            return self._add_stats_compare_panel(panel_id, template_name, panel_title)

        if not self._first_view_adopted:
            pv_view = pvsimple.GetActiveViewOrCreate("RenderView")
            self._first_view_adopted = True
            ref_view = None
            ref_panel_id = None
        else:
            # Reference panel: prefer the caller-provided one (per-
            # panel buttons pass the panel they were rendered into),
            # fall back to active, fall back to first known panel.
            ref_panel_id = (
                reference_panel_id
                or self._active_panel_id
                or next(iter(self._pv_internal), None)
            )
            ref_view = self._pv_internal.get(ref_panel_id) if ref_panel_id else None
            if ref_view is None:
                ref_view = next(iter(self._pv_internal.values()), None)
            pv_view = pvsimple.CreateRenderView()
        pv_view.MakeRenderWindowInteractor(True)
        self._pv_internal[panel_id] = pv_view

        # Per-view scene registry hook. The scene is created up front
        # so any per-(rep, view) work has its owner ready.
        scene_registry = getattr(self.server.context, "scene_registry", None)
        if scene_registry is not None:
            try:
                scene_registry.add_view(panel_id, pv_view)
                # Seed the fresh scene with whatever reps are already
                # loaded. Without this, the state.change handler on
                # `ui_loaded_rep_paths` only fires when the list
                # CHANGES — a split that happens after the data is
                # loaded would leave the new scene empty.
                scene_registry.sync_loaded_reps(
                    self.server.state.ui_loaded_rep_paths or [],
                )
            except Exception as exc:
                pass

        # Diff view starts empty; render views replicate by default.
        if replicate is None:
            replicate = kind == "render"
        if replicate and ref_view is not None:
            self._replicate_visibility(ref_view, pv_view)
            # `_replicate_visibility` mirrored display props and
            # `_seed_per_view_hidden_state` below mirrors the ref
            # panel's active-array bucket, so the new panel shows the
            # same coloring as the source; the user can then diverge
            # via the per-view eye chips in the tree.
            #
            # Also replicate the per-(rep, view) state — threshold
            # chain, slice plane, clip plane — so a split copies the
            # source panel's full scene state, not just its visibility.
            if scene_registry is not None and ref_panel_id:
                try:
                    scene_registry.replicate_view(ref_panel_id, panel_id)
                except Exception as exc:
                    pass
        elif kind == "render" and ref_view is not None:
            # Empty render view (replicate=False) — pre-hide every
            # existing source in this panel so subsequent lazy display
            # creations (e.g. ColorBy fan-out triggered by a global
            # state.change) don't paint phantom outlines (PV's default
            # display proxy is Visibility=1, Representation='Outline').
            self._force_hide_all_sources(pv_view)
        # Seed the new panel's per-view hidden set so the tree's eye
        # row starts in a coherent state for this panel. `replicate`
        # disambiguates the empty-render case from the replicate-from-
        # ref case (both have a ref_panel_id otherwise).
        self._seed_per_view_hidden_state(
            panel_id, ref_panel_id, kind=kind, replicate=replicate,
        )
        # Render the markers the new panel inherited from its ref (the
        # seed above only copied the STATE bucket; this creates+shows
        # each marker's per-marker extractor in the new scene).
        if scene_registry is not None:
            try:
                scene_registry.apply_visible_markers(panel_id)
            except Exception as exc:
                pass

        self._panel_titles[panel_id] = panel_title
        self._panel_kinds[panel_id] = kind

        if kind == "diff":
            self._diff_panel_id = panel_id
            self.server.state.fespp_diff_panel_id = panel_id

        namespace = (
            self._namespace_prefix
            if self._view_count == 1
            else f"{self._namespace_prefix}_{self._view_count}"
        )

        with DivLayout(self.server, template_name) as ui:
            ui.root.style = "position:relative;height:100%;width:100%;"
            html_view = paraview.VtkRemoteView(
                pv_view,
                interactive_ratio=0.5,
                interactive_quality=60,
                namespace=namespace,
                style="width: 100%; height: 100%;",
                interactor_events=("interactor_events_default", ["EndAnimation"]),
                EndAnimation=(self._sync_camera_from, f"['{panel_id}']"),
            )
            self._html_views[panel_id] = html_view

            # Active panel indicator — a 3px inset blue border around
            # the viewport, plus an "ACTIVE" pill in the top-right
            # (top-center is taken by the TimeControl; top-left by the
            # camera chrome). Reactive on `fespp_active_panel_id`.
            html.Div(
                v_show=(f"fespp_active_panel_id === '{panel_id}'",),
                style=(
                    "position:absolute; inset:0;"
                    " box-shadow: inset 0 0 0 3px #1976d2;"
                    " pointer-events: none;"
                    " z-index: 10;"
                ),
            )
            html.Div(
                "ACTIVE",
                v_show=(f"fespp_active_panel_id === '{panel_id}'",),
                style=(
                    "position:absolute; top: 4px; right: 4px;"
                    " padding: 2px 8px;"
                    " background: #1976d2; color: #fff;"
                    " font-size: 10px; font-weight: 700;"
                    " letter-spacing: 0.5px;"
                    " border-radius: 4px;"
                    " pointer-events: none;"
                    " z-index: 11;"
                ),
            )

            if kind == "diff":
                self._render_diff_chrome(panel_id)
            else:
                self._render_panel_time_control(panel_id, pv_view)
                self._render_panel_realization_picker(panel_id)
                # Camera chrome (magnet + reset/orient/2D-3D) on the
                # top-left of the 3D area. Render panels only — diff
                # panels have their own action buttons.
                self._render_panel_camera_chrome(panel_id)

            # Per-panel action chrome — only on render panels, the
            # diff panel has its own action buttons (palette/edit)
            # via _render_diff_chrome.
            if kind == "render":
                self._render_panel_actions(panel_id)

        # Position the panel relative to the reference (the caller's
        # explicit choice, else active) — dockview interprets
        # `position` to create either a new tab in the same group
        # ("within") or a split group on the side
        # ("right"/"below"/…).
        if direction and direction != "within":
            ref = reference_panel_id or self._active_panel_id or ref_panel_id
            if ref:
                self.add_panel(
                    panel_id,
                    panel_title,
                    template_name,
                    position={"direction": direction, "referencePanel": ref},
                )
            else:
                self.add_panel(panel_id, panel_title, template_name)
        else:
            self.add_panel(panel_id, panel_title, template_name)

        if self._active_panel_id is None:
            self._active_panel_id = panel_id
            pvsimple.SetActiveView(pv_view)
            # _on_view_activated won't fire for the very first panel
            # (it's invoked by dockview's active_panel event on tab
            # switches), so publish the active-panel state vars here
            # too — otherwise downstream consumers
            # (recompute_visibility_state, the contextual buttons,
            # etc.) see an empty fespp_active_panel_id until the user
            # clicks a tab.
            self.server.state.fespp_active_panel_id = panel_id
            self.server.state.fespp_active_panel_title = self._panel_titles.get(panel_id, "")

        # `_copy_display_props` deliberately doesn't copy
        # ColorArrayName / LookupTable (field-wise copy leaves PV6 in
        # a hybrid state where the display renders SolidColor + outline
        # because the scalar mapping isn't bound to the LUT). Apply the
        # full ColorBy via the engine path now — same code the eye
        # click goes through. Done AFTER the panel is wired so the
        # html_view exists when we push the post-Render frame.
        if replicate and kind == "render":
            try:
                self.server.controller.apply_panel_coloring(panel_id)
            except Exception:
                pass

            # Per-view LUT / PWF: ColorBy created this scene's scoped
            # LUTs seeded from the global singleton (PV's auto-default,
            # not the ref view's tweaks which live on the ref scene's
            # scoped LUTs). Mirror the ref's LUT / PWF values now so the
            # new view's first frame shows the same gradient.
            if ref_panel_id and scene_registry is not None:
                try:
                    ref_scene = scene_registry.get_scene(ref_panel_id)
                    new_scene = scene_registry.get_scene(panel_id)
                    if ref_scene is not None and new_scene is not None:
                        new_scene.replicate_tfs_from(ref_scene)
                except Exception as exc:
                    pass

            # ColorBy can lazily create displays for chain proxies in
            # the new view with default Visibility=1. Re-enforce
            # visibility from the ref view as a final pass, then
            # render the corrected frame.
            if ref_view is not None:
                try:
                    self._enforce_view_visibility_from_ref(ref_view, pv_view)
                except Exception:
                    pass
                try:
                    pvsimple.Render(view=pv_view)
                    html_view = self._html_views.get(panel_id)
                    if html_view is not None:
                        html_view.update()
                except Exception:
                    pass

        self._publish_panels_state()
        return panel_id

    def _add_stats_panel(self, panel_id, template_name, panel_title):
        """Build the singleton Stats dockview tab. HTML-only — no PV
        view, no scene, no replicate / hidden-state seeding. Body is
        the multi-property `DescriptiveStatsPanel` rendered with the
        full width of the tile (no drawer-width squeezing). Always
        docks at the bottom of the dockview root (full content
        width) — both entry-points (`controller.open_stats_panel`
        and `controller.toggle_stats_display`) want that placement.

        Tracks itself on `self._stats_panel_id` and publishes the
        same id on `state.fespp_stats_panel_id` so callers (the tree's
        chart icon, the toolbar button) can detect existence and
        focus the tab instead of creating a duplicate."""
        # Lazy import — avoids a circular import at module load time.
        from fespp_on_trame.app.ui.content.panel.descriptive_stats_panel import (
            DescriptiveStatsPanel,
        )
        self._panel_titles[panel_id] = panel_title
        self._panel_kinds[panel_id] = "stats"
        self._stats_panel_id = panel_id
        self.server.state.fespp_stats_panel_id = panel_id
        with DivLayout(self.server, template_name) as ui:
            # Outer container: position:relative so the
            # active-panel overlay (blue inset border + ACTIVE
            # pill) anchors against it.
            ui.root.style = (
                "position:relative; height:100%; width:100%;"
                " background-color: #fafafa;"
            )
            # --- Scrollable body ---------------------------------
            with html.Div(
                classes="fespp-stats-panel",
                style=(
                    "position:absolute; inset:0;"
                    " overflow-y: auto; overflow-x: auto;"
                    " padding: 12px;"
                ),
            ):
                # Header — title + open-state hint.
                with html.Div(
                    classes="d-flex align-center mb-3",
                    style="gap: 8px;",
                ):
                    vuetify3.VIcon(
                        "mdi-chart-box-outline",
                        color="teal-darken-2",
                        size="large",
                    )
                    html.Span(
                        "Descriptive Statistics",
                        classes="text-h6 font-weight-medium",
                    )
                    vuetify3.VSpacer()
                    html.Span(
                        "{{ (ui_stats_pinned_paths || []).length }} pinned",
                        classes="text-caption text-medium-emphasis",
                    )
                DescriptiveStatsPanel().render()
            # No active-panel blue inset on the Stats panel: it's a
            # singleton overlay, so the "active for editing" semantics
            # that drive that border on render panels don't apply.
            #
            # Minimize / maximize buttons — overflow up into the
            # floating window's tabstrip via negative top (the
            # `.dv-content-container` overflow:visible rule in
            # shared/styles.py keeps them from being clipped). Clicking
            # toggles ui_stats_panel_minimized, mirrored to a body class
            # that styles.py uses to collapse the floating shell.
            with html.Div(
                style=(
                    "position: absolute;"
                    " top: calc(-1 * var(--dv-tabs-and-actions-container-height, 35px));"
                    " height: var(--dv-tabs-and-actions-container-height, 35px);"
                    " right: 8px;"
                    " z-index: 5;"
                    " display: flex; align-items: center; gap: 4px;"
                    " pointer-events: auto;"
                ),
                mousedown="$event.stopPropagation()",
                click="$event.stopPropagation()",
            ):
                with vuetify3.VTooltip(location="bottom"):
                    with vuetify3.Template(v_slot_activator="{ props }"):
                        vuetify3.VBtn(
                            v_bind="props",
                            icon=(
                                "ui_stats_panel_minimized"
                                " ? 'mdi-window-restore'"
                                " : 'mdi-window-minimize'",
                            ),
                            variant="text",
                            density="compact",
                            size="small",
                            color="white",
                            click=(
                                "ui_stats_panel_minimized ="
                                " !ui_stats_panel_minimized;"
                                " ui_stats_panel_maximized = false"
                            ),
                        )
                    html.Span(
                        "{{ ui_stats_panel_minimized"
                        " ? 'Restore Stats panel'"
                        " : 'Minimize Stats panel' }}",
                    )
                with vuetify3.VTooltip(location="bottom"):
                    with vuetify3.Template(v_slot_activator="{ props }"):
                        vuetify3.VBtn(
                            v_bind="props",
                            icon=(
                                "ui_stats_panel_maximized"
                                " ? 'mdi-window-restore'"
                                " : 'mdi-window-maximize'",
                            ),
                            variant="text",
                            density="compact",
                            size="small",
                            color="white",
                            click=(
                                "ui_stats_panel_maximized ="
                                " !ui_stats_panel_maximized;"
                                " ui_stats_panel_minimized = false"
                            ),
                        )
                    html.Span(
                        "{{ ui_stats_panel_maximized"
                        " ? 'Restore Stats panel size'"
                        " : 'Maximize Stats panel' }}",
                    )
        # Open as a FLOATING overlay so Stats hovers over the render
        # views without splitting the dockview grid. `floating` accepts
        # `{width, height, position: {left|right, top|bottom}}`; the
        # bundle defaults ({left:100, top:100, width:300, height:300})
        # are too small for the multi-property table. The user drags the
        # tabstrip to move the panel, Shift+drag the tab to re-dock.
        self.add_panel(
            panel_id, panel_title, template_name,
            floating={
                "width": 1400,
                "height": 450,
                "position": {"left": 100, "top": 100},
            },
        )
        self._publish_panels_state()
        return panel_id

    def _add_distribution_panel(self, panel_id, template_name, panel_title):
        """Build one floating Distribution overlay instance. Multi-
        instance: every per-row Hist click + every Compare-histograms
        click spawns a fresh panel, so this runs once per click (no
        singleton tracking, no minimize/maximize chrome). HTML-only
        template: no pv_view, no scene_registry entry, no per-panel
        state buckets (the Plotly figure state var is scoped per-panel
        by DistributionPanel.state_var)."""
        from fespp_on_trame.app.ui.content.panel.distribution_panel import (
            DistributionPanel,
        )
        self._panel_titles[panel_id] = panel_title
        self._panel_kinds[panel_id] = "distribution"
        with DivLayout(self.server, template_name) as ui:
            ui.root.style = (
                "position:relative; height:100%; width:100%;"
                " background-color: #fafafa;"
            )
            # Plotly needs a Vuetify VContainer/VRow/VCol wrapper here;
            # an html.Div flex column collapses it to 0×0 in a dockview
            # floating shell.
            with vuetify3.VContainer(
                fluid=True,
                classes="pa-0 ma-0",
                style="height: 100%; width: 100%;",
            ):
                with vuetify3.VRow(
                    no_gutters=True,
                    classes="fill-height ma-0",
                ):
                    with vuetify3.VCol(classes="fill-height pa-0"):
                        DistributionPanel(panel_id).render()
        self.add_panel(
            panel_id, panel_title, template_name,
            floating={
                "width": 900,
                "height": 550,
                "position": {"left": 200, "top": 120},
            },
        )
        self._publish_panels_state()
        return panel_id

    def _add_stats_compare_panel(self, panel_id, template_name, panel_title):
        """Build one floating Compare-stats panel INSTANCE. Multi-
        instance singleton-per-property: boot._open_compare_stats
        guards against duplicates by checking
        state.ui_stats_compare_panel[array_path] first. Pure HTML
        template (no pv_view, no scene_registry entry); per-panel
        state vars are scoped by StatsComparePanel(panel_id)."""
        from fespp_on_trame.app.ui.content.panel.stats_compare_panel import (
            StatsComparePanel,
        )
        self._panel_titles[panel_id] = panel_title
        self._panel_kinds[panel_id] = "stats_compare"
        with DivLayout(self.server, template_name) as ui:
            ui.root.style = (
                "position:relative; height:100%; width:100%;"
                " background-color: #fafafa;"
            )
            with vuetify3.VContainer(
                fluid=True,
                classes="pa-0 ma-0",
                style="height: 100%; width: 100%;",
            ):
                with vuetify3.VRow(
                    no_gutters=True,
                    classes="fill-height ma-0",
                ):
                    with vuetify3.VCol(classes="fill-height pa-0"):
                        StatsComparePanel(panel_id).render()
        self.add_panel(
            panel_id, panel_title, template_name,
            floating={
                "width": 1100,
                "height": 600,
                "position": {"left": 180, "top": 100},
            },
        )
        self._publish_panels_state()
        return panel_id

    def _on_view_closed(self, panel_id):
        # Capture the panel's kind BEFORE popping it so the kind-gated
        # cleanup branches further down (distribution / stats_compare)
        # can still read it.
        panel_kind = self._panel_kinds.get(panel_id)
        self._html_views.pop(panel_id, None)
        self._panel_titles.pop(panel_id, None)
        self._panel_kinds.pop(panel_id, None)
        # Tear down the ViewScene created in add_view so the per-(rep,
        # view) bookkeeping doesn't leak.
        scene_registry = getattr(self.server.context, "scene_registry", None)
        if scene_registry is not None:
            try:
                scene_registry.remove_view(panel_id)
            except Exception as exc:
                pass
        # Drop the panel's per-view buckets so a future panel with
        # the same id doesn't inherit stale state.
        hidden_by_view = dict(self.server.state.ui_hidden_rep_paths_by_view or {})
        if panel_id in hidden_by_view:
            hidden_by_view.pop(panel_id, None)
            self.server.state.ui_hidden_rep_paths_by_view = hidden_by_view
        active_by_view = dict(self.server.state.ui_active_array_by_rep_by_view or {})
        if panel_id in active_by_view:
            active_by_view.pop(panel_id, None)
            self.server.state.ui_active_array_by_rep_by_view = active_by_view
        # Drop the closed panel from every camera-link group and remove
        # its own entry so a future panel with the same id doesn't
        # inherit a stale link set.
        links = {k: list(v) for k, v in (self.server.state.view_links or {}).items()}
        if panel_id in links:
            links.pop(panel_id, None)
        for k in list(links.keys()):
            if panel_id in links[k]:
                links[k] = [p for p in links[k] if p != panel_id]
                if not links[k]:
                    links.pop(k)
        self.server.state.view_links = links
        if self._active_panel_id == panel_id:
            self._active_panel_id = next(iter(self._html_views), None)
            self._mirror_active_hidden_state()
        if self._diff_panel_id == panel_id:
            self._diff_panel_id = None
            self.server.state.fespp_diff_panel_id = None
            self.server.state.fespp_diff_ready = False
        if self._stats_panel_id == panel_id:
            self._stats_panel_id = None
            self.server.state.fespp_stats_panel_id = ""
        # Distribution panels are multi-instance — no singleton field
        # to clear. Drop the per-panel figure / option / meta / CSV
        # state vars, the stored context, and the controller method
        # registered by DistributionPanel.render.
        if panel_kind == "distribution":
            per_panel_vars = (
                f"ui_distribution_figure_{panel_id}",
                f"ui_distribution_mode_{panel_id}",
                f"ui_distribution_nbins_{panel_id}",
                f"ui_distribution_log_y_{panel_id}",
                f"ui_distribution_show_stats_{panel_id}",
                f"ui_distribution_cumulative_{panel_id}",
                f"ui_distribution_norm_{panel_id}",
                f"ui_distribution_is_compare_{panel_id}",
                f"ui_distribution_meta_{panel_id}",
                f"ui_distribution_csv_{panel_id}",
            )
            try:
                state_dict = dict(self.server.state.to_dict())
                for var in per_panel_vars:
                    if var in state_dict:
                        setattr(self.server.state, var, None)
            except Exception:
                pass
            try:
                contexts = dict(self.server.state.ui_distribution_contexts or {})
                if panel_id in contexts:
                    contexts.pop(panel_id, None)
                    self.server.state.ui_distribution_contexts = contexts
            except Exception:
                pass
            try:
                compare_panels = dict(
                    self.server.state.ui_stats_compare_dist_panel or {},
                )
                changed = False
                for ap, pid in list(compare_panels.items()):
                    if pid == panel_id:
                        compare_panels.pop(ap, None)
                        changed = True
                if changed:
                    self.server.state.ui_stats_compare_dist_panel = compare_panels
            except Exception:
                pass
            # Defensively mirror the cleanup for the Compare-stats
            # singleton map too, keeping the two maps consistent.
            try:
                stats_compare_panels = dict(
                    self.server.state.ui_stats_compare_panel or {},
                )
                changed = False
                for ap, pid in list(stats_compare_panels.items()):
                    if pid == panel_id:
                        stats_compare_panels.pop(ap, None)
                        changed = True
                if changed:
                    self.server.state.ui_stats_compare_panel = stats_compare_panels
            except Exception:
                pass
            ctrl_attr = f"update_distribution_figure_{panel_id}"
            try:
                if hasattr(self.server.controller, ctrl_attr):
                    delattr(self.server.controller, ctrl_attr)
            except Exception:
                pass
        # Compare-stats panels are singleton-per-property, registered
        # in `ui_stats_compare_panel[array_path]`. Drop the singleton
        # entry and null out the per-panel state vars.
        if panel_kind == "stats_compare":
            per_panel_vars = (
                f"ui_stats_compare_array_path_{panel_id}",
                f"ui_stats_compare_visible_metrics_{panel_id}",
                f"ui_stats_compare_baseline_{panel_id}",
                f"ui_stats_compare_order_{panel_id}",
                f"ui_stats_compare_transposed_{panel_id}",
                f"ui_stats_compare_sort_key_{panel_id}",
                f"ui_stats_compare_sort_asc_{panel_id}",
                f"ui_stats_compare_annotations_{panel_id}",
                f"ui_stats_compare_items_{panel_id}",
                f"ui_stats_compare_csv_{panel_id}",
            )
            try:
                state_dict = dict(self.server.state.to_dict())
                for var in per_panel_vars:
                    if var in state_dict:
                        setattr(self.server.state, var, None)
            except Exception:
                pass
            try:
                stats_compare_panels = dict(
                    self.server.state.ui_stats_compare_panel or {},
                )
                changed = False
                for ap, pid in list(stats_compare_panels.items()):
                    if pid == panel_id:
                        stats_compare_panels.pop(ap, None)
                        changed = True
                if changed:
                    self.server.state.ui_stats_compare_panel = stats_compare_panels
            except Exception:
                pass
        self._publish_panels_state()
        super()._on_view_closed(panel_id)

    def _on_view_activated(self, panel_id):
        self._active_panel_id = panel_id
        # Publish active panel info to Vue — the contextual band above
        # the dockview reads these to render the per-panel actions
        # (settings, …) targeted on whichever panel is currently
        # focused.
        self.server.state.fespp_active_panel_id = panel_id or ""
        self.server.state.fespp_active_panel_title = self._panel_titles.get(panel_id, "")
        # Never propagate the diff panel as ParaView's active view: tree
        # eye-clicks (which retarget pvsimple.GetActiveView()) must keep
        # acting on the user's render views. The diff view's own work
        # sets the active view explicitly and restores it when done.
        #
        # Also skip the legacy-mirror sync: the diff panel's per-view
        # buckets are empty by design, and pushing those empties onto
        # ui_hidden_rep_paths / ui_active_array_by_rep would trigger
        # _on_active_array_change and clear ColorBy on the previous
        # render panel (sending it to SolidColor).
        if panel_id == self._diff_panel_id:
            return
        # Stats panel has no pv_view — `super()._on_view_activated`
        # would dereference one and crash. The stats tab is a passive
        # HTML view; it doesn't need the legacy-active-view sync.
        if panel_id == self._stats_panel_id:
            return
        # Distribution panels are HTML-only (no pv_view) — same
        # rationale as the stats short-circuit above.
        if self._panel_kinds.get(panel_id) == "distribution":
            return
        # Compare-stats panels are HTML-only (no pv_view) — same
        # rationale as the stats / distribution short-circuits.
        if self._panel_kinds.get(panel_id) == "stats_compare":
            return
        # Render-panel activation: mirror its per-view buckets onto the
        # legacy globals so rep_sources auto-reload, the prune logic
        # and the Activator see the now-active render panel's state.
        self._mirror_active_hidden_state()
        super()._on_view_activated(panel_id)

    def _mirror_active_hidden_state(self):
        """Copy the active panel's hidden-rep bucket and active-array
        map into the legacy globals so consumers reading the flat
        forms (rep_sources._relayout_chain, the prune logic in
        recompute_visibility_state, the Activator's LUT setup,
        solid_color_panel's chip refresh) see the active view's
        state. Called on every panel-active switch."""
        active = self._active_panel_id
        if not active:
            return
        st = self.server.state
        hidden_by_view = st.ui_hidden_rep_paths_by_view or {}
        bucket = list(hidden_by_view.get(active, []) or [])
        if list(st.ui_hidden_rep_paths or []) != bucket:
            st.ui_hidden_rep_paths = bucket

        active_by_view = st.ui_active_array_by_rep_by_view or {}
        new_active = dict(active_by_view.get(active, {}) or {})
        if dict(st.ui_active_array_by_rep or {}) != new_active:
            st.ui_active_array_by_rep = new_active

    def get_or_create_diff_view(
        self,
        direction: str = "within",
        reference_panel_id: str | None = None,
    ):
        """Return (panel_id, pv_view) for the dedicated diff panel,
        creating it (kind=diff, no replicate) if needed. `direction`
        and `reference_panel_id` are forwarded to add_view to control
        where the diff panel appears the first time it's created —
        ignored on subsequent calls since the existing diff panel is
        reused."""
        if self._diff_panel_id and self._diff_panel_id in self._pv_internal:
            return self._diff_panel_id, self._pv_internal[self._diff_panel_id]
        pid = self.add_view(
            kind="diff",
            direction=direction,
            reference_panel_id=reference_panel_id,
        )
        return pid, self._pv_internal[pid]

    def get_pv_view(self, panel_id):
        """Public accessor for a panel's PV render view by id. Used by
        the fespp engine when a per-view eye click needs to target a
        specific view (rather than the active one). Returns None if
        the panel doesn't exist (e.g. just closed)."""
        return self._pv_internal.get(panel_id)

    def get_html_view(self, panel_id):
        """Public accessor for a panel's trame VtkRemoteView widget by
        id. Pair with get_pv_view when an action needs to also push a
        fresh frame to the client for that specific panel."""
        return self._html_views.get(panel_id)

    def active_html_view(self):
        if self._active_panel_id is None:
            return None
        return self._html_views.get(self._active_panel_id)

    def active_pv_view(self):
        if self._active_panel_id is None:
            return None
        return self._pv_internal.get(self._active_panel_id)

    def panel_pv_views(self):
        """Public read-only snapshot ``{panel_id: PV render view}`` for every
        panel — for callers that fan an action across all views (camera /
        orientation / transformation editors, diff). Returns a copy so callers
        can't mutate the internal map."""
        return dict(self._pv_internal)

    def panel_html_views(self):
        """Public read-only snapshot ``{panel_id: trame VtkRemoteView}`` for
        every panel. Copy, like `panel_pv_views`."""
        return dict(self._html_views)

    def diff_panel_id(self):
        """Public accessor for the current diff panel id (or None when no
        diff view exists)."""
        return self._diff_panel_id

    def update_active(self, *_args, **_kwargs):
        v = self.active_html_view()
        if v is not None:
            v.update()

    def update_all(self, *_args, **_kwargs):
        """Push a fresh image to every panel's vtk.js client. Used by
        the global TC so a time change refreshes all views — not just
        the active one (which would otherwise leave the other panels
        showing the previous timestep until the user clicks on them)."""
        for v in self._html_views.values():
            try:
                v.update()
            except Exception:
                pass

    def reset_camera_active(self, *_args, **_kwargs):
        v = self.active_html_view()
        if v is not None:
            v.reset_camera()

    def replace_active(self, new_pv_view, *_args, **_kwargs):
        v = self.active_html_view()
        if v is not None:
            v.replace_view(new_pv_view)

    def _sync_camera_from(self, panel_id, *_args, **_kwargs):
        """Copy camera params from `panel_id`'s view to every view
        explicitly linked to it (`state.view_links[panel_id]`) and
        trigger a render + client image push on each. Bound to the
        vtk.js EndAnimation event of each VtkRemoteView so the sync
        only happens when the user releases the mouse — avoids the
        per-frame re-render cost of vtkSMCameraLink during the drag.

        Without a link (`view_links[panel_id]` empty / missing), no
        broadcast happens — the magnet button (ViewLinkMenu) is the
        single source of truth for camera-coupling between views.

        CenterOfRotation is part of the sync: vtk.js's interactor
        orbits around the view's CenterOfRotation, not its current
        CameraFocalPoint. Without copying it, a rotate-in-view-1
        moves the focal point in view 2 but leaves view 2's pivot
        wherever the initial ResetCamera put it, and the next
        rotate-in-view-2 orbits around the wrong point."""
        src_view = self._pv_internal.get(panel_id)
        if src_view is None or len(self._pv_internal) < 2:
            return
        links = (self.server.state.view_links or {}).get(panel_id, [])
        if not links:
            return
        params = {
            "CameraPosition": list(src_view.CameraPosition),
            "CameraFocalPoint": list(src_view.CameraFocalPoint),
            "CameraViewUp": list(src_view.CameraViewUp),
            "CameraParallelScale": float(src_view.CameraParallelScale),
            "CameraViewAngle": float(src_view.CameraViewAngle),
            "CenterOfRotation": list(src_view.CenterOfRotation),
        }
        for pid in links:
            if pid == panel_id:
                continue
            view = self._pv_internal.get(pid)
            if view is None:
                continue
            try:
                view.CameraPosition = params["CameraPosition"]
                view.CameraFocalPoint = params["CameraFocalPoint"]
                view.CameraViewUp = params["CameraViewUp"]
                view.CameraParallelScale = params["CameraParallelScale"]
                view.CameraViewAngle = params["CameraViewAngle"]
                view.CenterOfRotation = params["CenterOfRotation"]
                pvsimple.Render(view=view)
                html = self._html_views.get(pid)
                if html is not None:
                    html.update()
            except Exception:
                pass

    # Properties copied verbatim from a ref display onto the new
    # display when replicating a scene. We deliberately **omit**
    # `ColorArrayName`, `LookupTable`, `ScalarOpacityFunction`,
    # `MapScalars`: those describe scalar coloring and copying them
    # field-wise leaves PV6's display in a hybrid state where the
    # field is set but the scalar mapping isn't actually bound to the
    # LUT — the display ends up rendering in SolidColor + outline.
    # The full ColorBy is re-applied right after by the engine's
    # `apply_panel_coloring` controller (same path the eye click goes
    # through), which uses `pvsimple.ColorBy()` to do the binding
    # properly.
    #
    # `BlockSelectors` is included: a default of `['/']` on the new
    # display renders ALL blocks of the dataset as an outline overlay
    # behind the slicer surfaces; copying the ref's narrower selector
    # keeps the new display masked to the same blocks.
    _REPLICATED_DISPLAY_PROPS = (
        "Representation",
        "Opacity",
        "DiffuseColor",
        "AmbientColor",
        "Scale",
        "PointSize",
        "LineWidth",
        "BlockSelectors",
        "BlockColor",
        "BlockOpacity",
        "BlockVisibility",
        "BlockColorArrayNames",
        "OpacityArray",
        "OpacityArrayName",
        "ScalarOpacityUnitDistance",
        "InterpolateScalarsBeforeMapping",
    )

    def _copy_display_props(self, src_disp, dst_disp):
        """Mirror visual settings from src_disp onto dst_disp so a newly
        Show()n source in the destination view looks the same as in the
        source view (representation type, color array, solid color,
        opacity, z-scale, multiblock per-block tweaks, LUT/opacity-tf
        references). Properties absent on a given display class are
        silently skipped."""
        for name in self._REPLICATED_DISPLAY_PROPS:
            try:
                value = getattr(src_disp, name)
            except AttributeError:
                continue
            if value is None:
                continue
            try:
                setattr(dst_disp, name, value)
            except Exception:
                pass

    def _is_per_view_source(self, src_name: str) -> bool:
        """True when `src_name` encodes a panel id — i.e. is a per-view
        proxy (extractor, threshold, slice, clip, per-view IjkGrid
        sub-proxy, ViewScene clone). Per-view proxies belong to ONE
        scene and must never be lazily wired into another view's
        display list, otherwise `GetDisplayProperties(per_view_src,
        view=other_view)` creates a default `Vis=1 Rep='Outline'`
        display and the other view paints a phantom outline / second
        threshold overlay.

        Detection is name-based since the create sites use heterogenous
        patterns (`_v<panel_id>`, `<panel_id>_`, `EPCCollector_View<panel_id>`).
        We just check whether ANY currently-tracked panel_id appears as
        a substring of the source name."""
        if not src_name:
            return False
        for pid in self._pv_internal.keys():
            if pid and pid in src_name:
                return True
        return False

    def _force_hide_all_sources(self, new_view):
        """Hide every existing source in `new_view`, pre-creating its
        display proxy with `Visibility=0`. Used for empty render views
        so that downstream lazy `GetDisplayProperties` calls (e.g.
        from `apply_color_array` triggered by a global state change)
        return the already-hidden display instead of creating a fresh
        Vis=1 Rep='Outline' one.

        Skips per-view proxies (those belonging to OTHER scenes) since
        lazily creating a display for them in `new_view` would paint a
        phantom outline."""
        for source_id, src in pvsimple.GetSources().items():
            name = source_id[0] if isinstance(source_id, tuple) else source_id
            if name and name.startswith("fespp_diff"):
                continue
            if self._is_per_view_source(name):
                continue
            try:
                pvsimple.Hide(proxy=src, view=new_view)
            except Exception:
                pass
        try:
            pvsimple.ResetCamera(view=new_view)
            pvsimple.Render(view=new_view)
        except Exception:
            pass

    def _enforce_view_visibility_from_ref(self, ref_view, new_view):
        """For every shared / legacy source registered in PV, force the
        new_view's display Visibility to match the ref_view's. Run
        AFTER `apply_panel_coloring` since `pvsimple.ColorBy` can
        lazily create display proxies in new_view with `Visibility=1`
        by default — leaving phantom outline overlays of upstreams
        that the user expects hidden.

        Skips per-view proxies (belonging to OTHER scenes): mirroring
        their visibility from ref into new makes no sense (they render
        in their own scene's pv_view only), and calling
        `GetDisplayProperties` on them lazily creates Vis=1 display
        proxies in BOTH views by side effect."""
        for source_id, src in pvsimple.GetSources().items():
            name = source_id[0] if isinstance(source_id, tuple) else source_id
            if name and name.startswith("fespp_diff"):
                continue
            if self._is_per_view_source(name):
                continue
            try:
                ref_disp = pvsimple.GetDisplayProperties(src, view=ref_view)
            except Exception:
                ref_disp = None
            if ref_disp is None:
                continue
            ref_vis = int(getattr(ref_disp, "Visibility", 0) or 0)
            try:
                new_disp = pvsimple.GetDisplayProperties(src, view=new_view)
                if new_disp is None:
                    continue
                if int(getattr(new_disp, "Visibility", 0) or 0) != ref_vis:
                    new_disp.Visibility = ref_vis
                    sm = getattr(new_disp, "SMProxy", None)
                    if sm is not None:
                        sm.UpdateVTKObjects()
            except Exception:
                pass

    def _replicate_visibility(self, ref_view, new_view):
        """Mirror ref_view's display state onto new_view for every
        shared / legacy source. Done in two phases so visibility is
        enforced *after* all displays are created — that way a
        Show()/Hide() on one source can't flip a sibling's visibility
        through a PV side effect.

        Phase 1 — instantiate the display proxy in new_view via
        `GetDisplayProperties` (creates lazily), then copy non-color
        display props (color is applied later by
        `apply_panel_coloring` via the engine's ColorBy path).

        Phase 2 — set Visibility on each new display from the ref's
        Visibility and call `UpdateVTKObjects` to commit. Forcing this
        in a second pass guarantees no Show()/Hide() side effect on
        another source can reset what we just set.

        Skipped sources:
          - `fespp_diff*`: owned by the dedicated diff view; replicating
            it into a render view both visually duplicates the diff
            and leaks its LUT.
          - Per-view proxies (containing any panel id as substring):
            they belong to ONE scene and `GetDisplayProperties` on
            them in the wrong view lazily creates Vis=1 outline
            displays that paint phantom geometry. The per-view chain /
            slice / clip on new_view is set up by
            `scene_registry.replicate_view` instead.
        """
        work = []
        for source_id, src in pvsimple.GetSources().items():
            name = source_id[0] if isinstance(source_id, tuple) else source_id
            if name and name.startswith("fespp_diff"):
                continue
            if self._is_per_view_source(name):
                continue
            try:
                ref_disp = pvsimple.GetDisplayProperties(src, view=ref_view)
            except Exception:
                ref_disp = None
            if ref_disp is None:
                continue
            ref_vis = int(getattr(ref_disp, "Visibility", 0) or 0)
            work.append((name, src, ref_disp, ref_vis))

        # Phase 1: create displays + copy non-color props
        for name, src, ref_disp, ref_vis in work:
            try:
                new_disp = pvsimple.GetDisplayProperties(src, view=new_view)
                if new_disp is not None:
                    self._copy_display_props(ref_disp, new_disp)
            except Exception:
                pass

        # Phase 2: enforce visibility per source
        for name, src, ref_disp, ref_vis in work:
            try:
                new_disp = pvsimple.GetDisplayProperties(src, view=new_view)
                if new_disp is None:
                    continue
                new_disp.Visibility = ref_vis
                sm = getattr(new_disp, "SMProxy", None)
                if sm is not None:
                    sm.UpdateVTKObjects()
            except Exception:
                pass

        try:
            pvsimple.ResetCamera(view=new_view)
            pvsimple.Render(view=new_view)
        except Exception:
            pass

    def _render_panel_realization_picker(self, panel_id):
        """Per-view RealizationPicker — shown when:
          - at least one MR property is active on this panel's ColorBy
            (`panel_has_mr_by_id[panel_id]`), AND
          - the per-panel user toggle `show_panel_mr_<panel_id>` is on.
        The widget binds to `ui_panel_active_mr_specs_by_id[panel_id]`,
        recomputed server-side on every relevant state change.

        Vertical position is reactive: when the TC widget is visible
        (TS active AND user toggle on), MR sits at top:52px just below
        it. Otherwise MR climbs to top:4px so the panel never wastes
        the top slot. The condition mirrors the TC's own v_if in
        `_render_panel_time_control`."""
        mr_visible_var = f"show_panel_mr_{panel_id}"
        tc_visible_var = f"show_panel_tc_{panel_id}"
        self.server.state.setdefault(mr_visible_var, True)
        per_panel_show = (
            f"!!(panel_has_mr_by_id && panel_has_mr_by_id['{panel_id}'])"
            f" && {mr_visible_var}"
        )
        tc_actually_shown = (
            f"!!(panel_has_ts_by_id && panel_has_ts_by_id['{panel_id}'])"
            f" && {tc_visible_var}"
        )
        with html.Div(
            v_if=(per_panel_show, False),
            style=(
                f"`position: absolute; left: 50%;"
                f" transform: translateX(-50%);"
                f" top: ${{({tc_actually_shown}) ? 52 : 4}}px;"
                f" z-index: 2;"
                f" pointer-events: none;`"
            ,),
        ):
            PerViewRealizationPicker(panel_id).render()

    def _render_panel_time_control(self, panel_id, pv_view):
        """Per-view TimeControl docked at the top of a render panel.
        Writes view.ViewTime on this specific view only (no TimeKeeper
        touch), so this panel can diverge from the other views' time.

        Visibility is per-panel via `panel_has_ts_by_id[panel_id]` —
        the engine recomputes that map from
        `ui_active_array_by_rep_by_view` so a panel rendering only
        static properties doesn't show a useless TC. A per-panel user
        toggle `show_panel_tc_<id>` (defaults to True) hides the
        widget without unloading anything — driven by the eye-icon
        button in the panel action bar.

        Per-view realization is handled by `PerViewRealizationPicker`
        in the panel overlay (see `_render_panel_realization_picker`)
        — each panel's ColorBy binds to its own suffixed VTK array
        `<title>_real_<idx>`, so different realizations can be shown
        side by side in different panels."""
        tc_visible_var = f"show_panel_tc_{panel_id}"
        self.server.state.setdefault(tc_visible_var, True)
        html_view = self._html_views.get(panel_id)
        time_value_var = f"time_value_{panel_id}"
        time_label_var = f"ui_time_label_{panel_id}"
        register = getattr(self.server.controller, "register_per_view_time_label", None)
        if register is not None:
            try:
                register(time_value_var, time_label_var)
            except Exception:
                pass
        per_panel_show = (
            f"!!(panel_has_ts_by_id && panel_has_ts_by_id['{panel_id}'])"
            f" && {tc_visible_var}"
        )
        with html.Div(
            v_if=(per_panel_show, False),
            style=(
                "position:absolute; left:50%; transform:translateX(-50%);"
                " top: 4px; z-index: 2;"
                " min-width: 360px; max-width: 90%;"
                " pointer-events: auto;"
            ),
        ):
            FesppTimeControl(
                scope="view",
                namespace=panel_id,
                target_pv_view=pv_view,
                target_html_view=html_view,
                time_expression=time_label_var,
                show_var=per_panel_show,
            )

    def _render_panel_camera_chrome(self, panel_id):
        """Top-left vertical chrome on a render panel: magnet (link
        cameras to other views) above the per-view camera toolbar
        (reset / +X / +Y / +Z / 2D-3D). Actions iterate over the
        panel + its `state.view_links` set."""
        with html.Div(
            classes="d-flex flex-column align-center",
            style=(
                "position:absolute; top: 4px; left: 4px; z-index: 3;"
                " gap: 2px; pointer-events: auto;"
                " background: rgba(255,255,255,0.7);"
                " border-radius: 4px;"
                " padding: 2px;"
            ),
        ):
            ViewLinkMenu(panel_id).render()
            PerViewCameraToolbar(panel_id).render()

    def _render_panel_actions(self, panel_id):
        """Per-render-panel action chrome: small buttons (TC toggle,
        MR toggle, ⚙ settings) that overflow upward into the dockview
        tab row (negative top, with overflow:visible forced on
        dockview's content containers via app_layout CSS). Sitting on
        the tab row gives the buttons the dockview theme's dark
        background regardless of the panel's own background, so they
        stay readable."""
        controller = self.server.controller
        # Buttons sit centered in the dockview tab row, sized to the row
        # height (--dv-tabs-and-actions-container-height is dockview's
        # standard CSS var). `right` is reactive: when the top toolbar
        # is hidden, the floating show-toolbar chevron lives at the
        # viewport top-right, so the chrome slides left to avoid overlap.
        with html.Div(
            classes="d-flex align-center",
            style=(
                "`position: absolute;"
                " top: calc(-1 * var(--dv-tabs-and-actions-container-height, 35px));"
                " height: var(--dv-tabs-and-actions-container-height, 35px);"
                " right: ${toolbar_visible ? '8px' : '56px'};"
                " z-index: 5;"
                " gap: 4px;"
                " pointer-events: auto;`",
            ),
            # Stop mousedown/click at the wrapper so dockview doesn't
            # read them as a tab-activation request (which would force a
            # panel switch just to use these buttons).
            mousedown="$event.stopPropagation()",
            click="$event.stopPropagation()",
        ):
            tc_visible_var = f"show_panel_tc_{panel_id}"
            mr_visible_var = f"show_panel_mr_{panel_id}"
            # TC toggle — disabled when the panel has no TS property
            # active (`panel_has_ts_by_id`).
            with vuetify3.VTooltip(location="bottom"):
                with vuetify3.Template(v_slot_activator="{ props }"):
                    vuetify3.VBtn(
                        icon=(
                            f"{tc_visible_var} ? 'mdi-clock-outline'"
                            " : 'mdi-clock-remove-outline'",
                        ),
                        v_bind="props",
                        variant="text",
                        size="small",
                        color="white",
                        disabled=(
                            f"!(panel_has_ts_by_id && panel_has_ts_by_id['{panel_id}'])",
                        ),
                        click=f"{tc_visible_var} = !{tc_visible_var}",
                    )
                html.Span("Toggle in-view TimeControl")
            # MR toggle — disabled when the panel has no MR property
            # active (`panel_has_mr_by_id`).
            with vuetify3.VTooltip(location="bottom"):
                with vuetify3.Template(v_slot_activator="{ props }"):
                    vuetify3.VBtn(
                        icon=(
                            f"{mr_visible_var} ? 'mdi-layers-triple'"
                            " : 'mdi-layers-triple-outline'",
                        ),
                        v_bind="props",
                        variant="text",
                        size="small",
                        color="white",
                        disabled=(
                            f"!(panel_has_mr_by_id && panel_has_mr_by_id['{panel_id}'])",
                        ),
                        click=f"{mr_visible_var} = !{mr_visible_var}",
                    )
                html.Span("Toggle in-view Realization picker")
            with vuetify3.VTooltip(location="bottom"):
                with vuetify3.Template(v_slot_activator="{ props }"):
                    vuetify3.VBtn(
                        icon="mdi-cog-outline",
                        v_bind="props",
                        variant="text",
                        size="small",
                        color="white",
                        click=(
                            controller.open_view_settings,
                            f"['{panel_id}']",
                        ),
                    )
                html.Span("View settings (rename, …)")

    def _render_diff_chrome(self, panel_id):
        """Inline chrome for the diff panel: an A/B setup form overlay
        (visible until compute_diff runs), an in-flight compute spinner,
        and floating action buttons (palette to tweak the diff LUT,
        edit to redo A/B)."""
        # Compute spinner overlay — visible only while compute_diff is
        # running. Sits above the setup form / action buttons.
        with html.Div(
            v_if="fespp_diff_computing",
            style=(
                "position:absolute; inset:0; z-index:4;"
                " display:flex; flex-direction:column;"
                " align-items:center; justify-content:center; gap:12px;"
                " background:rgba(0,0,0,0.45);"
            ),
        ):
            vuetify3.VProgressCircular(
                indeterminate=True,
                color="blue",
                size=64,
                width=6,
            )
            html.Span(
                "Computing diff…",
                style="color: white; font-size: 0.95rem;",
            )

        # Setup form overlay — visible while fespp_diff_ready is false.
        with html.Div(
            v_if="!fespp_diff_ready",
            style=(
                "position:absolute; inset:0; z-index:3;"
                " display:flex; align-items:center; justify-content:center;"
                " background:rgba(20,20,20,0.55);"
            ),
        ):
            with vuetify3.VCard(width="460", classes="pa-2"):
                vuetify3.VCardTitle("Diff view setup")
                with vuetify3.VCardText(classes="pa-2"):
                    html.Div(
                        "Pick two properties on the same grid. The result"
                        " (A − B) is shown here.",
                        classes="text-caption text-medium-emphasis mb-3",
                    )
                    vuetify3.VSelect(
                        label="Property A",
                        v_model=("diff_array_a_path", None),
                        items=("diff_array_choices", []),
                        item_title="title",
                        item_value="value",
                        clearable=True,
                        density="comfortable",
                        variant="outlined",
                        classes="mb-2",
                    )
                    vuetify3.VSelect(
                        label="Property B",
                        v_model=("diff_array_b_path", None),
                        items=("diff_array_b_choices", []),
                        item_title="title",
                        item_value="value",
                        clearable=True,
                        disabled=("!diff_array_a_path",),
                        density="comfortable",
                        variant="outlined",
                    )
                    vuetify3.VAlert(
                        v_if=("diff_compute_error",),
                        type="error",
                        density="compact",
                        text=("diff_compute_error",),
                        classes="mt-2",
                    )
                with vuetify3.VCardActions():
                    vuetify3.VSpacer()
                    vuetify3.VBtn(
                        "Compute",
                        variant="tonal",
                        color="blue",
                        disabled=("!diff_array_a_path || !diff_array_b_path",),
                        click=(self.ctrl.compute_diff,),
                    )

        # Action buttons — top-left, only when diff has been computed.
        with html.Div(
            v_if="fespp_diff_ready",
            classes="position-absolute d-flex flex-column",
            style="top: 0.5rem; left: 0.5rem; gap: 4px; z-index: 2;",
        ):
            vuetify3.VBtn(
                icon="mdi-palette",
                size="small",
                variant="tonal",
                color="blue",
                click="diff_colors_dialog_visible = true",
            )
            vuetify3.VBtn(
                icon="mdi-pencil",
                size="small",
                variant="tonal",
                color="blue",
                click="fespp_diff_ready = false; diff_compute_error = ''",
            )
