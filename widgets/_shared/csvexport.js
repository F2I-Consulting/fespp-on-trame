/*
 * The CSV a widget hands over, shared by every table widget (the server side
 * has the same layout in engine/utils/csv_export.py): the provenance header
 * lines the server sent (already prefixed with "# "), one column line, then
 * one line per row of RAW values — never the rounded, converted text of the
 * screen. `null` is a value that could not be evaluated and reads "n/a";
 * `undefined` or "" is a cell that does not apply and stays empty.
 */
import { unitPower } from "./numfmt.js";

export const NA = "n/a";

/* A text cell, quoted when it holds a comma, a quote or a line break. */
export function csvCell(v) {
  const s = v === null || v === undefined ? "" : String(v);
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

/* A raw cell: the number as it is, a boolean as a word, text escaped. */
export function rawCell(v) {
  if (v === null) return NA;
  if (v === undefined || v === "") return "";
  if (typeof v === "number") return Number.isNaN(v) ? NA : String(v);
  if (typeof v === "boolean") return v ? "true" : "false";
  return csvCell(String(v));
}

/* A column header with its unit: "min (m3/m3)", "variance ((m3/m3)^2)", "cells". */
export function csvColumn(name, uom = "", power = 1) {
  const unit = unitPower(uom, power, true);
  return unit ? `${name} (${unit})` : name;
}

/* The whole file: header lines verbatim, the column line, one line per row. */
export function buildCsv(headerLines, columns, rows) {
  const lines = [...(headerLines || [])];
  lines.push(columns.map(csvCell).join(","));
  for (const r of rows) lines.push(r.map(rawCell).join(","));
  return lines.join("\n") + "\n";
}

/*
 * The name and header the server decided for this table — or, when it has
 * not provided them, a plain name and a header line that says the provenance
 * is missing: the file is still handed over, never silently incomplete.
 */
export function csvMeta(csv, fallbackName) {
  const name = (csv && csv.name) || fallbackName;
  const header = (csv && Array.isArray(csv.header) && csv.header.length)
    ? csv.header.slice()
    : ["# provenance header not available: the server did not provide one"];
  return { name, header };
}

/*
 * Hand `text` to the user: the clipboard when the browser offers one (a
 * secure context — https or localhost), else a download of `filename` built
 * here in the page. Resolves to what happened, for the button to say.
 */
export async function handOver(text, filename, type, failHint = "select the table and copy it") {
  try {
    if (navigator.clipboard) {
      await navigator.clipboard.writeText(text);
      return "Copied";
    }
  } catch (e) { /* no clipboard here: the download below is the way out */ }
  try {
    const url = URL.createObjectURL(new Blob([text], { type }));
    const a = Object.assign(document.createElement("a"), { href: url, download: filename });
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    return "Downloaded";
  } catch (e) {
    return "Export failed — " + failHint;
  }
}

/*
 * The same function, reachable from a panel written in Python (the
 * statistics cards): a Vuetify-in-Python click handler is a JS expression in
 * the page and cannot import an ES module, and the alternative is a second
 * copy of the clipboard / download rule that would drift from this one. The
 * side effect runs as soon as any widget bundle imports this file, which
 * every enabled table widget does.
 */
if (typeof window !== "undefined") window.fpHandOver = handOver;
