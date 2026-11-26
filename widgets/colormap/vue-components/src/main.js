import ColormapPanel from "./ColormapPanel.vue";
import LegendsPanel from "./LegendsPanel.vue";

const components = { ColormapPanel, LegendsPanel };

export function install(Vue) {
  Object.keys(components).forEach((name) => {
    Vue.component(name, components[name]);
  });
}
