<template>
  <span class="fcp-row-tools">
    <fp-btn v-if="row.pinned" variant="bare" icon title="Remove this pinned row"
            @click="$emit('set', ['unpin', rowId])">
      <v-icon size="15">mdi-pin-off-outline</v-icon>
    </fp-btn>
    <fp-btn v-else-if="pinnable" variant="bare" icon
            title="Pin a copy of this row as it is read now — the copy keeps this realization and time step, this row moves on"
            @click="$emit('set', ['pin', rowId])">
      <v-icon size="15">mdi-pin-outline</v-icon>
    </fp-btn>
  </span>
</template>

<script>
/*
 * The button beside a row's name: its pin, when it has a realization or a
 * time step to keep (a following row has neither).
 */
import FpBtn from "../../../_shared/components/FpBtn.vue";
import { pinnable } from "./rowActs.js";

export default {
  name: "CompareRowTools",
  components: { FpBtn },
  props: {
    rowId: { type: String, required: true },
    row: { type: Object, required: true },
  },
  emits: ["set"],
  computed: {
    pinnable() {
      return pinnable(this.row);
    },
  },
};
</script>

<style scoped>
.fcp-row-tools { display: inline-flex; flex: 0 0 auto; align-items: center; gap: 2px; }
</style>
