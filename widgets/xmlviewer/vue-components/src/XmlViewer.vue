<template>
  <!-- The explorer view wears the panel frame: title, the two readings, the
       export. Inside an Attributes card the card frame is the title, so the
       same viewer draws only its controls row. -->
  <fp-panel v-if="framed" class="fxv" title="Explorer"
            title-tip="One RESQML object as fesapi holds it, the same over a local EPC and over ETP: a readable tree, or the raw text"
            :summary="current.title || ''" :scroll="false">
    <template #controls>
      <fp-seg v-model="mode" :options="MODES" title="How the object is read" />
    </template>
    <template #export>
      <fp-export label="Copy RAW" mime="application/xml" :filename="fileName" :build="() => xml || ''"
                 :disabled="!xml" disabled-why="there is no object to copy yet"
                 fail-hint="select the text and copy it"
                 title="Copy the raw text, the object's bytes verbatim — a download when the browser offers no clipboard (plain http)" />
    </template>
    <template v-if="note" #notes>
      <fp-note severity="warning" :text="note" />
    </template>
    <div class="fxv-in">
      <!-- The add row: adds any object of the repository as a new tab, by
           title, type or uuid, so the explorer stands on its own instead of
           opening only from another view's gesture. What it does is ADD a
           tab, so it says so (the PO, 15/10: it read as a "find"). -->
      <div class="fxv-find">
        <input class="fp-input fxv-find-in" type="text" :value="query"
               placeholder="Add an object: title, type or uuid"
               title="Every word typed must appear in the object's title, type or uuid; pick one below to add it as a new tab"
               @input="onQuery($event.target.value)" />
        <span v-if="hitState.query" class="fp-sum fxv-find-n"
              :title="hitState.total + ' object(s) match; the first ' + hitState.hits.length + ' are listed'">
          {{ hitState.hits.length < hitState.total ? hitState.hits.length + " of " + hitState.total : hitState.total }} to add
        </span>
      </div>
      <fp-note v-if="hitState.note" severity="warning" :text="hitState.note" />
      <div v-if="hitState.query && !hitState.note" class="fxv-hits" role="list">
        <button v-for="h in hitState.hits" :key="h.uuid" type="button" class="fxv-hit" role="listitem"
                :title="'Add ' + h.title + ' (' + h.type + ') as a new tab — ' + h.uuid + (h.partial ? ' — a reference only, not in the loaded data' : '')"
                @click="$emit('pick', h)">
          <span class="fxv-hit-t" :class="{ 'fxv-muted': h.partial }">{{ h.title }}</span>
          <fp-chip sm variant="line" :text="h.type" :title="'RESQML type: ' + h.type" />
          <fp-chip v-if="h.partial" sm variant="line" text="reference only" title="A partial stub: the file names it but does not carry it" />
          <span class="fxv-hit-u fxv-muted">{{ h.uuid.slice(0, 8) }}</span>
        </button>
        <span v-if="!hitState.hits.length" class="fp-sum">No object matches “{{ hitState.query }}”.</span>
      </div>
      <!-- Tabs, explorer only. Descending a reference chain is easy; coming
           back is not, and a breadcrumb alone loses the branch left behind.
           A tab keeps a whole navigation stack alive. Tabs are open
           documents, not readings of one document, so they are chrome and
           not a segmented control (UI rule R13, see
           doc/wiki/UI-Drawer-Toolbar-Shared.md). -->
      <div v-if="(tabs || []).length" class="fxv-tabs">
        <button v-for="(t, i) in tabs" :key="i" type="button" class="fxv-tab"
                :class="{ 'fxv-tab-on': i === activeTab }"
                :title="'Read ' + (t.title || 'this object') + ' and the references walked from it'"
                @click="$emit('select-tab', i)">
          <span class="fxv-tab-t">{{ t.title || "object" }}</span>
          <span v-if="tabs.length > 1" class="fxv-x" title="Close this tab"
                @click.stop="$emit('close-tab', i)">×</span>
        </button>
      </div>
      <!-- the stack of THIS tab: click any step to come back to it. One line
           of one height in every tab (it scrolls rather than wraps), drawn
           as soon as a tab is open, so switching tabs never moves what is
           below it. The "+" that copied the tab in front is gone (the PO,
           15/10): a copy of what is shown added nothing. -->
      <div v-if="(tabs || []).length && (trail || []).length" class="fxv-trail fxv-trail-fixed">
        <template v-for="(c, i) in trail" :key="i">
          <span v-if="i" class="fxv-muted">&#8250;</span>
          <button type="button" class="fxv-crumb" :class="{ 'fxv-crumb-on': i === trail.length - 1 }"
                  :title="'Back to ' + (c.title || c.uuid)" @click="$emit('back', i + 1)">{{ c.title || c.uuid }}</button>
        </template>
      </div>
      <xml-relations v-if="mode === 'graph'"
                     :root-uuid="current.uuid || ''" :root-title="current.title || ''"
                     :root-type="current.type || ''"
                     :relations="relations" :supported="relationsSupported"
                     :raws="raws"
                     @need="$emit('need-relations', $event)"
                     @raw="$emit('raw', $event)"
                     @follow="$emit('follow', $event)" />
      <xml-body v-else :xml="xml" :mode="mode" :empty-label="emptyLabel" @follow="$emit('follow', $event)" />
    </div>
  </fp-panel>

  <div v-else class="fxv fxv-in">
    <div class="fxv-nav">
      <!-- the stack of THIS tab: click any step to come back to it -->
      <div v-if="(trail || []).length > 1" class="fxv-trail">
        <template v-for="(c, i) in trail" :key="i">
          <span v-if="i" class="fxv-muted">&#8250;</span>
          <button type="button" class="fxv-crumb" :class="{ 'fxv-crumb-on': i === trail.length - 1 }"
                  :title="'Back to ' + (c.title || c.uuid)" @click="$emit('back', i + 1)">{{ c.title || c.uuid }}</button>
        </template>
      </div>
      <span class="fxv-right">
        <fp-seg v-model="mode" :options="MODES" title="How the object is read" />
        <fp-export label="Copy RAW" mime="application/xml" :filename="fileName" :build="() => xml || ''"
                   :disabled="!xml" disabled-why="there is no object to copy yet"
                   fail-hint="select the text and copy it"
                   title="Copy the raw text, the object's bytes verbatim — a download when the browser offers no clipboard (plain http)" />
      </span>
    </div>
    <fp-note v-if="note" severity="warning" :text="note" />
    <xml-relations v-if="mode === 'graph'"
                   :root-uuid="current.uuid || ''" :root-title="current.title || ''"
                   :root-type="current.type || ''"
                   :relations="relations" :supported="relationsSupported"
                   :raws="raws"
                   @need="$emit('need-relations', $event)"
                   @raw="$emit('raw', $event)"
                   @follow="$emit('follow', $event)" />
    <xml-body v-else :xml="xml" :mode="mode" :empty-label="emptyLabel" @follow="$emit('follow', $event)" />
  </div>
</template>

<script>
/*
 * XmlViewer — one RESQML object, two ways: a readable tree and the raw text.
 *
 * Mounted BOTH in the per-view Attributes card and in the XML explorer view,
 * which is why it is a widget of its own rather than a section of either: the
 * two would otherwise drift apart, and the tree walk is the part that must
 * not. The walk itself is XmlBody, the Graph reading is XmlRelations; this is
 * the frame around them.
 *
 *   props  — xml (the object's serialized XML), trail (the stack of
 *            references walked to reach it), tabs/activeTab (explorer only),
 *            note (why a follow led nowhere), emptyLabel (the gesture that
 *            fills the empty state), framed (the explorer: the panel frame
 *            with its title; off inside a card, whose frame is the title),
 *            hits ({query, hits:[{uuid,title,type,partial}], total, note}:
 *            the answer to the last search, explorer only),
 *            relations / relationsSupported / raws (the Graph reading, see
 *            XmlRelations).
 *   events — follow({uuid,title}) a DataObjectReference was clicked;
 *            back(depth) a breadcrumb step; select-tab / close-tab / new-tab;
 *            search(text) the find row changed (debounced); pick(hit) a
 *            found object was chosen; need-relations(uuid) the Graph reading
 *            asks for the relations of one object; raw({uuid, title, type,
 *            action}) an object's XML beside the graph, pinned, or closed.
 *
 * The host owns every piece of that state: this component fetches nothing.
 */
import FpChip from "../../../_shared/components/FpChip.vue";
import FpExport from "../../../_shared/components/FpExport.vue";
import FpNote from "../../../_shared/components/FpNote.vue";
import FpPanel from "../../../_shared/components/FpPanel.vue";
import FpSeg from "../../../_shared/components/FpSeg.vue";
import XmlBody from "./XmlBody.vue";
import XmlRelations from "./XmlRelations.vue";

const MODES = [
  { value: "tree", label: "Tree", title: "The object as a tree of fields, folded and filterable" },
  { value: "raw", label: "Raw", title: "The text of the object as fesapi wrote it" },
  // The only reading that leaves the object: the two others read its bytes,
  // and half of its neighbourhood is not in them, since a
  // DataObjectReference is written in the XML of the object that POINTS.
  { value: "graph", label: "Graph", title: "What this object designates, and what designates it — walkable" },
];

export default {
  name: "XmlViewer",
  components: { FpChip, FpExport, FpNote, FpPanel, FpSeg, XmlBody, XmlRelations },
  props: {
    xml: { type: String, default: "" },
    trail: { type: Array, default: () => [] },
    tabs: { type: Array, default: () => [] },
    activeTab: { type: Number, default: 0 },
    note: { type: String, default: "" },
    emptyLabel: {
      type: String,
      default: "Click a node that is a RESQML object in the tree — a folder or an aggregate the tree builds is no object of the file.",
    },
    framed: { type: Boolean, default: false },
    hits: { type: Object, default: () => ({}) },
    // The Graph reading: the relations the host has fetched so far, and
    // whether this plugin build answers the relationship query at all.
    relations: { type: Object, default: () => ({}) },
    relationsSupported: { type: Boolean, default: true },
    // objects read beside the graph, a right-click away (see XmlRelations)
    raws: { type: Array, default: () => [] },
  },
  emits: ["follow", "back", "select-tab", "close-tab", "new-tab", "search",
          "pick", "need-relations", "raw"],
  data() {
    return { mode: "tree", MODES, query: "", timer: null };
  },
  watch: {
    // The host cleared the list (an object was picked): clear the find row too.
    hits(h) {
      if (h && !h.query && this.query) this.query = "";
    },
  },
  methods: {
    onQuery(text) {
      this.query = text;
      clearTimeout(this.timer);
      this.timer = setTimeout(() => this.$emit("search", this.query.trim()), 250);
    },
  },
  computed: {
    hitState() {
      const h = this.hits || {};
      return { query: h.query || "", hits: h.hits || [], total: h.total || 0, note: h.note || "" };
    },
    current() {
      return (this.trail || [])[(this.trail || []).length - 1] || {};
    },
    // The export is the object's bytes verbatim, named after its title (or
    // uuid): an XML file carries its own provenance.
    fileName() {
      const name = (this.current.title || this.current.uuid || "object").replace(/[^\w.-]+/g, "_");
      return name + ".xml";
    },
  },
};
</script>

<style>
/* first: an @import after any rule is ignored, and the bundle then
   shipped without the kit's sheet */
@import "../../../_shared/panel.css";
.fxv-find { display: flex; align-items: center; gap: 8px; padding: 4px 8px; }
.fxv-find-in { flex: 1 1 auto; }
.fxv-find-n { white-space: nowrap; }
.fxv-hits { display: flex; flex-direction: column; gap: 2px; padding: 0 8px 6px; max-height: 40%; overflow: auto; }
.fxv-hit { display: flex; align-items: center; gap: 8px; padding: 3px 6px; border: 1px solid var(--fp-field-line); border-radius: 3px; background: var(--fp-bg); font: inherit; text-align: left; cursor: pointer; }
.fxv-hit:hover { background: var(--fp-bg-hover, #f3f5f8); }
.fxv-hit-t { flex: 1 1 auto; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fxv-hit-u { font-family: ui-monospace, monospace; font-size: 11px; }
/* A reference chip that opens its object (XmlBody, XmlRelations): the bare
   button around it draws nothing of its own; the chip lights up under the
   pointer and shows the keyboard focus. */
.fp-btn.fx-link { padding: 0; border: 0; background: none; min-height: 0; height: auto; cursor: pointer; vertical-align: middle; }
.fp-btn.fx-link:hover .fp-chip { border-color: var(--fp-accent); background: var(--fp-bg-hover, #eef4fb); }
.fp-btn.fx-link:focus-visible { outline: 2px solid var(--fp-accent); outline-offset: 1px; border-radius: 3px; }
.fx-link-arrow { margin-left: 4px; color: var(--fp-accent); }
</style>

<style scoped>
.fxv-in { display: flex; flex-direction: column; gap: 5px; flex: 1 1 auto; height: 100%; min-height: 0; font-family: system-ui, sans-serif; font-size: 13px; box-sizing: border-box; }
.fxv-tabs { display: flex; gap: 2px; flex: 0 0 auto; overflow-x: auto; border-bottom: 1px solid #e0e6ee; padding-bottom: 3px; }
.fxv-tab { display: flex; align-items: center; gap: 5px; font-size: 11px; padding: 2px 7px; background: #f5f7fa; border: 1px solid #e0e6ee; border-radius: 3px 3px 0 0; color: #55606e; cursor: pointer; white-space: nowrap; max-width: 190px; }
.fxv-tab-on { background: var(--fp-accent); border-color: var(--fp-accent); color: #fff; }
.fxv-tab-t { overflow: hidden; text-overflow: ellipsis; }
.fxv-x { opacity: 0.6; }
.fxv-x:hover { opacity: 1; }
.fxv-nav { display: flex; align-items: center; gap: 6px; flex: 0 0 auto; flex-wrap: wrap; }
.fxv-trail { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; flex: 1 1 auto; min-width: 0; }
.fxv-trail-fixed { flex: 0 0 auto; flex-wrap: nowrap; overflow-x: auto; overflow-y: hidden; height: 24px; }
.fxv-trail-fixed .fxv-crumb, .fxv-trail-fixed .fxv-muted { flex: 0 0 auto; }
.fxv-crumb { font-size: 11px; padding: 1px 6px; background: #fff; border: 1px solid #cfd8e3; border-radius: 3px; color: var(--fp-accent); cursor: pointer; max-width: 170px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fxv-crumb-on { background: #eef4fb; font-weight: 600; }
.fxv-right { display: flex; align-items: center; gap: 6px; margin-left: auto; }
.fxv-muted { color: #999; font-size: 11px; }
</style>
