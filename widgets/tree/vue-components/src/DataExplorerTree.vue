<template>
  <div class="fdx">
    <div class="fdx-tabs" v-if="tabs.length > 1">
      <button
        v-for="(t, i) in tabs"
        :key="t.name"
        :class="['fdx-tab', { active: activeTabIndex === i }]"
        @click="onTab(i)"
      >{{ t.name }} ({{ tabCounts[i] }})</button>
    </div>

    <div class="fdx-toolbar">
      <div class="fdx-filter">
        <input
          class="fdx-filter-input"
          type="text"
          :value="nameInput"
          @input="onNameInput"
          placeholder="Filter by name (* ? wildcards)"
        />
        <button v-if="nameInput" class="fdx-filter-clear" title="Clear" @click="clearName">×</button>
        <fp-select class="fdx-filter-kind" :model-value="kindFilter" :options="kindOptions"
                   title="Show only the objects of one type" @update:model-value="kindFilter = $event || ''" />
      </div>
      <!-- How the forest is laid out: the objects at the top, or grouped
           under the interpretation they carry, or under feature then
           interpretation. The reader picks a layout of the SAME data (R13,
           a segmented control). A grid keeps its whole block (geometry,
           properties, SubRep, blocked wellbores) in every layout: the
           grouping rows sit above the block, never inside it. -->
      <div v-if="layout && layoutOffered" class="fdx-layout">
        <span class="fp-lab" title="How the trees are laid out">layout</span>
        <fp-seg :model-value="layout" :options="LAYOUTS"
                title="How the trees are laid out — changing it unchecks everything, the rows change place"
                @update:model-value="$emit('layout-change', $event)" />
      </div>
      <div v-if="bulkSelect" class="fdx-select">
        <button class="fdx-select-btn" :class="{ open: selectMenuOpen }" @click="toggleSelectMenu">Select ▾</button>
        <div v-if="selectMenuOpen" class="fdx-backdrop" @click="closeSelectMenu"></div>
        <div v-if="selectMenuOpen" class="fdx-menu">
          <template v-for="(row, i) in selectMenu">
            <div v-if="row.sep" :key="'sep' + i" class="fdx-menu-sep"></div>
            <div
              v-else
              :key="i"
              :class="['fdx-menu-item', { child: row.level === 1, disabled: row.disabled }]"
              @click="onBulk(row)"
            >{{ row.label }}</div>
          </template>
          <fp-empty v-if="!selectMenu.length" class="fdx-menu-none"
                    shows="The types this tab holds, to tick or clear at once."
                    gesture="Open an EPC, or pick another tab, and its types are listed here." />
        </div>
      </div>
    </div>

    <div class="fdx-body" ref="body" @keydown="onKey">
      <TreeNode
        v-for="node in filteredRoots"
        :key="node.path"
        :node="node"
        :depth="0"
        :selected="selectedSet"
        :visible="visibleSet"
        :eyeable="eyeableSet"
        :expanded="expanded"
        :force-open="filterActive"
        :active="activePath"
        :icons="iconMap"
        :color-editing="colorEditing"
        :handlers="handlers"
      />
      <fp-empty
        v-if="!filteredRoots.length"
        :shows="emptyState.shows"
        :gesture="emptyState.gesture"
        :why="emptyState.why"
      />
    </div>

    <div v-if="ctxOpen" class="fdx-backdrop" @click="ctxOpen = false" @contextmenu.prevent="ctxOpen = false"></div>
    <div v-if="ctxOpen" class="fdx-ctxmenu" :style="{ left: ctxPos.x + 'px', top: ctxPos.y + 'px' }">
      <div class="fdx-ctx-title">{{ ctxNode && ctxNode.title }}</div>
      <template v-for="(a, i) in ctxItems" :key="i">
        <div v-if="a.separatorBefore && i > 0" class="fdx-menu-sep"></div>
        <div :class="['fdx-menu-item', { danger: a.danger, disabled: a.disabled }]"
             @click="a.disabled || onCtxAction(a)">{{ a.label }}</div>
      </template>
    </div>
  </div>
</template>

<script>
import TreeNode from "./TreeNode.vue";
import FpEmpty from "../../../_shared/components/FpEmpty.vue";
import FpSeg from "../../../_shared/components/FpSeg.vue";
import FpSelect from "../../../_shared/components/FpSelect.vue";
import { FESPP_ICONS as FI } from "../../../_shared/icons/fespp-icons.js";
import {
  mdiChartBoxOutline, mdiShapeOutline, mdiScriptTextOutline,
  mdiAlertOutline,
  mdiEye, mdiEyeOutline,
} from "@mdi/js";

/*
 * Autonomous data-explorer tree over a vtkDataAssembly.
 *
 *   in  : `assembly` (the assembly serialized to XML), plus light config.
 *   own : selection / visibility / expansion / active / filter / tabs — the
 *         component holds its own interaction state.
 *   out : it emits its outputs (selected/visible paths, active path, colour &
 *         context requests). The Python wrapper mirrors these into trame state
 *         vars, so the host just watches them with @state.change — no per-event
 *         wiring, and new outputs don't break callers.
 *
 * Node identity is the vtkDataAssembly path (e.g. /Root/Reservoir/Geogrid/Ijk).
 * Per-node data comes from XML attributes: label (title), type, eye
 * ('rep'|'array'), color, crs/dims/count/units/info — and `family`, the tab
 * a node of a SYNTHETIC assembly belongs to when its type says nothing of it
 * (the Compare view's rep folders name the family of the representation they
 * stand for): a tab keeps a node whose type it lists OR whose family is the
 * tab's own name.
 */

const KIND_LABELS = {
  IjkGrid: "IJK Grids", UnstructuredGrid: "Unstructured Grids",
  TriangulatedSet: "Triangulations", Grid2d: "2D Grids", Grid2dRepresentation: "2D Grids",
  Polyline: "Polylines", PolylineSet: "Polyline Sets", PointSet: "Point Sets",
  Wellbore: "Wellbores", Trajectory: "Trajectories", WellboreTrajectory: "Trajectories",
  MarkerFrame: "Markers", ContinuousProperty: "Continuous Properties",
  DiscreteProperty: "Discrete Properties", CategoricalProperty: "Categorical Properties",
  Feature: "Features",
};

// Per-type Material Design Icons (SVG paths via @mdi/js). Override via `kindIcons`.
/*
 * The drawing of each RESQML type, from the application's own set
 * (widgets/_shared/icons/fespp-icons.js). The plugin speaks TWO
 * vocabularies for a node's `type`: a representation carries its RESQML
 * class ("IjkGrid", "TriangulatedSet"), everything else the name of its
 * TreeViewNodeType ("WellboreFrame", "PropertiesFolder"). Both are mapped,
 * which is why several keys share one drawing.
 *
 * A type with no drawing of its own keeps an mdi glyph: a bare property, and
 * the two grouping rows of the Interpretation / Feature layouts, which are
 * not objects of the model.
 */
const KIND_ICONS = {
  // the rock
  GridContainer: FI.gridContainer,
  IjkGrid: FI.gridIjk, ExplicitStructuredGrid: FI.gridIjk,
  UnstructuredGrid: FI.gridUnstructured,
  // the plugin shortens an xml tag by dropping a trailing "Representation",
  // so a SubRepresentation reaches the tree typed "Sub"
  Sub: FI.subRepresentation, SubRepresentation: FI.subRepresentation,
  BlockedWellbore: FI.blockedWellbore,
  PropertiesFolder: FI.folderProperties,
  SubRepresentationFolder: FI.folderSubRepresentation,
  BlockedWellboreFolder: FI.folderBlockedWellbore,

  // the surfaces
  Grid2d: FI.surfaceGrid2d, Grid2dRepresentation: FI.surfaceGrid2d,
  TriangulatedSet: FI.surfaceTin,
  PointSet: FI.pointSet,
  Polyline: FI.polyline, PolylineSet: FI.polylineSet,

  // the wells
  Wellbore: FI.wellbore,
  Trajectory: FI.trajectory, WellboreTrajectory: FI.trajectory,
  Frame: FI.logFrame, WellboreFrame: FI.logFrame,
  WellboreChannel: FI.logChannel,
  MarkerFrame: FI.markerFrame, WellboreMarkerFrame: FI.markerFrame,
  Marker: FI.marker, WellboreMarker: FI.marker,
  WellboreCompletion: FI.completion, Perforation: FI.perforation,
  WellboreLogsFolder: FI.folderLogs,
  WellboreMarkersFolder: FI.folderMarkers,
  WellboreCompletionsFolder: FI.folderCompletions,

  // the properties
  Property: mdiChartBoxOutline, Properties: mdiChartBoxOutline,
  ContinuousProperty: FI.propertyContinuous,
  DiscreteProperty: FI.propertyDiscrete,
  CategoricalProperty: FI.propertyCategorical,
  TimeSeries: FI.timeSeries,
  MultiRealization: FI.multiRealization,
  MultiRealizationTimeSeries: FI.multiRealizationTimeSeries,
  Collection: FI.propertySet,

  // the grouping rows of the alternate layouts — not objects of the model
  Feature: mdiShapeOutline, Interpretation: mdiScriptTextOutline,

  // the synthetic rows of the Compare / Statistics tree, grouped by PWLS
  // kind: a kind folder holds properties, a rep folder stands for the object
  // they were read from (its own drawing comes from `family`, in TreeNode),
  // and an item is a property whose `propType` names its drawing
  KindFolder: FI.folderProperties, RepFolder: FI.gridContainer,
  CompareItem: mdiChartBoxOutline,
};

// A rep folder of the Compare tree draws the FAMILY it belongs to — the tab
// the data tree would file it under — rather than one folder for all three.
const FAMILY_ICONS = {
  Reservoir: FI.gridContainer, Surface: FI.surfaceTin, Well: FI.wellbore,
};
const FALLBACK_ICON = FI.unknown;

const BULK_EXCLUDE_RE = /property$/i;

const DEFAULT_TABS = [
  // GridContainer wraps the grid (SolidColor variant) — match it so pruneTree
  // keeps its whole subtree (geometry + properties + blocked wellbore); keep the
  // bare grid types too for older flat assemblies.
  { name: "Reservoir", types: ["GridContainer", "IjkGrid", "UnstructuredGrid", "ExplicitStructuredGrid"] },
  { name: "Surface", types: ["TriangulatedSet", "Grid2d", "Grid2dRepresentation", "Polyline", "PolylineSet", "PointSet"] },
  { name: "Well", types: ["Wellbore", "Trajectory", "WellboreTrajectory", "MarkerFrame"] },
];

const DEFAULT_SELECT_GROUPS = [
  { label: "All Grids", types: ["GridContainer", "IjkGrid", "UnstructuredGrid", "ExplicitStructuredGrid"] },
  { label: "All Surfaces", types: ["TriangulatedSet", "Grid2d", "Grid2dRepresentation", "Polyline", "PolylineSet", "PointSet"] },
  { label: "All Wells", types: ["Wellbore"] },
  { label: "All Trajectories", types: ["Trajectory", "WellboreTrajectory"] },
  { label: "All Markers", types: ["MarkerFrame"] },
  { label: "All Features", types: ["Feature"] },
];

// The FESPP vtkDataAssembly carries `kind` (the kind string) + `title`, but no
// `eye`. Representations get eye='rep', properties/arrays get eye='array';
// derive it from kind. If the C++ side later emits an `eye` attribute, it wins.
const REP_KINDS = new Set([
  "IjkGrid", "UnstructuredGrid", "ExplicitStructuredGrid", "Grid2d",
  "Grid2dRepresentation", "TriangulatedSet", "Polyline", "PolylineSet", "PointSet",
  "BlockedWellbore", "SubRepresentation",
  "Wellbore", "Trajectory", "WellboreTrajectory", "Frame", "MarkerFrame",
]);
// Grid geometry leaf types — the one hoisted OUT of a GridContainer's
// PropertiesFolder to sit beside it, relabelled "geometry".
const GEOMETRY_TYPES = new Set(["IjkGrid", "UnstructuredGrid", "ExplicitStructuredGrid"]);
// A grid known by reference only: the file read names it but does not carry
// it (the Olympus split — the properties' EPC before the grid's). The plugin
// builds the grid's layout anyway, with the geometry leaf typed Partial and
// the grid's type in supporttype. Nothing of that grid can reach the 3D view
// until its own file is read, and every row that would need it says so.
const PARTIAL_GRID_NOTE = "Reference only: this file names the grid but does not carry it,"
  + " so nothing of it can show in 3D — import the grid's own EPC (and .h5).";
function isPartialGeometry(node) {
  return !!node.partial && GEOMETRY_TYPES.has(node.supporttype || "");
}
function markUnreachable(node) {
  for (const c of node.children || []) {
    if (!c.disabled) { c.disabled = true; c.unreachable = true; }
    c.info = (c.info ? c.info + "\n" : "") + PARTIAL_GRID_NOTE;
    markUnreachable(c);
  }
}
// MultiRealization / MultiRealizationTimeSeries / TimeSeries are synthetic
// property leaves (they colour their parent rep) -> eye='array'. MR/MRTS carry
// per-realization children in the XML, but the tree collapses them to a single
// leaf (the realization picker handles the index, outside the tree).
const COLLAPSE_RE = /^MultiRealization(TimeSeries)?$/;
// Container types whose checkbox loads ALL their children at once (a MarkerFrame
// loads its markers, a log Frame loads its channels).
const SELECT_ALL_CHILDREN_KINDS = new Set(["MarkerFrame", "Frame"]);
// The three layouts the plugin can build the forest in (its TreeHierarchyMode).
// The tabs a layout says nothing about: a layout groups representations
// under the interpretation or the feature they carry, which is how a
// reservoir is read. A well already comes laid out — its logs, its markers,
// its completions, its trajectory — and the strip only added a control that
// moved nothing there.
const LAYOUT_SILENT_TABS = new Set(["Well"]);

const LAYOUTS = [
  { value: "flat", label: "Representation",
    title: "Every representation at the top: the grids, the surfaces, the wells" },
  { value: "by_interpretation", label: "Interpretation",
    title: "The representations grouped under the interpretation they carry — a grid keeps its geometry, properties, SubRep and blocked wellbores together beneath it" },
  { value: "by_feature_and_interpretation", label: "Feature",
    title: "Feature, then its interpretations, then their representations — the geology first, the objects under it" },
];
function eyeForType(kind) {
  if (!kind) return null;
  if (kind === "Marker") return "marker";        // each marker toggles its own eye
  if (REP_KINDS.has(kind)) return "rep";
  if (/property$/i.test(kind)) return "array";
  if (COLLAPSE_RE.test(kind) || kind === "TimeSeries") return "array";
  return null;
}
// A wellbore's children (FESPP 2026-09-18): the log frames sit in a "logs"
// folder, the marker frames in "markers", the completions in "completions",
// the trajectory beside them. Order them logs / markers / completions /
// trajectory, whatever their titles sort like.
const WELL_FOLDER_RANK = { WellboreLogsFolder: 0, WellboreMarkersFolder: 1, WellboreCompletionsFolder: 2 };
function orderWellChildren(well) {
  const rank = (n) => (n.type in WELL_FOLDER_RANK ? WELL_FOLDER_RANK[n.type] : 3);
  well.children.sort((a, b) => {
    const r = rank(a) - rank(b);
    return r !== 0 ? r
      : a.title.localeCompare(b.title, undefined, { numeric: true, sensitivity: "base" });
  });
}
// SolidColor GridContainer: the FESPP assembly nests the grid GEOMETRY leaf
// inside the "properties" folder (title "SolidColor"). Hoist it OUT to be a
// direct, FIRST child of the container, relabelled "geometry" — then order
// children geometry / properties / blocked wellbore. Path/kind/eye are
// untouched (selection identity is path-based).
function hoistGridGeometry(container) {
  const props = container.children.find((c) => c.type === "PropertiesFolder");
  if (!props || !props.children) return;
  const gi = props.children.findIndex((c) => GEOMETRY_TYPES.has(c.type) || isPartialGeometry(c));
  if (gi < 0) return;
  const geom = props.children.splice(gi, 1)[0];
  geom.title = "geometry";
  if (geom.partial) {
    // the grid is a reference: its geometry row says why it is greyed, and
    // so do the properties, the folder and the container — none of them can
    // be ticked into the 3D view
    geom.info = PARTIAL_GRID_NOTE;
    container.disabled = true;
    container.unreachable = true;
    container.info = PARTIAL_GRID_NOTE;
    markUnreachable(container);
  }
  const bw = container.children.find((c) => c.type === "BlockedWellboreFolder");
  if (bw) bw.title = "blocked wellbore";
  // The geometry was the folder's ONLY child (a property-less grid, or the
  // Globe's pruned assembly): an empty "properties" row is pure noise.
  if (!props.children.length) {
    container.children = container.children.filter((c) => c !== props);
  }
  container.children.push(geom);
  const rank = (n) => (n === geom ? 0
    : n.type === "PropertiesFolder" ? 1
    : n.type === "BlockedWellboreFolder" ? 2 : 3);
  container.children.sort((a, b) => {
    const r = rank(a) - rank(b);
    return r !== 0 ? r
      : a.title.localeCompare(b.title, undefined, { numeric: true, sensitivity: "base" });
  });
}

export default {
  name: "DataExplorerTree",
  components: { TreeNode, FpEmpty, FpSeg, FpSelect },
  props: {
    // The vtkDataAssembly serialized to XML (SerializeToXML).
    assembly: { type: String, default: "" },
    // Tabs as kind filters: [{ name, types: [...] }] — a node is in a tab
    // when its type is listed or its `family` is the tab's name. [] ->
    // single tree.
    tabs: { type: Array, default: () => DEFAULT_TABS },
    // Session seed (paths); the component owns the selection afterwards.
    initialSelected: { type: Array, default: () => [] },
    // Controlled selection (two-way with `selected-changed`): when the host
    // changes this (e.g. another view's tree loaded something), the tree
    // reflects it.
    selected: { type: Array, default: () => [] },
    // Controlled ACTIVE node (two-way with `active-changed`): when the host
    // activates a node (e.g. a pick in the render view), the tree switches to
    // its tab, expands its ancestors, highlights it and scrolls it into view.
    active: { type: String, default: "" },
    // Visibility is SERVER-OWNED, one-way: the chips render this prop as is.
    // The widget never writes an eye list — an eye click emits `eye-toggle`
    // {path, n} and the host applies it. (A client-written full list raced
    // the server's born-visible / born-hidden edits and clobbered them.)
    visible: { type: Array, default: () => [] },
    // Which paths MAY carry an eye — see TreeNode.eyeable. `null` (unbound)
    // leaves the checkbox as the gate, which is what the data tree wants.
    eyePaths: { type: Array, default: null },
    colorEditing: { type: Boolean, default: false },
    kindIcons: { type: Object, default: () => ({}) },
    selectGroups: { type: Array, default: () => DEFAULT_SELECT_GROUPS },
    // The "Select ▾" menu ticks whole KINDS at once. Its "Select all (N)"
    // row keeps out the types matching /property$/i, so on the data tree it
    // never bulk-loads values. It is offered THERE only: everywhere else
    // that row would tick representations into the 3D scene from a panel
    // that has nothing to do with the scene, so a panel's tree says false
    // and the menu is not drawn at all.
    bulkSelect: { type: Boolean, default: true },
    contextActions: { type: Array, default: () => [] },
    // the layout in force ("" = no layout control: the Compare tree)
    layout: { type: String, default: "" },
    // What the menu says on a node none of `contextActions` applies to. A
    // gesture must never be silent: the same right-click that gives four
    // entries one row below opened nothing at all here, so the reader could
    // not tell a node with no act from a tree with no menu. Each tree names
    // its own reason; this default only keeps a caller that forgot from
    // being silent.
    contextEmptyLabel: { type: String, default: "No action on this node." },
  },
  emits: ["selected-changed", "eye-toggle", "active-changed", "active-by-tab", "colour-request", "context-action", "layout-change"],
  data() {
    return {
      LAYOUTS,
      selectedPaths: [...((this.selected && this.selected.length)
        ? this.selected : (this.initialSelected || []))],
      applyingSelected: false,
      expanded: {},
      // Active node kept PER TAB — switching tabs restores that tab's
      // active node instead of losing
      // it; `activePath` is the DISPLAYED tab's one.
      activeByTab: {},
      activePath: null,
      activeTabIndex: 0,
      selectMenuOpen: false,
      nameInput: "",
      nameQuery: "",
      kindFilter: "",
      nameTimer: null,
      ctxOpen: false,
      ctxNode: null,
      ctxPos: { x: 0, y: 0 },
      nonce: 0,
    };
  },
  watch: {
    selectedPaths(v) {
      if (this.applyingSelected) return; // prop-driven update -> don't echo back
      this.$emit("selected-changed", v);
    },
    activePath(v) { this.$emit("active-changed", v); },
    // The tab list can shrink (the Compare tree's `Other` exists only while
    // the file has a rep of no family): an index past its end would draw the
    // first tab's rows under no highlighted button.
    tabs(v) { if (v && v.length && this.activeTabIndex >= v.length) this.onTab(0); },
    active(v) {
      if (!v || v === this.activePath) return;
      this.revealPath(v);
    },
    // Controlled selection: an external change (e.g. another view) reflects into
    // our state without re-emitting (guards against a feedback loop).
    selected(v) {
      const a = new Set(this.selectedPaths || []);
      const b = new Set(v || []);
      if (a.size === b.size && [...b].every((x) => a.has(x))) return;
      this.applyingSelected = true;
      this.selectedPaths = [...(v || [])];
      this.$nextTick(() => { this.applyingSelected = false; });
    },
  },
  computed: {
    iconMap() { return { _fallback: FALLBACK_ICON, _partial: mdiAlertOutline, _ts: FI.timeMark, _logChannel: FI.logChannel, _family: FAMILY_ICONS, _eyeFull: mdiEye, _eyeOutline: mdiEyeOutline, ...KIND_ICONS, ...(this.kindIcons || {}) }; },
    selectedSet() { return new Set(this.selectedPaths); },
    visibleSet() { return new Set(this.visible || []); },
    eyeableSet() { return this.eyePaths ? new Set(this.eyePaths) : null; },

    // Parse the assembly XML into a forest. The root element is the assembly
    // container; its children are the top-level nodes.
    parsedRoots() {
      const xml = this.assembly;
      if (!xml) return [];
      let doc;
      try { doc = new DOMParser().parseFromString(xml, "application/xml"); } catch (e) { return []; }
      const root = doc && doc.documentElement;
      if (!root || root.getElementsByTagName("parsererror").length) return [];
      // `loadState` ("unloaded" / "loading" / "failed"): a tree may list a
      // property before the session has read it (the Compare view's does —
      // the assembly names every property of the file for free). The leaf
      // stays tickable; the tick is what loads it.
      // `colorRGB` is the colour the DATA declares for this object (a RESQML
      // GraphicalInformationSet, read by the plugin): when it is there the
      // row's icon is drawn in it instead of its family colour.
      const META = ["crs", "dims", "count", "units", "info", "componentCount",
        "loadState", "supporttype", "colorRGB"];
      // siblings sorted alphabetically ascending at every level (case-insensitive,
      // natural for trailing numbers e.g. WELL-2 before WELL-10).
      const byTitle = (a, b) => a.title.localeCompare(b.title, undefined, { numeric: true, sensitivity: "base" });
      const toNode = (el, parentPath) => {
        const path = parentPath + "/" + el.tagName;
        // FESPP assembly: the node's TYPE ("IjkGrid", "TimeSeries") is in
        // `type`. It used to be in `kind`, wrongly — in RESQML a KIND is the
        // PropertyKind (depth, volume). The old plugin ALSO had a numeric
        // `type`, hence the digit test rather than a plain fallback.
        // Display name is `title` (`label` is sanitized); no `eye`.
        let nodeType = el.getAttribute("type") || "";
        if (!nodeType || /^\d+$/.test(nodeType)) nodeType = el.getAttribute("kind") || "";
        const node = {
          path,
          title: el.getAttribute("title") || el.getAttribute("label") || el.tagName,
          type: nodeType,
          eye: el.getAttribute("eye") || eyeForType(nodeType),
          color: el.getAttribute("color") || null,
          children: [],
        };
        for (const a of META) { const v = el.getAttribute(a); if (v != null) node[a] = v; }
        // The property's own type on a synthetic MR/TS leaf -> drives its
        // icon. FESPP called this "propKind" before; in RESQML a KIND is the
        // PropertyKind (depth, volume), so it is a TYPE and now says so.
        // The old name is read as a fallback for an un-rebuilt plugin.
        const pk = el.getAttribute("propType") || el.getAttribute("propKind");
        if (pk) node.propType = pk;
        const fam = el.getAttribute("family");
        if (fam) node.family = fam;
        const d = el.getAttribute("disabled");
        if (d === "1" || d === "true") node.disabled = true;
        // Partial = reference stub: not loadable -> no checkbox, greyed, warned.
        if (/^partial$/i.test(nodeType)) { node.partial = true; node.disabled = true; }
        // MarkerFrame / log Frame: the checkbox loads all children at once.
        if (SELECT_ALL_CHILDREN_KINDS.has(nodeType)) node.selectChildren = true;
        // MR/MRTS collapse to leaves: don't recurse their per-realization children.
        if (!COLLAPSE_RE.test(nodeType)) {
          for (const child of Array.from(el.children)) {
            if (child.tagName === "dataset") continue;
            node.children.push(toNode(child, path));
          }
          // log Frame: its primary channel = the topmost node in the XML (before
          // the alphabetical sort) carries the single visibility eye.
          if (nodeType === "Frame" && node.children.length) node.children[0].frameEye = true;
          // and every child of a frame IS a log channel, whatever RESQML
          // class it carries: the plugin types them as properties, so the
          // tree would otherwise draw a channel exactly like a grid property
          if (nodeType === "Frame" || nodeType === "WellboreFrame") {
            for (const c of node.children) c.logChannel = true;
          }
          node.children.sort(byTitle);
          // SolidColor variant: pull the grid geometry out of "properties".
          if (nodeType === "GridContainer") hoistGridGeometry(node);
          // A well laid out like a grid: its folders first (logs, markers,
          // completions), the trajectory after them.
          if (nodeType === "Wellbore") orderWellChildren(node);
        }
        return node;
      };
      const rootPath = "/" + root.tagName;
      return Array.from(root.children)
        .filter((c) => c.tagName !== "dataset")
        .map((c) => toNode(c, rootPath))
        .sort(byTitle);
    },

    nodeByPath() {
      const map = new Map();
      const walk = (nodes) => { for (const n of nodes || []) { map.set(n.path, n); if (n.children) walk(n.children); } };
      walk(this.parsedRoots);
      return map;
    },

    // Roots for the active tab: the whole forest pruned to the tab's nodes
    // (matches keep their subtree; ancestors kept for context). No tabs -> all.
    tabRoots() {
      const tabs = this.tabs || [];
      if (!tabs.length) return this.parsedRoots;
      return this.pruneTree(this.parsedRoots, this.tabPred(tabs[this.activeTabIndex] || tabs[0]));
    },
    tabNodeByPath() {
      const map = new Map();
      const walk = (nodes) => { for (const n of nodes || []) { map.set(n.path, n); if (n.children) walk(n.children); } };
      walk(this.tabRoots);
      return map;
    },

    // Per-tab ROOT counts for the tab labels ("Reservoir (2)") — the
    // top-level item count of each tab's subtree.
    // whether the layout strip belongs over the tab being read
    layoutOffered() {
      const t = (this.tabs || [])[this.activeTabIndex];
      return !(t && LAYOUT_SILENT_TABS.has(t.name));
    },
    tabCounts() {
      return (this.tabs || []).map((t) => this.pruneTree(this.parsedRoots, this.tabPred(t)).length);
    },

    allTypeCounts() { return this.countTypes(this.tabRoots, {}); },
    kindCounts() {
      const out = {}; const all = this.allTypeCounts;
      for (const t in all) if (!BULK_EXCLUDE_RE.test(t)) out[t] = all[t];
      return out;
    },
    filterTypes() {
      const all = this.allTypeCounts;
      return Object.keys(all).sort((a, b) => this.kindLabel(a).localeCompare(this.kindLabel(b)))
        .map((t) => ({ type: t, label: this.kindLabel(t), count: all[t] }));
    },
    kindOptions() {
      return [{ value: "", label: "All types", title: "Every type this tab holds" }].concat(
        this.filterTypes.map((k) => ({
          value: k.type, label: k.label + " (" + k.count + ")",
          title: k.count + " " + k.label + " in this tab",
        })));
    },

    nameRe() {
      const q = (this.nameQuery || "").trim();
      if (!q) return null;
      const rx = q.replace(/[.+^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*").replace(/\?/g, ".");
      try { return new RegExp(rx, "i"); } catch (e) { return null; }
    },
    filterActive() { return !!this.nameRe || !!this.kindFilter; },
    filteredRoots() {
      if (!this.filterActive) return this.tabRoots;
      return this.pruneTree(this.tabRoots, (n) => this.matchNode(n));
    },
    // R8: what the body would list, and the gesture that fills it — the
    // tab's family is named when it is the tab that is empty
    emptyState() {
      if (!this.parsedRoots.length) {
        return { shows: "The objects of the open file, one row each.",
          gesture: "Click “Import data” in the top bar to fill it.",
          why: "No data is loaded yet." };
      }
      if (this.filterActive) {
        return { shows: "The rows matching the filter.",
          gesture: "Clear the name filter, or set the type filter back to all types, to see the whole tab.",
          why: "" };
      }
      const t = (this.tabs || [])[this.activeTabIndex];
      const name = t && t.name ? String(t.name) : "this tab";
      return { shows: "What the open file holds for " + name + ".",
        gesture: "Pick another tab, or import a file that has some.",
        why: "This file holds none." };
    },

    nodeIndex() {
      const map = new Map();
      const walk = (nodes, parentPath) => {
        for (const n of nodes || []) {
          const hasChildren = !!(n.children && n.children.length);
          map.set(n.path, { node: n, parentPath, hasChildren });
          if (hasChildren) walk(n.children, n.path);
        }
      };
      walk(this.filteredRoots, null);
      return map;
    },

    ctxItems() {
      const items = this.ctxItemsFor(this.ctxNode);
      return items.length
        ? items
        : [{ key: "", label: this.contextEmptyLabel, disabled: true }];
    },

    // how many nodes of each type the tab shows are ticked
    tickedCounts() {
      const sel = new Set(this.selectedPaths);
      const out = {};
      const walk = (nodes) => {
        for (const n of nodes || []) {
          if (!n.disabled && sel.has(n.path)) out[n.type] = (out[n.type] || 0) + 1;
          if (n.children && n.children.length) walk(n.children);
        }
      };
      walk(this.tabRoots);
      return out;
    },

    // The menu ticks whole kinds at once, and unticks them: a row whose
    // kinds are all ticked reads "Clear …" and removes them; a last row
    // clears everything the tab shows. It used to only ever add.
    selectMenu() {
      const counts = this.kindCounts;
      const ticked = this.tickedCounts;
      const present = Object.keys(counts);
      if (!present.length) return [];
      const row = (label, types, level) => {
        const n = types.reduce((s, t) => s + counts[t], 0);
        const k = types.reduce((s, t) => s + (ticked[t] || 0), 0);
        const clear = n > 0 && k === n;
        return { label: (clear ? `Clear ${label}` : label) + ` (${n})`, types, level, clear };
      };
      const total = present.reduce((s, t) => s + counts[t], 0);
      const totalTicked = present.reduce((s, t) => s + (ticked[t] || 0), 0);
      const rows = [
        row(totalTicked === total ? 'all' : 'Select all', present.slice(), 0),
        { sep: true },
      ];
      const presentSet = new Set(present);
      const used = new Set();
      for (const g of this.selectGroups || []) {
        const types = (g.types || []).filter((t) => presentSet.has(t));
        if (!types.length) continue;
        types.forEach((t) => used.add(t));
        if (types.length === 1) {
          const t = types[0];
          rows.push(row(`All ${this.kindLabel(t)}`, [t], 0));
        } else {
          rows.push(row(g.label, types.slice(), 0));
          for (const t of types) rows.push(row(`All ${this.kindLabel(t)}`, [t], 1));
        }
      }
      for (const t of present) {
        if (used.has(t)) continue;
        rows.push(row(`All ${this.kindLabel(t)}`, [t], 0));
      }
      if (totalTicked > 0 && totalTicked < total) {
        rows.push({ sep: true });
        rows.push({ label: `Clear all ticked (${totalTicked})`, types: present.slice(), level: 0, clear: true });
      }
      return rows;
    },

    handlers() {
      return {
        toggleSelect: (path) => this.toggleSelect(path),
        toggleVisible: (path) => this.toggleVisible(path),
        activate: (path) => this.setActive(path),
        toggleExpand: (path) => this.setExpanded(path, !this.expanded[path]),
        context: (node, event) => this.openContext(node, event),
        color: (node, kind) => this.$emit("colour-request", { path: node.path, kind, n: ++this.nonce }),
      };
    },
  },
  methods: {
    kindLabel(type) { return KIND_LABELS[type] || (type.endsWith("s") ? type : type + "s"); },
    countTypes(nodes, counts) {
      for (const n of nodes || []) {
        if (!n.disabled && n.type) counts[n.type] = (counts[n.type] || 0) + 1;
        if (n.children && n.children.length) this.countTypes(n.children, counts);
      }
      return counts;
    },
    // A tab keeps a node whose type it lists, or whose `family` is its name
    tabPred(t) {
      const types = new Set((t && t.types) || []);
      const name = t && t.name ? String(t.name) : "";
      return (n) => types.has(n.type) || (!!n.family && n.family === name);
    },
    pruneTree(roots, pred) {
      const rec = (nodes) => {
        const out = [];
        for (const n of nodes || []) {
          if (pred(n)) { out.push(n); continue; }
          const kids = n.children && n.children.length ? rec(n.children) : [];
          if (kids.length) out.push({ ...n, children: kids });
        }
        return out;
      };
      return rec(roots);
    },
    matchNode(n) {
      if (this.kindFilter && n.type !== this.kindFilter) return false;
      if (this.nameRe && !(n.title && this.nameRe.test(n.title))) return false;
      return true;
    },
    toggleSelect(path) {
      const node = this.nodeByPath.get(path);
      const sel = new Set(this.selectedPaths);
      // Only the SELECTION is written here; eyes are server-owned (born on
      // load, dropped with the unchecked paths).
      const add = (n) => { sel.add(n.path); };
      const drop = (p) => { sel.delete(p); };
      if (node && node.selectChildren) {
        // MarkerFrame / log Frame: tri-state semantics — ANY child
        // selected (full OR intermediate) -> the click EMPTIES the subtree;
        // only a fully-empty container bulk-selects it.
        const leaves = [];
        const collect = (nodes) => {
          for (const c of nodes || []) {
            if (c.children && c.children.length) collect(c.children);
            else if (!c.disabled) leaves.push(c);
          }
        };
        collect(node.children);
        const anySel = leaves.some((c) => sel.has(c.path));
        for (const c of leaves) { if (anySel) drop(c.path); else add(c); }
      } else if (node && node.children && node.children.length) {
        // Grouping container (well, folder, ...): tri-state click —
        // ANY selected descendant (or the container itself) -> EMPTY the
        // whole subtree; fully empty -> check the container (the server
        // cascade then selects its descendants). The subtree is what the
        // CURRENT TAB shows of it — the one the box's tri-state is drawn
        // over: a container the tab prunes (a Compare kind folder holding
        // grid and well representations, under Reservoir) ticks its shown
        // part only, each complete child by its own path so the host
        // cascades it as ever, a pruned one by its children in turn.
        const shown = this.tabNodeByPath.get(path) || node;
        const descSel = [];
        const walk = (ns) => {
          for (const c of ns || []) {
            if (sel.has(c.path)) descSel.push(c.path);
            walk(c.children);
          }
        };
        walk(shown.children);
        if (descSel.length || sel.has(path)) {
          for (const p2 of descSel) drop(p2);
          drop(path);
        } else {
          for (const t of this.tickTargets(node, shown)) add(t);
        }
      } else if (node) {
        if (sel.has(path)) {
          drop(path);
        } else {
          add(node);
          // Ticking a leaf reads it AND makes it the active node: the cards
          // that follow the active node (Attributes, Colormap, Thresholds,
          // Volumetrics) show what was just ticked without a second click
          // on the row. A container tick is a cascade the host resolves;
          // it activates nothing.
          this.setActive(path);
        }
      }
      this.selectedPaths = [...sel];
    },
    // The nodes a tick on `full` stands for when the tab shows `shown` of
    // it: the container itself when nothing is pruned, else its shown
    // children — a whole one as it is, a pruned one through its own.
    tickTargets(full, shown) {
      const size = (n) => {
        let c = 0;
        const walk = (ns) => { for (const k of ns || []) { c++; walk(k.children); } };
        walk(n.children);
        return c;
      };
      if (shown === full || size(shown) === size(full)) return [full];
      const out = [];
      for (const c of shown.children || []) {
        const whole = this.nodeByPath.get(c.path) || c;
        if (size(c) === size(whole)) out.push(whole);
        else out.push(...this.tickTargets(whole, c));
      }
      return out;
    },
    // Every loaded, eye-bearing leaf under `node` (the node itself if it is
    // one). Used to make a folder's eye drive its whole subtree.
    eyeLeavesUnder(node) {
      const out = [];
      const sel = this.eyeableSet || this.selectedSet;
      const walk = (n) => {
        const kids = n.children || [];
        const own = n.eye && sel.has(n.path);
        if (own && (!kids.length || !kids.some((c) => c.eye))) {
          out.push(n.path);
          return;
        }
        for (const c of kids) walk(c);
      };
      walk(node);
      return out;
    },
    toggleVisible(path) {
      const node = this.nodeByPath.get(path);
      const leaves = node ? this.eyeLeavesUnder(node) : [];
      // A folder eye drives its children: any of them open -> close them all,
      // none open -> open them all (the tri-state the checkboxes already use).
      // Emitting the whole list keeps it ONE server round-trip.
      if (node && leaves.length > 0
          && !(leaves.length === 1 && leaves[0] === path)) {
        const anyOn = leaves.some((p) => this.visibleSet.has(p));
        this.$emit("eye-toggle", {
          path, paths: leaves, visible: !anyOn, n: ++this.nonce,
        });
        return;
      }
      this.$emit("eye-toggle", { path, n: ++this.nonce });
    },
    onBulk(row) {
      if (row.sep || row.disabled) return;
      const typeSet = row.types ? new Set(row.types) : null;
      const sel = new Set(this.selectedPaths);
      const walk = (nodes) => {
        for (const n of nodes || []) {
          if (!n.disabled && (typeSet ? typeSet.has(n.type) : true)) {
            if (row.clear) sel.delete(n.path); else sel.add(n.path);
          }
          if (n.children && n.children.length) walk(n.children);
        }
      };
      walk(this.tabRoots);
      this.selectedPaths = [...sel];
      this.selectMenuOpen = false;
    },
    onNameInput(e) {
      this.nameInput = e.target.value;
      clearTimeout(this.nameTimer);
      const v = this.nameInput;
      this.nameTimer = setTimeout(() => { this.nameQuery = v; }, 200);
    },
    clearName() { clearTimeout(this.nameTimer); this.nameInput = ""; this.nameQuery = ""; },
    tabKey(i) {
      const t = (this.tabs || [])[i];
      return t && t.name ? String(t.name).toLowerCase() : String(i);
    },
    // Host-driven activation (pick): find the node's tab, open it, expand
    // every ancestor, activate, scroll the row into view.
    revealPath(path) {
      const node = this.nodeByPath.get(path);
      if (!node) return;
      const tabs = this.tabs || [];
      const inTab = (i) => {
        const walk = (ns) => (ns || []).some((n) => n.path === path || walk(n.children));
        return walk(this.pruneTree(this.parsedRoots, this.tabPred(tabs[i])));
      };
      if (tabs.length && !inTab(this.activeTabIndex)) {
        const i = tabs.findIndex((_t, k) => inTab(k));
        if (i >= 0) this.onTab(i);
      }
      const exp = { ...this.expanded };
      const parts = path.split("/");
      for (let k = 2; k < parts.length; k++) exp[parts.slice(0, k).join("/")] = true;
      this.expanded = exp;
      this.setActive(path);
      this.$nextTick(() => {
        const body = this.$refs.body;
        const row = body && body.querySelector('.tn-row[data-path="' + path.replace(/"/g, '\\"') + '"]');
        if (row && row.scrollIntoView) row.scrollIntoView({ block: "center" });
      });
    },
    setActive(path) {
      this.activeByTab = { ...this.activeByTab, [this.tabKey(this.activeTabIndex)]: path };
      this.activePath = path;
      this.$emit("active-by-tab", { ...this.activeByTab });
    },
    onTab(i) {
      this.activeTabIndex = i;
      this.selectMenuOpen = false;
      this.ctxOpen = false;
      this.clearName();
      this.kindFilter = "";
      // The displayed tab's own active node comes back (may be none).
      this.activePath = this.activeByTab[this.tabKey(i)] || null;
    },
    toggleSelectMenu() { this.selectMenuOpen = !this.selectMenuOpen; },
    closeSelectMenu() { this.selectMenuOpen = false; },
    setExpanded(path, open) { this.expanded = { ...this.expanded, [path]: open }; },
    // an action declares the node types it applies to; one without `types`
    // applies everywhere. `when` narrows it further to one side of the
    // checkbox — "selected" for what LEAVES the panel (Remove from stats),
    // "unselected" for what enters it — so a pair of opposite actions never
    // shows the one that would do nothing.
    ctxItemsFor(node) {
      if (!node) return [];
      const t = node.type;
      const ticked = this.selectedSet.has(node.path);
      return (this.contextActions || []).filter(
        (a) => (!a.types || a.types.indexOf(t) >= 0)
          && (!a.when || (a.when === "selected") === ticked));
    },
    openContext(node, event) {
      // nothing applies to this node: the menu still opens, on one disabled
      // line saying why — a gesture that works one row above and does
      // nothing here, without a word, is the silence the rules forbid
      if (!node) return;
      this.ctxNode = node;
      this.ctxPos = { x: event.clientX, y: event.clientY };
      this.ctxOpen = true;
    },
    onCtxAction(a) {
      this.$emit("context-action", { action: a.key, path: this.ctxNode.path, n: ++this.nonce });
      this.ctxOpen = false;
    },
    onKey(e) {
      const row = e.target.closest && e.target.closest(".tn-row");
      if (!row) return;
      const body = this.$refs.body;
      const rows = Array.from(body.querySelectorAll(".tn-row"));
      const idx = rows.indexOf(row);
      const path = row.getAttribute("data-path");
      const entry = this.nodeIndex.get(path);
      const node = entry && entry.node;
      const open = this.filterActive || !!(node && this.expanded[node.path]);
      const focus = (el) => { if (el) { el.focus(); e.preventDefault(); } };
      const sel = (p) => body.querySelector('.tn-row[data-path="' + (p || "").replace(/"/g, '\\"') + '"]');
      switch (e.key) {
        case "ArrowDown": return focus(rows[idx + 1]);
        case "ArrowUp": return focus(rows[idx - 1]);
        case "Home": return focus(rows[0]);
        case "End": return focus(rows[rows.length - 1]);
        case "ArrowRight":
          if (entry && entry.hasChildren && !open) { this.setExpanded(node.path, true); e.preventDefault(); }
          else if (entry && entry.hasChildren && open) { focus(rows[idx + 1]); }
          return;
        case "ArrowLeft":
          if (entry && entry.hasChildren && open) { this.setExpanded(node.path, false); e.preventDefault(); }
          else if (entry && entry.parentPath != null) { focus(sel(entry.parentPath)); }
          return;
        case " ":
        case "Spacebar":
          if (node && !node.disabled) this.toggleSelect(node.path);
          e.preventDefault();
          return;
        case "Enter":
          if (node) this.setActive(node.path);
          e.preventDefault();
          return;
      }
    },
  },
};
</script>

<style>
@import "../../../_shared/panel.css";
</style>

<style scoped>
.fdx { display: flex; flex-direction: column; height: 100%; font-family: system-ui, sans-serif; font-size: 13px; }
.fdx-tabs { display: flex; border-bottom: 1px solid #ddd; flex: 0 0 auto; }
.fdx-tab { flex: 1; padding: 6px 8px; background: #f5f5f5; border: none; cursor: pointer; font-size: 12px; color: #555; }
.fdx-tab.active { background: #fff; color: var(--fp-accent); font-weight: 600; box-shadow: inset 0 -2px 0 var(--fp-accent); }

.fdx-toolbar { flex: 0 0 auto; padding: 6px; border-bottom: 1px solid #eee; display: flex; flex-direction: column; gap: 6px; }
.fdx-filter { display: flex; align-items: center; gap: 4px; }
.fdx-layout { display: flex; align-items: center; gap: 6px; }
.fdx-filter-input { flex: 1 1 auto; min-width: 0; font-size: 12px; padding: 3px 6px; border: 1px solid #cfd8e3; border-radius: 3px; }
.fdx-filter-input:focus { outline: none; border-color: var(--fp-accent); }
.fdx-filter-clear { flex: 0 0 auto; border: none; background: transparent; color: var(--fp-ink-faint); cursor: pointer; font-size: 15px; line-height: 1; padding: 0 4px; }
.fdx-filter-clear:hover { color: var(--fp-accent); }
.fdx-filter-kind { flex: 0 0 auto; max-width: 130px; font-size: 12px; }
.fdx-select { position: relative; display: inline-block; }
.fdx-select-btn { font-size: 12px; padding: 3px 10px; background: #fff; border: 1px solid #cfd8e3; border-radius: 3px; color: var(--fp-accent); cursor: pointer; }
.fdx-select-btn:hover, .fdx-select-btn.open { background: #f0f7ff; border-color: var(--fp-accent); }

.fdx-backdrop { position: fixed; inset: 0; z-index: 10; }
.fdx-menu { position: absolute; top: 100%; left: 0; margin-top: 2px; z-index: 11; min-width: 200px; background: #fff; border: 1px solid #cfd8e3; border-radius: 4px; box-shadow: 0 4px 14px rgba(0,0,0,0.14); padding: 4px 0; max-height: 60vh; overflow: auto; }
.fdx-ctxmenu { position: fixed; z-index: 11; min-width: 180px; background: #fff; border: 1px solid #cfd8e3; border-radius: 4px; box-shadow: 0 4px 14px rgba(0,0,0,0.18); padding: 4px 0; max-height: 70vh; overflow: auto; }
.fdx-ctx-title { padding: 3px 12px 5px; font-size: 11px; font-weight: 600; color: var(--fp-accent); border-bottom: 1px solid #eee; margin-bottom: 4px; max-width: 240px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fdx-menu-item { padding: 4px 12px; cursor: pointer; white-space: nowrap; color: #333; }
.fdx-menu-item:hover { background: #f0f7ff; color: var(--fp-accent); }
.fdx-menu-item.child { padding-left: 26px; color: #555; font-size: 12px; }
.fdx-menu-item.danger { color: #c62828; }
.fdx-menu-item.danger:hover { background: #ffebee; color: #c62828; }
.fdx-menu-item.disabled { color: #8a8a8a; cursor: default; white-space: normal; max-width: 260px; }
.fdx-menu-item.disabled:hover { background: transparent; color: #8a8a8a; }
.fdx-menu-sep { height: 1px; background: #eee; margin: 4px 0; }
.fdx-menu-none { padding: 6px 12px; }

.fdx-body { flex: 1 1 0; overflow: auto; padding: 4px 0; }
</style>
