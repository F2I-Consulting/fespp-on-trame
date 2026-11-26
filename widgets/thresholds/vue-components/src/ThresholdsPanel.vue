<template>
  <fp-slicer :state="card" :player="player" @edit="$emit('edit', $event)"
             shows="The cells kept by the values of a property."
             gesture="Tick a property of a grid, a surface or a point set in the tree." />
</template>

<script>
/*
 * The Property slicer of one view (the Thresholds card; the PO's manager,
 * 28/10): the shared slicer card (_shared/FpSlicer) on the properties
 * added to it — the Geometry slicer is the same card on I, J, K. The host
 * (app/features/property_slicer) applies the gestures to the view's
 * threshold chain.
 */
import FpSlicer from "../../../_shared/components/FpSlicer.vue";

export default {
  name: "ThresholdsPanel",
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
