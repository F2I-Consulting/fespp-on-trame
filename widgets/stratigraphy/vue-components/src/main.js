import StratigraphicColumn from "./StratigraphicColumn.vue";
import TimeDepthLaw from "./TimeDepthLaw.vue";
import LawStrip from "./LawStrip.vue";

const components = { StratigraphicColumn, TimeDepthLaw, LawStrip };

export function install(Vue) {
  Object.keys(components).forEach((name) => {
    Vue.component(name, components[name]);
  });
}
