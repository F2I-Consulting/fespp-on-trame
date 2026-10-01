/*
 * Derive `widgets/_shared/icons/svg/` — one .svg per icon plus a contact
 * sheet — from `widgets/_shared/icons/fespp-icons.js`.
 *
 *     node scripts/gen_icon_sheet.mjs            # write the folder
 *     node scripts/gen_icon_sheet.mjs --check    # fail if it is stale
 *
 * ONE WAY ONLY, and the module is the source. A part of an icon carries the
 * NAME of its family (`p("M4 8.5h…", "rock")`), which the renderer turns
 * into `var(--fp-ic-rock)`; a file can only carry the resolved value, and
 * any vector editor rewrites `stroke` to a literal colour — the family name
 * would be lost with nothing visibly broken. So the files are an artefact
 * for looking at, editing in Inkscape, or handing to someone who does not
 * read Vue, and they are gitignored.
 *
 * Each file stands on its own: the light palette's hex is the CSS
 * variable's fallback, and the root carries the tree's own `color` so the
 * parts with no family (drawn in `currentColor`) are not black outside the
 * application. Both are inert once the icon is inlined in a page that
 * defines the variables.
 *
 * `--check` regenerates in memory and compares; it prints every file that
 * differs and exits 1. Nothing here is silent.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const SRC = path.join(ROOT, "widgets/_shared/icons/fespp-icons.js");
const DIR = path.join(ROOT, "widgets/_shared/icons/svg");
const CHECK = process.argv.includes("--check");

// `.tn-icon`'s colour in the tree (TreeNode.vue): what a part with no
// family resolves to in the application, so a standalone file matches.
const NEUTRAL = "#546e7a";
const BANNER = "GENERATED — edits here are lost on the next run."
  + " The source is ../fespp-icons.js (node scripts/gen_icon_sheet.mjs)";

// the module is an ES module of plain data: run its body, no import
const body = fs.readFileSync(SRC, "utf8")
  .replace(/export default[\s\S]*$/, "")
  .replace(/^export /gm, "");
const { FESPP_ICONS: ICONS, FESPP_ICON_COLORS: PAL } =
  new Function(body + "\nreturn { FESPP_ICONS, FESPP_ICON_COLORS };")();

const kebab = (k) => k.replace(/([a-z0-9])([A-Z])/g, "$1-$2").toLowerCase();
const colour = (c) => (c ? `var(--fp-ic-${c}, ${PAL.light[c]})` : "currentColor");

const files = new Map();
for (const [key, icon] of Object.entries(ICONS)) {
  const parts = icon.parts.map((q) => (q.fill
    ? `  <path d="${q.d}" fill="${colour(q.c)}"/>`
    : `  <path d="${q.d}" fill="none" stroke="${colour(q.c)}" stroke-width="1.8"`
      + ` stroke-linecap="round" stroke-linejoin="round"/>`)).join("\n");
  files.set(`${kebab(key)}.svg`,
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24"`
    + ` color="${NEUTRAL}" data-icon="${key}">\n  <!-- ${BANNER} -->\n${parts}\n</svg>\n`);
}

const vars = (set) => Object.entries(set).map(([k, v]) => `--fp-ic-${k}:${v}`).join("; ");
const cells = [...Object.keys(ICONS)].map((key) => {
  const file = `${kebab(key)}.svg`;
  const n = ICONS[key].parts.length;
  return `<figure>
  <div class="big"><img src="${file}" width="48" height="48" alt="${key}"></div>
  <div class="sizes"><img src="${file}" width="24" height="24" alt=""><img src="${file}" width="15" height="15" alt=""></div>
  <figcaption>${key}<span>${file} · ${n} trait${n > 1 ? "s" : ""}</span></figcaption>
</figure>`;
}).join("\n");

files.set("index.html", `<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8"><title>Planche des icônes</title>
<!-- ${BANNER} -->
<style>
 :root { --bg:#fff; --ink:#1c2430; --mut:#6b7684; --line:#e6eaef; --card:#fafbfc; ${vars(PAL.light)}; }
 :root[data-t="dark"] { --bg:#161a1f; --ink:#e8edf3; --mut:#9aa6b4; --line:#2b323b; --card:#1d222a; ${vars(PAL.dark)}; }
 body { margin:0; background:var(--bg); color:var(--ink); font:14px/1.5 system-ui,Segoe UI,sans-serif }
 header { display:flex; align-items:baseline; gap:16px; padding:20px 24px 4px }
 h1 { font-size:19px; margin:0 } p { color:var(--mut); margin:0 24px 14px; max-width:78ch }
 button { margin-left:auto; font:inherit; padding:4px 10px; border:1px solid var(--line);
          background:var(--card); color:var(--ink); border-radius:5px; cursor:pointer }
 .sheet { display:grid; grid-template-columns:repeat(auto-fill,minmax(148px,1fr)); gap:14px; padding:0 24px 40px }
 figure { margin:0; padding:12px 8px 10px; border:1px solid var(--line); border-radius:8px;
          background:var(--card); text-align:center }
 .big { height:52px; display:flex; align-items:center; justify-content:center }
 .sizes { display:flex; align-items:center; justify-content:center; gap:10px; height:26px }
 figcaption { font:12px ui-monospace,monospace; margin-top:6px; word-break:break-all }
 figcaption span { display:block; color:var(--mut); font-size:10.5px; margin-top:2px }
</style></head><body>
<header><h1>Un fichier par icône</h1>
<button onclick="document.documentElement.dataset.t=document.documentElement.dataset.t==='dark'?'light':'dark'">thème clair / sombre</button></header>
<p>Chaque vignette est le fichier <code>.svg</code> lui-même, chargé en <code>&lt;img&gt;</code> : à 48, à 24 (les barres) et à 15 px (l’arbre).
Les couleurs y sont écrites <code>var(--fp-ic-rock, #8a7043)</code> — la valeur de repli fait que le fichier s’ouvre seul, correctement,
dans un navigateur ou un éditeur vectoriel ; une fois inséré en ligne dans l’application, il suit le thème. Un <code>&lt;img&gt;</code> ne voit
PAS les variables de la page : c’est pourquoi le bouton ci-dessus ne change ici que le fond. Dossier généré, jamais versionné —
<code>node scripts/gen_icon_sheet.mjs</code>.</p>
<div class="sheet">
${cells}
</div>
</body></html>
`);

if (CHECK) {
  const stale = [];
  const known = new Set(files.keys());
  for (const [name, want] of files) {
    const at = path.join(DIR, name);
    if (!fs.existsSync(at)) stale.push(`missing  ${name}`);
    else if (fs.readFileSync(at, "utf8") !== want) stale.push(`differs  ${name}`);
  }
  const there = fs.existsSync(DIR) ? fs.readdirSync(DIR) : [];
  for (const name of there) if (!known.has(name)) stale.push(`leftover ${name}`);
  if (stale.length) {
    console.error(`widgets/_shared/icons/svg is stale (${stale.length}):`);
    for (const s of stale) console.error("  " + s);
    console.error("run: node scripts/gen_icon_sheet.mjs");
    process.exit(1);
  }
  console.log(`up to date — ${files.size - 1} icons`);
} else {
  fs.mkdirSync(DIR, { recursive: true });
  for (const name of fs.readdirSync(DIR)) {
    if (!files.has(name)) { fs.unlinkSync(path.join(DIR, name)); console.log("removed " + name); }
  }
  for (const [name, text] of files) fs.writeFileSync(path.join(DIR, name), text);
  console.log(`${files.size - 1} icons -> ${path.relative(ROOT, DIR)} (+ index.html)`);
}
