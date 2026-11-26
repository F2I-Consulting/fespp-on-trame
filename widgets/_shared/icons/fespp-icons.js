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
 * SHAPE. `{ parts: [{ d, c, fill, m }] }` — `c` names a colour of the
 * palette below (absent = `currentColor`, which follows the theme and the
 * row's state), `fill` fills the part instead of stroking it, `m` the ink
 * the part takes in a toolbar (`mono`: "f2i", the green; absent, the
 * toolbar's one ink) — so one drawing serves the tree in its family colours
 * and a toolbar in the blue and the green of F2I. A host renders one
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

// The palette. On a page each colour is the CSS variable `--fp-ic-<family>`
// (defined in widgets/_shared/tokens.css, which must match `light`), so a
// theme retunes the set in one place. This object carries the same values,
// with their dark counterparts, for whatever draws the set outside a page
// (scripts/gen_icon_sheet.mjs). Mid-tones, picked to hold their own on white
// AND on the dark ground: never a pastel, never a near-black.
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
    // the green of the i of F2I: the toolbar's SECOND ink (the PO, 15/10).
    // A toolbar draws its icons in one ink (`mono`), except the parts of
    // this family, which keep the green beside the accent blue.
    f2i: "#8FC31F",
    // the blue of the F of F2I, the application's accent: with the green,
    // what a toolbar's own drawings are made of
    brand: "#00436d",
    // what stands back in a drawing: the branches of a tree under its root
    mute: "#8e9aa3",
  },
  dark: {
    rock: "#c2a267", surface: "#4db6ac", well: "#90a7b4", log: "#63b3ee",
    top: "#f0a04b", prop: "#8b9cf0", time: "#e0b44a", real: "#b190e8",
    oil: "#57c98a", gas: "#f07a68", water: "#63b3ee", f2i: "#a6d63f",
    brand: "#8cc8f0", mute: "#7f8b94",
  },
};

const p = (d, c, fill, m) => ({ d, c, fill, m });

export const FESPP_ICONS = {
  // ------------------------------------------------------------ the rock
  // A corner-point / IJK grid: a block of cells, seen from three quarters,
  // divided in two each way — cells, not a box.
  gridIjk: { parts: [
    p("M4 8.5h12v10H4Z M10 8.5v10 M4 13.5h12", "rock"),
    p("M4 8.5 8 5.5h12v10l-4 3 M16 8.5 20 5.5", "rock"),
  ] },

  // A lattice grid, the velocity model: the same block, its cells all alike,
  // its layers even in time, in the amber of time.
  gridLattice: { parts: [
    p("M3.5 8.5h13v11h-13Z M7.83 8.5v11 M12.17 8.5v11", "rock"),
    p("M3.5 8.5 7.5 5h13v11l-4 3.5 M16.5 8.5 20.5 5", "rock"),
    p("M3.5 12.17h13 M3.5 15.83h13", "time"),
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

  // --------------------------------------------------------- the seismic
  // A seismic trace, time running down: a lobe on one side then one on the
  // other, filled as a variable-area display fills them — in the blue and
  // the green of F2I. No axis: the two lobes say it.
  seismic: { parts: [
    p("M12 4C22 4.3 22 11.7 12 12Z", "brand", true),
    p("M12 12C2 12.3 2 19.7 12 20Z", "f2i", true),
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

  // A point set: points, plural — several dots, never one that reads as a
  // bullet.
  pointSet: { parts: [p(
    "M7 7.1a1.45 1.45 0 1 0 0 2.9 1.45 1.45 0 1 0 0-2.9"
    + "M12.5 4.6a1.45 1.45 0 1 0 0 2.9 1.45 1.45 0 1 0 0-2.9"
    + "M17.6 8.1a1.45 1.45 0 1 0 0 2.9 1.45 1.45 0 1 0 0-2.9"
    + "M8.4 14.1a1.45 1.45 0 1 0 0 2.9 1.45 1.45 0 1 0 0-2.9"
    + "M15.2 15.7a1.45 1.45 0 1 0 0 2.9 1.45 1.45 0 1 0 0-2.9", "surface", true)] },

  // A polyline: one open line through its vertices (a fault stick, a
  // contour). The SET repeats it.
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
    p("M9.7 10c3 1.7-3 3.4 0 5.1", "log", false, "f2i"),
  ] },
  // The log view: two log tracks side by side, the green of F2I and the
  // blue of a log, read across as a correlation is.
  // the depth axis at the left, pointing down, then two tracks
  logView: { parts: [
    p("M4.5 4v15 M2.6 16.8 4.5 19.2l1.9-2.4"),
    p("M11.5 3.5c3 2.1-3 4.2 0 6.3s-3 4.2 0 6.3s-3 2.2 0 4.4", "f2i", false, "f2i"),
    p("M18.5 3.5c-3 2.1 3 4.2 0 6.3s3 4.2 0 6.3s3 2.2 0 4.4", "log"),
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

  // Integer codes WITH names (facies): the legend itself, so it is never
  // taken for the discrete staircase above. The one icon that is genuinely
  // polychrome, because the object IS a palette.
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
  // of time alone — the signature multiRealizationTimeSeries and timeSeries
  // carry, small enough to sit beside a title at 13 px.
  timeMark: { parts: [p("M3.5 12h14 M15.5 9.6 19.5 12l-4 2.4", "time")] },

  // One property through time.
  timeSeries: { parts: [
    p("M3 14c3.5 0 4-7.5 7-7.5s3.5 7.5 6.5 7.5", "prop"),
    p("M3 19h17.5 M18.6 17.2 20.8 19l-2.2 1.8", "time"),
  ] },

  // A property set: a named bag of properties — sheets stacked.
  propertySet: { parts: [p("M5.5 9h13v9.5h-13Z M8 6.5h13 M10.5 4h11", "prop")] },

  // An object the tree does not know: a broken circle that says so, rather
  // than a dot that passes for data.
  unknown: { parts: [p("M9.6 4.4a8 8 0 0 0-5.2 5.2 M4.4 14.4a8 8 0 0 0 5.2 5.2 M14.4 19.6a8 8 0 0 0 5.2-5.2 M19.6 9.6a8 8 0 0 0-5.2-5.2")] },

  // ---------------------------------------------------------- the panels
  // The stratigraphic column: its units are what a strat column colours.
  stratigraphicColumn: { parts: [
    p("M8.5 3.5h7V8h-7Z", "rock", true, "f2i"),
    p("M8.5 12h7v4h-7Z", "top", true, "f2i"),
    p("M8.5 3.5h7v17h-7Z M8.5 8h7 M8.5 12h7 M8.5 16h7 M5.5 3.5v17"),
  ] },

  // Log against grid: the curve, and the cells it is weighed against.
  logVsGrid: { parts: [
    p("M5 4.5c2.4 2-2.4 4 0 6s-2.4 4 0 6", "log", false, "f2i"),
    p("M14 4.5h6.5v14H14Z M14 9.2h6.5 M14 13.8h6.5", "rock"),
    p("M9.3 11.5h3.4 M10.5 10.3 9.3 11.5l1.2 1.2"),
  ] },

  // File health: the report on the data, and its pulse.
  fileHealth: { parts: [
    p("M6.5 5.5h11V20h-11Z M9.5 3.5h5v3h-5Z"),
    p("M8.5 14h2.2l1.3-4 1.6 6.4 1.1-2.4h1.3", "gas", false, "f2i"),
  ] },

  // ------------------------------------------- the view toolbar's tools
  // Two inks (the PO, 15/10): the accent blue of the toolbar (no family,
  // `currentColor`) and the green of F2I (`f2i`), which a `mono` toolbar
  // keeps.

  // The volumes of a reservoir: the block, and the fluid filling its lower
  // part, in green.
  volumetrics: { parts: [
    p("M5 12.2 12 15.7l7-3.5v4.3L12 20l-7-3.5Z", "f2i", true),
    p("M5 7.5 12 4l7 3.5v9L12 20l-7-3.5Z M5 7.5 12 11l7-3.5 M12 11v9"),
  ] },

  // Slicers: a K layer of the grid, in green, and the I and J directions
  // it is cut along, the blue cross over it.
  slicers: { parts: [
    p("M2.5 17 8.5 7h13l-6 10Z", "f2i", true),
    p("M4.6 12h14.8 M8.7 17.6 15.3 6.4"),
  ] },

  // Explorer: two RESQML objects, one pointing at the other (a reference),
  // and the lens that reads them, in green — not the 3D view's tree
  // (mdi-file-tree): this panel walks references, it does not list a
  // hierarchy (the PO, 16/10).
  explorer: { parts: [
    p("M3 3.5h7.5v5H3Z M3 15.5h7.5v5H3Z M6.75 8.5v6 M5 12.8l1.75 1.7 1.75-1.7"),
    p("M16.5 5.5a4 4 0 1 0 0 8 4 4 0 1 0 0-8Z M19.3 12.3 22 15", "f2i"),
  ] },

  // Thresholds: a bell curve cut by a vertical bar — what the cut keeps,
  // under the curve beyond the bar, in green; the rest left white (the
  // manager, 21/10). The green edge is the curve's own arc, split at the bar.
  threshold: { parts: [
    p("M14.5 7.6C16.5 11.8 18.1 19.5 21 19.5H14.5Z", "f2i", true),
    p("M3 19.5C7 19.5 8.5 5 12 5s5 14.5 9 14.5 M2.5 19.5h19"),
    p("M14.5 3.5v17"),
  ] },

  // Values: a table, its header row in green.
  values: { parts: [
    p("M3.5 5h17v4.5h-17Z", "f2i", true),
    p("M3.5 5h17v14h-17Z M3.5 9.5h17 M3.5 14.2h17 M9.5 5v14"),
  ] },

  // Time to depth: T, an arrow in green, D — side by side, read as one
  // word.
  timeDepth: { parts: [
    p("M2.6 7h6.2 M5.7 7v10 M15.6 7v10h1.6a3.6 5 0 0 0 0-10Z"),
    p("M9.8 12h4.2 M12.2 10.2 14 12l-1.8 1.8", "f2i"),
  ] },

  // The Globe: the sea in blue, the land in green.
  globe: { parts: [
    p("M12 3a9 9 0 1 0 0 18 9 9 0 1 0 0-18Z", null, true),
    p("M6 6.5c1.8-1 4-.6 4.3 1 .2 1.2-.9 1.8-.6 3 .3 1.3 1.8 1.6 1.9 3.1.1 1.6-1.1 3.4-2.6 3.9-.6-1.5-.4-3-1.5-4.1C6.4 12.4 4.6 11.5 4.3 10c-.3-1.4.6-2.8 1.7-3.5Z"
      + " M13 4.2c2.3-.4 4.6.4 5.9 2.1-.8.6-2 .4-2.6 1.2-.5.7.2 1.6 1.1 1.8 1.2.3 2.5 0 3.2.9.4 1.6.2 3.3-.6 4.8-.9-.6-1.9-.2-2.4.7-.6 1.1-.5 2.6-1.5 3.4-.8-1.3-.6-3-1.4-4.2-.6-.9-1.9-1.1-2.3-2.2-.4-1.2.6-2.2.5-3.4-.1-1-.9-1.6-.8-2.6Z", "f2i", true),
  ] },

  // Settings: three sliders, each at its own value — the card that drives a
  // view (the Globe's EPSG, framings, opacity, imagery)
  settings: { parts: [
    p("M4 7h16 M4 12h16 M4 17h16"),
    p("M9 5a2 2 0 1 0 0 4 2 2 0 1 0 0-4Z M15 10a2 2 0 1 0 0 4 2 2 0 1 0 0-4Z"
      + " M7 15a2 2 0 1 0 0 4 2 2 0 1 0 0-4Z", null, true),
  ] },

  // Colormap: a colour bar running from white through the green to the
  // blue (the PO, 15/10: blue to green alone was too faint), framed.
  colormap: { parts: [
    p("M3.5 7h3.6v10H3.5Z", "#ffffff", true),
    p("M7.1 7h3.6v10H7.1Z", "#cfe8a4", true),
    p("M10.7 7h3.6v10h-3.6Z", "f2i", true),
    p("M14.3 7h3.6v10h-3.6Z", "#3f8fa6", true),
    p("M17.9 7h2.6v10h-2.6Z", "#1f5fb5", true),
    p("M3.5 7h17v10h-17Z"),
  ] },

  // Navigation: three axes from one corner, the vertical one in green.
  navigation: { parts: [
    p("M8 16h12 M17.8 13.8 20 16l-2.2 2.2 M8 16l-4.5 4.5 M3.5 17.4v3.1h3.1"),
    p("M8 16V3.8 M5.8 6 8 3.8 10.2 6", "f2i"),
  ] },

  // Synchronize camera: a magnet, its two poles in green.
  magnet: { parts: [
    p("M4.5 4h4.2v8.3a3.3 3.3 0 0 0 6.6 0V4h4.2v8.3a7.5 7.5 0 0 1-15 0Z", null, true),
    p("M4.5 4h4.2v3.6H4.5Z M15.3 4h4.2v3.6h-4.2Z", "f2i", true),
  ] },

  // Select cells ON the surface: the pointer in blue, its click in green.
  selectSurface: { parts: [
    p("M9.5 8.5v11.8l3-2.9 2.2 4.6 2.1-1-2.2-4.6h4.2Z"),
    p("M9.5 2.8v2.6 M3.8 8.5h2.6 M5.4 4.4l1.8 1.8 M13.6 4.4l-1.8 1.8", "f2i"),
  ] },

  // Select cells THROUGH the volume: the block in blue, the frame that
  // takes all of it in green.
  selectVolume: { parts: [
    p("M12 7.2l4.3 2.4v4.8L12 16.8l-4.3-2.4V9.6Z M7.7 9.6 12 12l4.3-2.4 M12 12v4.8"),
    p("M3.5 8V3.5H8 M16 3.5h4.5V8 M20.5 16v4.5H16 M8 20.5H3.5V16", "f2i"),
  ] },

  // ------------------------------------------ a 3D view's title bar
  // The same two inks on the bar's dark ground (widgets/title3dview: the
  // light blue of the chrome and the green of F2I, the PO, 03/11): the
  // part that names the gesture is the green one.

  // Move the scene: the open hand, the drag it makes in green.
  viewHand: { parts: [
    p("M8.2 14V8.6a1.2 1.2 0 0 1 2.4 0V13 M10.6 12V7a1.2 1.2 0 0 1 2.4 0v5 M13 12V7.6a1.2 1.2 0 0 1 2.4 0V12.4"
      + " M15.4 12.4V9.4a1.2 1.2 0 0 1 2.4 0v4.6c0 3.6-2.2 6.3-5.2 6.3-2.1 0-3.4-.9-4.6-2.7l-2.4-3.8a1.2 1.2 0 0 1 2-1.3l.6.9"),
    p("M4.5 7.2a4.6 4.6 0 0 1 2.4-3 M19.5 7.2a4.6 4.6 0 0 0-2.4-3", "f2i"),
  ] },

  // Show position: the mouse, the button that reads in green.
  viewMouse: { parts: [
    p("M12 3.5a5.5 5.5 0 0 0-5.5 5.5V9H12Z", "f2i", true),
    p("M12 3.5c3.1 0 5.5 2.4 5.5 5.5v6c0 3.1-2.4 5.5-5.5 5.5s-5.5-2.4-5.5-5.5V9c0-3.1 2.4-5.5 5.5-5.5Z M12 3.5V9 M6.5 9h11"),
  ] },

  // Shading on: the bulb, lit — its rays in green.
  viewLightOn: { parts: [
    p("M9.5 17.6h5 M10.2 20.4h3.6 M12 4.6a5.2 5.2 0 0 0-3.1 9.4c.5.4.7.9.7 1.5v.4h4.8v-.4c0-.6.2-1.1.7-1.5A5.2 5.2 0 0 0 12 4.6Z"),
    p("M3.4 9.6h1.6 M19 9.6h1.6 M5.6 3.9l1.1 1.1 M18.4 3.9l-1.1 1.1 M12 1.6v1.2", "f2i"),
  ] },

  // Exact colours: the bulb out, struck through in green.
  viewLightOff: { parts: [
    p("M9.5 17.6h5 M10.2 20.4h3.6 M12 4.6a5.2 5.2 0 0 0-3.1 9.4c.5.4.7.9.7 1.5v.4h4.8v-.4c0-.6.2-1.1.7-1.5A5.2 5.2 0 0 0 12 4.6Z"),
    p("M4.5 3.5l15 16", "f2i"),
  ] },

  // Frame everything: the frame's corners, what it takes in, in green.
  viewFrame: { parts: [
    p("M3.5 8.5v-5h5 M15.5 3.5h5v5 M20.5 15.5v5h-5 M8.5 20.5h-5v-5"),
    p("M9 9h6v6H9Z", "f2i", true),
  ] },

  // Look along an axis: the three axes of the Navigation card's icon, the
  // one looked along in green.
  viewLookX: { parts: [
    p("M8 16l-4.5 4.5 M3.5 17.4v3.1h3.1 M8 16V3.8 M5.8 6 8 3.8 10.2 6"),
    p("M8 16h12 M17.8 13.8 20 16l-2.2 2.2", "f2i"),
  ] },
  viewLookY: { parts: [
    p("M8 16h12 M17.8 13.8 20 16l-2.2 2.2 M8 16V3.8 M5.8 6 8 3.8 10.2 6"),
    p("M8 16l-4.5 4.5 M3.5 17.4v3.1h3.1", "f2i"),
  ] },
  viewLookZ: { parts: [
    p("M8 16h12 M17.8 13.8 20 16l-2.2 2.2 M8 16l-4.5 4.5 M3.5 17.4v3.1h3.1"),
    p("M8 16V3.8 M5.8 6 8 3.8 10.2 6", "f2i"),
  ] },

  // Zoom in and out: the lens, its plus or minus in green.
  viewZoomIn: { parts: [
    p("M10.5 3.8a6.7 6.7 0 1 0 0 13.4 6.7 6.7 0 1 0 0-13.4Z M15.3 15.3l5.2 5.2"),
    p("M7.6 10.5h5.8 M10.5 7.6v5.8", "f2i"),
  ] },
  viewZoomOut: { parts: [
    p("M10.5 3.8a6.7 6.7 0 1 0 0 13.4 6.7 6.7 0 1 0 0-13.4Z M15.3 15.3l5.2 5.2"),
    p("M7.6 10.5h5.8", "f2i"),
  ] },

  // The camera linked: two links held, the second in green; unlinked,
  // they part and a green stroke cuts between them.
  viewLinked: { parts: [
    p("M10.2 13.8a3.8 3.8 0 0 0 5.4 0l3-3a3.8 3.8 0 0 0-5.4-5.4l-1.1 1.1"),
    p("M13.8 10.2a3.8 3.8 0 0 0-5.4 0l-3 3a3.8 3.8 0 0 0 5.4 5.4l1.1-1.1", "f2i"),
  ] },
  viewUnlinked: { parts: [
    p("M13.6 6.6l.6-.6a3.8 3.8 0 0 1 5.4 5.4l-2.4 2.4 M10.4 17.4l-.6.6a3.8 3.8 0 0 1-5.4-5.4l2.4-2.4"),
    p("M4 4l16 16", "f2i"),
  ] },

  // A second 3D view: the pane says 3D in as many letters, and the
  // plus opens the next one. This button is only ever drawn at 24 px in the
  // top bar, which is what lets an icon carry letters at all.
  newView3d: { parts: [
    p("M3.5 6h13v11h-13Z"),
    p("M6.1 9.6a1.5 1.5 0 1 1 1.4 2.4 1.6 1.6 0 1 1-1.5 2.5", "rock"),
    p("M10.4 15.1V9.3h1.6a2.9 2.9 0 0 1 0 5.8Z", "rock"),
    p("M18.6 5.8v4.6 M16.3 8.1h4.6", null, false, "f2i"),
  ] },
  // The 3D views: the same pane, without the plus — the top bar's door to
  // them, each shown or hidden, and a new one (widgets/newview's ViewsDoor).
  view3d: { parts: [
    p("M4.5 5.5h15v13h-15Z"),
    p("M7.4 9.6a1.5 1.5 0 1 1 1.4 2.4 1.6 1.6 0 1 1-1.5 2.5", "rock"),
    p("M11.7 15.1V9.3h1.6a2.9 2.9 0 0 1 0 5.8Z", "rock"),
  ] },

  // ------------------------------------------- the top bar's doors
  // Two inks, as the view toolbar's: the accent blue and the green of F2I
  // (the PO, 03/11).

  // The data tree: the root, its branches, and the rows they hold as two
  // small dots — the room is the root's, which says what the tree is. The
  // root wears the two colours of F2I, the tree under it stands back in grey.
  dataTree: { parts: [
    p("M3.5 3h14v8.5h-14Z", "brand"),
    p("M6.5 7.25h8", "f2i"),
    p("M7.5 11.5V19.5H13.6 M7.5 15.5H13.6", "mute"),
    p("M15.4 15.5a1.4 1.4 0 1 0 2.8 0a1.4 1.4 0 1 0-2.8 0Z M15.4 19.5a1.4 1.4 0 1 0 2.8 0a1.4 1.4 0 1 0-2.8 0Z", "mute", true),
  ] },

  // The tree of one family: the data tree, its root drawn as the family — a
  // block of cells, a warped sheet, a derrick, a seismic trace.
  // the block of cells of `gridIjk`, seen from three quarters: a volume,
  // where a flat divided frame read as a surface
  dataTreeReservoir: { parts: [
    p("M3.5 6h10.5v6H3.5Z M3.5 6 7 3h10.5v6l-3.5 3 M14 6l3.5-3", "brand"),
    p("M8.75 6.9v4.2 M4.4 9h8.7", "f2i"),
    p("M7.5 12V19.5H13.6 M7.5 15.5H13.6", "mute"),
    p("M15.4 15.5a1.4 1.4 0 1 0 2.8 0a1.4 1.4 0 1 0-2.8 0Z M15.4 19.5a1.4 1.4 0 1 0 2.8 0a1.4 1.4 0 1 0-2.8 0Z", "mute", true),
  ] },

  dataTreeSurface: { parts: [
    p("M3.5 5q3.5-3 7 0t7 0v5.5q-3.5 3-7 0t-7 0Z", "brand"),
    p("M5.6 7.6q2.5-2 4.9 0t4.9 0", "f2i"),
    p("M7.5 9.6V19.5H13.6 M7.5 15.5H13.6", "mute"),
    p("M15.4 15.5a1.4 1.4 0 1 0 2.8 0a1.4 1.4 0 1 0-2.8 0Z M15.4 19.5a1.4 1.4 0 1 0 2.8 0a1.4 1.4 0 1 0-2.8 0Z", "mute", true),
  ] },

  // the derrick, an A, between its two levels drawn thin: the kelly bushing
  // across it, the datum the vertical depths count from at its feet; the
  // hole is the trunk
  dataTreeWell: { parts: [
    p("M6.5 11.5 10.5 3l4 8.5", "brand"),
    p("M6 6.95h9v1.1H6Z M3.5 10.95h14v1.1h-14Z", "f2i", true),
    p("M10.5 12.6V19.5H13.6 M10.5 15.5H13.6", "mute"),
    p("M15.4 15.5a1.4 1.4 0 1 0 2.8 0a1.4 1.4 0 1 0-2.8 0Z M15.4 19.5a1.4 1.4 0 1 0 2.8 0a1.4 1.4 0 1 0-2.8 0Z", "mute", true),
  ] },

  // the trace has no axis, so the trunk is not one: it hangs under the lobes
  dataTreeSeismic: { parts: [
    p("M10.5 3C19.5 3.2 19.5 7.3 10.5 7.5Z", "brand", true),
    p("M10.5 7.5C1.5 7.7 1.5 11.8 10.5 12Z", "f2i", true),
    p("M7.5 12.6V19.5H13.6 M7.5 15.5H13.6", "mute"),
    p("M15.4 15.5a1.4 1.4 0 1 0 2.8 0a1.4 1.4 0 1 0-2.8 0Z M15.4 19.5a1.4 1.4 0 1 0 2.8 0a1.4 1.4 0 1 0-2.8 0Z", "mute", true),
  ] },

  // Statistics: the sum, and two bars of a distribution in green.
  statistics: { parts: [
    p("M13 5H4.5l5 7-5 7H13"),
    p("M16.5 19v-5 M20 19V9", "f2i"),
  ] },

  // Calculator: the body and its keys, the display in green.
  calculator: { parts: [
    p("M5.5 3.5h13v17h-13Z M8.6 13.2h.6 M11.7 13.2h.6 M14.8 13.2h.6 M8.6 17h.6 M11.7 17h.6 M14.8 17h.6"),
    p("M8 6.2h8v3.4H8Z", "f2i", true),
  ] },

  // Reload: the turn, its arrowhead in green.
  reload: { parts: [
    p("M19.5 12a7.5 7.5 0 1 1-2.2-5.3"),
    p("M17.6 2.6V7h-4.4", "f2i"),
  ] },

  // Session: the disk the state is saved on, its label in green.
  session: { parts: [
    p("M4.5 3.5h11.5l3.5 3.5v13.5h-15Z M8 3.5V8h7V3.5"),
    p("M7.5 20.5v-6.5h9v6.5", "f2i"),
  ] },

  // ------------------------------------------- a card's title bar
  // Where the card goes, in green, in the view's frame: docked left, right,
  // at the top, at the bottom, or floating over it (widgets/view-card, the
  // dock's tab rows).
  cardDockLeft: { parts: [
    p("M3.5 5h17v14h-17Z"),
    p("M3.5 5h6v14h-6Z", "f2i", true),
  ] },
  cardDockRight: { parts: [
    p("M3.5 5h17v14h-17Z"),
    p("M14.5 5h6v14h-6Z", "f2i", true),
  ] },
  cardDockTop: { parts: [
    p("M3.5 5h17v14h-17Z"),
    p("M3.5 5h17v5.5h-17Z", "f2i", true),
  ] },
  cardDockBottom: { parts: [
    p("M3.5 5h17v14h-17Z"),
    p("M3.5 13.5h17V19h-17Z", "f2i", true),
  ] },
  cardFloat: { parts: [
    p("M3.5 5h17v14h-17Z"),
    p("M10 8.5h7.5v6.5H10Z", "f2i", true),
  ] },

  // ------------------------------------------- a view's tab row
  // What the click does, as on a browser's title bar: two windows to detach
  // the view, one to anchor it.
  viewDetach: { parts: [
    p("M4 8h12v12H4Z", "f2i"),
    p("M8 8V4h12v12h-4", "f2i"),
  ] },
  viewAnchor: { parts: [
    p("M5 5h14v14H5Z", "f2i"),
  ] },

  // Import data: the cloud, the arrow coming in from it in green.
  importData: { parts: [
    p("M8.5 18.5h-1a4 4 0 0 1-.5-8A5 5 0 0 1 17 10.5a4 4 0 0 1 0 8h-1"),
    p("M12 20.5V12 M9 15l3-3 3 3", "f2i"),
  ] },

  // The grid as a whole — the row that holds the geometry, the
  // properties, the sub-representations — held in a bracket. The geometry
  // below it is that same block, divided into its cells.
  gridContainer: { parts: [
    p("M8 9h8.5v8.5H8Z M8 9 10 7h8.5v8.5L16.5 17.5", "rock"),
    p("M6 5.5H4v15h2", "rock"),
  ] },

  // The folders of the tree: one silhouette for all of them, and one mark
  // inside that names what the folder holds.
  folderProperties: { parts: [
    p("M3.5 7h6l1.6 2.2h9.4v9.8h-17Z"),
    p("M7.5 16.2c1.6 0 1.9-3.4 3.6-3.4s2.1 2.6 3.7 2.6", "prop"),
  ] },

  folderSubRepresentation: { parts: [
    p("M3.5 7h6l1.6 2.2h9.4v9.8h-17Z"),
    p("M12.8 12.6h3.8v3.8h-3.8Z", "real", true),
    p("M8 12.6h3.4v3.8H8Z", "real"),
  ] },

  folderBlockedWellbore: { parts: [
    p("M3.5 7h6l1.6 2.2h9.4v9.8h-17Z"),
    p("M10.8 13.2h4.6v4.6h-4.6Z", "rock"),
    p("M13.1 11v2.2", "well"),
  ] },

  folderLogs: { parts: [
    p("M3.5 7h6l1.6 2.2h9.4v9.8h-17Z"),
    p("M12 12.2c1.9 1.3-1.9 2.7 0 4", "log"),
    p("M9 12.2v4", "well"),
  ] },

  folderMarkers: { parts: [
    p("M3.5 7h6l1.6 2.2h9.4v9.8h-17Z"),
    p("M12 11.9v5.4", "well"),
    p("M12 12.6a1.6 1.6 0 1 0 0 3.2 1.6 1.6 0 1 0 0-3.2", "top", true),
  ] },

  folderCompletions: { parts: [
    p("M3.5 7h6l1.6 2.2h9.4v9.8h-17Z"),
    p("M10.6 11.9v5.2 M13.8 11.9v5.2", "well"),
    p("M10.9 13.9h2.6v1.7h-2.6Z", "well", true),
  ] },
};

export default FESPP_ICONS;
