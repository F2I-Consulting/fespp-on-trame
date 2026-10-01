<template>
  <div class="fc-host">
    <Teleport :to="dockTarget || 'body'" :disabled="!docked || !dockTarget">
      <div
        v-show="open"
        class="fc"
        :class="{ 'fc-fixed': !resizable, 'fc-docked': docked, 'fc-dock-left': dock === 'left', 'fc-dock-right': dock === 'right' }"
        :style="cardStyle"
        @pointerdown.capture="raise"
      >
        <div class="fc-head" :class="{ 'fc-head-docked': docked }" @pointerdown="onDown">
          <span class="fc-head-text">
            <span class="fc-title">{{ title }}</span>
            <span v-if="target" class="fc-target" :title="target">&middot; {{ target }}</span>
          </span>
          <span class="fc-tools" @pointerdown.stop>
            <button v-if="dock !== 'left' && dockLeft" type="button" class="fc-tool" title="Dock left" @click="setDock('left')">&#9703;</button>
            <button v-if="dock !== 'right' && dockRight" type="button" class="fc-tool" title="Dock right" @click="setDock('right')">&#9707;</button>
            <button v-if="docked" type="button" class="fc-tool" title="Float" @click="setDock('float')">&#10064;</button>
            <button type="button" class="fc-close" title="Close" @click="$emit('close')">×</button>
          </span>
        </div>
        <div class="fc-body"><slot /></div>
        <div v-if="resizable && !docked" class="fc-resize" title="resize" @pointerdown.stop="onResizeDown"></div>
        <div v-if="resizable && docked" class="fc-resize-x" title="resize width" @pointerdown.stop="onResizeDown"></div>
      </div>
    </Teleport>
  </div>
</template>

<script>
/*
 * A draggable + RESIZABLE tool card, absolutely positioned inside its view
 * container. Dragging keeps only the TITLE BAR reachable (the card may hang
 * off the container's edges, which clips it) — clamping the whole card inside
 * left a tall card with a few pixels of play. The host sets the default size
 * per tool via `width` / `height`; the user can then resize. Default slot =
 * the tool's content. Visibility is the `open` prop (a v-show on the card
 * itself — it must survive the teleport below).
 *
 * `target` names what the tool acts on, after the title ("Slicers · Geogrid"):
 * the host writes it, the card only shows it — ellipsised, the full text in
 * the tooltip. Empty = the tool has no single target to name.
 *
 * DOCKING: ◧ / ◨ in the title bar move the card into the host's LEFT / RIGHT
 * dock column (`dockLeft` / `dockRight` = CSS selectors of those columns,
 * flex columns beside the render) via <Teleport>; ❐ floats it back. Cards in
 * one column STACK and share its height; the column's width follows the
 * widest card (width-only resize on the inner edge). Emits dock(mode).
 *
 * Decoupled from any picker: open it from a toolbar, a radial menu, anything.
 */

// Shared across all card instances: the next "bring to front" z-index.
let zTop = 5;

const GRAB = 60;   // px of a floating card that must stay inside horizontally
const HEAD = 32;   // px: the title bar must stay inside vertically

export default {
  name: "FloatingCard",
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
    // where the card starts: "float" | "left" | "right" — what the host
    // remembered from the last session, so a reload finds the card docked
    // where it was left
    dock0: { type: String, default: "float" },
  },
  // `geometry` says where the card ended up after a drag, a resize or a
  // dock change ({x, y, w, h, dock}), for the host to remember
  emits: ["close", "dock", "geometry"],
  data() {
    return { x: this.x0, y: this.y0, w: this.width, h: this.height, z: 5, drag: null, resize: null,
      dock: ["left", "right"].includes(this.dock0) ? this.dock0 : "float" };
  },
  computed: {
    docked() { return this.dock !== "float"; },
    dockTarget() {
      if (this.dock === "left") return this.dockLeft || null;
      if (this.dock === "right") return this.dockRight || null;
      return null;
    },
    cardStyle() {
      if (this.docked) {
        // stacked flex item of the dock column, stretched to its width. The
        // COLUMN's width is set by syncColumn() (max of its docked cards'
        // widths) — never by the content's intrinsic width, which would
        // let a wide select / button row blow the column up.
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
      // the dock column's width = the widest OPEN card docked in it; each
      // card keeps its own entry on the column element
      const col = sel ? document.querySelector(sel) : null;
      if (!col) return;
      col.__fcW = col.__fcW || new Map();
      const mine = (this.docked && this.dockTarget === sel && this.open && this.resizable) ? this.w : 0;
      col.__fcW.set(this, mine);
      const ws = Array.from(col.__fcW.values()).filter((v) => v > 0);
      col.style.width = ws.length ? Math.max(...ws) + "px" : "";
    },
    container() {
      // the view container the floating card is positioned in (the
      // teleport wrapper's parent — NOT the dock column)
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
      // free movement: keep GRAB px inside horizontally, the title bar inside
      // vertically — the container clips whatever hangs out
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
      // a closed docked card must not keep the column wide
      if (this.docked) this.$nextTick(() => this.syncColumn(this.dockTarget));
      // ...and one that OPENS comes to the front. A card is never destroyed,
      // only hidden (v-show, so it keeps its geometry and its state), and a
      // hidden card kept the z it was left with — so opening one from the
      // toolbar could put it UNDER the cards opened since: the button looked
      // dead while the card was there all along, behind another.
      if (now) this.raise();
    },
  },
  mounted() {
    // tag the card element so cardEl() can find it once teleported
    const el = this.$el && this.$el.querySelector && this.$el.querySelector(":scope > .fc");
    if (el) el.__fcOwner = this;
    // born docked (a remembered geometry): the column must learn its width
    if (this.docked && this.dockTarget) this.$nextTick(() => this.syncColumn(this.dockTarget));
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
/* buttons, not spans: the head is reached with the keyboard too, and a
   card nobody can close without a mouse is a card that stays open */
.fc-tool, .fc-close { border: none; background: transparent; color: inherit; font: inherit; cursor: pointer; }
.fc-tool { opacity: 0.8; font-size: 13px; line-height: 1; padding: 0; }
.fc-tool:hover, .fc-tool:focus-visible { opacity: 1; }
.fc-close { opacity: 0.85; padding: 0 2px; }
.fc-close:hover, .fc-close:focus-visible { opacity: 1; }
/* non-resizable: the card hugs its content (e.g. the fixed ptc camera widget) */
.fc-fixed { width: max-content; height: max-content; max-height: none; }
.fc-fixed .fc-body { flex: 0 0 auto; overflow: visible; padding: 2px; }
/* min-width:0 lets the body shrink below its content's intrinsic width */
.fc-body { overflow: auto; padding: 6px; flex: 1 1 auto; min-height: 0; min-width: 0; }
.fc-resize {
  position: absolute; right: 0; bottom: 0; width: 14px; height: 14px;
  cursor: nwse-resize; user-select: none;
  background: linear-gradient(135deg, transparent 0 50%, #bbb 50% 60%,
    transparent 60% 72%, #bbb 72% 82%, transparent 82%);
  border-radius: 0 0 4px 0;
}
/* docked: a stacked item of the dock column — equal share of the height,
   stretched to the column's width, no shadow, no drag cursor */
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
</style>
