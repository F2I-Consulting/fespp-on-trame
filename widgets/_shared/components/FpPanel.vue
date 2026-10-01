<template>
  <div
    class="fp-panel"
    :data-fp-incomplete="incomplete ? '' : null"
    v-bind="$attrs"
  >
    <div class="fp-bar">
      <span class="fp-title" :title="titleTip || null">{{ name }}</span>
      <fp-chip v-if="target" variant="accent" :title="target" :text="target" />
      <slot name="controls" />
      <div v-if="hasRight" class="fp-right">
        <fp-chip
          v-if="summaryText && summaryDropped"
          variant="warn"
          :title="summaryText"
          :text="summaryText"
        />
        <span v-else-if="summaryText" class="fp-sum">{{ summaryText }}</span>
        <slot name="actions" />
        <slot name="export" />
        <slot name="tree" />
      </div>
    </div>
    <div
      v-if="busy"
      class="fp-busy"
      role="progressbar"
      title="Working — the panel keeps what it was showing until the new figures arrive"
    ></div>
    <div v-if="$slots.subbar" class="fp-subbar"><slot name="subbar" /></div>
    <fp-note
      v-if="controlsHoldANote()"
      severity="error"
      data-fp-incomplete
      text="A note was written into the row of controls, where a band that grows pushes the buttons about."
      next="move it to this panel's notes slot, which is this band"
    />
    <slot name="notes" />
    <div v-if="scroll" class="fp-scroll"><slot /></div>
    <slot v-else />
  </div>
</template>

<script>
/*
 * The frame every session panel wears. The ORDER is the enforcement: the
 * summary, the action, the export and the tree button are slots INSIDE the
 * right group, in that order, so a host cannot put its actions before its
 * summary. What a slot cannot refuse is what is handed to it, so the
 * `controls` slot is READ: a note found in the row of controls — the
 * regression that moved Compare's Copy CSV from x=296 to x=1141 — is
 * accused in a band of its own, and the browser sweep fails on any .fp-note
 * inside an .fp-bar, which covers the panels written in Python too.
 *
 * R1  — the bar is ALWAYS rendered, never behind a `v-show` on having data,
 *       and its order is title, target, controls, then the right group.
 * R2  — one title, the `label` of views_config.VIEW_KINDS, never a control's
 *       word.
 * R3  — the tree button is the LAST slot of the right group, at the far right.
 * R9  — `busy` draws the 2 px indeterminate bar UNDER the bar and adds
 *       "recomputing…" to the summary; the body keeps its content, because
 *       the frame never empties it.
 * R10 — notes are a full-width band under the bar (and under the sub-bar),
 *       never inside the row of controls.
 * R12 — the target is written ONCE, here, as an accent chip right after the
 *       title; a panel that acts on the view or the session passes none.
 * R14 — the summary is the FIRST element of the right group, and wears the
 *       warning chip only when something was left out.
 *
 * The docked aside is deliberately not here: for Statistics, the well log and
 * Compare the 320 px column is built in Python (views/widgets/docked_tree),
 * and the widget receives only the BUTTON, into the `tree` slot.
 */
import FpChip from "./FpChip.vue";
import FpNote from "./FpNote.vue";

/* A note anywhere in what a host handed to the `controls` slot. */
function holdsANote(nodes) {
  for (const vnode of nodes || []) {
    if (!vnode || typeof vnode !== "object") continue;
    if (vnode.type && vnode.type.name === "FpNote") return true;
    const cls = vnode.props && vnode.props.class;
    if (typeof cls === "string" && /(^| )fp-note( |$)/.test(cls)) return true;
    if (Array.isArray(vnode.children) && holdsANote(vnode.children)) return true;
  }
  return false;
}

export default {
  name: "FpPanel",
  inheritAttrs: false,
  components: { FpChip, FpNote },
  props: {
    title: { type: String, required: true },
    titleTip: { type: String, default: "" },
    target: { type: String, default: null },
    summary: { type: String, default: "" },
    summaryDropped: { type: Boolean, default: false },
    busy: { type: Boolean, default: false },
    scroll: { type: Boolean, default: true },
  },
  computed: {
    incomplete() {
      return !this.title;
    },
    name() {
      return this.title || "this panel does not name itself — a defect";
    },
    summaryText() {
      if (!this.busy) return this.summary;
      return this.summary ? this.summary + " · recomputing…" : "recomputing…";
    },
    hasRight() {
      return !!this.summaryText || !!this.$slots.actions
        || !!this.$slots.export || !!this.$slots.tree;
    },
  },
  methods: {
    // a method, not a computed: slot content is not a reactive dependency,
    // and a cached answer would go on accusing a row already put right
    controlsHoldANote() {
      return !!this.$slots.controls && holdsANote(this.$slots.controls());
    },
  },
};
</script>
