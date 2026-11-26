<template>
  <div ref="host" class="wlc-host">
    <!-- the depth zoom and the depth the wells are laid out on, as the 3D
         view's Z and the time-depth model's: in the view's tab row -->
    <teleport v-if="head" :to="head">
      <fp-z-scale class="wlc-head-tool" :model-value="zoomShown" :typed-min="1" :typed-max="ZOOM_MAX" :digits="0"
                  title="Vertical exaggeration of the logs, a whole number: 1 shows the whole depth span"
                  @update:model-value="setZoom" />
      <fp-btn variant="bare" icon class="wlc-head-tool wlc-fit" title="Show the whole well"
              @click="setZoom(1)">
        <fp-icon icon="fespp-view-frame" chrome :size="16" />
      </fp-btn>
    </teleport>
    <!-- "From grid": a loaded grid property sampled along a wellbore's
         trajectory. The host does the sampling and sends the result back as
         a dashed curve; this only edits the requests. -->
    <div v-if="showSynth" class="wlc-synth">
      <span class="wlc-synth-title">From grid</span>
      <template v-if="synthWells.length && synthProps.length">
        <fp-select class="wlc-synth-sel" v-model="draft.well" :options="synthWellOptions" title="Wellbore of the panel" />
        <fp-select class="wlc-synth-sel" v-model="draft.prop" :options="synthPropOptions" title="Loaded grid property" />
        <label class="wlc-synth-step">step
          <fp-num v-model="draft.step" size="sm" :min="0.01" title="Sampling step along the hole, in depth units" />
        </label>
        <fp-btn tiny label="+ Sample" :disabled="!canSample"
                :title="canSample ? 'Sample this property along this well' : 'Pick a well, a property and a step above zero'"
                @click="addSynth" />
      </template>
      <span v-else class="fp-sum wlc-synth-hint">
        {{ synthWells.length ? 'Tick a grid property in the main tree first' : 'Add a wellbore to the panel first' }}
      </span>
      <fp-chip v-for="(s, i) in synth" :key="s.well + '|' + s.prop + '|' + s.step" variant="line" class="wlc-synth-chip"
               :title="propTitle(s.prop) + ' sampled along ' + wellTitle(s.well) + ' every ' + s.step + ' depth units, drawn dashed'">
        <span class="wlc-synth-dash"></span>
        {{ wellTitle(s.well) }} ▸ {{ propTitle(s.prop) }} @ {{ s.step }}
        <template #after>
          <fp-btn variant="bare" label="×" title="Remove this synthetic log" @click="removeSynth(i)" />
        </template>
      </fp-chip>
    </div>

    <!-- The D3 renderer owns this node and clears it on every draw
         (root.selectAll("*").remove()), so nothing else may live inside it. -->
    <div ref="container" class="well-log-correlation" :class="{ 'wlc-grabbing': grabbing }"
         @pointerdown="grab" @pointermove="hover" @pointerleave="unhover" @scroll="scrolled"></div>
    <!-- the readout under the pointer over a track: filled and moved by
         `readout`, outside Vue's rendering so a move redraws nothing -->
    <div ref="tip" class="wlc-tip" hidden></div>
    <!-- the scrollbars: in depth against the last track, sideways along the
         bottom (a browser's own may show only while it scrolls) -->
    <fp-v-scroll v-if="bar" :style="{ left: bar.left + 'px', top: bar.top + 'px', height: bar.length + 'px' }"
                 :top="sTop" :total="bar.total" :view="bar.view" :length="bar.length"
                 title="Scroll the logs in depth" @scroll="scrollTo" />
    <fp-v-scroll v-if="hbar" horizontal
                 :style="{ left: hbar.left + 'px', top: hbar.top + 'px', width: hbar.length + 'px' }"
                 :top="sLeft" :total="hbar.total" :view="hbar.view" :length="hbar.length"
                 title="Scroll the wells sideways" @scroll="scrollAcross" />
  </div>
</template>

<script>
import * as d3 from "d3";
// Side-effect import: registers window.WellLogCorrelation = { render, hover, mockData }
import "../../src/correlation.js";
import { fmt, fmtFixed } from "../../../_shared/numfmt.js";
import FpBtn from "../../../_shared/components/FpBtn.vue";
import FpChip from "../../../_shared/components/FpChip.vue";
import FpNum from "../../../_shared/components/FpNum.vue";
import FpSelect from "../../../_shared/components/FpSelect.vue";
import FpIcon from "../../../_shared/components/FpIcon.vue";
import FpVScroll from "../../../_shared/components/FpVScroll.vue";
import FpZScale from "../../../_shared/components/FpZScale.vue";
import { grabPan } from "../../../_shared/grabPan.js";

const { ZOOM_MAX } = window.WellLogCorrelation;


// how often at most the cursor's sample is told to the host
const CURSOR_MS = 150;

export default {
  name: "WellLogCorrelation",
  components: { FpBtn, FpChip, FpIcon, FpNum, FpSelect, FpVScroll, FpZScale },
  props: {
    data: {
      type: Object,
      default: () => ({ wells: [], markers: [], flattenOn: null }),
    },
    // Vertical exaggeration, a whole number as a 3D view's Z: 1 shows the
    // whole depth span. Set from the Z of the tab row; the wheel and the
    // right-drag report back through `zoom-change` so it follows.
    depthScale: {
      type: Number,
      default: 1,
    },
    // The depth every well is laid out on, "TVD" or "MD"; the tab row's
    // choice comes back through `align-change`.
    align: {
      type: String,
      default: "TVD",
    },
    // The markers the reader dimmed (a click on a name), by name; a click
    // sends the new list through `markers-off-change`.
    markersOff: {
      type: Array,
      default: () => [],
    },
    // The samples highlighted elsewhere (rows of the Values view), by
    // measured depth: {well: {curve: [md]}} — dots on the curves.
    lit: {
      type: Object,
      default: () => ({}),
    },
    // The active node of the view's tree, its graph brought to the middle of
    // the view: {well, curve ("" for the whole well), n (counts the asks)};
    // with `md`, that measured depth brought there (a sample held in the
    // Values view) instead of the middle of the curve.
    focusNode: {
      type: Object,
      default: null,
    },
    // A sample pointed at in the Values view (its row under the pointer):
    // {well, md, curves: [names]} — crossed in blue on those curves, as this
    // view's own cursor does, and kept in sight; null none.
    pointedAt: {
      type: Object,
      default: null,
    },
    // Show the "from grid" editor above the tracks.
    showSynth: {
      type: Boolean,
      default: false,
    },
    // The synthetic-log requests in force, [{well, prop, step}], and what
    // the editor may offer: {wells: [{title, value}], props: [{title, value,
    // unit, kind}]}. Both are the host's; `synth-change` sends edits back.
    synth: {
      type: Array,
      default: () => [],
    },
    synthChoices: {
      type: Object,
      default: () => ({ wells: [], props: [] }),
    },
  },
  emits: ["zoom-change", "synth-change", "flatten-change", "align-change", "markers-off-change", "cursor-change",
          "pick-change"],
  data() {
    return {
      draft: { well: "", prop: "", step: 1 },
      head: null, bar: null, hbar: null, sTop: 0, sLeft: 0, grabbing: false,
      // a focus asked for before its graph was drawn
      focusDue: false,
    };
  },
  computed: {
    ZOOM_MAX() {
      return ZOOM_MAX;
    },
    zoomShown() {
      return this.wholeZoom(this.depthScale > 0 ? this.depthScale : 1);
    },
    // every well laid out on its TVD (the manager, 12/11: no MD layout, the
    // MD and TVD columns never swap; the tracks start at the MD datum)
    alignMode() {
      return "TVD";
    },
    synthWells() {
      return (this.synthChoices && this.synthChoices.wells) || [];
    },
    synthProps() {
      return (this.synthChoices && this.synthChoices.props) || [];
    },
    synthWellOptions() {
      return this.synthWells.map((w) => ({ value: w.value, label: w.title, title: "Sample along " + w.title }));
    },
    synthPropOptions() {
      return this.synthProps.map((p) => ({
        value: p.value, label: p.title + (p.unit ? " [" + p.unit + "]" : ""), title: "Sample " + p.title,
      }));
    },
    canSample() {
      return !!this.draft.well && !!this.draft.prop && Number(this.draft.step) > 0;
    },
  },
  watch: {
    focusNode() {
      this.focusDue = !this.centreOn();
    },
    pointedAt() {
      this.pointTo(true);
    },
    data: {
      deep: true,
      handler() {
        this.draw();
      },
    },
    depthScale() {
      this.draw();
    },
    align() {
      this.draw();
    },
    lit() {
      this.draw();
    },
    // the echo of a click the drawing already shows redraws nothing
    markersOff(v) {
      if (JSON.stringify(v || []) !== this.offSent) this.draw();
    },
    // keep the draft pointing at something that exists
    synthChoices: {
      immediate: true,
      deep: true,
      handler() {
        const wells = this.synthWells, props = this.synthProps;
        if (!wells.some((w) => w.value === this.draft.well)) {
          this.draft.well = wells.length ? wells[0].value : "";
        }
        if (!props.some((p) => p.value === this.draft.prop)) {
          this.draft.prop = props.length ? props[0].value : "";
        }
      },
    },
  },
  mounted() {
    const view = this.$el.closest(".wlp");
    this.head = view ? view.querySelector(".wlp-chrome") : null;
    // the tracks take the room they are given: a card docked beside them,
    // the "from grid" row, a resized view
    if (typeof ResizeObserver !== "undefined") {
      this.observer = new ResizeObserver(() => this.resizedSoon());
      this.observer.observe(this.$refs.container);
    }
    this.draw();
  },
  beforeUnmount() {
    if (this.observer) this.observer.disconnect();
    cancelAnimationFrame(this.placing);
    cancelAnimationFrame(this.reading);
    clearTimeout(this.cursorTimer);
    cancelAnimationFrame(this.sizing);
  },
  methods: {
    wholeZoom(v) {
      return Math.max(1, Math.min(ZOOM_MAX, Math.round(v)));
    },
    setZoom(v) {
      this.$emit("zoom-change", this.wholeZoom(v));
    },
    wellTitle(path) {
      const w = this.synthWells.find((x) => x.value === path);
      return w ? w.title : path;
    },
    propTitle(path) {
      const p = this.synthProps.find((x) => x.value === path);
      return p ? p.title : path;
    },
    addSynth() {
      const step = Number(this.draft.step);
      if (!this.draft.well || !this.draft.prop || !(step > 0)) return;
      const req = { well: this.draft.well, prop: this.draft.prop, step };
      const dup = (this.synth || []).some(
        (s) => s.well === req.well && s.prop === req.prop && s.step === req.step);
      if (dup) return;
      this.$emit("synth-change", [...(this.synth || []), req]);
    },
    removeSynth(i) {
      const next = [...(this.synth || [])];
      next.splice(i, 1);
      this.$emit("synth-change", next);
    },
    draw() {
      const el = this.$refs.container;
      if (!el || !window.WellLogCorrelation) {
        return;
      }
      window.WellLogCorrelation.render(el, this.data || {}, {
        d3,
        zoom: this.depthScale,
        align: this.alignMode,
        markersOff: this.markersOff,
        lit: this.lit,
        onZoom: (z) => this.$emit("zoom-change", z),
        // the click-to-flatten is the renderer's; the host keeps the datum
        // so a rebuilt payload (a tick, a cutoff) comes back still flattened
        onFlatten: (m) => this.$emit("flatten-change", m),
        // a click on a name dims it at once; the host keeps the list
        onMarkersOff: (names) => {
          this.offSent = JSON.stringify(names);
          this.$emit("markers-off-change", names);
        },
        // a wheel zoom redraws under a still pointer: its readout follows
        onDrawn: () => {
          this.placeBar();
          this.readSoon();
          // a log made active before it was drawn: brought once it is
          if (this.focusDue) this.focusDue = !this.centreOn();
          // a drawing again takes the crosses away: the Values view's pointer put back
          if (this.pointedAt) this.pointTo(false);
        },
      });
    },
    // a new size: drawn again, once per frame at most (a sash dragged)
    resizedSoon() {
      cancelAnimationFrame(this.sizing);
      this.sizing = requestAnimationFrame(() => {
        const el = this.$refs.container;
        if (!el || !el.clientWidth || !el.clientHeight) return;
        const size = el.clientWidth + "x" + el.clientHeight;
        if (size === this.drawnSize) {
          this.placeBar();
          return;
        }
        this.drawnSize = size;
        this.draw();
      });
    },
    // the depth bar beside the last track, over the plot below the sticky
    // header; the sideways one along the bottom, when the wells are wider
    // than the view
    placeBar() {
      const el = this.$refs.container;
      const st = el && el.__wlc;
      this.sTop = el ? el.scrollTop : 0;
      this.sLeft = el ? el.scrollLeft : 0;
      if (!st || !el.clientWidth) {
        this.bar = null;
        this.hbar = null;
        return;
      }
      const across = el.scrollWidth - el.clientWidth > 1;
      this.hbar = across ? {
        left: el.offsetLeft + 2, top: el.offsetTop + el.clientHeight - 12,
        length: el.clientWidth - 4, total: el.scrollWidth, view: el.clientWidth,
      } : null;
      if (el.scrollHeight - el.clientHeight <= 1) {
        this.bar = null;
        return;
      }
      const head = st.lastHeadTotal || 0;
      const right = Math.min((st.lastPlotR || 0) - el.scrollLeft + 3, el.clientWidth - 12);
      this.bar = {
        left: el.offsetLeft + right, top: el.offsetTop + head,
        length: el.clientHeight - head - (across ? 14 : 0),
        total: el.scrollHeight, view: el.clientHeight,
      };
    },
    // the next frame: not a change of position inside the scroll event
    // (Firefox reads that as a scroll-linked effect), nor inside the
    // observer's own delivery
    placeBarSoon() {
      cancelAnimationFrame(this.placing);
      this.placing = requestAnimationFrame(() => this.placeBar());
    },
    scrolled() {
      this.placeBarSoon();
      this.readSoon();
    },
    // The pointer over the logs: the readout and the depth marks follow it,
    // a frame at a time. Kept off Vue's reactivity, as the scroll bar's frame.
    hover(e) {
      this.pointer = { x: e.clientX, y: e.clientY, pressed: e.buttons !== 0 };
      this.readSoon();
    },
    unhover() {
      this.pointer = null;
      this.readSoon();
    },
    readSoon() {
      if (this.reading) return;
      this.reading = requestAnimationFrame(() => {
        this.reading = 0;
        this.readout();
      });
    },
    // nothing while a button is down (a drag, a band zoom) or a menu is open
    readout() {
      const el = this.$refs.container;
      const tip = this.$refs.tip;
      const api = window.WellLogCorrelation;
      if (!el || !tip || !api) return;
      const p = this.pointer;
      const quiet = !p || p.pressed || this.grabbing
        || document.querySelector(".fp-menu-root, .v-menu.v-overlay--active");
      const hit = quiet ? api.hover(el, null) : api.hover(el, p.x, p.y);
      if (!hit) {
        tip.hidden = true;
        if (!quiet || !p) this.tellCursor(null);
        // the mouse elsewhere: the Values view's pointer stays crossed
        if (!p && this.pointedAt) api.pointAt(el, this.pointedAt);
        return;
      }
      this.tellCursor(hit);
      this.paintTip(tip, hit);
      tip.hidden = false;
      // beside the pointer, on the side the host has room on
      const host = this.$refs.host.getBoundingClientRect();
      const w = tip.offsetWidth;
      const h = tip.offsetHeight;
      let left = p.x - host.left + 14;
      let top = p.y - host.top + 14;
      if (left + w > host.width - 4) left = Math.max(4, p.x - host.left - 14 - w);
      if (top + h > host.height - 4) top = Math.max(4, p.y - host.top - 10 - h);
      tip.style.transform = `translate(${left}px, ${top}px)`;
    },
    // the focus's graph in the middle of the view: its well's track (the
    // well's tracks for a well), at the middle of the depths its curve holds
    // values over; false while it is not drawn yet
    centreOn() {
      const f = this.focusNode;
      const el = this.$refs.container;
      const H = el && el.__wlc && el.__wlc.hover;
      if (!f || !f.well || !H) return false;
      const w = (H.wells || []).findIndex((x) => x.name === f.well);
      if (w < 0) return false;
      const G = H.geom[w];
      const tracks = H.wells[w].tracks || [];
      const k = f.curve ? tracks.findIndex((t) => (t.curves || []).some((c) => c.name === f.curve)) : -1;
      if (f.curve && k < 0) return false;
      const x = k >= 0 ? G.track(k) + H.L.trackW / 2 : G.plotL + G.width / 2;
      el.scrollLeft = Math.max(0, x - el.clientWidth / 2);
      const curve = k >= 0 ? tracks[k].curves.find((c) => c.name === f.curve) : null;
      // a sample held in the Values view: its depth in the middle
      const at = f.md != null ? window.WellLogCorrelation.depthOfMd(el, f.well, f.curve || "", f.md) : null;
      const depths = at != null ? [at] : ((curve && curve.samples) || [])
        .filter((s) => s[0] != null && !Number.isNaN(s[0])).map((s) => s[1]);
      if (depths.length && H.scales[w]) {
        const y = H.scales[w]((Math.min(...depths) + Math.max(...depths)) / 2);
        const head = H.headTotal || 0;
        el.scrollTop = Math.max(0, y - head - (el.clientHeight - head) / 2);
      }
      this.placeBar();
      return true;
    },
    // the Values view's pointer crossed on its curves; `follow`: brought into
    // sight when it stands outside the part of the drawing shown
    pointTo(follow) {
      const el = this.$refs.container;
      if (!el || !window.WellLogCorrelation) return;
      const p = window.WellLogCorrelation.pointAt(el, this.pointedAt);
      const H = el.__wlc && el.__wlc.hover;
      if (!follow || !p || !H) return;
      const head = H.headTotal || 0;
      const top = el.scrollTop + head;
      const bottom = el.scrollTop + el.clientHeight;
      if (p.y < top + 8 || p.y > bottom - 8) {
        el.scrollTop = Math.max(0, p.y - head - (el.clientHeight - head) / 2);
      }
      if (p.x < el.scrollLeft || p.x > el.scrollLeft + el.clientWidth) {
        el.scrollLeft = Math.max(0, p.x - el.clientWidth / 2);
      }
      this.placeBar();
    },
    // where a hit stands, as the host reads it: {} off the tracks
    hitAt(hit) {
      return hit ? { well: hit.well, depths: (hit.depths || []).map((d) => ({ ref: d.ref, value: d.value })),
                     curves: (hit.curves || []).map((c) => c.name) } : {};
    },
    // the sample the cursor stands on, told to the host (the Values view
    // marks its row), none off the tracks: once it changes, at most every CURSOR_MS
    tellCursor(hit) {
      const at = this.hitAt(hit);
      const key = JSON.stringify(at);
      if (key === this.cursorKey) return;
      this.cursorKey = key;
      this.cursorNext = at;
      if (this.cursorTimer) return;
      this.cursorTimer = setTimeout(() => {
        this.cursorTimer = 0;
        this.$emit("cursor-change", this.cursorNext);
      }, CURSOR_MS);
    },
    // the well, the pointer's depth on the axis it is laid out on then on
    // the other, then every curve of the track named as its header names
    // it, with its value there
    paintTip(tip, hit) {
      const cell = (cls, text) => {
        const d = document.createElement("div");
        d.className = cls;
        d.textContent = text;
        return d;
      };
      const rows = [cell("wlc-tip-head", hit.well)];
      for (const d of hit.depths) {
        rows.push(cell("wlc-tip-lab", d.ref),
                  cell("wlc-tip-num", fmtFixed(d.value, 1) + (d.unit && d.value != null ? " " + d.unit : "")));
      }
      for (const c of hit.curves) {
        const name = cell("wlc-tip-lab", c.name + (c.unit ? " (" + c.unit + ")" : ""));
        const swatch = document.createElement("span");
        swatch.className = "wlc-tip-sw" + (c.synthetic ? " wlc-tip-sw-dash" : "");
        swatch.style.borderColor = c.color;
        name.prepend(swatch);
        rows.push(name, c.value == null
          ? cell("wlc-tip-num wlc-tip-none", "no value")
          : cell("wlc-tip-num", fmt(c.value)));
      }
      tip.replaceChildren(...rows);
    },
    scrollTo(top) {
      const el = this.$refs.container;
      el.scrollTop = top;
      this.sTop = el.scrollTop;
    },
    scrollAcross(left) {
      const el = this.$refs.container;
      el.scrollLeft = left;
      this.sLeft = el.scrollLeft;
    },
    // the left button moves the logs, in depth and sideways; a press that
    // does not move is still a click (a marker name dims on it)
    grab(e) {
      this.unhover();
      if (e.button !== 0 || e.target.closest("input, textarea, select, button")) return;
      const el = this.$refs.container;
      // a press released where it began is a click on the sample there (a
      // marker's name keeps its own click): told to the host, {} off the tracks
      const x0 = e.clientX;
      const y0 = e.clientY;
      const named = !!e.target.closest("text");
      window.addEventListener("pointerup", (u) => {
        const api = window.WellLogCorrelation;
        if (named || !api || Math.abs(u.clientX - x0) > 3 || Math.abs(u.clientY - y0) > 3) return;
        this.$emit("pick-change", this.hitAt(api.hover(el, u.clientX, u.clientY)));
      }, { once: true, capture: true });
      grabPan(e, { y: el, x: el,
                   onMove: () => this.placeBar(),
                   onGrab: (on) => { this.grabbing = on; } });
    },
  },
};
</script>

<style>
@import "../../../_shared/panel.css";
</style>

<style scoped>
.wlc-host {
  position: relative;
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  min-height: 0;
}
.well-log-correlation {
  flex: 1 1 auto;
  min-height: 0;
  cursor: grab;
  /* the scrollbars are drawn beside the tracks (FpVScroll) */
  scrollbar-width: none;
}
.well-log-correlation::-webkit-scrollbar { display: none; }
.wlc-grabbing, .wlc-grabbing * { cursor: grabbing !important; user-select: none; }
/* the pointer's readout: the menus' white box, its first line their title's */
.wlc-tip {
  position: absolute;
  left: 0;
  top: 0;
  z-index: 10;
  display: grid;
  grid-template-columns: auto auto;
  column-gap: 12px;
  row-gap: 1px;
  padding: 3px 8px 4px;
  background: var(--fp-bg);
  border: 1px solid var(--fp-btn-line);
  border-radius: 4px;
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.2);
  color: var(--fp-ink);
  font-family: var(--fp-font);
  font-size: var(--fp-size-small);
  font-variant-numeric: tabular-nums;
  line-height: 1.35;
  white-space: nowrap;
  pointer-events: none;
}
.wlc-tip[hidden] { display: none; }
.wlc-tip :deep(.wlc-tip-head) {
  grid-column: 1 / -1;
  margin-bottom: 2px;
  padding-bottom: 2px;
  border-bottom: 1px solid var(--fp-line-soft);
  color: var(--fp-accent);
  font-weight: 600;
}
.wlc-tip :deep(.wlc-tip-lab) { color: var(--fp-ink-soft); }
.wlc-tip :deep(.wlc-tip-num) { text-align: right; }
.wlc-tip :deep(.wlc-tip-none) { color: var(--fp-ink-faint); }
.wlc-tip :deep(.wlc-tip-sw) {
  display: inline-block;
  width: 12px;
  height: 0;
  margin-right: 5px;
  border-top: 2px solid;
  vertical-align: middle;
}
.wlc-tip :deep(.wlc-tip-sw-dash) { border-top-style: dashed; }
.wlc-head-tool { pointer-events: auto; }
.wlc-fit:hover:not(:disabled) { background: rgba(255, 255, 255, 0.16); }
/* the TVD | MD strip on the dark tab row, its lit half the Z slider's blue */
.wlc-align { display: inline-flex; margin-left: 4px; }
.wlc-align :deep(.fp-segbtn) {
  height: 22px;
  padding: 0 7px;
  font-size: 11px;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.85);
  background: rgba(255, 255, 255, 0.1);
  border-color: rgba(255, 255, 255, 0.45);
}
.wlc-align :deep(.fp-segbtn:not(.fp-on):hover) { background: rgba(255, 255, 255, 0.22); }
.wlc-align :deep(.fp-segbtn.fp-on) {
  color: #00436d;
  background: #b9ddf6;
  border-color: #b9ddf6;
}
.wlc-synth {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  padding: 4px 10px;
  border-bottom: 1px solid #e2e2e2;
  background: var(--fp-bar-bg);
  font-size: 11px;
}
.wlc-synth-title {
  font-weight: 600;
  color: var(--fp-accent);
}
.wlc-synth-sel {
  max-width: 220px;
  font-size: inherit;
}
.wlc-synth-step {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  color: #555;
}
.wlc-synth-chip {
  gap: 4px;
}
.wlc-synth-dash {
  display: inline-block;
  width: 16px;
  height: 0;
  border-top: 2px dashed #1565c0;
}
</style>
