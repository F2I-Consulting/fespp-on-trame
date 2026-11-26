// Vue plugin entry of the UMD bundle: the python module's `vue_use` installs
// it, which registers <data-explorer-tree> on the client app.
import DataExplorerTree from "./DataExplorerTree.vue";

const components = { DataExplorerTree };

export function install(Vue) {
  Object.keys(components).forEach((name) => {
    Vue.component(name, components[name]);
  });
}
