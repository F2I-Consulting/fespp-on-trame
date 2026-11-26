import UploadData from "./UploadData.vue";
import UploadFile from "./components/UploadFile.vue";
import UploadOsdu from "./components/UploadOsdu.vue";

const components = { UploadData, UploadFile, UploadOsdu };

export function install(Vue) {
  Object.keys(components).forEach((name) => {
    Vue.component(name, components[name]);
  });
}
