<template>
  <Teleport to="body">
    <div class="fp-scrim" v-if="open" @click.self="$emit('close')" @keydown.esc="$emit('close')">
      <!-- `tabindex="-1"`: a click on the text of a dialog whose only
           focusable elements are its buttons drops the focus on <body>, and
           the Esc the scrim listens for never reaches it again. Focusable
           but not tabbable, the card catches that click itself and Esc keeps
           working wherever the reader clicked. -->
      <div class="fp-dialog fnv" role="dialog" aria-modal="true" tabindex="-1">
        <div class="fp-dialog-head">
          <span class="fp-title">New 3D view</span>
          <fp-btn variant="bare" title="Close without opening a view" label="×" @click="$emit('close')" />
        </div>

        <div class="fnv-body">
          <!-- two exclusive answers to the same question, which is what
               <fp-seg> is for -->
          <fp-seg v-model="mode" :options="MODES" title="What the new view starts from" />

          <template v-if="mode === 'copy'">
            <label class="fp-lab" title="The view whose shown objects and camera the new one takes">From
              <fp-select v-model="from" :options="viewOptions"
                         title="The view whose shown objects and camera the new one takes" />
            </label>
            <div class="fp-sum">
              It opens beside that view, showing the same objects, with the same camera.
              The two cameras are <b>not</b> synchronized — tick that in the view's
              own <em>Synchronize camera</em> card when you want them to move together.
            </div>
          </template>
          <div v-else class="fp-sum">
            It opens empty, with a tree of its own: nothing is shown until you
            tick something in it.
          </div>

          <fp-note v-if="mode === 'copy' && !viewOptions.length" severity="warning"
                   text="There is no other 3D view to copy yet — open an empty one first." />
        </div>

        <div class="fnv-foot">
          <fp-btn label="Cancel" title="Close without opening a view" @click="$emit('close')" />
          <fp-btn variant="primary" label="Open" :disabled="!canOpen"
                  :disabled-why="'there is no view to copy'"
                  title="Open the new 3D view" @click="open_()" />
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script>
/*
 * What a second 3D view starts from: a copy of another view, or nothing.
 *
 * Copying the current view is right when you want the same thing twice side
 * by side, and wrong when you want a clean view to build something else in,
 * so the gesture asks, once, with a two-way choice.
 *
 * It offers only what it can do: the "from" list holds the open render
 * views, and a Globe view is not among them. Its camera lives in ECEF world
 * coordinates, so copying it into a local-CRS view would put the new one
 * nowhere useful.
 *
 * Pure display, like every widget here:
 *   props in   — open, views [{id, title, globe}], defaultFrom
 *   events out — create(sourceId) ("" = empty), close()
 */
import FpBtn from "../../../_shared/components/FpBtn.vue";
import FpNote from "../../../_shared/components/FpNote.vue";
import FpSeg from "../../../_shared/components/FpSeg.vue";
import FpSelect from "../../../_shared/components/FpSelect.vue";

const MODES = [
  { value: "copy", label: "Copy a view",
    title: "The same objects shown, and the same camera" },
  { value: "empty", label: "Empty view",
    title: "Nothing shown; pick what you want in the new view's own tree" },
];

export default {
  name: "NewViewDialog",
  components: { FpBtn, FpNote, FpSeg, FpSelect },
  props: {
    open: { type: Boolean, default: false },
    views: { type: Array, default: () => [] },
    defaultFrom: { type: String, default: "" },
  },
  emits: ["create", "close"],
  data() {
    return { MODES, mode: "copy", from: "" };
  },
  computed: {
    // a Globe view is not offered: its camera is in ECEF, and copying it
    // into a local-CRS 3D view would aim the new one far from the data
    viewOptions() {
      return (this.views || []).filter((v) => v && !v.globe)
        .map((v) => ({ value: v.id, label: v.title || v.id }));
    },
    canOpen() {
      return this.mode === "empty" || !!this.from;
    },
  },
  watch: {
    // each opening proposes the active view (defaultFrom), not whatever was
    // picked the time before; with no view to copy, it starts on "empty"
    open(now) {
      if (!now) return;
      const ids = this.viewOptions.map((o) => o.value);
      this.from = ids.includes(this.defaultFrom) ? this.defaultFrom : (ids[0] || "");
      this.mode = ids.length ? "copy" : "empty";
    },
  },
  methods: {
    open_() {
      if (!this.canOpen) return;
      this.$emit("create", this.mode === "copy" ? this.from : "");
      // gone with the first click, not when the server answers: every further
      // click on Open would be one more view
      this.$emit("close");
    },
  },
};
</script>

<style>
@import "../../../_shared/panel.css";
</style>

<style scoped>
.fnv { width: 380px; max-width: 92vw; }
.fnv-body { display: flex; flex-direction: column; gap: 10px; padding: 12px; }
.fnv-foot { display: flex; justify-content: flex-end; gap: 8px;
  padding: 8px 12px; border-top: 1px solid var(--fp-line-soft); }
</style>
