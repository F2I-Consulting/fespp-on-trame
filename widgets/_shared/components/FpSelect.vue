<template>
  <label v-if="label" class="fp-lab" :title="tooltip">
    <span>{{ label }}</span>
    <select
      class="fp-sel"
      v-model="inner"
      :title="tooltip"
      :disabled="disabled"
      :data-fp-incomplete="incomplete ? '' : null"
      v-bind="$attrs"
    >
      <option
        v-for="o in allOptions"
        :key="String(o.value)"
        :value="o.value"
        :title="o.title"
        :disabled="o.disabled"
      >{{ o.label }}</option>
    </select>
  </label>
  <select
    v-else
    class="fp-sel"
    v-model="inner"
    :title="tooltip"
    :disabled="disabled"
    :data-fp-incomplete="incomplete ? '' : null"
    v-bind="$attrs"
  >
    <option
      v-for="o in allOptions"
      :key="String(o.value)"
      :value="o.value"
      :title="o.title"
      :disabled="o.disabled"
    >{{ o.label }}</option>
  </select>
</template>

<script>
/*
 * The one field that picks one value out of a list.
 *
 * R18 - one shared field: 44 hand-written selects in five paddings become
 *       this one, and the eslint gate refuses a <select> in a widget.
 * R1  - a control that sits in a bar is NAMED: `title` is required, and
 *       `label` writes the word in front of the field inside an `fp-lab`.
 * R11-style - a disabled control says WHY: `disabledWhy` is required as soon
 *       as `disabled` is true, and the tooltip carries it. An OPTION may be
 *       disabled too, and it is not mute either: its own `title` says why it
 *       cannot be chosen.
 *
 * ONE option shape for this component and for <fp-seg>: {value, label,
 * title?} - `label` is the word drawn, `title` the tooltip, defaulting to the
 * label. The two used to disagree (label drawn here, title drawn there), and
 * they sit side by side in the same sub-bar: an option array copied from one
 * to the other rendered a dropdown of blank rows and said nothing. The
 * validator now refuses that shape, and a label that is missing all the same
 * (a production build strips validators) draws the accusation in the row.
 *
 * The field is written twice on purpose: with a word in front it is a
 * `<label class="fp-lab">` the reader can click, without one it is the bare
 * field a bar puts between two buttons - wrapping a naked select would
 * change how every host lays it out. The options are written once.
 * `v-model` on the native select, also on purpose: Vue keeps the option's
 * real value on the element, so a Number option comes back a Number and not
 * the string the DOM would otherwise hand over.
 */
import { optionsAreWritten } from "./options.js";

const NO_WORDS = "(this option has no words — a defect)";

export default {
  name: "FpSelect",
  inheritAttrs: false,
  props: {
    modelValue: { required: true },
    options: { type: Array, required: true, validator: optionsAreWritten },
    title: { type: String, required: true },
    label: { type: String, default: "" },
    placeholder: { type: String, default: "" },
    mandatory: { type: Boolean, default: false },
    disabled: { type: Boolean, default: false },
    disabledWhy: {
      type: String,
      default: "",
      validator: (v, props) => !props.disabled || !!v,
    },
  },
  emits: ["update:modelValue"],
  computed: {
    allOptions() {
      const first = this.placeholder
        ? [{
          value: "", label: this.placeholder, title: this.placeholder,
          disabled: this.mandatory,
        }]
        : [];
      return first.concat((this.options || []).map((o) => ({
        value: o.value,
        label: o.label || NO_WORDS,
        title: o.title || o.label || NO_WORDS,
        disabled: !!o.disabled,
      })));
    },
    inner: {
      get() {
        return this.modelValue === null || this.modelValue === undefined
          ? "" : this.modelValue;
      },
      set(v) {
        this.$emit("update:modelValue", v === "" ? null : v);
      },
    },
    written() {
      return optionsAreWritten(this.options);
    },
    incomplete() {
      return !this.title || !this.written || (this.disabled && !this.disabledWhy);
    },
    tooltip() {
      if (!this.title) return "this field does not say what it chooses - a defect";
      if (!this.written) {
        return this.title + " - an option of this list has no words to draw:"
          + " {value, label, title?}, the same shape as <fp-seg>. A defect";
      }
      if (!this.disabled) return this.title;
      if (this.disabledWhy) return this.title + " - " + this.disabledWhy;
      return this.title + " - disabled without saying why: a defect";
    },
  },
};
</script>
