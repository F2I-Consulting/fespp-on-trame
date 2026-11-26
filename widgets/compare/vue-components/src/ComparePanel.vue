<template>
  <fp-panel class="fcp" title="Statistics"
            title-tip="Count, mean, spread and percentiles of the properties you tick, side by side, their distributions and cross-plot"
            :scroll="false">
    <!-- One TAB per PWLS kind of the selection, each with its own baseline,
         sort, metrics and histogram options. There are as many
         tabs as kinds, so they are a row of buttons, not a segmented
         control (R13 in doc/wiki/UI-Drawer-Toolbar-Shared.md caps those at
         four); drawn once there is something to read. -->
    <template #controls>
      <span v-if="kinds.length" class="fcp-tabs" role="tablist">
        <fp-btn v-for="k in kinds" :key="k.kind" tiny class="fcp-tab" role="tab"
                :variant="tab === k.kind ? 'on' : 'default'" :class="{ 'fcp-tab-on': tab === k.kind }"
                :title="k.count + (k.count > 1 ? ' properties' : ' property') + ' of this kind: its own baseline, sort and histogram options'"
                @click="$emit('set', ['tab', k.kind])">{{ k.kind }} <span class="fcp-kind-n">{{ k.count }}</span></fp-btn>
      </span>
    </template>

    <template v-if="kindTab && hasAnnotations" #center>
      <compare-legend :baseline="!!baseline" />
    </template>

    <template v-if="kindTab" #actions>
      <span class="fcp-pop-anchor">
        <fp-btn label="Metrics ▾" :variant="metricsOpen ? 'on' : 'default'"
                title="Choose the visible metrics" @click="metricsOpen = !metricsOpen" />
        <div v-if="metricsOpen" class="fcp-pop">
          <div class="fcp-pop-row fcp-pop-presets">
            <fp-btn v-for="p in presets" :key="p.label" tiny :label="p.label"
                    :title="p.title" @click="setVisible(p.keys)" />
          </div>
          <label v-for="k in pickableKeys" :key="k" class="fp-check fcp-pop-row">
            <input type="checkbox" :checked="visibleSet.has(k)" @change="toggleMetric(k)" />
            <span>{{ metricLabels[k] }}</span>
          </label>
        </div>
      </span>
    </template>
    <template v-if="kindTab" #export>
      <fp-export :filename="csvName" :build="csvText" :disabled="!blocks.length"
                 disabled-why="there is no matrix to copy yet"
                 title="Copy this kind's matrix as CSV, raw values under a dated provenance header — a download when the browser offers no clipboard (plain http)" />
    </template>
    <!-- the panel's tree button: the host puts it in the `tools` slot so
         every panel carries the same one, last in the bar (R3) -->
    <template #tree>
      <slot name="tools"></slot>
    </template>

    <!-- what the panel did NOT do: a band under the bar, so it never shifts
         the buttons, and it stays until its cause goes or the reader closes it -->
    <template v-if="note" #notes>
      <fp-note :severity="noteSeverity === 'error' ? 'error' : 'warning'" :text="note"
               :next="noteSeverity === 'error' ? (noteNext || 'see the server log') : ''"
               @close="$emit('set', ['note', ''])" />
    </template>

    <div class="fcp-body" :class="{ 'fcp-thirds': kindTab && chips.length }">
      <fp-empty v-if="!chips.length"
                shows="The statistics of the properties you tick, side by side: count, mean, spread and percentiles, their distributions overlaid and their cross-plot."
                gesture="Tick a property in this panel's own tree, or use Stats in the right-click menu of a property in a 3D view's data tree." />
      <template v-else>
        <compare-matrix v-show="kindTab" :blocks="blocks" :rows="rows" :annotations="annotations" :deltas="deltas"
                        :visible-metrics="visibleMetrics" :base-key="baseline" :sort-key="sortKey" :sort-asc="sortAsc"
                        @set="$emit('set', $event)" />

        <!-- under the matrix: the distributions of the kind at the left, its
             cross-plot at the right; the charts are the host's -->
        <div v-if="kindTab" class="fcp-charts">
          <section class="fcp-chart">
            <div class="fp-subbar">
              <span class="fcp-chart-name">Distribution</span>
              <fp-hist-options compact :opts="distOpts" @set="$emit('set', ['dist_opt', $event])" />
              <fp-chip v-if="distMeta.note" class="fcp-badge" variant="accent" :text="distMeta.note"
                       :title="distMeta.note" />
            </div>
            <div class="fcp-chart-body"><slot name="dist"></slot></div>
          </section>
          <section class="fcp-chart">
            <div class="fp-subbar">
              <span class="fcp-chart-name">Cross-plot</span>
              <fp-select label="X" :model-value="xplotAxes.x || ''" :options="axisOptions.filter((o) => o.value !== xplotAxes.y)"
                         title="The row of the matrix on the horizontal axis"
                         @update:model-value="$emit('set', ['xplot_axis', ['x', $event]])" />
              <fp-btn variant="bare" icon title="Swap X and Y" :disabled="!xplotAxes.x || !xplotAxes.y"
                      @click="$emit('set', ['xplot_axis', ['swap', null]])">
                <v-icon size="15">mdi-swap-horizontal</v-icon>
              </fp-btn>
              <fp-select label="Y" :model-value="xplotAxes.y || ''" :options="axisOptions.filter((o) => o.value !== xplotAxes.x)"
                         title="The row of the matrix on the vertical axis"
                         @update:model-value="$emit('set', ['xplot_axis', ['y', $event]])" />
            </div>
            <fp-note v-if="xplotNote" severity="warning" :text="xplotNote" />
            <div class="fcp-chart-body"><slot name="xplot"></slot></div>
          </section>
        </div>
      </template>
    </div>

    <!-- A tick in this panel's tree that would read more than it shows asks
         first, as in any other tree: that confirmation box is the
         application's single one, drawn in the layout, not in this widget. -->
  </fp-panel>
</template>

<script>
import { STAT_UNIT_POWER } from "../../../_shared/numfmt.js";
import { buildCsv, csvColumn, csvMeta } from "../../../_shared/csvexport.js";
import FpBtn from "../../../_shared/components/FpBtn.vue";
import FpChip from "../../../_shared/components/FpChip.vue";
import FpEmpty from "../../../_shared/components/FpEmpty.vue";
import FpExport from "../../../_shared/components/FpExport.vue";
import FpHistOptions from "../../../_shared/components/FpHistOptions.vue";
import FpNote from "../../../_shared/components/FpNote.vue";
import FpPanel from "../../../_shared/components/FpPanel.vue";
import FpSelect from "../../../_shared/components/FpSelect.vue";
import { onEscape } from "../../../_shared/escape.js";
import CompareLegend from "./CompareLegend.vue";
import CompareMatrix from "./CompareMatrix.vue";
import { COUNT_KEYS, CSV_METRIC, METRIC_KEYS, METRIC_LABELS, NO_UNIT, PRESETS, blockHas } from "./metrics.js";

// the file's name when the server decided none
const CSV_NAME = "statistics.csv";

export default {
  name: "ComparePanel",
  components: { CompareLegend, CompareMatrix, FpBtn, FpChip, FpEmpty, FpExport, FpHistOptions, FpNote, FpPanel, FpSelect },
  props: {
    chips: { type: Array, default: () => [] },
    // the tabs: one per PWLS kind in the selection, [{kind, count}]
    kinds: { type: Array, default: () => [] },
    // the current kind tab, a kind label
    tab: { type: String, default: "" },
    // the current kind's baseline, "" for none: plain statistics (every value
    // below is that kind's own)
    baseline: { type: String, default: "" },
    blocks: { type: Array, default: () => [] },
    rows: { type: Object, default: () => ({}) },
    annotations: { type: Object, default: () => ({}) },
    // {id: {metric: {abs, rel}}} — each row's difference to the kind's baseline
    deltas: { type: Object, default: () => ({}) },
    visibleMetrics: { type: Array, default: () => [] },
    sortKey: { type: String, default: "" },
    sortAsc: { type: Boolean, default: true },
    distOpts: { type: Object, default: () => ({}) },
    distMeta: { type: Object, default: () => ({}) },
    xplotNote: { type: String, default: "" },
    // the rows on the cross-plot's axes, {x, y}: their ids
    xplotAxes: { type: Object, default: () => ({}) },
    note: { type: String, default: "" },
    noteSeverity: { type: String, default: "warn" },
    // an error's next step (R10), sent apart by the host
    noteNext: { type: String, default: "" },
    // the file name and provenance header the server decided for the CSV
    csv: { type: Object, default: () => ({ name: "", header: [] }) },
  },
  emits: ["set"],
  data() {
    return {
      metricsOpen: false,
      metricLabels: METRIC_LABELS,
      presets: PRESETS,
    };
  },
  computed: {
    visibleSet() {
      return new Set(this.visibleMetrics || []);
    },
    // what "Metrics" offers: a metric no block of the tab can draw is no choice
    pickableKeys() {
      const blocks = this.blocks || [];
      return METRIC_KEYS.filter((k) => !COUNT_KEYS.has(k)
        && (!blocks.length || blocks.some((b) => blockHas(b, k))));
    },
    csvName() {
      return csvMeta(this.csv, CSV_NAME).name;
    },
    // a kind tab is open
    kindTab() {
      return !!this.tab;
    },
    // this kind's items, in selection order (the chips are the server's
    // per-item facts; the widget reads them, it does not draw them)
    shownChips() {
      const all = this.chips || [];
      return this.kindTab ? all.filter((c) => (c.kind || "no kind") === this.tab) : all;
    },
    // what the cells' colours say: the server tags them when there is a
    // difference to tell
    hasAnnotations() {
      const a = this.annotations || {};
      return Object.keys(a).some((k) => Object.keys(a[k] || {}).length > 0);
    },
    // what the cross-plot's axes offer: the items of the kind
    axisOptions() {
      return this.shownChips.map((c) => {
        const label = this.row(c.uid).label || c.uid;
        return { value: c.uid, label, title: label };
      });
    },
  },
  watch: {
    tab() {
      this.metricsOpen = false;
    },
  },
  mounted() {
    // Escape closes the Metrics popover
    this._unEscape = onEscape(() => { this.metricsOpen = false; });
  },
  beforeUnmount() {
    if (this._unEscape) this._unEscape();
  },
  methods: {
    row(k) {
      return (this.rows || {})[k] || {};
    },
    setVisible(keys) {
      const want = new Set(keys);
      this.$emit("set", ["visible_metrics", METRIC_KEYS.filter((k) => want.has(k))]);
    },
    toggleMetric(k) {
      const next = new Set(this.visibleSet);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      this.setVisible([...next]);
    },
    // the matrix of the tab as a file: the raw metrics of every row, every
    // metric and not only the visible ones (the mean along the hole only on a
    // block where a row has it); a unit column joins the row's columns when
    // the rows mix units. A host feeding several blocks gets one section each.
    csvText() {
      const { header } = csvMeta(this.csv, CSV_NAME);
      const sections = (this.blocks || []).map((b) => {
        const uom = b.uom || "";
        const mixed = !!b.uom_mixed;
        const kindLine = `# kind: ${b.kind}${uom ? ` (${uom})` : mixed ? " (mixed units)" : ""}`;
        const keys = METRIC_KEYS.filter((m) => m !== "Mean (L)" || b.has_length);
        const columns = ["property", "representation", "realization", "time_step"]
          .concat(mixed ? ["unit"] : [])
          .concat(keys.map((m) => csvColumn(CSV_METRIC[m], uom, STAT_UNIT_POWER[m])));
        const rows = (b.keys || []).map((k) => {
          const r = this.row(k);
          const metrics = r.metrics || {};
          return [r.label || k, r.support_label || r.rep || "",
            r.real ?? r.real_read ?? "", r.ts_text || r.ts_label || (r.ts ?? "")]
            .concat(mixed ? [r.uom || NO_UNIT] : [])
            .concat(keys.map((m) => (metrics[m] === undefined ? null : metrics[m])));
        });
        return buildCsv([kindLine], columns, rows);
      });
      return header.join("\n") + "\n" + sections.join("\n");
    },
  },
};
</script>

<style>
@import "../../../_shared/panel.css";
@import "./cells.css";
</style>

<style scoped>
.fcp-tabs { display: inline-flex; align-items: center; gap: 2px; }
.fcp-tab { font-weight: 500; }

.fcp-pop-anchor { position: relative; }
.fcp-pop {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  z-index: 20;
  min-width: 200px;
  background: var(--fp-bg);
  border: 1px solid var(--fp-btn-line);
  border-radius: 4px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.18);
  padding: 6px;
}
.fcp-pop-row { display: flex; align-items: center; gap: 5px; padding: 2px; }
.fcp-pop-presets {
  flex-wrap: wrap;
  border-bottom: 1px solid var(--fp-line-soft);
  padding-bottom: 6px;
  margin-bottom: 4px;
}

.fcp-badge {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* body */
.fcp-body { flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column; overflow: auto; }
/* a third for the matrix, whose rows alone scroll, two for the charts */
.fcp-thirds { display: grid; grid-template-rows: minmax(0, 1fr) minmax(0, 2fr); grid-template-columns: minmax(0, 1fr); overflow: hidden; }
/* under the matrix, side by side, each in half of the width */
.fcp-charts {
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  grid-template-rows: auto auto minmax(0, 1fr);
  column-gap: 8px;
  padding: 0 8px 4px;
}
/* on the rows of the grid: however their bars wrap, the plots start level */
.fcp-chart { display: grid; grid-row: span 3; grid-template-rows: subgrid; grid-template-columns: minmax(0, 1fr); min-height: 0; min-width: 0; overflow: hidden; border-top: 1px solid var(--fp-line-soft); }
.fcp-chart-name { font-weight: 600; color: var(--fp-accent); }
.fcp-chart-body { grid-row: 3; min-height: 0; display: flex; flex-direction: column; }
.fcp-chart-body :deep(.fxg) { flex: 1 1 auto; min-height: 0; grid-auto-rows: minmax(0, 1fr); }

/* the item count beside a kind tab's name */
.fcp-kind-n { opacity: 0.7; }
</style>
