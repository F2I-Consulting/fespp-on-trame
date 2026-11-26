import ComparePanel from "./ComparePanel.vue";

const components = { ComparePanel };

export function install(Vue) {
  Object.keys(components).forEach((name) => {
    Vue.component(name, components[name]);
  });
}
