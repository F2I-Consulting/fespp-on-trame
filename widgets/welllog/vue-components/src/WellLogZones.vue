<template>
  <!-- Zone statistics: the payload's `zones` per well, one row per (well,
       zone, curve), and the cutoffs that flag the pay. A card of the log
       view: it fills the card and its table scrolls. -->
  <div class="wlc-zones">
    <div class="wlc-zones-head">
      <span class="wlc-zones-src">{{ sourceLabel }}</span>
      <fp-export :filename="zonesCsvName" :build="zonesCsvText" :disabled="!zoneRows.length"
                 disabled-why="there is no zone to report yet"
                 title="Copy the zones table as CSV — raw values under a dated provenance header, n/a where a figure could not be evaluated; a download when the browser offers no clipboard (plain http)" />
      <!-- Cutoffs: pay is where EVERY rule holds. The rules are evaluated
           server-side on the samples; this only edits them. -->
      <span v-if="curveNames.length" class="wlc-cut">
        <span class="wlc-cut-title">Cutoffs</span>
        <span v-for="(r, i) in rules" :key="i" class="wlc-cut-rule">
          <fp-select :model-value="r.curve" :options="curveOptions" placeholder="curve" mandatory
                     title="The log the cutoff reads" @update:model-value="r.curve = $event || ''; emitRules()" />
          <fp-select :model-value="r.op" :options="opOptions"
                     title="Operator — = and ≠ are for a discrete log (a facies code, a zone index); on a continuous log a value is rarely hit exactly"
                     @update:model-value="r.op = $event; emitRules()" />
          <fp-num :model-value="ruleValue(r)" nullable size="sm" placeholder="value"
                  title="Threshold, in the curve's unit" @update:model-value="r.value = $event; emitRules()" />
          <fp-btn variant="bare" label="×" title="Remove this cutoff" @click="removeRule(i)" />
        </span>
        <fp-btn tiny label="+ Cutoff" :disabled="!curveNames.length"
                :title="curveNames.length ? 'Add a cutoff: pay is where every cutoff holds' : 'No log is drawn yet'"
                @click="addRule" />
        <span v-if="hasCutoffs" class="wlc-cut-legend">
          <span class="wlc-pay-swatch"></span>pay
        </span>
      </span>
    </div>
    <div v-if="zoneRows.length" class="wlc-zones-scroll">
      <table class="wlc-zones-table">
        <thead>
          <tr>
            <th>Well</th><th>Zone</th>
            <th class="num" :title="depthTitle">Top ({{ drawAxis }})</th>
            <th class="num" :title="depthTitle">Base ({{ drawAxis }})</th>
            <th v-if="showGrossDrawn" class="num" :title="grossDrawnTitle">Gross ({{ drawAxis }})</th>
            <th class="num" title="Gross vertical thickness: base TVD − top TVD">Gross (TVD)</th>
            <th v-if="hasCutoffs" class="num" title="Net vertical thickness: the pay of the zone summed on true vertical depth">Net (TVD)</th>
            <th v-if="hasCutoffs" class="num" title="Net TVD ÷ gross TVD">N/G (TVD)</th>
            <th v-if="hasSums" class="num" :title="phihTitle">
              Φ·h (TVD)<span v-if="phiPick" class="wlc-th-sub">{{ phiPick }}</span>
            </th>
            <th v-if="hasSums" class="num" :title="hcphTitle">
              Φ(1−Sw)·h (TVD)<span v-if="phiPick && swPick" class="wlc-th-sub">{{ phiPick }}, {{ swPick }}</span>
            </th>
            <th>Curve</th>
            <th class="num">n</th><th class="num">Mean</th>
            <th v-if="hasCutoffs" class="num" title="Mean over the pay samples">Mean·pay</th>
            <th class="num">P10</th><th class="num">P50</th><th class="num">P90</th>
            <th class="num">Min</th><th class="num">Max</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in zoneRows" :key="r.key" :class="{ 'wlc-zones-gross': !r.curve }">
            <td>{{ r.well }}</td>
            <td>
              <span class="wlc-swatch" :style="{ background: r.color || '#bbb' }"></span>
              {{ r.zone }}
            </td>
            <td class="num" :title="r.depthRef">{{ fmtFixed(r.top, 2) }}</td>
            <td class="num" :title="r.depthRef">{{ fmtFixed(r.bottom, 2) }}</td>
            <td v-if="showGrossDrawn" class="num" :title="r.depthRef">{{ fmtFixed(r.thickness, 2) }}</td>
            <td class="num" :class="{ 'wlc-na': r.na.gross }" :title="r.na.gross">{{ grossText(r) }}</td>
            <td v-if="hasCutoffs" class="num" :class="{ 'wlc-na': r.na.net }" :title="r.na.net">{{ sumText(r, 'net') }}</td>
            <td v-if="hasCutoffs" class="num" :class="{ 'wlc-na': r.na.ntg }" :title="r.na.ntg">{{ sumText(r, 'ntg') }}</td>
            <td v-if="hasSums" class="num" :class="{ 'wlc-na': r.na.phih }" :title="r.na.phih">{{ sumText(r, 'phih') }}</td>
            <td v-if="hasSums" class="num" :class="{ 'wlc-na': r.na.hcph }" :title="r.na.hcph">{{ sumText(r, 'hcph') }}</td>
            <td>{{ r.curve || '–' }}<span v-if="r.unit" class="wlc-unit"> {{ r.unit }}</span></td>
            <td class="num">{{ r.curve ? fmtInt(r.n) : '' }}</td>
            <td class="num">{{ r.curve ? fmt(r.mean) : '' }}</td>
            <td v-if="hasCutoffs" class="num" :class="{ 'wlc-na': r.na.mean_pay }" :title="r.na.mean_pay">{{ sumText(r, 'mean_pay') }}</td>
            <td class="num">{{ r.curve ? fmt(r.p10) : '' }}</td>
            <td class="num">{{ r.curve ? fmt(r.p50) : '' }}</td>
            <td class="num">{{ r.curve ? fmt(r.p90) : '' }}</td>
            <td class="num">{{ r.curve ? fmt(r.min) : '' }}</td>
            <td class="num">{{ r.curve ? fmt(r.max) : '' }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <fp-empty v-else class="wlc-zones-none"
              shows="One row per well, zone and curve: thickness, net pay under the cutoffs and the statistics of each log."
              gesture="Check two markers on the same well, and the zones between them appear." />
    <!-- Under the cutoffs, the report says what it read: the porosity and
         water-saturation logs behind Φ·h (the kind is matched by name, so
         a neutron porosity can be taken for an effective one — the reader
         must see which), and the wells whose pay it could not evaluate,
         with why and the next step when there is one. -->
    <div v-if="zoneNotes.length" class="wlc-zones-notes">
      <div v-for="(n, i) in zoneNotes" :key="i">{{ n }}</div>
    </div>
  </div>
</template>

<script>
import { fmt, fmtFixed, fmtInt, fmtPct } from "../../../_shared/numfmt.js";
import { buildCsv, csvMeta } from "../../../_shared/csvexport.js";
import FpBtn from "../../../_shared/components/FpBtn.vue";
import FpEmpty from "../../../_shared/components/FpEmpty.vue";
import FpExport from "../../../_shared/components/FpExport.vue";
import FpNum from "../../../_shared/components/FpNum.vue";
import FpSelect from "../../../_shared/components/FpSelect.vue";

// the zones table as a file: one unit per column, the reasons of every n/a in `note`
const ZONES_CSV_COLUMNS = [
  "well", "depth_axis", "zone", "zone_source",
  "top (depth_axis)", "base (depth_axis)", "top_tvd", "base_tvd",
  "gross (depth_axis)", "gross_tvd", "net_tvd", "ntg (fraction)", "phih_tvd", "hcph_tvd",
  "curve", "unit", "n", "mean", "mean_pay", "p10", "p50", "p90", "min", "max", "note",
];

// the two equalities are for a discrete log (a facies code, a zone index)
const OPS = [">=", "<=", ">", "<", "=", "≠"];
const OP_WORDS = {
  ">=": "at least", "<=": "at most", ">": "above", "<": "below",
  "=": "equal to (a discrete log)", "≠": "other than (a discrete log)",
};

// a rule leaves the widget only once its curve, operator and finite value are set
function complete(r) {
  return r.curve && OPS.includes(r.op) && r.value !== "" && r.value !== null
    && Number.isFinite(Number(r.value));
}

export default {
  name: "WellLogZones",
  components: { FpBtn, FpEmpty, FpExport, FpNum, FpSelect },
  props: {
    // the log view's payload ({wells, csv}): the zones of each well
    data: {
      type: Object,
      default: () => ({ wells: [], markers: [], flattenOn: null }),
    },
    // The cutoffs in force, [{curve, op, value}]: the host's copy, echoed
    // back through `cutoffs-change` as the user edits them.
    cutoffs: {
      type: Array,
      default: () => [],
    },
  },
  emits: ["cutoffs-change"],
  data() {
    return { rules: [] };
  },
  computed: {
    // One row per (well, zone, curve); a zone with no curve still gets a
    // row carrying its thickness — the gross interval is information too.
    // `na` holds, per summation column, why the row has no figure there:
    // a pay figure is null when a rule's log is not among the well's
    // curves (the zone's `pay_na`, worded from the well's `pay_na_why`:
    // unticked is not unlogged), Φ·h when no porosity log was read — never
    // a zero, which would read as a sterile well.
    zoneRows() {
      const rows = [];
      for (const w of (this.data && this.data.wells) || []) {
        const sums = w.summation || {};
        for (const z of w.zones || []) {
          const notEval = z.pay_na && z.pay_na.length
            ? `${this.absentText(z.pay_na, w.pay_na_why)} — the cutoff cannot be evaluated` : null;
          const noPhi = sums.phi ? null
            : `no porosity log read on this well — ${this.noKindWhy("porosity", sums.phi_absent)}`;
          const noSw = sums.sw ? null
            : `no water-saturation log read on this well — ${this.noKindWhy("water saturation", sums.sw_absent)}`;
          const base = {
            well: w.name, zone: z.name, color: z.color, source: z.source,
            depthRef: w.depthRef || "TVD",
            top: z.top, bottom: z.bottom, thickness: z.thickness,
            top_tvd: z.top_tvd, bottom_tvd: z.bottom_tvd,
            thickness_tvd: z.thickness_tvd,
            net: z.net, ntg: z.ntg, phih: z.phih, hcph: z.hcph,
            na: {
              gross: z.tvd_na || null,
              net: notEval || z.tvd_na || null,
              ntg: notEval || z.tvd_na || null,
              phih: notEval || z.tvd_na || noPhi,
              hcph: notEval || z.tvd_na || noPhi || noSw,
            },
          };
          if (!z.curves || !z.curves.length) {
            rows.push({ ...base, key: `${w.name}|${z.name}|${z.top}|-`, curve: null });
            continue;
          }
          // the gross row first, so Net / N/G read once per zone
          rows.push({ ...base, key: `${w.name}|${z.name}|${z.top}|-`, curve: null });
          for (const c of z.curves) {
            const noPay = c.mean_pay === null && !notEval
              ? "no sample of this log falls in the pay of this zone" : null;
            rows.push({ ...base, ...c, curve: c.name,
                        na: { mean_pay: notEval || noPay },
                        key: `${w.name}|${z.name}|${z.top}|${c.name}` });
          }
        }
      }
      return rows;
    },
    // the wells the summation report was built for — `summation` rides on
    // every well of a payload rebuilt under cutoffs
    sumWells() {
      return ((this.data && this.data.wells) || []).filter((w) => w.summation);
    },
    // the porosity / water-saturation log every well agrees on, else null
    // (the notes then name each well's own)
    phiPick() {
      const picks = new Set(this.sumWells.map((w) => w.summation.phi || ""));
      return picks.size === 1 ? [...picks][0] || null : null;
    },
    swPick() {
      const picks = new Set(this.sumWells.map((w) => w.summation.sw || ""));
      return picks.size === 1 ? [...picks][0] || null : null;
    },
    phihTitle() {
      return "Porosity-thickness over the pay" + (this.phiPick
        ? ` — Φ read from ${this.phiPick}`
        : " — the note under the table names each well's porosity log");
    },
    hcphTitle() {
      return "Hydrocarbon pore thickness over the pay" + (this.phiPick && this.swPick
        ? ` — Φ read from ${this.phiPick}, Sw from ${this.swPick}`
        : " — the note under the table names each well's porosity and water-saturation logs");
    },
    // The axis the DEPTHS are tabulated on — measured depth when every well
    // of the table has one, true vertical otherwise, "per well" when they
    // disagree (each depth cell then carries its own in a tooltip). The
    // thicknesses never follow it: they are vertical on every well.
    drawAxis() {
      const refs = new Set(((this.data && this.data.wells) || [])
        .map((w) => w.depthRef || "TVD"));
      if (refs.size === 1) return [...refs][0];
      return refs.size ? "per well" : "TVD";
    },
    drawAxisWord() {
      return { MD: "measured depth", TVD: "true vertical depth" }[this.drawAxis]
        || "each well's own depth axis";
    },
    depthTitle() {
      return `Depth on ${this.drawAxisWord}`;
    },
    // the along-hole gross beside the vertical one — nothing is replaced in
    // silence. When every well is on the vertical the two are the same
    // figure, so the column would only repeat itself and is hidden.
    showGrossDrawn() {
      return ((this.data && this.data.wells) || [])
        .some((w) => (w.depthRef || "TVD") !== "TVD");
    },
    grossDrawnTitle() {
      return `Gross along ${this.drawAxisWord}: base − top`
             + " — an interval of hole, not a thickness of rock";
    },
    zoneNotes() {
      const wells = this.sumWells;
      const notes = [];
      // which axis is tabulated and which is summed — the reader must never
      // have to guess whether a thickness follows the hole or the vertical
      if (this.zoneRows.length) {
        notes.push(`Top and base are on ${this.drawAxisWord}; thicknesses, N/G`
                   + " and the Φ·h sums are integrated on true vertical depth.");
      }
      // a well that comes back up: an upward stretch subtracts, which is the
      // right vertical thickness and a surprise worth stating
      for (const w of (this.data && this.data.wells) || []) {
        if (w.tvd_up_hole > 0) {
          notes.push(`${w.name}: ${fmtFixed(w.tvd_up_hole, 1)} m of hole comes`
                     + " back up (a re-entry or an upward horizontal section);"
                     + " an upward stretch subtracts from the vertical thicknesses.");
        }
      }
      // the summation line explains columns, so it only stands under a
      // table: one line when every well reads the same logs, else one per
      // well, named
      if (this.zoneRows.length) {
        const lines = wells.map((w) => this.summationLine(w.summation));
        const distinct = new Set(lines);
        notes.push(...(distinct.size === 1
          ? [lines[0]] : wells.map((w, i) => `${w.name}: ${lines[i]}`)));
      }
      // a well whose pay is not evaluable: why, and what it dashes — the
      // columns the table actually has
      const cols = this.hasSums
        ? "Net, N/G, Mean·pay, Φ·h and Φ(1−Sw)·h" : "Net, N/G and Mean·pay";
      for (const w of wells) {
        if (w.pay_na && w.pay_na.length) {
          notes.push(`${w.name}: ${this.absentText(w.pay_na, w.pay_na_why)} — the cutoff`
                     + " cannot be evaluated there: no pay band"
                     + (this.zoneRows.length ? `, and ${cols} show a dash.` : "."));
        }
      }
      return notes;
    },
    sourceLabel() {
      const wells = (this.data && this.data.wells) || [];
      const src = new Set();
      for (const w of wells) for (const z of w.zones || []) src.add(z.source);
      if (src.has("frame")) return "zones from the marker frame's own stratigraphy";
      if (src.has("column")) return "zones from the stratigraphic column";
      if (src.has("markers")) return "zones between consecutive markers";
      return "";
    },
    // every log name any well carries — the editor's curve choices
    curveNames() {
      const names = new Set();
      for (const w of (this.data && this.data.wells) || []) {
        for (const t of w.tracks || []) {
          for (const c of t.curves || []) if (!c.missing) names.add(c.name);
        }
      }
      return [...names].sort();
    },
    hasCutoffs() {
      return this.sumWells.length > 0;
    },
    // the Φ·h columns exist as soon as one well has a porosity log to read
    // — a well that has one but lacks the cutoff's log shows a dash there
    hasSums() {
      return this.sumWells.some((w) => w.summation.phi);
    },
    curveOptions() {
      return this.curveNames.map((n) => ({ value: n, label: n, title: "The " + n + " log" }));
    },
    opOptions() {
      return OPS.map((o) => ({ value: o, label: o, title: OP_WORDS[o] }));
    },
    zonesCsvName() {
      return csvMeta(this.data && this.data.csv, "zones.csv").name;
    },
  },
  watch: {
    // the host's copy wins (another client, a reset) — but not while the
    // user is typing: a half-typed rule is not sent, so it must not be
    // overwritten by the echo of the last complete set
    cutoffs: {
      immediate: true,
      handler(v) {
        const sent = this.rules.filter(complete).map(this.plain);
        if (JSON.stringify(sent) !== JSON.stringify(v || [])) {
          this.rules = (v || []).map((r) => ({ ...r }));
        }
      },
    },
  },
  methods: {
    fmt,
    // depths keep their centimetres: a zone top is a position, not a
    // measured quantity rounded to four digits
    fmtFixed,
    fmtInt,
    // the gross VERTICAL thickness, or a dash when the zone has none (a
    // horizontal section, or bounds with no vertical depth) — the top and
    // base stay in their own columns either way
    grossText(r) {
      return r.na.gross ? "–" : fmtFixed(r.thickness_tvd, 2);
    },
    // a summation cell: the figure, or a dash when the row says why not
    sumText(r, key) {
      if (key === "mean_pay" ? !r.curve : r.curve) return "";
      if (r.na[key]) return "–";
      return key === "ntg" ? fmtPct(r[key]) : fmt(r[key]);
    },
    // the zones table, raw: a summation column exists on the file as on the
    // screen (with cutoffs, with a porosity log); a figure the row could not
    // evaluate is null, reads n/a, and its reason goes to `note`
    zonesCsvRows() {
      const sums = this.hasCutoffs;
      const phi = this.hasSums;
      const gone = (r, key, on) => {
        if (!on || (key === "mean_pay" ? !r.curve : r.curve)) return "";
        return r.na[key] ? null : (r[key] === undefined ? "" : r[key]);
      };
      return this.zoneRows.map((r) => {
        const cells = {
          net: gone(r, "net", sums), ntg: gone(r, "ntg", sums),
          phih: gone(r, "phih", phi), hcph: gone(r, "hcph", phi),
          mean_pay: gone(r, "mean_pay", sums),
        };
        // the gross vertical thickness stands on every row, as the top and
        // base do; n/a with its reason when the zone has no vertical one.
        // The along-hole gross rides beside it in its own column.
        cells.gross = r.na.gross ? null : r.thickness_tvd;
        const why = [...new Set(Object.keys(cells).filter((k) => cells[k] === null).map((k) => r.na[k]))];
        const curve = (v) => (r.curve ? (v === undefined ? "" : v) : "");
        return [
          r.well, r.depthRef, r.zone, r.source || "",
          r.top, r.bottom, r.top_tvd, r.bottom_tvd,
          r.thickness, cells.gross, cells.net, cells.ntg, cells.phih, cells.hcph,
          curve(r.curve), curve(r.unit), curve(r.n), curve(r.mean), cells.mean_pay,
          curve(r.p10), curve(r.p50), curve(r.p90), curve(r.min), curve(r.max),
          why.join("; "),
        ];
      });
    },
    zonesCsvText() {
      const { header } = csvMeta(this.data && this.data.csv, "zones.csv");
      return buildCsv(header, ZONES_CSV_COLUMNS, this.zonesCsvRows());
    },
    // a rule's threshold as the field wants it: a Number, or null while
    // the rule is being written
    ruleValue(r) {
      return r.value === "" || r.value === null || r.value === undefined
        || !Number.isFinite(Number(r.value)) ? null : Number(r.value);
    },
    // Why the named logs are not among a well's curves, from the host's
    // reason codes (`pay_na_why`, `phi_absent`…): the well logs them but
    // they are not ticked (channels are ticked per wellbore, so the next
    // step is named), or ticked with no readable sample, or not logged at
    // all. Any name without a code reads as not logged. `what` names what
    // the logs are to the report ("the porosity log"), when that matters.
    absentText(names, why, what) {
      const by = { unticked: [], unreadable: [], unlogged: [] };
      for (const n of names) (by[(why || {})[n]] || by.unlogged).push(n);
      const subject = (ns) => {
        const list = ns.length === 1 ? ns[0]
          : `${ns.slice(0, -1).join(", ")} and ${ns[ns.length - 1]}`;
        return what ? `${what}${ns.length === 1 ? "" : "s"} ${list}` : list;
      };
      const be = (ns) => (ns.length === 1 ? "is" : "are");
      const parts = [];
      if (by.unticked.length) {
        parts.push(`${subject(by.unticked)} ${be(by.unticked)} not ticked for this well`
                   + ` (tick ${by.unticked.length === 1 ? "it" : "them"} in the well tree)`);
      }
      if (by.unreadable.length) {
        parts.push(`${subject(by.unreadable)} ${be(by.unreadable)} ticked for this well`
                   + " but no sample could be read");
      }
      if (by.unlogged.length) {
        parts.push(`${subject(by.unlogged)} ${be(by.unlogged)} not logged on this well`);
      }
      return parts.join("; ");
    },
    // why no log of `noun` was read on a well: the well logs one the panel
    // does not carry (named, with why), or no curve's kind names it
    noKindWhy(noun, absent) {
      const names = Object.keys(absent || {});
      return names.length
        ? this.absentText(names, absent, `the ${noun} log`)
        : `no curve's property kind names a ${noun}`;
    },
    summationLine(sums) {
      const among = (picked, all) => (all.length > 1
        ? `${picked} (picked among ${all.join(", ")})` : picked);
      if (!sums.phi) {
        return `Φ·h and Φ(1−Sw)·h are not reported: ${this.noKindWhy("porosity", sums.phi_absent)}.`;
      }
      const phi = `Φ·h reads ${among(sums.phi, sums.phi_candidates || [])}`;
      const sw = sums.sw
        ? `Sw from ${among(sums.sw, sums.sw_candidates || [])}`
        : `Φ(1−Sw)·h is not reported: ${this.noKindWhy("water saturation", sums.sw_absent)}`;
      return `${phi} · ${sw}.`;
    },
    plain(r) {
      return { curve: r.curve, op: r.op, value: Number(r.value) };
    },
    addRule() {
      this.rules.push({ curve: this.curveNames[0] || "", op: ">=", value: null });
    },
    removeRule(i) {
      this.rules.splice(i, 1);
      this.emitRules();
    },
    // only the complete rules leave the widget; a rule being typed stays here
    emitRules() {
      this.$emit("cutoffs-change", this.rules.filter(complete).map(this.plain));
    },
  },
};
</script>

<style scoped>
.wlc-zones {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  font-size: 12px;
}
.wlc-zones-none {
  padding: 8px 10px;
}
.wlc-zones-head {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  padding: 2px 4px 4px;
  border-bottom: 1px solid #e2e2e2;
}
.wlc-zones-src {
  color: #777;
  font-size: 11px;
}
.wlc-cut {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-left: auto;
  font-size: 11px;
}
.wlc-cut-title {
  font-weight: 600;
  color: var(--fp-accent);
}
.wlc-cut-rule {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 1px 3px;
  border: 1px solid #d8d8d8;
  border-radius: 3px;
  background: #fff;
}
.wlc-cut-rule .fp-sel,
.wlc-cut-rule .fp-num {
  font-size: inherit;
}
.wlc-cut-legend {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: #555;
}
.wlc-pay-swatch {
  display: inline-block;
  width: 14px;
  height: 9px;
  background: rgba(126, 211, 33, 0.45);
  border: 1px solid rgba(0, 0, 0, 0.2);
}
.wlc-zones-scroll {
  flex: 1 1 auto;
  overflow: auto;
  min-height: 0;
}
.wlc-zones-table {
  border-collapse: collapse;
  width: 100%;
  font-variant-numeric: tabular-nums;
}
.wlc-zones-table th,
.wlc-zones-table td {
  padding: 2px 8px;
  white-space: nowrap;
  border-bottom: 1px solid #ececec;
  text-align: left;
}
.wlc-zones-table th {
  position: sticky;
  top: 0;
  background: #f0f0f0;
  font-weight: 600;
}
.wlc-zones-table .num {
  text-align: right;
}
.wlc-zones-gross td {
  color: #555;
  background: #f5f5f5;
}
.wlc-zones-table .wlc-na {
  color: #999;
  cursor: help;
}
.wlc-th-sub {
  margin-left: 4px;
  font-weight: normal;
  color: #777;
}
.wlc-zones-notes {
  flex: 0 0 auto;
  padding: 3px 4px;
  border-top: 1px solid #e2e2e2;
  color: #555;
  font-size: 11px;
}
.wlc-swatch {
  display: inline-block;
  width: 9px;
  height: 9px;
  margin-right: 5px;
  border: 1px solid rgba(0, 0, 0, 0.25);
  vertical-align: middle;
}
.wlc-unit {
  color: #888;
}
</style>
