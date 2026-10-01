import Title3dView from "./Title3dView.vue";

const components = { Title3dView };

export function install(Vue) {
  Object.keys(components).forEach((name) => {
    Vue.component(name, components[name]);
  });
}
