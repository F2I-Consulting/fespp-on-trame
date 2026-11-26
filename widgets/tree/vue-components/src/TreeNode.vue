<template>
  <div class="tn">
    <div
      class="tn-row"
      :class="{ active: isActive, 'tn-extract-row': node.session === 'extract' }"
      :style="{ paddingLeft: (depth + (node.under ? 1 : 0)) * 16 + 4 + 'px' }"
      tabindex="0"
      :data-path="node.path"
      :title="tooltip"
      @click.capture="handlers.touch && handlers.touch(node.path)"
      @click="handlers.activate(node.path)"
      @contextmenu.prevent="handlers.context(node, $event)"
    >
      <span class="tn-caret" @click.stop="handlers.toggleExpand(node.path)">
        <template v-if="hasChildren">{{ isOpen ? "▾" : "▸" }}</template>
      </span>
      <span
        v-if="!node.disabled && !node.session && !node.noCheck"
        class="tn-check"
        @click.stop="handlers.toggleSelect(node.path)"
      >{{ checkGlyph }}</span>
      <!-- a row the session made has no box to tick: it exists only here;
           its × sits where the box would (the PO, 20/10) -->
      <span v-else-if="node.session && node.sessionRemovable !== false" class="tn-check tn-x"
            :title="node.session === 'extract' ? 'Delete this extract (the object is drawn whole again)' : 'Delete this derived property'"
            @click.stop="handlers.sessionRemove(node)">×</span>
      <span v-else-if="node.session || node.noCheck" class="tn-check"></span>
      <fp-icon
        class="tn-icon"
        :class="{ 'tn-icon-warn': node.partial }"
        :icon="icon"
        :size="15"
        :declared="declaredColour"
        :disabled="!!node.disabled"
      />
      <!-- the colour the object is drawn in when no property colours it:
           which row is which object in 3D, at a glance -->
      <span v-if="chipColour" class="tn-chip tn-chip-edit" :style="{ background: chipColour }"
            title="Drawn in this color when no property colors it — click to change it, and the opacity of the object, in the Colormap card"
            @click.stop="handlers.color(node, 'solid')"></span>
      <template v-if="colorEditing">
        <span
          v-if="node.color"
          class="tn-swatch"
          :class="{ 'tn-cmap-off': !isSelected }"
          :style="{ background: node.color }"
          :title="isSelected ? 'Edit color' : 'Load (check) to edit the color'"
          @click.stop="isSelected && handlers.color(node, 'solid')"
        ></span>
      </template>
      <!-- depth or time, on the object where its domain starts, when the
           file holds both (the PO, 28/10); no tooltip on depth vs time (the
           manager, 29/10) -->
      <!-- one tag: drawn converted, the T→D says the domain too -->
      <span v-if="ownDomain && !converted.has(node.path)" class="tn-tag" :class="'tn-tag-' + ownDomain"
            :data-click="convertible ? '' : null"
            :title="convertible ? 'Only in its own domain here: click to draw it converted in this view'
              : fixed.has(node.path) ? (ownDomain === 'time' ? 'Nothing of the Seismic tree is converted: a view in time draws it'
                                                             : 'In depth: a view in time draws time alone')
              : (ownDomain === 'time' ? 'In time: its vertical axis is a seismic two-way time' : 'In depth')"
            @click="convertible && handlers.domainToggle(node)">{{ ownDomain === 'time' ? 'T' : 'D' }}</span>
      <span v-if="converted.has(node.path)" class="tn-tag tn-tag-conv" :class="node.vdomain === 'time' ? 'tn-conv-td' : 'tn-conv-dt'"
            data-click :title="'Drawn converted for this view with the time-depth law: in ' + (node.vdomain || 'the other domain') + ', shown in the view\'s domain. Click: only in its own domain'"
            @click.stop="handlers.domainToggle(node)">{{ node.vdomain === 'time' ? 'T→D' : 'D→T' }}</span>
      <span v-if="isMR" class="tn-tag tn-tag-mr" title="Multi-realization">MR</span>
      <span v-if="Number(node.componentCount) > 1" class="tn-tag tn-tag-vec"
            :title="'Vector property: ' + node.componentCount + ' values per element'">×{{ node.componentCount }}</span>
      <fp-icon v-if="isTS" class="tn-tag-ts" :icon="icons._ts" :size="13" title="Time series" />
      <span v-if="node.partial" class="tn-partial" :title="node.info || 'Partial — reference stub, not loadable'">PARTIAL</span>
      <span v-else-if="node.unreachable" class="tn-partial" :title="node.info">NOT IN 3D</span>
      <!-- made in the session, not in the file (the PO, 15/10): its own
           colour and a tag, "disposable" -->
      <!-- an extract says what it is by its colour and its icon (the PO,
           20/10): only a derived property keeps the word -->
      <span v-if="node.session && node.session !== 'extract'" class="tn-tag tn-tag-session"
            title="Made in this session — not in the file, never exported; gone when the session ends">session</span>
      <input v-if="renaming" ref="rename" class="tn-rename" :value="draft"
             :aria-label="'New name of ' + node.title"
             @input="draft = $event.target.value" @click.stop
             @keydown.enter.prevent="commitRename" @keydown.esc.prevent.stop="renaming = false"
             @blur="commitRename" />
      <span v-else class="tn-title" :class="{ 'tn-muted': node.disabled, 'tn-session': node.session, 'tn-title-tight': handlers.isActiveModel(node) }">{{ node.title }}</span>
      <span v-if="handlers.isActiveModel(node) && !renaming" class="tn-active-model"
            title="The velocity model the time to depth conversions read">(active T→D)</span>
      <!-- an extract is named by the reader: the pencil writes its name -->
      <span v-if="node.session === 'extract' && node.sessionRemovable !== false && !renaming"
            class="tn-pencil" title="Rename" @click.stop="startRename">✎</span>
      <!-- its eye goes right, under the other eyes -->
      <span v-if="node.session === 'extract'" class="tn-spacer"></span>
      <!-- while cells of this grid are highlighted: keep them, or remove
           them, as a new object under the grid — the two acts offered
           directly, no "+" to open first (the PO, 16/10) -->
      <template v-if="selCount > 0">
        <span class="tn-pick" :title="'Keep only the ' + selCount + ' highlighted cell(s) of this grid, as a new object under it'"
              @click.stop="handlers.extract(node, 'keep')">Keep</span>
        <span class="tn-pick" :title="'Take the ' + selCount + ' highlighted cell(s) out of this grid, as a new object under it'"
              @click.stop="handlers.extract(node, 'remove')">Remove</span>
      </template>
      <span v-if="loadMark" class="tn-load" :class="'tn-load-' + node.loadState"
            :title="node.info || ''" :aria-label="loadWord">{{ loadMark }}</span>
      <span v-if="loadedBadge" class="tn-badge" :title="loadedBadge + ' loaded below'">{{ loadedBadge }}</span>
      <span
        v-if="showEye"
        class="tn-eye"
        :title="isVisible ? 'Hide' : 'Show'"
        @click.stop="handlers.toggleVisible(node.path)"
      ><svg viewBox="0 0 24 24" width="15" height="15"><path v-if="isVisible" :d="icons._eyeFull" fill="currentColor" /><template v-else><path :d="icons._eyeOutline" fill="currentColor" /><path d="M4.5 20.5 L19.5 3.5" stroke="#000000" stroke-width="2.4" stroke-linecap="round" fill="none" /></template></svg></span>
      <!-- a session extract: its own eye (the grid gives it its place in
           the view) and its ×; a derived property: its × -->
      <span
        v-if="node.session === 'extract' || node.session === 'derived'"
        class="tn-eye"
        :title="node.sessionEyeTitles ? node.sessionEyeTitles[node.sessionVisible ? 1 : 0]
          : (node.sessionVisible ? 'Hide (the grid is drawn again)'
          : (node.session === 'derived' ? 'Show the grid colored by this formula (in place of the grid)' : 'Show (in place of the grid)'))"
        @click.stop="handlers.sessionEye(node)"
      ><svg viewBox="0 0 24 24" width="15" height="15"><path v-if="node.sessionVisible" :d="icons._eyeFull" fill="currentColor" /><template v-else><path :d="icons._eyeOutline" fill="currentColor" /><path d="M4.5 20.5 L19.5 3.5" stroke="#000000" stroke-width="2.4" stroke-linecap="round" fill="none" /></template></svg></span>
    </div>
    <template v-if="hasChildren && isOpen">
      <TreeNode
        v-for="c in node.children"
        :key="c.path"
        :node="c"
        :depth="depth + 1"
        :selected="selected"
        :visible="visible"
        :converted="converted"
        :undrawn="undrawn"
        :fixed="fixed"
        :eyeable="eyeable"
        :expanded="expanded"
        :force-open="forceOpen"
        :active="active"
        :icons="icons"
        :color-editing="colorEditing"
        :handlers="handlers"
      />
    </template>
  </div>
</template>

<script>
// Recursive node row. Renders itself, then its children when expanded.
// Identity is the node `path` (the vtkDataAssembly path). Membership sets
// (selected / visible) hold paths; actions go through `handlers`.
//
// Node shape (parsed from the assembly XML by DataExplorerTree): { path,
// title, type, eye, color?, colorRGB?, loadState?, propType?, family?,
// children, disabled?, partial?, unreachable?, crs?/dims?/count?/units?/info? }.
import FpIcon from "../../../_shared/components/FpIcon.vue";

export default {
  name: "TreeNode",
  components: { FpIcon },
  props: {
    node: { type: Object, required: true },
    depth: { type: Number, default: 0 },
    selected: { type: Set, required: true },   // loaded paths
    visible: { type: Set, required: true },    // visible paths
    converted: { type: Set, default: () => new Set() },  // drawn converted with the law
    undrawn: { type: Set, default: () => new Set() },    // of the other domain, not drawn: no eye
    fixed: { type: Set, default: () => new Set() },      // those of them the view never converts
    // Which nodes MAY carry an eye, when the checkbox is not the gate: a
    // tree whose tick means something other than loading passes the paths
    // the session can actually show. `null` = the checkbox is the gate.
    eyeable: { type: Set, default: null },
    expanded: { type: Object, required: true },
    forceOpen: { type: Boolean, default: false },
    active: { default: null },                 // active path
    icons: { type: Object, default: () => ({}) },
    colorEditing: { type: Boolean, default: false },
    handlers: { type: Object, required: true },
  },
  data() {
    return { renaming: false, draft: "" };
  },
  computed: {
    // the solid colour of a loaded representation (its grid folder too)
    chipColour() {
      return this.handlers.solidColour ? this.handlers.solidColour(this.node.path) : "";
    },
    // highlighted cells of this row's grid (Keep / Remove offered while > 0)
    selCount() {
      return this.handlers.selCount ? this.handlers.selCount(this.node.path) : 0;
    },
    hasChildren() {
      return Array.isArray(this.node.children) && this.node.children.length > 0;
    },
    // the domain its tag says: where its domain starts, or on any row kept in
    // it — never on a property (a log, a grid's property): what has no
    // geometry is neither in depth nor in time
    ownDomain() {
      if (this.node.eye === "array" || this.node.logChannel) return "";
      return this.node.domainTag || (this.undrawn.has(this.node.path) ? this.node.vdomain : "");
    },
    // kept in its own domain here, and a click on its tag draws it converted
    convertible() { return this.undrawn.has(this.node.path) && !this.fixed.has(this.node.path); },
    isOpen() { return this.forceOpen || !!this.expanded[this.node.path]; },
    isSelected() { return this.selected.has(this.node.path); },
    // EVERY node with children shows a tri-state reflecting its subtree:
    // full when all selectable leaves are checked, intermediate when some
    // are. Leaves reflect their own selection.
    checkGlyph() {
      if (this.node.selectChildren || this.hasChildren) {
        const s = this.containerState;
        if (s === "some") return "▣";
        if (s === "all") return "☑";
        return this.isSelected ? "☑" : "☐";
      }
      return this.isSelected ? "☑" : "☐";
    },
    containerState() {
      let total = 0, sel = 0;
      const walk = (nodes) => {
        for (const n of nodes || []) {
          if (n.children && n.children.length) walk(n.children);
          else if (!n.disabled && !n.noCheck && !n.session) { total++; if (this.selected.has(n.path)) sel++; }
        }
      };
      walk(this.node.children);
      if (!total || sel === 0) return "none";
      return sel === total ? "all" : "some";
    },
    // Every loaded, eye-bearing leaf of this subtree (the node itself when it
    // is one) — a folder's eye drives them all.
    eyeLeaves() {
      const out = [];
      const walk = (n) => {
        const kids = n.children || [];
        const own = n.eye && this.canEye(n.path);
        if (own && (!kids.length || !kids.some((c) => c.eye))) {
          out.push(n.path);
          return;
        }
        for (const c of kids) walk(c);
      };
      walk(this.node);
      return out;
    },
    // True when this node's eye drives OTHER nodes rather than itself.
    isFolderEye() {
      const l = this.eyeLeaves;
      return l.length > 0 && !(l.length === 1 && l[0] === this.node.path);
    },
    // A loaded rep / marker / Frame-primary channel shows a visibility eye —
    // and so does any folder holding such leaves, which it then drives.
    showEye() {
      if (this.isFolderEye) return true;
      if (!this.canEye(this.node.path)) return false;
      return this.node.eye === "rep" || this.node.eye === "marker"
        || this.node.eye === "array" || !!this.node.frameEye;
    },
    // A folder reads as "on" as soon as one of its leaves is shown.
    isVisible() {
      if (this.isFolderEye) {
        return this.eyeLeaves.some((p) => this.visible.has(p));
      }
      return this.visible.has(this.node.path);
    },
    // A tree may list a property the session has not read (the Statistics
    // view's does). "Not read yet" is what the empty checkbox already says,
    // so it carries no mark at all; the two states a checkbox CANNOT say —
    // a read in flight, a read that failed — carry one discreet character,
    // with the sentence and the next step in the row tooltip (`info`).
    loadMark() {
      return { loading: "\u2026", failed: "!" }[this.node.loadState] || "";
    },
    loadWord() {
      return { loading: "loading", failed: "read failed" }[this.node.loadState] || "";
    },
    isActive() { return this.active != null && this.node.path === this.active; },
    // The colour the FILE declares for this object (RESQML
    // GraphicalInformationSet, "R,G,B" on the node): the icon then wears it
    // instead of its family colour, so the row says what the 3D view shows.
    // A partial row keeps the warning colour — it is a reference, not an
    // object, and has nothing to be coloured by.
    declaredColour() {
      if (this.node.partial || this.node.disabled) return "";
      const rgb = this.node.colorRGB;
      if (rgb && /^\s*\d+\s*,\s*\d+\s*,\s*\d+\s*$/.test(rgb)) return `rgb(${rgb})`;
      return "";
    },
    // Synthetic leaves (MR/TS/MRTS) keep the UNDERLYING property's icon via
    // `propType`; the MR/TS aspect shows as separate badges (see isMR/isTS).
    icon() {
      if (this.node.partial) return this.icons._partial;
      if (this.handlers.isLattice(this.node)) return this.icons._lattice;
      // a channel of a log frame is typed as a property by the plugin, but
      // it is read against a depth axis, not over a grid: it wears the log
      // track's own curve
      if (this.node.logChannel && this.icons._logChannel) return this.icons._logChannel;
      // a rep folder of the Statistics tree draws the family it belongs to —
      // that type ONLY: `family` rides on other rows too, where it says
      // which tab files them and must not take their own drawing away
      if (this.node.type === "RepFolder" && this.node.family
          && this.icons._family && this.icons._family[this.node.family]) {
        return this.icons._family[this.node.family];
      }
      return (this.node.propType && this.icons[this.node.propType])
        // a container wears the drawing of the geometry it wraps (a
        // surface's container, 27/10)
        || (this.node.iconType && this.icons[this.node.iconType])
        || this.icons[this.node.type]
        || this.icons._fallback;
    },
    isMR() { return this.node.type === "MultiRealization" || this.node.type === "MultiRealizationTimeSeries"; },
    isTS() { return this.node.type === "TimeSeries" || this.node.type === "MultiRealizationTimeSeries"; },
    loadedBadge() {
      if (!this.hasChildren) return "";
      let c = 0;
      const walk = (nodes) => {
        for (const n of nodes || []) {
          if (this.selected.has(n.path)) c++;
          if (n.children && n.children.length) walk(n.children);
        }
      };
      walk(this.node.children);
      return c > 0 ? String(c) : "";
    },
    tooltip() {
      const n = this.node;
      const lines = [];
      if (n.type) lines.push(n.type);
      if (n.path) lines.push(n.path);
      // depth or time: the vertical reference of the object (the PO, 28/10)
      if (n.vdomain) lines.push(n.vdomain === "time" ? "Time domain" : "Depth domain");
      if (n.crs) lines.push("CRS: " + n.crs);
      if (n.dims) lines.push("Dims: " + n.dims);
      if (n.count != null) lines.push("Count: " + n.count);
      if (n.units) lines.push("Units: " + n.units);
      if (n.info) lines.push(n.info);
      return lines.join("\n");
    },
  },
  methods: {
    startRename() {
      this.draft = this.node.title || "";
      this.renaming = true;
      this.$nextTick(() => { const el = this.$refs.rename; if (el) { el.focus(); el.select(); } });
    },
    commitRename() {
      if (!this.renaming) return;
      this.renaming = false;
      const t = (this.draft || "").trim();
      if (t && t !== this.node.title) this.handlers.sessionRename(this.node, t);
    },
    // May THIS path carry an eye: the tree's own gate when it declares one
    // (`eyeable`), the checkbox otherwise; never an object of the other
    // domain the view does not draw (the PO's manager, 02/11)
    canEye(p) {
      if (this.undrawn.has(p)) return false;
      return this.eyeable ? this.eyeable.has(p) : this.selected.has(p);
    },
  },
};
</script>

<style scoped>
.tn-row { display: flex; align-items: center; gap: 4px; padding: 2px 4px; cursor: pointer; white-space: nowrap; outline: none; }
.tn-row:hover { background: #f0f7ff; }
.tn-row:focus { background: #e8f1fc; box-shadow: inset 0 0 0 1px #90caf9; }
.tn-row.active { background: #e3f2fd; font-weight: 600; }
.tn-caret { width: 12px; display: inline-block; text-align: center; color: var(--fp-ink-mute); cursor: pointer; flex: 0 0 auto; }
.tn-check { width: 16px; cursor: pointer; color: var(--fp-accent); flex: 0 0 auto; }
.tn-icon { flex: 0 0 auto; display: block; color: #546e7a; }
.tn-icon-warn { color: #f57c00; }
.tn-partial { flex: 0 0 auto; font-size: 9px; font-weight: 700; letter-spacing: 0.4px; line-height: 1; padding: 2px 5px; border-radius: 3px; background: #fff3e0; color: #e65100; border: 1px solid #ffb74d; }
/* One character, no box: the row already says everything else. */
.tn-load { flex: 0 0 auto; font-size: 11px; font-weight: 700; line-height: 1; padding: 0 2px; }
.tn-load-loading { color: var(--fp-accent); }
.tn-load-failed { color: var(--fp-error-ink); }
.tn-muted { color: #9e9e9e; font-style: italic; }
.tn-pencil { flex: 0 0 auto; color: #78909c; cursor: pointer; font-size: 12px; padding: 0 2px; }
.tn-pencil:hover { color: var(--fp-accent); }
.tn-rename { flex: 1 1 auto; min-width: 0; font: inherit; font-size: 12px; padding: 0 3px; border: 1px solid var(--fp-accent); border-radius: 2px; }
/* an extract (the PO, 21/10): its × red, its icon in the F2I blue and
   green (the cube, the corners), its name green, its pencil black, its eye
   blue as every other eye */
.tn-extract-row .tn-x { color: var(--fp-error-ink, #b00020); }
.tn-extract-row .tn-icon { color: var(--fp-accent, #00436d); }
.tn-extract-row .tn-title { flex: 0 1 auto; color: var(--fp-f2i-ink, #5c8a0f); font-style: normal; }
.tn-extract-row .tn-pencil { color: var(--fp-ink, #222); }
.tn-extract-row .tn-pencil:hover { color: var(--fp-accent, #00436d); }
/* a row just made: the tree scrolls to it and it lights up a moment */
.tn-row.tn-flash { animation: tn-flash 2.4s ease-out; }
@keyframes tn-flash { 0%, 40% { background: #dcedc8; } 100% { background: transparent; } }
.tn-spacer { flex: 1 1 auto; }
.tn-chip { flex: 0 0 auto; width: 9px; height: 9px; border-radius: 50%; border: 1px solid rgba(0,0,0,0.3); }
.tn-swatch { flex: 0 0 auto; width: 11px; height: 11px; border-radius: 2px; border: 1px solid rgba(0,0,0,0.25); cursor: pointer; }
.tn-swatch.tn-cmap-off { opacity: 0.3; cursor: default; }
.tn-tag { flex: 0 0 auto; font-size: 9px; font-weight: 700; line-height: 1; padding: 2px 4px; border-radius: 3px; }
.tn-tag-mr { background: #ede7f6; color: #5e35b1; border: 1px solid #b39ddb; }
.tn-tag-vec { background: #e3f2fd; color: #1565c0; border: 1px solid #90caf9; }
.tn-tag-depth { background: #e8f5e9; color: #2e7d32; border: 1px solid #a5d6a7; font-weight: 600; }
.tn-tag-time { background: #fff8e1; color: #a15c00; border: 1px solid #ffcc80; font-weight: 600; }
.tn-tag[data-click] { cursor: pointer; }
.tn-tag-conv { color: #3d5a1e; border: 1px solid #c5d68a; font-weight: 600; }
/* from its domain's colour to the view's: the T tag's yellow to the D tag's green */
.tn-conv-td { background: linear-gradient(90deg, #ffe9a8, #c8e6c9); }
.tn-conv-dt { background: linear-gradient(90deg, #c8e6c9, #ffe9a8); }
.tn-tag-ts { flex: 0 0 auto; display: block; }
.tn-title { flex: 1 1 auto; overflow: hidden; text-overflow: ellipsis; }
.tn-title.tn-title-tight { flex: 0 1 auto; }
.tn-active-model { flex: 1 1000 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; color: var(--fp-f2i-ink, #5c8a0f); font-weight: 600; }
.tn-badge { flex: 0 0 auto; font-size: 10px; line-height: 1; padding: 1px 5px; border-radius: 8px; background: #e0e0e0; color: #555; }
.tn-eye { cursor: pointer; opacity: 0.9; flex: 0 0 auto; display: flex; align-items: center; color: var(--fp-accent); }
.tn-eye:hover { opacity: 1; }
/* the session's own rows: their own colour, "disposable" (the PO, 15/10) */
.tn-session { color: #c2185b; font-style: italic; }
.tn-tag-session { background: #fce4ec; color: #ad1457; border: 1px solid #f48fb1; font-weight: 600; }
.tn-x { flex: 0 0 auto; width: 14px; text-align: center; color: #ad1457; cursor: pointer; font-weight: 700; }
.tn-x:hover { color: var(--fp-error-ink, #c62828); }
.tn-pick { flex: 0 0 auto; font-size: 10px; font-weight: 600; padding: 1px 5px; border-radius: 3px;
  border: 1px solid #ad1457; color: #ad1457; background: #fff; cursor: pointer; }
.tn-pick:hover { background: #fce4ec; }
.tn-chip-edit { cursor: pointer; }
.tn-chip-edit:hover { outline: 2px solid var(--fp-accent, #00436d); outline-offset: 1px; }
</style>
