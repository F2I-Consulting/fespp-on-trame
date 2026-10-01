import FloatingCard from "./FloatingCard.vue";

const components = { FloatingCard };

export function install(Vue) {
  Object.keys(components).forEach((name) => {
    Vue.component(name, components[name]);
  });
}
