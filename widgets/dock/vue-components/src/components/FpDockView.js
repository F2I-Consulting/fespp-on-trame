// The application's dock: trame-dockview 2.0.1 (Kitware, MIT, see
// ../../../LICENSE) on dockview 7.0.4, its panels FpDockPanel.
import "dockview-vue/dist/styles/dockview.css";
import { computed, onBeforeUnmount, provide, ref, watch } from "vue";
import { DockviewVue, getPanelData } from "dockview-vue";
import FpDockPanel from "./FpDockPanel";
import FpDockHeader, { DOCK_HEADER, HEADER_ORDER } from "./FpDockHeader";

const THEMES = {
  dark: {
    name: "dark",
    className: "dockview-theme-dark",
  },
  light: {
    name: "light",
    className: "dockview-theme-light",
  },
  visualstudio: {
    name: "visualStudio",
    className: "dockview-theme-vs",
  },
  abyss: {
    name: "abyss",
    className: "dockview-theme-abyss",
  },
  dracula: {
    name: "dracula",
    className: "dockview-theme-dracula",
  },
  abyssspaced: {
    name: "abyssSpaced",
    className: "dockview-theme-abyss-spaced",
    gap: 10,
    dndOverlayMounting: "absolute",
    dndPanelOverlay: "group",
  },
  lightspaced: {
    name: "lightSpaced",
    className: "dockview-theme-light-spaced",
    gap: 10,
    dndOverlayMounting: "absolute",
    dndPanelOverlay: "group",
  },
};

const LAYOUT_CHANGE_DEBOUNCE = 500;

// The fixed central panel of a dock given the `center` prop.
const CENTER_ID = "__center__";
// Pixels: rounding slack between group rectangles, and the widest spacing a
// theme puts between two touching groups.
const RECT_TOLERANCE = 2;
const ADJACENT_GAP = 16;

const positive = (value) => typeof value === "number" && value > 0;

// addGroup directions of the dock's four edges (the header's buttons).
const EDGE_DIRECTIONS = {
  left: "left",
  right: "right",
  top: "above",
  bottom: "below",
};
// Where a card may open the first time, beside the center (its spec's `side`).
const CENTER_SIDES = ["left", "right", "above", "below"];
// A detached panel's window, as a share of the dock, centred in it.
const FLOAT_SHARE = 0.6;
// The most of the dock a panel docked along an edge takes.
const EDGE_SHARE = 0.5;
// What dockview's drop targets set on a drag event one of them takes
// (Droptarget.USED_EVENT_ID, not exported).
const TAKEN_BY_DOCKVIEW = "__dockview_droptarget_event_is_used__";

const clamp = (value, low, high) => Math.max(low, Math.min(value, Math.max(low, high)));

// initialWidth / initialHeight of an addPanel call, only when > 0.
function initialSize(source) {
  const size = {};
  if (positive(source?.initialWidth)) {
    size.initialWidth = source.initialWidth;
  }
  if (positive(source?.initialHeight)) {
    size.initialHeight = source.initialHeight;
  }
  return size;
}

function templateToComponent(name) {
  const safeName = name
    .toLowerCase()
    .replaceAll("_", "-")
    .replaceAll("--", "-");
  return `trame-template-${safeName}`;
}

const PROP_NAMES = [
  "defaultRenderer",
  "disableAutoResizing",
  "disableDnd",
  "disableFloatingGroups",
  "disableTabsOverflowList",
  "dndEdges",
  "floatingGroupBounds",
  "floatingGroupDragHandle",
  "hideBorders",
  "locked",
  "noPanelsOverlay",
  "popoutUrl",
  "scrollbars",
  "singleTabMode",
];

export default {
  emits: [
    "ready",
    "activePanel",
    "removePanel",
    "layoutChanged",
    "panelVisibility",
    "panelCloseRequest",
    "headerAction",
  ],
  props: {
    // The buttons at the right end of every tab row but the center's, among
    // "left", "right", "top", "bottom", "float", "close", drawn in that
    // order; each acts on its group's active panel.
    headerButtons: {
      type: Array,
      default: () => [],
    },
    // Those of headerButtons emitted as headerAction {id, action, width,
    // height, floating} instead of performed here; with "float", a tab
    // dropped where nothing docks it is emitted too, with {left, top}.
    headerEmit: {
      type: Array,
      default: () => [],
    },
    // Trame template of a fixed central panel: no tab row, nothing docks
    // into it, it cannot be dragged nor closed.
    // the layout this dock was left in (its layoutChanged): read once, when
    // the dock is ready
    layout: {
      type: Object,
      default: null,
    },
    center: {
      type: String,
    },
    // {id, n}: the panel `id` brought in front of its group's other tabs,
    // each time `n` changes
    reveal: {
      type: Object,
      default: null,
    },
    // Ids of the card panels that must be present, around the center.
    panels: {
      type: Array,
    },
    // Card id -> {title, initialWidth, initialHeight, minimumWidth,
    // minimumHeight, slot, side, below, with}; a card is added once its spec
    // is known. `below`: the id of a panel the card opens under, split below
    // it, while that panel is docked; `with`: the id of a panel it opens
    // beside as a tab of its group, first, while that panel is docked.
    panelSpecs: {
      type: Object,
    },
    theme: {
      default: "Dracula",
    },
    defaultRenderer: {
      default: "always",
      type: String,
    },
    disableAutoResizing: {
      default: false,
      type: Boolean,
    },
    disableDnd: {
      default: false,
      type: Boolean,
    },
    disableFloatingGroups: {
      default: false,
      type: Boolean,
    },
    disableTabsOverflowList: {
      default: false,
      type: Boolean,
    },
    dndEdges: {
      default: false,
      type: Boolean,
    },
    // "titlebar" (a bar of its own above a floating window) | "tabbar"
    // (the empty part of its tab row moves it)
    floatingGroupDragHandle: {
      type: String,
    },
    floatingGroupBounds: {}, // {minimumHeightWithinViewport, minimumWidthWithinViewport} | boundedWithinViewport
    hideBorders: {
      default: false,
      type: Boolean,
    },
    locked: {
      default: false,
      type: Boolean,
    },
    noPanelsOverlay: {
      default: "watermark", // watermark | emptyGroup
      type: String,
    },
    popoutUrl: {
      type: String,
    },
    scrollbars: {
      // custom | native
      type: String,
    },
    singleTabMode: {
      default: "default", // default | fullwidth
      type: String,
    },
    components: {
      default: () => ({
        defaultTabComponent: null,
        leftHeaderActionsComponent: null,
        prefixHeaderActionsComponent: null,
        rightHeaderActionsComponent: null,
        watermarkComponent: null,
      }),
    },
  },
  components: {
    DockviewVue,
    FpDockPanel,
  },
  setup(props, { emit }) {
    let api = null;
    // The dock's own element: its size is what a button places panels in.
    const root = ref(null);
    let layoutMutation = null;
    const disposables = [];
    const panelDisposables = new Map();
    const pendingCalls = [];
    const theme = computed(() => THEMES[props.theme.toLowerCase()]);
    let disposed = false;
    // Card panels currently added from `panels`, and their order of addition.
    const cardIds = new Set();
    let cardOrder = [];
    // Cards being removed by the `panels` watch: no event reaches the server.
    const silentRemovals = new Set();
    // Card id -> where it stood when the watch last removed it.
    const lastPlaces = new Map();
    // The group holding cards the user last made active.
    let lastCardGroup = null;

    onBeforeUnmount(() => {
      disposed = true;
      stopOutside();
      panelDisposables.forEach((disposable) => disposable.dispose());
      panelDisposables.clear();
      while (disposables.length) {
        disposables.pop().dispose();
      }
    });

    // Queue calls made before the dockview api is ready and flush them in order
    function whenReady(fn) {
      if (api) {
        fn();
      } else {
        pendingCalls.push(fn);
      }
    }

    function debounce(fn, delay) {
      let timeout = null;
      const debounced = (...args) => {
        window.clearTimeout(timeout);
        timeout = window.setTimeout(() => fn(...args), delay);
      };
      debounced.cancel = () => window.clearTimeout(timeout);
      return debounced;
    }

    function watchPanelVisibility(panel) {
      const panelId = panel?.id;
      if (!panelId || !panel?.api?.onDidVisibilityChange) {
        return;
      }
      panelDisposables.get(panelId)?.dispose();
      panelDisposables.set(
        panelId,
        panel.api.onDidVisibilityChange(({ isVisible }) => {
          emit("panelVisibility", { id: panelId, visible: isVisible });
        }),
      );
      // Seed the server-side visibility map with the panel's current state,
      // covering panels added inactive or restored hidden via fromJSON.
      emit("panelVisibility", { id: panelId, visible: panel.api.isVisible });
    }

    const isCenter = (id) => !!props.center && id === CENTER_ID;

    // The center can neither be closed, dragged nor receive tabs, and shows
    // no tab row.
    function secureCenter(panel) {
      panel.api.close = () => {};
      const group = panel.api.group;
      if (group) {
        // true, not "no-drop-target": cards may still dock along its edges.
        group.locked = true;
        group.header.hidden = true;
      }
    }

    // A user close of a card asks the server, which shrinks `panels`.
    function guardPanel(panel) {
      if (isCenter(panel?.id)) {
        secureCenter(panel);
      } else if (cardIds.has(panel?.id)) {
        const id = panel.id;
        panel.api.close = () => emit("panelCloseRequest", id);
      }
    }

    function ensureCenter() {
      if (disposed || !api || !props.center) {
        return;
      }
      let panel = api.getPanel(CENTER_ID);
      if (!panel) {
        const spec = {
          id: CENTER_ID,
          component: "FpDockPanel",
          // a slot: the host's content moves in (FpDockSlot), no trame
          // template of its own
          params: { slot: props.center },
        };
        // Back at the right edge rather than as a tab in the active card group.
        if (api.panels.length) {
          spec.position = { direction: "right" };
        }
        panel = api.addPanel(spec);
      }
      secureCenter(panel);
    }

    // Deferred out of the dockview event that asked for it.
    function restoreLater(withCards) {
      Promise.resolve().then(() => {
        try {
          ensureCenter();
          if (withCards) {
            syncPanels();
          }
        } catch (error) {
          console.error("fp-dock: restoring the center or cards failed", error);
        }
      });
    }

    function onReady(event) {
      api = event.api;

      // A layout load removes and re-adds panels internally. Track its
      // transaction so temporary lifecycle events cannot tear down
      // server-owned views.
      disposables.push(
        api.onWillMutateLayout((mutation) => {
          layoutMutation = mutation;
        }),
      );
      disposables.push(
        api.onDidMutateLayout((mutation) => {
          layoutMutation = null;
          if (mutation?.kind === "load" && (props.center || cardIds.size)) {
            restoreLater(true);
          }
        }),
      );

      // Listen to active panel to emit event
      disposables.push(
        api.onDidActivePanelChange((e) => {
          if (layoutMutation?.kind === "load" || silentRemovals.size) {
            return;
          }
          if (isCenter(e.panel?.id)) {
            return;
          }
          emit("activePanel", e.panel?.id);
        }),
      );
      disposables.push(
        api.onDidActiveGroupChange((group) => {
          if (group && !group.panels.some((panel) => isCenter(panel.id))) {
            lastCardGroup = group;
          }
        }),
      );
      disposables.push(
        api.onDidRemovePanel((e) => {
          const id = e?.id;
          panelDisposables.get(id)?.dispose();
          panelDisposables.delete(id);
          if (layoutMutation?.kind === "load") {
            return;
          }
          if (isCenter(id)) {
            restoreLater(false);
            return;
          }
          if (cardIds.has(id)) {
            // Gone without the watch: let the server drop it from `panels`.
            if (!silentRemovals.has(id)) {
              cardIds.delete(id);
              emit("panelCloseRequest", id);
            }
            return;
          }
          emit("removePanel", id);
        }),
      );

      // The center never leaves its place.
      disposables.push(
        api.onWillDragPanel((e) => {
          if (isCenter(e.panel?.id)) {
            e.nativeEvent.preventDefault();
          }
        }),
      );
      disposables.push(
        api.onWillDragGroup((e) => {
          if (e.group?.panels?.some((panel) => isCenter(panel.id))) {
            e.nativeEvent.preventDefault();
          }
        }),
      );

      // Track visibility of every panel, including panels restored via fromJSON
      disposables.push(
        api.onDidAddPanel((panel) => {
          guardPanel(panel);
          watchPanelVisibility(panel);
        }),
      );

      // Emit debounced layout snapshots for persistence
      const emitLayout = debounce(
        () => emit("layoutChanged", api.toJSON()),
        LAYOUT_CHANGE_DEBOUNCE,
      );
      disposables.push(api.onDidLayoutChange(emitLayout));
      disposables.push({ dispose: emitLayout.cancel });

      // A layout left by this dock earlier (a session reopened, a page
      // reloaded) comes back first; the load then puts the center and the
      // cards wanted right (restoreLater).
      if (props.center && isObject(props.layout) && isObject(props.layout.grid)
          && isObject(props.layout.panels)) {
        try {
          loadSaved(props.layout);
        } catch (error) {
          console.error("fp-dock: the saved layout could not be restored", error);
        }
      }
      // Before the queued calls: the cards are placed around it.
      try {
        ensureCenter();
      } catch (error) {
        console.error("fp-dock: center panel failed", error);
      }

      emit("ready");

      while (pendingCalls.length) {
        const call = pendingCalls.shift();
        try {
          call();
        } catch (error) {
          console.error("fp-dock: queued call failed", error);
        }
      }
    }

    function addPanel(id, title, templateName, addOn = {}) {
      whenReady(() => {
        // Idempotent: the server replays its open-panel set on every `ready`
        // (fresh client, browser refresh); a client that already has the
        // panel must not throw on the duplicate id.
        if (api.getPanel(id)) {
          return;
        }
        const spec = {
          id,
          title,
          component: "FpDockPanel",
          ...addOn,
          params: { ...addOn?.params, templateName },
        };
        try {
          api.addPanel(spec);
        } catch (error) {
          // A stale position (e.g. its referencePanel was closed after the
          // layout was recorded) throws in dockview. One bad position
          // must not abort the add — and with it the rest of the replayed
          // panel set — so retry with default placement instead.
          if (!spec.position) {
            throw error;
          }
          console.warn(
            "fp-dock: addPanel position rejected, adding unpositioned",
            error,
          );
          delete spec.position;
          api.addPanel(spec);
        }
      });
    }

    // --- Card panels, driven by `panels` / `panelSpecs` ---

    function groupRect(group) {
      const rect = group?.element?.getBoundingClientRect();
      return rect && rect.width > 0 && rect.height > 0 ? rect : null;
    }

    function inLeftColumn(card, center) {
      if (card.api.location.type !== "grid") {
        return false;
      }
      const rect = groupRect(card.api.group);
      const centerRect = groupRect(center.api.group);
      // Not laid out (hidden dock): trust the grid placement.
      if (!rect || !centerRect) {
        return true;
      }
      return rect.right <= centerRect.left + RECT_TOLERANCE;
    }

    // First card on its spec's side of the center (left by default), the next
    // left ones stacked below the most recently added card still in that
    // left column.
    function defaultPlace(spec) {
      const center = props.center ? api.getPanel(CENTER_ID) : undefined;
      if (!center) {
        return initialSize(spec);
      }
      if (CENTER_SIDES.includes(spec.side) && spec.side !== "left") {
        return {
          ...initialSize(spec),
          position: { referencePanel: CENTER_ID, direction: spec.side },
        };
      }
      for (let i = cardOrder.length - 1; i >= 0; i--) {
        const card = cardIds.has(cardOrder[i]) && api.getPanel(cardOrder[i]);
        if (card && inLeftColumn(card, center)) {
          return {
            ...initialSize(spec),
            position: { referencePanel: card.id, direction: "below" },
          };
        }
      }
      return {
        ...initialSize(spec),
        position: { referencePanel: CENTER_ID, direction: "left" },
      };
    }

    // A tab beside the panel the spec names (`with`), in its group, when that
    // panel is docked in the grid; a floating or absent one names no place.
    function withPlace(spec) {
      const mate = spec.with ? api.getPanel(spec.with) : null;
      if (!mate || mate.api.location.type !== "grid") {
        return null;
      }
      return {
        ...initialSize(spec),
        position: { referencePanel: mate.id, direction: "within" },
      };
    }

    // Split below the panel the spec names (`below`), when that panel is
    // docked in the grid; a floating or absent one names no place.
    function belowPlace(spec) {
      const anchor = spec.below ? api.getPanel(spec.below) : null;
      if (!anchor || anchor.api.location.type !== "grid") {
        return null;
      }
      return {
        ...initialSize(spec),
        position: { referencePanel: anchor.id, direction: "below" },
      };
    }

    const holdsCards = (group) =>
      !!group &&
      api.groups.includes(group) &&
      group.panels.some((panel) => cardIds.has(panel.id));

    // The card group last made active, else the group of the most recently
    // added card still in the dock, else any group holding a card.
    function cardGroup() {
      if (holdsCards(lastCardGroup)) {
        return lastCardGroup;
      }
      for (let i = cardOrder.length - 1; i >= 0; i--) {
        const card = cardIds.has(cardOrder[i]) && api.getPanel(cardOrder[i]);
        if (card && holdsCards(card.api.group)) {
          return card.api.group;
        }
      }
      return api.groups.find(holdsCards) || null;
    }

    // The last tab of the card group, as a browser opens a new tab.
    function tabPlace() {
      const group = cardGroup();
      if (!group) {
        return null;
      }
      return {
        position: { referenceGroup: group, direction: "within", index: group.panels.length },
      };
    }

    function rememberedPlace(id) {
      const place = lastPlaces.get(id);
      if (!place) {
        return null;
      }
      if (place.floating) {
        return props.disableFloatingGroups ? null : { floating: place.floating };
      }
      const reference = place.references.find((ref) => api.getPanel(ref));
      if (!reference) {
        return null;
      }
      if (place.direction === "within") {
        const count = api.getPanel(reference).api.group.panels.length;
        return {
          position: {
            referencePanel: reference,
            direction: "within",
            index: Math.min(place.index, count),
          },
        };
      }
      return {
        ...initialSize(place),
        position: { referencePanel: reference, direction: place.direction },
      };
    }

    // The floating window's anchored box when the group is alone in it,
    // else the group's own box.
    function floatingBox(group) {
      const entry = (api.toJSON().floatingGroups || []).find(
        (floating) => floating.data?.id === group.id,
      );
      if (entry?.position) {
        const { width, height, ...anchor } = entry.position;
        return { position: anchor, width, height };
      }
      const box = group.api.boundingBox;
      return box
        ? { x: box.left, y: box.top, width: box.width, height: box.height }
        : null;
    }

    // The side of `group` facing its nearest grid neighbour. Touching
    // neighbours win, first those of the same extent along the shared edge
    // (a sibling in the same split, e.g. the card above in a column), then
    // the longest shared edge; otherwise the closest centre.
    function sidePlace(group) {
      const rect = groupRect(group);
      if (!rect) {
        return null;
      }
      let best = null;
      for (const other of api.groups) {
        if (
          other === group ||
          other.api.location.type !== "grid" ||
          !other.panels.length
        ) {
          continue;
        }
        const near = groupRect(other);
        if (!near) {
          continue;
        }
        const rowOverlap =
          Math.min(rect.bottom, near.bottom) - Math.max(rect.top, near.top);
        const columnOverlap =
          Math.min(rect.right, near.right) - Math.max(rect.left, near.left);
        const sides = [
          ["right", rect.left - near.right, rowOverlap, rect.height - near.height],
          ["left", near.left - rect.right, rowOverlap, rect.height - near.height],
          ["below", rect.top - near.bottom, columnOverlap, rect.width - near.width],
          ["above", near.top - rect.bottom, columnOverlap, rect.width - near.width],
        ];
        let candidate = null;
        for (const [direction, gap, overlap, extent] of sides) {
          if (overlap > 0 && gap >= -RECT_TOLERANCE && gap <= ADJACENT_GAP) {
            candidate = {
              direction,
              rank: Math.abs(extent) <= RECT_TOLERANCE ? 0 : 1,
              score: -overlap,
            };
            break;
          }
        }
        if (!candidate) {
          const dx = (rect.left + rect.right - near.left - near.right) / 2;
          const dy = (rect.top + rect.bottom - near.top - near.bottom) / 2;
          candidate = {
            direction:
              Math.abs(dx) >= Math.abs(dy)
                ? dx >= 0 ? "right" : "left"
                : dy >= 0 ? "below" : "above",
            rank: 2,
            score: Math.hypot(dx, dy),
          };
        }
        if (
          !best ||
          candidate.rank < best.rank ||
          (candidate.rank === best.rank && candidate.score < best.score)
        ) {
          best = { ...candidate, group: other };
        }
      }
      if (!best) {
        return null;
      }
      const panels = best.group.panels;
      const references = [
        ...panels.filter((panel) => panel.id === CENTER_ID),
        ...panels.filter((panel) => panel === best.group.activePanel),
        ...panels,
      ].map((panel) => panel.id);
      return {
        direction: best.direction,
        references: [...new Set(references)],
        initialWidth: rect.width,
        initialHeight: rect.height,
      };
    }

    function recordPlace(panel) {
      const group = panel.api.group;
      const others = (group?.panels || [])
        .filter((other) => other !== panel && other.id !== CENTER_ID)
        .map((other) => other.id);
      let place = null;
      if (others.length) {
        place = {
          direction: "within",
          references: others,
          index: group.panels.indexOf(panel),
        };
      } else if (group?.api.location.type === "floating") {
        const box = floatingBox(group);
        place = box ? { floating: box } : null;
      } else if (group?.api.location.type === "grid") {
        place = sidePlace(group);
      }
      if (place) {
        lastPlaces.set(panel.id, place);
      } else {
        lastPlaces.delete(panel.id);
      }
    }

    function addCard(id, spec) {
      const base = {
        id,
        title: spec.title ?? id,
        component: "FpDockPanel",
        params: { slot: spec.slot },
      };
      if (positive(spec.minimumWidth)) {
        base.minimumWidth = spec.minimumWidth;
      }
      if (positive(spec.minimumHeight)) {
        base.minimumHeight = spec.minimumHeight;
      }
      // Registered first: onDidAddPanel installs the close interception.
      cardIds.add(id);
      // Last resort at the dock's left edge: unpositioned, dockview would
      // open it as a tab of the active group, possibly the center's.
      // a card that names its side (the zone statistics under the logs,
      // the manager, 12/11) opens there before it would join the card group
      const sided = CENTER_SIDES.includes(spec.side) && spec.side !== "left";
      // a card that names the panel it joins as a tab, or the one it opens
      // under, goes there before where it stood last
      const places = [
        withPlace(spec),
        belowPlace(spec),
        rememberedPlace(id),
        ...(sided ? [defaultPlace(spec), tabPlace()] : [tabPlace(), defaultPlace(spec)]),
        props.center
          ? { ...initialSize(spec), position: { direction: "left" } }
          : {},
      ];
      let lastError = null;
      for (const place of places) {
        if (!place || api.getPanel(id)) {
          continue;
        }
        try {
          api.addPanel({ ...base, ...place });
        } catch (error) {
          lastError = error;
        }
      }
      if (!api.getPanel(id)) {
        cardIds.delete(id);
        console.error("fp-dock: card panel could not be added", id, lastError);
        return;
      }
      cardOrder = cardOrder.filter((other) => other !== id);
      cardOrder.push(id);
    }

    function removeCard(id) {
      const panel = api.getPanel(id);
      if (panel) {
        try {
          recordPlace(panel);
        } catch (error) {
          lastPlaces.delete(id);
        }
        silentRemovals.add(id);
        try {
          api.removePanel(panel);
        } finally {
          silentRemovals.delete(id);
        }
      }
      cardIds.delete(id);
    }

    function syncPanels() {
      if (disposed || !api) {
        return;
      }
      const wanted = (Array.isArray(props.panels) ? props.panels : []).filter(
        (id) => id !== CENTER_ID,
      );
      const specs = props.panelSpecs || {};
      for (const id of [...cardIds]) {
        if (!wanted.includes(id)) {
          removeCard(id);
        }
      }
      for (const id of wanted) {
        // An id taken by a panel of addPanel() is left alone.
        if (api.getPanel(id) || !specs[id]) {
          continue;
        }
        addCard(id, specs[id]);
      }
    }

    watch(
      () => [props.panels, props.panelSpecs],
      () => whenReady(syncPanels),
      { immediate: true, deep: true },
    );

    watch(
      () => props.reveal && props.reveal.n,
      () => {
        if (props.reveal && props.reveal.id) {
          activePanel(props.reveal.id);
        }
      },
    );

    const headerButtons = computed(() => {
      const listed = Array.isArray(props.headerButtons)
        ? props.headerButtons
        : [];
      return HEADER_ORDER.filter((name) => listed.includes(name));
    });

    // v-bind
    const bind = computed(() => {
      const dockViewProps = {};
      Object.entries(props.components).forEach(([k, v]) => {
        if (v) {
          dockViewProps[k] = templateToComponent(v);
        }
      });

      PROP_NAMES.forEach((key) => {
        if (props[key]) {
          dockViewProps[key] = props[key];
        }
      });

      // The dock's own buttons take the right header actions over a
      // template given for them.
      if (headerButtons.value.length) {
        dockViewProps.rightHeaderActionsComponent = FpDockHeader;
      }

      return dockViewProps;
    });

    function removePanel(panelId) {
      whenReady(() => {
        api.getPanel(panelId)?.api?.close();
      });
    }

    function activePanel(panelId) {
      whenReady(() => {
        api.getPanel(panelId)?.api?.setActive();
      });
    }

    function setPanelTitle(panelId, title) {
      whenReady(() => {
        api.getPanel(panelId)?.api?.setTitle(title);
      });
    }

    // addPanel-style directions -> dockview moveTo positions.
    const MOVE_POSITIONS = {
      within: "center",
      center: "center",
      left: "left",
      right: "right",
      above: "top",
      top: "top",
      below: "bottom",
      bottom: "bottom",
    };

    function movePanelTo(panelId, position) {
      whenReady(() => {
        const panel = api.getPanel(panelId);
        if (!panel) {
          return;
        }
        // position mirrors addPanel's shape: { referencePanel?, direction? }.
        // Without a referencePanel the move is relative to the panel's own
        // group; direction "within" (default) stacks as a tab in the target.
        const spec = position || {};
        const reference = spec.referencePanel
          ? api.getPanel(spec.referencePanel)
          : null;
        const group = reference ? reference.api.group : panel.api.group;
        panel.api.moveTo({
          group,
          position: MOVE_POSITIONS[spec.direction] || "center",
        });
      });
    }

    // --- The buttons of the tab rows (headerButtons / headerEmit) ---

    function dockSize() {
      const el = root.value;
      return { width: el?.clientWidth || 0, height: el?.clientHeight || 0 };
    }

    // What the panel spans across the edge it docks along: its group's, or,
    // out of a floating window, what it spanned when last docked.
    function dockedExtent(panel, horizontal) {
      const key = horizontal ? "initialWidth" : "initialHeight";
      const place = lastPlaces.get(panel.id);
      if (panel.api.location.type !== "grid" && positive(place?.[key])) {
        return place[key];
      }
      const rect = groupRect(panel.api.group);
      return rect ? (horizontal ? rect.width : rect.height) : 0;
    }

    // `extent` px wide (`horizontal`) or high, at most `share` of the dock.
    function fitExtent(group, horizontal, extent, share) {
      const size = dockSize();
      const total = horizontal ? size.width : size.height;
      if (!group || !positive(extent) || !positive(total)) {
        return;
      }
      const value = Math.round(Math.min(extent, total * share));
      group.api.setSize(horizontal ? { width: value } : { height: value });
    }

    // Along an edge of the whole dock, in a group of its own; the group it
    // leaves, empty, goes (moveTo).
    function dockAtEdge(panel, edge) {
      const horizontal = edge === "left" || edge === "right";
      const extent = dockedExtent(panel, horizontal);
      const group = api.addGroup({
        direction: EDGE_DIRECTIONS[edge],
        skipSetActive: true,
      });
      try {
        panel.api.moveTo({ group, position: "center" });
      } catch (error) {
        if (!group.panels.length) {
          api.removeGroup(group);
        }
        throw error;
      }
      fitExtent(panel.api.group, horizontal, extent, EDGE_SHARE);
    }

    function floatPanel(panel) {
      try {
        recordPlace(panel);
      } catch (error) {
        lastPlaces.delete(panel.id);
      }
      const { width, height } = dockSize();
      if (!positive(width) || !positive(height)) {
        api.addFloatingGroup(panel);
        return;
      }
      const w = Math.round(width * FLOAT_SHARE);
      const h = Math.round(height * FLOAT_SHARE);
      api.addFloatingGroup(panel, {
        position: {
          left: Math.round((width - w) / 2),
          top: Math.round((height - h) / 2),
        },
        width: w,
        height: h,
      });
    }

    // A recorded docked place (recordPlace) taken again by a panel already
    // in the dock; false when none of its references is docked any more.
    function moveToPlace(panel, place) {
      const reference = (place.references || [])
        .map((id) => api.getPanel(id))
        .find(
          (other) =>
            other && other !== panel && other.api.location.type === "grid",
        );
      if (!reference) {
        return false;
      }
      const group = reference.api.group;
      if (place.direction === "within") {
        panel.api.moveTo({
          group,
          position: "center",
          index: Math.min(place.index, group.panels.length),
        });
        return true;
      }
      panel.api.moveTo({ group, position: MOVE_POSITIONS[place.direction] });
      const horizontal =
        place.direction === "left" || place.direction === "right";
      fitExtent(
        panel.api.group,
        horizontal,
        horizontal ? place.initialWidth : place.initialHeight,
        1,
      );
      return true;
    }

    // Out of its floating window: back where it was docked before it
    // floated, else along the dock's left edge.
    function anchorBack(panel) {
      const place = lastPlaces.get(panel.id);
      if (!place || place.floating || !moveToPlace(panel, place)) {
        dockAtEdge(panel, "left");
      }
    }

    function headerAct(group, name) {
      if (disposed || !api || !group) {
        return;
      }
      const panel = group.activePanel;
      if (!panel || panel.id === CENTER_ID) {
        return;
      }
      const floating = group.api.location.type === "floating";
      const emitted = Array.isArray(props.headerEmit) ? props.headerEmit : [];
      if (emitted.includes(name)) {
        const { width, height } = dockSize();
        emit("headerAction", {
          id: panel.id,
          action: name,
          width,
          height,
          floating,
        });
        return;
      }
      try {
        if (name === "close") {
          panel.api.close();
        } else if (name === "float") {
          if (floating) {
            anchorBack(panel);
          } else {
            floatPanel(panel);
          }
        } else if (EDGE_DIRECTIONS[name]) {
          dockAtEdge(panel, name);
        }
      } catch (error) {
        console.error(`fp-dock: the ${name} button failed`, error);
      }
    }

    provide(DOCK_HEADER, {
      buttons: headerButtons,
      act: headerAct,
      isCenter: (id) => id === CENTER_ID,
    });

    // --- Dragging a tab of this dock (HTML5 drag and drop) ---

    // The last pointer press in the dock: where a tab is grabbed.
    let lastPress = null;
    // The point of the dragged tab under the pointer, in the tab.
    let grab = { x: 0, y: 0 };
    // The pointer of the last dragover that no dockview target took.
    let freeOver = null;

    // The tab drag of this dock in progress, if any.
    function ownTabDrag() {
      const data = api ? getPanelData() : undefined;
      return data && data.viewId === api.id && data.panelId ? data : null;
    }

    const emitsFloat = () =>
      Array.isArray(props.headerEmit) && props.headerEmit.includes("float");

    function onPointerDown(event) {
      lastPress = {
        x: event.clientX,
        y: event.clientY,
        target: event.target,
      };
    }

    // dockview draws its ghost off the pointer: the same image, held where
    // the tab was grabbed. Runs after the tab's own dragstart.
    function onDragStart(event) {
      freeOver = null;
      const tab = event.target?.closest?.(".dv-tab");
      if (!tab || !event.dataTransfer || !ownTabDrag()) {
        return;
      }
      const rect = tab.getBoundingClientRect();
      const from =
        lastPress && tab.contains(lastPress.target)
          ? lastPress
          : { x: event.clientX, y: event.clientY };
      grab = {
        x: Math.round(clamp(from.x - rect.left, 0, rect.width)),
        y: Math.round(clamp(from.y - rect.top, 0, rect.height)),
      };
      const ghosts = document.body.querySelectorAll(
        ":scope > .dv-tab-ghost-drag",
      );
      const ghost = ghosts.length ? ghosts[ghosts.length - 1] : tab;
      try {
        event.dataTransfer.setDragImage(ghost, grab.x, grab.y);
      } catch (error) {
        console.warn("fp-dock: the drag image could not be set", error);
      }
      // outside the dock too, where no dockview target is, the tab floats
      window.addEventListener("dragover", onDragOverOutside);
      window.addEventListener("drop", onDropOutside);
    }

    function outsideDock(event) {
      const rect = root.value?.getBoundingClientRect();
      return !!rect && (event.clientX < rect.left || event.clientX > rect.right
        || event.clientY < rect.top || event.clientY > rect.bottom);
    }

    function onDragOverOutside(event) {
      if (!outsideDock(event) || !ownTabDrag()) {
        return;
      }
      onDragOver(event);
    }

    function onDropOutside(event) {
      if (!outsideDock(event)) {
        return;
      }
      onDrop(event);
    }

    function stopOutside() {
      window.removeEventListener("dragover", onDragOverOutside);
      window.removeEventListener("drop", onDropOutside);
    }

    // Capture phase: cleared before the targets of dockview see the event,
    // so a dragover that never bubbles back here leaves no free place.
    function onDragOverCapture() {
      freeOver = null;
    }

    // A tab over a place no dockview target takes (the middle of the
    // center, for one): accepted, its drop floats it there.
    function onDragOver(event) {
      if (event[TAKEN_BY_DOCKVIEW] || !ownTabDrag()) {
        return;
      }
      if (props.disableFloatingGroups && !emitsFloat()) {
        return;
      }
      event.preventDefault();
      if (event.dataTransfer) {
        event.dataTransfer.dropEffect = "move";
      }
      freeOver = { x: event.clientX, y: event.clientY };
    }

    // Only a drop that no dockview target handled (those stop it) and that
    // follows a free dragover; a drag cancelled by Esc never drops.
    function onDrop(event) {
      const over = freeOver;
      freeOver = null;
      const data = ownTabDrag();
      if (!over || !data || !root.value) {
        return;
      }
      const panel = api.getPanel(data.panelId);
      if (!panel || isCenter(panel.id)) {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      const at =
        (event.clientX || event.clientY)
          ? { x: event.clientX, y: event.clientY }
          : over;
      const rect = root.value.getBoundingClientRect();
      try {
        floatAt(panel, at.x - rect.left - grab.x, at.y - rect.top - grab.y);
      } catch (error) {
        console.error("fp-dock: floating the dropped tab failed", error);
      }
    }

    function onDragEnd() {
      freeOver = null;
      stopOutside();
    }

    // A floating window whose tab row's top left corner is at (left, top)
    // in the dock, kept inside it. A dock whose header button "float" is
    // emitted lets the server detach it there.
    function floatAt(panel, left, top) {
      const { width, height } = dockSize();
      if (emitsFloat()) {
        emit("headerAction", {
          id: panel.id,
          action: "float",
          width,
          height,
          floating: false,
          left: Math.round(left),
          top: Math.round(top),
        });
        return;
      }
      if (!positive(width) || !positive(height)) {
        return;
      }
      // Leaving the grid: anchoring it later brings it back there.
      if (panel.api.location.type === "grid") {
        try {
          recordPlace(panel);
        } catch (error) {
          lastPlaces.delete(panel.id);
        }
      }
      const rect = groupRect(panel.api.group);
      const w = Math.round(
        Math.min(rect?.width || width, width * FLOAT_SHARE),
      );
      const h = Math.round(
        Math.min(rect?.height || height, height * FLOAT_SHARE),
      );
      api.addFloatingGroup(panel, {
        position: {
          left: Math.round(clamp(left, 0, width - w)),
          top: Math.round(clamp(top, 0, height - h)),
        },
        width: w,
        height: h,
      });
    }

    const isObject = (value) => value !== null && typeof value === "object";

    // A saved layout, its slots made this dock's own: the view it was saved
    // from may have had another id. Its cards are cards of this dock before
    // they are added, so their close is intercepted from the start.
    function loadSaved(layout) {
      const copy = JSON.parse(JSON.stringify(layout));
      const specs = props.panelSpecs || {};
      Object.entries(copy.panels || {}).forEach(([id, panel]) => {
        if (id === CENTER_ID) {
          panel.params = { ...(panel.params || {}), slot: props.center };
        } else if (specs[id]) {
          panel.params = { ...(panel.params || {}), slot: specs[id].slot };
          cardIds.add(id);
        }
      });
      api.fromJSON(copy);
    }

    function restoreLayout(layout) {
      whenReady(() => {
        // fromJSON clears the dock before validating its input, so reject
        // anything that is not a serialized layout instead of wiping panels.
        if (
          !isObject(layout) ||
          !isObject(layout.grid) ||
          !isObject(layout.panels)
        ) {
          console.warn("fp-dock: ignoring invalid layout", layout);
          return;
        }
        try {
          // Preserve live Vue component instances and their state across the
          // layout restore.
          api.fromJSON(layout, { reuseExistingPanels: true });
          if (!isCenter(api.activePanel?.id)) {
            emit("activePanel", api.activePanel?.id);
          }
        } catch (error) {
          console.error("fp-dock: failed to restore layout", error);
        }
      });
    }

    return {
      root,
      theme,
      onReady,
      addPanel,
      bind,
      removePanel,
      activePanel,
      setPanelTitle,
      movePanelTo,
      restoreLayout,
      onPointerDown,
      onDragStart,
      onDragOverCapture,
      onDragOver,
      onDrop,
      onDragEnd,
    };
  },
  template:
    '<div ref="root" style="position:relative;width:100%;height:100%;"' +
    ' @pointerdown.capture="onPointerDown" @dragstart="onDragStart"' +
    ' @dragover.capture="onDragOverCapture" @dragover="onDragOver"' +
    ' @drop="onDrop" @dragend="onDragEnd">' +
    '<dockview-vue style="position:absolute;width:100%;height:100%" :theme="theme" v-bind="bind" @ready="onReady" /></div>',
};
