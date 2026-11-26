import NewViewDialog from "./NewViewDialog.vue";
import ViewsDoor from "./ViewsDoor.vue";

const components = { NewViewDialog, ViewsDoor };

export function install(Vue) {
  Object.keys(components).forEach((name) => {
    Vue.component(name, components[name]);
  });
}
