<template>
  <div class="fxr">
    <fp-note v-if="!supported" severity="warning"
             text="This FESPP build does not answer the relationship query: what designates an object cannot be read from the object itself, so nothing can be shown here."
             next="rebuild the plugin, or read the object as a Tree — the references it makes are written in its own text" />
    <fp-empty v-else-if="!rootUuid"
              shows="What an object designates, and what designates it."
              gesture="Open an object first — add it above, or follow a reference." />
    <template v-else>
      <div class="fxr-top">
        <fp-seg v-model="view" :options="VIEWS" title="How the neighbourhood of the object is drawn" />
        <div class="fxr-how fp-sum">
          A <b>reference</b> is written in the object that points, never in
          the one it points at — so <em>Referenced by</em> is readable nowhere but here.
          {{ view === "diagram"
            ? "Click a box to open it; right-click it to read it beside the graph, as a tree or raw."
            : "Open a row to walk on; right-click a name to read it beside the list, as a tree or raw." }}
        </div>
      </div>
      <div class="fxr-body">
        <!-- THE DIAGRAM (the PO, 15/10, after Doxygen's collaboration
             diagrams): the object in the middle — the count of what it
             references on its first line, of what references it on its last
             (the PO, 16/10) —, what it references above, what references it
             below, every arrow dashed. One step each way; the List walks
             further. -->
        <div v-if="view === 'diagram'" class="fxr-wrap fxr-dia-wrap">
          <fp-progress v-if="!relations[rootUuid]" class="fxr-dia-wait" label="Reading…" />
          <svg v-else class="fxr-svg" :viewBox="'0 0 ' + dia.w + ' ' + dia.h"
               :style="{ maxWidth: dia.w + 'px' }" role="img"
               :aria-label="'References of ' + (rootTitle || rootUuid)">
            <defs>
              <marker id="fxr-arrow-ref" viewBox="0 0 10 10" refX="9" refY="5"
                      markerWidth="8" markerHeight="8" orient="auto-start-reverse">
                <path d="M0,0 L10,5 L0,10 z" fill="#4f9fe8" />
              </marker>
              <marker id="fxr-arrow-by" viewBox="0 0 10 10" refX="9" refY="5"
                      markerWidth="8" markerHeight="8" orient="auto-start-reverse">
                <path d="M0,0 L10,5 L0,10 z" fill="#9b4fd1" />
              </marker>
            </defs>
            <line v-for="e in dia.edges" :key="e.key" :x1="e.x1" :y1="e.y1" :x2="e.x2" :y2="e.y2"
                  :class="e.by ? 'fxr-edge-by' : 'fxr-edge-ref'"
                  :marker-end="e.by ? 'url(#fxr-arrow-by)' : 'url(#fxr-arrow-ref)'" />
            <g v-for="b in dia.boxes" :key="b.key" class="fxr-box"
               :class="['fxr-box-' + b.kind, { 'fxr-box-partial': b.partial, 'fxr-box-open': b.open }]"
               :tabindex="b.kind === 'root' ? -1 : 0" :role="b.kind === 'root' ? null : 'button'"
               @click="onBox(b)" @keydown.enter="onBox(b)" @contextmenu.prevent="onBoxRaw(b)">
              <title>{{ b.tip }}</title>
              <!-- a series is a stack: one more frame behind it -->
              <rect v-if="b.kind === 'group'" class="fxr-stack" :x="b.x + 3" :y="b.y - 3"
                    :width="b.w" :height="b.h" rx="2" />
              <rect :x="b.x" :y="b.y" :width="b.w" :height="b.h" rx="2" />
              <template v-if="b.kind === 'root'">
                <text :x="b.x + b.w / 2" :y="b.y + 13" text-anchor="middle" class="fxr-box-n">{{ b.refs }}</text>
                <text :x="b.x + b.w / 2" :y="b.y + 29" text-anchor="middle" class="fxr-box-t">{{ b.label }}</text>
                <text :x="b.x + b.w / 2" :y="b.y + 42" text-anchor="middle" class="fxr-box-ty">{{ b.typeLabel }}</text>
                <text :x="b.x + b.w / 2" :y="b.y + 56" text-anchor="middle" class="fxr-box-n">{{ b.refsBy }}</text>
              </template>
              <template v-else>
                <text :x="b.x + b.w / 2" :y="b.y + 14" text-anchor="middle" class="fxr-box-t">{{ b.label }}</text>
                <text :x="b.x + b.w / 2" :y="b.y + 27" text-anchor="middle" class="fxr-box-ty">{{ b.typeLabel }}</text>
              </template>
            </g>
          </svg>
        </div>
        <div v-else class="fxr-wrap">
          <table class="fxr-rows">
            <tr v-for="r in rows" :key="r.key" :class="{ 'fxr-group': r.group }">
              <td class="fxr-c" :style="{ paddingLeft: (4 + r.depth * 14) + 'px' }"
                  @contextmenu.prevent="!r.group && r.depth > 0 && showRaw(r)">
                <fp-btn v-if="r.canOpen" variant="bare" class="fxr-caret"
                        :label="isOpen(r.key) ? '▾' : '▸'"
                        :title="(isOpen(r.key) ? 'Close ' : 'Open ') + r.label"
                        @click="toggle(r)" />
                <span v-else class="fxr-caret fxr-caret-void"></span>

                <template v-if="r.group">
                  <span class="fxr-group-name">{{ r.label }}</span>
                  <span class="fxr-muted">{{ r.count }}</span>
                </template>
                <template v-else>
                  <!-- the root is the object this tab already shows: a link
                       to itself led nowhere and read as one (the manager,
                       15/10), so it is its plain name -->
                  <span v-if="r.depth === 0" class="fxr-root">{{ r.label }}</span>
                  <!-- the whole chip opens the object (the PO, 15/10), as in
                       the Tree reading: a bare button around the chip -->
                  <fp-btn v-else variant="bare" class="fx-link"
                          :title="'Open ' + r.label + ' in an Explorer tab — ' + r.type + ' — ' + r.uuid + (r.partial ? ' — a reference only, not in the loaded data' : '') + ' — right-click: its XML beside'"
                          @click="$emit('follow', { uuid: r.uuid, title: r.title })">
                    <fp-chip sm variant="line" class="fxr-name"
                             :text="r.label"
                             :title="'Open ' + r.label + ' in an Explorer tab — ' + r.type + ' — ' + r.uuid + (r.partial ? ' — a reference only, not in the loaded data' : '')">
                      <template #after><span class="fx-link-arrow" aria-hidden="true">→</span></template>
                    </fp-chip>
                  </fp-btn>
                  <span class="fxr-type fxr-muted">{{ r.type }}</span>
                  <span v-if="r.partial" class="fxr-muted fxr-partial">reference only</span>
                  <!-- A RESQML graph has cycles: opening an object already on
                       the path down to this row would walk for ever, so the
                       row is named and stopped here instead. -->
                  <span v-if="r.loop" class="fxr-muted fxr-loop">already above</span>
                  <fp-progress v-else-if="r.waiting" class="fxr-row-wait" label="Reading…" />
                </template>
              </td>
            </tr>
          </table>
        </div>
        <!-- the objects read beside the graph (right-click a box or a name):
             the last one shown replaces the previous, a pinned one stays (the
             PO, 16/10: more than a box says, without leaving the object) -->
        <div v-if="(raws || []).length" class="fxr-raws">
          <div v-for="r in raws" :key="r.uuid" class="fxr-raw" :class="{ 'fxr-raw-pinned': r.pinned }">
            <div class="fxr-raw-top">
              <span class="fxr-raw-t" :title="(r.title || r.uuid) + ' — ' + r.type + ' — ' + r.uuid">{{ r.title || r.uuid }}</span>
              <span class="fxr-muted fxr-type">{{ shortType(r.type) }}</span>
              <fp-seg class="fxr-raw-mode" :model-value="rawMode[r.uuid] || 'tree'" :options="RAW_MODES"
                      title="Read it as a tree or as its raw text"
                      @update:model-value="rawMode = Object.assign({}, rawMode, { [r.uuid]: $event })" />
              <!-- the pin of the Statistics view, not a word (the PO, 21/10):
                   outlined to pin, filled while pinned -->
              <fp-btn variant="bare" icon class="fxr-pin" :class="{ 'fxr-pin-on': r.pinned }"
                      :title="r.pinned ? 'Pinned: it stays when another object is read beside — click to release it' : 'Pin it: it stays beside the graph when another object is read'"
                      @click="$emit('raw', { uuid: r.uuid, action: 'pin' })">
                <v-icon size="16">{{ r.pinned ? "mdi-pin" : "mdi-pin-outline" }}</v-icon>
              </fp-btn>
              <fp-btn tiny label="Open" title="Open it in an Explorer tab"
                      @click="$emit('follow', { uuid: r.uuid, title: r.title })" />
              <fp-btn tiny label="×" title="Close this reading"
                      @click="$emit('raw', { uuid: r.uuid, action: 'close' })" />
            </div>
            <xml-body :xml="r.xml" :mode="rawMode[r.uuid] || 'tree'"
                      empty-label="Nothing to read for this object: a reference only, not in the loaded data."
                      @follow="$emit('follow', $event)" />
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<script>
/*
 * The object GRAPH of one RESQML object: what it designates, and what
 * designates it, walkable in place.
 *
 * The two other readings of the explorer (Tree and Raw, see XmlBody) show
 * the XML of ONE object. Neither shows the object's neighbourhood, and one
 * half of that neighbourhood is not in its bytes at all: a
 * DataObjectReference is written in the XML of the object that POINTS,
 * never in the one it points at. So "what designates this" cannot be read
 * from the object, only asked of the repository (repo_query.object_relations
 * -> fesapi's backwardRels).
 *
 * THE DIAGRAM draws one step each way. Objects of one type and one title
 * met several times on one side — the steps of a time series, the
 * realizations of a property (the host reads their `ts` / `real` from their
 * XML) — are ONE box, "GasSat · TS ×12", which a click opens into its
 * members and closes again. A side draws 10 boxes, then a "+N more" box
 * that draws 10 more per click, until all are there (the PO, 16/10).
 *
 * THE LIST: the rows are flat with a depth, like XmlBody's: one table, one
 * padding. Expanding involves the host: the relations of an object are
 * fetched on demand, so opening a row whose answer is not held yet emits
 * `need(uuid)`, and the row says "reading…" until the answer lands.
 *
 * CYCLES. A RESQML graph has them by construction (an interpretation names
 * its feature, the feature's representations name the interpretation). A
 * node whose uuid is already on the path from the root is therefore marked
 * "already above" and cannot be opened: the walk stops where it would have
 * gone round, and says so rather than looking like a leaf.
 *
 * BESIDE. A right-click on a box or a name shows that object's XML beside
 * the graph (`raw`); the host keeps the pinned ones when the next comes.
 *
 *   props  — rootUuid / rootTitle / rootType, relations ({uuid: {target,
 *            source}} as far as the host has fetched; an item may carry
 *            `ts` / `real`), supported (this plugin build answers the query
 *            at all), raws ([{uuid, title, type, xml, pinned}])
 *   events — need(uuid) fetch the relations of that object;
 *            follow({uuid, title}) open it in a tab;
 *            raw({uuid, title, type, action}) show / pin / close a reading
 */
import FpBtn from "../../../_shared/components/FpBtn.vue";
import FpChip from "../../../_shared/components/FpChip.vue";
import FpEmpty from "../../../_shared/components/FpEmpty.vue";
import FpNote from "../../../_shared/components/FpNote.vue";
import FpProgress from "../../../_shared/components/FpProgress.vue";
import FpSeg from "../../../_shared/components/FpSeg.vue";

// an object read beside the graph: its readable tree, or its raw text
const RAW_MODES = [
  { value: "tree", label: "Tree", title: "The object as a readable tree" },
  { value: "raw", label: "Raw", title: "The object's raw text, as stored" },
];
import XmlBody from "./XmlBody.vue";

const GROUPS = [
  { dir: "target", label: "References" },
  { dir: "source", label: "Referenced by" },
];

const VIEWS = [
  { value: "diagram", label: "Diagram", title: "The object, what it references above, what references it below" },
  { value: "list", label: "List", title: "Every reference as a row, walkable further down" },
];

// the diagram's geometry, in SVG units (px at scale 1)
const DIA_W = 760;      // drawing width; rows wrap within it
const BH = 34;          // box height: a title line and a type line
const RBH = 62;         // the root's: its two counts around them
const GAP = 14;         // between two boxes of a row
const ROW_GAP = 42;     // between two rows: room for the arrows
const PAGE = 10;        // boxes a side draws, and how many more a click adds
const LABEL_CHARS = 30; // a title longer than this is cut, whole in the tooltip

// "resqml20.obj_IjkGridRepresentation" -> "IjkGridRepresentation"
function shortType(type) {
  return String(type || "").replace(/^.*[.:]/, "").replace(/^obj_/, "");
}

function cut(s, n) {
  s = String(s || "");
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}

// what one member of a series is called: its step, its realization
function indexLabel(it) {
  const parts = [];
  if (it.real != null) parts.push("real " + it.real);
  if (it.ts != null) parts.push("t" + it.ts);
  return parts.join(" · ");
}

function byIndex(a, b) {
  return ((a.real ?? -1) - (b.real ?? -1)) || ((a.ts ?? -1) - (b.ts ?? -1))
    || String(a.uuid).localeCompare(String(b.uuid));
}

export default {
  name: "XmlRelations",
  components: { FpBtn, FpChip, FpEmpty, FpNote, FpProgress, FpSeg, XmlBody },
  props: {
    rootUuid: { type: String, default: "" },
    rootTitle: { type: String, default: "" },
    rootType: { type: String, default: "" },
    relations: { type: Object, default: () => ({}) },
    supported: { type: Boolean, default: true },
    raws: { type: Array, default: () => [] },
  },
  emits: ["need", "follow", "raw"],
  data() {
    // rawMode: how each object read beside the graph is shown, its tree
    // by default or its raw text (the manager, 21/10)
    return { open: [], view: "diagram", VIEWS, expanded: [], more: { t: PAGE, s: PAGE },
             rawMode: {}, RAW_MODES };
  },
  watch: {
    // Another object at the root is another graph: what was open under the
    // previous one means nothing here; the new root opens as on mount.
    rootUuid() {
      this.open = [];
      this.expanded = [];
      this.more = { t: PAGE, s: PAGE };
      if (this.rootUuid) this.toggle({ key: this.rootUuid, uuid: this.rootUuid, group: false });
    },
  },
  computed: {
    /*
     * The diagram: boxes, arrows, laid out in rows. What the root
     * references sits above it (the nearest row first), what references it
     * below; each row is centred and wraps at DIA_W. An arrow points AT what
     * is referenced, as the reference does; a series' members, once open,
     * follow its box, tinted, without an arrow of their own.
     */
    dia() {
      const rel = this.relations[this.rootUuid] || {};
      const sized = (b, lines) => {
        const chars = Math.max(...lines.map((l) => String(l || "").length));
        b.w = Math.min(230, Math.max(96, Math.round(chars * 6.4) + 18));
        return b;
      };
      const objectBox = (it, side, kind) => {
        const idx = indexLabel(it);
        const label = cut(kind === "member" && idx ? idx : (it.title || it.uuid), LABEL_CHARS);
        const typeLabel = shortType(it.type);
        return sized({
          key: kind[0] + ":" + side + ":" + it.uuid, kind, uuid: it.uuid, title: it.title,
          idx, type: it.type, label, typeLabel, partial: !!it.partial, h: BH,
          tip: (it.title || it.uuid) + (idx ? " (" + idx + ")" : "") + " — " + (it.type || "")
               + " — " + it.uuid + (it.partial ? " — a reference only, not in the loaded data" : "")
               + " — click to open it in a tab, right-click to read it beside the graph",
        }, [label, typeLabel]);
      };
      // one side: its objects, a repeated (type, title) folded into a series;
      // an entry is a box, with the members of an open series after it
      const entries = (items, side) => {
        const members = new Map();
        for (const it of items) {
          const k = (it.type || "") + "|" + (it.title || "");
          if (!members.has(k)) members.set(k, []);
          members.get(k).push(it);
        }
        const out = [];
        const done = new Set();
        for (const it of items) {
          const k = (it.type || "") + "|" + (it.title || "");
          const ms = members.get(k);
          if (ms.length < 2) { out.push({ box: objectBox(it, side, "obj"), members: [] }); continue; }
          if (done.has(k)) continue;
          done.add(k);
          const gkey = side + "|" + k;
          const open = this.expanded.includes(gkey);
          const ts = ms.every((m) => m.ts != null);
          const real = ms.every((m) => m.real != null);
          const series = ts && real ? "TS · MR" : ts ? "TS" : real ? "MR" : "";
          const what = ts && !real ? "steps of a time series" : real && !ts
            ? "realizations" : series ? "steps and realizations" : "objects of the same title";
          const label = cut((open ? "▾ " : "▸ ") + (it.title || it.uuid), LABEL_CHARS);
          const typeLabel = shortType(it.type) + " · " + (series ? series + " " : "") + "×" + ms.length;
          out.push({
            box: sized({
              key: "g:" + gkey, kind: "group", gkey, open, label, typeLabel, h: BH,
              tip: ms.length + " " + what + " of " + (it.title || it.uuid) + " (" + shortType(it.type)
                   + ") — click to " + (open ? "fold them back into one box" : "show each of them"),
            }, [label, typeLabel]),
            // an open series shows ALL its members at once (the PO, 16/10)
            members: open ? [...ms].sort(byIndex).map((m) => objectBox(m, side, "member")) : [],
          });
        }
        return out;
      };
      // a side draws `more[side]` entries (an open series counts as one),
      // then one box for the rest
      const page = (all, side) => {
        const kept = all.slice(0, this.more[side]);
        const shown = kept.flatMap((e) => [e.box, ...e.members]);
        const left = all.length - kept.length;
        if (left > 0) {
          const label = "+" + left + " more";
          const typeLabel = "draw " + Math.min(PAGE, left) + " more";
          shown.push(sized({
            key: "more:" + side, kind: "more", side, label, typeLabel, h: BH,
            tip: left + " more not drawn yet — click to draw " + Math.min(PAGE, left) + " more",
          }, [label, typeLabel]));
        }
        return shown;
      };
      const pack = (items) => {
        const rows = [];
        let row = [], width = 0;
        for (const b of items) {
          if (row.length && width + GAP + b.w > DIA_W) { rows.push(row); row = []; width = 0; }
          width += (row.length ? GAP : 0) + b.w;
          row.push(b);
        }
        if (row.length) rows.push(row);
        return rows;
      };
      const place = (row, y) => {
        const width = row.reduce((n, b) => n + b.w, 0) + GAP * (row.length - 1);
        let x = (DIA_W - width) / 2;
        for (const b of row) { b.x = x; b.y = y; x += b.w + GAP; }
      };
      const targets = rel.target || [];
      const sources = rel.source || [];
      const up = pack(page(entries(targets, "t"), "t"));
      const down = pack(page(entries(sources, "s"), "s"));
      const rootLabel = cut(this.rootTitle || this.rootUuid, LABEL_CHARS);
      const refs = "References (" + targets.length + ")";
      const refsBy = "Referenced by (" + sources.length + ")";
      const root = sized({
        key: "root", kind: "root", uuid: this.rootUuid, label: rootLabel,
        typeLabel: shortType(this.rootType), refs, refsBy, h: RBH,
        tip: (this.rootTitle || this.rootUuid) + " — " + (this.rootType || "") + " — "
             + this.rootUuid + " — " + refs + ", " + refsBy.toLowerCase(),
      }, [rootLabel, shortType(this.rootType), refsBy]);
      const step = BH + ROW_GAP;
      const top = 10;
      // the rows above, the nearest to the root last in y
      up.forEach((row, i) => place(row, top + (up.length - 1 - i) * step));
      const rootY = top + up.length * step;
      place([root], rootY);
      down.forEach((row, i) => place(row, rootY + RBH + ROW_GAP + i * step));
      const h = rootY + RBH + (down.length ? ROW_GAP + down.length * step - ROW_GAP : 0) + 10;
      const edges = [];
      // the arrows leave / reach the root spread along its edge; a series'
      // members and the "more" boxes have none of their own
      const linked = (b) => b.kind === "obj" || b.kind === "group";
      const at = (k, n) => root.x + 10 + (root.w - 20) * (n === 1 ? 0.5 : k / (n - 1));
      const ups = up.flat(), downs = down.flat();
      const upL = ups.filter(linked), downL = downs.filter(linked);
      upL.forEach((b, k) => edges.push({
        key: "e" + b.key, by: false, x1: at(k, upL.length), y1: rootY,
        x2: b.x + b.w / 2, y2: b.y + BH }));
      downL.forEach((b, k) => edges.push({
        key: "e" + b.key, by: true, x1: b.x + b.w / 2, y1: b.y,
        x2: at(k, downL.length), y2: rootY + RBH }));
      return { w: DIA_W, h, edges, boxes: [...ups, root, ...downs] };
    },
    /*
     * The visible rows, depth-first. A row's key is its PATH ("a/b/c"), not
     * its uuid: the same object reached two ways is two rows, each opening
     * on its own, and the path is also what tells a cycle from a repeat.
     */
    rows() {
      const out = [];
      const walk = (uuid, title, type, partial, depth, path, seen) => {
        const key = path;
        const loop = seen.has(uuid);
        out.push({
          key, depth, uuid, type, partial, loop,
          title, label: title || uuid,
          canOpen: !loop,
          waiting: !loop && this.isOpen(key) && !this.relations[uuid],
          group: false, count: "",
        });
        if (loop || !this.isOpen(key)) return;
        const rel = this.relations[uuid];
        if (!rel) return;
        const next = new Set(seen);
        next.add(uuid);
        for (const g of GROUPS) {
          const items = rel[g.dir] || [];
          const gkey = key + "!" + g.dir;
          out.push({
            key: gkey, depth: depth + 1, group: true, label: g.label,
            count: items.length ? "(" + items.length + ")" : "(none)",
            canOpen: items.length > 0, uuid: "", type: "", title: "",
            partial: false, loop: false, waiting: false,
          });
          if (!items.length || !this.isOpen(gkey)) continue;
          for (const it of items) {
            walk(it.uuid, it.title, it.type, it.partial, depth + 2,
                 gkey + "/" + it.uuid, next);
          }
        }
      };
      if (this.rootUuid) {
        walk(this.rootUuid, this.rootTitle, this.rootType, false, 0,
             this.rootUuid, new Set());
      }
      return out;
    },
  },
  mounted() {
    // The root opens on its own: a graph view that shows one closed row
    // tells the reader nothing.
    if (this.rootUuid) this.toggle({ key: this.rootUuid, uuid: this.rootUuid, group: false });
  },
  methods: {
    shortType,
    // a box of the diagram: an object opens in a tab, a series opens into
    // its members (or folds back), "more" draws the next page of its side
    onBox(b) {
      if (b.kind === "obj" || b.kind === "member") {
        this.$emit("follow", { uuid: b.uuid, title: b.title });
      } else if (b.kind === "group") {
        this.expanded = b.open ? this.expanded.filter((k) => k !== b.gkey)
          : this.expanded.concat([b.gkey]);
      } else if (b.kind === "more") {
        this.more = { ...this.more, [b.side]: this.more[b.side] + PAGE };
      }
    },
    // a right-click on an object's box: its XML beside the graph
    onBoxRaw(b) {
      if (b.kind === "obj" || b.kind === "member") this.showRaw(b);
    },
    showRaw(o) {
      // a member of a series is named with its step or realization: the
      // readings of GasSat t1 and t2 side by side must say which is which
      const title = (o.title || "") + (o.idx ? " · " + o.idx : "");
      this.$emit("raw", { uuid: o.uuid, title, type: o.type || "", action: "show" });
    },
    isOpen(key) { return this.open.indexOf(key) >= 0; },
    toggle(row) {
      const i = this.open.indexOf(row.key);
      if (i >= 0) {
        // closing an object forgets its groups, so reopening it opens them again
        this.open = this.open.filter((k) => k !== row.key && !k.startsWith(row.key + "!"));
        return;
      }
      // An object opens with its two groups open (the manager, 15/10: an
      // object showing two closed rows "References (3)" and "Referenced by
      // (2)" asked for two more clicks before showing anything).
      this.open = this.open.concat(row.group ? [row.key]
        : [row.key].concat(GROUPS.map((g) => row.key + "!" + g.dir)));
      // A group row carries no object; an object row whose relations are not
      // held yet asks the host for them.
      if (!row.group && row.uuid && !this.relations[row.uuid]) {
        this.$emit("need", row.uuid);
      }
    },
  },
};
</script>

<style scoped>
/* The same frame, type and row height as the Tree reading (XmlBody): going
   from one reading to the other changes what is shown, not the size of
   everything (the PO, 15/10). */
.fxr { display: flex; flex-direction: column; gap: 5px; min-height: 0; flex: 1 1 auto;
  font-family: system-ui, sans-serif; font-size: 11px; }
.fxr-how { padding: 0 2px; font-size: 11px; }
.fxr-body { display: flex; gap: 6px; flex: 1 1 auto; min-height: 0; }
.fxr-wrap { flex: 1 1 60%; min-width: 0; min-height: 80px; overflow: auto; border: 1px solid #e0e6ee; border-radius: 3px; }
.fxr-rows { width: 100%; border-collapse: collapse; font-size: 11px; }
.fxr-rows tr:nth-child(even) { background: var(--fp-line-faint); }
.fxr-c { padding: 1px 4px; white-space: nowrap; border-bottom: 1px solid #f4f6f8; }
.fxr-caret { width: 16px; display: inline-block; text-align: center;
  color: var(--fp-ink-soft); }
.fxr-caret-void { visibility: hidden; }
.fxr-group-name { font-weight: 600; }
.fxr-root { font-weight: 600; color: var(--fp-ink); }
.fxr-muted { color: var(--fp-ink-soft); font-size: 11px; margin-left: 6px; }
.fxr-type { font-family: ui-monospace, Consolas, monospace; }
.fxr-partial, .fxr-loop { font-style: italic; }
.fxr-top { display: flex; align-items: center; gap: 8px; flex: 0 0 auto; }
.fxr-top .fxr-how { flex: 1 1 auto; min-width: 0; }
/* the diagram: Doxygen's collaboration diagram, in the app's ink; every
   arrow dashed (the PO, 16/10) */
.fxr-dia-wrap { padding: 6px; background: #fff; }
.fxr-dia-wait { padding: 8px; }
.fxr-svg { display: block; width: 100%; height: auto; margin: 0 auto; }
.fxr-edge-ref { stroke: #4f9fe8; stroke-width: 1.4; stroke-dasharray: 5 3; }
.fxr-edge-by { stroke: #9b4fd1; stroke-width: 1.4; stroke-dasharray: 5 3; }
.fxr-box rect { fill: #fff; stroke: #4a4f57; stroke-width: 1; }
.fxr-box { cursor: pointer; outline: none; }
.fxr-box:hover rect, .fxr-box:focus-visible rect { stroke: var(--fp-accent); stroke-width: 2; fill: #eef4fb; }
.fxr-box-root { cursor: default; }
.fxr-box-root rect, .fxr-box-root:hover rect { fill: #a9adb3; stroke: #4a4f57; stroke-width: 1; }
.fxr-box-partial rect { stroke-dasharray: 4 3; }
/* a series: a stack of frames; its members, once open, tinted like it */
.fxr-box-group rect.fxr-stack, .fxr-box-group:hover rect.fxr-stack { fill: #f3f8e9; stroke: #8a9a6a; stroke-width: 1; }
.fxr-box-group rect { fill: #f3f8e9; stroke: #6b7d45; }
.fxr-box-member rect { fill: #f3f8e9; stroke: #9aab78; }
.fxr-box-more rect { fill: #fff; stroke: var(--fp-accent); stroke-dasharray: 3 3; }
.fxr-box-more .fxr-box-t { fill: var(--fp-accent); }
.fxr-box-t { font: 600 11px system-ui, sans-serif; fill: var(--fp-ink); pointer-events: none; }
.fxr-box-ty { font: 10px ui-monospace, Consolas, monospace; fill: var(--fp-ink-soft); pointer-events: none; }
.fxr-box-n { font: 600 10px system-ui, sans-serif; fill: #2b2f35; pointer-events: none; }
.fxr-box-root .fxr-box-ty { fill: #2b2f35; }
.fxr-box-partial .fxr-box-t { fill: var(--fp-ink-soft); font-style: italic; }
/* the objects read beside the graph */
.fxr-raws { flex: 0 0 40%; min-width: 240px; display: flex; flex-direction: column; gap: 6px; overflow: auto; }
.fxr-raw { display: flex; flex-direction: column; gap: 4px; min-height: 160px; max-height: 340px; flex: 0 0 auto;
  padding: 4px; border: 1px solid #e0e6ee; border-radius: 3px; background: #fff; }
.fxr-raw-pinned { border-color: var(--fp-accent); box-shadow: inset 3px 0 0 var(--fp-accent); }
.fxr-pin { color: var(--fp-ink-soft, #555); }
.fxr-pin.fxr-pin-on { color: var(--fp-accent); }
.fxr-raw-top { display: flex; align-items: center; gap: 6px; flex: 0 0 auto; }
.fxr-raw-t { flex: 1 1 auto; min-width: 0; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
