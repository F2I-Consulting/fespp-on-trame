<template>
  <div class="fcm">
    <!-- a geometry node active: the object's own colour, its palette open,
         and the opacity it is drawn at in it — the colour it is drawn in
         where no property paints it, its chip in the tree -->
    <template v-if="geometryNode">
      <fp-color-picker :color="look.color" :alpha="objectOpacity" :label="look.label"
                       :alpha-title="'The opacity of ' + look.label + ' in this color, in this view'"
                       @commit-color="$emit('set-object-color', $event)"
                       @commit-alpha="$emit('set-object-opacity', $event)" />
      <div v-if="look.painted" class="fcm-muted">A property paints {{ look.label }}: this colour shows where its eye is closed.</div>
    </template>

    <template v-else>
    <!-- a property node active: the opacity of the whole object while a
         property paints it, then the property's colormap -->
    <div v-if="look && look.path" class="fcm-row fcm-object" :title="'The object ' + look.label">
      <label class="fcm-label">Opacity</label>
      <fp-range class="fcm-grow" single fill="left" :min="0" :max="1" :step="0.05"
                :low="objectOpacity"
                :low-title="'The opacity of ' + look.label + ' while a property paints it, in this view'"
                @commit="(_w, v) => $emit('set-object-opacity', v)" />
      <span class="fcm-muted fcm-pct">{{ Math.round(objectOpacity * 100) }} %</span>
    </div>
    <fp-empty v-if="!cmap || !cmap.array"
              :shows="look && look.path ? 'No property paints ' + look.label + ': its opacity is above.' : 'The colors of the property painting this view: its preset, its range, what lies outside it, the codes when it is painted by code.'"
              gesture="Activate a property in the tree, or open its eye, and its colormap is here." />

    <template v-else>
      <!-- the property itself is the card's TARGET, named by the card frame
           ("Colormap · Facies"); what stays here is what qualifies it -->
      <div v-if="cmap.is_ts || cmap.is_mr || cmap.categorical" class="fcm-tags" :title="'VTK array ' + cmap.array">
        <fp-chip v-if="cmap.is_ts" sm variant="accent" class="fcm-tag" text="TS" title="Time series: one value per time step" />
        <fp-chip v-if="cmap.is_mr" sm variant="accent" class="fcm-tag" text="MR" title="Multi-realization: one value per realization" />
        <fp-chip v-if="cmap.categorical" sm variant="accent" class="fcm-tag fcm-tag-cat" text="codes"
                 title="A property whose values are codes: one color per code, the codes named on the color bar" />
      </div>

      <!-- a property painted by code: the codes, their names, their
           colours — no ramp, no range -->
      <template v-if="cmap.categorical">
        <div class="fcm-row">
          <label class="fcm-label">Preset</label>
          <fp-select class="fcm-grow" :model-value="cmap.preset || ''" :options="presetOptions(presetsCategorical)"
                     placeholder="Choose" mandatory
                     title="A palette made to tell codes apart; the codes keep their names"
                     @update:model-value="$emit('set-preset', $event)" />
        </div>
        <div class="fcm-cats" :title="cmap.categories.length + ' codes in the data of this view'">
          <div v-for="c in cmap.categories" :key="c.code" class="fcm-cat"
               :class="{ 'fcm-cat-hidden': catAlpha(c) === 0 }">
            <fp-color-swatch :color="c.color" :alpha="catAlpha(c)" :label="'Code ' + codeText(c.code)"
                             :title="'Color of code ' + codeText(c.code)"
                             @commit-color="$emit('set-category-color', [c.code, $event])"
                             @commit-alpha="$emit('set-category-opacity', [c.code, $event])" />
            <span class="fcm-cat-label" :title="c.label">{{ c.label }}</span>
            <span v-if="c.label !== codeText(c.code)" class="fcm-muted fcm-cat-code">{{ codeText(c.code) }}</span>
            <!-- the code's opacity: at 0 its cells are taken out of the grid
                 (their neighbours' faces show), the other codes stay -->
            <fp-range class="fcm-cat-op" single fill="left" :min="0" :max="1" :step="0.05" :low="catAlpha(c)"
                      :low-title="'Opacity of code ' + codeText(c.code) + ': ' + fmt(catAlpha(c))
                        + ' (at 0 its cells are taken out, their neighbors show)'"
                      @drag="(_w, v) => dragCat(c.code, v)"
                      @commit="(_w, v) => $emit('set-category-opacity', [c.code, v])" />
          </div>
        </div>
        <!-- every code at once: the whole property see-through, or back -->
        <div class="fcm-row">
          <label class="fcm-label">All codes</label>
          <fp-range class="fcm-grow" single fill="left" :min="0" :max="1" :step="0.05" :low="allAlphaValue"
                    low-title="The opacity of every code at once"
                    @drag="(_w, v) => (allDraft = v)"
                    @commit="(_w, v) => $emit('set-category-opacity', [null, v])" />
          <span class="fcm-num-val fcm-op-val">{{ allAlphaText }}</span>
        </div>
        <div class="fcm-muted fcm-cat-count">{{ cmap.categories.length }} codes · one colour and one opacity each</div>
      </template>

      <template v-else>
      <!-- the colour / opacity node graph, mounted by the host (e.g. Kitware's
           ColorOpacityEditor) -->
      <slot></slot>

      <!-- range labels under the graph -->
      <div class="fcm-range-labels">
        <span>{{ fmt(cmap.min) }}</span>
        <span class="fcm-muted">data {{ fmt(cmap.data_min) }} … {{ fmt(cmap.data_max) }}</span>
        <span>{{ fmt(cmap.max) }}</span>
      </div>

      <!-- preset -->
      <div class="fcm-row">
        <label class="fcm-label">Preset</label>
        <fp-select class="fcm-grow" :model-value="cmap.preset || ''" :options="presetOptions(presets)"
                   placeholder="Choose" mandatory title="The color ramp the values are painted with"
                   @update:model-value="$emit('set-preset', $event)" />
      </div>

      <!-- below | min | max | above  (colour-bar reading order): each side
           is ONE swatch (its colour + opacity) opening the palette -->
      <div class="fcm-row">
        <fp-color-swatch :color="belowHex" :alpha="belowAlpha" label="Below range" title="Below-range color / opacity"
                         @commit-color="setSide('below', $event, belowAlpha)"
                         @commit-alpha="setSide('below', belowHex, $event)" />
        <fp-num class="fcm-num" :model-value="rangeValue(cmap.min)" title="Lowest value of the ramp; Enter or leaving the field applies"
                @update:model-value="commitRange('min', $event)" />
        <fp-num class="fcm-num" :model-value="rangeValue(cmap.max)" title="Highest value of the ramp; Enter or leaving the field applies"
                @update:model-value="commitRange('max', $event)" />
        <fp-color-swatch :color="aboveHex" :alpha="aboveAlpha" label="Above range" title="Above-range color / opacity"
                         @commit-color="setSide('above', $event, aboveAlpha)"
                         @commit-alpha="setSide('above', aboveHex, $event)" />
      </div>

      <!-- rescale actions -->
      <div class="fcm-row fcm-wrap">
        <span class="fcm-label">Rescale</span>
        <fp-btn tiny label="Data range" title="Rescale to the current data range (unpins)"
                @click="$emit('rescale', 'data')" />
        <fp-btn tiny label="All time steps" :disabled="!cmap.is_ts"
                :title="cmap.is_ts ? 'Range over ALL time steps of this time series' : 'Not a time series'"
                @click="$emit('rescale', 'time')" />
        <fp-btn tiny label="All realizations" :disabled="!cmap.is_mr"
                :title="cmap.is_mr ? 'Range over ALL realizations of this property' : 'Not a multi-realization property'"
                @click="$emit('rescale', 'mr')" />
        <fp-btn tiny label="All TS × MR" :disabled="!(cmap.is_ts && cmap.is_mr)"
                :title="cmap.is_ts && cmap.is_mr ? 'Range over ALL time steps AND ALL realizations (global)' : 'Needs a property that is both a time series and multi-realization'"
                @click="$emit('rescale', 'all')" />
        <fp-btn tiny label="Symmetric around 0" title="[-m, +m] with m = max(|min|, |max|) of the data range"
                @click="$emit('rescale', 'symmetric')" />
        <fp-btn tiny label="Diverging"
                title="Cool to Warm preset on a range symmetric around 0 — for a difference, a rise reads warm and a drop cool"
                @click="$emit('rescale', 'diverging')" />
      </div>
      </template>
      <!-- what the last action had to say (a preset missing, nothing to
           rescale): a band, until its cause goes or the reader closes it -->
      <fp-note v-if="cmap.note" severity="warning" :text="cmap.note" />
      <!-- a discrete property painted with a ramp all the same says why -->
      <fp-note v-if="cmap.categories_note" severity="warning" :text="cmap.categories_note" />

      <!-- vector property: the magnitude, or one component — the choice the
           colour AND every analysis panel read -->
      <div v-if="cmap.components > 1" class="fcm-row">
        <label class="fcm-label" title="A vector property: color by its magnitude, or by one component">Component</label>
        <fp-select class="fcm-grow" :model-value="componentValue()" :options="componentOptions"
                   title="A vector property: color by its magnitude, or by one component"
                   @update:model-value="$emit('set-component', $event)" />
      </div>

      <!-- scale / colour bar -->
      <div class="fcm-row">
        <template v-if="!cmap.categorical">
        <label class="fcm-label">Scale</label>
        <fp-select :model-value="cmap.scale || 'linear'" :options="SCALES"
                   title="Linear / logarithmic (native) / exponential (node re-spacing)"
                   @update:model-value="$emit('set-scale', $event)" />
        </template>
        <label class="fcm-check" style="margin-left:auto"><input type="checkbox" :checked="cmap.bar !== false"
               @change="$emit('set-bar', $event.target.checked)" /> Color bar</label>
      </div>

      <!-- NaN: the same swatch as below / above -->
      <div class="fcm-row">
        <label class="fcm-label">NaN</label>
        <fp-color-swatch :color="nanHex" :alpha="nanAlpha" label="NaN" title="NaN color / opacity"
                         @commit-color="setSide('nan', $event, nanAlpha)"
                         @commit-alpha="setSide('nan', nanHex, $event)" />
        <label class="fcm-check" style="margin-left:auto" :title="hideNanTitle"
               :class="{ 'fcm-check-off': cmap.hide_nan_ok === false }"><input type="checkbox"
               :checked="!!cmap.hide_nan" :disabled="cmap.hide_nan_ok === false"
               @change="$emit('set-hide-nan', $event.target.checked)" /> Hide NaN cells</label>
      </div>
    </template>
    </template>
  </div>
</template>

<script>
/*
 * On a geometry node (`look.node` "geometry"): the object's own colour, its
 * palette open, and its opacity — nothing else. On a property: the
 * object's opacity, then the property's colormap.
 * Per-view COLORMAP controls: preset, range, scale, below- and above-range
 * colour and opacity, NaN colour and opacity, colour bar, vector component,
 * and the rescales. The colour/opacity NODE graph itself is the Kitware
 * ColorOpacityEditor the host mounts in the default slot. Knows nothing
 * about ParaView:
 *   props in  — `cmap` (the host's projection of the view-scoped LUT of the
 *               view's active array), `presets`, `presetsCategorical`,
 *   events out — set-preset(name) / set-range([lo, hi]) /
 *               set-scale(linear | log | exp) / set-below([hex, alpha]) /
 *               set-above([hex, alpha]) / set-nan([hex, alpha]) /
 *               set-hide-nan(bool) / set-bar(bool) / set-component(value) /
 *               set-category-color([code, hex]) /
 *               set-category-opacity([code, alpha], code null: every code) /
 *               rescale(mode: data | time | mr | all | symmetric | diverging).
 * cmap: { array, label, preset, min, max, data_min, data_max, scale,
 *         below, below_alpha, above, above_alpha, nan, nan_opacity, bar,
 *         is_ts, is_mr, note, components, component,
 *         categorical, categories: [{code, label, color, opacity}], categories_note,
 *         hide_nan, hide_nan_auto, hide_nan_ok, hide_nan_why, hide_nan_hidden }
 * "Hide NaN cells" removes the grid's NaN cells so their neighbours' faces
 * show (NaN opacity 0 alone leaves a see-through hole); the host checks it
 * itself when the NaN opacity goes to 0 (`hide_nan_auto`), disables it
 * with `hide_nan_why` where it cannot apply (a node property, no grid), and
 * counts the cells it hides (`hide_nan_hidden`).
 * A property painted by code (`categorical`) shows its codes, their names
 * and a colour picker and an opacity slider each instead of the graph, the
 * range and the rescales (an indexed table ignores the opacity function:
 * one opacity per code is all it reads); `presetsCategorical` are the
 * qualitative presets offered then, set-category-color([code, hex]) is one
 * code's new colour, set-category-opacity([code, alpha]) its opacity, and
 * the "Opacity" row sends [null, alpha] for every code.
 * `array` is the VTK array name (the key), `label` the property's display
 * name — title, component, unit — which the host shows in the card frame;
 * `note` is what the last action had to say, "" or absent when nothing.
 * The min/max fields write the range exactly and Enter (or leaving the
 * field) applies what is displayed.
 */
import { fmt } from "../../../_shared/numfmt.js";
import FpBtn from "../../../_shared/components/FpBtn.vue";
import FpChip from "../../../_shared/components/FpChip.vue";
import FpColorPicker from "../../../_shared/components/FpColorPicker.vue";
import FpColorSwatch from "../../../_shared/components/FpColorSwatch.vue";
import FpRange from "../../../_shared/components/FpRange.vue";
import FpEmpty from "../../../_shared/components/FpEmpty.vue";
import FpNote from "../../../_shared/components/FpNote.vue";
import FpNum from "../../../_shared/components/FpNum.vue";
import FpSelect from "../../../_shared/components/FpSelect.vue";

const SCALES = [
  { value: "linear", label: "Linear", title: "The values spaced as they are" },
  { value: "log", label: "Log", title: "Logarithmic, native to the lookup table" },
  { value: "exp", label: "Exponential", title: "The color nodes re-spaced exponentially" },
];

export default {
  name: "ColormapPanel",
  components: { FpBtn, FpChip, FpColorPicker, FpColorSwatch, FpEmpty, FpNote, FpNum, FpSelect, FpRange },
  props: {
    viewId: { type: String, default: "" },
    cmap: { type: Object, default: () => ({}) },
    presets: { type: Array, default: () => [] },
    presetsCategorical: { type: Array, default: () => [] },
    // the active object: {path, label, node (geometry | property), color,
    // painted, opacity} | {}
    look: { type: Object, default: () => ({}) },
  },
  emits: ["set-preset", "set-range", "set-scale", "set-below", "set-above",
          "set-nan", "set-hide-nan", "set-bar", "rescale", "set-component",
          "set-category-color", "set-category-opacity", "set-object-color", "set-object-opacity"],
  data() {
    const c = this.cmap || {};
    return {
      // a slider's value while it is dragged, until the host's answer
      catDraft: {},
      allDraft: null,
      SCALES,
      belowHex: c.below || "#000000",
      aboveHex: c.above || "#ffffff",
      belowAlpha: c.below_alpha != null ? c.below_alpha : 1,
      aboveAlpha: c.above_alpha != null ? c.above_alpha : 1,
      nanHex: c.nan || "#ff0000",
      nanAlpha: c.nan_opacity != null ? c.nan_opacity : 1,
    };
  },
  watch: {
    cmap(c) {
      if (!c) return;
      if (c.below) this.belowHex = c.below;
      if (c.above) this.aboveHex = c.above;
      if (c.below_alpha != null) this.belowAlpha = c.below_alpha;
      if (c.above_alpha != null) this.aboveAlpha = c.above_alpha;
      if (c.nan) this.nanHex = c.nan;
      if (c.nan_opacity != null) this.nanAlpha = c.nan_opacity;
      this.catDraft = {};
      this.allDraft = null;
    },
  },
  computed: {
    // a geometry node active: its colour and its opacity, no colormap
    geometryNode() {
      return Boolean(this.look && this.look.path && this.look.node === "geometry");
    },
    objectOpacity() {
      const o = this.look && this.look.opacity;
      return o == null ? 1 : Number(o);
    },
    // the opacity every code shares, null when they differ
    allAlpha() {
      const cats = (this.cmap && this.cmap.categories) || [];
      if (!cats.length) return 1;
      const first = this.catAlpha(cats[0]);
      return cats.every((c) => this.catAlpha(c) === first) ? first : null;
    },
    allAlphaValue() {
      if (this.allDraft != null) return this.allDraft;
      return this.allAlpha != null ? this.allAlpha : 1;
    },
    allAlphaText() {
      if (this.allDraft != null) return fmt(this.allDraft);
      return this.allAlpha != null ? fmt(this.allAlpha) : "mixed";
    },
    hideNanTitle() {
      const c = this.cmap || {};
      if (c.hide_nan_ok === false) return c.hide_nan_why || "Not available for this property";
      const n = c.hide_nan_hidden;
      const count = (c.hide_nan && n != null)
        ? n.toLocaleString("en-US") + (n === 1 ? " cell" : " cells") + " hidden. " : "";
      if (c.hide_nan && c.hide_nan_auto) {
        return count + "Checked because the NaN opacity is 0: the cells whose value is NaN "
          + "are removed, so the faces of their neighbors show";
      }
      if (c.hide_nan) {
        return count + "The cells whose value is NaN are removed, so the faces of their "
          + "neighbors show";
      }
      return "Remove the cells whose value is NaN, so the faces of their neighbors show "
        + "(a NaN opacity of 0 alone leaves a see-through hole)";
    },
    componentOptions() {
      const n = (this.cmap && this.cmap.components) || 0;
      const out = [{ value: "magnitude", label: "Magnitude", title: "The length of the vector" }];
      for (let i = 0; i < n; i += 1) {
        out.push({ value: String(i), label: this.componentLabel(i), title: "The component " + this.componentLabel(i) });
      }
      return out;
    },
  },
  methods: {
    presetOptions(names) {
      return (names || []).map((p) => ({ value: p, label: p, title: "The preset " + p }));
    },
    // a bound as the field wants it: a Number, or nothing while unknown
    rangeValue(v) {
      const n = Number(v);
      return Number.isFinite(n) ? n : null;
    },
    // a code's opacity: the dragged value, else the host's, else opaque
    catAlpha(c) {
      if (this.catDraft[c.code] != null) return this.catDraft[c.code];
      if (this.allDraft != null) return this.allDraft;
      return c.opacity != null ? Number(c.opacity) : 1;
    },
    dragCat(code, v) {
      this.catDraft = Object.assign({}, this.catDraft, { [code]: Number(v) });
    },
    // a code is an identifier: written whole, never grouped
    codeText(code) {
      const n = Number(code);
      return Number.isInteger(n) ? String(n) : String(code);
    },
    componentValue() {
      const c = this.cmap ? this.cmap.component : null;
      return (c === null || c === undefined || c === "magnitude") ? "magnitude" : String(c);
    },
    // X/Y/Z for a vector, the Voigt order for a symmetric tensor, else an index
    componentLabel(i) {
      const n = this.cmap ? this.cmap.components : 0;
      if (n === 3) return ["X", "Y", "Z"][i];
      if (n === 6) return ["XX", "YY", "ZZ", "XY", "YZ", "XZ"][i];
      return "Component " + i;
    },
    // a colour outside the ramp ("below", "above", "nan"): shown at once, its
    // colour and its opacity sent together
    setSide(side, hex, alpha) {
      this[side + "Hex"] = hex;
      this[side + "Alpha"] = alpha;
      this.$emit("set-" + side, [hex, alpha]);
    },
    fmt,
    commitRange(which, v) {
      if (v === null || v === undefined || !Number.isFinite(Number(v))) return;
      let lo = which === "min" ? v : Number(this.cmap.min);
      let hi = which === "max" ? v : Number(this.cmap.max);
      if (!(hi > lo)) return;
      this.$emit("set-range", [lo, hi]);
    },
  },
};
</script>

<style>
@import "../../../_shared/panel.css";
</style>

<style scoped>
.fcm { font-family: system-ui, sans-serif; font-size: 12px; padding: 8px; display: flex; flex-direction: column; gap: 8px; }
.fcm-tags { display: flex; align-items: center; gap: 6px; }
.fcm-tag { font-weight: 700; }
.fcm-tag-cat { background: #e0f2f1; color: #00695c; }
.fcm-cats { display: flex; flex-direction: column; gap: 3px; max-height: 12rem; overflow-y: auto; padding-right: 2px; }
.fcm-cat { display: flex; align-items: center; gap: 6px; }
.fcm-cat-label { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fcm-cat-code { font-variant-numeric: tabular-nums; }
.fcm-cat-count { font-size: 11px; }
.fcm-cat-op { flex: 0 0 64px; width: 64px; min-width: 0; }
/* a code at opacity 0: its name greys, its cells are gone */
.fcm-cat-hidden .fcm-cat-label { color: #999; text-decoration: line-through; }
.fcm-op-val { min-width: 3.2em; text-align: right; font-variant-numeric: tabular-nums; }
.fcm-range-labels { display: flex; justify-content: space-between; font-size: 11px; color: #333; }
.fcm-muted { color: #999; }
.fcm-row { display: flex; align-items: center; gap: 6px; }
.fcm-wrap { flex-wrap: wrap; }
.fcm-label { color: #555; min-width: 48px; }
.fcm-grow { flex: 1 1 auto; min-width: 0; }
.fcm-num { width: 78px; flex: 1 1 auto; min-width: 0; }
.fcm-num-val { color: var(--fp-accent); font-weight: 600; }
.fcm-check { display: flex; align-items: center; gap: 4px; margin-right: 10px; cursor: pointer; }
.fcm-check-off { opacity: 0.5; cursor: default; }
.fcm-object { border-bottom: 1px solid #e0e0e0; padding-bottom: 6px; margin-bottom: 4px; }
.fcm-pct { min-width: 36px; text-align: right; font-variant-numeric: tabular-nums; }
</style>
