// The velocity scale of the tracks: the colours the view paints the
// Velocity model's velocity with, sampled from its table by the server
// (app/features/time_depth_pins: {lo, hi, stops, log}); Viridis, below, while
// the view paints none.
export const VIRIDIS = [
  "#440154", "#471365", "#482475", "#463480", "#414487", "#3b528b", "#355f8d", "#2f6c8e",
  "#2a788e", "#25848e", "#21918c", "#1e9c89", "#22a884", "#2fb47c", "#44bf70", "#5ec962",
  "#7ad151", "#9bd93c", "#bddf26", "#dfe318", "#fde725",
];

function hex(c) {
  return [parseInt(c.slice(1, 3), 16), parseInt(c.slice(3, 5), 16), parseInt(c.slice(5, 7), 16)];
}

/* The colour of `v` between `lo` and `hi` (clamped), as "rgb(r, g, b)". */
export function colourFor(v, lo, hi) {
  if (!Number.isFinite(v)) return "transparent";
  const span = hi > lo ? hi - lo : 1;
  const u = Math.min(1, Math.max(0, (v - lo) / span)) * (VIRIDIS.length - 1);
  const k = Math.floor(u);
  const f = u - k;
  const a = hex(VIRIDIS[Math.min(k, VIRIDIS.length - 1)]);
  const b = hex(VIRIDIS[Math.min(k + 1, VIRIDIS.length - 1)]);
  const c = a.map((x, i) => Math.round(x + (b[i] - x) * f));
  return `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
}

/* The same colour softened for a cell background. */
export function tintFor(v, lo, hi, alpha = 0.28) {
  const rgb = colourFor(v, lo, hi);
  return rgb === "transparent" ? rgb : rgb.replace("rgb(", "rgba(").replace(")", `, ${alpha})`);
}

/* The range the scale spans, rounded outward to 100 m/s. */
export function scaleOf(values) {
  const vs = values.filter((v) => Number.isFinite(v));
  if (!vs.length) return [1500, 4500];
  const lo = Math.floor(Math.min(...vs) / 100) * 100;
  const hi = Math.ceil(Math.max(...vs) / 100) * 100;
  return [lo, hi > lo ? hi : lo + 100];
}

/* The colour of `v` on the view's colours `colors` ({lo, hi, stops: [hex]
 * evenly spaced, log}), else on Viridis between `lo` and `hi`. */
export function colourOn(v, colors, lo, hi) {
  const stops = (colors && colors.stops) || [];
  if (!Number.isFinite(v)) return "transparent";
  if (stops.length < 2 || !(colors.hi > colors.lo)) return colourFor(v, lo, hi);
  const log = colors.log && colors.lo > 0 && v > 0;
  const a = log ? Math.log10(colors.lo) : colors.lo;
  const b = log ? Math.log10(colors.hi) : colors.hi;
  const x = log ? Math.log10(v) : v;
  const u = Math.min(1, Math.max(0, (x - a) / (b - a))) * (stops.length - 1);
  const k = Math.floor(u);
  const f = u - k;
  const c0 = hex(stops[Math.min(k, stops.length - 1)]);
  const c1 = hex(stops[Math.min(k + 1, stops.length - 1)]);
  const c = c0.map((q, i) => Math.round(q + (c1[i] - q) * f));
  return `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
}
