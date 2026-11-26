import ReconcilePanel from "./ReconcilePanel.vue";

const components = { ReconcilePanel };

export function install(Vue) {
  Object.keys(components).forEach((name) => {
    Vue.component(name, components[name]);
  });
}
