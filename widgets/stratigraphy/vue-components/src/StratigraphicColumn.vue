<template>
  <!-- The column the file declares, with its own bar — title, rank,
       summary —, filters and notes (the time-depth model is a card of the
       3D view since 03/11). -->
  <div class="fst">
    <!-- One rank of the column is read at a time; the target chip names it when
         the file declares only one, the select picks it when it declares more. -->
    <fp-panel class="fst-column" title="Stratigraphy"
              title-tip="The stratigraphic column of the loaded data, as the file states it: nothing added, every hole shown"
              :target="hasColumns && columns.length === 1 ? current.title : null"
              :summary="summary" :scroll="false">
      <template v-if="hasColumns && columns.length > 1" #controls>
        <fp-select :model-value="current.uuid" :options="columnOptions"
                   title="Which rank of the column to read — a file can declare several"
                   @update:model-value="$emit('select', $event)" />
      </template>
      <template v-if="hasColumns" #subbar>
        <!-- the levels sort the units by what their own name says; a rank the
             file dates is read by its ages, not by levels -->
        <fp-seg v-if="!dated" :model-value="detail" :options="levels"
                title="Which units to draw, by what their name says they are" @update:model-value="detail = $event" />
        <input class="fp-input fst-search" :value="query" placeholder="Filter by name"
               title="Keep only the units whose name contains these letters"
               @input="query = $event.target.value" />
      </template>
      <template v-if="hasColumns && (generatedCount || undatedNote)" #notes>
        <fp-note v-if="generatedCount" severity="warning"
                 :text="generatedCount + ' unit color(s) are generated: these units carry no color in the file, and the shades are chosen so the column stays readable.'" />
        <fp-note v-if="undatedNote" severity="warning" :text="undatedNote" />
      </template>

    <!-- The empty state must not assert a cause the app has not established:
         a file with no column, a failed parse, an unsupported package and an
         ETP source all end here, and only the server knows which, so its
         note is the why. -->
    <fp-empty v-if="!hasColumns"
              shows="The stratigraphic column of the loaded data, as the file states it."
              gesture="Open a package that declares one with “Import data” in the top bar."
              :why="why" />

    <div v-else class="fst-chart">
      <div class="fst-hdr" :style="{ width: totalW + 'px' }">
        <div class="fst-h fst-ma-w" :title="dated ? 'Age in millions of years, as the file states it; older downward' : 'The order the file lists the units in; the file states no age'">
          {{ dated ? "Ma" : "Order" }} &darr;
        </div>
        <template v-for="c in cols">
          <div v-if="c.gap" :key="c.key" class="fst-gap"></div>
          <template v-else>
            <div v-for="h in c.heads" :key="c.key + h.label" class="fst-h"
                 :class="{ 'fst-h-ics': c.side === 'ics' }" :style="{ width: h.w + 'px' }" :title="c.tip">
              {{ h.label }}
            </div>
          </template>
        </template>
      </div>

      <!-- Laid out as a table, as ORES draws it: a unit runs from its top to
           its base, and stretches to the right over every lane that holds
           nothing beside it; a row where the file states nothing is a
           HATCHED cell, never a blank (the PO's manager: everything true, no
           hole). -->
      <div class="fst-body" :style="{ height: bodyH + 'px', width: totalW + 'px' }">
        <div class="fst-ma-col fst-ma-w"></div>

        <template v-for="c in cols">
          <div v-if="c.gap" :key="c.key" class="fst-gap"></div>
          <div v-else :key="c.key" class="fst-col" :style="{ width: c.w + 'px' }">
            <div v-for="b in c.blocks" :key="b.key" class="fst-blk"
                 :class="['fst-' + b.kind,
                          b.kind === 'unit' && c.wide ? 'fst-blk-rock' : '',
                          b.kind === 'unit' && b.e.name === highlight ? 'fst-on' : '']"
                 :style="b.style" :title="b.tip"
                 @click="b.kind === 'unit' && $emit('pick', b.e.name)">
              <template v-if="b.kind === 'unit' && c.wide && b.main">
                <span class="fst-lbl">{{ b.e.name }}</span>
                <span v-if="!dated" class="fst-kind" :class="'fst-k-' + b.e.kind"
                      :title="kindTip(b.e.kind)">{{ short(b.e.kind) }}</span>
              </template>
              <span v-else-if="b.kind === 'hole' && b.h >= 14" class="fst-hole-lbl">not defined</span>
              <span v-else-if="b.kind === 'none'" class="fst-vert fst-none-lbl">{{ b.label }}</span>
              <!-- a name across: the ICS epochs and stages, whose rows are too
                   short for a name written up the block -->
              <span v-else-if="b.horiz && b.h >= 11" class="fst-hlbl">{{ b.label }}</span>
              <!-- a name up the block, on EVERY part of it tall enough: a unit
                   stretched to the right is cut into parts, and a part with
                   no name reads as an empty cell -->
              <span v-else-if="!b.horiz && b.kind !== 'hole' && !(b.kind === 'unit' && c.wide) && b.h > 34 && b.w >= 18"
                    class="fst-vert">{{ b.label }}</span>
            </div>
          </div>
        </template>

        <!-- a rule right across at every age the chart draws, so an age reads
             as a level in the whole column; the file's own ages in full ink,
             the ages only the ICS reference brings in a lighter one -->
        <div v-for="r in rules" :key="'r' + r.y" class="fst-rule"
             :class="{ 'fst-rule-ics': !r.file }" :style="{ top: r.y + 'px' }">
          <span class="fst-ma" :title="r.file ? 'An age the file states' : 'An age of the ICS reference only'">{{ r.label }}</span>
        </div>
      </div>
    </div>
    </fp-panel>

  </div>
</template>

<script>
const PX = 13;            // height of one unit-index step (a rank the file does not date), in px
const ROW = 22;           // height of one interval between two ages (a dated rank), in px
const LANE = 26;          // width of a lane holding a vertical name, in px
// widths of the ICS lanes: the period's name is written up its block, the
// epoch's and the stage's across it (their rows are too short otherwise)
const ICS_WIDTHS = [34, 96, 108];
const WIDE_LANE = 190;    // width of a lane holding a horizontal name, in px
// header labels on two lines (pre-line): "ICS", then the rank
const ICS_RANKS = [["period", "ICS\nperiod"], ["epoch", "ICS\nepoch"], ["stage", "ICS\nstage"]];

/* Lanes for a set of spans so that none overlaps another. A span runs in
   steps from `t` to `b` (excluded). Two passes, in this order and for
   different reasons:
   1. TRIM (a rank the file does not date only). A partial overlap is
      almost always one contact written twice: the base of the upper unit
      and the top of the lower one are the same level, listed in an
      arbitrary order. Clip the upper unit to where the lower one starts.
      Never on ages the file states: there an overlap is the file's, shown.
   2. LANE. Whatever still collides gets its own lane rather than being
      hidden: an overlap the data really contains must stay visible. */
function pack(spans, trim) {
  const xs = spans.slice().sort((p, q) => p.t - q.t || p.b - q.b);
  if (trim) {
    for (let i = 0; i < xs.length; i += 1) {
      for (let j = i + 1; j < xs.length; j += 1) {
        if (xs[j].t >= xs[i].b) break;
        if (xs[j].b > xs[i].b && xs[j].t > xs[i].t) { xs[i].b = xs[j].t; break; }
      }
    }
  }
  const ends = [];
  for (const x of xs) {
    let k = 0;
    while (k < ends.length && ends[k] > x.t) k += 1;
    if (k === ends.length) ends.push(0);
    ends[k] = Math.max(x.b, x.t + 1);
    x.lane = k;
  }
  return { spans: xs, lanes: Math.max(1, ends.length) };
}

/* The blocks of one column of `lanes` lanes, rows `from` to `to`, as ORES
   lays its table out: each span on its lane, STRETCHED to the right over
   every lane that holds nothing beside it on that row (a cell with no finer
   subdivision runs to the last column); a span whose right side changes
   from row to row is cut into blocks, its name on the tallest. A row the
   column holds nothing on becomes a hole across its whole width (`hole`
   names it). */
function layout(spans, lanes, from, to, hole) {
  const rows = Math.max(0, to - from);
  const occ = Array.from({ length: rows }, () => []);
  for (const x of spans) {
    for (let r = Math.max(x.t, from); r < Math.min(x.b, to); r += 1) occ[r - from].push(x.lane);
  }
  const out = [];
  for (const x of spans) {
    if (x.b <= x.t) {        // an instant: a hairline on its lane
      out.push({ ...x, lane: x.lane, end: x.lane + 1, main: true });
      continue;
    }
    const segs = [];
    for (let r = Math.max(x.t, from); r < Math.min(x.b, to); r += 1) {
      const next = occ[r - from].filter((l) => l > x.lane);
      const end = next.length ? Math.min(...next) : lanes;
      const last = segs[segs.length - 1];
      if (last && last.end === end && last.b === r) last.b = r + 1;
      else segs.push({ t: r, b: r + 1, end });
    }
    let tallest = 0;
    segs.forEach((s, i) => { if (s.b - s.t > segs[tallest].b - segs[tallest].t) tallest = i; });
    // the blocks of one span read as ONE cell: no rule between them
    segs.forEach((s, i) => out.push({ ...x, key: x.key + "#" + i, t: s.t, b: s.b, end: s.end, main: i === tallest,
                                      openTop: i > 0, openBottom: i < segs.length - 1 }));
  }
  let start = -1;
  for (let r = from; r <= to; r += 1) {
    const empty = r < to && !occ[r - from].length;
    if (empty && start < 0) start = r;
    if (!empty && start >= 0) {
      out.push({ kind: "hole", key: "h" + start, t: start, b: r, lane: 0, end: lanes, tip: hole(start, r) });
      start = -1;
    }
  }
  return out;
}

// an age as the file writes it, without trailing noise: 0.00425, 2.58, 145
function ma(v) {
  return String(Number(Number(v).toPrecision(5)));
}

import FpEmpty from "../../../_shared/components/FpEmpty.vue";
import FpNote from "../../../_shared/components/FpNote.vue";
import FpPanel from "../../../_shared/components/FpPanel.vue";
import FpSeg from "../../../_shared/components/FpSeg.vue";
import FpSelect from "../../../_shared/components/FpSelect.vue";

// What a file without a column most often means. Appended to the server's
// note when that note reports a plain absence, never to a parse failure.
const NONE_IS_NORMAL = "A file may legitimately carry none — RESQML keeps"
  + " stratigraphy in the interpretation layer, so geometry-only data sets"
  + " have no column.";

export default {
  name: "StratigraphicColumn",
  components: { FpEmpty, FpNote, FpPanel, FpSeg, FpSelect },
  props: {
    columns: { type: Array, default: () => [] },
    selected: { type: String, default: "" },
    highlight: { type: String, default: "" },
    note: { type: String, default: "" },
  },
  emits: ["select", "pick"],
  data() {
    return {
      // everything the file lists is shown by default: an entry left
      // unclassified must never be hidden by a classification
      detail: "all",
      query: "",
      levels: [
        { value: "group", label: "Groups", title: "Groups only: the units whose name says GP or GROUP" },
        { value: "named", label: "+ Formations", title: "Formations and members too: their name says FM, FORMATION, MB or MEMBER" },
        { value: "all", label: "All", title: "Also the units whose name says neither group, formation nor member" },
      ],
    };
  },
  computed: {
    hasColumns() {
      return (this.columns || []).length > 0;
    },
    current() {
      const cols = this.columns || [];
      return cols.find((c) => c.uuid === this.selected) || cols[0] || {};
    },
    // the file dates this rank: it is laid on the file's ages
    dated() {
      return !!this.current.dated;
    },
    columnOptions() {
      return (this.columns || []).map((c) => ({
        value: c.uuid, label: c.title + (c.dated ? " — dated" : ""),
        title: "Read the rank " + c.title + (c.dated ? ", which the file dates" : ""),
      }));
    },
    entities() {
      return this.current.entities || [];
    },
    keep() {
      const q = this.query.trim().toLowerCase();
      return (e) => !q || e.name.toLowerCase().includes(q);
    },
    datedEntities() {
      return this.entities.filter((e) => e.younger_ma != null && e.older_ma != null);
    },
    // DATED: the ages the chart draws, the file's and the ICS reference's
    // inside the file's range, sorted; one row per interval between two
    ages() {
      if (!this.dated) return [];
      const file = this.datedEntities;
      if (!file.length) return [];
      const lo = Math.min(...file.map((e) => e.younger_ma));
      const hi = Math.max(...file.map((e) => e.older_ma));
      const vals = new Map();
      const add = (v, isFile) => {
        const k = Number(Number(v).toPrecision(9));
        vals.set(k, (vals.get(k) || false) || isFile);
      };
      for (const e of file) { add(e.younger_ma, true); add(e.older_ma, true); }
      for (const u of ((this.current.ics || {}).units || [])) {
        if (u.top_ma > lo && u.top_ma < hi) add(u.top_ma, false);
        if (u.base_ma > lo && u.base_ma < hi) add(u.base_ma, false);
      }
      return [...vals.entries()].map(([v, isFile]) => ({ v, file: isFile })).sort((a, b) => a.v - b.v);
    },
    rowOf() {
      const idx = new Map(this.ages.map((a, i) => [a.v, i]));
      return (v) => {
        const k = Number(Number(v).toPrecision(9));
        if (idx.has(k)) return idx.get(k);
        // an ICS bound outside the file's range: clamped to its edge
        return v <= this.ages[0].v ? 0 : this.ages.length - 1;
      };
    },
    step() {
      return this.dated ? ROW : PX;
    },
    // the rows the chart has: intervals between ages, or unit positions
    rowCount() {
      if (this.dated) return Math.max(0, this.ages.length - 1);
      return this.entities.reduce((m, e) => Math.max(m, (e.base || 0) + 1), 0);
    },
    bodyH() {
      return Math.max(1, this.rowCount) * this.step;
    },
    cols() {
      const out = [this.icsCol, { key: "gap", gap: true, w: 12 }];
      return out.concat(this.dated ? this.datedCols : this.orderCols);
    },
    // The ICS chart, three lanes (period, epoch, stage): beside a rank the
    // file dates, the chart's units over the same ages, in their official
    // colours, laid out with no hole (a unit with no finer one beside it
    // runs into the next lane). Beside a rank the file does NOT date, the
    // three lanes stay EMPTY: nothing was matched (the PO, 2026-10-15).
    icsCol() {
      const ics = this.current.ics || {};
      const chart = ics.chart || "";
      const heads = ICS_RANKS.map(([, label], i) => ({ label, w: ICS_WIDTHS[i] }));
      const w = ICS_WIDTHS.reduce((n, x) => n + x, 0);
      const col = { key: "ics", side: "ics", heads, w, lanes: ICS_RANKS.length,
                    tip: this.dated
                      ? "The ICS chart " + chart + ", drawn as a reference over the ages the file states"
                      : "The file states no age: nothing is placed on the ICS chart" };
      if (!this.dated) {
        col.blocks = [this.block({ kind: "none", key: "none", t: 0, b: this.rowCount, lane: 0, end: ICS_RANKS.length,
                                   main: true, label: "No age in the file: nothing placed on the ICS chart",
                                   tip: col.tip }, ICS_WIDTHS)];
        return col;
      }
      const spans = [];
      ICS_RANKS.forEach(([rank], lane) => {
        for (const u of (ics.units || []).filter((x) => x.rank === rank)) {
          spans.push({
            // the rank in the key: a unit may be its epoch's only stage (Pridoli)
            kind: "ics", key: "i" + lane + u.name, label: u.name, lane, color: u.color, horiz: lane > 0,
            t: this.rowOf(u.top_ma), b: this.rowOf(u.base_ma),
            tip: u.name + " (" + rank + "): " + ma(u.top_ma) + "–" + ma(u.base_ma) + " Ma — ICS chart "
              + chart + ", a reference beside the ages the file states, not read from the file",
          });
        }
      });
      col.blocks = layout(spans, ICS_RANKS.length, 0, this.rowCount,
        (t, b) => "The ICS chart has no unit here: " + ma(this.ages[t].v) + "–" + ma(this.ages[b].v) + " Ma")
        .map((x) => this.block(x, ICS_WIDTHS));
      return col;
    },
    // DATED: the file's units laid on the file's ages; a row no unit covers
    // is a hatched "not defined" hole
    datedCols() {
      const spans = this.datedEntities.filter(this.keep).map((e) => ({
        kind: "unit", key: "u" + e.name + e.top, e, label: e.name, color: e.color,
        t: this.rowOf(e.younger_ma), b: this.rowOf(e.older_ma),
        tip: e.name + "\n" + ma(e.younger_ma) + "–" + ma(e.older_ma) + " Ma, as the file states it"
          + (e.color_source === "generated" ? "\ncolour generated" : ""),
      }));
      const p = pack(spans, false);
      // a filter hides units, so the holes it would leave are its own: none drawn
      const filtered = !!this.query.trim();
      const blocks = layout(p.spans, p.lanes, 0, this.rowCount,
        (t, b) => "Not defined in the file: " + ma(this.ages[t].v) + "–" + ma(this.ages[b].v)
          + " Ma — no unit of this rank covers these ages")
        .filter((x) => !(filtered && x.kind === "hole"));
      const w = p.lanes * WIDE_LANE;
      return [{ key: "units", side: "file", wide: true, w, lanes: p.lanes,
                heads: [{ label: "Units (the file's ages)", w }],
                tip: "The units of this rank, laid on the ages the file states",
                blocks: blocks.map((x) => this.block(x, WIDE_LANE)) }];
    },
    // NOT DATED: the file's order, the units sorted into lanes by what their
    // own name says; in each lane, a position the lane states nothing at is
    // a hatched hole
    orderCols() {
      const filtered = !!this.query.trim();
      const build = (ents, key, label, wide, tip) => {
        const spans = ents.map((e) => ({
          kind: "unit", key: "u" + e.name + e.top, e, label: e.name, color: e.color, t: e.top, b: e.base + 1,
          tip: e.name + "\nno age in the file" + (e.color_source === "generated" ? "\ncolour generated" : ""),
        }));
        const p = pack(spans, true);
        const laneW = wide ? WIDE_LANE : LANE;
        const blocks = layout(p.spans, p.lanes, 0, this.rowCount,
          () => "Nothing stated here: no " + label.toLowerCase() + " of the file at these positions")
          .filter((x) => !(filtered && x.kind === "hole"));
        const w = p.lanes * laneW;
        return { key, side: "file", wide, w, lanes: p.lanes, heads: [{ label, w }], tip,
                 blocks: blocks.map((x) => this.block(x, laneW)) };
      };
      const out = [];
      const groups = this.entities.filter((e) => e.kind === "group" && this.keep(e));
      if (groups.length) out.push(build(groups, "grp", "Group", false, "The units whose name says GP or GROUP"));
      const wanted = this.detail === "group" ? [] : ["formation", "member"];
      const rocks = this.entities.filter((e) => wanted.includes(e.kind) && this.keep(e));
      if (rocks.length) out.push(build(rocks, "rock", "Rock unit", true, "The units whose name says FM, FORMATION, MB or MEMBER"));
      const others = this.detail === "all"
        ? this.entities.filter((e) => e.kind === "other" && this.keep(e)) : [];
      if (others.length) out.push(build(others, "other", "Unclassified", true, "The units whose name says neither group, formation nor member"));
      return out;
    },
    totalW() {
      // + 40: the gutter on the left
      return this.cols.reduce((n, c) => n + c.w, 0) + 40;
    },
    rules() {
      if (!this.dated) return [];
      return this.ages.map((a, i) => ({ y: i * ROW, label: ma(a.v), file: a.file }));
    },
    summary() {
      if (!this.hasColumns) return "";
      const n = this.entities.length;
      if (!this.dated) return n + " units · no age in the file · nothing placed on the ICS chart";
      const gaps = (this.current.age_gaps || []).length;
      const ics = (this.current.ics || {}).units || [];
      const n2 = this.datedEntities.length;
      return n2 + (n2 === 1 ? " unit" : " units") + " dated by the file · "
        + gaps + (gaps === 1 ? " hole" : " holes")
        + (ics.length ? " · ICS " + this.current.ics.chart + " as reference" : "");
    },
    undatedNote() {
      if (!this.dated) return "";
      const left = this.entities.filter((e) => e.younger_ma == null || e.older_ma == null);
      if (!left.length) return "";
      return left.length + " unit(s) of this rank carry no age in the file, so they are not drawn on the ages: "
        + left.map((e) => e.name).join(", ") + ".";
    },
    why() {
      const note = (this.note || "").trim();
      if (!note || /^No stratigraphic column/.test(note)) {
        return (note ? note + " " : "") + NONE_IS_NORMAL;
      }
      return note;
    },
    generatedCount() {
      return this.entities.filter((e) => e.color_source === "generated").length;
    },
  },
  methods: {
    // a laid-out span as the template draws it: its box in px
    // `laneW`: one width for every lane, or the width of each lane
    block(x, laneW) {
      const h = Math.max((x.b - x.t) * this.step, 3);
      const at = (lane) => (Array.isArray(laneW)
        ? laneW.slice(0, lane).reduce((n, v) => n + v, 0) : lane * laneW);
      const w = at(x.end) - at(x.lane);
      return {
        ...x, h, w,
        style: {
          top: x.t * this.step + "px", height: h + "px",
          left: at(x.lane) + "px", width: w + "px",
          background: x.kind === "unit" || x.kind === "ics" ? (x.color || "#ddd") : null,
          borderTopWidth: x.openTop ? "0" : null,
          borderBottomWidth: x.openBottom ? "0" : null,
        },
      };
    },
    short(kind) {
      return { group: "GP", formation: "Fm", member: "Mb" }[kind] || "·";
    },
    kindTip(kind) {
      return {
        group: "Group — its name says GP or GROUP",
        formation: "Formation — its name says FM or FORMATION",
        member: "Member — its name says MB or MEMBER",
      }[kind] || "Unclassified — its name says neither group, formation nor member";
    },
  },
};
</script>

<style>
@import "../../../_shared/panel.css";
</style>

<style scoped>
/* the panel: the column filling it */
.fst { display: flex; flex-direction: column; height: 100%; min-height: 0;
       font-family: var(--fp-font); font-size: var(--fp-size);
       background: var(--fp-bg); color: var(--fp-ink); }
.fst-column { flex: 1 1 0; height: auto; min-height: 0; }
.fst-search { flex: 1 1 60px; max-width: 220px; font-size: 12px; }

.fst-chart { flex: 1 1 auto; min-height: 0; overflow: auto; padding: 6px; }
.fst-hdr {
  display: flex; position: sticky; top: 0; z-index: 5;
  background: #fff; border-bottom: 1px solid #bbb;
}
.fst-h {
  font-size: 9px; font-weight: 700; text-transform: uppercase;
  color: #666; text-align: center; padding-bottom: 2px;
  box-sizing: border-box; flex: 0 0 auto; overflow: hidden;
}
.fst-h-ics { color: #6a4c93; white-space: pre-line; line-height: 1.15; }
.fst-ma-w { flex: 0 0 40px; width: 40px; box-sizing: border-box; }
.fst-gap { flex: 0 0 12px; width: 12px; }

.fst-body { display: flex; position: relative; align-items: stretch; }
/* Dotted rules between columns, drawn as ::after so they cost no layout
   width, and above the blocks so a colour cannot hide them. */
.fst-col::after, .fst-gap::after {
  content: ""; position: absolute; top: 0; bottom: 0; right: 0;
  border-right: 1px dotted #9e9e9e; pointer-events: none; z-index: 4;
}
/* the reference / file divide: a stronger rule */
.fst-gap { position: relative; }
.fst-gap::after { right: 50%; border-right: 1px dashed #7e57c2; }
.fst-h { border-right: 1px dotted #9e9e9e; }
.fst-col { position: relative; box-sizing: border-box; flex: 0 0 auto; }
.fst-ma-col { border-right: 2px solid #4a148c; flex: 0 0 auto; }
.fst-blk {
  position: absolute;
  border: 1px solid rgba(0, 0, 0, 0.3);
  box-sizing: border-box; overflow: hidden; cursor: pointer;
  display: flex; align-items: center; justify-content: center;
}
.fst-blk:hover { outline: 2px solid var(--fp-accent); outline-offset: -2px; z-index: 2; }
.fst-on { outline: 2px solid #d81b60; outline-offset: -2px; z-index: 2; }
.fst-blk-rock { justify-content: space-between; padding: 0 5px; gap: 5px; }
/* the ICS reference: the chart's official colours, never a unit's */
.fst-ics { border-color: rgba(0, 0, 0, 0.25); cursor: default; }
.fst-ics:hover { outline: none; }
/* a rank the file does not date: the ICS lanes stay empty, and say why */
.fst-none { background: #f6f3fa; border: 1px dashed #c5b8dc; cursor: default; }
.fst-none:hover { outline: none; }
.fst-none-lbl { font-weight: 400; font-style: italic; color: #7e6b9e; }
/* a hole: hatched, so it reads as "the file says nothing here", never as a unit */
.fst-hole {
  background: repeating-linear-gradient(45deg, #eceff1 0 4px, #cfd8dc 4px 8px);
  border: 1px dashed #90a4ae; cursor: help; z-index: 1;
}
.fst-hole:hover { outline: none; }
.fst-hole-lbl {
  font-size: 9px; font-style: italic; color: #455a64;
  background: rgba(255, 255, 255, 0.8); padding: 0 3px; border-radius: 2px;
  white-space: nowrap; pointer-events: none;
}
.fst-vert {
  writing-mode: vertical-rl; transform: rotate(180deg);
  font-size: 9px; font-weight: 600; white-space: nowrap;
  overflow: hidden; max-height: 100%; pointer-events: none;
  text-shadow: 0 0 3px rgba(255, 255, 255, 0.9);
}
.fst-hlbl {
  font-size: 9px; font-weight: 600; white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; max-width: 100%; padding: 0 3px; pointer-events: none;
  text-shadow: 0 0 3px rgba(255, 255, 255, 0.9);
}
.fst-lbl {
  flex: 1 1 auto; font-size: 11px; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap;
  text-shadow: 0 0 3px rgba(255, 255, 255, 0.9);
}
.fst-kind {
  font-size: 9px; font-weight: 700; white-space: nowrap;
  border-radius: 2px; padding: 0 3px;
  background: rgba(255, 255, 255, 0.72); color: #444;
}
.fst-k-formation { color: #1b5e20; }
.fst-k-member { color: #33691e; }
/* drawn ON TOP of the blocks on purpose: an age that stops at the margin
   cannot be read against a unit halfway across the chart */
.fst-rule {
  position: absolute; left: 0; right: 0; z-index: 3;
  border-top: 1px solid rgba(74, 20, 140, 0.45);
  pointer-events: none;
}
.fst-rule-ics { border-top: 1px dotted rgba(106, 76, 147, 0.35); }
.fst-ma {
  position: absolute; left: 0; top: -6px; width: 36px; text-align: right;
  font-size: 9px; font-variant-numeric: tabular-nums; color: #4a148c;
  background: rgba(255, 255, 255, 0.85); line-height: 1;
}
.fst-rule-ics .fst-ma { color: #9575cd; }
</style>
