<template>
  <!-- The session's time-depth model, in a view of its own: its laws
       (TDLaws) side by side as in a well correlation, on ONE depth scale,
       and the velocity model they make, in two-way time. No model to start
       with: the TDLaws entered, Generate makes one of them, updated from
       then on as they change. One TDLaw: its law everywhere; several,
       placed, are its control points. -->
  <div class="tdl" :class="{ 'tdl-tab': tab }">
    <!-- the tracks' zoom, as the 3D view's Z and framing: in the view's tab row -->
    <teleport v-if="head" :to="head">
      <fp-z-scale class="tdl-head-tool" :model-value="zoom" :max="ZOOM_MAX" :typed-min="1" :typed-max="ZOOM_MAX"
                  title="Vertical exaggeration of the tracks" @update:model-value="setZoom" />
      <fp-btn variant="bare" icon class="tdl-reset tdl-head-tool" :disabled="zoom === 1" title="Fit the tracks' depths to the card"
              @click="resetZoom">
        <fp-icon icon="fespp-view-frame" chrome :size="16" />
      </fp-btn>
    </teleport>
    <div class="tdl-body">
      <!-- the velocity model: its zone, its time range, its cells -->
      <div class="tdl-row">
        <span class="tdl-lbl tdl-on-box">3D grid</span>
        <span class="tdl-on-box">
          <fp-select :key="law.model + ':' + law.refused" class="tdl-model" mandatory
                     :model-value="law.model" :options="law.models || []"
                     title="The active velocity model: one the session generated, any IJK grid of the data whose geometry is a lattice, or none — the inputs of a new one to generate"
                     @update:model-value="$emit('edit', { op: 'model_activate', value: $event })" />
        </span>
        <label v-for="(name, k) in CORNERS" :key="name" class="tdl-f">
          <span class="tdl-fl">{{ cornerWords[k] }}</span>
          <fp-num size="sm" :digits="0" nullable :model-value="extentAt(k)" :placeholder="usedAt(k)" :title="cornerTips[k]"
                  @update:model-value="corner(name, $event)" />
        </label>
        <span v-if="grownChip" class="tdl-on-box"><fp-chip variant="warn" sm :text="grownChip.text" :title="grownChip.title" /></span>
        <label v-for="(name, k) in TIMES" :key="name" class="tdl-f">
          <span class="tdl-fl">{{ k ? "T max (ms)" : "T min (ms)" }}</span>
          <fp-num size="sm" :digits="0" :model-value="trange[k]"
                  :title="k ? 'The latest two-way time the velocity model reaches, ms'
                            : 'The two-way time of the velocity model\'s top, ms'"
                  @update:model-value="$emit('edit', { op: 'cube_set', [name]: $event })" />
        </label>
        <label v-for="(name, k) in CELLS" :key="name" class="tdl-f">
          <span class="tdl-fl tdl-fl-mid">{{ ["I", "J", "K"][k] }}</span>
          <fp-num size="sm" integer stepper :min="1" :max="200" :model-value="cube[name] || 100" :class="{ 'tdl-k': k === 2 }"
                  :title="cellTips[k]" @update:model-value="$emit('edit', { op: 'cube_set', [name]: $event })" />
        </label>
        <span v-if="cellSize" class="tdl-on-box"><fp-chip variant="neutral" sm :text="cellSize" title="The size of one cell" /></span>
        <span v-if="cube.edited" class="tdl-on-box"><fp-chip variant="line" sm :text="cube.edited + (cube.edited > 1 ? ' cells' : ' cell') + ' by hand'"
                 title="Cells whose velocity was set in the Values card's Map: kept while the velocity model keeps its cells and layers" /></span>
      </div>

      <!-- the velocity: where it comes from; from a property, which one and
           what it is, in place of the TDLaws -->
      <div class="tdl-row">
        <span class="tdl-lbl tdl-on-box">Average velocity</span>
        <span class="tdl-on-box tdl-from">from</span>
        <span class="tdl-on-box">
          <fp-select :key="source + ':' + law.refused" class="tdl-verb" mandatory :model-value="source"
                     :options="sourceOptions" title="Where the velocity of the model comes from"
                     @update:model-value="$emit('edit', { op: 'source', value: $event })" />
        </span>
        <template v-if="fromData && law.velocity">
          <span class="tdl-on-box">
            <fp-select class="tdl-model" mandatory
                       :model-value="law.velocity.path" :options="law.velocity.properties || []"
                       title="The property of the grid read as the velocity"
                       @update:model-value="$emit('edit', { op: 'velocity_property', path: $event })" />
          </span>
          <span class="tdl-on-box tdl-from">of kind</span>
          <span class="tdl-on-box">
            <fp-select class="tdl-model" mandatory
                       :model-value="law.velocity.reading || 'interval'" :options="READINGS"
                       title="What the property is: an average velocity gives depth = velocity × time / 2, an interval velocity is integrated layer by layer, an RMS velocity is made interval velocities by Dix's formula first"
                       @update:model-value="$emit('edit', { op: 'velocity_kind', reading: $event })" />
          </span>
        </template>
      </div>
      <div v-if="law.note && !problems.includes(law.note)" class="tdl-data-note">{{ law.note }}</div>

      <!-- the TDLaws, side by side on one depth scale fitted to the card;
           a new one asked for its easting and northing at their right.
           Sideways the row scrolls here; in depth `rows` does, all the tracks
           together, its scrollbar on the active track -->
      <div v-show="!fromData" ref="strips" class="tdl-strips">
        <div ref="rows" class="tdl-rows" :class="{ 'tdl-grabbing': grabbing }"
             @wheel="wheel" @scroll="rowsScrolled" @pointerdown="grab">
          <law-strip v-for="s in strips" :key="s.key" :rows="s.rows" :scale="depthScale" :name="s.name"
                     :head-title="s.title" :active="s.active" :why="s.why" :colors="colors"
                     :vmin="scale[0]" :vmax="scale[1]" :x="s.x" :y="s.y" :axes="axes" :outside="s.outside"
                     :placeable="Boolean(cube.extent_used)"
                     @active="pick(s)" @remove="$emit('edit', { op: 'del_column', index: s.index })"
                     @column="$emit('edit', { ...$event, index: s.index })"
                     @edit="$emit('edit', { ...$event, column: s.index })" />
          <div class="tdl-add" :style="{ height: (depthScale.height + HEAD_H) + 'px' }">
            <law-head :name="newName" :name-placeholder="nextName" :x="draft[0]" :y="draft[1]" :axes="axes"
                      :suggestions="suggestions" :placeable="Boolean(cube.extent_used)"
                      :title="'A new TDLaw: its track comes once its ' + axisWords.join(' and ') + ' are entered'"
                      @rename="newName = $event" @place="setDraft" />
          </div>
          <!-- read from left to right: the TDLaws, a new one, then the
               model they make -->
          <div v-if="!law.generated" class="tdl-gen">
            <fp-btn label="Generate" variant="primary" :disabled="!law.can_generate" :title="generateTip"
                    @click="$emit('edit', { op: 'generate' })" />
          </div>
          <fp-empty v-if="!columns.length" class="tdl-start"
                    shows="The TDLaws the velocity model is made of, a track each."
                    :gesture="'Enter the first one in the box: its ' + axisWords.join(' and ').toLowerCase()
                      + ', or Place. Or read them from the wells with the list above. Then Generate.'"
                    why="None is entered yet." />
        </div>
        <fp-v-scroll v-if="bar" :style="{ left: bar.left + 'px', top: '0px', height: bar.height + 'px' }"
                     :top="rowsTop" :total="bar.total" :view="bar.height" :length="bar.height"
                     title="Scroll the tracks in depth, all together" @scroll="scrollRows" />
      </div>
      <fp-note v-for="p in problems" :key="p" severity="warning" :text="p" />
    </div>
  </div>
</template>

<script>
import { fmtInt } from "../../../_shared/numfmt.js";
import FpBtn from "../../../_shared/components/FpBtn.vue";
import FpChip from "../../../_shared/components/FpChip.vue";
import FpEmpty from "../../../_shared/components/FpEmpty.vue";
import FpIcon from "../../../_shared/components/FpIcon.vue";
import FpNote from "../../../_shared/components/FpNote.vue";
import FpNum from "../../../_shared/components/FpNum.vue";
import FpVScroll from "../../../_shared/components/FpVScroll.vue";
import FpZScale from "../../../_shared/components/FpZScale.vue";
import { grabPan } from "../../../_shared/grabPan.js";
import LawHead from "./LawHead.vue";
import FpSelect from "../../../_shared/components/FpSelect.vue";
import LawStrip from "./LawStrip.vue";
import { scaleOf } from "./viridis.js";

const CORNERS = ["x0", "x1", "y0", "y1"];
const TIMES = ["t0", "t1"];

// what each Pre-fill entry does, in its tooltip
const VERTICAL_ONLY = " — vertical wells only: a deviated one is left out";
// an entry's count: how many wells make a TDLaw, of how many that carry the data
const countOf = (n, out) => (out ? ` (${n} vertical of ${n + out})` : (n ? ` (${n})` : ""));
const PREFILL_WELLS = "One TDLaw per well that carries a time log (a channel in s or ms, a checkshot table):"
  + " its samples read without loading the well, the points on a depth step shared by all the wells";
const PREFILL_SONIC = "One TDLaw per well that carries a sonic log (DT in us/ft or us/m, Vp in m/s or ft/s;"
  + " a shear log is left out): its values integrated down from the top of the log, above it the current"
  + " model's time";
const PREFILL_MARKERS = "One TDLaw per well with markers: each marker read on THE surface in time of its"
  + " interpretation (by its uuid; an interpretation with several is left out) — its depth against the"
  + " surface's two-way time";
const allOut = (n, what) => `The ${n} wells with ${what} are all deviated: only a vertical well makes a TDLaw`;
const CELLS = ["nx", "ny", "nz"];
const READINGS = [{ value: "average", label: "Average velocity" }, { value: "interval", label: "Interval velocity" },
                  { value: "rms", label: "RMS velocity" }];
const SUGGESTED = 10;  // even values offered for a new TDLaw's easting and northing
const TOP = 10;        // the shallowest depth's height on the tracks, px
const MIN_SPAN = 80;   // the tracks' height from the shallowest to the deepest depth, at least, px
const TAIL = 30;       // the arrow on below the deepest depth, px
const HEAD_H = 56;     // a track's name and place above it, px
const BOTTOM = 14;     // the tracks' row's horizontal scrollbar, px
const ZOOM_STEP = 1.25;
const ZOOM_MAX = 50;
const BAR_W = 10;      // the scrollbar on the active track, px

export default {
  name: "TimeDepthLaw",
  components: { FpBtn, FpChip, FpEmpty, FpIcon, FpNote, FpNum, FpSelect, FpVScroll, FpZScale, LawHead, LawStrip },
  props: {
    // {columns: [{name, x, y, rows, problems, why, valid}], active, generated,
    //  can_generate, axes, cube: {extent, extent_from, extent_used,
    //  extent_grown, nx, ny, nz, trange, summary, edited}, prefill, note,
    //  models, model, problems, valid} (app/features/time_depth_law)
    law: { type: Object, default: () => ({}) },
    // the whole of its host (a card of the 3D view)
    tab: { type: Boolean, default: false },
    // the view's colours of the velocity: {lo, hi, stops, log} from the
    // table painting the Velocity model there (app/features/time_depth_pins);
    // empty, the tracks read Viridis on the velocity model's range
    colors: { type: Object, default: () => ({}) },
  },
  emits: ["edit"],
  data() {
    return { READINGS, draft: [null, null], newName: "", avail: 0, zoom: 1, head: null, bar: null, rowsTop: 0,
             grabbing: false,
             CORNERS, TIMES, CELLS, HEAD_H, ZOOM_MAX };
  },
  watch: {
    // a new TDLaw being typed belongs to the model it was typed on
    "law.model"() {
      this.draft = [null, null];
      this.newName = "";
    },
    active: "placeBar",
    "columns.length": "placeBar",
    zoom: "placeBar",
    avail: "placeBar",
  },
  computed: {
    columns() { return (this.law && this.law.columns) || []; },
    active() { return (this.law && this.law.active) || 0; },
    cube() { return (this.law && this.law.cube) || {}; },
    problems() { return (this.law && this.law.problems) || []; },
    // the active model is a grid of the data read as it is: no TDLaw
    fromData() { return Boolean(this.law && this.law.data); },
    generateTip() {
      return this.law.can_generate
        ? "Generate the velocity model the 3D view previews: a lattice grid in the Seismic tree, the active model the conversions read, updated from then on as its TDLaws change"
        : "A velocity model needs a TDLaw that converts: enter one in the tracks, or read the wells'";
    },
    // where the velocity comes from: "property", a Pre-fill, "hand"
    source() { return (this.law && this.law.source) || "hand"; },
    sourceOptions() {
      const only = "A grid of the data takes its velocity from one of its properties";
      return [
        { value: "property", label: "3D property", disabled: !this.fromData,
          title: this.fromData ? "One property of the grid, as it is"
            : "No property exists on this grid: its TDLaws make its velocity" },
        ...this.prefillEntries.map((o) => (this.fromData ? { ...o, disabled: true, title: only } : o)),
        { value: "hand", label: "TDLaws by hand", disabled: this.fromData,
          title: this.fromData ? only : "TDLaws entered by hand in the tracks below" },
      ];
    },
    trange() { return this.cube.trange || [0, 5000]; },
    // the horizontal axes as the CRS names them, with their unit
    axes() { return (this.law && this.law.axes) || ["Easting", "Northing"]; },
    axisWords() { return this.axes.map((a) => String(a).split(" (")[0]); },
    axisUnits() { return this.axes.map((a) => (String(a).match(/\(([^)]*)\)/) || [null, "m"])[1]); },
    axisShort() {
      return this.axisWords.map((w, k) => `${w.charAt(0).toUpperCase()} (${this.axisUnits[k]})`);
    },
    cornerWords() {
      const [e, n] = this.axisShort.map((s) => s.split(" ")[0]);
      const [ue, un] = this.axisUnits;
      return [`${e} min (${ue})`, `${e} max (${ue})`, `${n} min (${un})`, `${n} max (${un})`];
    },
    cornerTips() {
      const [e, n] = this.axisWords;
      const edge = (side, most, word) => `${side} edge (${most} ${word.toLowerCase()}): the extent of the files, in grey`
        + " — typed, the zone stays; emptied, back to the files'";
      return [edge("West", "least", e), edge("East", "most", e), edge("South", "least", n), edge("North", "most", n)];
    },
    cellTips() {
      const [e, n] = this.axisWords;
      return [`Cells along the ${e.toLowerCase()}`, `Cells along the ${n.toLowerCase()}`,
              "Layers in K: the velocity model cut in that many even layers in two-way time, from T min to T max"];
    },
    nextName() { return `TDLaw${this.columns.length + 1}`; },
    // the tracks: the TDLaws
    strips() {
      const grown = new Set(this.cube.extent_grown || []);
      return this.columns.map((c, i) => ({
        key: "c" + i, index: i, active: i === this.active, why: c.why || "",
        name: c.name, rows: c.rows || [], title: this.headTitle(c),
        x: c.x == null ? null : c.x, y: c.y == null ? null : c.y, outside: grown.has(i),
      }));
    },
    // ONE depth scale for every track, fitted to the card: a depth stands at
    // one height in each, whatever else the tracks hold; zoomed, in depth
    // alone, the tracks' row scrolls
    depthScale() {
      const depths = this.strips.flatMap((s) => s.rows.map((r) => r.depth));
      const z0 = depths.length ? Math.min(...depths) : 0;
      const z1 = depths.length ? Math.max(...depths) : 0;
      const room = this.avail ? this.avail - HEAD_H - TOP - TAIL - BOTTOM : 0;
      const span = Math.max(room, MIN_SPAN) * this.zoom;
      return { top: TOP, z0, slope: z1 > z0 ? span / (z1 - z0) : 0.05, height: TOP + span + TAIL };
    },
    // the scale the fallback tints read on: the velocity model's, else the laws' velocities
    scale() {
      const s = this.cube.summary;
      if (s && Number.isFinite(s.vmin) && s.vmax > s.vmin) return scaleOf([s.vmin, s.vmax]);
      return scaleOf(this.strips.flatMap((st) => st.rows.map((r) => r.velocity)).filter((v) => v != null));
    },
    // 10 even values across the velocity model's I and J, offered for a new TDLaw
    suggestions() {
      const e = this.cube.extent_used;
      if (!e) return [[], []];
      const along = (a, b) => Array.from({ length: SUGGESTED }, (_v, k) => Math.round(a + (k + 0.5) * (b - a) / SUGGESTED));
      return [along(e[0], e[1]), along(e[2], e[3])];
    },
    prefillEntries() {
      const ready = Boolean(this.law.prefill && this.law.prefill.ready);
      const wells = Number((this.law.prefill && this.law.prefill.wells) || 0);
      const sonic = Number((this.law.prefill && this.law.prefill.sonic) || 0);
      const markers = Number((this.law.prefill && this.law.prefill.markers) || 0);
      const wellsOut = Number((this.law.prefill && this.law.prefill.wells_out) || 0);
      const sonicOut = Number((this.law.prefill && this.law.prefill.sonic_out) || 0);
      const markersOut = Number((this.law.prefill && this.law.prefill.markers_out) || 0);
      const inTime = Number((this.law.prefill && this.law.prefill.time_grids) || 0);
      const why = "Nothing is read yet: import a file first";
      let markersTip = PREFILL_MARKERS + VERTICAL_ONLY;
      if (!ready) markersTip = why;
      else if (!markers) markersTip = markersOut ? allOut(markersOut, "markers") : "No well of the data read carries markers";
      else if (!inTime) markersTip = "No 2D grid in time among the data read: the markers have no time horizon to be read on";
      return [
        { value: "wells", label: "All wells' time logs" + countOf(wells, wellsOut), disabled: !ready || !wells,
          title: !ready ? why : (wells ? PREFILL_WELLS + VERTICAL_ONLY
            : (wellsOut ? allOut(wellsOut, "a time log") : "No well of the files carries a time log (a channel in s or ms)")) },
        { value: "sonic", label: "All wells' sonic logs" + countOf(sonic, sonicOut), disabled: !ready || !sonic,
          title: !ready ? why : (sonic ? PREFILL_SONIC + VERTICAL_ONLY
            : (sonicOut ? allOut(sonicOut, "a sonic log") : "No well of the files carries a sonic log (DT or Vp)")) },
        { value: "markers", label: "All well markers" + (inTime ? countOf(markers, markersOut) : ""),
          disabled: !ready || !markers || !inTime,
          title: markersTip },
      ];
    },
    grownChip() {
      const n = (this.cube.extent_grown || []).length;
      const e = this.cube.extent_used;
      if (!n || !e) return null;
      const placed = `${n} TDLaw${n > 1 ? "s" : ""} placed outside it`;
      return { text: `+ ${n} outside the zone`,
               title: `${this.span(e)} — the velocity model grows past the zone to take in ${placed}; the zone itself stays` };
    },
    cellSize() {
      const e = this.cube.extent_used;
      if (!e || !this.cube.nx || !this.cube.ny) return "";
      return `≈ ${fmtInt(Math.round((e[1] - e[0]) / this.cube.nx))} × ${fmtInt(Math.round((e[3] - e[2]) / this.cube.ny))} m`;
    },
  },
  mounted() {
    const el = this.$refs.strips;
    if (el && typeof ResizeObserver !== "undefined") {
      // the next frame: not a change of size inside the observer's own delivery
      this.observer = new ResizeObserver(() => {
        cancelAnimationFrame(this.measuring);
        this.measuring = requestAnimationFrame(() => { this.avail = el.offsetHeight; });
      });
      this.observer.observe(el);
    }
    this.avail = el ? el.offsetHeight : 0;
    const view = this.$el.closest(".tdp");
    this.head = view ? view.querySelector(".tdp-chrome") : null;
  },
  beforeUnmount() {
    if (this.observer) this.observer.disconnect();
    cancelAnimationFrame(this.measuring);
    cancelAnimationFrame(this.scrolling);
  },
  methods: {
    fmtInt,
    headTitle(c) {
      const [e, n] = this.axisWords;
      const where = c.x == null || c.y == null ? "not placed"
        : `at ${e.toLowerCase()} ${fmtInt(Math.round(c.x))}, ${n.toLowerCase()} ${fmtInt(Math.round(c.y))}`;
      return `${c.name} — ${where}${c.why ? " · left out: " + c.why : ""}. Click to make it the active TDLaw;`
        + " right-click its band to add a point, drag a point to move it in depth (its time stays), click a value to edit it;"
        + " the wheel over the tracks zooms in depth";
    },
    pick(s) {
      if (s.index != null && s.index !== this.active) this.$emit("edit", { op: "active", index: s.index });
    },
    // an extent [x0, x1, y0, y1] in metres: "Easting 0 – 1000 · Northing 0 – 500"
    span(e) {
      const r = (v) => fmtInt(Math.round(v));
      const [x, y] = this.axisWords;
      return `${x} ${r(e[0])} – ${r(e[1])} · ${y} ${r(e[2])} – ${r(e[3])}`;
    },
    extentAt(k) {
      const e = this.cube.extent;
      return e && e[k] != null && !["columns", "data"].includes(this.cube.extent_from) ? e[k] : null;
    },
    // the extent in use, greyed in a field nothing was entered in
    usedAt(k) {
      const e = this.cube.extent_used;
      return e && e[k] != null ? String(Math.round(e[k])) : "";
    },
    // a corner typed sets the zone; emptied, the zone is the files' again
    corner(name, value) {
      if (value != null) this.$emit("edit", { op: "cube_set", [name]: value });
      else if (this.cube.extent_from !== "data") this.$emit("edit", { op: "cube_auto" });
    },
    // the wheel zooms in depth about the depth under the mouse; with Shift it
    // is the row's own, sideways
    wheel(e) {
      if (e.shiftKey) return;
      e.preventDefault();
      this.zoomAbout(this.zoom * (e.deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP), e.clientY);
    },
    // the Z of the title bar: about the depth in the middle of what shows
    setZoom(v) {
      const box = this.$refs.rows.getBoundingClientRect();
      this.zoomAbout(v, box.top + box.height / 2);
    },
    resetZoom() {
      this.zoom = 1;
      this.$nextTick(() => { this.$refs.rows.scrollTop = 0; });
    },
    // the depth at `clientY` stays where it is
    zoomAbout(next, clientY) {
      const track = this.$el.querySelector(".tls-track");
      const was = this.depthScale;
      const y = track ? clientY - track.getBoundingClientRect().top : 0;
      const depth = was.z0 + (y - was.top) / was.slope;
      this.zoom = Math.min(ZOOM_MAX, Math.max(1, next));
      this.$nextTick(() => {
        if (!track) return;
        const now = this.depthScale;
        const at = track.getBoundingClientRect().top + now.top + (depth - now.z0) * now.slope;
        this.$refs.rows.scrollTop += at - clientY;
      });
    },
    // the scrollbar stands in the room the tracks keep at their right,
    // in the active one, and spans the same height as the tracks it scrolls
    placeBar() {
      this.$nextTick(() => {
        const { strips, rows } = this.$refs;
        const on = strips && strips.querySelector(".tls-on");
        if (!on || rows.scrollHeight - rows.clientHeight <= 1) {
          this.bar = null;
          return;
        }
        const edge = on.getBoundingClientRect().right - strips.getBoundingClientRect().left + strips.scrollLeft;
        this.bar = { left: edge - BAR_W - 2, height: rows.clientHeight, total: rows.scrollHeight };
        this.rowsTop = rows.scrollTop;
      });
    },
    // the thumb moves at the next frame: moved inside the scroll event,
    // Firefox reads it as a scroll-linked effect. A drag (grab, the
    // scrollbar) moves it at once, from the gesture itself.
    rowsScrolled() {
      cancelAnimationFrame(this.scrolling);
      this.scrolling = requestAnimationFrame(() => { this.rowsTop = this.$refs.rows.scrollTop; });
    },
    // a press dragged on the tracks moves them, in depth as the scrollbar
    // does and sideways; a press that does not move is still a click
    grab(e) {
      if (e.button !== 0 || e.target.closest("input, textarea, select, button, .tlh")) return;
      const { rows, strips } = this.$refs;
      grabPan(e, { y: rows, x: strips,
                   onMove: () => { this.rowsTop = rows.scrollTop; },
                   onGrab: (on) => { this.grabbing = on; } });
    },
    // the scrollbar's gesture (FpVScroll), the thumb moved from it at once
    scrollRows(top) {
      const { rows } = this.$refs;
      rows.scrollTop = top;
      this.rowsTop = rows.scrollTop;
    },
    // the track comes once both are entered, or at "Place": the centre of
    // the zone, the nearest free place inside it
    setDraft(place) {
      if (place.at === "free") {
        this.$emit("edit", { op: "add_column", at: "centre", name: this.newName });
        this.draft = [null, null];
        this.newName = "";
        return;
      }
      const d = this.draft.slice();
      if (place.x !== undefined) d[0] = place.x;
      if (place.y !== undefined) d[1] = place.y;
      if (d[0] == null || d[1] == null) {
        this.draft = d;
        return;
      }
      this.$emit("edit", { op: "add_column", x: d[0], y: d[1], name: this.newName });
      this.draft = [null, null];
      this.newName = "";
    },
  },
};
</script>

<style scoped>
.tdl-head-tool { pointer-events: auto; }
.tdl { flex: 0 0 auto; font-size: 12px; }
/* the height of its card: the tracks fit what is left of it */
.tdl-tab { height: 100%; min-height: 0; display: flex; flex-direction: column; overflow: hidden; }
.tdl-body { padding: 4px 8px 4px; display: flex; flex-direction: column; gap: 6px; flex: 1 1 auto; min-height: 0; }
.tdl-row { display: flex; align-items: flex-end; gap: 6px; flex-wrap: wrap; min-height: 26px; }
.tdl-lbl { font-size: 10px; text-transform: uppercase; letter-spacing: 0.04em; opacity: 0.7; min-width: 52px; align-self: center; }
/* what stands in a row of labelled boxes stands on the boxes, not on their labels */
.tdl-on-box { align-self: flex-end; display: inline-flex; align-items: center; height: 23px; }
.tdl-f { display: inline-flex; flex-direction: column; gap: 1px; }
/* wide enough for seven digits of a projected northing */
.tdl-f .fp-num { width: 66px; box-sizing: border-box; }
.tdl-fl { font-size: 10px; opacity: 0.7; white-space: nowrap; }
/* over the box itself, between its − and its + */
.tdl-fl-mid { text-align: center; }
.tdl-k { width: 52px; }
.tdl-verb { min-width: 190px; }
.tdl-from { font-size: 11px; opacity: 0.7; }
/* what is left of the card, whatever the tracks hold: they are sized from it */
.tdl-data-note { font-size: 12px; opacity: 0.75; line-height: 1.4; }
.tdl-strips { flex: 1 1 0; min-height: 120px; position: relative; display: flex; overflow: auto hidden; }
.tdl-rows { flex: 0 0 auto; min-width: 100%; min-height: 0; display: flex; align-items: flex-start; gap: 4px;
  overflow: hidden auto; scrollbar-width: none; }
.tdl-rows::-webkit-scrollbar { display: none; }
.tdl-rows :deep(.tls-track) { cursor: grab; }
.tdl-grabbing, .tdl-grabbing :deep(*) { cursor: grabbing !important; user-select: none; }
/* the room of the scrollbar, kept: a track does not change size as it zooms */
.tdl-rows :deep(.tls) { padding-right: 16px; }
.tdl-reset:hover:not(:disabled) { background: rgba(255, 255, 255, 0.16); }
/* as a track's frame, so its head stands level with theirs */
.tdl-add { flex: 0 0 auto; width: 186px; box-sizing: border-box; padding: 2px 4px 4px;
  border: 1px dashed var(--fp-border, #c8c8c8); border-radius: 4px; opacity: 0.85; }
.tdl-add:hover { opacity: 1; border-color: var(--fp-accent, #1565c0); }
/* level with the tracks' heads, and staying there as they scroll in depth */
.tdl-gen { flex: 0 0 auto; align-self: flex-start; position: sticky; top: 0; z-index: 3; padding: 4px 4px 0 6px; }
/* beside the box it speaks of, in the room the tracks will take */
.tdl-start { flex: 0 1 380px; align-self: flex-start; margin: 6px 0 0 10px; }
.tdl-add :deep(.tlh) { position: sticky; top: 0; z-index: 3; background: var(--fp-bg, #fff); }
</style>
