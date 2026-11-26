import XmlViewer from "./XmlViewer.vue";

const components = { XmlViewer };

export function install(Vue) {
  Object.keys(components).forEach((name) => {
    Vue.component(name, components[name]);
  });
}
