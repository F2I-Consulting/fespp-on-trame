import ThresholdsPanel from "./ThresholdsPanel.vue";

const components = { ThresholdsPanel };

export function install(Vue) {
  Object.keys(components).forEach((name) => {
    Vue.component(name, components[name]);
  });
}
