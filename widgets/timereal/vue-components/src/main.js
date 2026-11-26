import TimeRealPanel from "./TimeRealPanel.vue";

const components = { TimeRealPanel };

export function install(Vue) {
  Object.keys(components).forEach((name) => {
    Vue.component(name, components[name]);
  });
}
