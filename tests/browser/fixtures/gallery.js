/*
 * The bench: every shared component, in every state it can be in.
 *
 * It imports the components BY THE PATH A WIDGET USES, so what is on screen
 * here is what a widget gets — same file, same build (vite + plugin-vue,
 * production Vue, prop validation stripped exactly as in the served page).
 */
import { createApp } from "vue";
import Gallery from "./Gallery.vue";

createApp(Gallery).mount("#app");
