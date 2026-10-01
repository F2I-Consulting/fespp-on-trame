<template>
  <div class="t3">
    <!-- What the mouse does in this view. The HAND moves the scene (drag to
         rotate, wheel to zoom, right or middle drag to pan); the MOUSE
         reads what is under the pointer (position, block, wellbore, cell,
         property value) and holds the scene still — back to the hand to
         move it. One of the two is always on, and it wears the outline. -->
    <span class="t3-group" role="radiogroup" aria-label="What the mouse does">
      <button type="button" class="t3-btn t3-pointer" :class="{ 't3-on': !cursor }"
              role="radio" :aria-checked="!cursor ? 'true' : 'false'" data-t3-hand
              title="Move the scene: drag to rotate, wheel to zoom, right or middle drag to pan"
              @click="cursor && $emit('set-cursor', false)">
        <v-icon size="18">mdi-hand-back-right-outline</v-icon>
      </button>
      <button type="button" class="t3-btn t3-pointer" :class="{ 't3-on': cursor }"
              role="radio" :aria-checked="cursor ? 'true' : 'false'" data-t3-mouse
              title="Show position: the scene stays still, the pointer reads what is under it — position, object, wellbore, cell and property value. The hand moves the scene again"
              @click="!cursor && $emit('set-cursor', true)">
        <v-icon size="18">mdi-mouse</v-icon>
      </button>
    </span>

    <span class="t3-sep"></span>

    <!-- Interaction mode. Per VIEW: it reads as the mode it is IN, and the
         tooltip says what pressing it does — a button whose label is its
         own effect and whose label is also its state is unreadable. -->
    <button type="button" class="t3-btn t3-mode" :title="modeTitle"
            @click="$emit('set-mode', is2d ? '3D' : '2D')">{{ is2d ? "2D" : "3D" }}</button>

    <!-- How every block of this view is DRAWN. It lived in a floating card
         of its own, which held this one control and nothing else: a card to
         open, move and close for a single choice. It belongs here, beside
         the mode it reads with — both say how the view LOOKS, neither says
         what it shows. -->
    <fp-select v-if="(repStyles || []).length" class="t3-style"
               :model-value="repStyle" :options="styleOptions"
               title="How every block of this view is drawn"
               @update:model-value="$emit('set-style', $event)" />

    <!-- Shading, beside how the view is drawn: a lit surface reads a
         different colour than its legend says, so the reader can ask for
         the legend's colours exactly. The glyph shows the mode it is IN, the
         tooltip what a click does. Kept on the Earth: it lights there too. -->
    <button type="button" class="t3-btn t3-flat" :class="{ 't3-on': flat }" :title="flatTitle"
            :aria-pressed="flat ? 'true' : 'false'" @click="$emit('set-flat', !flat)">
      <v-icon size="18">{{ flat ? "mdi-lightbulb-off-outline" : "mdi-lightbulb-on-outline" }}</v-icon>
    </button>

    <span class="t3-sep"></span>

    <!-- On the Earth, the one framing that DOES work: the whole planet. It
         lived in the Globe card alone, so putting the view back in view
         meant opening a card first — and the framings beside it are dead
         here. -->
    <button v-if="globe" type="button" class="t3-btn t3-earth"
            title="Frame the whole Earth" @click="$emit('frame', 'earth')">
      <v-icon size="18">mdi-earth</v-icon>
    </button>

    <!-- Framings. On the Earth they are drawn DEAD rather than dropped: the
         bounds they aim at are local-CRS metres, which in ECEF point at the
         other side of the planet — the reason rides in the tooltip, and the
         span carries it because a disabled button gets no pointer events. -->
    <span class="t3-group" :title="globe ? GLOBE_WHY : ''">
      <button type="button" class="t3-btn" :disabled="globe"
              title="Frame everything in this view" @click="$emit('reset')">
        <v-icon size="18">mdi-crop-free</v-icon>
      </button>
      <button v-for="a in AXES" :key="a.key" type="button" class="t3-btn" :disabled="globe"
              :title="a.title" @click="$emit('axis', a.key)">
        <v-icon size="18">{{ a.icon }}</v-icon>
      </button>
    </span>

    <span class="t3-sep"></span>

    <!-- A zoom notch, for a trackpad where the wheel is awkward and for a
         framing you want to repeat exactly. Offered on the Earth too: it
         only dollies along the view direction, which is the wheel's own
         gesture, and reads no bounds. -->
    <button type="button" class="t3-btn" title="Zoom in" @click="$emit('zoom', 0.8)">
      <v-icon size="18">mdi-magnify-plus-outline</v-icon>
    </button>
    <button type="button" class="t3-btn" title="Zoom out" @click="$emit('zoom', 1.25)">
      <v-icon size="18">mdi-magnify-minus-outline</v-icon>
    </button>
  </div>
</template>

<script>
/*
 * The camera strip of ONE 3D view's title bar: interaction mode, framing,
 * the three axis looks and a zoom notch.
 *
 * WHY IT IS CHROME AND NOT A CARD. These are gestures reached for in the
 * middle of a drag — a panel to open, move and close costs more than the
 * gesture is worth. They sit in the title bar, beside the tab, always open,
 * and they name the view they drive by sitting on it.
 *
 * WHY IT IS DRAWN LIKE THE BAR. It used to be Kitware's ptc button group,
 * a white pill of dark icons laid on the F2I blue: a foreign object with
 * its own background, its own radius and its own weight. Chrome is not a
 * widget dropped on a bar, it is the bar — so the strip has no ground of
 * its own, its ink is the tab's white, and only the hover says a button is
 * there. Its two dividers group what belongs together: the mode, the
 * framings, the zoom.
 *
 * Stateless, like every widget of the house:
 *   props in   — cursor (the mouse is on: show position, scene fixed; the
 *                hand otherwise), mode ("3D" | "2D"), globe (this view is
 *                on the Earth), repStyle / repStyles (how every block of the
 *                view is drawn), flat (no shading: the colours are the
 *                legend's)
 *   events out — set-cursor(bool), set-mode(mode), reset(),
 *                axis("+x"|"+y"|"+z"), zoom(factor), set-style(name),
 *                set-flat(bool), frame("earth") — offered on the Earth only
 * The host computes every move (boot's nav_* controllers), so this strip and
 * the Navigation card move the camera through the SAME code.
 */
import FpSelect from "../../../_shared/components/FpSelect.vue";

const AXES = [
  { key: "+x", icon: "mdi-axis-x-arrow", title: "Look along +X" },
  { key: "+y", icon: "mdi-axis-y-arrow", title: "Look along +Y" },
  { key: "+z", icon: "mdi-axis-z-arrow", title: "Look along +Z (from above)" },
];

const GLOBE_WHY = "This view draws on the Earth — these framings are computed "
  + "on the data's own coordinates and would aim at the other side of the "
  + "planet. Use the globe button beside them, or the Globe card.";

export default {
  name: "Title3dView",
  components: { FpSelect },
  props: {
    // true = the mouse (show position, the scene held still); false = the hand
    cursor: { type: Boolean, default: false },
    mode: { type: String, default: "3D" },
    globe: { type: Boolean, default: false },
    // How every block of this view is drawn, and what is on offer.
    // NOT named `style`: that is a reserved DOM attribute, so Vue takes the
    // value for CSS and the prop never arrives -- and the whole element's
    // attribute serialisation goes with it (the sibling trap of a prop named
    // like a DOM event, which emits <tag html-error />).
    repStyle: { type: String, default: "Surface" },
    repStyles: { type: Array, default: () => [] },
    // false = lit (the default), true = exact colours, no shading
    flat: { type: Boolean, default: false },
  },
  emits: ["set-cursor", "set-mode", "reset", "axis", "zoom", "set-style", "set-flat", "frame"],
  data() {
    return { AXES, GLOBE_WHY };
  },
  computed: {
    is2d() { return String(this.mode || "3D").toUpperCase() === "2D"; },
    styleOptions() { return (this.repStyles || []).map((s) => ({ value: s, label: s })); },
    modeTitle() {
      return this.is2d
        ? "Interaction: 2D — rotation is locked. Click for 3D"
        : "Interaction: 3D — drag to rotate. Click for 2D (rotation locked)";
    },
    flatTitle() {
      return this.flat
        ? "Exact colours — no shading, the colours are the legend's. Click to shade"
        : "Shading on — colours are lit and can look different from the legend. Click for exact colours";
    },
  },
};
</script>

<style scoped>
/* Chrome of the dockview tab row (--dv-tabs-and-actions-container-*): no
   ground of its own, the bar's own white ink, hover only. */
.t3 {
  display: flex; align-items: center; gap: 1px; height: 100%;
  font-family: system-ui, sans-serif;
}
.t3-group { display: flex; align-items: center; gap: 1px; }
.t3-btn {
  height: 26px; min-width: 28px; padding: 0 4px;
  display: inline-flex; align-items: center; justify-content: center;
  border: none; border-radius: 3px; background: transparent;
  color: rgba(255, 255, 255, 0.85); cursor: pointer; line-height: 1;
}
.t3-btn:hover:not(:disabled) { background: rgba(255, 255, 255, 0.16); color: #fff; }
.t3-btn:active:not(:disabled) { background: rgba(255, 255, 255, 0.26); }
.t3-btn:focus-visible { outline: 1px solid rgba(255, 255, 255, 0.7); outline-offset: -1px; }
.t3-btn:disabled { opacity: 0.35; cursor: default; }
/* the mode reads as a state, so it wears a chip rather than a glyph */
.t3-mode {
  font-size: 11px; font-weight: 700; letter-spacing: 0.06em;
  border: 1px solid rgba(255, 255, 255, 0.45); min-width: 30px;
}
/* exact colours is the mode away from the default: it wears the mode's
   outline so the reader sees it is on */
.t3-flat { margin-left: 2px; }
/* the hand and the mouse: the one on wears the outline, the other is a
   plain button that switches to it */
.t3-pointer { min-width: 26px; }
.t3-on { border: 1px solid rgba(255, 255, 255, 0.45); color: #fff; }
.t3-sep {
  width: 1px; height: 16px; margin: 0 4px;
  background: rgba(255, 255, 255, 0.3);
}
/* The shared select, dressed for a dark bar. `:deep` because the control is
   <fp-select>'s own element: the charter's control is reused, only its skin
   follows the chrome — a private copy of a select is what the gate refuses,
   and rightly. */
.t3-style { margin-left: 4px; }
.t3-style :deep(.fp-sel) {
  height: 24px; max-width: 160px; padding: 0 20px 0 6px;
  border: 1px solid rgba(255, 255, 255, 0.45); border-radius: 3px;
  background-color: transparent; color: #fff;
  font-size: 11.5px; line-height: 1;
}
.t3-style :deep(.fp-sel:hover) { background-color: rgba(255, 255, 255, 0.16); }
.t3-style :deep(.fp-sel:focus-visible) { outline: 1px solid rgba(255, 255, 255, 0.7); outline-offset: -1px; }
/* the popup list is drawn by the system, on the system's own ground */
.t3-style :deep(.fp-sel option) { color: #1c2430; background: #fff; }
</style>
