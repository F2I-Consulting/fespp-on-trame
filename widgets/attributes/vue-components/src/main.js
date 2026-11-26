import AttributesPanel from "./AttributesPanel.vue";

const components = { AttributesPanel };

export function install(Vue) {
  Object.keys(components).forEach((name) => {
    Vue.component(name, components[name]);
  });
}
