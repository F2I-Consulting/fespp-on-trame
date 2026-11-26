<template>
  <div class="fsl">
    <div class="fsl-top">
      <!-- the object the card cuts, when the view holds several -->
      <fp-select v-if="targets.length > 1" class="fsl-target" :model-value="state.target || ''"
                 :options="targetOptions" mandatory
                 :title="'The object this card cuts in this view (' + targets.length + ' can be)'"
                 @update:model-value="edit({ op: 'target', path: $event })" />
      <span class="fsl-gap"></span>
      <slot name="header" />
      <!-- the whole card at once, at the far right (the PO, 28/10) -->
      <fp-btn v-if="shape.boxes" variant="bare" class="fsl-eye" :class="{ off: !allVisible }" :disabled="!ready"
              :label="allVisible ? '\u{1F441}' : '\u{1F6AB}'"
              :title="allVisible ? 'Show the whole object (the slicing is kept)' : 'Cut the object again'"
              @click="edit({ op: 'all_visible', on: !allVisible })" />
      <fp-btn v-if="shape.boxes" variant="bare" class="fsl-reset" label="⟲" :disabled="!ready"
              :title="state.fixed ? 'Start again: one box keeping everything' : 'Start again: no box, no property'"
              @click="edit({ op: 'reset' })" />
    </div>

    <!-- a card on properties with no box yet: its first property makes its
         first box; then each box takes its own properties (the PO, 30/10) -->
    <div v-if="!state.fixed && state.target && !boxes.length && addOptions.length" class="fsl-add">
      <fp-select class="fsl-addsel" v-model="adding" :options="addOptions" placeholder="+ Property" mandatory
                 title="Cut on a property of the object: a first box holding it"
                 @update:model-value="addSubject($event)" />
    </div>

    <!-- no object to cut: what the card is for; an object but nothing cut on
         yet: only why, when there is a why (the "+ Property" above says the
         rest — the PO, 28/10: the sentence was useless there) -->
    <fp-empty v-if="!state.target" :shows="shows" :gesture="gesture" :why="state.note || ''" />
    <div v-else-if="!ready && state.note" class="fsl-note">{{ state.note }}</div>

    <template v-else-if="ready">
      <div v-if="shape.boxes" class="fsl-vol">
        <span>Boxes</span>
        <fp-btn tiny icon label="+" title="Add a box (Range, keeping everything; switch it to Slice for cuts)"
                @click="edit({ op: 'add_box', mode: 'range' })" />
      </div>
      <fp-empty v-if="!boxes.length" shows="The boxes kept, shown together." gesture="Press “+” beside Boxes to add one." />

      <!-- the boxes, joined by ∪ or ∩ (∩ binding tighter, the manager,
           29/10); each Range (ranges joined by ∪ or ∩) or Slice (cuts of one
           value) -->
      <div class="fsl-volume" v-for="(box, bi) in boxes" :key="box.id"
           :class="{ off: box.visible === false, bare: !shape.boxes }">
        <div v-if="shape.boxes" class="fsl-vrow">
          <fp-btn v-if="bi > 0" tiny class="fsl-op" :label="box.op === 'and' ? '∩' : '∪'"
                  :title="box.op === 'and'
                    ? 'Intersection: only what this box shares with the one above (click: union)'
                    : 'Union: this box as well as the ones above (click: intersection)'"
                  @click="edit({ op: 'join_box', id: box.id, join: box.op === 'and' ? 'or' : 'and' })" />
          <span class="fsl-vname">Box {{ bi + 1 }}</span>
          <fp-seg v-if="shape.modes" :model-value="box.mode === 'slice' ? 'slice' : 'range'" :options="MODES"
                  title="How this box cuts: ranges, or cuts of one value"
                  @update:model-value="edit({ op: 'box_mode', id: box.id, mode: $event })" />
          <fp-btn variant="bare" class="fsl-eye" :class="{ off: box.visible === false }"
                  :label="box.visible !== false ? '\u{1F441}' : '\u{1F6AB}'"
                  :title="box.visible === false ? 'Show this box' : 'Hide this box'"
                  @click="edit({ op: 'toggle_box', id: box.id })" />
          <fp-btn variant="bare" label="×" title="Remove this box" @click="edit({ op: 'del_box', id: box.id })" />
        </div>

        <!-- RANGE box -->
        <template v-if="box.mode !== 'slice'">
          <div class="fsl-axis" v-for="(s, si) in subjectsOf(box)" :key="s.value">
            <!-- a property's name has a line of its own (I, J, K sit in the
                 row), its × taking it out of this box; a subject of one value
                 cannot be cut: its line says so, no slider (the manager, 29/10) -->
            <div v-if="headed(s)" class="fsl-arow">
              <!-- the properties of a Range box intersect (the PO, 30/10:
                   "can I not join them?"): said, the union being two boxes -->
              <span v-if="si > 0 && !state.fixed" class="fsl-join"
                    title="Intersection: the cells kept by this property AND by the one above; for a union, put it in another box joined by ∪">∩</span>
              <span class="fsl-lab fsl-lab-head" :title="labelOf(s)">{{ labelOf(s) }}</span>
              <span v-if="constant(s)" class="fsl-const" :title="constantTitle(s)">{{ constantText(s) }}</span>
              <fp-btn v-if="!state.fixed" variant="bare" class="fsl-end fsl-prop-x" label="×"
                      :title="'Stop cutting on ' + s.label + ' in this box'"
                      @click="edit({ op: 'del_subject', box: box.id, subject: s.value })" />
            </div>
            <template v-for="(r, ri) in (constant(s) ? [] : rangesOf(box, s.value))" :key="r.id">
              <!-- a narrow row, its + or × always inside the card (the PO,
                   28/10, had to widen the window to find the ×): the join
                   of a range after the first in the label's place, a value
                   field as wide as the subject's values -->
              <div class="fsl-arow">
                <fp-btn v-if="ri > 0" tiny class="fsl-op" :label="r.op === 'and' ? '∩' : '∪'"
                        :title="r.op === 'and'
                          ? 'Intersection: only what this range shares with the one above (click: union)'
                          : 'Union: this range as well as the ones above (click: intersection)'"
                        @click="edit({ op: 'join_range', id: r.id, join: r.op === 'and' ? 'or' : 'and' })" />
                <span v-else class="fsl-lab" :title="s.label">{{ headed(s) ? '' : s.label }}</span>
                <fp-select v-if="s.kind === 'Categorical'" class="fsl-cat" :model-value="rangeOf(r)[0]"
                           :options="categoryOptions(s)" title="Lowest category kept"
                           @update:model-value="setRange(s, r, 'low', $event)" />
                <fp-num v-else class="fsl-num" :stepper="integer(s)" size="sm" :integer="integer(s)"
                        :digits="digits(s)" :style="numStyle(s)" :min="s.extent[0]" :max="s.extent[1]"
                        :model-value="rangeOf(r)[0]" :title="'Lowest ' + s.label + ' kept'"
                        @update:model-value="setRange(s, r, 'low', $event)" />
                <span class="fsl-gap"></span>
                <fp-select v-if="s.kind === 'Categorical'" class="fsl-cat" :model-value="rangeOf(r)[1]"
                           :options="categoryOptions(s)" title="Highest category kept"
                           @update:model-value="setRange(s, r, 'high', $event)" />
                <fp-num v-else class="fsl-num" :stepper="integer(s)" size="sm" :integer="integer(s)"
                        :digits="digits(s)" :style="numStyle(s)" :min="s.extent[0]" :max="s.extent[1]"
                        :model-value="rangeOf(r)[1]" :title="'Highest ' + s.label + ' kept'"
                        @update:model-value="setRange(s, r, 'high', $event)" />
                <fp-btn v-if="ri === 0" variant="bare" class="fsl-end" label="+"
                        :title="'Another ' + s.label + ' range in this box, joined by ∪ (click its ∪ for ∩)'"
                        @click="edit({ op: 'add_range', box: box.id, subject: s.value, join: 'or' })" />
                <fp-btn v-else variant="bare" class="fsl-end" label="×" title="Remove this range"
                        @click="edit({ op: 'del_range', id: r.id })" />
              </div>
              <!-- one track, two thumbs, and the span between them dragged
                   whole: the range slides, its width kept -->
              <div class="fsl-drow">
                <fp-range class="fsl-dual" :min="s.extent[0]" :max="s.extent[1]" :step="step(s)"
                          :low="rangeOf(r)[0]" :high="rangeOf(r)[1]" :ticks="ticksOf(s)"
                          @drag="(which, v) => dragRange(s, r, which, v)"
                          @commit="(which, v) => setRange(s, r, which, v)" />
              </div>
              <fp-player-bar v-bind="barOf(r.id)" play-title="Play: the whole range slides, its width kept"
                             :disabled="whole(s, rangeOf(r))"
                             disabled-title="The range holds the whole extent: there is nothing to slide. Narrow it to play"
                             @play="edit({ op: 'player', id: r.id, action: 'play', value: $event })"
                             @speed="edit({ op: 'player', id: r.id, action: 'speed', value: $event })"
                             @loop="edit({ op: 'player', id: r.id, action: 'loop', value: $event })" />
            </template>
          </div>
        </template>

        <!-- SLICE box: per subject, cuts of one value each -->
        <template v-else>
          <div class="fsl-axis" v-for="(s, si) in subjectsOf(box)" :key="s.value">
            <div class="fsl-arow">
              <!-- the cuts of a Slice box show together -->
              <span v-if="si > 0 && !state.fixed" class="fsl-join"
                    title="Union: the cuts of this property shown as well as the ones above">∪</span>
              <span class="fsl-lab fsl-lab-head" :title="labelOf(s)">{{ labelOf(s) }}</span>
              <span v-if="constant(s)" class="fsl-const" :title="constantTitle(s)">{{ constantText(s) }}</span>
              <fp-btn v-else-if="shape.many" tiny icon label="+" :title="'Add a cut on ' + s.label + ' in this box'"
                      @click="edit({ op: 'add_cut', box: box.id, subject: s.value })" />
              <fp-btn v-if="!state.fixed" variant="bare" class="fsl-end fsl-prop-x" label="×"
                      :title="'Stop cutting on ' + s.label + ' in this box'"
                      @click="edit({ op: 'del_subject', box: box.id, subject: s.value })" />
            </div>
            <template v-for="cut in (constant(s) ? [] : cutsOf(box, s.value))" :key="cut.id">
              <!-- a cut on two lines, as a range: what it keeps and its
                   value, its eye and × at the right; its slider under them -->
              <div class="fsl-cut" :class="{ off: cut.visible === false }" :data-fp-cut="cut.id">
                <div class="fsl-prow">
                  <!-- what the cut keeps: below it, its value only, above it -->
                  <fp-seg v-if="shape.cmp" class="fsl-cmp" :model-value="cut.cmp || 'only'" :options="CMPS"
                          :title="'What the cut keeps of ' + s.label"
                          @update:model-value="edit({ op: 'cut_cmp', id: cut.id, cmp: $event })" />
                  <fp-select v-if="s.kind === 'Categorical'" class="fsl-cat" :model-value="atOf(cut)"
                             :options="categoryOptions(s)" title="The category cut at"
                             @update:model-value="setCut(s, cut, $event)" />
                  <fp-num v-else class="fsl-num" :stepper="integer(s)" size="sm" :integer="integer(s)"
                          :digits="digits(s)" :style="numStyle(s)"
                          :min="s.extent[0]" :max="s.extent[1]" :model-value="atOf(cut)" :title="'The ' + s.label + ' cut'"
                          @update:model-value="setCut(s, cut, $event)" />
                  <span class="fsl-gap"></span>
                  <fp-btn v-if="shape.many" variant="bare" class="fsl-eye" :class="{ off: cut.visible === false }"
                          :label="cut.visible !== false ? '\u{1F441}' : '\u{1F6AB}'"
                          :title="cut.visible === false ? 'Show this cut' : 'Hide this cut (the others stay)'"
                          @click="edit({ op: 'toggle_cut', id: cut.id })" />
                  <fp-btn v-if="shape.many" variant="bare" label="×" title="Remove this cut"
                          @click="edit({ op: 'del_cut', id: cut.id })" />
                </div>
                <!-- one thumb, what is kept filled -->
                <div class="fsl-drow">
                  <fp-range class="fsl-dual" single :fill="FILL[cut.cmp || 'only']" :min="s.extent[0]"
                            :max="s.extent[1]" :step="step(s)" :low="atOf(cut)" :high="atOf(cut)"
                            :ticks="ticksOf(s)" :low-title="'Move the cut along ' + s.label"
                            @drag="(_w, v) => dragCut(s, cut, v)" @commit="(_w, v) => setCut(s, cut, v)" />
                </div>
                <fp-player-bar v-bind="barOf(cut.id)" :play-title="'Play: the cut steps along ' + s.label"
                               @play="edit({ op: 'player', id: cut.id, action: 'play', value: $event })"
                               @speed="edit({ op: 'player', id: cut.id, action: 'speed', value: $event })"
                               @loop="edit({ op: 'player', id: cut.id, action: 'loop', value: $event })" />
              </div>
            </template>
          </div>
        </template>
        <!-- a card on properties: this box's own "+ Property" (the PO, 30/10) -->
        <div v-if="!state.fixed" class="fsl-add fsl-box-add">
          <span v-if="!subjectsOf(box).length" class="fsl-note">Not used until it holds a property.</span>
          <fp-select v-if="boxAddOptions(box).length" class="fsl-addsel" :model-value="addingBox[box.id] || ''"
                     :options="boxAddOptions(box)" placeholder="+ Property" mandatory
                     title="Cut this box on one more property of the object"
                     @update:model-value="addSubject($event, box)" />
        </div>
      </div>
    </template>
  </div>
</template>

<script>
/*
 * A slicer card — the Geometry slicer and the Property slicer alike (the
 * PO's manager, 28/10: "the same UI for the two, so a user who understands
 * one understands the other"); they differ by their SUBJECTS only: the I,
 * J, K of a grid (`state.fixed`), or the properties added to the card.
 * Boxes joined by ∪ or ∩ (∩ binds tighter; the manager, 29/10), each in its
 * own mode (the manager: to mix):
 *   Range — each subject's ranges joined by ∪ or ∩ (∩ binds tighter), the
 *           subjects intersecting; a range dragged by its band slides whole;
 *   Slice — per subject, cuts at a value, shown together, each keeping
 *           below it (≤), its value only (=) or above it (≥).
 * A card on properties: "+ Property" adds one (a row in every box), the ×
 * on a property's line takes it out of that box (29/10: no chips under the
 * boxes). A subject of one value is said constant, never cut.
 * Under every slider its player bar: play slides the range whole, or steps
 * the cut from value to value, looping or not.
 * The card's SHAPE, from its host (the PO, 29/10: the Time & Realizations
 * card is rows of one value, nothing else): `shape` = {boxes: the boxes'
 * rows, "+" and the card's eye and ⟲; modes: Range / Slice; cmp: ≤ = ≥;
 * many: several cuts a subject, their eye and ×} — all true unless said.
 * Knows nothing of the engine: `state` = {card {subjects, boxes [{id, op, mode,
 * visible, ranges, cuts}]}, subjects [{value, label, single_label?, kind, extent, categories}], addable,
 * fixed, shape, target, targets, all_visible, note}, `player` = the card's player
 * {entry, index, count, label, playing, speed, loop, rates}; ONE event out,
 * `edit` (a gesture the host applies: app/features/slicer_card_host). A
 * drag goes live, a value every 50 ms at most (liveSender), the thumbs on a
 * local draft; the release sends the exact last value.
 */
import FpBtn from "./FpBtn.vue";
import FpEmpty from "./FpEmpty.vue";
import FpNum from "./FpNum.vue";
import FpPlayerBar from "./FpPlayerBar.vue";
import FpRange from "./FpRange.vue";
import FpSeg from "./FpSeg.vue";
import FpSelect from "./FpSelect.vue";
import { liveSender } from "./liveSender.js";

const MODES = [
  { value: "range", label: "Range", title: "Ranges, joined by ∪ or ∩" },
  { value: "slice", label: "Slice", title: "Cuts at a value" },
];
// what a cut keeps (the PO, 28/10), and how its slider fills
const CMPS = [
  { value: "below", label: "≤", title: "Below: from the lowest value up to this one" },
  { value: "only", label: "=", title: "Only this value" },
  { value: "above", label: "≥", title: "Above: from this one up to the highest" },
];
const FILL = { below: "left", only: "none", above: "right" };

export default {
  name: "FpSlicer",
  components: { FpBtn, FpEmpty, FpNum, FpPlayerBar, FpRange, FpSeg, FpSelect },
  props: {
    state: { type: Object, default: () => ({}) },
    player: { type: Object, default: () => ({}) },
    shows: { type: String, default: "" },
    gesture: { type: String, default: "" },
  },
  emits: ["edit"],
  data() {
    return { draft: {}, live: liveSender(), adding: "", addingBox: {}, MODES, CMPS, FILL };
  },
  watch: {
    // the server answered: its values are the truth again — unless the
    // mouse is still dragging (the echo would pull the thumb back)
    state() {
      if (!this.live.dragging) this.draft = {};
    },
  },
  beforeUnmount() {
    this.live.dispose();
  },
  computed: {
    card() {
      return this.state.card || {};
    },
    subjects() {
      return (this.state.subjects || []).filter((s) => (this.card.subjects || []).includes(s.value));
    },
    ready() {
      // a card on properties shows its boxes before any property is in them
      return !!this.state.target && (this.subjects.length > 0 || (!this.state.fixed && this.boxes.length > 0));
    },
    boxes() {
      return this.card.boxes || [];
    },
    allVisible() {
      return this.state.all_visible !== false;
    },
    targets() {
      return this.state.targets || [];
    },
    targetOptions() {
      return this.targets.map((t) => ({ value: t.value, label: t.label || t.value, title: t.label || t.value }));
    },
    addOptions() {
      return (this.state.addable || []).map((a) => ({ value: a.value, label: a.label || a.value, title: a.label || a.value }));
    },
    shape() {
      return Object.assign({ boxes: true, modes: true, cmp: true, many: true }, this.state.shape || {});
    },
  },
  methods: {
    edit(e) {
      this.$emit("edit", e);
    },
    addSubject(v, box) {
      if (!v) return;
      if (box) {
        this.addingBox = { ...this.addingBox, [box.id]: v };
        this.edit({ op: "add_subject", subject: v, box: box.id });
        this.$nextTick(() => { this.addingBox = { ...this.addingBox, [box.id]: "" }; });
        return;
      }
      this.edit({ op: "add_subject", subject: v });
      this.$nextTick(() => { this.adding = ""; });
    },
    // the properties a box can take: the object's ticked ones it does not
    // cut on yet (the card's own included)
    boxAddOptions(box) {
      const seen = new Set();
      const out = [];
      const held = (s) => s in (box.ranges || {}) || s in (box.cuts || {});
      for (const a of [...(this.state.addable || []), ...(this.state.subjects || [])]) {
        if (!a || seen.has(a.value) || held(a.value)) continue;
        seen.add(a.value);
        out.push({ value: a.value, label: a.label || a.value, title: a.label || a.value });
      }
      return out;
    },
    integer(s) {
      return s.kind !== "Continuous";
    },
    step(s) {
      if (this.integer(s)) return 1;
      return Math.abs(s.extent[1] - s.extent[0]) / 1000 || 1;
    },
    // the decimals of a continuous subject's values (the PO, 28/10: two are
    // enough): two from a span of 1 up, two significant ones below it
    // (0.123 on a porosity 0-0.4)
    digits(s) {
      if (this.integer(s)) return 0;
      const span = Math.abs(Number(s.extent[1]) - Number(s.extent[0]));
      if (!(span > 0)) return 2;
      return Math.min(8, Math.max(2, Math.ceil(-Math.log10(span)) + 2));
    },
    // a value as the card keeps it: whole, or at its subject's decimals — the
    // field shows exactly the value in force; an end of the subject's extent
    // stays exact (rounded, the highest cell would fall out of a range)
    rounded(s, v) {
      if (this.integer(s)) return Math.round(v);
      const f = 10 ** this.digits(s);
      const r = Math.round(v * f) / f;
      for (const e of s.extent) {
        if (Math.round(Number(e) * f) / f === r) return Number(e);
      }
      return r;
    },
    // a value field as wide as its subject's widest value, not wider
    numStyle(s) {
      const d = this.digits(s);
      const chars = Math.max(...s.extent.map((e) => {
        const n = Number(e);
        return String(Math.trunc(Math.abs(n))).length + (d ? d + 1 : 0) + (n < 0 ? 1 : 0);
      }), 2);
      return { width: `calc(${chars}ch + 10px)` };
    },
    categoryOptions(s) {
      return (s.categories || []).map((c) => ({ value: c.value, label: c.label, title: c.label + " (" + c.value + ")" }));
    },
    // the ticks under a slider: a categorical subject's values, up to a
    // dozen (fifty time steps drew a band of dots and of overlapping dates)
    ticksOf(s) {
      const cats = s.categories || [];
      return cats.length <= 12 ? cats : [];
    },
    // the subjects a box cuts on: a property taken out of one box by its ×
    // stays in the others (the manager, 29/10)
    subjectsOf(box) {
      return this.subjects.filter((s) => s.value in (box.ranges || {}) || s.value in (box.cuts || {}));
    },
    // a subject named on a line of its own: a property, an axis whose name
    // does not fit the row ("Easting (m)", 29/10), a constant one; I, J, K
    // sit in their row
    headed(s) {
      return !this.state.fixed || String(s.label || "").length > 2 || this.constant(s);
    },
    // a subject of one value (a constant property, the Z of a flat surface):
    // nothing to cut, its rows are left out (the PO, 29/10)
    constant(s) {
      return Number(s.extent[0]) === Number(s.extent[1]);
    },
    constantTitle(s) {
      return s.single_label ? "" : s.label + " has one value everywhere: nothing to cut on it";
    },
    // `single_label`: the name a subject of one value goes by, its value
    // then said alone ("Unique time step" 1995-01-01)
    labelOf(s) {
      return this.constant(s) && s.single_label ? s.single_label : s.label;
    },
    constantText(s) {
      return (s.single_label ? "" : "constant ") + this.shown(s, s.extent[0]);
    },
    // a value as the field shows it
    shown(s, v) {
      if (s.kind === "Categorical") {
        const c = (s.categories || []).find((x) => Number(x.value) === Number(v));
        if (c) return c.label;
      }
      return this.integer(s) ? String(Math.round(Number(v))) : Number(v).toFixed(this.digits(s));
    },
    rangesOf(box, subject) {
      return (box.ranges || {})[subject] || [];
    },
    cutsOf(box, subject) {
      return (box.cuts || {})[subject] || [];
    },
    rangeOf(r) {
      return this.draft[r.id] || [r.low, r.high];
    },
    // a range holding the whole extent: nothing to slide, nothing to play
    whole(s, range) {
      const [lo, hi] = s.extent || [];
      if (lo == null || hi == null) return false;
      const tol = Math.abs(hi - lo) * 1e-9;
      return range[0] <= lo + tol && range[1] >= hi - tol;
    },
    atOf(cut) {
      return this.draft[cut.id] ?? cut.at;
    },
    barOf(id) {
      const p = this.player || {};
      const active = p.entry === id;
      return {
        active, playing: active && !!p.playing, speed: Number(p.speed) || 5, rates: p.rates || [],
        loop: p.loop !== false, index: active ? Number(p.index) || 0 : 0,
        count: active ? Number(p.count) || 0 : 0,
      };
    },
    // a bound or the whole range moved, as the kept [low, high]: whole on an
    // integer subject, clamped, the moved bound pushing the other
    moved(s, r, which, raw) {
      const clamp = (v) => Math.max(s.extent[0], Math.min(s.extent[1], v));
      const round = (v) => this.rounded(s, v);
      if (which === "range") return [clamp(round(Number(raw[0]))), clamp(round(Number(raw[1])))];
      const v = parseFloat(String(raw).replace(",", "."));
      if (Number.isNaN(v)) return null;
      const cur = this.rangeOf(r);
      let lo = which === "low" ? clamp(round(v)) : Number(cur[0]);
      let hi = which === "high" ? clamp(round(v)) : Number(cur[1]);
      // the bound moved stops on the other, never pushes it (the manager,
      // 29/10: the low end stays where it is)
      if (lo > hi) { if (which === "low") lo = hi; else hi = lo; }
      return [lo, hi];
    },
    dragRange(s, r, which, raw) {
      const b = this.moved(s, r, which, raw);
      if (!b) return;
      this.draft = { ...this.draft, [r.id]: b };
      this.live.send(() => {
        const cur = this.rangeOf(r);
        this.edit({ op: "set_range", id: r.id, low: cur[0], high: cur[1], live: true });
      });
    },
    setRange(s, r, which, raw) {
      const b = this.moved(s, r, which, raw);
      if (!b) return;
      this.live.end();
      this.draft = { ...this.draft, [r.id]: b };
      this.edit({ op: "set_range", id: r.id, low: b[0], high: b[1] });
    },
    at(s, raw) {
      const v = parseFloat(String(raw).replace(",", "."));
      if (Number.isNaN(v)) return null;
      return Math.max(s.extent[0], Math.min(s.extent[1], this.rounded(s, v)));
    },
    dragCut(s, cut, raw) {
      const v = this.at(s, raw);
      if (v === null) return;
      this.draft = { ...this.draft, [cut.id]: v };
      this.live.send(() => this.edit({ op: "set_cut", id: cut.id, at: this.atOf(cut), live: true }));
    },
    setCut(s, cut, raw) {
      const v = this.at(s, raw);
      if (v === null) return;
      this.live.end();
      this.draft = { ...this.draft, [cut.id]: v };
      this.edit({ op: "set_cut", id: cut.id, at: v });
    },
  },
};
</script>

<style scoped>
.fsl { font-family: system-ui, sans-serif; font-size: 13px; padding: 8px; display: flex; flex-direction: column; gap: 8px; }
.fsl-top { display: flex; align-items: center; gap: 8px; border-bottom: 1px solid #ddd; padding-bottom: 6px; }
.fsl-target { flex: 1 1 auto; min-width: 0; font-size: 11px; }
/* a card on properties: one more */
.fsl-add { display: flex; align-items: center; }
.fsl-addsel { font-size: 11px; max-width: 150px; }
.fsl-box-add { gap: 6px; padding-top: 2px; flex-wrap: wrap; }
/* the join between two properties of a box: said, not clickable */
.fsl-join { flex: 0 0 auto; color: var(--fp-accent); font-weight: 700; padding-right: 4px; }
/* a subject of one value: said, not cut */
.fsl-const { flex-shrink: 0; font-size: 11px; color: #777; font-style: italic; white-space: nowrap; }
.fsl-vol { display: flex; align-items: center; gap: 6px; font-weight: 600; color: #555; }
.fsl-volume { display: flex; flex-direction: column; gap: 2px; padding: 4px 6px; border: 1px solid #e3e3e3; border-radius: 4px; }
.fsl-volume.off, .fsl-cut.off { opacity: 0.6; }
.fsl-volume.bare { border: none; padding: 0; }
.fsl-cut { display: flex; flex-direction: column; gap: 2px; padding-left: 8px; }
.fsl-vrow { display: flex; align-items: center; gap: 4px; }
.fsl-vname { flex: 1 1 auto; font-weight: 600; color: var(--fp-accent); font-size: 12px; }
.fsl-axis { display: flex; flex-direction: column; gap: 2px; }
.fsl-arow, .fsl-prow { display: flex; align-items: center; gap: 3px; }
/* the label's place: I, J, K, or the join of a range after the first */
.fsl-lab { flex: 0 0 22px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  text-align: center; font-weight: 600; color: var(--fp-accent); }
.fsl-lab-head { flex: 1 1 auto; min-width: 0; text-align: left; }
.fsl-op { flex: 0 0 22px; padding: 1px 0; color: var(--fp-accent); font-weight: 700; }
.fsl-eye, .fsl-reset, .fsl-end { font-size: 13px; opacity: 1; flex-shrink: 0; }
.fsl-eye.off { filter: grayscale(1); opacity: 0.55; }
.fsl-note { font-size: 12px; color: #666; }
/* the value fields give way before the + or × of their row does */
.fsl-num { font-size: 12px; flex: 0 1 auto; min-width: 3ch; }
.fsl-arow :deep(.fp-lab), .fsl-prow :deep(.fp-lab) { gap: 2px; min-width: 0; flex: 0 1 auto; }
.fsl-cat { max-width: 96px; min-width: 0; flex: 0 1 auto; font-size: 11px; }
.fsl-cmp { flex-shrink: 0; font-size: 11px; }
.fsl-grow { flex: 1 1 auto; max-width: none; }
.fsl-range { flex: 1 1 auto; min-width: 0; }
.fsl-gap { flex: 1 1 auto; }
.fsl-drow { display: flex; padding-left: 25px; }
.fsl-cut .fsl-drow { padding-left: 8px; }
/* where the shared double slider (<fp-range>) sits in its row */
.fsl-dual { flex: 1 1 auto; min-width: 60px; }
</style>
