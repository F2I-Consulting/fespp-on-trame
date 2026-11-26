<template>
  <fp-panel class="fhl" title="Data health" :summary="summaryLine" :scroll="false"
            title-tip="What is wrong with the loaded data, in one place — read-only">
    <template #controls>
      <fp-chip v-for="c in counts" :key="c.word" :class="{ 'fhl-zero': !c.n }"
               :variant="c.variant" :title="c.title" :text="fmtInt(c.n) + ' ' + c.word" />
    </template>
    <template #actions>
      <fp-btn variant="primary" label="Refresh" title="Read the loaded data again"
              @click="$emit('refresh')" />
    </template>
    <template #export>
      <fp-export :filename="csvName" :build="csvText" :disabled="!findings.length"
                 disabled-why="the file has no finding to hand over"
                 title="Copy the table as CSV — the rows as filtered here, under a dated provenance header; a download when the browser offers no clipboard (plain http)" />
    </template>

    <!-- These rows sit in the body, not in the frame's `subbar` slot: the
         frame draws the slot's bordered band as soon as the slot exists,
         which would leave an empty row on a file with nothing to report. -->
    <!-- The files the session holds, with the objects each one added: the
         only list of what was imported (a file is never read twice). -->
    <div class="fhl-files" v-if="summary.files && summary.files.length">
      <span class="fhl-files-label">Files</span>
      <span v-for="f in summary.files" :key="f.name" class="fhl-file" :class="{ 'fhl-file-failed': f.failed }"
            :title="f.failed ? f.name + ' could not be read — see the errors below'
                    : f.name + ': ' + fmtInt(f.objects) + ' object(s) added to the tree, ' + f.size_mb + ' MB'">
        {{ f.name }} <b v-if="!f.failed">{{ fmtInt(f.objects) }}</b><b v-else>failed</b>
      </span>
    </div>
    <div class="fhl-types" v-if="summary.types && summary.types.length">
      <span v-for="t in summary.types" :key="t[0]" class="fhl-type">{{ t[0] }} <b>{{ fmtInt(t[1]) }}</b></span>
    </div>
    <div class="fp-subbar" v-if="findings.length">
      <fp-seg v-model="severity" :options="severityOptions" title="Show one severity, or all of them" />
      <fp-select v-model="category" :options="categoryOptions" placeholder="every category"
                 title="Show one category of finding, or every category" />
      <input class="fp-input fhl-search" type="search" v-model="search" placeholder="filter…" />
      <span class="fhl-count">{{ fmtInt(filtered.length) }} / {{ fmtInt(findings.length) }}</span>
    </div>

    <fp-empty v-if="!findings.length" :shows="cleanBill" :gesture="cleanBillGesture" />
    <!-- A filter that hides every row must say so: an empty table reads as a
         table that failed. The clean bill of health is only given when the
         text is the only filter narrowing the table: with a severity or a
         category set, the object may carry findings the filter hides, and
         saying nothing is wrong with it would be false. -->
    <fp-empty v-else-if="!filtered.length" :shows="filteredOut"
              gesture="Clear the severity, the category and the text filter above to see every finding." />
    <div class="fp-scroll" v-else>
      <table class="fhl-table fp-table">
        <thead>
          <tr>
            <th></th>
            <th>Category</th>
            <th>Object</th>
            <th>Finding</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(f, i) in filtered" :key="i" :class="['sev-' + f.severity, { link: !!f.path }]"
              :title="f.path ? 'Click: make it the active node in the 3D view' : ''"
              @click="f.path && $emit('activate', f.path)">
            <td class="fhl-dot"><span :class="'dot-' + f.severity">●</span></td>
            <td class="fhl-cat">{{ f.category }}</td>
            <td class="fhl-obj">{{ f.object }}</td>
            <td class="fhl-msg">{{ f.message }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </fp-panel>
</template>

<script>
/*
 * Data health panel, decoupled from the engine:
 *   props in   — `data`: {summary, findings, note, csv: {name, header}} built
 *                by engine/health_dispatch, and `focus` (see below),
 *   events out — refresh() / activate(path).
 * Filters by severity, category and text; a row with a tree path is a
 * link to that node.
 *
 * The frame, the chips, the segment, the field, the button, the export and
 * the two empty states come from widgets/_shared/components: this file only
 * holds the findings table and its filtering, so no shared style is written
 * twice.
 */
import FpBtn from "../../../_shared/components/FpBtn.vue";
import FpChip from "../../../_shared/components/FpChip.vue";
import FpEmpty from "../../../_shared/components/FpEmpty.vue";
import FpExport from "../../../_shared/components/FpExport.vue";
import FpPanel from "../../../_shared/components/FpPanel.vue";
import FpSeg from "../../../_shared/components/FpSeg.vue";
import FpSelect from "../../../_shared/components/FpSelect.vue";
import { fmtInt } from "../../../_shared/numfmt.js";
import { buildCsv, csvMeta } from "../../../_shared/csvexport.js";

const CSV_COLUMNS = ["severity", "category", "object", "path", "message", "count"];

// The segment only filters: what each severity covers is told by the chips of the bar.
const SEVERITIES = [
  { value: "", label: "All", title: "Every finding" },
  { value: "error", label: "Errors", title: "Only the errors" },
  { value: "warning", label: "Warnings", title: "Only the warnings" },
  { value: "info", label: "Infos", title: "Only the infos" },
];

export default {
  name: "HealthPanel",
  components: { FpBtn, FpChip, FpEmpty, FpExport, FpPanel, FpSeg, FpSelect },
  props: {
    data: { type: Object, default: () => ({}) },
    // {text, n}: a request to show one object, from another panel's context
    // menu. It lands in the text filter (this is the session's only findings
    // table), and `n` changes on every request, so asking twice for the same
    // object still reaches the watcher.
    focus: { type: Object, default: null },
  },
  emits: ["refresh", "activate"],
  watch: {
    focus: {
      deep: true,
      // `immediate`: the panel may be created by the very gesture that names
      // the object, so it mounts with the value already set and a plain
      // watcher would never fire. The name stays visible in the filter box,
      // which tells the reader why the table shows a single object.
      immediate: true,
      handler(f) {
        if (f && f.text != null) { this.search = String(f.text); }
      },
      // The severity and category filters are NOT cleared: they are the
      // reader's own choice. The empty state names them instead, so the
      // table never claims an object is clean while a filter hides its
      // findings.
    },
  },
  data() {
    return { severity: "", category: "", search: "" };
  },
  computed: {
    severityOptions() { return SEVERITIES; },
    summary() { return (this.data && this.data.summary) || {}; },
    findings() { return (this.data && this.data.findings) || []; },
    categories() { return [...new Set(this.findings.map((f) => f.category))].sort(); },
    categoryOptions() { return this.categories.map((c) => ({ value: c, label: c })); },
    counts() {
      const s = this.summary;
      return [
        { variant: "error", word: "errors", n: s.errors || 0,
          title: "Partial objects, unreadable datasets, fesapi errors" },
        { variant: "warn", word: "warnings", n: s.warnings || 0,
          title: "Missing units, trajectories, a CRS the projection cannot use" },
        { variant: "accent", word: "infos", n: s.infos || 0,
          title: "Kinds, duplicates, constants — worth knowing, not wrong" },
      ];
    },
    filtered() {
      const q = this.search.trim().toLowerCase();
      return this.findings.filter((f) =>
        (!this.severity || f.severity === this.severity)
        && (!this.category || f.category === this.category)
        && (!q || `${f.object} ${f.message} ${f.category}`.toLowerCase().includes(q)));
    },
    // Panel rule R14 (doc/wiki/UI-Drawer-Toolbar-Shared.md): how much was
    // read, and how much of it came back partial.
    summaryLine() {
      if (!this.summary.objects) return "";
      const read = `${fmtInt(this.summary.objects)} objects`;
      return this.summary.partial
        ? `${read} · ${fmtInt(this.summary.partial)} partial` : read;
    },
    cleanBill() { return (this.data && this.data.note) || "No finding."; },
    // Refresh is only offered once there is something to read again.
    cleanBillGesture() {
      return this.summary.objects
        ? "Press “Refresh” to read the loaded data again."
        : "The table fills itself as soon as a file is loaded.";
    },
    filteredOut() {
      const q = this.search;
      if (q && !this.severity && !this.category) {
        return `Nothing matches the filters above — “${q}” has no finding, which`
          + " for an object of the file means nothing is wrong with it.";
      }
      if (q) {
        return `Nothing matches the filters above — “${q}” has none under the`
          + " severity and category chosen above; clear them to see whether it"
          + " has any at all.";
      }
      return "Nothing matches the filters above.";
    },
    csvName() { return csvMeta(this.data && this.data.csv, "health.csv").name; },
  },
  methods: {
    fmtInt,
    // The rows as filtered on screen, under the header the server sent plus
    // one line of this widget's own that says so. A finding seen once
    // carries no count: an empty cell, not an unavailable value.
    csvText() {
      const { header } = csvMeta(this.data && this.data.csv, "health.csv");
      header.push("# rows: as filtered on screen");
      const rows = this.filtered.map((f) => [
        f.severity, f.category, f.object, f.path, f.message, f.count == null ? "" : f.count,
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
/* a zero count is still worth reading, just not first */
.fhl-zero { opacity: 0.45; }
.fhl-types { display: flex; flex-wrap: wrap; gap: 4px 10px; padding: 4px 8px; border-bottom: 1px solid #eee; color: #555; font-size: 11px; }
.fhl-files { display: flex; flex-wrap: wrap; gap: 4px 10px; padding: 4px 8px; border-bottom: 1px solid #eee; color: #555; font-size: 11px; }
.fhl-files-label { font-weight: 600; color: #777; }
.fhl-file b { color: var(--fp-accent); }
.fhl-file-failed b { color: var(--fp-error-ink); }
.fhl-type b { color: var(--fp-accent); }
.fhl-search { flex: 1 1 120px; min-width: 80px; }
.fhl-count { color: var(--fp-ink-faint); }
.fhl-table td { vertical-align: top; }
.fhl-dot { width: 14px; }
.dot-error { color: #b00020; }
.dot-warning { color: #d18a00; }
.dot-info { color: #5c8bb0; }
.fhl-cat { color: var(--fp-ink-mute); white-space: nowrap; }
.fhl-obj { font-weight: 600; white-space: nowrap; max-width: 260px; overflow: hidden; text-overflow: ellipsis; }
.fhl-msg { color: #333; }
tr.link { cursor: pointer; }
tr.link:hover td { background: #f3f7fa; }
tr.sev-error td.fhl-msg { color: #7a0016; }
</style>
