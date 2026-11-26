// Every function a widget's TEMPLATE calls must be defined in its script.
//
// eslint's Vue rules do not see it: a method removed from the script while
// the template still calls it fails only in the browser, at the first event
// that runs the call ("x is not a function"), and nothing else reports it.
//
// Reads each `*.vue` under `<widget>/vue-components/src` (and `_shared`):
// the calls `name(` in the template's bound attributes (`:x`, `@x`, `v-*`,
// `#x`) and in `{{ }}`, string literals removed first (a tooltip saying
// "row(s)" is no call), against the script's definitions — a method
// `name(...) {`, a key `name:`, a `const/let/var/function name`, an import.
// Exits 1 and names each call it cannot find. Run by widgets/lint.sh.
import fs from "fs";
import path from "path";

const root = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"));
const files = [];
(function walk(d) {
  for (const e of fs.readdirSync(d, { withFileTypes: true })) {
    if (e.name === "node_modules" || e.name === "serve" || e.name.startsWith(".")) continue;
    const p = path.join(d, e.name);
    if (e.isDirectory()) walk(p);
    else if (p.endsWith(".vue")) files.push(p);
  }
})(root);

// what a template may call without the component defining it
const GLOBALS = new Set([
  "if", "for", "while", "switch", "return", "typeof", "in", "of", "Number", "String", "Math",
  "parseInt", "parseFloat", "isNaN", "isFinite", "Boolean", "Array", "Object",
  "JSON", "Date", "$emit", "encodeURIComponent", "RegExp", "Set", "Map",
  "console", "setTimeout",
]);
const STRINGS = /'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*"|`(?:[^`\\]|\\.)*`/g;

let missing = 0;
for (const f of files) {
  const src = fs.readFileSync(f, "utf8");
  const tpl = (src.match(/<template>([\s\S]*)<\/template>/) || [, ""])[1];
  const script = (src.match(/<script[^>]*>([\s\S]*?)<\/script>/) || [, ""])[1];
  const calls = new Set();
  const bound = /\s(?::|@|#|v-[\w-]+)[\w.:-]*="([^"]*)"|\{\{([\s\S]*?)\}\}/g;
  for (const m of tpl.matchAll(bound)) {
    const expr = (m[1] || m[2] || "").replace(/&quot;/g, '"').replace(STRINGS, "''");
    for (const c of expr.matchAll(/(?<![\w.$])([A-Za-z_$][\w$]*)\s*\(/g)) calls.add(c[1]);
  }
  for (const c of calls) {
    if (GLOBALS.has(c)) continue;
    const def = new RegExp(String.raw`(^|[\s,{])${c}\s*\([^)]*\)\s*\{|\b${c}\s*:|\b(const|let|var|function)\s+${c}\b|import[^;]*\b${c}\b`, "m");
    if (!def.test(script)) {
      console.error(`${path.relative(root, f)}: the template calls ${c}(), which the script does not define`);
      missing += 1;
    }
  }
}
if (missing) {
  console.error(`template calls: ${missing} undefined in ${files.length} components`);
  process.exit(1);
}
console.log(`template calls: all defined (${files.length} components)`);
