<template>
  <fp-btn
    :title="tooltip"
    :label="shown"
    :disabled="disabled"
    v-bind="{ ...$attrs, ...flags }"
    @click="run"
  />
</template>

<script>
/*
 * The one export of the application.
 *
 * R11 — one word, one place, one behaviour: the word follows the data
 *       ("Copy CSV", "Copy XML" — the verb never changes, so the `label`
 *       validator refuses anything not beginning with "Copy "), the place is
 *       the panel's `export` slot just before the tree button, and the
 *       behaviour is `_shared/csvexport.handOver`: the clipboard when the
 *       browser offers one, a download otherwise — AND IT SAYS WHICH OF THE
 *       TWO IT DID, in place of the label, for two seconds.
 * R11 — a table with nothing to hand over keeps its button, disabled, with a
 *       tooltip that says why: `disabledWhy` is required as soon as
 *       `disabled` is true.
 * "Nothing silent" — a failure is not swallowed: the button reads
 *       "Export failed — <hint>" for six seconds.
 *
 * `build` returns the text, and is called on the click: each widget keeps
 * its own provenance header and column order (buildCsv/csvMeta). Taking
 * columns and rows instead would be the table shell the contract rejects.
 * Six copies of this block, one per table widget, go away.
 *
 * `inheritAttrs: false` with the attributes re-bound onto the button: what a
 * host writes on <fp-export> — a class, a test hook — reaches the control it
 * can see, and `flags` comes last so a host cannot write over the incomplete
 * marker.
 */
import { handOver } from "../csvexport.js";
import FpBtn from "./FpBtn.vue";

const HELD = 2000;
const HELD_ON_FAILURE = 6000;

export default {
  name: "FpExport",
  inheritAttrs: false,
  components: { FpBtn },
  props: {
    filename: { type: String, required: true },
    build: { type: Function, required: true },
    title: { type: String, required: true },
    label: {
      type: String,
      default: "Copy CSV",
      validator: (v) => /^Copy /.test(v),
    },
    mime: { type: String, default: "text/csv" },
    disabled: { type: Boolean, default: false },
    disabledWhy: {
      type: String,
      default: "",
      validator: (v, props) => !props.disabled || !!v,
    },
    failHint: { type: String, default: "select the table and copy it" },
  },
  data() {
    return { outcome: "", timer: null };
  },
  computed: {
    incomplete() {
      return !this.title || !this.filename || typeof this.build !== "function"
        || !/^Copy /.test(this.label)
        || (this.disabled && !this.disabledWhy);
    },
    flags() {
      return this.incomplete ? { "data-fp-incomplete": "" } : {};
    },
    shown() {
      return this.outcome || this.label;
    },
    tooltip() {
      if (this.incomplete) {
        return (this.title || "This export")
          + " — an export names its file, says what it hands over and, when it"
          + " is disabled, why: a defect";
      }
      if (this.disabled) return this.title + " — " + this.disabledWhy;
      return this.title;
    },
  },
  beforeUnmount() {
    if (this.timer) clearTimeout(this.timer);
  },
  methods: {
    say(word, held) {
      if (this.timer) clearTimeout(this.timer);
      this.outcome = word;
      this.timer = setTimeout(() => { this.outcome = ""; this.timer = null; }, held);
    },
    async run() {
      let text;
      try {
        text = await this.build();
      } catch (e) {
        this.say("Export failed — the table could not be written", HELD_ON_FAILURE);
        return;
      }
      if (text === null || text === undefined || text === "") {
        this.say("Export failed — nothing to hand over", HELD_ON_FAILURE);
        return;
      }
      const how = await handOver(text, this.filename, this.mime, this.failHint);
      this.say(how, /failed/.test(how) ? HELD_ON_FAILURE : HELD);
    },
  },
};
</script>
