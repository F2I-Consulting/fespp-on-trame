<template>
  <span
    class="fp-chip"
    :class="[variantClass, { 'fp-chip-sm': sm, 'fp-on': on }]"
    :title="tooltip"
    :data-fp-incomplete="incomplete ? '' : null"
    v-bind="passThrough"
  ><span class="fp-chip-text"><slot>{{ text }}</slot></span><slot name="after" /></span>
</template>

<script>
/*
 * A chip: a short word glued to what it qualifies.
 *
 * R10 — a chip is the INFORMATION channel (a count, a unit, a provenance);
 *       a warning or an error is a band, never a chip in the row of controls.
 *       `warn` and `error` stay available because R14 gives the summary a
 *       warning form when something was left out, and the counts of File
 *       health are coloured counts — but they are held to a LENGTH: past
 *       MAX_WARNING characters a warning is a sentence, and an ellipsed
 *       one-line badge for a sentence is the shape R10 names as a defect
 *       (Compare's badge, 200 characters cut to "9 of 412 cells d…").
 * R12 — the target line: a chip ellipses, so `title` is REQUIRED and carries
 *       the FULL text. A truncated chip with no tooltip hides its own
 *       content. A target NAME is legitimately long and ellipsed, which is
 *       why the length only holds the warning channel.
 * A chip is not a control: it emits no click, it has no tab stop, no role
 * and no key handler to make one honest, and a click listener a host puts
 * on it is NOT bound — it is refused out loud, because binding it would
 * hand the reader a control the keyboard skips. Something to press inside
 * a chip is an <fp-btn variant="bare"> in the `after` slot.
 * The ellipsis lives on `.fp-chip-text` in panel.css: an inline-flex chip
 * cannot ellipse its own anonymous text.
 */
const VARIANTS = {
  neutral: "",
  accent: "fp-chip-accent",
  warn: "fp-chip-warn",
  error: "fp-chip-error",
  line: "fp-chip-line",
  off: "fp-chip-off",
};

const MAX_WARNING = 60;

export default {
  name: "FpChip",
  inheritAttrs: false,
  props: {
    title: { type: String, required: true },
    text: { type: String, default: "" },
    variant: {
      type: String,
      default: "neutral",
      validator: (v) => Object.prototype.hasOwnProperty.call(VARIANTS, v),
    },
    sm: { type: Boolean, default: false },
    on: { type: Boolean, default: false },
  },
  computed: {
    clickable() {
      return !!(this.$attrs.onClick || this.$attrs.onClickCapture);
    },
    passThrough() {
      const rest = { ...this.$attrs };
      delete rest.onClick;
      delete rest.onClickCapture;
      return rest;
    },
    tooLong() {
      return (this.variant === "warn" || this.variant === "error")
        && (this.text || "").length > MAX_WARNING;
    },
    incomplete() {
      return !this.title || this.tooLong || this.clickable;
    },
    tooltip() {
      if (!this.title) return "this chip does not say what it holds — a defect";
      if (this.clickable) {
        return this.title + " — a chip is not a control and no keyboard reaches"
          + " one: put what is pressed in its `after` slot, as an"
          + " <fp-btn variant=\"bare\">. The click was not bound: a defect";
      }
      if (this.tooLong) {
        return this.title + " — a sentence this long is a band under the bar,"
          + " not a chip: <fp-note>. A defect";
      }
      return this.title;
    },
    variantClass() {
      return VARIANTS[this.variant] === undefined ? "" : VARIANTS[this.variant];
    },
  },
};
</script>
