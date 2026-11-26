<template>
  <fp-panel class="fcalc" title="Calculator"
            title-tip="A derived property: a formula over the properties of one grid, kept as a recipe and recomputed when its inputs change">
    <!-- the recipe's identity (grid, name, unit, kind); the verb sits at the right -->
    <template #controls>
      <fp-select class="fcalc-grow" :model-value="rep || ''" :options="repOptions" placeholder="Grid" mandatory
                 title="The grid the formula runs on" @update:model-value="$emit('set-rep', $event || '')" />
      <input class="fp-input fcalc-name" :value="name" placeholder="Name"
             title="Name of the derived property"
             @input="$emit('set-name', $event.target.value)" />
      <input class="fp-input fcalc-uom" :value="uom" placeholder="Unit"
             title="Unit of measure of the result" @input="$emit('set-uom', $event.target.value)" />
      <fp-select class="fcalc-kind" :model-value="kind" :options="KINDS"
                 title="Continuous values, or discrete categories" @update:model-value="$emit('set-kind', $event)" />
    </template>
    <template #actions>
      <fp-btn variant="primary" :label="editing ? 'Update' : 'Create'" :disabled="!canCreate" :title="createTitle"
              @click="$emit('create')" />
      <fp-btn v-if="editing" label="Cancel" title="Leave the recipe as it was" @click="$emit('cancel-edit')" />
    </template>

    <!-- what the formula did not do, named with the next step -->
    <template v-if="status && status.error" #notes>
      <fp-note severity="error" :text="status.error" next="correct the formula, the properties it may name are listed under Properties" />
    </template>

    <div class="fcalc-body">
      <!-- PROPERTY CHIPS: a chip shows the property's name exactly as
           written, which a button label in Title case would not; its +
           appends the identifier to the formula, so nothing is typed by hand -->
      <div class="fcalc-row fcalc-wrap">
        <span class="fcalc-muted">Properties:</span>
        <fp-chip v-for="p in propChips" :key="p.ident" variant="line" class="fcalc-ident"
                 :class="{ 'fcalc-derived': p.derived }" :text="p.label"
                 :title="(p.uom ? p.label + ' in ' + p.uom : p.label) + (p.derived ? ' — a derived property' : '')">
          <template #after>
            <fp-btn variant="bare" label="+" :title="'Put ' + p.ident + ' in the formula'" @click="$emit('append', p.ident)" />
          </template>
        </fp-chip>
        <span v-if="!propChips.length" class="fp-sum">
          Tick a grid property in the tree first.
        </span>
      </div>

      <!-- UNCERTAINTY: per-cell P10 / P50 / P90 across realizations. Not the
           same percentiles as the preview's "p10 cells" / "p90 cells" below,
           which run over the cells of one result: the row says so. -->
      <div v-if="mrProps.length" class="fcalc-row fcalc-wrap">
        <span class="fcalc-muted">Uncertainty:</span>
        <fp-select class="fcalc-grow" :model-value="mrPick || ''" :options="mrOptions"
                   placeholder="Multi-realization property" mandatory
                   title="The multi-realization property whose spread is read"
                   @update:model-value="$emit('set-mr-pick', $event || '')" />
        <fp-btn label="Create P10 / P50 / P90" :disabled="!mrPick"
                :title="mrPick ? 'Per-cell percentiles across realizations (exceedance: P90 = low case)' : 'Pick a multi-realization property first'"
                @click="$emit('make-percentiles')" />
        <span class="fcalc-muted fcalc-convention">
          Per cell, across the realizations, in the reserves convention: P90 is the low case, P10 the high case.
        </span>
      </div>

      <!-- DIFFERENCE A − B: two properties, or one property at two
           realizations / time steps (a pinned identifier: NAME__r3, NAME__t5);
           an unpinned side follows the view's own slider -->
      <div v-if="propChips.length" class="fcalc-row fcalc-wrap fcalc-diff">
        <span class="fcalc-muted" title="A − B as a derived property — between two properties, two realizations or two time steps">A − B:</span>
        <fp-select class="fcalc-pick" :model-value="diffA" :options="chipOptions('a')" placeholder="A" mandatory
                   title="A: the property the difference starts from" @update:model-value="diffA = $event || ''" />
        <fp-select v-if="axesOf(diffA).reals.length" class="fcalc-pin" :model-value="diffAr"
                   :options="pinOptions(axesOf(diffA).reals, 'real: slider', 'ar')"
                   title="Realization of A (the view's slider when none is pinned)" @update:model-value="diffAr = $event || ''" />
        <fp-select v-if="axesOf(diffA).ts.length" class="fcalc-pin" :model-value="diffAt"
                   :options="pinOptions(axesOf(diffA).ts, 'time: slider', 'at')"
                   title="Time step of A (the view's time when none is pinned)" @update:model-value="diffAt = $event || ''" />
        <span class="fcalc-minus">−</span>
        <fp-select class="fcalc-pick" :model-value="diffB" :options="chipOptions('b')" placeholder="B" mandatory
                   title="B: the property taken away" @update:model-value="diffB = $event || ''" />
        <fp-select v-if="axesOf(diffB).reals.length" class="fcalc-pin" :model-value="diffBr"
                   :options="pinOptions(axesOf(diffB).reals, 'real: slider', 'br')"
                   title="Realization of B (the view's slider when none is pinned)" @update:model-value="diffBr = $event || ''" />
        <fp-select v-if="axesOf(diffB).ts.length" class="fcalc-pin" :model-value="diffBt"
                   :options="pinOptions(axesOf(diffB).ts, 'time: slider', 'bt')"
                   title="Time step of B (the view's time when none is pinned)" @update:model-value="diffBt = $event || ''" />
        <fp-btn label="Create A − B" :disabled="!canDiff"
                :title="canDiff ? 'Create the derived property A − B' : !diffA || !diffB ? 'Pick A and B first' : 'A and B are the same reading: pin another realization or time on one of them'"
                @click="makeDiff" />
      </div>

      <!-- INSERT (functions and operators) and TEMPLATES: two selects used as
           verbs, each going back to its placeholder once the pick has landed
           in the formula -->
      <div class="fcalc-row fcalc-wrap">
        <fp-select class="fcalc-tpl" v-model="insertPick" :options="INSERTS" placeholder="Insert" mandatory
                   title="A function or an operator, appended to the formula" @update:model-value="onInsert($event)" />
        <fp-select class="fcalc-tpl" v-model="templatePick" :options="templateOptions" placeholder="Templates" mandatory
                   title="Start from a ready-made formula, written on the first property" @update:model-value="onTemplate($event)" />
      </div>

      <!-- FORMULA -->
      <textarea class="fcalc-formula" rows="2" :value="expr"
                placeholder="e.g. log10(PERMX)   ·   PORO * NTG"
                title="The formula: property identifiers, numbers, the functions and operators of the Insert list"
                @input="$emit('set-expr', $event.target.value)"></textarea>

      <!-- VALIDATION: what the formula reads; an error shows in the notes band above -->
      <div v-if="status && status.ok" class="fcalc-ok">{{ status.summary }}</div>

      <!-- LIVE PREVIEW: statistics of the unsaved formula, evaluated at full
           resolution by the host -->
      <div v-if="preview && preview.n" class="fcalc-row fcalc-wrap fcalc-stats">
        <span v-for="s in statChips" :key="s.k" class="fcalc-stat" :title="s.title">
          <b>{{ s.k }}</b> {{ s.v }}
        </span>
      </div>

      <!-- EXISTING RECIPES OF THIS GRID, each with its shortcuts -->
      <div class="fcalc-defs">
        <div class="fcalc-muted fcalc-defs-title">Derived properties of this grid</div>
        <div v-for="d in defsHere" :key="d.path" class="fcalc-def">
          <fp-chip variant="line" class="fcalc-derived" :text="'ƒ ' + d.name" :title="'The derived property ' + d.name" />
          <span class="fcalc-expr" :title="d.expression">{{ d.expression }}</span>
          <span class="fcalc-muted">{{ d.uom }}</span>
          <fp-chip v-if="d.stale || d.error" sm variant="warn" :text="d.stale ? 'grid unloaded' : 'not computed'"
                   :title="d.stale ? 'Its grid is unloaded: the recipe is kept and recomputes when the grid is read again' : d.error" />
          <fp-btn variant="bare" label="▤" title="Statistics: add this property to the Statistics view"
                  @click="$emit('act', ['stats', d.path])" />
          <fp-btn variant="bare" label="✎" title="Edit: load this recipe above"
                  @click="$emit('act', ['edit', d.path])" />
          <fp-btn variant="bare" class="fcalc-danger" label="×" title="Delete this derived property"
                  @click="$emit('act', ['delete', d.path])" />
        </div>
        <fp-empty v-if="!defsHere.length" class="fcalc-none"
                  shows="The derived properties of this grid: recipes, recomputed when their inputs change."
                  gesture="Write a formula above, name it, and press “Create”." />
      </div>
    </div>
  </fp-panel>
</template>

<script>
/*
 * The calculator: a formula over the properties of one grid, kept as a
 * recipe. Pure display: the host validates, previews, creates and lists
 * (engine/derived_props); the widget edits the fields and says what each
 * action would do.
 *   props in  — rep, repChoices, propChips, mrProps, mrPick, expr, name,
 *               uom, kind, editing, status {ok, error, summary}, preview,
 *               derivedProps, axes
 *   events out — set-rep / set-name / set-uom / set-kind / set-expr /
 *               set-mr-pick / append(text) / template([expr, uom]) /
 *               create / cancel-edit / make-percentiles / act([verb, path])
 *               / diff([expr, name, uom])
 */
import { fmt, fmtInt, fmtPct } from "../../../_shared/numfmt.js";
import FpBtn from "../../../_shared/components/FpBtn.vue";
import FpChip from "../../../_shared/components/FpChip.vue";
import FpEmpty from "../../../_shared/components/FpEmpty.vue";
import FpNote from "../../../_shared/components/FpNote.vue";
import FpPanel from "../../../_shared/components/FpPanel.vue";
import FpSelect from "../../../_shared/components/FpSelect.vue";

const KINDS = [
  { value: "ContinuousProperty", label: "Continuous", title: "Continuous values" },
  { value: "DiscreteProperty", label: "Discrete", title: "Discrete categories, whole numbers" },
];
const FUNCS = [
  ["log10", "Decimal logarithm"], ["ln", "Natural logarithm"], ["exp", "Exponential"],
  ["sqrt", "Square root"], ["abs", "Absolute value"],
  ["clip", "clip(x, low, high): x held between two bounds"],
  ["where", "where(condition, if true, if false)"],
  ["min", "Smallest value over the cells"], ["max", "Largest value over the cells"],
  ["mean", "Mean over the cells"],
];
const OPS = [
  ["+", "Plus"], ["-", "Minus"], ["*", "Times"], ["/", "Divided by"], ["**", "To the power"],
  ["(", "Open a bracket"], [")", "Close a bracket"],
];
const INSERTS = FUNCS.map(([f, t]) => ({ value: f + "(", label: f + "(", title: t }))
  .concat(OPS.map(([o, t]) => ({ value: o, label: o, title: t })));
const TEMPLATES = [
  { label: "log10(X)", expr: "log10(X)", uom: "" },
  { label: "X × Y", expr: "X * Y", uom: "" },
  { label: "1 − X", expr: "1 - X", uom: "frac" },
  { label: "normalize", expr: "(X - min(X)) / (max(X) - min(X))", uom: "" },
  { label: "pay flag", expr: "where(X > 0.1, 1, 0)", uom: "" },
  { label: "mD → m²", expr: "X * 9.869233e-16", uom: "m2" },
  { label: "psi → bar", expr: "X * 0.0689476", uom: "bar" },
  { label: "ft → m", expr: "X * 0.3048", uom: "m" },
];

export default {
  name: "CalculatorPanel",
  components: { FpBtn, FpChip, FpEmpty, FpNote, FpPanel, FpSelect },
  props: {
    rep: { type: String, default: "" },
    repChoices: { type: Array, default: () => [] },
    propChips: { type: Array, default: () => [] },
    mrProps: { type: Array, default: () => [] },
    mrPick: { type: String, default: "" },
    expr: { type: String, default: "" },
    name: { type: String, default: "" },
    uom: { type: String, default: "" },
    kind: { type: String, default: "ContinuousProperty" },
    editing: { type: String, default: "" },
    status: { type: Object, default: () => ({}) },
    preview: { type: Object, default: () => ({}) },
    derivedProps: { type: Array, default: () => [] },
    // {ident: {reals: [{title, value}], ts: [{title, value}]}} — what a
    // multi-realization / time-series chip can pin in a formula
    axes: { type: Object, default: () => ({}) },
  },
  emits: [
    "set-rep", "set-name", "set-uom", "set-kind", "set-expr", "set-mr-pick",
    "append", "template", "create", "cancel-edit", "make-percentiles", "act",
    "diff",
  ],
  data() {
    return {
      diffA: "", diffAr: "", diffAt: "",
      diffB: "", diffBr: "", diffBt: "",
      insertPick: "",
      templatePick: "",
      KINDS,
      INSERTS,
    };
  },
  computed: {
    repOptions() {
      return (this.repChoices || []).map((c) => ({ value: c.value, label: c.title, title: "Run the formula on " + c.title }));
    },
    mrOptions() {
      return (this.mrProps || []).map((m) => ({ value: m.value, label: m.title, title: m.title }));
    },
    templateOptions() {
      return TEMPLATES.map((t, i) => ({ value: String(i), label: t.label, title: t.expr }));
    },
    canCreate() {
      return !!(this.status && this.status.ok) && !!(this.name || "").trim();
    },
    createTitle() {
      if (this.canCreate) return this.editing ? "Write the recipe back with this formula" : "Create the derived property from this formula";
      if (!(this.status && this.status.ok)) return "Write a formula that reads first";
      return "Name the property first";
    },
    canDiff() {
      return !!this.diffA && !!this.diffB
        && !(this.diffA === this.diffB && this.diffAr === this.diffBr && this.diffAt === this.diffBt);
    },
    defsHere() {
      return (this.derivedProps || []).filter((d) => d.rep_path === this.rep);
    },
    statChips() {
      // p10 / p90 are percentiles of the CELLS of this result — not the
      // across-realization P10 / P90 of the Uncertainty row, whose names
      // follow the reserves convention (P90 = low case)
      const p = this.preview || {};
      const keys = [
        ["n", "n", "Cells of the grid"],
        ["nan", "NaN", "Cells without a finite value"],
        ["min", "min", "Smallest value over the cells"],
        ["mean", "mean", "Arithmetic mean over the cells"],
        ["max", "max", "Largest value over the cells"],
        ["p10", "p10 cells", "10th percentile of the cells of this result"],
        ["p90", "p90 cells", "90th percentile of the cells of this result"],
      ];
      // counts keep every digit; the values follow the shared rule
      return keys
        .filter(([k]) => p[k] !== undefined)
        .map(([k, label, title]) => ({
          k: label,
          title,
          v: k === "n" ? fmtInt(p.n)
            : k === "nan" ? `${fmtInt(p.nan)} (${fmtPct(Number(p.nan_pct) / 100)})`
              : fmt(p[k]),
        }));
    },
  },
  watch: {
    // another grid: the A − B picks do not name its properties, so they reset;
    // a new A or B resets that side's pins
    rep() { this.diffA = this.diffB = ""; this.diffAr = this.diffAt = this.diffBr = this.diffBt = ""; },
    diffA() { this.diffAr = this.diffAt = ""; },
    diffB() { this.diffBr = this.diffBt = ""; },
  },
  methods: {
    chipOptions(side) {
      return (this.propChips || []).map((p) => ({
        value: p.ident, label: p.label, title: (side === "a" ? "A = " : "B = ") + p.label,
      }));
    },
    // the pins of a chip: the view's slider first (""), then each value
    pinOptions(list, sliderWord, key) {
      return [{ value: "", label: sliderWord, title: "Follow the view's own slider" }]
        .concat((list || []).map((x) => ({ value: String(x.value), label: String(x.title), title: key[1] === "r" ? "Pin the realization " + x.title : "Pin the time step " + x.title })));
    },
    axesOf(ident) {
      const a = (ident && this.axes && this.axes[ident]) || {};
      return { reals: a.reals || [], ts: a.ts || [] };
    },
    pinned(ident, r, t) {
      // NAME__r3__t5: the derived-property store reads that input at THAT
      // realization / time step instead of following the view's sliders
      return ident + (r !== "" ? `__r${r}` : "") + (t !== "" ? `__t${t}` : "");
    },
    pinLabel(ident, r, t) {
      const a = this.axesOf(ident);
      const parts = [];
      if (r !== "") parts.push((a.reals.find((x) => String(x.value) === r) || {}).title || `real ${r}`);
      if (t !== "") parts.push((a.ts.find((x) => String(x.value) === t) || {}).title || `t${t}`);
      return parts.length ? ` (${parts.join(", ")})` : "";
    },
    makeDiff() {
      if (!this.diffA || !this.diffB) return;
      const chipA = this.propChips.find((p) => p.ident === this.diffA) || {};
      const chipB = this.propChips.find((p) => p.ident === this.diffB) || {};
      const labelA = (chipA.label || this.diffA).replace(/ \((MR|TS)\)$/, "").replace(/^ƒ /, "");
      const labelB = (chipB.label || this.diffB).replace(/ \((MR|TS)\)$/, "").replace(/^ƒ /, "");
      const expr = `${this.pinned(this.diffA, this.diffAr, this.diffAt)} - ${this.pinned(this.diffB, this.diffBr, this.diffBt)}`;
      const name = `${labelA}${this.pinLabel(this.diffA, this.diffAr, this.diffAt)} − ${labelB}${this.pinLabel(this.diffB, this.diffBr, this.diffBt)}`;
      // one event: the host sets the formula, the name and the unit, then
      // creates the property
      this.$emit("diff", [expr, name, chipA.uom || ""]);
    },
    // the two lists are verbs, not values: each goes back to its placeholder
    // once the pick has landed in the formula
    onInsert(v) {
      if (!v) return;
      this.$emit("append", v);
      this.$nextTick(() => { this.insertPick = ""; });
    },
    onTemplate(i) {
      if (i === "" || i === null || i === undefined) return;
      const t = TEMPLATES[Number(i)];
      const first = (this.propChips[0] || {}).ident || "X";
      this.$emit("template", [t.expr.split("X").join(first), t.uom]);
      this.$nextTick(() => { this.templatePick = ""; });
    },
  },
};
</script>

<style>
@import "../../../_shared/panel.css";
</style>

<style scoped>
.fcalc-body {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px;
  font-size: 13px;
}
.fcalc-row {
  display: flex;
  align-items: center;
  gap: 4px;
}
.fcalc-wrap {
  flex-wrap: wrap;
}
.fcalc-grow {
  flex: 1 1 160px;
}
.fcalc-diff {
  padding: 4px 6px;
  border: 1px dashed var(--fp-btn-line);
  border-radius: 4px;
}
.fcalc-pick {
  max-width: 180px;
}
.fcalc-pin {
  max-width: 120px;
}
.fcalc-minus {
  font-weight: 700;
  color: var(--fp-accent);
}
.fcalc-name {
  flex: 0 1 130px;
}
.fcalc-uom {
  flex: 0 1 70px;
}
.fcalc-kind {
  flex: 0 1 105px;
}
.fcalc-tpl {
  flex: 0 1 130px;
}
/* a property, as a chip whose + writes it into the formula */
.fcalc-ident {
  font-weight: 500;
}
.fcalc-derived {
  border-style: dashed;
}
.fcalc-formula {
  width: 100%;
  box-sizing: border-box;
  font-family: monospace;
  font-size: 12px;
  border: 1px solid var(--fp-btn-line);
  border-radius: 3px;
  padding: 4px 6px;
  resize: vertical;
}
.fcalc-ok {
  color: #2e7d32;
  font-size: 12px;
}
.fcalc-stats {
  gap: 6px;
}
.fcalc-stat {
  background: #f5f5f5;
  border-radius: 3px;
  padding: 1px 6px;
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}
.fcalc-muted {
  color: #888;
  font-size: 11px;
}
.fcalc-convention {
  flex-basis: 100%;
}
.fcalc-defs {
  border-top: 1px solid #eee;
  padding-top: 6px;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.fcalc-defs-title {
  text-transform: uppercase;
  font-weight: 600;
}
.fcalc-def {
  display: flex;
  align-items: center;
  gap: 5px;
  border: 1px solid #eee;
  border-radius: 3px;
  padding: 2px 4px;
}
.fcalc-expr {
  font-family: monospace;
  font-size: 11px;
  flex: 1 1 auto;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.fcalc-danger {
  color: #b71c1c;
}
.fcalc-none {
  padding: 4px 0;
}
</style>
