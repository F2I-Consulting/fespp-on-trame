// The ONE component of this module: the shared icon, registered globally so
// the application's own layout — the top bar, built in Python with Vuetify
// buttons — can draw an object of the model. See the README beside it.
import FpIcon from "../../../_shared/components/FpIcon.vue";

const components = { FpIcon };

export function install(Vue) {
  Object.keys(components).forEach((name) => {
    Vue.component(name, components[name]);
  });
}
