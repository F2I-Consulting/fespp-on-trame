import SessionDoor from "./SessionDoor.vue";
import LeaveGuard from "./LeaveGuard.vue";

const components = { SessionDoor, LeaveGuard };

export function install(Vue) {
  Object.keys(components).forEach((name) => {
    Vue.component(name, components[name]);
  });
}
