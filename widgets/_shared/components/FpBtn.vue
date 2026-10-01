<template>
  <button
    type="button"
    class="fp-btn"
    :class="[variantClass, { 'fp-icon': icon, 'fp-tiny': tiny }]"
    :title="tooltip"
    :disabled="disabled || busy"
    :data-fp-busy="busy ? '' : null"
    :data-fp-incomplete="incomplete ? '' : null"
    v-bind="$attrs"
    @click="$emit('click', $event)"
  ><slot>{{ label }}</slot></button>
</template>

<script>
/*
 * The one button of the application.
 *
 * R18 — one button vocabulary: seven private copies (`fcalc-btn`, `ftr-btn`,
 * `fcm-btn`, `fxv-btn`, `fth-btn`, `fnav-btn`, `fsl-btn`) stop being
 * writable, because the eslint gate refuses a `<button>` in a widget.
 * R15 — Title case: the `label` validator refuses a word starting lower case.
 * R9  — busy: DISABLED while it works, and the LABEL UNCHANGED, so the word
 *       the reader clicked is still the word under the pointer.
 * "Nothing silent" — `title` is REQUIRED: an affordance says what it does,
 *       and a disabled one says why (R11/R15). A production build strips
 *       prop validation, so a missing tooltip also renders a visible
 *       accusation into the tooltip and raises `data-fp-incomplete`, which
 *       the browser harness fails on.
 */
const VARIANTS = {
  default: "",
  primary: "fp-primary",
  on: "fp-on",
  // the transparent × / ★ / ⌕ carried inside a chip
  bare: "fp-chip-btn",
};

export default {
  name: "FpBtn",
  inheritAttrs: false,
  props: {
    title: { type: String, required: true },
    label: {
      type: String,
      default: "",
      validator: (v) => v === "" || /^[^a-z]/.test(v),
    },
    variant: {
      type: String,
      default: "default",
      validator: (v) => Object.prototype.hasOwnProperty.call(VARIANTS, v),
    },
    icon: { type: Boolean, default: false },
    tiny: { type: Boolean, default: false },
    disabled: { type: Boolean, default: false },
    busy: { type: Boolean, default: false },
  },
  emits: ["click"],
  computed: {
    incomplete() {
      return !this.title || (!!this.label && /^[a-z]/.test(this.label));
    },
    tooltip() {
      if (!this.title) return "this control does not say what it does — a defect";
      if (this.label && /^[a-z]/.test(this.label)) {
        return this.title + " — a button label is written in Title case: a defect";
      }
      return this.title;
    },
    variantClass() {
      return VARIANTS[this.variant] === undefined ? "" : VARIANTS[this.variant];
    },
  },
};
</script>
