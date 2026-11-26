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
        <fp-icon icon="fespp-view-hand" chrome :size="18" />
      </button>
      <span :title="empty ? EMPTY_WHY : ''">
        <button type="button" class="t3-btn t3-pointer" :class="{ 't3-on': cursor }"
                role="radio" :aria-checked="cursor ? 'true' : 'false'" data-t3-mouse
                :disabled="empty"
                title="Show position: the scene stays still, the pointer reads what is under it — position, object, wellbore, cell and property value. The hand moves the scene again"
                @click="!cursor && $emit('set-cursor', true)">
          <fp-icon icon="fespp-view-mouse" chrome :size="18" />
        </button>
      </span>
    </span>

    <span class="t3-sep"></span>

    <!-- Interaction mode, per view. The label shows the mode the view is IN
         and the tooltip says what a click does: a label that tried to be
         both the state and the effect would be unreadable. -->
    <button type="button" class="t3-btn t3-mode" :title="modeTitle"
            @click="$emit('set-mode', is2d ? '3D' : '2D')">{{ is2d ? "2D" : "3D" }}</button>

    <!-- The vertical domain the view draws (the PO, 28/10): depth by
         default, time on a click — offered when the data holds the other. Like
         the mode, the label is the domain the view IS in; the objects of
         the other keep their tick and come back on the switch. No tooltip
         on depth vs time (the manager, 29/10). -->
    <button v-if="domainOffered" type="button" class="t3-btn t3-mode t3-domain"
            :class="{ 't3-time': isTime }" data-t3-domain
            @click="$emit('set-domain', isTime ? 'depth' : 'time')">{{ isTime ? "Time" : "Depth" }}</button>

    <!-- This view's vertical exaggeration: slid, or typed for a value the
         slider does not stop at. -->
    <fp-z-scale class="t3-z" :model-value="zScale" title="Vertical exaggeration of this view"
                @update:model-value="$emit('set-zscale', $event)" />

    <!-- How every block of this view is DRAWN. It sits here rather than in
         a card of its own (a card to open, move and close is too much for a
         single choice), beside the mode it reads with: both say how the
         view LOOKS, neither says what it shows. -->
    <span v-if="(repStyles || []).length" class="t3-style">
      <fp-select :model-value="repStyle" :options="styleOptions" :disabled="bare"
                 :title="bare ? BARE_STYLE_WHY : 'How every block of this view is drawn'"
                 @update:model-value="$emit('set-style', $event)" />
    </span>

    <!-- Shading, beside how the view is drawn: a lit surface shows a
         different colour than its legend says, so the flat mode offers the
         legend's colours exactly. The glyph shows the mode it is IN, the
         tooltip what a click does. Offered on the Earth too: the globe is
         lit as well. -->
    <span :title="bare ? BARE_STYLE_WHY : ''">
      <button type="button" class="t3-btn t3-flat" :class="{ 't3-on': flat }" :title="flatTitle"
              :disabled="bare" :aria-pressed="flat ? 'true' : 'false'" @click="$emit('set-flat', !flat)">
        <fp-icon :icon="flat ? 'fespp-view-light-off' : 'fespp-view-light-on'" chrome :size="18" />
      </button>
    </span>

    <span class="t3-sep"></span>

    <!-- Framings. On the Earth the first one frames the whole planet, the
         others are shown disabled rather than dropped: the bounds they aim at
         are local-CRS metres, which in ECEF point at the other side of the
         planet. The reason is in the tooltip, carried by the span because a
         disabled button gets no pointer events. -->
    <span class="t3-group" :title="globe ? GLOBE_WHY : empty ? EMPTY_WHY : ''">
      <button type="button" class="t3-btn" :disabled="empty && !globe"
              :title="globe ? 'Frame the whole Earth' : 'Frame everything in this view'"
              @click="globe ? $emit('frame', 'earth') : $emit('reset')">
        <fp-icon icon="fespp-view-frame" chrome :size="18" />
      </button>
      <!-- the camera moves the mouse alone cannot make, the axis looks
           among them: the Navigation card of this view, opened and closed
           here (a view drawing one thing on its own has no cards) -->
      <button v-if="!bare" type="button" class="t3-btn" :class="{ 't3-on': navOpen }" data-t3-nav
              :disabled="globe || empty" :aria-pressed="navOpen ? 'true' : 'false'" :title="NAV_TITLE"
              @click="$emit('navigation')">
        <fp-icon icon="fespp-navigation" chrome :size="18" />
      </button>
    </span>

    <!-- A view drawing one thing on its own has no cards: its camera is
         linked from here, with the last 3D view of the data used. -->
    <template v-if="linkable">
      <span class="t3-sep"></span>
      <button type="button" class="t3-btn" :class="{ 't3-on': linked }" data-t3-link
              :aria-pressed="linked ? 'true' : 'false'" :title="linkTitle"
              @click="$emit('toggle-link')">
        <fp-icon :icon="linked ? 'fespp-view-linked' : 'fespp-view-unlinked'" chrome :size="18" />
      </button>
    </template>
  </div>
</template>

<script>
/*
 * The camera strip of ONE 3D view's title bar: the hand or the mouse,
 * the interaction mode, how blocks are drawn, shading, framing and the
 * Navigation card's button.
 *
 * WHY IT IS CHROME AND NOT A CARD. These are gestures reached for in the
 * middle of a drag: a panel to open, move and close costs more than the
 * gesture is worth. They sit in the title bar, beside the tab, always open,
 * and they name the view they drive by sitting on it.
 *
 * WHY IT IS DRAWN LIKE THE BAR. Chrome is not a widget dropped on a bar,
 * with its own background, radius and weight: it is the bar. So the strip
 * has no ground of its own, its words are the tab's white, its glyphs the
 * application's own (widgets/_shared/icons) in the two inks of F2I made for
 * the dark ground — the chrome's light blue and the green —, and only the
 * hover says a button is there. Its dividers group what belongs together: the
 * pointer, how the view looks, the framings.
 *
 * Stateless, like every widget of this project:
 *   props in   — cursor (the mouse is on: show position, scene fixed; the
 *                hand otherwise), mode ("3D" | "2D"), globe (this view is
 *                on the Earth), repStyle / repStyles (how every block of the
 *                view is drawn), flat (no shading: the colours are the
 *                legend's), empty (the view shows nothing: the mouse
 *                that reads, the framings and the zoom greyed, the reason
 *                on hover; the settings stay), bare (one thing drawn on its
 *                own: the data's settings greyed, no card), linkable / linked
 *                (the camera link offered in the strip, and the views it
 *                moves with), navOpen (the Navigation card is open)
 *   events out — set-cursor(bool), set-mode(mode), reset(),
 *                navigation() — open or close the Navigation card, set-style(name),
 *                set-flat(bool), frame("earth") — offered on the Earth only,
 *                set-domain("depth" | "time") — vdomain / domains in,
 *                set-zscale(number) — zScale in, the view's exaggeration,
 *                toggle-link() — linkable only
 * The host computes every move (boot's nav_* controllers), so this strip and
 * the Navigation card move the camera through the SAME code.
 */
import FpIcon from "../../../_shared/components/FpIcon.vue";
import FpSelect from "../../../_shared/components/FpSelect.vue";
import FpZScale from "../../../_shared/components/FpZScale.vue";

const NAV_TITLE = "Navigation — frame the active object, centre or zoom on a pick, "
  + "look along an axis, parallel projection";

const GLOBE_WHY = "This view draws on the Earth — these framings are computed "
  + "on the data's own coordinates and would aim at the other side of the "
  + "planet. Use the globe button beside them, or the Globe card.";

// the view shows nothing yet: reading, framing and zooming act on nothing
// (the PO, 28/10: a button that cannot act is greyed, with why). The mode,
// the drawing style and the shading are settings: they hold for what comes
const EMPTY_WHY = "Nothing is shown in this view yet: open an eye in the tree";
// a view drawing the velocity model alone (the Stratigraphy panel's): the
// data's settings act on nothing there
const BARE_STYLE_WHY = "Only the velocity model is drawn here: how the data is drawn and its shading act in the 3D views";

export default {
  name: "Title3dView",
  components: { FpIcon, FpSelect, FpZScale },
  props: {
    // true = the mouse (show position, the scene held still); false = the hand
    cursor: { type: Boolean, default: false },
    mode: { type: String, default: "3D" },
    globe: { type: Boolean, default: false },
    // How every block of this view is drawn, and the styles on offer.
    // NOT named `style`: that is a reserved DOM attribute, so Vue takes the
    // value for CSS and the prop never arrives, and the element's whole
    // attribute serialisation breaks with it (the same trap as a prop named
    // like a DOM event, which emits <tag html-error />).
    repStyle: { type: String, default: "Surface" },
    repStyles: { type: Array, default: () => [] },
    // false = lit (the default), true = exact colours, no shading
    flat: { type: Boolean, default: false },
    // the view shows nothing: everything but the hand is greyed
    empty: { type: Boolean, default: false },
    // "depth" | "time": the vertical domain the view draws, and the domains
    // the loaded data holds (the switch is offered when it holds one)
    vdomain: { type: String, default: "depth" },
    domains: { type: Array, default: () => [] },
    // this view's vertical exaggeration
    zScale: { type: Number, default: 1 },
    // the view draws one thing on its own (the velocity model): the data's
    // settings are greyed with why, the domain switch offered whatever
    // the data holds — the velocity model has both
    bare: { type: Boolean, default: false },
    // the camera link offered here, and the titles of the views this one
    // moves with ("" = none)
    linkable: { type: Boolean, default: false },
    linked: { type: String, default: "" },
    // this view's Navigation card is open
    navOpen: { type: Boolean, default: false },
  },
  emits: ["set-cursor", "set-mode", "reset", "navigation", "set-style", "set-flat", "frame", "set-domain",
          "set-zscale", "toggle-link"],
  data() {
    return { NAV_TITLE, GLOBE_WHY, EMPTY_WHY, BARE_STYLE_WHY };
  },
  computed: {
    is2d() { return String(this.mode || "3D").toUpperCase() === "2D"; },
    styleOptions() { return (this.repStyles || []).map((s) => ({ value: s, label: s })); },
    modeTitle() {
      return this.is2d
        ? "Interaction: 2D — rotation is locked. Click for 3D"
        : "Interaction: 3D — drag to rotate. Click for 2D (rotation locked)";
    },
    isTime() { return this.vdomain === "time"; },
    // offered as soon as the data says its domain: the other one is drawn
    // converted, with the default law when no velocity model was made; a view
    // left in time keeps its way back even once the data is gone
    domainOffered() {
      return this.bare || this.isTime || (this.domains || []).length > 0;
    },
    linkTitle() {
      return this.linked
        ? `Moves with ${this.linked}: the cameras are linked. Click to unlink`
        : "Link the camera with the last 3D view of the data used: the two move together";
    },
    flatTitle() {
      return this.flat
        ? "Exact colors — no shading, the colors are the legend's. Click to shade"
        : "Shading on — colors are lit and can look different from the legend. Click for exact colors";
    },
  },
};
</script>

<style scoped>
/* Chrome of the dockview tab row (--dv-tabs-and-actions-container-*): the
   bar's ground and its white ink, hover only. */
.t3 {
  display: flex; align-items: center; gap: 1px; height: 100%;
  font-family: system-ui, sans-serif;
  max-width: 100%; overflow: hidden; pointer-events: auto;
  /* the bar's own colour: invisible, until tabs run under the strip */
  background: var(--dv-tabs-and-actions-container-background-color, #00436d);
}
/* A narrow group (two or three views side by side): the strip drops its
   least used controls rather than run over the tabs. The host wraps it in a
   size container spanning the row from the first tab to the right edge
   (app/views/render_panel.py); the hand, the mouse, the mode and the reset
   framing stay to the last. */
@container (max-width: 640px) {
  .t3 :deep(.fp-z-slider) { display: none; }
}
@container (max-width: 570px) {
  .t3-style { display: none; }
}
@container (max-width: 435px) {
  .t3 .t3-z { display: none; }
}
@container (max-width: 240px) {
  .t3 .t3-flat, .t3 .t3-sep { display: none; }
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
.t3-btn:hover:not(:disabled) { --fp-chrome-ic: #b9ddf6; }
/* the mode reads as a state, so it wears a chip rather than a glyph */
.t3-mode {
  font-size: 11px; font-weight: 700; letter-spacing: 0.06em;
  border: 1px solid rgba(255, 255, 255, 0.45); min-width: 30px;
}
/* exact colours is the mode away from the default: when on, it wears the
   t3-on outline */
.t3-flat { margin-left: 2px; }
/* the domain beside the mode; in time it is the mode away from the default */
.t3-domain { margin-left: 3px; min-width: 44px; }
.t3-domain.t3-time { background: rgba(255, 204, 128, 0.28); border-color: rgba(255, 224, 178, 0.8); }
.t3-z { margin-left: 4px; }
/* the hand and the mouse: the one on wears the outline, the other is a
   plain button that switches to it */
.t3-pointer { min-width: 26px; }
.t3-on { border: 1px solid rgba(255, 255, 255, 0.45); color: #fff; }
.t3-sep {
  width: 1px; height: 16px; margin: 0 4px;
  background: rgba(255, 255, 255, 0.3);
}
/* The shared select, dressed for a dark bar. `:deep` because the control is
   <fp-select>'s own element: the shared control is reused and only its skin
   follows the chrome (the eslint gate refuses a private <select> in a
   widget). */
.t3-style { margin-left: 4px; }
.t3-style :deep(.fp-sel) {
  height: 24px; max-width: 160px; padding: 0 20px 0 6px;
  border: 1px solid rgba(255, 255, 255, 0.45); border-radius: 3px;
  background-color: transparent; color: #fff;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 8 5'%3E%3Cpath d='M0 0h8L4 5z' fill='%23fff'/%3E%3C/svg%3E");
  background-position: right 7px center;
  font-size: 11.5px; line-height: 1;
}
.t3-style :deep(.fp-sel:hover) { background-color: rgba(255, 255, 255, 0.16); }
.t3-style :deep(.fp-sel:focus-visible) { outline: 1px solid rgba(255, 255, 255, 0.7); outline-offset: -1px; }
/* the popup list is drawn by the system, on the system's own ground */
.t3-style :deep(.fp-sel option) { color: #1c2430; background: #fff; }
</style>
