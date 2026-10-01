import ViewToolbar from "./ViewToolbar.vue";

const components = { ViewToolbar };

export function install(Vue) {
  Object.keys(components).forEach((name) => {
    Vue.component(name, components[name]);
  });
}
