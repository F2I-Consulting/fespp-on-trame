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
      <!-- How the forest is laid out: the objects at the top, grouped under
           the interpretation they carry, or under feature then
           interpretation. These are readings of the SAME data, hence a
           segmented control (UI rule R13). A grid keeps its whole block
           (geometry, properties, SubRep, blocked wellbores) in every layout:
           the grouping rows sit above the block, never inside it. -->
      <!-- the strips start on one edge, their labels in a column before them -->
      <div v-if="(layout && layoutOffered) || domainOffered" class="fdx-strips">
        <template v-if="layout && layoutOffered">
          <span class="fp-lab" title="How the trees are laid out">Layout</span>
          <div class="fdx-layout">
            <fp-seg :model-value="layout" :options="layoutOptions"
                    title="How the trees are laid out — the rows change place, nothing is unticked"
                    @update:model-value="$emit('layout-change', $event)" />
          </div>
        </template>
        <!-- depth and time are two vertical references: the objects of one
             only — offered when the file holds both; an object with no CRS
             shows under each; no tooltip on depth vs time -->
        <template v-if="domainOffered">
          <span class="fp-lab">Domain</span>
          <div class="fdx-domain">
            <fp-seg :model-value="domainFilter || 'all'" :options="DOMAIN_FILTERS"
                    @update:model-value="domainFilter = $event === 'all' ? '' : $event" />
          </div>
        </template>
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
        :converted="convertedSet"
        :undrawn="undrawnSet"
        :replaced="replacedSet"
        :fixed="fixedSet"
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

    <fp-menu class="fdx-ctx" :at="ctxOpen ? ctxPos : null"
             :title="(ctxNode && ctxNode.title) || 'this object'"
             :items="ctxItems" :empty-why="contextEmptyLabel"
             @pick="onCtxAction" @close="ctxOpen = false" />
  </div>
</template>

<script>
import TreeNode from "./TreeNode.vue";
import FpEmpty from "../../../_shared/components/FpEmpty.vue";
import FpSeg from "../../../_shared/components/FpSeg.vue";
import FpSelect from "../../../_shared/components/FpSelect.vue";
import FpMenu from "../../../_shared/components/FpMenu.vue";
import { downloadAll } from "../../../_shared/download.js";
import { onEscape } from "../../../_shared/escape.js";
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
 * Per-node data comes from XML attributes: title (or label), type, eye
 * ('rep'|'array'|'marker', derived from the type when absent), color,
 * crs/dims/count/units/info — and `family`, the tab
 * a node of a SYNTHETIC assembly belongs to when its type says nothing of it
 * (the Statistics view's rep folders name the family of the representation they
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

/*
 * The drawing of each RESQML type, an SVG path from the application's own
 * set (widgets/_shared/icons/fespp-icons.js); the `kindIcons` prop overrides
 * it per type. The plugin speaks TWO
 * vocabularies for a node's `type`: a representation carries its RESQML
 * class ("IjkGrid", "TriangulatedSet"), everything else the name of its
 * TreeViewNodeType ("WellboreFrame", "PropertiesFolder"). Both are mapped,
 * which is why several keys share one drawing.
 *
 * A type with no drawing of its own keeps an @mdi/js glyph: a bare property, and
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

  // the synthetic rows of the Statistics tree, grouped by PWLS
  // kind: a kind folder holds properties, a rep folder stands for the object
  // they were read from (its own drawing comes from `family`, in TreeNode),
  // and an item is a property whose `propType` names its drawing
  KindFolder: FI.folderProperties, RepFolder: FI.gridContainer,
  CompareItem: mdiChartBoxOutline,
};

// A rep folder of the Statistics tree draws the FAMILY it belongs to — the tab
// the data tree would file it under — rather than one folder for all three.
const FAMILY_ICONS = {
  Reservoir: FI.gridContainer, Surface: FI.surfaceTin, Well: FI.wellbore,
};
const FALLBACK_ICON = FI.unknown;

// Types the "Select ▾" menu leaves out: a bulk tick never loads property values.
const BULK_EXCLUDE_RE = /property$/i;

const DEFAULT_TABS = [
  // GridContainer wraps the grid (SolidColor variant) — matching it makes
  // pruneTree keep its whole subtree (geometry + properties + blocked
  // wellbore); the bare grid types match a flat assembly with no container.
  { name: "Reservoir", types: ["GridContainer", "IjkGrid", "UnstructuredGrid", "ExplicitStructuredGrid"], lattice: "leave" },
  { name: "Surface", types: ["TriangulatedSet", "Grid2d", "Grid2dRepresentation", "Polyline", "PolylineSet", "PointSet"] },
  { name: "Well", types: ["Wellbore", "Trajectory", "WellboreTrajectory", "MarkerFrame"] },
  // the lattice grids (a velocity model, a seismic cube), filed by row
  { name: "Seismic", types: [], lattice: "take" },
];

const DEFAULT_SELECT_GROUPS = [
  { label: "All Grids", types: ["GridContainer", "IjkGrid", "UnstructuredGrid", "ExplicitStructuredGrid"] },
  { label: "All Surfaces", types: ["TriangulatedSet", "Grid2d", "Grid2dRepresentation", "Polyline", "PolylineSet", "PointSet"] },
  { label: "All Wells", types: ["Wellbore"] },
  { label: "All Trajectories", types: ["Trajectory", "WellboreTrajectory"] },
  { label: "All Markers", types: ["MarkerFrame"] },
  { label: "All Features", types: ["Feature"] },
];

// The FESPP vtkDataAssembly carries no `eye` attribute: eyeForType derives it
// from the node type — 'rep' for a representation, 'array' for a property.
// An explicit `eye` attribute on a node wins.
const REP_KINDS = new Set([
  "IjkGrid", "UnstructuredGrid", "ExplicitStructuredGrid", "Grid2d",
  "Grid2dRepresentation", "TriangulatedSet", "Polyline", "PolylineSet", "PointSet",
  // the plugin types a SubRepresentation "Sub" (see the icons above): both
  // spellings are a representation, with an eye
  "BlockedWellbore", "SubRepresentation", "Sub",
  "Wellbore", "Trajectory", "WellboreTrajectory", "Frame", "MarkerFrame",
]);
// Grid geometry leaf types (a grid known by reference only says so, below).
const GEOMETRY_TYPES = new Set(["IjkGrid", "UnstructuredGrid", "ExplicitStructuredGrid"]);
// The geometry leaf a container wraps — hoisted OUT of its PropertiesFolder
// to sit beside it, relabelled "geometry": a grid, and since 27/10 a
// surface, a polyline or a point set (the plugin lays them out alike).
const CONTAINED_TYPES = new Set([...GEOMETRY_TYPES, "Grid2d", "Grid2dRepresentation",
  "TriangulatedSet", "Polyline", "PolylineSet", "PointSet"]);
// The folders of the layout: rows the plugin lays out, not objects of the
// file — nothing to read on them, so no right-click menu; and one with
// nothing under it is not drawn (the PO's users, 28/10: a grid whose
// SubRepresentations all stand on faces had an empty SubRep folder)
const FOLDER_TYPES = new Set(["PropertiesFolder", "SubRepresentationFolder",
  "BlockedWellboreFolder", "WellboreLogsFolder", "WellboreMarkersFolder",
  "WellboreCompletionsFolder", "KindFolder", "Interpretation", "Feature"]);
// What a row is filed and counted as: a container is the geometry it wraps
// (a surface's container goes to the Surface tab, wears a surface's icon).
function kindOf(n) {
  return n.type === "GridContainer" && n.geomType ? n.geomType : n.type;
}
// a container of anything but a grid is not counted by the "Select" menu:
// its geometry leaf is, once (a grid's container keeps its row there)
function countable(n) {
  return !(n.type === "GridContainer" && n.geomType && !GEOMETRY_TYPES.has(n.geomType));
}
// A grid known by reference only: the file read names it but does not carry
// it (a dataset split over several EPCs, the properties' file read before the
// grid's). The plugin
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
// The tabs where only some layouts mean something: a well carries no
// interpretation nor feature, so there its logs are laid out by kind or not.
const TAB_LAYOUTS = { Well: ["flat", "kind"] };

// The three layouts the plugin can build the forest in (its TreeHierarchyMode).
const LAYOUTS = [
  { value: "flat", label: "Representation",
    title: "Every representation at the top: the grids, the surfaces, the wells" },
  { value: "by_interpretation", label: "Interpretation",
    title: "The representations grouped under the interpretation they carry — a grid keeps its geometry, properties, SubRep and blocked wellbores together beneath it" },
  { value: "by_feature_and_interpretation", label: "Feature",
    title: "Feature, then its interpretations, then their representations — the geology first, the objects under it" },
  { value: "kind", label: "Prop. kind",
    title: "Property kind — the properties by what they measure, then their representation;"
      + " the geometries and the partial objects as kinds of their own; after them, the objects with the rest of what they hold" }
];
// Rows a layout draws: no object of the file behind them
const LAYOUT_ROW = "layout://";
const isLayoutRow = (path) => String(path).startsWith(LAYOUT_ROW);
const NO_KIND = "no kind";
// what the Kind layout files as kinds of their own, beside the property kinds
const GEOMETRY_KIND = "geometry";
const PARTIAL_KIND = "partial";
const byTitle = (a, b) => (a.sortLast ? 1 : 0) - (b.sortLast ? 1 : 0)
  || a.title.localeCompare(b.title, undefined, { numeric: true, sensitivity: "base" });
// The vertical domains an object's CRS places it in (the PO, 28/10).
const DOMAIN_FILTERS = [
  { value: "all", label: "All" },
  { value: "depth", label: "Depth" },
  { value: "time", label: "Time" },
];
function eyeForType(kind) {
  if (!kind) return null;
  if (kind === "Marker") return "marker";        // each marker toggles its own eye
  if (REP_KINDS.has(kind)) return "rep";
  if (/property$/i.test(kind)) return "array";
  if (COLLAPSE_RE.test(kind) || kind === "TimeSeries") return "array";
  return null;
}
// A wellbore's children: the log frames sit in a "logs"
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
// A container is ticked and drawn as the object it wraps: it wears the
// vertical domain the plugin set on that representation (28/10), its tag
// with it, and everything under it shares it.
function adoptDomain(container) {
  const g = container.children.find((c) => c.vdomain && CONTAINED_TYPES.has(c.type));
  if (!g) return;
  const dom = g.vdomain;
  container.vdomain = dom;
  container.domainTag = dom;
  const spread = (n) => {
    for (const c of n.children || []) {
      c.vdomain = dom;
      c.anyDomain = true;
      delete c.domainTag;
      spread(c);
    }
  };
  spread(container);
}
function hoistGridGeometry(container) {
  const props = container.children.find((c) => c.type === "PropertiesFolder");
  if (!props || !props.children) return;
  const gi = props.children.findIndex((c) => CONTAINED_TYPES.has(c.type)
    || (c.partial && CONTAINED_TYPES.has(c.supporttype || "")));
  if (gi < 0) return;
  const geom = props.children.splice(gi, 1)[0];
  geom.title = "geometry";
  // the container is what it wraps: its tab, its icon (kindOf)
  container.geomType = geom.partial ? (geom.supporttype || "") : geom.type;
  if (container.geomType && !GEOMETRY_TYPES.has(container.geomType)) container.iconType = container.geomType;
  if (isPartialGeometry(geom)) {
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
  // Globe's pruned assembly): an empty "properties" row would be noise.
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
  components: { TreeNode, FpEmpty, FpSeg, FpSelect, FpMenu },
  props: {
    // The vtkDataAssembly serialized to XML (SerializeToXML).
    assembly: { type: String, default: "" },
    // Tabs as kind filters: [{ name, types: [...], lattice? }] — a node is in
    // a tab when its type is listed or its `family` is the tab's name; the
    // rows of `latticeRows` go to the tab with `lattice: "take"` and leave
    // the one with `lattice: "leave"`. [] -> single tree.
    tabs: { type: Array, default: () => DEFAULT_TABS },
    // Session seed (paths); the component owns the selection afterwards.
    initialSelected: { type: Array, default: () => [] },
    // Controlled selection (two-way with `selected-changed`): when the host
    // changes this (e.g. another view's tree loaded something), the tree
    // reflects it.
    selected: { type: Array, default: () => [] },
    // bumped by the server whenever the boxes must read `selected` again
    boxesNonce: { type: Number, default: 0 },
    // Controlled ACTIVE node (two-way with `active-changed`): when the host
    // activates a node (e.g. a pick in the render view), the tree switches to
    // its tab, expands its ancestors, highlights it and scrolls it into view.
    active: { type: String, default: "" },
    // Visibility is SERVER-OWNED, one-way: the chips render this prop as is.
    // The widget never writes an eye list — an eye click emits `eye-toggle`
    // and the host applies it. A client-written full list would race the
    // server's born-visible / born-hidden edits and overwrite them.
    visible: { type: Array, default: () => [] },
    // the objects drawn converted with the time-depth law (server-owned,
    // one-way): their row says so
    converted: { type: Array, default: () => [] },
    // the ticked objects of the other domain the view does not draw: no
    // eye on their rows (server-owned, one-way)
    undrawn: { type: Array, default: () => [] },
    // the geometries an extract stands in for in the view: their eye shown
    // closed, what is drawn being the extract (server-owned, one-way)
    replaced: { type: Array, default: () => [] },
    // those of them the view never converts (a velocity model of the data,
    // anything in a view in time): their tag is no button
    fixed: { type: Array, default: () => [] },
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
    // The layout in force, one of LAYOUTS ("" = no layout control: the
    // Statistics tree). A pick emits `layout-change`; the host applies it (a new
    // assembly, every path changed) and writes the value back.
    layout: { type: String, default: "" },
    // the assembly itself is laid out by kind (the Statistics tree)
    kindBuilt: { type: Boolean, default: false },
    // What the menu says on a node none of `contextActions` applies to. A
    // gesture is never silent: a right-click that opened nothing would not
    // tell a node with no action from a tree with no menu. Each tree names
    // its own reason; this default only covers a caller that names none.
    contextEmptyLabel: { type: String, default: "No action on this node." },
    // Rows the SESSION adds (the PO, 15/10): [{path, parent, title, kind:
    // "extract" | "derived", type, visible?, info}], hung under the row
    // whose path is `parent`. Made in the session, never written to the
    // file: drawn in a colour of their own, "disposable".
    sessionRows: { type: Array, default: () => [] },
    // rows not shown, nor what is under them: the velocity model's earlier
    // versions, read by the reader and left behind (app/features/time_depth_tree)
    hiddenRows: { type: Array, default: () => [] },
    // {path: "#rrggbb…"}: the colour a LOADED representation is drawn in when
    // no property colours it (its grid folder too): the row wears it as a
    // chip, so the tree says which object is which in 3D (the PO, 20/10)
    solidColors: { type: Object, default: () => ({}) },
    // {row path: highlighted cells}: such a row offers "+" — keep or remove
    // the selection.
    selectionCounts: { type: Object, default: () => ({}) },
    // the rows of the IJK grids whose geometry is a lattice (a velocity
    // model): they wear their own drawing
    latticeRows: { type: Array, default: () => [] },
    // the row of the velocity model the conversions read: its title says so
    activeModel: { type: String, default: "" },
  },
  emits: ["selected-changed", "eye-toggle", "active-changed", "active-by-tab", "active-again", "colour-request", "context-action", "layout-change", "node-open",
          "extract", "session-eye", "session-remove", "session-rename", "domain-toggle"],
  data() {
    return {
      LAYOUTS,
      DOMAIN_FILTERS,
      // "" (both), "depth" or "time"
      domainFilter: "",
      selectedPaths: [...((this.selected && this.selected.length)
        ? this.selected : (this.initialSelected || []))],
      applyingSelected: false,
      expanded: {},
      // the extracts already seen (their folder opened once, then the reader's)
      seenExtracts: new Set(),
      // Active node kept PER TAB (keyed by tabKey) — switching tabs restores
      // that tab's active node; `activePath` is the DISPLAYED tab's one.
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
      // what makes each gesture a new value of its state var: from the clock, as a
      // new tree (its view anchored again, the page reloaded) writes to the same var
      // and the server drops a value equal to the last one
      nonce: Date.now(),
    };
  },
  watch: {
    // a new extract shows at once: its grid and its SubRep folder open, the
    // tree scrolls to its row and the row lights up a moment — open
    // properties above it hid it (the PO, 21/10)
    sessionRows(rows) {
      const fresh = (rows || []).filter((r) => r.kind === "extract" && !this.seenExtracts.has(r.path));
      if (!fresh.length) return;
      fresh.forEach((r) => this.seenExtracts.add(r.path));
      this.$nextTick(() => {
        for (const r of fresh) {
          const n = this.nodeByPath.get(r.path);
          if (n && n.folder) {
            this.setExpanded(n.container, true);
            this.setExpanded(n.folder, true);
          }
        }
        // the rows of the opened folders are drawn on the next tick
        this.$nextTick(() => this.showRow(fresh[fresh.length - 1].path));
      });
    },
    selectedPaths(v) {
      if (this.applyingSelected) return; // prop-driven update -> don't echo back
      this.$emit("selected-changed", v);
    },
    // The server owns the boxes (the one grammar, the PO 18/10: a tick is the
    // session's load, and an untick of what another view uses asks first).
    // The click shows at once, and every time the server publishes or puts
    // back the selection it bumps this number: the boxes then go back to
    // what it says — even when that is the very list it already sent, which
    // a refused or vetoed tick leaves unchanged.
    boxesNonce() {
      this.applyingSelected = true;
      this.selectedPaths = [...(this.selected || [])];
      this.$nextTick(() => { this.applyingSelected = false; });
    },
    activePath(v) { this.$emit("active-changed", v); },
    // The tab list can shrink (the Statistics tree's `Other` exists only while
    // the file has a rep of no family): an index past its end would draw the
    // first tab's rows under no highlighted button.
    tabs(v) { if (v && v.length && this.activeTabIndex >= v.length) this.onTab(0); },
    active(v) {
      if (!v) {
        // the host let the active node go (unticked, unloaded): the row is
        // no longer active here either, so a tick or a click on it makes it
        // active again — kept, it would say nothing to the host
        if (this.activePath) {
          const gone = this.activePath;
          this.activeByTab = Object.fromEntries(Object.entries(this.activeByTab).filter(([, p]) => p !== gone));
          this.activePath = null;
        }
        return;
      }
      if (v === this.activePath) return;
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
    iconMap() { return { _fallback: FALLBACK_ICON, _lattice: FI.gridLattice, _partial: mdiAlertOutline, _ts: FI.timeMark, _logChannel: FI.logChannel, _family: FAMILY_ICONS, _eyeFull: mdiEye, _eyeOutline: mdiEyeOutline, SelectionExtract: FI.selectVolume, ...KIND_ICONS, ...(this.kindIcons || {}) }; },
    selectedSet() { return new Set(this.selectedPaths); },
    visibleSet() { return new Set(this.visible || []); },
    convertedSet() { return new Set(this.converted || []); },
    undrawnSet() { return new Set(this.undrawn || []); },
    replacedSet() { return new Set(this.replaced || []); },
    fixedSet() { return new Set(this.fixed || []); },
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
      // property before the session has read it (the Statistics view's does —
      // the assembly names every property of the file for free). The leaf
      // stays tickable; the tick is what loads it.
      // `colorRGB` is the colour the DATA declares for this object (a RESQML
      // GraphicalInformationSet, read by the plugin): when it is there the
      // row's icon is drawn in it instead of its family colour.
      // `vdomain` ("depth" | "time", the plugin reads it off the object's
      // CRS) is inherited: a property, a folder sits in its object's domain
      const META = ["crs", "dims", "count", "units", "info", "componentCount",
        "loadState", "supporttype", "colorRGB", "propertyKind",
        "interpretation", "interpretationTitle", "feature", "featureTitle"];
      // siblings sorted alphabetically ascending at every level (case-insensitive,
      // natural for trailing numbers e.g. WELL-2 before WELL-10).
      // a host may put a row after its siblings (`sortLast`: the Statistics tree's
      // parts of a grid, after the kinds).
      const toNode = (el, parentPath, parentDomain) => {
        const path = parentPath + "/" + el.tagName;
        // FESPP assembly: the node's TYPE ("IjkGrid", "TimeSeries") is in
        // `type`. An assembly written by an earlier plugin build carries it
        // in `kind` beside a numeric `type`, hence the digit test before the
        // fallback (in RESQML a kind is the PropertyKind — depth, volume —
        // never a node type). The display name is `title` (`label` is
        // sanitized); there is no `eye`.
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
        const own = el.getAttribute("vdomain");
        const dom = own || parentDomain;
        if (dom) node.vdomain = dom;
        // the row where a domain starts wears it (the object, not its
        // properties nor its folders) — when the file holds both, below
        if (own && own !== parentDomain) node.domainTag = own;
        // The property's own type on a synthetic MR/TS leaf drives its icon.
        // `propKind` is the same attribute as an earlier plugin build names
        // it, read as a fallback.
        const pk = el.getAttribute("propType") || el.getAttribute("propKind");
        if (pk) node.propType = pk;
        const fam = el.getAttribute("family");
        if (fam) node.family = fam;
        if (el.getAttribute("sortLast")) node.sortLast = true;
        // a folder with nothing to tick: the session hangs its rows under it
        if (el.getAttribute("noCheck")) node.noCheck = true;
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
            node.children.push(toNode(child, path, node.vdomain));
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
          node.children = node.children.filter((c) => !(FOLDER_TYPES.has(c.type) && !c.children.length));
          node.children.sort(byTitle);
          // SolidColor variant: pull the grid geometry out of "properties".
          if (nodeType === "GridContainer") {
            hoistGridGeometry(node);
            if (!node.vdomain) adoptDomain(node);
          }
          // A well laid out like a grid: its folders first (logs, markers,
          // completions), the trajectory after them.
          if (nodeType === "Wellbore") orderWellChildren(node);
        }
        // whether a domain is at or under the row: a folder grouping objects
        // of both is kept by the domain filter for the rows it holds
        node.anyDomain = !!node.vdomain || node.children.some((c) => c.anyDomain);
        return node;
      };
      const rootPath = "/" + root.tagName;
      const hidden = new Set(this.hiddenRows || []);
      const roots = Array.from(root.children)
        .filter((c) => c.tagName !== "dataset" && !hidden.has(rootPath + "/" + c.tagName))
        .map((c) => toNode(c, rootPath, ""))
        .sort(byTitle);
      // depth and time told apart on the rows only when the file holds both
      // (the PO, 28/10): a file all in depth wears no tag
      const doms = new Set();
      const tagged = [];
      const scan = (nodes) => {
        for (const n of nodes) {
          if (n.domainTag) { doms.add(n.domainTag); tagged.push(n); }
          if (n.anyDomain) scan(n.children);
        }
      };
      scan(roots);
      if (doms.size < 2) tagged.forEach((n) => { delete n.domainTag; });
      // the session's own rows, last among their parent's children; a row
      // whose parent is not in this tree is not drawn
      if ((this.sessionRows || []).length) {
        const byPath = new Map();
        const siblingsOf = new Map();   // path -> the list holding the node
        const walk = (nodes) => {
          for (const n of nodes) {
            byPath.set(n.path, n);
            siblingsOf.set(n.path, nodes);
            walk(n.children || []);
          }
        };
        walk(roots);
        for (const r of this.sessionRows) {
          const parent = byPath.get(r.parent);
          if (!parent || !r.path) continue;
          const row = {
            path: r.path, title: r.title || r.path, type: r.type || "", info: r.info || "",
            session: r.kind || "session", sessionVisible: !!r.visible,
            // a panel's tree: the row is the 3D view's to delete, and its eye
            // means "in this panel" ([hidden title, shown title])
            sessionRemovable: r.removable !== false,
            sessionEyeTitles: Array.isArray(r.eye_titles) ? r.eye_titles : null,
            eye: "", children: [],
            // drawn one step in, right under the object it was made from
            under: r.kind === "extract",
            // in the domain of the object it was made from
            vdomain: parent.vdomain, anyDomain: !!parent.vdomain,
            // and in its tab, on a tree whose tabs go by family
            family: parent.family,
          };
          // a grid's extract is a subset of its cells, as a SubRepresentation
          // is: it goes in the grid's SubRep folder, made when the grid has
          // none (the PO, 20/10) — a folder of the session, no box, no eye,
          // no menu, a path the file has not
          if (r.kind === "extract" && parent.children.some((c) => GEOMETRY_TYPES.has(c.type))) {
            let sub = parent.children.find((c) => c.type === "SubRepresentationFolder");
            if (!sub) {
              sub = {
                path: "session://subreps" + parent.path, title: "SubRep",
                type: "SubRepresentationFolder", eye: "", children: [], noCheck: true,
                info: "The cells kept or taken out of this grid in this session",
                vdomain: parent.vdomain, anyDomain: !!parent.vdomain,
              };
              parent.children.push(sub);
              byPath.set(sub.path, sub);
            }
            row.under = false;
            row.folder = sub.path;
            row.container = parent.path;
            sub.children.push(row);
            continue;
          }
          // an extract right under the object it was selected on (the PO,
          // 20/10): a grid's "geometry" row, or the object's own row (a
          // point set, a surface) — seen without opening anything; the
          // extracts of one object follow each other. Anything else last
          // among its parent's children
          const geom = r.kind === "extract"
            ? parent.children.findIndex((c) => GEOMETRY_TYPES.has(c.type)) : -1;
          const list = r.kind === "extract" && geom < 0 ? siblingsOf.get(parent.path) : null;
          if (geom >= 0 || list) {
            const into = geom >= 0 ? parent.children : list;
            let at = (geom >= 0 ? geom : into.indexOf(parent)) + 1;
            while (at < into.length && into[at].session === "extract") at++;
            into.splice(at, 0, row);
          } else {
            parent.children.push(row);
          }
        }
      }
      return roots;
    },

    // The forest as the layout draws it: the Kind layout is drawn here, the
    // others by the host's assembly (`kindBuilt`: its assembly is by kind)
    layoutRoots() {
      if (this.layout === "kind") return this.kindBuilt ? this.parsedRoots : this.byKind(this.parsedRoots);
      if (this.layout === "by_interpretation") return this.byOwner(this.parsedRoots, false);
      if (this.layout === "by_feature_and_interpretation") return this.byOwner(this.parsedRoots, true);
      return this.parsedRoots;
    },

    nodeByPath() {
      const map = new Map();
      const walk = (nodes) => { for (const n of nodes || []) { map.set(n.path, n); if (n.children) walk(n.children); } };
      walk(this.layoutRoots);
      return map;
    },

    // Roots for the active tab: the whole forest pruned to the tab's nodes
    // (matches keep their subtree; ancestors kept for context). No tabs -> all.
    tabRoots() {
      const tabs = this.tabs || [];
      if (!tabs.length) return this.layoutRoots;
      return this.pruneTree(this.layoutRoots, this.tabPred(tabs[this.activeTabIndex] || tabs[0]));
    },
    tabNodeByPath() {
      const map = new Map();
      const walk = (nodes) => { for (const n of nodes || []) { map.set(n.path, n); if (n.children) walk(n.children); } };
      walk(this.tabRoots);
      return map;
    },

    // Whether the displayed tab shows the layout control, and the layouts it
    // offers there (see TAB_LAYOUTS).
    layoutOffered() {
      return this.layoutOptions.length > 1;
    },
    layoutOptions() {
      const t = (this.tabs || [])[this.activeTabIndex];
      const only = !this.kindBuilt && t ? TAB_LAYOUTS[t.name] : null;
      return only ? LAYOUTS.filter((l) => only.includes(l.value)) : LAYOUTS;
    },
    // Per-tab ROOT counts for the tab labels ("Reservoir (2)") — the
    // top-level item count of each tab's subtree.
    tabCounts() {
      // the objects of the tab, however a layout groups them
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
    // the domains the forest holds: the filter is offered when it holds both
    domainsPresent() {
      const out = new Set();
      const walk = (nodes) => {
        for (const n of nodes || []) {
          if (n.vdomain) { out.add(n.vdomain); continue; }
          if (n.anyDomain) walk(n.children);
        }
      };
      walk(this.parsedRoots);
      return out;
    },
    domainOffered() { return this.domainsPresent.size > 1; },
    // the tab's rows of the domain chosen, and those with no CRS
    domainRoots() {
      const f = this.domainOffered ? this.domainFilter : "";
      if (!f) return this.tabRoots;
      return this.pruneTree(this.tabRoots, (n) => (n.vdomain ? n.vdomain === f : !n.anyDomain));
    },
    filteredRoots() {
      if (!this.filterActive) return this.domainRoots;
      return this.pruneTree(this.domainRoots, (n) => this.matchNode(n));
    },
    // The empty state (UI rule R8): what the body would list and the gesture
    // that fills it — the tab's family is named when it is the tab that is
    // empty.
    emptyState() {
      if (!this.parsedRoots.length) {
        return { shows: "The objects of the open file, one row each.",
          gesture: "Click “Import data” in the top bar to fill it.",
          why: "No data is loaded yet." };
      }
      if (this.domainOffered && this.domainFilter && !this.domainRoots.length) {
        return { shows: "The objects of this tab in " + this.domainFilter + ".",
          gesture: "Pick All above, or the other domain.",
          why: "This tab holds none in " + this.domainFilter + "." };
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

    // an empty list opens the menu all the same, with `contextEmptyLabel`
    // as its one disabled line (fp-menu, R16)
    ctxItems() {
      return this.ctxItemsFor(this.ctxNode);
    },

    // How many nodes of each type the tab shows are ticked.
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
    // kinds are all ticked reads "Clear …" and removes them; when only part
    // of the tab is ticked, a last row clears everything the tab shows.
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
      // an extract row is not a node of the file: nothing to activate
      // the row already active: no change of node tells the host that the
      // reader came back to it (`active-again`)
      const activate = (path) => {
        if (String(path).startsWith("session://") || isLayoutRow(path)) return;
        if (this._touched === path) { this._touched = null; return; }
        if (path === this.activePath) this.$emit("active-again", path);
        this.setActive(path);
      };
      // any click on a row, its box, eye or colour included, makes it the
      // active node (the PO, 23/11); a click on the active row's controls
      // says nothing more — its title alone tells the host the reader came
      // back to it
      const touch = (path) => {
        this._touched = null;
        if (String(path).startsWith("session://") || isLayoutRow(path) || path === this.activePath) return;
        this._touched = path;
        this.setActive(path);
      };
      return {
        toggleSelect: (path) => this.toggleSelect(path),
        toggleVisible: (path) => this.toggleVisible(path),
        activate,
        touch,
        toggleExpand: (path) => this.setExpanded(path, !this.expanded[path]),
        // a right-click is a click first: the row becomes the active one
        context: (node, event) => {
          activate(node.path);
          // a folder of the layout has nothing to act on; a leaf with no box still does
          if ((!node.noCheck || node.eye) && !FOLDER_TYPES.has(node.type)) this.openContext(node, event);
        },
        // a lattice grid: its row, and its geometry under it
        isLattice: (node) => (node.type === "GridContainer" || node.type === "IjkGrid")
          && (this.latticeRows || []).some((r) => node.path === r || String(node.path).startsWith(r + "/")),
        isActiveModel: (node) => !!this.activeModel && node.path === this.activeModel,
        color: (node, kind) => this.$emit("colour-request", { path: node.path, kind, n: ++this.nonce }),
        // the session's own rows and the "+" of a highlighted grid
        selCount: (path) => Number((this.selectionCounts || {})[path] || 0),
        solidColour: (path) => {
          const c = (this.solidColors || {})[path];
          return c ? String(c).slice(0, 7) : "";
        },
        extract: (node, mode) => this.$emit("extract", { path: node.path, mode, n: ++this.nonce }),
        sessionEye: (node) => this.$emit("session-eye", { path: node.path, n: ++this.nonce }),
        domainToggle: (node) => this.$emit("domain-toggle", { path: node.path, n: ++this.nonce }),
        sessionRemove: (node) => this.$emit("session-remove", { path: node.path, n: ++this.nonce }),
        sessionRename: (node, title) => this.$emit("session-rename", { path: node.path, title, n: ++this.nonce }),
      };
    },
  },
  mounted() {
    // Escape closes the Select menu (the right-click menu closes itself)
    this._unEscape = onEscape(() => { this.selectMenuOpen = false; });
    // a tree mounted on an active node the host named before it was there
    // (a panel opened by the very gesture that names it) shows it
    if (this.active && this.active !== this.activePath) this.revealPath(this.active);
  },
  beforeUnmount() {
    if (this._unEscape) this._unEscape();
  },
  methods: {
    // bring a row into sight and light it up a moment
    showRow(path) {
      const esc = window.CSS && CSS.escape ? CSS.escape(path) : String(path).replace(/"/g, '\\"');
      const el = this.$el && this.$el.querySelector(`.tn-row[data-path="${esc}"]`);
      if (!el) return;
      el.scrollIntoView({ block: "nearest", behavior: "smooth" });
      el.classList.remove("tn-flash");
      void el.offsetWidth;     // restart the animation on a second extract
      el.classList.add("tn-flash");
      setTimeout(() => el.classList.remove("tn-flash"), 2600);
    },
    kindLabel(type) { return KIND_LABELS[type] || (type.endsWith("s") ? type : type + "s"); },
    countTypes(nodes, counts) {
      for (const n of nodes || []) {
        if (!n.disabled && n.type && countable(n)) counts[n.type] = (counts[n.type] || 0) + 1;
        if (n.children && n.children.length) this.countTypes(n.children, counts);
      }
      return counts;
    },
    // The Kind layout: a row per kind, a row per object under it, its
    // properties under that (the same nodes, on their own paths: a tick or an
    // eye there is theirs) — a well's logs as a grid's properties. A grid's
    // geometry and the partial objects are kinds too. After them the objects,
    // with what they hold but these.
    byKind(roots) {
      const preds = (this.tabs || []).map((tab) => [tab, this.tabPred(tab)]);
      const tabOf = (n) => {
        const hit = preds.find(([, pred]) => pred(n));
        return hit ? hit[0].name : "";
      };
      const kinds = new Map();
      const file = (leaf, object, kind = leaf.propertyKind || NO_KIND) => {
        if (!kinds.has(kind)) kinds.set(kind, new Map());
        const objects = kinds.get(kind);
        if (!objects.has(object.path)) {
          objects.set(object.path, {
            path: LAYOUT_ROW + "kind/" + kind + "/" + object.path, title: object.title, type: "RepFolder", family: tabOf(object),
            domainTag: object.domainTag, vdomain: object.vdomain, anyDomain: !!object.vdomain, children: [],
          });
        }
        objects.get(object.path).children.push(leaf);
      };
      const rest = (n, object) => {
        if (!n.children || !n.children.length) return n;
        const owner = n.type === "GridContainer" || n.type === "Wellbore" || REP_KINDS.has(n.type)
          ? (object || n) : object;
        const children = [];
        for (const c of n.children) {
          if (owner && c.partial) file(c, owner, PARTIAL_KIND);
          else if (n.type === "GridContainer" && c.type === n.geomType) file(c, n, GEOMETRY_KIND);
          else if (owner && !c.session && eyeForType(c.type) === "array") file(c, owner);
          else {
            const kept = rest(c, owner);
            if (kept) children.push(kept);
          }
        }
        return children.length || !FOLDER_TYPES.has(n.type) ? { ...n, children } : null;
      };
      const objects = roots.map((n) => rest(n, null)).filter(Boolean);
      const folders = [...kinds.entries()].map(([kind, reps]) => ({
        path: LAYOUT_ROW + "kind/" + kind, title: kind, type: "KindFolder", children: [...reps.values()].sort(byTitle),
        // what cannot be read comes last
        sortLast: kind === PARTIAL_KIND,
      })).sort(byTitle);
      return [...folders, ...objects];
    },
    // The Interpretation and Feature layouts: the same objects on their own paths,
    // under a row of their interpretation, itself under one of its feature. An object
    // with none stays at the top, after them.
    byOwner(roots, withFeature) {
      const rows = new Map();
      const row = (kind, type, uuid, title, into) => {
        const path = LAYOUT_ROW + kind + "/" + uuid;
        if (!rows.has(path)) {
          rows.set(path, { path, title, type, children: [] });
          into.push(rows.get(path));
        }
        return rows.get(path).children;
      };
      const top = [];
      const objects = [];
      for (const n of roots) {
        if (!n.interpretation) {
          objects.push(n);
          continue;
        }
        const into = withFeature && n.feature ? row("feature", "Feature", n.feature, n.featureTitle, top) : top;
        row("interpretation", "Interpretation", n.interpretation, n.interpretationTitle, into).push(n);
      }
      rows.forEach((r) => r.children.sort(byTitle));
      return [...top.sort(byTitle), ...objects];
    },
    // A tab keeps a node whose type it lists, or whose `family` is its name.
    // The lattice grids are filed by row, their type being a reservoir
    // grid's: a tab with `lattice: "take"` takes their rows and what is under
    // them, one with `lattice: "leave"` leaves them out.
    tabPred(t) {
      const types = new Set((t && t.types) || []);
      const name = t && t.name ? String(t.name) : "";
      const takes = !!t && t.lattice === "take";
      const rows = takes || (t && t.lattice === "leave") ? (this.latticeRows || []) : [];
      const underLattice = (n) => rows.some((r) => n.path === r || String(n.path).startsWith(r + "/"));
      return (n) => (rows.length && underLattice(n)
        ? takes
        : types.has(kindOf(n)) || (!!n.family && n.family === name));
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
      // a row a layout draws stands for what it holds: the host knows no such path
      const add = (n) => {
        if (isLayoutRow(n.path)) (n.children || []).forEach(add);
        else sel.add(n.path);
      };
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
        // cascades it, a pruned one by its children in turn.
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
          // on the row. A container tick is a cascade the host resolves; it
          // activates nothing (the Values card reads what it holds,
          // app/scene/activation).
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
      // the row whose eye opens is the one worked on next: active, as a
      // click on it makes it
      const opened = () => {
        if (!String(path).startsWith("session://") && !isLayoutRow(path)) this.setActive(path);
      };
      // A folder eye drives its children: any of them open -> close them all,
      // none open -> open them all (the tri-state the checkboxes already use).
      // Emitting the whole list keeps it ONE server round-trip.
      if (node && leaves.length > 0
          && !(leaves.length === 1 && leaves[0] === path)) {
        const anyOn = leaves.some((p) => this.visibleSet.has(p));
        if (!anyOn) opened();
        this.$emit("eye-toggle", {
          path, paths: leaves, visible: !anyOn, n: ++this.nonce,
        });
        return;
      }
      if (!this.visibleSet.has(path)) opened();
      this.$emit("eye-toggle", { path, n: ++this.nonce });
    },
    onBulk(row) {
      if (row.sep || row.disabled) return;
      const typeSet = row.types ? new Set(row.types) : null;
      const sel = new Set(this.selectedPaths);
      const walk = (nodes) => {
        for (const n of nodes || []) {
          if (!n.disabled && countable(n) && (typeSet ? typeSet.has(n.type) : true)) {
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
        return walk(this.pruneTree(this.layoutRoots, this.tabPred(tabs[i])));
      };
      if (tabs.length && !inTab(this.activeTabIndex)) {
        const i = tabs.findIndex((_t, k) => inTab(k));
        // a node of none of its tabs is another tree's (another family's
        // card): nothing of it here, and never this tree's memory
        if (i < 0) return;
        this.onTab(i, true);
      }
      // an object of the other domain, picked in a view: the tree shows both
      if (this.domainFilter && node.vdomain && node.vdomain !== this.domainFilter) this.domainFilter = "";
      const exp = { ...this.expanded };
      const open = (ns) => (ns || []).some((n) => {
        if (n.path === path) return true;
        const under = open(n.children);
        if (under) exp[n.path] = true;
        return under;
      });
      open(this.layoutRoots);
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
    onTab(i, keep) {
      this.activeTabIndex = i;
      this.selectMenuOpen = false;
      this.ctxOpen = false;
      this.clearName();
      this.kindFilter = "";
      // The displayed tab's own active node comes back; a tab never clicked
      // in takes its first object read, so the cards follow a node of the
      // tree shown, never another tab's (`keep`: the caller activates one)
      const kept = this.activeByTab[this.tabKey(i)];
      if (kept || keep) {
        this.activePath = kept || null;
        return;
      }
      const first = this.firstTicked(i);
      if (first) this.setActive(first);
      else this.activePath = null;
    },
    // the first row ticked of tab `i`, in the tree's order
    firstTicked(i) {
      const tabs = this.tabs || [];
      if (!tabs.length) return null;
      let found = null;
      const walk = (ns) => (ns || []).some((n) => {
        if (this.selectedSet.has(n.path) && !isLayoutRow(n.path)) {
          found = n.path;
          return true;
        }
        return walk(n.children);
      });
      walk(this.pruneTree(this.layoutRoots, this.tabPred(tabs[i])));
      return found;
    },
    toggleSelectMenu() { this.selectMenuOpen = !this.selectMenuOpen; },
    closeSelectMenu() { this.selectMenuOpen = false; },
    // A node the user opens is announced (`node-open`, its path): the host
    // may only now read what it holds (a lazy ETP load leaves it on the
    // server until then). Not the ancestors a reveal opens.
    setExpanded(path, open) {
      this.expanded = { ...this.expanded, [path]: open };
      if (open) this.$emit("node-open", path);
    },
    // An action declares the node types it applies to; one without `types`
    // applies everywhere. `when` narrows it further to one side of the
    // checkbox ("selected" / "unselected", "loaded": the row or one under
    // it ticked) or of the eye ("shown" / "hidden") — in a PANEL's tree the eye is "in this panel" (the one
    // grammar, the PO 18/10): "shown" for what LEAVES the panel (Remove from
    // stats), "hidden" for what enters it — so a pair of opposite actions
    // never shows the one that would do nothing.
    // "{title}" in a label is the row's name.
    ctxItemsFor(node) {
      if (!node || isLayoutRow(node.path)) return [];
      const t = node.type;
      const ticked = this.selectedSet.has(node.path);
      const shown = this.visibleSet.has(node.path);
      // loaded: the row or a row under it is ticked, or a row of the
      // session (an extract is drawn by being made) — a row with nothing
      // loaded has nothing to show, select or count (the PO, 21/10)
      const below = (node.path || "") + "/";
      const loaded = ticked || !!node.session || this.selectedPaths.some((p) => p.startsWith(below));
      // a whole property not read yet offers what a read one does: the entry
      // reads it first (`read`), as its box would
      const readable = !loaded && !node.partial && !node.disabled && eyeForType(t) === "array";
      const side = { selected: ticked, unselected: !ticked, shown, hidden: !shown, loaded: loaded || readable };
      // `rows`: the entry is offered on these rows and what is under them
      // alone (the lattice grids "Use as velocity model" reads)
      const p = node.path || "";
      const onRows = (rows) => rows.some((r) => p === r || p.startsWith(r + "/"));
      return (this.contextActions || [])
        .filter((a) => (!a.types || a.types.indexOf(t) >= 0)
          && (!a.when || side[a.when] === true)
          && (!a.rows || onRows(a.rows)))
        .map((a) => ({
          ...a,
          ...(a.label && a.label.indexOf("{title}") >= 0
            ? { label: a.label.replace("{title}", node.title || "this object") } : {}),
          read: readable && a.when === "loaded",
        }));
    },
    openContext(node, event) {
      // The menu opens even when no action applies to the node: ctxItems
      // then holds one disabled line saying why, so the right-click is
      // never silent.
      if (!node) return;
      this.ctxNode = node;
      this.ctxPos = { x: event.clientX, y: event.clientY };
      this.ctxOpen = true;
    },
    onCtxAction(a) {
      // an entry naming files (the velocity model's "Save as EPC"): the
      // browser takes them, one after the other, from the session's own
      // route (`download`: URLs relative to the page, as the upload's)
      if (Array.isArray(a.download)) downloadAll(a.download);
      this.$emit("context-action", { action: a.key, path: this.ctxNode.path, read: !!a.read, n: ++this.nonce });
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
.fdx-strips { display: grid; grid-template-columns: auto minmax(0, 1fr); align-items: center; gap: 4px 6px; }
.fdx-layout { display: flex; min-width: 0; }
/* a strip longer than the card goes on onto a second line, never cut: each
   button keeps its own left edge, the one in use drawn over its neighbours */
.fdx-layout :deep(.fp-seg) { flex-wrap: wrap; row-gap: 3px; min-width: 0; }
.fdx-layout :deep(.fp-segbtn + .fp-segbtn) { border-left: 1px solid var(--fp-btn-line); margin-left: -1px; }
.fdx-layout :deep(.fp-segbtn.fp-on) { position: relative; }
.fdx-domain { display: flex; align-items: center; }
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
.fdx-menu-item { padding: 4px 12px; cursor: pointer; white-space: nowrap; color: #333; }
.fdx-menu-item:hover { background: #f0f7ff; color: var(--fp-accent); }
.fdx-menu-item.child { padding-left: 26px; color: #555; font-size: 12px; }
.fdx-menu-item.disabled { color: #8a8a8a; cursor: default; white-space: normal; max-width: 260px; }
.fdx-menu-item.disabled:hover { background: transparent; color: #8a8a8a; }
.fdx-menu-sep { height: 1px; background: #eee; margin: 4px 0; }
.fdx-menu-none { padding: 6px 12px; }

/* the room on the right: Firefox draws its scrollbar over the content, on the eyes */
.fdx-body { flex: 1 1 0; overflow: auto; padding: 4px 14px 4px 0; }
</style>
