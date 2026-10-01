/*
 * The application's own icons — the objects a petroleum-geoscience reader
 * knows, which no general icon set draws, and which no single colour tells
 * apart.
 *
 * Why a set of our own: Material Design Icons has no corner-point grid, no
 * borehole trajectory, no log track, no formation top, no perforated
 * interval, no realization fan. What it offers instead is a metaphor from
 * another trade — a power pylon for a well, a map pin for a formation top,
 * a QR code for an unstructured mesh — and a reader who knows the objects
 * reads those as noise. Drawing them ourselves also settles the licensing
 * question: this file is the project's own work.
 *
 * WHAT THE COLOUR DOES. It names the FAMILY, so a full tree sorts itself
 * before a word is read: the rock is ochre, a surface is teal, a well is
 * steel, a log is blue, a formation top is orange, a property is indigo,
 * time is amber, the realizations are violet. Inside an icon a second
 * colour is spent once, and only where it carries the meaning: the darts
 * of a perforation are the red of the flow, the fluid in a volumetrics box
 * is the green of oil, the codes of a categorical property are a real
 * palette. Everything else stays in the family colour.
 *
 * THE GRAMMAR, so the set reads as one hand:
 *   - 24 x 24 box, every shape inside 3 .. 21 (the tree draws at 15 px, the
 *     toolbars at 24: a shape with more than four strokes turns to mush at
 *     fifteen, so each icon keeps four or five);
 *   - STROKE, not fill: 1.8 wide, round caps and joins. A line drawing is
 *     what these objects are — a bore, a curve, a mesh. `fill` is spent on
 *     the few shapes that are matter: the dots of a point set, the swatches
 *     of a legend, the fluid in a box, the bands of a column;
 *   - depth runs DOWN the box, as on a log: the ground is a horizontal line
 *     and everything below it is the subsurface — high in the box when the
 *     object hangs under it (a trajectory), lower when something stands on
 *     it (the derrick of a well). A column is read top to bottom;
 *   - a grid is a divided block, a surface is a single warped sheet, a set
 *     of things repeats its member three times.
 *
 * SHAPE. `{ parts: [{ d, c, fill }] }` — `c` names a colour of the palette
 * below (absent = `currentColor`, which follows the theme and the row's
 * state), `fill` fills the part instead of stroking it. A host renders one
 * <path> per part:
 *   <path :d="p.d" :fill="p.fill ? colour(p.c) : 'none'"
 *         :stroke="p.fill ? 'none' : colour(p.c)" stroke-width="1.8"
 *         stroke-linecap="round" stroke-linejoin="round" />
 * with `colour(c) = c ? 'var(--fp-ic-' + c + ')' : 'currentColor'`.
 *
 * A DISABLED ROW must still read as disabled: the host greys the whole
 * icon with `filter: grayscale(1); opacity: .55` rather than by changing
 * `currentColor`, which a coloured part does not follow.
 */

// The palette. Each colour is a CSS variable so a theme retunes the set in
// one place; the values below are the defaults, picked to hold their own on
// white AND on the dark ground (mid-tones, never a pastel, never a
// near-black).
export const FESPP_ICON_COLORS = {
  light: {
    rock: "#8a7043",      // the matrix: grids, their folders, their subsets
    surface: "#00897b",   // horizons, triangulated sets, point sets, polylines
    well: "#4a6572",      // the hole itself: bore, trajectory, casing
    log: "#1f76c4",       // a log track and its curves
    top: "#e0701a",       // a formation top — the pick, warm, seen at once
    prop: "#4054b2",      // a property and its values
    time: "#b8860b",      // dates, time steps
    real: "#7b4fc4",      // the realizations of a model, a designated subset
    oil: "#2e9e5b",       // the fluids, on the trade's own convention
    gas: "#d1453a",
    water: "#2d8fd5",
  },
  dark: {
    rock: "#c2a267", surface: "#4db6ac", well: "#90a7b4", log: "#63b3ee",
    top: "#f0a04b", prop: "#8b9cf0", time: "#e0b44a", real: "#b190e8",
    oil: "#57c98a", gas: "#f07a68", water: "#63b3ee",
  },
};

const p = (d, c, fill) => ({ d, c, fill });

export const FESPP_ICONS = {
  // ------------------------------------------------------------ the rock
  // A corner-point / IJK grid: a block of cells, seen from three quarters,
  // divided in two each way — cells, not a box.
  gridIjk: { parts: [
    p("M4 8.5h12v10H4Z M10 8.5v10 M4 13.5h12", "rock"),
    p("M4 8.5 8 5.5h12v10l-4 3 M16 8.5 20 5.5", "rock"),
  ] },

  // An unstructured grid: one triangle split from an inside point — the
  // tetrahedra a section through such a mesh shows.
  gridUnstructured: { parts: [
    p("M12 4 21.5 20H2.5Z", "rock"),
    p("M12 13V4.6 M12 13 3.9 19.2 M12 13l8.1 6.2", "rock"),
  ] },

  // A sub-representation: a named part of a grid — one cell pulled out of
  // the block, and the part is what the violet marks.
  subRepresentation: { parts: [
    p("M4.5 9h8v8h-8Z M4.5 13h8 M8.5 9v8", "rock"),
    p("M8.5 9h4v4h-4Z", "real", true),
    p("M15.5 4.5h4.5V9h-4.5Z", "real"),
  ] },

  // A blocked wellbore: the cells of a grid a well passes through.
  blockedWellbore: { parts: [
    p("M5 8.5h10v10H5Z", "rock"),
    p("M10 8.5h5v5h-5Z M5 13.5h5v5H5Z", "well", true),
    p("M12.5 4.2v4.3 M7.5 18.5v2.6", "well"),
  ] },

  // -------------------------------------------------------- the surfaces
  // A 2D grid: one warped sheet with its lattice — a depth or time horizon.
  // No thickness: that is what separates it from the block above.
  surfaceGrid2d: { parts: [
    p("M3.5 9.5q4.5-4 9 0t8 0v5q-3.5 4-8 0t-9 0Z", "surface"),
    p("M8.4 7.9v5 M13.8 10.1v5", "surface"),
  ] },

  // A triangulated set: an irregular patch of triangles.
  surfaceTin: { parts: [
    p("M3.5 17 8.5 7l4.5 6.5L18 5.5l2.5 11.5Z", "surface"),
    p("M8.5 7 20.5 17 M13 13.5 3.5 17", "surface"),
  ] },

  // A point set: points, plural — the old icon was a single medium dot.
  pointSet: { parts: [p(
    "M7 7.1a1.45 1.45 0 1 0 0 2.9 1.45 1.45 0 1 0 0-2.9"
    + "M12.5 4.6a1.45 1.45 0 1 0 0 2.9 1.45 1.45 0 1 0 0-2.9"
    + "M17.6 8.1a1.45 1.45 0 1 0 0 2.9 1.45 1.45 0 1 0 0-2.9"
    + "M8.4 14.1a1.45 1.45 0 1 0 0 2.9 1.45 1.45 0 1 0 0-2.9"
    + "M15.2 15.7a1.45 1.45 0 1 0 0 2.9 1.45 1.45 0 1 0 0-2.9", "surface", true)] },

  // A polyline: one open line through its vertices (a fault stick, a
  // contour). The SET repeats it — the two share one icon today.
  polyline: { parts: [p("M3.5 16.5 8.5 9l5 4.5 7-7.5", "surface")] },
  polylineSet: { parts: [
    p("M3.5 12 7.5 6l4 5.5 5-3.5", "surface"),
    p("M4.5 19 8 15l5 2.5 7.5-4.5", "surface"),
    p("M17 5.5 20.5 8", "surface"),
  ] },

  // ----------------------------------------------------------- the wells
  // A wellbore: the ground, the wellhead, the hole going down and away.
  wellbore: { parts: [
    p("M3.5 10h17", "rock"),
    p("M8 10 10.7 4.5h2.6L16 10 M9.2 7.2h5.6", "well"),
    p("M12 10v10", "well"),
  ] },

  // A trajectory: the path of the hole — the deviated profile every well
  // section draws.
  trajectory: { parts: [
    p("M3.5 4h17", "rock"),
    p("M8 4v5.6c0 6 4.4 7.6 10.5 9", "well"),
  ] },

  // A log frame: a track with a header and a curve in it — the
  // petrophysicist's own object. Its channels are the curve alone.
  logFrame: { parts: [
    p("M4.5 3.5h15v17h-15Z M4.5 7.7h15", "log"),
    p("M9.7 10c3 1.7-3 3.4 0 5.1", "log"),
  ] },
  logChannel: { parts: [
    p("M6.5 3.5v17", "well"),
    p("M12.5 4.6c3.2 2.3-3.2 4.6 0 6.9s-3.2 4.6 0 6.9", "log"),
  ] },

  // A formation top: the bore crossed by the pick, in the warm colour a
  // pick is always drawn in. The FRAME carries the set of them.
  marker: { parts: [
    p("M12 3.5v17", "well"),
    p("M12 9.8a2.2 2.2 0 1 0 0 4.4 2.2 2.2 0 1 0 0-4.4", "top", true),
  ] },
  markerFrame: { parts: [
    p("M12 3.5v17", "well"),
    p("M12 5.6a1.7 1.7 0 1 0 0 3.4 1.7 1.7 0 1 0 0-3.4 M12 10.3a1.7 1.7 0 1 0 0 3.4 1.7 1.7 0 1 0 0-3.4 M12 15a1.7 1.7 0 1 0 0 3.4 1.7 1.7 0 1 0 0-3.4",
      "top", true),
  ] },

  // A completion: the casing hung in the hole, and the packer set in it —
  // the packer is what makes it a completion rather than two bars.
  completion: { parts: [
    p("M7 4h10 M9.5 4v16 M14.5 4v16", "well"),
    p("M8.2 12.6h7.6v3.4H8.2Z", "well", true),
  ] },

  // A perforated interval: the casing shot through — the darts are the
  // trade's own mark, and they carry the colour of what flows.
  perforation: { parts: [
    p("M9.5 3.5v17 M14.5 3.5v17", "well"),
    p("M9.5 9 4.8 7.2 M14.5 9l4.7-1.8 M9.5 15l-4.7-1.8 M14.5 15l4.7-1.8", "gas"),
  ] },

  // ------------------------------------------------------ the properties
  // Floating values: one smooth curve — the staircase below is the same
  // drawing with the values quantised, which is exactly the difference.
  propertyContinuous: { parts: [p("M3.5 16c2.5 0 3-8 5.5-8s3 6 5.5 6 3-5 6-5", "prop")] },

  // Integer codes with no names: a staircase of values.
  propertyDiscrete: { parts: [p("M3.5 18h4v-4h4v-4h4v-4h4.5", "prop")] },

  // Integer codes WITH names (facies): the legend itself. Today discrete
  // and categorical wear the same bar chart and cannot be told apart — and
  // this is the one icon that is genuinely polychrome, because the object
  // IS a palette.
  propertyCategorical: { parts: [
    p("M3.5 8.5h17v7h-17Z"),
    p("M4.4 9.4h3.4v5.2H4.4Z", "gas", true),
    p("M8.3 9.4h3.4v5.2H8.3Z", "time", true),
    p("M12.2 9.4h3.4v5.2h-3.4Z", "oil", true),
    p("M16.1 9.4h3.5v5.2h-3.5Z", "water", true),
  ] },

  // One property across the realizations of the model: the fan a reader
  // draws for P10 / P50 / P90.
  multiRealization: { parts: [
    p("M3.5 12c5 0 8-7 17-7.5 M3.5 12c5 0 8 7 17 7.5", "real"),
    p("M3.5 12c5 0 8 0 17-.5", "real"),
  ] },

  // The same, through time: the fan over the arrow of time.
  multiRealizationTimeSeries: { parts: [
    p("M3.5 10.5c5 0 8-5 17-5.5 M3.5 10.5c5 0 8 5 17 5.5", "real"),
    p("M3 19.5h17.5 M18.8 17.9 20.8 19.5l-2 1.6", "time"),
  ] },

  // The badge a row carries when its property runs through TIME: the arrow
  // of time alone — the same signature the two drawings below carry, small
  // enough to sit beside a title at 13 px.
  timeMark: { parts: [p("M3.5 12h14 M15.5 9.6 19.5 12l-4 2.4", "time")] },

  // One property through time.
  timeSeries: { parts: [
    p("M3 14c3.5 0 4-7.5 7-7.5s3.5 7.5 6.5 7.5", "prop"),
    p("M3 19h17.5 M18.6 17.2 20.8 19l-2.2 1.8", "time"),
  ] },

  // A property set: a named bag of properties — sheets stacked.
  propertySet: { parts: [p("M5.5 9h13v9.5h-13Z M8 6.5h13 M10.5 4h11", "prop")] },

  // An object the tree does not know: said as unknown, not as a 2 px dot.
  unknown: { parts: [p("M9.6 4.4a8 8 0 0 0-5.2 5.2 M4.4 14.4a8 8 0 0 0 5.2 5.2 M14.4 19.6a8 8 0 0 0 5.2-5.2 M19.6 9.6a8 8 0 0 0-5.2-5.2")] },

  // ---------------------------------------------------------- the panels
  // The stratigraphic column: its units are what a strat column colours.
  stratigraphicColumn: { parts: [
    p("M8.5 3.5h7V8h-7Z", "rock", true),
    p("M8.5 12h7v4h-7Z", "top", true),
    p("M8.5 3.5h7v17h-7Z M8.5 8h7 M8.5 12h7 M8.5 16h7 M5.5 3.5v17"),
  ] },

  // Log against grid: the curve, and the cells it is weighed against.
  logVsGrid: { parts: [
    p("M5 4.5c2.4 2-2.4 4 0 6s-2.4 4 0 6", "log"),
    p("M14 4.5h6.5v14H14Z M14 9.2h6.5 M14 13.8h6.5", "rock"),
    p("M9.3 11.5h3.4 M10.5 10.3 9.3 11.5l1.2 1.2"),
  ] },

  // File health: the report on the data, and its pulse.
  fileHealth: { parts: [
    p("M6.5 5.5h11V20h-11Z M9.5 3.5h5v3h-5Z"),
    p("M8.5 14h2.2l1.3-4 1.6 6.4 1.1-2.4h1.3", "gas"),
  ] },

  // The volumes of a reservoir: the rock, and the fluid filling part of it.
  volumetrics: { parts: [
    p("M5 12.2 12 15.7l7-3.5v4.3L12 20l-7-3.5Z", "oil", true),
    p("M5 7.5 12 4l7 3.5v9L12 20l-7-3.5Z M5 7.5 12 11l7-3.5 M12 11v9", "rock"),
  ] },

  // Slicers: the block, and where it is cut.
  slicers: { parts: [
    p("M4.5 6.5h15v11h-15Z", "rock"),
    p("M9.2 6.5v11 M14.5 6.5v11 M9.2 3.5v3 M14.5 3.5v3 M9.2 17.5v3 M14.5 17.5v3", "real"),
  ] },

  // A second 3D view: the pane says 3D in as many letters, and the
  // plus opens the next one. This button is only ever drawn at 24 px in the
  // top bar, which is what lets an icon carry letters at all.
  newView3d: { parts: [
    p("M3.5 6h13v11h-13Z"),
    p("M6.1 9.6a1.5 1.5 0 1 1 1.4 2.4 1.6 1.6 0 1 1-1.5 2.5", "rock"),
    p("M10.4 15.1V9.3h1.6a2.9 2.9 0 0 1 0 5.8Z", "rock"),
    p("M18.6 5.8v4.6 M16.3 8.1h4.6"),
  ] },

  // Compare: two populations that overlap — the figure a reader
  // takes as "weigh these two against each other", owing nothing to one
  // kind of chart.
  compareView: { parts: [
    p("M9.8 6.2a5.8 5.8 0 1 0 0 11.6 5.8 5.8 0 1 0 0-11.6", "prop"),
    p("M14.2 6.2a5.8 5.8 0 1 1 0 11.6 5.8 5.8 0 1 1 0-11.6", "real"),
  ] },

  // The grid as a whole — the row that holds the geometry, the
  // properties, the sub-representations — held in a bracket. The geometry
  // below it is that same block, divided into its cells.
  gridContainer: { parts: [
    p("M8 9h8.5v8.5H8Z M8 9 10 7h8.5v8.5L16.5 17.5", "rock"),
    p("M6 5.5H4v15h2", "rock"),
  ] },

  // A folder of the tree: one silhouette for all of them, and
  // one mark inside that names what this one holds.
  folderProperties: { parts: [
    p("M3.5 7h6l1.6 2.2h9.4v9.8h-17Z"),
    p("M7.5 16.2c1.6 0 1.9-3.4 3.6-3.4s2.1 2.6 3.7 2.6", "prop"),
  ] },

  // A folder of the tree: one silhouette for all of them, and
  // one mark inside that names what this one holds.
  folderSubRepresentation: { parts: [
    p("M3.5 7h6l1.6 2.2h9.4v9.8h-17Z"),
    p("M12.8 12.6h3.8v3.8h-3.8Z", "real", true),
    p("M8 12.6h3.4v3.8H8Z", "real"),
  ] },

  // A folder of the tree: one silhouette for all of them, and
  // one mark inside that names what this one holds.
  folderBlockedWellbore: { parts: [
    p("M3.5 7h6l1.6 2.2h9.4v9.8h-17Z"),
    p("M10.8 13.2h4.6v4.6h-4.6Z", "rock"),
    p("M13.1 11v2.2", "well"),
  ] },

  // A folder of the tree: one silhouette for all of them, and
  // one mark inside that names what this one holds.
  folderLogs: { parts: [
    p("M3.5 7h6l1.6 2.2h9.4v9.8h-17Z"),
    p("M12 12.2c1.9 1.3-1.9 2.7 0 4", "log"),
    p("M9 12.2v4", "well"),
  ] },

  // A folder of the tree: one silhouette for all of them, and
  // one mark inside that names what this one holds.
  folderMarkers: { parts: [
    p("M3.5 7h6l1.6 2.2h9.4v9.8h-17Z"),
    p("M12 11.9v5.4", "well"),
    p("M12 12.6a1.6 1.6 0 1 0 0 3.2 1.6 1.6 0 1 0 0-3.2", "top", true),
  ] },

  // A folder of the tree: one silhouette for all of them, and
  // one mark inside that names what this one holds.
  folderCompletions: { parts: [
    p("M3.5 7h6l1.6 2.2h9.4v9.8h-17Z"),
    p("M10.6 11.9v5.2 M13.8 11.9v5.2", "well"),
    p("M10.9 13.9h2.6v1.7h-2.6Z", "well", true),
  ] },
};

export default FESPP_ICONS;
