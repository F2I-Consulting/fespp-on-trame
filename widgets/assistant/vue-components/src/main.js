import AssistantPanel from "./AssistantPanel.vue";

const components = { AssistantPanel };

// Vue plugin entry: trame calls install() for the names listed in the
// Python module's vue_use, which registers <assistant-panel>.
export function install(Vue) {
  Object.keys(components).forEach((name) => {
    Vue.component(name, components[name]);
  });
}
