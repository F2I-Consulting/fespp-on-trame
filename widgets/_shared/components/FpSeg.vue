<template>
  <span
    class="fp-seg"
    :title="tooltip"
    :data-fp-incomplete="incomplete ? '' : null"
    v-bind="$attrs"
  >
    <button
      v-for="o in options"
      :key="String(o.value)"
      type="button"
      class="fp-segbtn"
      :class="{ 'fp-on': o.value === modelValue }"
      :title="o.title || o.label"
      @click="$emit('update:modelValue', o.value)"
    >{{ o.label || NO_WORDS }}</button>
  </span>
</template>

<script>
/*
 * Two to four exclusive readings of the SAME data.
 *
 * R13 — the `options` validator refuses a strip of one (an inert single tab
 *       is a control that promises a choice it does not have) and a strip of
 *       five (that is a list, and it belongs in a select). A production
 *       build strips the validator, so a malformed strip also raises
 *       `data-fp-incomplete` and says so in its tooltip.
 * The option shape is the one <fp-select> takes: {value, label, title?}.
 * This is NOT the tree's type tabs (`fdx-tabs`, which R13 reserves to the
 * tree) and NOT the XML navigation stack (several open documents, not
 * alternative readings of one).
 */
import { optionsAreWritten } from "./options.js";

const NO_WORDS = "(no words — a defect)";

export default {
  name: "FpSeg",
  inheritAttrs: false,
  props: {
    options: {
      type: Array,
      required: true,
      validator: (v) => v.length >= 2 && v.length <= 4 && optionsAreWritten(v),
    },
    modelValue: { required: true },
    title: { type: String, default: "" },
  },
  emits: ["update:modelValue"],
  computed: {
    NO_WORDS() {
      return NO_WORDS;
    },
    thin() {
      const n = (this.options || []).length;
      return n < 2 || n > 4;
    },
    incomplete() {
      return this.thin || !optionsAreWritten(this.options);
    },
    tooltip() {
      if (!this.incomplete) return this.title || undefined;
      const said = this.thin
        ? "a segmented control holds two to four readings of the same data"
        : "a reading of this strip has no words to draw: {value, label,"
          + " title?}, the same shape as <fp-select>";
      return (this.title ? this.title + " — " : "") + said + ": a defect";
    },
  },
};
</script>
