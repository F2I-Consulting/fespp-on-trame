<template>
  <!-- the active node is the card's target, named by the card frame after
       its title ("Values · Facies"): the widget draws no second header
       for it -->
  <div class="fap">
    <template v-if="activeNode">
      <!-- No "Colored by" line: the eyed property is the marked column of
           the table (the manager, 21/10: the two first lines said nothing).
           No XML section: the XML explorer is a view of its own (the
           manager, 15/10). -->

      <!-- The values, paged, open at once: the card IS the values (the
           PO, 15/10). A geometry node is read by its cells (id, I J K on
           an IJK grid, the ticked properties) or by its points (id, X Y Z,
           the ticked point properties); a property node on its whole grid
           or on a part of it (the manager, 21/10). -->
      <div class="fap-section fap-grow">
        <!-- ONE head line: what the rows are read on — a property on its
             whole grid or one of its parts, named in the accent (the PO,
             21/10: a bare select went unnoticed), a geometry by its cells or
             points — then, at the right, the count and the export -->
        <div class="fap-top">
          <!-- only when there is a part to read on (a subrepresentation or an
               extract in memory): a grid alone has nothing to choose -->
          <div v-if="supportOptions.length > 1" class="fap-on">
            <span class="fap-on-label">Read on</span>
            <fp-select class="fap-part" :model-value="(values && values.part) || ''"
                       :options="supportOptions" title="Read the property on its whole grid or on one of its parts"
                       @update:model-value="setPart($event)" />
          </div>
          <fp-seg v-if="values && values.geometry && shown === 'table'" class="fap-assoc" :model-value="assocShown" :options="values.readings || ASSOCS"
                  title="Read the geometry by its cells or by its points"
                  @update:model-value="assoc = $event; resetFilters()" />
          <fp-seg v-if="ijk" class="fap-assoc" :model-value="view" :options="VIEWS"
                  title="The values as rows, or one K layer of the grid as a map coloured as in the view"
                  @update:model-value="setView($event)" />
          <span class="fap-gap"></span>
          <!-- what is highlighted (rows of the table or cells selected in
               3D): kept or taken out as a new object under the grid, as the
               tree row offers it, or cleared (the manager, 29/10) -->
          <template v-if="lit">
            <fp-btn v-if="!named && !samples" tiny class="fap-hl" label="Keep"
                    :title="'Keep only the ' + lit + ' highlighted ' + itemWord + ', as a new object under the grid'"
                    @click="extract('keep')" />
            <fp-btn v-if="!named && !samples" tiny class="fap-hl" label="Remove"
                    :title="'Take the ' + lit + ' highlighted ' + itemWord + ' out of the grid, as a new object under it'"
                    @click="extract('remove')" />
            <fp-btn tiny class="fap-hl" :label="lit + ' ● Clear'"
                    :title="'Clear the ' + lit + ' highlighted ' + itemWord + ' in the view'"
                    @click="clearSelection" />
          </template>
          <span v-if="values && values.count != null" class="fap-muted">{{ fmtInt(values.count) }} {{ rowWord }}</span>
          <fp-export v-if="values && values.columns" :filename="csvName" :build="csvText"
                     :disabled="!values || !values.rows || !values.rows.length"
                     disabled-why="there is no row to hand over"
                     :title="'Copy every row the filter keeps, all pages (the first ' + fmtInt(CSV_MAX) + '), as CSV'" />
        </div>
        <!-- the Map: one K layer, I across and J down as on a map, each
             cell its value in its colour of the view's table (the PO,
             03/11); on the velocity model's grid a click edits a cell -->
        <div v-if="openValues && shown === 'map'" class="fap-map">
          <div v-if="layerMap && layerMap.error" class="fap-hint">{{ layerMap.error }}</div>
          <fp-progress v-else-if="!layerMap || !layerMap.rows" class="fap-hint" label="Loading…" />
          <template v-else>
            <div class="fap-map-head">
              <span class="fap-on-label">Layer</span>
              <fp-num size="sm" integer stepper :min="1" :max="layerMap.nk" :model-value="layerMap.k + 1"
                      title="The K layer the map shows, 1 at the top of the grid"
                      @update:model-value="loadMap($event - 1)" />
              <span class="fap-muted">of {{ layerMap.nk }} · {{ layerMap.array }} · {{ layerMap.ni }} × {{ layerMap.nj }}</span>
              <span v-if="layerMap.editable" class="fap-muted">· click a cell to set its velocity</span>
            </div>
            <div class="fap-map-wrap">
              <table class="fap-mapt">
                <thead>
                  <tr>
                    <th class="fap-map-corner" title="J down the rows, I across the columns, counted from 1">J \ I</th>
                    <th v-for="i in layerMap.ni" :key="'i' + i">{{ i }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(row, r) in layerMap.rows" :key="'r' + r">
                    <th>{{ layerMap.nj - r }}</th>
                    <td v-for="(v, i) in row" :key="'c' + i" class="fap-mapc"
                        :class="{ 'fap-map-edit': layerMap.editable }"
                        :style="cellStyle(r, i)" :title="mapTip(r, i, v)"
                        @click="mapEdit(i, layerMap.nj - 1 - r)" @focusout="mapEditing = null">
                      <fp-num v-if="isMapEditing(i, layerMap.nj - 1 - r)" class="fap-map-input" size="sm" :min="1"
                              :model-value="v" :title="'The velocity of cell I ' + (i + 1) + ' J ' + (layerMap.nj - r) + ' K ' + (layerMap.k + 1) + ', m/s'"
                              @update:model-value="mapCommit(i, layerMap.nj - 1 - r, $event)" />
                      <span v-else>{{ mapText(v) }}</span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </template>
        </div>
        <template v-if="openValues && shown === 'table'">
          <!-- the filter, Hide NaN and the rows selected in 3D only once the node is read: before,
               they filter nothing -->
          <template v-if="values && values.columns">
            <!-- rows of conditions, each on the column the reader picks (the
                 first property by default), its fields starting at that
                 column's range; a row joins the one above by ∩ (both) or ∪
                 (either), ∩ binding tighter, as in the Thresholds card (the
                 PO, 21/10: a filter on J dropped the one on I). Enter or blur
                 applies a bound. -->
            <div v-for="(c, i) in conds" :key="i" class="fap-filter">
              <fp-btn v-if="i > 0" tiny class="fap-op" :label="c.op === 'or' ? '∪' : '∩'"
                      :title="c.op === 'or' ? 'Union: the rows passing this group OR the one above — click for ∩' : 'Intersection: the rows passing this AND the row above — click for ∪'"
                      @click="toggleOp(i)" />
              <span v-else class="fap-muted fap-op-w">filter</span>
              <fp-select v-if="filterColumns.length > 1" class="fap-fcol" :model-value="colOf(c)"
                         :options="filterColumns" title="The column this condition reads"
                         @update:model-value="setColumn(i, $event)" />
              <span v-else-if="colOf(c)" class="fap-muted">{{ colOf(c) }}</span>
              <fp-num :model-value="c.min !== null ? c.min : rangeOf(c)[0]" nullable size="sm" placeholder="min"
                      :title="'Keep the rows whose ' + (colOf(c) || 'value') + ' is at least this; it starts at the lowest value, empty for no lower bound'"
                      @update:model-value="setBound(i, 'min', $event)" />
              <span class="fap-muted">…</span>
              <fp-num :model-value="c.max !== null ? c.max : rangeOf(c)[1]" nullable size="sm" placeholder="max"
                      :title="'Keep the rows whose ' + (colOf(c) || 'value') + ' is at most this; it starts at the highest value, empty for no upper bound'"
                      @update:model-value="setBound(i, 'max', $event)" />
              <fp-btn v-if="conds.length > 1 || c.min !== null || c.max !== null" tiny icon label="×"
                      :title="conds.length > 1 ? 'Remove this condition' : 'Clear the filter and show every row again'"
                      @click="removeCond(i)" />
              <fp-btn v-if="i === conds.length - 1" tiny icon label="+"
                      title="Add a condition: ∩ keeps the rows passing both; click its ∩ to make it ∪ (either)"
                      @click="addCond" />
            </div>
            <!-- the cells the selection tool holds in 3D: their rows are
                 marked, and this keeps them alone (the manager, 15/10: they
                 had to be hunted for) -->
            <!-- the rows with no value in the column the filter reads left out,
                 by default as everywhere a NaN is (the PO, 20/11) -->
            <label class="fp-check fap-only"
                   :title="'Leave out the rows with no value (NaN) in ' + (nanColumns || 'the filtered column')">
              <input type="checkbox" :checked="hideNan" @change="hideNan = $event.target.checked; reload(0)" />
              Hide NaN
            </label>
            <label v-if="(values && values.picked) || only" class="fp-check fap-only"
                   :title="'Keep only the rows of the ' + itemWord + ' selected in the 3D view (the selection tool of the view\'s toolbar)'">
              <input type="checkbox" :checked="only" @change="only = $event.target.checked; reload(0)" />
              Selected {{ itemWord }} only <span class="fap-muted">({{ fmtInt((values && values.picked) || 0) }})</span>
            </label>
          </template>
          <!-- a node not read yet: offered to be read, as its box in a panel's tree would -->
          <div v-if="values && !values.columns && values.error" class="fap-hint">
            {{ values.error }}
            <fp-btn v-if="values.read" tiny class="fap-read" :label="'Read ' + (values.read_title || 'it')"
                    :title="'Read ' + (values.read_title || 'this node') + ' to see its values here; the 3D views do not change'"
                    @click="$emit('read-node', values.read)" />
          </div>
          <fp-progress v-else-if="!values || !values.columns" class="fap-hint" label="Loading…" />
          <template v-else-if="!values.rows.length">
            <div class="fap-hint">No values{{ filtered ? ' in this range' : hideNan ? ' but NaN — untick Hide NaN to see those rows' : ' on this node' }}.</div>
          </template>
          <template v-else>
            <div class="fap-table-wrap">
              <!-- a row read by its cell lists the cell's points (their ids,
                   the Points reading's), unfolded to their X Y Z (the PO,
                   21/10); the column stands after the cell's I J K -->
              <table class="fap-table" :class="{ 'fap-one': single }">
                <thead>
                  <tr>
                    <th v-for="h in headers" :key="h.key" :class="{ 'fap-num': h.num, 'fap-eyed': h.eyed, 'fap-pts': h.points }"
                        :style="colStyle(h.key)" :title="h.title">{{ h.label }}<span
                          class="fap-grip" title="Drag to set the column's width; double-click: as wide as what it holds"
                          @pointerdown.stop.prevent="gripDown($event, h.key)" @dblclick.stop="gripReset(h.key)"></span></th>
                  </tr>
                </thead>
                <tbody @pointerleave="hoverRow(null)">
                  <template v-for="r in values.rows" :key="r[0]">
                    <tr :class="{ 'fap-sel': selected.has(r[0]), 'fap-picked': pickedSet.has(r[0]), 'fap-still': !lights,
                                  'fap-cursor': values.cursor != null && values.cursor === r[0] }"
                        :title="!lights ? null : single ? 'Click: hold this sample in the views (again: let it go)'
                          : 'Click or press-and-drag: highlight in the view (multi-select)'"
                        @pointerdown.prevent="dragStart(r[0])" @pointerenter="dragOver(r[0]); hoverRow(r)">
                      <td v-for="(c, ci) in cells(r)" :key="c.key" :class="{ 'fap-num': c.num, 'fap-eyed': c.eyed, 'fap-pts': c.points }"
                          :style="colStyle((headers[ci] || {}).key)">
                        <template v-if="c.points && pointsOf(r[0])">
                          <fp-btn tiny icon class="fap-chev" :label="unfolded.has(r[0]) ? '▾' : '▸'"
                                  :aria-expanded="unfolded.has(r[0]) ? 'true' : 'false'"
                                  :title="(unfolded.has(r[0]) ? 'Fold' : 'Unfold') + ' the X Y Z of the cell\'s points'"
                                  @pointerdown.stop @click="unfold(r[0])" />
                          <span :title="pointsTitle(r[0])">{{ pointsText(r[0]) }}</span>
                        </template>
                        <template v-else-if="!c.points">{{ c.text }}</template>
                      </td>
                    </tr>
                    <tr v-if="hasPoints && unfolded.has(r[0]) && pointsOf(r[0])" class="fap-sub">
                      <td :colspan="headers.length">
                        <table class="fap-subtable">
                          <thead><tr><th>point id</th><th v-for="a in 'XYZ'" :key="a" class="fap-num">{{ axis(a) }}</th></tr></thead>
                          <tbody>
                            <tr v-for="(pid, k) in pointsOf(r[0]).ids" :key="pid">
                              <td>{{ pid }}</td>
                              <td v-for="(x, a) in pointsOf(r[0]).xyz[k]" :key="a" class="fap-num">{{ fmt(x, "XYZ"[a]) }}</td>
                            </tr>
                          </tbody>
                        </table>
                        <div v-if="pointsOf(r[0]).more" class="fap-muted">and {{ fmtInt(pointsOf(r[0]).more) }} more points</div>
                      </td>
                    </tr>
                  </template>
                </tbody>
              </table>
            </div>
            <div class="fap-pager">
              <fp-btn tiny icon label="◀" :disabled="values.offset <= 0"
                      :title="values.offset <= 0 ? 'This is the first page' : 'The previous ' + PAGE + ' values'"
                      @click="page(-1)" />
              <span>{{ fmtInt(values.offset + 1) }}–{{ fmtInt(values.offset + values.rows.length) }} / {{ fmtInt(values.count) }}<span v-if="values.total != null && values.total !== values.count" class="fap-muted"> (of {{ fmtInt(values.total) }})</span></span>
              <fp-btn tiny icon label="▶" :disabled="values.offset + values.rows.length >= values.count"
                      :title="values.offset + values.rows.length >= values.count ? 'This is the last page' : 'The next ' + PAGE + ' values'"
                      @click="page(1)" />
            </div>
          </template>
        </template>
      </div>
    </template>

    <fp-empty v-else
              shows="The values of the active node, a page at a time: a geometry's cells (their I J K and points) or points (their X Y Z) with its ticked properties, a property on its grid or on a part of it."
              gesture="Click the name of a node in the tree to make it the active one." />
  </div>
</template>

<script>
/*
 * Per-view Values card (custom Vue, no Vuetify). Knows nothing about the
 * engine:
 *   props in  — the active node (title) and a PAGE of its values {count,
 *               total, offset, assoc, columns, rows, picked, picked_rows,
 *               only, highlight, supports, part, points, points_at, row_names,
 *               cursor (the row the log view's cursor stands on, marked and scrolled to),
 *               rows_lit}: `picked` the node's cells
 *               the 3D selection tool holds, `picked_rows` those of this
 *               page, `highlight` the column coloring the view (marked),
 *               `supports` the parts of its grid a property can be read on
 *               ({value, label}, "" the whole grid) and `part` the one read;
 *               `points` {row index: {ids, xyz, more}} the points of each
 *               row's cell, drawn in a column at `points_at`; `row_names`
 *               {row index: name} the rows that are named things, a
 *               frame's markers or its logs — no cells to keep or remove —
 *               and `rows_lit` false when a row lights nothing in the view;
 *               `valuesCsv` the host's answer to export-values {n, name,
 *               text} or {n, error}.
 *   events out — load-values({offset, filters, only, hide_nan, assoc, part}): the
 *               host computes the page; `filters` = [{column, min, max, op}]
 *               the rows of conditions — column "" for its default, the
 *               first property; null = no bound; op "and" (∩) or "or" (∪),
 *               ∩ binding tighter — the page says which columns can be
 *               filtered and the range of each one read (`ranges`), where
 *               the fields start;
 *               `assoc` "" lets the host read the node its way, a point set
 *               by its points; `only` keeps the cells selected in 3D;
 *               `hide_nan` leaves out the rows with no value in a column the
 *               filter reads (on by default); `part`
 *               "" reads a property on its whole grid);
 *               export-values({...the same, n}): every row the filter
 *               keeps, as CSV, answered in `valuesCsv` under `n`
 *               (_shared/askHost);
 *               highlight([indices]): the rows selected in the table (multi,
 *               click toggles) to highlight in the view; [] clears;
 *               extract("keep" | "remove"): what is highlighted kept or
 *               taken out as a new object under the grid (29/10);
 *               read-node(path): the node a page offers to read (`read`,
 *               `read_title` on a page with no columns) read.
 * Everything is scoped to ONE view.
 */
import { fmt as fmtNum, fmtInt } from "../../../_shared/numfmt.js";
import { askHost } from "../../../_shared/askHost.js";
import FpBtn from "../../../_shared/components/FpBtn.vue";
import FpProgress from "../../../_shared/components/FpProgress.vue";
import FpEmpty from "../../../_shared/components/FpEmpty.vue";
import FpExport from "../../../_shared/components/FpExport.vue";
import FpNum from "../../../_shared/components/FpNum.vue";
import FpSeg from "../../../_shared/components/FpSeg.vue";
import FpSelect from "../../../_shared/components/FpSelect.vue";

const PAGE = 200;
// a row under the pointer is told this often at most
const HOVER_MS = 60;

// a condition of the filter: no bound, the host's default column, ∩
function freshCond(col = "") {
  return { col, min: null, max: null, op: "and" };
}
// the rows a Copy CSV hands over at most (engine/values_table.CSV_MAX_ROWS)
const CSV_MAX = 100000;

// the values as rows, or a K layer of an IJK grid as a coloured map
const VIEWS = [
  { value: "table", label: "Table", title: "The values as rows, a page at a time" },
  { value: "map", label: "Map", title: "One K layer of the grid: I across, J down, each cell in its colour of the view" },
];

// how a geometry node is read
const ASSOCS = [
  { value: "CELLS", label: "Cells", title: "One row per cell: its id, its I J K on an IJK grid, the ticked cell properties" },
  { value: "POINTS", label: "Points", title: "One row per point (node): its id, its X Y Z, the ticked point properties" },
];

export default {
  name: "AttributesPanel",
  components: { FpBtn, FpEmpty, FpExport, FpNum, FpProgress, FpSeg, FpSelect },
  props: {
    activeNode: { type: String, default: "" },
    // the active node's path: two nodes of one title ("geometry" of two
    // objects, the velocity of two versions of a grid) are two nodes
    activeKey: { type: String, default: "" },
    values: { type: Object, default: () => ({}) },
    valuesCsv: { type: Object, default: () => ({}) },
    // the Map's layer: {array, k, nk, ni, nj, rows, colors, editable} | {error}
    layerMap: { type: Object, default: () => ({}) },
  },
  emits: ["load-values", "export-values", "highlight", "hover", "extract", "load-map", "map-cell", "read-node"],
  data() {
    // the filter bounds are Numbers or null: <fp-num> reads a typed comma as
    // the decimal point, and the host converts what it receives to float
    // `assoc` "" and a condition's `col` "" leave the choice to the host (a
    // point set read by its points, the filter on the first property);
    // `part` "" reads a property on its whole grid
    return { openValues: true, conds: [freshCond()], only: false, hideNan: true, assoc: "",
             part: "", selected: new Set(), dragMode: "", dragFrom: -1, dragBase: null,
             unfolded: new Set(), PAGE, CSV_MAX, ASSOCS, VIEWS, view: "table", mapEditing: null,
             // {column: px} the widths the reader set, by the column's key
             colW: {} };
  },
  mounted() {
    // the card opens on its values
    if (this.activeNode) this.reload(0);
  },
  computed: {
    nodeKey() { return this.activeKey || this.activeNode; },
    // the node reads an IJK grid: its rows carry I J K
    ijk() {
      const cols = (this.values && this.values.columns) || [];
      return cols.includes("I") && cols.includes("J") && cols.includes("K");
    },
    // what the card shows: the Map where the node has one, else the
    // table — the reader's choice kept for the next grid
    shown() {
      return this.view === "map" && this.ijk ? "map" : "table";
    },
    filtered() {
      return this.only || this.conds.some((c) => c.min !== null || c.max !== null);
    },
    // the columns Hide NaN reads: those of the filter's rows
    nanColumns() {
      return [...new Set(this.conds.map((c) => this.colOf(c)).filter(Boolean))].join(", ");
    },
    // how many rows are highlighted: those of the table, else the cells
    // the 3D selection holds
    lit() {
      return this.selected.size || Number((this.values && this.values.picked) || 0);
    },
    // a row read by its cell lists the cell's points
    hasPoints() {
      return !!(this.values && this.values.points && this.values.points_at);
    },
    pickedSet() {
      return new Set((this.values && this.values.picked_rows) || []);
    },
    // rows that are named things (a frame's markers, its logs), not cells
    named() {
      return !!(this.values && this.values.row_names);
    },
    // a click on a row lights it in the view
    lights() {
      return !(this.values && this.values.rows_lit === false);
    },
    // a log's samples: one held at a time
    single() {
      return !!(this.values && this.values.single);
    },
    // what a row is: a point set read by its points selects points
    // a well's log read sample by sample: nothing of a grid to keep or take out
    samples() {
      return !!(this.values && this.values.columns && this.values.columns[0] === "sample");
    },
    itemWord() {
      if (this.named || this.samples) return this.values.columns[0] + "s";
      return this.values && this.values.assoc === "POINTS" ? "points" : "cells";
    },
    // the count names the first column's rows: a blocked wellbore's are
    // intervals
    rowWord() {
      return this.values && this.values.columns && this.values.columns[0] === "interval"
        ? "intervals" : this.itemWord;
    },
    // the reader's choice, else how the host read the node
    assocShown() {
      return this.assoc || (this.values && this.values.assoc) || "CELLS";
    },
    supportOptions() {
      return ((this.values && this.values.supports) || [])
        .map((s) => ({ value: s.value, label: s.label, title: "Read the property on " + s.label }));
    },
    filterColumns() {
      return ((this.values && this.values.filter_columns) || [])
        .map((c) => ({ value: c, label: c, title: "Filter on " + c }));
    },
    // the file's name is the server's rule (csv_export), said with the page
    csvName() {
      return (this.values && this.values.csv_name) || "values.csv";
    },
    // the table's columns, the points column (a row's cell's points) set
    // after the cell's I J K when the page carries it
    headers() {
      const v = this.values || {};
      const out = (v.columns || []).map((c, j) => ({
        key: c, label: this.axis(c), num: j > 0, eyed: j > 0 && c === v.highlight,
        title: j > 0 && c === v.highlight ? c + " colors the view" : ((v.titles || {})[c] || null),
      }));
      if (this.hasPoints) {
        out.splice(Math.min(v.points_at, out.length), 0, {
          key: "points", label: "points", points: true,
          title: "The ids of the cell's points (the Points reading's point id); ▸ unfolds their X Y Z",
        });
      }
      return out;
    },
  },
  watch: {
    // the host dropped the page while the node kept its title (the
    // velocity model's grid written anew under the same name): read again
    values(v) {
      if (this.activeNode && this.openValues && v && !Object.keys(v).length
          && Date.now() - (this.askedAt || 0) > 500) this.reload(0);
    },
    // the row the log view's cursor stands on: brought into the middle of
    // the table, clear of its sticky header (at the edge, the first row of a
    // page hid under it)
    // the sample held from the log view (or let go there): the table's selection
    "values.held"(rows) {
      if (this.single && Array.isArray(rows)) this.selected = new Set(rows);
    },
    "values.cursor"(gi) {
      if (gi == null) return;
      this.$nextTick(() => {
        const row = this.$el && this.$el.querySelector("tr.fap-cursor");
        if (row) row.scrollIntoView({ block: "center" });
      });
    },
    // another node activated: drop the highlight (its indices belong to the
    // previous node) and the filter (another node, other columns), let the
    // host read it its way, and load page 0 — and the Map its layer
    nodeKey() {
      if (this.selected.size) this.clearSelection();
      this.assoc = "";
      this.conds = [freshCond()];
      this.part = "";
      this.unfolded = new Set();
      if (this.openValues) this.reload(0);
      if (this.shown === "map") this.loadMap(0);
    },
    // the Map shown again (picked, or a grid reached from a node without
    // one): its layer read
    shown(v) {
      if (v === "map") this.loadMap((this.layerMap && this.layerMap.k) || 0);
    },
  },
  methods: {
    setView(v) {
      this.view = v;
    },
    loadMap(k) {
      this.mapEditing = null;
      this.$emit("load-map", { k: Math.max(0, Number(k) || 0) });
    },
    cellStyle(r, i) {
      const c = this.layerMap.colors && this.layerMap.colors[r] && this.layerMap.colors[r][i];
      if (!c) return null;
      const n = parseInt(c.slice(1), 16);
      const lum = 0.299 * (n >> 16) + 0.587 * ((n >> 8) & 255) + 0.114 * (n & 255);
      return { background: c, color: lum > 140 ? "#111" : "#fff" };
    },
    mapText(v) {
      if (v == null) return "–";
      return Math.abs(v) >= 100 ? fmtInt(Math.round(v)) : String(Number(v.toPrecision(3)));
    },
    mapTip(r, i, v) {
      const m = this.layerMap;
      return `I ${i + 1} J ${m.nj - r} K ${m.k + 1}: ${v == null ? "no value" : v}`
        + (m.editable ? " — click to set it" : "");
    },
    isMapEditing(i, j) {
      return Boolean(this.mapEditing && this.mapEditing.i === i && this.mapEditing.j === j);
    },
    mapEdit(i, j) {
      if (!this.layerMap.editable || this.isMapEditing(i, j)) return;
      this.mapEditing = { i, j };
      this.$nextTick(() => {
        const input = this.$el.querySelector(".fap-map-input");
        if (input) {
          input.focus();
          input.select();
        }
      });
    },
    mapCommit(i, j, v) {
      this.mapEditing = null;
      if (v == null || !Number.isFinite(v)) return;
      this.$emit("map-cell", { i, j, k: this.layerMap.k, v });
    },
    request(offset) {
      return { offset, only: this.only, hide_nan: this.hideNan, assoc: this.assoc, part: this.part,
               filters: this.conds.map((c) => ({ column: c.col, min: c.min, max: c.max, op: c.op })) };
    },
    // the column a condition reads: the reader's, else the host's default
    colOf(c) {
      return c.col || (this.values && this.values.filter_on) || "";
    },
    rangeOf(c) {
      const r = this.values && this.values.ranges && this.values.ranges[this.colOf(c)];
      return r ? [r[0] != null ? r[0] : null, r[1] != null ? r[1] : null] : [null, null];
    },
    addCond() {
      this.conds = [...this.conds, freshCond(this.colOf(this.conds[this.conds.length - 1]))];
    },
    removeCond(i) {
      this.conds = this.conds.length > 1
        ? this.conds.filter((_c, k) => k !== i)
        : [freshCond(this.conds[0].col)];
      this.reload(0);
    },
    toggleOp(i) {
      this.conds = this.conds.map((c, k) => (k === i ? { ...c, op: c.op === "or" ? "and" : "or" } : c));
      this.reload(0);
    },
    resetFilters() {
      this.conds = [freshCond()];
      this.reload(0);
    },
    reload(offset) {
      this.askedAt = Date.now();
      this.$emit("load-values", this.request(offset));
    },
    // every row the filter keeps, built by the host (the card holds one page)
    async csvText() {
      const answer = await askHost(this, (n) => this.$emit("export-values", { ...this.request(0), n }),
                                   () => this.valuesCsv);
      if (answer.error) throw new Error(answer.error);
      return answer.text;
    },
    // a row's cells in the headers' order: the id, the values, the points
    cells(r) {
      const cols = this.values.columns;
      const out = r.map((v, j) => ({
        key: j, text: j === 0 ? this.rowName(v) : this.fmt(v, cols[j]), num: j > 0,
        eyed: j > 0 && cols[j] === this.values.highlight,
      }));
      if (this.hasPoints) out.splice(Math.min(this.values.points_at, out.length), 0, { key: "points", points: true });
      return out;
    },
    // a row under its own name when the page gives one (a marker), else its id
    rowName(gi) {
      const names = (this.values || {}).row_names;
      return names && names[String(gi)] != null ? names[String(gi)] : gi;
    },
    pointsOf(gi) {
      return (this.values && this.values.points && this.values.points[String(gi)]) || null;
    },
    // the first ids, the rest in the tooltip and the unfolded rows
    pointsText(gi) {
      const p = this.pointsOf(gi);
      if (!p) return "";
      const shown = p.ids.slice(0, 8).join(" ");
      return p.ids.length > 8 || p.more ? shown + " …" : shown;
    },
    pointsTitle(gi) {
      const p = this.pointsOf(gi);
      if (!p) return "";
      return p.ids.join(" ") + (p.more ? " and " + fmtInt(p.more) + " more" : "");
    },
    unfold(gi) {
      const s = new Set(this.unfolded);
      if (s.has(gi)) s.delete(gi); else s.add(gi);
      this.unfolded = s;
    },
    // another column for a condition: its own range, no bound carried over
    setColumn(i, name) {
      this.conds = this.conds.map((c, k) => (k === i ? { ...c, col: name || "", min: null, max: null } : c));
      this.reload(0);
    },
    // another part of the grid: other rows, the highlight and the filter go
    setPart(value) {
      if (this.selected.size) this.clearSelection();
      this.unfolded = new Set();
      this.part = value || "";
      this.only = false;
      this.resetFilters();
    },
    // a bound left at the column's range is no bound (a NaN row stays)
    setBound(i, which, v) {
      const [lo, hi] = this.rangeOf(this.conds[i]);
      const edge = which === "min" ? lo : hi;
      const same = v !== null && edge !== null
        && Math.abs(v - edge) <= 1e-9 * Math.max(1, Math.abs(edge));
      const b = v === null || same ? null : v;
      this.conds = this.conds.map((c, k) => (k === i ? { ...c, [which]: b } : c));
      this.reload(0);
    },
    page(dir) {
      this.reload(Math.max(0, (this.values.offset || 0) + dir * PAGE));
    },
    // pressing a row toggles it and starts a sweep: every row from the first
    // to the one under the pointer gets the SAME action (add / remove) — a
    // range, not the rows the pointer happened to enter: a fast sweep
    // skipped some (the PO, 21/10); going back gives the rows back. The
    // highlight is sent once, on release
    dragStart(idx) {
      if (!this.lights) return;
      if (this.single) {
        this.selected = this.selected.has(idx) && this.selected.size === 1 ? new Set() : new Set([idx]);
        this.$emit("highlight", [...this.selected]);
        return;
      }
      this.dragBase = new Set(this.selected);
      this.dragMode = this.dragBase.has(idx) ? "remove" : "add";
      this.dragFrom = this.rowPos(idx);
      this.sweepTo(idx);
      window.addEventListener("pointerup", this.dragEnd, { once: true });
    },
    dragOver(idx) {
      if (this.dragMode) this.sweepTo(idx);
    },
    rowPos(gi) {
      return ((this.values && this.values.rows) || []).findIndex((r) => r[0] === gi);
    },
    sweepTo(idx) {
      const rows = (this.values && this.values.rows) || [];
      const to = this.rowPos(idx);
      if (to < 0 || this.dragFrom < 0) return;
      const s = new Set(this.dragBase);
      for (let k = Math.min(this.dragFrom, to); k <= Math.max(this.dragFrom, to); k++) {
        if (this.dragMode === "add") s.add(rows[k][0]); else s.delete(rows[k][0]);
      }
      this.selected = s;
    },
    dragEnd() {
      if (!this.dragMode) return;
      this.dragMode = "";
      this.$emit("highlight", [...this.selected]);
    },
    // a log's sample under the pointer, told to the host (lit in blue in the
    // views and the log view, as the log view's cursor is), none once the
    // pointer leaves the table: once it changes, at most every HOVER_MS
    hoverRow(r) {
      const at = (this.values && this.values.columns || []).indexOf("MD");
      const md = r && this.single && at >= 0 && typeof r[at] === "number" ? r[at] : null;
      const next = md == null ? null : { row: r[0], md };
      const key = JSON.stringify(next);
      if (key === this.hoverKey) return;
      this.hoverKey = key;
      this.hoverNext = next;
      if (this.hoverTimer) return;
      this.hoverTimer = setTimeout(() => {
        this.hoverTimer = 0;
        this.$emit("hover", this.hoverNext);
      }, HOVER_MS);
    },
    clearSelection() {
      this.selected = new Set();
      this.$emit("highlight", []);
    },
    // the highlight stays after a Keep or a Remove: Clear lets go of it
    extract(mode) {
      this.$emit("extract", mode);
    },
    fmtInt,
    colStyle(key) {
      const w = this.colW[key];
      return w ? { width: w + "px", minWidth: w + "px", maxWidth: w + "px" } : null;
    },
    // the right edge of a column's title dragged: its width, kept while the card lives
    gripDown(e, key) {
      const from = e.target.closest("th").getBoundingClientRect().width;
      const start = e.clientX;
      const move = (m) => { this.colW = { ...this.colW, [key]: Math.max(24, Math.round(from + m.clientX - start)) }; };
      const up = () => {
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", up);
      };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", up);
    },
    gripReset(key) {
      const kept = { ...this.colW };
      delete kept[key];
      this.colW = kept;
    },
    // a column of places under the name the page gives it (Easting (m),
    // MD from kelly bushing (m)), any other under its own
    axis(c) {
      return ((this.values || {}).labels || {})[c] || c;
    },
    // an integer value is a code or an index, written in full; a measured
    // value follows the shared rule of _shared/numfmt
    // a coordinate keeps its decimals (up to 3): -3002.5 is not -3 003
    fmt(v, column) {
      const n = Number(v);
      if (typeof v === "number" && ["X", "Y", "Z", "MD", "Elevation", "Time"].includes(column)) {
        return String(Math.round(n * 1000) / 1000);
      }
      return typeof v === "number" && Number.isInteger(n) ? String(n) : fmtNum(v);
    },
  },
};
</script>

<style>
@import "../../../_shared/panel.css";
</style>

<style scoped>
.fap { font-family: system-ui, sans-serif; font-size: 13px; padding: 8px; display: flex; flex-direction: column; gap: 10px; height: 100%; box-sizing: border-box; min-height: 0; }
.fap-section { display: flex; flex-direction: column; gap: 4px; flex: 0 0 auto; min-height: 0; }
.fap-grow { flex: 1 1 auto; }
.fap-hint { color: #999; font-size: 11px; font-style: italic; }
.fap-map { display: flex; flex-direction: column; min-height: 0; flex: 1 1 auto; gap: 4px; }
.fap-map-head { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.fap-map-wrap { flex: 1 1 auto; min-height: 0; overflow: auto; }
.fap-mapt { border-collapse: separate; border-spacing: 1px; font-size: 10px; font-variant-numeric: tabular-nums; }
.fap-mapt th { position: sticky; background: #f5f5f5; font-weight: 600; padding: 0 3px; z-index: 1; }
.fap-mapt thead th { top: 0; }
.fap-mapt tbody th { left: 0; }
.fap-map-corner { left: 0; z-index: 2; }
.fap-mapc { min-width: 34px; height: 17px; padding: 0 2px; text-align: right; }
.fap-map-edit { cursor: pointer; }
.fap-map-edit:hover { outline: 2px solid var(--fp-accent, #00436d); outline-offset: -2px; }
.fap-muted { color: #999; font-size: 11px; font-weight: normal; }
/* the head line: what the rows are read on at the left, the count and the
   export at the right */
.fap-top { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; flex: 0 0 auto; min-height: 24px; }
.fap-gap { flex: 1 1 auto; }
/* the support of a property, in the accent */
.fap-on { display: inline-flex; align-items: center; gap: 8px; padding: 3px 6px; border-radius: 3px; background: var(--fp-accent-soft, #e3eef6); }
.fap-on-label { font-size: 11px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: var(--fp-accent, #00436d); }
.fap-part { min-width: 12rem; max-width: 100%; border-color: var(--fp-accent, #00436d); font-weight: 600; color: var(--fp-accent, #00436d); }
.fap-table-wrap { flex: 1 1 auto; min-height: 100px; overflow: auto; border: 1px solid #e0e6ee; border-radius: 3px; }
/* each column as wide as what it holds: stretched over the card, an id's stood far from its values */
.fap-table { border-collapse: collapse; font-size: 11px; }
.fap-table th { position: sticky; top: 0; background: #f5f7fa; text-align: left; padding: 3px 6px; border-bottom: 1px solid #e0e6ee; white-space: nowrap; }
.fap-table td { padding: 2px 6px; border-bottom: 1px solid #f0f0f0; white-space: nowrap; }
/* a column narrowed by its grip cuts what it holds */
.fap-table th, .fap-table td { overflow: hidden; text-overflow: ellipsis; }
.fap-grip { position: absolute; top: 0; right: 0; width: 6px; height: 100%; cursor: col-resize; }
.fap-grip:hover { background: var(--fp-accent, #00436d); opacity: 0.35; }
.fap-table td.fap-num { text-align: right; font-family: ui-monospace, Consolas, monospace; }
/* a column of numbers is right-aligned: its title too, over its digits (the PO, 28/10) */
.fap-table th.fap-num { text-align: right; }
/* the column coloring the view: the F2I green, its header underlined */
.fap-table th.fap-eyed { color: var(--fp-f2i-ink, #5c8a0f); box-shadow: inset 0 -2px 0 var(--fp-ic-f2i, #8FC31F); }
.fap-table td.fap-eyed { background: rgba(143, 195, 31, 0.12); font-weight: 600; }
/* a cell's points: the first ids, ▸ unfolds their X Y Z beneath the row */
.fap-table td.fap-pts { font-family: ui-monospace, Consolas, monospace; color: #555; max-width: 14rem; overflow: hidden; text-overflow: ellipsis; }
.fap-chev { margin-right: 4px; }
.fap-table tbody tr.fap-sub { cursor: default; }
.fap-table tbody tr.fap-sub:hover { background: none; }
.fap-table tbody tr.fap-sub > td { padding: 2px 6px 6px 24px; background: #fafbfc; }
.fap-subtable { border-collapse: collapse; font-size: 11px; }
.fap-subtable th { position: static; background: none; padding: 1px 8px 1px 0; border-bottom: 1px solid #e0e6ee; }
.fap-subtable td { padding: 1px 8px 1px 0; border-bottom: 0; }
.fap-table tbody tr { cursor: pointer; user-select: none; }
.fap-table tbody tr:hover { background: #f0f7ff; }
.fap-table tbody tr.fap-still { cursor: default; }
.fap-table tbody tr.fap-sel { background: #ffe0f0; color: #ad1457; font-weight: 600; }
.fap-table tbody tr.fap-sel td.fap-eyed { background: transparent; }
/* a cell the 3D selection tool holds: marked, under the table's own pick */
.fap-table tbody tr.fap-picked:not(.fap-sel) { background: #fff3cd; }
/* the row the log view's pointer stands on: blue; a row held stays in the selection's magenta (.fap-sel) */
.fap-table tbody tr.fap-cursor { background: #e3efff; color: #1565c0; font-weight: 600; }
.fap-table tbody tr.fap-sel.fap-cursor { background: #ffe0f0; color: #ad1457; }
.fap-table tbody tr.fap-picked td:first-child { box-shadow: inset 3px 0 0 #e0a800; }
.fap-only { font-size: 11px; flex: 0 0 auto; }
.fap-read { margin-left: 6px; }
.fap-filter { display: flex; align-items: center; gap: 4px; flex: 0 0 auto; }
.fap-fcol { max-width: 9rem; }
/* the join of a condition to the one above, or the word on the first row:
   one width, the fields of every row in line */
.fap-op, .fap-op-w { min-width: 2.6rem; text-align: center; }
.fap-hl { color: #ad1457; border-color: #ad1457; }
.fap-pager { display: flex; align-items: center; justify-content: center; gap: 10px; font-size: 11px; color: #555; flex: 0 0 auto; }
</style>
