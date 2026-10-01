<template>
  <div class="tn">
    <div
      class="tn-row"
      :class="{ active: isActive }"
      :style="{ paddingLeft: depth * 16 + 4 + 'px' }"
      tabindex="0"
      :data-path="node.path"
      :title="tooltip"
      @click="handlers.activate(node.path)"
      @contextmenu.prevent="handlers.context(node, $event)"
    >
      <span class="tn-caret" @click.stop="handlers.toggleExpand(node.path)">
        <template v-if="hasChildren">{{ isOpen ? "▾" : "▸" }}</template>
      </span>
      <span
        v-if="!node.disabled"
        class="tn-check"
        @click.stop="handlers.toggleSelect(node.path)"
      >{{ checkGlyph }}</span>
      <fp-icon
        class="tn-icon"
        :class="{ 'tn-icon-warn': node.partial }"
        :icon="icon"
        :size="15"
        :declared="declaredColour"
        :disabled="!!node.disabled"
      />
      <template v-if="colorEditing">
        <span
          v-if="node.color"
          class="tn-swatch"
          :class="{ 'tn-cmap-off': !isSelected }"
          :style="{ background: node.color }"
          :title="isSelected ? 'Edit colour' : 'Load (check) to edit the colour'"
          @click.stop="isSelected && handlers.color(node, 'solid')"
        ></span>
      </template>
      <span v-if="isMR" class="tn-tag tn-tag-mr" title="Multi-realization">MR</span>
      <span v-if="Number(node.componentCount) > 1" class="tn-tag tn-tag-vec"
            :title="'Vector property: ' + node.componentCount + ' values per element'">×{{ node.componentCount }}</span>
      <fp-icon v-if="isTS" class="tn-tag-ts" :icon="icons._ts" :size="13" title="Time series" />
      <span v-if="node.partial" class="tn-partial" :title="node.info || 'Partial — reference stub, not loadable'">PARTIAL</span>
      <span v-else-if="node.unreachable" class="tn-partial" :title="node.info">NOT IN 3D</span>
      <span class="tn-title" :class="{ 'tn-muted': node.disabled }">{{ node.title }}</span>
      <span v-if="loadMark" class="tn-load" :class="'tn-load-' + node.loadState"
            :title="node.info || ''" :aria-label="loadWord">{{ loadMark }}</span>
      <span v-if="loadedBadge" class="tn-badge" :title="loadedBadge + ' loaded below'">{{ loadedBadge }}</span>
      <span
        v-if="showEye"
        class="tn-eye"
        :title="isVisible ? 'Hide' : 'Show'"
        @click.stop="handlers.toggleVisible(node.path)"
      ><svg viewBox="0 0 24 24" width="15" height="15"><path v-if="isVisible" :d="icons._eyeFull" fill="currentColor" /><template v-else><path :d="icons._eyeOutline" fill="currentColor" /><path d="M4.5 20.5 L19.5 3.5" stroke="#000000" stroke-width="2.4" stroke-linecap="round" fill="none" /></template></svg></span>
    </div>
    <template v-if="hasChildren && isOpen">
      <TreeNode
        v-for="c in node.children"
        :key="c.path"
        :node="c"
        :depth="depth + 1"
        :selected="selected"
        :visible="visible"
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
// Node shape (parsed from the assembly XML): { path, title, type, eye, color?,
// colorRGB?, state?, children, disabled?, crs?/dims?/count?/units?/info? }.
import FpIcon from "../../../_shared/components/FpIcon.vue";

export default {
  name: "TreeNode",
  components: { FpIcon },
  props: {
    node: { type: Object, required: true },
    depth: { type: Number, default: 0 },
    selected: { type: Set, required: true },   // loaded paths
    visible: { type: Set, required: true },    // visible paths
    // Which nodes MAY carry an eye, when the checkbox is not the gate: a
    // tree whose tick means something other than loading (the Compare
    // view's means "in the comparison") passes the paths the session can
    // actually show. `null` = the checkbox is the gate.
    eyeable: { type: Set, default: null },
    expanded: { type: Object, required: true },
    forceOpen: { type: Boolean, default: false },
    active: { default: null },                 // active path
    icons: { type: Object, default: () => ({}) },
    colorEditing: { type: Boolean, default: false },
    handlers: { type: Object, required: true },
  },
  computed: {
    hasChildren() {
      return Array.isArray(this.node.children) && this.node.children.length > 0;
    },
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
          else if (!n.disabled) { total++; if (this.selected.has(n.path)) sel++; }
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
    // A tree may list a property the session has not read (the Compare
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
      // a channel of a log frame is typed as a property by the plugin, but
      // it is read against a depth axis, not over a grid: it wears the log
      // track's own curve
      if (this.node.logChannel && this.icons._logChannel) return this.icons._logChannel;
      // a rep folder of the Compare tree draws the family it belongs to —
      // that type ONLY: `family` rides on other rows too, where it says
      // which tab files them and must not take their own drawing away
      if (this.node.type === "RepFolder" && this.node.family
          && this.icons._family && this.icons._family[this.node.family]) {
        return this.icons._family[this.node.family];
      }
      return (this.node.propType && this.icons[this.node.propType])
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
      if (n.crs) lines.push("CRS: " + n.crs);
      if (n.dims) lines.push("Dims: " + n.dims);
      if (n.count != null) lines.push("Count: " + n.count);
      if (n.units) lines.push("Units: " + n.units);
      if (n.info) lines.push(n.info);
      return lines.join("\n");
    },
  },
  methods: {
    // May THIS path carry an eye: the tree's own gate when it declares one
    // (`eyeable`), the checkbox otherwise.
    canEye(p) {
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
.tn-swatch { flex: 0 0 auto; width: 11px; height: 11px; border-radius: 2px; border: 1px solid rgba(0,0,0,0.25); cursor: pointer; }
.tn-swatch.tn-cmap-off { opacity: 0.3; cursor: default; }
.tn-tag { flex: 0 0 auto; font-size: 9px; font-weight: 700; line-height: 1; padding: 2px 4px; border-radius: 3px; }
.tn-tag-mr { background: #ede7f6; color: #5e35b1; border: 1px solid #b39ddb; }
.tn-tag-vec { background: #e3f2fd; color: #1565c0; border: 1px solid #90caf9; }
.tn-tag-ts { flex: 0 0 auto; display: block; }
.tn-title { flex: 1 1 auto; overflow: hidden; text-overflow: ellipsis; }
.tn-badge { flex: 0 0 auto; font-size: 10px; line-height: 1; padding: 1px 5px; border-radius: 8px; background: #e0e0e0; color: #555; }
.tn-eye { cursor: pointer; opacity: 0.9; flex: 0 0 auto; display: flex; align-items: center; color: var(--fp-accent); }
.tn-eye:hover { opacity: 1; }
</style>
