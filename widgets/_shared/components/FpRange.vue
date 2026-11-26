<template>
  <div
    class="fp-range"
    :class="{ 'fp-range-ticked': ticked, 'fp-range-single': single }"
    v-bind="$attrs"
  >
    <div class="fp-range-track"><div class="fp-range-fill" :style="fillStyle"></div></div>
    <!-- the kept span itself, grabbed between the thumbs: the whole range
         slides, its width kept (the PO's manager, 28/10) -->
    <div v-if="band && !single && bandStyle" class="fp-range-band" :style="bandStyle"
         title="Drag: the whole range slides, its width kept"
         @pointerdown.prevent="slideStart" @pointermove="slideMove"
         @pointerup="slideEnd" @pointercancel="slideEnd"></div>
    <input
      type="range"
      :min="min"
      :max="max"
      :step="step"
      :value="low"
      :title="lowTitle || null"
      :style="{ zIndex: lowOnTop ? 3 : 2 }"
      @input="$emit('drag', 'low', read($event, 'low'))"
      @change="$emit('commit', 'low', read($event, 'low'))"
    />
    <input
      v-if="!single"
      type="range"
      :min="min"
      :max="max"
      :step="step"
      :value="high"
      :title="highTitle || null"
      :style="{ zIndex: lowOnTop ? 2 : 3 }"
      @input="$emit('drag', 'high', read($event, 'high'))"
      @change="$emit('commit', 'high', read($event, 'high'))"
    />
    <!-- one labelled tick per category -->
    <div v-if="ticked" class="fp-range-ticks">
      <span
        v-for="t in ticks"
        :key="t.value"
        class="fp-range-tick"
        :class="{ 'fp-range-kept': t.value >= low && t.value <= high }"
        :style="{ left: tickLeft(t.value) }"
        :title="t.title || t.label"
      ><i></i><b>{{ t.label }}</b></span>
    </div>
  </div>
</template>

<script>
/*
 * THE slider of the application: one track, two thumbs, the kept span filled,
 * or one thumb (`single`).
 *
 * The thumb on the side of the track's middle it sits stays on top, so two
 * thumbs pushed together can always be pulled apart again. A drag reports
 * every position (`drag`, for a live preview the host paces); the release
 * reports the last one (`commit`, what the host sends). Both carry
 * ("low" | "high", the number). A thumb stops on the other one, never
 * pushes it (the PO's manager, 29/10: the low end stays where it is when
 * the high one comes down on it); the thumb under the pointer is put back
 * there. Other clamping stays the host's.
 *
 * `ticks` [{value, label, title?}] put one labelled tick per category under
 * the track, lit inside the kept span.
 *
 * The span between the thumbs is a handle too (`band`, on by default; the
 * PO's manager, 28/10): dragged, the whole range slides, low and high
 * together, its width kept and clamped to the track — `drag` and `commit`
 * then carry ("range", [low, high]).
 *
 * `single`: one thumb (`low`, the value), what is kept filled as `fill`
 * says — "left" (the lowest value up to it), "right" (it up to the
 * highest), "none" (the value only): a slicer cut's ≤ / ≥ / =, an opacity,
 * a position. A click on the track moves the thumb there.
 */
export default {
  name: "FpRange",
  inheritAttrs: false,
  props: {
    min: { type: Number, required: true },
    max: { type: Number, required: true },
    step: { type: [Number, String], default: 1 },
    low: { type: Number, required: true },
    high: { type: Number, default: 0 },
    lowTitle: { type: String, default: "" },
    highTitle: { type: String, default: "" },
    ticks: { type: Array, default: () => [] },
    band: { type: Boolean, default: true },
    single: { type: Boolean, default: false },
    fill: { type: String, default: "between" },
  },
  emits: ["drag", "commit"],
  data() {
    return { sliding: null };
  },
  computed: {
    span() {
      return Math.max(1e-12, this.max - this.min);
    },
    lowOnTop() {
      return this.low > (this.min + this.max) / 2;
    },
    fillStyle() {
      const at = ((this.low - this.min) / this.span) * 100;
      if (this.single) {
        if (this.fill === "left") return { left: "0%", width: `${Math.max(0, at)}%` };
        if (this.fill === "right") return { left: `${Math.max(0, at)}%`, width: `${Math.max(0, 100 - at)}%` };
        return { left: `${Math.max(0, at)}%`, width: "0%" };
      }
      const width = ((this.high - this.low) / this.span) * 100;
      return { left: `${Math.max(0, at)}%`, width: `${Math.max(0, width)}%` };
    },
    ticked() {
      return Array.isArray(this.ticks) && this.ticks.length > 0;
    },
    // the grabbable span, inset by a thumb at each end so the thumbs stay
    // reachable; none when the thumbs touch
    bandStyle() {
      const a = (this.low - this.min) / this.span;
      const b = (this.high - this.min) / this.span;
      if (!(b > a)) return null;
      return {
        left: `calc(6px + (100% - 12px) * ${a} + 6px)`,
        width: `max(0px, calc((100% - 12px) * ${b - a} - 12px))`,
      };
    },
  },
  methods: {
    // a thumb's value, stopped on the other thumb: two thumbs do not cross
    read(ev, which) {
      let v = Number(ev.target.value);
      if (!this.single && which === "low" && v > this.high) v = this.high;
      if (!this.single && which === "high" && v < this.low) v = this.low;
      if (Number(ev.target.value) !== v) ev.target.value = String(v);
      return v;
    },
    // the range slid by the pointer's travel, on the step, inside the track
    slid(ev) {
      const s = this.sliding;
      const width = this.$el.getBoundingClientRect().width - 12;
      let d = ((ev.clientX - s.x) / Math.max(1, width)) * this.span;
      const st = Number(this.step) || 0;
      if (st > 0) d = Math.round(d / st) * st;
      d = Math.max(this.min - s.low, Math.min(this.max - s.high, d));
      return [s.low + d, s.high + d];
    },
    slideStart(ev) {
      this.sliding = { x: ev.clientX, low: this.low, high: this.high, last: null };
      if (ev.target.setPointerCapture) ev.target.setPointerCapture(ev.pointerId);
    },
    slideMove(ev) {
      if (!this.sliding) return;
      const r = this.slid(ev);
      const last = this.sliding.last;
      if (last && last[0] === r[0]) return;
      this.sliding.last = r;
      this.$emit("drag", "range", r);
    },
    slideEnd(ev) {
      if (!this.sliding) return;
      const r = this.sliding.last;
      this.sliding = null;
      if (r) this.$emit("commit", "range", r);
    },
    // under the thumb's centre: the track is inset by half a thumb (6 px)
    tickLeft(v) {
      return `calc(6px + (100% - 12px) * ${(v - this.min) / this.span})`;
    },
  },
};
</script>
