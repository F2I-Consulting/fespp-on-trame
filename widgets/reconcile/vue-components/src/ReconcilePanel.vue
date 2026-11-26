<template>
  <fp-panel class="frc" title="Log ↔ Grid"
            title-tip="The logs ticked in this panel's tree or held by the log view, against the grid property of their kind sampled along the trajectory, zone by zone"
            :summary="summary" :scroll="false">
    <template #controls>
      <label class="fp-lab" title="Sampling step along the trajectory, in depth units">
        step
        <fp-num class="frc-num" v-model="stepValue" size="sm" :min="0.05"
                title="Sampling step along the trajectory, in depth units" />
      </label>
      <fp-select v-if="wells.length > 1" class="frc-sel" v-model="wellFilter" :options="wellOptions"
                 placeholder="every well" title="Keep the rows of one well" />
    </template>
    <template #actions>
      <fp-btn variant="primary" label="Refresh" title="Sample the grid along the trajectories and rebuild the table"
              @click="$emit('compute', [stepValue])" />
      <fp-btn label="Auto-pair" title="Pair every log with the grid properties of its kind (by name when a file declares no kind)"
              @click="$emit('auto-pairs')" />
    </template>
    <!-- the host's tree button (the docked tree that ticks logs and grid
         properties into this table), in the frame's tree slot -->
    <template #tree>
      <slot name="tools"></slot>
    </template>
    <template #export>
      <fp-export :filename="csvName" :build="csvText" :disabled="!rows.length"
                 disabled-why="there is no row yet, press Refresh first"
                 title="Copy the table as CSV — the rows as filtered and sorted here, raw values under a dated provenance header; a download when the browser offers no clipboard (plain http)" />
    </template>

    <!-- the pairs: what is compared with what, and on which basis -->
    <template #subbar>
      <span class="frc-h">Pairs</span>
      <fp-chip v-if="data && data.auto" sm variant="accent" text="auto"
               title="Paired automatically by kind; edit them and the list becomes yours" />
      <span class="fp-sum" v-if="!pairs.length">none yet</span>
      <fp-chip v-for="(p, i) in pairs" :key="p.log + '|' + p.prop" variant="line" class="frc-pair"
               :title="pairTitle(p)">
        <span class="frc-plog">{{ p.log }}</span>
        <span class="frc-arrow">↔</span>
        <span class="frc-pprop">{{ propTitle(p.prop) }}</span>
        <span class="fp-chip fp-chip-sm frc-basis" :class="[basisClass(p.basis), { 'frc-basis-bad': p.class_mismatch }]">{{ basisLabel(p.basis) }}{{ p.class_mismatch ? " !" : "" }}</span>
        <template #after>
          <fp-btn variant="bare" label="×" title="Drop this pair" @click="removePair(i)" />
        </template>
      </fp-chip>
      <span class="frc-add">
        <fp-select class="frc-sel" v-model="newLog" :options="logOptions" placeholder="Log" mandatory
                   title="The log of the new pair" />
        <fp-select class="frc-sel" v-model="newProp" :options="propOptions" placeholder="Grid property" mandatory
                   title="The grid property the log is set against" />
        <fp-btn tiny label="+" :disabled="!newLog || !newProp"
                :title="newLog && newProp ? 'Add this pair' : 'Pick a log and a grid property first'"
                @click="addPair" />
      </span>
    </template>

    <fp-empty v-if="!rows.length"
              shows="One row per log, zone by zone, against the grid property of its kind: the means, the medians and how far apart they stand."
              gesture="Tick logs and a grid property in this panel's tree (the tree button), pair them above (or let “Auto-pair” do it), then press “Refresh”."
              :why="(data && data.note) || ''" />
    <div class="fp-scroll" v-else>
      <table class="frc-table fp-table">
        <thead>
          <tr>
            <th v-for="c in columns" :key="c.key" :class="{ on: sortKey === c.key, num: c.num }"
                :title="c.title" @click="sortBy(c.key)">
              {{ c.label }}<span v-if="sortKey === c.key">{{ sortDir > 0 ? " ▲" : " ▼" }}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(r, i) in sorted" :key="i" :class="severity(r)">
            <td>{{ r.well }}</td>
            <td :title="r.zone_source + ' · ' + fmtFixed(r.top, 2) + ' – ' + fmtFixed(r.bottom, 2)">{{ r.zone }}</td>
            <td>{{ r.kind }}</td>
            <td>{{ r.log }}</td>
            <td :title="r.prop_unit ? 'declared in ' + r.prop_unit : 'no unit declared'">{{ r.prop }}</td>
            <td :title="unitTitle(r)">{{ valueUnit(r) || "–" }}</td>
            <td class="num">{{ fmtInt(r.n_log) }}</td>
            <td class="num">{{ fmtInt(r.n_grid) }}</td>
            <td class="num">{{ fmt(r.mean_log) }}</td>
            <td class="num">{{ fmt(r.mean_grid) }}</td>
            <td class="num" :title="lengthTitle(r)">{{ fmt(r.mean_grid_len) }}</td>
            <td class="num">{{ fmt(r.p50_log) }}</td>
            <td class="num">{{ fmt(r.p50_grid) }}</td>
            <td class="num">{{ fmt(r.gap) }}</td>
            <td class="num">{{ fmtPct(r.rel) }}</td>
            <td class="num frc-z">{{ fmt(r.z) }}</td>
            <td><span class="frc-flag" :class="{ 'frc-flag-few': isFew(f), 'frc-flag-bad': isBadClass(f) }" v-for="f in r.flags" :key="f" :title="flagTitle(f)">{{ f }}</span></td>
          </tr>
        </tbody>
      </table>
    </div>
  </fp-panel>
</template>

<script>
/*
 * Well ↔ model reconciliation panel, decoupled from the engine:
 *   props in   — `data`: {rows, pairs, auto, logs, props, wells, note, step,
 *                min_samples, csv: {name, header}} built by
 *                engine/reconcile_dispatch,
 *   events out — compute([step]) / auto-pairs() / set-pairs(pairs).
 * The table sorts on a header click; the pairs list is editable (drop one,
 * add one from the logs and grid properties the session offers).
 * Units differ from one row to the next, so the unit is a column: the one
 * mean, P50 and Δ are expressed in — the log's, or the grid property's when
 * the log was scaled to it (the server names the scaling in the flags); the
 * grid property's own unit is the tooltip of its cell.
 */
import { fmt, fmtFixed, fmtInt, fmtPct } from "../../../_shared/numfmt.js";
import { buildCsv, csvMeta } from "../../../_shared/csvexport.js";
import FpBtn from "../../../_shared/components/FpBtn.vue";
import FpChip from "../../../_shared/components/FpChip.vue";
import FpEmpty from "../../../_shared/components/FpEmpty.vue";
import FpExport from "../../../_shared/components/FpExport.vue";
import FpNum from "../../../_shared/components/FpNum.vue";
import FpPanel from "../../../_shared/components/FpPanel.vue";
import FpSelect from "../../../_shared/components/FpSelect.vue";

const COLUMNS = [
  { key: "well", label: "Well" },
  { key: "zone", label: "Zone", title: "From the stratigraphic column laid onto the well, else the marker pairs" },
  { key: "kind", label: "Kind", title: "The RESQML property kind the pair shares" },
  { key: "log", label: "Log" },
  { key: "prop", label: "Grid property" },
  { key: "unit", label: "Unit", title: "The unit mean, P50 and Δ are in: the log's, or the grid property's when the log was scaled to it (see the flags)" },
  { key: "n_log", label: "n log", num: true, title: "Log samples in the zone" },
  { key: "n_grid", label: "n cells", num: true, title: "Trajectory stations in the zone that fall in a grid cell" },
  { key: "mean_log", label: "mean log", num: true },
  { key: "mean_grid", label: "mean grid", num: true, title: "The grid property averaged over the samples of the zone, one sample one vote" },
  { key: "mean_grid_len", label: "Mean grid (L)", num: true, title: "The grid property averaged over the length of hole actually traversed inside the zone, on true vertical depth — a sample near a zone bound counts only for the part of its stretch that is inside" },
  { key: "p50_log", label: "P50 log", num: true },
  { key: "p50_grid", label: "P50 grid", num: true },
  { key: "gap", label: "Δ", num: true, title: "mean log − mean grid, in the row's unit" },
  { key: "rel", label: "Δ %", num: true, title: "Δ over the log's mean" },
  { key: "z", label: "z", num: true, title: "Δ in log standard deviations — the contradiction score; a zone with too few log samples ranks after the others" },
  { key: "flags", label: "Flags", title: "Too few log samples for the sort, unit scaled or differing, approximate kind, pairing by name, quantity classes differing or unchecked" },
];

const CSV_COLUMNS = [
  "well", "zone", "zone_source", "top", "bottom", "kind", "log", "log_unit",
  "grid_property", "grid_unit", "unit", "basis", "class_log", "class_grid",
  "n_log", "n_cells", "mean_log", "mean_grid", "mean_grid_len", "traversed_length",
  "p50_log", "p50_grid", "delta", "delta_rel (fraction)", "z", "flags",
];

const BASIS = {
  kind: ["kind", "The same RESQML property kind on both sides"],
  "kind~": ["≈ kind", "Kinds sharing a word — approximate"],
  name: ["name", "The same title; no kind declared"],
  "name~": ["≈ name", "Titles sharing a word — approximate"],
  manual: ["manual", "Paired by hand"],
};

export default {
  name: "ReconcilePanel",
  components: { FpBtn, FpChip, FpEmpty, FpExport, FpNum, FpPanel, FpSelect },
  props: {
    data: { type: Object, default: () => ({}) },
  },
  emits: ["compute", "auto-pairs", "set-pairs"],
  data() {
    return {
      stepValue: 1.0,
      sortKey: "",
      sortDir: -1,
      wellFilter: "",
      newLog: "",
      newProp: "",
    };
  },
  watch: {
    "data.step"(v) { if (v) this.stepValue = v; },
  },
  computed: {
    columns() { return COLUMNS; },
    rows() { return (this.data && this.data.rows) || []; },
    pairs() { return (this.data && this.data.pairs) || []; },
    logs() { return (this.data && this.data.logs) || []; },
    props() { return (this.data && this.data.props) || []; },
    wells() { return [...new Set(this.rows.map((r) => r.well))]; },
    wellOptions() {
      return this.wells.map((w) => ({ value: w, label: w, title: "Only the rows of " + w }));
    },
    logOptions() {
      return this.logs.map((l) => ({
        value: l.title, label: l.title + (l.kind ? " · " + l.kind : ""), title: l.kind ? l.title + " (" + l.kind + ")" : l.title,
      }));
    },
    propOptions() {
      return this.props.map((p) => ({
        value: p.path, label: p.title + (p.kind ? " · " + p.kind : ""), title: p.kind ? p.title + " (" + p.kind + ")" : p.title,
      }));
    },
    csvName() {
      return csvMeta(this.data && this.data.csv, "log_grid.csv").name;
    },
    filtered() {
      return this.wellFilter ? this.rows.filter((r) => r.well === this.wellFilter) : this.rows;
    },
    sorted() {
      if (!this.sortKey) return this.filtered;     // the server's order: |z| first
      const k = this.sortKey, d = this.sortDir;
      return [...this.filtered].sort((a, b) => {
        const x = a[k], y = b[k];
        if (x == null && y == null) return 0;
        if (x == null) return 1;
        if (y == null) return -1;
        if (typeof x === "number" && typeof y === "number") return (x - y) * d;
        return String(x).localeCompare(String(y)) * d;
      });
    },
    summary() {
      if (!this.data) return "";
      const n = this.rows.length;
      // a zone flagged for too few samples has no z worth counting: it is
      // listed apart, never among the "beyond 2 sigma"
      const isThin = (r) => (r.flags || []).some((f) => this.isFew(f));
      const bad = this.rows.filter((r) => r.z != null && Math.abs(r.z) > 2 && !isThin(r)).length;
      const few = this.rows.filter(isThin).length;
      const thin = few ? ` · ${few} with n<${this.minSamples}` : "";
      return n ? `${n} rows · ${bad} beyond 2 σ${thin}` : "";
    },
    minSamples() { return (this.data && this.data.min_samples) || 5; },
  },
  methods: {
    fmt,
    fmtFixed,
    fmtInt,
    fmtPct,
    // the unit the compared values are in (a row without one keeps the log's)
    valueUnit(r) { return r.unit != null ? r.unit : (r.log_unit || ""); },
    unitTitle(r) {
      const u = this.valueUnit(r);
      if (!u) return "The log declares no unit — the values are as recorded";
      if (r.log_unit && u !== r.log_unit) return `Log in ${r.log_unit}, scaled to the grid property's ${u} (see the flags): mean, P50 and Δ are in ${u}`;
      return r.prop_unit && r.prop_unit !== u
        ? `Log in ${u}; the grid property is declared in ${r.prop_unit} (see the flags)`
        : `Log and grid property in ${u}`;
    },
    severity(r) {
      const z = r.z == null ? null : Math.abs(r.z);
      return z == null ? "" : z > 2 ? "sev-2" : z > 1 ? "sev-1" : "";
    },
    propTitle(path) {
      const p = this.props.find((x) => x.path === path);
      return p ? p.title : path;
    },
    // the "n<N" flag (N = min_samples): the zone holds too few log samples
    // for its z to rank the row, which sorts after the others and stays in
    // the table
    isFew(f) { return /^n<\d+$/.test(f); },
    // the two sides are not the same kind of quantity: the row is not a
    // contradiction to read, it is a pairing to drop
    isBadClass(f) { return f.startsWith("different quantity classes"); },
    flagTitle(f) {
      if (this.isFew(f)) {
        return `Fewer than ${this.minSamples} log samples in the zone: too few for the sort — the row is ranked after the others`;
      }
      if (this.isBadClass(f)) {
        return "The PWLS quantity classes of the log and of the grid property differ: they are not the same kind of quantity, so the row ranks last";
      }
      if (f === "quantity class not checked") {
        return "PWLS knows the quantity class of neither side (or of only one): the pairing could not be checked against one, and the ranking is unchanged";
      }
      return f;
    },
    // what the length-weighted grid mean rests on
    lengthTitle(r) {
      if (r.mean_grid_len == null) {
        return "No length of hole could be weighed in this zone (a single grid sample): the plain mean is the only one reported";
      }
      return `Weighted by ${fmtFixed(r.len_grid, 2)} of hole traversed in the zone, on true vertical depth`;
    },
    basisLabel(b) { return (BASIS[b] || BASIS.manual)[0]; },
    // the class of an approximate basis carries no "~": a tilde in a class
    // name must be escaped in a selector, and an unescaped one turns the
    // rule into a dangling sibling combinator that the browser drops whole
    basisClass(b) { return "b-" + String(b || "manual").replace("~", "-approx"); },
    basisTitle(b) { return (BASIS[b] || BASIS.manual)[1]; },
    // the whole reason for the pair — the basis words AND what the two PWLS
    // quantity classes said. A pair the class guard demoted carries a "!"
    // and the amber, so it shows in the strip even when it yields no row at
    // all (a zone with no sample never reaches the table)
    pairTitle(p) {
      const t = this.basisTitle(p.basis);
      return p.why ? `${t} — ${p.why}` : t;
    },
    sortBy(key) {
      if (this.sortKey === key) {
        if (this.sortDir < 0) this.sortDir = 1;
        else { this.sortKey = ""; this.sortDir = -1; }
      } else {
        this.sortKey = key;
        this.sortDir = -1;
      }
    },
    removePair(i) {
      this.$emit("set-pairs", this.pairs.filter((_, j) => j !== i).map((p) => ({ ...p })));
    },
    addPair() {
      if (!this.newLog || !this.newProp) return;
      if (this.pairs.some((p) => p.log === this.newLog && p.prop === this.newProp)) return;
      this.$emit("set-pairs", this.pairs.map((p) => ({ ...p })).concat([{ log: this.newLog, prop: this.newProp, basis: "manual" }]));
      this.newLog = "";
      this.newProp = "";
    },
    // the rows as filtered and sorted on screen (the one header line this
    // widget writes itself says so), raw values, one unit per column
    csvText() {
      const { header } = csvMeta(this.data && this.data.csv, "log_grid.csv");
      header.push("# rows: as filtered/sorted on screen");
      const rows = this.sorted.map((r) => [
        r.well, r.zone, r.zone_source, r.top, r.bottom, r.kind,
        r.log, r.log_unit, r.prop, r.prop_unit, this.valueUnit(r), r.basis,
        r.class_log, r.class_grid,
        r.n_log, r.n_grid, r.mean_log, r.mean_grid, r.mean_grid_len, r.len_grid,
        r.p50_log, r.p50_grid,
        r.gap, r.rel, r.z, (r.flags || []).join("; "),
      ]);
      return buildCsv(header, CSV_COLUMNS, rows);
    },
  },
};
</script>

<style>
@import "../../../_shared/panel.css";
</style>

<style scoped>
.frc-sel { max-width: 220px; }
.frc-h { font-weight: 600; color: var(--fp-ink-soft); }
.frc-pair { gap: 4px; }
.frc-pair .fp-chip-text { display: inline-flex; align-items: center; gap: 4px; }
.frc-plog, .frc-pprop { font-weight: 600; }
.frc-arrow { color: var(--fp-accent); }
/* the basis of a pair, glued to it: by kind, by name, or approximate */
.frc-basis.b-kind { background: #d9efd9; color: #2e6b2e; }
.frc-basis.b-kind-approx, .frc-basis.b-name-approx { background: var(--fp-warn-bg); color: var(--fp-warn-ink); }
.frc-basis.b-name { background: var(--fp-accent-soft); color: var(--fp-accent); }
.frc-basis.frc-basis-bad { background: var(--fp-warn-bg); color: var(--fp-warn-ink); font-weight: 700; border: 1px solid var(--fp-warn-ink); }
.frc-add { display: inline-flex; align-items: center; gap: 4px; }
.frc-table th { cursor: pointer; }
.frc-table th.on { text-decoration: underline; }
.frc-table td { white-space: nowrap; }
.frc-z { font-weight: 700; }
tr.sev-1 td.frc-z { color: #b26a00; }
tr.sev-2 td.frc-z { color: var(--fp-error-ink); }
tr.sev-2 td { background: #fff5f5; }
.frc-flag { display: inline-block; font-size: var(--fp-size-tiny); background: var(--fp-warn-bg); color: var(--fp-warn-ink); border-radius: 8px; padding: 0 5px; margin-right: 3px; }
.frc-flag-few { background: var(--fp-accent-soft); color: var(--fp-accent); font-weight: 600; }
.frc-flag-bad { background: var(--fp-warn-bg); color: var(--fp-warn-ink); font-weight: 700; border: 1px solid var(--fp-warn-ink); }
</style>
