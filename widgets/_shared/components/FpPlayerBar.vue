<template>
  <div class="fpb" :class="{ active }">
    <span :title="disabled && !playing ? disabledTitle : null">
      <fp-btn tiny :variant="playing ? 'on' : undefined" :label="playing ? '❚❚' : '▶'"
              :title="playing ? 'Pause: the row keeps what it shows' : playTitle"
              :disabled="disabled && !playing" @click="$emit('play', !playing)" />
    </span>
    <fp-select class="fpb-speed" :model-value="speed" :options="speedOptions" mandatory
               title="Steps per second" @update:model-value="$emit('speed', Number($event))" />
    <fp-btn tiny class="fpb-loop" :variant="loop ? 'on' : undefined" label="⟳"
            :title="loop ? 'Loop: the player starts again at the end (click: stop at the end)'
                         : 'Once: the player stops at the end (click: loop)'"
            @click="$emit('loop', !loop)" />
    <span v-if="active && count > 1" class="fpb-pct" :title="'Step ' + (index + 1) + ' of ' + count">{{ percent }} %</span>
  </div>
</template>

<script>
/*
 * The player bar under a slicer card's slider (the PO's manager, 28/10:
 * not a button that swaps the slider for a player — the slider and its
 * player one under the other). Play starts the card's player on THIS
 * slider from where it stands (a range slides whole, a cut steps from value
 * to value), pause keeps it there; the slider above follows the steps.
 * The manager, 29/10: no range written under the slider (the value is the
 * field above it), the way along shown from 0 to 100 %, and a loop or not.
 * `active`: the card's player is on this slider. `disabled`: nothing to
 * play from there, play greyed with `disabledTitle` (a running player can
 * still be paused).
 */
import FpBtn from "./FpBtn.vue";
import FpSelect from "./FpSelect.vue";

export default {
  name: "FpPlayerBar",
  components: { FpBtn, FpSelect },
  props: {
    active: { type: Boolean, default: false },
    playing: { type: Boolean, default: false },
    speed: { type: Number, default: 5 },
    loop: { type: Boolean, default: true },
    rates: { type: Array, default: () => [1, 2, 5, 10, 20] },
    index: { type: Number, default: 0 },
    count: { type: Number, default: 0 },
    playTitle: { type: String, default: "Play" },
    disabled: { type: Boolean, default: false },
    disabledTitle: { type: String, default: "Nothing to play from here" },
  },
  emits: ["play", "speed", "loop"],
  computed: {
    speedOptions() {
      return (this.rates.length ? this.rates : [1, 2, 5, 10, 20])
        .map((r) => ({ value: r, label: "×" + r, title: r + " steps per second" }));
    },
    percent() {
      return Math.round((100 * this.index) / Math.max(1, this.count - 1));
    },
  },
};
</script>

<style scoped>
.fpb { display: flex; align-items: center; gap: 4px; padding-left: 16px; font-size: 11px; color: #555; }
.fpb-speed { width: 52px; font-size: 11px; flex-shrink: 0; }
.fpb-loop { flex-shrink: 0; }
.fpb-pct { font-weight: 600; color: #333; font-variant-numeric: tabular-nums; white-space: nowrap; }
</style>
