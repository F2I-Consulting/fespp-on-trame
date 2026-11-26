<template>
  <span class="fp-z">
    <span class="fp-z-lab" :title="title">Z</span>
    <fp-range class="fp-z-slider" single fill="left" :min="min" :max="max" :low="onSlider" :low-title="title"
              @drag="(_w, v) => $emit('update:modelValue', v)" @commit="(_w, v) => $emit('update:modelValue', v)" />
    <span class="fp-z-lab">×</span>
    <fp-num size="sm" :digits="digits" :min="typedMin" :max="typedMax" :model-value="modelValue"
            :style="{ width: numWidth }"
            :title="title + ': type any value up to ' + typedMax"
            @update:model-value="$emit('update:modelValue', $event)" />
  </span>
</template>

<script>
/*
 * A vertical exaggeration, on a dark title bar: slid, or typed for a value the
 * slider does not stop at. The field is as wide as the widest value it can
 * show: the integer digits of `typedMax`, the point and `digits` decimals.
 */
import FpNum from "./FpNum.vue";
import FpRange from "./FpRange.vue";

export default {
  name: "FpZScale",
  components: { FpNum, FpRange },
  props: {
    modelValue: { type: Number, default: 1 },
    title: { type: String, required: true },
    // where the slider stops
    min: { type: Number, default: 1 },
    max: { type: Number, default: 50 },
    // what can be typed
    typedMin: { type: Number, default: 0.01 },
    typedMax: { type: Number, default: 100 },
    // the decimals shown
    digits: { type: Number, default: 2 },
  },
  emits: ["update:modelValue"],
  computed: {
    onSlider() {
      return Math.min(this.max, Math.max(this.min, this.modelValue));
    },
    numWidth() {
      const whole = String(Math.floor(Math.abs(this.typedMax))).length;
      const chars = whole + (this.digits > 0 ? 1 + this.digits : 0);
      return `calc(${chars}ch + 10px)`;
    },
  },
};
</script>

<style scoped>
.fp-z { display: inline-flex; align-items: center; gap: 4px; }
.fp-z-lab { font-size: 11px; font-weight: 700; color: rgba(255, 255, 255, 0.85); white-space: nowrap; }
.fp-z-slider { flex: 0 0 64px; width: 64px; }
/* in a card's title bar short of room, the field alone */
@container (max-width: 170px) {
  .fp-z-slider { display: none; }
}
.fp-z :deep(.fp-range-track) { background: rgba(255, 255, 255, 0.35); }
.fp-z :deep(.fp-range-fill) { background: #b9ddf6; }
.fp-z :deep(input[type="range"]::-webkit-slider-thumb) { background: #b9ddf6; }
.fp-z :deep(input[type="range"]::-moz-range-thumb) { background: #b9ddf6; }
/* it does not give way in a bar short of room: the digits stay readable */
.fp-z :deep(.fp-num) {
  flex: 0 0 auto; height: 22px; padding: 0 3px; box-sizing: border-box; text-align: right;
  font-variant-numeric: tabular-nums;
  color: #fff; background: rgba(255, 255, 255, 0.1);
  border: 1px solid rgba(255, 255, 255, 0.45); border-radius: 3px;
}
.fp-z :deep(.fp-num:focus-visible) { outline: 1px solid rgba(255, 255, 255, 0.7); outline-offset: -1px; }
</style>
