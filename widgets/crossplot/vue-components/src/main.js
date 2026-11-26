// Vue plugin entry of the bundle: trame installs it by the name listed in
// the Python module's `vue_use`, which registers every component globally.
import CrossplotControls from "./CrossplotControls.vue";

const components = { CrossplotControls };

export function install(Vue) {
  Object.keys(components).forEach((name) => {
    Vue.component(name, components[name]);
  });
}
