<template>
  <!-- A tool card: the frame names it ("Volumetrics · <grid>"), so the first
       row is a sub-bar of controls, not a second title. -->
  <div class="fvo fp-panel">
    <div class="fp-subbar fvo-filled">
      <fp-select class="fvo-sel" label="grid" :model-value="params.grid || ''" :options="gridOptions"
                 placeholder="Grid" mandatory title="The grid whose cells are cubed"
                 @update:model-value="set('grid', $event || '')" />
      <fp-btn variant="primary" label="Compute" :disabled="!params.grid"
              :title="params.grid ? 'Read the cells and rebuild the table' : 'Pick a grid first'"
              @click="compute" />
      <div class="fp-right">
        <span class="fp-sum" v-if="data && data.cells">{{ fmtInt(data.active) }} / {{ fmtInt(data.cells) }} active cells</span>
        <fp-export :filename="csvName" :build="csvText" :disabled="!hasTable"
                   disabled-why="press Compute first, there is no table yet"
                   title="Copy the table as CSV — raw cubic meters under a dated, self-describing header; a download when the browser offers no clipboard (plain http)" />
      </div>
    </div>

    <!-- What the card understood, in one line: the terms it picked, the
         contacts, the surface factors. The pickers sit behind Edit: seven
         controls at once read as a form to fill, and the picks made from
         the property kinds are usually right. -->
    <div class="fp-subbar fvo-chain" v-if="params.grid && !editing">
      <fp-chip v-for="c in chain" :key="c.key" sm :variant="c.warn ? 'warn' : 'line'"
               :text="c.text" :title="c.title" />
      <fp-btn tiny label="Edit" title="Change the terms (porosity, NTG, Sw, region), the contacts and the surface factors"
              @click="editing = true" />
    </div>

    <template v-if="params.grid && editing">
      <div class="fp-subbar fvo-params">
        <label class="fp-lab" v-for="k in terms" :key="k.key" :class="{ 'fvo-warn': warned[k.key] }" :title="warned[k.key] || k.title">{{ k.label }}
          <fp-select class="fvo-sel" :model-value="params[k.key] || ''" :options="propOptions(k.key)"
                     :title="warned[k.key] || k.title" @update:model-value="set(k.key, $event || '')" />
        </label>
        <label class="fp-lab" title="Gas-oil contact, depth positive down (TVD); empty = no gas cap">GOC
          <fp-num class="fvo-num" :model-value="depth(params.goc)" nullable placeholder="depth"
                  title="Gas-oil contact, depth positive down (TVD); empty = no gas cap"
                  @update:model-value="set('goc', $event)" />
        </label>
        <label class="fp-lab" title="Oil-water contact, depth positive down (TVD); empty = no water leg">OWC
          <fp-num class="fvo-num" :model-value="depth(params.owc)" nullable placeholder="depth"
                  title="Oil-water contact, depth positive down (TVD); empty = no water leg"
                  @update:model-value="set('owc', $event)" />
        </label>
        <!-- the planes need a depth to sit at: with no contact given the
             box is disabled and its tooltip says why, rather than offering
             a tick that does nothing -->
        <label class="fp-lab fvo-check" :class="{ 'fvo-off': !hasContact }" :title="contactsTitle">
          <input type="checkbox" :checked="!!params.show_contacts" :disabled="!hasContact"
                 :title="contactsTitle" @change="set('show_contacts', $event.target.checked)" />
          show the contacts in the 3D view
        </label>
      </div>
      <!-- Surface conditions, optional: the HCPV is a volume at reservoir
           pressure; Bo / Bg take it to surface conditions (STOIIP, GIIP),
           the recovery factors to what is produced. No factor given, no
           column added. -->
      <div class="fp-subbar fvo-params fvo-surface">
        <span class="fxo-tag fp-sum" title="Optional: from the hydrocarbon pore volume to surface volumes">Surface</span>
        <label class="fp-lab" v-for="f in SURFACE" :key="f.key" :title="f.title">{{ f.label }}
          <fp-num class="fvo-num" :model-value="depth(params[f.key])" nullable :placeholder="f.placeholder"
                  :title="f.title" @update:model-value="set(f.key, $event)" />
        </label>
        <fp-btn tiny label="Done" title="Fold the terms back into their summary line" @click="editing = false" />
      </div>
    </template>

    <!-- UI rule R10 (doc/wiki/UI-Drawer-Toolbar-Shared.md): what the compute
         held back is a warning band, not the empty state's text -->
    <fp-note v-if="data && data.note" severity="warning" :text="data.note" />

    <fp-empty v-if="!hasTable"
              shows="Bulk, net, pore and hydrocarbon pore volumes (GRV → NRV → PV → HCPV) per fluid zone and region, from the grid's own properties — and, with Bo / Bg, the oil and gas in place at surface conditions."
              gesture="Press “Compute” — the line above says which properties the card picked; “Edit” changes them and sets the contacts." />
    <template v-else>
      <!-- one display unit per family of columns: the reservoir volumes,
           the oil at surface, the gas at surface (each select shown only
           when its columns are); the CSV stays in cubic metres -->
      <div class="fp-subbar fvo-units">
        <fp-select class="fvo-unit" label="reservoir" v-model="scale" :options="UNIT_OPTIONS"
                   title="Display unit of the reservoir volumes (GRV, NRV, PV, HCPV) — the CSV export stays in cubic meters. Reservoir barrels (6.28981 rbbl per m³, at reservoir conditions — not stock-tank barrels)" />
        <fp-select v-if="hasOil" class="fvo-unit" label="oil" v-model="oilScale" :options="OIL_OPTIONS"
                   title="Display unit of the oil at surface conditions (STOIIP, recoverable oil) — the CSV export stays in standard cubic meters; 6.28981 stb per sm³" />
        <fp-select v-if="hasGas" class="fvo-unit" label="gas" v-model="gasScale" :options="GAS_OPTIONS"
                   title="Display unit of the gas at surface conditions (GIIP, recoverable gas) — the CSV export stays in standard cubic meters; 35.3147 scf per sm³" />
      </div>
      <div class="fp-scroll">
        <table class="fvo-table fp-table">
          <thead>
            <tr>
              <th>Region</th><th>Fluid</th><th class="num">Cells</th>
              <th class="num" title="Gross rock volume">GRV ({{ unitLabel }})</th>
              <th class="num" title="Net rock volume = GRV × NTG">NRV ({{ unitLabel }})</th>
              <th class="num" title="Pore volume = NRV × porosity">PV ({{ unitLabel }})</th>
              <th class="num" title="Hydrocarbon pore volume = PV × (1 − Sw)">HCPV ({{ unitLabel }})</th>
              <th v-if="hasOil" class="num" title="Stock-tank oil initially in place = HCPV / Bo, on the oil zones">STOIIP ({{ oilLabel }})</th>
              <th v-if="hasRecOil" class="num" title="Recoverable oil = STOIIP × RF oil">Rec. oil ({{ oilLabel }})</th>
              <th v-if="hasGas" class="num" title="Gas initially in place = HCPV / Bg, on the gas zones">GIIP ({{ gasLabel }})</th>
              <th v-if="hasRecGas" class="num" title="Recoverable gas = GIIP × RF gas">Rec. gas ({{ gasLabel }})</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(r, i) in rows" :key="'r' + i">
              <td :title="regionTitle(r)">{{ r.region }}</td><td>{{ r.fluid }}</td><td class="num">{{ fmtInt(r.cells) }}</td>
              <td class="num">{{ volume(r.grv) }}</td><td class="num">{{ volume(r.nrv) }}</td>
              <td class="num">{{ volume(r.pv) }}</td><td class="num">{{ volume(r.hcpv) }}</td>
              <td v-if="hasOil" class="num">{{ oil(r.stoiip) }}</td>
              <td v-if="hasRecOil" class="num">{{ oil(r.rec_oil) }}</td>
              <td v-if="hasGas" class="num">{{ gas(r.giip) }}</td>
              <td v-if="hasRecGas" class="num">{{ gas(r.rec_gas) }}</td>
            </tr>
            <tr v-for="(r, i) in totals" :key="'t' + i" :class="['total', { grand: r.fluid === 'total' }]">
              <td :title="regionTitle(r)">{{ r.region }}</td><td>{{ r.fluid }}</td><td class="num">{{ fmtInt(r.cells) }}</td>
              <td class="num">{{ volume(r.grv) }}</td><td class="num">{{ volume(r.nrv) }}</td>
              <td class="num">{{ volume(r.pv) }}</td><td class="num">{{ volume(r.hcpv) }}</td>
              <td v-if="hasOil" class="num">{{ oil(r.stoiip) }}</td>
              <td v-if="hasRecOil" class="num">{{ oil(r.rec_oil) }}</td>
              <td v-if="hasGas" class="num">{{ gas(r.giip) }}</td>
              <td v-if="hasRecGas" class="num">{{ gas(r.rec_gas) }}</td>
            </tr>
          </tbody>
        </table>
        <div class="fvo-foot" v-if="data && data.convention">{{ data.convention }}</div>
      </div>
    </template>
  </div>
</template>

<script>
/*
 * Volumetrics panel, decoupled from the engine:
 *   props in   — `data`: {grids, props, params, rows, totals, cells, active,
 *                units, convention, note, grid_title, surface,
 *                percentile_terms, csv: {name, header}}, built by the host
 *                from engine/volumetrics_dispatch,
 *   events out — set([key, value]) / compute().
 * Volumes arrive in m³ (the surface ones in sm³); the unit selects rescale
 * for display only, one per family of columns (reservoir, oil, gas). The
 * CSV carries the raw cubic metres under the provenance header the server
 * sends. The terms, the contacts and the surface factors sit behind Edit:
 * at rest the card says what it understood in one line of chips.
 */
import { fmt, fmtInt } from "../../../_shared/numfmt.js";
import { buildCsv, csvMeta } from "../../../_shared/csvexport.js";
import FpBtn from "../../../_shared/components/FpBtn.vue";
import FpChip from "../../../_shared/components/FpChip.vue";
import FpEmpty from "../../../_shared/components/FpEmpty.vue";
import FpExport from "../../../_shared/components/FpExport.vue";
import FpNote from "../../../_shared/components/FpNote.vue";
import FpNum from "../../../_shared/components/FpNum.vue";
import FpSelect from "../../../_shared/components/FpSelect.vue";

const TERMS = [
  { key: "poro", label: "porosity", short: "φ", title: "Porosity — a fraction, or % (read as a fraction)" },
  { key: "ntg", label: "NTG", short: "NTG", title: "Net-to-gross — a fraction, a pay flag from the cutoffs; none = 1" },
  { key: "sw", label: "Sw", short: "Sw", title: "Water saturation — a fraction; none leaves HCPV empty" },
  { key: "region", label: "region", short: "by", title: "A discrete or categorical property that splits the totals: fault blocks, zones, facies" },
];
// the surface factors: how a reservoir volume becomes a surface one, and
// what part of it is recoverable
const SURFACE = [
  { key: "bo", label: "Bo", placeholder: "rm³/sm³", title: "Oil formation volume factor, reservoir m³ per stock-tank m³ (e.g. 1.2): STOIIP = HCPV / Bo on the oil zones. Empty = no STOIIP" },
  { key: "bg", label: "Bg", placeholder: "rm³/sm³", title: "Gas formation volume factor, reservoir m³ per standard m³ (e.g. 0.005): GIIP = HCPV / Bg on the gas zones. Empty = no GIIP" },
  { key: "rf_oil", label: "RF oil", placeholder: "0–1", title: "Oil recovery factor, a fraction (30 is read as 30 %): recoverable oil = STOIIP × RF. Empty = in place only" },
  { key: "rf_gas", label: "RF gas", placeholder: "0–1", title: "Gas recovery factor, a fraction (70 is read as 70 %): recoverable gas = GIIP × RF. Empty = in place only" },
];
// barrels per cubic metre: reservoir barrels per reservoir m³ for the
// reservoir volumes, stock-tank barrels per standard m³ for the oil
const BBL_PER_M3 = 6.28981;
// standard cubic feet per standard cubic metre, for the gas
const SCF_PER_M3 = 35.3147;
const UNITS = {
  "1": { label: "m³", factor: 1 },
  "1e6": { label: "10⁶ m³", factor: 1e-6 },
  rbbl: { label: "rbbl", factor: BBL_PER_M3 },
  MMrbbl: { label: "MMrbbl", factor: BBL_PER_M3 / 1e6 },
};
const OIL_UNITS = {
  "1": { label: "sm³", factor: 1 },
  "1e6": { label: "10⁶ sm³", factor: 1e-6 },
  stb: { label: "stb", factor: BBL_PER_M3 },
  MMstb: { label: "MMstb", factor: BBL_PER_M3 / 1e6 },
};
const GAS_UNITS = {
  "1": { label: "sm³", factor: 1 },
  "1e6": { label: "10⁶ sm³", factor: 1e-6 },
  scf: { label: "scf", factor: SCF_PER_M3 },
  Bcf: { label: "Bcf", factor: SCF_PER_M3 / 1e9 },
};
const UNIT_OPTIONS = [
  { value: "1", label: "m³", title: "Cubic meters" },
  { value: "1e6", label: "10⁶ m³", title: "Millions of cubic meters" },
  { value: "rbbl", label: "rbbl (reservoir barrel)", title: "Reservoir barrels, 6.28981 per cubic meter at reservoir conditions" },
  { value: "MMrbbl", label: "MMrbbl", title: "Millions of reservoir barrels" },
];
const OIL_OPTIONS = [
  { value: "1", label: "sm³", title: "Standard cubic meters" },
  { value: "1e6", label: "10⁶ sm³", title: "Millions of standard cubic meters" },
  { value: "stb", label: "stb (stock-tank barrel)", title: "Stock-tank barrels, 6.28981 per standard cubic meter" },
  { value: "MMstb", label: "MMstb", title: "Millions of stock-tank barrels" },
];
const GAS_OPTIONS = [
  { value: "1", label: "sm³", title: "Standard cubic meters" },
  { value: "1e6", label: "10⁶ sm³", title: "Millions of standard cubic meters" },
  { value: "scf", label: "scf (standard cubic foot)", title: "Standard cubic feet, 35.3147 per standard cubic meter" },
  { value: "Bcf", label: "Bcf", title: "Billions of standard cubic feet" },
];
const CSV_COLUMNS = ["region_code", "region", "fluid", "cells", "GRV (m3)", "NRV (m3)", "PV (m3)", "HCPV (m3)"];
// the surface columns: [CSV header, row key, computed flag that shows the
// column on screen]
const CSV_SURFACE = [
  ["STOIIP (sm3)", "stoiip", "hasOil"], ["recoverable_oil (sm3)", "rec_oil", "hasRecOil"],
  ["GIIP (sm3)", "giip", "hasGas"], ["recoverable_gas (sm3)", "rec_gas", "hasRecGas"],
];

export default {
  name: "VolumetricsPanel",
  components: { FpBtn, FpChip, FpEmpty, FpExport, FpNote, FpNum, FpSelect },
  props: {
    data: { type: Object, default: () => ({}) },
  },
  emits: ["set", "compute"],
  data() {
    return { scale: "1e6", oilScale: "MMstb", gasScale: "Bcf", editing: false,
      UNIT_OPTIONS, OIL_OPTIONS, GAS_OPTIONS, SURFACE };
  },
  watch: {
    // another grid comes with its own picks: fold the fields back so the
    // summary line shows them
    "params.grid"() { this.editing = false; },
  },
  computed: {
    terms() { return TERMS; },
    grids() { return (this.data && this.data.grids) || []; },
    props() { return (this.data && this.data.props) || []; },
    params() { return (this.data && this.data.params) || {}; },
    rows() { return (this.data && this.data.rows) || []; },
    totals() { return (this.data && this.data.totals) || []; },
    hasTable() { return this.rows.length > 0 || this.totals.length > 0; },
    // a surface column exists only when its factor was given to the last
    // compute
    surface() { return (this.data && this.data.surface) || {}; },
    hasOil() { return !!this.surface.bo; },
    hasGas() { return !!this.surface.bg; },
    hasRecOil() { return this.hasOil && this.surface.rf_oil !== null && this.surface.rf_oil !== undefined; },
    hasRecGas() { return this.hasGas && this.surface.rf_gas !== null && this.surface.rf_gas !== undefined; },
    gridOptions() {
      return this.grids.map((g) => ({ value: g.path, label: g.title, title: "Cube the cells of " + g.title }));
    },
    csvName() {
      return csvMeta(this.data && this.data.csv, "volumetrics.csv").name;
    },
    unitLabel() { return (UNITS[this.scale] || UNITS["1"]).label; },
    oilLabel() { return (OIL_UNITS[this.oilScale] || OIL_UNITS["1"]).label; },
    gasLabel() { return (GAS_UNITS[this.gasScale] || GAS_UNITS["1"]).label; },
    // {term: sentence} for a term whose property is a per-cell percentile
    // across realizations: cubing it does not give the percentile of the
    // volume, and the field says so where it is chosen
    warned() {
      const out = {};
      ((this.data && this.data.percentile_terms) || []).forEach((w) => {
        out[w.term] = w.text;
      });
      return out;
    },
    hasContact() {
      return this.depth(this.params.goc) !== null || this.depth(this.params.owc) !== null;
    },
    contactsTitle() {
      return this.hasContact
        ? "Draw the contacts as translucent horizontal planes through the grid in the 3D view (orange GOC, blue OWC)"
        : "Give a GOC or an OWC first: there is no contact to draw";
    },
    // the summary line: one chip per term (the property picked, or none),
    // the contacts, the surface factors given — what Compute will use
    chain() {
      const out = [];
      for (const t of TERMS) {
        const path = this.params[t.key];
        const p = this.props.find((x) => x.path === path);
        const name = p ? p.title : "none";
        // FpChip caps a warn chip at sixty characters: the text is cut
        // short and the full name stays in the tooltip
        const text = t.short + ": " + name;
        out.push({ key: t.key, text: text.length > 56 ? text.slice(0, 55) + "…" : text, warn: !!this.warned[t.key],
          title: (this.warned[t.key] || t.title) + " — " + (p ? p.title + (p.unit ? " (" + p.unit + ")" : "") : "none picked") });
      }
      const goc = this.depth(this.params.goc), owc = this.depth(this.params.owc);
      const drawn = this.hasContact && !!this.params.show_contacts;
      out.push({ key: "contacts",
        text: ((goc === null && owc === null) ? "no contact" : ["GOC " + (goc === null ? "–" : goc), "OWC " + (owc === null ? "–" : owc)].join(" · "))
          + (drawn ? " · drawn in 3D" : ""),
        title: "The fluid zones: gas above the GOC, oil between the contacts, water below the OWC; no contact = the whole grid, one zone"
          + (drawn ? " — drawn as horizontal planes in the 3D view (orange GOC, blue OWC)" : "") });
      const sf = SURFACE.filter((f) => this.depth(this.params[f.key]) !== null)
        .map((f) => f.label + " " + this.depth(this.params[f.key]));
      if (sf.length) out.push({ key: "surface", text: sf.join(" · "), title: "Surface conditions: STOIIP = HCPV / Bo, GIIP = HCPV / Bg, recoverable = in place × RF" });
      return out;
    },
  },
  methods: {
    set(key, value) {
      this.$emit("set", [key, value]);
    },
    // Compute is the end of an edit: the summary line says what was cubed
    compute() {
      this.editing = false;
      this.$emit("compute");
    },
    // a contact (or a surface factor) is a Number, or null when not set;
    // the host sends a float or None, and <fp-num> reads a typed comma as
    // the decimal point
    depth(v) {
      return v === null || v === undefined || v === "" ? null : Number(v);
    },
    propsFor(key) {
      if (key === "region") {
        return this.props.filter((p) => p.type === "DiscreteProperty" || p.type === "CategoricalProperty");
      }
      return this.props.filter((p) => p.type !== "CategoricalProperty");
    },
    propOptions(key) {
      const none = key === "region"
        ? "Totals over the whole grid, no split"
        : (TERMS.find((t) => t.key === key) || {}).title + " — none";
      return [{ value: "", label: "(none)", title: none }].concat(this.propsFor(key).map((p) => ({
        value: p.path,
        label: p.title + (p.unit ? " · " + p.unit : "") + (p.kind ? " · " + p.kind : ""),
        title: p.title + (p.kind ? " (" + p.kind + ")" : ""),
      })));
    },
    fmtInt,
    // values for the screen: the raw m³ (or sm³) converted to the unit
    // selected for its family, then formatted by the shared numfmt rule
    volume(v) {
      if (v === null || v === undefined) return fmt(null);
      return fmt(Number(v) * (UNITS[this.scale] || UNITS["1"]).factor);
    },
    oil(v) {
      if (v === null || v === undefined) return fmt(null);
      return fmt(Number(v) * (OIL_UNITS[this.oilScale] || OIL_UNITS["1"]).factor);
    },
    gas(v) {
      if (v === null || v === undefined) return fmt(null);
      return fmt(Number(v) * (GAS_UNITS[this.gasScale] || GAS_UNITS["1"]).factor);
    },
    regionTitle(r) {
      return r.region_code !== null && r.region_code !== undefined ? "code " + r.region_code : "";
    },
    // raw cubic metres whatever the display unit; a volume the terms could
    // not give (no Sw for HCPV) is null and reads n/a; the region code is
    // empty on the rows that aggregate every region; the surface columns
    // are the ones on screen: a factor never given means no column, not a
    // column of n/a
    csvText() {
      const { header } = csvMeta(this.data && this.data.csv, "volumetrics.csv");
      const surface = CSV_SURFACE.filter(([, , flag]) => this[flag]);
      const rows = this.rows.concat(this.totals).map((r) => [
        r.region_code === null || r.region_code === undefined ? "" : r.region_code,
        r.region, r.fluid, r.cells, r.grv, r.nrv, r.pv, r.hcpv,
      ].concat(surface.map(([, key]) => r[key])));
      return buildCsv(header, CSV_COLUMNS.concat(surface.map(([name]) => name)), rows);
    },
  },
};
</script>

<style>
@import "../../../_shared/panel.css";
</style>

<style scoped>
/* the first row carries the bar's fill; the rows below it continue the bar */
.fvo-filled { background: var(--fp-neutral-bg); border-bottom-color: var(--fp-line); }
.fvo-params, .fvo-chain, .fvo-units { background: none; }
.fvo-chain { gap: 6px; }
.fvo-surface { padding-top: 0; }
.fxo-tag { white-space: nowrap; }
.fvo-check { cursor: pointer; user-select: none; }
.fvo-check.fvo-off { opacity: 0.55; cursor: not-allowed; }
.fvo-sel { max-width: 240px; }
.fvo-unit { max-width: 200px; }
.fvo-num { width: 84px; }
.fvo-warn { color: var(--fp-warn-ink); border-left: 3px solid var(--fp-warn-bg); padding-left: 5px; }
.fvo-table td { white-space: nowrap; }
tr.total td { font-weight: 600; background: #f7f9fb; }
tr.grand td { border-top: 2px solid var(--fp-accent); }
.fvo-foot { color: var(--fp-ink-faint); font-size: var(--fp-size-small); padding: 6px 8px; }
</style>
