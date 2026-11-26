<template>
  <span class="fcp-legend">
    <template v-if="baseline">
      <span class="fcp-cell-base">baseline</span>
      <span class="fcp-cell-pos">above baseline</span>
      <span class="fcp-cell-neg">below baseline</span>
      <span class="fcp-cell-eq">equal</span>
    </template>
    <template v-else>
      <span class="fcp-cell-min">min</span>
      <span class="fcp-cell-max">max</span>
    </template>
  </span>
</template>

<script>
/* What the colours of the matrix's cells say: against the baseline when the
   kind has one, else the two ends of each metric. */
export default {
  name: "CompareLegend",
  props: {
    baseline: { type: Boolean, default: false },
  },
};
</script>

<style scoped>
.fcp-legend { display: inline-flex; flex-wrap: wrap; gap: 6px; align-items: center; font-size: var(--fp-size-small); }
.fcp-legend > span { padding: 0 6px; border-radius: 3px; }
</style>
