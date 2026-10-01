<template>
  <div
    class="fp-empty"
    :data-fp-shows="shows"
    :data-fp-gesture="gesture"
    :data-fp-incomplete="incomplete ? '' : null"
    v-bind="$attrs"
  >{{ sentence }}</div>
</template>

<script>
/*
 * What a panel would show, and the gesture that fills it.
 *
 * R8 — `shows` and `gesture` are BOTH required, in that order, so a mute
 *      empty state cannot be written; `why` comes third when the gesture
 *      cannot be made. The eight private classes (`fap-empty`, `fcm-empty`,
 *      `fsl-empty`, `ftr-empty`, `fth-empty`, `fst-empty`, `st-empty`,
 *      `fxv-empty`) go with it.
 * R8 — the gesture must EXIST on screen: a control named in it is quoted
 *      with its exact words, and the browser harness reads the quoted words
 *      back off `data-fp-gesture` and looks for them in the same panel.
 * A production build strips prop validation, so a missing sentence renders a
 * visible accusation instead of nothing — and `data-fp-incomplete` makes the
 * harness fail before a reader ever meets it.
 * `why` never replaces R10: a cause carries `why` AND the panel's note.
 */
export default {
  name: "FpEmpty",
  inheritAttrs: false,
  props: {
    shows: { type: String, required: true },
    gesture: { type: String, required: true },
    why: { type: String, default: "" },
  },
  computed: {
    incomplete() {
      return !this.shows || !this.gesture;
    },
    sentence() {
      if (this.incomplete) {
        return "this panel does not say what it would show — a defect";
      }
      return [this.shows, this.gesture, this.why].filter(Boolean).join(" ");
    },
  },
};
</script>
