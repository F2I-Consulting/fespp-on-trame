<template>
  <div class="fxg">
    <!-- no chart at all (a tab before it holds two items): what would be drawn,
         the gesture that fills it, and the server's reason -->
    <fp-empty v-if="!shown.length" class="fxg-none"
              :shows="SHOWS" :gesture="GESTURE" :why="(meta && meta.note) || ''" />
    <!-- one cell per chart, under its own caption line: what it draws, the
         pairs it holds, then what can be done to it (drawn alone, pinned as a
         snapshot, unpinned) -->
    <div v-for="c in shown" :key="c.key" class="fxg-cell"
         :class="{ 'fxg-pinned': c.pinned, 'fxg-loading': c.loading }">
      <div class="fxg-caption" :title="captionTitle(c)">
        <span class="fxg-title">{{ c.title }}</span>
        <span v-if="c.kept" class="fp-sum fxg-n">{{ fmtInt(c.kept) }}</span>
        <span class="fxg-acts">
          <fp-btn variant="bare" :class="{ 'fxg-lit': lit(c) }"
                  :title="zoomTitle(c)"
                  :disabled="!c.kept && !lit(c)"
                  @click="$emit('set', ['focus', lit(c) ? null : c.key])">
            <svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true">
              <circle cx="6.5" cy="6.5" r="4.5" fill="none" stroke="currentColor" stroke-width="1.6" />
              <line x1="10" y1="10" x2="14.5" y2="14.5" stroke="currentColor" stroke-width="1.8"
                    stroke-linecap="round" />
            </svg>
          </fp-btn>
          <!-- pinned: a filled mark and an x that drops the snapshot;
               live: an outline pin that freezes the chart -->
          <fp-btn v-if="c.pinned" variant="bare" title="Unpin (remove this snapshot)"
                  @click="$emit('set', ['pin', c.key])">
            <svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true">
              <path d="M6 1.5h4v1l-1 1v3.5l2.5 2V10H8.6v4.5L8 15.5 7.4 14.5V10H4.5V9l2.5-2V3.5l-1-1z"
                    fill="currentColor" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round" />
            </svg>
          </fp-btn>
          <fp-btn v-else variant="bare" :disabled="!c.kept"
                  :title="c.kept ? 'Pin a snapshot of this chart: it stays as it is while this Y moves on' : 'Nothing is drawn: there is no chart to pin'"
                  @click="$emit('set', ['pin', c.key])">
            <svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true">
              <path d="M6 1.5h4v1l-1 1v3.5l2.5 2V10H8.6v4.5L8 15.5 7.4 14.5V10H4.5V9l2.5-2V3.5l-1-1z"
                    fill="none" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round" />
            </svg>
          </fp-btn>
        </span>
      </div>
      <!-- a chart whose values are still being read says so where it will
           be drawn: the busy bar under its caption (R9) -->
      <fp-progress v-if="c.loading" label="Reading the values of this chart" />
      <!-- the chart: the host's plotly component, one per figure; the
           selection leaves with the chart's key, a double-click clears -->
      <trame-plotly v-if="figureOf(c)" class="fxg-fig"
                    :data="figureOf(c).data" :layout="figureOf(c).layout"
                    :display-mode-bar="true" :displaylogo="false" :responsive="true"
                    :mode-bar-buttons-to-add="MODEBAR"
                    @selected="onSelected(c.key, $event)" @deselect="$emit('select', null)" />
      <div v-else-if="c.loading" class="fxg-fig"></div>
      <!-- nothing drawn anywhere: the empty state sits in the first cell,
           where the gesture that fills it is -->
      <fp-empty v-else-if="c.key === firstUndrawn" class="fxg-fig fxg-why"
                :shows="SHOWS" :gesture="GESTURE" :why="c.note || (meta && meta.note) || ''" />
      <!-- a row with nothing to draw keeps its place and says why -->
      <div v-else class="fxg-fig fxg-why fp-sum">{{ c.note || 'Nothing to draw.' }}</div>
    </div>
  </div>
</template>

<script>
/*
 * The charts of the cross-plot: one cell per chart, under its caption line.
 * Pure display: the figures come from the host, one per drawn chart, filled in
 * as they are read; a caption control leaves as set([key, value]), a box or
 * lasso on a chart as select({chart, range, lasso}).
 *   props in  — charts [{key, title, pinned, kept, nan_y, nonpos_y, note,
 *               loading}] (every chart, drawn or not), figures [{key, rev,
 *               data, layout}] (the drawn ones), focus (the key drawn alone),
 *               meta
 * A live chart is `live:i`, a pinned snapshot `pin:n`. A chart not drawn yet
 * shows its loading mark; one that cannot be drawn (no Y, another grid, the
 * diagonal) keeps its cell and says why.
 * R9 is the panel rule of doc/wiki/UI-Drawer-Toolbar-Shared.md for a slow
 * action: a busy bar, the previous content kept underneath.
 */
import { fmtInt } from "../../../_shared/numfmt.js";
import FpBtn from "../../../_shared/components/FpBtn.vue";
import FpProgress from "../../../_shared/components/FpProgress.vue";
import FpEmpty from "../../../_shared/components/FpEmpty.vue";

// The modebar offers only the box on WebGL scatters, never the lasso:
// both are asked for explicitly.
const MODEBAR = ["lasso2d", "select2d"];

const SHOWS = "X against Y, cell by cell.";

const GESTURE = "Pick them above, among the rows on this grid.";

// The figure objects handed to plotly, held per grid instance. The host
// ships the whole list again at every step of a run (the first chart,
// then two, four…), and plotly redraws a chart whenever its `data` object
// CHANGES: redrawing every chart at every shipment freezes the page. A
// figure whose `rev` is the one already held is handed over as the SAME
// object, and plotly leaves it alone. The held figure also stays on
// screen, under the busy bar, while its chart is read again (R9: the
// previous content kept underneath), so a log toggle updates the chart in
// place and its zoom survives instead of a remount.
const FIGS = new WeakMap();

export default {
  name: "CrossplotGrid",
  components: { FpBtn, FpEmpty, FpProgress },
  props: {
    charts: { type: Array, default: () => [] },
    figures: { type: Array, default: () => [] },
    focus: { default: null },
    meta: { type: Object, default: () => ({}) },
  },
  emits: ["set", "select"],
  data() {
    return { MODEBAR, SHOWS, GESTURE };
  },
  computed: {
    byKey() {
      const out = {};
      for (const f of this.figures || []) if (f && f.key) out[f.key] = f;
      return out;
    },
    // every chart of the panel, or the focused one alone
    shown() {
      const all = this.charts || [];
      if (!this.focus) return all;
      const one = all.filter((c) => c.key === this.focus);
      return one.length ? one : all;
    },
    // the cell that carries the empty state: the first live one on screen,
    // and only when nothing is drawn or being read anywhere in the panel
    firstUndrawn() {
      if ((this.charts || []).some((c) => c.loading || this.byKey[c.key])) return null;
      const first = this.shown.find((c) => !c.pinned);
      return first ? first.key : null;
    },
  },
  methods: {
    fmtInt,
    // the magnifier: one chart alone
    lit(c) {
      return this.focus === c.key;
    },
    zoomTitle(c) {
      if (this.lit(c)) return "Back to all charts";
      if (!c.kept) return "Nothing is drawn: there is nothing to show alone";
      return "Show this chart alone";
    },
    figureOf(c) {
      const f = this.byKey[c.key];
      let held = FIGS.get(this);
      if (!held) FIGS.set(this, (held = {}));
      const h = held[c.key];
      if (f) {
        if (h && f.rev && h.rev === f.rev) return h.fig;
        held[c.key] = { rev: f.rev, fig: f };
        return f;
      }
      if (c.loading && h) return h.fig;
      delete held[c.key];
      return null;
    },
    // the caption's tooltip says what the chart drew and what its Y left
    // out; an undrawn chart says why, a loading one that it is read
    captionTitle(c) {
      if (c.loading) return c.title + " — reading its values";
      if (!c.kept) return c.note || c.title;
      const unit = (this.meta || {}).unit || "values";
      const gaps = [c.nan_y ? `${fmtInt(c.nan_y)} ${unit} without a Y value` : "",
        c.nonpos_y ? `${fmtInt(c.nonpos_y)} ≤ 0 on the log Y axis` : ""].filter(Boolean);
      return [`${c.title} — ${fmtInt(c.kept)} pairs`].concat(gaps).join(" · ");
    },
    // the geometry only, with the chart it was drawn on — never the points
    onSelected(key, ev) {
      if (!ev) { this.$emit("select", null); return; }
      this.$emit("select", { chart: key, range: ev.range || null, lasso: ev.lassoPoints || null });
    },
  },
};
</script>

<style scoped>
.fxg {
  position: relative;
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 8px;
  padding: 8px;
  align-content: start;
  font-family: var(--fp-font);
  font-size: var(--fp-size);
}
.fxg-cell { display: flex; flex-direction: column; min-width: 0; height: 100%; min-height: 320px; border: 1px solid var(--fp-line-soft); border-radius: 4px; background: var(--fp-bg); }
.fxg-pinned { border-style: dashed; }
.fxg-caption {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 2px 6px;
  border-bottom: 1px solid var(--fp-line-soft);
  min-height: 26px;
}
.fxg-loading .fxg-caption { border-bottom: 0; }
.fxg-title { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 600; font-size: var(--fp-size-small); }
.fxg-n { flex: 0 0 auto; font-size: var(--fp-size-tiny); font-variant-numeric: tabular-nums; }
.fxg-acts { flex: 0 0 auto; display: inline-flex; align-items: center; gap: 2px; }
.fxg-lit { opacity: 1; color: var(--fp-accent); }
.fxg-fig { width: 100%; flex: 1 1 auto; height: 100%; min-height: 0; }
.fxg-why { display: flex; align-items: center; justify-content: center; text-align: center; padding: 8px; font-style: italic; }
.fxg-none { grid-column: 1 / -1; }
</style>
