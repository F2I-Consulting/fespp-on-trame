// The buttons at the right end of a group's tab row (FpDockView's
// `headerButtons`), given to dockview as its right header actions. They act
// on the group's active panel through the dock that provides DOCK_HEADER.
import { computed, getCurrentInstance, inject, markRaw, onBeforeUnmount, ref } from "vue";
import "./FpDockHeader.css";

export const DOCK_HEADER = Symbol("fp-dock-header");

// The order they are drawn in, whatever order the host lists them in.
export const HEADER_ORDER = ["left", "right", "top", "bottom", "float", "close"];

// A group narrower than this keeps its room for its tab: no button to dock
// it to an edge (dragging the tab still does).
const NARROW = 340;
const EDGES = new Set(["left", "right", "top", "bottom"]);

// `text`: what the button shows without the application's FpIcon.
const LOOKS = {
  left: { icon: "fespp-card-dock-left", title: "Dock left", text: "⇤" },
  right: { icon: "fespp-card-dock-right", title: "Dock right", text: "⇥" },
  top: { icon: "fespp-card-dock-top", title: "Dock at the top", text: "⤒" },
  bottom: { icon: "fespp-card-dock-bottom", title: "Dock at the bottom", text: "⤓" },
  float: { icon: "fespp-card-float", title: "Detach", text: "⧉" },
  anchor: { icon: "fespp-view-anchor", title: "Anchor", text: "▣" },
  close: { icon: "", title: "Close", text: "×" },
};

export default markRaw({
  name: "FpDockHeader",
  props: {
    // dockview's header props: {group, panels, activePanel, location, ...};
    // a location change replaces them with {location} alone, so the group
    // is kept from the first ones
    params: { type: Object, default: null },
  },
  setup(props) {
    const dock = inject(DOCK_HEADER, null);
    const group = props.params?.group || null;
    // The application's icon, registered app-wide by widgets/icon: the same
    // component as widgets/_shared/components/FpIcon.vue.
    const icon = getCurrentInstance()?.appContext?.components?.FpIcon || null;
    // the group's width, 0 until it is laid out
    const width = ref(group?.width || 0);
    const sized = group?.api?.onDidDimensionsChange?.((e) => { width.value = e.width; });
    onBeforeUnmount(() => sized?.dispose?.());

    const shown = computed(() => {
      // every header update brings new params: re-read the group then
      void props.params;
      if (!dock || !group) {
        return [];
      }
      const panels = group.panels || [];
      if (!panels.length || panels.some((panel) => dock.isCenter(panel.id))) {
        return [];
      }
      const floating = group.api?.location?.type === "floating";
      const narrow = width.value > 0 && width.value < NARROW;
      return dock.buttons.value.filter((name) => !(narrow && EDGES.has(name))).map((name) => ({
        name,
        ...(name === "float" && floating ? LOOKS.anchor : LOOKS[name]),
      }));
    });

    function press(name) {
      dock?.act(group, name);
    }

    return { shown, press, icon };
  },
  template:
    '<div v-if="shown.length" class="fp-dock-actions"' +
    ' @pointerdown.stop @mousedown.stop @dblclick.stop>' +
    '<button v-for="b in shown" :key="b.name" type="button" class="fp-dock-act"' +
    ' :title="b.title" :aria-label="b.title" :data-fp-action="b.name"' +
    " :data-fp-incomplete=\"b.icon && !icon ? '' : null\"" +
    ' @click.stop="press(b.name)">' +
    '<component v-if="b.icon && icon" :is="icon" :icon="b.icon" chrome :size="16" />' +
    '<span v-else class="fp-dock-act-text">{{ b.text }}</span>' +
    "</button>" +
    "</div>",
});
