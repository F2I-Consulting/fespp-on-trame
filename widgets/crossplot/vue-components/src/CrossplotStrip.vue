<template>
  <div class="fxp-strip">
    <!-- in the bar of the host's chart: its plot stands level with its neighbours' -->
    <teleport :to="bar || 'body'" :disabled="!bar">
    <div class="fxp-line">
      <span class="fxp-tag">Color by</span>
      <fp-select class="fxp-prop" :model-value="color || ''" :options="propOptions" placeholder="none"
                 title="Color by — the property whose value colors each point; a categorical one gives one trace per category"
                 @update:model-value="$emit('set', ['color', $event || null])" />

      <label class="fp-check" title="Logarithmic X axis">
        <input type="checkbox" :checked="!!logx"
               @change="$emit('set', ['logx', $event.target.checked])" />
        <span>log X</span>
      </label>
      <label class="fp-check" title="Logarithmic Y axis">
        <input type="checkbox" :checked="!!logy"
               @change="$emit('set', ['logy', $event.target.checked])" />
        <span>log Y</span>
      </label>

      <!-- what a box or a lasso lit, or why it lights nothing -->
      <fp-chip v-if="meta && meta.selected" class="fxp-badge" variant="accent"
               :text="meta.selected" :title="meta.selected" />
    </div>
    </teleport>
  </div>
</template>

<script>
/*
 * The control strip of the cross-plot: what its charts share — the colour and
 * the scales — on ONE line, in the bar of the host's chart. Pure display: every
 * edit leaves as set([key, value]) and the host owns the routing.
 */
import FpChip from "../../../_shared/components/FpChip.vue";
import FpSelect from "../../../_shared/components/FpSelect.vue";

export default {
  name: "CrossplotStrip",
  components: { FpChip, FpSelect },
  props: {
    // the server sends null for "no property picked", never "" — typing
    // this as String makes Vue warn and coerce on every publish
    color: { default: null },
    logx: { type: Boolean, default: false },
    logy: { type: Boolean, default: false },
    choices: { type: Array, default: () => [] },
    meta: { type: Object, default: () => ({}) },
  },
  emits: ["set"],
  data() {
    return { bar: null };
  },
  mounted() {
    const chart = this.$el.closest(".fcp-chart");
    this.bar = chart ? chart.querySelector(".fp-subbar") : null;
  },
  computed: {
    // {title, value} from the host, {value, label, title} for the field
    propOptions() {
      return (this.choices || []).map((c) => ({ value: c.value, label: c.title, title: c.title }));
    },
  },
};
</script>

<style scoped>
.fxp-strip:empty { display: none; }
.fxp-strip {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 4px 8px;
  border-bottom: 1px solid var(--fp-line);
  background: var(--fp-bar-bg);
  font-family: var(--fp-font);
  font-size: var(--fp-size);
}
.fxp-line { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; min-height: 30px; }
.fxp-tag { font-size: var(--fp-size-small); color: var(--fp-ink-soft); white-space: nowrap; }
.fxp-prop { flex: 1 1 150px; max-width: 230px; }
.fxp-badge { font-variant-numeric: tabular-nums; }
</style>
