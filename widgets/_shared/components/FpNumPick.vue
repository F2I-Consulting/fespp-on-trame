<template>
  <span class="fp-numpick">
    <fp-num v-bind="$attrs" :model-value="modelValue"
            @focus="show" @click="show" @blur="hide" @keydown.esc="hide"
            @update:model-value="commit" />
    <Teleport v-if="open" to="body">
      <div class="fp-numpick-list" role="listbox" :style="place">
        <button v-for="v in suggestions" :key="v" type="button" tabindex="-1" role="option"
                class="fp-numpick-item" @mousedown.prevent="commit(v)">{{ fmtExact(v) }}</button>
      </div>
    </Teleport>
  </span>
</template>

<script>
/*
 * A number the reader types (FpNum) or picks among values offered: the list
 * opens at the first click in the field, where a <datalist> waits for a
 * second one, and is drawn on the page, so no card clips it. Any other value
 * can still be typed. With nothing to offer it is a plain FpNum.
 */
import { fmtExact } from "../numfmt.js";
import { popPlace } from "../popPlace.js";
import FpNum from "./FpNum.vue";

const ROW_H = 22;
const LEAST_W = 92;

export default {
  name: "FpNumPick",
  components: { FpNum },
  inheritAttrs: false,
  props: {
    modelValue: { type: Number, default: null },
    suggestions: { type: Array, default: () => [] },
  },
  emits: ["update:modelValue"],
  data() {
    return { open: false, place: {} };
  },
  methods: {
    fmtExact,
    show() {
      if (this.open || !(this.suggestions && this.suggestions.length)) return;
      const width = Math.max(this.$el.getBoundingClientRect().width, LEAST_W);
      this.place = popPlace(this.$el, width, this.suggestions.length * ROW_H + 8);
      this.open = true;
    },
    hide() {
      this.open = false;
    },
    commit(value) {
      this.open = false;
      this.$emit("update:modelValue", value);
    },
  },
};
</script>

<style scoped>
.fp-numpick { display: inline-flex; }
.fp-numpick-list {
  position: fixed; z-index: 4000; box-sizing: border-box; padding: 4px 0; display: flex; flex-direction: column;
  background: var(--fp-bg, #fff); border: 1px solid var(--fp-line, #ddd); border-radius: 4px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.18);
}
.fp-numpick-item {
  height: 22px; padding: 0 8px; border: none; background: none; cursor: pointer; text-align: right;
  font: 12px system-ui, sans-serif; font-variant-numeric: tabular-nums; color: var(--fp-ink, #222);
}
.fp-numpick-item:hover { background: var(--fp-accent-soft, #e3eef6); }
</style>
