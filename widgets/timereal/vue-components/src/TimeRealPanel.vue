<template>
  <fp-slicer :state="card" :player="player" @edit="$emit('edit', $event)"
             shows="The time step this view is at, the realization each multi-realization property shows, the component each vector property is drawn by: a cut of one value each, stepped by hand or by the player."
             gesture="Activate a time series, a multi-realization property or a vector property in the tree, and its row is here." />
</template>

<script>
/*
 * The Time & Realizations card of one view (the PO, 29/10: the same card
 * as the slicers): the shared slicer card (_shared/FpSlicer) on the view's
 * time step, its realizations and its vector components — a cut of one
 * value each, the player stepping it, looping or not. The host
 * (app/features/timereal_slicer) applies the gestures to the view.
 */
import FpSlicer from "../../../_shared/components/FpSlicer.vue";

export default {
  name: "TimeRealPanel",
  components: { FpSlicer },
  props: {
    viewId: { type: String, default: "" },
    card: { type: Object, default: () => ({}) },
    player: { type: Object, default: () => ({}) },
  },
  emits: ["edit"],
};
</script>

<style>
@import "../../../_shared/panel.css";
</style>
