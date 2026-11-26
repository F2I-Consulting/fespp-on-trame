import NavigationPanel from "./NavigationPanel.vue";
import ViewContextMenu from "./ViewContextMenu.vue";

const components = { NavigationPanel, ViewContextMenu };

export function install(Vue) {
  Object.keys(components).forEach((name) => {
    Vue.component(name, components[name]);
  });
}
