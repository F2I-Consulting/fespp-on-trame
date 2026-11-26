<template>
  <div
    class="fp-transport"
    :class="{ 'fp-transport-stacked': slider === 'below' }"
    :data-fp-incomplete="incomplete ? '' : null"
    v-bind="$attrs"
  >
    <div class="fp-transport-row">
      <slot name="lead" />
      <fp-btn tiny icon label="⏮" :disabled="atFirst"
              :title="atFirst ? 'Already at the first ' + what : 'First ' + what"
              @click="go(0)" />
      <fp-btn tiny icon label="◀" :disabled="atFirst"
              :title="atFirst ? 'Already at the first ' + what : 'Previous ' + what"
              @click="go(index - 1)" />
      <template v-if="player">
        <fp-btn v-if="!playing" tiny icon label="▶"
                :title="playTitle || 'Play the ' + whats + ' in a loop'"
                @click="$emit('play', true)" />
        <fp-btn v-else tiny icon variant="on" label="■"
                :title="stopTitle || 'Stop playing'"
                @click="$emit('play', false)" />
      </template>
      <fp-btn tiny icon label="▶" :disabled="atLast"
              :title="atLast ? 'Already at the last ' + what : 'Next ' + what"
              @click="go(index + 1)" />
      <fp-btn tiny icon label="⏭" :disabled="atLast"
              :title="atLast ? 'Already at the last ' + what : 'Last ' + what"
              @click="go(count - 1)" />
      <fp-select v-if="player" class="fp-transport-speed" :model-value="speed || 1"
                 :options="speeds" :title="speedTitle || 'Play speed'"
                 @update:model-value="$emit('speed', Number($event))" />
      <slot />
      <fp-range v-if="slider === 'inline'" class="fp-transport-slider" single fill="left"
                :min="0" :max="Math.max(0, count - 1)" :low="index" :low-title="sliderTitle"
                @drag="(_w, v) => drag(v)" @commit="(_w, v) => release(v)" />
      <span class="fp-transport-count" :title="'The ' + what + ' shown, of ' + count">{{ index + 1 }} / {{ count }}</span>
    </div>
    <fp-range v-if="slider === 'below'" class="fp-transport-slider" single fill="left"
              :min="0" :max="Math.max(0, count - 1)" :low="index" :low-title="sliderTitle"
              @drag="(_w, v) => drag(v)" @commit="(_w, v) => release(v)" />
  </div>
</template>

<script>
/*
 * The one transport: stepping through time steps and realizations.
 *
 * The same buttons in the same order everywhere — first, previous, play or
 * stop (a `player` only), next, last — then the speed (a `player` only, the
 * same five speeds everywhere), what the host adds in the default slot (a
 * label, an index picker), and the position as "n / count". A disabled step
 * says why ("Already at the first time step"). The slider moves on RELEASE
 * (`change`, never `input`): one step per gesture, not one per pixel of the
 * drag, each of which would read data on the server.
 *
 * It counts POSITIONS, 0 to count - 1: a host whose indices are sparse
 * (the loaded realizations) maps the position it gets back in `step`.
 *
 * `live`: the slider steps WHILE it is dragged, for a host whose step is
 * cheap and whose movement must be fluid (the value player of the
 * Thresholds card: one threshold range, 16 ms on 926 808 cells). At most
 * one step every LIVE_MS, the last position always sent on release.
 * `rates`: the host's own speeds, when the five shared ones do not fit.
 */
import FpBtn from "./FpBtn.vue";
import FpRange from "./FpRange.vue";
import FpSelect from "./FpSelect.vue";

const RATES = [0.25, 0.5, 1, 2, 5];
// a live slider sends at most one step per LIVE_MS while it is dragged
const LIVE_MS = 50;

export default {
  name: "FpTransport",
  inheritAttrs: false,
  components: { FpBtn, FpRange, FpSelect },
  props: {
    // the position shown and the number of positions
    index: { type: Number, required: true },
    count: { type: Number, required: true },
    // what one position is, in the singular ("time step") and, when the
    // plural is not that plus "s", in the plural
    unit: { type: String, required: true },
    units: { type: String, default: "" },
    // play / stop and the speed
    player: { type: Boolean, default: false },
    playing: { type: Boolean, default: false },
    speed: { type: Number, default: 1 },
    playTitle: { type: String, default: "" },
    stopTitle: { type: String, default: "" },
    speedTitle: { type: String, default: "" },
    // the slider under the row, or in it before the count
    slider: {
      type: String,
      default: "below",
      validator: (v) => v === "below" || v === "inline",
    },
    // the slider steps while dragged (throttled), not only on release
    live: { type: Boolean, default: false },
    // the speeds offered, in positions per second
    rates: { type: Array, default: () => RATES },
  },
  emits: ["step", "play", "speed"],
  computed: {
    what() {
      return this.unit || "position (no unit given — a defect)";
    },
    whats() {
      return this.units || this.what + "s";
    },
    atFirst() {
      return this.index <= 0;
    },
    atLast() {
      return this.index >= this.count - 1;
    },
    speeds() {
      return (this.rates && this.rates.length ? this.rates : RATES).map((s) => ({
        value: s,
        label: "×" + s,
        title: s === 1 ? "One " + this.what + " per second" : s + " " + this.whats + " per second",
      }));
    },
    sliderTitle() {
      return "The " + this.what + " shown, " + (this.live ? "follows the slider" : "moved on release");
    },
    incomplete() {
      return !this.unit || (this.slider !== "below" && this.slider !== "inline");
    },
  },
  beforeUnmount() {
    clearTimeout(this.liveTimer);
  },
  methods: {
    clamp(pos) {
      return Math.max(0, Math.min(this.count - 1, Math.round(Number(pos) || 0)));
    },
    go(pos) {
      const p = this.clamp(pos);
      if (p !== this.index) this.$emit("step", p);
    },
    // a live slider: one step now, then at most one per LIVE_MS, the
    // position the hand is on when the wait ends
    drag(pos) {
      if (!this.live) return;
      this.liveWant = this.clamp(pos);
      if (this.liveTimer) return;
      this.sendLive();
      this.liveTimer = setTimeout(() => {
        this.liveTimer = null;
        if (this.liveWant !== this.liveSent) this.sendLive();
      }, LIVE_MS);
    },
    sendLive() {
      this.liveSent = this.liveWant;
      this.$emit("step", this.liveWant);
    },
    release(pos) {
      if (!this.live) return this.go(pos);
      clearTimeout(this.liveTimer);
      this.liveTimer = null;
      const p = this.clamp(pos);
      if (p !== this.liveSent || p !== this.index) {
        this.liveSent = p;
        this.$emit("step", p);
      }
    },
  },
};
</script>
