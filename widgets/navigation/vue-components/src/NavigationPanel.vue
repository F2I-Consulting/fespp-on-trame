<template>
  <div class="fnav">
    <!-- FRAMING: what the camera looks at -->
    <div class="fnav-section">
      <div class="fnav-label">Framing</div>
      <div class="fnav-row">
        <fp-btn class="fnav-wide" label="Reset" title="Fit everything loaded in this view"
                @click="$emit('reset')" />
        <fp-btn class="fnav-wide" label="Frame object" :disabled="!hasActive"
                :title="hasActive ? 'Frame the object active in the tree'
                                  : 'Activate an object in the tree first'"
                @click="$emit('frame')" />
      </div>
    </div>

    <!-- PIVOT: rotation turns around what you clicked -->
    <div class="fnav-section">
      <div class="fnav-label">Picked cells</div>
      <div class="fnav-row">
        <fp-btn class="fnav-wide" label="Center here" :disabled="!hasPick"
                :title="hasPick ? 'Rotation turns around the picked cells'
                                : 'Pick a cell first (hand or frustum tool)'"
                @click="$emit('center', false)" />
        <fp-btn class="fnav-wide" label="Zoom here" :disabled="!hasPick"
                :title="hasPick ? 'Move the camera in on the picked cells'
                                : 'Pick a cell first (hand or frustum tool)'"
                @click="$emit('center', true)" />
      </div>
      <div v-if="!hasPick" class="fnav-hint">
        Use the hand or frustum tool, then come back.
      </div>
    </div>

    <!-- AXIS PRESETS: both signs of each axis (ParaView only offers the positive ones) -->
    <div class="fnav-section">
      <div class="fnav-label">Look along</div>
      <div class="fnav-row">
        <fp-btn v-for="a in axes" :key="a" class="fnav-axis" :label="a"
                :title="'Look along ' + a" @click="$emit('axis', a)" />
      </div>
    </div>

    <!-- DISPLAY: projection, rotation-centre cross, graduated axes grid -->
    <div class="fnav-section">
      <label class="fnav-check" title="Parallel projection keeps two equal
thicknesses equal on screen; perspective makes the near one look bigger.">
        <input type="checkbox" :checked="!!parallel"
               @change="$emit('projection', $event.target.checked)" />
        <span>Parallel projection</span>
      </label>
      <label class="fnav-check" title="The little cross marking the point the
view rotates around. Right-click the scene → Set rotation centre here to move it.">
        <input type="checkbox" :checked="!!pivotShown"
               @change="$emit('pivot-shown', $event.target.checked)" />
        <span>Show rotation center</span>
      </label>
      <label class="fnav-check" title="A box around everything shown, its edges graduated
in the units of the file (metres, feet) along X, Y and Z: the scale and the
orientation of the scene. The Z graduations read true depths whatever the
vertical exaggeration.">
        <input type="checkbox" :checked="!!axesGrid"
               @change="$emit('axes-grid', $event.target.checked)" />
        <span>Axes grid (scale)</span>
      </label>
    </div>

    <!-- feedback of the last action: plain information, so a text line rather
         than a coloured alert band -->
    <div v-if="note" class="fp-sum fnav-note">{{ note }}</div>
  </div>
</template>

<script>
import FpBtn from "../../../_shared/components/FpBtn.vue";

export default {
  name: "NavigationPanel",
  components: { FpBtn },
  props: {
    hasPick: { type: Boolean, default: false },
    hasActive: { type: Boolean, default: false },
    parallel: { type: Boolean, default: false },
    pivotShown: { type: Boolean, default: false },
    axesGrid: { type: Boolean, default: false },
    note: { type: String, default: "" },
  },
  emits: ["reset", "axis", "center", "frame", "projection", "pivot-shown", "axes-grid"],
  data() {
    return { axes: ["+X", "-X", "+Y", "-Y", "+Z", "-Z"] };
  },
};
</script>

<style>
@import "../../../_shared/panel.css";
</style>

<style scoped>
.fnav {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 8px;
  font-size: 13px;
}
.fnav-section {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.fnav-label {
  font-size: 11px;
  text-transform: uppercase;
  font-weight: 600;
  color: #666;
  letter-spacing: 0.03em;
}
.fnav-row {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.fnav-wide {
  flex: 1 1 96px;
}
.fnav-axis {
  flex: 0 0 auto;
  min-width: 34px;
  font-variant-numeric: tabular-nums;
}
.fnav-check {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
}
.fnav-hint,
.fnav-note {
  font-size: 11px;
  line-height: 1.3;
}
.fnav-hint {
  color: #888;
}
.fnav-note {
  border-top: 1px solid #eee;
  padding-top: 6px;
}
</style>
