<template>
  <div class="fc-host">
    <Teleport v-if="inPanel" :to="panelEntry && panelEntry.el" :disabled="!panelEntry">
      <div v-show="open && !!panelEntry" class="fc fc-in-panel">
        <span class="fc-title fc-sr-only">{{ headText }}</span>
        <div
          ref="panelBody"
          class="fc-body fc-panel-body"
          :class="{ 'fc-panel-fixed': !resizable }"
          @scroll.capture.passive="onPanelScroll"
        ><slot /></div>
      </div>
    </Teleport>
    <Teleport v-else :to="dockTarget || 'body'" :disabled="!docked || !dockTarget">
      <div
        v-show="open"
        class="fc"
        :class="{ 'fc-fixed': !resizable, 'fc-docked': docked, 'fc-dock-left': dock === 'left', 'fc-dock-right': dock === 'right', 'fc-dock-bottom': dock === 'bottom' }"
        :style="cardStyle"
        @pointerdown.capture="raise"
      >
        <div class="fc-head" :class="{ 'fc-head-docked': docked }" @pointerdown="onDown">
          <span class="fc-head-text">
            <span class="fc-title">{{ title }}</span>
            <span v-if="target" class="fc-target" :title="target">&middot; {{ target }}</span>
          </span>
          <span class="fc-tools" @pointerdown.stop>
            <button v-if="dock !== 'left' && dockLeft" type="button" class="fc-tool" title="Dock left" @click="setDock('left')"><fp-icon icon="fespp-card-dock-left" chrome :size="15" /></button>
            <button v-if="dock !== 'right' && dockRight" type="button" class="fc-tool" title="Dock right" @click="setDock('right')"><fp-icon icon="fespp-card-dock-right" chrome :size="15" /></button>
            <button v-if="dock !== 'bottom' && dockBottom" type="button" class="fc-tool" title="Dock at the bottom" @click="setDock('bottom')"><fp-icon icon="fespp-card-dock-bottom" chrome :size="15" /></button>
            <button v-if="docked" type="button" class="fc-tool" title="Float" @click="setDock('float')"><fp-icon icon="fespp-card-float" chrome :size="15" /></button>
            <button type="button" class="fc-close" title="Close" @click="$emit('close')">×</button>
          </span>
        </div>
        <div class="fc-body"><slot /></div>
        <div v-if="resizable && !docked" class="fc-resize" title="resize" @pointerdown.stop="onResizeDown"></div>
        <div v-if="resizable && docked && dock !== 'bottom'" class="fc-resize-x" title="resize width" @pointerdown.stop="onResizeDown"></div>
        <div v-if="resizable && dock === 'bottom'" class="fc-resize-y" title="resize height" @pointerdown.stop="onResizeDown"></div>
      </div>
    </Teleport>
  </div>
</template>

<script>
/*
 * A draggable, resizable tool card, absolutely positioned inside its view
 * container. Dragging keeps only the title bar reachable, not the whole card:
 * the card may hang off the container's edges, which clip it, so a tall card
 * still has room to move. The host sets the default size per tool via
 * `width` / `height`; the user can then resize. The default slot holds the
 * tool's content. Visibility is the `open` prop, applied as a v-show on the
 * card element itself so that it still applies once the card is teleported
 * into a dock column.
 *
 * `target` names what the tool acts on, after the title ("Slicers · Geogrid"):
 * the host writes it, the card only shows it, ellipsised, with the full text
 * in the tooltip. Empty means the tool has no single target to name.
 *
 * Docking: the dock-left / dock-right / dock-bottom buttons of the title bar
 * move the card into the host's left / right column or its bottom row
 * (`dockLeft` / `dockRight` / `dockBottom` are CSS selectors of those flex
 * boxes, beside and under the render) via <Teleport>; the float button
 * brings it back. Cards in one column stack and share its height; the
 * column's width follows the widest card (width-only resize on the inner
 * edge). Cards in the bottom row stand side by side and share its width;
 * the row's height follows the tallest card (height-only resize on the top
 * edge). Emits dock(mode) and geometry({x, y, w, h, dock}).
 *
 * Decoupled from any picker: open it from a toolbar, a radial menu, anything.
 *
 * Panel mode (`inPanel`): the card lives in a panel of the view's dock, which
 * carries the tab, the title and the close. The card then renders only its
 * body, with no header, no drag, no resize, no geometry event and no z-order.
 * The dock registers each open panel in window.__fpCardSlots under the card's
 * `panelSlot` ({el, api}); while that entry exists the body is teleported into
 * `el`, otherwise it stays in place (the host keeps it in a hidden reservoir).
 * The body is never unmounted, so a closed card keeps its client state. The
 * panel's tab gets the text the header would show (title, then target); the
 * card keeps that text too, in a `.fc-title` read by screen readers only.
 */
import { reactive, toRaw } from "vue";
import FpIcon from "../../../_shared/components/FpIcon.vue";

// The dock's registry of open card panels, shared with the dock bundle through
// the one global Vue: slot key -> {el, api}, present while the panel exists.
// Whichever bundle comes first creates it.
function cardSlots() {
  if (!window.__fpCardSlots) window.__fpCardSlots = reactive(new Map());
  return window.__fpCardSlots;
}

// Shared across all card instances: the next "bring to front" z-index.
let zTop = 5;

const GRAB = 60;   // px of a floating card that must stay inside horizontally
const HEAD = 32;   // px: the title bar must stay inside vertically

export default {
  name: "FloatingCard",
  components: { FpIcon },
  props: {
    title: { type: String, default: "" },
    target: { type: String, default: "" },
    open: { type: Boolean, default: true },
    x0: { type: Number, default: 52 },
    y0: { type: Number, default: 8 },
    width: { type: Number, default: 260 },
    height: { type: Number, default: 0 }, // 0 = auto (fit content)
    minWidth: { type: Number, default: 180 },
    minHeight: { type: Number, default: 120 },
    // false -> the card fits its content exactly and has no resize handle
    resizable: { type: Boolean, default: true },
    // CSS selectors of the host's dock columns; empty = no docking that side
    dockLeft: { type: String, default: "" },
    dockRight: { type: String, default: "" },
    dockBottom: { type: String, default: "" },
    // where the card starts: "float" | "left" | "right" | "bottom"; the host passes the
    // dock it saved, so a reload finds the card docked where it was left
    dock0: { type: String, default: "float" },
    // true -> the card is shown in the dock panel registered under `panelSlot`
    inPanel: { type: Boolean, default: false },
    panelSlot: { type: String, default: "" },
  },
  // `geometry` says where the card ended up after a drag, a resize or a
  // dock change ({x, y, w, h, dock}), for the host to remember
  emits: ["close", "dock", "geometry"],
  data() {
    // the card mounts floating and docks once its column is in the page:
    // a teleport to a target the page does not hold yet mounts nothing
    return { x: this.x0, y: this.y0, w: this.width, h: this.height, z: 5, drag: null, resize: null,
      dock: "float" };
  },
  computed: {
    docked() { return this.dock !== "float"; },
    // what the header shows: "Slicers · Geogrid"
    headText() { return this.target ? `${this.title} · ${this.target}` : this.title; },
    panelEntry() {
      if (!this.inPanel || !this.panelSlot) return null;
      const e = cardSlots().get(this.panelSlot);
      // the raw panel api: its methods must not run through a reactive proxy
      return e && e.el ? { el: e.el, api: toRaw(e.api) } : null;
    },
    dockTarget() {
      if (this.dock === "left") return this.dockLeft || null;
      if (this.dock === "right") return this.dockRight || null;
      if (this.dock === "bottom") return this.dockBottom || null;
      return null;
    },
    cardStyle() {
      if (this.dock === "bottom") {
        // a flex item of the bottom row, stretched to its height (set by
        // syncColumn: the tallest docked card's)
        return { height: "100%", minWidth: 0 };
      }
      if (this.docked) {
        // stacked flex item of the dock column, stretched to its width. The
        // column's width is set by syncColumn() (max of its docked cards'
        // widths), never by the content's intrinsic width, which would let
        // a wide select or button row blow the column up.
        return { width: "100%", minWidth: 0 };
      }
      if (!this.resizable) {
        return { left: this.x + "px", top: this.y + "px", zIndex: this.z };
      }
      return {
        left: this.x + "px",
        top: this.y + "px",
        width: this.w + "px",
        height: this.h ? this.h + "px" : "auto",
        minHeight: this.minHeight + "px",
        zIndex: this.z,
      };
    },
  },
  methods: {
    raise() {
      this.z = ++zTop;
    },
    // Moving the body between its reservoir and its panel resets the scroll
    // offsets of everything in it: they are noted as the user scrolls and put
    // back each time the body shows in its panel.
    onPanelScroll(e) {
      if (this.settling) return;
      const t = e.target;
      if (t && t.nodeType === 1) this.scrollMemo.set(t, [t.scrollLeft, t.scrollTop]);
    },
    restoreScroll() {
      const body = this.$refs.panelBody;
      if (!body) return;
      for (const [el, [l, t]] of this.scrollMemo) {
        if (!body.contains(el)) { this.scrollMemo.delete(el); continue; }
        el.scrollLeft = l;
        el.scrollTop = t;
      }
    },
    reportGeometry() {
      this.$emit("geometry", { x: this.x, y: this.y, w: this.w, h: this.h, dock: this.dock });
    },
    setDock(mode) {
      const prev = this.dockTarget;
      this.dock = mode;
      this.$emit("dock", mode);
      this.reportGeometry();
      this.$nextTick(() => {
        if (prev) this.syncColumn(prev);
        if (this.dockTarget) this.syncColumn(this.dockTarget);
      });
    },
    syncColumn(sel) {
      // the dock column's width is that of the widest open, resizable card
      // docked in it; each card keeps its own entry on the column element
      const col = sel ? document.querySelector(sel) : null;
      if (!col) return;
      col.__fcW = col.__fcW || new Map();
      // the bottom row is sized by height, the columns by width
      const row = sel === this.dockBottom;
      const size = row ? (this.h || this.height || 300) : this.w;
      const mine = (this.docked && this.dockTarget === sel && this.open && this.resizable) ? size : 0;
      col.__fcW.set(this, mine);
      const ws = Array.from(col.__fcW.values()).filter((v) => v > 0);
      col.style[row ? "height" : "width"] = ws.length ? Math.max(...ws) + "px" : "";
    },
    container() {
      // the view container the floating card is positioned in (the
      // teleport wrapper's parent, not the dock column)
      const host = this.$el;
      return host && host.parentElement ? host.parentElement : null;
    },
    onDown(e) {
      if (this.docked) return; // docked cards don't move
      this.drag = { px: e.clientX, py: e.clientY, x: this.x, y: this.y };
      window.addEventListener("pointermove", this.onMove);
      window.addEventListener("pointerup", this.onUp);
    },
    onMove(e) {
      if (!this.drag) return;
      const dx = e.clientX - this.drag.px;
      const dy = e.clientY - this.drag.py;
      const p = this.container();
      const el = this.cardEl();
      const cw = p ? p.clientWidth : Infinity;
      const ch = p ? p.clientHeight : Infinity;
      const ow = el ? el.offsetWidth : this.w;
      // free movement: keep GRAB px inside horizontally and the title bar
      // inside vertically; the container clips whatever hangs out
      const minX = -(ow - GRAB);
      const maxX = cw - GRAB;
      const maxY = Math.max(0, ch - HEAD);
      this.x = Math.max(minX, Math.min(this.drag.x + dx, maxX));
      this.y = Math.max(0, Math.min(this.drag.y + dy, maxY));
    },
    onUp() {
      const moved = !!this.drag;
      this.drag = null;
      window.removeEventListener("pointermove", this.onMove);
      window.removeEventListener("pointerup", this.onUp);
      if (moved) this.reportGeometry();
    },
    cardEl() {
      // the teleported card element (this.$el is the in-place wrapper)
      const host = this.$el;
      if (!host) return null;
      const inPlace = host.querySelector && host.querySelector(":scope > .fc");
      if (inPlace) return inPlace;
      if (this.dockTarget) {
        const col = document.querySelector(this.dockTarget);
        return col ? Array.from(col.children).find((c) => c.__fcOwner === this) || null : null;
      }
      return null;
    },
    onResizeDown(e) {
      const el = this.cardEl();
      this.resize = { px: e.clientX, py: e.clientY, w: this.w, h: this.h || (el ? el.offsetHeight : this.minHeight) };
      window.addEventListener("pointermove", this.onResizeMove);
      window.addEventListener("pointerup", this.onResizeUp);
    },
    onResizeMove(e) {
      if (!this.resize) return;
      const dy = e.clientY - this.resize.py;
      const p = this.container();
      if (this.dock === "bottom") {
        // handle on the top edge: up heightens, down lowers
        const maxH = p ? Math.max(this.minHeight, p.clientHeight + this.resize.h - 80) : Infinity;
        this.h = Math.max(this.minHeight, Math.min(this.resize.h - dy, maxH));
        this.syncColumn(this.dockTarget);
        return;
      }
      if (this.docked) {
        // handle on the inner edge: toward the render widens, away narrows
        const dx = (this.dock === "right" ? -1 : 1) * (e.clientX - this.resize.px);
        const maxW = p ? Math.max(this.minWidth, p.clientWidth - 120) : Infinity;
        this.w = Math.max(this.minWidth, Math.min(this.resize.w + dx, maxW));
        this.syncColumn(this.dockTarget);
        return;
      }
      const dx = e.clientX - this.resize.px;
      const maxW = p ? Math.max(this.minWidth, p.clientWidth - this.x) : Infinity;
      const maxH = p ? Math.max(this.minHeight, p.clientHeight - this.y) : Infinity;
      this.w = Math.max(this.minWidth, Math.min(this.resize.w + dx, maxW));
      this.h = Math.max(this.minHeight, Math.min(this.resize.h + dy, maxH));
    },
    onResizeUp() {
      const resized = !!this.resize;
      this.resize = null;
      window.removeEventListener("pointermove", this.onResizeMove);
      window.removeEventListener("pointerup", this.onResizeUp);
      if (resized) this.reportGeometry();
    },
  },
  watch: {
    open(now) {
      if (this.inPanel) return;
      // a closed docked card must not keep the column wide
      if (this.docked) this.$nextTick(() => this.syncColumn(this.dockTarget));
      // a card that opens comes to the front. Cards are never destroyed, only
      // hidden (v-show, so they keep their geometry and state), and a hidden
      // card keeps its old z-index: without the raise, reopening it would put
      // it under the cards opened since, and its toolbar button would seem to
      // do nothing.
      if (now) this.raise();
    },
  },
  created() {
    this.scrollMemo = new Map();
    this.settling = false;
    // the panel's tab carries the header's text
    this.$watch(() => [this.panelEntry, this.headText], ([entry, text]) => {
      if (entry && text && entry.api && typeof entry.api.setTitle === "function") entry.api.setTitle(text);
    }, { immediate: true });
    // after the teleport has moved the body, then once the panel is laid out;
    // meanwhile a set clamped by a panel not laid out yet fires a scroll event
    // that must not be taken for the user's
    this.$watch(() => !!(this.open && this.panelEntry) && this.panelEntry.el, (el) => {
      if (!el) return;
      this.settling = true;
      this.restoreScroll();
      requestAnimationFrame(() => {
        this.restoreScroll();
        requestAnimationFrame(() => { this.settling = false; });
      });
    }, { flush: "post" });
  },
  mounted() {
    if (this.inPanel) return;
    // tag the card element so cardEl() can find it once teleported
    const el = this.$el && this.$el.querySelector && this.$el.querySelector(":scope > .fc");
    if (el) el.__fcOwner = this;
    // starts docked (a saved geometry, or the tool's own dock): once the
    // column is in the page, the card goes there and the column learns its size
    const want = ["left", "right", "bottom"].includes(this.dock0) ? this.dock0 : "float";
    if (want !== "float") {
      const sel = { left: this.dockLeft, right: this.dockRight, bottom: this.dockBottom }[want];
      let tries = 0;
      const settle = () => {
        if (sel && document.querySelector(sel)) {
          this.dock = want;
          this.$nextTick(() => this.syncColumn(this.dockTarget));
        } else if (tries++ < 100) {
          requestAnimationFrame(settle);
        }
      };
      settle();
    }
  },
  beforeUnmount() {
    if (this.dockTarget) {
      const col = document.querySelector(this.dockTarget);
      if (col && col.__fcW) { col.__fcW.delete(this); this.dock = "float"; this.syncColumn(this.dockTarget); }
    }
    window.removeEventListener("pointermove", this.onMove);
    window.removeEventListener("pointerup", this.onUp);
    window.removeEventListener("pointermove", this.onResizeMove);
    window.removeEventListener("pointerup", this.onResizeUp);
  },
};
</script>

<style>
@import "../../../_shared/tokens.css";
</style>

<style scoped>
.fc-host { display: contents; }
.fc {
  position: absolute; z-index: 5;
  display: flex; flex-direction: column; max-height: calc(100% - 16px);
  background: #fff; border: 1px solid #bbb; border-radius: 4px;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.25);
  font-family: system-ui, sans-serif; font-size: 13px;
}
.fc-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 4px 8px; background: var(--fp-accent); color: #fff;
  border-radius: 4px 4px 0 0; cursor: move; user-select: none;
  font-size: 12px; font-weight: 600; flex: 0 0 auto;
}
/* title + target: the target shrinks and ellipsises, the title never does */
.fc-head-text { display: flex; align-items: baseline; min-width: 0; gap: 5px; }
.fc-title { flex: 0 0 auto; }
.fc-target { flex: 0 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 400; opacity: 0.85; }
.fc-tools { display: flex; align-items: center; gap: 6px; flex: 0 0 auto; }
/* buttons, not spans: the head must be reachable with the keyboard, so a
   card can be docked or closed without a mouse */
.fc-tool, .fc-close { border: none; background: transparent; color: inherit; font: inherit; cursor: pointer; }
.fc-tool { opacity: 0.85; font-size: 13px; line-height: 1; padding: 0; display: inline-flex; }
.fc-tool:hover, .fc-tool:focus-visible { opacity: 1; }
.fc-close { opacity: 0.85; padding: 0 2px; }
.fc-close:hover, .fc-close:focus-visible { opacity: 1; }
/* non-resizable: the card hugs its content (a tool widget of fixed size) */
.fc-fixed { width: max-content; height: max-content; max-height: none; }
.fc-fixed .fc-body { flex: 0 0 auto; overflow: visible; padding: 2px; }
/* min-width:0 lets the body shrink below its content's intrinsic width */
.fc-body { overflow: auto; padding: 6px; flex: 1 1 auto; min-height: 0; min-width: 0; }
/* in a dock panel: no frame of its own, the panel is the frame */
.fc.fc-in-panel {
  position: relative; z-index: auto; width: 100%; height: 100%; max-height: none;
  border: none; border-radius: 0; box-shadow: none;
}
.fc-sr-only {
  position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
  overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0;
}
/* the body fills the panel's div, its new container, and takes over what it
   inherited from the card frame */
.fc-panel-body {
  box-sizing: border-box; width: 100%; height: 100%;
  background: #fff; font-family: system-ui, sans-serif; font-size: 13px;
}
.fc-panel-fixed { padding: 2px; }
.fc-resize {
  position: absolute; right: 0; bottom: 0; width: 14px; height: 14px;
  cursor: nwse-resize; user-select: none;
  background: linear-gradient(135deg, transparent 0 50%, #bbb 50% 60%,
    transparent 60% 72%, #bbb 72% 82%, transparent 82%);
  border-radius: 0 0 4px 0;
}
/* docked: a stacked item of the dock column, with an equal share of the
   height, stretched to the column's width, no shadow, no drag cursor */
.fc-docked {
  position: relative; flex: 1 1 0; min-height: 40px; max-height: none;
  border-radius: 0; box-shadow: none; overflow: hidden;
  border-left: none; border-right: none; border-top: none;
}
.fc-docked.fc-fixed { flex: 0 0 auto; }
.fc-head-docked { cursor: default; border-radius: 0; }
/* width handle on the INNER edge (the one touching the render) */
.fc-resize-x {
  position: absolute; top: 0; bottom: 0; width: 6px; cursor: ew-resize;
  user-select: none; background: transparent;
}
.fc-dock-left .fc-resize-x { right: 0; }
.fc-dock-right .fc-resize-x { left: 0; }
.fc-resize-x:hover { background: rgba(21, 101, 192, 0.25); }
/* docked at the bottom: side by side in the row under the render, the
   height handle on the top edge */
.fc-dock-bottom { flex: 1 1 0; border-top: 1px solid #bbb; border-left: 1px solid #ddd; border-bottom: none; }
.fc-resize-y {
  position: absolute; left: 0; right: 0; top: 0; height: 6px; cursor: ns-resize;
  user-select: none; background: transparent; z-index: 1;
}
.fc-resize-y:hover { background: rgba(21, 101, 192, 0.25); }
</style>
