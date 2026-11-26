<template>
  <div class="fxb">
    <template v-if="xml">
      <template v-if="mode === 'tree'">
        <fp-note v-if="parseError" severity="error" :text="parseError"
                 next="read it as Raw, the text is shown as it is" />
        <template v-else>
          <div class="fxb-filter">
            <input class="fp-input fxb-in" type="text" placeholder="Filter by name or value"
                   title="Keep only the fields whose name or value contains these letters, flat, whatever branch they are in"
                   :value="filter" @input="filter = $event.target.value" />
            <fp-btn tiny label="Expand all" title="Open every branch of the tree" @click="expandAll(true)" />
            <fp-btn tiny label="Collapse all" title="Close every branch under the root" @click="expandAll(false)" />
          </div>
          <div class="fxb-wrap">
            <table class="fxb-rows">
              <tr v-for="r in shownRows" :key="r.id">
                <td class="fxb-k" :style="{ paddingLeft: (4 + r.depth * 12) + 'px' }">
                  <span v-if="r.kids" class="fxb-caret fxb-caret-btn"
                        @click="toggle(r.id)">{{ collapsed.has(r.id) ? "▸" : "▾" }}</span>
                  <span v-else class="fxb-caret"></span>
                  <span class="fxb-el">{{ r.name }}</span>
                  <span v-if="r.index != null" class="fxb-muted">[{{ r.index }}]</span>
                </td>
                <td class="fxb-v" :class="{ 'fxb-void': !r.value && !r.attrs.length }">
                  <!-- A DataObjectReference names another object; the query
                       channel serves it whether or not it is in the tree.
                       The WHOLE chip opens it (the PO, 15/10: only the arrow
                       did): a chip is not a control (UI rule R12, see
                       doc/wiki/UI-Drawer-Toolbar-Shared.md), so the chip sits
                       inside a bare button, which the keyboard reaches; the
                       arrow stays as the sign of a link. The name keeps its
                       case: it is the button's content, not a label (R15). -->
                  <fp-btn v-if="r.ref" variant="bare" class="fx-link"
                          :title="'Open ' + (r.ref.title || 'this object') + ' in an Explorer tab — ' + r.ref.uuid"
                          @click="$emit('follow', r.ref)">
                    <fp-chip sm variant="line" class="fxb-ref" :text="r.ref.title || r.ref.uuid"
                             :title="'Open ' + (r.ref.title || 'this object') + ' in an Explorer tab — ' + r.ref.uuid">
                      <template #after><span class="fx-link-arrow" aria-hidden="true">→</span></template>
                    </fp-chip>
                  </fp-btn>
                  <!-- the UUID field of a reference opens the object too (the
                       manager, 15/10: the uuid was not a link) -->
                  <fp-btn v-if="r.link" variant="bare" class="fx-link fxb-uuid"
                          :title="'Open ' + (r.link.title || 'this object') + ' in an Explorer tab — ' + r.link.uuid"
                          @click="$emit('follow', r.link)">{{ r.value }}<span class="fx-link-arrow" aria-hidden="true">→</span></fp-btn>
                  <span v-else-if="r.value">{{ r.value }}</span>
                  <span v-for="a in r.attrs" :key="a.n" class="fxb-at">
                    {{ a.n }}=<span class="fxb-at-v">{{ a.v }}</span>
                  </span>
                  <span v-if="!r.value && !r.attrs.length && r.kids" class="fxb-muted">{{ r.kids }} field(s)</span>
                </td>
              </tr>
            </table>
          </div>
          <fp-empty v-if="!visibleRows.length"
                    shows="The fields whose name or value contains the filter."
                    gesture="Shorten the filter, or clear it to see the whole object." />
          <div v-else-if="hiddenCount" class="fp-sum fxb-hint">
            {{ plural(hiddenCount, "more row", "more rows") }} not shown — collapse a branch or narrow the filter.
          </div>
        </template>
      </template>
      <!-- Rendered as spans, never v-html. The XML is USER data (an uploaded
           EPC, an OSDU/ETP dataspace), so inserting it as raw HTML would be an
           injection surface; this is why the highlighter used here returns a
           token TREE rather than a string of HTML. -->
      <pre v-else class="fxb-raw"><span v-for="(s, i) in tokens" :key="i"
        :class="s.cls">{{ s.text }}</span></pre>
    </template>
    <fp-empty v-else
              shows="One RESQML object as fesapi holds it: a readable tree, or its raw text."
              :gesture="emptyLabel" />
  </div>
</template>

<script>
/*
 * XmlBody — the object itself, two ways: the readable tree (filtered,
 * folded, capped at MAX_ROWS rows) and the raw text, syntax-highlighted.
 * The frame around it (XmlViewer) owns the reading mode, the tabs, the trail
 * and the export; this component owns the parse and the fold state, and
 * fetches nothing.
 *
 *   props  — xml, mode ("tree" | "raw"), emptyLabel (the gesture that fills
 *            the empty state, given by the host: the explorer and the
 *            Attributes card are filled differently)
 *   events — follow({uuid,title}) a DataObjectReference was clicked
 */
import Prism from "prismjs/components/prism-core";
import "prismjs/components/prism-markup";
import { plural } from "../../../_shared/numfmt.js";
import FpBtn from "../../../_shared/components/FpBtn.vue";
import FpChip from "../../../_shared/components/FpChip.vue";
import FpEmpty from "../../../_shared/components/FpEmpty.vue";
import FpNote from "../../../_shared/components/FpNote.vue";

// A container at this depth or deeper starts collapsed. One RESQML part can
// hold megabytes of XML, tens of thousands of elements and thousands of
// siblings under a single parent, so rendering the whole document is not an
// option: the tree opens shallow and the reader descends.
const OPEN_DEPTH = 2;
// Past this many elements in the whole part, every container below the root
// starts collapsed.
const BIG_PART = 2000;
// Hard ceiling on the rows put in the DOM at once, filter included.
const MAX_ROWS = 600;

export default {
  name: "XmlBody",
  components: { FpBtn, FpChip, FpEmpty, FpNote },
  props: {
    xml: { type: String, default: "" },
    mode: { type: String, default: "tree" },
    emptyLabel: { type: String, required: true },
  },
  emits: ["follow"],
  data() {
    return { filter: "", collapsed: new Set() };
  },
  computed: {
    // The browser parses XML natively (DOMParser), so no XML parser package
    // is needed; what matters here is how the fields are SHOWN, which is the
    // walk below: one flat row per element, with its depth.
    parsed() {
      const text = this.xml || "";
      if (!text) return { rows: [], error: "" };
      let doc;
      try {
        doc = new DOMParser().parseFromString(text, "application/xml");
      } catch (e) {
        return { rows: [], error: "This object could not be read." };
      }
      if (doc.getElementsByTagName("parsererror").length) {
        return { rows: [], error: "This object could not be read." };
      }
      const rows = [];
      // `parentRef`: the reference the parent element makes, so its UUID
      // field links where the reference does
      const walk = (el, depth, id, index, parentRef) => {
        const kids = [];
        for (const c of el.children) kids.push(c);
        // A leaf's text is its value; a container's text is never shown (it
        // would be the concatenation of every descendant).
        const value = kids.length ? "" : (el.textContent || "").trim();
        const attrs = [];
        for (const a of el.attributes) {
          // xmlns declarations are gSOAP plumbing repeated on every subtree;
          // xsi:type stays, since on a RESQML object it IS information.
          if (a.name === "xmlns" || a.name.startsWith("xmlns:")) continue;
          attrs.push({ n: a.name, v: a.value });
        }
        // Detect a reference by its xsi:type, NOT by "the value looks like a
        // uuid": a part also carries uuid-shaped ExtraMetadata VALUES, and
        // offering those as links would promise a destination that does not
        // exist.
        let ref = null;
        if (attrs.some((a) => a.n.endsWith("type") &&
                              a.v.endsWith("DataObjectReference"))) {
          let u = "", ti = "";
          for (const c of kids) {
            const n = c.nodeName.replace(/^.*:/, "");
            if (n === "UUID" || n === "Uuid") u = (c.textContent || "").trim();
            else if (n === "Title") ti = (c.textContent || "").trim();
          }
          if (u) ref = { uuid: u, title: ti };
        }
        const local = el.nodeName.replace(/^.*:/, "");
        const link = parentRef && value && (local === "UUID" || local === "Uuid") ? parentRef : null;
        rows.push({ id, depth, name: el.nodeName, index, value, attrs, ref, link,
                    kids: kids.length });
        // Index siblings only when the name repeats, so a plain field is not
        // decorated with a meaningless [0].
        const counts = {};
        for (const c of kids) counts[c.nodeName] = (counts[c.nodeName] || 0) + 1;
        const seen = {};
        kids.forEach((c, i) => {
          const rep = counts[c.nodeName] > 1;
          const n = rep ? (seen[c.nodeName] = (seen[c.nodeName] || 0)) : null;
          if (rep) seen[c.nodeName] += 1;
          walk(c, depth + 1, id + "." + i, n, ref);
        });
      };
      if (doc.documentElement) walk(doc.documentElement, 0, "0", null, null);
      return { rows, error: "" };
    },
    rows() { return this.parsed.rows; },
    parseError() { return this.parsed.error; },
    visibleRows() {
      const rows = this.rows;
      const q = this.filter.trim().toLowerCase();
      if (q) {
        // A filter shows the matches themselves, flat, ignoring the fold: a
        // match hidden behind a collapsed ancestor would defeat the filter.
        return rows.filter((r) =>
          r.name.toLowerCase().includes(q) ||
          (r.value && r.value.toLowerCase().includes(q)) ||
          r.attrs.some((a) => a.v.toLowerCase().includes(q) ||
                              a.n.toLowerCase().includes(q)));
      }
      const out = [];
      let hidden = null;   // id prefix of the collapsed subtree being skipped
      for (const r of rows) {
        if (hidden !== null) {
          if (r.id.startsWith(hidden)) continue;
          hidden = null;
        }
        out.push(r);
        if (r.kids && this.collapsed.has(r.id)) hidden = r.id + ".";
      }
      return out;
    },
    // What is actually put in the DOM, at most MAX_ROWS rows. Rendering a
    // large part whole would freeze the tab, and silently dropping the rest
    // would be worse, so the footer says how many rows are hidden.
    shownRows() { return this.visibleRows.slice(0, MAX_ROWS); },
    hiddenCount() { return Math.max(0, this.visibleRows.length - MAX_ROWS); },
    // Flat {text, cls} spans rather than an HTML string. Prism emits a
    // distinct "namespace" token for the resqml20: / eml23: prefix that
    // almost every element of a RESQML part carries; muting it is what makes
    // the element names legible, and a highlighter that lumps the whole tag
    // name into one token cannot do it.
    tokens() {
      const text = this.xml || "";
      if (!text) return [];
      const out = [];
      const walk = (node, inherited) => {
        if (typeof node === "string") {
          if (node) out.push({ text: node, cls: inherited });
          return;
        }
        if (Array.isArray(node)) { node.forEach((n) => walk(n, inherited)); return; }
        const cls = (inherited + " token " + node.type +
                     (node.alias ? " " + [].concat(node.alias).join(" ") : "")).trim();
        walk(node.content, cls);
      };
      try {
        walk(Prism.tokenize(text, Prism.languages.markup), "");
      } catch (e) {
        return [{ text, cls: "" }];   // a highlighting failure never loses the content
      }
      return out;
    },
  },
  watch: {
    xml: {
      immediate: true,
      handler() {
        // Fold deep containers on arrival, so a large part opens at once, and
        // start the new object with no filter.
        const c = new Set();
        const deep = this.rows.length > BIG_PART ? 1 : OPEN_DEPTH;
        for (const r of this.rows) {
          if (r.kids && r.depth >= deep) c.add(r.id);
        }
        this.collapsed = c;
        this.filter = "";
      },
    },
  },
  methods: {
    plural,
    toggle(id) {
      const c = new Set(this.collapsed);
      c.has(id) ? c.delete(id) : c.add(id);
      this.collapsed = c;
    },
    expandAll(open) {
      if (open) { this.collapsed = new Set(); return; }
      const c = new Set();
      for (const r of this.rows) if (r.kids && r.depth >= 1) c.add(r.id);
      this.collapsed = c;
    },
  },
};
</script>

<style>
@import "../../../_shared/tokens.css";
</style>

<style scoped>
.fxb { display: flex; flex-direction: column; gap: 5px; flex: 1 1 auto; min-height: 0; font-family: system-ui, sans-serif; font-size: 13px; box-sizing: border-box; }
.fxv { display: flex; flex-direction: column; gap: 5px; height: 100%; min-height: 0; font-family: system-ui, sans-serif; font-size: 13px; box-sizing: border-box; }
.fxb-filter { display: flex; align-items: center; gap: 4px; flex: 0 0 auto; }
.fxb-in { flex: 1 1 auto; min-width: 0; font-size: 11px; }
.fxb-wrap { flex: 1 1 auto; min-height: 80px; overflow: auto; border: 1px solid #e0e6ee; border-radius: 3px; }
.fxb-rows { width: 100%; border-collapse: collapse; font-size: 11px; }
.fxb-rows td { padding: 1px 4px; vertical-align: top; border-bottom: 1px solid #f4f6f8; }
.fxb-k { color: #666; white-space: nowrap; width: 1%; font-family: ui-monospace, Consolas, monospace; }
.fxb-v { font-family: ui-monospace, Menlo, Consolas, monospace; word-break: break-word; }
/* An element with neither value nor attribute: faint, but through the
   faint-ink token, which keeps the word readable (a light grey such as #bbb
   on white falls below 2:1 contrast). */
.fxb-void { color: var(--fp-ink-faint); font-style: italic; }
.fxb-caret { width: 10px; color: #888; display: inline-block; }
.fxb-caret-btn { cursor: pointer; }
.fxb-caret-btn:hover { color: var(--fp-accent); }
.fxb-el { color: var(--fp-accent); }
.fxb-at { color: #7a7f87; margin-left: 8px; white-space: nowrap; }
.fxb-at-v { color: #a1642a; }
.fxb-ref { font-family: system-ui, sans-serif; font-weight: 400; }
.fp-btn.fxb-uuid { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 11px;
  color: var(--fp-accent); text-decoration: underline dotted; text-underline-offset: 2px; }
.fp-btn.fxb-uuid:hover { text-decoration-style: solid; }
.fxb-muted { color: #999; font-size: 11px; }
.fxb-hint { font-size: 11px; font-style: italic; }
.fxb-raw { flex: 1 1 auto; min-height: 80px; margin: 0; padding: 6px; overflow: auto; font-family: ui-monospace, Consolas, monospace; font-size: 11px; line-height: 1.35; background: #f7f9fb; border: 1px solid #e0e6ee; border-radius: 3px; white-space: pre; color: #263238; }
/* Prism token classes, styled here rather than by importing a theme file that
   would leak into the whole app. The namespace prefix gets its own shade: it
   is on ~every element, so muting it is what makes the element NAMES legible. */
.fxb-raw .token.tag { color: var(--fp-accent); font-weight: 600; }
.fxb-raw .token.namespace { color: #9aa0a6; font-weight: 400; }
.fxb-raw .token.punctuation { color: #99a1ab; font-weight: 400; }
.fxb-raw .token.attr-name { color: #7a7f87; font-weight: 400; }
.fxb-raw .token.attr-value { color: #a1642a; font-weight: 400; }
.fxb-raw .token.comment { color: #9aa0a6; font-style: italic; }
.fxb-raw .token.prolog { color: #8e44ad; }
</style>
