<template>
  <!-- One TDLaw as a track, side by side with the others as in a well
       correlation: the arrow down from its start, each interval a band
       coloured by its velocity on the view's colours, the velocity written
       beside it; each point's depth on the left — the main value, the same
       depth at the same height in every track (`scale`) — and its two-way
       time on the right, a click on either edits it, the box going with the
       focus. A point is DRAGGED to another depth, between its neighbours,
       its time kept, the velocities above and below it read again as it
       moves; a right-click on the band adds a point there, on a point
       removes it. Points lying on one another show as a numbered disc: a
       click lists them all, the one picked comes on top. The velocity of an
       interval is edited too: the time below it follows, the depths stay.
       A press anywhere on the track makes it the active one. -->
  <div class="tls" :class="{ 'tls-on': active }" @pointerdown="!active && $emit('active')">
    <law-head :name="name" :title="headTitle" :x="x" :y="y" :axes="axes" :why="why" :outside="outside"
              :placeable="placeable" removable @active="$emit('active')" @remove="$emit('remove')"
              @rename="$emit('column', { op: 'name_column', name: $event })"
              @place="$emit('column', { op: 'set_column', ...$event })" />
    <div ref="track" class="tls-track" :style="{ height: scale.height + 'px', width: W + 'px' }">
      <svg class="tls-svg" :width="W" :height="scale.height" aria-hidden="true">
        <rect v-for="b in bands" :key="'b' + b.i" class="tls-band" :x="BAND_X" :y="b.y0" :width="BAND_W"
              :height="Math.max(b.y1 - b.y0, 1)" :fill="colour(b.v)" />
        <rect class="tls-band tls-tail" :x="BAND_X" :y="lastY" :width="BAND_W"
              :height="Math.max(scale.height - 14 - lastY, 0)" :fill="colour(lastV)" />
        <line class="tls-line" :x1="LINE_X" :y1="firstY" :x2="LINE_X" :y2="scale.height - 12" />
        <polygon class="tls-arrow" :points="arrowHead" />
        <!-- the band: a right-click adds a point where the mouse is -->
        <rect class="tls-hit" :x="LINE_X - 10" y="0" :width="BAND_X + BAND_W - LINE_X + 14" :height="scale.height"
              @contextmenu.prevent.stop="menuAt($event, null)" />
        <!-- the points: dragged to another depth, a right-click removes one -->
        <template v-for="m in marks" :key="m.key">
          <g v-if="m.stack" class="tls-stack" @pointerdown.prevent.stop @click.stop="stackMenu($event, m.stack)"
             @contextmenu.prevent.stop="stackMenu($event, m.stack)">
            <title>{{ m.stack.to - m.stack.from + 1 }} points on one another: click to pick one</title>
            <circle :cx="LINE_X" :cy="m.stack.y" r="7" />
            <text :x="LINE_X" :y="m.stack.y + 3" text-anchor="middle">{{ m.stack.to - m.stack.from + 1 }}</text>
          </g>
          <circle v-else class="tls-dot"
                  :class="{ 'tls-dot-start': m.i === 0, 'tls-dot-drag': drag && drag.i === m.i, 'tls-dot-on': chosen === m.i }"
                  :cx="LINE_X" :cy="rowY(m.i)" r="5"
                  @pointerdown.prevent.stop="press(m.i, $event)" @contextmenu.prevent.stop="menuAt($event, m.i)" />
        </template>
      </svg>
      <!-- each point: its depth left, its time right; the start moves, it is
           not deleted -->
      <div v-for="(p, i) in laid" :key="'p' + i" class="tls-pt" :class="{ 'tls-pt-on': chosen === i }"
           :style="{ top: (labelYs[i] - 9) + 'px' }">
        <div class="tls-dep" :style="{ width: LEFT_W + 'px' }" @focusout="editing = null">
          <fp-num v-if="isEditing(i, 'depth')" class="tls-edit" size="sm" :digits="1" :model-value="p.depth"
                  :title="i === 0 ? 'Depth of the start, metres (a datum: not necessarily 0)' : 'Depth of this point, metres'"
                  @update:model-value="commit(i, 'depth', $event)" />
          <span v-else class="tls-val"
                :title="(i === 0 ? 'The start: ' : '') + 'click to edit the depth; drag the point to move it in depth, its time kept'"
                @click="edit(i, 'depth')">{{ fmtM(depthOf(i)) }}</span>
        </div>
        <div class="tls-twt" :style="{ left: (LEFT_W + AXIS_W) + 'px' }" @focusout="editing = null">
          <fp-num v-if="isEditing(i, 'twt')" class="tls-edit" size="sm" :digits="1" :model-value="p.twt"
                  :title="i === 0 ? 'Two-way time of the start, milliseconds' : 'Two-way time of this point, milliseconds'"
                  @update:model-value="commit(i, 'twt', $event)" />
          <template v-else>
            <span class="tls-val" :title="(i === 0 ? 'The start: ' : '') + 'click to edit the two-way time'"
                  @click="edit(i, 'twt')">{{ fmtMs(p.twt) }}</span>
            <fp-btn v-if="i > 0" tiny variant="bare" class="tls-del" label="×" title="Remove this point"
                    @click="$emit('edit', { op: 'del', index: i })" />
          </template>
        </div>
      </div>
      <!-- each interval: its velocity, edited in place (the time below follows) -->
      <div v-for="b in bands" v-show="b.y1 - b.y0 >= 30 || isEditing(b.i, 'vel')" :key="'v' + b.i" class="tls-vel"
           :class="{ 'tls-bad': b.v == null, 'tls-live': drag && (drag.i === b.i || drag.i === b.i - 1) }"
           :style="{ top: ((b.y0 + b.y1) / 2 - 8) + 'px', left: (LEFT_W + AXIS_W) + 'px' }"
           @focusout="editing = null">
        <fp-num v-if="isEditing(b.i, 'vel')" class="tls-edit" size="sm" :digits="0" :min="1" :model-value="b.v"
                title="Interval velocity, m/s: the time of the point below follows, its depth stays; the points under it shift with it"
                @update:model-value="commit(b.i, 'velocity', $event)" />
        <span v-else class="tls-val"
              :title="b.v == null ? 'Not below and later than the point above'
                                : 'Interval velocity: 2 × depth step / time step — click to edit it, the time below follows'"
              @click="b.v != null && edit(b.i, 'vel')">{{ b.v == null ? "out of order" : fmtV(b.v) }}</span>
      </div>
    </div>
    <fp-menu :at="menu" :title="name" :items="menuItems" @pick="menuPick" @close="menu = null" />
  </div>
</template>

<script>
import { fmtInt } from "../../../_shared/numfmt.js";
import FpBtn from "../../../_shared/components/FpBtn.vue";
import FpMenu from "../../../_shared/components/FpMenu.vue";
import FpNum from "../../../_shared/components/FpNum.vue";
import LawHead from "./LawHead.vue";
import { colourOn } from "./viridis.js";

const LEFT_W = 62;     // the depths, px
const AXIS_W = 30;     // the arrow and its band, px
const RIGHT_W = 84;    // the times and the velocities, px
const LINE_X = LEFT_W + 8;
const BAND_X = LINE_X + 5;
const BAND_W = 11;
const W = LEFT_W + AXIS_W + RIGHT_W;
const LEAST_M = 1;     // a dragged point stays this far, in depth, from its neighbours
const LABEL_H = 18;    // the labels of a track, at least this far apart, px
const STACK_PX = 6;    // points closer than this down the track lie on one another, px
const HOLD_MS = 4000;  // a released point waits this long for the model's answer

export default {
  name: "LawStrip",
  components: { FpBtn, FpMenu, FpNum, LawHead },
  props: {
    // [{depth, twt, velocity}], the start first (app/features/time_depth_law)
    rows: { type: Array, default: () => [] },
    // the model's one depth scale, the same in every track: {top (px, at the
    // depth z0), z0, slope (px per metre), height}
    scale: { type: Object, required: true },
    name: { type: String, default: "" },
    headTitle: { type: String, default: "" },
    active: { type: Boolean, default: false },
    why: { type: String, default: "" },
    // the view's colours of the velocity ({lo, hi, stops, log}), else
    // Viridis on vmin..vmax
    colors: { type: Object, default: () => ({}) },
    vmin: { type: Number, default: 1500 },
    vmax: { type: Number, default: 4500 },
    // where the TDLaw stands (null: not placed), the axes as the CRS names
    // them, whether it lies outside the zone, whether "Place" can find it a
    // spot (a zone exists)
    x: { type: Number, default: null },
    y: { type: Number, default: null },
    axes: { type: Array, default: () => ["Easting", "Northing"] },
    outside: { type: Boolean, default: false },
    placeable: { type: Boolean, default: false },
  },
  // `column`: a gesture on the TDLaw itself ({op: name_column | set_column, …})
  emits: ["edit", "active", "remove", "column"],
  data() {
    return { editing: null, drag: null, menu: null, menuOn: null, chosen: null, LEFT_W, AXIS_W, LINE_X, BAND_X, BAND_W, W };
  },
  computed: {
    laid() {
      return this.rows.map((r) => ({ ...r, y: this.yOf(r.depth) }));
    },
    // the labels, kept apart down the track; the points stay on the scale
    labelYs() {
      let last = -Infinity;
      return this.laid.map((_row, i) => {
        last = Math.max(this.rowY(i), last + LABEL_H);
        return last;
      });
    },
    // the runs of points lying on one another: [{from, to, y}]
    stacks() {
      const out = [];
      let from = 0;
      for (let i = 1; i <= this.laid.length; i += 1) {
        if (i === this.laid.length || this.rowY(i) - this.rowY(i - 1) >= STACK_PX) {
          if (i - 1 > from) out.push({ from, to: i - 1, y: (this.rowY(from) + this.rowY(i - 1)) / 2 });
          from = i;
        }
      }
      return out;
    },
    // what the axis paints, in order: the points, each stack's disc over its
    // own, the point picked on top of all
    marks() {
      const out = this.laid.map((_row, i) => i).filter((i) => i !== this.chosen).map((i) => ({ key: "d" + i, i }));
      this.stacks.forEach((s) => out.push({ key: "s" + s.from, stack: s }));
      if (this.chosen != null) out.push({ key: "d" + this.chosen, i: this.chosen });
      return out;
    },
    firstY() { return this.laid.length ? this.rowY(0) : 0; },
    lastY() { return this.laid.length ? this.rowY(this.laid.length - 1) : 0; },
    lastV() { return this.bands.length ? this.bands[this.bands.length - 1].v : null; },
    // each interval, its velocity read again while a point is dragged
    bands() {
      const out = [];
      for (let i = 1; i < this.laid.length; i += 1) {
        const dz = this.depthOf(i) - this.depthOf(i - 1);
        const dt = this.laid[i].twt - this.laid[i - 1].twt;
        const live = this.drag && (this.drag.i === i || this.drag.i === i - 1);
        const v = live ? (dz > 0 && dt > 0 ? 2000 * dz / dt : null) : this.laid[i].velocity;
        out.push({ i, v, y0: this.rowY(i - 1), y1: this.rowY(i) });
      }
      return out;
    },
    arrowHead() {
      const h = this.scale.height;
      return `${LINE_X - 5},${h - 14} ${LINE_X + 5},${h - 14} ${LINE_X},${h - 3}`;
    },
    // the right-click menu: on a point, its removal; on the band, a point there
    menuItems() {
      const on = this.menuOn;
      if (!on) return [];
      if (on.stack) {
        return this.laid.slice(on.stack.from, on.stack.to + 1).map((p, k) => ({
          key: "pick" + (on.stack.from + k), label: `${this.fmtM(p.depth)} · ${this.fmtMs(p.twt)}`,
          title: "This point, brought on top of the others: drag it, or right-click it to remove it",
        }));
      }
      if (on.i != null) {
        return [{ key: "del", label: "Remove this point", icon: "mdi-close", disabled: on.i === 0,
                  title: on.i === 0 ? "The start is moved, not removed: drag it, or edit its values" : "Remove this point from the law" }];
      }
      return [{ key: "add", label: `Add a point here: ${this.fmtM(on.depth)} · ${this.fmtMs(on.twt)}`, icon: "mdi-plus",
                title: "A point at this depth, its time read on the law — refine either value after" }];
    },
  },
  watch: {
    rows(now) {
      this.editing = null;
      if (this.chosen != null && this.chosen >= now.length) this.chosen = null;
      const d = this.drag;
      if (d && d.released && now[d.i] && Math.abs(now[d.i].depth - d.depth) < 0.5) this.letGo();
    },
  },
  beforeUnmount() {
    clearTimeout(this.held);
  },
  methods: {
    letGo() {
      clearTimeout(this.held);
      this.drag = null;
    },
    fmtM(v) { return Number.isFinite(v) ? fmtInt(Math.round(v)) + " m" : "–"; },
    fmtMs(v) { return Number.isFinite(v) ? fmtInt(Math.round(v)) + " ms" : "–"; },
    fmtV(v) { return Number.isFinite(v) ? fmtInt(Math.round(v)) + " m/s" : "–"; },
    colour(v) { return v == null ? "transparent" : colourOn(v, this.colors, this.vmin, this.vmax); },
    // the depth of a row: where its point is dragged to, else its own
    depthOf(i) {
      return this.drag && this.drag.i === i ? this.drag.depth : this.laid[i].depth;
    },
    rowY(i) {
      return this.drag && this.drag.i === i ? this.drag.y : this.laid[i].y;
    },
    // the height of a depth on the shared scale, and back
    yOf(depth) { return this.scale.top + (depth - this.scale.z0) * this.scale.slope; },
    depthAtY(y) { return this.scale.z0 + (y - this.scale.top) / this.scale.slope; },
    // the time of the law at a depth: between its points, the end
    // intervals carried on beyond them
    twtAt(depth) {
      const r = this.rows;
      if (r.length < 2) return r.length ? r[0].twt + depth - r[0].depth : depth;
      let i = r.findIndex((p) => p.depth >= depth);
      if (i < 0) i = r.length - 1;
      if (i === 0) i = 1;
      const a = r[i - 1];
      const b = r[i];
      return a.twt + (depth - a.depth) * (b.twt - a.twt) / Math.max(b.depth - a.depth, 1e-9);
    },
    // a press on a point: it follows the mouse in depth, between its
    // neighbours, its time kept, and is set where it is released
    press(i, e) {
      if (e.button !== 0) return;
      clearTimeout(this.held);
      this.$emit("active");
      this.chosen = i;
      const lo = i > 0 ? this.rows[i - 1].depth + LEAST_M : -Infinity;
      const hi = i < this.rows.length - 1 ? this.rows[i + 1].depth - LEAST_M : Infinity;
      const at = (ev) => {
        const top = this.$refs.track.getBoundingClientRect().top;
        const y = Math.max(0, Math.min(this.scale.height - 14, ev.clientY - top));
        const depth = Math.min(hi, Math.max(lo, Math.round(this.depthAtY(y))));
        this.drag = { i, depth, y: this.yOf(depth) };
      };
      const move = (ev) => at(ev);
      const up = (ev) => {
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", up);
        at(ev);
        const d = this.drag;
        if (!d || Math.abs(d.depth - this.rows[i].depth) < 0.5) {
          this.drag = null;
          return;
        }
        // it stays where it is released until the model answers
        this.drag = { ...d, released: true };
        this.held = setTimeout(() => { this.drag = null; }, HOLD_MS);
        this.$emit("edit", { op: "set", index: i, depth: d.depth });
      };
      at(e);
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", up);
    },
    menuAt(e, i) {
      this.$emit("active");
      if (i != null) {
        this.menuOn = { i };
      } else {
        const top = this.$refs.track.getBoundingClientRect().top;
        const y = Math.max(0, Math.min(this.scale.height - 14, e.clientY - top));
        const depth = Math.round(this.depthAtY(y));
        this.menuOn = { i: null, depth, twt: Math.round(this.twtAt(depth)) };
      }
      this.menu = { x: e.clientX, y: e.clientY };
    },
    stackMenu(e, stack) {
      this.$emit("active");
      this.menuOn = { stack };
      this.menu = { x: e.clientX, y: e.clientY };
    },
    menuPick(it) {
      const on = this.menuOn;
      this.menu = null;
      if (!on) return;
      if (on.stack) {
        this.chosen = Number(it.key.slice(4));
        return;
      }
      if (it.key === "del" && on.i > 0) {
        this.$emit("edit", { op: "del", index: on.i });
      } else if (it.key === "add" && !this.rows.some((r) => Math.abs(r.depth - on.depth) < 0.5)) {
        this.$emit("edit", { op: "add", depth: on.depth, twt: on.twt });
      }
    },
    isEditing(i, field) {
      return Boolean(this.editing && this.editing.i === i && this.editing.field === field);
    },
    // the box opens with the focus in it, and goes with the focus
    edit(i, field) {
      this.editing = { i, field };
      this.$nextTick(() => {
        const input = this.$refs.track.querySelector(".tls-edit");
        if (input) {
          input.focus();
          input.select();
        }
      });
    },
    commit(i, field, value) {
      this.editing = null;
      if (value == null || !Number.isFinite(value)) return;
      this.$emit("edit", { op: "set", index: i, [field]: value });
    },
  },
};
</script>

<style scoped>
.tls { flex: 0 0 auto; display: flex; flex-direction: column; gap: 2px; padding: 2px 4px 4px;
  border: 1px solid transparent; border-radius: 4px; font-size: 11px; }
.tls-on { border-color: var(--fp-accent, #1565c0); background: var(--fp-accent-soft, #e3f2fd); }
.tls-on :deep(.tlh-name) { border-color: var(--fp-accent, #1565c0); }
/* zoomed in depth, the heads stay in sight while the tracks scroll */
.tls :deep(.tlh) { position: sticky; top: 0; z-index: 3; background: var(--fp-bg, #fff); }
.tls-on :deep(.tlh) { background: var(--fp-accent-soft, #e3f2fd); }
.tls-track { position: relative; }
.tls-svg { position: absolute; left: 0; top: 0; overflow: visible; }
.tls-line { stroke: currentColor; stroke-width: 1.5; opacity: 0.7; }
.tls-arrow { fill: currentColor; opacity: 0.7; }
.tls-band { opacity: 0.9; }
.tls-tail { opacity: 0.35; }
.tls-dot { fill: #1565c0; stroke: #fff; stroke-width: 1.5; cursor: ns-resize; }
.tls-dot:hover { stroke: #1565c0; fill: #fff; }
.tls-dot-start { fill: #757575; }
.tls-dot-drag { fill: #fff; stroke: #1565c0; stroke-width: 2; }
.tls-dot-on { stroke: #8fc31f; stroke-width: 2; }
.tls-stack { cursor: pointer; }
.tls-stack circle { fill: #1565c0; stroke: #fff; stroke-width: 1.5; }
.tls-stack:hover circle { fill: #00436d; }
.tls-stack text { fill: #fff; font-size: 9px; font-weight: 700; pointer-events: none; }
.tls-hit { fill: transparent; cursor: context-menu; }
.tls-pt { position: absolute; left: 0; right: 0; height: 18px; pointer-events: none; }
.tls-dep { position: absolute; left: 0; top: 0; height: 18px; pointer-events: auto;
  display: flex; align-items: center; justify-content: flex-end; }
.tls-twt { position: absolute; top: 0; height: 18px; pointer-events: auto;
  display: flex; align-items: center; gap: 1px; white-space: nowrap; }
.tls-val { font-variant-numeric: tabular-nums; cursor: pointer; padding: 0 2px; border-radius: 2px; }
.tls-val:hover { background: rgba(0, 0, 0, 0.06); }
.tls-pt-on .tls-val { font-weight: 700; color: var(--fp-accent, #1565c0); }
.tls-del { visibility: hidden; opacity: 0.55; }
.tls-pt:hover .tls-del { visibility: visible; }
.tls-del:hover { opacity: 1; }
.tls-vel { position: absolute; font-style: italic; opacity: 0.8; white-space: nowrap; }
.tls-vel:hover { opacity: 1; }
.tls-live { opacity: 1; font-weight: 600; color: var(--fp-accent, #1565c0); }
.tls-bad { color: #c62828; }
</style>
