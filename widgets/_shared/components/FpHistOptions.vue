<template>
  <span class="fp-hist-options" v-bind="$attrs">
    <component :is="picker" :model-value="opts.mode || 'bars'" :options="MODES"
               title="How the distribution is drawn"
               @update:model-value="set('mode', $event)" />
    <label class="fp-lab" :title="BINS_TIP">Bins
      <fp-num :model-value="Number(opts.nbins) || 50" :min="5" :max="500" integer size="sm"
              :title="BINS_TIP" @update:model-value="set('nbins', $event)" />
    </label>
    <label class="fp-check" title="Logarithmic Y axis">
      <input type="checkbox" :checked="!!opts.log_y" @change="set('log_y', $event.target.checked)" />
      <span>Log Y</span>
    </label>
    <slot />
    <label class="fp-check" title="Cumulative distribution">
      <input type="checkbox" :checked="!!opts.cumulative" @change="set('cumulative', $event.target.checked)" />
      <span>Cumulative</span>
    </label>
    <component :is="picker" :model-value="opts.norm || 'count'" :options="NORMS"
               title="What the height of a class means"
               @update:model-value="set('norm', $event)" />
  </span>
</template>

<script>
/*
 * The options of a histogram, one form wherever a histogram is drawn: its
 * words and tooltips live here, so two panels cannot read differently. The
 * values are the host's: `opts` in, `set` [name, value] out. Its controls
 * stand in the host's bar, one beside the other (panel.css); an option only
 * that host has goes in the slot.
 *
 * `compact` draws the two choices as lists, for a bar that shares its width;
 * else they are strips, every option in sight.
 */
import FpNum from "./FpNum.vue";
import FpSeg from "./FpSeg.vue";
import FpSelect from "./FpSelect.vue";

const MODES = [
  { value: "bars", label: "Bars", title: "One bar per class" },
  { value: "line", label: "Line", title: "A step line through the classes" },
  { value: "curve", label: "Curve", title: "A smoothed curve through the classes" },
];
const NORMS = [
  { value: "count", label: "Count", title: "The number of values in each class" },
  { value: "density", label: "Density", title: "The share of the values over the class width: the area is 1" },
  { value: "probability", label: "Probability", title: "The share of the values in each class: they sum to 1" },
];
const BINS_TIP = "How many classes the values are counted in (5 to 500)";

export default {
  name: "FpHistOptions",
  inheritAttrs: false,
  components: { FpNum },
  props: {
    // {mode, nbins, log_y, cumulative, norm}
    opts: { type: Object, default: () => ({}) },
    compact: { type: Boolean, default: false },
  },
  emits: ["set"],
  data() {
    return { MODES, NORMS, BINS_TIP };
  },
  computed: {
    picker() {
      return this.compact ? FpSelect : FpSeg;
    },
  },
  methods: {
    set(name, value) {
      this.$emit("set", [name, value]);
    },
  },
};
</script>
