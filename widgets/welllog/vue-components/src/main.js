import WellLogCorrelation from "./WellLogCorrelation.vue";
import WellLogZones from "./WellLogZones.vue";

const components = {
  WellLogCorrelation,
  WellLogZones,
};

// Vue plugin entry: trame installs it through `vue_use` (see
// trame_welllog/module), registering <well-log-correlation> and
// <well-log-zones>.
export function install(Vue) {
  Object.keys(components).forEach((name) => {
    Vue.component(name, components[name]);
  });
}
