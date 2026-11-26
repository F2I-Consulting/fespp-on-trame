<template>
  <fp-select v-if="options.length" class="fcp-axis-sel" :class="{ 'fcp-axis-ts': isTime }"
             :model-value="named ?? ''" :options="options" :placeholder="placeholder"
             :title="'The ' + word + ' this row reads'"
             @update:model-value="$emit('pick', numOf($event))" />
  <span v-else>{{ text }}</span>
</template>

<script>
/*
 * Where a row of the matrix reads, on one axis (its realization or its time
 * step): a picker on a row that chooses, its words on a row that does not (a
 * pinned copy keeps what it read, a following row reads what it follows).
 */
import { DASH } from "../../../_shared/numfmt.js";
import FpSelect from "../../../_shared/components/FpSelect.vue";

export default {
  name: "CompareAxisPick",
  components: { FpSelect },
  props: {
    row: { type: Object, required: true },
    which: { type: String, required: true, validator: (v) => v === "real" || v === "ts" },
  },
  emits: ["pick"],
  computed: {
    isTime() {
      return this.which === "ts";
    },
    word() {
      return this.isTime ? "time step" : "realization";
    },
    named() {
      return this.isTime ? this.row.ts : this.row.real;
    },
    // {title, value} from the host
    choices() {
      return (this.isTime ? this.row.ts_opts : this.row.reals) || [];
    },
    // {value, label, title} for the field
    options() {
      if (this.row.pinned || this.row.support) return [];
      return this.choices.map((o) => ({
        value: o.value, label: String(o.title), title: "The " + this.word + " " + o.title,
      }));
    },
    // the first line of the list, the row naming nothing: what it reads while
    // it names nothing; once it names one, that line is the way back, and the
    // server's reading is the named one, so the line stays a word
    placeholder() {
      const word = this.isTime ? "time" : "real";
      if (this.named !== null && this.named !== undefined) return word;
      const read = this.isTime ? this.row.ts_text : this.row.real_read;
      return read === null || read === undefined || read === "" ? word : String(read);
    },
    text() {
      if (this.isTime && (this.row.ts_text || this.row.ts_label)) {
        return this.row.ts_text || this.row.ts_label;
      }
      const v = this.isTime ? this.row.ts : (this.row.real ?? this.row.real_read);
      if (v === null || v === undefined) return DASH;
      const hit = this.choices.find((o) => Number(o.value) === Number(v));
      return hit ? String(hit.title) : String(v);
    },
  },
  methods: {
    // the value an <fp-select> hands over: null for its placeholder
    numOf(v) {
      return v === null || v === undefined || v === "" ? null : Number(v);
    },
  },
};
</script>

<style scoped>
.fcp-axis-sel { font-size: var(--fp-size-small); padding: 0 14px 0 3px; max-width: 110px; background-position: right 3px center; }
.fcp-axis-ts { max-width: 130px; }
</style>
