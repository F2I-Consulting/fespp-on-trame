// What a dock panel shows when it is a slot (params.slot): this content,
// mounted once where the host builds it and moved into the panel's div while
// the panel exists (window.__fpCardSlots, filled by FpDockPanel). Moved, not
// rebuilt: a 3D render or a card keeps its state across a close.
import { computed, reactive } from "vue";

function cardSlots() {
  if (!window.__fpCardSlots) {
    window.__fpCardSlots = reactive(new Map());
  }
  return window.__fpCardSlots;
}

export default {
  props: {
    slotKey: { type: String, default: "" },
  },
  setup(props) {
    const entry = computed(() => cardSlots().get(props.slotKey) || null);
    return { entry };
  },
  template:
    '<teleport :to="entry && entry.el" :disabled="!entry">' +
    '<div style="position:relative;width:100%;height:100%;display:flex;"><slot /></div>' +
    "</teleport>",
};
