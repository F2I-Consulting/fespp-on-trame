<template>
  <div class="fcp-stats">
    <div v-for="b in blocks" :key="b.kind" class="fcp-block">
      <div v-if="blocks.length > 1" class="fcp-block-title">{{ b.kind }}</div>
      <div class="fcp-scroll">
        <table class="fcp-table">
          <thead>
            <tr>
              <th class="fcp-th-item">Property{{ b.uom ? " (" + b.uom + ")" : "" }}</th>
              <th class="fcp-th-rep fcp-th-sortable" :class="{ 'fcp-th-sorted': sortKey === repColumn }"
                  title="Where the row reads: the representation of its property, or what a following row is read on — click to sort"
                  @click="sortBy(repColumn)">
                Representation<span v-if="sortKey === repColumn">{{ sortAsc ? " ▲" : " ▼" }}</span>
              </th>
              <th v-if="blockHasAxis(b, 'reals')" class="fcp-th-axis" title="The realization the row reads">Realization</th>
              <th v-if="blockHasAxis(b, 'ts_opts')" class="fcp-th-axis" title="The time step the row reads">Time step</th>
              <th v-if="b.uom_mixed" class="fcp-th-axis" :title="'The properties of this block do not share a unit: ' + blockUnits(b) + ' — their values are not directly comparable'">Unit</th>
              <th v-for="m in shownKeys(b)" :key="m" class="fcp-th-metric fcp-th-sortable"
                  :class="{ 'fcp-th-sorted': sortKey === m }"
                  :title="metricTitle(b, m)" @click="sortBy(m)">
                {{ metricHead(b, m) }}<span v-if="sortKey === m">{{ sortAsc ? " ▲" : " ▼" }}</span>
              </th>
              <th class="fcp-th-profile" title="Distribution profile from skewness and kurtosis">Profile</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="k in b.keys" :key="k" class="fcp-item"
                :class="{ 'fcp-row-base': k === baseKey, 'fcp-row-off': rowUnread(k), 'fcp-follows': !!row(k).support }"
                :title="rowHover(k)" @contextmenu.prevent="openMenu(k, $event)">
              <td class="fcp-td-item">
                <span class="fcp-item-line">
                  <span class="fcp-item-title">{{ rowTitle(k) }}</span>
                  <compare-row-tools :row-id="k" :row="row(k)" @set="$emit('set', $event)" />
                </span>
              </td>
              <td class="fcp-td-rep">
                <span class="fcp-item-rep" :title="rowRep(k)">{{ rowRep(k) }}</span>
              </td>
              <td v-if="blockHasAxis(b, 'reals')" class="fcp-td-axis">
                <compare-axis-pick :row="row(k)" which="real" @pick="$emit('set', ['real', [k, $event]])" />
              </td>
              <td v-if="blockHasAxis(b, 'ts_opts')" class="fcp-td-axis">
                <compare-axis-pick :row="row(k)" which="ts" @pick="$emit('set', ['ts', [k, $event]])" />
              </td>
              <td v-if="b.uom_mixed" class="fcp-td-axis">{{ rowUnit(k) }}</td>
              <td v-for="m in shownKeys(b)" :key="m" class="fcp-num" :class="cellClass(k, m)">
                {{ cell(k, m) }}
                <span v-if="deltaOf(k, m)" class="fcp-delta" :title="deltaTitle(k, m)">{{ deltaOf(k, m) }}</span>
              </td>
              <td class="fcp-td-profile">
                <span v-if="profileOf(k)" class="fcp-profile" :class="'fcp-profile-' + rowProfile(k)">
                  {{ profileOf(k) }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
    <!-- the right-click menu of a row: the actions on ONE row. A disabled entry
         says why in its tooltip (R16: a right-click is never mute) -->
    <fp-menu class="fcp-ctx" :at="menu" :title="menuTitle"
             :items="menuItems" @pick="menuAct" @close="menu = null" />
    <fp-empty v-if="!blocks.length"
              shows="The statistics matrix of this kind, one row per property."
              gesture="Wait for the ticked properties to be read — a property whose values are not in yet has no row." />
  </div>
</template>

<script>
/*
 * The matrix of a kind. The selection IS the matrix: one row per item and,
 * right under it, the rows that follow it (a part of its grid, a 3D view that
 * cuts or filters it). A row picks its realization and time step on itself,
 * carries its pin, and has a right-click menu for the rest. One block per
 * kind; a host feeding several gets them titled. Pure display: every gesture
 * leaves through one `set` event.
 */
import { fmt, fmtInt, unitPower, STAT_UNIT_POWER } from "../../../_shared/numfmt.js";
import FpEmpty from "../../../_shared/components/FpEmpty.vue";
import FpMenu from "../../../_shared/components/FpMenu.vue";
import CompareAxisPick from "./CompareAxisPick.vue";
import CompareRowTools from "./CompareRowTools.vue";
import {
  COUNT_COLUMNS, COUNT_KEYS, METRIC_KEYS, METRIC_LABELS, METRIC_TITLES, NO_UNIT, REP_COLUMN, blockHas, rowHas,
} from "./metrics.js";
import { followingActs, itemActs } from "./rowActs.js";

const PROFILE_TEXT = {
  symmetric: "sym", skewed_right: "↦ skew", skewed_left: "↤ skew", heavy_tail: "heavy",
};

export default {
  name: "CompareMatrix",
  components: { CompareAxisPick, CompareRowTools, FpEmpty, FpMenu },
  props: {
    blocks: { type: Array, default: () => [] },
    rows: { type: Object, default: () => ({}) },
    annotations: { type: Object, default: () => ({}) },
    // {id: {metric: {abs, rel}}} — each row's difference to the kind's baseline
    deltas: { type: Object, default: () => ({}) },
    visibleMetrics: { type: Array, default: () => [] },
    // the id of the row the others are read against
    baseKey: { type: String, default: "" },
    sortKey: { type: String, default: "" },
    sortAsc: { type: Boolean, default: true },
  },
  emits: ["set"],
  data() {
    return {
      // the right-click menu of a row: {k, x, y}, or null
      menu: null,
      repColumn: REP_COLUMN,
    };
  },
  computed: {
    // the server may send the list in any order: draw it canonical
    visibleKeys() {
      const visible = new Set(this.visibleMetrics || []);
      return METRIC_KEYS.filter((k) => visible.has(k) && !COUNT_KEYS.has(k));
    },
    menuTitle() {
      if (!this.menu) return "";
      return this.row(this.menu.k).support ? this.rowLabel(this.menu.k) : this.rowTitle(this.menu.k);
    },
    menuItems() {
      if (!this.menu) return [];
      const k = this.menu.k;
      const r = this.row(k);
      const pinnedOfPath = Object.values(this.rows || {})
        .filter((x) => x.path === r.path && x.pinned).length;
      return r.support ? followingActs() : itemActs(r, k === this.baseKey, pinnedOfPath);
    },
  },
  methods: {
    // a row by its item id, the item's own identity (its uid): a pinned
    // copy and its source stay two rows even at the same realization and
    // time step
    row(k) {
      return (this.rows || {})[k] || {};
    },
    rowLabel(k) {
      return this.row(k).label || k;
    },
    // the property's name alone: its representation, realization and time
    // step have their columns
    rowTitle(k) {
      return this.row(k).title || this.rowLabel(k);
    },
    // where the row reads, its column: its representation, or for a following
    // row what it follows on
    rowRep(k) {
      return this.row(k).support_label || this.row(k).rep;
    },
    rowHover(k) {
      const r = this.row(k);
      return [this.rowLabel(k), r.value_type, r.note].filter(Boolean).join(" · ");
    },
    rowUnit(k) {
      return this.row(k).uom || NO_UNIT;
    },
    // a row is greyed only when nothing could be read of it — a note that
    // merely says a weighted mean is missing must not dim good figures
    rowUnread(k) {
      return !!this.row(k).note && !Object.keys(this.row(k).metrics || {}).length;
    },
    rowProfile(k) {
      return this.row(k).profile || "";
    },
    profileOf(k) {
      return PROFILE_TEXT[this.rowProfile(k)] || "";
    },
    // a block draws the Realization / Time step column when one of its rows
    // has options on that axis, pinned or not
    blockHasAxis(b, which) {
      return (b.keys || []).some((k) => (this.row(k)[which] || []).length > 0);
    },
    // the distinct units the rows of a block declare, for the "mixed units"
    // chip — a row without one is listed as such, never folded under the others
    blockUnits(b) {
      const declared = [...new Set((b.keys || []).map((k) => this.row(k).uom).filter(Boolean))];
      const undeclared = (b.keys || []).some((k) => !this.row(k).uom);
      return declared.concat(undeclared ? [NO_UNIT] : []).join(", ");
    },
    shownKeys(b) {
      return COUNT_COLUMNS.concat(this.visibleKeys.filter((m) => blockHas(b, m)));
    },
    // a metric header: its word, then the unit it is read in when the block has one
    metricHead(b, m) {
      const unit = unitPower(b.uom || "", STAT_UNIT_POWER[m]);
      return METRIC_LABELS[m] + (unit ? ` (${unit})` : "");
    },
    // its tooltip: what it is weighted by when that needs saying, its unit, and the sort hint
    metricTitle(b, m) {
      const unit = unitPower(b.uom || "", STAT_UNIT_POWER[m]);
      const name = METRIC_TITLES[m] || METRIC_LABELS[m];
      return (unit ? `${name} (${unit})` : name) + " — click to sort";
    },
    metric(k, m) {
      const read = this.row(k).metrics || {};
      if (m === "Total") {
        return read.Cardinality === undefined ? null : Number(read.Cardinality) + Number(read.NaN_count || 0);
      }
      const v = read[m];
      return v === undefined || !rowHas(this.row(k), m) ? null : v;
    },
    // a count keeps every digit; a quantity follows the shared rule
    cell(k, m) {
      const v = this.metric(k, m);
      return COUNT_KEYS.has(m) ? fmtInt(v) : fmt(v);
    },
    // whether a cell reads against the baseline: neither figure may be one that means nothing
    compared(k, m) {
      return rowHas(this.row(k), m) && rowHas(this.row(this.baseKey), m);
    },
    // string tags become cell classes; a heat intensity (number) is ignored
    cellClass(k, m) {
      const tag = ((this.annotations || {})[k] || {})[m];
      return typeof tag === "string" && tag && this.compared(k, m) ? `fcp-cell-${tag}` : "";
    },
    // "+0.0123 (+7.1 %)" — the difference to the baseline under the cell,
    // signed, in the metric's unit, then in percent of the baseline
    deltaOf(k, m) {
      if (!this.compared(k, m)) return "";
      const d = ((this.deltas || {})[k] || {})[m];
      if (!d || d.abs === null || d.abs === undefined || !Number.isFinite(Number(d.abs))) return "";
      const a = Number(d.abs);
      const sign = a > 0 ? "+" : a < 0 ? "−" : "";
      const abs = COUNT_KEYS.has(m) ? fmtInt(Math.abs(a)) : fmt(Math.abs(a));
      const rel = d.rel === null || d.rel === undefined || !Number.isFinite(Number(d.rel))
        ? "" : " (" + (Number(d.rel) > 0 ? "+" : Number(d.rel) < 0 ? "−" : "") + fmt(Math.abs(Number(d.rel))) + " %)";
      return sign + abs + rel;
    },
    deltaTitle(k, m) {
      const d = ((this.deltas || {})[k] || {})[m];
      const base = this.baseKey ? this.rowLabel(this.baseKey) : "the baseline";
      const rel = d && (d.rel === null || d.rel === undefined)
        ? " — no relative difference: the baseline is 0" : "";
      return "Difference to " + base + " in the metric's unit, then in percent of it" + rel;
    },
    // a column's key — a metric, "Total" or the representation's — the
    // server sorts the block by; a second click reverses
    sortBy(m) {
      const asc = this.sortKey === m ? !this.sortAsc : true;
      this.$emit("set", ["sort", [m, asc]]);
    },
    openMenu(k, ev) {
      this.menu = { k, x: ev.clientX, y: ev.clientY };
    },
    menuAct(m) {
      if (m.disabled) return;
      const k = this.menu.k;
      this.menu = null;
      if (m.key === "baseline") this.$emit("set", ["baseline", k]);
      else if (m.key === "baseline_off") this.$emit("set", ["baseline", ""]);
      else if (m.key === "pin") this.$emit("set", [this.row(k).pinned ? "unpin" : "pin", k]);
      else if (m.key === "pin_all_ts") this.$emit("set", ["pin_all", [k, "ts"]]);
      else if (m.key === "pin_all_real") this.$emit("set", ["pin_all", [k, "real"]]);
      else if (m.key === "unpin_all") this.$emit("set", ["unpin_all", k]);
    },
  },
};
</script>

<style scoped>
.fcp-stats { min-height: 0; display: flex; flex-direction: column; overflow: hidden; padding: 4px 8px; }

/* the item cell: the name, its buttons; the representation in the next column */
.fcp-item-line { display: inline-flex; align-items: center; gap: 4px; max-width: 100%; }
.fcp-item-title { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 180px; }
.fcp-item-rep { display: inline-block; vertical-align: bottom; opacity: 0.7; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 220px; }
.fcp-th-axis, .fcp-td-axis, .fcp-th-rep, .fcp-td-rep { text-align: left !important; }

/* a following row reads under its item, in a lighter hand */
tr.fcp-follows .fcp-td-item { padding-left: 18px; }
.fcp-follows .fcp-item-title { font-weight: 400; }

.fcp-block { flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column; }
.fcp-block-title {
  font-weight: 700;
  color: var(--fp-accent);
  padding: 4px 0;
  border-bottom: 2px solid var(--fp-accent-soft);
  margin-bottom: 2px;
}

/* the matrix is denser than the shared table style: a column per metric */
.fcp-scroll { flex: 1 1 auto; min-height: 0; overflow: auto; }
.fcp-table { border-collapse: separate; border-spacing: 0; font-variant-numeric: tabular-nums; white-space: nowrap; }
.fcp-table thead th { position: sticky; top: 0; z-index: 2; }
.fcp-table thead .fcp-th-item { z-index: 3; }
.fcp-table th, .fcp-table td { padding: 2px 8px; border-bottom: 1px solid var(--fp-line-soft); text-align: right; }
.fcp-table th { font-weight: 600; color: var(--fp-accent); background: #fafafa; }
.fcp-th-item, .fcp-td-item {
  text-align: left !important;
  position: sticky;
  left: 0;
  background: var(--fp-bg);
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
}
.fcp-th-item { background: #fafafa; }
.fcp-th-sortable { cursor: pointer; user-select: none; }
.fcp-th-sortable:hover { background: var(--fp-accent-soft); }
.fcp-th-sorted { text-decoration: underline; }
.fcp-row-base > td { background: #fff59d; }
.fcp-row-off { color: #9e9e9e; }
.fcp-num { text-align: right; }
.fcp-delta { display: block; font-size: 10px; opacity: 0.8; white-space: nowrap; }
.fcp-td-profile, .fcp-th-profile { text-align: center !important; }
.fcp-profile {
  display: inline-block;
  border-radius: 8px;
  padding: 0 6px;
  font-size: var(--fp-size-tiny);
  line-height: 15px;
  background: var(--fp-neutral-bg);
  color: var(--fp-ink-soft);
}
.fcp-profile-symmetric { background: #e8f5e9; color: #1b5e20; }
.fcp-profile-heavy_tail { background: #f3e5f5; color: #6a1b9a; }
.fcp-profile-skewed_right, .fcp-profile-skewed_left { background: #fff3e0; color: #e65100; }
</style>
