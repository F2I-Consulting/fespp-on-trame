import SlicersPanel from "./SlicersPanel.vue";

const components = { SlicersPanel };

export function install(Vue) {
  Object.keys(components).forEach((name) => {
    Vue.component(name, components[name]);
  });
}
