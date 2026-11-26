<template>
  <!-- Inside the Statistics view: the frame is that view's, whose table says the
       counts. The figures are the grid's, under the empty state that says what
       would be drawn. -->
  <div class="fxp">
    <crossplot-strip :color="color" :logx="logx" :logy="logy" :choices="choices" :meta="meta"
                     @set="$emit('set', $event)" />
    <crossplot-grid :charts="charts" :figures="figures" :focus="focus" :meta="meta"
                    @set="$emit('set', $event)" @select="$emit('select', $event)" />
  </div>
</template>

<script>
/*
 * The cross-plot of the Statistics view: the strip of what its charts share
 * (colour, scales), then the charts, each under its own caption line. Its X
 * and its Y are the host's, picked over the chart among the rows of the
 * matrix. Pure display: the figures, the subsampling, the pinned snapshots and
 * the selection round-trip are computed in engine/crossplot_dispatch; each
 * chart is a plotly figure of its own (`figures`, filled in as they are read),
 * drawn by CrossplotGrid.
 *   props in  — color, logx / logy, choices, meta, charts, figures, focus
 *   events out — set([key, value]), one channel for every control;
 *               select({chart, range, lasso} | null), a box or lasso on
 *               one chart (its geometry only), or the double-click that
 *               clears it
 */
import CrossplotGrid from "./CrossplotGrid.vue";
import CrossplotStrip from "./CrossplotStrip.vue";

export default {
  name: "CrossplotControls",
  components: { CrossplotGrid, CrossplotStrip },
  props: {
    color: { default: null },
    logx: { type: Boolean, default: false },
    logy: { type: Boolean, default: false },
    choices: { type: Array, default: () => [] },
    meta: { type: Object, default: () => ({}) },
    charts: { type: Array, default: () => [] },
    figures: { type: Array, default: () => [] },
    focus: { default: null },
  },
  emits: ["set", "select"],
};
</script>

<style>
@import "../../../_shared/panel.css";
</style>

<style scoped>
.fxp { display: flex; flex-direction: column; flex: 1 1 auto; min-height: 0; }
</style>
