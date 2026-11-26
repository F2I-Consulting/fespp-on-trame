<template>
  <!-- What a TDLaw is: its name and where it stands. The head of a track, and
       all there is of a new TDLaw until its easting and northing are entered. -->
  <div class="tlh">
    <div class="tlh-row" :title="title" @click="$emit('active')">
      <input class="fp-input tlh-name" :value="name" :placeholder="namePlaceholder" :title="title + ' — type to name it'"
             @focus="$emit('active')" @change="$emit('rename', $event.target.value)" />
      <span v-if="why" class="tlh-why" :title="'Left out of the model: ' + why">!</span>
      <span v-if="outside" class="tlh-why"
            title="Placed outside the zone: the velocity model grows past it to take it in, the zone stays">⇲</span>
      <fp-btn v-if="placeable && (x == null || y == null)" tiny class="tlh-place" label="Place"
              title="At the centre of the velocity model, or the nearest free place inside it: the TDLaw then starts from its law there"
              @click.stop="$emit('place', { at: 'free' })" />
      <fp-btn v-if="removable" tiny variant="bare" class="tlh-x" label="×"
              title="Remove this TDLaw"
              @click.stop="$emit('remove')" />
    </div>
    <div class="tlh-row" @click="$emit('active')">
      <template v-for="k in [0, 1]" :key="k">
        <span class="tlh-ax" :title="axes[k]">{{ axisShort(k) }}</span>
        <fp-num-pick class="tlh-at" size="sm" :digits="0" :model-value="k ? y : x" :placeholder="axisWord(k)"
                     :title="axes[k] + ' of the TDLaw'" :suggestions="suggestions[k]"
                     @update:model-value="$emit('place', k ? { y: $event } : { x: $event })" />
      </template>
    </div>
  </div>
</template>

<script>
import FpBtn from "../../../_shared/components/FpBtn.vue";
import FpNumPick from "../../../_shared/components/FpNumPick.vue";

export default {
  name: "LawHead",
  components: { FpBtn, FpNumPick },
  props: {
    name: { type: String, default: "" },
    namePlaceholder: { type: String, default: "" },
    title: { type: String, default: "" },
    // where it stands (null: not placed), the axes as the CRS names them
    x: { type: Number, default: null },
    y: { type: Number, default: null },
    axes: { type: Array, default: () => ["Easting", "Northing"] },
    // the values offered for each, on a click in its field
    suggestions: { type: Array, default: () => [[], []] },
    why: { type: String, default: "" },
    outside: { type: Boolean, default: false },
    placeable: { type: Boolean, default: false },
    removable: { type: Boolean, default: false },
  },
  // `place`: {x} | {y} | {at: "free"}
  emits: ["active", "rename", "place", "remove"],
  methods: {
    axisWord(k) { return String(this.axes[k] || (k ? "Northing" : "Easting")).split(" (")[0]; },
    // "E (m)": the axis's letter and its unit
    axisShort(k) {
      const unit = (String(this.axes[k] || "").match(/\(([^)]*)\)/) || [null, "m"])[1];
      return `${this.axisWord(k).charAt(0).toUpperCase()} (${unit})`;
    },
  },
};
</script>

<style scoped>
.tlh { display: flex; flex-direction: column; gap: 2px; font-size: 11px; }
.tlh-row { display: flex; align-items: center; gap: 2px; min-height: 22px; }
.tlh-name { flex: 0 1 110px; min-width: 60px; font-weight: 600; font-size: 11px; padding: 1px 4px; }
.tlh-ax { font-size: 10px; opacity: 0.7; white-space: nowrap; }
/* wide enough for seven digits of a projected northing */
.tlh-row :deep(.tlh-at) { width: 56px; box-sizing: border-box; }
.tlh-why { color: #a85d00; font-weight: 700; padding: 0 3px; cursor: help; }
/* on the name's row, at its right: the fields' row has no room for it */
.tlh-place { margin-left: auto; }
.tlh-x { margin-left: auto; opacity: 0.55; }
.tlh-place + .tlh-x { margin-left: 2px; }
.tlh-x:hover { opacity: 1; }
</style>
