import VolumetricsPanel from "./VolumetricsPanel.vue";

const components = { VolumetricsPanel };

// Vue plugin entry: trame calls install() for the module's `vue_use` entry.
export function install(Vue) {
  Object.keys(components).forEach((name) => {
    Vue.component(name, components[name]);
  });
}
