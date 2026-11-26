/*
 * Builds the component bench (fixtures/index.html) into tests/browser/out/.
 *
 *   node fixtures/build.mjs
 *
 * There is no node_modules here on purpose: the widgets' toolchain is
 * installed once, in widgets/tree/vue-components, and everything else in the
 * repository borrows it. vite and the Vue plugin are therefore imported by
 * their path inside it rather than by name — the same toolchain that builds
 * the widget bundles builds this page, so what the bench shows is what a
 * widget would get.
 *
 * TWO builds:
 *   out/fixture      production Vue — what the served application runs, prop
 *                    validation STRIPPED. This is the one the probe drives
 *                    and screenshots, because it is what a reader would see.
 *   out/fixture-dev  development Vue — the same page with the validators
 *                    live, so the probe can print the warnings a missing
 *                    required prop raises, which production Vue never shows.
 */
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(here, "..", "..", "..");
const kit = path.join(repo, "widgets", "tree", "vue-components", "node_modules");

const { build } = await import(
  pathToFileURL(path.join(kit, "vite", "dist", "node", "index.js")));
const vue = (await import(
  pathToFileURL(path.join(kit, "@vitejs", "plugin-vue", "dist", "index.mjs")))).default;

const vueRuntime = path.join(kit, "vue", "dist", "vue.runtime.esm-bundler.js");

async function once(mode, outDir) {
  await build({
    configFile: false,
    root: here,
    base: "./",
    mode,
    plugins: [vue()],
    resolve: { alias: { vue: vueRuntime } },
    define: {
      __VUE_OPTIONS_API__: "true",
      __VUE_PROD_DEVTOOLS__: "false",
      __VUE_PROD_HYDRATION_MISMATCH_DETAILS__: "false",
      // without this, vite builds for production whatever the mode
      "process.env.NODE_ENV": JSON.stringify(mode),
    },
    build: { outDir, emptyOutDir: true, minify: false },
    logLevel: "warn",
  });
  console.log("built " + mode + " -> " + outDir);
}

const out = path.join(repo, "tests", "browser", "out");
await once("production", path.join(out, "fixture"));
await once("development", path.join(out, "fixture-dev"));
