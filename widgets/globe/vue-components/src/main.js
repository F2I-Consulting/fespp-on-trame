import GlobePanel from "./GlobePanel.vue";

const components = { GlobePanel };

export function install(Vue) {
  Object.keys(components).forEach((name) => {
    Vue.component(name, components[name]);
  });
}
