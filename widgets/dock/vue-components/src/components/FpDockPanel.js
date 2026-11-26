// A dock panel: the trame template it was added with (trame-dockview's
// DockPanel, Kitware, MIT), or, when its params carry a `slot`, an empty div
// that a card widget of another bundle fills through window.__fpCardSlots.
import { markRaw, onBeforeUnmount, onMounted, reactive, ref } from "vue";

// Shared across bundles: slot key -> {el, api}. vue is external, so every
// bundle gets the same global Vue and the Map stays reactive for all of them.
function cardSlots() {
  if (!window.__fpCardSlots) {
    window.__fpCardSlots = reactive(new Map());
  }
  return window.__fpCardSlots;
}

export default {
  props: ["params"],
  setup(props) {
    const panelParams = props.params.params || {};
    const templateName = panelParams.templateName;
    const slotKey = panelParams.slot || null;
    const slotEl = ref(null);

    if (slotKey) {
      // markRaw keeps the dockview api out of Vue's deep proxying and lets
      // the unmount check compare the stored entry by identity.
      let entry = null;
      onMounted(() => {
        entry = markRaw({ el: slotEl.value, api: props.params.api });
        cardSlots().set(slotKey, entry);
      });
      onBeforeUnmount(() => {
        const slots = cardSlots();
        // A panel re-added under the same slot may already have registered.
        if (slots.get(slotKey) === entry) {
          slots.delete(slotKey);
        }
      });
    }

    return { templateName, slotKey, slotEl };
  },
  template:
    '<div v-if="slotKey" ref="slotEl" style="position:relative;width:100%;height:100%;overflow:auto"></div>' +
    '<trame-template v-else :templateName="templateName" />',
};
