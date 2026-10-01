<template>
  <span v-if="stepper" class="fp-lab" :title="tooltip">
    <fp-btn
      tiny
      icon
      label="−"
      :title="stepTitle('down')"
      :disabled="disabled || atMin"
      @click="bump(-1)"
    />
    <input
      class="fp-num"
      type="text"
      inputmode="decimal"
      :size="cols"
      :value="draft"
      :title="tooltip"
      :placeholder="placeholder"
      :disabled="disabled"
      :data-fp-incomplete="incomplete ? '' : null"
      v-bind="$attrs"
      @input="draft = $event.target.value"
      @change="commit"
    />
    <fp-btn
      tiny
      icon
      label="+"
      :title="stepTitle('up')"
      :disabled="disabled || atMax"
      @click="bump(1)"
    />
  </span>
  <input
    v-else
    class="fp-num"
    type="text"
    inputmode="decimal"
    :size="cols"
    :value="draft"
    :title="tooltip"
    :placeholder="placeholder"
    :disabled="disabled"
    :data-fp-incomplete="incomplete ? '' : null"
    v-bind="$attrs"
    @input="draft = $event.target.value"
    @change="commit"
  />
</template>

<script>
/*
 * A number the reader types.
 *
 * The rule this component exists for: NEVER an input of type "number".
 * Chromium writes AND reads such a field in the BROWSER's locale, so a
 * French reader is shown "0,25" beside a card writing "0.25", and what comes
 * back is whatever that locale parsed. Here the field is text with a decimal
 * keypad, the value is written by numfmt.fmtExact — every digit the value
 * has, a point, no grouping: a typed 1250.5 shown back as 1251 would be the
 * field lying about the value in force — and a typed comma is read as the
 * decimal point.
 * Three widgets had each written their own parseFloat/replace pair; four
 * number fields are still wrong today. The eslint gate refuses the type.
 *
 * Committed on `change` (blur or Enter), never on every keystroke: clamping a
 * half-typed "1" to a minimum of 10 fights the reader. The clamp, the
 * rounding of an integer field and the refusal of something that is not a
 * number are all VISIBLE — the field snaps back to the value still in force.
 */
import { fmtExact, parseNum } from "../numfmt.js";
import FpBtn from "./FpBtn.vue";

export default {
  name: "FpNum",
  inheritAttrs: false,
  components: { FpBtn },
  props: {
    // Number or null: a nullable field means "none", and none is not a Number
    modelValue: {
      required: true,
      validator: (v) => v === null || v === undefined || typeof v === "number",
    },
    title: { type: String, required: true },
    min: { type: Number, default: null },
    max: { type: Number, default: null },
    integer: { type: Boolean, default: false },
    nullable: { type: Boolean, default: false },
    stepper: { type: Boolean, default: false },
    step: { type: Number, default: 1 },
    placeholder: { type: String, default: "" },
    disabled: { type: Boolean, default: false },
    size: {
      type: String,
      default: "md",
      validator: (v) => v === "sm" || v === "md",
    },
  },
  emits: ["update:modelValue"],
  data() {
    return { draft: "" };
  },
  computed: {
    incomplete() {
      return !this.title;
    },
    tooltip() {
      return this.title || "this field does not say what it sets — a defect";
    },
    cols() {
      return this.size === "sm" ? 5 : 9;
    },
    atMin() {
      return this.min !== null && this.modelValue !== null
        && this.modelValue <= this.min;
    },
    atMax() {
      return this.max !== null && this.modelValue !== null
        && this.modelValue >= this.max;
    },
  },
  watch: {
    // Number or null: a nullable field means "none", and none is not a Number
    modelValue: { immediate: true, handler() { this.draft = this.written(); } },
  },
  methods: {
    stepTitle(way) {
      return "One step " + way + " — " + this.tooltip;
    },
    written() {
      return this.modelValue === null || this.modelValue === undefined
        ? "" : fmtExact(this.modelValue);
    },
    bounded(n) {
      let v = this.integer ? Math.round(n) : n;
      if (this.min !== null) v = Math.max(this.min, v);
      if (this.max !== null) v = Math.min(this.max, v);
      return v;
    },
    commit() {
      const typed = parseNum(this.draft);
      if (typed === null) {
        if (this.nullable) {
          this.draft = "";
          this.$emit("update:modelValue", null);
          return;
        }
        this.draft = this.written();
        return;
      }
      const v = this.bounded(typed);
      this.draft = fmtExact(v);
      if (v !== this.modelValue) this.$emit("update:modelValue", v);
    },
    bump(direction) {
      const from = this.modelValue === null || this.modelValue === undefined
        ? (this.min === null ? 0 : this.min)
        : this.modelValue;
      const v = this.bounded(from + direction * this.step);
      this.draft = fmtExact(v);
      if (v !== this.modelValue) this.$emit("update:modelValue", v);
    },
  },
};
</script>
