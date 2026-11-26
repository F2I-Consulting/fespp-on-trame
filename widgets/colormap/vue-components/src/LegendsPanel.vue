<template>
  <div v-if="shown" class="flg" :class="{ 'flg-folded': folded }">
    <fp-btn variant="bare" class="flg-fold" :title="headTitle" :aria-expanded="folded ? 'false' : 'true'"
            @click="folded = !folded">
      <span class="flg-caret">{{ folded ? "▸" : "▾" }}</span>Legends ({{ tables.length }})
    </fp-btn>

    <div v-if="!folded" class="flg-list">
      <template v-for="s in sections" :key="s.family">
        <div class="flg-section">{{ s.label }}</div>
        <div v-for="t in s.rows" :key="t.key" class="flg-row"
             :class="{ 'flg-held': t.bar, 'flg-held-off': !t.bar && t.bar_off }">
          <!-- the whole row is ONE button, laid over the words rather than
               around them: the words are data names, not a label, and a
               name such as "active_cell" is no Title-case slip -->
          <fp-btn variant="bare" class="flg-pick" :title="pickTitle(t)" @click="$emit('pick', t.key)" />
          <span class="flg-swatch" :style="{ background: swatch(t) }"></span>
          <span class="flg-name">{{ t.title }}</span>
          <span v-if="ownersText(t)" class="flg-owners">{{ ownersText(t) }}</span>
          <span class="flg-range">{{ rangeText(t) }}</span>
          <fp-chip v-if="t.log" sm class="flg-mark" text="log" title="The values are mapped on a log scale" />
        </div>
      </template>
    </div>
  </div>
</template>

<script>
/*
 * The LEGENDS of one 3D view, drawn ON the render: every coloured table of
 * the view, one row each, grouped by what they paint. A view shows ONE
 * colour bar in 3D (ParaView's, bottom right), that of the table the
 * Colormap card edits; picking a row here makes that table the edited one,
 * hence the one whose bar is shown. Knows nothing about ParaView:
 *   props in  — `legends` {tables: [{key, title, lo, hi, stops, codes, log,
 *               bar, bar_off, family, owners}]}, sorted (family, then title)
 *               and formatted by the host (`lo` / `hi` are shown as they
 *               come); `stops` = 16 colours sampled left to right for a
 *               continuous table, `codes` = [{code, label, color}] for a
 *               table painted by code, `family` = grid | well | surface |
 *               other, `owners` = the names of the objects it paints,
 *   events out — pick(key).
 * `bar` marks the table holding the bar; `bar_off` the one that would hold
 * it but whose bar the reader switched off in the Colormap card.
 *
 * WHY AN OVERLAY AND NOT A CARD. A legend is read WITH the picture, so it
 * sits on it: top right, no ground, never lower than half the view so it
 * cannot reach the colour bar ParaView draws at the bottom right. The host
 * mounts it straight in the render container (position:relative), and the
 * root positions itself. It lets the pointer through everywhere but on its
 * controls, so the view stays draggable around and under it.
 */
import FpBtn from "../../../_shared/components/FpBtn.vue";
import FpChip from "../../../_shared/components/FpChip.vue";

const FAMILIES = [
  ["grid", "Grids"],
  ["well", "Wells"],
  ["surface", "Surfaces"],
  ["seismic", "Seismic"],
  ["other", "Other"],
];
const KNOWN = new Set(FAMILIES.map((f) => f[0]));

export default {
  name: "LegendsPanel",
  components: { FpBtn, FpChip },
  props: {
    viewId: { type: String, default: "" },
    legends: { type: Object, default: () => ({}) },
  },
  emits: ["pick"],
  data() {
    return { folded: false };
  },
  computed: {
    tables() {
      const t = this.legends ? this.legends.tables : null;
      return Array.isArray(t) ? t : [];
    },
    // one table is already legended by its own bar; the exception is a
    // single table whose bar is switched off: then this list is the only
    // legend on screen
    shown() {
      const n = this.tables.length;
      return n > 1 || (n === 1 && !!this.tables[0].bar_off);
    },
    // the host's order is kept inside a section; an unknown family is Other
    sections() {
      const by = {};
      for (const t of this.tables) {
        const f = KNOWN.has(t.family) ? t.family : "other";
        (by[f] = by[f] || []).push(t);
      }
      return FAMILIES.filter((f) => by[f[0]]).map((f) => ({ family: f[0], label: f[1], rows: by[f[0]] }));
    },
    headTitle() {
      return this.folded
        ? "Show the list of this view's color tables"
        : "Fold the list of this view's color tables";
    },
  },
  methods: {
    // equal spacing: the host already sampled the stops in the table's own
    // scale; a coded table is hard-edged stripes, one per code
    swatch(t) {
      const codes = t.codes || [];
      if (codes.length) {
        const w = 100 / codes.length;
        return "linear-gradient(to right, " + codes.map((c, i) =>
          (c.color || "transparent") + " " + (i * w).toFixed(3) + "% " + ((i + 1) * w).toFixed(3) + "%",
        ).join(", ") + ")";
      }
      const stops = t.stops || [];
      if (stops.length > 1) return "linear-gradient(to right, " + stops.join(", ") + ")";
      return stops[0] || "var(--fp-neutral-bg)";
    },
    ownersText(t) {
      return Array.isArray(t.owners) ? t.owners.filter(Boolean).join(", ") : "";
    },
    rangeText(t) {
      const n = (t.codes || []).length;
      if (n) return n === 1 ? "1 code" : n + " codes";
      const lo = t.lo == null ? "" : String(t.lo);
      const hi = t.hi == null ? "" : String(t.hi);
      return lo || hi ? lo + " – " + hi : "";
    },
    // the tooltip carries what the row ellipses — the full title and every
    // owner — the range, and what a press does; it starts with the title,
    // being also the button's accessible name
    pickTitle(t) {
      const owners = this.ownersText(t);
      const n = (t.codes || []).length;
      const range = this.rangeText(t);
      let s = t.title + ".";
      if (owners) s += " Paints " + owners + ".";
      if (n) s += " " + range + ".";
      else if (range) s += " Range " + range + (t.log ? ", on a log scale." : ".");
      if (t.bar) return s + " Holds this view's color bar, shown in 3D; the Colormap card edits it.";
      if (t.bar_off) return s + " The Colormap card edits it; its color bar is switched off there (Color bar).";
      return s + " Press to show its color bar in 3D and edit it in the Colormap card.";
    },
  },
};
</script>

<style>
@import "../../../_shared/panel.css";
</style>

<style scoped>
/* Text over the 3D render. tokens.css has no ink for it: every token is
   written for a white panel, and the render's ground is whatever the scene
   is. ParaView writes its own bar labels white, so the list does too, with
   a dark halo that keeps it legible on a pale scene — the title bar strip
   (title3dview) writes its white ink the same way. Declared once here. */
.flg {
  --flg-ink: #fff;
  --flg-ink-mute: rgba(255, 255, 255, 0.78);
  --flg-halo: 0 0 2px rgba(0, 0, 0, 0.95), 0 0 4px rgba(0, 0, 0, 0.75), 0 1px 1px rgba(0, 0, 0, 0.9);
  --flg-wash: rgba(0, 0, 0, 0.28);
  /* above the render image (no z-index), below the pick overlay (4) and
     every floating card (5 and up, raised on focus) */
  position: absolute; top: 6px; right: 8px; z-index: 3;
  max-height: calc(50% - 6px); max-width: min(360px, 45%);
  display: flex; flex-direction: column; align-items: flex-end; min-height: 0;
  box-sizing: border-box; background: transparent; pointer-events: none;
  font-family: var(--fp-font); font-size: var(--fp-size); color: var(--flg-ink); text-shadow: var(--flg-halo);
}
.flg-fold, .flg-list { pointer-events: auto; }
/* the bare button is the chip's faded ×: here it carries a heading, so it
   is drawn at full ink */
.flg-fold {
  flex: 0 0 auto; opacity: 1; border-radius: 3px; padding: 1px 4px;
  color: var(--flg-ink); font-weight: 600; text-shadow: var(--flg-halo);
}
.flg-fold:hover, .flg-fold:focus-visible { background: var(--flg-wash); }
.flg-fold:focus-visible { outline: 2px solid var(--flg-ink); outline-offset: -2px; }
.flg-caret { display: inline-block; width: 1em; }
/* a whole wellbore can hold dozens of tables: the list scrolls, the header
   stays */
.flg-list {
  flex: 0 1 auto; min-height: 0; width: 100%; overflow-y: auto; overflow-x: hidden;
  display: flex; flex-direction: column; gap: 1px; scrollbar-width: thin;
}
.flg-section {
  padding: 4px 4px 1px; color: var(--flg-ink-mute); font-size: var(--fp-size-tiny);
  font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase;
}
.flg-row { position: relative; display: flex; align-items: center; gap: 6px; min-width: 0; padding: 2px 4px; border-radius: 3px; }
.flg-row:hover { background: var(--flg-wash); }
/* the held row: a rule on its left, in the ink, since the accent's dark
   blue disappears on a dark scene */
.flg-held { box-shadow: inset 2px 0 0 var(--flg-ink); font-weight: 600; }
.flg-held-off { box-shadow: inset 2px 0 0 var(--flg-ink-mute); }
/* the bare button stretched over its row: every pixel of the row presses it,
   and its focus ring is the row's outline */
.flg-pick { position: absolute; inset: 0; width: 100%; height: 100%; margin: 0; padding: 0; border-radius: 3px; opacity: 1; }
.flg-pick:focus-visible { outline: 2px solid var(--flg-ink); outline-offset: -2px; }
.flg-held .flg-pick { cursor: default; }
.flg-swatch {
  flex: 0 0 40px; height: 12px; box-sizing: border-box; border-radius: 2px;
  border: 1px solid var(--flg-ink-mute); box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.45);
}
/* the owners give way first, then the name down to a few letters, then the
   range */
.flg-name { flex: 0 1 auto; min-width: 4em; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.flg-owners { flex: 1 100 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  color: var(--flg-ink-mute); font-size: var(--fp-size-small); font-weight: 400; }
.flg-range { flex: 0 1 auto; min-width: 0; margin-left: auto; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  color: var(--flg-ink-mute); font-size: var(--fp-size-small); font-weight: 400; font-variant-numeric: tabular-nums; }
/* a chip has its own ground: the halo would only blur its words */
.flg-mark { flex: 0 0 auto; text-shadow: none; }
</style>
