import DataExplorerTree from "./DataExplorerTree.vue";

const components = { DataExplorerTree };

export function install(Vue) {
  Object.keys(components).forEach((name) => {
    Vue.component(name, components[name]);
  });
}
