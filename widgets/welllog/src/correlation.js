/* Well-log correlation panel — pure D3/SVG renderer.
 *
 * No framework: a single `render(container, data, options)` entry point, so the
 * standalone demo (demo.html) and the Trame Vue widget (which hands it a
 * container and the JSON payload) drive the same code.
 *
 * Depth is drawn at a CONSTANT pixel-per-unit scale (zoomable, and drivable by
 * the host through `options.zoom`), so the panel is as tall as the data and the
 * container scrolls through depth — the shallowest and deepest samples are
 * always reachable. Wells sit SIDE BY SIDE on ONE depth scale (the same depth
 * at the same height in every well), or flattened on a marker; inside a well
 * there is one track per property KIND, with the logs of that kind overlaid on
 * the track's one value scale. The headers are sticky and stay pinned while
 * the depth content scrolls under them.
 *
 * Data shape:
 *   {
 *     wells: [
 *       { name, color, depthRef,
 *         depthUnit, tvdUnit,                     // "" when no CRS states one
 *         mdDatum: { ref, tvd } | null,           // the MD zero: its MdReference
 *                                                 // ("kelly bushing"...), its TVD
 *         mdTvd: [ [md, tvd], ... ],              // drawn in MD: its TVD
 *         depth: { min, max },                    // of the samples and tops; the
 *                                                 // tracks start at the MD datum
 *         tracks: [ { kind, unit, logScale,
 *                     range:[min,max],  // ONE value scale for every curve of
 *                                       // the track: a synthetic log is read
 *                                       // against the measured one
 *                     curves: [ { name, color, unit, range:[min,max], missing,
 *                                 synthetic,        // sampled from a grid: dashed
 *                                 samples:[[value|null, depth, tvd?], ...] } ] } ],
 *         tops:   [ { name, depth, tvd } ],       // depth = the DRAWN axis
 *         // depthRef names the axis `depth` is expressed in; integrationRef
 *         // ("TVD") the one every thickness is summed on.
 *         absent: { channel title: { kind, why } }, // logged, not in the panel
 *         pay:    [ [top, bottom], ... ],          // under the host's cutoffs,
 *                                                  // on the DRAWN axis
 *         pay_tvd: [ [top, bottom], ... ],         // the same pay, vertical
 *         pay_na: [ curve name, ... ],             // rule logs this well lacks
 *         pay_na_why: { curve name: why },         // unticked / unreadable / unlogged
 *         summation: { phi, phi_candidates, phi_absent,
 *                      sw, sw_candidates, sw_absent },
 *         zones:  [ { name, color, top, bottom, thickness, source,
 *                     top_tvd, bottom_tvd, thickness_tvd, tvd_na,
 *                     net, ntg, phih, hcph, pay_na,  // only with cutoffs
 *                     curves: [ { name, unit, n, mean, min, max,
 *                                 p10, p50, p90, n_pay, mean_pay } ] } ],
 *         strati: { time|group|rock: [ { name, kind, parent, color,
 *                                         top, bottom, top_tvd, bottom_tvd } ] } },
 *       ...
 *     ],
 *     markers: [ { name, color } ],              // correlation tops, by name
 *     flattenOn: <marker name> | null            // align all wells on this top
 *   }
 *
 * Options: `align` ("TVD", the default, or "MD": the depth the wells are laid
 * out on — a well drawn in MD is laid out on the TVD of its samples, tops and
 * bands, its MD read beside; a well with no TVD stays on its MD and its
 * header says so), `zoom` (the host's vertical exaggeration, a whole number
 * as a 3D view's Z: 1 fits the depth span in the panel's height),
 * `onZoom(factor)`, `onFlatten(name|null)`, `markersOff` (the names of the
 * markers dimmed) and `onMarkersOff(names)` (a click on a name dims it or
 * shows it again), `onDrawn()` (after each draw: a host's scrollbars),
 * `layout` (overrides of LAYOUT) and `d3`. The wheel zooms in depth, a
 * right-drag frames a depth window; the left button is the host's.
 * `hover(container, clientX, clientY)` reads what lies under the pointer off
 * the last drawing and marks its depth on the depth columns; the host shows
 * the readout and says when not to (a drag, an open menu).
 *
 * d3 (v7) is taken from `options.d3` when provided (the Vue widget imports it
 * as an npm dependency), else from the global `d3` (the standalone demo loads
 * it from a CDN).
 *
 * An ES module (it imports the shared number format): the demo loads it with
 * `type="module"`, which a browser only does over http, not from file://.
 */
import { fmt, fmtFixed } from "../../_shared/numfmt.js";

(function (global) {
  let _idSeq = 0;

  const STRATI_LANES = ["time", "group", "rock"];

  // The vertical exaggeration is a whole number, as a 3D view's Z: 1 shows
  // the whole depth span in the panel's height, n draws it n times taller.
  // The upper bound is high enough that markers a metre apart separate and
  // their names stop piling up.
  const ZOOM_MAX = 100;
  const zoomOf = (z) => Math.max(1, Math.min(ZOOM_MAX, Math.round(z)));
  const LABEL_GAP = 13;       // px between two side labels before they collide
  const LABEL_MAX_SHIFT = 14; // px a label may be nudged before it is dropped
  const OFF_OPACITY = 0.25;   // a dimmed marker: its lines and its name
  const LABEL_IN = 18;        // px between a well and the names right of it: the depth scrollbar
  const RIGHT_PAD = 20;       // px right of the last well when no name stands there
  const NAMES_PAD = 14;       // px about the names left of the wells: 6 before, 8 after

  const LAYOUT = {
    trackW: 132,          // plot area of ONE track
    trackGapIn: 2,        // gap between two tracks of the SAME well
    trackGap: 60,         // gap between wells: room for the tilted tie lines
                          // (marker names live in the side gutters)
    stratiLaneW: 13,      // ONE lane of the stratigraphic band
    depthAxisW: 46,       // depth label gutter, once per well
    tvdAxisW: 44,         // the depth read beside it, when the well has two
    headerH: 40,          // coloured well-name bar (sticky): the name, the wellhead's place under it
    kindH: 15,            // the track's kind + unit line
    curveRowH: 12,        // one curve's colour / name / scale row
    padTop: 6,            // small pad above the plot content (below the header)
    marginBottom: 28,
    sideLabelW: 150,      // the marker name columns, at most
    pxPerUnit: 0.6,       // px per depth unit when there is no span to fit
  };

  // A span of values, bracketed: neither a minus sign nor a decimal point
  // reads as its delimiter
  const spanText = (a, b, f = fmt) => "[" + f(a) + " .. " + f(b) + "]";

  // The stratigraphic column is the SAME column whatever well it is read
  // against, so the panel draws it once, in its own left gutter, instead of
  // repeating it against every well and running it under the marker labels.
  // Each well has its own depth axis, so the column is shown on the depths of
  // a REFERENCE well: the first one that has any stratigraphy at all.
  function stratiPlan(wells, L) {
    const index = wells.findIndex((w) => STRATI_LANES.some(
      (k) => (((w.strati || {})[k]) || []).length > 0));
    const ref = index >= 0 ? wells[index] : null;
    const laneKeys = ref ? STRATI_LANES.filter(
      (k) => (((ref.strati || {})[k]) || []).length > 0) : [];
    return { index, ref, laneKeys, w: laneKeys.length * L.stratiLaneW };
  }

  // MD -> TVD along a well, linear between its known pairs, nothing outside them
  function tvdLookup(pairs) {
    return (md) => {
      if (!(md >= pairs[0][0]) || !(md <= pairs[pairs.length - 1][0])) return null;
      let lo = 0;
      let hi = pairs.length - 1;
      while (hi - lo > 1) {
        const mid = (lo + hi) >> 1;
        if (pairs[mid][0] <= md) lo = mid; else hi = mid;
      }
      const a = pairs[lo];
      const b = pairs[hi];
      return b[0] === a[0] ? a[1] : a[1] + ((md - a[0]) * (b[1] - a[1])) / (b[0] - a[0]);
    };
  }

  // TVD -> MD along a well: on the first stretch of hole, by increasing MD,
  // that crosses that vertical depth (a hole that comes back up crosses it twice)
  function mdLookup(pairs) {
    return (tvd) => {
      if (tvd == null || Number.isNaN(tvd)) return null;
      for (let i = 0; i + 1 < pairs.length; i++) {
        const a = pairs[i];
        const b = pairs[i + 1];
        if (tvd < Math.min(a[1], b[1]) || tvd > Math.max(a[1], b[1])) continue;
        return b[1] === a[1] ? a[0] : a[0] + ((tvd - a[1]) * (b[0] - a[0])) / (b[1] - a[1]);
      }
      return null;
    };
  }

  const span2 = (a, b) => [Math.min(a, b), Math.max(a, b)];

  // A well as the panel lays it out: on its drawn axis, or, aligned on TVD, a
  // well drawn in MD with every sample, top, pay band and stratigraphic band
  // at its true vertical depth. `axis` names the depth it is laid out on,
  // `other` the one read beside it (a column, the readout), `noTvd` a well
  // asked in TVD that has none and stays on its MD. Kept per well object and
  // alignment: a new payload brings new ones.
  const _plotted = new WeakMap();
  function plotted(w, align) {
    const hit = _plotted.get(w);
    if (hit && hit.align === align) return hit.well;
    const well = layOut(w, align);
    _plotted.set(w, { align, well });
    return well;
  }

  // The tracks start at the MD datum, where every measured depth counts
  // from: its zero on MD, its vertical depth on TVD when the file states it
  function fromDatum(w, ref, depth) {
    const top = ref === "MD" ? 0 : (ref === "TVD" && w.mdDatum ? w.mdDatum.tvd : null);
    return top != null && Number.isFinite(top) && top < depth.min
      ? { min: top, max: depth.max } : depth;
  }

  function layOut(w, align) {
    const ref = w.depthRef || "DEPTH";
    const pairs = ref === "MD" && Array.isArray(w.mdTvd) && w.mdTvd.length > 1 ? w.mdTvd : null;
    const asDrawn = (noTvd) => Object.assign({}, w, {
      depth: fromDatum(w, ref, w.depth),
      axis: { ref, unit: w.depthUnit || "" },
      other: pairs ? { ref: "TVD", unit: w.tvdUnit || "", at: tvdLookup(pairs) } : null,
      noTvd,
    });
    if (align !== "TVD" || ref !== "MD") return asDrawn(false);
    if (!pairs) return asDrawn(true);
    const toTvd = tvdLookup(pairs);
    const at = (d, t) => (t != null && Number.isFinite(t) ? t : (d == null ? null : toTvd(d)));
    let lo = Infinity;
    let hi = -Infinity;
    const seen = (v) => {
      if (v != null) {
        if (v < lo) lo = v;
        if (v > hi) hi = v;
      }
      return v;
    };
    // each sample keeps its own measured depth third: the readout says it,
    // never one read back through the MD-TVD table
    const tracks = (w.tracks || []).map((t) => Object.assign({}, t, {
      curves: (t.curves || []).map((c) => Object.assign({}, c, {
        samples: (c.samples || []).map((s) => [s[0], seen(at(s[1], s[2])), s[1]])
          .filter((s) => s[1] != null),
      })),
    }));
    const tops = (w.tops || [])
      .map((tp) => Object.assign({}, tp, { md: tp.depth, depth: seen(at(tp.depth, tp.tvd)) }))
      .filter((tp) => tp.depth != null);
    if (!(hi >= lo)) return asDrawn(true);
    const pay = (Array.isArray(w.pay_tvd) ? w.pay_tvd : (w.pay || []).map(([a, b]) => [toTvd(a), toTvd(b)]))
      .filter(([a, b]) => a != null && b != null).map(([a, b]) => span2(a, b));
    const strati = {};
    Object.keys(w.strati || {}).forEach((k) => {
      strati[k] = (w.strati[k] || []).map((s) => {
        const a = at(s.top, s.top_tvd);
        const b = at(s.bottom, s.bottom_tvd);
        return a == null || b == null ? null : Object.assign({}, s, { top: Math.min(a, b), bottom: Math.max(a, b) });
      }).filter(Boolean);
    });
    return Object.assign({}, w, {
      tracks, tops, pay, strati,
      depth: fromDatum(w, "TVD", { min: lo, max: hi > lo ? hi : lo + 1 }),
      axis: { ref: "TVD", unit: w.tvdUnit || "" },
      other: { ref: "MD", unit: w.depthUnit || "", at: mdLookup(pairs) },
      noTvd: false,
    });
  }

  // Wells SIDE BY SIDE, each with its own depth gutter and its own row of
  // tracks — the usual log-display layout, and the one the tie lines between
  // wells need. Inside a well, one track per property KIND, with the logs of
  // that kind overlaid: the two saturations together, the three impedances
  // together. `leftPad` is the width of the stratigraphic gutter, `namesW`
  // the one of the marker names left of the wells; the names also stand
  // right of the well `namesAfter`, the last one that has some.
  function layout(wells, L, leftPad, namesW, namesAfter) {
    const geom = [];
    let x = (leftPad || 0) + namesW;
    wells.forEach((w, i) => {
      const tracks = w.tracks || [];
      const n = Math.max(1, tracks.length);
      const width = n * L.trackW + (n - 1) * L.trackGapIn;
      const x0 = x;
      // the depth the well is laid out on first, the one read beside it next
      const sideW = w.other ? L.tvdAxisW : 0;
      const plotL = x0 + L.depthAxisW + sideW;
      // each depth axis a column of its own, set off like a track
      const column = (x, w) => ({ x, w: w - L.trackGapIn, right: x + w - L.trackGapIn });
      geom.push({
        x0, plotL, width, plotR: plotL + width,
        axis: column(x0, L.depthAxisW),
        side: sideW ? column(x0 + L.depthAxisW, sideW) : null,
        track: (k) => plotL + k * (L.trackW + L.trackGapIn),
      });
      x = plotL + width + (i === namesAfter ? LABEL_IN + L.sideLabelW : L.trackGap);
    });
    return geom;
  }

  // How tall the sticky header must be: the track with the most curves of
  // any well decides, every curve having its row
  function headerRows(wells) {
    let rows = 1;
    wells.forEach((w) => (w.tracks || []).forEach((t) => {
      rows = Math.max(rows, (t.curves || []).length);
    }));
    return rows;
  }

  // The track's value scale. Every curve of the track is drawn on it, so a
  // synthetic log sits on the very scale of the measured log it is compared
  // with. A payload without a track range falls back to the span of the
  // track's curves. A kind whose values span decades is unreadable on a
  // linear axis, so the payload may ask for a log scale (`logScale`); it falls
  // back to linear when the domain is not strictly positive.
  function trackScale(d3, track, x0, x1) {
    let r = track.range;
    if (!r) {
      const spans = (track.curves || []).map((c) => c.range).filter((q) => q && q.length === 2);
      r = spans.length
        ? [Math.min(...spans.map((q) => q[0])), Math.max(...spans.map((q) => q[1]))]
        : [0, 1];
    }
    if (track.logScale && r[0] > 0 && r[1] > 0) {
      return d3.scaleLog().domain(r).range([x0, x1]);
    }
    return d3.scaleLinear().domain(r).range([x0, x1]);
  }

  function fit(text, px) {
    // SVG has no ellipsis; ~5.6px per char at font-size 10 is close enough to
    // keep a name inside its column instead of bleeding over its neighbour.
    const max = Math.max(3, Math.floor(px / 5.6));
    text = String(text == null ? "" : text);
    return text.length <= max ? text : text.slice(0, max - 1) + "…";
  }

  // A depth column's ground: neither a curve track's white nor the panel's grey
  const DEPTH_FILL = "#f4f6f8";

  const DEPTH_WORDS = { MD: "Measured depth along the hole", TVD: "True vertical depth" };
  const inUnit = (u) => (u ? ", in " + u : "");

  // An MD datum (RESQML MdReference) as the trade abbreviates it
  const DATUM_SHORT = {
    "kelly bushing": "KB", "rotary bushing": "RB", "rotary table": "RT",
    "derrick floor": "DF", "ground level": "GL", "mean sea level": "MSL",
    "sea floor": "SF", "casing flange": "CF", "crown valve": "CV",
    "kickoff point": "KOP", "arbitrary point": "AP", "lowest astronomical tide": "LAT",
    "mean high water": "MHW", "mean higher high water": "MHHW",
    "mean low water": "MLW", "mean lower low water": "MLLW", "mean tide level": "MTL",
  };
  // `{short, words}` of a well's MD datum, null when the file does not say
  function datumOf(well) {
    const ref = well.mdDatum && well.mdDatum.ref;
    if (!ref) return null;
    const short = DATUM_SHORT[String(ref).toLowerCase()];
    return { short: "from " + (short || ref), words: "from the " + ref + (short ? " (" + short + ")" : "") };
  }

  // A depth column's header cell: its name and unit on one line, the unit
  // on the next when the line is wider than the column, then `note` (an MD
  // column's datum). The depth the well is laid out on (`main`) is bold and
  // underlined, the one read beside it plain. One tooltip for the cell.
  function depthHead(hsvg, col, top, bottom, name, unit, tip, main, note) {
    const cell = hsvg.append("g");
    cell.append("title").text(tip);
    cell.append("rect").attr("x", col.x).attr("y", top)
      .attr("width", col.w).attr("height", bottom - top)
      .attr("fill", DEPTH_FILL).attr("stroke", "#222");
    const cx = col.x + col.w / 2;
    const label = cell.append("text").attr("x", cx).attr("y", top + 11)
      .attr("text-anchor", "middle").attr("font-size", 10)
      .attr("font-weight", main ? 700 : 400).attr("text-decoration", main ? "underline" : null)
      .attr("fill", main ? "#111" : "#555").text(name + (unit ? " (" + unit + ")" : ""));
    const node = label.node();
    let below = note || "";
    if (unit && node.getComputedTextLength && node.getComputedTextLength() > col.w - 4) {
      label.text(name);
      below = "(" + unit + ")" + (note ? " " + note : "");
    }
    if (below) {
      cell.append("text").attr("x", cx).attr("y", top + 23)
        .attr("text-anchor", "middle").attr("font-size", 9).attr("fill", "#444")
        .text(fit(below, col.w - 2));
    }
  }

  // A marker's name as the side columns write it
  const nameText = (name, active, L) => fit((active ? "▸ " : "") + name, L.sideLabelW - 26);

  // The widest of `texts` written as a marker name (12 px, bold), measured
  // in the container; one not laid out yet is guessed from its length
  function namesWidth(container, texts) {
    const ns = "http://www.w3.org/2000/svg";
    const probe = document.createElementNS(ns, "svg");
    probe.setAttribute("style", "position:absolute;visibility:hidden;font-family:system-ui, sans-serif");
    const nodes = texts.map((s) => {
      const t = document.createElementNS(ns, "text");
      t.setAttribute("font-size", 12);
      t.setAttribute("font-weight", 800);
      t.textContent = s;
      probe.appendChild(t);
      return t;
    });
    container.appendChild(probe);
    const w = Math.max(...nodes.map((t, i) => t.getComputedTextLength() || texts[i].length * 7.5));
    probe.remove();
    return Math.ceil(w);
  }

  function topDepth(well, name) {
    const t = (well.tops || []).find((t) => t.name === name);
    return t ? t.depth : null;
  }

  // The depth span the panel would have to fit — mirrors both branches of the
  // scale block below so "fit" means the same thing flattened or not.
  function depthSpan(wells, flattenOn) {
    if (!wells.length) return 0;
    if (flattenOn) {
      let a = Infinity, b = -Infinity;
      wells.forEach((w) => {
        const m = topDepth(w, flattenOn);
        if (m == null) return;
        a = Math.min(a, w.depth.min - m);
        b = Math.max(b, w.depth.max - m);
      });
      if (isFinite(a)) return b - a;
    }
    let a = Infinity, b = -Infinity;
    wells.forEach((w) => {
      a = Math.min(a, w.depth.min);
      b = Math.max(b, w.depth.max);
    });
    return isFinite(a) ? b - a : 0;
  }

  // The ground the wells and the marker names stand on.
  const GROUND = "#deded6";

  // A colour written as text on `bg`: darkened, its hue kept, until it reads
  // (a contrast of 4.5:1); its key keeps the colour itself.
  function inkOn(col, bg) {
    const rgb = (c) => {
      const m = /^#([0-9a-f]{6})$/i.exec(String(c || "").trim());
      if (!m) return null;
      const n = parseInt(m[1], 16);
      return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
    };
    const lum = (c) => {
      const f = (v) => {
        const x = v / 255;
        return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4);
      };
      return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]);
    };
    let c = rgb(col);
    const b = rgb(bg);
    if (!c || !b) return col;
    const lb = lum(b);
    const contrast = (x) => {
      const l = lum(x);
      return (Math.max(l, lb) + 0.05) / (Math.min(l, lb) + 0.05);
    };
    for (let i = 0; i < 16 && contrast(c) < 4.5; i++) {
      c = c.map((v) => Math.round(v * 0.85));
    }
    return "#" + c.map((v) => v.toString(16).padStart(2, "0")).join("");
  }

  function render(container, data, options) {
    options = options || {};
    const d3 = options.d3 || global.d3;
    // Per-container UI state that must survive re-renders: depth zoom, scroll
    // anchor, bound listeners, the dimmed markers.
    const state = container.__wlc || (container.__wlc = { zoom: 1 });
    const align = options.align === "MD" ? "MD" : "TVD";
    const wells = (data.wells || []).map((w) => plotted(w, align));
    // A host can DRIVE the depth scale (a slider next to the panel) instead of
    // leaving it to the Ctrl+wheel gesture; the wheel keeps working and reports
    // back through options.onZoom so the host's control stays in sync.
    // Only a CHANGED host value wins: the wheel re-renders with the same
    // options object, and re-applying its stale zoom would undo every scroll.
    const hostZoom = options.zoom != null && isFinite(options.zoom)
      && options.zoom !== state.hostZoom;
    if (hostZoom) {
      state.hostZoom = options.zoom;
      state.zoom = zoomOf(options.zoom > 0 ? options.zoom : 1);
      // a value the field cannot hold (a fraction, the old "fit" sentinel)
      // goes back whole, so the host's control shows the one in force
      if (state.zoom !== options.zoom && options.onZoom) options.onZoom(state.zoom);
    }
    // the host's dimmed markers, when it hands a new list; a click keeps
    // its own until then
    if (!state.off || options.markersOff !== state.hostOff) {
      state.hostOff = options.markersOff;
      state.off = new Set(options.markersOff || []);
    }
    const off = state.off;
    const L = Object.assign({}, LAYOUT, options.layout || {});
    const markers = data.markers || [];
    const markerColor = {};
    markers.forEach((m) => (markerColor[m.name] = m.color));
    const headTotal = L.headerH + L.kindH + headerRows(wells) * L.curveRowH + 4;
    // At 1 the depth span fills the height under the header, so a new
    // height (a card docked under the tracks, a view resized) draws the
    // same depth window to it, as a 3D view's scene is
    const span = depthSpan(wells, data.flattenOn);
    const room = (container.clientHeight || 0) - headTotal - L.padTop - L.marginBottom - 2;
    const pxPerUnit = (span > 0 ? Math.max(room, 60) / span : L.pxPerUnit) * state.zoom;
    // Scroll must survive the rebuild below, and `scrollTop` alone will not do
    // it. It is a PIXEL offset: at 3x the same number is a third of the depth,
    // so restoring it verbatim throws the reader up the well on every zoom
    // step. Convert to a depth anchor and put the same DEPTH back afterwards.
    const prevScroll = container.scrollTop;
    const prevLeft = container.scrollLeft;
    const viewH = container.clientHeight || 0;
    const anchor = state.lastPxPerUnit
      ? (prevScroll + viewH / 2 - (state.lastHeadTotal || 0) - L.padTop)
        / state.lastPxPerUnit
      : null;

    state.lastData = data;
    state.lastOptions = options;
    // Drag a band to zoom into exactly that depth window — the way to pull
    // apart a pile of markers a metre apart. Pixel arithmetic only: the band's
    // height against the viewport IS the zoom ratio, so this behaves the same
    // flattened or not, and with every well on its own depth axis. The
    // listeners are bound once per container and read the latest data and
    // options from `state`.
    if (!state.boxZoomBound) {
      state.boxZoomBound = true;
      if (!container.style.position) container.style.position = "relative";
      let y0 = null, box = null, dragged = false;
      const contentY = (ev) => ev.clientY
        - container.getBoundingClientRect().top + container.scrollTop;
      // The right button: the left one moves the tracks (the host's hand).
      // The box only arms past a 6 px threshold; the panel has no menu of
      // its own, so the browser's is kept off it.
      container.addEventListener("contextmenu", (ev) => ev.preventDefault());
      container.addEventListener("mousedown", (ev) => {
        if (ev.button !== 2) return;
        y0 = contentY(ev);
        dragged = false;
      });
      container.addEventListener("mousemove", (ev) => {
        if (y0 == null) return;
        const y1 = contentY(ev);
        if (!dragged && Math.abs(y1 - y0) < 6) return;   // still a click
        if (!dragged) {
          dragged = true;
          box = document.createElement("div");
          box.style.cssText = "position:absolute;left:0;right:0;z-index:9;"
            + "pointer-events:none;background:rgba(0,67,109,0.16);"
            + "border-top:1px solid #00436d;border-bottom:1px solid #00436d;";
          container.appendChild(box);
        }
        ev.preventDefault();
        box.style.top = Math.min(y0, y1) + "px";
        box.style.height = Math.abs(y1 - y0) + "px";
      });
      window.addEventListener("mouseup", (ev) => {
        if (y0 == null) return;
        const y1 = contentY(ev);
        if (box) { box.remove(); box = null; }
        const top = Math.min(y0, y1);
        const h = Math.abs(y1 - y0);
        const wasDrag = dragged;
        y0 = null;
        dragged = false;
        if (!wasDrag) return;                   // a click: leave it alone
        const head = state.lastHeadTotal || 0;
        const avail = (container.clientHeight || 0) - head;
        if (h < 8 || avail < 40) return;        // a click, not a band
        const next = zoomOf(state.zoom * (avail / h));
        const applied = next / state.zoom;
        // hostZoom is left as it was: the redraw below still carries the
        // options of the last one, whose stale zoom would otherwise win
        state.zoom = next;
        // land the band's top just under the sticky header: its place in
        // the plot (below the header and the pad) scales with the zoom
        const pad = (state.lastOptions && state.lastOptions.layout
          && state.lastOptions.layout.padTop) || LAYOUT.padTop;
        state.pendingScroll = pad + Math.max(0, top - head - pad) * applied;
        const opts = state.lastOptions || {};
        if (opts.onZoom) opts.onZoom(state.zoom);
        render(container, state.lastData, opts);
      });
    }

    // Click a marker (its correlation line or in-track tick) to flatten the
    // panel on it; click the active one again to release.
    function flattenOnMarker(name) {
      data.flattenOn = data.flattenOn === name ? null : name;
      if (options.onFlatten) options.onFlatten(data.flattenOn);
      render(container, data, options);
    }
    // Click a marker's name to dim it, again to show it
    function toggleMarker(name) {
      if (off.has(name)) off.delete(name); else off.add(name);
      if (options.onMarkersOff) options.onMarkersOff([...off]);
      render(container, data, options);
    }

    // ---- depth -> y scales at a constant px/unit; content height is dynamic ----
    const pt = L.padTop;
    let contentHeight = 0;
    let scales;
    const wTops = [];
    const wBots = [];
    if (data.flattenOn) {
      // Align every well's flatten top at the same y. Relative depths are taken
      // about each well's own marker; the global extent sizes the band so no
      // well's shallowest/deepest sample is ever cut.
      const md = (w) => topDepth(w, data.flattenOn);
      let relTop = Infinity, relBot = -Infinity;
      wells.forEach((w) => {
        const m = md(w);
        if (m == null) return;
        relTop = Math.min(relTop, w.depth.min - m);
        relBot = Math.max(relBot, w.depth.max - m);
      });
      if (!isFinite(relTop)) { relTop = -650; relBot = 650; }
      contentHeight = (relBot - relTop) * pxPerUnit;
      scales = wells.map((w, i) => {
        const m = md(w);
        if (m == null) return null;
        wTops[i] = pt;
        wBots[i] = pt + contentHeight;
        return d3.scaleLinear().domain([m + relTop, m + relBot]).range([pt, pt + contentHeight]);
      });
    } else {
      // Every well on ONE depth scale: the same depth at the same height in
      // every well, which is what makes the tilt of a tie line the dip. Each
      // well's tracks span its own depths.
      let a = Infinity, b = -Infinity;
      wells.forEach((w) => {
        a = Math.min(a, w.depth.min);
        b = Math.max(b, w.depth.max);
      });
      if (!isFinite(a)) { a = 0; b = 1; }
      contentHeight = (b - a) * pxPerUnit;
      const y = d3.scaleLinear().domain([a, b]).range([pt, pt + contentHeight]);
      scales = wells.map((w, i) => {
        wTops[i] = y(w.depth.min);
        wBots[i] = y(w.depth.max);
        return y;
      });
    }
    const contentBot = pt + contentHeight;
    const SP = stratiPlan(wells, L);
    // the marker names stand right of the last well that has a marker drawn
    let namesAfter = -1;
    wells.forEach((w, i) => {
      if (scales[i] && (w.tops || []).length) namesAfter = i;
    });
    // the names left of the wells: a gutter as wide as the longest of them
    const leftNames = markers
      .filter((m) => wells.some((w, i) => scales[i] && topDepth(w, m.name) != null))
      .map((m) => nameText(m.name, data.flattenOn === m.name, L));
    const namesW = Math.min(L.sideLabelW,
      (leftNames.length ? namesWidth(container, leftNames) : 0) + NAMES_PAD);
    const geom = layout(wells, L, SP.w, namesW, namesAfter);
    const lastG = geom[geom.length - 1];
    const width = (lastG ? lastG.plotR : SP.w + namesW)
      + (namesAfter >= 0 && namesAfter === wells.length - 1 ? LABEL_IN + L.sideLabelW : RIGHT_PAD);
    const plotH = contentBot + L.marginBottom;

    // ---- the container is the scroll parent ----
    const root = d3.select(container);
    root.selectAll("*").remove();
    container.style.overflow = "auto";
    container.style.position = "relative";
    container.style.background = GROUND;

    // ---- sticky header: coloured well-name bars (stay pinned while scrolling) ----
    const header = root.append("div")
      .style("position", "sticky").style("top", "0px").style("z-index", "2")
      // sized to the CONTENT, not the scrollport: a block box would stop at the
      // viewport edge and the plot would scroll through the header's gutters
      // as soon as the track is wider than the panel.
      .style("width", width + "px")
      .style("background", GROUND);
    const hsvg = header.append("svg").attr("width", width).attr("height", headTotal)
      .style("display", "block").style("font-family", "system-ui, sans-serif");
    wells.forEach((well, i) => {
      const G = geom[i];
      const tracks = well.tracks || [];

      // the well's own coloured name bar, spanning its gutter + tracks
      hsvg.append("rect").attr("x", G.x0).attr("y", 0)
        .attr("width", G.plotR - G.x0).attr("height", L.headerH)
        .attr("fill", well.color || "#ccc").attr("stroke", "#222");
      const placed = Array.isArray(well.head) && well.head.every((v) => v != null && isFinite(v));
      hsvg.append("text").attr("x", G.plotL + G.width / 2).attr("y", placed ? 14 : L.headerH / 2)
        .attr("text-anchor", "middle").attr("dominant-baseline", "central")
        .attr("font-weight", 700).attr("font-size", 15).text(well.name);
      // the wellhead's easting and northing, small, on a line of their own under the name
      if (placed) {
        const u = well.xyUnit ? " " + well.xyUnit : "";
        const at = hsvg.append("g");
        at.append("title").text("The wellhead: its easting (E) and northing (N)" + (u ? ", in" + u : ""));
        at.append("text").attr("x", G.plotL + G.width / 2).attr("y", L.headerH - 9)
          .attr("text-anchor", "middle").attr("dominant-baseline", "central")
          .attr("font-size", 9).attr("fill", "#222")
          .text("E " + Math.round(well.head[0]) + u + "  N " + Math.round(well.head[1]) + u);
      }
      // laid out on TVD, this well has none: it stays on its MD, and says so
      if (well.noTvd) {
        const note = hsvg.append("g");
        note.append("title").text("No true vertical depth on this well: drawn on its measured depth");
        note.append("text").attr("x", (G.x0 + G.plotL) / 2).attr("y", L.headerH / 2)
          .attr("text-anchor", "middle").attr("dominant-baseline", "central")
          .attr("font-size", 9).attr("font-weight", 600).attr("fill", "#222")
          .text("no TVD");
      }
      // the depth columns' own header cells, level with the tracks' ones;
      // the MD one says where it counts from
      const datum = datumOf(well);
      const mdNote = (ref) => (ref === "MD" && datum ? datum.short : "");
      const mdFrom = (ref) => (ref === "MD" && datum ? ", " + datum.words : "");
      depthHead(hsvg, G.axis, L.headerH, headTotal, well.axis.ref, well.axis.unit,
        (DEPTH_WORDS[well.axis.ref] || well.axis.ref) + inUnit(well.axis.unit)
          + mdFrom(well.axis.ref) + ": the depth the well is laid out on",
        true, mdNote(well.axis.ref));
      if (G.side) {
        depthHead(hsvg, G.side, L.headerH, headTotal, well.other.ref, well.other.unit,
          (well.other.ref === "TVD" ? "True vertical depth, beside each measured depth"
            : "Measured depth, beside each true vertical depth") + inUnit(well.other.unit)
            + mdFrom(well.other.ref),
          false, mdNote(well.other.ref));
      }

      // one header cell per track: its KIND and unit, then a row per curve
      // carrying that curve's colour, name and the scale it is drawn against.
      // This is the legend AND the scale key, the way a log header works.
      tracks.forEach((t, k) => {
        const tx = G.track(k);
        const top = L.headerH;
        const kindLabel = t.kind + (t.unit ? "  (" + t.unit + ")" : "")
          + (t.logScale ? "  log" : "");
        // the scale every curve of the track is drawn on, at its two ends
        const tr = trackScale(d3, t, 0, 1).domain();
        // ONE tooltip for the whole cell, wherever the pointer is in it: the
        // complete header, names cut to the track's width included
        const cell = hsvg.append("g");
        cell.append("title").text([kindLabel, "scale " + spanText(tr[0], tr[1])]
          .concat((t.curves || []).map((c) => {
            const r = c.range || [0, 1];
            return c.name + (c.unit ? " (" + c.unit + ")" : "") + "   " + spanText(r[0], r[1]);
          })).join("\n"));
        cell.append("rect").attr("x", tx).attr("y", top)
          .attr("width", L.trackW).attr("height", headTotal - top)
          .attr("fill", "#fff").attr("stroke", "#222");
        cell.append("text").attr("x", tx + L.trackW / 2).attr("y", top + 11)
          .attr("text-anchor", "middle").attr("font-size", 10)
          .attr("font-weight", 700).attr("fill", "#111")
          .text(fit(kindLabel, L.trackW - 6));
        cell.append("text").attr("x", tx + 3).attr("y", top + L.kindH - 1)
          .attr("font-size", 7).attr("fill", "#999").text(fmt(tr[0]));
        cell.append("text").attr("x", tx + L.trackW - 3).attr("y", top + L.kindH - 1)
          .attr("text-anchor", "end").attr("font-size", 7).attr("fill", "#999").text(fmt(tr[1]));

        (t.curves || []).forEach((c, j) => {
          const y = top + L.kindH + j * L.curveRowH + 9;
          const col = c.color || "#1565c0";
          cell.append("line").attr("x1", tx + 3).attr("x2", tx + 13)
            .attr("y1", y - 3).attr("y2", y - 3)
            .attr("stroke", col).attr("stroke-width", 2.5)
            .attr("opacity", c.missing ? 0.25 : 1);
          const r = c.range || [0, 1];
          const values = spanText(r[0], r[1]);
          // name on the left, the span of ITS values right-aligned beside it
          // (drawn on the track's scale, said in the header line above);
          // ~4.4 px a character of the span
          cell.append("text").attr("x", tx + 17).attr("y", y)
            .attr("font-size", 9)
            .attr("fill", c.missing ? "#aaa" : "#222")
            .text(fit(c.name, L.trackW - 24 - values.length * 4.4));
          cell.append("text").attr("x", tx + L.trackW - 3).attr("y", y)
            .attr("text-anchor", "end").attr("font-size", 8)
            .attr("fill", c.missing ? "#bbb" : "#777")
            .text(values);
        });
      });
    });

    // ---- scrollable plot svg ----
    const svg = root.append("svg").attr("width", width).attr("height", plotH)
      .style("display", "block").style("font-family", "system-ui, sans-serif");

    // The wheel zooms in depth, the depth under the pointer staying under
    // it; with Shift it is the browser's own, sideways. A notch is about
    // 15 %, and at least one whole step.
    svg.node().addEventListener("wheel", (event) => {
      if (event.shiftKey) return;
      event.preventDefault();
      const z = state.zoom;
      const next = zoomOf(event.deltaY < 0 ? Math.max(z + 1, z * 1.15) : Math.min(z - 1, z / 1.15));
      if (next === state.zoom) return;
      const yIn = event.clientY - container.getBoundingClientRect().top;
      const plotY = yIn + container.scrollTop - headTotal - pt;
      state.pendingScroll = Math.max(0, headTotal + pt + plotY * (next / state.zoom) - yIn);
      state.zoom = next;
      if (options.onZoom) options.onZoom(state.zoom);
      render(container, data, options);
    }, { passive: false });

    // Clip curves, pay bands and correlation lines to the plot band, so nothing
    // drawn past a well's depth range spills over the margins.
    const clipId = (state.uid || (state.uid = "wlc" + ++_idSeq)) + "-band";
    svg.append("defs").append("clipPath").attr("id", clipId)
      .append("rect").attr("x", 0).attr("y", pt).attr("width", width).attr("height", contentHeight);
    const clip = "url(#" + clipId + ")";

    // A marker's element: lit by a hover of its name or line, at `base`
    // opacity at rest, a quarter of it while the reader has it dimmed
    const tag = (sel, name, base) => {
      const rest = off.has(name) ? base * OFF_OPACITY : base;
      return sel.attr("data-m", name).attr("data-o", rest).attr("data-l", base)
        .attr("opacity", rest);
    };

    // ---- per well: depth gutter, then one track per kind ----
    wells.forEach((well, i) => {
      const y = scales[i];
      if (y == null) return;
      const G = geom[i];
      const tracks = well.tracks || [];
      const wTop = wTops[i];
      const wBot = wBots[i];
      const g = svg.append("g");
      const nticks = Math.max(2, Math.round((wBot - wTop) / 60));
      const dA = y.invert(wTop);
      const dB = y.invert(wBot);
      const ticks = d3.ticks(Math.min(dA, dB), Math.max(dA, dB), nticks);

      // the depth columns, once per well, left of its first track: no grid,
      // the labels inside
      [G.axis, G.side].forEach((col) => {
        if (!col) return;
        g.append("rect").attr("x", col.x).attr("y", wTop)
          .attr("width", col.w).attr("height", wBot - wTop)
          .attr("fill", DEPTH_FILL).attr("stroke", "#222");
      });
      const axis = d3.axisLeft(y).tickValues(ticks).tickSize(4)
        .tickFormat(d3.format("d"));
      const ag = g.append("g")
        .attr("transform", `translate(${G.axis.right},0)`).call(axis);
      ag.select(".domain").remove();
      ag.selectAll("text").attr("x", -6).attr("font-size", 10);
      // the other depth at the heights of the axis's ticks
      if (G.side) {
        ticks.forEach((d) => {
          const v = well.other.at(d);
          if (v == null) return;
          g.append("text").attr("x", G.side.right - 4).attr("y", y(d))
            .attr("text-anchor", "end").attr("dominant-baseline", "central")
            .attr("font-size", 10).attr("fill", "#666").text(d3.format("d")(v));
        });
      }

      tracks.forEach((t, k) => {
        const tx = G.track(k);
        const tR = tx + L.trackW;
        g.append("rect").attr("x", tx).attr("y", wTop)
          .attr("width", L.trackW).attr("height", wBot - wTop)
          .attr("fill", "#fff").attr("stroke", "#222");

        // horizontal depth grid + the vertical decade/quarter guides
        ticks.forEach((d) => {
          const yy = y(d);
          if (yy < wTop || yy > wBot) return;
          g.append("line").attr("x1", tx).attr("x2", tR)
            .attr("y1", yy).attr("y2", yy)
            .attr("stroke", "#bbb").attr("stroke-width", 0.5);
        });
        const guides = t.logScale
          ? trackScale(d3, t, tx + 3, tR - 3).ticks(4)
              .map((v) => trackScale(d3, t, tx + 3, tR - 3)(v))
          : [1, 2, 3].map((c) => tx + (L.trackW * c) / 4);
        guides.forEach((xx) => {
          if (xx <= tx || xx >= tR) return;
          g.append("line").attr("x1", xx).attr("x2", xx)
            .attr("y1", wTop).attr("y2", wBot)
            .attr("stroke", "#e4e4e4").attr("stroke-width", 0.5);
        });

        // the pay flag under the host's cutoffs: a band behind the curves,
        // in every track, so "where is the pay" is read on the logs themselves
        (well.pay || []).forEach(([a, b]) => {
          const y0 = Math.max(wTop, Math.min(y(a), y(b)));
          const y1 = Math.min(wBot, Math.max(y(a), y(b)));
          if (y1 <= y0) return;
          g.append("rect").attr("x", tx + 1).attr("y", y0)
            .attr("width", L.trackW - 2).attr("height", y1 - y0)
            .attr("fill", "#7ed321").attr("fill-opacity", 0.28)
            .attr("clip-path", clip);
        });

        // every log of this kind, overlaid on the track's ONE value scale: a
        // synthetic log and the measured one it stands beside are read
        // against the same axis, which is what puts them in the same track
        const xs = trackScale(d3, t, tx + 3, tR - 3);
        (t.curves || []).forEach((curve) => {
          if (curve.missing || !curve.samples || !curve.samples.length) return;
          const line = d3.line()
            .defined((s) => s[0] != null && !Number.isNaN(s[0])
                            && (!t.logScale || s[0] > 0))
            .x((s) => xs(s[0])).y((s) => y(s[1]));
          g.append("path").attr("d", line(curve.samples))
            .attr("fill", "none")
            .attr("stroke", curve.color || "#1565c0").attr("stroke-width", 1)
            .attr("stroke-dasharray", curve.synthetic ? "5 3" : null)
            .attr("clip-path", clip);
          litMarks(g, well, curve, options.lit, xs, y, tx, tR, clip);
        });
      });

      // tops as a tick across this well's tracks — clickable to flatten
      (well.tops || []).forEach((tp) => {
        const yy = y(tp.depth);
        if (yy < wTop || yy > wBot) return;
        const w0 = data.flattenOn === tp.name ? 3 : 1.5;
        const tick = tag(g.append("line").attr("x1", G.plotL).attr("x2", G.plotR)
          .attr("y1", yy).attr("y2", yy)
          .attr("stroke", markerColor[tp.name] || "#444")
          .attr("stroke-width", w0), tp.name, 1)
          .attr("data-w", w0)
          .style("cursor", "pointer");
        // the pick's depth on both axes: its own other depth when it has one
        const second = well.other ? (well.other.ref === "TVD" ? tp.tvd : tp.md) : null;
        const alt = second != null ? second : (well.other ? well.other.at(tp.depth) : null);
        tick.append("title").text(tp.name + "\n" + well.axis.ref + " " + fmtFixed(tp.depth, 2)
          + (well.other ? "\n" + well.other.ref + " " + fmtFixed(alt, 2) : ""));
        tick
          .on("mouseenter", () => setHover(tp.name))
          .on("mouseleave", () => setHover(null))
          .on("click", () => flattenOnMarker(tp.name));
      });
    });

    // ---- correlation lines between adjacent wells + side labels ----
    // A top ties the right edge of one well to the left edge of the next: the
    // tilt IS the structural dip, which is what the panel exists to show.
    // Click one to flatten every well on it.
    // Marker names sit in the side gutters, away from their lines, to stay
    // legible. Two things tie a name to its line: the COLOUR, identical for
    // one marker across every well, and hover — hovering a name (or a line)
    // lights that marker everywhere and fades the rest. No permanent clutter,
    // and the answer to "where is it" is one gesture away.
    function setHover(name) {
      svg.selectAll("[data-m]").each(function () {
        const mine = this.getAttribute("data-m");
        this.setAttribute("opacity", !name ? this.getAttribute("data-o")
          : mine === name ? this.getAttribute("data-l") : 0.08);
        const w0 = this.getAttribute("data-w");
        if (w0) {
          this.setAttribute("stroke-width",
            name && mine === name ? String(parseFloat(w0) * 2.4) : w0);
        }
      });
    }

    const leftLabels = [], rightLabels = [];
    const labelColL = SP.w + namesW - 8;            // right edge of the left gutter
    // left edge of the names right of the wells
    const labelColR = namesAfter >= 0 ? geom[namesAfter].plotR + LABEL_IN : null;
    markers.forEach((m) => {
      const col = m.color || "#444";
      const active = data.flattenOn === m.name;
      const lw = active ? 3.5 : 2;
      for (let i = 0; i < wells.length - 1; i++) {
        if (!scales[i] || !scales[i + 1]) continue;
        const da = topDepth(wells[i], m.name);
        const db = topDepth(wells[i + 1], m.name);
        if (da == null || db == null) continue;
        // dashed: where the marker runs between two wells is not known
        tag(svg.append("line")
          .attr("x1", geom[i].plotR).attr("x2", geom[i + 1].plotL)
          .attr("y1", scales[i](da)).attr("y2", scales[i + 1](db))
          .attr("stroke", col).attr("stroke-width", lw).attr("stroke-dasharray", "6 4")
          .attr("clip-path", clip), m.name, 1)
          .attr("data-w", lw)
          .style("cursor", "pointer")
          .on("mouseenter", () => setHover(m.name))
          .on("mouseleave", () => setHover(null))
          .on("click", () => flattenOnMarker(m.name));
      }
      // collected, not drawn: where two tops sit a metre apart their names
      // land on the same pixel, and only a pass over ALL of them can de-pile
      function label(x, left, yy) {
        if (yy < pt || yy > contentBot) return;   // off the plot band → skip
        (left ? leftLabels : rightLabels)
          .push({ x, left, y: yy, name: m.name, col, active });
      }
      // The label goes in a DEDICATED gutter, at the depth the marker has on
      // the nearest well that carries it: the left one at the panel's left
      // end, the right one after the last well that has a marker. Beside
      // that well it would land in the gap between two wells, on top of the
      // curves and the correlation lines.
      const fi = wells.findIndex((w, i) => scales[i] && topDepth(w, m.name) != null);
      if (fi >= 0) {
        label(labelColL, true, scales[fi](topDepth(wells[fi], m.name)));
      }
      let li = -1;
      for (let k = wells.length - 1; k >= 0; k--) {
        if (scales[k] && topDepth(wells[k], m.name) != null) { li = k; break; }
      }
      if (li >= 0 && labelColR != null) {
        label(labelColR, false, scales[li](topDepth(wells[li], m.name)));
      }
    });

    // Side labels, de-piled: each is pushed just far enough down to clear the
    // one above it, and a leader line runs back to the true depth so the
    // displacement never lies about where the top actually is.
    function placeLabels(items) {
      const kept = items.filter((it) => it.y >= pt && it.y <= contentBot)
                        .sort((a, b) => a.y - b.y);
      // Each label sits at its OWN depth, nudged down only far enough to clear
      // the one above it. A label that would have to move further than
      // LABEL_MAX_SHIFT is DROPPED, never displaced: a name parked far from
      // its line does not just look odd, it points at the wrong marker. The
      // crowd thins out as you zoom in, so the dropped names come back — and
      // every marker line names itself on hover meanwhile.
      const shown = [];
      let prev = -Infinity;
      for (const it of kept) {
        const ly = Math.max(it.y, prev + LABEL_GAP);
        if (ly - it.y > LABEL_MAX_SHIFT) continue;   // no honest room here
        it.ly = ly;
        prev = ly;
        shown.push(it);
      }
      shown.forEach((it) => {
        // toward the wells: right of the left names, left of the right ones
        const dir = it.left ? 1 : -1;
        if (Math.abs(it.ly - it.y) > 1.5) {
          tag(svg.append("line")
            .attr("x1", it.x + dir * 2).attr("y1", it.ly)
            .attr("x2", it.x + dir * 7).attr("y2", it.y)
            .attr("stroke", it.col).attr("stroke-width", 0.8), it.name, 0.6);
        }
        // the name, written in its line's colour, stands alone on both sides
        const dimmed = off.has(it.name);
        tag(svg.append("text").attr("x", it.x).attr("y", it.ly)
          .attr("text-anchor", it.left ? "end" : "start").attr("dominant-baseline", "central")
          .attr("font-size", 12).attr("font-weight", it.active ? 800 : 600)
          .attr("text-decoration", it.active ? "underline" : null)
          .attr("fill", inkOn(it.col, GROUND)).style("cursor", "pointer")
          .text(nameText(it.name, it.active, L)), it.name, 1)
          .on("mouseenter", () => setHover(it.name))
          .on("mouseleave", () => setHover(null))
          .on("click", () => toggleMarker(it.name))
          .append("title").text(it.name + (dimmed ? " (dimmed)" : ""));
      });
    }
    placeLabels(leftLabels);
    placeLabels(rightLabels);

    // The pointer's depth on the depth columns of the well it is over: one
    // mark per column, moved by `hover`, never redrawn. Before the
    // stratigraphic column, which covers a column scrolled under it.
    const cursor = svg.append("g").attr("pointer-events", "none").style("display", "none");
    const notch = () => cursor.append("path").attr("d", "M0,0L-7,-4.5L-7,4.5Z")
      .style("fill", "var(--fp-accent, #00436d)");
    // a small dashed cross on each curve of the track, at the pointer's
    // depth (the manager, 12/11)
    const crosses = cursor.append("g");
    state.hover = {
      wells, geom, scales, wTops, wBots, L, headTotal, d3,
      stratiW: SP.laneKeys.length && scales[SP.index] ? SP.w : 0,
      svg: svg.node(), cursor: cursor.node(), axisMark: notch().node(), sideMark: notch().node(),
      crosses: crosses.node(),
    };

    // ---- the stratigraphic column: once, and pinned to the left edge ----
    // Drawn LAST so nothing paints over it, and translated by the scroll
    // offset on every scroll: with a dozen wells side by side the reader is
    // usually scrolled far to the right, which is exactly when the column
    // has to stay in sight.
    if (SP.laneKeys.length && scales[SP.index]) {
      const ry = scales[SP.index];
      const rTop = wTops[SP.index];
      const rBot = wBots[SP.index];
      const sg = svg.append("g");
      sg.append("rect").attr("x", 0).attr("y", 0)
        .attr("width", SP.w).attr("height", plotH).attr("fill", "#fff")
        .append("title").text("Stratigraphy on the depths of "
                              + (SP.ref.name || "the first well"));
      SP.laneKeys.forEach((lane, li) => {
        const lx = li * L.stratiLaneW;
        (((SP.ref.strati || {})[lane]) || []).forEach((s) => {
          const y0 = Math.max(rTop, ry(s.top));
          const y1 = Math.min(rBot, ry(s.bottom));
          if (!(y1 > y0)) return;
          const band = sg.append("rect")
            .attr("x", lx).attr("y", y0)
            .attr("width", L.stratiLaneW).attr("height", y1 - y0)
            // the time lane keeps the chart's flat lavender, so the panel and
            // the stratigraphy card read as one axis, not two colour schemes
            .attr("fill", lane === "time" ? "#ede7f6" : (s.color || "#ccc"))
            .attr("stroke", "#555").attr("stroke-width", 0.4);
          band.append("title")
            .text(s.name + (s.parent ? `  (in ${s.parent})` : "")
                  + "\n" + spanText(s.top, s.bottom, (v) => fmtFixed(v, 2)));
          const h = y1 - y0;
          if (h > 26) {
            const cx = lx + L.stratiLaneW / 2;
            const cy = (y0 + y1) / 2;
            sg.append("text").attr("x", cx).attr("y", cy)
              .attr("transform", `rotate(-90, ${cx}, ${cy})`)
              .attr("text-anchor", "middle").attr("dominant-baseline", "central")
              .attr("font-size", 9)
              .attr("font-weight", s.kind === "group" ? 700 : 400)
              .attr("fill", "#111").attr("pointer-events", "none")
              .text(fit(s.name, h - 8));
          }
        });
      });
      sg.append("line").attr("x1", SP.w).attr("x2", SP.w)
        .attr("y1", 0).attr("y2", plotH)
        .attr("stroke", "#9e9e9e").attr("stroke-width", 1);
      const pin = () => sg.attr("transform",
        `translate(${container.scrollLeft},0)`);
      pin();
      if (state.pinStrati) container.removeEventListener("scroll", state.pinStrati);
      state.pinStrati = pin;
      container.addEventListener("scroll", pin, { passive: true });
    } else if (state.pinStrati) {
      container.removeEventListener("scroll", state.pinStrati);
      state.pinStrati = null;
    }

    // `root.selectAll("*").remove()` collapses the content to zero width, so
    // the browser resets scrollLeft to 0 — with many wells and tracks the
    // panel is far wider than its container and every re-render would
    // otherwise yank the reader back to the first log. scrollTop is restored
    // from the depth anchor (or the box zoom's target) computed above.
    container.scrollTop = state.pendingScroll != null
      ? state.pendingScroll
      : (anchor != null && state.lastPxPerUnit !== pxPerUnit)
        ? Math.max(0, anchor * pxPerUnit + headTotal + pt - viewH / 2)
        : prevScroll;
    state.pendingScroll = null;
    container.scrollLeft = prevLeft;
    state.lastPxPerUnit = pxPerUnit;
    state.lastHeadTotal = headTotal;
    // where the last track ends: the host's scrollbar stands against it
    state.lastPlotR = lastG ? lastG.plotR : width;
    if (options.onDrawn) options.onDrawn();
    return svg.node();
  }

  // Where the hole is at a depth of the drawn axis: [x, y] between the two
  // points of the well's path around it, null off the path
  const _holes = new WeakMap();
  function holeAt(well) {
    const hit = _holes.get(well);
    if (hit) return hit;
    const k = well.axis && well.axis.ref === "MD" ? 0 : 1;
    const path = (well.hole || []).filter((p) => p[k] != null).sort((a, b) => a[k] - b[k]);
    const at = (d) => {
      if (d == null || path.length < 2 || d < path[0][k] || d > path[path.length - 1][k]) return null;
      let lo = 0;
      let hi = path.length - 1;
      while (hi - lo > 1) {
        const mid = (lo + hi) >> 1;
        if (path[mid][k] <= d) lo = mid; else hi = mid;
      }
      const a = path[lo];
      const b = path[hi];
      const t = b[k] === a[k] ? 0 : (d - a[k]) / (b[k] - a[k]);
      return [a[2] + (b[2] - a[2]) * t, a[3] + (b[3] - a[3]) * t];
    };
    _holes.set(well, at);
    return at;
  }

  // The samples highlighted elsewhere (rows of the Values view, by measured
  // depth: `lit` {well: {curve: [md]}}): a dot on the curve and a faint line
  // across the track, in the 3D selection's colour
  const LIT = "#ff00ff";
  const LIT_MAX = 2000;
  function litMarks(g, well, curve, lit, xs, y, left, right, clip) {
    const mds = ((lit || {})[well.name] || {})[curve.name];
    if (!mds || !mds.length) return;
    const md = (s) => (well.axis && well.axis.ref === "MD" ? s[1] : (s.length > 2 ? s[2] : null));
    // each depth held lights the sample of the curve nearest it, within the
    // depths the curve runs between: the views read the same samples, their
    // depths need not agree to the last decimal
    const held = curve.samples
      .filter((s) => md(s) != null && s[0] != null && !Number.isNaN(s[0]))
      .sort((a, b) => md(a) - md(b));
    if (!held.length) return;
    const nearest = (m) => {
      let lo = 0;
      let hi = held.length - 1;
      while (hi - lo > 1) {
        const mid = (lo + hi) >> 1;
        if (md(held[mid]) < m) lo = mid; else hi = mid;
      }
      return Math.abs(md(held[lo]) - m) <= Math.abs(md(held[hi]) - m) ? held[lo] : held[hi];
    };
    const top = md(held[0]);
    const bottom = md(held[held.length - 1]);
    const picked = new Set(mds.slice(0, LIT_MAX).filter((m) => m >= top && m <= bottom).map(nearest));
    picked.forEach((s) => {
      const yy = y(s[1]);
      g.append("line").attr("x1", left + 1).attr("x2", right - 1).attr("y1", yy).attr("y2", yy)
        .attr("stroke", LIT).attr("stroke-width", 1).attr("stroke-opacity", 0.45).attr("clip-path", clip);
      g.append("circle").attr("cx", xs(s[0])).attr("cy", yy).attr("r", 3.5)
        .attr("fill", LIT).attr("clip-path", clip);
    });
  }

  // The sample of a curve the cursor stands on: [value, depth] of the sample
  // holding a value whose depth is the nearest to `d` — what the file holds,
  // never a value made up between two samples —; null off the depths the
  // curve runs between.
  function sampleNear(curve, logScale, d) {
    const s = curve.samples || [];
    const ok = (v) => v != null && !Number.isNaN(v) && (!logScale || v > 0);
    let best = null;
    let top = Infinity;
    let bottom = -Infinity;
    for (let i = 0; i < s.length; i++) {
      if (!ok(s[i][0])) continue;
      top = Math.min(top, s[i][1]);
      bottom = Math.max(bottom, s[i][1]);
      if (best == null || Math.abs(s[i][1] - d) < Math.abs(best[1] - d)) best = s[i];
    }
    return best && d >= top && d <= bottom ? best : null;
  }

  // The dashed crosses of the hovered track: one per curve on the sample the
  // cursor stands on, where its line passes, inside the track, in the blue
  // the Values view marks that sample's row with (a held one is magenta, LIT)
  const SVG_NS = "http://www.w3.org/2000/svg";
  const HOVER = "#1565c0";
  function crossesAt(H, scale, curves, yOf, left, right) {
    const g = H.crosses;
    while (g.firstChild) g.removeChild(g.firstChild);
    addCrosses(g, scale, curves, yOf, left, right);
  }

  function addCrosses(g, scale, curves, yOf, left, right) {
    const R = 7;
    curves.forEach((c) => {
      const x = c.value == null ? NaN : scale(c.value);
      const y = yOf(c);
      if (!Number.isFinite(x) || x < left || x > right) return;
      const path = document.createElementNS(SVG_NS, "path");
      path.setAttribute("d", `M${x - R},${y}H${x + R}M${x},${y - R}V${y + R}`);
      path.setAttribute("stroke", HOVER);
      path.setAttribute("stroke-width", "1.3");
      path.setAttribute("stroke-dasharray", "2,2");
      path.setAttribute("fill", "none");
      g.appendChild(path);
      const dot = document.createElementNS(SVG_NS, "circle");
      dot.setAttribute("cx", x);
      dot.setAttribute("cy", y);
      dot.setAttribute("r", "3.5");
      dot.setAttribute("fill", HOVER);
      g.appendChild(dot);
    });
  }

  // What lies under the pointer, read off the last drawing: the well, the
  // track, the depth at the pointer on the axis the well is laid out on and
  // on the one read beside it, and the value of each curve of the track there
  // — or null off a track, under the sticky header or under the pinned
  // stratigraphic column. The depth columns' marks follow; `hover(container)`
  // with no position hides them.
  function hover(container, clientX, clientY) {
    const H = container && container.__wlc && container.__wlc.hover;
    if (!H || !H.svg.isConnected) return null;
    const mark = (hit, G, y) => {
      H.cursor.style.display = hit ? "" : "none";
      if (!hit) return null;
      H.axisMark.setAttribute("transform", `translate(${G.axis.right},${y})`);
      H.sideMark.style.display = G.side ? "" : "none";
      if (G.side) H.sideMark.setAttribute("transform", `translate(${G.side.right},${y})`);
      return hit;
    };
    if (clientX == null || clientY == null) return mark(null);
    const frame = container.getBoundingClientRect();
    if (clientY < frame.top + H.headTotal || clientX < frame.left + H.stratiW) return mark(null);
    const box = H.svg.getBoundingClientRect();
    const x = clientX - box.left;
    const y = clientY - box.top;
    const L = H.L;
    for (let i = 0; i < H.wells.length; i++) {
      const G = H.geom[i];
      const ys = H.scales[i];
      if (!ys || x < G.plotL || x > G.plotR) continue;
      const well = H.wells[i];
      const k = Math.floor((x - G.plotL) / (L.trackW + L.trackGapIn));
      const t = (well.tracks || [])[k];
      if (!t || x > G.track(k) + L.trackW || y < H.wTops[i] || y > H.wBots[i]) return mark(null);
      // the cursor stands on a real sample: each curve's nearest the pointer,
      // the depths read at the nearest of them
      const pointed = ys.invert(y);
      const logScale = !!t.logScale;
      const near = (t.curves || [])
        .filter((c) => !c.missing && c.samples && c.samples.length)
        .map((c) => ({ c, p: sampleNear(c, logScale, pointed) }));
      // the sample the cursor stands on carries its other depth third (its
      // TVD drawn in MD, its MD drawn in TVD): read there, not through the table
      let snap = null;
      let snapOther = null;
      near.forEach(({ p }) => {
        if (p && (snap == null || Math.abs(p[1] - pointed) < Math.abs(snap - pointed))) {
          snap = p[1];
          snapOther = p.length > 2 && p[2] != null && Number.isFinite(p[2]) ? p[2] : null;
        }
      });
      const depth = snap == null ? pointed : snap;
      const depths = [{ ref: well.axis.ref, value: depth, unit: well.axis.unit }];
      if (well.other) {
        depths.push({ ref: well.other.ref, value: snapOther != null ? snapOther : well.other.at(depth),
          unit: well.other.unit });
      }
      const curves = near.map(({ c, p }) => ({
        name: c.name, unit: c.unit || "", color: c.color || "#1565c0",
        synthetic: !!c.synthetic, value: p ? p[0] : null, at: p ? p[1] : null,
      }));
      crossesAt(H, trackScale(H.d3, t, G.track(k), G.track(k) + L.trackW), curves,
        (c) => (c.at == null ? y : ys(c.at)), G.track(k), G.track(k) + L.trackW);
      return mark({ well: well.name, depths, curves }, G, ys(depth));
    }
    return mark(null);
  }

  // A sample pointed at from elsewhere (a row of the Values view under the
  // pointer): `at` {well, md, curves: [names]} — the cursor's blue crosses on
  // those curves at their sample nearest that measured depth, and the depth
  // columns' marks there; null hides them. Nothing is drawn again. Returns
  // where it stands in the drawing ({x, y}), null when nothing is shown.
  function pointAt(container, at) {
    const H = container && container.__wlc && container.__wlc.hover;
    if (!H || !H.svg.isConnected) return null;
    const g = H.crosses;
    while (g.firstChild) g.removeChild(g.firstChild);
    H.cursor.style.display = "none";
    if (!at || at.md == null || !Number.isFinite(Number(at.md))) return null;
    const md = Number(at.md);
    const w = H.wells.findIndex((x) => x.name === at.well);
    if (w < 0 || !H.scales[w]) return null;
    const well = H.wells[w];
    const G = H.geom[w];
    const ys = H.scales[w];
    const L = H.L;
    const names = new Set(at.curves || []);
    const mdOf = (s) => (well.axis && well.axis.ref === "MD" ? s[1] : (s.length > 2 ? s[2] : null));
    let depth = null;
    let x = null;
    (well.tracks || []).forEach((t, k) => {
      const left = G.track(k);
      const right = left + L.trackW;
      const logScale = !!t.logScale;
      const shown = [];
      (t.curves || []).forEach((c) => {
        if (c.missing || !c.samples || !c.samples.length || !names.has(c.name)) return;
        // the sample holding a value nearest that depth, within the depths the curve runs between
        let best = null;
        let top = Infinity;
        let bottom = -Infinity;
        c.samples.forEach((s) => {
          const m = mdOf(s);
          if (m == null || s[0] == null || Number.isNaN(s[0]) || (logScale && !(s[0] > 0))) return;
          top = Math.min(top, m);
          bottom = Math.max(bottom, m);
          if (best == null || Math.abs(m - md) < Math.abs(mdOf(best) - md)) best = s;
        });
        if (!best || md < top || md > bottom) return;
        shown.push({ value: best[0], at: best[1] });
      });
      if (!shown.length) return;
      addCrosses(g, trackScale(H.d3, t, left, right), shown, (c) => ys(c.at), left, right);
      if (depth == null) {
        depth = shown[0].at;
        x = left + L.trackW / 2;
      }
    });
    if (depth == null) return null;
    const y = ys(depth);
    H.cursor.style.display = "";
    H.axisMark.setAttribute("transform", `translate(${G.axis.right},${y})`);
    H.sideMark.style.display = G.side ? "" : "none";
    if (G.side) H.sideMark.setAttribute("transform", `translate(${G.side.right},${y})`);
    return { x, y };
  }

  // The depth on the axis a well is laid out on of the sample of its curve
  // `curve` ("" any of its curves) nearest the measured depth `md`; null when
  // it has none there.
  function depthOfMd(container, wellName, curve, md) {
    const H = container && container.__wlc && container.__wlc.hover;
    if (!H || md == null) return null;
    const well = (H.wells || []).find((x) => x.name === wellName);
    if (!well) return null;
    const mdOf = (s) => (well.axis && well.axis.ref === "MD" ? s[1] : (s.length > 2 ? s[2] : null));
    let best = null;
    (well.tracks || []).forEach((t) => (t.curves || []).forEach((c) => {
      if (c.missing || !c.samples || (curve && c.name !== curve)) return;
      c.samples.forEach((s) => {
        const m = mdOf(s);
        if (m == null || s[0] == null || Number.isNaN(s[0])) return;
        if (best == null || Math.abs(m - md) < Math.abs(mdOf(best) - md)) best = s;
      });
    }));
    return best ? best[1] : null;
  }

  // ---- mock data for demo.html (3 wells, 2 curves each, shared tops at
  // offset depths) ----
  function mockData() {
    const MARKERS = [
      { name: "BB", color: "#1b5e20" },
      { name: "TOP A", color: "#2e7d32" },
      { name: "BOTTOM A", color: "#d32f2f" },
      { name: "FLATTEN DATUM", color: "#795548" },
      { name: "BOTTOM B", color: "#1565c0" },
      { name: "C", color: "#7b1fa2" },
      { name: "D", color: "#29b6f6" },
    ];
    function walk(d0, d1, step, base, amp) {
      const out = []; let v = base;
      for (let d = d0; d <= d1; d += step) {
        v += (Math.sin(d / 17) + (((d * 31) % 13) - 6) / 6) * amp * 0.18;
        v = Math.max(base - amp, Math.min(base + amp, v));
        out.push([v, d]);
      }
      return out;
    }
    function well(name, color, d0, off) {
      return {
        name, color, depthRef: "SSTVD",
        depth: { min: d0, max: d0 + 1300 },
        curves: [
          { name: "GR", color: "#1565c0", unit: "API", range: [0, 150], samples: walk(d0, d0 + 1300, 4, 75, 70) },
          { name: "RES", color: "#2e7d32", unit: "ohm.m", range: [0.2, 2000], samples: walk(d0, d0 + 1300, 4, 1000, 950) },
        ],
        tops: [
          { name: "BB", depth: d0 + 130 + off },
          { name: "TOP A", depth: d0 + 600 + off * 1.2 },
          { name: "BOTTOM A", depth: d0 + 690 - off },
          { name: "FLATTEN DATUM", depth: d0 + 820 },
          { name: "BOTTOM B", depth: d0 + 900 + off },
          { name: "C", depth: d0 + 980 + off },
          { name: "D", depth: d0 + 1060 + off * 1.4 },
        ],
      };
    }
    return {
      markers: MARKERS,
      flattenOn: null,
      wells: [
        well("WELL-A", "#ffeb3b", 2100, 0),
        well("WELL-B", "#8bc34a", 2150, 35),
        well("WELL-C", "#26c6da", 1950, -60),
      ],
    };
  }

  global.WellLogCorrelation = { render, hover, pointAt, depthOfMd, mockData, ZOOM_MAX };
})(typeof window !== "undefined" ? window : globalThis);
