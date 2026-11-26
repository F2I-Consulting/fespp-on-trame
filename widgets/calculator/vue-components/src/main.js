import CalculatorPanel from "./CalculatorPanel.vue";

const components = { CalculatorPanel };

export function install(Vue) {
  Object.keys(components).forEach((name) => {
    Vue.component(name, components[name]);
  });
}
