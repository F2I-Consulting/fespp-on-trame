import CameraLinkPanel from "./CameraLinkPanel.vue";

const components = { CameraLinkPanel };

export function install(Vue) {
  Object.keys(components).forEach((name) => {
    Vue.component(name, components[name]);
  });
}
