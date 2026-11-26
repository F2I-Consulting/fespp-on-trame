<template>
  <fp-slicer :state="card" :player="player" @edit="$emit('edit', $event)"
             shows="The I/J/K crop of this view's grid: boxes of I, J, K ranges, or cuts along I, J and K."
             gesture="Tick an IJK grid in the tree and show it in this view, and it is cut here.">
    <template #header>
      <!-- copies another view's slicing onto this one -->
      <fp-select v-if="card.target && otherViews.length" class="fsl-copy" v-model="copySource"
                 :options="viewOptions" placeholder="Copy from" mandatory
                 title="Copy another view's slicing of this grid onto this view"
                 @update:model-value="copyFrom($event)" />
    </template>
  </fp-slicer>
</template>

<script>
/*
 * The Geometry slicer of one view (the Slicers card; the PO's manager,
 * 28/10): the shared slicer card (_shared/FpSlicer) on the I, J, K of the
 * view's grid — the Property slicer is the same card on properties. The
 * host (app/features/geometry_slicer) applies the gestures; this adds the
 * copy from another view.
 */
import FpSelect from "../../../_shared/components/FpSelect.vue";
import FpSlicer from "../../../_shared/components/FpSlicer.vue";

export default {
  name: "SlicersPanel",
  components: { FpSelect, FpSlicer },
  props: {
    viewId: { type: String, default: "" },
    card: { type: Object, default: () => ({}) },
    player: { type: Object, default: () => ({}) },
    views: { type: Array, default: () => [] },
  },
  emits: ["edit", "copy-from"],
  data() {
    return { copySource: "" };
  },
  computed: {
    otherViews() {
      return (this.views || []).filter((v) => v && v.id && v.id !== this.viewId && !v.globe);
    },
    viewOptions() {
      return this.otherViews.map((v) => ({
        value: v.id, label: v.title || v.id, title: "Copy the slicing of " + (v.title || v.id),
      }));
    },
  },
  methods: {
    // the menu is a verb, not a value: back to "Copy from…" once sent
    copyFrom(id) {
      if (!id) return;
      this.$emit("copy-from", id);
      this.$nextTick(() => { this.copySource = ""; });
    },
  },
};
</script>

<style>
@import "../../../_shared/panel.css";
</style>

<style scoped>
.fsl-copy { font-size: 11px; max-width: 110px; flex-shrink: 0; }
</style>
