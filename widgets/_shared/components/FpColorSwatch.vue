<template>
  <span class="fp-cswatch" v-bind="$attrs">
    <button ref="button" type="button" class="fp-cswatch-btn" :title="title" :aria-label="title"
            :aria-expanded="open ? 'true' : 'false'" @click="toggle">
      <span class="fp-cswatch-fill" :style="{ background: fill }"></span>
    </button>
    <Teleport to="body">
      <template v-if="open">
        <div class="fp-cswatch-back" @click="close"></div>
        <div class="fp-cswatch-pop" :style="place">
          <div class="fp-cswatch-title">{{ label }}</div>
          <fp-color-picker :color="color" :alpha="alpha" :label="label" :alpha-label="label + ' opacity'"
                           @commit-color="$emit('commit-color', $event)"
                           @commit-alpha="$emit('commit-alpha', $event)" />
        </div>
      </template>
    </Teleport>
  </span>
</template>

<script>
/*
 * A colour in a list or a row, where the open palette (FpColorPicker) would
 * take too much room: a swatch of the colour and its opacity, the palette
 * opening over the page on a click. It is drawn on the page itself, so a
 * scrolling list or a card never clips it. A click beside it or Escape
 * closes it; `commit-color` ("#rrggbb") and `commit-alpha` (0..1) are the
 * palette's. `color` and `alpha` are the host's.
 */
import { onEscape } from "../escape.js";
import { popPlace } from "../popPlace.js";
import FpColorPicker from "./FpColorPicker.vue";

const POP_W = 216;
const POP_H = 232;

export default {
  name: "FpColorSwatch",
  components: { FpColorPicker },
  inheritAttrs: false,
  props: {
    color: { type: String, default: "#cccccc" },
    alpha: { type: Number, default: 1 },
    // what the colour is of, heading the palette
    label: { type: String, default: "" },
    title: { type: String, default: "" },
  },
  emits: ["commit-color", "commit-alpha"],
  data() {
    return { open: false, place: {} };
  },
  computed: {
    // #rrggbbaa: the swatch shows the opacity over its checkerboard
    fill() {
      const a = Math.round(Math.min(1, Math.max(0, Number(this.alpha))) * 255);
      return String(this.color).slice(0, 7) + a.toString(16).padStart(2, "0");
    },
  },
  beforeUnmount() {
    this.close();
  },
  methods: {
    toggle() {
      if (this.open) {
        this.close();
        return;
      }
      this.place = popPlace(this.$refs.button, POP_W, POP_H);
      this.open = true;
      this._unEscape = onEscape(() => this.close());
    },
    close() {
      this.open = false;
      if (this._unEscape) this._unEscape();
      this._unEscape = null;
    },
  },
};
</script>

<style scoped>
.fp-cswatch { position: relative; display: inline-flex; flex: 0 0 auto; }
/* checkerboard under the fill so the opacity reads */
.fp-cswatch-btn {
  width: 26px; height: 22px; padding: 0; overflow: hidden; cursor: pointer;
  border: 1px solid var(--fp-btn-line, #bbb); border-radius: 3px;
  background: repeating-conic-gradient(#ccc 0% 25%, #fff 0% 50%) 0 0 / 8px 8px;
}
.fp-cswatch-btn:focus-visible { outline: 2px solid var(--fp-accent, #00436d); outline-offset: 1px; }
.fp-cswatch-fill { display: block; width: 100%; height: 100%; }
.fp-cswatch-back { position: fixed; inset: 0; z-index: 3999; }
.fp-cswatch-pop {
  position: fixed; z-index: 4000; display: flex; flex-direction: column; gap: 6px; padding: 8px;
  box-sizing: border-box; font: 12px system-ui, sans-serif; background: var(--fp-bg, #fff);
  border: 1px solid var(--fp-line, #ddd); border-radius: 4px; box-shadow: 0 4px 12px rgba(0, 0, 0, 0.18);
}
.fp-cswatch-title { font-size: 11px; color: var(--fp-ink-soft, #555); }
</style>
