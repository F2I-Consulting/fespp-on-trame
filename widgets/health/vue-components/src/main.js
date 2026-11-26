import HealthPanel from "./HealthPanel.vue";

const components = { HealthPanel };

export function install(Vue) {
  Object.keys(components).forEach((name) => {
    Vue.component(name, components[name]);
  });
}
