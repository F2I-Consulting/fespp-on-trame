/*
 * The one way a number is written on screen, shared by every widget (the
 * server side has the same rule in engine/utils/numfmt.py):
 *   - four significant digits, ties rounded away from zero;
 *   - scientific notation outside [1e-3, 1e6] (tested on the rounded value);
 *   - a thin space between thousands, a point as the decimal separator;
 *   - an en dash for a missing value.
 * CSV exports never go through here: they carry the raw values.
 */
export const DASH = "\u2013";
export const THIN = "\u2009";
export const NBSP = "\u00a0";

// the power of the unit each descriptive statistic carries (0 = unitless)
export const STAT_UNIT_POWER = {
  Cardinality: 0, NaN_count: 0,
  Minimum: 1, Maximum: 1, Mean: 1, "Mean (V)": 1, "Mean (PV)": 1,
  "Standard Deviation": 1, Sum: 1,
  P10: 1, Q1: 1, Median: 1, Q3: 1, P90: 1,
  Variance: 2, M2: 2, M3: 3, M4: 4,
  Skewness: 0, Kurtosis: 0,
};

const SUPERSCRIPT = { 2: "²", 3: "³", 4: "⁴" };

// an integer's digits grouped in threes from the right, once it has more than three
function group(digits, sep) {
  if (!sep || digits.length <= 3) return digits;
  let out = "";
  for (let i = digits.length; i > 0; i -= 3) {
    const chunk = digits.slice(Math.max(0, i - 3), i);
    out = out ? chunk + sep + out : chunk;
  }
  return out;
}

// the digits of a whole number without scientific notation
function wholeDigits(a) {
  return a >= 1e21 ? BigInt(a).toString() : String(a);
}

/*
 * What `v` is as a number: `null` for a missing value, the string itself
 * when it is a label (a string Number() cannot read), else the number.
 */
function read(v) {
  if (v === null || v === undefined) return null;
  if (typeof v === "string") {
    const s = v.trim();
    if (s === "") return null;
    const n = Number(s);
    return Number.isNaN(n) ? v : n;
  }
  const n = Number(v);
  return Number.isNaN(n) ? null : n;
}

/* A measured quantity. */
export function fmt(v, sep = THIN) {
  const n = read(v);
  if (n === null) return DASH;
  if (typeof n === "string") return n;
  if (n === Infinity) return "∞";
  if (n === -Infinity) return "-∞";
  if (n === 0) return "0";
  const sign = n < 0 ? "-" : "";
  const a = Math.abs(n);
  // rounding the largest doubles up overflows: they are written as they are
  let r = Number(a.toPrecision(4));
  if (!Number.isFinite(r)) r = a;
  const [mantissa, exp] = r.toExponential(3).split("e");
  const E = parseInt(exp, 10);
  if (r < 1e-3 || r > 1e6) {
    const m = mantissa.replace(/\.?0+$/, "");
    return sign + m + "e" + (E < 0 ? "-" : "+") + Math.abs(E);
  }
  let s = r.toFixed(Math.max(0, 3 - E));
  if (s.includes(".")) s = s.replace(/0+$/, "").replace(/\.$/, "");
  const [whole, frac] = s.split(".");
  return sign + group(whole, sep) + (frac ? "." + frac : "");
}

/* A count: every digit, grouped, never scientific. */
export function fmtInt(v) {
  const n = read(v);
  if (n === null) return DASH;
  if (typeof n === "string") return n;
  if (!Number.isFinite(n)) return fmt(n);
  const a = Math.trunc(Math.abs(n) + 0.5);
  return (n < 0 && a > 0 ? "-" : "") + group(wholeDigits(a), THIN);
}

/* A fraction written as a percentage. */
export function fmtPct(f) {
  const n = read(f);
  if (n === null) return DASH;
  if (typeof n === "string") return n;
  return fmt(n * 100) + NBSP + "%";
}

/* A coordinate, a depth, a contact: fixed decimals, grouped, never scientific. */
export function fmtFixed(v, decimals) {
  const n = read(v);
  if (n === null) return DASH;
  if (typeof n === "string") return n;
  if (!Number.isFinite(n)) return fmt(n);
  const d = Math.max(0, decimals | 0);
  const a = Math.abs(n);
  // toFixed turns to an exponent from 1e21; such a double is already whole
  const s = a >= 1e21 ? wholeDigits(a) + (d ? "." + "0".repeat(d) : "") : a.toFixed(d);
  const [whole, frac] = s.split(".");
  const negative = n < 0 && Number(s) !== 0;
  return (negative ? "-" : "") + group(whole, THIN) + (frac ? "." + frac : "");
}

/* `fmt` without grouping — for an editable field, where a thin space would not parse back. */
export function fmtPlain(v) {
  return fmt(v, "");
}

/*
 * A value the reader typed, written back EXACTLY: every digit it has, a
 * point, no grouping, no rounding. Four significant digits are the rule for
 * a measured quantity read off a table; a contact depth typed as 1250.5 and
 * shown back as 1251 is a field lying about the value in force.
 */
export function fmtExact(v) {
  const n = read(v);
  if (n === null) return "";
  if (typeof n === "string") return n;
  if (!Number.isFinite(n)) return fmt(n);
  // twelve significant digits: what a double holds, without the noise a
  // slider step or a sum leaves in the last places (0.30000000000000004)
  return String(Number(n.toPrecision(12)));
}

/* What a typed value is: thousands spaces dropped, a comma read as the point; null when not a number. */
export function parseNum(s) {
  if (s === null || s === undefined) return null;
  const t = String(s).replace(/[\u2009\u202f\u00a0 ]/g, "").replace(",", ".").trim();
  if (t === "") return null;
  const n = Number(t);
  return Number.isNaN(n) ? null : n;
}

/* A unit raised to a power, as a header writes it: "(m3/m3)²" — or "(m3/m3)^2" in a CSV. */
export function unitPower(uom, power, ascii = false) {
  if (!uom || !power) return "";
  if (power === 1) return uom;
  return "(" + uom + ")" + (ascii ? "^" + power : SUPERSCRIPT[power] || "^" + power);
}

/* `1 property`, `3 properties` — the twin of numfmt.plural: a sentence
   reading "1 property(ies)" says the page did not know how many it had. */
export function plural(count, one, many) {
  const n = read(count);
  const k = (typeof n === "number" && Number.isFinite(n)) ? Math.trunc(n) : 0;
  const word = k === 1 ? one : (many === undefined ? one + "s" : many);
  return fmtInt(k) + " " + word;
}
