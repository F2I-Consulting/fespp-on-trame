<template>
  <div
    v-if="!dismissed"
    class="fp-note"
    :class="{ 'fp-note-error': severity === 'error' }"
    :data-fp-severity="severity"
    :data-fp-next="next || null"
    :data-fp-incomplete="incomplete ? '' : null"
    v-bind="$attrs"
  >
    <span class="fp-note-text">{{ sentence }}</span>
    <fp-btn
      variant="bare"
      label="×"
      :title="'Dismiss this note: ' + text"
      @click="dismiss"
    />
  </div>
</template>

<script>
/*
 * A band, full width, under the bar.
 *
 * R10 — two severities and two only: something was held back (warning), or
 *       an action failed (error, and it names the suite à donner). A
 *       validator REFUSES "info": information goes to `fp-sum` or to a chip
 *       glued to its control, never to a band that pushes the controls about.
 * R10 — the cross is not optional: R10 gives a band the duration "until its
 *       cause disappears OR the user closes it", so every band carries one,
 *       and the harness fails a band that has none.
 * R10 — it does NOT evaporate on refresh. The component owns dismissal and
 *       keys it on its own TEXT, so a host never has to clear a note to make
 *       it go away, and therefore never clears it on the next push. A new
 *       text is a new note and shows again.
 */
import FpBtn from "./FpBtn.vue";

export default {
  name: "FpNote",
  inheritAttrs: false,
  components: { FpBtn },
  props: {
    text: { type: String, required: true },
    severity: {
      type: String,
      required: true,
      validator: (v) => v === "warning" || v === "error",
    },
    // required when severity === "error"
    next: { type: String, default: "" },
  },
  emits: ["close"],
  data() {
    return { dismissedText: null };
  },
  computed: {
    dismissed() {
      return this.dismissedText === this.text;
    },
    incomplete() {
      return !this.text || !this.validSeverity || (this.severity === "error" && !this.next);
    },
    validSeverity() {
      return this.severity === "warning" || this.severity === "error";
    },
    sentence() {
      const parts = [];
      parts.push(this.text || "this note says nothing — a defect");
      if (this.next) parts.push(this.next);
      if (this.severity === "error" && !this.next) {
        parts.push("no next step was given — a defect");
      }
      if (!this.validSeverity) {
        parts.push("a note is a warning or an error; information belongs in"
          + " the summary or in a chip beside its control — a defect");
      }
      return parts.join(" — ");
    },
  },
  methods: {
    dismiss() {
      this.dismissedText = this.text;
      this.$emit("close");
    },
  },
};
</script>
