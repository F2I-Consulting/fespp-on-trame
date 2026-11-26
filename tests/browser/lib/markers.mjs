/*
 * The stable markers this harness is allowed to know about.
 *
 * The rule: a test addresses the application by ROLE (a button of the
 * top bar), by VISIBLE TEXT (a tree row titled `velocity`), or by one of the
 * class markers below — never by a pixel position, a size or an index in a
 * layout. Every marker here was read off the running application and belongs to
 * a widget's own template, so it moves only when that widget is rewritten.
 *
 * The application state is a marker too, and the strongest one: `window.trame`
 * exposes the shared state, so a test can ask the application what it thinks it
 * is showing (which tools this view offers, which array colours which
 * representation) instead of inferring it from the screen. See `state()`.
 */
export const M = {
  // --- the shared panel chrome (widgets/_shared/panel.css) -----------------
  // Every panel wears these, widget or Vuetify-in-Python alike.
  bar: '.fp-bar',
  title: '.fp-title',
  empty: '.fp-empty',
  // the right-hand group of a header row: summary, actions, export, and the
  // tree button last
  right: '.fp-right',

  // --- shell ---------------------------------------------------------------
  // The views' dock, never the dock of cards a 3D view may hold in its panel
  // (`.fp-cards`, view_panel). No ancestor is named in front: under a scope
  // (a part, a floating window) Playwright matches a selector's combinators
  // within that scope only, and `.fp-views` lies outside it.
  // A dockview tab exists only once the server has pushed its layout: this is
  // THE gate that says the client is up (the mount itself happens earlier).
  dockTab: '.dv-tab:not(.fp-cards *)',
  dockTabActive: '.dv-tab.dv-active-tab:not(.fp-cards *)',
  dockTabClose: '.dv-default-tab-action',   // scoped UNDER a tab
  // a panel's content: dockview-vue wraps the buttons of a tab row in the
  // same class
  dockPart: '.dv-vue-part:not(.fp-cards *):not(.dv-tabs-and-actions-container *)',
  // a view detached from the dock, in a floating window
  dockWindow: '.dv-resize-container:not(.fp-cards *)',
  // a group's tab row, and the buttons at its right end (data-fp-action:
  // left, right, top, bottom, float, close), the same on views and cards
  dockRow: '.dv-tabs-and-actions-container:not(.fp-cards *)',
  dockAction: '.fp-dock-act:not(.fp-cards *)',
  topBarButton: 'header button',

  // --- the camera strip of a 3D view's title bar (widgets/title3dview) -----
  // one per render view, drawn in the dockview tab row above its panel
  titleStrip: '.t3',
  titleStripBtn: '.t3-btn',      // scoped UNDER a strip, never page-wide
  titleStripMode: '.t3-mode:not(.t3-domain)',    // the 3D / 2D chip, per view

  // --- per-view toolbar and its tool cards ---------------------------------
  // A card floats in its view, or is a panel of the view's own dock of cards
  // (`.fc-in-panel`): that panel's tab shows the title and closes it, and the
  // card keeps its full title (title · target) in a `.fc-title` read by
  // screen readers only.
  toolbar: '.tb',
  toolButton: '.tb .tb-btn',
  card: '.fc',
  cardTitle: '.fc-title',
  cardBody: '.fc-body',
  cardClose: '.fc-close',          // a floating card's own
  cardInPanel: '.fc-in-panel',
  cardDock: '.fp-cards',

  // --- data explorer tree --------------------------------------------------
  tree: '.fdx',
  // the Reservoir / Surface / Well family tabs, drawn when a tree has more
  // than one; the current one carries `active`
  treeTab: '.fdx-tab',
  treeRow: '.tn-row',
  treeCaret: '.tn-caret',        // ▸ collapsed, ▾ expanded
  treeCheck: '.tn-check',
  treeTitle: '.tn-title',
  treeLoadTag: '.tn-load',       // a read in flight, or one that failed
  treeEye: '.tn-eye',            // shown in a 3D view
  // every panel that carries a tree opens it with the SAME button
  treeToggle: 'button[title^="Show or hide this panel"]',
  // the bulk-select menu, offered in the DATA tree and nowhere else
  treeBulk: '.fdx-select-btn',
  treeBulkItem: '.fdx-select .fdx-menu-item',   // a row of the Select ▾ menu
  caretCollapsed: '\u25b8',
  // The tree's right-click menu is the shared <fp-menu> (class `fdx-ctx` on
  // its root, the backdrop that a click closes it on); the Select menu keeps
  // `.fdx-backdrop` / `.fdx-menu-item`.
  ctxMenu: '.fdx-ctx .fp-menu',
  ctxTitle: '.fdx-ctx .fp-menu-title',
  ctxItem: '.fdx-ctx .fp-menu-item',
  backdrop: '.fdx-ctx',

  // --- the 3D views door and the "New 3D view" question (widgets/newview) ---
  // the door opens a pop-over of tiles, its "+" tile asks whether the new view
  // starts empty or as a copy of an open one
  viewsDoor: 'header .fvd button',
  viewsDoorPop: '.fvd-pop',
  viewsDoorAdd: '.fvd-add',
  newViewDialog: '.fnv',

  // --- the confirmation dialog ---------------------------------------------
  // one gesture whose cost is bigger than what it shows asks first
  scrim: '.fp-scrim',
  dialog: '.fp-dialog',

  // --- import door ---------------------------------------------------------
  fileInput: 'input[type=file]',
  // the import starts by itself once the files have settled; this is the
  // button that ENDS it, offered only when every file is in
  importClose: 'button.uf-close',

  // --- the Statistics view (kind `compare`, widgets/compare) ----------------
  compare: '.fcp',
  compareTab: '.fcp-tab',          // a kind of the selection
  compareTabOn: '.fcp-tab-on',
  // one row of the matrix: an item of the kind shown,
  // or a row that follows an item (a part of its grid, a 3D view cutting it)
  compareItem: '.fcp-item',
  compareOwnItem: '.fcp-item:not(.fcp-follows)',
  compareFollows: '.fcp-item.fcp-follows',
  compareRowMenu: '.fcp-ctx .fp-menu',   // over the page's body: look it up from the page
  compareBadge: '.fcp-badge',      // why a row could not be drawn: no count, the table says it

  // --- cross-plot panel ----------------------------------------------------
  crossplot: '.fxp',
  // the point count: the summary of the panel's own bar. Under the Statistics
  // view's bar there is none: the table says it

  // --- data health panel ---------------------------------------------------
  health: '.fhl',

  // --- Log ↔ Grid panel ----------------------------------------------------
  reconcile: '.frc',

  plotly: '.js-plotly-plot',
};

/*
 * Toolbar buttons that flip a VIEW MODE instead of opening a card. They sit in
 * the same button strip as the tools and are indistinguishable from the DOM —
 * the application tells them apart by key, and so does this harness.
 */
export const MODE_KEYS = ['pick', 'frustum'];

/*
 * Console warnings that are not the application's. The remote 3D view streams
 * rendered images, and the GPU driver comments on the readback; nothing the
 * application can fix, and it appears the moment anything is displayed. Every
 * OTHER warning, and every error, fails the run.
 */
export const CONSOLE_NOISE = [/^\[\.WebGL-/];
