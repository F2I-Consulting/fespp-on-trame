import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  base: "./",
  plugins: [vue()],
  build: {
    lib: {
      entry: "./src/main.js",
      name: "trame_fespp_tree",
      formats: ["umd"],
      // Force .js: with "type":"module", vite would emit .umd.cjs, which the
      // `scripts` path of the python module (trame_fespp_tree/module) misses.
      fileName: (format) => `trame_fespp_tree.${format}.js`,
    },
    rollupOptions: {
      external: ["vue"],
      output: { globals: { vue: "Vue" } },
    },
    outDir: "../trame_fespp_tree/module/serve",
    assetsDir: ".",
  },
});
